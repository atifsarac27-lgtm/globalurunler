#!/usr/bin/env python3
"""
YENİ ÜRÜN RADARI - ERİŞİM DENEMESİ (BASIN ODALARI)

Amaç: GitHub'ın sunucularından resmi marka sitelerine ulaşılabiliyor mu,
ana sayfadaki bannerlar ekran görüntüsü olarak alınabiliyor mu?

- API anahtarı gerekmez.
- Her site için iki ekran görüntüsü alır (kaydırmalı bannerların değiştiğini görmek için).
- Bir site erişimi engellerse (captcha, "Access Denied" vb.) engeli aşmaya ÇALIŞMAZ,
  sadece "ENGELLİ" olarak raporlar. Denemenin amacı tam olarak bunu ölçmek.

Çıktılar (sonuc/ klasörü):
  ozet.md                  okunabilir özet tablo
  sonuclar.csv / .json     ayrıntılı sonuçlar
  ekran_goruntuleri/       her site için 2 PNG
"""
import csv
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

OUT = Path(os.environ.get("OUT_DIR", "sonuc"))
SHOTS = OUT / "ekran_goruntuleri"

# Sıradan bir masaüstü Chrome kimliği. Engel aşma amaçlı başka hiçbir ayar yok.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# (kod, marka, ülke, adres, tarayıcı dili)
# Adresler en iyi tahminimizdir; açılmayan bir adres "HATA" olarak görünür, bu da denemenin bir parçası.
SITES = [
    # Subway resmi haber odaları (bölgesel)
    ("subnews-us", "Subway", "ABD / Kanada (haber odası)", "https://newsroom.subway.com/", "en-US"),
    ("subnews-emea", "Subway", "Avrupa-Orta Doğu-Afrika (haber odası)", "https://emea.newsroom.subway.com/", "en-GB"),
    ("subnews-apac", "Subway", "Asya-Pasifik (haber odası)", "https://apac.newsroom.subway.com/", "en-AU"),
    ("subnews-lac", "Subway", "Latin Amerika (haber odası)", "https://lac.newsroom.subway.com/", "es-MX"),
    ("subnews-reg", "Subway", "Bölgesel (haber odası)", "https://regional.newsroom.subway.com/", "en-GB"),
    # KFC resmi basın odaları
    ("kfcnews-global", "KFC", "Global / ABD (basın odası)", "https://global.kfc.com/press-releases", "en-US"),
    ("kfcnews-es", "KFC", "İspanya (basın odası)", "https://prensa.kfc.es/", "es-ES"),
    # McDonald's ülke haber odaları (mcdonalds.com altında)
    ("mcdnews-us", "McDonald's", "ABD (haber odası)", "https://www.mcdonalds.com/us/en-us/newsroom.html", "en-US"),
    ("mcdnews-gb", "McDonald's", "Birleşik Krallık (haber odası)", "https://www.mcdonalds.com/gb/en-gb/newsroom.html", "en-GB"),
    ("mcdnews-ca", "McDonald's", "Kanada (haber odası)", "https://www.mcdonalds.com/ca/en-ca/newsroom.html", "en-CA"),
    ("mcdnews-au", "McDonald's", "Avustralya (haber odası)", "https://www.mcdonalds.com/au/en-au/newsroom.html", "en-AU"),
    ("mcdnews-de", "McDonald's", "Almanya (haber odası)", "https://www.mcdonalds.com/de/de-de/newsroom.html", "de-DE"),
    ("mcdnews-fr", "McDonald's", "Fransa (haber odası)", "https://www.mcdonalds.com/fr/fr-fr/newsroom.html", "fr-FR"),
    ("mcdnews-es", "McDonald's", "İspanya (haber odası)", "https://www.mcdonalds.com/es/es-es/newsroom.html", "es-ES"),
    ("mcdnews-tr", "McDonald's", "Türkiye (haber odası)", "https://www.mcdonalds.com/tr/tr-tr/newsroom.html", "tr-TR"),
    ("mcdnews-corp", "McDonald's", "Kurumsal (corporate.mcdonalds.com)", "https://corporate.mcdonalds.com/corpmcd/en-us/our-stories.html", "en-US"),
    ("mcdnews-news", "McDonald's", "news.mcdonalds.com", "https://news.mcdonalds.com/", "en-US"),
]

