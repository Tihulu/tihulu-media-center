"""Hardware suitability for verified offline TV speech and translation models.

Detection is read-only and does not equate GPU presence with CUDA runtime
readiness. Raspberry Pi's optional Hailo accelerator is a separate backend.
"""
from __future__ import annotations
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess


def _command(command, timeout=3):
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                timeout=timeout,check=False)
        return result.stdout.decode("utf-8","replace").strip() if result.returncode == 0 else ""
    except (OSError,subprocess.TimeoutExpired):
        return ""


def _find_executable(executable, alternatives=()):
    return shutil.which(executable) or next(
        (name for name in alternatives if Path(name).is_file()
         and os.access(name,os.X_OK)), None)


def quick_hardware():
    """Cheap startup snapshot; NO subprocess, compiler probe or model import.

    Detailed GPU/NPU detection runs in a worker only after the UI is visible.
    """
    try:
        ram=int(re.search(r"^MemTotal:\s+(\d+)\s+kB",
                          Path("/proc/meminfo").read_text(),re.M).group(1))//1024
    except (OSError,AttributeError,ValueError):
        ram=None
    try:
        pi5="Raspberry Pi 5" in Path("/proc/device-tree/model").read_text(
            encoding="utf-8",errors="replace")
    except OSError:
        pi5=False
    hailo=[p.name for p in Path("/dev").glob("hailo*")]
    return {
        "cpu":platform.machine() or "CPU",
        "architecture":platform.machine(),
        "ram_mib":ram,
        "raspberry_pi_5":pi5,
        "gpu":{"detected":False,"name":"Checking in background…",
               "vram_mib":None,"compute_capability":None,
               "driver_tool":False,"cuda_compiler":None,"cuda_version":None,
               "cuda_compile_possible":False,
               "reason":"Full CUDA discovery is deferred until after first paint"},
        "npu":{"detected":bool(hailo),"devices":hailo,"hailo_arch":"",
               "ready":False,
               "detail":"NPU model compatibility unverified"},
    }


