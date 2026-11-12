"""Owner-managed local Qwen3 Forced Aligner (Apache-2.0).

Never downloads during radio playback, startup or model inventory. CPU and
NVIDIA contexts remain independent of the existing Faster-Whisper worker.
Qwen's speech aligner is not assumed reliable for singing or background music;
Whisper remains the always-available fallback.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import atexit

from .radio_karaoke_router import QWEN_ALIGN_LANGUAGES, LANGUAGE_NAMES

MODEL_ID="Qwen/Qwen3-ForcedAligner-0.6B"
ROOT=Path.home()/".local/share/tihulu-tv-center/qwen-aligner"
MARKER=".tihulu-owned-qwen-aligner"
READY=".tihulu-qwen-weights-ready"


class QwenForcedAlignerMarket:
    def __init__(self,root=None):
        self.root=Path(root or ROOT).expanduser()
        self.python=self.root/"venv/bin/python3"
        self.weights=self.root/"weights"

    def installed(self):
        return (not self.root.is_symlink() and
            self.python.is_file() and (self.root/MARKER).is_file() and
            (self.root/READY).is_file() and
            (self.weights/"config.json").is_file() and
            any(self.weights.glob("*.safetensors")))

    def status(self):
        return {"model":MODEL_ID,"installed":self.installed(),
                "languages":sorted(QWEN_ALIGN_LANGUAGES),
                "license":"Apache-2.0","speech_trained":True,
                "singing_benchmarked":False,
                "fallback":"Whisper multilingual word matching"}

    def _guard(self):
        home=Path.home().resolve()
        folder=self.root.resolve()
        if self.root.is_symlink() or not folder.is_relative_to(home) or folder==home:
            raise RuntimeError("Qwen weights require private owner-owned storage")
        if self.root.is_dir() and any(self.root.iterdir()) and not (
                self.root/MARKER).is_file():
            raise RuntimeError("Refusing to modify unowned Qwen directory")

    def env(self,online=False):
        env=os.environ.copy()
        env["PYTHONPATH"]=(str(Path(__file__).resolve().parent.parent)+
                           os.pathsep+env.get("PYTHONPATH",""))
        env["HF_HUB_DISABLE_TELEMETRY"]="1"
        if online:
            env.pop("HF_HUB_OFFLINE",None)
            env.pop("TRANSFORMERS_OFFLINE",None)
        else:
            env["HF_HUB_OFFLINE"]="1"
            env["TRANSFORMERS_OFFLINE"]="1"
        env["OMP_NUM_THREADS"]="2"
        return env

    def install(self):
        if os.geteuid()==0:
            raise RuntimeError("Run Qwen installer as normal user")
        self._guard()
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/MARKER).write_text("TIHULU Qwen model, Apache-2.0\n")
        (self.root/READY).unlink(missing_ok=True)
        def run(argv,timeout,env=None):
            p=subprocess.run(argv,env=env,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                timeout=timeout,check=False)
            if p.returncode:
                raise RuntimeError("Qwen model installation failed: "+
                   p.stderr.decode("utf-8","replace")[-600:])
        if not self.python.is_file():
            run([sys.executable,"-m","venv",str(self.root/"venv")],180)
        run([str(self.python),"-m","pip","install",
             "--disable-pip-version-check","qwen-asr"],2400,
             self.env(online=True))
        self.weights.mkdir(parents=True,exist_ok=True)
        # No remote model-provided source code or executable files downloaded.
        script=("from huggingface_hub import snapshot_download;"
                "snapshot_download(repo_id="+repr(MODEL_ID)+
                ",local_dir="+repr(str(self.weights))+
                ",allow_patterns=['*.json','*.safetensors','*.model',"
                "'*.txt','*.tiktoken'])")
        run([str(self.python),"-c",script],2400,self.env(online=True))
        if not (self.weights/"config.json").is_file() or not any(
                self.weights.glob("*.safetensors")):
            raise RuntimeError("Incomplete Qwen weights; no ready marker written")
        (self.root/READY).write_text(
            "Weights downloaded; singing/latency validation pending\n")
        return self.status()


class _Worker:
    """Timeout-bounded pipe to an isolated CUDA/CPU aligner process."""
    def __init__(self):
        self.lock=threading.Lock()
        self.proc=None

    def close(self):
        with self.lock:
            self._stop()

    def _stop(self):
        p=self.proc
        self.proc=None
        if p is not None and p.poll() is None:
            p.terminate()
            try:p.wait(timeout=2)
            except subprocess.TimeoutExpired:p.kill()

    def align(self,pcm:bytes,text:str,language:str,timeout=3):
        market=QwenForcedAlignerMarket()
        if not market.installed() or language not in QWEN_ALIGN_LANGUAGES:
            return None
        if (not isinstance(pcm,bytes) or len(pcm)<32000 or len(pcm)>640000
                or len(pcm)%2 or not isinstance(text,str) or not text.strip()
                or len(text)>800):
            return None
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self._stop()
                self.proc=subprocess.Popen(
                    [str(market.python),"-u","-m",
                     "tv_center.qwen_forced_aligner","--serve"],
                    env=market.env(),stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    bufsize=0,close_fds=True)
            try:
                self.proc.stdin.write(json.dumps({
                    "pcm":base64.b64encode(pcm).decode("ascii"),
                    "text":text,"language":language},separators=(",",":")
                ).encode("ascii")+b"\n")
                self.proc.stdin.flush()
                ready,_,_=select.select([self.proc.stdout],[],[],timeout)
                if not ready:
                    self._stop()
                    return None
                raw=self.proc.stdout.readline(80_000)
                result=json.loads(raw)
                return result.get("words") if isinstance(result.get("words"),list) else None
            except (OSError,ValueError,EOFError,BrokenPipeError):
                self._stop()
                return None


_WORKER=_Worker()
atexit.register(_WORKER.close)

def align_observed_phrase(pcm,text,language,timeout=3):
    """Optional aligner never claims a match by itself; first verify ASR text."""
    return _WORKER.align(pcm,text,language,timeout)


def stop_alignment():
    """Release the separate acoustic worker without blocking SDR shutdown.

    Intentional non-blocking termination: a still-loading Qwen model must not
    prevent the user from closing/stopping DAB or ordinary Whisper captions.
    """
    proc=_WORKER.proc
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except (OSError,ProcessLookupError):
            pass


def _serve():
    # Import heavy packages only in the isolated, explicitly requested worker.
    import numpy as np
    import torch
    from qwen_asr import Qwen3ForcedAligner
    owner=QwenForcedAlignerMarket()
    if not owner.installed():
        raise RuntimeError("Qwen weights were not installed by the owner")
    model=Qwen3ForcedAligner.from_pretrained(
        str(owner.weights),dtype=torch.bfloat16 if torch.cuda.is_available()
        else torch.float32,
        device_map="cuda:0" if torch.cuda.is_available() else "cpu")
    for line in sys.stdin:
        try:
            request=json.loads(line)
            language=request.get("language")
            if language not in QWEN_ALIGN_LANGUAGES:
                raise ValueError("Unsupported language")
            pcm=base64.b64decode(request["pcm"],validate=True)
            if not 32000<=len(pcm)<=640000 or len(pcm)%2:
                raise ValueError("Invalid radio audio")
            samples=np.frombuffer(pcm,dtype="<i2").astype("float32")/32768
            # welle/FFmpeg is captured at 32 kHz; Qwen will resample.
            # Never claim 16 kHz for 32 kHz bytes (would double time).
            result=model.align(audio=(samples,32000),text=request["text"],
                               language=LANGUAGE_NAMES[language])
            words=[{"text":str(w.text),"start":float(w.start_time),
                    "end":float(w.end_time)} for w in result[0]][:150]
            answer={"words":words}
        except Exception as exc:
            answer={"error":str(exc)[:160]}
        sys.stdout.write(json.dumps(answer,ensure_ascii=False)+"\n")
        sys.stdout.flush()


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    market=QwenForcedAlignerMarket()
    if args==["--status"]:
        print(json.dumps(market.status()))
        return 0
    if args==["--install"]:
        print(json.dumps(market.install()))
        return 0
    if args==["--serve"]:
        _serve()
        return 0
    return 2

if __name__=="__main__":
    raise SystemExit(main())