# Çerez penceresini kapatmak için sıradan bir ziyaretçinin basacağı düğmeler
COOKIE_SELECTORS = [
    "#onetrust-accept-btn-handler",
    "button:has-text('Accept all')", "button:has-text('Accept All')", "button:has-text('Accept')",
    "button:has-text('Aceptar')", "button:has-text('Akzeptieren')", "button:has-text('Alle akzeptieren')",
    "button:has-text('Aceitar')", "button:has-text('Kabul')", "button:has-text('Tümünü kabul')",
    "button:has-text('Zaakceptuj')", "button:has-text('Souhlasím')", "button:has-text('Akkoord')",
    "button:has-text('同意')", "button:has-text('承諾')", "button:has-text('동의')",
]

# Engel / doğrulama sayfası belirtileri
BLOCK_RE = re.compile(
    r"access denied|request blocked|attention required|just a moment|checking your browser|"
    r"verify you are (a )?human|are you a robot|captcha|unusual traffic|pardon our interruption|"
    r"you have been blocked|erişim engellendi|zugriff verweigert|acceso denegado|"
    r"enable javascript and cookies|errors\.edgesuite\.net|incapsula incident|px-captcha",
    re.I,
)

# "Yeni" anlamına gelen sözcükler (Latin harfli diller için sözcük sınırıyla)
NEW_LATIN_RE = re.compile(
    r"\b(new|nuevo|nueva|nuevos|nuevas|nouveau|nouveaux|nouvelle|neu|nieuw|nuovo|nuova|nuovi|novo|nova|novos|"
    r"novidade|novinka|novinky|nowo[sś][cć]|nowy|nowa|nowe|yeni|novi|nov[aeiy]|ново|новинка|новый)\b",
    re.I,
)
AY = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Ene|Abr|Ago|Dic|Mär|Mai|Okt|Dez|Oca|Şub|Nis|Haz|Tem|Eyl|Eki|Kas|Ara)[a-zçğıöşü]*\.?"
DATE_RE = re.compile(
    r"\b(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]20\d{2}|" + AY + r"\s+\d{1,2},?\s+20\d{2}|\d{1,2}\.?\s+" + AY + r"\s+20\d{2})",
    re.I,
)
NEW_CJK_RE = re.compile(r"新発売|新登場|新商品|新メニュー|新品|新登场|신메뉴|신제품|新")


def runner_info():
    """Denemenin hangi ülkeden/hangi IP'den çalıştığını kaydeder."""
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        return f"{d.get('country', '?')} / {d.get('region', '')} / {d.get('org', '')}"
    except Exception as e:  # noqa: BLE001
        return f"bilinmiyor ({type(e).__name__})"


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


def siniflandir(status, baslik, metin):
    """(durum, neden) döndürür. Durumlar: OK, ENGELLİ, BOŞ"""
    kisa = len(metin) < 3000
    if status in (401, 403, 429):
        return "ENGELLİ", f"HTTP {status}"
    if BLOCK_RE.search(baslik or "") or (kisa and BLOCK_RE.search(metin or "")):
        return "ENGELLİ", "Doğrulama / erişim engeli sayfası"
    if status and status >= 500:
        return "HATA", f"HTTP {status}"
    if status and status >= 400:
        return "HATA", f"HTTP {status}"
    if len(metin.strip()) < 200:
        return "BOŞ", "Sayfada neredeyse hiç metin yok (yüklenmemiş ya da yalnızca görsel olabilir)"
    return "OK", ""


