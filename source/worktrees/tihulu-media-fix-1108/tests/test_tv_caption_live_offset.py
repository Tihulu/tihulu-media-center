"""Regression tests for live user-offset changes without restarting Whisper."""
import unittest
from dataclasses import replace
from kaffeine_next.caption_timing import CaptionConfig, CueQueue


class LiveCaptionOffsetRegressionTests(unittest.TestCase):
    def test_retime_preserves_pending_phrase_and_revision(self):
        base = CaptionConfig(mode="asr", source="de", offset_ms=0,
                             playback_delay_ms=12000, revision=7).validate()
        q = CueQueue(maximum=8)
        original = {"source": "de", "original": "Test phrase"}
        q.add(original, base, captured_start=10.0, captured_end=12.0,
              finished=14.0)
        self.assertEqual(len(q.items), 1)
        first = q.items[0]["due"]
        changed = replace(base, offset_ms=2500, font_px=32, opacity=0)
        q.retime(2500, changed)
        self.assertEqual(len(q.items), 1)
        self.assertAlmostEqual(q.items[0]["due"], first+2.5,places=5)
        self.assertEqual(q.items[0]["result"]["original"], "Test phrase")
        self.assertEqual(q.items[0]["revision"], 7)
        self.assertEqual(q.items[0]["config"].font_px, 32)

    def test_negative_offset_moves_subtitle_earlier(self):
        original = CaptionConfig(mode="asr", source="de").validate()
        q = CueQueue(maximum=8)
        q.add({"original": "Hallo", "source": "de"}, original,
              8.0, 10.0, 13.0)
        due = q.items[0]["due"]
        q.retime(-3000, replace(original, offset_ms=-3000))
        self.assertAlmostEqual(q.items[0]["due"], due-3.0)
        self.assertIsNotNone(q.poll(due-2.5, original.revision))

    def test_invalid_offset_shift_does_not_mutate(self):
        cfg = CaptionConfig()
        q = CueQueue()
        q.add({"original":"x"}, cfg,1.0,2.0,2.0)
        original=q.items[0]["due"]
        with self.assertRaises(ValueError):
            q.retime(30000, cfg)
        self.assertEqual(q.items[0]["due"], original)


if __name__=="__main__":
    unittest.main()
