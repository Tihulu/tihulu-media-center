"""User-approved CUDA Faster-Whisper with a persistent isolated worker.

No nvcc, system Python pip installs, tuner access, or downloads during live TV.
The GPU model is downloaded only from an explicit Model Market action.
Whisper.cpp CPU/CUDA engines and their GGML models remain untouched.
"""
from __future__ import annotations
import atexit
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import threading

ROOT = Path.home() / ".local/share/tihulu-tv-center/cuda-faster-whisper"
MODEL_ID = "dropbox-dash/faster-whisper-large-v3-turbo"
REVISION = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
MODEL_SHA256 = "e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da"
MARKER = ".tihulu-owned-faster-whisper-cuda"
MODEL_MARKER = ".tihulu-verified-faster-whisper-turbo"
PARTIAL_MARKER = ".tihulu-faster-whisper-install-in-progress"


class FasterWhisperCUDA:
    def __init__(self, root=None, model_dir=None):
        self.root = Path(root or ROOT).expanduser()
        if model_dir is None:
            from .ai_settings import AISettings
            model_dir = AISettings().values.get("model_dir", "")
        base = (Path(model_dir).expanduser() if model_dir else
                Path.home()/".local/share/tihulu-tv-center")
        self.model_dir = base / "faster-whisper-models" / "large-v3-turbo"

    @property
    def python(self):
        return self.root / "bin/python3"

    def _guard(self):
        if self.root.is_symlink() or not self.root.resolve().is_relative_to(
                Path.home().resolve()):
            raise RuntimeError("CUDA worker runtime must be a non-symlinked user directory")
        if (self.root.exists() and any(self.root.iterdir()) and
                not (self.root / MARKER).is_file()):
            raise RuntimeError("Refusing to overwrite unowned CUDA runtime")
        base = self.model_dir.parent
        if (self.model_dir.is_symlink() or base.is_symlink() or
                self.model_dir.resolve() == Path("/") or
                (self.model_dir.exists() and any(self.model_dir.iterdir()) and
                 not (self.model_dir / MODEL_MARKER).exists() and
                 not (self.model_dir / PARTIAL_MARKER).exists())):
            raise RuntimeError("Refusing to overwrite unowned Faster-Whisper model directory")

    def installed(self):
        return ((self.root / MARKER).is_file() and self.python.is_file()
                and (self.model_dir / MODEL_MARKER).is_file()
                and (self.model_dir / "model.bin").is_file()
                and (self.model_dir / "config.json").is_file()
                and (self.model_dir / "tokenizer.json").is_file())

    def worker_env(self):
        env = os.environ.copy()
        site_packages = list((self.root / "lib").glob("python*/site-packages"))
        libdirs = []
        for site in site_packages:
            for package in ("cublas", "cudnn"):
                location = site / "nvidia" / package / "lib"
                if location.is_dir():
                    libdirs.append(str(location))
        if libdirs:
            previous = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = ":".join(libdirs + ([previous] if previous else []))
        repository = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = repository + os.pathsep + env.get("PYTHONPATH", "")
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        return env

    def probe(self):
        if not self.installed():
            return {"ready": False, "reason": "Managed CUDA worker or verified CT2 model missing"}
        try:
            proc = subprocess.run(
                [str(self.python), "-m", "tv_center.cuda_faster_whisper", "--probe"],
                env=self.worker_env(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25, check=False)
            if proc.returncode:
                return {"ready": False, "reason": proc.stderr.decode(
                    "utf-8", "replace")[-230:] or "CUDA backend probe failed"}
            data = json.loads(proc.stdout)
            return {"ready": bool(data.get("devices", 0)),
                    "reason": None if data.get("devices", 0) else "CTranslate2 sees no CUDA device"}
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return {"ready": False, "reason": str(exc)[:180]}

    def inference_selftest(self):
        """Opt-in true CTranslate2/Blackwell model+kernel smoke test; no RF."""
        if not self.installed():
            return {"ready":False, "reason":"Install managed CUDA model first"}
        try:
            proc = subprocess.run(
                [str(self.python), "-m", "tv_center.cuda_faster_whisper", "--selftest"],
                env=self.worker_env(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=150, check=False)
            if proc.returncode:
                return {"ready":False, "reason":(
                    proc.stderr.decode("utf-8","replace")[-700:]
                    or "CUDA model inference failed")}
            result = json.loads(proc.stdout)
            return {"ready":bool(result.get("model_loaded") and result.get("cuda_tested")),
                    "reason":result.get("error"), "device":result.get("device"),
                    "model":result.get("model")}
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return {"ready":False,"reason":str(exc)[:300]}

    def install(self):
        if os.geteuid() == 0:
            raise RuntimeError("Install GPU models as your normal desktop user")
        self._guard()
        from .hardware_market import detect_hardware
        if not detect_hardware()["gpu"]["detected"]:
            raise RuntimeError("NVIDIA GPU missing; check nvidia-smi/driver")
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / MARKER).write_text("TIHULU user-owned CUDA Faster-Whisper venv\n")
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(self.root)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=240, check=False)
        if result.returncode:
            raise RuntimeError("Creating CUDA worker venv failed: " +
                               result.stderr.decode("utf-8", "replace")[-300:])
        packages = (
            "faster-whisper>=1.2,<2", "ctranslate2>=4.6.3,<5",
            "huggingface_hub>=0.28,<1",
            "nvidia-cublas-cu12>=12.8,<13", "nvidia-cudnn-cu12>=9,<10")
        result = subprocess.run(
            [str(self.python), "-m", "pip", "install", "--disable-pip-version-check",
             *packages], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=2700, check=False)
        if result.returncode:
            raise RuntimeError("CUDA worker dependencies failed: " +
                               result.stderr.decode("utf-8", "replace")[-450:])
        # This explicit installation command is the only time network access
        # is allowed. The worker never downloads during a live TV broadcast.
        result = subprocess.run(
            [str(self.python), "-m", "tv_center.cuda_faster_whisper",
             "--download", str(self.model_dir)],
            stdin=subprocess.DEVNULL, env={
                **self.worker_env(), "HF_HUB_OFFLINE": "0"},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5400,
            check=False)
        if result.returncode:
            raise RuntimeError("Pinned Faster-Whisper model download failed: " +
                               result.stderr.decode("utf-8", "replace")[-440:])
        check = self.probe()
        if not check["ready"]:
            raise RuntimeError("CUDA runtime installed but not ready: " + str(check["reason"]))
        verification = self.inference_selftest()
        if not verification["ready"]:
            raise RuntimeError(
                "CUDA libraries and model installed, but real GPU inference failed: " +
                str(verification.get("reason") or "unknown")[:500])
        return ("NVIDIA Faster-Whisper Large-v3 Turbo installed and a real CUDA "
                "model inference self-test passed (without nvcc). "
                "Restart captions and select GPU/Auto. Live speed remains unmeasured.")

    def remove(self):
        self._guard()
        if not (self.root / MARKER).is_file():
            return "No managed CUDA runtime"
        shutil.rmtree(self.root)
        # Deliberately preserve downloaded model files, including external SSD.
        return "Managed CUDA Python runtime removed; model files preserved"


