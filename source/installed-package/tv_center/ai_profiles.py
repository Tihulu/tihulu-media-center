"""Explicit offline-first AI model profiles for native TV Center.

A profile is a *plan*, not a virtual model installation. Only supported
runtimes are provisioned; Hailo AI HAT+ 2 memory is separate from host RAM.
No downloads, network probes, model imports, or device opens at import time.
"""
from __future__ import annotations

from pathlib import Path

# Installation steps are intentionally reusable across profiles.
# No unverified Hailo Whisper/translation backend is advertised.
PROFILES = {
    "pi5": {
        "name": "Raspberry Pi 5 · 8 GB",
        "description": "Whisper Tiny CPU + Argos offline. Limit speech inference to 3 CPU threads to reserve Pi 5 capacity for TV playback and translation; first benchmark a single target subtitle language.",
        "components": ("whisper_cpu", "tiny", "argos"),
        "speech": "tiny", "backend": "cpu", "translator": "argos",
        "min_ram_mib": 6000, "min_vram_mib": 0,
        "disk_gb_estimate": "2–4 GB including CPU runtime and language packs",
    },
    "pi5_hat2": {
        "name": "Raspberry Pi 5 · 8 GB + AI HAT+ 2 (8 GB NPU)",
        "description": "Whisper Base via Hailo-10H NPU when official encoder/decoder HEFs, NPY files and HailoRT are configured; CPU Tiny is the safe fallback. Argos still uses host CPU. HAT's 8GB is separate NPU memory.",
        "components": ("whisper_cpu", "tiny", "argos"),
        "speech": "tiny", "backend": "cpu", "translator": "argos",
        "min_ram_mib": 6000, "min_vram_mib": 0,
        "disk_gb_estimate": "2–4 GB CPU bundle; Hailo-10H Whisper assets installed separately",
    },
    "normal": {
        "name": "Normal · regular desktop / laptop",
        "description": "Whisper Small CPU + offline Argos + lightest supported speaker and sound-label models. Whisper lyric alignment remains the default fallback.",
        "components": ("whisper_cpu", "small", "argos",
                       "resemblyzer", "sound_labels"),
        "speech": "small", "backend": "cpu", "translator": "argos",
        "min_ram_mib": 7500, "min_vram_mib": 0,
        "disk_gb_estimate": "3–5 GB including runtime and translations",
    },
    "performance": {
        "name": "Performance · NVIDIA CUDA · min 12 GB VRAM / 16 GB RAM",
        "description": "CUDA Whisper Large-v3 Turbo + Argos + Resemblyzer + AST sound labels + Qwen3 ForcedAligner 0.6B. Whisper stays live for presenters and unsupported lyric languages. Requires 12 GB VRAM/16 GB RAM; music performance unverified.",
        "components": ("cuda_turbo", "whisper_cpu", "small", "argos",
                       "resemblyzer", "sound_labels", "qwen_aligner"),
        "speech": "small", "backend": "gpu", "translator": "argos",
        "min_ram_mib": 16000, "min_vram_mib": 12000,
        "disk_gb_estimate": "7–12 GB including CUDA wheels and fallback",
    },
    "experimental": {
        "name": "Experimental · NVIDIA CUDA · min 24 GB VRAM / 32 GB RAM",
        "description": "NVIDIA CUDA Turbo speech, MADLAD-400 3B, NLLB comparison and CPU fallback. Requires at least 24 GB NVIDIA VRAM and 32 GB host RAM; live speed unverified.",
        "components": ("cuda_turbo", "whisper_cpu", "small", "argos",
                       "resemblyzer", "sound_labels", "qwen_aligner", "nllb", "madlad"),
        "speech": "small", "backend": "gpu", "translator": "madlad",
        "min_ram_mib": 32000, "min_vram_mib": 24000,
        "disk_gb_estimate": "30–50 GB (large translations and dependencies)",
    },
}

COMPONENTS = {
    "whisper_cpu": ("whisper.cpp CPU engine", "Source compile; offline after installation"),
    "tiny": ("Whisper Tiny multilingual · 78 MB", "Verified GGML CPU weights"),
    "small": ("Whisper Small multilingual · 488 MB", "Verified GGML CPU weights"),
    "argos": ("Argos DE / EN / TR / FR", "6 directed language packs; all 12 cross-language directions via English pivot"),
    "cuda_turbo": ("Faster-Whisper Large-v3 Turbo CUDA", "CTranslate2 NVIDIA CUDA + checked model"),
    "resemblyzer": ("Resemblyzer speaker clustering", "Estimated voice clusters, not identity"),
    "sound_labels": ("AST AudioSet sound labels (CPU)", "Optional acoustic labels; Whisper speech unaffected"),
    "qwen_aligner": ("Qwen3 ForcedAligner 0.6B", "11 supported languages, Apache-2.0; Whisper fallback for TR/unsupported"),
    "nllb": ("NLLB-200 distilled 600M", "CC-BY-NC-4.0; non-commercial only"),
    "madlad": ("MADLAD-400 3B", "Apache-2.0; large CUDA-only translation"),
}


