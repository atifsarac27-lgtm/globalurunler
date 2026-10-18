"""Resmi site ve haber sonuçlarını tek PDF raporunda birleştirir.

Kullanım:
    python birlestir_pdf.py --veri rapor/veri.json --haber rapor/haber_urunleri.json --cikti rapor/birlesik_rapor.pdf

Kurallar:
- Her ürün kartında kaynak yazar: "Kaynak: Resmi site" ya da "Kaynak: Haber" (haber sitesinin adıyla).
- Markalar MARKA_SIRA sırasıyla gelir; her markanın altında ülke başlıkları İngilizce yazılır (ülkesi bilinmeyenler en sonda).
- Haber kartında görsel yoksa kutuda haber sitesinin adı yazar. Resmi üründe görsel yoksa "Görsel yok" yazar.
- Dönem uzunluğu DONEM_GUN ortam değişkeninden alınır (varsayılan 60).
- Haber dosyası yoksa yalnızca resmi siteler yazılır.
"""
import argparse
import html
import json
import os
import re
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

MARKA_SIRA = ["Burger King", "Popeyes", "Arby's", "Sbarro", "Subway", "McDonald's", "KFC"]
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
         "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
ISTANBUL = ZoneInfo("Europe/Istanbul")
RESMI, HABER = "Resmi site", "Haber"
BILINMEYEN_ULKE = "Ülke belirtilmemiş"

PDF_CSS = """
@page { size: A4 landscape; }
* { box-sizing: border-box; }
body { margin: 0; color: #1d1d1b; font: 9pt/1.4 "Noto Sans", "Liberation Sans", Arial, "Noto Sans CJK JP", sans-serif; }
section.sayfa { break-before: page; }
h1 { font-size: 34pt; margin: 0 0 8pt; letter-spacing: -.015em; line-height: 1.1; }
h2 { font-size: 19pt; margin: 0 0 10pt; padding-bottom: 5pt; border-bottom: 2.2pt solid #1d1d1b; break-after: avoid; }
h2 .sayi { font-size: 10pt; color: #6b6b66; font-weight: 400; margin-left: 6pt; }
h2 .logo { height: 17pt; width: auto; max-width: 48pt; vertical-align: -4pt; margin-right: 8pt; }
h3.ulke { font-size: 12pt; margin: 12pt 0 6pt; padding-bottom: 3pt; border-bottom: 1pt solid #d8d7d0; break-after: avoid; }
h3.ulke .sayi { font-size: 8.5pt; color: #6b6b66; font-weight: 400; margin-left: 6pt; }
.ust-yazi { font-size: 9pt; letter-spacing: .15em; color: #6b6b66; margin-bottom: 10pt; }
.alt { color: #6b6b66; font-size: 10pt; }
.not { color: #44443f; font-size: 9.5pt; margin: 10pt 0; }
.kutular { display: flex; gap: 10pt; margin: 18pt 0; }
.kutu { border: 1pt solid #d8d7d0; border-radius: 6pt; padding: 10pt 14pt; min-width: 130pt; }
.kutu b { display: block; font-size: 22pt; }
.kutu span { color: #6b6b66; font-size: 9pt; }
.uyari { border-left: 3pt solid #8a5a00; background: #fdf0d5; padding: 6pt 9pt; margin: 6pt 0; font-size: 9pt; }
.satir { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8pt; break-inside: avoid; }
.ulke-blok { min-width: 0; }
.kartlar { display: grid; gap: 8pt; }
.kart { border: 1pt solid #d8d7d0; border-radius: 6pt; overflow: hidden; break-inside: avoid; }
.gorsel { height: 110pt; background: #f4f3ef; display: flex; align-items: center; justify-content: center; }
.gorsel img { max-width: 100%; max-height: 100%; object-fit: contain; }
.gorsel.gy { color: #8a8a84; font-size: 9pt; }
.gorsel.hab { background: #eef2f8; color: #2b4f8a; font-size: 10pt; font-weight: 700; padding: 0 12pt; text-align: center; line-height: 1.25; }
.gorsel.mkt { height: auto; min-height: 118pt; display: block; text-align: left; padding: 10pt 12pt; box-sizing: border-box; color: #fff; overflow: hidden; }
.mkt .mk { font-size: 7.5pt; letter-spacing: .14em; opacity: .92; }
.mkt .tu { font-size: 8.5pt; font-weight: 700; letter-spacing: .06em; margin-top: 9pt; }
.mkt .ua { font-size: 14pt; font-weight: 700; line-height: 1.15; margin-top: 1pt; }
.mkt .ak { font-size: 8.5pt; line-height: 1.35; margin-top: 6pt; }
.govde { padding: 7pt 9pt 8pt; }
.ust { display: flex; justify-content: space-between; align-items: center; gap: 6pt; font-size: 8pt; color: #6b6b66; margin-bottom: 4pt; }
.rz { padding: 1pt 7pt; border-radius: 99pt; font-weight: 700; font-size: 7.5pt; white-space: nowrap; }
.rz.rr { background: #e3f3ea; color: #1f7a45; }
.rz.rh { background: #e6ecf7; color: #2b4f8a; }
.ad { font-weight: 700; font-size: 10pt; margin-bottom: 2pt; }
.ac { color: #44443f; font-size: 8.5pt; }
.kn { font-size: 8pt; color: #6b6b66; margin-top: 5pt; }
.kn a { color: #2b4f8a; }
.etk { font-weight: 700; color: #1d1d1b; }
table.k { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
table.k th, table.k td { border-bottom: 1pt solid #e4e3dd; padding: 5pt 7pt; text-align: left; }
table.k th.s, table.k td.s { text-align: right; }
ul.yon { padding-left: 16pt; }
ul.yon li { margin-bottom: 6pt; }
"""


