# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit read-only reuse of an existing TIHULU asset home.

Only known local model/runtime paths are considered; no recursive home scan,
copy, model loading, download, credential import or settings write.
"""
import json
import os
from pathlib import Path


def asset_home():
    value = os.environ.get("TIHULU_ASSET_HOME", "")
    return Path(value).expanduser() if value and Path(value).is_absolute() else None


def existing_asset(path):
    path = Path(path).expanduser()
    home = asset_home()
    if path.exists() or home is None:
        return path
    try:
        relative = path.relative_to(Path.home())
    except ValueError:
        return path
    candidate = home / relative
    return candidate if candidate.exists() else path


def model_preferences():
    home = asset_home()
    if home is None or home == Path.home():
        return {}
    path = home / ".config/tihulu-tv-center/ai-settings.json"
    try:
        if not path.is_file() or path.stat().st_size > 16384:
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != 1:
            return {}
        result = {}
        for key in ("model_path", "model_dir"):
            value = raw.get(key)
            if isinstance(value, str) and value and len(value) <= 1024:
                p = Path(value).expanduser()
                if p.is_absolute() and (p.is_file() if key == "model_path" else p.is_dir()):
                    result[key] = str(p)
        translator = raw.get("translation_model")
        if translator in ("argos", "nllb", "madlad", "de_tr_direct", "auto_offline"):
            result["translation_model"] = translator
        return result
    except (OSError, ValueError):
        return {}


def require_asset_write():
    if asset_home() is not None:
        raise RuntimeError("Existing assets are read-only in this test profile; use the owner installation to manage models")


def configure_argos_path():
    path = existing_asset(Path.home() / ".local/share/argos-translate/packages")
    if asset_home() is not None and path.is_dir():
        os.environ.setdefault("ARGOS_PACKAGES_DIR", str(path))
