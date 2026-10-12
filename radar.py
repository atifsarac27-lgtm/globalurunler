#!/usr/bin/env python3
"""
YENİ ÜRÜN RADARI  (sürüm 2)

Son 2 ayda (varsayılan 60 gün) marka x ülke bazında piyasaya çıkan YENİ ürünleri bulur.

Hat:
  1) Resmi sitelerin ana sayfası gerçek tarayıcıyla açılır (çerez ve açılır pencereler kapatılır),
     ekran görüntüsü alınır.
  2) Gemini (görüntü okuma) yalnızca üzerinde "yeni" ifadesi olan banner ürünlerini çıkarır,
     ürünün görüntüdeki yerini de verir (rapor için kırpılır).
  3) Her marka x ülke için Google aramalı Gemini ile ikinci bir keşif yapılır
     (siteye girilemeyen yerler için tek kaynak budur).
  4) Adaylar birleştirilir, önceki çalışmaların arşiviyle karşılaştırılır.
  5) Her aday için iki geçişli doğrulama: önce aramalı serbest metin, sonra araçsız yapılandırma.
     Kaynak bağlantısı yoksa satır asla "Doğrulandı" olmaz ve "Dünyada İlk"e giremez.
  6) Rapor: Dünyada İlk / Ülkede İlk / Belirsiz / Elenenler (PDF, HTML, XLSX, CSV).

Gerekli ortam değişkeni: GEMINI_API_KEY
"""
import base64
import csv
import difflib
import hashlib
import html
import io
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
from urllib.parse import urljoin, urlparse

# --------------------------------------------------------------------------------------
# Ayarlar
# --------------------------------------------------------------------------------------
GUN = int(os.environ.get("DONEM_GUN") or "60")             # son 2 ay
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
THINKING = os.environ.get("GEMINI_THINKING", "low")        # boş bırakılırsa gönderilmez
PARALEL = int(os.environ.get("PARALEL", "5"))
MAX_ADAY = int(os.environ.get("MAX_ADAY", "900"))          # doğrulanacak en çok aday
MAX_ARAMA = int(os.environ.get("MAX_ARAMA", "1800"))       # bir çalışmada en çok aramalı çağrı
ONLY = [x.strip() for x in os.environ.get("ONLY", "").split(",") if x.strip()]  # yalnız bu markalar
SADECE_ARAMA = os.environ.get("SADECE_ARAMA") == "1"       # siteleri açma (test)

OUT = Path(os.environ.get("OUT_DIR", "rapor"))
SHOTS = OUT / "ekran_goruntuleri"
GORSEL = OUT / "gorseller"
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
KAPAT_SELECTORS = [
    "[role=dialog] [aria-label*='close' i]", "[role=dialog] [aria-label*='kapat' i]",
    "[aria-modal=true] [aria-label*='close' i]", "[aria-label='Close']", "[aria-label='close']",
    ".modal [class*='close' i]", "[class*='popup' i] [class*='close' i]", "[class*='modal' i] button[class*='close' i]",
    "button:has-text('×')", "button:has-text('✕')", "button:has-text('No thanks')", "button:has-text('Not now')",
]
# Ekranın büyük kısmını kaplayan sabit katmanları (konum/abonelik/uygulama pencereleri) gizler.
# Bu bir engel aşma değildir: sıradan bir ziyaretçinin pencereyi kapatmasıyla aynı sonuç.
KATMAN_GIZLE_JS = """
() => {
  const W = innerWidth, H = innerHeight; let n = 0;
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    const r = el.getBoundingClientRect();
    if (r.top <= 0 && r.height < 220) continue;               // üst menü / başlık
    if (r.width * r.height < 0.25 * W * H) continue;          // küçük şeritler
    const z = parseInt(s.zIndex || '0', 10);
    if (isNaN(z) || z < 10) continue;
    el.style.setProperty('display', 'none', 'important'); n++;
  }
  document.documentElement.style.overflow = 'auto'; document.body.style.overflow = 'auto';
  return n;
}
"""
BLOCK_RE = re.compile(
    r"access denied|request blocked|attention required|just a moment|checking your browser|"
    r"verify you are (a )?human|are you a robot|captcha|unusual traffic|pardon our interruption|"
    r"you have been blocked|erişim engellendi|zugriff verweigert|acceso denegado|"
    r"enable javascript and cookies|errors\.edgesuite\.net|incapsula incident|px-captcha", re.I)


def _tikla_ilk(page, secimler, bekle=700):
    for sel in secimler:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=300):
                loc.click(timeout=1500)
                page.wait_for_timeout(bekle)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def pencereleri_kapat(page):
    _tikla_ilk(page, COOKIE_SELECTORS)
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:  # noqa: BLE001
        pass
    for _ in range(2):
        if not _tikla_ilk(page, KAPAT_SELECTORS):
            break
    try:
        page.evaluate(KATMAN_GIZLE_JS)
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:  # noqa: BLE001
        pass


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
        pencereleri_kapat(page)
        page.wait_for_timeout(1200)
        dosyalar = []
        for i in (1, 2):
            if i == 2:
                page.wait_for_timeout(6000)       # kaydırmalı bannerın değişmesi için
                pencereleri_kapat(page)           # sonradan açılan pencereler
            f = SHOTS / f"{kod}_{i}.jpg"
            page.screenshot(path=str(f), type="jpeg", quality=80)
            dosyalar.append(f.name)
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


