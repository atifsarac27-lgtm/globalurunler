"""Haber görseli testi: ilk N haberin bağlantısını gerçek haber adresine çevirip paylaşım görselini arar.

Kullanım:
    python haber_gorsel_testi.py --kaynak rapor/kaynak_sonuc.json --cikti rapor/gorsel_testi.md --adet 10

Gemini kullanmaz. Sonuç bir tablo olarak yazılır: hangi yöntemle adres bulundu, görsel var mı.
"""
import argparse
import json
import urllib.parse

from haber_gorsel import UZANTI, gorsel_uygun, indir, og_gorsel

try:
    from googlenewsdecoder import gnewsdecoder
except ImportError:  # Paket kurulu değilse yalnızca yönlendirme yöntemi denenir.
    gnewsdecoder = None


def gercek_adres(url):
    """Google Haberler bağlantısından gerçek haber adresini bulmaya çalışır. (adres, yöntem, hata) döndürür."""
    hata = ""
    if gnewsdecoder is not None:
        try:
            sonuc = gnewsdecoder(url, interval=1)
            if sonuc.get("status") and sonuc.get("decoded_url"):
                return sonuc["decoded_url"], "çözücü", ""
            hata = str(sonuc.get("message", "çözülemedi"))[:80]
        except Exception as e:  # noqa: BLE001  # Tek bağlantının hatası testi durdurmaz.
            hata = f"{type(e).__name__}: {str(e)[:60]}"
    else:
        hata = "çözücü kurulu değil"
    try:
        _, _, son = indir(url, azami=200_000)
        if son and "news.google.com" not in urllib.parse.urlparse(son).netloc:
            return son, "yönlendirme", ""
    except Exception as e:  # noqa: BLE001
        hata += f" | yönlendirme: {type(e).__name__}"
    return "", "", hata


def gorsel_dene(url):
    """Bir haber bağlantısı için sonuç sözlüğü döndürür."""
    adres, yontem, hata = gercek_adres(url)
    if not adres:
        return {"yontem": "yok", "sayfa": "-", "gorsel": "yok", "not": hata}
    sayfa = urllib.parse.urlparse(adres).netloc
    try:
        icerik, _, son = indir(adres, azami=1_500_000)
        gorsel_adresi = og_gorsel(icerik.decode("utf-8", errors="ignore"), son or adres)
        if not gorsel_uygun(gorsel_adresi):
            return {"yontem": yontem, "sayfa": sayfa, "gorsel": "yok", "not": "paylaşım görseli yok"}
        veri, tur, _ = indir(gorsel_adresi)
        uzanti = UZANTI.get(tur.split(";")[0].strip().lower())
        if not uzanti or len(veri) >= 3_000_000:
            return {"yontem": yontem, "sayfa": sayfa, "gorsel": "yok", "not": f"uygun değil ({tur[:30]})"}
        return {"yontem": yontem, "sayfa": sayfa, "gorsel": "var", "not": uzanti}
    except Exception as e:  # noqa: BLE001
        return {"yontem": yontem, "sayfa": sayfa, "gorsel": "yok", "not": f"{type(e).__name__}"}


def haber_adaylari(kaynak, adet):
    """Kaynak dosyadan ilk `adet` tekil haber bağlantısını seçer."""
    gorulen, secilen = set(), []
    for s in kaynak:
        if s.get("sonuc") != "haber RSS":
            continue
        for a in s.get("adaylar", []):
            url = a.get("url")
            if not url or url in gorulen or a.get("tekrar"):
                continue
            gorulen.add(url)
            secilen.append({"marka": s.get("marka", ""), "metin": a.get("metin", ""), "url": url})
            if len(secilen) >= adet:
                return secilen
    return secilen


def main():
    p = argparse.ArgumentParser(description="Haber görseli testi (Gemini kullanmaz)")
    p.add_argument("--kaynak", required=True, help="kaynak_zinciri.py çıktısı")
    p.add_argument("--cikti", required=True, help="markdown sonuç dosyası")
    p.add_argument("--adet", type=int, default=10)
    a = p.parse_args()

    with open(a.kaynak, encoding="utf-8") as f:
        kaynak = json.load(f)
    adaylar = haber_adaylari(kaynak, a.adet)
    satirlar = [
        "## Haber görseli testi",
        "",
        "| No | Marka | Başlık | Yöntem | Sayfa | Görsel | Not |",
        "|---|---|---|---|---|---|---|",
    ]
    bulunan = 0
    for n, h in enumerate(adaylar, 1):
        r = gorsel_dene(h["url"])
        bulunan += r["gorsel"] == "var"
        baslik = h["metin"].rsplit(" - ", 1)[0][:50].replace("|", "/")
        satirlar.append(f"| {n} | {h['marka']} | {baslik} | {r['yontem']} | {r['sayfa']} | {r['gorsel']} | {r['not']} |")
    satirlar += ["", f"**Görsel bulunan: {bulunan} / {len(adaylar)}**"]
    metin = "\n".join(satirlar) + "\n"
    with open(a.cikti, "w", encoding="utf-8") as f:
        f.write(metin)
    print(metin)


if __name__ == "__main__":
    main()
