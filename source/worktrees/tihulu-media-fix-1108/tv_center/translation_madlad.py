"""Optional high-capacity local MADLAD-400 3B translator (Apache-2.0).

GPU-only initial release: real 11+GB safetensors, no bundled weights, no
unverified CPU/NPU acceleration. Downloads happen only after confirmation.
"""
from __future__ import annotations
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

MODEL_ID="google/madlad400-3b-mt"
LICENSE="Apache-2.0"
MODEL_REQUIREMENTS="~12 GB model files; large RAM/VRAM and CUDA recommended"


class MadladMarket:
    def __init__(self,root=None):
        if root is None:
            from .ai_settings import AISettings
            folder=AISettings().values.get("model_dir","")
            root=(Path(folder)/"translator-models" if folder else
                  Path.home()/".local/share/tihulu-tv-center/translator-models")
        self.root=Path(root).expanduser()
        self.model=self.root/"madlad400-3b-mt"
        self.marker=self.model/".tihulu-madlad-ready"

    def status(self):
        return {"installed":self.marker.is_file() and
                (self.model/"config.json").is_file() and
                any(self.model.glob("*.safetensors")),
                "model":MODEL_ID,"path":str(self.model),
                "license":LICENSE,"disk_note":MODEL_REQUIREMENTS}

    def install(self):
        if os.geteuid()==0:
            raise RuntimeError("Do not download AI model as root")
        if self.root.is_symlink() or self.model.is_symlink() or (
                self.model.resolve().parent!=self.root.resolve()):
            raise RuntimeError("Unsafe model storage location")
        self.root.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(self.root).free < 16*1024**3:
            raise RuntimeError("MADLAD download needs at least 16 GB free disk")
        from .runtime import AIRuntime
        rt=AIRuntime()
        if not rt.status()["installed"]:
            rt.install_argos()
        python=rt.status()["python"]
        required=["transformers>=4.48,<5","accelerate>=0.32,<2",
                  "sentencepiece","torch>=2.7","safetensors",
                  "huggingface_hub>=0.28,<1"]
        result=subprocess.run([python,"-m","pip","install",
            "--disable-pip-version-check",*required],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,timeout=2400,check=False)
        if result.returncode:
            raise RuntimeError("Managed MADLAD dependencies failed: "+
                               result.stderr.decode("utf-8","replace")[-350:])
        env=os.environ.copy()
        env["PYTHONPATH"]=str(Path(__file__).resolve().parent.parent)+os.pathsep+env.get("PYTHONPATH","")
        result=subprocess.run([python,"-m","tv_center.translation_madlad","--download"],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env=env,timeout=5400,check=False)
        if result.returncode or not self.status()["installed"]:
            raise RuntimeError("MADLAD download failed: "+
                               result.stderr.decode("utf-8","replace")[-350:])
        verified=self.selftest()
        if not verified.get("ready"):
            raise RuntimeError("MADLAD downloaded but real GPU inference FAILED: "+
                               str(verified.get("reason","unknown"))[:250])
        return "MADLAD real DE→EN GPU translation verified. Select and Save."

    def _download(self):
        from huggingface_hub import snapshot_download
        self.model.mkdir(parents=True,exist_ok=True)
        snapshot_download(repo_id=MODEL_ID,revision="main",
            local_dir=str(self.model),max_workers=2,
            allow_patterns=["*.safetensors","*.json","*.model","*.txt"])
        if not (self.model/"config.json").is_file() or not any(
                self.model.glob("*.safetensors")):
            raise RuntimeError("MADLAD checkpoint incomplete")
        if sum(p.stat().st_size for p in self.model.glob("*.safetensors"))<3*1024**3:
            raise RuntimeError("MADLAD checkpoint too short")
        self.marker.write_text("TIHULU user-managed MADLAD; Apache-2.0\n",encoding="utf-8")

    def selftest(self):
        if not self.status()["installed"]:
            return {"ready":False,"reason":"Download MADLAD first"}
        from .runtime import AIRuntime
        runtime=AIRuntime().status()
        if not runtime["installed"]:
            return {"ready":False,"reason":"Managed Python runtime missing"}
        env=os.environ.copy()
        env["PYTHONPATH"]=str(Path(__file__).resolve().parent.parent)+os.pathsep+env.get("PYTHONPATH","")
        env["HF_HUB_OFFLINE"]="1"
        env["TRANSFORMERS_OFFLINE"]="1"
        env["TOKENIZERS_PARALLELISM"]="false"
        try:
            outcome=subprocess.run([runtime["python"],"-m",
                "tv_center.translation_madlad","--selftest"],
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                env=env,timeout=240,check=False)
            if outcome.returncode:
                lines=outcome.stderr.decode("utf-8","replace").splitlines()
                return {"ready":False,"reason":next(
                    (l.strip() for l in reversed(lines) if "Error:" in l),
                    "MADLAD process failed or was killed by memory pressure")[:300]}
            parsed=json.loads(outcome.stdout.decode("utf-8"))
            return parsed if parsed.get("ready") else {"ready":False,"reason":"No valid translated output"}
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
            return {"ready":False,"reason":str(exc)[:300]}

    def remove(self):
        if self.model.is_symlink() or not self.marker.is_file():
            raise RuntimeError("Refusing to delete unverified model")
        if self.model.resolve().parent!=self.root.resolve():
            raise RuntimeError("Refusing unsafe model location")
        shutil.rmtree(self.model)
        return "User-managed MADLAD checkpoint removed; Argos/NLLB untouched"