class _Durdur(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def adres_coz(kaynaklar):
    """Gemini'nin yönlendirme bağlantılarını (vertexaisearch...) gerçek sayfa adresine çevirmeyi dener."""
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
        out.append({"baslik": k.get("baslik", "") or urlparse(a).netloc, "adres": a,
                    "destek": k.get("destek", [])})
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


def evet_hayir(x):
    x = str(x or "").strip().lower()
    if x in ("evet", "yes", "true", "1"):
        return "evet"
    if x in ("hayir", "hayır", "no", "false", "0"):
        return "hayir"
    return "bilinmiyor"


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
        "GÖREV: Yalnızca üzerinde AÇIKÇA yenilik ifadesi yazan yemek-içecek ÜRÜNLERİNİ listele. Yenilik ifadesi "
        "örnekleri: NEW, New!, Nuevo, Nueva, Neu, Nieuw, Nouveau, Novo, Nowość, Yeni, 新発売, 新登場, 新品, 신메뉴, "
        "Limited time, 期間限定, Only for a limited time, Just dropped. Ayrıca 'is back', 'returns', 'vuelve', "
        "'regresa', 'geri döndü', '復活' gibi GERİ DÖNÜŞ ifadesi olanları da listele ve geri_donus=true yap.\n"
        "ALMA: fiyat kampanyaları, indirimler, mevcut ürünlerden oluşan menü/paket fırsatları, uygulama reklamları, "
        "oyuncak/kampanya ürünleri, restoran açılışları, üzerinde yenilik ya da geri dönüş ifadesi olmayan ürünler.\n"
        "Görüntüde olmayan hiçbir şeyi tahmin etme.\n"
        "Her ürün için JSON nesnesi: {\"ad\": ürün adı görüntüde yazdığı gibi, ÇEVİRMEDEN, \"aciklama\": 1 cümle Türkçe "
        "açıklama, \"yeni_ifadesi\": görüntüdeki yenilik ya da geri dönüş ifadesinin aynısı, \"geri_donus\": true/false, "
        "\"fiyat\": görünüyorsa, \"ekran\": 1 veya 2, \"kutu\": [ymin, xmin, ymax, xmax] ürün görselini ve adını içeren "
        "alan, 0-1000 ölçeğinde}.\n"
        "Aynı ürünü iki ekranda görürsen tek kez yaz. Yalnızca JSON dizisi döndür; uygun ürün yoksa []."
    )})
    metin, _ = cagri(parts, json_cikti=True, sicaklik=0.0)
    veri = json_cikar(metin)
    sonuc = []
    if isinstance(veri, list):
        for x in veri:
            if not (isinstance(x, dict) and str(x.get("ad", "")).strip()):
                continue
            ifade = str(x.get("yeni_ifadesi", "") or "").strip()
            donus = x.get("geri_donus") in (True, "true", "evet")
            if not ifade and not donus:
                continue                      # yenilik kanıtı yok -> alma
            ekran_no = x.get("ekran") if x.get("ekran") in (1, 2) else 1
            ekran_no = min(ekran_no, len(site["ekranlar"]))
            kutu = x.get("kutu") if isinstance(x.get("kutu"), list) and len(x.get("kutu")) == 4 else None
            sonuc.append({
                "marka": marka, "ulke": ulke, "ad": str(x["ad"]).strip(),
                "aciklama": str(x.get("aciklama", "") or "").strip(),
                "etiket": ifade, "fiyat": str(x.get("fiyat", "") or "").strip(),
                "kaynak_turu": ["site"], "ekran": site["ekranlar"][ekran_no - 1], "kutu": kutu,
                "site_adresi": site["adres"], "kaynaklar": [], "site_geri_donus": donus,
            })
    return sonuc


# --------------------------------------------------------------------------------------
# 2) Aramalı keşif (marka x ülke) - iki geçiş
# --------------------------------------------------------------------------------------
def arama_adaylar(marka, ulke):
    bas, bit = DONEM_BAS.isoformat(), BUGUN.isoformat()
    p1 = (
        f"{marka} markası {ulke} pazarında {bas} ile {bit} tarihleri arasında hangi YENİ yemek-içecek ürünlerini "
        "menüye ekledi ya da lanse etti? Google aramasını kullan; markanın resmi sitesine, sosyal medya duyurularına, "
        "basın açıklamalarına ve güvenilir haberlere bak.\n"
        "DAHİL ETME: fiyat kampanyaları, indirimler, mevcut ürünlerden oluşan menü/paket fırsatları, uygulama "
        "kampanyaları, oyuncaklar, ambalaj/tasarım değişiklikleri, restoran açılışları.\n"
        "Geri dönen (daha önce satılmış, tekrar menüye gelen) ürünleri ayrıca 'geri dönen' diye belirt.\n"
        "Her ürün için markanın kullandığı ORİJİNAL adı (çevirmeden), çıkış tarihini ve kısa açıklamasını yaz. "
        "Sadece aramada bulduğun bilgiyi yaz, tahmin etme. Bu dönemde yeni ürün bulamazsan açıkça 'bulunamadı' yaz."
    )
    metin, kaynaklar = cagri([{"text": p1}], arama=True)
    if not kaynaklar:                         # Gemini 3.x'te bazen metaveri eksik gelir; bir kez daha dene
        metin, kaynaklar = cagri([{"text": p1}], arama=True)
    if not metin or (re.search(r"bulunamad|bulamad|no new|not found", metin[:300], re.I) and len(metin) < 400):
        return []
    p2 = (
        f"Aşağıdaki metinde geçen {marka} / {ulke} ürünlerini JSON dizisine çevir. YALNIZCA metinde yazanı kullan, "
        "bilgi ekleme.\nHer öğe: {\"ad\": markanın kullandığı orijinal ad (ÇEVİRME), \"aciklama\": 1 cümle Türkçe, "
        "\"cikis_tarihi\": \"YYYY-AA-GG veya YYYY-AA veya boş\", \"geri_donus\": \"evet/hayir/bilinmiyor\"}.\n"
        "Fiyat kampanyası, paket fırsatı ya da ürün olmayan şeyleri ALMA. Ürün yoksa [] döndür.\n\nMETİN:\n" + metin
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
                    "kaynak_turu": ["arama"], "ekran": "", "kutu": None, "site_adresi": "",
                    "kaynaklar": k, "arama_tarihi": str(x.get("cikis_tarihi", "") or "").strip(),
                    "arama_geri_donus": evet_hayir(x.get("geri_donus")),
                })
    return sonuc