def tara(browser, kod, marka, ulke, url, dil):
    r = {
        "kod": kod, "marka": marka, "ulke": ulke, "adres": url, "son_adres": "", "http": "",
        "durum": "HATA", "neden": "", "baslik": "", "metin_uzunlugu": 0,
        "yeni_kelime": 0, "buyuk_gorsel": 0, "alt_metin": 0, "sure_sn": 0,
        "ekran1": "", "ekran2": "", "ulke_degisti": "",
        "tarih_sayisi": 0, "baglanti_sayisi": 0, "haber_basliklari": [],
    }
    t0 = time.time()
    ctx = browser.new_context(viewport={"width": 1440, "height": 1600}, locale=dil, user_agent=UA)
    page = ctx.new_page()
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=40000)
        r["http"] = resp.status if resp else ""
        page.wait_for_timeout(5000)
        cerez_kapat(page)
        page.wait_for_timeout(1500)
        try:
            page.evaluate("window.scrollTo(0, 0)")
        except Exception:  # noqa: BLE001
            pass

        f1 = SHOTS / f"{kod}_1.png"
        page.screenshot(path=str(f1))
        r["ekran1"] = f1.name
        page.wait_for_timeout(6000)  # kaydırmalı bannerın değişmesi için
        f2 = SHOTS / f"{kod}_2.png"
        page.screenshot(path=str(f2))
        r["ekran2"] = f2.name

        r["son_adres"] = page.url
        r["baslik"] = (page.title() or "")[:120]
        metin = page.evaluate("document.body ? document.body.innerText : ''") or ""
        alts = page.eval_on_selector_all("img[alt]", "els => els.map(e => e.alt).filter(Boolean)") or []
        r["metin_uzunlugu"] = len(metin)
        r["alt_metin"] = len(alts)
        tum = metin + "\n" + "\n".join(alts)
        r["yeni_kelime"] = len(NEW_LATIN_RE.findall(tum)) + len(NEW_CJK_RE.findall(tum))
        r["buyuk_gorsel"] = page.evaluate(
            "Array.from(document.images).filter(i => i.naturalWidth >= 600).length"
        )
        # Basın odası içeriği: uzun bağlantı metinleri (haber başlığı olabilir) ve tarih sayısı
        try:
            baglar = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => [(e.innerText||'').trim().replace(/\\s+/g,' '), e.href])",
            ) or []
        except Exception:  # noqa: BLE001
            baglar = []
        r["baglanti_sayisi"] = len(baglar)
        gor = set()
        for t, h in baglar:
            if 25 <= len(t) <= 220 and t not in gor:
                gor.add(t)
                r["haber_basliklari"].append({"baslik": t, "adres": h})
            if len(r["haber_basliklari"]) >= 25:
                break
        adres_tarih = sum(1 for _, h in baglar if re.search(r"/20\d{2}[-/]\d{1,2}[-/]\d{1,2}", h or ""))
        r["tarih_sayisi"] = len(DATE_RE.findall(metin)) + adres_tarih
        durum, neden = siniflandir(r["http"] if isinstance(r["http"], int) else None, r["baslik"], metin)
        r["durum"], r["neden"] = durum, neden

        a, b = urlparse(url), urlparse(r["son_adres"])
        ilk = a.netloc.replace("www.", "") + a.path.rstrip("/")
        son = b.netloc.replace("www.", "") + b.path.rstrip("/")
        if ilk != son:
            r["ulke_degisti"] = f"yönlendirildi: {b.netloc}{b.path}"[:120]
    except Exception as e:  # noqa: BLE001
        ad = type(e).__name__
        mesaj = str(e).splitlines()[0][:160] if str(e) else ""
        r["durum"] = "HATA"
        r["neden"] = f"{ad}: {mesaj}"
        # Hata anında da bir görüntü almayı dene
        try:
            f1 = SHOTS / f"{kod}_hata.png"
            page.screenshot(path=str(f1))
            r["ekran1"] = f1.name
        except Exception:  # noqa: BLE001
            pass
    finally:
        r["sure_sn"] = round(time.time() - t0, 1)
        ctx.close()
    return r


