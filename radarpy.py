#!/usr/bin/env python3
"""
YENİ ÜRÜN RADARI

Son 2 ayda (varsayılan 60 gün) marka x ülke bazında piyasaya çıkan YENİ ürünleri bulur.

Hat:
  1) Resmi sitelerin ana sayfası gerçek tarayıcıyla açılır, ekran görüntüsü alınır.
  2) Gemini (görüntü okuma) bannerlardaki "yeni" ürünleri çıkarır.
  3) Her marka x ülke için Google aramalı Gemini ile ikinci bir keşif yapılır
     (siteye girilemeyen yerler için tek kaynak budur).
  4) Adaylar birleştirilir, önceki çalışmaların arşiviyle karşılaştırılır.
  5) Her aday için iki geçişli doğrulama: önce aramalı serbest metin, sonra araçsız yapılandırma.
     KAYNAK BAĞLANTISI YOKSA satır asla "Doğrulandı" olmaz.
  6) Rapor: Dünyada İlk / Ülkede İlk / Elenenler + site durumu (HTML, XLSX, CSV).

Gerekli ortam değişkeni: GEMINI_API_KEY
"""
import base64
import csv
import difflib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

# --------------------------------------------------------------------------------------
# Ayarlar
# --------------------------------------------------------------------------------------
GUN = int(os.environ.get("DONEM_GUN") or "60")            # son 2 ay
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
THINKING = os.environ.get("GEMINI_THINKING", "low")      # boş bırakılırsa gönderilmez
PARALEL = int(os.environ.get("PARALEL", "4"))
MAX_ADAY = int(os.environ.get("MAX_ADAY", "300"))        # doğrulanacak en çok aday
MAX_ARAMA = int(os.environ.get("MAX_ARAMA", "1000"))      # bir çalışmada en çok aramalı çağrı
ONLY = [x.strip() for x in os.environ.get("ONLY", "").split(",") if x.strip()]  # test: yalnız bu markalar
SADECE_ARAMA = os.environ.get("SADECE_ARAMA") == "1"     # siteleri açma (test)