def e(s):
    return html.escape(str(s or ""), quote=True)


def marka_sirasi(m):
    return MARKA_SIRA.index(m) if m in MARKA_SIRA else len(MARKA_SIRA)


def anahtar(s):
    return (s or "").lower().translate(str.maketrans("çğıöşüâî", "cgiosuai"))


def alan_adi(adres):
    n = urllib.parse.urlparse(adres or "").netloc.lower()
    return n[4:] if n.startswith("www.") else n


def tr_tarih(t):
    """'2026-10-13' ya da date nesnesi -> '13 Ekim 2026'. Okunamazsa boş döner."""
    if isinstance(t, str):
        try:
            t = datetime.fromisoformat(t[:10]).date()
        except ValueError:
            return ""
    return f"{t.day} {AYLAR[t.month - 1]} {t.year}"


def kisalt(s, n):
    """Metni n karakterde keser; kelimenin ortasından değil, kelime sınırından kırpar."""
    s = (s or "").strip()
    if len(s) <= n:
        return s
    kesim = s[:n - 1]
    bosluk = kesim.rfind(" ")
    if bosluk > n * 0.6:
        kesim = kesim[:bosluk]
    return kesim.rstrip(" ,;:-–—") + "…"


def haber_kaynagi(metin):
    """Google Haberler başlıkları 'Başlık - Kaynak' biçimindedir. (başlık, kaynak) döndürür."""
    metin = (metin or "").strip()
    if " - " in metin:
        baslik, kaynak = metin.rsplit(" - ", 1)
        if kaynak.strip():
            return baslik.strip(), kaynak.strip()
    return metin, ""


