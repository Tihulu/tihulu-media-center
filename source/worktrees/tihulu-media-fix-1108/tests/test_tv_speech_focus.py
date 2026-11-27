"""Opt-in spoken dialogue priority under background music: safety and wiring."""
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from kaffeine_next.caption_timing import CaptionConfig
from tv_center.asr_quality import accepted_whisper_segments
from tv_center.speech_focus import (
    DIALOGUE_FILTER, ffmpeg_audio_filter, whisper_vad_settings)


def segment(text, *, start=0., end=2.0, no_speech_prob=.08,
            avg_logprob=-.2, compression_ratio=1.2):
    return SimpleNamespace(text=text, start=start, end=end,
                           no_speech_prob=no_speech_prob,
                           avg_logprob=avg_logprob,
                           compression_ratio=compression_ratio)


class SpeechFocusConfigTests(unittest.TestCase):
    def test_off_by_default_and_is_sent_to_decoder(self):
        self.assertFalse(CaptionConfig().speech_priority)
        self.assertFalse(CaptionConfig().options()["speech_priority"])
        config = CaptionConfig(speech_priority=True).validate()
        self.assertTrue(config.options()["speech_priority"])
        with self.assertRaises(ValueError):
            CaptionConfig(speech_priority="true").validate()

    def test_dialogue_filter_is_opt_in_and_not_used_for_singing(self):
        self.assertEqual(ffmpeg_audio_filter(), ())
        self.assertEqual(ffmpeg_audio_filter(music_transcription=True), ())
        self.assertEqual(ffmpeg_audio_filter(
            speech_priority=True, music_transcription=True), ())
        self.assertEqual(ffmpeg_audio_filter(speech_priority=True),
                         ("-af", DIALOGUE_FILTER))
        self.assertIn("highpass=f=140", DIALOGUE_FILTER)
        self.assertIn("lowpass=f=5200", DIALOGUE_FILTER)
        self.assertNotIn("atempo", DIALOGUE_FILTER)
        with self.assertRaises(ValueError):
            ffmpeg_audio_filter(speech_priority=1)

    def test_cuda_vad_prioritizes_dialogue_not_singing(self):
        regular = whisper_vad_settings()
        focused = whisper_vad_settings(speech_priority=True)
        vocal = whisper_vad_settings(music_transcription=True)
        self.assertTrue(regular["vad_filter"])
        self.assertTrue(focused["vad_filter"])
        self.assertLess(focused["vad_parameters"]["threshold"],
                        regular["vad_parameters"]["threshold"])
        self.assertLess(focused["vad_parameters"]["min_speech_duration_ms"],
                        regular["vad_parameters"]["min_speech_duration_ms"])
        self.assertFalse(vocal["vad_filter"])

    def test_ui_and_all_decoders_receive_independent_flag(self):
        from kaffeine_next import captions_overlay
        from tv_center import captions, cuda_faster_whisper
        screen = inspect.getsource(captions_overlay.main)
        self.assertIn("Prefer spoken dialogue over background music", screen)
        self.assertIn("speech_priority=speech_priority.isChecked()", screen)
        self.assertIn("speech_priority.setChecked(False)", screen)
        self.assertIn('speech_priority=bool(options.get("speech_priority",False))',
                      inspect.getsource(captions_overlay.CaptionTap._decode))
        decoder = inspect.getsource(captions.decode_segment)
        self.assertIn('asr_kwargs["speech_priority"] = True', decoder)
        asr = inspect.getsource(captions.asr_from_clip)
        self.assertIn("ffmpeg_audio_filter", asr)
        self.assertIn("speech_priority=speech_priority", asr)
        gpu = inspect.getsource(cuda_faster_whisper.main)
        self.assertIn('dialogue_priority = (bool(request.get("speech_priority"))', gpu)


class SpeechPriorityQualityTests(unittest.TestCase):
    def test_confident_dialogue_over_music_kept_only_when_opted_in(self):
        dialogue = segment("Ich habe das gerade gesagt und das stimmt.",
                           start=0., end=2.2,
                           no_speech_prob=.71, avg_logprob=-.19)
        normal, reason = accepted_whisper_segments([dialogue],
                                                    source_language="de")
        self.assertEqual(normal, [])
        self.assertIsNotNone(reason)
        focus, reason = accepted_whisper_segments(
            [dialogue], source_language="de", speech_priority=True)
        self.assertEqual(focus, [dialogue])
        self.assertIsNone(reason)

    def test_silent_music_and_unsupported_numeric_jingle_remain_rejected(self):
        clips = [
            segment("BR 2018", end=.8,
                    no_speech_prob=.43, avg_logprob=-.48),
            segment("Not really real conversation", end=1.8,
                    no_speech_prob=.92, avg_logprob=-.12),
            segment("No no no no no no", compression_ratio=4.1),
        ]
        valid, reason = accepted_whisper_segments(
            clips, source_language="de", speech_priority=True)
        self.assertEqual(valid, [])
        self.assertTrue(reason)

    def test_short_confident_real_interjections_survive(self):
        spoken = segment("Ja, stimmt!", end=.85, no_speech_prob=.24,
                         avg_logprob=-.14)
        text, _ = accepted_whisper_segments(
            [spoken], source_language="de", speech_priority=True)
        self.assertEqual(text, [spoken])


if __name__ == "__main__":
    unittest.main()