OUT = Path(os.environ.get("OUT_DIR", "rapor"))
SHOTS = OUT / "ekran_goruntuleri"
ARSIV = Path(os.environ.get("ARSIV_DOSYASI", "arsiv/urunler.json"))
SON_EKRAN = Path(os.environ.get("SON_EKRAN_DIR", "son-ekran"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

BUGUN = date.today()
DONEM_BAS = BUGUN - timedelta(days=GUN)

# --------------------------------------------------------------------------------------
# Marka x ülke listesi: (kod, marka, ülke, adres veya None, tarayıcı dili)
# Adresi olan siteler için ekran görüntüsü alınır, adresi None olanlar yalnızca aramayla taranır.
# Yeni ülke eklemek için bir satır eklemek yeterli.
# --------------------------------------------------------------------------------------
SITES = [
    # Burger King
    ("bk-mx", "Burger King", "Meksika", "https://www.burgerking.com.mx/", "es-MX"),
    ("bk-jp", "Burger King", "Japonya", "https://www.burgerking.co.jp/", "ja-JP"),
    ("bk-uk", "Burger King", "Birleşik Krallık", "https://www.burgerking.co.uk/", "en-GB"),
    ("bk-br", "Burger King", "Brezilya", "https://www.burgerking.com.br/", "pt-BR"),
    ("bk-de", "Burger King", "Almanya", "https://www.burgerking.de/", "de-DE"),
    ("bk-kr", "Burger King", "Güney Kore", "https://www.burgerking.co.kr/", "ko-KR"),
    ("bk-tr", "Burger King", "Türkiye", "https://www.burgerking.com.tr/", "tr-TR"),
    ("bk-us", "Burger King", "ABD", None, "en-US"),
    ("bk-ca", "Burger King", "Kanada", None, "en-CA"),
    ("bk-fr", "Burger King", "Fransa", None, "fr-FR"),
    ("bk-es", "Burger King", "İspanya", None, "es-ES"),
    ("bk-it", "Burger King", "İtalya", None, "it-IT"),
    ("bk-nl", "Burger King", "Hollanda", None, "nl-NL"),
    ("bk-au", "Burger King", "Avustralya", None, "en-AU"),
    ("bk-nz", "Burger King", "Yeni Zelanda", None, "en-NZ"),
    ("bk-in", "Burger King", "Hindistan", None, "en-IN"),
    ("bk-cn", "Burger King", "Çin", None, "zh-CN"),
    ("bk-th", "Burger King", "Tayland", None, "th-TH"),
    ("bk-ph", "Burger King", "Filipinler", None, "en-PH"),
    ("bk-cl", "Burger King", "Şili", None, "es-CL"),
    ("bk-ar", "Burger King", "Arjantin", None, "es-AR"),
    ("bk-co", "Burger King", "Kolombiya", None, "es-CO"),
    ("bk-sa", "Burger King", "Suudi Arabistan", None, "ar-SA"),
    ("bk-ae", "Burger King", "Birleşik Arap Emirlikleri", None, "en-AE"),
    ("bk-pl", "Burger King", "Polonya", None, "pl-PL"),
    # Popeyes
    ("pop-us", "Popeyes", "ABD", "https://www.popeyes.com/", "en-US"),
    ("pop-sg", "Popeyes", "Singapur", "https://www.popeyes.com.sg/", "en-SG"),
    ("pop-uk", "Popeyes", "Birleşik Krallık", "https://www.popeyes.co.uk/", "en-GB"),
    ("pop-ca", "Popeyes", "Kanada", None, "en-CA"),
    ("pop-mx", "Popeyes", "Meksika", None, "es-MX"),
    ("pop-kr", "Popeyes", "Güney Kore", None, "ko-KR"),
    ("pop-cn", "Popeyes", "Çin", None, "zh-CN"),
    ("pop-my", "Popeyes", "Malezya", None, "en-MY"),
    ("pop-sa", "Popeyes", "Suudi Arabistan", None, "ar-SA"),
    ("pop-fr", "Popeyes", "Fransa", None, "fr-FR"),
    # Arby's
    ("arb-us", "Arby's", "ABD", "https://www.arbys.com/", "en-US"),
    ("arb-ca", "Arby's", "Kanada", None, "en-CA"),
    # Sbarro
    ("sbr-us", "Sbarro", "ABD", "https://sbarro.com/", "en-US"),
    ("sbr-ca", "Sbarro", "Kanada", None, "en-CA"),
    ("sbr-ae", "Sbarro", "Birleşik Arap Emirlikleri", None, "en-AE"),
    ("sbr-sa", "Sbarro", "Suudi Arabistan", None, "ar-SA"),
    # Subway
    ("sub-us", "Subway", "ABD", "https://www.subway.com/en-us", "en-US"),
    ("sub-jp", "Subway", "Japonya", "https://subway.co.jp/", "ja-JP"),
    ("sub-kr", "Subway", "Güney Kore", "https://www.subway.co.kr/", "ko-KR"),
    ("sub-ca", "Subway", "Kanada", None, "en-CA"),
    ("sub-uk", "Subway", "Birleşik Krallık", None, "en-GB"),
    ("sub-au", "Subway", "Avustralya", None, "en-AU"),
    ("sub-de", "Subway", "Almanya", None, "de-DE"),
    ("sub-fr", "Subway", "Fransa", None, "fr-FR"),
    ("sub-in", "Subway", "Hindistan", None, "en-IN"),
    ("sub-br", "Subway", "Brezilya", None, "pt-BR"),
    ("sub-mx", "Subway", "Meksika", None, "es-MX"),
    # McDonald's
    ("mcd-us", "McDonald's", "ABD", "https://www.mcdonalds.com/us/en-us.html", "en-US"),
    ("mcd-jp", "McDonald's", "Japonya", "https://www.mcdonalds.co.jp/", "ja-JP"),
    ("mcd-de", "McDonald's", "Almanya", "https://www.mcdonalds.com/de/de-de.html", "de-DE"),
    ("mcd-tr", "McDonald's", "Türkiye", "https://www.mcdonalds.com/tr/tr-tr.html", "tr-TR"),
    ("mcd-uk", "McDonald's", "Birleşik Krallık", None, "en-GB"),
    ("mcd-ca", "McDonald's", "Kanada", None, "en-CA"),
    ("mcd-fr", "McDonald's", "Fransa", None, "fr-FR"),
    ("mcd-es", "McDonald's", "İspanya", None, "es-ES"),
    ("mcd-it", "McDonald's", "İtalya", None, "it-IT"),
    ("mcd-nl", "McDonald's", "Hollanda", None, "nl-NL"),
    ("mcd-pl", "McDonald's", "Polonya", None, "pl-PL"),
    ("mcd-au", "McDonald's", "Avustralya", None, "en-AU"),
    ("mcd-nz", "McDonald's", "Yeni Zelanda", None, "en-NZ"),
    ("mcd-in", "McDonald's", "Hindistan", None, "en-IN"),
    ("mcd-cn", "McDonald's", "Çin", None, "zh-CN"),
    ("mcd-kr", "McDonald's", "Güney Kore", None, "ko-KR"),
    ("mcd-tw", "McDonald's", "Tayvan", None, "zh-TW"),
    ("mcd-hk", "McDonald's", "Hong Kong", None, "zh-HK"),
    ("mcd-sg", "McDonald's", "Singapur", None, "en-SG"),
    ("mcd-my", "McDonald's", "Malezya", None, "en-MY"),
    ("mcd-th", "McDonald's", "Tayland", None, "th-TH"),
    ("mcd-ph", "McDonald's", "Filipinler", None, "en-PH"),
    ("mcd-id", "McDonald's", "Endonezya", None, "id-ID"),
    ("mcd-br", "McDonald's", "Brezilya", None, "pt-BR"),
    ("mcd-mx", "McDonald's", "Meksika", None, "es-MX"),
    ("mcd-ar", "McDonald's", "Arjantin", None, "es-AR"),
    ("mcd-cl", "McDonald's", "Şili", None, "es-CL"),
    ("mcd-sa", "McDonald's", "Suudi Arabistan", None, "ar-SA"),
    ("mcd-ae", "McDonald's", "Birleşik Arap Emirlikleri", None, "en-AE"),
    ("mcd-eg", "McDonald's", "Mısır", None, "ar-EG"),
    ("mcd-za", "McDonald's", "Güney Afrika", None, "en-ZA"),
    ("mcd-se", "McDonald's", "İsveç", None, "sv-SE"),
    ("mcd-at", "McDonald's", "Avusturya", None, "de-AT"),
    ("mcd-ch", "McDonald's", "İsviçre", None, "de-CH"),
    ("mcd-pt", "McDonald's", "Portekiz", None, "pt-PT"),
    ("mcd-cz", "McDonald's", "Çekya", None, "cs-CZ"),
    ("mcd-ro", "McDonald's", "Romanya", None, "ro-RO"),
    ("mcd-gr", "McDonald's", "Yunanistan", None, "el-GR"),
    ("mcd-ie", "McDonald's", "İrlanda", None, "en-IE"),
    # KFC
    ("kfc-pl", "KFC", "Polonya", "https://kfc.pl/", "pl-PL"),
    ("kfc-mx", "KFC", "Meksika", "https://www.kfc.com.mx/", "es-MX"),
    ("kfc-my", "KFC", "Malezya", "https://www.kfc.com.my/", "en-MY"),
    ("kfc-nl", "KFC", "Hollanda", "https://www.kfc.nl/", "nl-NL"),
    ("kfc-cz", "KFC", "Çekya", "https://www.kfc.cz/", "cs-CZ"),
    ("kfc-us", "KFC", "ABD", None, "en-US"),
    ("kfc-ca", "KFC", "Kanada", None, "en-CA"),
    ("kfc-uk", "KFC", "Birleşik Krallık", None, "en-GB"),
    ("kfc-de", "KFC", "Almanya", None, "de-DE"),
    ("kfc-fr", "KFC", "Fransa", None, "fr-FR"),
    ("kfc-es", "KFC", "İspanya", None, "es-ES"),
    ("kfc-tr", "KFC", "Türkiye", None, "tr-TR"),
    ("kfc-au", "KFC", "Avustralya", None, "en-AU"),
    ("kfc-nz", "KFC", "Yeni Zelanda", None, "en-NZ"),
    ("kfc-in", "KFC", "Hindistan", None, "en-IN"),
    ("kfc-cn", "KFC", "Çin", None, "zh-CN"),
    ("kfc-jp", "KFC", "Japonya", None, "ja-JP"),
    ("kfc-kr", "KFC", "Güney Kore", None, "ko-KR"),
    ("kfc-th", "KFC", "Tayland", None, "th-TH"),
    ("kfc-ph", "KFC", "Filipinler", None, "en-PH"),
    ("kfc-id", "KFC", "Endonezya", None, "id-ID"),
    ("kfc-sg", "KFC", "Singapur", None, "en-SG"),
    ("kfc-za", "KFC", "Güney Afrika", None, "en-ZA"),
    ("kfc-sa", "KFC", "Suudi Arabistan", None, "ar-SA"),
    ("kfc-ae", "KFC", "Birleşik Arap Emirlikleri", None, "en-AE"),
    ("kfc-br", "KFC", "Brezilya", None, "pt-BR"),
    ("kfc-ar", "KFC", "Arjantin", None, "es-AR"),
    ("kfc-cl", "KFC", "Şili", None, "es-CL"),
    ("kfc-hu", "KFC", "Macaristan", None, "hu-HU"),
    ("kfc-ro", "KFC", "Romanya", None, "ro-RO"),
]

# --------------------------------------------------------------------------------------
# Site tarama (gerçek tarayıcı, engel aşma yok)
# --------------------------------------------------------------------------------------
COOKIE_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button:has-text('Accept all')", "button:has-text('Accept All')", "button:has-text('Accept')",
    "button:has-text('Aceptar')", "button:has-text('Akzeptieren')", "button:has-text('Alle akzeptieren')",
    "button:has-text('Aceitar')", "button:has-text('Kabul')", "button:has-text('Tümünü kabul')",
    "button:has-text('Zaakceptuj')", "button:has-text('Souhlasím')", "button:has-text('Akkoord')",
    "button:has-text('同意')", "button:has-text('承諾')", "button:has-text('동의')",
]
BLOCK_RE = re.compile(
    r"access denied|request blocked|attention required|just a moment|checking your browser|"
    r"verify you are (a )?human|are you a robot|captcha|unusual traffic|pardon our interruption|"
    r"you have been blocked|erişim engellendi|zugriff verweigert|acceso denegado|"
    r"enable javascript and cookies|errors\.edgesuite\.net|incapsula incident|px-captcha", re.I)


def cerez_kapat(page):
    for sel in COOKIE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=400):
                loc.click(timeout=1500)
                page.wait_for_timeout(800)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def site_durumu(status, baslik, metin):
    kisa = len(metin) < 3000
    if status in (401, 403, 429):
        return "ENGELLİ", f"HTTP {status}"
    if BLOCK_RE.search(baslik or "") or (kisa and BLOCK_RE.search(metin or "")):
        return "ENGELLİ", "Doğrulama / erişim engeli sayfası"
    if status and status >= 400:
        return "HATA", f"HTTP {status}"
    if len(metin.strip()) < 200:
        return "BOŞ", "Sayfada neredeyse hiç metin yok"
    return "OK", ""


