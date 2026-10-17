"""Haber başlıklarını Gemini ile sınıflandırır: yeni ürün haberi mi?

Girdi : kaynak_sonuc.json (kaynak_zinciri.py çıktısı)
Çıktı : yeni_urunler.json (yalnızca "yeni ürün" olarak işaretlenen başlıklar + ham karar listesi)

Ortam değişkeni: GEMINI_API_KEY (anahtarı sohbete ya da dosyaya yazmayın)
İsteğe bağlı   : GEMINI_MODEL (varsayılan radar.py ile aynı), MAX_CAGRI (varsayılan 1: tek çağrı, 25 başlık)

Kullanım (Windows cmd, kaynak_sonuc.json ile aynı klasörde):
    set GEMINI_API_KEY=anahtarınız
    python yeni_urun_siniflandir.py --sonuc kaynak_sonuc.json --cikti yeni_urunler.json
"""
import argparse
import json
import os
import re
import urllib.error
import urllib.request

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
API_KEY = os.environ.get("GEMINI_API_KEY", "")
MAX_CAGRI = int(os.environ.get("MAX_CAGRI") or "1")  # varsayılan: tek çağrı (güvenli deneme)
GRUP_BOYU = 25
ZAMAN_ASIMI = 90

ISTEM = """Aşağıda fast food markalarıyla ilgili haber başlıkları var. Her başlık için karar ver:
- yeni_urun: Başlık somut bir YENİ ürün, yeni menü öğesi, yeni tat/çeşit veya yeni menü lansmanını anlatıyor mu?
  Kampanya, fiyat, mağaza açılışı, hisse/finans, yorum/analiz, şirket haberi, reklam kampanyası, sadakat programı ise false.
- marka: Başlıkta geçen ana marka (Burger King, Popeyes, Arby's, Subway, McDonald's, KFC, Sbarro veya diğer).
Yalnızca şu biçimde JSON dizisi döndür: [{"i": 0, "yeni_urun": true, "marka": "KFC"}, ...]

Başlıklar:
"""


def parti(liste, boy):
    return [liste[k:k + boy] for k in range(0, len(liste), boy)]


def json_ayikla(metin):
    """Model yanıtından JSON dizisini çıkarır."""
    try:
        return json.loads(metin)
    except ValueError:
        eslesme = re.search(r"\[.*\]", metin, re.S)
        if not eslesme:
            raise
        return json.loads(eslesme.group(0))


def gemini_cagri(istem):
    """Gemini generateContent; yanıt metnini döndürür."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    govde = {
        "contents": [{"parts": [{"text": istem}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    istek = urllib.request.Request(
        url, data=json.dumps(govde).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY}, method="POST")
    with urllib.request.urlopen(istek, timeout=ZAMAN_ASIMI) as yanit:
        veri = json.loads(yanit.read().decode("utf-8"))
    return veri["candidates"][0]["content"]["parts"][0]["text"]


def benzersiz_basliklar(sonuclar):
    """Tekrar olmayan haber başlıklarını (site bilgisiyle) sırayla toplar."""
    liste = []
    for s in sonuclar:
        for a in s["adaylar"]:
            if s["sonuc"] == "haber RSS" and not a.get("tekrar"):
                liste.append({"metin": a["metin"], "url": a["url"], "marka_site": s["marka"]})
    return liste


def siniflandir(basliklar, cagri=gemini_cagri, cagri_siniri=MAX_CAGRI):
    """Başlıkları gruplara böler, her gruba bir çağrı yapar. (karar listesi, uyarılar) döndürür."""
    kararlar, uyarilar = [], []
    for n, grup in enumerate(parti(basliklar, GRUP_BOYU)):
        if n >= cagri_siniri:
            uyarilar.append(f"çağrı sınırına ulaşıldı (MAX_CAGRI={cagri_siniri}); kalan başlıklar sınıflandırılmadı")
            break
        satirlar = "\n".join(f"{k}. {b['metin']} ({b['marka_site']})" for k, b in enumerate(grup))
        try:
            yanit = json_ayikla(cagri(ISTEM + satirlar))
        except (urllib.error.URLError, ValueError, KeyError, IndexError, TypeError) as e:
            uyarilar.append(f"grup {n}: {type(e).__name__}: {str(e)[:120]}")
            continue
        for karar in yanit:
            k = karar.get("i")
            if isinstance(k, int) and 0 <= k < len(grup):
                kararlar.append({**grup[k], "yeni_urun": bool(karar.get("yeni_urun")),
                                 "marka": karar.get("marka", "")})
    return kararlar, uyarilar


def main():
    p = argparse.ArgumentParser(description="Haber başlıklarında yeni ürün sınıflandırması")
    p.add_argument("--sonuc", default="kaynak_sonuc.json")
    p.add_argument("--cikti", default="yeni_urunler.json")
    a = p.parse_args()
    if not API_KEY:
        raise SystemExit("HATA: GEMINI_API_KEY tanımlı değil. 'set GEMINI_API_KEY=...' ile tanımlayın.")

    with open(a.sonuc, encoding="utf-8") as f:
        sonuclar = json.load(f)
    basliklar = benzersiz_basliklar(sonuclar)
    kararlar, uyarilar = siniflandir(basliklar)

    yeniler = [k for k in kararlar if k["yeni_urun"]]
    with open(a.cikti, "w", encoding="utf-8") as f:
        json.dump({"yeni_urun": yeniler, "tum_kararlar": kararlar, "uyarilar": uyarilar},
                  f, ensure_ascii=False, indent=2)

    print(f"Sınıflandırılan başlık: {len(kararlar)} / {len(basliklar)}")
    print(f"Yeni ürün olarak işaretlenen: {len(yeniler)}")
    for u in uyarilar:
        print("UYARI:", u)
    print(f"Çıktı: {a.cikti}")


if __name__ == "__main__":
    main()
