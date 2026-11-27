"""Regress virtual native DVB captions and conservative Whisper speech filters."""
import inspect
import unittest
from types import SimpleNamespace

from tv_center.asr_quality import accepted_whisper_segments
from kaffeine_next.patch_upstream import transform


def segment(text, *, start=0.0, end=2.5,
            no_speech_prob=0.05, avg_logprob=-0.2,
            compression_ratio=1.2):
    return SimpleNamespace(
        text=text, start=start, end=end, no_speech_prob=no_speech_prob,
        avg_logprob=avg_logprob, compression_ratio=compression_ratio,
        words=())


class WhisperTvConfidenceTests(unittest.TestCase):
    def test_credible_dialogue_and_short_interjection_remain(self):
        clips = [segment("Wir treffen uns am Bahnhof."),
                 segment("Ja", end=0.8, avg_logprob=-0.12)]
        chosen, reason = accepted_whisper_segments(clips, source_language="de")
        self.assertEqual(chosen, clips)
        self.assertIsNone(reason)

    def test_station_jingle_year_and_no_speech_are_not_subtitles(self):
        jingles = [segment("BR 2018", end=0.7,
                           no_speech_prob=0.32, avg_logprob=-0.48),
                   segment("Thanks for watching", no_speech_prob=0.88)]
        chosen, reason = accepted_whisper_segments(jingles, source_language="de")
        self.assertEqual(chosen, [])
        self.assertTrue(reason)

    def test_repetitive_and_low_confidence_are_rejected(self):
        for kwargs in ({"compression_ratio":3.3},
                       {"avg_logprob":-1.20},
                       {"no_speech_prob":0.90}):
            chosen, reason = accepted_whisper_segments(
                [segment("glaubwürdiger Satz", **kwargs)],
                source_language="de")
            self.assertEqual(chosen, [])
            self.assertIsNotNone(reason)

    def test_mixed_audio_keeps_only_supported_speech(self):
        good = segment("Wir sprechen auf Deutsch", start=2.0, end=4.2)
        unreliable = segment("BR 2018", end=0.7, avg_logprob=-0.5)
        chosen, reason = accepted_whisper_segments([unreliable, good],
                                                  source_language="de")
        self.assertEqual(chosen, [good])
        self.assertIsNone(reason)

    def test_unknown_auto_language_abstains_instead_of_guessing(self):
        chosen, reason = accepted_whisper_segments(
            [segment("Unknown speech")], source_language="auto",
            detected_probability=0.28)
        self.assertEqual(chosen, [])
        self.assertEqual(reason, "uncertain_auto_detect_language")
        known, _ = accepted_whisper_segments(
            [segment("Guten Tag")], source_language="de",
            detected_probability=0.28)
        self.assertEqual(len(known), 1)


class NativeSubtitleMenuTests(unittest.TestCase):
    def test_video_marquee_flag_not_unrelated_enum(self):
        patch = inspect.getsource(transform)
        self.assertIn("atTop ? 4 : 8", patch)
        self.assertNotIn("atTop ? libvlc_position_top : libvlc_position_bottom", patch)

    def test_ai_subtitle_is_virtual_and_dvb_preserved(self):
        patch = inspect.getsource(transform)
        for snippet in (
            "TIHULU AI · Live Whisper / translations",
            "tihuluAiCaptionAvailable = false",
            "tihuluAiCaptionSelected = false",
            "currentSubtitle == subtitleModel->rowCount()-1",
            "backend->setCurrentSubtitle(0)",
            "source->setCurrentSubtitle(-1)",
            "items << i18n(",
            "if (!tihuluAiCaptionSelected)",
            "setAiAvailability(false)",
            "setAiAvailability(true)",
        ):
            self.assertIn(snippet, patch)
        self.assertIn("if (subtitleModel->stringList() != items)", patch)

    def test_caption_sidecar_heartbeat_preserves_choice(self):
        from kaffeine_next import captions_overlay
        body = inspect.getsource(captions_overlay.main)
        self.assertIn("now-last_published >= 1.5", body)
        self.assertIn("ttl_ms=3500", body)
        self.assertIn('replace(applied, mode="off")', body)
        self.assertIn("Whisper suppressed an uncertain TV audio result", body)


if __name__ == "__main__":
    unittest.main()
