"""Regression guards: TIHULU remains useful with ZERO RF receivers.

Static source assertions exercise architecture contracts without requiring a
USB device, a display server, a station connection or an RF antenna in CI.
They cannot prove third-party remote streams are online or audible.
"""
from pathlib import Path
import tempfile
import unittest

from tv_center.hardware_status import inspect

ROOT=Path(__file__).resolve().parents[1]/"kaffeine_next"


class HardwareOptionalPlaybackTests(unittest.TestCase):
    def test_no_receivers_is_normal_inventory_result(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            data=inspect(usb_root=root/"sys",dvb_root=root/"dev",
                         usb_nodes=root/"usb",sys_dvb=root/"class")
            self.assertEqual(data["dvb"],[])
            self.assertEqual(data["usb"],[])
            self.assertEqual(data["summary"]["receiver_candidates"],0)

    def test_web_tv_starts_player_not_rf_receiver(self):
        source=(ROOT/"native_web_tv_dialog.h").read_text(encoding="utf-8")
        play_url=source.split("void playUrl(const QString &address)",1)[1].split(
            "\n MediaWidget *player_",1)[0]
        self.assertIn("showPlayback_();",play_url)
        self.assertIn("player_->play(url);",play_url)
        self.assertNotIn("requestDevice(",play_url)
        self.assertNotIn("startReceiver(",play_url)
        self.assertIn("https://iptv-org.github.io",source)

    def test_internet_radio_independent_of_welle_and_rtl_fm(self):
        source=(ROOT/"native_radio_tab.h").read_text(encoding="utf-8")
        play_radio=source.split("void playInternetRadio(const QString &address)",1)[1].split(
            "\n\tvoid stopInternetRadio()",1)[0]
        self.assertIn("player_->play(url);",play_radio)
        self.assertNotIn("startReceiver(",play_radio)
        self.assertNotIn("startAnalog(",play_radio)
        self.assertIn("Internet radio is ready. No tuner connection required.",source)

    def test_web_tv_is_available_in_television_menu_without_device_test(self):
        patch=(ROOT/"patch_upstream.py").read_text(encoding="utf-8")
        menu=patch.split('QAction *webTvAction = dvbMenu->addAction',1)[1].split(
            '// Keep native Kaffeine channel switching',1)[0]
        self.assertIn("TihuluWebTvDialog",menu)
        self.assertNotIn("requestExclusiveDevice",menu)
        self.assertNotIn("frontend0",menu)

    def test_local_file_playback_not_conditioned_on_usb(self):
        source=(ROOT/"native_media_panel.h").read_text(encoding="utf-8")
        self.assertIn("player_->play(QUrl::fromLocalFile(path_));",source)
        self.assertNotIn("requestExclusiveDevice(",source)
        self.assertNotIn("startReceiver(",source)

    def test_empty_hardware_ui_explains_remaining_media_options(self):
        source=(ROOT/"native_hardware_tab.h").read_text(encoding="utf-8")
        self.assertIn("No antenna or USB tuner?",source)
        self.assertIn("Local media, Web TV and Internet radio",source)


if __name__=="__main__":
    unittest.main()
