"""Resmi site ve haber sonuçlarını tek PDF raporunda birleştirir.

Kullanım:
    python birlestir_pdf.py --veri rapor/veri.json --haber rapor/haber_urunleri.json --cikti rapor/birlesik_rapor.pdf

Kurallar:
- Her ürün kartında kaynak yazar: "Kaynak: Resmi site" ya da "Kaynak: Haber" (haber sitesinin adıyla).
- Markalar MARKA_SIRA sırasıyla gelir; her markanın altında ülke başlıkları vardır (ülkesi bilinmeyenler en sonda).
- Haber kartında görsel yoksa kutuda haber sitesinin adı yazar. Resmi üründe görsel yoksa "Görsel yok" yazar.
- Dönem uzunluğu DONEM_GUN ortam değişkeninden alınır (varsayılan 60).
- Haber dosyası yoksa yalnızca resmi siteler yazılır.
"""
import argparse
import html
import json
import os
import urllib.parse
from datetime import datetime, timedelta
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
.grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8pt; }
.kart { border: 1pt solid #d8d7d0; border-radius: 6pt; overflow: hidden; break-inside: avoid; }
.gorsel { height: 110pt; background: #f4f3ef; display: flex; align-items: center; justify-content: center; }
.gorsel img { max-width: 100%; max-height: 100%; object-fit: contain; }
.gorsel.gy { color: #8a8a84; font-size: 9pt; }
.gorsel.hab { background: #eef2f8; color: #2b4f8a; font-size: 10pt; font-weight: 700; padding: 0 12pt; text-align: center; line-height: 1.25; }
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
    s = (s or "").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


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
            "ulke": ulke_adi(k.get("ulke_tespit")), "ad": baslik, "aciklama": "",
            "tarih": k.get("tarih") or "", "gorsel_yolu": k.get("gorsel") or "", "adres": adres,
            "kaynak_adi": kaynak or alan_adi(adres),
        })
    return urunler


def sirala(urunler):
    return sorted(urunler, key=lambda u: (u["ulke"] == BILINMEYEN_ULKE, anahtar(u["ulke"]),
                                          0 if u["etiket"] == RESMI else 1, anahtar(u["ad"])))


def kart_html(u, kok):
    resmi = u["etiket"] == RESMI
    rozet_sinif, rozet = ("rr", "Resmi sitede yeni") if resmi else ("rh", "Haber: yeni ürün")
    yol = kok / u["gorsel_yolu"] if u["gorsel_yolu"] else None
    if yol and yol.exists():
        gorsel = f'<div class="gorsel"><img src="{yol.as_uri()}"></div>'
    elif resmi:
        gorsel = '<div class="gorsel gy">Görsel yok</div>'
    else:
        gorsel = f'<div class="gorsel hab">{e(kisalt(u["kaynak_adi"], 30) or HABER)}</div>'
    tarih = tr_tarih(u["tarih"])
    if tarih and resmi:
        tarih = "tespit " + tarih
    ust_sag = e(tarih)
    kaynak_metni = e(kisalt(u["kaynak_adi"], 40))
    kaynak = f'<a href="{e(u["adres"])}">{kaynak_metni}</a>' if u["adres"] else kaynak_metni
    aciklama = f'<div class="ac">{e(kisalt(u["aciklama"], 140))}</div>' if u["aciklama"] else ""
    return (f'<div class="kart">{gorsel}<div class="govde">'
            f'<div class="ust"><span class="rz {rozet_sinif}">{rozet}</span><span>{ust_sag}</span></div>'
            f'<div class="ad">{e(kisalt(u["ad"], 90))}</div>{aciklama}'
            f'<div class="kn"><span class="etk">Kaynak: {e(u["etiket"])}</span> · {kaynak}</div>'
            "</div></div>")


def marka_bolumu(marka, urunler, kok):
    if not urunler:
        return (f'<section class="sayfa"><h2>{e(marka)}<span class="sayi">bulunamadı</span></h2>'
                '<p class="not">Bu dönemde bu markada yeni ürün bulunamadı.</p></section>')
    bloklar = []
    for ulke, grup in groupby(sirala(urunler), key=lambda u: u["ulke"]):
        grup = list(grup)
        kartlar = "".join(kart_html(u, kok) for u in grup)
        bloklar.append(f'<h3 class="ulke">{e(ulke)}<span class="sayi">{len(grup)} ürün</span></h3>'
                       f'<div class="grid">{kartlar}</div>')
    return (f'<section class="sayfa"><h2>{e(marka)}<span class="sayi">{len(urunler)} ürün</span></h2>'
            f'{"".join(bloklar)}</section>')


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
<li><b>Haber:</b> Google Haberler'de marka ve yeni ürün kelimeleriyle geçen başlıklar. Yeni ürün olup olmadıkları ve hangi ülkeye ait oldukları başlıktan otomatik belirlendi; ülke belirtilmeyenler "Ülke belirtilmemiş" altında yer alır. Haber kaynağı başlığın sonundan alındı. Görsel, haber sayfasındaki paylaşım görselidir; bulunamazsa kaynağın adı yazılır.</li>
<li><b>Sınır:</b> Haber listesi otomatik derlendiği için ürün dışı ya da tekrar eden başlıklar bulunabilir.</li>
</ul></section>"""


def rapor_html(urunler, kok, bas, bit, gun, uyarilar):
    # Veri olmayan markalar da (bulunamadı olarak) raporda yer alır.
    markalar = sorted(set(MARKA_SIRA) | {u["marka"] for u in urunler}, key=marka_sirasi)
    resmi = sum(1 for u in urunler if u["etiket"] == RESMI)
    ulke_sayisi = len({u["ulke"] for u in urunler if u["ulke"] != BILINMEYEN_ULKE})
    uyari_html = "".join(f'<div class="uyari"><b>UYARI:</b> {e(u)}</div>' for u in uyarilar)
    kapak = (f'<section class="kapak"><div class="ust-yazi">GLOBAL YENİ ÜRÜNLER</div>'
             f'<h1>{tr_tarih(bas)} – {tr_tarih(bit)}</h1>'
             f'<div class="alt">{e(" · ".join(MARKA_SIRA))}</div>'
             f'<p class="not">Bu rapor, son {gun} günde yukarıdaki markaların resmi sitelerinde öne çıkardığı '
             'yeni ürünleri ve haber kaynaklarında yeni ürün olarak geçen haberleri derler.</p>'
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

    resmi_liste = resmi_urunleri(veri)
    haber_liste = haber_urunleri(haber)
    urunler = resmi_liste + haber_liste
    if not urunler:
        print("UYARI: yazılacak ürün yok, PDF üretilmedi")
        return

    cikti = Path(a.cikti)
    cikti.parent.mkdir(parents=True, exist_ok=True)
    bit = datetime.now(ISTANBUL).date()
    bas = bit - timedelta(days=a.gun)
    html_metni = rapor_html(urunler, cikti.resolve().parent, bas, bit, a.gun, uyarilar)
    pdf_yaz(html_metni, cikti, f"Global Yeni Ürünler · {tr_tarih(bas)} – {tr_tarih(bit)}")
    print(f"Resmi site: {len(resmi_liste)}, haber: {len(haber_liste)}, toplam: {len(urunler)}")
    print(f"Çıktı: {cikti}")


if __name__ == "__main__":
    main()