@lru_cache(maxsize=1)
def _load():
    from transformers import AutoTokenizer,AutoModelForSeq2SeqLM
    import torch
    location=MadladMarket()
    if not location.status()["installed"]:
        raise RuntimeError("MADLAD model not installed")
    if not torch.cuda.is_available():
        raise RuntimeError("MADLAD 3B requires verified CUDA GPU in this release; "
                           "Argos and NLLB remain available")
    tokenizer=AutoTokenizer.from_pretrained(str(location.model),
        local_files_only=True,trust_remote_code=False)
    model=AutoModelForSeq2SeqLM.from_pretrained(str(location.model),
        local_files_only=True,use_safetensors=True,trust_remote_code=False,
        torch_dtype=torch.float16,low_cpu_mem_usage=False,
        device_map=None)
    from .translation_market import unmaterialized_tensors
    if unmaterialized_tensors(model):
        raise RuntimeError("MADLAD weights include unmaterialized meta tensors; "
                           "not using unsafe model")
    model=model.to("cuda").eval()
    return model,tokenizer,torch


def run_madlad(text,source,target):
    from .language_codes import language_code
    src=language_code(source)
    dst=language_code(target)
    if len(src)!=2 or len(dst)!=2:
        raise ValueError("MADLAD requires 2-letter ISO language codes")
    if not isinstance(text,str) or not text.strip() or len(text)>1200:
        raise ValueError("Invalid MADLAD input")
    model,tokenizer,torch=_load()
    prefix="<2"+dst+">"
    if tokenizer.convert_tokens_to_ids(prefix)==tokenizer.unk_token_id:
        raise ValueError("MADLAD tokenizer does not support target "+dst)
    tokens=tokenizer(prefix+" "+text,return_tensors="pt",
        truncation=True,max_length=256).to("cuda")
    with torch.inference_mode():
        output=model.generate(**tokens,max_new_tokens=180,num_beams=3)
    result=tokenizer.batch_decode(output,skip_special_tokens=True)[0].strip()
    if not result:
        raise RuntimeError("MADLAD produced empty translation")
    return result


def main():
    if sys.argv[1:]==["--download"]:
        MadladMarket()._download()
        return 0
    if sys.argv[1:]==["--selftest"]:
        result=run_madlad("Guten Morgen","de","en")
        if result.casefold()=="guten morgen":
            raise RuntimeError("MADLAD self-test did not translate")
        print(json.dumps({"ready":True,"device":"cuda","translated":result}))
        return 0
    raise SystemExit("Only --download or --selftest accepted")

if __name__=="__main__":
    raise SystemExit(main())