def json_oku(yol):
    try:
        with open(yol, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def ulke_adi(s):
    """Ülke adı yoksa ya da belirsizse 'Ülke belirtilmemiş' döner."""
    s = (s or "").strip()
    return s if s and s.lower() not in ("-", "belirsiz") else BILINMEYEN_ULKE


BILINMEYEN_ULKE_EN = "Country not specified"
ULKE_EN = {
    "ABD": "United States", "Amerika Birleşik Devletleri": "United States", "Birleşik Devletler": "United States",
    "Almanya": "Germany", "Arjantin": "Argentina", "Avustralya": "Australia", "Avusturya": "Austria",
    "Birleşik Arap Emirlikleri": "United Arab Emirates", "Birleşik Krallık": "United Kingdom",
    "Brezilya": "Brazil", "Danimarka": "Denmark", "Filipinler": "Philippines", "Finlandiya": "Finland",
    "Fransa": "France", "Güney Kore": "South Korea", "Hindistan": "India", "Hollanda": "Netherlands",
    "Hong Kong": "Hong Kong", "Hırvatistan": "Croatia", "İrlanda": "Ireland", "İspanya": "Spain",
    "İsrail": "Israel", "İsviçre": "Switzerland", "İtalya": "Italy", "Japonya": "Japan", "Kanada": "Canada",
    "Letonya": "Latvia", "Litvanya": "Lithuania", "Macaristan": "Hungary", "Malezya": "Malaysia",
    "Meksika": "Mexico", "Myanmar": "Myanmar", "Polonya": "Poland", "Portekiz": "Portugal",
    "Romanya": "Romania", "Singapur": "Singapore", "Tayland": "Thailand", "Türkiye": "Turkey",
    "Yeni Zelanda": "New Zealand", "Yunanistan": "Greece", "Çin": "China", "Şili": "Chile",
}


def ulke_goster(ulke):
    """Rapordaki ülke başlığı İngilizce yazılır (Çin -> China). Listede yoksa olduğu gibi kalır."""
    if ulke == BILINMEYEN_ULKE:
        return BILINMEYEN_ULKE_EN
    return ULKE_EN.get(ulke, ulke)


# Yayın adı (küçük harf) -> ülke. Yalnızca ülkesi açıkça bilinen yayınlar.
HABER_KAYNAK_ULKE = {
    "people.com": "ABD", "southern living": "ABD", "allrecipes": "ABD", "sporked": "ABD",
    "104.5 wokv": "ABD", "yahoo finance": "ABD", "yahoo": "ABD", "the washington post": "ABD",
    "delish": "ABD", "tasting table": "ABD", "dailyvoice.com": "ABD", "mashable": "ABD",
    "parade magazine": "ABD", "verge magazine": "ABD", "pizza marketplace": "ABD",
    "restaurantnews.com": "ABD", "nation's restaurant news": "ABD",
    "mcdonald's france": "Fransa", "business standard": "Hindistan",
    "metro.co.uk": "Birleşik Krallık", "manchester evening news": "Birleşik Krallık",
    "the irish sun": "İrlanda", "presseportal": "Almanya", "handelsblatt": "Almanya", "nordkurier": "Almanya",
    "los andes": "Arjantin", "milenio": "Meksika", "mercado negro": "Meksika", "el universal": "Meksika",
    "revista merca2.0": "Meksika", "restauración news": "İspanya", "canal ideal": "Brezilya",
    "hungrygowhere": "Singapur", "soranews24": "Japonya", "nine.com.au": "Avustralya",
    "roastbrief": "ABD", "roastbrief us": "ABD", "chowhound": "ABD",
    "chip": "Almanya", "afr": "Avustralya",
}


def haber_ulkesi(ulke_tespit, kaynak, baslik):
    """Haberin ülkesi: başlıkta yazıyorsa o; yoksa yayın adından ya da başlığın yazı dilinden tahmin edilir."""
    ulke = ulke_adi(ulke_tespit)
    if ulke != BILINMEYEN_ULKE:
        return ulke
    yayin = (kaynak or "").strip().lower()
    if yayin in HABER_KAYNAK_ULKE:
        return HABER_KAYNAK_ULKE[yayin]
    if re.search(r"[぀-ヿ]", baslik or ""):  # Hiragana / Katakana
        return "Japonya"
    if re.search(r"[가-힯]", baslik or ""):  # Hangul
        return "Güney Kore"
    if re.search(r"[֐-׿]", baslik or ""):  # İbranice
        return "İsrail"
    return BILINMEYEN_ULKE


def latin_orani(metin):
    """Metindeki harflerin ne kadarı Latin alfabesinden (Türkçe harfler dahil)."""
    harfler = [c for c in (metin or "") if c.isalpha()]
    if not harfler:
        return 0.0
    latin = sum(1 for c in harfler if c.isascii() or c in "ÇĞİÖŞÜçğıöşüÂâÎîÛû")
    return latin / len(harfler)


MARKA_RENK = [  # (marka adında geçen parça, kutu rengi)
    ("burger king", "#D62300"), ("popeyes", "#F47A2B"), ("kfc", "#E4002B"),
    ("mcdonald", "#DA291C"), ("subway", "#00703C"), ("arby", "#2E3B55"), ("sbarro", "#A6192E"),
]
KUTU_VARSAYILAN_RENK = "#4a4a45"


def tr_buyuk(s):
    """Türkçe büyük harf: 'i' -> 'İ' (Python varsayılanı 'I' yapar)."""
    return (s or "").replace("i", "İ").upper()


def marka_rengi(marka):
    m = (marka or "").lower()
    return next((renk for parca, renk in MARKA_RENK if parca in m), KUTU_VARSAYILAN_RENK)


def marka_slug(marka):
    """'Burger King' -> 'burger-king', \"McDonald's\" -> 'mcdonalds'. Logo dosya adı için."""
    s = unicodedata.normalize("NFKD", marka or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s.replace("'", "").replace("’", "")).strip("-")


def gecerli_gorsel_mi(bayt):
    """Dosyanın başına bakar: PNG, JPEG, GIF, WEBP, ICO ya da SVG mi? Bozuk dosya kırık simge olarak çıkmasın."""
    b = bayt[:4096]
    if b.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"\x00\x00\x01\x00")):
        return True
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return True
    s = b.lstrip()
    return s.startswith(b"<svg") or (s.startswith(b"<?xml") and b"<svg" in s)


def marka_logosu(marka, kok):
    """logolar/<marka>.<uzantı> dosyası geçerli bir görselse başlıkta küçük logo gösterilir."""
    klasor = Path(kok) / "logolar"
    if not klasor.exists():
        return ""
    for dosya in sorted(klasor.glob(marka_slug(marka) + ".*")):
        with open(dosya, "rb") as f:
            if gecerli_gorsel_mi(f.read(4096)):
                return f'<img class="logo" src="{dosya.as_uri()}">'
    return ""


def resmi_urunleri(veri):
    urunler = []
    for a in veri.get("tum", []):
        if a.get("sinif") != "ulke":
            continue
        adres = (a.get("kaynaklar") or [{}])[0].get("adres") or a.get("site_adresi") or ""
        urunler.append({
            "etiket": RESMI, "marka": a.get("marka") or "Diğer", "ulke": ulke_adi(a.get("ulke")),
            "ad": a.get("ad", ""),
            "aciklama": " ".join(x for x in [a.get("aciklama"), a.get("fiyat")] if x),
            "tarih": a.get("tespit_tarihi") or "",
            "gorsel_yolu": f"gorseller/{a['gorsel']}" if a.get("gorsel") else "",
            "adres": adres, "kaynak_adi": alan_adi(adres),
        })
    return urunler


