#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure, offline MEDIA-REAL-AI-RUNTIME-ACCEPTANCE-14 evidence assessor.

This file never probes GPU/devices, imports model packages, launches a worker,
downloads data, scans HOME, changes settings, or accesses model files. It
assesses user-supplied (possibly synthetic) JSON metadata only.

A result is a proposed evidence classification, not an independent audit of
the supplied facts. Public release remains HOLD even for green observations.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re

ENGINES = (
    "whisper_cpu", "faster_whisper_cuda", "argos", "nllb",
    "madlad", "qwen_aligner",
)
# These minima come from the preserved app's *profile definitions*, not a
# guarantee of kernels fitting in free VRAM on any particular device.
PROFILE_MIN_VRAM_MIB = {
    "pi5": 0, "pi5_hat2": 0, "normal": 0,
    "performance": 12000, "experimental": 24000,
}
REQUIRED_LANGUAGES = ("en", "de", "tr")
REQUIRED_TRANSLATIONS = (
    ("en", "de"), ("de", "en"), ("en", "tr"), ("tr", "en"),
    ("de", "tr"), ("tr", "de"),
)
GPU_ENGINES = frozenset(("faster_whisper_cuda", "madlad"))
ALLOWED_CAUSES = frozenset((
    "NOT_TESTED", "MISSING_MODEL", "UNSUPPORTED_LANGUAGE",
    "MISSING_DEPENDENCY", "INSUFFICIENT_VRAM", "INCOMPATIBLE_GPU",
    "MODEL_LOADING_FAILURE", "INFERENCE_FAILURE", "EVIDENCE_HOLD",
    "REAL_INFERENCE_REPORTED",
))


def _observed_boolean(observation: dict, name: str):
    value = observation.get(name)
    if value is None:
        return None
    if type(value) is not bool:
        raise ValueError(f"{name}: expected true, false or null")
    return value


def classify_runtime(engine: str, observation: dict | None) -> str:
    """Separate likely failure classes without inventing GPU/model outcomes."""
    if engine not in ENGINES:
        raise ValueError("Unknown engine")
    if observation is None:
        return "NOT_TESTED"
    if not isinstance(observation, dict):
        raise ValueError("Runtime evidence must be a JSON object")
    weights = _observed_boolean(observation, "model_present")
    if weights is False:
        return "MISSING_MODEL"
    language = _observed_boolean(observation, "target_language_supported")
    if language is False:
        return "UNSUPPORTED_LANGUAGE"
    dependencies = _observed_boolean(observation, "dependencies_ready")
    if dependencies is False:
        return "MISSING_DEPENDENCY"
    if engine in GPU_ENGINES:
        minimum = observation.get("min_vram_mib", 0)
        available = observation.get("available_vram_mib")
        if type(minimum) is not int or minimum < 0:
            raise ValueError("min_vram_mib must be a nonnegative integer")
        if available is not None and (type(available) is not int or available < 0):
            raise ValueError("available_vram_mib must be nonnegative integer or null")
        if available is not None and minimum > 0 and available < minimum:
            return "INSUFFICIENT_VRAM"
        if (_observed_boolean(observation, "gpu_compatible") is False or
                _observed_boolean(observation, "cuda_device_visible") is False):
            return "INCOMPATIBLE_GPU"
    loaded = _observed_boolean(observation, "model_loaded")
    if loaded is False:
        return "MODEL_LOADING_FAILURE"
    inference = _observed_boolean(observation, "inference_success")
    if inference is False:
        return "INFERENCE_FAILURE"
    # Never count synthetic or mere "installed" marker/file evidence as
    # production PASS: the assessor did not independently inspect output.
    if (weights is True and dependencies is True and loaded is True and
            inference is True and observation.get("evidence") == "authorized_real"
            and _observed_boolean(observation, "offline") is True
            and _observed_boolean(observation, "isolated") is True
            and observation.get("fixture_id") and observation.get("model_digest")):
        return "REAL_INFERENCE_REPORTED"
    return "EVIDENCE_HOLD"


