"""Regression for retaining speech after ASR chunk boundaries."""
import unittest
from tv_center.sentence_joiner import LiveSentenceJoiner


class LiveRadioSentenceTests(unittest.TestCase):
    def test_german_sentence_completed_across_windows(self):
        j=LiveSentenceJoiner()
        first=j.push("Ich bin heute mit dem",language="de")
        self.assertTrue(first["pending"])
        self.assertEqual(first["text"],"")
        done=j.push("Zug nach Berlin gefahren.",language="de")
        self.assertTrue(done["complete"])
        self.assertEqual(done["text"],
                         "Ich bin heute mit dem Zug nach Berlin gefahren.")
        self.assertFalse(done["pending"])

    def test_second_sentence_fragment_is_kept(self):
        j=LiveSentenceJoiner()
        item=j.push("Das ist korrekt. Aber ich",language="de")
        self.assertEqual(item["text"],"Das ist korrekt.")
        self.assertTrue(item["pending"])
        done=j.push("denke anders.",language="de")
        self.assertEqual(done["text"],"Aber ich denke anders.")

    def test_empty_chunk_finishes_previous_text_without_fabrication(self):
        j=LiveSentenceJoiner()
        j.push("Hier beginnt ein Satz",language="de")
        item=j.push("",language="de",silent=True)
        self.assertEqual(item["text"],"Hier beginnt ein Satz")
        self.assertTrue(item["closed_by_pause"])

    def test_unpunctuated_radio_segment_has_bounded_latency(self):
        j=LiveSentenceJoiner(max_chunks=3)
        self.assertTrue(j.push("Ein langer Satz",language="de")["pending"])
        self.assertTrue(j.push("wird heute im Radio",language="de")["pending"])
        done=j.push("noch weiter gesprochen",language="de")
        self.assertFalse(done["complete"])
        self.assertTrue(done["continued"])
        self.assertTrue(done["text"].endswith(" …"))

    def test_language_changes_do_not_mix_sentences(self):
        j=LiveSentenceJoiner()
        j.push("Die Wetterlage",language="de")
        first=j.push("Breaking news",language="en")
        self.assertEqual(first["text"],"Die Wetterlage …")
        next_=j.push("is here.",language="en")
        self.assertEqual(next_["text"],"Breaking news is here.")

    def test_music_marker_not_assembled(self):
        j=LiveSentenceJoiner()
        self.assertEqual(j.push("[music]",language=None)["text"],"[music]")


if __name__=="__main__":
    unittest.main()
