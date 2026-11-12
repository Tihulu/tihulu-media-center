"""Offline regressions: real timed SRT and safe native caption controls."""
import inspect
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from kaffeine_next.caption_timing import CaptionConfig, KaffeineOSD
from kaffeine_next.live_srt import LiveSRTRecorder, srt_timestamp


class LiveSRTEngineTests(unittest.TestCase):
    def test_one_file_per_real_language_and_non_destructive_restart(self):
        cfg = CaptionConfig(source="de", target_languages=("en", "tr"),
                            show_original=True, show_translation=True).validate()
        result = {"original": "Guten Morgen",
                  "translations": {"en": "Good morning", "tr": "Günaydın"}}
        with tempfile.TemporaryDirectory() as temp:
            writer = LiveSRTRecorder()
            folder = writer.start(temp, "ZDF neo", now=100.0)
            self.assertTrue(folder.is_dir())
            writer.append({"due": 102.0, "expires": 105.0,
                           "result": result}, cfg)
            paths = writer.stop()
            self.assertEqual(len(paths), 3)
            self.assertIn("00:00:02,000 --> 00:00:05,000",
                          (folder / "original.srt").read_text())
            self.assertIn("Good morning",
                          (folder / "translation-en.srt").read_text())
            self.assertIn("Günaydın",
                          (folder / "translation-tr.srt").read_text())
            self.assertNotIn("Günaydın",
                             (folder / "translation-en.srt").read_text())
            again = writer.start(temp, "ZDF neo", now=150.0)
            self.assertNotEqual(again, folder)
            writer.stop()
            self.assertTrue((folder / "original.srt").exists())

    def test_empty_and_missing_translation_never_invented(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = CaptionConfig(target_languages=("en",)).validate()
            recorder = LiveSRTRecorder()
            folder = recorder.start(temp, now=10.0)
            recorder.append({"due": 11.0, "expires": 13.0,
                             "result": {"original": "", "translations": {}}}, cfg)
            self.assertEqual(recorder.paths, ())
            recorder.append({"due": 13.0, "expires": 16.0,
                             "result": {"original": "Hallo"}}, cfg)
            self.assertEqual(len(recorder.paths), 1)
            recorder.stop()
            self.assertEqual((folder / "original.srt").read_text().count("-->"), 1)
            self.assertFalse((folder / "translation-en.srt").exists())

    def test_timestamps_and_track_monotonicity(self):
        self.assertEqual(srt_timestamp(0.0), "00:00:00,000")
        self.assertEqual(srt_timestamp(3661.234), "01:01:01,234")
        with tempfile.TemporaryDirectory() as temp:
            recorder = LiveSRTRecorder()
            folder = recorder.start(temp, now=20.0)
            config = CaptionConfig().validate()
            for due in (20.2, 20.3):
                recorder.append({"due": due, "expires": due + 0.5,
                                 "result": {"original": "Hallo"}}, config)
            recorder.stop()
            content = (folder / "original.srt").read_text()
            self.assertIn("00:00:01,200 --> 00:00:02,000", content)
            self.assertEqual(content.count("-->"), 2)

    def test_native_renderer_config_and_ipc(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = CaptionConfig(render_mode="native", opacity=0).validate()
            ipc = KaffeineOSD(1234, runtime=Path(temp))
            ipc.publish("Hallo", cfg)
            self.assertIn('"render_mode":"native"', ipc.path.read_text())
            self.assertIn('"opacity":0', ipc.path.read_text())
            # Native video compositor must receive the user-selected backing
            # opacity and RGB value, not silently discard them in the GUI.
            cfg = replace(cfg, opacity=70, background_color="#0B2540")
            ipc.publish("Guten Morgen", cfg)
            self.assertIn('"opacity":70', ipc.path.read_text())
            self.assertIn('"background_color":"#0B2540"', ipc.path.read_text())
            ipc.close()
            with self.assertRaises(ValueError):
                replace(cfg, render_mode="untrusted").validate()

    def test_native_video_background_does_not_overlay_a_qt_window(self):
        from kaffeine_next.patch_upstream import transform
        code = inspect.getsource(transform)
        for required in (
            "libvlc_video_set_logo_string",
            "libvlc_video_set_logo_int",
            "libvlc_logo_file",
            "libvlc_logo_position",
            "libvlc_logo_opacity",
            "libvlc_logo_enable",
            "QTemporaryDir tihuluCaptionLogoDir",
            "artwork.fill(Qt::transparent)",
            "painter.drawRoundedRect(box, 9, 9)",
            "backing.setAlpha(qBound(0, backgroundPercent, 100)*255/100)",
            "ink.setAlpha(qBound(0, textOpacity, 100)*255/100)",
            "backgroundPercent > 0",
            "obj.value(QLatin1String(\"opacity\")).toInt(0)",
            "obj.value(QLatin1String(\"background_color\"))",
            "libvlc_video_set_logo_int(vlcMediaPlayer, libvlc_logo_enable, 0)",
        ):
            self.assertIn(required, code, required)
        from kaffeine_next import captions_overlay
        gui = inspect.getsource(captions_overlay.main)
        self.assertIn("background are composited into the VLC video itself", gui)


class CaptionWindowControlsTests(unittest.TestCase):
    def test_no_longer_equate_stop_with_exit(self):
        from kaffeine_next import captions_overlay
        code = inspect.getsource(captions_overlay.main)
        self.assertIn('start_subtitles = QPushButton("Start subtitles")', code)
        self.assertIn('stop_subtitles = QPushButton("Stop subtitles")', code)
        self.assertIn('exit_subtitles = QPushButton("Exit caption service")', code)
        self.assertIn('stop_subtitles.clicked.connect(lambda: set_subtitles_running(False))', code)
        self.assertIn('exit_subtitles.clicked.connect(stop_caption_service)', code)
        self.assertIn('values["mode"] = "off"', code)
        self.assertIn('renderer.addItem("Native libVLC', code)
        self.assertIn('pages.addTab(appearance_scroll, "Appearance")', code)
        self.assertIn('srt_recorder.append(cue, applied)', code)
        from kaffeine_next.patch_upstream import transform
        patch = inspect.getsource(transform)
        self.assertIn('atTop ? 4 : 8', patch)
        self.assertIn('tihuluCaptionCacheKey.clear()', patch)
        self.assertIn('Load generated SRT in native player...', patch)

    def test_tv_auto_language_prefers_dvb_descriptor(self):
        from tv_center import captions
        source = inspect.getsource(captions.decode_segment)
        self.assertIn('speech_language = audio_source or source', source)
        from kaffeine_next import captions_overlay
        capture = inspect.getsource(captions_overlay.CaptionTap._reader)
        self.assertIn('captured_options["audio_source"] = code', capture)


if __name__ == "__main__":
    unittest.main()