def _number(value, name: str) -> float:
    if (type(value) not in (int, float) or
            not math.isfinite(value) or value < 0):
        raise ValueError(name + ": expected nonnegative finite number")
    return float(value)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Unicode-aware punctuation-insensitive WER; does not erase accents."""
    if not isinstance(reference, str) or not isinstance(hypothesis, str):
        raise ValueError("WER inputs must be strings")
    lhs = re.findall(r"\w+", reference.casefold(), re.UNICODE)
    rhs = re.findall(r"\w+", hypothesis.casefold(), re.UNICODE)
    if not lhs:
        raise ValueError("Reference transcript must contain at least one word")
    costs = list(range(len(rhs) + 1))
    for i, a in enumerate(lhs, 1):
        nxt = [i]
        for j, b in enumerate(rhs, 1):
            nxt.append(min(nxt[-1] + 1, costs[j] + 1,
                           costs[j - 1] + (a != b)))
        costs = nxt
    return costs[-1] / len(lhs)


def asr_quality_case(*, language: str, context: str, wer: float,
                     auto_language_correct: bool,
                     hallucinated_on_silence: bool) -> bool:
    """Proposed thresholds for future benchmark, NOT measured results."""
    if language not in REQUIRED_LANGUAGES:
        raise ValueError("Only predefined EN/DE/TR benchmark languages")
    if context not in ("clean", "broadcast"):
        raise ValueError("Expected clean or broadcast corpus")
    if type(auto_language_correct) is not bool or type(hallucinated_on_silence) is not bool:
        raise ValueError("Expected boolean observations")
    return (_number(wer, "WER") <= (0.20 if context == "clean" else 0.35)
            and auto_language_correct and not hallucinated_on_silence)


def translation_quality_case(*, source: str, target: str,
                             adequacy_pct: float, proper_nouns_pct: float,
                             critical_omissions: int, invented_facts: int) -> bool:
    if (source, target) not in REQUIRED_TRANSLATIONS:
        raise ValueError("Unlisted translation direction")
    if type(critical_omissions) is not int or type(invented_facts) is not int:
        raise ValueError("Omission/hallucination counts must be integers")
    return (_number(adequacy_pct, "adequacy") >= 90
            and _number(proper_nouns_pct, "proper noun retention") >= 95
            and critical_omissions == 0 and invented_facts == 0)


def timing_quality_case(*, kind: str, audio_buffer_ms: int,
                        cue_delay_p95_ms: float, cue_drift_p95_ms: float,
                        recovery_seconds: float, playback_dropouts: int) -> bool:
    if kind not in ("tv", "radio"):
        raise ValueError("Unknown live surface")
    if type(audio_buffer_ms) is not int or not 0 <= audio_buffer_ms <= 60000:
        raise ValueError("Invalid configured audio buffer")
    if type(playback_dropouts) is not int or playback_dropouts < 0:
        raise ValueError("Invalid playback dropout count")
    return (_number(cue_delay_p95_ms, "delay") <= audio_buffer_ms + 3000
            and _number(cue_drift_p95_ms, "drift") <= 1500
            and _number(recovery_seconds, "recovery") <= 12
            and playback_dropouts == 0)


def assess_report(report: dict) -> dict:
    """Only classify supplied observations, never promote a public release."""
    if not isinstance(report, dict):
        raise ValueError("Report must be a JSON object")
    profile = report.get("profile")
    if profile is not None and profile not in PROFILE_MIN_VRAM_MIB:
        raise ValueError("Unknown profile")
    engines = report.get("engines", {})
    if not isinstance(engines, dict) or set(engines) - set(ENGINES):
        raise ValueError("Unknown engine evidence")
    decisions = {key: classify_runtime(key, engines.get(key)) for key in ENGINES}
    # This tool does not independently verify user claims or grant a release.
    return {
        "baseline": "2f5699eeb47505468bf3327be4dbdd89fed3dff1",
        "scope": "metadata-only evidence assessment",
        "profile": profile or "unspecified",
        "engine_decisions": decisions,
        "real_inference_reported": sum(
            value == "REAL_INFERENCE_REPORTED" for value in decisions.values()),
        "public_release": "HOLD",
        "reason": "Independent inference, TV/Radio behavioral parity, licensing "
                  "and owner approval remain external release gates.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path,
                        help="Explicitly supplied JSON observation file; otherwise empty")
    args = parser.parse_args(argv)
    if args.report:
        if args.report.stat().st_size > 256 * 1024:
            parser.error("Evidence metadata file exceeds 256 KiB")
        report = json.loads(args.report.read_text(encoding="utf-8"))
    else:
        report = {"profile": "performance", "engines": {}}
    print(json.dumps(assess_report(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
