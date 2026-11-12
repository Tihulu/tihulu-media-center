# SPDX-License-Identifier: GPL-2.0-or-later
"""Disposable synthetic only — neither real GPU nor original owner data."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source/installed-package"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SOURCE))

from qa.media_real_ai_acceptance_14 import (
    ALLOWED_CAUSES, ENGINES, PROFILE_MIN_VRAM_MIB,
    REQUIRED_LANGUAGES, REQUIRED_TRANSLATIONS, assess_report,
    asr_quality_case, classify_runtime, timing_quality_case,
    translation_quality_case, word_error_rate,
)
from tv_center.ai_profiles import PROFILES, hardware_issue
from tv_center.ai_settings import DEFAULTS
from tv_center.ai_provision import translate_ready_three
from tv_center.radio_karaoke_router import karaoke_alignment_choice
from tv_center.translation_failover import TranslationFailover
from textcenter.compute import choose_backend


def proven(evidence="synthetic"):
    return {"model_present": True, "target_language_supported": True,
            "dependencies_ready": True, "model_loaded": True,
            "inference_success": True, "offline": True,
            "isolated": True, "evidence": evidence,
            "fixture_id": "synthetic-no-real-voice",
            "model_digest": "not-an-actual-model-digest"}


class RuntimeClassification(unittest.TestCase):
    def test_no_runtime_evidence_is_not_a_success(self):
        for engine in ENGINES:
            with self.subTest(engine=engine):
                self.assertEqual(classify_runtime(engine, None), "NOT_TESTED")

    def test_missing_model_has_separate_failure_class(self):
        self.assertEqual(classify_runtime("whisper_cpu", {"model_present": False}),
                         "MISSING_MODEL")

    def test_unsupported_language_is_not_missing_model(self):
        self.assertEqual(classify_runtime("qwen_aligner", {
            "model_present": True, "target_language_supported": False,
        }), "UNSUPPORTED_LANGUAGE")

    def test_missing_dependency_is_separate(self):
        self.assertEqual(classify_runtime("argos", {
            "model_present": True, "dependencies_ready": False,
        }), "MISSING_DEPENDENCY")

    def test_insufficient_vram_precedes_kernel_failure(self):
        self.assertEqual(classify_runtime("faster_whisper_cuda", {
            "model_present": True, "dependencies_ready": True,
            "available_vram_mib": 10000, "min_vram_mib": 12000,
            "cuda_device_visible": False,
        }), "INSUFFICIENT_VRAM")

    def test_cuda_incompatibility_separate_from_vram(self):
        self.assertEqual(classify_runtime("faster_whisper_cuda", {
            "model_present": True, "dependencies_ready": True,
            "available_vram_mib": 16000, "min_vram_mib": 12000,
            "cuda_device_visible": False,
        }), "INCOMPATIBLE_GPU")

    def test_model_loading_failure_separate_from_inference(self):
        self.assertEqual(classify_runtime("nllb", {
            "model_present": True, "dependencies_ready": True,
            "model_loaded": False,
        }), "MODEL_LOADING_FAILURE")

    def test_inference_failure_separate_from_loading(self):
        self.assertEqual(classify_runtime("argos", {
            "model_present": True, "dependencies_ready": True,
            "model_loaded": True, "inference_success": False,
        }), "INFERENCE_FAILURE")

    def test_marker_only_is_not_evidence_of_inference(self):
        for engine in ENGINES:
            self.assertEqual(classify_runtime(engine, {
                "model_present": True, "dependencies_ready": True,
            }), "EVIDENCE_HOLD")

    def test_fake_model_cannot_claim_success(self):
        self.assertEqual(classify_runtime("whisper_cpu", proven()),
                         "EVIDENCE_HOLD")

    def test_reported_real_evidence_is_not_release_approval(self):
        report = assess_report({"profile": "performance", "engines": {
            "whisper_cpu": proven("authorized_real"),
        }})
        self.assertEqual(report["engine_decisions"]["whisper_cpu"],
                         "REAL_INFERENCE_REPORTED")
        self.assertEqual(report["public_release"], "HOLD")
        self.assertEqual(report["real_inference_reported"], 1)

    def test_unrecognized_or_ill_typed_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            classify_runtime("unknown", None)
        with self.assertRaises(ValueError):
            classify_runtime("argos", {"model_present": "true"})
        with self.assertRaises(ValueError):
            classify_runtime("faster_whisper_cuda", {"available_vram_mib": -1})
        with self.assertRaises(ValueError):
            assess_report({"engines": {"not_an_engine": {}}})
        self.assertIn("MODEL_LOADING_FAILURE", ALLOWED_CAUSES)


class LanguageQuality(unittest.TestCase):
    def test_en_de_tr_is_complete_language_matrix(self):
        self.assertEqual(REQUIRED_LANGUAGES, ("en", "de", "tr"))
        self.assertEqual(len(REQUIRED_TRANSLATIONS), 6)

    def test_unicode_word_error_rate_matches_speech_examples(self):
        self.assertEqual(word_error_rate("Guten Morgen", "Guten"), 0.5)
        self.assertEqual(word_error_rate("Merhaba dünya", "Merhaba dünya"), 0.0)
        self.assertEqual(word_error_rate("Hello world!", "Hello, world"), 0.0)
        with self.assertRaises(ValueError):
            word_error_rate("", "some speech")

    def test_quality_thresholds_are_proposed_not_inference(self):
        for lang in REQUIRED_LANGUAGES:
            self.assertTrue(asr_quality_case(
                language=lang, context="clean", wer=0.20,
                auto_language_correct=True, hallucinated_on_silence=False))
            self.assertFalse(asr_quality_case(
                language=lang, context="clean", wer=0.21,
                auto_language_correct=True, hallucinated_on_silence=False))
            self.assertTrue(asr_quality_case(
                language=lang, context="broadcast", wer=0.35,
                auto_language_correct=True, hallucinated_on_silence=False))
            self.assertFalse(asr_quality_case(
                language=lang, context="broadcast", wer=0.0,
                auto_language_correct=True, hallucinated_on_silence=True))

    def test_translation_requires_accuracy_and_no_fabrications(self):
        for src, dst in REQUIRED_TRANSLATIONS:
            self.assertTrue(translation_quality_case(
                source=src, target=dst, adequacy_pct=90, proper_nouns_pct=95,
                critical_omissions=0, invented_facts=0))
            self.assertFalse(translation_quality_case(
                source=src, target=dst, adequacy_pct=100, proper_nouns_pct=100,
                critical_omissions=0, invented_facts=1))

    def test_timing_includes_configured_delay_not_raw_lag(self):
        self.assertTrue(timing_quality_case(
            kind="tv", audio_buffer_ms=10000, cue_delay_p95_ms=13000,
            cue_drift_p95_ms=1500, recovery_seconds=12,
            playback_dropouts=0))
        self.assertFalse(timing_quality_case(
            kind="tv", audio_buffer_ms=10000, cue_delay_p95_ms=14000,
            cue_drift_p95_ms=100, recovery_seconds=1,
            playback_dropouts=0))
        self.assertFalse(timing_quality_case(
            kind="radio", audio_buffer_ms=0, cue_delay_p95_ms=1000,
            cue_drift_p95_ms=1600, recovery_seconds=1,
            playback_dropouts=0))
        self.assertFalse(timing_quality_case(
            kind="radio", audio_buffer_ms=0, cue_delay_p95_ms=100,
            cue_drift_p95_ms=10, recovery_seconds=1,
            playback_dropouts=1))


class FrozenSourceContract(unittest.TestCase):
    def test_five_source_profiles_and_vram_not_suitable_for_experimental(self):
        self.assertEqual(set(PROFILES), set(PROFILE_MIN_VRAM_MIB))
        self.assertEqual(PROFILES["performance"]["min_vram_mib"], 12000)
        self.assertEqual(PROFILES["experimental"]["min_vram_mib"], 24000)
        simulated_5080 = {"ram_mib": 64000,
                          "gpu": {"detected": True, "vram_mib": 16303}}
        self.assertIsNone(hardware_issue("performance", simulated_5080))
        self.assertIn("VRAM", hardware_issue("experimental", simulated_5080))

    def test_asr_is_off_by_default_and_original_json_not_read(self):
        self.assertFalse(DEFAULTS["asr_enabled"])
        self.assertFalse(DEFAULTS["translation_enabled"])
        self.assertFalse(DEFAULTS["remote_gpu_enabled"])
        self.assertEqual(DEFAULTS["active_profile"], "")

    def test_qwen_tr_unsupported_de_en_available_only_when_installed(self):
        tr = karaoke_alignment_choice("tr", qwen_installed=True)
        en_missing = karaoke_alignment_choice("en", qwen_installed=False)
        de = karaoke_alignment_choice("de", qwen_installed=True)
        self.assertEqual(tr["engine"], "whisper")
        self.assertEqual(en_missing["engine"], "whisper")
        self.assertEqual(de["engine"], "qwen")
        self.assertTrue(tr["whisper_caption_independent"])

    def test_argos_mesh_needs_real_both_directions(self):
        directed = [{"source": a, "target": b} for a, b in (
            ("en", "de"), ("de", "en"), ("en", "tr"), ("tr", "en"))]
        self.assertTrue(translate_ready_three(directed))
        self.assertFalse(translate_ready_three(directed[:-1]))

    def test_auto_gpu_not_selected_without_ready_runtime(self):
        data = {"devices": [
            {"id": key, "name": key, "detected": True} for key in ("cpu", "gpu", "npu")
        ], "speech": {"ready_cpu": True, "ready_gpu": False, "ready_npu": False}}
        self.assertEqual(choose_backend(data, "auto")["selected"], "cpu")
        self.assertFalse(choose_backend(data, "gpu")["ready"])

    def test_nllb_failure_cooldown_then_argos_recovery(self):
        tick = [100.0]
        circuit = TranslationFailover(retry_seconds=180, clock=lambda: tick[0])
        attempts = [0]

        def failed_nllb(_text, _source, _target):
            attempts[0] += 1
            raise RuntimeError("Synthetic model load failed")

        def good_argos(_text, _source, _target):
            return "Guten Tag"

        for _ in range(2):
            outcome = circuit.translate("Good day", "en", "de", preferred="nllb",
                                        nllb=failed_nllb, argos=good_argos)
            self.assertEqual(outcome.engine, "argos-fallback")
        self.assertEqual(attempts[0], 1)
        tick[0] += 181
        circuit.translate("Good day", "en", "de", preferred="nllb",
                          nllb=failed_nllb, argos=good_argos)
        self.assertEqual(attempts[0], 2)

    def test_report_without_hardware_never_claims_public_pass(self):
        output = assess_report({"profile": "performance", "engines": {}})
        self.assertEqual(output["public_release"], "HOLD")
        self.assertEqual(output["real_inference_reported"], 0)
        self.assertTrue(all(x == "NOT_TESTED"
                            for x in output["engine_decisions"].values()))


if __name__ == "__main__":
    unittest.main()
