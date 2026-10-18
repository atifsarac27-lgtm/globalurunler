"""Kaynak zinciri: yeni ürün adaylarını sırayla farklı kaynaklardan dener.

Sıra (bir kaynak aday bulamazsa bir sonrakine geçilir):
  1. Resmi site      : ana sayfadaki "yeni / new / launch" bağlantıları
  2. Basın odası     : ana sayfadaki basın bağlantısı -> oradaki marka/yeni bağlantıları
  3. Haber RSS       : Google Haberler, son 60 gündeki marka haberleri

Arşiv (Wayback) yalnızca tanı amaçlıdır: site son 60 gün arşivde var mıydı.
Standart kütüphane kullanır. Her marka-ülke için denenen kaynakların sonucu
ve nedeni kaydedilir.

Kullanım:
    python3 kaynak_zinciri.py --veri arsiv/son-veri.json --cikti kaynak_sonuc.json
    python3 kaynak_zinciri.py --veri arsiv/son-veri.json --limit 20
"""
import argparse
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

UA = "Mozilla/5.0 (compatible; GlobalUrunRadar/1.0)"
ZAMAN_ASIMI = 20
GERIYE_GUN = 60
SBARRO_GERIYE_GUN = 180  # Sbarro'da 2 ürün bulunana kadar en fazla bu kadar geriye bakılır


def geriye_gun(marka):
    return SBARRO_GERIYE_GUN if marka == "Sbarro" else GERIYE_GUN
BASIN_IPUCU = ("press", "newsroom", "basin", "basın", "medya", "media", "haber", "news")
# Kelime sınırlı eşleşme: "news", "newsroom" gibi menü linkleri "new" sayılmasın diye.
YENI_RE = re.compile(r"\b(?:new|yeni|launch\w*|introduc\w*|debut\w*)\b|신메뉴|신제품|新品", re.I)
# Haber başlığında gerçek ürün/menü kelimesi aranır (Subway metrosu gibi haberleri elemek için).
URUN_RE = re.compile(
    r"\b(?:launch\w*|introduc\w*|debut\w*|limited|menu|nuggets?|chicken|burgers?|sandwich\w*|"
    r"flavou?rs?|wraps?|fries|dips?|sauces?|items?|bundles?|combos?|bites?|drinks?|desserts?|"
    r"coffee|biscuits?|pizza|meals?|snacks?)\b", re.I)
# Kampanya, mağaza açılışı, fiyat ve finans haberleri ürün değildir; bunları eler.
KAMPANYA_RE = re.compile(
    r"\b(?:opens?|opening|opened|reopens?|stores?|restaurants?|drive[- ]?thru|outlets?|branch(?:es)?|"
    r"franchises?|jobs?|hiring|celebrat\w*|anniversary|years?|free|giveaway\w*|deals?|value|"
    r"açıl\w*|kampanya\w*|indirim\w*|promosyon\w*|promotions?|promo|"
    r"sweepstakes|contest|stocks?|shares?|investors?|earnings|revenue|profits?|valuation|game|"
    r"crossover|charity|reviews?|tried|tasted|lawsuit|sued|campaign)\b|[£$€]", re.I)
GEZINME_TAM = {"news", "news & press", "newsroom", "more", "see more", "home", "homepage",
               "contact", "detay", "detaylı", "daha fazla"}
GEZINME_ICERIK = ("anasayfa", "ana sayfa", "hikayesi", "newsletter", "iletişim",
                  "read more", "términos", "terms and conditions", "dokümanı", "promociones",
                  "what’s new", "what's new")


class Baglantilar(HTMLParser):
    """Sayfadaki (href, metin) çiftlerini toplar."""

    def __init__(self):
        super().__init__()
        self.liste = []
        self._href = None
        self._parca = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._parca = []

    def handle_data(self, veri):
        if self._href is not None:
            self._parca.append(veri)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.liste.append((self._href, " ".join(" ".join(self._parca).split())))
            self._href = None


def indir(url):
    """(True, metin) veya (False, neden)."""
    try:
        istek = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI) as yanit:
            return True, yanit.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}"


def gezinme_mi(metin):
    """Menü/gezinme bağlantısı mı (ürün değil)."""
    m = metin.strip().lower()
    return m in GEZINME_TAM or any(k in m for k in GEZINME_ICERIK)


def aday_bul(sayfa, taban, marka=None):
    """Sayfada yeni-ürün ipucu ya da marka adı taşıyan bağlantılar."""
    ayristirici = Baglantilar()
    ayristirici.feed(sayfa)
    adaylar = []
    for href, metin in ayristirici.liste:
        if not metin or gezinme_mi(metin):
            continue
        marka_var = marka is not None and marka.lower() in metin.lower()
        if KAMPANYA_RE.search(metin):
            continue  # kampanya/mağaza/fiyat bağlantısı ürün değil
        if marka_var or YENI_RE.search(metin) or YENI_RE.search(href):
            adaylar.append({"metin": metin[:120], "url": urllib.parse.urljoin(taban, href)})
    return adaylar