def haber_urunleri(haber):
    urunler = []
    for k in haber.get("yeni_urun", []):
        baslik, kaynak = haber_kaynagi(k.get("metin"))
        adres = k.get("url") or ""
        urunler.append({
            "etiket": HABER, "marka": k.get("marka_site") or k.get("marka") or "Diğer",
            "ulke": haber_ulkesi(k.get("ulke_tespit"), kaynak, baslik), "ad": baslik, "aciklama": "",
            "tarih": k.get("tarih") or "", "gorsel_yolu": k.get("gorsel") or "", "adres": adres,
            "kaynak_adi": kaynak or alan_adi(adres),
            "tur": k.get("urun_turu") or "", "urun_adi": k.get("urun_adi") or "",
            "kutu_aciklama": k.get("aciklama") or "",
        })
    return urunler


HABER_GUN = 30            # haberler: son 1 ay
RESMI_GUN = 90            # resmi siteler: son 3 ay (tespit tarihine göre)
SBARRO = "Sbarro"
SBARRO_EN_AZ_URUN = 2     # Sbarro'da en az bu kadar ürün bulunana kadar geriye gidilir
SBARRO_EN_FAZLA_GUN = 180 # ...ama en fazla bu kadar geriye


def tarih_oku(s):
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def anahtar_baslik(metin):
    return re.sub(r"\W+", " ", (metin or "").lower()).strip()


ANAHTAR_DURDUR = set("""
a an the is are was were be been of in on for to and or with by from at as it its their his her this that
these those what how who which when where why not no do does did just now new up into they them you your
we will can but if so about over more one after again back around long won wont time limited menu menus
item items launch launches launched launching introduces introduce introduced introducing unveils unveil
debuts debut yeni yeniden ve ile bir için da de bu sunuyor sundu sunulan
nuevo nueva nuevos nuevas lanza lanzan lanzar lanzamiento presenta presentan presentar unen para por con sin
en el la los las un una unos unas del y o al se su sus que es son lo mas más especial edicion edición
limitada sabor sabores novo nova novos novas lança lançam lançamento com em do da dos das um uma
neu neue neuen neues der die das den dem und mit für fur von im zu ist sind wird
nouveau nouvelle nouveaux nouvelles le les une des du et pour avec dans sur
""".split())


def kok_bul(k):
    """Çok hafif kök: çoğul ve ek düşürülür (favorites / favorite -> favorit)."""
    for ek in ("ing", "ed", "es", "s", "e"):
        if k.endswith(ek) and len(k) - len(ek) >= 3:
            return k[:-len(ek)]
    return k


def anahtar_kelimeler(metin, marka=""):
    """Başlıktan karşılaştırma için anahtar kelimeler: marka adı, dolgu kelimeler ve kısa sözcükler çıkarılır."""
    def duz(s):
        s = unicodedata.normalize("NFKD", (s or "").lower())
        return "".join(c for c in s if not unicodedata.combining(c))

    marka_k = set(re.findall(r"[a-z0-9]+", duz(marka))) | {"mcdonalds", "arbys"}
    kelimeler = set()
    for k in re.findall(r"[a-z0-9]+", duz(metin)):
        if len(k) < 2 or k in ANAHTAR_DURDUR or k in marka_k:
            continue
        kelimeler.add(kok_bul(k))
    return kelimeler


def ayni_konu(a, b):
    """İki anahtar kelime kümesi aynı konuyu mu anlatıyor: en az 2 ortak kelime ve küçük kümenin yarısından fazlası."""
    if not a or not b:
        return False
    ortak = len(a & b)
    return ortak >= 2 and ortak / min(len(a), len(b)) >= 0.5


def haber_kelimeleri(u):
    return anahtar_kelimeler(u["ad"], u["marka"]) | anahtar_kelimeler(u.get("urun_adi"), u["marka"])


def ayni_olay(ta, tb, ka, kb):
    """Aynı markanın iki haberi aynı olay olabilir. Aynı gün yayımlandıysa en az 2 ortak kelime ve küçük kümenin en az
    dörtte biri yeter; bir gün ara varsa ortak oran en az %40 olmalı. Daha uzak tarihli haberler birleştirilmez."""
    da, db = tarih_oku(ta), tarih_oku(tb)
    if not da or not db or not ka or not kb:
        return False
    ortak = len(ka & kb)
    m = min(len(ka), len(kb))
    if ortak < 2:
        return False
    fark = abs((da - db).days)
    if fark == 0:
        return ortak * 4 >= m
    if fark == 1:
        return ortak * 5 >= m * 2
    return False


