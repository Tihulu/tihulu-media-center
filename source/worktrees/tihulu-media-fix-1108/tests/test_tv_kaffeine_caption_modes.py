"""Regression tests: subtitle pages vs arbitrary Teletext news."""
import unittest
from unittest.mock import patch, call
from tv_center.captions import decode_segment

SAMPLE_TS = bytes([0x47]) + bytes(187)

class RealSubtitlePageTests(unittest.TestCase):
    def test_automatic_mode_uses_broadcaster_subtitle_page_and_asr_fallback(self):
        with patch("tv_center.captions.teletext_from_clip", return_value="") as tele:
            with patch("tv_center.captions.asr_from_clip", return_value="Actual spoken words") as asr:
                with patch("tv_center.captions.translate", return_value=("Gerçek sözler",None)):
                    output = decode_segment(SAMPLE_TS, mode="auto", page=150,
                                            source="de", target="tr", model="/models/tiny",
                                            service_id=771)
        self.assertEqual(tele.call_args.args[1], "subtitle")
        self.assertEqual(output["source"], "local_asr")
        self.assertEqual(output["translated"], "Gerçek sözler")
        self.assertEqual(asr.call_count, 1)

    def test_manual_page_mode_only_for_explicit_teletext_request(self):
        with patch("tv_center.captions.teletext_from_clip", return_value="News page 150") as tele:
            with patch("tv_center.captions.asr_from_clip") as asr:
                with patch("tv_center.captions.translate", return_value=(None,None)):
                    output = decode_segment(SAMPLE_TS, mode="page", page=150,
                                            source="de", target="de")
        self.assertEqual(tele.call_args.args[1], 150)
        self.assertEqual(asr.call_count, 0)
        self.assertEqual(output["source"], "teletext_page_150")

    def test_broadcast_subtitle_only_does_not_fallback_to_news(self):
        with patch("tv_center.captions.teletext_from_clip", return_value="Caption") as tele:
            with patch("tv_center.captions.asr_from_clip") as asr:
                with patch("tv_center.captions.translate", return_value=(None,None)):
                    output = decode_segment(SAMPLE_TS, mode="teletext", page=150,
                                            source="de", target="de")
        self.assertEqual(tele.call_args.args[1], "subtitle")
        self.assertEqual(asr.call_count, 0)
        self.assertEqual(output["source"], "broadcaster_teletext_subtitles")
