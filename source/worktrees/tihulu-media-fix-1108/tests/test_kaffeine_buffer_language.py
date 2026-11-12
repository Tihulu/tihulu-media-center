"""Native DVB buffer-progress accuracy and TV Auto language regressions."""
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kaffeine_next.caption_timing import buffer_fill_progress, KaffeineOSD
from tv_center.captions import asr_from_clip
from tv_center.language_codes import language_code


def status(requested=15000, effective=15000, queued=0, primed=False, **kw):
    return {"requested_ms": requested, "effective_ms": effective,
            "queue_age_ms": queued, "primed": primed,
            "has_queue_age": True, "capped": effective < requested, **kw}


class NativeBufferProgressTests(unittest.TestCase):
    def test_measured_fill_and_ready(self):
        first = buffer_fill_progress(status(queued=4500), 15000)
        self.assertEqual(first["percent"], 30)
        self.assertEqual(first["state"], "filling")
        self.assertEqual(first["queued_ms"], 4500)
        full = buffer_fill_progress(status(queued=15000, primed=True), 15000)
        self.assertEqual(full["percent"], 100)
        self.assertEqual(full["state"], "ready")

    def test_capped_effective_target_not_fabricated_requested_fill(self):
        limited = buffer_fill_progress(
            status(effective=9000, queued=4500), 15000)
        self.assertEqual(limited["percent"], 50)
        self.assertEqual(limited["effective_ms"], 9000)
        self.assertEqual(limited["requested_ms"], 15000)
        self.assertEqual(buffer_fill_progress(
            status(effective=9000, queued=12000), 15000)["percent"], 99)

    def test_missing_stale_old_format_and_mismatched_request_are_unknown(self):
        self.assertIsNone(buffer_fill_progress(None, 15000)["percent"])
        self.assertIsNone(buffer_fill_progress(
            status(requested=8000), 15000)["percent"])
        self.assertIsNone(buffer_fill_progress(
            status(has_queue_age=False), 15000)["percent"])
        self.assertEqual(buffer_fill_progress(
            status(requested=0, effective=0, primed=True), 0)["state"], "live")
        self.assertEqual(buffer_fill_progress(
            status(effective=0), 15000)["state"], "unavailable")
        with self.assertRaises(ValueError):
            buffer_fill_progress(status(), -500)

    def test_telemetry_5_fields_real_queue_age(self):
        with tempfile.TemporaryDirectory() as directory:
            ipc = KaffeineOSD(501, directory)
            ipc.effective.write_text("15000 12000 4000000 0 6000")
            found = ipc.read_effective_delay()
            self.assertTrue(found["has_queue_age"])
            self.assertEqual(buffer_fill_progress(found, 15000)["percent"], 50)
            ipc.effective.write_text("15000 12000 4000000 1 12000")
            self.assertEqual(buffer_fill_progress(ipc.read_effective_delay(), 15000)
                             ["percent"], 100)
            ipc.effective.write_text("15000 12000 4000000")
            self.assertFalse(ipc.read_effective_delay()["has_queue_age"])
            self.assertIsNone(buffer_fill_progress(ipc.read_effective_delay(),
                                                   15000)["percent"])
            ipc.close()


class LiveTvAutoLanguageTests(unittest.TestCase):
    def test_auto_reaches_real_receiver_stage_instead_of_rejection(self):
        with patch("tv_center.captions._program_streams",
                   side_effect=RuntimeError("receiver reached")):
            with self.assertRaisesRegex(RuntimeError, "receiver reached"):
                asr_from_clip(Path("/not-a-real-clip.ts"), "auto", "")
            with self.assertRaisesRegex(ValueError, "Unsupported transcription language"):
                asr_from_clip(Path("/not-a-real-clip.ts"), "invalid", "")
            with self.assertRaisesRegex(RuntimeError, "receiver reached"):
                asr_from_clip(Path("/not-a-real-clip.ts"), "de", "")

    def test_dvb_iso_code_and_manual_override(self):
        self.assertEqual(language_code("deu"), "de")
        from kaffeine_next import captions_overlay
        from_controls = inspect.getsource(captions_overlay.main)
        self.assertIn('spoken = (hinted or "auto") if automatic_source', from_controls)
        self.assertIn('language_code(source.currentText())', from_controls)
        self.assertIn('QProgressBar()', from_controls)
        self.assertIn('buffer_fill_progress(effective, applied.playback_delay_ms)', from_controls)


if __name__ == "__main__":
    unittest.main()
