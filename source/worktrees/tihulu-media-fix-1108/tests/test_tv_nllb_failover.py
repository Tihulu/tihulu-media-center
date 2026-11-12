"""NLLB meta-tensor recovery and safety of live subtitle fallback.

No model weights, tuner, network or GPU needed in CI. Real model loading is
tested separately by the owner through Model Market's explicit self-test.
"""
from __future__ import annotations
import os
import tempfile
import types
import unittest
from unittest import mock

from kaffeine_next.caption_timing import CaptionConfig
from tv_center.captions import decode_segment, translate
from tv_center.translation_failover import TranslationFailover, live_failover
from tv_center.translation_market import unmaterialized_tensors, _load_nllb


class TranslationRecoveryTests(unittest.TestCase):
    def setUp(self):
        live_failover().reset()

    def tearDown(self):
        live_failover().reset()
        _load_nllb.cache_clear()

    def test_meta_failure_uses_real_installed_argos_and_circuit_breaks(self):
        moment=[50.0]
        engine=TranslationFailover(retry_seconds=180,clock=lambda:moment[0])
        nllb=mock.Mock(side_effect=NotImplementedError(
            "Cannot copy out of meta tensor; no data!"))
        argos=mock.Mock(side_effect=["Hello","Merhaba"])
        first=engine.translate("Hallo","de","en",
            preferred="nllb",nllb=nllb,argos=argos)
        second=engine.translate("Hallo","de","tr",
            preferred="nllb",nllb=nllb,argos=argos)
        self.assertEqual(first.text,"Hello")
        self.assertEqual(second.text,"Merhaba")
        self.assertEqual(first.engine,"argos-fallback")
        self.assertEqual(second.engine,"argos-fallback")
        self.assertIn("switched",first.warning)
        self.assertEqual(nllb.call_count,1)
        self.assertEqual(argos.call_count,2)
        moment[0] += 181
        nllb.side_effect=None
        nllb.return_value="Hallo!"
        recovered=engine.translate("Hallo","de","en",
            preferred="nllb",nllb=nllb,argos=argos)
        self.assertEqual(recovered.engine,"nllb")
        self.assertEqual(nllb.call_count,2)

    def test_no_installed_pack_keeps_original_and_reports_languages(self):
        with mock.patch.dict(os.environ,{"TIHULU_TRANSLATOR_MODEL":"nllb"}), \
             mock.patch("tv_center.translation_service.translate_nllb",
                        side_effect=RuntimeError(
                            "Cannot copy out of meta tensor; no data!")), \
             mock.patch("tv_center.captions._translate_argos_local",
                        side_effect=RuntimeError("no de->tr Argos pack")), \
             mock.patch("tv_center.captions.teletext_from_clip",
                        return_value="Guten Morgen"):
            phrase, issue=translate("Guten Morgen","de","tr")
            self.assertIsNone(phrase)
            self.assertIn("DE",issue)
            self.assertNotIn("meta tensor",issue)
            result=decode_segment(bytes([0x47])+bytes(187),
                                  mode="teletext",page=150,
                                  source="de",target="tr",targets=("tr",))
        self.assertEqual(result["original"],"Guten Morgen")
        self.assertIsNone(result["error"])
        self.assertIn("tr",result["translation_errors"])
        caption=CaptionConfig(mode="teletext",source="de",target="tr",
            target_languages=("tr",),show_original=False,
            show_translation=True).validate().render(result)
        self.assertIn("Guten Morgen",caption)
        self.assertNotIn("meta tensor",caption)

    def test_successful_fallback_records_actual_engine_and_warning(self):
        with mock.patch.dict(os.environ,{"TIHULU_TRANSLATOR_MODEL":"nllb"}), \
             mock.patch("tv_center.translation_service.translate_nllb",
                        side_effect=NotImplementedError("meta tensor")), \
             mock.patch("tv_center.captions._translate_argos_local",
                        return_value="Merhaba"), \
             mock.patch("tv_center.captions.teletext_from_clip",
                        return_value="Hallo"):
            result=decode_segment(bytes([0x47])+bytes(187),
                                  mode="teletext",page=150,
                                  source="de",target="tr",targets=("tr",))
        self.assertEqual(result["translations"]["tr"],"Merhaba")
        self.assertEqual(result["translation_engines"]["tr"],"argos-fallback")
        self.assertIn("tr",result["translation_warnings"])
        self.assertNotIn("tr",result["translation_errors"])
        self.assertIsNone(result["error"])

    def test_both_english_and_turkish_targets_survive_nllb_failure(self):
        choices={"en":"Good morning","tr":"Günaydın"}
        def argos(text, source, target):
            return choices[target]
        with mock.patch.dict(os.environ,{"TIHULU_TRANSLATOR_MODEL":"nllb"}), \
             mock.patch("tv_center.translation_service.translate_nllb",
                        side_effect=NotImplementedError(
                            "Cannot copy out of meta tensor; no data!")) as nllb, \
             mock.patch("tv_center.captions._translate_argos_local",
                        side_effect=argos) as fallback, \
             mock.patch("tv_center.captions.teletext_from_clip",
                        return_value="Guten Morgen"):
            result=decode_segment(bytes([0x47])+bytes(187),
                                  mode="teletext",page=150,
                                  source="de",target="en",
                                  targets=("en","tr"))
        self.assertEqual(result["translations"],choices)
        self.assertEqual(result["translation_errors"],{})
        self.assertEqual(result["translation_engines"],{
            "en":"argos-fallback","tr":"argos-fallback"})
        self.assertEqual(nllb.call_count,1)
        self.assertEqual(fallback.call_count,2)

    def test_meta_parameters_cannot_be_treated_as_loaded_weights(self):
        model=mock.Mock()
        model.named_parameters.return_value=[
            ("encoder.layers.0.weight",types.SimpleNamespace(is_meta=True))]
        model.named_buffers.return_value=[]
        self.assertEqual(unmaterialized_tensors(model),
                         ["encoder.layers.0.weight"])

        fake_tokenizer=mock.Mock()
        fake_tokenizer.from_pretrained.return_value=object()
        fake_loader=mock.Mock(return_value=model)
        fake_transformers=types.SimpleNamespace(
            AutoTokenizer=fake_tokenizer,
            AutoModelForSeq2SeqLM=types.SimpleNamespace(from_pretrained=fake_loader))
        fake_torch=types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda:True))
        with mock.patch("tv_center.translation_market.TranslationModelMarket") as market, \
             mock.patch.dict("sys.modules",{
                 "transformers":fake_transformers,"torch":fake_torch}):
            market.return_value.status.return_value={"installed":True}
            market.return_value.model="/fake/pinned-nllb"
            _load_nllb.cache_clear()
            with self.assertRaisesRegex(RuntimeError,"unmaterialized meta"):
                _load_nllb()
        self.assertFalse(model.to.called)
        self.assertFalse(model.to_empty.called)
        self.assertFalse(fake_loader.call_args.kwargs["low_cpu_mem_usage"])
        self.assertIsNone(fake_loader.call_args.kwargs["device_map"])

    def test_normal_loaded_weights_can_move_to_cuda(self):
        model=mock.Mock()
        model.named_parameters.return_value=[
            ("w",types.SimpleNamespace(is_meta=False))]
        model.named_buffers.return_value=[]
        tok=mock.Mock()
        loader=mock.Mock(return_value=model)
        tf=types.SimpleNamespace(
            AutoTokenizer=types.SimpleNamespace(from_pretrained=mock.Mock(return_value=tok)),
            AutoModelForSeq2SeqLM=types.SimpleNamespace(from_pretrained=loader))
        torch=types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda:True))
        with mock.patch("tv_center.translation_market.TranslationModelMarket") as market, \
             mock.patch.dict("sys.modules",{"transformers":tf,"torch":torch}):
            market.return_value.status.return_value={"installed":True}
            market.return_value.model="/fake/nllb"
            _load_nllb.cache_clear()
            loaded_model,_,device,_=_load_nllb()
        self.assertIs(loaded_model,model)
        self.assertEqual(device,"cuda")
        model.to.assert_called_once_with("cuda")

if __name__=="__main__":
    unittest.main()