# Pre-download planning hints (NOT exact transfer sizes). Python packages,
# compiler dependencies and translation packs vary by OS and installation.
# Values must never be used as actual download progress denominators.
COMPONENT_DOWNLOADS = {
    "whisper_cpu": "source/build · size varies (no model weight)",
    "tiny": "~78 MB model download",
    "small": "~488 MB model download",
    "argos": "runtime + 6 DE/EN/TR/FR language packs · size varies by platform",
    "cuda_turbo": "~1.62 GB model + CUDA/Python dependencies (several GB possible)",
    "resemblyzer": "model + CPU PyTorch dependencies · size varies",
    "sound_labels": "AST AudioSet model + isolated CPU PyTorch · several GB possible",
    "qwen_aligner": "Qwen 0.6B weights + isolated PyTorch/CUDA · several GB possible",
    "nllb": "~2.5 GB model + Python dependencies (non-commercial license)",
    "madlad": "~12 GB model weights + CUDA/Python dependencies",
}


def component_estimate(component):
    if component not in COMPONENT_DOWNLOADS:
        raise ValueError("Unknown AI component")
    return COMPONENT_DOWNLOADS[component]


def progress_fraction(received, expected):
    """Only report percentages based on an actual known, positive file length."""
    if (type(received) is not int or received < 0 or
            type(expected) is not int or expected <= 0):
        return None
    return min(1000, received * 1000 // expected)


def profile(key):
    if key not in PROFILES:
        raise ValueError("Unknown AI profile")
    return PROFILES[key]


def hardware_issue(key, hardware):
    spec = profile(key)
    ram = hardware.get("ram_mib")
    if isinstance(ram,int) and ram < spec["min_ram_mib"]:
        return "System RAM below profile minimum"
    gpu = hardware.get("gpu") or {}
    if spec["min_vram_mib"]:
        if not gpu.get("detected"):
            return "A verified NVIDIA CUDA GPU is required"
        vram = gpu.get("vram_mib")
        if not isinstance(vram,int) or vram < spec["min_vram_mib"]:
            return "NVIDIA VRAM below profile minimum"
    if key.startswith("pi5") and not hardware.get("raspberry_pi_5"):
        return "This mode is for Raspberry Pi 5 hardware (preview only on this PC)"
    if key == "pi5_hat2":
        # /dev/hailo does not prove Hailo-10H model compatibility.
        npu = hardware.get("npu",{})
        detected = npu.get("devices") or []
        if not any("hailo" in str(device).lower() for device in detected):
            return "Hailo device not detected; HAT+ 2 mode is preview-only"
        if npu.get("hailo_arch") != "HAILO10H":
            return "Hailo-10H not verified (hailortcli fw-control identify)"
    return None


def local_status(key, *, library=None, starter=None):
    """Inspect cheap local markers; optional Argos pair discovery runs only on request.

    This is intentionally not called from the application's main startup.
    """
    if key not in COMPONENTS:
        raise ValueError("Unknown component")
    if key in ("tiny", "small"):
        from .model_market import ModelLibrary
        lib=library or ModelLibrary()
        return lib._path(key).is_file()
    if key == "whisper_cpu":
        from .whisper_engine import WhisperRuntime
        return WhisperRuntime().ready()
    if key == "argos":
        # A runtime alone does not prove six required directed packs.
        from .ai_provision import StarterAI
        return bool((starter or StarterAI(library=library)).status()[
            "translation_four_languages_ready"])
    if key == "cuda_turbo":
        from .cuda_faster_whisper import FasterWhisperCUDA
        return FasterWhisperCUDA().installed()
    if key == "resemblyzer":
        from .free_speakers import FreeSpeakerMarket
        return FreeSpeakerMarket().status()["installed"]
    if key == "sound_labels":
        from .audio_classifiers import AudioLabels
        return AudioLabels().installed("sound")
    if key == "qwen_aligner":
        from .qwen_forced_aligner import QwenForcedAlignerMarket
        return QwenForcedAlignerMarket().installed()
    if key == "nllb":
        from .translation_market import TranslationModelMarket
        return TranslationModelMarket().status()["installed"]
    if key == "madlad":
        from .translation_madlad import MadladMarket
        return MadladMarket().status()["installed"]
    return False


def missing_components(key, status):
    spec=profile(key)
    return tuple(component for component in spec["components"]
                 if not status.get(component, False))


def install_components(key, *, library=None, progress=None,
                       installer=None, events=None):
    """Install missing components sequentially; never select the mode.

    The optional event sink receives structured per-component status updates
    on the worker thread. No Qt object is touched by this function.
    For known GGML HTTP Content-Length, report actual bytes and true total.
    For subprocess/pip/HF transfers, a stage-only indeterminate state is used.
    """
    spec=profile(key)
    from .model_market import ModelLibrary
    lib=library or ModelLibrary()
    def notice(message):
        if progress:
            progress(message)
    def emit(component, state, **extra):
        if events:
            events({"component":component, "state":state, **extra})
    steps=[]
    # Check hardware BEFORE large downloads. The test seam bypasses hardware.
    from .hardware_market import detect_hardware
    issue=hardware_issue(key,detect_hardware()) if installer is None else None
    if issue:
        raise RuntimeError("Cannot install this mode on current hardware: "+issue)
    for index,component in enumerate(spec["components"],1):
        notice(f"{index}/{len(spec['components'])} · {COMPONENTS[component][0]}")
        emit(component,"checking")
        try:
            if local_status(component,library=lib):
                steps.append((component,"already installed"))
                emit(component,"already installed")
                continue
            emit(component,"installing")
            if installer is not None:
                installer(component)
            elif component=="whisper_cpu":
                from .whisper_engine import WhisperRuntime
                WhisperRuntime().install()
            elif component in ("tiny","small"):
                # Avoid flooding the Qt queue for each 256-KiB network read.
                # Progress updates arrive every approximately 4 MiB.
                last_bucket=[-1]
                def bytes_progress(received,total,*,code=component):
                    bucket=received // (4 * 1048576)
                    if bucket==last_bucket[0]:
                        return
                    last_bucket[0]=bucket
                    notice(f"{code}: {received // 1048576} MiB received")
                    emit(code,"downloading",received=received,total=total)
                lib.download(component,progress=bytes_progress)
                emit(component,"verifying")
            elif component=="argos":
                from .ai_provision import StarterAI
                from .runtime import AIRuntime
                rt=AIRuntime()
                if not rt.status()["installed"]:
                    rt.install_argos()
                StarterAI(library=lib)._setup_argos_packs(
                    progress=lambda msg:(
                        notice(msg),
                        emit(component,"installing",message=msg)))
            elif component=="cuda_turbo":
                from .cuda_faster_whisper import FasterWhisperCUDA
                FasterWhisperCUDA().install()
            elif component=="resemblyzer":
                from .free_speakers import FreeSpeakerMarket
                FreeSpeakerMarket().install()
            elif component=="sound_labels":
                from .audio_classifiers import AudioLabels
                AudioLabels().install("sound")
            elif component=="qwen_aligner":
                from .qwen_forced_aligner import QwenForcedAlignerMarket
                QwenForcedAlignerMarket().install()
            elif component=="nllb":
                from .translation_market import TranslationModelMarket
                TranslationModelMarket().install()
            elif component=="madlad":
                from .translation_madlad import MadladMarket
                MadladMarket().install()
            else:
                raise RuntimeError("Unknown installer")
            emit(component,"verifying")
            if not local_status(component,library=lib):
                raise RuntimeError(COMPONENTS[component][0] +
                                   " is not verified after installation")
            steps.append((component,"installed"))
            emit(component,"installed")
        except Exception as exc:
            emit(component,"failed",message=str(exc)[:200])
            raise
    return steps

def selection_patch(key, *, library, hardware, status, hailo_ready=False):
    """Plan activation separately from installing; fail closed on missing assets."""
    spec=profile(key)
    issue=hardware_issue(key,hardware)
    if issue:
        raise RuntimeError(issue)
    missing=missing_components(key,status)
    if missing:
        raise RuntimeError("Install all first; missing: " +
                           ", ".join(COMPONENTS[x][0] for x in missing))
    chosen=library._path(spec["speech"])
    if not Path(chosen).is_file():
        raise RuntimeError("Missing local CPU Whisper fallback model")
    # NPU is a separate, optional component. The HAT profile can always
    # use its installed Tiny CPU fallback, but promotes speech to Hailo-10H
    # only when model files and local runtime were actually inspected.
    backend = ("npu" if key=="pi5_hat2" and hailo_ready
               else spec["backend"])
    return {
        "active_profile":key,
        "asr_enabled":True,
        "translation_enabled":True,
        "pi_cpu_threads":3 if key.startswith("pi5") else 3,
        "backend":backend,
        "translation_model":spec["translator"],
        "model_path":str(chosen),
        "model_dir":str(library.root),
    }
