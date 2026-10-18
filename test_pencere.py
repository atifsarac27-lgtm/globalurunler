"""Dönem penceresi, Sbarro kuralı ve haber tekrarı testleri. Ağ kullanmaz."""
import unittest
from datetime import date, timedelta
from email.utils import format_datetime
from datetime import datetime, timezone

import birlestir_pdf as bp
import kaynak_zinciri as kz

BIT = date(2026, 10, 18)


def haber(marka, ad, gun_once, ek=None):
    u = {"marka": marka, "ad": ad, "tarih": (BIT - timedelta(days=gun_once)).isoformat(), "etiket": bp.HABER}
    if ek:
        u["ek_kaynak"] = ek
    return u


class PencereTesti(unittest.TestCase):
    def test_geriye_gun_sbarro_ozel(self):
        self.assertEqual(kz.geriye_gun("Sbarro"), 180)
        self.assertEqual(kz.geriye_gun("KFC"), kz.GERIYE_GUN)

    def test_rss_gun_parametresi_pencereyi_degistirir(self):
        simdi = datetime(2026, 10, 18, tzinfo=timezone.utc)
        def oge(gun_once, baslik):
            return (f"<item><title>{baslik}</title><link>https://x/{gun_once}</link>"
                    f"<pubDate>{format_datetime(simdi - timedelta(days=gun_once))}</pubDate></item>")
        xml = f"<rss><channel>{oge(10, 'Yeni A')}{oge(100, 'Yeni B')}</channel></rss>"
        self.assertEqual(len(kz.rss_ogeleri(xml, simdi)), 1)
        self.assertEqual(len(kz.rss_ogeleri(xml, simdi, gun=180)), 2)

    def test_haber_son_1_ay(self):
        haberler = [haber("Popeyes", "A yeni", 10), haber("Popeyes", "B yeni", 40)]
        sonuc = bp.haber_penceresi(haberler, BIT)
        self.assertEqual([u["ad"] for u in sonuc], ["A yeni"])

    def test_resmi_eslesen_haber_ayrik_kart_olmaz(self):
        resmi = [{"marka": "KFC", "ad": "Go Bucket", "ek_kaynak": 0}]
        haberler = [haber("KFC", "KFC Go Bucket is back in Canada", 3),
                    haber("KFC", "KFC yeni kola tanıtıldı", 3)]
        resmi_son, kalan = bp.haberleri_resmiye_bagla(resmi, haberler)
        self.assertEqual(resmi_son[0]["ek_kaynak"], 1)
        self.assertEqual([u["ad"] for u in kalan], ["KFC yeni kola tanıtıldı"])

    def test_farkli_markadaki_eslesme_baglanmaz(self):
        resmi = [{"marka": "Subway", "ad": "Go Bucket", "ek_kaynak": 0}]
        haberler = [haber("KFC", "KFC Go Bucket is back", 3)]
        resmi_son, kalan = bp.haberleri_resmiye_bagla(resmi, haberler)
        self.assertEqual(resmi_son[0]["ek_kaynak"], 0)
        self.assertEqual(len(kalan), 1)

    def test_sbarro_iki_urun_bulunana_kadar_geriye(self):
        haberler = [haber("Sbarro", "Eski 1", 100), haber("Sbarro", "Eski 2", 150), haber("Sbarro", "Eski 3", 200)]
        sonuc = bp.haber_penceresi(haberler, BIT)
        self.assertEqual(sorted(u["ad"] for u in sonuc), ["Eski 1", "Eski 2"])

    def test_sbarro_yakin_iki_urun_varsa_eskiye_gitmez(self):
        haberler = [haber("Sbarro", "Yeni 1", 5), haber("Sbarro", "Yeni 2", 20), haber("Sbarro", "Eski", 100)]
        sonuc = bp.haber_penceresi(haberler, BIT)
        self.assertEqual(sorted(u["ad"] for u in sonuc), ["Yeni 1", "Yeni 2"])

    def test_resmi_son_90_gun(self):
        resmi = [{"tarih": (BIT - timedelta(days=80)).isoformat(), "ad": "A"},
                 {"tarih": (BIT - timedelta(days=100)).isoformat(), "ad": "B"}]
        self.assertEqual([u["ad"] for u in bp.resmi_penceresi(resmi, BIT)], ["A"])


class TekrarTesti(unittest.TestCase):
    def test_ayni_haber_farkli_kaynakta_tek_karta_iner(self):
        haberler = [haber("Popeyes", "Popeyes Just Combined 3 Fan Favorites Into 1 New Sandwich", 2),
                    haber("Popeyes", "Popeyes just combined 3 fan favorites into 1 new sandwich!", 3)]
        sonuc = bp.benzer_haberleri_birlestir(haberler)
        self.assertEqual(len(sonuc), 1)
        self.assertEqual(sonuc[0]["ek_kaynak"], 1)

    def test_farkli_haberler_ayrik_kalir(self):
        haberler = [haber("KFC", "KFC yeni tavuk menüsü", 2), haber("KFC", "KFC Cheetos menüsü Kanada", 3)]
        self.assertEqual(len(bp.benzer_haberleri_birlestir(haberler)), 2)

    def test_farkli_markadaki_ayni_baslik_birlesmez(self):
        haberler = [haber("KFC", "Yeni menü", 2), haber("Subway", "Yeni menü", 3)]
        self.assertEqual(len(bp.benzer_haberleri_birlestir(haberler)), 2)


if __name__ == "__main__":
    unittest.main()
