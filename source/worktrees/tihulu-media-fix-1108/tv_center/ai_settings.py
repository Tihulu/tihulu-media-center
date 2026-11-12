"""Explicit per-user optional AI engine settings (off by default)."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile

DEFAULTS = {
    "version": 1, "asr_enabled": False, "translation_enabled": False,
    "backend": "auto", "model_path": "", "model_dir": "",
    "translation_model": "argos",
}

class AISettings:
    def __init__(self, path=None):
        self.path = Path(path or Path.home()/".config/tihulu-tv-center/ai-settings.json")
        self.values = dict(DEFAULTS)
        if self.path.is_file():
            if self.path.stat().st_size > 16384:
                raise ValueError("AI settings file exceeds size limit")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") != 1:
                raise ValueError("Unsupported AI settings format")
            self.update(raw, persist=False)

    def update(self, patch, persist=True):
        unknown = set(patch) - set(DEFAULTS)
        if unknown:
            raise ValueError("Unexpected AI setting keys")
        updated = {**self.values, **patch}
        if type(updated["asr_enabled"]) is not bool or type(updated["translation_enabled"]) is not bool:
            raise ValueError("AI toggles must be boolean")
        if updated["backend"] not in ("auto", "cpu", "gpu", "npu"):
            raise ValueError("Unsupported AI backend")
        if updated["translation_model"] not in ("argos", "nllb", "deepl", "madlad"):
            raise ValueError("Unsupported translation model")
        for field in ("model_path", "model_dir"):
            if not isinstance(updated[field], str) or len(updated[field]) > 1024:
                raise ValueError("Model paths must be strings")
        self.values = updated
        if persist:
            self.save()
        return self.values

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                         prefix=".ai-", delete=False) as fp:
            tmp = Path(fp.name)
            json.dump(self.values, fp, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def configure_environment(self):
        """Bridge existing TEXT CENTER runtime without loading model unless enabled."""
        from .whisper_engine import WhisperRuntime
        os.environ["TIHULU_TRANSLATOR_MODEL"] = self.values["translation_model"]
        managed = WhisperRuntime()
        if managed.ready():
            os.environ["TIHULU_WHISPER_CLI"] = str(managed.binary)
        if managed.ready_gpu():
            os.environ["TIHULU_WHISPER_CUDA_CLI"] = str(managed.cuda_binary)
        else:
            os.environ.pop("TIHULU_WHISPER_CUDA_CLI", None)
        if not self.values["asr_enabled"]:
            os.environ.pop("TIHULU_WHISPER_MODEL", None)
            os.environ["TIHULU_TV_ASR_BACKEND"] = "off"
            return
        model = self.values["model_path"]
        if model:
            os.environ["TIHULU_WHISPER_MODEL"] = model
        os.environ["TIHULU_TV_ASR_BACKEND"] = self.values["backend"]