def tara_site(browser, kod, marka, ulke, url, dil):
    r = {"kod": kod, "marka": marka, "ulke": ulke, "adres": url, "durum": "HATA", "neden": "",
         "ekranlar": []}
    ctx = browser.new_context(viewport={"width": 1440, "height": 1600}, locale=dil, user_agent=UA)
    page = ctx.new_page()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=40000)
        status = resp.status if resp else None
        page.wait_for_timeout(5000)
        cerez_kapat(page)
        page.wait_for_timeout(1500)
        dosyalar = []
        for i in (1, 2):
            f = SHOTS / f"{kod}_{i}.jpg"
            page.screenshot(path=str(f), type="jpeg", quality=72)
            dosyalar.append(f.name)
            if i == 1:
                page.wait_for_timeout(6000)   # kaydırmalı bannerın değişmesi için
        baslik = page.title() or ""
        metin = page.evaluate("document.body ? document.body.innerText : ''") or ""
        r["durum"], r["neden"] = site_durumu(status, baslik, metin)
        r["ekranlar"] = dosyalar
    except Exception as e:  # noqa: BLE001
        r["durum"] = "HATA"
        r["neden"] = f"{type(e).__name__}: {(str(e).splitlines() or [''])[0][:140]}"
    finally:
        ctx.close()
    return r


# --------------------------------------------------------------------------------------
# Gemini istemcisi
# --------------------------------------------------------------------------------------
API_KEY = os.environ.get("GEMINI_API_KEY", "")
_arama_sayaci = {"n": 0}


def cagri(parts, arama=False, json_cikti=False, sicaklik=0.2):
    """Gemini generateContent. (metin, kaynaklar) döndürür.
    arama=True -> Google Search grounding (yalnız düz metin; JSON istenmez, çünkü Gemini 3.x
    aramayı sessizce kapatabiliyor). json_cikti=True -> araçsız JSON."""
    if arama and json_cikti:
        raise ValueError("Aramalı çağrıda JSON istenemez; iki geçiş kullanın.")
    if arama:
        _arama_sayaci["n"] += 1
        if _arama_sayaci["n"] > MAX_ARAMA:
            raise RuntimeError("Aramalı çağrı sınırı doldu")
    govde = {"contents": [{"role": "user", "parts": parts}],
             "generationConfig": {"temperature": sicaklik}}
    if arama:
        govde["tools"] = [{"google_search": {}}]
    if json_cikti:
        govde["generationConfig"]["responseMimeType"] = "application/json"
    if THINKING:
        govde["generationConfig"]["thinkingConfig"] = {"thinkingLevel": THINKING}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

    son_hata = ""
    for deneme in range(6):
        istek = urllib.request.Request(
            url, data=json.dumps(govde).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY}, method="POST")
        try:
            with urllib.request.urlopen(istek, timeout=180) as r:
                d = json.loads(r.read().decode("utf-8"))
            return _yanit_coz(d)
        except urllib.error.HTTPError as e:
            govde_hata = e.read().decode("utf-8", "replace")[:400]
            son_hata = f"HTTP {e.code}: {govde_hata}"
            if e.code == 400 and "thinking" in govde_hata.lower() and "thinkingConfig" in govde["generationConfig"]:
                del govde["generationConfig"]["thinkingConfig"]      # bu model düzeyi kabul etmiyor
                continue
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 4 * 2 ** deneme))
                continue
            raise RuntimeError(son_hata) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            son_hata = f"{type(e).__name__}: {e}"
            time.sleep(min(60, 4 * 2 ** deneme))
    raise RuntimeError(f"Gemini yanıt vermedi: {son_hata}")


def _yanit_coz(d):
    adaylar = d.get("candidates") or []
    if not adaylar:
        raise RuntimeError(f"Boş yanıt: {json.dumps(d.get('promptFeedback', d), ensure_ascii=False)[:300]}")
    c = adaylar[0]
    metin = "".join(p.get("text", "") for p in (c.get("content", {}).get("parts") or []) if not p.get("thought"))
    kaynaklar, gorulen, dizin = [], set(), {}
    gm = c.get("groundingMetadata") or {}
    for i, ch in enumerate(gm.get("groundingChunks") or []):
        w = ch.get("web") or {}
        uri = w.get("uri")
        if uri and uri not in gorulen:
            gorulen.add(uri)
            dizin[i] = len(kaynaklar)
            kaynaklar.append({"baslik": w.get("title", ""), "adres": uri, "destek": []})
        elif uri:
            dizin[i] = next(j for j, k in enumerate(kaynaklar) if k["adres"] == uri)
    # Hangi cümleyi hangi kaynak destekliyor (groundingSupports)
    for sp in gm.get("groundingSupports") or []:
        parca = ((sp.get("segment") or {}).get("text") or "")[:300]
        for j in {dizin[i] for i in (sp.get("groundingChunkIndices") or []) if i in dizin}:
            if parca and len(kaynaklar[j]["destek"]) < 12:
                kaynaklar[j]["destek"].append(parca)
    return metin.strip(), kaynaklar


