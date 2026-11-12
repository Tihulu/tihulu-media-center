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
    "active_profile": "", "remote_gpu_enabled": False,
    "remote_gpu_url": "", "remote_gpu_fallback": True,
    "hailo_encoder_hef": "", "hailo_decoder_hef": "", "hailo_npy_dir": "",
    "hailo_cpu_fallback": True, "pi_cpu_threads": 3,
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
        if updated["backend"] not in ("auto", "cpu", "gpu", "npu", "remote"):
            raise ValueError("Unsupported AI backend")
        if updated["translation_model"] not in ("argos", "nllb", "deepl", "madlad",
                                                "de_tr_direct", "auto_offline"):
            raise ValueError("Unsupported translation model")
        from .ai_profiles import PROFILES
        if updated["active_profile"] and updated["active_profile"] not in PROFILES:
            raise ValueError("Unknown selected AI mode")
        for key in ("remote_gpu_enabled", "remote_gpu_fallback", "hailo_cpu_fallback"):
            if type(updated[key]) is not bool:
                raise ValueError("Remote GPU switches must be boolean")
        if not isinstance(updated["remote_gpu_url"],str) or len(updated["remote_gpu_url"]) > 512:
            raise ValueError("Invalid remote GPU URL")
        # A stored endpoint does not send anything by itself. Explicit
        # remote mode plus TLS/token requirements are checked by the client.
        if updated["backend"]=="remote" and not updated["remote_gpu_enabled"]:
            raise ValueError("Enable remote GPU explicitly before selecting it")
        if type(updated["pi_cpu_threads"]) is not int or not 1 <= updated["pi_cpu_threads"] <= 4:
            raise ValueError("Raspberry Pi CPU threads must be 1–4")
        for field in ("model_path", "model_dir", "hailo_encoder_hef",
                      "hailo_decoder_hef", "hailo_npy_dir"):
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
        # Keep model loading and HailoRT device access deferred until speech
        # starts. Environment only carries approved local asset paths.
        from .pi_hailo import environment
        names=("TIHULU_HAILO_ENCODER_HEF", "TIHULU_HAILO_DECODER_HEF",
               "TIHULU_HAILO_WHISPER_NPY_DIR")
        for name in names:
            os.environ.pop(name, None)
        os.environ.update(environment(self.values))
        active = self.values.get("active_profile")
        try:
            on_pi = "Raspberry Pi 5" in Path("/proc/device-tree/model").read_text(
                encoding="utf-8", errors="replace")
        except OSError:
            on_pi = False
        # Vanilla first install has no explicitly selected profile. Apply
        # the Pi CPU budget then as well; no subprocess/driver probe on boot.
        if active in ("pi5","pi5_hat2") or (on_pi and not active):
            os.environ["TIHULU_PI_CPU_THREADS"] = str(self.values["pi_cpu_threads"])
        else:
            os.environ.pop("TIHULU_PI_CPU_THREADS", None)
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