def benzer_haberleri_birlestir(haberler):
    """Aynı haberin kopyalarını ya da aynı konuyu anlatan başlıkları tek karta indirir; ek kaynak sayısını 'ek_kaynak' alanına yazar."""
    tutulan = []
    for u in sorted(haberler, key=lambda x: x["tarih"] or "", reverse=True):
        a = anahtar_baslik(u["ad"])
        kel = haber_kelimeleri(u)
        esi = next((t for t in tutulan if t["marka"] == u["marka"]
                    and (SequenceMatcher(None, anahtar_baslik(t["ad"]), a).ratio() >= 0.85
                         or ayni_konu(haber_kelimeleri(t), kel)
                         or ayni_olay(t["tarih"], u["tarih"], haber_kelimeleri(t), kel))), None)
        if esi:
            esi["ek_kaynak"] = esi.get("ek_kaynak", 0) + 1
            if esi.get("ulke") == BILINMEYEN_ULKE and u.get("ulke", BILINMEYEN_ULKE) != BILINMEYEN_ULKE:
                esi["ulke"] = u["ulke"]  # birleşen kopyalardan biri ülkeyi biliyorsa kart ülkesiz kalmasın
        else:
            tutulan.append(u)
    return tutulan


def haber_penceresi(haberler, bit):
    """Haberler son HABER_GUN güne göre süzülür. Sbarro'da en az 2 ürün olana kadar en fazla 180 güne kadar bakılır."""
    sinir = bit - timedelta(days=HABER_GUN)
    sinir_sbarro = bit - timedelta(days=SBARRO_EN_FAZLA_GUN)
    sonuc = []
    for marka, grup in groupby(sorted(haberler, key=lambda u: u["marka"]), key=lambda u: u["marka"]):
        grup = sorted(grup, key=lambda u: u["tarih"] or "", reverse=True)
        tarihli = lambda u: tarih_oku(u["tarih"]) or date.min
        if marka == SBARRO:
            # Önce son 30 gün; az kalırsa en fazla 180 güne kadar eski ürünlerden tamamlanır.
            yakin = [u for u in grup if tarihli(u) >= sinir]
            uzak = [u for u in grup if sinir_sbarro <= tarihli(u) < sinir]
            sonuc += yakin + uzak[:max(0, SBARRO_EN_AZ_URUN - len(yakin))]
        else:
            sonuc += [u for u in grup if tarihli(u) >= sinir]
    return sonuc


def resmi_penceresi(resmi, bit):
    sinir = bit - timedelta(days=RESMI_GUN)
    return [u for u in resmi if (tarih_oku(u["tarih"]) or date.min) >= sinir]


def resmiye_eslesir(resmi_ad, haber, marka=""):
    """Haber başlığında (ya da ürün adında) resmi ürünün adı geçiyorsa, ya da ürünün kelimelerinin çoğu geçiyorsa eşleşir."""
    r = anahtar_baslik(resmi_ad)
    if len(r) >= 5:
        for metin in (haber.get("urun_adi") or "", haber["ad"]):
            h = anahtar_baslik(metin)
            if h and (r in h or SequenceMatcher(None, r, h).ratio() >= 0.85):
                return True
    urun_k = anahtar_kelimeler(resmi_ad, marka or haber.get("marka", ""))
    if len(urun_k) >= 2:
        ortak = len(urun_k & haber_kelimeleri(haber))
        return ortak >= 2 and ortak / len(urun_k) >= 0.6
    return False


def haberleri_resmiye_bagla(resmi, haberler):
    """Haber, resmi sitedeki aynı ürünle eşleşirse ayrı kart olmaz; resmi kartın 'ek kaynak' sayısını artırır."""
    kalan = []
    for h in haberler:
        esi = next((r for r in resmi if r["marka"] == h["marka"] and resmiye_eslesir(r["ad"], h, h["marka"])), None)
        if esi:
            esi["ek_kaynak"] = esi.get("ek_kaynak", 0) + 1
        else:
            kalan.append(h)
    return resmi, kalan


def kontrol_ozeti(urunler, kok):
    """Raporda kaç kartın fotoğrafı, kaç kartın kutusu olduğunu sayar (kontrol için)."""
    kok = Path(kok)
    resmi = [u for u in urunler if u["etiket"] == RESMI]
    haber = [u for u in urunler if u["etiket"] == HABER]

    def gorselli(u):
        return bool(u["gorsel_yolu"]) and (kok / u["gorsel_yolu"]).exists()

    return {
        "resmi_toplam": len(resmi), "resmi_gorselli": sum(gorselli(u) for u in resmi),
        "haber_toplam": len(haber), "haber_gorselli": sum(gorselli(u) for u in haber),
        "haber_kutulu": sum(1 for u in haber if not gorselli(u)
                            and (u.get("urun_adi") or u.get("tur") or u.get("kutu_aciklama"))),
        "resmiye_bagli_haber": sum(u.get("ek_kaynak", 0) for u in resmi),
    }


def sirala(urunler):
    return sorted(urunler, key=lambda u: (u["ulke"] == BILINMEYEN_ULKE, ulke_goster(u["ulke"]).lower(),
                                          0 if u["etiket"] == RESMI else 1, anahtar(u["ad"])))