def adres_coz(kaynaklar):
    """Gemini'nin yönlendirme bağlantılarını (vertexaisearch...) gerçek sayfa adresine çevirmeyi dener."""
    class _Durdur(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    op = urllib.request.build_opener(_Durdur)
    out = []
    for k in kaynaklar[:8]:
        a = k["adres"]
        if "vertexaisearch.cloud.google.com" in a or "grounding-api-redirect" in a:
            try:
                op.open(urllib.request.Request(a, headers={"User-Agent": UA}), timeout=8)
            except urllib.error.HTTPError as e:
                loc = e.headers.get("Location")
                if loc and e.code in (301, 302, 303, 307, 308):
                    a = loc
            except Exception:  # noqa: BLE001
                pass
        out.append({"baslik": k.get("baslik", "") or urlparse(a).netloc, "adres": a, "destek": k.get("destek", [])})
    return out


def json_cikar(metin):
    if not metin:
        return None
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", metin.strip(), flags=re.I)
    adaylar = [(t.find(b), b, k) for b, k in (("[", "]"), ("{", "}")) if t.find(b) != -1]
    for i, b, k in sorted(adaylar):                      # önce metinde ilk görünen parantez türü
        j = t.rfind(k)
        if j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


# --------------------------------------------------------------------------------------
# 1) Görüntü okuma (banner -> ürün adayları)
# --------------------------------------------------------------------------------------
def gorsel_adaylar(site):
    marka, ulke = site["marka"], site["ulke"]
    parts = []
    for ad in site["ekranlar"]:
        b = (SHOTS / ad).read_bytes()
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}})
    parts.append({"text": (
        f"Bunlar {marka} markasının {ulke} resmi sitesinin ana sayfasından alınmış iki ekran görüntüsüdür "
        "(aynı sayfa, birkaç saniye arayla; kaydırmalı bannerlar değişmiş olabilir).\n"
        "GÖREV: Yalnızca görüntüde gerçekten yazan, markanın YENİ / yeni çıkan / sınırlı süreli / lansman olarak "
        "öne çıkardığı yemek-içecek ÜRÜNLERİNİ listele. Kampanyaları, indirimleri, uygulama reklamlarını, "
        "kurumsal duyuruları ve klasik menü ürünlerini ALMA. Görüntüde olmayan hiçbir şeyi tahmin etme.\n"
        "Her ürün için JSON nesnesi ver: {\"ad\": ürün adı (görüntüdeki yazılışıyla), \"aciklama\": görüntüdeki kısa "
        "açıklama, \"etiket\": görüntüdeki yenilik ifadesi (ör. NEW, Nuevo, 新発売; yoksa boş), \"fiyat\": görünüyorsa, "
        "\"ekran\": 1 veya 2}.\n"
        "Aynı ürünü iki ekranda görürsen tek kez yaz. Yalnızca JSON dizisi döndür; hiç ürün yoksa []."
    )})
    metin, _ = cagri(parts, json_cikti=True, sicaklik=0.0)
    veri = json_cikar(metin)
    sonuc = []
    if isinstance(veri, list):
        for x in veri:
            if isinstance(x, dict) and str(x.get("ad", "")).strip():
                ekran_no = x.get("ekran") if x.get("ekran") in (1, 2) else 1
                ekran_no = min(ekran_no, len(site["ekranlar"]))
                sonuc.append({
                    "marka": marka, "ulke": ulke, "ad": str(x["ad"]).strip(),
                    "aciklama": str(x.get("aciklama", "") or "").strip(),
                    "etiket": str(x.get("etiket", "") or "").strip(),
                    "fiyat": str(x.get("fiyat", "") or "").strip(),
                    "kaynak_turu": ["site"], "ekran": site["ekranlar"][ekran_no - 1],
                    "site_adresi": site["adres"], "kaynaklar": [],
                })
    return sonuc


# --------------------------------------------------------------------------------------
# 2) Aramalı keşif (marka x ülke) - iki geçiş
# --------------------------------------------------------------------------------------
def arama_adaylar(marka, ulke):
    bas, bit = DONEM_BAS.isoformat(), BUGUN.isoformat()
    p1 = (
        f"{marka} markası {ulke} pazarında {bas} ile {bit} tarihleri arasında hangi YENİ yemek-içecek ürünlerini "
        "(menüye yeni giren ya da yeni lanse edilen) satışa sundu? Google aramasını kullan; markanın resmi sitesine, "
        "basın açıklamalarına ve güvenilir haberlere bak. Her ürün için adı, çıkış tarihi ve kısa açıklamasını yaz. "
        "Sadece aramada bulduğun bilgiyi yaz, tahmin etme. Bu dönemde yeni ürün bulamazsan açıkça 'bulunamadı' yaz."
    )
    metin, kaynaklar = cagri([{"text": p1}], arama=True)
    if not kaynaklar:                         # Gemini 3.x'te bazen metaveri eksik gelir; bir kez daha dene
        metin, kaynaklar = cagri([{"text": p1}], arama=True)
    if not metin or re.search(r"bulunamad|bulamad|no new|not found", metin[:300], re.I) and len(metin) < 400:
        return []
    p2 = (
        f"Aşağıdaki metinde geçen {marka} / {ulke} yeni ürünlerini JSON dizisine çevir. YALNIZCA metinde yazanı kullan, "
        "bilgi ekleme.\nHer öğe: {\"ad\": ..., \"aciklama\": ..., \"cikis_tarihi\": \"YYYY-AA-GG veya YYYY-AA veya boş\"}.\n"
        "Ürün yoksa [] döndür.\n\nMETİN:\n" + metin
    )
    m2, _ = cagri([{"text": p2}], json_cikti=True, sicaklik=0.0)
    veri = json_cikar(m2)
    sonuc = []
    if isinstance(veri, list):
        k = adres_coz(kaynaklar) if kaynaklar else []
        for x in veri:
            if isinstance(x, dict) and str(x.get("ad", "")).strip():
                sonuc.append({
                    "marka": marka, "ulke": ulke, "ad": str(x["ad"]).strip(),
                    "aciklama": str(x.get("aciklama", "") or "").strip(), "etiket": "", "fiyat": "",
                    "kaynak_turu": ["arama"], "ekran": "", "site_adresi": "",
                    "kaynaklar": k, "arama_tarihi": str(x.get("cikis_tarihi", "") or "").strip(),
                })
    return sonuc


