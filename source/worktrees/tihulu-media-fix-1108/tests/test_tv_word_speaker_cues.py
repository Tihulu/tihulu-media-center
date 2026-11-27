"""No hardware/network required: word pacing and optional speaker labeling."""
import unittest
from unittest.mock import patch

from kaffeine_next.caption_timing import CaptionConfig, CueQueue
from kaffeine_next.word_cues import word_groups, enqueue_word_cues
from tv_center.captions import _speaker_details


def clip(*, words=None, translations=None, turns=None):
    return {"source":"local_asr", "source_language":"de",
            "original":"Guten Morgen meine Freunde und willkommen zurück",
            "words": words or [
                {"text":"Guten","start":0.2,"end":0.5},
                {"text":"Morgen","start":0.6,"end":0.9},
                {"text":"meine","start":1.2,"end":1.45},
                {"text":"Freunde","start":1.5,"end":1.85},
                {"text":"und","start":2.0,"end":2.2},
                {"text":"willkommen","start":2.5,"end":2.9},
                {"text":"zurück","start":3.0,"end":3.3}],
            "translations":translations or {"tr":"Günaydın arkadaşlarım tekrar hoş geldiniz"},
            "speaker_turns":turns or []}


class WordCueTests(unittest.TestCase):
    def test_cues_are_short_and_timed_to_prebuffer_capture(self):
        data=clip()
        groups=word_groups(data,maximum_words=3)
        self.assertGreaterEqual(len(groups),3)
        self.assertTrue(all(len(g[2]["original"].split())<=3 for g in groups))
        self.assertTrue(all(len(g[2]["translations"]["tr"].split())<=9 for g in groups))
        q=CueQueue(maximum=32)
        config=CaptionConfig(playback_delay_ms=10000)
        final=enqueue_word_cues(q,data,config,
                                captured_start=100.0,captured_end=106.0,
                                finished=107.0)
        self.assertIsNotNone(final)
        self.assertGreater(len(q.items),1)
        self.assertTrue(min(item["due"] for item in q.items) >= 110.0)
        self.assertEqual(q.poll(109,0),None)
        self.assertIsNotNone(q.poll(111,0))

    def test_missing_timestamps_and_non_whisper_use_normal_chunk(self):
        self.assertEqual(word_groups({"source":"broadcaster_teletext_subtitles",
                                     "words":clip()["words"]}),[])
        self.assertEqual(word_groups(clip(words=[
            {"text":"bad","start":1.0,"end":1.4},
            {"text":"earlier","start":0.1,"end":0.2}])),[])

    def test_identifies_real_speaker_turns_per_clip_without_age_gender(self):
        data=clip(turns=[
            {"id":"SPEAKER_00","start":0.0,"end":1.2},
            {"id":"SPEAKER_01","start":1.2,"end":5.0}])
        groups=word_groups(data)
        self.assertGreaterEqual(len(groups),2)
        self.assertIn("[Speaker 1 · clip]",groups[0][2]["speaker_label"])
        self.assertIn("[Speaker 2 · clip]",groups[-1][2]["speaker_label"])
        self.assertNotIn("woman",str(groups).lower())
        self.assertNotIn("child",str(groups).lower())

    def test_diarization_never_erases_transcript_if_unavailable(self):
        with patch("tv_center.speaker_market.diarize_pcm",
                   side_effect=RuntimeError("Missing gated model")):
            meta={}
            text=_speaker_details(b"1234","Guten Morgen",meta,True,
                                  provider="pyannote")
        self.assertEqual(text,"Guten Morgen")
        self.assertIn("Missing gated model",meta["speaker_error"])
        with patch("tv_center.speaker_market.diarize_pcm") as worker:
            meta={}
            self.assertEqual(_speaker_details(b"1234","Hallo",meta,False),"Hallo")
            worker.assert_not_called()

    def test_config_requires_opt_in(self):
        self.assertFalse(CaptionConfig().speaker_enabled)
        self.assertFalse(CaptionConfig().options()["speaker_enabled"])
        cfg=CaptionConfig(speaker_enabled=True).validate()
        self.assertTrue(cfg.options()["speaker_enabled"])
        cfg.render({"original":"Test","speaker_label":"[Speaker 2 · clip]"})
        self.assertIn("Speaker 2",cfg.render(
            {"original":"Test","speaker_label":"[Speaker 2 · clip]"}))
        manual=CaptionConfig(speaker_enabled=True,
                             speaker_aliases=("Woman","Man","Child")).validate()
        rendered=manual.render({"original":"Test",
                    "speaker_index":3,"speaker_label":"[Speaker 3 · clip]"})
        self.assertIn("[Child · clip]",rendered)
        untouched=CaptionConfig(speaker_enabled=False,
                                 speaker_aliases=("Woman",)).validate()
        self.assertNotIn("Woman",untouched.render(
            {"original":"Test","speaker_index":1,
             "speaker_label":"[Speaker 1 · clip]"}))

if __name__=="__main__":
    unittest.main()
