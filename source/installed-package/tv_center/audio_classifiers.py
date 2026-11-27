"""Opt-in, offline acoustic sound-event and voice-type classifiers.

Resemblyzer does NOT predict age or gender. A separate audEERING model
(CC BY-NC-SA 4.0, non-commercial use ONLY) emits probabilistic perceived
child/female/male acoustic labels; these are NOT demographic facts.
MIT AST AudioSet sound tags are BSD-3-Clause, also separate from ASR.
Nothing here downloads, runs torch or accesses RF on normal application start.
"""
from __future__ import annotations

import atexit
import base64
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import threading

ROOT=Path.home()/".local/share/tihulu-tv-center/audio-label-classifiers"
MARKER=".tihulu-owned-audio-labels"
WEIGHTS={
    "sound":("MIT/ast-finetuned-audioset-10-10-0.4593","f826b80"),
    "voice":("audeering/wav2vec2-large-robust-6-ft-age-gender","a681b72"),
}
MAX_AUDIO=4_000_000
EVENT_LABELS={
    "music":"music",
    "musical instrument":"music",
    "humming":"hum",
    "hum":"hum",
    "applause":"applause",
    "clapping":"applause",
    "laughter":"laughter",
    "laughing":"laughter",
    "white noise":"noise",
    "noise":"noise",
}
EVENT_NAMES=("music","hum","applause","laughter","noise")


