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
     "marka_site": "Popeyes", "ulke": "ABD", "tarih": "2026-10-10"},
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


if __name__ == "__main__":
    unittest.main()