def ana_sayfa(site, ctx):
    """Ana sayfayı bir kez çeker, sonucu katmanlar arasında paylaşır."""
    if "ana_sayfa" not in ctx:
        ctx["ana_sayfa"] = indir(site["adres"])
    return ctx["ana_sayfa"]


def katman_resmi(site, ctx):
    if not site["adres"]:
        return "yok", "adres tanımsız", []
    ok, veri = ana_sayfa(site, ctx)
    if not ok:
        return "hata", veri, []
    adaylar = aday_bul(veri, site["adres"])
    if adaylar:
        return "ok", "", adaylar
    return "yok", "ana sayfada yeni ürün bağlantısı yok", []


def katman_basin(site, ctx):
    if not site["adres"]:
        return "yok", "adres tanımsız", []
    ok, veri = ana_sayfa(site, ctx)
    if not ok:
        return "hata", f"ana sayfa açılamadı: {veri}", []
    ayristirici = Baglantilar()
    ayristirici.feed(veri)
    basin = [
        urllib.parse.urljoin(site["adres"], h)
        for h, m in ayristirici.liste
        if any(k in (h + " " + m).lower() for k in BASIN_IPUCU)
    ]
    if not basin:
        return "yok", "basın bağlantısı bulunamadı", []
    ok, sayfa = indir(basin[0])
    if not ok:
        return "hata", f"basın sayfası: {sayfa}", []
    adaylar = aday_bul(sayfa, basin[0])  # yalnızca "yeni" ipucu; marka adı yetmez (menü ürünleri yeni değil)
    if adaylar:
        return "ok", "", adaylar
    return "yok", "basın sayfasında marka ya da yeni bağlantısı yok", []


def rss_ogeleri(xml_metni, simdi=None, gun=None):
    """RSS'teki son `gun` günlük haber başlıkları (verilmezse GERIYE_GUN)."""
    simdi = simdi or datetime.now(timezone.utc)
    sinir = simdi - timedelta(days=gun or GERIYE_GUN)
    ogeler = []
    for item in ET.fromstring(xml_metni).iter("item"):
        baslik = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        try:
            tarih = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if tarih.tzinfo is None:
            tarih = tarih.replace(tzinfo=timezone.utc)
        if baslik and tarih >= sinir:
            ogeler.append({"metin": baslik[:160], "url": link, "tarih": tarih.date().isoformat()})
    return ogeler


def ulke_kodu(site):
    """Site kodundaki son ekten ülke kodu: bk-tr -> TR. Google Haberler için UK -> GB."""
    cc = site["kod"].rsplit("-", 1)[-1].upper()
    return {"UK": "GB"}.get(cc, cc)


# Yerel dilde haber araması: ülke kodu -> (hl, ceid, arama terimleri, başlık filtresi).
# Sonuçlar İngilizce aramaya EK olarak gelir; yerel arama başarısız olursa İngilizce sonuçlar kalır.
YEREL_ARAMA = {
    "TR": ("tr", "TR:tr", '(yeni OR lansman OR "yeni ürün" OR menü)',
           re.compile(r"yeni|lansman|menü|tanıt|sunu|ürün", re.I)),
    "MX": ("es-419", "MX:es-419", '(nuevo OR lanzamiento OR "nuevo producto" OR menú)',
           re.compile(r"nuev|lanza|menú|producto|sabor", re.I)),
    "BR": ("pt-419", "BR:pt-419", '(novo OR lançamento OR "novo produto" OR cardápio)',
           re.compile(r"novo|nova|lançament|cardápio|sabor", re.I)),
    "FR": ("fr", "FR:fr", '(nouveau OR nouvelle OR lancement OR "nouveau produit")',
           re.compile(r"nouveau|nouvelle|lancement|lance|menu|saveur", re.I)),
    "DE": ("de", "DE:de", '(neu OR neue OR Einführung OR "neues Produkt")',
           re.compile(r"neu|einführ|menü|geschmack", re.I)),
    "KR": ("ko", "KR:ko", "(신메뉴 OR 신제품 OR 출시)", re.compile(r"신메뉴|신제품|출시|론칭")),
    "JP": ("ja", "JP:ja", "(新商品 OR 新発売 OR 新メニュー)", re.compile(r"新商品|新発売|新メニュー|発売")),
    "CN": ("zh-CN", "CN:zh-Hans", "(新品 OR 上市 OR 新菜单)", re.compile(r"新品|上市|新菜单|推出")),
    "SA": ("ar", "SA:ar", "(جديد OR إطلاق)", re.compile(r"جديد|إطلاق|يطلق")),
    "AE": ("ar", "AE:ar", "(جديد OR إطلاق)", re.compile(r"جديد|إطلاق|يطلق")),
}


def haber_sorgula(marka, hl, gl, ceid, terimler, gun=None):
    """Google Haberler RSS'inde tek bir arama yapar. (öğeler, hata) döndürür; öğeler None ise hata var."""
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f'"{marka}" {terimler}', "hl": hl, "gl": gl, "ceid": ceid})
    ok, veri = indir(url)
    if not ok:
        return None, veri
    try:
        return rss_ogeleri(veri, gun=gun), ""
    except ET.ParseError as e:
        return None, f"RSS ayrıştırılamadı: {e}"


