"""foto_denemesi.py ayrıştırma testleri. Ağ kullanmaz."""
import unittest

import foto_denemesi as fd


class FotoDenemesiTesti(unittest.TestCase):
    def test_alt_metni_ve_mutlak_adres(self):
        html = '<img src="/img/tavuk.png" alt="Crispy Tavuk Menü">'
        sonuc = fd.gorselleri_ayikla(html, "https://site.com/menu")
        self.assertEqual(sonuc, [{"alt": "Crispy Tavuk Menü", "src": "https://site.com/img/tavuk.png"}])

    def test_data_src_yedek_olarak_kullanilir(self):
        html = '<img data-src="https://cdn.site.com/a.jpg" alt="Burger">'
        self.assertEqual(fd.gorselleri_ayikla(html, "https://site.com/")[0]["src"], "https://cdn.site.com/a.jpg")

    def test_base64_ve_tekrar_atlanir(self):
        html = ('<img src="data:image/gif;base64,AAA" alt="x">'
                '<img src="/a.jpg" alt="Ürün">'
                '<img src="/a.jpg" alt="Ürün">')
        self.assertEqual(len(fd.gorselleri_ayikla(html, "https://site.com/")), 1)

    def test_menu_baglantilari_ayni_site_ve_anahtar_kelime(self):
        html = ('<a href="/menu/burger">a</a><a href="https://dis.com/menu">b</a>'
                '<a href="/hakkimizda">c</a>')
        self.assertEqual(fd.menu_baglantilari(html, "https://site.com/"), ["https://site.com/menu/burger"])


if __name__ == "__main__":
    unittest.main()
