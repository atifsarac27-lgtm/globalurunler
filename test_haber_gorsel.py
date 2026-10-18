"""haber_gorsel.py testleri. Ağ kullanmaz."""
import unittest

import haber_gorsel as hg


class HaberGorselTesti(unittest.TestCase):
    def test_og_image_bulunur_ozellik_sirasi_fark_etmez(self):
        sayfa = '<meta content="https://site.com/a.jpg" property="og:image">'
        self.assertEqual(hg.og_gorsel(sayfa, "https://site.com/haber"), "https://site.com/a.jpg")

    def test_goreli_adres_mutlak_yapilir(self):
        sayfa = '<meta property="og:image" content="/img/a.jpg">'
        self.assertEqual(hg.og_gorsel(sayfa, "https://site.com/haber/1"), "https://site.com/img/a.jpg")

    def test_twitter_image_yedek_olarak_kullanilir(self):
        sayfa = '<meta name="twitter:image" content="https://site.com/t.jpg">'
        self.assertEqual(hg.og_gorsel(sayfa, "https://site.com/"), "https://site.com/t.jpg")

    def test_gorsel_yoksa_bos(self):
        self.assertEqual(hg.og_gorsel("<html></html>", "https://site.com/"), "")

    def test_google_gorseli_kabul_edilmez(self):
        self.assertFalse(hg.gorsel_uygun("https://www.google.com/logo.png"))
        self.assertFalse(hg.gorsel_uygun("https://lh3.googleusercontent.com/x"))
        self.assertTrue(hg.gorsel_uygun("https://site.com/a.jpg"))

    def test_adres_yoksa_indirme_yapilmaz(self):
        from pathlib import Path
        self.assertEqual(hg.gorsel_kaydet({"url": ""}, Path(".")), "")


if __name__ == "__main__":
    unittest.main()
