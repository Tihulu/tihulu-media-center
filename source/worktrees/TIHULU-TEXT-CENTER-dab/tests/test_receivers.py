"""Passive hardware inventory regressions; no tuner is accessed."""
import tempfile
from pathlib import Path
import unittest
from textcenter.receivers import receiver_inventory


class ReceiverInventoryTests(unittest.TestCase):
    def test_absent_usb_is_not_false_live_rf(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            status=receiver_inventory(sys_usb_root=p,sys_dvb_root=p/"dvb",
                executable_lookup=lambda _: None,system_name="Linux")
            self.assertEqual(status["status"],"no_supported_usb_candidate")
            self.assertEqual(status["rtl_usb_count"],0)
            self.assertFalse(status["signal_verified"])
            self.assertFalse(status["active_capture"])

    def test_passive_rtl_detection_and_decoder_presence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            usb=root/"usb"
            device=usb/"1-2"
            device.mkdir(parents=True)
            (device/"idVendor").write_text("0bda\n")
            (device/"idProduct").write_text("2838\n")
            (device/"manufacturer").write_text("Nooelec\n")
            (device/"product").write_text("NESDR SMArt v5\n")
            false_dev=usb/"2-1"
            false_dev.mkdir()
            (false_dev/"idVendor").write_text("1234")
            (false_dev/"idProduct").write_text("5678")
            dvb=root/"dvb"/"adapter0"
            dvb.mkdir(parents=True)
            (dvb/"frontend0").touch()
            inventory=receiver_inventory(
                sys_usb_root=usb,sys_dvb_root=root/"dvb",
                executable_lookup=lambda name: "/usr/bin/"+name if name in ("rtl_fm","redsea") else None,
                system_name="Linux")
            self.assertEqual(inventory["rtl_usb_count"],1)
            self.assertEqual(inventory["rtl_usb_devices"][0]["usb_id"],"0bda:2838")
            self.assertEqual(inventory["dvb_frontends"],["adapter0/frontend0"])
            self.assertTrue(inventory["rds_pipeline_available"])
            self.assertFalse(inventory["connected_decoder"])
            self.assertFalse(inventory["signal_verified"])

    def test_non_linux_does_not_claim_usb_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=receiver_inventory(sys_usb_root=Path(tmp),
                executable_lookup=lambda _:None,system_name="Darwin")
            self.assertEqual(result["status"],"sysfs_unavailable")
            self.assertEqual(result["rtl_usb_count"],0)


if __name__=="__main__":
    unittest.main()
