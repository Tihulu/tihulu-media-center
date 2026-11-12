"""Live Whisper compute timing and CUDA weight-reuse regression tests.

No GPU, actual speech models, broadcast or external network needed.
"""
import sys
import types
import unittest
from unittest import mock

from textcenter.speech import _cached_cuda_whisper
from tv_center.captions import decode_segment


class WhisperTimingAndModelReuseTests(unittest.TestCase):
    def tearDown(self):
        _cached_cuda_whisper.cache_clear()

    def test_cuda_faster_whisper_model_is_not_reloaded_for_every_clip(self):
        _cached_cuda_whisper.cache_clear()
        loads=[]
        class FakeWhisperModel:
            def __init__(self, path, **kwargs):
                loads.append((path,kwargs))
        with mock.patch.dict(sys.modules, {"faster_whisper":
                                            types.SimpleNamespace(WhisperModel=FakeWhisperModel)}):
            first=_cached_cuda_whisper("/models/german-ct2")
            self.assertIs(first,_cached_cuda_whisper("/models/german-ct2"))
            self.assertEqual(len(loads),1)
            self.assertEqual(loads[0][1]["device"],"cuda")
            self.assertTrue(loads[0][1]["local_files_only"])
            other=_cached_cuda_whisper("/models/another-ct2")
            self.assertIsNot(first,other)
            self.assertEqual(len(loads),2)
        self.assertEqual(_cached_cuda_whisper.cache_info().maxsize,1)

    def test_asr_and_translation_stage_metrics_are_independently_reported(self):
        with mock.patch("tv_center.captions.asr_from_clip", return_value="Wie geht es dir?") as asr:
            with mock.patch("tv_center.captions.translate", return_value=("Nasılsın?",None)) as tr:
                result=decode_segment(b"\x47"+bytes(187),mode="asr",source="de",
                                      target="tr",targets=["tr"],page=150,model="/fake",
                                      previous_text="")
        self.assertEqual(result["original"],"Wie geht es dir?")
        self.assertEqual(result["translations"]["tr"],"Nasılsın?")
        self.assertEqual(result["asr_backend"],None)
        for name in ("teletext","asr","translation","total"):
            self.assertGreaterEqual(result["processing_ms"][name],0)
        self.assertEqual(result["processing_ms"]["teletext"],0)
        self.assertEqual(asr.call_count,1)
        self.assertEqual(tr.call_count,1)

    def test_teletext_first_avoids_whisper_cpu_load(self):
        with mock.patch("tv_center.captions.teletext_from_clip",
                        return_value="Broadcast caption") as teletext:
            with mock.patch("tv_center.captions.asr_from_clip") as whisper:
                result=decode_segment(b"\x47"+bytes(187),mode="auto",source="de",
                                      target="de",targets=(),page=150)
        self.assertEqual(result["original"],"Broadcast caption")
        self.assertEqual(result["source"],"broadcaster_teletext_subtitles")
        self.assertEqual(result["processing_ms"]["asr"],0)
        self.assertEqual(result["processing_ms"]["translation"],0)
        whisper.assert_not_called()
        self.assertEqual(teletext.call_args.args[1],"subtitle")

    def test_bad_asr_input_still_gives_error_and_timings(self):
        with mock.patch("tv_center.captions.asr_from_clip",
                        side_effect=RuntimeError("no audio stream")):
            result=decode_segment(b"\x47"+bytes(187),mode="asr",source="de",
                                  target="de",targets=(),page=150)
        self.assertEqual(result["original"],"")
        self.assertIn("no audio",result["error"])
        self.assertGreaterEqual(result["processing_ms"]["asr"],0)
