"""Experimental two-speaker *source separation*, not speaker diarization.

SpeechBrain SepFormer-wsj02mix (Apache-2.0) transforms ONE mono 32kHz
audio clip into TWO candidate mono 32kHz clips. Whisper must recognize
the candidates independently; no second transcript is constructed from
speaker clusters or duplicated words. Models and Python dependencies
are installed ONLY by an explicit owner action.

WSJ0-2Mix is mostly English clean mixtures, so performance on Turkish,
French, TV music/dubbing, three voices, and low-quality DVB is UNVERIFIED.
"""
from __future__ import annotations

import atexit
import base64
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import threading

ROOT = Path.home()/".local/share/tihulu-tv-center/overlap-separation"
MODEL_ID = "speechbrain/sepformer-wsj02mix"
MODEL_REVISION = "3a28263"  # explicit vendor revision; never main at runtime
MARKER = ".tihulu-owned-overlap-separation"
READY = ".tihulu-sepformer-wsj02mix-ready"
MODEL_FILES = ("hyperparams.yaml", "masknet.ckpt", "encoder.ckpt", "decoder.ckpt")
MAX_PCM = 4_000_000
MAX_LINE = 12_000_000


class OverlapSeparation:
    def __init__(self, root=None):
        self.root = Path(root or ROOT).expanduser()
        self.python = self.root/"venv/bin/python3"
        self.weights = self.root/"sepformer-wsj02mix"

    def installed(self):
        try:
            return (self.python.is_file() and
                    (self.root/MARKER).is_file() and
                    (self.root/READY).is_file() and
                    not self.weights.is_symlink() and
                    all((self.weights/name).is_file()
                        for name in MODEL_FILES) and
                    (self.weights/"masknet.ckpt").stat().st_size>10_000_000)
        except OSError:
            return False

    def env(self):
        env=os.environ.copy()
        env["PYTHONPATH"]=str(Path(__file__).resolve().parent.parent)+(
            os.pathsep+env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["HF_HUB_OFFLINE"]="1"
        env["TRANSFORMERS_OFFLINE"]="1"
        env["HF_DATASETS_OFFLINE"]="1"
        env["TOKENIZERS_PARALLELISM"]="false"
        return env

    def install(self):
        """EXPLICIT opt-in only. Does not run during TV or Market startup."""
        if os.geteuid()==0:
            raise RuntimeError("Install optional speech models as desktop user")
        home=Path.home().resolve()
        root=self.root.resolve()
        if (self.root.is_symlink() or root==home or root==Path("/")
                or not root.is_relative_to(home)):
            raise RuntimeError("Model location must be private user storage")
        if (self.root.exists() and any(self.root.iterdir())
                and not (self.root/MARKER).is_file()):
            raise RuntimeError("Refusing to modify a non-TIHULU directory")
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/MARKER).write_text("Owner-requested SepFormer model\n")
        def run(argv, timeout):
            proc=subprocess.run(argv,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                timeout=timeout,check=False)
            if proc.returncode:
                raise RuntimeError("SepFormer setup failed: "+
                    proc.stderr.decode("utf-8","replace")[-700:])
        if not self.python.is_file():
            run([sys.executable,"-m","venv",str(self.root/"venv")],240)
        run([str(self.python),"-m","pip","install",
             "--disable-pip-version-check","torch>=2.7,<3",
             "torchaudio>=2.7,<3","speechbrain==1.0.3",
             "scipy>=1.11,<2","numpy>=1.24,<3",
             "huggingface_hub>=0.26,<1.0"],3000)
        env=self.env().copy()
        env.pop("HF_HUB_OFFLINE",None)  # owner specifically requested download
        env.pop("TRANSFORMERS_OFFLINE",None)
        # SpeechBrain 1.0.3 uses Hub 0.x APIs. HTTP downloads avoid
        # optional Xet token/transport failures on desktop installations.
        env["HF_HUB_DISABLE_XET"]="1"
        env["HF_HUB_ETAG_TIMEOUT"]="30"
        code=("from huggingface_hub import snapshot_download;"
              "snapshot_download(repo_id="+repr(MODEL_ID)+
              ",revision="+repr(MODEL_REVISION)+
              ",local_dir="+repr(str(self.weights))+
              ",allow_patterns=['hyperparams.yaml','masknet.ckpt',"
              "'encoder.ckpt','decoder.ckpt','brain.ckpt','config.json'])")
        proc=subprocess.run([str(self.python),"-c",code],
            env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,timeout=1500,check=False)
        if proc.returncode:
            diagnostic=proc.stderr.decode("utf-8","replace").strip()
            # Last traceback lines alone often omit the HTTP status and
            # actual Hugging Face failure from the earlier exception.
            lines=diagnostic.splitlines()
            important=[line.strip() for line in lines if
                any(term in line for term in (
                    "HTTPError:","HfHubHTTPError:","OfflineModeIsEnabled:",
                    "RepositoryNotFoundError:","RevisionNotFoundError:",
                    "403 Client Error","401 Client Error","SSLError:",
                    "ConnectError:","ReadTimeout:","RuntimeError:"))]
            detail=" | ".join(important[-3:]) or "\n".join(lines[-5:])
            raise RuntimeError(
                "SepFormer model download failed at "+
                MODEL_ID+"@"+MODEL_REVISION+": "+detail[-1100:]+
                ". Check Hugging Face HTTPS access and retry; previously "
                "downloaded model files remain available.")
        if not all((self.weights/file).is_file() for file in MODEL_FILES):
            raise RuntimeError("Incomplete SepFormer weights; retry install")
        (self.root/READY).write_text(
            "SpeechBrain SepFormer weights present; REAL inference unverified\n")
        return ("SepFormer model files installed. Enable experimental "
                "overlap separation in Live Captions and test actual audio. "
                "CUDA/TV latency still needs verification.")


