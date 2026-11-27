import unittest
from textcenter.scan_catalog import (
    SPECTRUM_FEATURES, scan_capabilities, NETWORK_FEATURES, DVB_FEATURES
)


class StubSurvey:
    def availability(self, band="fm"):
        return {"ready":band!="navtex", "reason":"Test-only energy survey"}


class ScanCatalogTests(unittest.TestCase):
    def test_each_feature_has_an_honest_scan_contract(self):
        scans=scan_capabilities({
            "rtl_usb_count":1,"rtl_usb_devices":[{"product":"Test"}],
            "dvb_frontends":["adapter0/frontend0"],
            "decoders":{"rtl_power":True,"dvbv5-scan":True,"redsea":False},
        },StubSurvey())
        self.assertEqual(len(scans),31)
        by_id={item["id"]:item for item in scans}
        self.assertEqual(set(by_id),{item["id"] for item in scans})
        self.assertTrue(by_id["fm_rds"]["can_survey_now"])
        self.assertFalse(by_id["fm_rds"]["can_decode_now"])
        self.assertEqual(by_id["fm_rtplus"]["band"],"fm")
        self.assertTrue(by_id["dab_dls"]["can_survey_now"])
        self.assertFalse(by_id["dab_journaline"]["can_decode_now"])
        self.assertFalse(by_id["navtex"]["can_survey_now"])
        self.assertEqual(by_id["dvb_teletext"]["scan_type"],"dvb_service_adapter_pending")
        self.assertFalse(by_id["dvb_teletext"]["can_survey_now"])
        self.assertEqual(by_id["gemini"]["medium"],"internet_only")
        self.assertFalse(by_id["gemini"]["can_survey_now"])
        self.assertTrue(by_id["rss_atom"]["can_decode_now"])
        self.assertEqual(by_id["meshtastic"]["medium"],"separate_radio_hardware")
        self.assertFalse(by_id["official_cap"]["can_survey_now"])
        self.assertTrue(set(SPECTRUM_FEATURES).isdisjoint(NETWORK_FEATURES))
        self.assertTrue(set(SPECTRUM_FEATURES).isdisjoint(DVB_FEATURES))


if __name__=="__main__":
    unittest.main()