def kutu_html(u):
    """Haber görseli yoksa: marka renkli kutu (marka, ürün türü, ürün adı, kısa açıklama)."""
    tur = f"YENİ {tr_buyuk(u['tur'])}" if u.get("tur") else "YENİ ÜRÜN"
    ad_metni = u.get("urun_adi") or u["ad"]
    aciklama_metni = u.get("kutu_aciklama") or ""
    if latin_orani(ad_metni) < 0.8 and aciklama_metni:
        # Latin dışı ürün adı yerine Türkçe açıklama kutuda başlık olur.
        ad, aciklama = kisalt(aciklama_metni, 70), ""
    else:
        ad = kisalt(ad_metni, 40)
        aciklama = f'<div class="ak">{e(kisalt(aciklama_metni, 110))}</div>' if aciklama_metni else ""
    return (f'<div class="gorsel mkt" style="background:{marka_rengi(u["marka"])}">'
            f'<div class="mk">{e(tr_buyuk(u["marka"]))}</div>'
            f'<div class="tu">{e(tur)}</div>'
            f'<div class="ua">{e(ad)}</div>{aciklama}</div>')


def kart_html(u, kok):
    resmi = u["etiket"] == RESMI
    rozet_sinif, rozet = ("rr", "Resmi sitede yeni") if resmi else ("rh", "Haber: yeni ürün")
    yol = kok / u["gorsel_yolu"] if u["gorsel_yolu"] else None
    kutuda = False
    if yol and yol.exists():
        gorsel = f'<div class="gorsel"><img src="{yol.as_uri()}"></div>'
    elif resmi:
        gorsel = '<div class="gorsel gy">Görsel yok</div>'
    elif u.get("urun_adi") or u.get("tur") or u.get("kutu_aciklama"):
        gorsel = kutu_html(u)
        kutuda = True
    else:
        gorsel = f'<div class="gorsel hab">{e(kisalt(u["kaynak_adi"], 30) or HABER)}</div>'
    tarih = tr_tarih(u["tarih"])
    if tarih and resmi:
        tarih = "tespit " + tarih
    ust_sag = e(tarih)
    kaynak_metni = e(kisalt(u["kaynak_adi"], 40))
    kaynak = f'<a href="{e(u["adres"])}">{kaynak_metni}</a>' if u["adres"] else kaynak_metni
    if u.get("ek_kaynak"):
        kaynak += f' (+{u["ek_kaynak"]} kaynak)'
    baslik, ozet, alt_ad = u["ad"], u["aciklama"], ""
    if resmi and ozet and latin_orani(u["ad"]) < 0.8:
        # Ürün adı Latin harfli değilse (Japonca, Çince vb.) Türkçe açıklama başlık olur; orijinal ad altta küçük yazılır.
        baslik, ozet, alt_ad = ozet, "", u["ad"]
    elif not resmi and latin_orani(u["ad"]) < 0.8 and (kutuda or u.get("kutu_aciklama")):
        # Haber başlığı Latin harfli değilse orijinal başlık kartta basılmaz; Türkçe özet kullanılır.
        # Kutu aynı özeti zaten yazıyorsa alt başlık tekrar edilmez.
        baslik, ozet = ("" if kutuda else u["kutu_aciklama"]), ""
    if alt_ad:
        aciklama = f'<div class="ac">{e(alt_ad)}</div>'
    else:
        aciklama = f'<div class="ac">{e(kisalt(ozet, 140))}</div>' if ozet else ""
    ad_html = f'<div class="ad">{e(kisalt(baslik, 90))}</div>' if baslik else ""
    return (f'<div class="kart">{gorsel}<div class="govde">'
            f'<div class="ust"><span class="rz {rozet_sinif}">{rozet}</span><span>{ust_sag}</span></div>'
            f'{ad_html}{aciklama}'
            f'<div class="kn"><span class="etk">Kaynak: {e(u["etiket"])}</span> · {kaynak}</div>'
            "</div></div>")


KOLON = 4  # bir satırdaki kart sütunu sayısı


def satirlara_diz(gruplar):
    """Ülkeleri 4 sütunluk satırlara yan yana dizer; ürünü az olan ülkeler aynı satıra sığar, böylece sayfalar boş kalmaz.
    Bir ülkenin ürünleri 4'ü aşarsa 4'lük parçalara bölünür. Her satır sayfa ortasında bölünmez."""
    parcalar = []  # (ülke, toplam ürün, kartlar, devam mı)
    for ulke, kartlar in gruplar:
        for i in range(0, len(kartlar), KOLON):
            parcalar.append((ulke, len(kartlar), kartlar[i:i + KOLON], i > 0))
    satirlar, acik, dolu = [], [], 0
    for parca in parcalar:
        n = len(parca[2])
        if dolu + n > KOLON:
            satirlar.append(acik)
            acik, dolu = [], 0
        acik.append(parca)
        dolu += n
    if acik:
        satirlar.append(acik)
    html_satirlar = []
    for satir in satirlar:
        hucreler = []
        for ulke, toplam, kartlar, devam in satir:
            n = len(kartlar)
            sayi = "devamı" if devam else f"{toplam} ürün"
            hucreler.append(
                f'<div class="ulke-blok" style="grid-column: span {n}">'
                f'<h3 class="ulke">{e(ulke)}<span class="sayi">{sayi}</span></h3>'
                f'<div class="kartlar" style="grid-template-columns: repeat({n}, 1fr)">{"".join(kartlar)}</div></div>')
        html_satirlar.append(f'<div class="satir">{"".join(hucreler)}</div>')
    return "".join(html_satirlar)