# --------------------------------------------------------------------------------------
# 3) Birleştirme ve arşiv
# --------------------------------------------------------------------------------------
def slug(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[\W_]+", "", s)


def ad_varyantlari(ad):
    """'Ürün X (別名) / Ürün Y' -> ['ürün x (別名) / ürün y', 'ürün x', '別名', 'ürün y']"""
    parcalar = [ad] + [p for p in re.split(r"[()/|\[\]（）]", ad) if p.strip()]
    return [p.strip() for p in parcalar if len(slug(p)) >= 2]


def benzer(a, b):
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) >= 5 and (a in b or b in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.86


def ad_benzer(ad1, ad2):
    return any(benzer(slug(x), slug(y)) for x in ad_varyantlari(ad1) for y in ad_varyantlari(ad2))


def birlestir(adaylar):
    gruplar = []
    for a in adaylar:
        for g in gruplar:
            if g["marka"] == a["marka"] and g["ulke"] == a["ulke"] and ad_benzer(g["ad"], a["ad"]):
                for t in a["kaynak_turu"]:
                    if t not in g["kaynak_turu"]:
                        g["kaynak_turu"].append(t)
                if not g.get("ekran") and a.get("ekran"):
                    g["ekran"], g["kutu"], g["site_adresi"] = a["ekran"], a.get("kutu"), a["site_adresi"]
                for k in a.get("kaynaklar", []):
                    if k["adres"] not in {x["adres"] for x in g["kaynaklar"]}:
                        g["kaynaklar"].append(k)
                for alan in ("aciklama", "etiket", "fiyat", "arama_tarihi"):
                    if not g.get(alan) and a.get(alan):
                        g[alan] = a[alan]
                g["site_geri_donus"] = g.get("site_geri_donus") or a.get("site_geri_donus")
                if a.get("arama_geri_donus") == "evet":
                    g["arama_geri_donus"] = "evet"
                break
        else:
            b = dict(a)
            b["_slug"] = slug(a["ad"])
            b["id"] = hashlib.md5(f"{a['marka']}|{a['ulke']}|{b['_slug']}".encode()).hexdigest()[:10]
            gruplar.append(b)
    return gruplar


def arsiv_oku():
    try:
        return json.loads(ARSIV.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"urunler": []}


def arsivde_bul(arsiv, marka, ulke, ad):
    for u in arsiv.get("urunler", []):
        if u["marka"] == marka and u["ulke"] == ulke and ad_benzer(u["ad"], ad):
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
        f"2) {marka}, aynı ürünü (aynı ürün ya da aynı adla/aynı tarifle) daha önce dünyanın başka bir ülkesinde "
        "sattı mı? Hangi ülkelerde, ne zaman? Bulduğun her kaydı yaz.\n"
        f"3) Marka ya da haberler bu ürün için 'dünyada ilk', 'ilk kez', 'sadece {ulke}'de', 'world first', "
        "'exclusive', 'only in' gibi bir ifade kullanıyor mu? Kullanıyorsa aynen aktar.\n"
        f"4) Ürün daha önce {ulke}'de satılıp kaldırıldı ve şimdi geri mi döndü?\n"
        "Sadece aramada bulduğun bilgiyi yaz, tahmin etme. Bulamadığın konuda açıkça 'bilgi bulunamadı' yaz. "
        "Cevaplarında ürünün adını açıkça kullan. Mümkünse tarihleri ver."
    )
    metin, kaynaklar = cagri([{"text": p1}], arama=True)
    if not kaynaklar:
        metin, kaynaklar = cagri([{"text": p1}], arama=True)
    p2 = (
        "Aşağıdaki araştırma metnini JSON nesnesine çevir. YALNIZCA metinde yazanı kullan; metinde yoksa "
        "\"bilinmiyor\" yaz.\n{\n"
        "  \"bu_ulkede_ilk_cikis\": \"YYYY-AA-GG / YYYY-AA / bilinmiyor\",\n"
        "  \"baska_ulkelerde_once_satildi\": [{\"ulke\": ..., \"tarih\": ...}],\n"
        "  \"baska_ulkede_satildi_mi\": \"evet (metinde başka ülkede satış kaydı var) / hayir (metin araştırıldığını "
        "ve başka ülkede kayıt bulunmadığını ya da ürünün bu ülkeye özel olduğunu söylüyor) / bilinmiyor\",\n"
        "  \"dunyada_ilk_ifadesi\": \"metinde markanın ya da haberin 'dünyada ilk / sadece bu ülkede / exclusive' "
        "ifadesi varsa aynen, yoksa boş\",\n"
        "  \"bu_ulkede_geri_donus\": \"evet / hayir / bilinmiyor\",\n"
        "  \"kanit_ozeti\": \"1-2 cümle, Türkçe\"\n}\n\n"
        f"ÜRÜN: {ad} / {marka} / {ulke}\n\nMETİN:\n{metin}"
    )
    m2, _ = cagri([{"text": p2}], json_cikti=True, sicaklik=0.0)
    v = json_cikar(m2)
    if not isinstance(v, dict):
        v = {}
    return {"dogrulama": v, "dogrulama_metni": metin,
            "kaynaklar_dogrulama": adres_coz(kaynaklar) if kaynaklar else []}


ANLAMSIZ = {"the", "and", "with", "new", "menu", "con", "de", "del", "la", "el", "le", "les", "mit", "und",
            "und", "met", "en", "et", "com", "ve", "ile", "yeni", "nuevo", "nueva", "neu", "nieuw"}


def kaynak_bagli_mi(ad, marka, kaynak):
    """Kaynak, bu ürünün adını anan bir cümleyi destekliyor mu?"""
    metin = slug(" ".join(kaynak.get("destek", [])))
    if not metin:
        return False
    marka_s = {slug(w) for w in re.split(r"\W+", marka) if w}
    for v in ad_varyantlari(ad):
        sv = slug(v)
        if len(sv) >= 3 and sv in metin:
            return True
        kel = [slug(w) for w in re.split(r"[\s\-–,&+]+", v)]
        kel = [w for w in kel if len(w) >= 3 and w not in ANLAMSIZ and w not in marka_s]
        if len(kel) >= 2 and sum(1 for w in kel if w in metin) / len(kel) >= 0.6:
            return True
    return False


def sinif_ver(a):
    """a['sinif'] in dunya/ulke/belirsiz/elenen, a['guven'], a['neden'] doldurur."""
    v = a.get("dogrulama", {}) or {}
    dog_k = a.get("kaynaklar_dogrulama", [])
    tekil = {k["adres"]: k for k in dog_k + a.get("kaynaklar", [])}
    a["kaynaklar"] = list(tekil.values())
    bagli = [k for k in dog_k if kaynak_bagli_mi(a["ad"], a["marka"], k)]
    a["bagli_kaynak"] = len(bagli)
    kaynak_var = bool(dog_k)

    ilk = ay_anahtari(v.get("bu_ulkede_ilk_cikis", "")) or ay_anahtari(a.get("arama_tarihi", ""))
    a["ulkede_ilk_cikis"] = ilk
    baska = [x for x in (v.get("baska_ulkelerde_once_satildi") or []) if isinstance(x, dict) and x.get("ulke")
             and slug(str(x.get("ulke"))) != slug(a["ulke"])]
    a["baska_ulkeler"] = baska
    baska_mi = evet_hayir(str(v.get("baska_ulkede_satildi_mi", "")).split(" ")[0])
    if baska:
        baska_mi = "evet"
    donus = evet_hayir(v.get("bu_ulkede_geri_donus"))
    ifade = str(v.get("dunyada_ilk_ifadesi", "") or "").strip()
    if ifade.lower() in ("bilinmiyor", "yok", "-", "none"):
        ifade = ""
    a["dunyada_ilk_ifadesi"] = ifade[:200]
    a["kanit"] = str(v.get("kanit_ozeti", "") or "")[:400]
    bas_ay = ay_anahtari(DONEM_BAS.isoformat())

    def etiket_elenen():
        return "Doğrulandı" if bagli else ("Muhtemelen" if kaynak_var else "Doğrulanamadı")

    # --- Elenenler ---
    ars = a.get("arsiv_kaydi")
    if ars and ars["ilk_gorulme"] < DONEM_BAS.isoformat():
        a.update(sinif="elenen", guven="Doğrulandı",
                 neden=f"Arşivde {ars['ilk_gorulme']} tarihinde zaten görülmüş (dönemden önce)")
        return a
    if a.get("site_geri_donus"):
        a.update(sinif="elenen", guven="Doğrulandı", neden=f"Resmi sitede geri dönüş ifadesi: {a.get('etiket', '')}")
        return a
    if donus == "evet" or a.get("arama_geri_donus") == "evet":
        a.update(sinif="elenen", guven=etiket_elenen(), neden="Daha önce bu ülkede satılmış, geri dönen ürün")
        return a
    if ilk and ilk < bas_ay:
        a.update(sinif="elenen", guven=etiket_elenen(), neden=f"Bu ülkede ilk çıkış {ilk}: dönemden önce")
        return a

    # --- Kaynak yok: hiçbir zaman Dünyada/Ülkede İlk olmaz ---
    if not kaynak_var:
        a.update(sinif="belirsiz", guven="Doğrulanamadı",
                 neden="Doğrulama aramasında kaynak bulunamadı" if a.get("dogrulama") is not None
                 else "Doğrulanmadı")
        return a
    if not bagli:
        a.update(sinif="belirsiz", guven="Muhtemelen",
                 neden="Kaynaklar ürünün adını açıkça anmıyor")
        return a

    # --- Bağlı kaynak var ---
    if baska_mi == "evet":
        a.update(sinif="ulke", guven="Doğrulandı" if ilk else "Muhtemelen",
                 neden="" if ilk else "Bu ülkedeki çıkış tarihi bulunamadı")
    elif baska_mi == "hayir":
        if ilk and ifade:
            a.update(sinif="dunya", guven="Doğrulandı", neden="")
        else:
            a.update(sinif="dunya", guven="Muhtemelen",
                     neden="Başka ülkede satış kaydı bulunamadı" + ("" if ilk else "; çıkış tarihi bulunamadı"))
    else:
        a.update(sinif="belirsiz", guven="Muhtemelen",
                 neden="Başka ülkede önceden satılıp satılmadığı belirlenemedi")
    return a