def haber_filtrele(ogeler, marka, yerel_uyum=None):
    """Markayı içeren, ürün kelimesi geçen ve kampanya olmayan başlıkları tutar."""
    return [o for o in ogeler
            if marka.lower() in o["metin"].lower()
            and (URUN_RE.search(o["metin"]) or (yerel_uyum and yerel_uyum.search(o["metin"])))
            and not KAMPANYA_RE.search(o["metin"])]


def katman_haber(site, ctx):
    cc = ulke_kodu(site)
    marka = site["marka"]
    # Ülkeye özel haber sonucu: aksi halde her ülke için ABD haberleri gelir.
    gun = geriye_gun(marka)
    ogeler, hata = haber_sorgula(marka, "en-US", cc, f"{cc}:en", "(new OR launch OR yeni)", gun)
    if ogeler is None:
        return "hata", hata, []
    ogeler = haber_filtrele(ogeler, marka)
    if cc in YEREL_ARAMA:
        hl, ceid, terimler, uyum = YEREL_ARAMA[cc]
        yerel, _ = haber_sorgula(marka, hl, cc, ceid, terimler, gun)
        if yerel:
            goruldu = {o["url"] for o in ogeler}
            ogeler += [o for o in haber_filtrele(yerel, marka, uyum) if o["url"] not in goruldu]
    if ogeler:
        return "ok", "", ogeler
    return "yok", f"son {gun} günde haber yok", []


KATMANLAR = [
    ("resmi site", katman_resmi),
    ("basın odası", katman_basin),
    ("haber RSS", katman_haber),
]


def tani_arsiv(site):
    if not site["adres"]:
        return "adres yok"
    alan = urllib.parse.urlparse(site["adres"]).netloc
    bas = (datetime.now(timezone.utc) - timedelta(days=GERIYE_GUN)).strftime("%Y%m%d")
    url = "https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(
        {"url": alan + "/*", "from": bas, "filter": "statuscode:200", "limit": 3, "output": "json"})
    ok, veri = indir(url)
    if not ok:
        return f"hata: {veri}"
    try:
        satirlar = json.loads(veri)
    except ValueError:
        return "hata: yanıt JSON değil"
    return f"{max(len(satirlar) - 1, 0)} kayıt"


def zincir(site):
    ctx = {}
    denemeler = []
    sonuc, adaylar = "hiçbiri", []
    for ad, katman in KATMANLAR:
        durum, ayrinti, bulunan = katman(site, ctx)
        denemeler.append({"katman": ad, "durum": durum, "ayrinti": ayrinti, "aday": len(bulunan)})
        if durum == "ok":
            sonuc, adaylar = ad, bulunan[:20]
            break
    return {
        "kod": site["kod"], "marka": site["marka"], "ulke": site["ulke"], "adres": site["adres"],
        "sonuc": sonuc, "adaylar": adaylar, "denemeler": denemeler,
        "arsiv": tani_arsiv(site),
    }


def tekillestir(sonuclar):
    """Aynı başlık birden fazla ülkede geçiyorsa ilk görüleni dışındakileri 'tekrar' işaretler."""
    gorulen = set()
    for s in sonuclar:
        for a in s["adaylar"]:
            anahtar = a["metin"].lower()
            a["tekrar"] = anahtar in gorulen
            gorulen.add(anahtar)


def ozet(sonuclar):
    print("Sonuç dağılımı:", dict(Counter(s["sonuc"] for s in sonuclar)))
    for s in sonuclar:
        zincir_metin = " → ".join(f"{d['katman']}:{d['durum']}" for d in s["denemeler"])
        print(f"{s['kod']:10s} {s['marka']:12s} {s['ulke']:18s} {s['sonuc']:12s} | {zincir_metin}")


def main():
    p = argparse.ArgumentParser(description="Yeni ürün kaynak zinciri")
    p.add_argument("--veri", default="arsiv/son-veri.json")
    p.add_argument("--cikti", default="kaynak_sonuc.json")
    p.add_argument("--limit", type=int, default=0, help="ilk N siteyi dene (0 = hepsi)")
    a = p.parse_args()

    with open(a.veri, encoding="utf-8") as f:
        siteler = json.load(f)["siteler"]
    if a.limit:
        siteler = siteler[:a.limit]

    with ThreadPoolExecutor(max_workers=8) as havuz:
        sonuclar = list(havuz.map(zincir, siteler))

    tekillestir(sonuclar)
    with open(a.cikti, "w", encoding="utf-8") as f:
        json.dump(sonuclar, f, ensure_ascii=False, indent=2)
    ozet(sonuclar)
    benzersiz = sum(1 for s in sonuclar for a in s["adaylar"] if not a["tekrar"])
    print(f"Benzersiz aday metni: {benzersiz}")


if __name__ == "__main__":
    main()