# --------------------------------------------------------------------------------------
# 3) Birleştirme ve arşiv
# --------------------------------------------------------------------------------------
def slug(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[\W_]+", "", s)


def benzer(a, b):
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) >= 5 and (a in b or b in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.86


def birlestir(adaylar):
    gruplar = []
    for a in adaylar:
        sl = slug(a["ad"])
        for g in gruplar:
            if g["marka"] == a["marka"] and g["ulke"] == a["ulke"] and benzer(g["_slug"], sl):
                for t in a["kaynak_turu"]:
                    if t not in g["kaynak_turu"]:
                        g["kaynak_turu"].append(t)
                if not g.get("ekran") and a.get("ekran"):
                    g["ekran"], g["site_adresi"] = a["ekran"], a["site_adresi"]
                for k in a.get("kaynaklar", []):
                    if k["adres"] not in {x["adres"] for x in g["kaynaklar"]}:
                        g["kaynaklar"].append(k)
                for alan in ("aciklama", "etiket", "fiyat", "arama_tarihi"):
                    if not g.get(alan) and a.get(alan):
                        g[alan] = a[alan]
                break
        else:
            b = dict(a)
            b["_slug"] = sl
            gruplar.append(b)
    return gruplar


def arsiv_oku():
    try:
        return json.loads(ARSIV.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"urunler": []}


def arsivde_bul(arsiv, marka, ulke, sl):
    for u in arsiv.get("urunler", []):
        if u["marka"] == marka and u["ulke"] == ulke and benzer(u["slug"], sl):
            return u
    return None


# --------------------------------------------------------------------------------------
# 4) Doğrulama (iki geçiş)
# --------------------------------------------------------------------------------------
def ay_anahtari(t):
    """'2026-08-14' / '2026-08' -> '2026-08'; çözülemezse ''."""
    m = re.match(r"^\s*(\d{4})-(\d{1,2})", t or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else ""


def dogrula(a):
    marka, ulke, ad = a["marka"], a["ulke"], a["ad"]
    p1 = (
        f"Ürün: \"{ad}\" ({a.get('aciklama') or 'açıklama yok'}). Marka: {marka}. Ülke: {ulke}.\n"
        f"Bugünün tarihi {BUGUN.isoformat()}. Google aramasını kullanarak şunları araştır:\n"
        f"1) Bu ürün {ulke} pazarında ilk kez ne zaman satışa çıktı?\n"
        f"2) {marka}, aynı ürünü (aynı ürün ya da aynı adla/konseptle) daha önce dünyanın başka bir ülkesinde sattı mı? "
        "Hangi ülkelerde, ne zaman?\n"
        f"3) Ürün daha önce {ulke}'de satılıp kaldırıldı ve şimdi geri mi döndü?\n"
        "Sadece aramada bulduğun bilgiyi yaz, tahmin etme. Bilmediğin ya da bulamadığın konuda açıkça "
        "'bilgi bulunamadı' yaz. Mümkünse tarihleri ver."
    )
    metin, kaynaklar = cagri([{"text": p1}], arama=True)
    if not kaynaklar:
        metin, kaynaklar = cagri([{"text": p1}], arama=True)
    p2 = (
        "Aşağıdaki araştırma metnini JSON nesnesine çevir. YALNIZCA metinde yazanı kullan; metinde yoksa "
        "\"bilinmiyor\" yaz.\n{\n"
        "  \"bu_ulkede_ilk_cikis\": \"YYYY-AA-GG / YYYY-AA / bilinmiyor\",\n"
        "  \"baska_ulkelerde_once_satildi\": [{\"ulke\": ..., \"tarih\": ...}],\n"
        "  \"baska_ulkede_satildi_mi\": \"evet / hayir / bilinmiyor\",\n"
        "  \"bu_ulkede_geri_donus\": \"evet / hayir / bilinmiyor\",\n"
        "  \"kanit_ozeti\": \"1-2 cümle, Türkçe\"\n}\n"
        "'baska_ulkede_satildi_mi' yalnızca metin açıkça belirtiyorsa evet ya da hayir olsun.\n\n"
        f"ÜRÜN: {ad} / {marka} / {ulke}\n\nMETİN:\n{metin}"
    )
    m2, _ = cagri([{"text": p2}], json_cikti=True, sicaklik=0.0)
    v = json_cikar(m2)
    if not isinstance(v, dict):
        v = {}
    return {"dogrulama": v, "dogrulama_metni": metin,
            "kaynaklar_dogrulama": adres_coz(kaynaklar) if kaynaklar else []}


def sinif_ver(a):
    """Aday sözlüğünü sınıflandırır: a['sinif'] in dunya/ulke/elenen, a['guven'], a['neden']."""
    v = a.get("dogrulama", {}) or {}
    dog_k = a.get("kaynaklar_dogrulama", [])
    tekil = {k["adres"]: k for k in dog_k + a.get("kaynaklar", [])}
    a["kaynaklar"] = list(tekil.values())
    # Yalnızca bu ürün için yapılan doğrulama aramasında, ürün adını anan bir cümleyi destekleyen kaynak "bağlı" sayılır.
    sl = a.get("_slug", "")
    bagli = [k for k in dog_k if sl and any(sl in slug(t) for t in k.get("destek", []))]
    a["bagli_kaynak"] = len(bagli)
    kaynak_var = bool(dog_k)

    ilk = ay_anahtari(v.get("bu_ulkede_ilk_cikis", "")) or ay_anahtari(a.get("arama_tarihi", ""))
    a["ulkede_ilk_cikis"] = ilk
    baska = [x for x in (v.get("baska_ulkelerde_once_satildi") or []) if isinstance(x, dict) and x.get("ulke")]
    a["baska_ulkeler"] = baska
    baska_mi = str(v.get("baska_ulkede_satildi_mi", "bilinmiyor")).lower()
    if baska and baska_mi != "evet":
        baska_mi = "evet"
    donus = str(v.get("bu_ulkede_geri_donus", "bilinmiyor")).lower()
    a["kanit"] = str(v.get("kanit_ozeti", "") or "")[:400]
    bas_ay = ay_anahtari(DONEM_BAS.isoformat())

    # Arşiv: dönemden önce görülmüş ürün
    ars = a.get("arsiv_kaydi")
    if ars and ars["ilk_gorulme"] < DONEM_BAS.isoformat():
        a["sinif"], a["neden"] = "elenen", f"Arşivde {ars['ilk_gorulme']} tarihinde zaten görülmüş (dönemden önce)"
        a["guven"] = "Doğrulandı"
        return a
    if donus == "evet":
        a["sinif"], a["neden"] = "elenen", "Ürün daha önce bu ülkede satılmış, geri dönüş ürünü"
        a["guven"] = "Doğrulandı" if bagli else ("Muhtemelen yeni" if kaynak_var else "Doğrulanamadı")
        return a
    if ilk and ilk < bas_ay:
        a["sinif"], a["neden"] = "elenen", f"Bu ülkede ilk çıkış {ilk}: dönemden önce"
        a["guven"] = "Doğrulandı" if bagli else ("Muhtemelen yeni" if kaynak_var else "Doğrulanamadı")
        return a

    kesin = bool(ilk) and baska_mi in ("evet", "hayir") and donus in ("hayir",)
    if not kaynak_var:
        guven = "Doğrulanamadı"
    elif kesin and bagli:
        guven = "Doğrulandı"
    else:
        guven = "Muhtemelen yeni"
    a["guven"] = guven

    if baska_mi == "evet":
        a["sinif"], a["neden"] = "ulke", ""
    elif baska_mi == "hayir" and guven == "Doğrulandı":
        a["sinif"], a["neden"] = "dunya", ""
    else:
        # Bilinmiyor: asla "Dünyada İlk" olmaz
        a["sinif"], a["neden"] = "ulke", "Başka ülkede önceden satılıp satılmadığı doğrulanamadı"
    return a


# --------------------------------------------------------------------------------------
# 5) Raporlar
# --------------------------------------------------------------------------------------
def e(x):
    return html.escape(str(x or ""))


def kaynak_html(a):
    if not a["kaynaklar"]:
        return "<span class=\"yok\">kaynak yok</span>"
    return "<br>".join(f"<a href=\"{e(k['adres'])}\" target=\"_blank\" rel=\"noopener\">{e((k['baslik'] or urlparse(k['adres']).netloc)[:50])}</a>"
                       for k in a["kaynaklar"][:5])


def satir_html(a, elenen=False):
    ekran = (f"<a href=\"ekran_goruntuleri/{e(a['ekran'])}\" target=\"_blank\"><img loading=\"lazy\" "
             f"src=\"ekran_goruntuleri/{e(a['ekran'])}\" alt=\"\"></a>") if a.get("ekran") else ""
    baska = ", ".join(f"{e(x.get('ulke'))} ({e(x.get('tarih', '?'))})" for x in a.get("baska_ulkeler", [])[:6])
    kt = " + ".join({"site": "Resmi site", "arama": "Arama"}[t] for t in a["kaynak_turu"])
    guven_sinif = {"Doğrulandı": "g1", "Muhtemelen yeni": "g2", "Doğrulanamadı": "g3"}[a["guven"]]
    son_sutun = e(a.get("neden", "")) if elenen else e(baska or "-")
    return (f"<tr data-m=\"{e(a['marka'])}\"><td>{e(a['marka'])}</td><td>{e(a['ulke'])}</td>"
            f"<td><b>{e(a['ad'])}</b><div class=\"alt\">{e(a.get('aciklama'))} {e(a.get('fiyat'))}</div></td>"
            f"<td><span class=\"rozet {guven_sinif}\">{e(a['guven'])}</span><div class=\"alt\">{e(kt)}</div></td>"
            f"<td>{e(a.get('ulkede_ilk_cikis') or '-')}</td><td>{son_sutun}<div class=\"alt\">{e(a.get('kanit'))}</div></td>"
            f"<td>{kaynak_html(a)}</td><td class=\"ek\">{ekran}</td></tr>")


def html_yaz(dunya, ulke, elenen, siteler, zaman, istatistik):
    def tablo(liste, bos, elenen_mi=False):
        if not liste:
            return f"<p class=\"bos\">{bos}</p>"
        son = "Elenme nedeni" if elenen_mi else "Başka ülkelerde önceden"
        h = ("<table><thead><tr><th>Marka</th><th>Ülke</th><th>Ürün</th><th>Güven</th><th>Bu ülkede ilk çıkış</th>"
             f"<th>{son}</th><th>Kaynaklar</th><th>Ekran</th></tr></thead><tbody>")
        return h + "".join(satir_html(a, elenen_mi) for a in liste) + "</tbody></table>"

    st_satir = "".join(
        f"<tr><td>{e(s['marka'])}</td><td>{e(s['ulke'])}</td><td>{e(s['durum'])}</td><td>{e(s['neden'])}</td></tr>"
        for s in siteler)
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Yeni Ürün Radarı</title>
<style>
:root{{--bg:#fafaf8;--fg:#1c1c1a;--mut:#6b6b66;--kart:#fff;--cizgi:#e4e3dd;--ok:#1f7a45;--okb:#e3f3ea;--uyari:#8a5a00;--uyarib:#fdf0d5;--kot:#a02b2b;--kotb:#fbe5e5}}
@media(prefers-color-scheme:dark){{:root{{--bg:#161614;--fg:#ecebe6;--mut:#9a9992;--kart:#1f1f1c;--cizgi:#34332f;--ok:#6fd09a;--okb:#16301f;--uyari:#f1c36a;--uyarib:#33290f;--kot:#f08a8a;--kotb:#3a1b1b}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:1280px;margin:0 auto;padding:20px 16px 60px}}
h1{{margin:0 0 4px;font-size:24px}} .mut{{color:var(--mut)}}
nav{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 10px}}
nav button{{border:1px solid var(--cizgi);background:var(--kart);color:var(--fg);padding:8px 14px;border-radius:8px;cursor:pointer;font:inherit}}
nav button.on{{background:var(--fg);color:var(--bg)}}
.arac{{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 14px}} .arac input,.arac select{{padding:8px 10px;border:1px solid var(--cizgi);border-radius:8px;background:var(--kart);color:var(--fg);font:inherit}}
section{{display:none}} section.on{{display:block}}
.sar{{overflow-x:auto;border:1px solid var(--cizgi);border-radius:10px;background:var(--kart)}}
table{{border-collapse:collapse;width:100%;min-width:900px}} th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--cizgi);vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);position:sticky;top:0;background:var(--kart)}}
.alt{{font-size:12.5px;color:var(--mut)}} .rozet{{padding:2px 8px;border-radius:99px;font-size:12px;font-weight:600;white-space:nowrap}}
.g1{{background:var(--okb);color:var(--ok)}} .g2{{background:var(--uyarib);color:var(--uyari)}} .g3{{background:var(--kotb);color:var(--kot)}}
.ek img{{width:120px;border-radius:6px;border:1px solid var(--cizgi)}} .yok{{color:var(--kot)}} .bos{{padding:20px;color:var(--mut)}}
a{{color:inherit}}
</style></head><body><main>
<h1>Yeni Ürün Radarı</h1>
<div class="mut">Dönem: {DONEM_BAS.strftime('%d.%m.%Y')} – {BUGUN.strftime('%d.%m.%Y')} (son {GUN} gün) · Oluşturma: {e(zaman)}</div>
<div class="mut">Dünyada ilk: <b>{len(dunya)}</b> · Ülkede ilk: <b>{len(ulke)}</b> · Elenen: <b>{len(elenen)}</b> · {e(istatistik)}</div>
<p class="mut">Güven etiketleri: <span class="rozet g1">Doğrulandı</span> kaynak bağlantısı var ve ilk çıkış/başka ülke bilgisi net ·
<span class="rozet g2">Muhtemelen yeni</span> kaynak var ama bazı bilgiler belirsiz ·
<span class="rozet g3">Doğrulanamadı</span> kaynak bulunamadı, gözle kontrol edin. Doğrulanamayan satır hiçbir zaman "Dünyada İlk" olmaz.</p>
<nav><button class="on" data-t="dunya">Dünyada İlk ({len(dunya)})</button><button data-t="ulke">Ülkede İlk ({len(ulke)})</button>
<button data-t="elenen">Elenenler ({len(elenen)})</button><button data-t="site">Site durumu ({len(siteler)})</button></nav>
<div class="arac"><input id="ara" placeholder="Ara (ürün, ülke...)"><select id="marka"><option value="">Tüm markalar</option>
{''.join(f'<option>{e(m)}</option>' for m in sorted({s['marka'] for s in siteler}))}</select></div>
<section id="dunya" class="on"><div class="sar">{tablo(dunya, "Bu dönemde doğrulanmış dünyada ilk ürün bulunamadı.")}</div></section>
<section id="ulke"><div class="sar">{tablo(ulke, "Kayıt yok.")}</div></section>
<section id="elenen"><div class="sar">{tablo(elenen, "Kayıt yok.", True)}</div></section>
<section id="site"><div class="sar"><table><thead><tr><th>Marka</th><th>Ülke</th><th>Resmi site</th><th>Not</th></tr></thead><tbody>{st_satir}</tbody></table></div>
<p class="mut">OK: sayfa açıldı, ekran görüntüsü alındı. ENGELLİ/HATA/BOŞ: o ülke yalnızca arama ile tarandı (ekran görüntüsü yok).</p></section>
</main><script>
const bt=document.querySelectorAll('nav button'),ss=document.querySelectorAll('section');
bt.forEach(b=>b.onclick=()=>{{bt.forEach(x=>x.classList.toggle('on',x===b));ss.forEach(s=>s.classList.toggle('on',s.id===b.dataset.t))}});
const q=document.getElementById('ara'),m=document.getElementById('marka');
function f(){{const t=q.value.toLowerCase();document.querySelectorAll('section tbody tr').forEach(r=>{{
 const ok=(!t||r.textContent.toLowerCase().includes(t))&&(!m.value||r.cells[0].textContent===m.value);r.style.display=ok?'':'none'}})}}
q.oninput=f;m.onchange=f;
</script></body></html>"""


ALANLAR = ["marka", "ulke", "ad", "aciklama", "fiyat", "etiket", "guven", "ulkede_ilk_cikis", "baska_ulkeler",
           "neden", "kanit", "kaynak_turu", "kaynaklar", "ekran", "site_adresi"]


def satir_duz(a):
    return [
        a["marka"], a["ulke"], a["ad"], a.get("aciklama", ""), a.get("fiyat", ""), a.get("etiket", ""), a["guven"],
        a.get("ulkede_ilk_cikis", ""),
        "; ".join(f"{x.get('ulke')} ({x.get('tarih', '?')})" for x in a.get("baska_ulkeler", [])),
        a.get("neden", ""), a.get("kanit", ""), " + ".join(a["kaynak_turu"]),
        "\n".join(k["adres"] for k in a["kaynaklar"]), a.get("ekran", ""), a.get("site_adresi", ""),
    ]


BASLIK = ["Marka", "Ülke", "Ürün", "Açıklama", "Fiyat", "Marka etiketi", "Güven", "Bu ülkede ilk çıkış",
          "Başka ülkelerde önceden", "Elenme/uyarı nedeni", "Kanıt özeti", "Bulunduğu yer", "Kaynak bağlantıları",
          "Ekran dosyası", "Site adresi"]


def excel_yaz(dunya, ulke, elenen, siteler):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        return False
    wb = Workbook()
    wb.remove(wb.active)
    for ad, liste in (("Dünyada İlk", dunya), ("Ülkede İlk", ulke), ("Elenenler", elenen)):
        ws = wb.create_sheet(ad)
        ws.append(BASLIK)
        for a in liste:
            ws.append(satir_duz(a))
        _bicim(ws, Font, PatternFill, Alignment)
    ws = wb.create_sheet("Site durumu")
    ws.append(["Marka", "Ülke", "Resmi site", "Not", "Adres"])
    for s in siteler:
        ws.append([s["marka"], s["ulke"], s["durum"], s["neden"], s["adres"] or "(yalnızca arama)"])
    _bicim(ws, Font, PatternFill, Alignment)
    wb.save(OUT / "rapor.xlsx")
    return True


def _bicim(ws, Font, PatternFill, Alignment):
    for c in ws[1]:
        c.font = Font(name="Arial", bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F2F2B")
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(wrap_text=True, vertical="top")
    for i, col in enumerate(ws.columns):
        w = max((len(str(c.value or "")) for c in col[:60]), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(48, max(10, w + 2))
    ws.freeze_panes = "A2"


def csv_yaz(ad, liste):
    with open(OUT / ad, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(BASLIK)
        for a in liste:
            w.writerow(satir_duz(a))


# --------------------------------------------------------------------------------------
# Ana akış
# --------------------------------------------------------------------------------------
def guvenli(fn, *args):
    try:
        return fn(*args), ""
    except Exception as ex:  # noqa: BLE001
        return None, f"{type(ex).__name__}: {str(ex)[:160]}"


def main():
    if not API_KEY and not os.environ.get("RADAR_TEST"):
        print("HATA: GEMINI_API_KEY tanımlı değil. GitHub > Settings > Secrets and variables > Actions bölümüne ekleyin.")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    zaman = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    sites = [s for s in SITES if not ONLY or s[1] in ONLY]
    print(f"Dönem: {DONEM_BAS} - {BUGUN} ({GUN} gün), {len(sites)} marka x ülke", flush=True)

    # 1) Siteler
    siteler = []
    if SADECE_ARAMA:
        siteler = [{"kod": k, "marka": m, "ulke": u, "adres": a, "durum": "ATLANDI", "neden": "test", "ekranlar": []}
                   for k, m, u, a, d in sites]
    else:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            kw = {"headless": True}
            if os.environ.get("CHROMIUM_PATH"):
                kw.update(executable_path=os.environ["CHROMIUM_PATH"], args=["--no-sandbox"])
            br = p.chromium.launch(**kw)
            for i, (kod, marka, ulke, url, dil) in enumerate(sites, 1):
                if not url:
                    siteler.append({"kod": kod, "marka": marka, "ulke": ulke, "adres": None,
                                    "durum": "ADRES YOK", "neden": "Yalnızca arama ile taranır", "ekranlar": []})
                    continue
                s = tara_site(br, kod, marka, ulke, url, dil)
                siteler.append(s)
                print(f"  site [{i}/{len(sites)}] {marka}/{ulke}: {s['durum']} {s['neden']}", flush=True)
            br.close()

    # 2) Görüntü okuma
    adaylar, hatalar = [], []
    acik = [s for s in siteler if s["durum"] == "OK" and s["ekranlar"]]
    print(f"Görüntü okuma: {len(acik)} site", flush=True)
    with ThreadPoolExecutor(PARALEL) as ex:
        for s, (sonuc, hata) in zip(acik, ex.map(lambda s: guvenli(gorsel_adaylar, s), acik)):
            if hata:
                hatalar.append(f"görüntü {s['marka']}/{s['ulke']}: {hata}")
            else:
                adaylar += sonuc

    # 3) Aramalı keşif
    print(f"Aramalı keşif: {len(sites)} marka x ülke", flush=True)
    with ThreadPoolExecutor(PARALEL) as ex:
        sonuclar = list(ex.map(lambda s: guvenli(arama_adaylar, s[1], s[2]), sites))
    for s, (sonuc, hata) in zip(sites, sonuclar):
        if hata:
            hatalar.append(f"arama {s[1]}/{s[2]}: {hata}")
        else:
            adaylar += sonuc

    # 4) Birleştir, arşivle karşılaştır
    adaylar = birlestir(adaylar)
    arsiv = arsiv_oku()
    for a in adaylar:
        a["arsiv_kaydi"] = arsivde_bul(arsiv, a["marka"], a["ulke"], a["_slug"])
    print(f"Birleşik aday: {len(adaylar)}", flush=True)
    if len(adaylar) > MAX_ADAY:
        # Önce hem siteden hem aramadan gelenler, sonra siteden gelenler
        adaylar.sort(key=lambda a: (-len(a["kaynak_turu"]), "site" not in a["kaynak_turu"]))
        hatalar.append(f"{len(adaylar) - MAX_ADAY} aday sınır nedeniyle doğrulanmadı (MAX_ADAY={MAX_ADAY})")
        atlanan, adaylar = adaylar[MAX_ADAY:], adaylar[:MAX_ADAY]
    else:
        atlanan = []

    # 5) Doğrulama
    print("Doğrulama başlıyor", flush=True)
    with ThreadPoolExecutor(PARALEL) as ex:
        sonuclar = list(ex.map(lambda a: guvenli(dogrula, a), adaylar))
    for a, (sonuc, hata) in zip(adaylar, sonuclar):
        if hata:
            hatalar.append(f"doğrulama {a['marka']}/{a['ulke']}/{a['ad']}: {hata}")
            a["dogrulama"], a["kaynaklar_dogrulama"] = {}, []
        else:
            a.update(sonuc)
        sinif_ver(a)
    for a in atlanan:      # doğrulanmadı: asla Doğrulandı değil
        a["dogrulama"], a["kaynaklar_dogrulama"] = {}, []
        sinif_ver(a)
        a["sinif"], a["guven"], a["neden"] = "ulke", "Doğrulanamadı", "Doğrulama sınırı nedeniyle kontrol edilmedi"
    tum = adaylar + atlanan

    # 6) Arşivi güncelle
    bugun = BUGUN.isoformat()
    for a in tum:
        k = a.get("arsiv_kaydi")
        if k:
            k["son_gorulme"] = bugun
        else:
            arsiv.setdefault("urunler", []).append({
                "marka": a["marka"], "ulke": a["ulke"], "ad": a["ad"], "slug": a["_slug"],
                "ilk_gorulme": bugun, "son_gorulme": bugun})
    ARSIV.parent.mkdir(parents=True, exist_ok=True)
    ARSIV.write_text(json.dumps(arsiv, ensure_ascii=False, indent=1), encoding="utf-8")

    # 7) Rapor
    sira = lambda a: (a["marka"], a["ulke"], a["ad"])  # noqa: E731
    dunya = sorted([a for a in tum if a["sinif"] == "dunya"], key=sira)
    ulke = sorted([a for a in tum if a["sinif"] == "ulke"], key=sira)
    elenen = sorted([a for a in tum if a["sinif"] == "elenen"], key=sira)
    acik_n = len(acik)
    ist = (f"{len(siteler)} marka x ülke, resmi sitesi açılan {acik_n}, hata/uyarı {len(hatalar)}")
    (OUT / "rapor.html").write_text(html_yaz(dunya, ulke, elenen, siteler, zaman, ist), encoding="utf-8")
    csv_yaz("dunyada_ilk.csv", dunya)
    csv_yaz("ulkede_ilk.csv", ulke)
    csv_yaz("elenenler.csv", elenen)
    excel_yaz(dunya, ulke, elenen, siteler)
    (OUT / "hatalar.txt").write_text("\n".join(hatalar) or "Hata yok.", encoding="utf-8")

    # Depoda tutulacak son ekran görüntüleri
    if os.environ.get("EKRAN_KOPYALA") == "1":
        import shutil
        shutil.rmtree(SON_EKRAN, ignore_errors=True)
        shutil.copytree(SHOTS, SON_EKRAN)

    ozet = (f"## Yeni Ürün Radarı\nDönem: {DONEM_BAS} – {BUGUN}\n\n| Katman | Adet |\n|---|---|\n"
            f"| Dünyada ilk | {len(dunya)} |\n| Ülkede ilk | {len(ulke)} |\n| Elenen | {len(elenen)} |\n\n"
            f"Resmi sitesi açılan: {acik_n}/{len(siteler)} · Doğrulanamayan satır: "
            f"{sum(1 for a in tum if a['guven'] == 'Doğrulanamadı')} · Hata/uyarı: {len(hatalar)}\n"
            f"Aramalı Gemini çağrısı: {_arama_sayaci['n']}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(ozet)
    print(ozet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
