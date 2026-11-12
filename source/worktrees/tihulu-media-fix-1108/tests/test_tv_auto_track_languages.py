"""Automatic DVB language matching must not erase requested subtitles."""
import unittest

from kaffeine_next.track_preferences import recommended_track, _signaled_language
from kaffeine_next.caption_timing import CaptionConfig
from tv_center.captions import decode_segment
from unittest.mock import patch

class TrackLanguageTests(unittest.TestCase):
    def test_selects_single_real_english_teletext_track(self):
        track={"pid":55,"page":888,"language":"eng","label":"English subtitles"}
        self.assertIs(recommended_track([track],"de",kind="teletext"),track)
        self.assertEqual(_signaled_language(track),"en")
        self.assertIsNone(recommended_track([
            {"pid":55,"page":888,"language":"eng"},
            {"pid":57,"page":777,"language":"fra"}],
            "de",kind="teletext"))

    def test_prefers_matching_audio_pid_when_more_than_one(self):
        tracks=[
            {"pid":100,"language":"eng"},
            {"pid":101,"language":"deu"},
            {"pid":102,"language":"fra"}]
        self.assertIs(recommended_track(tracks,"de",kind="audio"),tracks[1])
        self.assertIsNone(recommended_track(tracks,"tr",kind="audio"))

    def test_never_guesses_unlabelled_channel(self):
        self.assertIsNone(recommended_track([
            {"pid":100,"language":"und"}],"de",kind="audio"))
        self.assertIsNone(recommended_track([
            {"pid":100,"page":0,"language":"eng"}],"en",kind="teletext"))

    def test_user_checked_en_and_tr_stay_even_if_broadcast_is_en(self):
        cfg = CaptionConfig(mode="teletext",source="en",target="en",
            target_languages=("en","tr"),show_original=False,
            show_translation=True).validate()
        with patch("tv_center.captions.teletext_from_clip",
                   return_value="Good morning"), \
             patch("tv_center.captions.translate",
                   return_value=("Günaydın",None)) as translate:
            decoded=decode_segment(bytes([0x47])+bytes(187),
                                   mode="teletext",source="en",target="en",
                                   targets=("en","tr"),page=888)
        self.assertEqual(decoded["translations"]["en"],"Good morning")
        self.assertEqual(decoded["translations"]["tr"],"Günaydın")
        translate.assert_called_once_with("Good morning","en","tr")
        output=cfg.render(decoded)
        self.assertIn("[EN] Good morning",output)
        self.assertIn("[TR] Günaydın",output)
        both=__import__("dataclasses").replace(cfg,show_original=True)
        displayed=both.render(decoded)
        self.assertIn("Good morning",displayed)
        self.assertIn("[TR] Günaydın",displayed)
        self.assertEqual(displayed.count("Good morning"),1)


if __name__ == "__main__":
    unittest.main()