class _PersistentCUDAWorker:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.path = None

    def _stop(self):
        p = self.process
        self.process = None
        self.path = None
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    def close(self):
        with self.lock:
            self._stop()

    def transcribe(self, pcm, language, model_path):
        return self.transcribe_details(pcm, language, model_path)["text"]

    def transcribe_details(self, pcm, language, model_path, *, music_mode=False,
                           speech_priority=False, timeout_s=90):
        if (type(timeout_s) not in (int,float) or not 4 <= timeout_s <= 90):
            raise ValueError("Invalid CUDA transcription deadline")
        if not isinstance(pcm, bytes) or not 0 < len(pcm) <= 4_000_000:
            raise RuntimeError("Invalid 32-kHz PCM audio segment")
        worker = FasterWhisperCUDA()
        if not worker.installed() or str(worker.model_dir) != str(model_path):
            raise RuntimeError("CUDA Faster-Whisper model not installed in Market")
        payload = json.dumps({
            "audio": base64.b64encode(pcm).decode("ascii"),
            "language": language, "model": str(worker.model_dir),
            "music_mode":bool(music_mode),
            "speech_priority":bool(speech_priority),
        }, separators=(",", ":")).encode("utf-8") + b"\n"
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._stop()
                self.process = subprocess.Popen(
                    [str(worker.python), "-u", "-m",
                     "tv_center.cuda_faster_whisper", "--serve"],
                    env=worker.worker_env(), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    bufsize=0, close_fds=True)
            try:
                self.process.stdin.write(payload)
                self.process.stdin.flush()
                ready, _, _ = select.select(
                    [self.process.stdout], [], [], float(timeout_s))
                if not ready:
                    self._stop()
                    raise TimeoutError(
                        f"CUDA Faster-Whisper clip exceeded {timeout_s}s "
                        "budget; real-time captions use a shorter deadline")
                reply = self.process.stdout.readline(10000)
                if not reply.endswith(b"\n"):
                    self._stop()
                    raise RuntimeError("GPU worker exited or returned incomplete output")
                result = json.loads(reply)
                if result.get("error"):
                    raise RuntimeError(str(result["error"])[:250])
                output = result.get("text")
                if not isinstance(output, str):
                    raise RuntimeError("Invalid CUDA transcription response")
                words = result.get("words") or []
                if not isinstance(words, list):
                    words = []
                words = [w for w in words[:240] if isinstance(w, dict)
                         and isinstance(w.get("text"), str)
                         and type(w.get("start")) in (float, int)
                         and type(w.get("end")) in (float, int)
                         and 0 <= w["start"] <= w["end"] <= 60]
                detected = result.get("language")
                return {"text":output[:3000],"words":words,
                        "language": detected if isinstance(detected,str) else language,
                        "language_probability": float(
                            result.get("language_probability",0.0) or 0.0),
                        "recognition_rejected":result.get("recognition_rejected")}
            except (OSError, ValueError, BrokenPipeError) as exc:
                self._stop()
                raise RuntimeError("CUDA worker unavailable: " + str(exc)[:180]) from exc


