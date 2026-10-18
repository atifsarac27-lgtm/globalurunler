"""logo_indir.py ve marka logosu testleri. Ağ kullanmaz."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

import birlestir_pdf as bp
import logo_indir as li


class LogoTesti(unittest.TestCase):
    def test_apple_touch_icon_once_secilir(self):
        sayfa = ('<link rel="icon" href="/f.png">'
                 '<link rel="apple-touch-icon" href="/a.png">')
        self.assertEqual(li.ikon_adaylari(sayfa, "https://s.com/")[0], "https://s.com/a.png")

    def test_goreli_adres_mutlak_yapilir(self):
        sayfa = '<link rel="shortcut icon" href="img/logo.svg">'
        self.assertEqual(li.ikon_adaylari(sayfa, "https://s.com/tr/")[0], "https://s.com/tr/img/logo.svg")

    def test_etiket_yoksa_yedek_adresler_denenir(self):
        adaylar = li.ikon_adaylari("<html></html>", "https://s.com/")
        self.assertIn("https://s.com/favicon.ico", adaylar)

    def test_marka_adresleri_tum_siteleri_sirayla_verir(self):
        veri = {"siteler": [{"marka": "KFC", "adres": "https://kfc.a/"},
                            {"marka": "KFC", "adres": "https://kfc.b/"},
                            {"marka": "Subway", "adres": "https://sub.a/"}]}
        self.assertEqual(li.marka_adresleri(veri),
                         {"KFC": ["https://kfc.a/", "https://kfc.b/"], "Subway": ["https://sub.a/"]})

    def test_marka_slug_turkce_ve_kesme_isaretli(self):
        self.assertEqual(bp.marka_slug("Burger King"), "burger-king")
        self.assertEqual(bp.marka_slug("McDonald's"), "mcdonalds")
        self.assertEqual(bp.marka_slug("Arby's"), "arbys")

    def test_logo_dosyasi_varsa_basliga_eklenir(self):
        haber = {"yeni_urun": [{"metin": "Burger King yeni - X", "url": "https://h/1",
                                "marka_site": "Burger King", "ulke_tespit": "ABD"}]}
        urunler = bp.haber_urunleri(haber)
        with tempfile.TemporaryDirectory() as d:
            kok = Path(d)
            (kok / "logolar").mkdir()
            (kok / "logolar" / "burger-king.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
            html_metni = bp.marka_bolumu("Burger King", urunler, kok)
        self.assertIn('<img class="logo"', html_metni)
        self.assertLess(html_metni.index('<img class="logo"'), html_metni.index("Burger King"))

    def test_logo_dosyasi_yoksa_baslik_duz_kalir(self):
        with tempfile.TemporaryDirectory() as d:
            html_metni = bp.marka_bolumu("Sbarro", [], Path(d))
        self.assertNotIn("<img", html_metni)
        self.assertIn("<h2>Sbarro", html_metni)

    def test_kapakta_tab_gida_yazar(self):
        with tempfile.TemporaryDirectory() as d:
            html_metni = bp.rapor_html([], Path(d), date(2026, 8, 19), date(2026, 10, 18), 60, [])
        self.assertIn("Tab Gıda Reklam Üssü", html_metni)


if __name__ == "__main__":
    unittest.main()


class KontrolTesti(unittest.TestCase):
    def test_kontrol_ozeti_gorselli_ve_kutulu_sayar(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            kok = Path(d)
            (kok / "gorseller").mkdir()
            (kok / "gorseller" / "a.jpg").write_bytes(b"\xff\xd8")
            urunler = [
                {"etiket": bp.RESMI, "gorsel_yolu": "gorseller/a.jpg", "ek_kaynak": 1, "marka": "KFC"},
                {"etiket": bp.RESMI, "gorsel_yolu": "", "marka": "KFC"},
                {"etiket": bp.HABER, "gorsel_yolu": "", "urun_adi": "Yeni", "marka": "KFC"},
                {"etiket": bp.HABER, "gorsel_yolu": "", "marka": "KFC"},
            ]
            ozet = bp.kontrol_ozeti(urunler, kok)
        self.assertEqual(ozet["resmi_toplam"], 2)
        self.assertEqual(ozet["resmi_gorselli"], 1)
        self.assertEqual(ozet["haber_kutulu"], 1)
        self.assertEqual(ozet["resmiye_bagli_haber"], 1)


class LogoKaydetTesti(unittest.TestCase):
    PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20

    def sahte_al(self, url, azami=0):
        """Ağ yerine sabit yanıtlar: ilk sitenin simgesi HTML hata sayfası, ikinci sitenin simgesi PNG."""
        yanitlar = {
            "https://bad.a/": (b"<html>hata</html>", "text/html"),
            "https://bad.a/apple-touch-icon.png": (b"<html>hata</html>", "image/png"),
            "https://good.b/": (b'<link rel="icon" href="/i.png">', "text/html"),
            "https://good.b/i.png": (self.PNG, "image/png"),
        }
        if url not in yanitlar:
            raise OSError("yok")
        govde, tur = yanitlar[url]
        return govde, tur, url

    def test_hata_sayfasi_kaydedilmez_sonraki_site_denenir(self):
        with tempfile.TemporaryDirectory() as d:
            klasor = Path(d)
            ad = li.logo_kaydet("Popeyes", ["https://bad.a/", "https://good.b/"], klasor, al=self.sahte_al)
            self.assertEqual(ad, "popeyes.png")
            self.assertEqual((klasor / ad).read_bytes(), self.PNG)

    def test_hicbir_site_gecerli_logo_vermezse_bos_doner(self):
        with tempfile.TemporaryDirectory() as d:
            ad = li.logo_kaydet("Popeyes", ["https://bad.a/"], Path(d), al=self.sahte_al)
            self.assertEqual(ad, "")
            self.assertEqual(list(Path(d).iterdir()), [])
