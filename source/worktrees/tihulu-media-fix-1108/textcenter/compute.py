"""Offline-first speech/translation compute discovery and explicit backend selection.

Device presence and executable presence never imply model compatibility.
Nothing downloads models or makes network calls. CPU fallback is a device,
NOT an assertion that recognition/translation software is installed.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time

# Cache the *GPU readiness probe* briefly across 6-second live TV clips.
# Spawning another Python/CTranslate2 process for every clip causes jitter.
# A changed model marker invalidates the cache after explicit installation.
_managed_cuda_probe_cache = {}


def _managed_cuda_probe(worker):
    marker = worker.model_dir / ".tihulu-verified-faster-whisper-turbo"
    try:
        marker_mtime = marker.stat().st_mtime_ns
    except OSError:
        # The installed() predicate remains the ownership guard. A live
        # upgrade can temporarily remove the marker between checks.
        marker_mtime = None
    signature = (str(worker.python), str(worker.model_dir), marker_mtime)
    now = time.monotonic()
    previous = _managed_cuda_probe_cache.get(signature)
    if previous and now - previous[0] < 25:
        return previous[1]
    state = worker.probe()
    _managed_cuda_probe_cache.clear()
    _managed_cuda_probe_cache[signature] = (now,state)
    return state


# Source-language codes from OpenAI Whisper's published multilingual
# tokenizer vocabulary. Speech support and translator model availability
# are different; a language may transcribe without an installed translator.
LANGUAGES = tuple("""
en zh de es ru ko fr ja pt tr pl ca nl ar sv it id hi fi vi he uk el ms cs ro da hu ta no th ur hr bg lt la mi ml cy sk te fa lv bn sr az sl kn et mk br eu is hy ne mn bs kk sq sw gl mr pa si km sn yo so af oc ka be tg sd gu am yi lo uz fo ht ps tk nn mt sa lb my bo tl mg as tt haw ln ha ba jw su yue
""".split())
BACKENDS = ("auto", "cpu", "gpu", "npu")


def _command_output(argv: list[str], timeout: float = 1.5) -> str:
    try:
        r=subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace")[:400]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def detect_devices(*, executable_lookup=None, device_root=None,
                   model_path=None, system=None, command_runner=None) -> dict:
    lookup = executable_lookup or shutil.which
    dev = Path("/dev") if device_root is None else Path(device_root)
    model_file = model_path if model_path is not None else os.environ.get("TIHULU_WHISPER_MODEL", "")
    model = Path(model_file).expanduser() if model_file else None
    system = system or platform.system()
    run = command_runner or _command_output
    devices=[{"id":"cpu","name":platform.processor() or platform.machine() or "System CPU",
              "detected":True,"runtime_ready":True,
              "detail":"Always available for ordinary computation; speech model may be missing"}]
    smi = lookup("nvidia-smi") or next(
        (p for p in ("/usr/bin/nvidia-smi","/bin/nvidia-smi")
         if Path(p).is_file()), None)
    nvidia = run([smi,"--query-gpu=name","--format=csv,noheader,nounits"]) if smi else ""
    if not nvidia and device_root is None and command_runner is None:
        try:
            from tv_center.hardware_market import detect_hardware
            hardware = detect_hardware()
            if hardware["gpu"]["detected"]:
                nvidia = hardware["gpu"]["name"]
        except (ImportError,OSError,ValueError):
            pass
    if nvidia.strip():
        devices.append({"id":"gpu","name":nvidia.strip().splitlines()[0][:100],
                        "detected":True,"runtime_ready":False,
                        "detail":"NVIDIA GPU detected; model/backend CUDA compatibility not verified"})
    elif system=="Darwin" and platform.machine() in ("arm64","aarch64"):
        devices.append({"id":"gpu","name":"Apple Silicon GPU / Metal",
                        "detected":True,"runtime_ready":False,
                        "detail":"Metal device inferred; selected speech engine compatibility not verified"})
    else:
        devices.append({"id":"gpu","name":"No compatible GPU detected",
                        "detected":False,"runtime_ready":False,
                        "detail":"No verified CUDA or Metal speech backend"})
    try:
        npus=sorted(x.name for x in dev.glob("hailo*"))[:5]
    except OSError:
        npus=[]
    # OpenVINO GenAI can run exported Whisper models on supported Intel NPUs.
    # Hailo is a separate accelerator family and needs its own tested adapter.
    ov_model_dir=os.environ.get("TIHULU_OPENVINO_WHISPER_MODEL","")
    ov_model=Path(ov_model_dir).expanduser() if ov_model_dir else None
    ov_installed=(importlib.util.find_spec("openvino") is not None and
                  importlib.util.find_spec("openvino_genai") is not None)
    intel_npu=None
    if ov_installed:
        try:
            import openvino as ov
            intel_npu=next((d for d in ov.Core().available_devices
                            if d.split(".")[0]=="NPU"),None)
        except (ImportError,RuntimeError,OSError):
            intel_npu=None
    ov_ready=bool(intel_npu and ov_model and ov_model.is_dir() and
                  (ov_model/"config.json").is_file() and
                  any(ov_model.glob("*.xml")))
    # Hailo-10H can run the vendor's local low-level WhisperPipeline.
    # Require explicit local HEF + NPY files. We NEVER invoke the vendor
    # 'resolve_hef_paths' helper since it auto-downloads missing files.
    hailo_encoder=os.environ.get("TIHULU_HAILO_ENCODER_HEF","")
    hailo_decoder=os.environ.get("TIHULU_HAILO_DECODER_HEF","")
    hailo_npy=os.environ.get("TIHULU_HAILO_WHISPER_NPY_DIR","")
    henc=Path(hailo_encoder).expanduser() if hailo_encoder else None
    hdec=Path(hailo_decoder).expanduser() if hailo_decoder else None
    hnpy=Path(hailo_npy).expanduser() if hailo_npy else None
    hailo_ready=bool(
        npus and
        importlib.util.find_spec("hailo_apps") is not None and
        importlib.util.find_spec("hailo_platform") is not None and
        henc and henc.is_file() and
        hdec and hdec.is_file() and
        hnpy and hnpy.is_dir() and any(hnpy.glob("*.npy"))
    )
    detected_npu=bool(npus or intel_npu)
    npu_label=("Intel OpenVINO "+intel_npu if intel_npu else
               "Hailo NPU ("+", ".join(npus)+")" if npus else "No NPU detected")
    devices.append({"id":"npu","name":npu_label,
                    "detected":detected_npu,"runtime_ready":ov_ready or hailo_ready,
                    "detail":("Hailo local HEF/NPY Whisper model configured" if hailo_ready else
                              "OpenVINO NPU Whisper model locally configured" if ov_ready
                              else "NPU device alone is insufficient; compatible model/runtime missing.")})
    explicit_cli = os.environ.get("TIHULU_WHISPER_CLI", "")
    executable=(explicit_cli if explicit_cli and
                Path(explicit_cli).is_file() and os.access(explicit_cli, os.X_OK)
                else lookup("whisper-cli") or lookup("main"))
    gpu_model_dir=os.environ.get("TIHULU_FASTER_WHISPER_MODEL","")
    gpu_model=Path(gpu_model_dir).expanduser() if gpu_model_dir else None
    cuda_count=0
    if nvidia.strip() and importlib.util.find_spec("faster_whisper") is not None:
        try:
            import ctranslate2
            cuda_count=int(ctranslate2.get_cuda_device_count())
        except (ImportError,OSError,RuntimeError,ValueError):
            cuda_count=0
    gpu_ready=bool(cuda_count and gpu_model and gpu_model.is_dir() and
                   (gpu_model/"model.bin").is_file() and (gpu_model/"config.json").is_file())
    gpu_engine = "faster_whisper" if gpu_ready else None
    gpu_executable = None
    # The native Kaffeine market can compile whisper.cpp with GGML_CUDA=ON
    # into a user-owned executable. Those models are GGML .bin, not CT2 dirs.
    try:
        from tv_center.whisper_engine import WhisperRuntime
        managed = WhisperRuntime()
        if nvidia.strip() and managed.ready_gpu() and model and model.is_file() and model.stat().st_size>1024:
            gpu_ready = True
            gpu_engine = "whisper_cpp_cuda"
            gpu_executable = str(managed.cuda_binary)
            gpu_model = model
    except (ImportError,OSError,ValueError):
        pass
    # Unlike whisper.cpp's CUDA *build*, the Faster-Whisper CTranslate2
    # worker uses NVIDIA's prebuilt cuBLAS/cuDNN pip wheels. It does not
    # require nvcc or import GPU Python modules into Kaffeine's Qt process.
    if nvidia.strip() and device_root is None:
        try:
            from tv_center.cuda_faster_whisper import FasterWhisperCUDA
            managed_cuda = FasterWhisperCUDA()
            if managed_cuda.installed() and _managed_cuda_probe(managed_cuda)["ready"]:
                gpu_ready = True
                gpu_engine = "faster_whisper_managed"
                gpu_model = managed_cuda.model_dir
                gpu_executable = None
        except (ImportError, OSError, RuntimeError, ValueError):
            pass
    speech_ready=bool(executable and model and model.is_file() and model.stat().st_size>1024)
    argos=importlib.util.find_spec("argostranslate") is not None
    return {
        "devices":devices,"languages":list(LANGUAGES),"options":list(BACKENDS),
        "speech":{
            "engine":"whisper.cpp CLI","executable":executable,
            "model_path":str(model) if model else None,
            "model_installed":bool(model and model.is_file()),
            "ready_cpu":speech_ready,"ready_gpu":gpu_ready,"ready_npu":ov_ready or hailo_ready,
            "npu_engine":"hailo_whisper" if hailo_ready else
                          "openvino_genai" if ov_ready else None,
            "hailo_encoder_hef":str(henc) if henc else None,
            "hailo_decoder_hef":str(hdec) if hdec else None,
            "hailo_npy_dir":str(hnpy) if hnpy else None,
            "npu_model_path":str(ov_model) if ov_model else None,
            "gpu_model_path":str(gpu_model) if gpu_model else None,
            "gpu_engine":gpu_engine,
            "gpu_executable":gpu_executable,
            "note":"whisper.cpp model must already be installed; configured with TIHULU_WHISPER_MODEL. No inference can be claimed without real capture and model."
        },
        "translation":{
            "engine":"Argos Translate","python_package_installed":argos,
            "ready":argos,"installed_pairs_verified":False,
            "note":"Installed language pairs, not Python package alone, determine offline translation capability; no models auto-downloaded."
        },
        "policy":"auto selects a verified runtime, never assumes an NPU/GPU can run arbitrary Whisper or Argos models",
    }


def choose_backend(profile:dict, selection:str="auto") -> dict:
    if selection not in BACKENDS:
        raise ValueError("Backend must be auto/cpu/gpu/npu")
    available={x["id"]:x for x in profile["devices"]}
    if selection=="auto":
        # Whitelisted runtime, not GPU presence. Later adapters can report ready_gpu.
        for key in ("npu","gpu","cpu"):
            if profile["speech"].get("ready_"+key) and available[key]["detected"]:
                return {"selected":key,"ready":True,"detected_device":available[key]["name"]}
        return {"selected":"cpu","ready":False,
                "detected_device":available["cpu"]["name"],
                "reason":"No compatible installed speech executable/model"}
    item=available[selection]
    ready=bool(profile["speech"].get("ready_"+selection) and item["detected"])
    return {"selected":selection,"ready":ready,"detected_device":item["name"],
            "reason":None if ready else "Selected hardware is detected only or model runtime is missing"}


def validate_language(value):
    if value not in LANGUAGES:
        raise ValueError("Not a language supported by the installed Whisper tokenizer")
    return value