def detect_hardware():
    nvidia_smi = _find_executable("nvidia-smi",
                                 ("/usr/bin/nvidia-smi","/bin/nvidia-smi",
                                  "/usr/local/bin/nvidia-smi"))
    gpu = _command([nvidia_smi,"--query-gpu=name,memory.total,compute_cap",
                    "--format=csv,noheader,nounits"]) if nvidia_smi else ""
    if not gpu and nvidia_smi:
        gpu = _command([nvidia_smi,"--query-gpu=name,memory.total",
                        "--format=csv,noheader,nounits"])
    name, vram_mib, compute_cap = None, None, None
    if gpu:
        fields=[x.strip() for x in gpu.splitlines()[0].split(",")]
        name=fields[0][:120]
        if len(fields)>1:
            try: vram_mib=int(float(fields[1]))
            except (TypeError,ValueError): pass
        if len(fields)>2:
            compute_cap=fields[2]
    if not name:
        # NVIDIA module provenance is useful when PATH or nvidia-smi is
        # unavailable inside the Qt app's sanitized launcher environment.
        for p in Path("/proc/driver/nvidia/gpus").glob("*/information"):
            try:
                txt=p.read_text(encoding="utf-8",errors="replace")[:4000]
                match=re.search(r"^Model:\s*(.+)$",txt,re.M)
                if match:
                    name=match.group(1).strip()[:120]; break
            except OSError:
                pass
    # CUDA toolkit installations from NVIDIA are frequently not in PATH.
    # Discover any versioned /usr/local/cuda-12.8, -13.0, -13.1... toolkits
    # without requiring users to change their shell/Conda environment.
    cuda_candidates = [
        Path("/usr/local/cuda/bin/nvcc"),
        Path("/opt/cuda/bin/nvcc"),
    ]
    cuda_candidates.extend(sorted(
        Path("/usr/local").glob("cuda-*/bin/nvcc"),reverse=True))
    for env_path in ("CUDA_HOME","CUDA_PATH"):
        value=os.environ.get(env_path)
        if value and len(value)<512:
            cuda_candidates.append(Path(value)/"bin/nvcc")
    nvcc=_find_executable("nvcc",tuple(map(str,cuda_candidates)))
    version_text=_command([nvcc,"--version"]) if nvcc else ""
    version=re.search(r"release\s+(\d+)\.(\d+)",version_text)
    cuda_version=(int(version.group(1)),int(version.group(2))) if version else None
    is_blackwell=bool(name and re.search(r"\b(?:RTX\s*50\d{2}|Blackwell)\b",name,re.I))
    can_compile=bool(nvcc and cuda_version and
                     (not is_blackwell or cuda_version >= (12,8)))
    ram_mib=None
    try:
        meminfo=Path("/proc/meminfo").read_text(encoding="ascii")
        match=re.search(r"^MemTotal:\s+(\d+)\s+kB",meminfo,re.M)
        if match: ram_mib=int(match.group(1))//1024
    except OSError:
        pass
    pi5=False
    try:
        pi5="Raspberry Pi 5" in Path("/proc/device-tree/model").read_bytes().decode(
            "utf-8","replace")
    except OSError:
        pass
    npu=list(Path("/dev").glob("hailo*"))
    from .pi_hailo import hardware_architecture
    hailo_arch=hardware_architecture() if npu else ""
    intel_npu = False
    try:
        import openvino as ov
        intel_npu = any(device.split(".")[0] == "NPU"
                        for device in ov.Core().available_devices)
    except (ImportError,OSError,RuntimeError):
        pass
    # /dev/accel may indicate Intel NPU hardware but does not prove an
    # OpenVINO speech model can execute there.
    accel = list(Path("/dev/accel").glob("accel*"))
    available_npu = [p.name for p in npu] + (
        ["Intel OpenVINO NPU"] if intel_npu else
        ["Intel accel node (runtime unverified)"] if accel else [])
    return {
        "cpu": platform.processor() or platform.machine() or "CPU",
        "architecture": platform.machine(),
        "ram_mib":ram_mib,
        "gpu":{"detected":bool(name),"name":name or "Not detected",
               "vram_mib":vram_mib,"compute_capability":compute_cap,
               "driver_tool":bool(nvidia_smi),
               "cuda_compiler":nvcc,"cuda_version":(
                   ".".join(map(str,cuda_version)) if cuda_version else None),
               "cuda_compile_possible":can_compile,
               "reason":(
                   "No nvcc compiler for optional whisper.cpp GPU source build. "
                   "RTX 50-series requires CUDA Toolkit >=12.8 only if building "
                   "whisper.cpp; prebuilt Faster-Whisper CUDA can run without nvcc."
                   if is_blackwell and not nvcc else
                   "Installed nvcc CUDA version is too old for Blackwell; >=12.8 required"
                   if is_blackwell and not can_compile else
                   "CUDA toolkit (nvcc) not detected; GPU can be detected without a CUDA speech runtime"
                   if name and not nvcc else
                   "CUDA compile toolchain detected; inference still requires a compiled runtime and tested model"
                   if name else "No NVIDIA GPU found")},
        "npu":{"detected":bool(available_npu),"devices":available_npu,
               "hailo_arch":hailo_arch,"ready":False,
               "detail":("Hailo "+(hailo_arch or "unverified device")+
                         ": compatible HEF/NPY and runtime are required"
                         if npu else
                         "Intel NPU detected: requires OpenVINO GenAI and NPU-exported Whisper model"
                         if available_npu else
                         "No NPU detected; optional NPU is not required")},
        "raspberry_pi_5":pi5,
    }


def model_fit(key, size_mb, hardware):
    """Estimated disk/RAM suitability, never performance or WER claims."""
    gpu=hardware["gpu"]
    ram=hardware.get("ram_mib")
    disk_mb=int(size_mb)
    # Model weights plus whisper.cpp runtime/activations; conservative margin.
    required_ram_mb=max(700, disk_mb * 3)
    if ram is not None and required_ram_mb > ram * 0.70:
        return "Not recommended · insufficient free-system-memory margin"
    if gpu["detected"] and gpu["vram_mib"] is not None:
        if required_ram_mb < gpu["vram_mib"] * 0.75:
            if gpu["cuda_compile_possible"]:
                return "Recommended for NVIDIA CUDA once runtime installed"
            try:
                from .cuda_faster_whisper import FasterWhisperCUDA
                cuda = FasterWhisperCUDA()
                if cuda.installed():
                    return ("RTX VRAM fits estimate · Faster-Whisper CUDA is "
                            "installed (GGML CPU model is separate)")
            except (ImportError, OSError, ValueError, RuntimeError):
                pass
            return ("Fits VRAM · GPU whisper.cpp needs nvcc >=12.8; "
                    "prebuilt Faster-Whisper does not require nvcc")
        return "Large for GPU VRAM · CPU or smaller quantized model"
    if key.startswith("large") and hardware["raspberry_pi_5"]:
        return "Not recommended for Pi 5 live captions"
    if key.startswith("medium") and hardware["raspberry_pi_5"]:
        return "May be too slow for Pi 5 live captions"
    return "CPU capable in principle · live speed unverified"
