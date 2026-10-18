"""birlestir_pdf.py testleri. Ağ kullanmaz; PDF testi yerel Chromium gerektirir."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import birlestir_pdf as bp


VERI = {"tum": [
    {"sinif": "ulke", "marka": "KFC", "ulke": "Japonya", "ad": "Yeni Go Bucket", "aciklama": "Tavuk",
     "kaynaklar": [{"adres": "https://www.kfc.jp/x"}], "tespit_tarihi": "2026-10-13"},
    {"sinif": "dunya", "marka": "KFC", "ulke": "Dünya", "ad": "Global menü", "kaynaklar": []},
]}
HABER = {"yeni_urun": [
    {"metin": "Popeyes launches new biscuit - Nation's Restaurant News", "url": "https://n/1",
     "marka_site": "Popeyes", "ulke_tespit": "ABD", "tarih": "2026-10-10"},
]}


class BirlestirPdfTesti(unittest.TestCase):
    def test_haber_kaynagi_basliktan_ayrilir(self):
        self.assertEqual(bp.haber_kaynagi("Yeni ürün - Hürriyet"), ("Yeni ürün", "Hürriyet"))

    def test_haber_kaynagi_yoksa_bos_doner(self):
        self.assertEqual(bp.haber_kaynagi("Sadece başlık"), ("Sadece başlık", ""))

    def test_resmi_yalnizca_ulke_sinifi(self):
        self.assertEqual(len(bp.resmi_urunleri(VERI)), 1)

    def test_resmi_etiketi_ve_kaynak_adi(self):
        u = bp.resmi_urunleri(VERI)[0]
        self.assertEqual(u["etiket"], "Resmi site")
        self.assertEqual(u["kaynak_adi"], "kfc.jp")

    def test_haber_marka_ulke_ve_kaynak(self):
        u = bp.haber_urunleri(HABER)[0]
        self.assertEqual(u["etiket"], "Haber")
        self.assertEqual(u["marka"], "Popeyes")
        self.assertEqual(u["ulke"], "ABD")
        self.assertEqual(u["kaynak_adi"], "Nation's Restaurant News")

    def test_tarih_turkce_yazilir(self):
        self.assertEqual(bp.tr_tarih("2026-10-13"), "13 Ekim 2026")
        self.assertEqual(bp.tr_tarih(""), "")

    def test_her_kartta_kaynak_yazar(self):
        urunler = bp.resmi_urunleri(VERI) + bp.haber_urunleri(HABER)
        with tempfile.TemporaryDirectory() as d:
            html_metni = bp.rapor_html(urunler, Path(d), date(2026, 8, 19), date(2026, 10, 18), 60, [])
        self.assertIn("Kaynak: Resmi site", html_metni)
        self.assertIn("Kaynak: Haber", html_metni)
        self.assertIn("tespit 13 Ekim 2026", html_metni)

    def test_markalar_radar_sirasinda(self):
        urunler = bp.resmi_urunleri(VERI) + bp.haber_urunleri(HABER)
        with tempfile.TemporaryDirectory() as d:
            html_metni = bp.rapor_html(urunler, Path(d), date(2026, 8, 19), date(2026, 10, 18), 60, [])
        self.assertLess(html_metni.index("<h2>Popeyes"), html_metni.index("<h2>KFC"))

    def test_veri_olmayan_marka_bulunamadi_yazar(self):
        urunler = bp.resmi_urunleri(VERI) + bp.haber_urunleri(HABER)
        with tempfile.TemporaryDirectory() as d:
            html_metni = bp.rapor_html(urunler, Path(d), date(2026, 8, 19), date(2026, 10, 18), 60, [])
        self.assertIn("<h2>Sbarro", html_metni)
        self.assertIn("bulunamadı", html_metni)

    def test_haber_ulkesi_yalnizca_basliktan_gelir(self):
        haber = {"yeni_urun": [{"metin": "Popeyes yeni tavuk - X", "url": "https://n/2",
                                "marka_site": "Popeyes", "ulke": "Kanada"}]}
        self.assertEqual(bp.haber_urunleri(haber)[0]["ulke"], bp.BILINMEYEN_ULKE)

    def test_ulke_adi_belirsizse_bilinmeyen(self):
        self.assertEqual(bp.ulke_adi("belirsiz"), bp.BILINMEYEN_ULKE)
        self.assertEqual(bp.ulke_adi(""), bp.BILINMEYEN_ULKE)
        self.assertEqual(bp.ulke_adi("Singapur"), "Singapur")

    def test_haber_gorseli_varsa_resim_yazilir(self):
        with tempfile.TemporaryDirectory() as d:
            kok = Path(d)
            (kok / "haber_gorseller").mkdir()
            (kok / "haber_gorseller" / "a.jpg").write_bytes(b"\xff\xd8\xff")
            haber = {"yeni_urun": [{"metin": "Popeyes yeni tavuk - Hürriyet", "url": "https://h/1",
                                    "marka_site": "Popeyes", "ulke_tespit": "Türkiye",
                                    "gorsel": "haber_gorseller/a.jpg"}]}
            kart = bp.kart_html(bp.haber_urunleri(haber)[0], kok)
        self.assertIn("<img src=", kart)

    def test_haber_gorseli_yoksa_kaynak_sitesi_adi_yazar(self):
        with tempfile.TemporaryDirectory() as d:
            kart = bp.kart_html(bp.haber_urunleri(HABER)[0], Path(d))
        self.assertIn('class="gorsel hab">Nation', kart)
        self.assertNotIn("<img", kart)

    def test_haber_kutusu_tur_ad_ve_marka_rengi(self):
        haber = {"yeni_urun": [{"metin": "Burger King nugget yenilendi - X", "url": "https://h/9",
                                "marka_site": "Burger King", "ulke_tespit": "ABD",
                                "urun_turu": "nugget", "urun_adi": "Le Nugguette",
                                "aciklama": "Nugget'a yeni bir dokunuş geldi."}]}
        kart = bp.kart_html(bp.haber_urunleri(haber)[0], Path("."))
        self.assertIn('class="gorsel mkt"', kart)
        self.assertIn("background:#D62300", kart)
        self.assertIn("YENİ NUGGET", kart)
        self.assertIn("Le Nugguette", kart)
        self.assertIn("BURGER KİNG", kart)
        self.assertNotIn("<img", kart)

    def test_turkce_buyuk_harf(self):
        self.assertEqual(bp.tr_buyuk("içecek"), "İÇECEK")
        self.assertEqual(bp.tr_buyuk("sandviç"), "SANDVİÇ")

    def test_ulke_basliklari_marka_icinde_sirali(self):
        haber = {"yeni_urun": [
            {"metin": "Popeyes yeni A - X", "url": "https://h/1", "marka_site": "Popeyes", "ulke_tespit": "Singapur"},
            {"metin": "Popeyes yeni B - Y", "url": "https://h/2", "marka_site": "Popeyes", "ulke_tespit": "belirsiz"},
            {"metin": "Popeyes yeni C - Z", "url": "https://h/3", "marka_site": "Popeyes", "ulke_tespit": "Japonya"},
        ]}
        with tempfile.TemporaryDirectory() as d:
            html_metni = bp.rapor_html(bp.haber_urunleri(haber), Path(d), date(2026, 8, 19), date(2026, 10, 18), 60, [])
        japonya = html_metni.index('<h3 class="ulke">Japan')
        singapur = html_metni.index('<h3 class="ulke">Singapore')
        bilinmeyen = html_metni.index(f'<h3 class="ulke">{bp.BILINMEYEN_ULKE_EN}')
        self.assertLess(japonya, singapur)
        self.assertLess(singapur, bilinmeyen)

    def test_pdf_dosyasi_uretilir(self):
        urunler = bp.resmi_urunleri(VERI) + bp.haber_urunleri(HABER)
        try:
            with tempfile.TemporaryDirectory() as d:
                hedef = Path(d) / "birlesik.pdf"
                html_metni = bp.rapor_html(urunler, Path(d), date(2026, 8, 19), date(2026, 10, 18), 60, [])
                bp.pdf_yaz(html_metni, hedef, "test")
                self.assertTrue(hedef.exists())
                self.assertEqual(hedef.read_bytes()[:4], b"%PDF")
        except ImportError:
            self.skipTest("Playwright kurulu değil")


class YeniKurallarTesti(unittest.TestCase):
    def test_ulke_adlari_ingilizce(self):
        self.assertEqual(bp.ulke_goster("Çin"), "China")
        self.assertEqual(bp.ulke_goster("Türkiye"), "Turkey")
        self.assertEqual(bp.ulke_goster(bp.BILINMEYEN_ULKE), bp.BILINMEYEN_ULKE_EN)
        self.assertEqual(bp.ulke_goster("Listede yok"), "Listede yok")

    def test_haber_ulkesi_aciklama_once(self):
        self.assertEqual(bp.haber_ulkesi("Singapur", "Milenio", "x"), "Singapur")

    def test_haber_ulkesi_yayin_adindan(self):
        self.assertEqual(bp.haber_ulkesi("belirsiz", "Milenio", "Subway lanza un pan"), "Meksika")
        self.assertEqual(bp.haber_ulkesi("belirsiz", "Yahoo Finance", "Popeyes sandwich"), "ABD")

    def test_haber_ulkesi_yazi_dilinden(self):
        self.assertEqual(bp.haber_ulkesi("belirsiz", "", "【大食い】ケンタッキーのバーガー"), "Japonya")
        self.assertEqual(bp.haber_ulkesi("belirsiz", "", "KFC yeni menü"), bp.BILINMEYEN_ULKE)

    def test_haber_urunleri_ulke_tahmini_kaynaktan(self):
        haber = {"yeni_urun": [{"metin": "Popeyes Just Launched A New Sandwich - Yahoo Finance",
                                "url": "https://n/5", "marka_site": "Popeyes", "ulke_tespit": "belirsiz"}]}
        self.assertEqual(bp.haber_urunleri(haber)[0]["ulke"], "ABD")

    def test_kisalt_kelime_sinirinda_keser(self):
        self.assertEqual(bp.kisalt("aaaa bbbb cccc dddd", 12), "aaaa bbbb…")
        self.assertEqual(bp.kisalt("kısa", 12), "kısa")

    def test_latin_orani(self):
        self.assertEqualFloat(bp.latin_orani("Gochujang"), 1.0)
        self.assertEqualFloat(bp.latin_orani("ザクタル"), 0.0)

    def assertEqualFloat(self, a, b):
        self.assertAlmostEqual(a, b, places=6)

    def test_latin_olmayan_resmi_ad_altta_kalir(self):
        u = {"etiket": bp.RESMI, "marka": "Subway", "ulke": "Japonya", "ad": "ザクタル",
             "aciklama": "Sonbahara özel sandviç.", "tarih": "2026-10-12", "gorsel_yolu": "",
             "adres": "https://subway.co.jp", "kaynak_adi": "subway.co.jp"}
        kart = bp.kart_html(u, Path("."))
        self.assertIn('<div class="ad">Sonbahara özel sandviç.</div>', kart)
        self.assertIn('<div class="ac">ザクタル</div>', kart)

    def test_latin_haber_kutusu_urun_adi_kullanir(self):
        haber = {"yeni_urun": [{"metin": "KFC yeni - X", "url": "https://h/3", "marka_site": "KFC",
                                "ulke_tespit": "ABD", "urun_turu": "menü", "urun_adi": "Go Buckets",
                                "aciklama": "Yeni kova."}]}
        kart = bp.kart_html(bp.haber_urunleri(haber)[0], Path("."))
        self.assertIn('<div class="ua">Go Buckets</div>', kart)

    def test_sbarro_tek_urunde_uyari_verir(self):
        self.assertIn("1 ürün", bp.sbarro_uyarisi([{"marka": "Sbarro"}]))
        self.assertEqual(bp.sbarro_uyarisi([{"marka": "Sbarro"}, {"marka": "Sbarro"}]), "")

    def test_gecerli_gorsel_sinami(self):
        self.assertTrue(bp.gecerli_gorsel_mi(b"\x89PNG\r\n\x1a\n" + b"0" * 8))
        self.assertTrue(bp.gecerli_gorsel_mi(b"RIFF\x00\x00\x00\x00WEBPVP8 "))
        self.assertTrue(bp.gecerli_gorsel_mi(b'<?xml version="1.0"?><svg xmlns="x"></svg>'))
        self.assertFalse(bp.gecerli_gorsel_mi(b"<html><body>Hata</body></html>"))

    def test_bozuk_logo_yazilmaz(self):
        with tempfile.TemporaryDirectory() as d:
            kok = Path(d)
            (kok / "logolar").mkdir()
            (kok / "logolar" / "popeyes.png").write_bytes(b"<html>hata</html>")
            self.assertEqual(bp.marka_logosu("Popeyes", kok), "")

    def test_kapakta_haber_suresi_30_gun(self):
        with tempfile.TemporaryDirectory() as d:
            html_metni = bp.rapor_html([], Path(d), date(2026, 7, 20), date(2026, 10, 18), 90, [])
        self.assertIn("son 90 günde", html_metni)
        self.assertIn("son 30 günde", html_metni)

    def test_yeni_kaynaklar_ulke_verir(self):
        self.assertEqual(bp.haber_ulkesi(None, "Roastbrief US", "x"), "ABD")
        self.assertEqual(bp.haber_ulkesi(None, "Roastbrief", "x"), "ABD")
        self.assertEqual(bp.haber_ulkesi(None, "Chowhound", "x"), "ABD")
        self.assertEqual(bp.haber_ulkesi(None, "CHIP", "Fast-Food-Konzern"), "Almanya")
        self.assertEqual(bp.haber_ulkesi(None, "AFR", "Size matters"), "Avustralya")

    def test_ulkeler_ayni_satirda_yan_yana(self):
        html_metni = bp.satirlara_diz([("Japan", ["<k1>"]), ("Singapore", ["<k2>"]), ("Turkey", ["<k3>", "<k4>"])])
        self.assertEqual(html_metni.count('class="satir"'), 1)
        self.assertIn('<h3 class="ulke">Turkey', html_metni)

    def test_sigmayan_ulke_yeni_satira_gecer(self):
        html_metni = bp.satirlara_diz([("A", ["<k>"] * 3), ("B", ["<k>"] * 2)])
        self.assertEqual(html_metni.count('class="satir"'), 2)

    def test_buyuk_ulke_parcalara_bolunur(self):
        html_metni = bp.satirlara_diz([("Japan", ["<k>"] * 5)])
        self.assertEqual(html_metni.count('class="satir"'), 2)
        self.assertIn(">5 ürün<", html_metni)
        self.assertIn(">devamı<", html_metni)


if __name__ == "__main__":
    unittest.main()