# --------------------------------------------------------------------------------------
# 5) Ürün görselleri
# --------------------------------------------------------------------------------------
def _pil():
    from PIL import Image
    return Image


def _kaydet_gorsel(img, hedef):
    Image = _pil()
    img = img.convert("RGB")
    img.thumbnail((760, 760), Image.LANCZOS)
    img.save(hedef, "JPEG", quality=78, optimize=True)


def banner_kirp(a):
    """Resmi site ekran görüntüsünden ürünün olduğu alanı kırpar."""
    Image = _pil()
    kaynak = SHOTS / a["ekran"]
    if not kaynak.exists():
        return ""
    img = Image.open(kaynak)
    W, H = img.size
    k = a.get("kutu")
    try:
        y0, x0, y1, x1 = [max(0, min(1000, float(t))) for t in k]
        if y1 - y0 < 40 or x1 - x0 < 40:
            raise ValueError
        py, px = (y1 - y0) * 0.06, (x1 - x0) * 0.06
        kutu = (int((x0 - px) / 1000 * W), int((y0 - py) / 1000 * H),
                int((x1 + px) / 1000 * W), int((y1 + py) / 1000 * H))
        kutu = (max(0, kutu[0]), max(0, kutu[1]), min(W, kutu[2]), min(H, kutu[3]))
        parca = img.crop(kutu)
    except Exception:  # noqa: BLE001
        parca = img.crop((0, 0, W, min(H, int(W * 0.6))))   # kutu yoksa sayfanın üst kısmı
    hedef = GORSEL / f"{a['id']}.jpg"
    _kaydet_gorsel(parca, hedef)
    return hedef.name


OG_RE = re.compile(
    r"<meta[^>]+(?:property|name)\s*=\s*[\"'](?:og:image(?::secure_url)?|twitter:image(?::src)?)[\"'][^>]*>", re.I)
CONTENT_RE = re.compile(r"content\s*=\s*[\"']([^\"']+)[\"']", re.I)


