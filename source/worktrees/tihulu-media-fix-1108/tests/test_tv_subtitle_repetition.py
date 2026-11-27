"""Regression guards for sudden repeated text in live Whisper subtitles.

ASR-only: broadcast Teletext/DVB content and intentional double repetitions
must not be silently altered, even when a noisy Whisper chunk loops.
"""
import unittest
from unittest.mock import patch

from kaffeine_next.continuous_captions import (
    remove_repeated_prefix, collapse_asr_repetition_loops)
from tv_center.sentence_joiner import LiveSentenceJoiner
from tv_center.captions import decode_segment


class WhisperRepetitionTests(unittest.TestCase):
    def test_long_raw_overlap_beyond_original_16_word_limit(self):
        sentence = ("Heute sprechen wir im deutschen Fernsehen über eine "
                    "sehr wichtige neue Entscheidung in unserer Stadt und "
                    "über die nächsten konkreten Schritte der Verwaltung")
        self.assertGreater(len(sentence.split()), 16)
        newer = sentence + " Die Abstimmung beginnt morgen."
        self.assertEqual(remove_repeated_prefix(sentence, newer),
                         "Die Abstimmung beginnt morgen.")

    def test_no_fuzzy_or_generic_cross_segment_deletion(self):
        a = "Und das ist wirklich sehr wichtig für alle Menschen"
        b = "Und das ist wirklich eine andere Geschichte heute."
        self.assertEqual(remove_repeated_prefix(a, b), b)
        self.assertEqual(remove_repeated_prefix(
            "Ich bin noch hier ja", "ja, ja, ich höre", minimum_words=4),
            "ja, ja, ich höre")

    def test_three_or_more_repeated_full_phrases_are_collapsed(self):
        phrase = "Wir haben heute wichtige Nachrichten für Sie."
        text = " ".join([phrase]*4) + " Danach geht es weiter."
        self.assertEqual(collapse_asr_repetition_loops(text),
                         phrase + " Danach geht es weiter.")

    def test_two_spoken_repetitions_survive(self):
        doubled = "Nein, nein, das stimmt wirklich nicht."
        self.assertEqual(collapse_asr_repetition_loops(doubled), doubled)
        phrase = "Ich werde das nicht vergessen."
        self.assertEqual(collapse_asr_repetition_loops(phrase+" "+phrase),
                         phrase+" "+phrase)

    def test_short_numeric_jingle_and_runaway_one_word_loop(self):
        repeated = "Hallo "*18
        self.assertEqual(collapse_asr_repetition_loops(repeated),
                         "Hallo Hallo")
        self.assertEqual(collapse_asr_repetition_loops(
            "Ja ja ja"), "Ja ja ja")

    def test_song_mode_can_preserve_intentional_chorus(self):
        original = "La la la la la la la la"
        self.assertEqual(collapse_asr_repetition_loops(
            original, enabled=False), original)

    def test_sentence_assembler_does_not_append_long_overlap(self):
        joiner = LiveSentenceJoiner()
        initial = "Dies sind die aktuellen Nachrichten aus der Region"
        self.assertTrue(joiner.push(initial, language="de")["pending"])
        done = joiner.push("Nachrichten aus der Region und heute folgt ein Bericht.",
                           language="de")
        self.assertEqual(done["text"],
                         initial + " und heute folgt ein Bericht.")

    def test_sentence_assembler_preserves_short_genuine_repeat(self):
        joiner = LiveSentenceJoiner()
        self.assertTrue(joiner.push("Nein nein", language="de")["pending"])
        text = joiner.push("nein nein, das stimmt.", language="de")
        self.assertEqual(text["text"], "Nein nein nein nein, das stimmt.")

    def test_clean_before_translation_and_do_not_fake_word_clock(self):
        repeated = "Das ist ein sehr wichtiger Bericht. "
        with (patch("tv_center.captions.asr_from_clip",
                    return_value=repeated*3) as transcriber,
              patch("tv_center.captions.translate",
                    return_value=("Bu çok önemli bir haber.", None)) as translate):
            result = decode_segment(
                b"test captured bytes", mode="asr", source="de",
                target="tr", targets=("tr",), model="none",
                music_transcription=False)
        self.assertTrue(result["asr_repetitions_removed"])
        self.assertEqual(result["original"], repeated.strip())
        self.assertEqual(result["words"], [])
        translate.assert_called_once_with(repeated.strip(), "de", "tr")
        transcriber.assert_called_once()

    def test_explicit_song_vocals_kept_unchanged(self):
        repeated = "Wir singen dieses Lied zusammen. "
        with patch("tv_center.captions.asr_from_clip",
                   return_value=repeated*3), patch(
                       "tv_center.captions.translate", return_value=("", "unavailable")):
            result = decode_segment(b"captured bytes", mode="asr",
                                    source="de", target="de", targets=(),
                                    music_transcription=True)
        self.assertEqual(result["original"], repeated*3)
        self.assertFalse(result["asr_repetitions_removed"])


if __name__ == "__main__":
    unittest.main()