class AudioLabels:
    def __init__(self,root=None):
        self.root=Path(root or ROOT).expanduser()
        self.python=self.root/"venv/bin/python3"

    def model_dir(self,kind):
        if kind not in WEIGHTS:
            raise ValueError("Unknown acoustic model")
        return self.root/("sound-events" if kind=="sound" else "voice-types")

    def installed(self,kind):
        folder=self.model_dir(kind)
        return (self.python.is_file() and (self.root/MARKER).is_file()
                and not folder.is_symlink()
                and (folder/"config.json").is_file()
                and (folder/"model.safetensors").is_file()
                and (folder/"preprocessor_config.json").is_file()
                and (folder/".tihulu-downloaded").is_file())

    def env(self):
        env=os.environ.copy()
        env["PYTHONPATH"]=str(Path(__file__).resolve().parent.parent)+(
            os.pathsep+env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["HF_HUB_OFFLINE"]="1"
        env["TRANSFORMERS_OFFLINE"]="1"
        env["HF_DATASETS_OFFLINE"]="1"
        env["HF_HUB_DISABLE_TELEMETRY"]="1"
        env["OMP_NUM_THREADS"]="2"
        return env

    def install(self,kind,*,noncommercial_acknowledged=False):
        """Owner approves each download. No managed TV or Pi model changes."""
        folder=self.model_dir(kind)
        if kind=="voice" and not noncommercial_acknowledged:
            raise ValueError("Accept CC-BY-NC-SA 4.0 noncommercial terms first")
        if os.geteuid()==0:
            raise RuntimeError("Install as current desktop user, not root")
        home=Path.home().resolve()
        root=self.root.resolve()
        if (self.root.is_symlink() or root==home or root==Path("/")
                or not root.is_relative_to(home)):
            raise RuntimeError("Unsafe audio classifier directory")
        if (self.root.exists() and any(self.root.iterdir())
                and not (self.root/MARKER).is_file()):
            raise RuntimeError("Refusing to overwrite non-TIHULU model files")
        self.root.mkdir(parents=True,exist_ok=True)
        (self.root/MARKER).write_text("Owner-approved audio label runtime\n")
        def run(argv,*,timeout,env=None):
            result=subprocess.run(argv,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                env=env,timeout=timeout,check=False)
            if result.returncode:
                raise RuntimeError(result.stderr.decode(
                    "utf-8","replace")[-640:] or "Acoustic model setup failed")
        if not self.python.is_file():
            run([sys.executable,"-m","venv",str(self.root/"venv")],timeout=240)
        run([str(self.python),"-m","pip","install",
             "--disable-pip-version-check","torch>=2.7,<3",
             "--index-url","https://download.pytorch.org/whl/cpu"],
            timeout=2400)
        run([str(self.python),"-m","pip","install",
             "--disable-pip-version-check","transformers>=4.44,<5",
             "scipy>=1.11,<2","numpy>=1.24,<3",
             "safetensors>=0.4","huggingface_hub>=0.26,<2"],
            timeout=1800)
        repo,rev=WEIGHTS[kind]
        folder.mkdir(parents=True,exist_ok=True)
        script=("from huggingface_hub import snapshot_download;"
                "snapshot_download(repo_id="+repr(repo)+
                ",revision="+repr(rev)+
                ",local_dir="+repr(str(folder))+
                ",allow_patterns=['config.json','model.safetensors',"
                "'preprocessor_config.json','vocab.json'])")
        env=self.env()
        env.pop("HF_HUB_OFFLINE",None)
        env.pop("TRANSFORMERS_OFFLINE",None)
        run([str(self.python),"-c",script],env=env,timeout=2000)
        if not all((folder/name).is_file()
                   for name in ("config.json","model.safetensors",
                                "preprocessor_config.json")):
            raise RuntimeError("Incomplete classifier model; retry install")
        (folder/".tihulu-downloaded").write_text(
            "Weights present; actual inference not yet benchmarked\n")
        return ("Installed local "+kind+
                " acoustic weights; a real prediction and speed check is "
                "still required. No background audio collection enabled.")


def classify_event_scores(pairs):
    """Map ACTUAL AudioSet classifier scores, never pitch or silence guesses."""
    outputs={}
    if not isinstance(pairs,list):
        return []
    for item in pairs[:60]:
        if not isinstance(item,dict):
            continue
        raw=str(item.get("label","")).casefold().strip()
        score=item.get("confidence")
        if not isinstance(score,(int,float)) or not 0.0<=score<=1.0:
            continue
        kind=EVENT_LABELS.get(raw)
        if kind and score>=0.80:
            outputs[kind]=max(score,outputs.get(kind,0.0))
    return [{"type":key,"confidence":score,"source":"AST AudioSet"}
            for key,score in sorted(outputs.items(),key=lambda item:-item[1])[:2]]


def voice_prediction(probabilities, age_score=None):
    """Conservative perceived acoustic type, never verified age or gender.

    A short adult/female narration clip can be mistaken for a child. A child
    label needs unusually strong evidence and must not contradict the same
    model's independent approximate age estimate. With doubt, show no label.
    """
    if (not isinstance(probabilities,list) or len(probabilities)!=3 or
            any(not isinstance(v,(float,int)) or v<0 or v>1
                for v in probabilities)):
        return None
    ranked=sorted((float(v) for v in probabilities),reverse=True)
    score=ranked[0]
    kind=("child","female","male")[probabilities.index(max(probabilities))]
    if (score < (0.95 if kind=="child" else 0.88) or
            score-ranked[1] < 0.25):
        return None
    if (kind=="child" and age_score is not None and
            (not isinstance(age_score,(int,float)) or
             not 0<=age_score<=1 or age_score>=0.18)):
        # 0.18 is roughly the model's adult-boundary estimate, not a
        # scientific age determination. Reject contradictions only.
        return None
    return {"voice_type":kind,"voice_type_confidence":score,
            "voice_type_source":"audEERING 6-layer (perceived voice, noncommercial)"}


class _Worker:
    def __init__(self):
        self.lock=threading.Lock()
        self.process=None

    def _stop(self):
        p=self.process
        self.process=None
        if p is not None and p.poll() is None:
            p.terminate()
            try:p.wait(timeout=2)
            except subprocess.TimeoutExpired:p.kill()

    def close(self):
        with self.lock:self._stop()

    def predict(self,pcm,kind):
        if not isinstance(pcm,bytes) or not 32000<=len(pcm)<=MAX_AUDIO or len(pcm)%2:
            raise ValueError("Expected 32kHz mono s16le audio")
        owner=AudioLabels()
        if not owner.installed(kind):
            raise RuntimeError("Optional "+kind+" model not installed")
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._stop()
                self.process=subprocess.Popen(
                    [str(owner.python),"-u","-m",
                     "tv_center.audio_classifiers","--serve"],
                    env=owner.env(),stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    bufsize=0,close_fds=True)
            request=json.dumps({
                "kind":kind,"pcm":base64.b64encode(pcm).decode("ascii")},
                separators=(",",":")).encode("ascii")+b"\n"
            try:
                self.process.stdin.write(request)
                self.process.stdin.flush()
                ready,_,_=select.select([self.process.stdout],[],[],3)
                if not ready:
                    self._stop()
                    raise TimeoutError("Acoustic model exceeded 3s live budget; optional labels skipped")
                answer=self.process.stdout.readline(100_000)
                if not answer.endswith(b"\n"):
                    self._stop()
                    raise RuntimeError("Acoustic classifier response incomplete")
                result=json.loads(answer)
                if result.get("error"):
                    raise RuntimeError(str(result["error"])[:160])
                return result
            except (OSError,BrokenPipeError,ValueError) as exc:
                self._stop()
                raise RuntimeError("Acoustic classifier unavailable: "+
                                   str(exc)[:160]) from exc


_worker=_Worker()
atexit.register(_worker.close)


def detect_sound_events(pcm):
    return classify_event_scores(_worker.predict(pcm,"sound").get("labels",[]))


def detect_voice_type(pcm):
    prediction=_worker.predict(pcm,"voice")
    return voice_prediction(prediction.get("probabilities"),
                            age_score=prediction.get("age_score"))


def _serve():
    import numpy as np
    import torch
    from scipy.signal import resample_poly
    from transformers import (AutoFeatureExtractor,
                              AutoModelForAudioClassification)
    torch.set_num_threads(2)
    models={}
    owner=AudioLabels()

    def loaded(kind):
        if kind in models:
            return models[kind]
        folder=owner.model_dir(kind)
        if not owner.installed(kind):
            raise RuntimeError("Missing installed classifier "+kind)
        if kind=="sound":
            extractor=AutoFeatureExtractor.from_pretrained(
                str(folder),local_files_only=True)
            model=AutoModelForAudioClassification.from_pretrained(
                str(folder),local_files_only=True).eval().cpu()
        else:
            from transformers import Wav2Vec2Processor
            from transformers.models.wav2vec2.modeling_wav2vec2 import (
                Wav2Vec2Model,Wav2Vec2PreTrainedModel)
            class ModelHead(torch.nn.Module):
                def __init__(self,config,num):
                    super().__init__()
                    self.dense=torch.nn.Linear(config.hidden_size,
                                               config.hidden_size)
                    self.dropout=torch.nn.Dropout(config.final_dropout)
                    self.out_proj=torch.nn.Linear(config.hidden_size,num)
                def forward(self,x):
                    x=self.dropout(x)
                    x=torch.tanh(self.dense(x))
                    return self.out_proj(self.dropout(x))
            class AgeGenderModel(Wav2Vec2PreTrainedModel):
                def __init__(self,config):
                    super().__init__(config)
                    self.wav2vec2=Wav2Vec2Model(config)
                    self.age=ModelHead(config,1)
                    self.gender=ModelHead(config,3)
                    self.post_init()
                def forward(self,input_values):
                    hidden=self.wav2vec2(input_values)[0].mean(dim=1)
                    return (self.age(hidden),
                            torch.softmax(self.gender(hidden),dim=1))
            extractor=Wav2Vec2Processor.from_pretrained(
                str(folder),local_files_only=True)
            model=AgeGenderModel.from_pretrained(
                str(folder),local_files_only=True).eval().cpu()
        models[kind]=(extractor,model)
        return models[kind]

    for raw in sys.stdin.buffer:
        try:
            request=json.loads(raw)
            kind=request.get("kind")
            if kind not in WEIGHTS:
                raise ValueError("Unknown acoustic kind")
            pcm=base64.b64decode(request["pcm"],validate=True)
            if not 32000<=len(pcm)<=MAX_AUDIO or len(pcm)%2:
                raise ValueError("Invalid PCM")
            sound=np.frombuffer(pcm,dtype="<i2").astype("float32")/32768
            sound=resample_poly(sound,1,2).astype("float32")
            extractor,model=loaded(kind)
            if kind=="sound":
                x=extractor(sound,sampling_rate=16000,return_tensors="pt")
                with torch.inference_mode():
                    logits=model(**x).logits.squeeze(0)
                values=torch.sigmoid(logits).tolist()
                mapping=model.config.id2label
                ranks=sorted(range(len(values)),key=lambda j:values[j],
                             reverse=True)[:60]
                response={"labels":[{"label":mapping.get(j,str(j)),
                                     "confidence":float(values[j])}
                                    for j in ranks]}
            else:
                x=extractor(sound,sampling_rate=16000,
                            return_tensors="pt")["input_values"]
                with torch.inference_mode():
                    age,p=model(x)
                response={"probabilities":[float(v) for v in p[0].tolist()],
                          "age_score":float(age.reshape(-1)[0].item())}
        except Exception as exc:
            response={"error":str(exc)[:160]}
        sys.stdout.write(json.dumps(response,separators=(",",":"))+"\n")
        sys.stdout.flush()


def main(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    if args==["--serve"]:
        _serve()
        return 0
    if args==["--status"]:
        print(json.dumps({k:AudioLabels().installed(k) for k in WEIGHTS}))
        return 0
    if args==["--install-sound"]:
        print(AudioLabels().install("sound"))
        return 0
    if args==["--install-voice"]:
        print(AudioLabels().install("voice",noncommercial_acknowledged=True))
        return 0
    raise SystemExit("Usage: audio_classifiers --status/--install-sound/"
                     "--install-voice/--serve")


if __name__=="__main__":
    raise SystemExit(main())
