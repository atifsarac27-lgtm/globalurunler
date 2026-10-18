"""Haber kartları için görsel çeker: haber sayfasındaki paylaşım görselini (og:image) indirir.

Kullanım:
    python haber_gorsel.py --haber rapor/haber_urunleri.json --kok rapor

Kurallar:
- Her haberin bağlantısı açılır, sayfadaki og:image (yoksa twitter:image) bulunur ve indirilir.
- Görsel bulunamazsa haber kartında kaynak sitesinin adı gösterilir.
- Google'ın kendi görselleri kabul edilmez.
- Her haber için "gorsel" alanı yazılır (kök klasöre göre yol, ör. "haber_gorseller/ab12.jpg").
"""
import argparse
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = "Mozilla/5.0 (compatible; GlobalUrunRadar/1.0)"
ZAMAN_ASIMI = 15
EN_FAZLA_BAYT = 3_000_000
UZANTI = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
META_RE = re.compile(r"<meta\s[^>]*?>", re.I)
ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*[\"']([^\"']*)[\"']")


def indir(url, azami=EN_FAZLA_BAYT):
    """Adresi indirir. (veri, içerik türü, son adres) döndürür; yönlendirmeleri izler."""
    istek = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI) as yanit:
        return yanit.read(azami), yanit.headers.get("Content-Type", ""), yanit.geturl()


def og_gorsel(sayfa, taban):
    """Sayfadaki paylaşım görselinin mutlak adresini döndürür; yoksa boş metin."""
    adaylar = {}
    for etiket in META_RE.findall(sayfa):
        ozellik = {k.lower(): v for k, v in ATTR_RE.findall(etiket)}
        icerik = ozellik.get("content", "").strip()
        if not icerik:
            continue
        if ozellik.get("property", "").lower() == "og:image":
            adaylar.setdefault("og", icerik)
        elif ozellik.get("name", "").lower() == "twitter:image":
            adaylar.setdefault("twitter", icerik)
    secilen = adaylar.get("og") or adaylar.get("twitter") or ""
    return urllib.parse.urljoin(taban, secilen) if secilen else ""


def gorsel_uygun(adres):
    """Google'ın kendi görsellerini (logo vb.) elemek için."""
    if not adres:
        return False
    alan = urllib.parse.urlparse(adres).netloc.lower()
    return "google" not in alan and "gstatic" not in alan


def gorsel_kaydet(haber, klasor):
    """Haberin görselini indirir. Bulunursa kök klasöre göre yolunu, bulunamazsa boş metni döndürür."""
    adres = haber.get("url") or ""
    if not adres:
        return ""
    try:
        sayfa_veri, _, son = indir(adres, azami=1_500_000)
        gorsel_adresi = og_gorsel(sayfa_veri.decode("utf-8", errors="ignore"), adres)
        if not gorsel_adresi and son != adres:
            gorsel_adresi = og_gorsel(sayfa_veri.decode("utf-8", errors="ignore"), son)
        if not gorsel_uygun(gorsel_adresi):
            return ""
        veri, tur, _ = indir(gorsel_adresi)
        uzanti = UZANTI.get(tur.split(";")[0].strip().lower())
        if not uzanti or len(veri) >= EN_FAZLA_BAYT:
            return ""
        ad = hashlib.sha1(adres.encode("utf-8")).hexdigest()[:12] + uzanti
        (klasor / ad).write_bytes(veri)
        return f"{klasor.name}/{ad}"
    except Exception:  # noqa: BLE001  # Ağ ve site hataları tek haberi atlatır, çalışmayı durdurmaz.
        return ""


def main():
    p = argparse.ArgumentParser(description="Haber kartları için paylaşım görsellerini çeker")
    p.add_argument("--haber", required=True, help="yeni_urun_siniflandir.py çıktısı")
    p.add_argument("--kok", required=True, help="rapor klasörü; görseller bunun altına yazılır")
    p.add_argument("--en-fazla", type=int, default=200)
    a = p.parse_args()
    if not os.path.exists(a.haber):
        print("UYARI: haber dosyası yok, görsel çekilmedi")
        return
    with open(a.haber, encoding="utf-8") as f:
        veri = json.load(f)
    haberler = veri.get("yeni_urun", [])[:a.en_fazla]
    klasor = Path(a.kok) / "haber_gorseller"
    klasor.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as havuz:
        sonuclar = list(havuz.map(lambda h: gorsel_kaydet(h, klasor), haberler))
    for haber, gorsel in zip(haberler, sonuclar):
        haber["gorsel"] = gorsel
    with open(a.haber, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2)
    print(f"Haber görseli bulundu: {sum(1 for g in sonuclar if g)} / {len(haberler)}")


if __name__ == "__main__":
    main()
