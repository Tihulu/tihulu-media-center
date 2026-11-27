import tempfile
from pathlib import Path
import unittest
from textcenter.dvb_hardware import diagnose_dvb


class DvbTest(unittest.TestCase):
    def test_empty_dvb_does_not_claim_hauppauge_arrived(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            data=diagnose_dvb(usb_root=root/"usb",dvb_root=root/"dvb",
                 class_root=root/"class",firmware_root=root/"firmware",
                 which=lambda _:None,system_name="Linux")
            self.assertFalse(data["model_confirmed"])
            self.assertFalse(data["service_scan_enabled"])
            self.assertEqual(data["dvb_frontends"],[])

    def test_identify_usb_separately_from_frontend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            usb=root/"usb"/"2-3"
            usb.mkdir(parents=True)
            (usb/"idVendor").write_text("2040")
            (usb/"idProduct").write_text("0265")
            (usb/"product").write_text("WinTV-soloHD")
            dvb=root/"dvb"/"adapter0"
            dvb.mkdir(parents=True)
            (dvb/"frontend0").touch()
            fw=root/"firmware"
            fw.mkdir()
            (fw/"dvb-demod-si2168-b40-01.fw").write_bytes(b"test-fixture")
            data=diagnose_dvb(usb_root=root/"usb",dvb_root=root/"dvb",
                class_root=root/"class",firmware_root=fw,
                which=lambda name:"/usr/bin/"+name if name=="dvbv5-scan" else None,
                system_name="Linux")
            self.assertTrue(data["model_confirmed"])
            self.assertEqual(data["hauppauge_usb"][0]["usb_id"],"2040:0265")
            self.assertEqual(data["dvb_frontends"][0]["frontend"],"adapter0/frontend0")
            self.assertFalse(data["dvb_frontends"][0]["ownership_verified"])
            self.assertTrue(data["firmware_candidates"]["dvb-demod-si2168-b40-01.fw"])
            self.assertTrue(data["tools"]["dvbv5-scan"])
            self.assertFalse(data["teletext_decoder_connected"])


if __name__=="__main__":
    unittest.main()
