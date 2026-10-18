"""Marka logolarını çeker: her markanın kendi sitesinin simgesini (apple-touch-icon ya da favicon) indirir.

Kullanım:
    python logo_indir.py --veri arsiv/son-veri.json --kok rapor

Çıktı: <kok>/logolar/<marka-slug>.<uzantı>  (örn. logolar/burger-king.png)
Bulunamayan marka rapora logosuz yazılır; çalışma durmaz.
"""
import argparse
import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from birlestir_pdf import gecerli_gorsel_mi, marka_slug
from haber_gorsel import ATTR_RE, indir

LINK_RE = re.compile(r"<link\s[^>]*?>", re.I)
UZANTI = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
          "image/svg+xml": ".svg", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico"}
EN_FAZLA_BAYT = 400_000


def ikon_adaylari(sayfa, taban):
    """Site simgesi adaylarını tercih sırasıyla döndürür: önce apple-touch-icon, sonra diğer icon etiketleri."""
    apple, genel = [], []
    for etiket in LINK_RE.findall(sayfa):
        ozellik = {k.lower(): v for k, v in ATTR_RE.findall(etiket)}
        rel = ozellik.get("rel", "").lower()
        href = ozellik.get("href", "").strip()
        if not href or "icon" not in rel:
            continue
        adres = urllib.parse.urljoin(taban, href)
        (apple if "apple-touch-icon" in rel else genel).append(adres)
    yedek = [urllib.parse.urljoin(taban, "/apple-touch-icon.png"), urllib.parse.urljoin(taban, "/favicon.ico")]
    return apple + genel + yedek


MARKA_BASINA_SITE = 6  # bir markanın en fazla bu kadar sitesinde logo aranır


def marka_adresleri(veri):
    """Her marka için arşivdeki site adreslerini (en fazla MARKA_BASINA_SITE) sırayla verir."""
    secilen = {}
    for s in veri.get("siteler", []):
        marka, adres = s.get("marka"), s.get("adres")
        if not marka or not adres:
            continue
        liste = secilen.setdefault(marka, [])
        if adres not in liste and len(liste) < MARKA_BASINA_SITE:
            liste.append(adres)
    return secilen


def logo_kaydet(marka, adresler, klasor, al=indir):
    """Markanın logosunu sitelerinden dener; ilk geçerli görseli kaydeder. Kayıt adını ya da boş metni döndürür."""
    for adres in adresler:
        try:
            sayfa, _, son = al(adres, azami=1_500_000)
        except Exception:  # noqa: BLE001  # Tek sitenin hatası diğer siteleri ve markaları durdurmaz.
            continue
        taban = son or adres
        for aday in ikon_adaylari(sayfa.decode("utf-8", errors="ignore"), taban):
            try:
                veri, tur, _ = al(aday, azami=EN_FAZLA_BAYT)
            except Exception:  # noqa: BLE001
                continue
            uzanti = UZANTI.get(tur.split(";")[0].strip().lower())
            # Bildirilen tür yetmez: içerik gerçekten görsel olmalı (HTML hata sayfası kaydedilmesin).
            if uzanti and 0 < len(veri) < EN_FAZLA_BAYT and gecerli_gorsel_mi(veri):
                ad = marka_slug(marka) + uzanti
                (klasor / ad).write_bytes(veri)
                return ad
    return ""


def main():
    p = argparse.ArgumentParser(description="Marka logolarını site simgelerinden çeker")
    p.add_argument("--veri", required=True, help="radar arşivi (son-veri.json)")
    p.add_argument("--kok", required=True, help="rapor klasörü; logolar bunun altına yazılır")
    a = p.parse_args()
    try:
        with open(a.veri, encoding="utf-8") as f:
            veri = json.load(f)
    except (OSError, ValueError):
        print("UYARI: arşiv okunamadı, logo çekilmedi")
        return
    adresler = marka_adresleri(veri)
    klasor = Path(a.kok) / "logolar"
    klasor.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as havuz:
        sonuclar = list(havuz.map(lambda m: logo_kaydet(m, adresler[m], klasor), adresler))
    print(f"Marka logosu bulundu: {sum(1 for s in sonuclar if s)} / {len(adresler)}")
    for marka, ad in zip(adresler, sonuclar):
        print(f"  {marka}: {ad or 'bulunamadı'}")


if __name__ == "__main__":
    main()
