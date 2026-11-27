"""Opt-in offline speaker *diarization*, separate from speaker demographics.

Community-1 is a gated model, so the owner accepts its Hugging Face terms and
supplies a short-lived access token explicitly. Inference is offline, bounded,
and disabled unless selected; diarization IDs are local to each TV clip, not
persistent identities or automatic age/gender determinations.
"""
from __future__ import annotations
import atexit
import base64
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import threading

MODEL_ID = "pyannote/speaker-diarization-community-1"
ROOT = Path.home()/".local/share/tihulu-tv-center/speaker-diarization"
MARKER = ".tihulu-owned-speaker-runtime"
READY = ".tihulu-speaker-model-downloaded"


class SpeakerMarket:
    def __init__(self, root=None):
        if root is None:
            from .ai_settings import AISettings
            selected = AISettings().values.get("model_dir", "")
            root = (Path(selected).expanduser()/"speaker-diarization"
                    if selected else ROOT)
        self.root = Path(root).expanduser()
        self.venv = self.root/"venv"
        self.cache = self.root/"hf-cache"

    @property
    def python(self):
        return self.venv/"bin/python3"

    def status(self):
        return {"installed": (self.root/MARKER).is_file() and
                (self.root/READY).is_file() and self.python.is_file(),
                "model":MODEL_ID, "license":"CC-BY-4.0",
                "gated":True,"path":str(self.root),
                "voice_ids":"per 6-second clip; not persistent identities",
                "hardware":"CPU fallback; CUDA only if compatible PyTorch wheel is usable"}

    def _guard(self):
        home = Path.home().resolve()
        if (self.root.is_symlink() or not self.root.resolve().is_relative_to(home)
                or self.root.resolve() == home):
            raise RuntimeError("Speaker models must use non-symlinked user storage")
        if self.root.exists() and any(self.root.iterdir()) and not (
                self.root/MARKER).is_file():
            raise RuntimeError("Refusing to modify an unowned model directory")

    def env(self, *, offline=True):
        env = os.environ.copy()
        env["HF_HOME"] = str(self.cache)
        env["HF_HUB_DISABLE_TELEMETRY"] = "1"
        if offline:
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
        else:
            env.pop("HF_HUB_OFFLINE",None)
            env.pop("TRANSFORMERS_OFFLINE",None)
        env["PYTHONPATH"] = (str(Path(__file__).resolve().parent.parent) +
                             os.pathsep+env.get("PYTHONPATH",""))
        return env

    def install(self, token):
        if os.geteuid() == 0:
            raise RuntimeError("Speaker model installation must not run as root")
        if not isinstance(token,str) or not 15 <= len(token.strip()) <= 256:
            raise ValueError("Enter a Hugging Face access token after accepting model terms")
        self._guard()
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/MARKER).write_text("TIHULU gated offline speaker runtime\n")
        def check(argv, timeout=3000, input_data=None):
            response = subprocess.run(argv, env=self.env(offline=False),
                input=input_data, stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                timeout=timeout,check=False)
            if response.returncode:
                # Never show stderr containing a user's sensitive HF token.
                raise RuntimeError("Offline diarization dependency/model install "
                                   "failed; check internet, model access permissions, "
                                   "disk space and PyTorch CUDA compatibility")
        check([sys.executable,"-m","venv",str(self.venv)],timeout=240)
        # Separate runtime: avoid disturbing NVIDIA driver, working
        # Faster-Whisper / Argos models or Kaffeine system Qt.
        check([str(self.python),"-m","pip","install","--disable-pip-version-check",
               "torch>=2.7","torchaudio>=2.7","--index-url",
               "https://download.pytorch.org/whl/cu128"],timeout=3600)
        check([str(self.python),"-m","pip","install","--disable-pip-version-check",
               "pyannote.audio>=4,<5","huggingface_hub>=0.28,<2"],timeout=3600)
        check([str(self.python),"-m","tv_center.speaker_market","--prepare"],
              timeout=1800,input_data=token.strip().encode("utf-8")+b"\n")
        (self.root/READY).write_text("Community-1 loaded with owner permission\n")
        return "Speaker diarization model prepared offline; enable in Caption Settings"

    def remove(self):
        self._guard()
        if not (self.root/MARKER).is_file():
            return "No TIHULU-owned diarization model"
        shutil.rmtree(self.root)
        return "Optional speaker model and its cache removed"


