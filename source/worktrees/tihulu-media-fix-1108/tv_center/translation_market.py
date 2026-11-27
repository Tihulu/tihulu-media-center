"""Optional higher-capacity local multilingual NLLB translator.

This model is ~2.5 GB, licensed CC-BY-NC-4.0 (non-commercial); the model
license is NOT inherited from the GPL code. The user must confirm the
download and license. This is an alternative to smaller Argos packages,
not claimed faster, universally more accurate, or compatible with any NPU.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

MODEL_ID = "facebook/nllb-200-distilled-600M"
MODEL_REVISION = "a3e77be725cf30383f1faeb8d2f0b0ea98ac554e"
LICENSE = "CC-BY-NC-4.0 (non-commercial use)"
from .language_codes import language_code

# Familiar ISO codes are a convenience. Advanced users can enter any
# installed NLLB tokenizer language token, such as srp_Cyrl or zho_Hant.
LANG = {
    "de":"deu_Latn", "en":"eng_Latn", "tr":"tur_Latn",
    "fr":"fra_Latn", "es":"spa_Latn", "it":"ita_Latn",
    "nl":"nld_Latn", "pl":"pol_Latn", "pt":"por_Latn",
    "ru":"rus_Cyrl", "uk":"ukr_Cyrl", "ar":"arb_Arab",
    "ja":"jpn_Jpan", "ko":"kor_Hang", "zh":"zho_Hans",
    "hi":"hin_Deva", "sv":"swe_Latn", "da":"dan_Latn",
    "fi":"fin_Latn", "el":"ell_Grek", "cs":"ces_Latn",
    "ro":"ron_Latn", "hu":"hun_Latn", "sk":"slk_Latn",
    "bg":"bul_Cyrl", "hr":"hrv_Latn", "sr":"srp_Cyrl",
    "ca":"cat_Latn", "he":"heb_Hebr", "id":"ind_Latn",
    "vi":"vie_Latn", "th":"tha_Thai",
}


def nllb_code(language):
    requested = language_code(language, nllb=True)
    return LANG.get(requested, requested if "_" in requested else "")


def nllb_token_id(tokenizer, language):
    code = nllb_code(language)
    if not code:
        raise ValueError(f"No NLLB mapping for {language}; enter a complete NLLB code")
    available = getattr(tokenizer, "lang_code_to_id", None)
    if isinstance(available, dict):
        if code not in available:
            raise ValueError(f"Chosen NLLB language is unsupported by installed tokenizer: {code}")
        return code, available[code]
    token = tokenizer.convert_tokens_to_ids(code)
    if (token is None or token == getattr(tokenizer, "unk_token_id", None)
            or type(token) is not int or token < 0):
        raise ValueError(f"Chosen NLLB language is unsupported by installed tokenizer: {code}")
    return code, token


class TranslationModelMarket:
    def __init__(self, root=None):
        if root is None:
            from .ai_settings import AISettings
            selected = AISettings().values.get("model_dir", "")
            root = (Path(selected) / "translator-models" if selected else
                    Path.home()/".local/share/tihulu-tv-center/translator-models")
        self.root=Path(root).expanduser()
        self.model=self.root/"nllb-600m"
        self.marker=self.model/".tihulu-nllb-ready"

    def status(self):
        return {"installed":self.marker.is_file() and
                (self.model/"model.safetensors").is_file() and
                (self.model/"config.json").is_file(),
                "path":str(self.model),"name":"NLLB-200 distilled 600M",
                "license":LICENSE,"approx_disk_gb":2.5,
                "minimum_ram_gb_recommended":6,
                "runtime":"local Transformers PyTorch (CPU or detected CUDA)"}

    def install(self):
        if os.geteuid()==0:
            raise RuntimeError("Do not install translation models as root")
        from .runtime import AIRuntime
        runtime=AIRuntime()
        if not runtime.status()["installed"]:
            runtime.install_argos()
        python=runtime.status()["python"]
        self.root.mkdir(parents=True,exist_ok=True)
        if self.root.is_symlink() or self.root.resolve() == Path("/"):
            raise RuntimeError("Refusing unsafe translator storage path")
        if self.model.resolve().parent != self.root.resolve():
            raise RuntimeError("Unsafe nested translator model path")
        if self.model.is_symlink():
            raise RuntimeError("Refusing symlink model directory")
        packages=["transformers>=4.44,<5","torch>=2.7","sentencepiece",
                  "huggingface_hub>=0.28,<1","safetensors"]
        result=subprocess.run([python,"-m","pip","install",
           "--disable-pip-version-check",*packages],
           stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
           stderr=subprocess.PIPE,timeout=2400,check=False)
        if result.returncode:
            raise RuntimeError("NLLB dependencies failed: " +
                result.stderr.decode("utf-8","replace")[-500:])
        env=os.environ.copy()
        root=str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"]=root+os.pathsep+env.get("PYTHONPATH","")
        outcome=subprocess.run([python,"-m","tv_center.translation_market","--download"],
            env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,timeout=2400,check=False)
        if outcome.returncode:
            raise RuntimeError("NLLB model download failed: " +
                outcome.stderr.decode("utf-8","replace")[-600:])
        if not self.status()["installed"]:
            raise RuntimeError("NLLB safetensors or tokenizer files missing")
        # Installing weights alone previously displayed INSTALLED while
        # model.shared.weight was still a meta tensor. Prove real inference.
        check=self.selftest()
        if not check.get("ready"):
            raise RuntimeError(
                "NLLB weights downloaded, but real offline inference failed: "+
                str(check.get("reason") or "unknown failure")[:360]+
                ". Original files kept; Argos stays available.")
        return ("NLLB real offline inference VERIFIED ("+
                str(check.get("device"))+"). Select NLLB and Save settings.")

    def _download(self):
        from huggingface_hub import snapshot_download
        self.model.mkdir(parents=True,exist_ok=True)
        snapshot_download(repo_id=MODEL_ID,revision=MODEL_REVISION,
            allow_patterns=["*.safetensors","*.json","*.model","*.txt"],
            local_dir=str(self.model),max_workers=2)
        for name in ("model.safetensors","config.json","tokenizer_config.json"):
            if not (self.model/name).is_file():
                raise RuntimeError("Expected NLLB model file missing: "+name)
        from safetensors import safe_open
        checkpoint=self.model/"model.safetensors"
        if checkpoint.stat().st_size < 200_000_000:
            raise RuntimeError("NLLB checkpoint unexpectedly short; refusing ready marker")
        with safe_open(str(checkpoint),framework="pt",device="cpu") as reader:
            keys=set(reader.keys())
            shared=("model.shared.weight","model.encoder.embed_tokens.weight",
                    "model.decoder.embed_tokens.weight","lm_head.weight",
                    "shared.weight")
            found=next((k for k in shared if k in keys),None)
            if not found:
                raise RuntimeError("NLLB genuine shared embedding checkpoint missing")
            shape=reader.get_slice(found).get_shape()
            if len(shape)!=2 or shape[0]<100_000 or shape[1]<500:
                raise RuntimeError("NLLB checkpoint shared embedding shape invalid")
        self.marker.write_text(
            f"TIHULU managed optional NLLB; revision={MODEL_REVISION}\n",
            encoding="utf-8")

    def selftest(self):
        """Opt-in actual offline German→English inference; no RF or downloads.

        Run in the same isolated environment as live NLLB, so the installed
        PyTorch/Transformers compatibility is tested rather than guessed.
        """
        from .runtime import AIRuntime
        if not self.status()["installed"]:
            return {"ready":False,"reason":"Install NLLB model first"}
        runtime=AIRuntime().status()
        if not runtime["installed"]:
            return {"ready":False,"reason":"Managed translator Python missing"}
        env=os.environ.copy()
        root=str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"]=root+os.pathsep+env.get("PYTHONPATH","")
        env["HF_HUB_OFFLINE"]="1"
        env["TRANSFORMERS_OFFLINE"]="1"
        env["TOKENIZERS_PARALLELISM"]="false"
        try:
            process=subprocess.run(
                [runtime["python"], "-m", "tv_center.translation_market", "--selftest"],
                cwd=root,env=env,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                timeout=180,check=False)
            if process.returncode:
                # The last 500 raw traceback bytes often start halfway through
                # a Python caret line (^^) and hide the actual exception.
                stderr = process.stderr.decode("utf-8", "replace")
                lines = [line.strip() for line in stderr.splitlines()
                         if line.strip()]
                if process.returncode < 0 and not lines:
                    reason = ("NLLB subprocess terminated by signal " +
                              str(-process.returncode) +
                              " (possible memory pressure; check available RAM)")
                elif lines:
                    reason = next(
                        (line for line in reversed(lines)
                         if (line.startswith(("RuntimeError:", "OSError:",
                                              "ValueError:", "ImportError:",
                                              "ModuleNotFoundError:",
                                              "NotImplementedError:",
                                              "TypeError:", "KeyError:",
                                              "AssertionError:", "CUDA")))),
                        lines[-1])
                else:
                    reason = ("NLLB offline self-test exited with code " +
                              str(process.returncode))
                return {"ready":False, "reason":reason[:600],
                        "exit_code":process.returncode,
                        "traceback_tail":stderr[-3000:]}
            result=json.loads(process.stdout.decode("utf-8","replace"))
            return result if isinstance(result,dict) and result.get("ready") else {
                "ready":False,"reason":"NLLB self-test returned invalid result"}
        except (OSError,ValueError,subprocess.TimeoutExpired) as error:
            return {"ready":False,"reason":str(error)[:300]}

    def remove(self):
        if self.model.is_symlink() or not self.marker.is_file():
            raise RuntimeError("Refusing to remove unverified translator model")
        if self.model.resolve().parent != self.root.resolve() or self.root.resolve() == Path("/"):
            raise RuntimeError("Translator model storage path unsafe; removal refused")
        shutil.rmtree(self.model)
        return "Managed NLLB translator removed; Argos packages preserved"


from functools import lru_cache

def unmaterialized_tensors(model, maximum=8):
    """Meta weights have no data; never use to_empty() as a fake repair."""
    entries = []
    for name, weight in list(model.named_parameters()) + list(model.named_buffers()):
        if getattr(weight, "is_meta", False):
            entries.append(name)
            if len(entries) >= maximum:
                break
    return entries



def repair_meta_embeddings_from_checkpoint(model, checkpoint):
    """Repair ONLY tied embedding parameters from actual safetensors values.

    Some Transformers versions leave tied M2M100 shared embedding parameters
    on the 'meta' device despite a complete HF checkpoint. This function
    never invents or reinitializes weights and never uses to_empty().
    It reads only canonical shared/encoder/decoder/lm_head aliases and
    validates shape and dtype before binding a real tensor.
    """
    missing=unmaterialized_tensors(model,maximum=64)
    if not missing:
        return []
    if not checkpoint.is_file() or checkpoint.stat().st_size < 200_000_000:
        raise RuntimeError("NLLB has unmaterialized meta tensors; "
                           "checkpoint file is missing or implausibly short. "
                           "Install/repair genuine weights.")
    try:
        import torch
        from safetensors import safe_open
    except ImportError as exc:
        raise RuntimeError("NLLB repair requires local torch and safetensors "
                           "in the managed Python runtime") from exc
    shared_aliases=(
        "model.shared.weight", "model.encoder.embed_tokens.weight",
        "model.decoder.embed_tokens.weight", "lm_head.weight",
        "shared.weight", "encoder.embed_tokens.weight",
        "decoder.embed_tokens.weight")
    if not all(key in shared_aliases for key in missing):
        raise RuntimeError("NLLB has non-embedding meta parameters ("+
                           ", ".join(missing[:4])+
                           "); genuine checkpoint or runtime repair needed")
    source=None
    with safe_open(str(checkpoint),framework="pt",device="cpu") as reader:
        keys=set(reader.keys())
        for alias in shared_aliases:
            if alias in keys:
                source=reader.get_tensor(alias)
                if source is not None and source.numel()>0:
                    break
    if source is None:
        raise RuntimeError("NLLB checkpoint has no real tied embedding weights")
    if source.device.type=="meta" or not source.is_floating_point():
        raise RuntimeError("NLLB shared checkpoint tensor was not materialized")
    # A single genuine materialized tensor can be tied across all compatible
    # embedding aliases without multiplying the model's memory usage.
    genuine=torch.nn.Parameter(source.contiguous(),requires_grad=False)
    for fullname in missing:
        current=model.get_parameter(fullname)
        if tuple(current.shape)!=tuple(genuine.shape):
            raise RuntimeError("Checkpoint shared-embedding shape mismatch for "+
                               fullname)
        parent_name,leaf=fullname.rsplit(".",1)
        parent=model.get_submodule(parent_name)
        setattr(parent,leaf,genuine)
    if hasattr(model,"tie_weights"):
        model.tie_weights()
    remaining=unmaterialized_tensors(model,maximum=64)
    if remaining:
        raise RuntimeError("Unmaterialized NLLB weights remain after genuine "
                           "checkpoint recovery: "+", ".join(remaining[:4]))
    return missing


@lru_cache(maxsize=1)
def _load_nllb():
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    import torch
    location = TranslationModelMarket()
    if not location.status()["installed"]:
        raise RuntimeError("NLLB translation weights not installed")
    tokenizer = AutoTokenizer.from_pretrained(
        str(location.model), local_files_only=True, trust_remote_code=False)
    # With recent Transformers / Accelerate combinations, the default
    # low-memory path may leave decoder weights on the *meta* device.
    # On RTX 5080 desktops the ordinary CPU materialization is safer:
    # load the actual pretrained safetensors fully before any .to("cuda").
    model = AutoModelForSeq2SeqLM.from_pretrained(
        str(location.model), local_files_only=True, use_safetensors=True,
        trust_remote_code=False, low_cpu_mem_usage=False, device_map=None)
    missing = unmaterialized_tensors(model)
    if missing:
        # First try the ordinary framework tie operation; only then load a
        # canonical tied embedding from the pinned, real safetensors file.
        if hasattr(model,"tie_weights"):
            model.tie_weights()
        if unmaterialized_tensors(model):
            repair_meta_embeddings_from_checkpoint(
                model,Path(location.model)/"model.safetensors")
    remaining=unmaterialized_tensors(model)
    if remaining:
        raise RuntimeError(
            "NLLB still has unmaterialized meta tensors: " +
            ", ".join(remaining[:4]) +
            ". Model remains disabled; use Argos while repairing.")
    model.eval()
    device = "cpu"
    if torch.cuda.is_available():
        try:
            model.to("cuda")
            device = "cuda"
        except (RuntimeError, NotImplementedError, OSError):
            # CUDA optional for translator; CPU materialization remains
            # valid and is not assumed to meet live TV latency requirements.
            model.to("cpu")
    return model, tokenizer, device, torch


def run_nllb(text,source,target):
    """Local model cached once per persistent worker, never per sentence."""
    model,tokenizer,device,torch=_load_nllb()
    src_code, _ = nllb_token_id(tokenizer, source)
    _, target_token = nllb_token_id(tokenizer, target)
    tokenizer.src_lang=src_code
    data=tokenizer(text[:1600],return_tensors="pt",truncation=True,
                   max_length=256).to(device)
    with torch.inference_mode():
        output=model.generate(**data,
            forced_bos_token_id=target_token,
            max_new_tokens=180,num_beams=3)
    return tokenizer.batch_decode(output,skip_special_tokens=True)[0].strip()


def main():
    if len(sys.argv)==2 and sys.argv[1]=="--download":
        TranslationModelMarket()._download()
        print(json.dumps({"status":"installed","model":MODEL_ID}))
        return 0
    if len(sys.argv)==2 and sys.argv[1]=="--selftest":
        # The explicit test executes real pretrained weights, not a mock
        # translation. The user's TV tuner and audio are never accessed.
        phrase=run_nllb("Guten Morgen", "de", "en")
        if not isinstance(phrase,str) or not phrase.strip() or (
                phrase.strip().casefold()=="guten morgen"):
            raise RuntimeError("NLLB model produced no useful self-test translation")
        model,_,device,_=_load_nllb()
        print(json.dumps({"ready":True,"source":"de","target":"en",
                          "device":device,"translated":phrase[:120]}))
        return 0
    raise SystemExit("Only --download or --selftest allowed")

if __name__=="__main__":
    raise SystemExit(main())