class _Worker:
    def __init__(self):
        self.lock=threading.Lock()
        self.proc=None

    def _stop(self):
        p=self.proc
        self.proc=None
        if p is not None and p.poll() is None:
            p.terminate()
            try: p.wait(timeout=2)
            except subprocess.TimeoutExpired: p.kill()

    def close(self):
        with self.lock:
            self._stop()

    def separate(self,pcm):
        if not isinstance(pcm,bytes) or not 32000<=len(pcm)<=MAX_PCM or len(pcm)%2:
            raise ValueError("Expected bounded s16le mono 32-kHz PCM")
        manager=OverlapSeparation()
        if not manager.installed():
            raise RuntimeError("SepFormer model absent: install it explicitly")
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                self._stop()
                self.proc=subprocess.Popen([
                    str(manager.python),"-u","-m",
                    "tv_center.overlap_separation","--serve"],
                    env=manager.env(),stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    bufsize=0,close_fds=True)
            try:
                request=json.dumps({"pcm":base64.b64encode(pcm).decode("ascii")},
                                   separators=(",",":")).encode("ascii")+b"\n"
                self.proc.stdin.write(request)
                self.proc.stdin.flush()
                ready,_,_=select.select([self.proc.stdout],[],[],6)
                if not ready:
                    self._stop()
                    raise TimeoutError("Two-speaker separation exceeded 6s live budget; "
                                       "normal Whisper must be used instead")
                answer=self.proc.stdout.readline(MAX_LINE)
                if not answer.endswith(b"\n"):
                    self._stop()
                    raise RuntimeError("Separator exited or response was incomplete")
                response=json.loads(answer)
                if response.get("error"):
                    raise RuntimeError(str(response["error"])[:180])
                streams=response.get("streams",[])
                if not isinstance(streams,list) or len(streams)!=2:
                    raise RuntimeError("Separator did not return two streams")
                decoded=[base64.b64decode(x,validate=True) for x in streams]
                if any(len(x)!=len(pcm) for x in decoded):
                    raise RuntimeError("Separator returned wrong audio length")
                return decoded
            except (BrokenPipeError,OSError,ValueError) as exc:
                self._stop()
                raise RuntimeError("SepFormer worker failed: "+str(exc)[:180]) from exc


_worker=_Worker()
atexit.register(_worker.close)


def separate_pcm(pcm):
    return _worker.separate(pcm)


