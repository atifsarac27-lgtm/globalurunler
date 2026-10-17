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


if __name__ == "__main__":
    unittest.main()
