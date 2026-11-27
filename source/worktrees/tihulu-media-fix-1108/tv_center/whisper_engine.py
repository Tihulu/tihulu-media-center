"""Optional CPU whisper.cpp CLI build from a pinned upstream release.

Executed only after owner confirmation from Settings; never during install,
boot, TV playback or model selection. CPU-only, user-owned. Requires git,
cmake and a C++ compiler. Real ARM64 performance not yet benchmarked.
"""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path.home()/".local/share/tihulu-tv-center/whisper-runtime"
MARKER = ".tihulu-managed-whisper"
RELEASE = "v1.9.5"
RELEASE_SHA_PREFIX = "d1be6fd"
REPOSITORY = "https://github.com/ggml-org/whisper.cpp.git"

class WhisperRuntimeError(RuntimeError):
    pass

class WhisperRuntime:
    def __init__(self, root=None):
        self.root = Path(root or ROOT).expanduser()

    @property
    def binary(self):
        return self.root/"build/bin/whisper-cli"

    @property
    def cuda_binary(self):
        return self.root/"build-cuda/bin/whisper-cli"

    def ready(self):
        return (self.root/MARKER).is_file() and self.binary.is_file() and os.access(self.binary, os.X_OK)

    def ready_gpu(self):
        return ((self.root/MARKER).is_file()
                and (self.root/".tihulu-cuda-ready").is_file()
                and self.cuda_binary.is_file()
                and os.access(self.cuda_binary, os.X_OK))

    def _guard(self):
        if self.root.is_symlink():
            raise WhisperRuntimeError("Symlink runtime path refused")
        if not self.root.resolve().is_relative_to(Path.home().resolve()):
            raise WhisperRuntimeError("Managed runtime must be under the user's home")
        if self.root.exists() and any(self.root.iterdir()) and not (self.root/MARKER).is_file():
            raise WhisperRuntimeError("Refusing to modify an unowned Whisper installation")

    def install(self):
        if os.geteuid() == 0:
            raise WhisperRuntimeError("Whisper engine must be built as an ordinary user, not root")
        self._guard()
        if self.ready():
            raise WhisperRuntimeError("Whisper engine already installed. Remove before rebuilding.")
        required = {"git":"git", "cmake":"cmake", "C++ compiler":"c++"}
        missing = [name for name, exe in required.items() if not shutil.which(exe)]
        if missing:
            raise WhisperRuntimeError("Build tools missing: " + ", ".join(missing) +
                                      ". On Debian/Pop!_OS run: sudo apt install git cmake g++")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root/MARKER).write_text("Managed by TIHULU TV Center\n", encoding="utf-8")
        source = self.root/"source"
        build = self.root/"build"
        try:
            if not source.exists():
                subprocess.run(["git", "clone", "--depth", "1", "--branch", RELEASE,
                                REPOSITORY, str(source)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, timeout=300, check=True)
            revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                               timeout=10).decode("ascii").strip()
            if not revision.startswith(RELEASE_SHA_PREFIX):
                raise WhisperRuntimeError("Upstream release commit was not the expected verified tag")
            subprocess.run(["cmake", "-S", str(source), "-B", str(build),
                            "-DCMAKE_BUILD_TYPE=Release",
                            "-DWHISPER_BUILD_TESTS=OFF", "-DGGML_CUDA=OFF"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=180, check=True)
            subprocess.run(["cmake", "--build", str(build), "--target", "whisper-cli",
                            "--config", "Release", "-j", "2"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=1800, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise WhisperRuntimeError("Whisper CPU build failed: " + str(exc)[:320]) from exc
        if not self.ready():
            raise WhisperRuntimeError("Compiled whisper-cli executable was not found")
        return "Whisper CPU engine installed. Restart TIHULU TV Center to activate: " + str(self.binary)

    def install_gpu(self):
        """Build a separate CUDA executable; CPU engine remains unaffected."""
        from .hardware_market import detect_hardware
        if os.geteuid() == 0:
            raise WhisperRuntimeError("CUDA Whisper must be built as your ordinary user")
        self._guard()
        if self.ready_gpu():
            return "CUDA whisper.cpp is already installed"
        hardware = detect_hardware()
        info = hardware["gpu"]
        if not info["detected"]:
            raise WhisperRuntimeError("No NVIDIA GPU detected. Check nvidia-smi / driver first.")
        if not info["cuda_compile_possible"]:
            raise WhisperRuntimeError(info["reason"] + ". Install supported CUDA toolkit.")
        required = ("git", "cmake", "c++")
        missing = [n for n in required if not shutil.which(n)]
        if missing:
            raise WhisperRuntimeError("Missing build tools: " + ", ".join(missing))
        nvcc = info["cuda_compiler"]
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root/MARKER).write_text("Managed by TIHULU TV Center\n",encoding="utf-8")
        source = self.root/"source"
        build = self.root/"build-cuda"
        try:
            if not source.is_dir():
                subprocess.run(["git","clone","--depth","1","--branch",RELEASE,
                     REPOSITORY,str(source)],stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                     check=True,timeout=300)
            revision = subprocess.check_output(
                ["git","-C",str(source),"rev-parse","HEAD"],timeout=12
            ).decode("ascii").strip()
            if not revision.startswith(RELEASE_SHA_PREFIX):
                raise WhisperRuntimeError("Pinned whisper.cpp source revision mismatch")
            env = os.environ.copy()
            env["CUDACXX"] = nvcc
            options=["-DGGML_CUDA=ON","-DWHISPER_BUILD_TESTS=OFF",
                     "-DCMAKE_BUILD_TYPE=Release"]
            if (info["name"] and
                    ("RTX 50" in info["name"] or "Blackwell" in info["name"])):
                options.append("-DCMAKE_CUDA_ARCHITECTURES=120")
            cfg = subprocess.run(["cmake","-S",str(source),"-B",str(build),*options],
                env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,timeout=300,check=False)
            if cfg.returncode:
                raise WhisperRuntimeError("CUDA configuration failed: " +
                    cfg.stderr.decode("utf-8","replace")[-650:])
            result = subprocess.run(["cmake","--build",str(build),"--target",
                 "whisper-cli","--parallel","2"],env=env,
                 stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                 stderr=subprocess.PIPE,timeout=2400,check=False)
            if result.returncode:
                raise WhisperRuntimeError("CUDA compilation failed: " +
                    result.stderr.decode("utf-8","replace")[-650:])
            if not self.cuda_binary.is_file():
                raise WhisperRuntimeError("CUDA Whisper executable was not produced")
            (self.root/".tihulu-cuda-ready").write_text("Built with GGML_CUDA=ON\n")
        except (OSError, subprocess.SubprocessError) as exc:
            raise WhisperRuntimeError("CUDA Whisper installation failed: " +
                                      str(exc)[:400]) from exc
        return "CUDA whisper.cpp compiled. Select GPU/Auto in the Market and save settings."

    def remove(self):
        self._guard()
        if not (self.root/MARKER).exists():
            return "No managed whisper.cpp engine installed"
        shutil.rmtree(self.root)
        return "Managed whisper.cpp CPU runtime removed; model files preserved"