def accept_two_transcripts(results):
    """Require ACTUALLY distinct, source-timed ASR outputs before 2-line UI.

    The separator emits two tracks even on a *single* voice; leakage and
    ASR hallucinations must not become a fabricated second speaker.
    """
    if not isinstance(results,(tuple,list)) or len(results)!=2:
        return None
    cleaned=[]
    for i,item in enumerate(results):
        if not isinstance(item,dict):
            return None
        text=item.get("text")
        words=item.get("words")
        if (not isinstance(text,str) or not text.strip() or
                not isinstance(words,list)):
            return None
        valid=[w for w in words if isinstance(w,dict)
               and isinstance(w.get("text"),str)
               and isinstance(w.get("start"),(int,float))
               and isinstance(w.get("end"),(int,float))
               and 0<=w["start"]<=w["end"]<=60]
        # One-word interruptions such as "Merhaba!" can be genuine when
        # the OTHER channel has a longer independent phrase. Require real
        # word timing, sufficient duration and distinct transcripts below.
        if (not valid or
                (len(valid)==1 and len(valid[0]["text"].strip())<3) or
                float(valid[-1]["end"])-float(valid[0]["start"])<0.18 or
                not isinstance(item.get("language"),str)):
            return None
        cleaned.append({"speaker_index":i+1,
                        "speaker_label":f"[Voice {i+1} · provisional]",
                        "original":text[:900].strip(),
                        "source_language":item["language"],
                        "words":valid[:180],
                        "translations":{},
                        "first_word_s":float(valid[0]["start"])})
    norm=lambda t:" ".join(t.casefold().split())
    if SequenceMatcher(None,norm(cleaned[0]["original"]),
                       norm(cleaned[1]["original"])).ratio()>0.68:
        return None
    if all(len(part["words"])==1 for part in cleaned):
        return None  # too little evidence: two standalone ASR tokens
    a_start,a_end=(cleaned[0]["words"][0]["start"],
                   cleaned[0]["words"][-1]["end"])
    b_start,b_end=(cleaned[1]["words"][0]["start"],
                   cleaned[1]["words"][-1]["end"])
    if min(a_end,b_end)-max(a_start,b_start)<0.2:
        # Sources do not actually overlap in time. Ordinary speaker
        # diarization, NOT two-source simultaneous captions, handles them.
        return None
    cleaned.sort(key=lambda item:(item["first_word_s"],item["speaker_index"]))
    return cleaned


def _serve():
    # Subprocess owns CUDA/PyTorch memory. No model imports at application
    # startup. Local-only and offline after explicit installer approval.
    import numpy as np
    from scipy.signal import resample_poly
    import torch
    from speechbrain.inference.separation import SepformerSeparation
    manager=OverlapSeparation()
    if not manager.installed():
        raise RuntimeError("No verified local SepFormer installation")
    torch.set_num_threads(2)
    device="cuda" if torch.cuda.is_available() else "cpu"
    separator=SepformerSeparation.from_hparams(
        source=str(manager.weights),savedir=str(manager.weights),
        run_opts={"device":device})
    for raw in sys.stdin.buffer:
        try:
            request=json.loads(raw)
            pcm=base64.b64decode(request["pcm"],validate=True)
            if not 32000<=len(pcm)<=MAX_PCM or len(pcm)%2:
                raise ValueError("Invalid source PCM")
            original=np.frombuffer(pcm,dtype="<i2").astype("float32")/32768.0
            at_8k=resample_poly(original,1,4).astype("float32")
            with torch.inference_mode():
                input_tensor=torch.from_numpy(at_8k).unsqueeze(0).to(device)
                candidates=separator.separate_batch(input_tensor)[0]
            if candidates.ndim!=2 or candidates.shape[1]!=2:
                raise ValueError("Model output is not two audio sources")
            tracks=[]
            for index in range(2):
                recovered=resample_poly(
                    candidates[:,index].detach().cpu().float().numpy(),4,1)
                recovered=np.clip(recovered[:len(original)],-0.98,0.98)
                if len(recovered)!=len(original):
                    raise ValueError("Separated stream length mismatch")
                tracks.append(base64.b64encode(
                    (recovered*32767).astype("<i2").tobytes()).decode("ascii"))
            response={"streams":tracks,"device":device}
        except Exception as exc:
            response={"error":str(exc)[:180]}
        sys.stdout.write(json.dumps(response,separators=(",",":"))+"\n")
        sys.stdout.flush()


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if args==["--install"]:
        print(OverlapSeparation().install())
        return 0
    if args==["--status"]:
        print(json.dumps({"installed":OverlapSeparation().installed(),
                          "model":MODEL_ID, "license":"Apache-2.0",
                          "trained_on":"English WSJ0-2Mix",
                          "caution":"Unverified on multilingual TV"}))
        return 0
    if args==["--serve"]:
        _serve()
        return 0
    raise SystemExit("Usage: python -m tv_center.overlap_separation "
                     "[--status|--install|--serve]")


if __name__=="__main__":
    raise SystemExit(main())