def ozet_yaz(sonuclar, runner, basla):
    n = len(sonuclar)
    ok = [s for s in sonuclar if s["durum"] == "OK"]
    L = []
    L.append("# Yeni Ürün Radarı - Erişim Denemesi\n")
    L.append(f"- Çalışma zamanı: {basla}")
    L.append(f"- Denemenin çalıştığı sunucu (ülke / bölge / ağ): **{runner}**")
    L.append(f"- Toplam site: **{n}**, sorunsuz açılan: **{len(ok)}** (%{round(100 * len(ok) / n) if n else 0})\n")

    L.append("## Markaya göre\n")
    L.append("| Marka | Site | Sorunsuz | Engelli | Boş | Hata |")
    L.append("|---|---|---|---|---|---|")
    for m in dict.fromkeys(s["marka"] for s in sonuclar):
        g = [s for s in sonuclar if s["marka"] == m]
        c = lambda d: sum(1 for s in g if s["durum"] == d)  # noqa: E731
        L.append(f"| {m} | {len(g)} | {c('OK')} | {c('ENGELLİ')} | {c('BOŞ')} | {c('HATA')} |")

    L.append("\n## Tüm siteler\n")
    L.append("| Marka | Ülke | Durum | Not | 'Yeni' sözcüğü | Büyük görsel | Süre (sn) |")
    L.append("|---|---|---|---|---|---|---|")
    for s in sonuclar:
        not_ = s["neden"] or s["ulke_degisti"] or ""
        L.append(f"| {s['marka']} | {s['ulke']} | **{s['durum']}** | {not_} | {s['yeni_kelime']} | {s['buyuk_gorsel']} | {s['sure_sn']} |")

    L.append("\n## Basın odası içeriği (sayfada görülen ilk başlıklar)\n")
    for s in sonuclar:
        if s["durum"] != "OK":
            continue
        L.append(f"### {s['marka']} - {s['ulke']}  (tarih sayısı: {s['tarih_sayisi']}, bağlantı: {s['baglanti_sayisi']})")
        L.append(f"Adres: {s['son_adres'] or s['adres']}\n")
        for h in s["haber_basliklari"][:10]:
            L.append(f"- {h['baslik']}  <{h['adres']}>")
        L.append("")

    L.append("\n## Nasıl okunur?\n")
    L.append("- **OK**: Sayfa açıldı ve ekran görüntüsü alındı. Görüntülerin gerçekten banner içerip içermediğine ekran görüntülerinden bakılmalı.")
    L.append("- **ENGELLİ**: Site otomatik tarayıcıyı engelledi (captcha / Access Denied). Engeli aşmaya çalışılmadı.")
    L.append("- **BOŞ**: Sayfa açıldı ama neredeyse hiç metin yok. Genellikle sayfa tam yüklenmemiştir ya da içerik yalnızca görseldir.")
    L.append("- **HATA**: Adres açılmadı (zaman aşımı, adres yanlış, sunucu hatası).")
    L.append("- **'Yeni' sözcüğü** ve **büyük görsel** sayıları, bannerların metin olarak mı yoksa yalnızca resim olarak mı geldiğini anlamak içindir. Büyük görsel çok, 'yeni' sözcüğü sıfırsa bannerlar resim içine gömülüdür; bunlar görüntü okuma (Gemini) ile okunur.")
    return "\n".join(L) + "\n"


def main():
    sites = SITES
    if os.environ.get("SITES_FILE"):
        sites = [tuple(x) for x in json.loads(Path(os.environ["SITES_FILE"]).read_text(encoding="utf-8"))]

    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    basla = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    runner = runner_info()
    print(f"Sunucu: {runner}", flush=True)

    sonuclar = []
    with sync_playwright() as p:
        kw = {"headless": True}
        if os.environ.get("CHROMIUM_PATH"):
            kw["executable_path"] = os.environ["CHROMIUM_PATH"]
            kw["args"] = ["--no-sandbox"]
        browser = p.chromium.launch(**kw)
        for i, (kod, marka, ulke, url, dil) in enumerate(sites, 1):
            print(f"[{i}/{len(sites)}] {marka} / {ulke} ... ", end="", flush=True)
            s = tara(browser, kod, marka, ulke, url, dil)
            sonuclar.append(s)
            print(f"{s['durum']} {s['neden']}", flush=True)
        browser.close()

    alanlar = list(sonuclar[0].keys()) if sonuclar else []
    with open(OUT / "sonuclar.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=alanlar, delimiter=";")
        w.writeheader()
        w.writerows([{k: (json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v) for k, v in s.items()} for s in sonuclar])
    (OUT / "sonuclar.json").write_text(json.dumps(sonuclar, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ozet_yaz(sonuclar, runner, basla)
    (OUT / "ozet.md").write_text(md, encoding="utf-8")
    ozet_dosyasi = os.environ.get("GITHUB_STEP_SUMMARY")
    if ozet_dosyasi:
        with open(ozet_dosyasi, "a", encoding="utf-8") as f:
            f.write(md)
    print("\nBitti. Sonuçlar:", OUT.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
