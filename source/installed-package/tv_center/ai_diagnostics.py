"""Read-only ASR hardware and model readiness report for the current TV user.

Never opens DVB, downloads models, loads model weights or runs speech inference.
Detected hardware is not represented as an actually working backend.
"""
from __future__ import annotations
import json
from pathlib import Path


def inspect():
    from tv_center.ai_settings import AISettings
    from tv_center.hardware_market import detect_hardware
    from tv_center.runtime import AIRuntime
    from tv_center.translation_market import TranslationModelMarket
    from tv_center.whisper_engine import WhisperRuntime
    from textcenter.compute import detect_devices, choose_backend

    settings = AISettings()
    settings.configure_environment()
    model = settings.values.get("model_path", "")
    hardware = detect_hardware()
    profile = detect_devices(model_path=model)
    choice = choose_backend(profile, settings.values["backend"])
    whisper = WhisperRuntime()
    gpu = hardware["gpu"]
    npu = hardware["npu"]
    return {
        "policy": "Read-only: no RF access, downloads, model inference or TV playback change.",
        "whisper": {
            "enabled": settings.values["asr_enabled"],
            "model": Path(model).name if model else None,
            "model_installed": bool(model and Path(model).is_file()),
            "requested_backend": settings.values["backend"],
            "selected_backend": choice.get("selected"),
            "backend_ready": bool(choice.get("ready")),
            "backend_reason": choice.get("reason"),
            "runtime_cpu": whisper.ready(),
            "runtime_cuda": bool(
                whisper.ready_gpu() or
                profile["speech"].get("gpu_engine") == "faster_whisper_managed"),
            "runtime_npu": bool(profile["speech"].get("ready_npu")),
            "known_gpu_engine": profile["speech"].get("gpu_engine"),
            "gpu_model_path": profile["speech"].get("gpu_model_path"),
        },
        "hardware": {
            "cpu": hardware["cpu"],
            "nvidia_gpu": gpu["name"],
            "gpu_detected": gpu["detected"],
            "vram_mib": gpu["vram_mib"],
            "cuda_compiler": gpu["cuda_version"],
            "cuda_compiler_path": gpu.get("cuda_compiler"),
            "cuda_compile_possible": gpu["cuda_compile_possible"],
            "cuda_note": gpu["reason"],
            "npu_detected": npu["detected"],
            "npu_runtime_ready": npu["ready"],
            "npu_detail": npu["detail"],
            "raspberry_pi_5": hardware["raspberry_pi_5"],
        },
        "translation": {
            "enabled": settings.values["translation_enabled"],
            "engine": settings.values["translation_model"],
            "argos_runtime_installed": AIRuntime().status()["installed"],
            "nllb_model_installed": TranslationModelMarket().status()["installed"],
            "readiness_note": (
                "Model files are not proof of a valid translation. "
                "Use AI Model Market → Language packs → Test NLLB offline. "
                "On NLLB failure, real installed Argos packs are tried; "
                "original captions are preserved otherwise.")
        },
        "caption_ui": {
            "feature_revision": "multilingual-nllb-failover-2026-11-08",
            "includes":"short word-timed captions, backup translator, speaker options",
            "restart_required": (
                "After reinstalling, close the old Live Captions sidecar "
                "using Stop subtitles & Exit and reopen via Kaffeine.")
        },
        "npu_explanation": (
            "RTX Tensor Cores are part of the NVIDIA GPU, not a separate "
            "Hailo/Intel NPU; no NPU is expected on this desktop."
            if gpu["detected"] and not npu["detected"] else
            "Use dedicated NPU only if its compatible model/runtime is installed."),
        "next_step": (
            "GPU READY: run 'tihulu-tv-center ai-check --deep' to test CUDA "
            "with a synthetic audio sample; real TV performance remains unverified."
            if choice.get("selected") == "gpu" and choice.get("ready") else
            "RTX GPU found but no ready CUDA speech engine. In Model Market "
            "press 'Install CUDA Faster-Whisper Large-v3 Turbo · no nvcc needed', "
            "not the advanced source-build button. The GPU installer uses "
            "cuBLAS >=12.8, cuDNN 9 and CTranslate2 >=4.6.3 and tests "
            "real model inference after downloading verified weights. "
            "CUDA Toolkit nvcc is optional and ONLY needed when building "
            "whisper.cpp CUDA from source."
            if gpu["detected"] and not gpu["cuda_compile_possible"] else
            "GPU found, but the user-owned CUDA whisper.cpp runtime is missing. "
            "Install CUDA Whisper in Model Market, then select a larger "
            "multilingual GGML model and save backend Auto/GPU."
            if gpu["detected"] and not whisper.ready_gpu() else
            "Install/activate a multilingual Whisper model and matching runtime in Model Market."
        )
    }


def main():
    import sys
    args = sys.argv[2:] if len(sys.argv)>1 and sys.argv[1]=="ai-check" else sys.argv[1:]
    if args not in ([], ["--deep"]):
        print("Usage: tihulu-tv-center ai-check [--deep]",file=sys.stderr)
        return 2
    report = inspect()
    if args == ["--deep"]:
        # Explicitly requested full model loading, never DVB/RF access.
        from .cuda_faster_whisper import FasterWhisperCUDA
        report["policy"] = (
            "Deep opt-in: synthetic local CUDA model inference only; "
            "no RF access, model downloads or TV playback changes.")
        report["deep_gpu_selftest"] = FasterWhisperCUDA().inference_selftest()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
