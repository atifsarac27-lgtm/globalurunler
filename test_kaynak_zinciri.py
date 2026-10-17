"""Kaynak zinciri testleri. Ağ kullanmaz; indir() sahte yanıtla değiştirilir."""
import unittest
from datetime import datetime, timezone
from unittest import mock

import kaynak_zinciri as kz

SITE = {"kod": "pop-th", "marka": "Popeyes", "ulke": "Tayland", "adres": "https://example.com/"}
RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Popeyes launches new chicken</title><link>https://n/1</link>
<pubDate>Thu, 15 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Popeyes old news</title><link>https://n/2</link>
<pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def sahte_ag(url, *a, **k):
    if url.startswith("https://example.com/press"):
        return True, '<a href="/y">Popeyes yeni tavuk</a>'
    if url.startswith("https://example.com/"):
        return True, '<p>Hoş geldiniz</p><a href="/press">Press</a>'
    if "web.archive.org" in url:
        return True, "[]"
    return False, "HTTP 403"


class ZincirTesti(unittest.TestCase):
    def test_resmi_site_bulunca_sonraki_katmana_gecilmez(self):
        ana = '<a href="/yeni-menu">Yeni menü</a>'
        with mock.patch.object(kz, "indir", side_effect=lambda u, *a, **k: (True, ana)):
            s = kz.zincir(SITE)
        self.assertEqual(s["sonuc"], "resmi site")
        self.assertEqual([d["katman"] for d in s["denemeler"]], ["resmi site"])

    def test_resmi_site_bos_ise_basina_gecer(self):
        with mock.patch.object(kz, "indir", side_effect=sahte_ag):
            s = kz.zincir(SITE)
        self.assertEqual(s["sonuc"], "basın odası")
        self.assertEqual([d["durum"] for d in s["denemeler"]], ["yok", "ok"])

    def test_hepsi_basarisizsa_her_katman_denenir_ve_neden_kaydedilir(self):
        def hep_403(url, *a, **k):
            return False, "HTTP 403"
        with mock.patch.object(kz, "indir", side_effect=hep_403):
            s = kz.zincir(SITE)
        self.assertEqual(s["sonuc"], "hiçbiri")
        self.assertEqual([d["katman"] for d in s["denemeler"]], ["resmi site", "basın odası", "haber RSS"])
        self.assertTrue(all(d["ayrinti"] for d in s["denemeler"]))

    def test_rss_yalnizca_son_60_gunu_alir(self):
        simdi = datetime(2026, 10, 17, tzinfo=timezone.utc)
        ogeler = kz.rss_ogeleri(RSS, simdi)
        self.assertEqual(len(ogeler), 1)
        self.assertIn("launches", ogeler[0]["metin"])


class EslesmeTesti(unittest.TestCase):
    def test_menu_linkleri_aday_degil(self):
        html = '<a href="/news">News</a><a href="/anasayfa">Anasayfa</a><a href="/nl">Newsletter</a>'
        self.assertEqual(kz.aday_bul(html, "https://example.com/"), [])

    def test_gercek_yeni_urun_linki_aday(self):
        html = '<a href="/x">New chicken wrap</a><a href="/y">Popeyes yeni tavuk</a>'
        adaylar = kz.aday_bul(html, "https://example.com/", "Popeyes")
        self.assertEqual(len(adaylar), 2)

    def test_urunsuz_haber_elenir(self):
        rss = """<?xml version="1.0"?><rss><channel>
        <item><title>Subway train crash in New York</title><link>https://n/1</link>
        <pubDate>Thu, 15 Oct 2026 10:00:00 GMT</pubDate></item>
        <item><title>Subway launches new chicken sandwich</title><link>https://n/2</link>
        <pubDate>Thu, 15 Oct 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>"""
        sahte = lambda url, *a, **k: (True, rss)
        with mock.patch.object(kz, "indir", side_effect=sahte):
            durum, _, adaylar = kz.katman_haber({"kod": "s", "marka": "Subway", "ulke": "Türkiye",
                                                  "adres": None}, {})
        self.assertEqual(durum, "ok")
        self.assertEqual(len(adaylar), 1)
        self.assertIn("chicken", adaylar[0]["metin"])

    def test_kampanya_ve_magaza_haberi_elenir_urun_haberi_kalir(self):
        rss = """<?xml version="1.0"?><rss><channel>
        <item><title>Burger King opens new store in Surrey</title><link>https://n/1</link>
        <pubDate>Thu, 15 Oct 2026 10:00:00 GMT</pubDate></item>
        <item><title>Burger King giving away free Whoppers</title><link>https://n/2</link>
        <pubDate>Thu, 15 Oct 2026 10:00:00 GMT</pubDate></item>
        <item><title>Burger King launches new chicken nuggets</title><link>https://n/3</link>
        <pubDate>Thu, 15 Oct 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>"""
        sahte = lambda url, *a, **k: (True, rss)
        with mock.patch.object(kz, "indir", side_effect=sahte):
            durum, _, adaylar = kz.katman_haber({"kod": "b", "marka": "Burger King", "ulke": "ABD",
                                                  "adres": None}, {})
        self.assertEqual(len(adaylar), 1)
        self.assertIn("nuggets", adaylar[0]["metin"])

    def test_ulke_kodu_site_kodundan_ve_uk_gb(self):
        self.assertEqual(kz.ulke_kodu({"kod": "kfc-cn"}), "CN")
        self.assertEqual(kz.ulke_kodu({"kod": "bk-uk"}), "GB")

    def test_haber_sorgusu_ulkeye_ozel(self):
        vars_ = {}
        def yakala(url, *a, **k):
            vars_["url"] = url
            return True, "<rss><channel></channel></rss>"
        with mock.patch.object(kz, "indir", side_effect=yakala):
            kz.katman_haber({"kod": "kfc-cn", "marka": "KFC", "ulke": "Çin", "adres": None}, {})
        self.assertIn("gl=CN", vars_["url"])
        self.assertIn("ceid=CN%3Aen", vars_["url"])

    def test_ayni_baslik_ikinci_kez_tekrar_sayilir(self):
        sonuclar = [
            {"adaylar": [{"metin": "KFC launches Big Dip"}]},
            {"adaylar": [{"metin": "KFC launches Big Dip"}, {"metin": "Popeyes new biscuit"}]},
        ]
        kz.tekillestir(sonuclar)
        self.assertFalse(sonuclar[0]["adaylar"][0]["tekrar"])
        self.assertTrue(sonuclar[1]["adaylar"][0]["tekrar"])
        self.assertFalse(sonuclar[1]["adaylar"][1]["tekrar"])


if __name__ == "__main__":
    unittest.main()
