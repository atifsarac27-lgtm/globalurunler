"""Sınıflandırıcı testleri. Gemini çağrısı sahte fonksiyonla değiştirilir."""
import unittest

import yeni_urun_siniflandir as ys


class SiniflandirmaTesti(unittest.TestCase):
    def test_json_ayikla_metin_icindeki_diziyi_bulur(self):
        self.assertEqual(ys.json_ayikla('Tamam: [{"i": 0}]'), [{"i": 0}])

    def test_benzersiz_basliklar_tekrarlari_almaz(self):
        sonuclar = [
            {"sonuc": "haber RSS", "marka": "KFC", "adaylar": [
                {"metin": "KFC launches Big Dip", "url": "u1"}]},
            {"sonuc": "haber RSS", "marka": "KFC", "adaylar": [
                {"metin": "KFC launches Big Dip", "url": "u1", "tekrar": True}]},
            {"sonuc": "resmi site", "marka": "KFC", "adaylar": [
                {"metin": "Menü", "url": "u2"}]},
        ]
        self.assertEqual(len(ys.benzersiz_basliklar(sonuclar)), 1)

    def test_siniflandir_karar_esler_ve_yeni_urunu_secer(self):
        basliklar = [{"metin": "A ürünü", "url": "1", "marka_site": "KFC"},
                     {"metin": "B kampanyası", "url": "2", "marka_site": "KFC"}]
        sahte = lambda istem: '[{"i": 0, "yeni_urun": true, "marka": "KFC"}, {"i": 1, "yeni_urun": false, "marka": "KFC"}]'
        kararlar, uyarilar = ys.siniflandir(basliklar, cagri=sahte)
        self.assertEqual(uyarilar, [])
        self.assertTrue(kararlar[0]["yeni_urun"])
        self.assertFalse(kararlar[1]["yeni_urun"])

    def test_ulke_basliktan_alinir_yoksa_belirsiz(self):
        basliklar = [{"metin": "A", "url": "1", "marka_site": "KFC"},
                     {"metin": "B", "url": "2", "marka_site": "KFC"}]
        sahte = lambda istem: ('[{"i": 0, "yeni_urun": true, "marka": "KFC", "ulke": "Singapur"}, '
                               '{"i": 1, "yeni_urun": true, "marka": "KFC"}]')
        kararlar, _ = ys.siniflandir(basliklar, cagri=sahte)
        self.assertEqual(kararlar[0]["ulke_tespit"], "Singapur")
        self.assertEqual(kararlar[1]["ulke_tespit"], "belirsiz")

    def test_kutu_alanlari_karara_aktarilir(self):
        basliklar = [{"metin": "Nugget yenilendi", "url": "1", "marka_site": "Burger King"}]
        sahte = lambda istem: ('[{"i": 0, "yeni_urun": true, "marka": "Burger King", "ulke": "ABD", '
                               '"urun_turu": "nugget", "urun_adi": "Le Nugguette", '
                               '"aciklama": "Nugget için yeni bir çeşit geldi."}]')
        kararlar, _ = ys.siniflandir(basliklar, cagri=sahte)
        self.assertEqual(kararlar[0]["urun_turu"], "nugget")
        self.assertEqual(kararlar[0]["urun_adi"], "Le Nugguette")
        self.assertEqual(kararlar[0]["aciklama"], "Nugget için yeni bir çeşit geldi.")

    def test_kutu_alanlari_yoksa_bos_kalir(self):
        basliklar = [{"metin": "A", "url": "1", "marka_site": "KFC"}]
        sahte = lambda istem: '[{"i": 0, "yeni_urun": true, "marka": "KFC"}]'
        kararlar, _ = ys.siniflandir(basliklar, cagri=sahte)
        self.assertEqual(kararlar[0]["urun_turu"], "")
        self.assertEqual(kararlar[0]["urun_adi"], "")
        self.assertEqual(kararlar[0]["aciklama"], "")

    def test_cagri_siniri_asilirsa_uyari_verir(self):
        basliklar = [{"metin": f"x{k}", "url": "", "marka_site": "KFC"} for k in range(60)]
        sayac = {"n": 0}
        def sahte(istem):
            sayac["n"] += 1
            return "[]"
        _, uyarilar = ys.siniflandir(basliklar, cagri=sahte, cagri_siniri=2)
        self.assertEqual(sayac["n"], 2)
        self.assertTrue(any("sınırına" in u for u in uyarilar))

    def test_zaman_asimi_cokertmez_diger_gruplar_islenir(self):
        basliklar = [{"metin": f"x{k}", "url": "", "marka_site": "KFC"} for k in range(30)]
        sayac = {"n": 0}
        def sahte(istem):
            sayac["n"] += 1
            if sayac["n"] == 1:
                raise TimeoutError("The read operation timed out")
            return '[{"i": 0, "yeni_urun": true, "marka": "KFC"}]'
        kararlar, uyarilar = ys.siniflandir(basliklar, cagri=sahte, cagri_siniri=2)
        self.assertEqual(sayac["n"], 2)
        self.assertEqual(len(kararlar), 1)
        self.assertTrue(any("TimeoutError" in u for u in uyarilar))


if __name__ == "__main__":
    unittest.main()
