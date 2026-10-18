"""Deneme: bir markanın sitesinden ürün adı (görselin alt metni) ve fotoğraf adreslerini çeker. Gemini kullanmaz.

Sayfalar gerçek tarayıcıyla (Playwright) açılır; basit HTTP isteği bazı siteler tarafından engellenir.

Kullanım:
    python foto_denemesi.py --adres https://www.kfcturkiye.com/ --kok rapor/foto_deneme
"""
import argparse
import json
import re
import urllib.parse
from pathlib import Path

from haber_gorsel import ATTR_RE, UZANTI

TARAYICI_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
IMG_RE = re.compile(r"<img\s[^>]*>", re.I)
A_RE = re.compile(r"<a\s[^>]*href=[\"']([^\"']+)[\"']", re.I)
MENU_RE = re.compile(r"menu|menü|urun|ürün|product|new|yeni|burger|chicken|sandwich", re.I)
EN_FAZLA_SAYFA = 4
EN_FAZLA_INDIRME = 12


def gorselleri_ayikla(html, taban):
    """Sayfadaki <img> etiketlerinden mutlak fotoğraf adreslerini ve alt metinlerini çıkarır."""
    sonuc, gorulen = [], set()
    for etiket in IMG_RE.findall(html):
        o = {k.lower(): v for k, v in ATTR_RE.findall(etiket)}
        kaynak = (o.get("src") or o.get("data-src") or o.get("data-lazy-src") or "").strip()
        if not kaynak or kaynak.startswith("data:"):
            continue
        adres = urllib.parse.urljoin(taban, kaynak)
        if adres in gorulen:
            continue
        gorulen.add(adres)
        alt = re.sub(r"\s+", " ", o.get("alt") or o.get("title") or "").strip()
        sonuc.append({"alt": alt, "src": adres})
    return sonuc


def menu_baglantilari(html, taban):
    """Aynı siteye ait, menü ya da yeni ürün gibi görünen bağlantıları döndürür."""
    kok = urllib.parse.urlparse(taban).netloc
    adaylar = []
    for h in A_RE.findall(html):
        adres = urllib.parse.urljoin(taban, h)
        if urllib.parse.urlparse(adres).netloc == kok and MENU_RE.search(adres) and adres not in adaylar:
            adaylar.append(adres)
    return adaylar[:EN_FAZLA_SAYFA]


def sayfa_ac(pg, url):
    pg.goto(url, wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_timeout(2500)
    return pg.content(), pg.url


def main():
    from playwright.sync_api import sync_playwright

    p_arg = argparse.ArgumentParser(description="Marka sitesinden ürün adı ve fotoğraf denemesi")
    p_arg.add_argument("--adres", required=True)
    p_arg.add_argument("--kok", required=True)
    a = p_arg.parse_args()

    kok = Path(a.kok)
    kok.mkdir(parents=True, exist_ok=True)
    rapor = {"adres": a.adres, "sayfalar": [], "gorseller": []}

    with sync_playwright() as p:
        tarayici = p.chromium.launch()
        pg = tarayici.new_page(user_agent=TARAYICI_UA, locale="tr-TR")
        try:
            html, taban = sayfa_ac(pg, a.adres)
        except Exception as e:  # noqa: BLE001
            rapor["hata"] = f"ana sayfa açılamadı: {type(e).__name__}: {str(e)[:150]}"
            (kok / "sonuc.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=2), encoding="utf-8")
            tarayici.close()
            print(rapor["hata"])
            return
        sayfalar = [(taban, html)]
        for link in menu_baglantilari(html, taban):
            try:
                h2, s2 = sayfa_ac(pg, link)
                sayfalar.append((s2, h2))
            except Exception:  # noqa: BLE001
                rapor["sayfalar"].append({"url": link, "durum": "açılamadı"})

        tum = []
        for s_url, s_html in sayfalar:
            gorseller = gorselleri_ayikla(s_html, s_url)
            rapor["sayfalar"].append({"url": s_url, "img_sayisi": len(gorseller),
                                      "alt_metinli": sum(1 for g in gorseller if len(g["alt"]) >= 3)})
            tum += gorseller

        aday = [g for g in tum if len(g["alt"]) >= 3]
        for n, g in enumerate(aday[:EN_FAZLA_INDIRME]):
            try:
                cevap = pg.request.get(g["src"], timeout=30000)
                tur = cevap.headers.get("content-type", "")
                uzanti = UZANTI.get(tur.split(";")[0].strip().lower())
                if cevap.status != 200 or not uzanti:
                    g.update({"durum": f"uygun değil (HTTP {cevap.status}, {tur[:30]})"})
                    continue
                veri = cevap.body()
                ad = f"img_{n:02d}{uzanti}"
                (kok / ad).write_bytes(veri)
                g.update({"durum": "indirildi", "dosya": ad, "bayt": len(veri)})
            except Exception as e:  # noqa: BLE001
                g.update({"durum": f"indirilemedi: {type(e).__name__}"})
        tarayici.close()

    rapor["gorseller"] = aday[:EN_FAZLA_INDIRME]
    rapor["toplam_img"] = len(tum)
    rapor["alt_metinli_img"] = len(aday)
    if len(tum) < 5:
        rapor["not"] = "Az görsel var; sayfa büyük ihtimalle JavaScript ile yükleniyor."
    (kok / "sonuc.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Toplam görsel: {len(tum)}, alt metinli: {len(aday)}, indirilen: "
          f"{sum(1 for g in rapor['gorseller'] if g.get('durum') == 'indirildi')}")


if __name__ == "__main__":
    main()