def marka_bolumu(marka, urunler, kok):
    if not urunler:
        return (f'<section class="sayfa"><h2>{marka_logosu(marka, kok)}{e(marka)}<span class="sayi">bulunamadı</span></h2>'
                '<p class="not">Bu dönemde bu markada yeni ürün bulunamadı.</p></section>')
    gruplar = []
    for ulke, grup in groupby(sirala(urunler), key=lambda u: ulke_goster(u["ulke"])):
        gruplar.append((ulke, [kart_html(u, kok) for u in grup]))
    return (f'<section class="sayfa"><h2>{marka_logosu(marka, kok)}{e(marka)}<span class="sayi">{len(urunler)} ürün</span></h2>'
            f'{satirlara_diz(gruplar)}</section>')


def ozet_html(urunler, markalar):
    satirlar = []
    for m in markalar:
        r = sum(1 for u in urunler if u["marka"] == m and u["etiket"] == RESMI)
        h = sum(1 for u in urunler if u["marka"] == m and u["etiket"] == HABER)
        if r + h == 0:
            satirlar.append(f'<tr><td><b>{e(m)}</b></td><td class="s" colspan="3">bulunamadı</td></tr>')
            continue
        satirlar.append(f'<tr><td><b>{e(m)}</b></td><td class="s">{r}</td><td class="s">{h}</td>'
                        f'<td class="s">{r + h}</td></tr>')
    return ('<section class="sayfa"><h2>Özet</h2><table class="k"><thead><tr><th>Marka</th>'
            '<th class="s">Resmi site</th><th class="s">Haber</th><th class="s">Toplam</th></tr></thead>'
            f'<tbody>{"".join(satirlar)}</tbody></table></section>')


YONTEM = """<section class="sayfa"><h2>Yöntem ve kaynaklar</h2><ul class="yon">
<li><b>Resmi site:</b> Markanın kendi sitesinde yeni olarak öne çıkardığı ürünler. Sitede çıkış tarihi yazmadığında tespit tarihi esas alınır.</li>
<li><b>Haber:</b> Google Haberler'de marka ve yeni ürün kelimeleriyle geçen başlıklar. Yeni ürün olup olmadıkları başlıktan otomatik belirlendi. Başlıkta ülke yazmıyorsa ülke, haberin yayın adından ya da başlığın yazı dilinden tahmin edildi; hiçbiri uymazsa ülke "Country not specified" altında yer alır. Görsel, haber sayfasındaki paylaşım görselidir; bulunamazsa marka renkli bir kutu gösterilir: ürün türü, ürün adı ve kısa açıklama başlıktan alınır, uydurma bilgi eklenmez.</li>
<li><b>Dönem:</b> Resmi siteler son 90 gün (tespit tarihine göre), haberler son 30 gün. Sbarro'da en az 2 benzersiz ürün bulunana kadar en fazla 180 gün geriye bakıldı. Aynı haberin kopyaları ve aynı konuyu anlatan haberler tek kartta birleştirildi; kartta ek kaynak sayısı yazar. Aynı ürün hem resmi sitede hem haberde varsa resmi site kartı gösterilir, haber ek kaynak olarak sayılır.</li>
<li><b>Dil:</b> Ürün adı Latin harfleriyle yazılmamışsa kartta Türkçe açıklama başlık olur; orijinal ad altta küçük yazılır.</li>
<li><b>Sınır:</b> Haber listesi otomatik derlendiği için ürün dışı ya da tekrar eden başlıklar bulunabilir.</li>
</ul></section>"""


