"""Offline-only Hailo-10H (AI HAT+ 2) checks for Raspberry Pi 5.

Hailo-apps already ships a supported Whisper Base InferModel pipeline.
TIHULU never invokes the vendor's auto-downloading resource resolver.
The operator must install HailoRT, hailo-apps, compatible HEF weights and
decoder .npy assets explicitly. These checks never infer from 8GB host RAM
that the HAT has more RAM or can run arbitrary GGML/Argos models.
"""
from __future__ import annotations

from functools import lru_cache
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess


HEF_FIELDS = ("hailo_encoder_hef", "hailo_decoder_hef")
HAILO_ASSETS = HEF_FIELDS + ("hailo_npy_dir",)


def _is_regular(path, suffix):
    try:
        target = Path(path).expanduser()
        return (bool(path) and target.is_file() and not target.is_symlink()
                and target.suffix.lower() == suffix and
                target.stat().st_size > 1024)
    except (OSError, ValueError):
        return False


def model_files_ready(settings):
    """Actual local HEF + NPY files, no installer/network calls."""
    if not all(_is_regular(settings.get(key, ""), ".hef")
               for key in HEF_FIELDS):
        return False
    value = settings.get("hailo_npy_dir", "")
    if not value:
        return False
    try:
        folder = Path(value).expanduser()
        return (folder.is_dir() and not folder.is_symlink()
                and any(_is_regular(p, ".npy") for p in folder.glob("*.npy")))
    except (OSError, ValueError):
        return False


def runtime_available():
    """Only cheap metadata. Importing the vendor packages can load drivers."""
    try:
        return (importlib.util.find_spec("hailo_platform") is not None and
                importlib.util.find_spec("hailo_apps") is not None)
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def parse_architecture(output):
    """Do not confuse Hailo-8/8L or a device node with Hailo-10H."""
    if not isinstance(output, str):
        return ""
    match = re.search(r"^\s*Device Architecture\s*:\s*(HAILO[-_]?10H|HAILO[-_]?8L?|HAILO[-_]?10)\b",
                      output, flags=re.I|re.M)
    return match.group(1).upper().replace("-", "").replace("_", "") if match else ""


@lru_cache(maxsize=1)
def hardware_architecture():
    """Read firmware identity once per process; no downloads or model load."""
    executable = shutil.which("hailortcli")
    if not executable:
        return ""
    try:
        completed = subprocess.run(
            [executable, "fw-control", "identify"], timeout=3,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=False)
        if completed.returncode != 0:
            return ""
        return parse_architecture(completed.stdout.decode(
            "utf-8", errors="replace")[:6000])
    except (OSError, subprocess.TimeoutExpired):
        return ""


def readiness(settings, *, hardware=None, runtime=None):
    """Explains missing requirements, doesn't claim tested speech inference."""
    if hardware is not None:
        is_pi = bool(hardware.get("raspberry_pi_5"))
        nodes = hardware.get("npu",{}).get("devices",[])
        arch = hardware.get("npu",{}).get("hailo_arch","")
    else:
        try:
            is_pi = "Raspberry Pi 5" in Path("/proc/device-tree/model").read_text(
                encoding="utf-8",errors="replace")
        except OSError:
            is_pi = False
        nodes = [p.name for p in Path("/dev").glob("hailo*")]
        arch = hardware_architecture() if nodes else ""
    if not is_pi:
        return {"ready":False,"reason":"Requires Raspberry Pi 5"}
    if not any("hailo" in str(node).lower() for node in nodes):
        return {"ready":False,"reason":"Hailo device missing; install AI HAT+ 2 and driver"}
    if arch != "HAILO10H":
        return {"ready":False,"reason":("Hailo-10H firmware identity not verified "
                                       "(hailortcli fw-control identify)")}
    present = runtime_available() if runtime is None else bool(runtime)
    if not present:
        return {"ready":False,"reason":"hailo_platform + hailo_apps not installed in this Python"}
    if not model_files_ready(settings):
        return {"ready":False,"reason":("Install Hailo-10H Whisper Base encoder/decoder "
                                       "HEFs and NPY decoder files; then choose paths")}
    return {"ready":True,"reason":"Hailo-10H + local model files recognized; real inference test still required"}


def environment(settings):
    """Build explicit model-path environment. Never invent paths."""
    values={}
    for name, env in (
        ("hailo_encoder_hef","TIHULU_HAILO_ENCODER_HEF"),
        ("hailo_decoder_hef","TIHULU_HAILO_DECODER_HEF"),
        ("hailo_npy_dir","TIHULU_HAILO_WHISPER_NPY_DIR")):
        value=settings.get(name,"")
        if value:
            values[env]=str(Path(value).expanduser())
    return values
