"""Yerel dilde haber araması testleri. Ağ kullanmaz; sorgular sahte yanıtla yapılır."""
import unittest
from unittest import mock

import kaynak_zinciri as kz


def oge(metin, url):
    return {"metin": metin, "url": url, "tarih": "2026-10-10"}


SITE = {"kod": "bk-tr", "marka": "Burger King", "ulke": "Türkiye", "adres": "https://bk.com.tr"}


class YerelHaberTesti(unittest.TestCase):
    def test_yerel_ulkeler_tanimli(self):
        for kod in ["TR", "MX", "BR", "FR", "DE", "KR", "JP", "CN", "SA", "AE"]:
            self.assertIn(kod, kz.YEREL_ARAMA)

    def test_turkce_baslik_yerel_filtreden_gecer(self):
        ogeler = [oge("Burger King yeni menüsünü tanıttı - Hürriyet", "https://h/1")]
        uyum = kz.YEREL_ARAMA["TR"][3]
        self.assertEqual(len(kz.haber_filtrele(ogeler, "Burger King", uyum)), 1)

    def test_kampanya_yerel_dilde_de_elenir(self):
        ogeler = [oge("Burger King yeni menü kampanyası indirim", "https://h/2")]
        uyum = kz.YEREL_ARAMA["TR"][3]
        self.assertEqual(kz.haber_filtrele(ogeler, "Burger King", uyum), [])

    def test_yerel_arama_ingilizce_sonuclara_ek_olur(self):
        ingilizce = [oge("Burger King launches new Whopper - Eater", "https://e/1")]
        yerel = [oge("Burger King yeni menüsünü tanıttı - Hürriyet", "https://h/1"),
                 oge("Burger King launches new Whopper - Eater", "https://e/1")]

        def sahte(marka, hl, gl, ceid, terimler):
            return (ingilizce, "") if hl == "en-US" else (yerel, "")

        with mock.patch.object(kz, "haber_sorgula", side_effect=sahte):
            durum, _, ogeler = kz.katman_haber(SITE, {})
        self.assertEqual(durum, "ok")
        self.assertEqual(sorted(o["url"] for o in ogeler), ["https://e/1", "https://h/1"])

    def test_yerel_arama_hata_verirse_ingilizce_kalir(self):
        ingilizce = [oge("Burger King launches new Whopper - Eater", "https://e/1")]

        def sahte(marka, hl, gl, ceid, terimler):
            return (ingilizce, "") if hl == "en-US" else (None, "zaman aşımı")

        with mock.patch.object(kz, "haber_sorgula", side_effect=sahte):
            durum, _, ogeler = kz.katman_haber(SITE, {})
        self.assertEqual(durum, "ok")
        self.assertEqual(len(ogeler), 1)

    def test_yerel_ulke_yoksa_tek_sorgu_yapilir(self):
        site = dict(SITE, kod="xx-us", ulke="ABD")
        with mock.patch.object(kz, "haber_sorgula", return_value=([], "")) as m:
            kz.katman_haber(site, {})
        self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()
