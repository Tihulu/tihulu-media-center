"""Evidence-based plain lyrics and subtitle clock regressions."""
import unittest
from unittest.mock import patch
from tv_center.lyrics_sync import lookup_synced_lyrics, LiveLyricMatcher, LyricCue
from tv_center.media_ai import _align_plain_lyrics_to_local_audio


class PlainLyricsTests(unittest.TestCase):
    def setUp(self):
        self.record = {"trackName":"Example Track","artistName":"Example Artist",
                       "duration":210,"instrumental":False,
                       "syncedLyrics":None,
                       "plainLyrics":"We walked through the morning rain\n"
                                     "And shared the quiet city streets\n"
                                     "Our voices echoed in the dark"}

    def test_plain_text_is_explicit_opt_in_and_has_no_fake_cues(self):
        with patch("tv_center.lyrics_sync._get_json",return_value=self.record):
            cues,details=lookup_synced_lyrics(
                title="Example Track",artist="Example Artist",
                online=True,allow_plain=True)
            self.assertEqual(cues,[])
            self.assertEqual(details["status"],"plain")
            self.assertEqual(len(details["plain_lines"]),3)
            self.assertEqual(details["alignment"],"awaiting_real_audio_ASR")

    def test_default_old_api_does_not_invent_timestamps(self):
        with patch("tv_center.lyrics_sync._get_json",return_value=self.record):
            cues,details=lookup_synced_lyrics(
                title="Example Track",artist="Example Artist",online=True)
        self.assertEqual(cues,[])
        self.assertEqual(details["status"],"unsynced_only")

    def test_real_words_produce_monotonic_approximate_match(self):
        lines=self.record["plainLyrics"].splitlines()
        matcher=LiveLyricMatcher(lines)
        self.assertIsNone(matcher.observe("Well here's an unrelated broadcaster greeting"))
        first=matcher.observe("We walked through the morning rain")
        self.assertIsNotNone(first)
        self.assertEqual(first["index"],0)
        self.assertGreaterEqual(first["confidence"],0.74)
        second=matcher.observe("And shared the quiet city streets")
        self.assertIsNotNone(second)
        self.assertEqual(second["index"],1)
        self.assertIsNone(matcher.observe("We walked through the morning rain"))
        self.assertTrue(first["approximate"])

    def test_random_low_overlap_has_no_lyric_output(self):
        matcher=LiveLyricMatcher(self.record["plainLyrics"].splitlines())
        self.assertIsNone(matcher.observe("The rose kokar rose metropol fm greeting"))
        self.assertIsNone(matcher.observe("hi hi"))

    def test_short_turkish_refrain_preserves_proper_words(self):
        words=["Gül kokar gül","Sevgin içimde büyür"]
        bad=LiveLyricMatcher(words)
        self.assertIsNone(bad.observe("Rose kokar rose"))
        good=LiveLyricMatcher(words)
        matched=good.observe("Gül kokar gül")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["text"],"Gül kokar gül")

    def test_file_cues_anchor_only_to_actual_asr(self):
        cues=[LyricCue(5,6.4,"We walked through the morning"),
              LyricCue(6.4,7.2,"rain"),
              LyricCue(18,19,"And shared the quiet"),
              LyricCue(19,21,"city streets")]
        aligned=_align_plain_lyrics_to_local_audio(
            self.record["plainLyrics"].splitlines(),cues)
        self.assertGreaterEqual(len(aligned),1)
        self.assertEqual(aligned[0].text,"We walked through the morning rain")
        self.assertEqual(aligned[0].start,5)
        self.assertEqual(aligned[0].provenance,"plain lyrics / observed ASR")
        self.assertEqual(_align_plain_lyrics_to_local_audio(
            self.record["plainLyrics"].splitlines(),[]),[])


if __name__=="__main__":
    unittest.main()
