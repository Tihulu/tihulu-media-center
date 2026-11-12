"""Offline regression tests for arbitrary target languages and honest fallbacks."""
import unittest
import os
from pathlib import Path
import tempfile
from unittest.mock import patch, Mock

from tv_center.language_codes import language_code
from tv_center.translation_market import nllb_token_id
from tv_center.captions import decode_segment, asr_from_clip
from kaffeine_next.caption_timing import CaptionConfig

TS = bytes([0x47]) + bytes(187)


class MultilingualCaptions(unittest.TestCase):
    def test_language_codes_and_nllb_tokens(self):
        self.assertEqual(language_code("pol"), "pl")
        self.assertEqual(language_code("es"), "es")
        self.assertEqual(language_code("zho_Hant", nllb=True), "zho_Hant")
        with self.assertRaises(ValueError):
            language_code("zz")
        with self.assertRaises(ValueError):
            language_code("../../unsafe")
        tokenizer = Mock(lang_code_to_id={"spa_Latn": 42})
        self.assertEqual(nllb_token_id(tokenizer, "es"), ("spa_Latn", 42))
        with self.assertRaises(ValueError):
            nllb_token_id(tokenizer, "jpn_Jpan")

    def test_unavailable_translation_keeps_original_visible(self):
        cfg = CaptionConfig(source="pl", target="tr",
                            target_languages=("tr",),
                            show_original=False, show_translation=True).validate()
        with patch("tv_center.captions.teletext_from_clip", return_value="Dzień dobry"):
            with patch("tv_center.captions.translate",
                       return_value=(None, "Polish to Turkish pack unavailable")):
                result = decode_segment(TS, mode="teletext", page=250,
                                        source="pl", target="tr", targets=("tr",))
        self.assertEqual(result["original"], "Dzień dobry")
        self.assertEqual(result["translations"], {})
        self.assertIn("PL · original", cfg.render(result))
        self.assertIn("TR unavailable", cfg.render(result))
        self.assertIn("tr", result["translation_errors"])

    def test_custom_language_and_no_translation_needed(self):
        with patch("tv_center.captions.teletext_from_clip", return_value="Bonjour!"):
            with patch("tv_center.captions.translate") as translate:
                result = decode_segment(TS, mode="teletext", page=366,
                                        source="fre", target="fr", targets=("fr",))
        translate.assert_not_called()
        self.assertEqual(result["source_language"], "fr")
        self.assertEqual(result["translations"]["fr"], "Bonjour!")
        self.assertTrue(CaptionConfig(source="ja", target="de",
                       target_languages=(), show_original=False,
                       show_translation=True).validate())

    def test_alternate_audio_language_is_suggested_without_wrong_transcription(self):
        streams = [{"codec_type":"audio","index":3,"id":"0x123",
                    "tags":{"language":"eng"}}]
        with patch("tv_center.captions._program_streams", return_value=streams):
            with self.assertRaisesRegex(RuntimeError, "Broadcast offers: EN"):
                asr_from_clip("test.ts", "de", "/not/used/model",
                              service_id=42, audio_pid=0x120)

    def test_selected_audio_pid_can_recover_to_same_language(self):
        from textcenter.compute import LANGUAGES, validate_language
        self.assertGreaterEqual(len(LANGUAGES), 100)
        self.assertEqual(validate_language("pl"), "pl")
        self.assertEqual(validate_language("ja"), "ja")
        streams = [
            {"codec_type":"audio", "index":3, "id":"0x122",
             "tags":{"language":"deu", "title":"Stereo"}},
            {"codec_type":"audio", "index":4, "id":"0x123",
             "tags":{"language":"eng", "title":"Stereo"}},
        ]
        with tempfile.NamedTemporaryFile() as model:
            with patch.dict(os.environ, {"TIHULU_TV_ASR_BACKEND":"cpu"}):
                with patch("tv_center.captions._program_streams", return_value=streams), \
                     patch("tv_center.captions._run") as ff, \
                     patch("textcenter.compute.detect_devices",
                           return_value={"speech":{"engine":"whisper.cpp CLI"}}), \
                     patch("textcenter.compute.choose_backend",
                           return_value={"selected":"cpu","ready":True}), \
                     patch("textcenter.speech.transcribe_pcm",
                           return_value="Guten Tag") as transcribe:
                    ff.return_value.returncode = 0
                    ff.return_value.stdout = bytes(64000)
                    diagnostic = {}
                    result = asr_from_clip(Path("sample.ts"), "de", model.name,
                                           service_id=42, audio_pid=0x120,
                                           diagnostics=diagnostic)
        self.assertEqual(result, "Guten Tag")
        self.assertIn("switched", diagnostic["audio_notice"])
        transcribe.assert_called_once()
        self.assertEqual(ff.call_args.args[0][
            ff.call_args.args[0].index("-map")+1], "0:3")

    def test_real_teletext_language_is_not_rejected_without_whisper_model(self):
        with patch("tv_center.captions.teletext_from_clip", return_value="Cześć!"):
            result = decode_segment(TS, mode="teletext", page=250,
                                    source="pol", target="pl", targets=("pl",))
        self.assertEqual(result["original"], "Cześć!")
        self.assertEqual(result["source_language"], "pl")

if __name__ == "__main__":
    unittest.main()
