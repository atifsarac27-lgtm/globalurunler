"""Yayın öncesi kalite kapısı.

Raporu yayınlamadan önce veri ve metin tutarlılığını denetler. Kullanım:

    python3 kalite_kapisi.py --veri arsiv/son-veri.json --pdf rapor/rapor.pdf

Çıkış kodu: 0 = tüm zorunlu kontroller geçti, 1 = en az biri başarısız.
UYARI düzeyindeki kontroller çıkış kodunu etkilemez.
"""
import argparse
import json
import re
import sys
from datetime import date

BILINEN_DURUMLAR = {"OK", "ENGELLİ", "ADRES YOK", "HATA", "BOŞ"}
YASAK_DONEM_IFADELERI = [r"son 2 ay"]


def tekil_sayi(kayitlar):
    return len({(a["marka"], a["ad"].strip().lower()) for a in kayitlar})


def veri_kontrolleri(v):
    """Veri dosyasından yapılan kontroller: (ad, geçti_mi, zorunlu_mu, ayrıntı)."""
    siteler = v["siteler"]
    yeni = [a for a in v["tum"] if a.get("sinif") == "ulke"]
    bugun = date.fromisoformat(v["bugun"])
    kontroller = []

    bilinmeyen = {s["durum"] for s in siteler} - BILINEN_DURUMLAR
    kontroller.append(("Site durumları tanımlı", not bilinmeyen, True,
                       f"bilinmeyen durum: {sorted(bilinmeyen) or '-'}"))

    t = tekil_sayi(yeni)
    kontroller.append(("Tekil sayı kayıt sayısını aşmıyor", t <= len(yeni), True,
                       f"kayıt {len(yeni)}, tekil {t}"))

    gelecek = [a["ad"] for a in yeni if a.get("tespit_tarihi") and date.fromisoformat(a["tespit_tarihi"]) > bugun]
    kontroller.append(("Tespit tarihleri tarama tarihinden önce", not gelecek, True,
                       f"gelecek tarihli: {gelecek[:3] or '-'}"))

    adressiz = sum(1 for s in siteler if s["durum"] == "ADRES YOK")
    kontroller.append(("Adressiz siteler (UYARI: raporda belirtilmeli)", adressiz == 0, False,
                       f"adresi tanımsız kayıt: {adressiz}"))
    return kontroller


def pdf_metni(yol):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(yol).pages)


def metin_kontrolleri(metin, v):
    """Rapor metninden yapılan kontroller."""
    yeni = [a for a in v["tum"] if a.get("sinif") == "ulke"]
    kayit, t = len(yeni), tekil_sayi(yeni)
    adressiz = sum(1 for s in v["siteler"] if s["durum"] == "ADRES YOK")
    kontroller = []

    bulunan = [p for p in YASAK_DONEM_IFADELERI if re.search(p, metin)]
    kontroller.append(("Eski dönem ifadesi yok", not bulunan, True,
                       f"bulunan: {bulunan or '-'}"))

    if t != kayit:
        kontroller.append(("Tekil ürün sayısı raporda yazılı", "tekil ürün" in metin, True,
                           f"kayıt {kayit}, tekil {t}"))

    beklenen = sum(1 for s in v["siteler"] if s["durum"] in {"ENGELLİ", "HATA", "BOŞ"})
    m = re.search(r"açılamayan\s+(\d+)\s+site", metin)
    bulunan_sayi = int(m.group(1)) if m else None
    kontroller.append(("Açılamayan site sayısı veriyle eşleşiyor", bulunan_sayi == beklenen, True,
                       f"raporda {bulunan_sayi}, veride {beklenen}"))

    kontroller.append(("Adressiz siteler raporda belirtilmiş (UYARI)",
                       adressiz == 0 or "adresi" in metin and "tanımlı" in metin, False,
                       f"adressiz kayıt: {adressiz}"))
    return kontroller


def calistir(veri_yolu, pdf_yolu=None):
    with open(veri_yolu, encoding="utf-8") as f:
        v = json.load(f)
    sonuclar = veri_kontrolleri(v)
    if pdf_yolu:
        sonuclar += metin_kontrolleri(pdf_metni(pdf_yolu), v)
    basarisiz_zorunlu = 0
    for ad, gecti, zorunlu, ayrinti in sonuclar:
        if gecti:
            durum = "GEÇTİ"
        elif zorunlu:
            durum = "BAŞARISIZ"
            basarisiz_zorunlu += 1
        else:
            durum = "UYARI"
        print(f"[{durum:10s}] {ad}" + (f"  ({ayrinti})" if ayrinti else ""))
    return 1 if basarisiz_zorunlu else 0


def main():
    p = argparse.ArgumentParser(description="Yayın öncesi kalite kapısı")
    p.add_argument("--veri", required=True, help="son-veri.json yolu")
    p.add_argument("--pdf", help="kontrol edilecek rapor PDF'i")
    a = p.parse_args()
    sys.exit(calistir(a.veri, a.pdf))


if __name__ == "__main__":
    main()
