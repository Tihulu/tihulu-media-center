import unittest
from textcenter.capabilities import capability_catalog, CAPABILITIES


class CapabilityCatalogTests(unittest.TestCase):
    def test_all_required_modules_present_and_honest(self):
        statuses=capability_catalog({
            "rtl_usb_count":1,
            "dvb_frontends":[],
            "receiver_conflicts":[{"process":"readsb"}],
            "decoders":{"rtl_fm":True,"redsea":False,"welle-cli":False}
        })
        by_id={x["id"]:x for x in statuses}
        expected={
            "fm_rds","fm_rtplus","fm_tmc","dab_dls","dab_journaline","dab_mot",
            "dab_epg","dab_tpeg","dvb_teletext","hbbtv","drm","rtty","navtex",
            "weatherfax","aprs","rss_atom","json_feed","news_politics","gemini",
            "gopher","external_bbs","local_board","meshtastic","aprs_tx",
            "official_cap","offline_wiki","offline_feeds","translate_ai",
            "region_presets","tihulu_portal","receiver_broker"}
        self.assertEqual(set(by_id),expected)
        self.assertEqual(len(statuses),len(CAPABILITIES))
        self.assertTrue(all(not r["live_verified"] for r in statuses))
        self.assertTrue(by_id["fm_rds"]["dependency_status"]["process_conflict_detected"])
        self.assertFalse(by_id["fm_rds"]["dependency_status"]["redsea_installed"])
        self.assertEqual(by_id["meshtastic"]["state"],"separate_tx_hardware_required")
        self.assertEqual(by_id["dab_journaline"]["state"],"licensed_decoder_needed")
        self.assertEqual(by_id["json_feed"]["state"],"implemented")
        self.assertEqual(by_id["local_board"]["state"],"single_owner_only")


if __name__ == "__main__":
    unittest.main()