class _SpeakerWorker:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None

    def close_locked(self):
        p = self.process
        self.process = None
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()

    def close(self):
        with self.lock:
            self.close_locked()

    def diarize(self, pcm):
        runtime=SpeakerMarket()
        if not runtime.status()["installed"]:
            raise RuntimeError("Opt-in pyannote Community-1 not installed in Model Market")
        if not isinstance(pcm,bytes) or not 0 < len(pcm) <= 4_000_000:
            raise ValueError("Invalid live PCM audio")
        message = json.dumps({"audio":base64.b64encode(pcm).decode("ascii")},
                             separators=(",",":")).encode("utf-8")+b"\n"
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.close_locked()
                self.process = subprocess.Popen(
                    [str(runtime.python),"-u","-m",
                     "tv_center.speaker_market","--serve"],
                    env=runtime.env(),stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    close_fds=True,bufsize=0)
            try:
                self.process.stdin.write(message)
                self.process.stdin.flush()
                ready,_,_=select.select([self.process.stdout],[],[],90)
                if not ready:
                    self.close_locked()
                    raise TimeoutError("Speaker diarization exceeded 90 s; disable for live TV")
                raw = self.process.stdout.readline(100000)
                if not raw.endswith(b"\n"):
                    self.close_locked()
                    raise RuntimeError("Speaker worker returned no response")
                answer=json.loads(raw)
                if "error" in answer:
                    raise RuntimeError(answer["error"][:250])
                return answer.get("turns",[])[:80]
            except (OSError, ValueError, BrokenPipeError) as exc:
                self.close_locked()
                raise RuntimeError("Speaker worker failed: "+str(exc)[:180]) from exc


_worker = _SpeakerWorker()
atexit.register(_worker.close)


def diarize_pcm(pcm):
    return _worker.diarize(pcm)


def _prepare():
    from pyannote.audio import Pipeline
    token=sys.stdin.readline(300).strip()
    if not token:
        raise RuntimeError("Hugging Face token required for gated model")
    pipe=Pipeline.from_pretrained(MODEL_ID, token=token)
    if pipe is None:
        raise RuntimeError("Model access declined or model could not be loaded")
    # All required model objects are fetched into private HF_HOME now.
    print(json.dumps({"ready":True}),flush=True)


def _serve():
    import numpy as np
    import torch
    from pyannote.audio import Pipeline
    runtime=SpeakerMarket()
    if not runtime.status()["installed"]:
        raise RuntimeError("Speaker model not installed")
    pipe=Pipeline.from_pretrained(MODEL_ID)
    if pipe is None:
        raise RuntimeError("Cached offline speaker model missing")
    # CPU is a reliable fallback if the separate cu128 runtime cannot
    # initialize kernels; do not conflate GPU with dedicated NPU.
    try:
        if torch.cuda.is_available():
            pipe.to(torch.device("cuda"))
    except (RuntimeError,OSError):
        pipe.to(torch.device("cpu"))
    for line in sys.stdin.buffer:
        try:
            if len(line)>5_500_000:
                raise ValueError("Oversized speaker clip")
            req=json.loads(line)
            pcm=base64.b64decode(req["audio"],validate=True)
            if not 0<len(pcm)<=4_000_000 or len(pcm)%2:
                raise ValueError("Invalid signed 16-bit audio")
            samples=np.frombuffer(pcm,dtype="<i2").astype(np.float32)
            samples=samples[:len(samples)//2*2]
            wave=((samples[0::2]+samples[1::2])/65536).astype(np.float32)
            result=pipe({"waveform":torch.from_numpy(wave).unsqueeze(0),
                         "sample_rate":16000})
            diarization=(getattr(result,"exclusive_speaker_diarization",None)
                        or result.speaker_diarization)
            turns=[]
            for turn,speaker in diarization:
                if len(turns)>=80:
                    break
                turns.append({"start":round(float(turn.start),3),
                              "end":round(float(turn.end),3),
                              "id":str(speaker)[:40]})
            answer={"turns":turns}
        except Exception as exc:
            answer={"error":str(exc)[:200]}
        print(json.dumps(answer),flush=True)


def main():
    if sys.argv[1:] == ["--prepare"]:
        _prepare()
        return 0
    if sys.argv[1:] == ["--serve"]:
        _serve()
        return 0
    raise SystemExit("Only --prepare or --serve accepted")

if __name__ == "__main__":
    raise SystemExit(main())