_worker = _PersistentCUDAWorker()
atexit.register(_worker.close)


def transcribe_cuda(pcm, language, model_path):
    return _worker.transcribe(pcm, language, model_path)


def transcribe_cuda_details(pcm, language, model_path, *,
                            music_mode=False, speech_priority=False,
                            timeout_s=90):
    """Return real word timestamps; dialogue focus is independent of singing."""
    return _worker.transcribe_details(
        pcm, language, model_path, music_mode=music_mode,
        speech_priority=speech_priority, timeout_s=timeout_s)


def _download(destination):
    from huggingface_hub import snapshot_download
    path = Path(destination).expanduser()
    worker = FasterWhisperCUDA(model_dir=path.parent.parent)
    if path != worker.model_dir:
        raise RuntimeError("Unexpected model download destination")
    worker._guard()
    path.mkdir(parents=True, exist_ok=True)
    (path / PARTIAL_MARKER).write_text(
        "Interrupted owner-approved model download may be resumed.\\n",
        encoding="utf-8")
    snapshot_download(repo_id=MODEL_ID, revision=REVISION,
                      allow_patterns=["model.bin", "config.json", "tokenizer.json",
                                      "preprocessor_config.json", "vocabulary.json"],
                      local_dir=str(path), max_workers=2)
    for name in ("model.bin", "config.json", "tokenizer.json"):
        if not (path / name).is_file():
            raise RuntimeError("Incomplete CUDA Whisper model: " + name)
    digest = hashlib.sha256()
    with (path / "model.bin").open("rb") as fp:
        for block in iter(lambda: fp.read(4 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != MODEL_SHA256:
        raise RuntimeError("Downloaded Whisper weights did not match pinned SHA-256")
    (path / MODEL_MARKER).write_text(
        "model=" + MODEL_ID + "\nrevision=" + REVISION +
        "\nsha256=" + MODEL_SHA256 + "\n", encoding="utf-8")
    (path / PARTIAL_MARKER).unlink(missing_ok=True)


def main():
    if sys.argv[1:] == ["--probe"]:
        import ctranslate2
        print(json.dumps({"devices": ctranslate2.get_cuda_device_count()}), flush=True)
        return 0
    if sys.argv[1:] == ["--selftest"]:
        # This option really constructs the locally verified model and runs
        # GPU decoder kernels on synthetic 16-kHz silence. It is deliberately
        # separate from the cheap, read-only CUDA visibility check.
        import numpy as np
        import ctranslate2
        from faster_whisper import WhisperModel
        owned = FasterWhisperCUDA()
        if not owned.installed() or ctranslate2.get_cuda_device_count() < 1:
            raise RuntimeError("Verified CUDA model or NVIDIA device missing")
        model = WhisperModel(str(owned.model_dir), device="cuda",
                             compute_type="float16", local_files_only=True)
        segments, _ = model.transcribe(np.zeros(16000,dtype=np.float32),
                                       language="en", task="transcribe",
                                       beam_size=1, vad_filter=False,
                                       max_new_tokens=8)
        list(segments)
        print(json.dumps({"model_loaded":True,"cuda_tested":True,
                          "device":"cuda","model":"large-v3-turbo"}), flush=True)
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "--download":
        _download(sys.argv[2])
        return 0
    if sys.argv[1:] != ["--serve"]:
        raise SystemExit("Usage: --probe | --selftest | --download PATH | --serve")
    import numpy as np
    from faster_whisper import WhisperModel
    from textcenter.compute import LANGUAGES as WHISPER_LANGUAGES
    model = None
    active_path = None
    for line in sys.stdin.buffer:
        try:
            if len(line) > 5_500_000:
                raise ValueError("CUDA audio message too large")
            request = json.loads(line)
            if request.get("language") not in WHISPER_LANGUAGES and request.get("language") != "auto":
                raise ValueError("Unsupported Whisper language")
            path = str(FasterWhisperCUDA().model_dir)
            if request.get("model") != path:
                raise ValueError("Unknown local CUDA model directory")
            pcm = base64.b64decode(request["audio"], validate=True)
            if not 0 < len(pcm) <= 4_000_000 or len(pcm) % 2:
                raise ValueError("Invalid PCM size")
            if active_path != path:
                model = WhisperModel(path, device="cuda",
                                     compute_type="float16", local_files_only=True)
                active_path = path
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
            samples = samples[:len(samples) // 2 * 2]
            waveform = (samples[0::2] + samples[1::2]) / 65536.0
            from tv_center.speech_focus import whisper_vad_settings
            dialogue_priority = (bool(request.get("speech_priority")) and
                                 not bool(request.get("music_mode")))
            vad = whisper_vad_settings(
                speech_priority=dialogue_priority,
                music_transcription=bool(request.get("music_mode")))
            segments, language_info = model.transcribe(
                waveform, language=(None if request["language"]=="auto" else
                                    request["language"]), task="transcribe",
                beam_size=3, **vad,
                condition_on_previous_text=False, word_timestamps=True,
                hallucination_silence_threshold=1.0)
            all_segments = list(segments)
            from tv_center.asr_quality import accepted_whisper_segments
            detected = getattr(language_info,"language",None)
            detected_probability = getattr(
                language_info,"language_probability",None)
            trusted_segments, rejection = accepted_whisper_segments(
                all_segments, source_language=request["language"],
                detected_probability=detected_probability,
                music_mode=bool(request.get("music_mode")),
                speech_priority=dialogue_priority)
            # Never translate hallucinated phrases or attach speaker labels
            # to empty/no-speech clips. Preserve the reason as diagnostics.
            text = " ".join(seg.text.strip() for seg in trusted_segments).strip()
            words = []
            for segment in trusted_segments:
                for word in segment.words or ():
                    token = word.word.strip()
                    if token and len(token) <= 100 and len(words) < 240:
                        words.append({
                            "text": token, "start":round(float(word.start),3),
                            "end":round(float(word.end),3)})
            detected = getattr(language_info,"language",None)
            output = {"text": text[:3000], "words": words,
                      "language":detected if isinstance(detected,str) else
                                 request["language"],
                      "language_probability":float(
                          getattr(language_info,"language_probability",0.0) or 0.0),
                      "recognition_rejected":rejection}
        except (ImportError, OSError, RuntimeError, ValueError, KeyError,
                TypeError) as exc:
            output = {"error": str(exc)[:300]}
        print(json.dumps(output, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
