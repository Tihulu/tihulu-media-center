"""Offline regression tests for the Kaffeine DVB stream tap."""
import os
import queue
import socket
import tempfile
import time
from pathlib import Path
from unittest import TestCase, mock

from kaffeine_next.captions_overlay import CaptionTap, validate_socket
from kaffeine_next.patch_upstream import REVISION, PATHS

class KaffeineCaptionTapTests(TestCase):
    def test_native_kaffeine_scanner_keeps_single_receiver_and_typed_frequency(self):
        from kaffeine_next.patch_upstream import transform
        # Source-patching regression check without opening a real tuner.
        # C++ build CI checks the same patch against pristine KDE Kaffeine.
        import inspect
        source = inspect.getsource(transform)
        self.assertIn("DvbTransponderBase::DvbT2", source)
        self.assertIn("DvbT2Transponder::Bandwidth8MHz", source)
        self.assertIn("538000000, 586000000, 626000000", source)
        self.assertIn("Channels / Antenna Scan", source)
        self.assertIn("Full Antenna Scan...", source)
        self.assertIn("Load generated SRT in native player...", source)
        self.assertIn("mediaWidget->stop()", source)
        self.assertIn("QTimer::singleShot", source)
        self.assertNotIn('QProcess::startDetached(QLatin1String("w_scan_cpp")', source)
        self.assertNotIn('QProcess::startDetached(QLatin1String("dvbv5-scan")', source)

    def test_software_video_profile_is_opt_in_and_does_not_override_settings(self):
        from kaffeine_next.patch_upstream import transform
        import inspect
        patched_source = inspect.getsource(transform)
        self.assertIn("TIHULU_VLC_PROFILE", patched_source)
        self.assertIn("--avcodec-hw=none", patched_source)
        self.assertIn("--file-caching=1500", patched_source)
        self.assertIn("software-no-audio", patched_source)
        self.assertIn('option.startsWith(QLatin1String("--avcodec-hw="))', patched_source)
        self.assertIn('args.append(QLatin1String(" --avcodec-hw=none"))', patched_source)

    def test_kaffeine_receiver_diagnostics_do_not_open_frontend(self):
        from kaffeine_next.diagnostics import inspect
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "home"
            dev = Path(root) / "dvb"
            home.mkdir()
            (dev / "adapter0").mkdir(parents=True)
            frontend = dev / "adapter0" / "frontend0"
            frontend.touch()
            with mock.patch("kaffeine_next.diagnostics.shutil.which", return_value=None):
                state = inspect(home, dev)
            self.assertEqual(state["frontend_devices"], [str(frontend)])
            self.assertTrue(state["checked_device_files_without_opening"])
            self.assertEqual(state["expected_test_multiplexes_mhz"], [538, 586, 626])
            self.assertEqual(state["frontend_busy"], "unknown")

    def test_kaffeine_saved_channel_sources_are_read_only(self):
        from kaffeine_next.diagnostics import inspect
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "home"
            dev = Path(root) / "dvb"
            (home / ".local/share/kaffeine").mkdir(parents=True)
            cfg = home / ".local/share/kaffeine/config.dvb"
            content = """[device]
frontendName=Silicon Labs Si2168
[config]
name=Terrestrial (T2)
scanSource=TIHULU tested: 538 / 586 / 626 MHz
"""
            cfg.write_text(content)
            with mock.patch("kaffeine_next.diagnostics.shutil.which", return_value=None):
                result = inspect(home, dev)
            saved = result["configured_sources"]["devices"][0]
            self.assertEqual(saved["frontend_name"], "Silicon Labs Si2168")
            self.assertEqual(saved["sources"][0]["name"], "Terrestrial (T2)")
            self.assertEqual(saved["sources"][0]["scan_source"],
                             "TIHULU tested: 538 / 586 / 626 MHz")
            self.assertEqual(cfg.read_text(), content)

    def test_dvb_failure_reports_connected_sources_not_just_generic_permission_error(self):
        from kaffeine_next.patch_upstream import transform
        import inspect
        source = inspect.getsource(transform)
        self.assertIn("TIHULU no usable DVB frontend:", source)
        self.assertIn("requested channel source=", source)
        self.assertIn("configured channel sources=", source)

    def test_switching_dvb_channels_uses_bounded_acquire_and_diagnostic(self):
        import inspect
        from kaffeine_next.patch_upstream import transform
        source=inspect.getsource(transform)
        self.assertIn("tihuluDeviceRetryCount < 2",source)
        self.assertIn("hasConnectedMatchingSource && !recording",source)
        self.assertIn("QTimer::singleShot(attempt * 400, this",source)
        self.assertIn("internal->tihuluTuneEpoch != epoch",source)
        self.assertIn("++internal->tihuluTuneEpoch",source)
        self.assertIn("channel.constData() == NULL",source)
        self.assertIn("source matches connected tuner=",source)
        self.assertIn("source Name used by the saved channel",source)
        self.assertIn("No tuner reset or channel settings were performed",source)
        self.assertNotIn("udevadm trigger",source)
        self.assertNotIn("systemctl stop",source)

    def test_dvb_diagnostics_displays_channel_source_names_read_only(self):
        import subprocess
        script=Path(__file__).resolve().parent.parent / "kaffeine_next" / "dvb_diagnostics.sh"
        subprocess.run(["bash","-n",str(script)],check=True)
        with tempfile.TemporaryDirectory() as root:
            config=Path(root) / ".local/share/tihulu-media-center/config.dvb"
            config.parent.mkdir(parents=True)
            config.write_text("[device]\nfrontendName=Silicon Labs Si2168\n"
                              "[config]\nname=Terrestrial (T2)\n"
                              "scanSource=AUTO-T2-Normal\n"
                              "deviceId=do-not-print-this\n")
            result=subprocess.run(["bash",str(script)],env={**os.environ,"HOME":root},
                                  capture_output=True,text=True,check=True)
            self.assertIn("Terrestrial (T2)",result.stdout)
            self.assertIn("Silicon Labs Si2168",result.stdout)
            self.assertIn("AUTO-T2-Normal",result.stdout)
            self.assertNotIn("do-not-print-this",result.stdout)

    def test_upstream_release_is_immutable(self):
        self.assertEqual(REVISION, "e7ea15b86dafed3b20b151cbcb080578ab8e2d5c")
        # The pinned KDE revision is immutable; patching its SQL allocator
        # adds one deliberately version-guarded upstream header to our list.
        self.assertEqual(len(PATHS), 20)
        self.assertIn("src/sqlinterface.h", PATHS)
        self.assertIn("src/dvb/dvbscandialog.cpp", PATHS)
        self.assertIn("src/dvb/dvbscandialog.h", PATHS)
        self.assertIn("src/dvb/dvbconfigdialog.cpp", PATHS)
        self.assertIn("src/mainwindow.h", PATHS)
        self.assertIn("src/CMakeLists.txt", PATHS)
        self.assertIn("src/main.cpp", PATHS)
        self.assertIn("src/dvb/dvbepg.cpp", PATHS)
        self.assertIn("src/backend-vlc/vlcmediawidget.cpp", PATHS)
        self.assertIn("src/dvb/dvbtab.h", PATHS)
        self.assertIn("src/dvb/dvbmanager.cpp", PATHS)
        self.assertIn("src/dvb/dvbtab.cpp", PATHS)

    def test_socket_accepts_only_private_kaffeine_endpoint(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": root}):
                valid = str(Path(root)/"tihulu-dvb-12345.sock")
                self.assertEqual(validate_socket(valid), Path(valid))
                with self.assertRaises(ValueError):
                    validate_socket(str(Path(root)/"other.sock"))
                with self.assertRaises(ValueError):
                    validate_socket("/tmp/tihulu-dvb-12345.sock")

    def test_datagrams_do_not_claim_dvb_device(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": root}):
                path = str(Path(root)/"tihulu-dvb-1001.sock")
                events = queue.Queue()
                tap = CaptionTap(path, lambda: {"mode":"off"}, events)
                tap.start()
                try:
                    packet = b"\x47" + b"\x00" * 187
                    sender = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
                    try:
                        sender.sendto(packet * 12, path)
                    finally:
                        sender.close()
                    for _ in range(30):
                        if tap.packet_count:
                            break
                        time.sleep(0.02)
                    self.assertEqual(tap.packet_count, 12)
                    self.assertEqual(tap.bad_packets, 0)
                finally:
                    tap.close()
                self.assertFalse(Path(path).exists())
