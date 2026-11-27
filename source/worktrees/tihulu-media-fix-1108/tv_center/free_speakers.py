"""Token-free offline speaker diarization for voluntary live-caption use.

Resemblyzer 0.1.4 includes public pretrained voice-embedding weights in
its Python wheel (Apache-2.0). No Hugging Face account/token, external audio
API, RF access or NVIDIA CUDA compiler required. This is *approximate*
clustering, not a qualified forensic speaker-ID system. It does not infer
sex/age and should never be advertised as accurate per-word diarization.
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
import time

MARKER = ".tihulu-free-speaker-owned"
READY = ".tihulu-resemblyzer-selftested"
DEFAULT_ROOT = Path.home() / ".local/share/tihulu-tv-center/speaker-resemblyzer"
MAX_AUDIO_BYTES = 4_000_000


class FreeSpeakerMarket:
    def __init__(self, root=None):
        if root is None:
            from .ai_settings import AISettings
            custom = AISettings().values.get("model_dir", "")
            root = (Path(custom).expanduser() / "speaker-resemblyzer"
                    if custom else DEFAULT_ROOT)
        self.root = Path(root).expanduser()
        self.venv = self.root / "venv"
        self.python = self.venv / "bin/python3"

    def _guard(self):
        home = Path.home().resolve()
        root = self.root.resolve()
        if (self.root.is_symlink() or not root.is_relative_to(home)
                or root == home or root == Path("/")):
            raise RuntimeError("Speaker runtime must be in private user-owned storage")
        if (self.root.exists() and any(self.root.iterdir()) and
                not (self.root / MARKER).is_file()):
            raise RuntimeError("Refusing to modify unowned speaker files")

    def status(self):
        return {
            "installed":(self.root / MARKER).is_file() and
                        (self.root / READY).is_file() and self.python.is_file(),
            "model":"Resemblyzer VoiceEncoder (public pretrained embedding model)",
            "license":"Apache-2.0",
            "gated":False,"token_required":False,"path":str(self.root),
            "backend":"CPU (CUDA-free and independent from GPU Whisper)",
            "limitations":"Approximate voice similarity; very short/overlapping voices may be wrong",
        }

    def env(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = (str(Path(__file__).resolve().parent.parent) +
                             os.pathsep + env.get("PYTHONPATH",""))
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["OMP_NUM_THREADS"] = "2"
        env["OPENBLAS_NUM_THREADS"] = "2"
        return env

    def install(self):
        if os.geteuid() == 0:
            raise RuntimeError("Install optional voice model as desktop user")
        self._guard()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / MARKER).write_text(
            "TIHULU token-free Apache-2.0 speaker runtime\n", encoding="utf-8")
        (self.root / READY).unlink(missing_ok=True)

        def check(argv, timeout):
            result = subprocess.run(
                argv, env=self.env(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout, check=False)
            if result.returncode:
                raise RuntimeError(
                    "Token-free speaker installation failed: " +
                    result.stderr.decode("utf-8","replace")[-600:])
        if not self.python.is_file():
            check([sys.executable, "-m", "venv", str(self.venv)], 240)
        # Install CPU PyTorch *inside this dedicated venv* to avoid touching
        # the owner's RTX CUDA Faster-Whisper and NLLB/Argos environments.
        check([str(self.python),"-m","pip","install",
               "--disable-pip-version-check","torch>=2.7,<3",
               "--index-url","https://download.pytorch.org/whl/cpu"],2400)
        check([str(self.python),"-m","pip","install",
               "--disable-pip-version-check",
               "Resemblyzer==0.1.4","numpy>=1.24,<2",
               "librosa>=0.10.2,<0.11"],2400)
        test = subprocess.run(
            [str(self.python),"-m","tv_center.free_speakers","--selftest"],
            env=self.env(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180,
            check=False)
        if test.returncode:
            raise RuntimeError("Voice model installed but unable to load or run: " +
                test.stderr.decode("utf-8","replace")[-500:])
        (self.root / READY).write_text("Resemblyzer encoder inference passed\n")
        return ("Installed & verified token-free offline voice tracking. "
                "Enable it in Live Captions → Speaker separation. "
                "Speaker labels are estimates, not identities.")

    def remove(self):
        self._guard()
        if not (self.root / MARKER).is_file():
            return "No TIHULU-owned token-free voice model installed"
        shutil.rmtree(self.root)
        return "Token-free voice model removed; GPU Whisper and pyannote preserved"


class VoiceClusters:
    """Bounded, per-channel running speaker centroids for short TV clips.

    Cosine similarity threshold is conservative, but still empirical. Never
    create confident labels based on the mere number of voices requested.
    """
    def __init__(self, threshold=0.76, maximum=4):
        self.threshold = threshold
        self.maximum = maximum
        self.centroids = []
        self.counts = []
        self.channel = None

    def reset(self, channel=None):
        self.centroids.clear()
        self.counts.clear()
        self.channel = channel

    def assign(self, embedding, channel=None):
        from math import isfinite, sqrt
        if channel != self.channel:
            self.reset(channel)
        try:
            vec = tuple(float(value) for value in embedding)
        except (TypeError, ValueError):
            return None
        if len(vec) != 256 or not all(isfinite(v) for v in vec):
            return None
        magnitude = sqrt(sum(v*v for v in vec))
        if magnitude < 1e-6:
            return None
        vec = tuple(v/magnitude for v in vec)
        if not self.centroids:
            self.centroids.append(vec)
            self.counts.append(1)
            return 0
        similarities = [
            sum(v*u for v,u in zip(vec,center))
            for center in self.centroids]
        best = max(range(len(similarities)),key=lambda i:similarities[i])
        if similarities[best] < self.threshold:
            if len(self.centroids) >= self.maximum:
                return None   # unknown voice; never coerce into wrong identity
            self.centroids.append(vec)
            self.counts.append(1)
            return len(self.centroids)-1
        count = self.counts[best]
        averaged = [u*min(count,8)+v
                    for u,v in zip(self.centroids[best],vec)]
        length = sqrt(sum(v*v for v in averaged))
        self.centroids[best] = tuple(v/max(length,1e-9) for v in averaged)
        self.counts[best] = count + 1
        return best


def cluster_windows(windows, tracker, channel, max_seconds):
    """Convert (start,end,256D embedding) windows into non-overlap labels."""
    result = []
    for start,end,vector in windows[:18]:
        if (not isinstance(start,(int,float)) or
                not isinstance(end,(int,float)) or
                not 0 <= start < end <= max_seconds + .01):
            continue
        index = tracker.assign(vector,channel)
        if index is None:
            continue
        # Consecutive overlapping 1.6-s embeddings are read as 0.8-s
        # *estimated* windows. This is NOT a word-level speech boundary.
        middle = (start+end)/2
        first = max(0.0,middle-0.4)
        last = min(max_seconds,middle+0.4)
        if result and result[-1]["id"] == f"SPEAKER_{index:02d}" and (
                first-result[-1]["end"] <= 0.15):
            result[-1]["end"] = round(last,3)
        else:
            result.append({"start":round(first,3),"end":round(last,3),
                           "id":f"SPEAKER_{index:02d}"})
    return result[:30]


class _FreeWorker:
    def __init__(self):
        self.lock=threading.Lock()
        self.process=None

    def _close(self):
        process=self.process
        self.process=None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    def close(self):
        with self.lock:
            self._close()

    def diarize(self, pcm, channel=None):
        market=FreeSpeakerMarket()
        if not market.status()["installed"]:
            raise RuntimeError(
                "No token-free speaker model installed. Open Model Market → "
                "Speaker separation → Install public Resemblyzer.")
        if (not isinstance(pcm,bytes) or not 32000 <= len(pcm) <=
                MAX_AUDIO_BYTES or len(pcm) % 2):
            raise ValueError("Invalid mono PCM broadcast audio")
        payload=(json.dumps({"audio":base64.b64encode(pcm).decode("ascii"),
                             "channel":str(channel or "")[:80]},
                            separators=(",",":")).encode("ascii")+b"\n")
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._close()
                self.process=subprocess.Popen(
                    [str(market.python),"-u","-m",
                     "tv_center.free_speakers","--serve"],
                    env=market.env(),stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    close_fds=True,bufsize=0)
            try:
                self.process.stdin.write(payload)
                self.process.stdin.flush()
                ready,_,_=select.select([self.process.stdout],[],[],9)
                if not ready:
                    self._close()
                    raise TimeoutError(
                        "Token-free speaker processing exceeded live TV budget; "
                        "original transcript remains available")
                reply=self.process.stdout.readline(16000)
                if not reply.endswith(b"\n"):
                    self._close()
                    raise RuntimeError("No response from offline speaker model")
                parsed=json.loads(reply)
                if parsed.get("error"):
                    raise RuntimeError(str(parsed["error"])[:180])
                turns=parsed.get("turns")
                if not isinstance(turns,list):
                    raise RuntimeError("Invalid speaker turns response")
                return turns[:30]
            except (BrokenPipeError,OSError,ValueError) as exc:
                self._close()
                raise RuntimeError("Offline speaker worker failed: "+str(exc)[:180]) from exc


_worker=_FreeWorker()
atexit.register(_worker.close)


def diarize_pcm(pcm, channel=None):
    return _worker.diarize(pcm,channel)


def _serve():
    import numpy as np
    from resemblyzer import VoiceEncoder
    from resemblyzer.hparams import sampling_rate
    # Package-bundled public weights, no network or access token, CPU avoids
    # competing for RTX memory with the main low-latency Whisper CUDA worker.
    encoder=VoiceEncoder("cpu",verbose=False)
    tracker=VoiceClusters()
    window_seconds=1.6
    step_seconds=0.8
    sample_rate=32000  # signed mono 16-bit PCM emitted by ffmpeg tap
    for line in sys.stdin.buffer:
        try:
            if len(line)>5_500_000:
                raise ValueError("Oversized audio request")
            item=json.loads(line)
            pcm=base64.b64decode(item["audio"],validate=True)
            if not 32000 <= len(pcm) <= MAX_AUDIO_BYTES or len(pcm)%2:
                raise ValueError("Invalid PCM audio")
            channel=str(item.get("channel") or "")[:80]
            data=np.frombuffer(pcm,dtype="<i2").astype(np.float32)/32768.
            wave=((data[0::2]+data[1::2])*0.5).astype(np.float32)
            seconds=len(wave)/sampling_rate
            win=int(window_seconds*sampling_rate)
            step=int(step_seconds*sampling_rate)
            windows=[]
            # Avoid labeling music/silence with fake speaker IDs.
            for start in range(0,max(1,len(wave)-win+1),step):
                segment=wave[start:start+win]
                if len(segment)<int(.8*sampling_rate):
                    continue
                if float(np.sqrt(np.mean(segment**2))) < .016:
                    continue
                embedding=encoder.embed_utterance(segment)
                windows.append((start/sampling_rate,
                                min(seconds,(start+len(segment))/sampling_rate),
                                embedding))
                if len(windows)>=18:
                    break
            answer={"turns":cluster_windows(
                windows,tracker,channel,seconds),"engine":"resemblyzer",
                "note":"Approximate unsupervised labels; no demographic inference"}
        except Exception as exc:
            answer={"error":str(exc)[:180]}
        print(json.dumps(answer),flush=True)


def _selftest():
    import numpy as np
    from resemblyzer import VoiceEncoder
    model=VoiceEncoder("cpu",verbose=False)
    # Synthetic signal tests model weights without downloading audio or
    # transmitting real microphone/broadcast audio.
    signal=(.03*np.sin(2*np.pi*180*np.arange(32000)/16000)).astype(np.float32)
    vector=model.embed_utterance(signal)
    if len(vector)!=256 or not np.all(np.isfinite(vector)):
        raise RuntimeError("Public Resemblyzer weights did not produce valid embeddings")
    print(json.dumps({"ready":True,"model":"Resemblyzer 0.1.4",
                      "device":"cpu","token_required":False}),flush=True)


def main():
    if sys.argv[1:] == ["--serve"]:
        _serve()
        return 0
    if sys.argv[1:] == ["--selftest"]:
        _selftest()
        return 0
    raise SystemExit("Usage: python -m tv_center.free_speakers --serve|--selftest")


if __name__ == "__main__":
    raise SystemExit(main())