def rapor_html(urunler, kok, bas, bit, gun, uyarilar):
    # Veri olmayan markalar da (bulunamadı olarak) raporda yer alır.
    markalar = sorted(set(MARKA_SIRA) | {u["marka"] for u in urunler}, key=marka_sirasi)
    resmi = sum(1 for u in urunler if u["etiket"] == RESMI)
    ulke_sayisi = len({u["ulke"] for u in urunler if u["ulke"] != BILINMEYEN_ULKE})
    uyari_html = "".join(f'<div class="uyari"><b>UYARI:</b> {e(u)}</div>' for u in uyarilar)
    kapak = (f'<section class="kapak"><div class="ust-yazi">Tab Gıda Reklam Üssü · Global Yeni Ürünler</div>'
             f'<h1>{tr_tarih(bas)} – {tr_tarih(bit)}</h1>'
             f'<div class="alt">{e(" · ".join(MARKA_SIRA))}</div>'
             f'<p class="not">Bu rapor, son {gun} günde yukarıdaki markaların resmi sitelerinde öne çıkardığı '
             f'yeni ürünleri ve son {HABER_GUN} günde haber kaynaklarında yeni ürün olarak geçen haberleri derler.</p>'
             '<div class="kutular">'
             f'<div class="kutu"><b>{len(urunler)}</b><span>toplam ürün</span></div>'
             f'<div class="kutu"><b>{resmi}</b><span>resmi sitede yeni</span></div>'
             f'<div class="kutu"><b>{len(urunler) - resmi}</b><span>haber kaynaklı</span></div>'
             f'<div class="kutu"><b>{ulke_sayisi}</b><span>ülke</span></div></div>'
             f'{uyari_html}</section>')
    govde = [kapak, ozet_html(urunler, markalar)]
    govde += [marka_bolumu(m, [u for u in urunler if u["marka"] == m], kok) for m in markalar]
    govde.append(YONTEM)
    return ('<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>Global Yeni Ürünler</title>'
            f'<style>{PDF_CSS}</style></head><body>{"".join(govde)}</body></html>')


def altbilgi_sablonu(metin):
    return ('<div style="font-family:Arial,sans-serif;font-size:7pt;color:#888;width:100%;padding:0 12mm;'
            f'display:flex;justify-content:space-between"><span>{e(metin)}</span>'
            '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')


def pdf_yaz(html_metni, hedef, altbilgi):
    from playwright.sync_api import sync_playwright

    gecici = hedef.with_name("_birlesik_gecici.html")
    gecici.write_text(html_metni, encoding="utf-8")
    try:
        with sync_playwright() as p:
            tarayici = p.chromium.launch()
            sayfa = tarayici.new_page()
            sayfa.goto(gecici.resolve().as_uri(), wait_until="load", timeout=180000)
            sayfa.pdf(path=str(hedef), format="A4", landscape=True, print_background=True,
                      display_header_footer=True, header_template="<span></span>",
                      footer_template=altbilgi_sablonu(altbilgi),
                      margin={"top": "12mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
            tarayici.close()
    finally:
        gecici.unlink(missing_ok=True)


def sbarro_uyarisi(haber_liste):
    """Sbarro'da 180 güne kadar bakılmasına rağmen 2 ürün çıkmazsa rapora not düşer."""
    sayi = sum(1 for u in haber_liste if u["marka"] == SBARRO)
    if sayi < SBARRO_EN_AZ_URUN:
        return f"Sbarro: {SBARRO_EN_FAZLA_GUN} güne kadar bakıldı; bu dönemde yalnızca {sayi} ürün bulundu."
    return ""


def main():
    p = argparse.ArgumentParser(description="Resmi site ve haber sonuçlarını tek PDF'te birleştir")
    p.add_argument("--veri", required=True, help="radar veri.json yolu")
    p.add_argument("--haber", required=True, help="yeni_urun_siniflandir.py çıktısı")
    p.add_argument("--cikti", required=True, help="birleşik PDF yolu")
    p.add_argument("--gun", type=int, default=int(os.environ.get("DONEM_GUN") or 60))
    a = p.parse_args()

    uyarilar = []
    veri = json_oku(a.veri)
    if veri is None:
        uyarilar.append("Resmi site sonuçları okunamadı")
        veri = {}
    haber = json_oku(a.haber)
    if haber is None:
        uyarilar.append("Haber sonuçları yok; yalnızca resmi siteler yazıldı")
        haber = {}

    bit = datetime.now(ISTANBUL).date()
    resmi_liste = resmi_penceresi(resmi_urunleri(veri), bit)
    haber_liste = haber_penceresi(benzer_haberleri_birlestir(haber_urunleri(haber)), bit)
    resmi_liste, haber_liste = haberleri_resmiye_bagla(resmi_liste, haber_liste)
    sbarro_notu = sbarro_uyarisi(haber_liste)
    if sbarro_notu:
        uyarilar.append(sbarro_notu)
    urunler = resmi_liste + haber_liste
    if not urunler:
        print("UYARI: yazılacak ürün yok, PDF üretilmedi")
        return

    cikti = Path(a.cikti)
    cikti.parent.mkdir(parents=True, exist_ok=True)
    bas = bit - timedelta(days=a.gun)
    kok = cikti.resolve().parent
    (kok / "kontrol.json").write_text(json.dumps(kontrol_ozeti(urunler, kok), ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    html_metni = rapor_html(urunler, kok, bas, bit, a.gun, uyarilar)
    pdf_yaz(html_metni, cikti, f"Global Yeni Ürünler · {tr_tarih(bas)} – {tr_tarih(bit)}")
    print(f"Resmi site: {len(resmi_liste)}, haber: {len(haber_liste)}, toplam: {len(urunler)}")
    print(f"Çıktı: {cikti}")


if __name__ == "__main__":
    main()
