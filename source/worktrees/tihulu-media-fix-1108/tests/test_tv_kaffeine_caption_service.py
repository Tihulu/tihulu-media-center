"""Tests for persistent subtitles when the settings panel is hidden."""
import os
import queue
import tempfile
import time
import unittest
from pathlib import Path

from kaffeine_next.caption_control import CaptionServiceControl


class PersistentCaptionServiceTests(unittest.TestCase):
    def test_private_control_socket_reopens_existing_subtitle_service(self):
        with tempfile.TemporaryDirectory() as root:
            events = queue.Queue()
            ctrl = CaptionServiceControl(Path(root), 7312, events)
            self.assertFalse(CaptionServiceControl.request_show(root, 7312))
            ctrl.start()
            try:
                self.assertTrue(ctrl.path.exists())
                self.assertEqual(ctrl.path.stat().st_mode & 0o777, 0o600)
                self.assertTrue(CaptionServiceControl.request_show(root, 7312))
                self.assertEqual(events.get(timeout=2), ("show_settings", None))
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    CaptionServiceControl(root, 7312, events).start()
                self.assertEqual(events.get(timeout=2), ("show_settings", None))
            finally:
                ctrl.close()
            self.assertFalse(ctrl.path.exists())
            self.assertFalse(CaptionServiceControl.request_show(root, 7312))

    def test_crashed_service_socket_can_be_recovered_without_stopping_tv(self):
        with tempfile.TemporaryDirectory() as root:
            import socket
            sock_path = Path(root) / "tihulu-captions-control-912.sock"
            old = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            old.bind(str(sock_path))
            old.close()
            events = queue.Queue()
            ctrl = CaptionServiceControl(Path(root), 912, events)
            ctrl.start()
            try:
                self.assertTrue(CaptionServiceControl.request_show(root, 912))
                self.assertEqual(events.get(timeout=2), ("show_settings", None))
            finally:
                ctrl.close()
            self.assertFalse(sock_path.exists())

    def test_x_hides_panel_but_does_not_quit_caption_event_loop(self):
        # Keep this static regression independent from running a Qt desktop in CI.
        source = (Path(__file__).resolve().parent.parent /
                  "kaffeine_next" / "captions_overlay.py").read_text(encoding="utf-8")
        self.assertIn("app.setQuitOnLastWindowClosed(False)", source)
        self.assertIn("def closeEvent(self, event):", source)
        self.assertIn("self.hide()", source)
        self.assertIn("event.ignore()", source)
        self.assertIn('kind == "show_settings"', source)
        self.assertIn("control.close()", source)
        self.assertIn("stop_subtitles.clicked.connect(lambda: set_subtitles_running(False))", source)
        self.assertIn("exit_subtitles.clicked.connect(stop_caption_service)", source)
        self.assertIn("timer.timeout.connect(pump)", source)