def _getir(url, sinir, zaman=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en,tr;q=0.8"})
    with urllib.request.urlopen(req, timeout=zaman) as r:
        return r.read(sinir), r.geturl(), r.headers.get("Content-Type", "")


def kaynak_gorseli(a):
    """Kaynak haber/duyuru sayfasının paylaşım görselini (og:image) indirir."""
    Image = _pil()
    sirali = sorted(a.get("kaynaklar", []), key=lambda k: not kaynak_bagli_mi(a["ad"], a["marka"], k))
    for k in sirali[:4]:
        try:
            govde, son_adres, _ = _getir(k["adres"], 1_500_000)
            sayfa = govde.decode("utf-8", "replace")
            m = OG_RE.search(sayfa)
            if not m:
                continue
            c = CONTENT_RE.search(m.group(0))
            if not c:
                continue
            gurl = urljoin(son_adres, html.unescape(c.group(1)))
            veri, _, tur = _getir(gurl, 6_000_000)
            img = Image.open(io.BytesIO(veri))
            if img.size[0] < 300 or img.size[1] < 180:
                continue
            hedef = GORSEL / f"{a['id']}.jpg"
            _kaydet_gorsel(img, hedef)
            return hedef.name, urlparse(son_adres).netloc.replace("www.", "")
        except Exception:  # noqa: BLE001
            continue
    return "", ""


def gorsel_bul(a):
    if a.get("ekran"):
        try:
            ad = banner_kirp(a)
            if ad:
                return ad, "Resmi site"
        except Exception:  # noqa: BLE001
            pass
    ad, alan = kaynak_gorseli(a)
    return (ad, f"Kaynak sayfa: {alan}") if ad else ("", "")


# --------------------------------------------------------------------------------------
# 6) Raporlar
# --------------------------------------------------------------------------------------
KATMAN = [("dunya", "Dünyada İlk"), ("ulke", "Ülkede İlk"), ("belirsiz", "Belirsiz (incelenecek)"),
          ("elenen", "Elenenler")]
GUVEN_SINIF = {"Doğrulandı": "g1", "Muhtemelen": "g2", "Doğrulanamadı": "g3"}


def e(x):
    return html.escape(str(x or ""))


def alan_adi(u):
    return urlparse(u).netloc.replace("www.", "")


def kaynak_html(a, n=4):
    if not a["kaynaklar"]:
        return "<span class=\"yok\">kaynak yok</span>"
    return "<br>".join(f"<a href=\"{e(k['adres'])}\" target=\"_blank\" rel=\"noopener\">{e(alan_adi(k['adres']) or k['baslik'])[:48]}</a>"
                       for k in a["kaynaklar"][:n])


def baska_metni(a):
    return ", ".join(f"{x.get('ulke')} ({x.get('tarih') or '?'})" for x in a.get("baska_ulkeler", [])[:6])


def kt_metni(a):
    return " + ".join({"site": "Resmi site", "arama": "Arama"}[t] for t in a["kaynak_turu"])


def satir_html(a):
    gorsel = (f"<a href=\"gorseller/{e(a['gorsel'])}\" target=\"_blank\"><img loading=\"lazy\" "
              f"src=\"gorseller/{e(a['gorsel'])}\" alt=\"\"></a>") if a.get("gorsel") else ""
    if a.get("ekran"):
        gorsel += f"<div class=\"alt\"><a href=\"ekran_goruntuleri/{e(a['ekran'])}\" target=\"_blank\">tam ekran</a></div>"
    son = a.get("neden", "") if a["sinif"] == "elenen" else (baska_metni(a) or "-")
    not_ = a.get("dunyada_ilk_ifadesi") or ("" if a["sinif"] == "elenen" else a.get("neden", ""))
    return (f"<tr><td>{e(a['marka'])}</td><td>{e(a['ulke'])}</td>"
            f"<td><b>{e(a['ad'])}</b><div class=\"alt\">{e(a.get('aciklama'))} {e(a.get('fiyat'))}</div>"
            f"{'<div class=alt>Sitede: ' + e(a['etiket']) + '</div>' if a.get('etiket') else ''}</td>"
            f"<td><span class=\"rozet {GUVEN_SINIF[a['guven']]}\">{e(a['guven'])}</span><div class=\"alt\">{e(kt_metni(a))}</div></td>"
            f"<td>{e(a.get('ulkede_ilk_cikis') or '-')}</td><td>{e(son)}<div class=\"alt\">{e(not_)}</div>"
            f"<div class=\"alt\">{e(a.get('kanit'))}</div></td>"
            f"<td>{kaynak_html(a)}</td><td class=\"ek\">{gorsel}</td></tr>")


def html_yaz(katmanlar, siteler, zaman, istatistik):
    def tablo(liste, son_baslik):
        if not liste:
            return "<p class=\"bos\">Kayıt yok.</p>"
        h = ("<table><thead><tr><th>Marka</th><th>Ülke</th><th>Ürün</th><th>Güven</th><th>Bu ülkede ilk çıkış</th>"
             f"<th>{son_baslik}</th><th>Kaynaklar</th><th>Görsel</th></tr></thead><tbody>")
        return h + "".join(satir_html(a) for a in liste) + "</tbody></table>"

    sonlar = {"dunya": "Not", "ulke": "Başka ülkelerde önceden", "belirsiz": "Bilinen", "elenen": "Elenme nedeni"}
    dugmeler = "".join(f"<button data-t=\"{k}\"{' class=on' if i == 0 else ''}>{ad} ({len(katmanlar[k])})</button>"
                       for i, (k, ad) in enumerate(KATMAN))
    bolumler = "".join(f"<section id=\"{k}\"{' class=on' if i == 0 else ''}><div class=\"sar\">{tablo(katmanlar[k], sonlar[k])}</div></section>"
                       for i, (k, _) in enumerate(KATMAN))
    st_satir = "".join(
        f"<tr><td>{e(s['marka'])}</td><td>{e(s['ulke'])}</td><td>{e(s['durum'])}</td><td>{e(s['neden'])}</td></tr>"
        for s in siteler)
    markalar = "".join(f"<option>{e(m)}</option>" for m in sorted({s['marka'] for s in siteler}))
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Yeni Ürün Radarı</title>
<style>
:root{{--bg:#fafaf8;--fg:#1c1c1a;--mut:#6b6b66;--kart:#fff;--cizgi:#e4e3dd;--ok:#1f7a45;--okb:#e3f3ea;--uyari:#8a5a00;--uyarib:#fdf0d5;--kot:#a02b2b;--kotb:#fbe5e5}}
@media(prefers-color-scheme:dark){{:root{{--bg:#161614;--fg:#ecebe6;--mut:#9a9992;--kart:#1f1f1c;--cizgi:#34332f;--ok:#6fd09a;--okb:#16301f;--uyari:#f1c36a;--uyarib:#33290f;--kot:#f08a8a;--kotb:#3a1b1b}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:1320px;margin:0 auto;padding:20px 16px 60px}}
h1{{margin:0 0 4px;font-size:24px}} .mut{{color:var(--mut)}}
nav{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 10px}}
nav button{{border:1px solid var(--cizgi);background:var(--kart);color:var(--fg);padding:8px 14px;border-radius:8px;cursor:pointer;font:inherit}}
nav button.on{{background:var(--fg);color:var(--bg)}}
.arac{{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 14px}} .arac input,.arac select{{padding:8px 10px;border:1px solid var(--cizgi);border-radius:8px;background:var(--kart);color:var(--fg);font:inherit}}
section{{display:none}} section.on{{display:block}}
.sar{{overflow-x:auto;border:1px solid var(--cizgi);border-radius:10px;background:var(--kart)}}
table{{border-collapse:collapse;width:100%;min-width:960px}} th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--cizgi);vertical-align:top}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut);position:sticky;top:0;background:var(--kart)}}
.alt{{font-size:12.5px;color:var(--mut)}} .rozet{{padding:2px 8px;border-radius:99px;font-size:12px;font-weight:600;white-space:nowrap}}
.g1{{background:var(--okb);color:var(--ok)}} .g2{{background:var(--uyarib);color:var(--uyari)}} .g3{{background:var(--kotb);color:var(--kot)}}
.ek img{{width:140px;max-height:140px;object-fit:contain;border-radius:6px;border:1px solid var(--cizgi);background:#fff}} .yok{{color:var(--kot)}} .bos{{padding:20px;color:var(--mut)}}
a{{color:inherit}}
</style></head><body><main>
<h1>Yeni Ürün Radarı</h1>
<div class="mut">Dönem: {DONEM_BAS.strftime('%d.%m.%Y')} – {BUGUN.strftime('%d.%m.%Y')} (son {GUN} gün) · Oluşturma: {e(zaman)}</div>
<div class="mut">{e(istatistik)}</div>
<p class="mut"><span class="rozet g1">Doğrulandı</span> ürünü adıyla anan kaynak var, tarih ve diğer bilgiler net ·
<span class="rozet g2">Muhtemelen</span> kaynak var ama bir bilgi eksik ya da kaynak ürünü adıyla anmıyor ·
<span class="rozet g3">Doğrulanamadı</span> kaynak bulunamadı. Kaynaksız satır hiçbir zaman Dünyada/Ülkede İlk'e girmez.</p>
<nav>{dugmeler}<button data-t="site">Site durumu ({len(siteler)})</button></nav>
<div class="arac"><input id="ara" placeholder="Ara (ürün, ülke...)"><select id="marka"><option value="">Tüm markalar</option>{markalar}</select></div>
{bolumler}
<section id="site"><div class="sar"><table><thead><tr><th>Marka</th><th>Ülke</th><th>Resmi site</th><th>Not</th></tr></thead><tbody>{st_satir}</tbody></table></div>
<p class="mut">OK: sayfa açıldı, ekran görüntüsü alındı. Diğerleri yalnızca arama ile tarandı.</p></section>
</main><script>
const bt=document.querySelectorAll('nav button'),ss=document.querySelectorAll('section');
bt.forEach(b=>b.onclick=()=>{{bt.forEach(x=>x.classList.toggle('on',x===b));ss.forEach(s=>s.classList.toggle('on',s.id===b.dataset.t))}});
const q=document.getElementById('ara'),m=document.getElementById('marka');
function f(){{const t=q.value.toLowerCase();document.querySelectorAll('section tbody tr').forEach(r=>{{
 const ok=(!t||r.textContent.toLowerCase().includes(t))&&(!m.value||r.cells[0].textContent===m.value);r.style.display=ok?'':'none'}})}}
q.oninput=f;m.onchange=f;
</script></body></html>"""


# ---------------------------------- PDF ----------------------------------------------
PDF_CSS = """
@page { size: A4; margin: 14mm 12mm 16mm 12mm; }
* { box-sizing: border-box; }
body { margin: 0; color: #1d1d1b; font: 9.6pt/1.42 "Noto Sans", "Liberation Sans", Arial, "Noto Sans CJK JP", "Noto Sans Thai", "Noto Sans Arabic", sans-serif; }
h1 { font-size: 26pt; margin: 0 0 6pt; letter-spacing: -.01em; }
h2 { font-size: 17pt; margin: 0 0 4pt; padding-bottom: 4pt; border-bottom: 2pt solid #1d1d1b; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 14pt 0 6pt; padding: 4pt 8pt; background: #efede6; border-radius: 4pt; break-after: avoid; }
.kapak { height: 250mm; display: flex; flex-direction: column; justify-content: center; }
.kapak .alt { font-size: 12pt; color: #5e5e58; }
.ozet { border-collapse: collapse; margin-top: 16pt; width: 100%; }
.ozet th, .ozet td { border-bottom: .6pt solid #d8d6ce; padding: 5pt 6pt; text-align: left; }
.ozet th { font-size: 8pt; text-transform: uppercase; color: #6b6b66; }
.ozet td.s { text-align: right; font-variant-numeric: tabular-nums; }
.aciklama { font-size: 9pt; color: #4a4a45; margin-top: 18pt; }
.bolum { break-before: page; }
.bolum-not { color: #5e5e58; margin: 0 0 6pt; }
.izgara { display: grid; grid-template-columns: 1fr 1fr; gap: 8pt; }
.kart { border: .7pt solid #d8d6ce; border-radius: 6pt; padding: 7pt; break-inside: avoid; display: flex; flex-direction: column; gap: 4pt; }
.kart .gorsel { height: 150pt; display: flex; align-items: center; justify-content: center; background: #f6f5f1; border-radius: 4pt; overflow: hidden; }
.kart .gorsel img { max-width: 100%; max-height: 150pt; object-fit: contain; }
.kart .gorsel.yok { height: 34pt; color: #8a8a83; font-size: 8pt; }
.kart .ad { font-weight: 700; font-size: 10.5pt; }
.kart .acik { color: #4a4a45; }
.kart .bilgi { font-size: 8.4pt; color: #3b3b37; }
.kart .kucuk { font-size: 7.6pt; color: #6b6b66; word-break: break-word; }
.rozet { display: inline-block; padding: 0 5pt; border-radius: 8pt; font-size: 7.6pt; font-weight: 700; }
.g1 { background: #e3f3ea; color: #1f7a45; } .g2 { background: #fdf0d5; color: #8a5a00; } .g3 { background: #fbe5e5; color: #a02b2b; }
table.liste { border-collapse: collapse; width: 100%; font-size: 8.4pt; }
table.liste th, table.liste td { border-bottom: .5pt solid #dedcd4; padding: 3.5pt 4pt; text-align: left; vertical-align: top; }
table.liste th { font-size: 7.4pt; text-transform: uppercase; color: #6b6b66; }
table.liste tr { break-inside: avoid; }
a { color: inherit; text-decoration: none; }
"""


def pdf_kart(a, kok):
    if a.get("gorsel"):
        g = (f"<div class=\"gorsel\"><img src=\"{(kok / 'gorseller' / a['gorsel']).as_uri()}\"></div>")
    else:
        g = "<div class=\"gorsel yok\">Görsel bulunamadı</div>"
    satir = [f"Bu ülkede ilk çıkış: <b>{e(a.get('ulkede_ilk_cikis') or 'bilinmiyor')}</b>"]
    if a.get("baska_ulkeler"):
        satir.append(f"Daha önce: {e(baska_metni(a))}")
    if a.get("dunyada_ilk_ifadesi"):
        satir.append(f"İfade: “{e(a['dunyada_ilk_ifadesi'])}”")
    if a.get("etiket"):
        satir.append(f"Sitede: {e(a['etiket'])}")
    if a.get("neden"):
        satir.append(f"Not: {e(a['neden'])}")
    kaynak = ", ".join(f"<a href=\"{e(k['adres'])}\">{e(alan_adi(k['adres']))}</a>" for k in a["kaynaklar"][:3]) or "yok"
    return (f"<div class=\"kart\">{g}<div class=\"ad\">{e(a['ad'])}</div>"
            f"<div><span class=\"rozet {GUVEN_SINIF[a['guven']]}\">{e(a['guven'])}</span> "
            f"<span class=\"kucuk\">{e(kt_metni(a))}</span></div>"
            f"{'<div class=acik>' + e(a.get('aciklama')) + '</div>' if a.get('aciklama') else ''}"
            f"<div class=\"bilgi\">{'<br>'.join(satir)}</div>"
            f"<div class=\"kucuk\">Kaynak: {kaynak}{' · Görsel: ' + e(a.get('gorsel_kaynagi')) if a.get('gorsel') else ''}</div></div>")


def gruplu(liste):
    g = {}
    for a in liste:
        g.setdefault(a["marka"], {}).setdefault(a["ulke"], []).append(a)
    return g


def pdf_html_yaz(katmanlar, siteler, zaman):
    kok = OUT.resolve()
    markalar = sorted({s["marka"] for s in siteler})
    ozet_satir = "".join(
        f"<tr><td>{e(m)}</td>" + "".join(f"<td class=s>{sum(1 for a in katmanlar[k] if a['marka'] == m)}</td>" for k, _ in KATMAN) + "</tr>"
        for m in markalar)
    toplam = "".join(f"<td class=s><b>{len(katmanlar[k])}</b></td>" for k, _ in KATMAN)
    acik = sum(1 for s in siteler if s["durum"] == "OK")
    parca = [f"""<section class="kapak"><div class="alt">GLOBAL YENİ ÜRÜNLER</div>
<h1>{DONEM_BAS.strftime('%d.%m.%Y')} – {BUGUN.strftime('%d.%m.%Y')}</h1>
<div class="alt">{len(markalar)} marka · {len(siteler)} marka x ülke · Oluşturma: {e(zaman)}</div>
<table class="ozet"><thead><tr><th>Marka</th>{''.join(f'<th>{ad}</th>' for _, ad in KATMAN)}</tr></thead>
<tbody>{ozet_satir}<tr><td><b>Toplam</b></td>{toplam}</tr></tbody></table>
<div class="aciklama"><b>Nasıl okunur?</b> <span class="rozet g1">Doğrulandı</span> ürünü adıyla anan bir kaynak var; çıkış
tarihi ve (Dünyada İlk için) markanın ya da haberin “ilk / özel” ifadesi bulundu.
<span class="rozet g2">Muhtemelen</span> kaynak var ama bir bilgi eksik. <span class="rozet g3">Doğrulanamadı</span> kaynak
bulunamadı. Kaynaksız ürün hiçbir zaman Dünyada İlk ya da Ülkede İlk bölümüne girmez.<br><br>
Ürünler iki yoldan bulunur: resmi sitenin ana sayfasındaki “yeni” bannerları ({acik} ülkede site açıldı) ve Google
araması. Görseller resmi sitedeki bannerdan kırpılır ya da kaynak haber sayfasından alınır.</div></section>"""]

    notlar = {
        "dunya": "Bu ülkede dönem içinde çıkan ve başka ülkede daha önce satıldığına dair kayıt bulunmayan ürünler.",
        "ulke": "Bu ülkede dönem içinde ilk kez çıkan, ama daha önce başka ülkelerde satılmış ürünler.",
        "belirsiz": "Yeni olabilecek ama kaynakla yeterince doğrulanamayan ürünler. Göz atılması önerilir.",
    }
    for k, ad in KATMAN[:3]:
        liste = katmanlar[k]
        parca.append(f"<section class=\"bolum\"><h2>{ad} ({len(liste)})</h2><p class=\"bolum-not\">{notlar[k]}</p>")
        if not liste:
            parca.append("<p>Kayıt yok.</p>")
        for marka, ulkeler in gruplu(liste).items():
            for ulke, urunler in ulkeler.items():
                parca.append(f"<h3>{e(marka)} — {e(ulke)}</h3><div class=\"izgara\">"
                             + "".join(pdf_kart(a, kok) for a in urunler) + "</div>")
        parca.append("</section>")

    el = katmanlar["elenen"]
    parca.append(f"<section class=\"bolum\"><h2>Elenenler ({len(el)})</h2>"
                 "<p class=\"bolum-not\">Markanın öne çıkardığı ama yeni olmayan ürünler: geri dönenler, dönemden önce "
                 "çıkanlar, daha önce arşivde görülenler.</p><table class=\"liste\"><thead><tr><th>Marka</th><th>Ülke</th>"
                 "<th>Ürün</th><th>Neden</th><th>Kaynak</th></tr></thead><tbody>"
                 + "".join(f"<tr><td>{e(a['marka'])}</td><td>{e(a['ulke'])}</td><td>{e(a['ad'])}</td><td>{e(a.get('neden'))}</td>"
                           f"<td>{e(', '.join(alan_adi(k['adres']) for k in a['kaynaklar'][:2]) or '-')}</td></tr>" for a in el)
                 + "</tbody></table></section>")
    parca.append("<section class=\"bolum\"><h2>Ek: Taranan marka x ülke</h2><table class=\"liste\"><thead><tr><th>Marka</th>"
                 "<th>Ülke</th><th>Resmi site</th><th>Not</th></tr></thead><tbody>"
                 + "".join(f"<tr><td>{e(s['marka'])}</td><td>{e(s['ulke'])}</td><td>{e(s['durum'])}</td><td>{e(s['neden'])}</td></tr>"
                           for s in siteler) + "</tbody></table></section>")
    return (f"<!doctype html><html lang=\"tr\"><head><meta charset=\"utf-8\"><title>Global Yeni Ürünler</title>"
            f"<style>{PDF_CSS}</style></head><body>{''.join(parca)}</body></html>")


def pdf_yaz(katmanlar, siteler, zaman, browser):
    kaynak = OUT / "_pdf.html"
    kaynak.write_text(pdf_html_yaz(katmanlar, siteler, zaman), encoding="utf-8")
    page = browser.new_page()
    page.goto(kaynak.resolve().as_uri(), wait_until="load", timeout=180000)
    page.pdf(path=str(OUT / "rapor.pdf"), format="A4", print_background=True, display_header_footer=True,
             header_template="<span></span>",
             footer_template=("<div style=\"font-size:7pt;color:#888;width:100%;padding:0 12mm;display:flex;"
                              "justify-content:space-between\"><span>Global Yeni Ürünler · "
                              f"{DONEM_BAS.strftime('%d.%m.%Y')} – {BUGUN.strftime('%d.%m.%Y')}</span>"
                              "<span><span class=\"pageNumber\"></span> / <span class=\"totalPages\"></span></span></div>"),
             margin={"top": "14mm", "bottom": "16mm", "left": "12mm", "right": "12mm"})
    page.close()
    kaynak.unlink(missing_ok=True)


# ---------------------------------- Excel / CSV ---------------------------------------
BASLIK = ["Marka", "Ülke", "Ürün", "Açıklama", "Fiyat", "Sitedeki ifade", "Güven", "Bu ülkede ilk çıkış",
          "Başka ülkelerde önceden", "'Dünyada ilk' ifadesi", "Not / elenme nedeni", "Kanıt özeti", "Bulunduğu yer",
          "Kaynak bağlantıları", "Görsel dosyası", "Ekran dosyası", "Site adresi"]


def satir_duz(a):
    return [
        a["marka"], a["ulke"], a["ad"], a.get("aciklama", ""), a.get("fiyat", ""), a.get("etiket", ""), a["guven"],
        a.get("ulkede_ilk_cikis", ""), baska_metni(a), a.get("dunyada_ilk_ifadesi", ""), a.get("neden", ""),
        a.get("kanit", ""), kt_metni(a), "\n".join(k["adres"] for k in a["kaynaklar"]), a.get("gorsel", ""),
        a.get("ekran", ""), a.get("site_adresi", ""),
    ]


def excel_yaz(katmanlar, siteler):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        return False
    wb = Workbook()
    wb.remove(wb.active)
    for k, ad in KATMAN:
        ws = wb.create_sheet(ad[:31])
        ws.append(BASLIK)
        for a in katmanlar[k]:
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
    for col in ws.columns:
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


def tarayici_ac(p):
    kw = {"headless": True}
    if os.environ.get("CHROMIUM_PATH"):
        kw.update(executable_path=os.environ["CHROMIUM_PATH"], args=["--no-sandbox"])
    return p.chromium.launch(**kw)


def main():
    if not API_KEY and not os.environ.get("RADAR_TEST"):
        print("HATA: GEMINI_API_KEY tanımlı değil. GitHub > Settings > Secrets and variables > Actions bölümüne ekleyin.")
        return 2
    from playwright.sync_api import sync_playwright
    for d in (OUT, SHOTS, GORSEL):
        d.mkdir(parents=True, exist_ok=True)
    zaman = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    sites = [s for s in SITES if not ONLY or s[1] in ONLY]
    print(f"Dönem: {DONEM_BAS} - {BUGUN} ({GUN} gün), {len(sites)} marka x ülke", flush=True)
    hatalar = []

    with sync_playwright() as p:
        br = tarayici_ac(p)

        # 1) Siteler
        siteler = []
        for i, (kod, marka, ulke, url, dil) in enumerate(sites, 1):
            if not url or SADECE_ARAMA:
                siteler.append({"kod": kod, "marka": marka, "ulke": ulke, "adres": url,
                                "durum": "ADRES YOK" if not url else "ATLANDI",
                                "neden": "Yalnızca arama ile taranır", "ekranlar": []})
                continue
            s = tara_site(br, kod, marka, ulke, url, dil)
            siteler.append(s)
            print(f"  site [{i}/{len(sites)}] {marka}/{ulke}: {s['durum']} {s['neden']}", flush=True)

        # 2) Görüntü okuma
        adaylar = []
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
            a["arsiv_kaydi"] = arsivde_bul(arsiv, a["marka"], a["ulke"], a["ad"])
        print(f"Birleşik aday: {len(adaylar)}", flush=True)
        # Arşivde dönemden önce görülenleri doğrulamaya gerek yok
        on_elenen = [a for a in adaylar if a["arsiv_kaydi"] and a["arsiv_kaydi"]["ilk_gorulme"] < DONEM_BAS.isoformat()]
        adaylar = [a for a in adaylar if a not in on_elenen]
        atlanan = []
        if len(adaylar) > MAX_ADAY:
            adaylar.sort(key=lambda a: (-len(a["kaynak_turu"]), "site" not in a["kaynak_turu"]))
            hatalar.append(f"{len(adaylar) - MAX_ADAY} aday sınır nedeniyle doğrulanmadı (MAX_ADAY={MAX_ADAY})")
            atlanan, adaylar = adaylar[MAX_ADAY:], adaylar[:MAX_ADAY]

        # 5) Doğrulama
        print(f"Doğrulama: {len(adaylar)} aday", flush=True)
        with ThreadPoolExecutor(PARALEL) as ex:
            sonuclar = list(ex.map(lambda a: guvenli(dogrula, a), adaylar))
        for a, (sonuc, hata) in zip(adaylar, sonuclar):
            if hata:
                hatalar.append(f"doğrulama {a['marka']}/{a['ulke']}/{a['ad']}: {hata}")
                a["dogrulama"], a["kaynaklar_dogrulama"] = {}, []
            else:
                a.update(sonuc)
            sinif_ver(a)
        for a in on_elenen + atlanan:
            a["dogrulama"], a["kaynaklar_dogrulama"] = None, []
            sinif_ver(a)
        for a in atlanan:
            a.update(sinif="belirsiz", guven="Doğrulanamadı", neden="Doğrulama sınırı nedeniyle kontrol edilmedi")
        tum = adaylar + on_elenen + atlanan

        # 6) Görseller (elenenler hariç)
        gosterilecek = [a for a in tum if a["sinif"] != "elenen"]
        print(f"Görseller: {len(gosterilecek)} ürün", flush=True)
        with ThreadPoolExecutor(8) as ex:
            for a, (sonuc, hata) in zip(gosterilecek, ex.map(lambda a: guvenli(gorsel_bul, a), gosterilecek)):
                a["gorsel"], a["gorsel_kaynagi"] = sonuc if sonuc else ("", "")

        # 7) Arşivi güncelle
        bugun = BUGUN.isoformat()
        for a in tum:
            k = a.get("arsiv_kaydi")
            if k:
                k["son_gorulme"] = bugun
            else:
                arsiv.setdefault("urunler", []).append({
                    "marka": a["marka"], "ulke": a["ulke"], "ad": a["ad"], "slug": a["_slug"],
                    "ilk_gorulme": bugun, "son_gorulme": bugun, "sinif": a["sinif"]})
        ARSIV.parent.mkdir(parents=True, exist_ok=True)
        ARSIV.write_text(json.dumps(arsiv, ensure_ascii=False, indent=1), encoding="utf-8")

        # 8) Raporlar
        sira = {"Doğrulandı": 0, "Muhtemelen": 1, "Doğrulanamadı": 2}
        katmanlar = {k: sorted([a for a in tum if a["sinif"] == k],
                               key=lambda a: (a["marka"], a["ulke"], sira[a["guven"]], a["ad"])) for k, _ in KATMAN}
        acik_n = len(acik)
        ist = (" · ".join(f"{ad}: {len(katmanlar[k])}" for k, ad in KATMAN)
               + f" · {len(siteler)} marka x ülke, resmi sitesi açılan {acik_n}")
        (OUT / "rapor.html").write_text(html_yaz(katmanlar, siteler, zaman, ist), encoding="utf-8")
        for k, ad in (("dunya", "dunyada_ilk"), ("ulke", "ulkede_ilk"), ("belirsiz", "belirsiz"), ("elenen", "elenenler")):
            csv_yaz(f"{ad}.csv", katmanlar[k])
        excel_yaz(katmanlar, siteler)
        try:
            pdf_yaz(katmanlar, siteler, zaman, br)
        except Exception as ex:  # noqa: BLE001
            hatalar.append(f"PDF oluşturulamadı: {type(ex).__name__}: {str(ex)[:200]}")
        br.close()

    (OUT / "hatalar.txt").write_text("\n".join(hatalar) or "Hata yok.", encoding="utf-8")
    if os.environ.get("EKRAN_KOPYALA") == "1":
        import shutil
        shutil.rmtree(SON_EKRAN, ignore_errors=True)
        shutil.copytree(SHOTS, SON_EKRAN)

    tum_n = sum(len(v) for v in katmanlar.values())
    ozet = (f"## Yeni Ürün Radarı\nDönem: {DONEM_BAS} – {BUGUN}\n\n| Katman | Adet | Doğrulandı | Muhtemelen | Doğrulanamadı |\n"
            "|---|---|---|---|---|\n"
            + "".join(f"| {ad} | {len(katmanlar[k])} | " + " | ".join(
                str(sum(1 for a in katmanlar[k] if a['guven'] == g)) for g in ("Doğrulandı", "Muhtemelen", "Doğrulanamadı")) + " |\n"
                for k, ad in KATMAN)
            + f"\nToplam aday: {tum_n} · Resmi sitesi açılan: {acik_n}/{len(siteler)} · "
              f"Görseli olan: {sum(1 for a in tum if a.get('gorsel'))} · Hata/uyarı: {len(hatalar)} · "
              f"Aramalı Gemini çağrısı: {_arama_sayaci['n']}\n")
    if hatalar:
        ozet += "\n<details><summary>Hata/uyarılar</summary>\n\n" + "\n".join(f"- {h}" for h in hatalar[:40]) + "\n</details>\n"
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(ozet)
    print(ozet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
