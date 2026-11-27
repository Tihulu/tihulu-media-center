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


def prepare_argos_runtime_view():
    """Writable tokenizer extraction cache with symlinked, read-only model weights.

    Called only inside a translation worker. Preview's host filesystem stays
    read-only; Argos may unpack stanza.zip into this private package view.
    """
    if asset_home() is None:
        return
    import fcntl
    import hashlib
    import shutil
    import zipfile
    from pathlib import PurePosixPath
    source = existing_asset(Path.home() / ".local/share/argos-translate/packages")
    if not source.is_dir():
        return
    cache = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "tihulu-argos"
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A package's path, sizes and mtimes invalidate the private view after updates.
    entries = sorted(p for p in source.rglob("*") if p.is_file())
    identity = str(source) + "".join(str(p.relative_to(source)) + str(p.stat().st_mtime_ns) + str(p.stat().st_size) for p in entries)
    view = cache / hashlib.sha256(identity.encode()).hexdigest()[:24]
    with (cache / ".prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = view / ".ready"
        if not marker.is_file():
            view.mkdir(exist_ok=True, mode=0o700)
            mutable = {}
            for archive in entries:
                if archive.name != "stanza.zip":
                    continue
                package = archive.parent.relative_to(source)
                with zipfile.ZipFile(archive) as zipped:
                    for info in zipped.infolist():
                        name = PurePosixPath(info.filename)
                        if name.is_absolute() or ".." in name.parts or "\\" in info.filename:
                            raise ValueError("Unsafe Argos tokenizer archive path")
                        if not info.is_dir():
                            mutable[package / str(name)] = (archive, info.filename)
            for file in entries:
                rel = file.relative_to(source)
                if rel in mutable:
                    continue
                dest = view / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists() and not dest.is_symlink():
                    dest.symlink_to(file)
            for rel, (archive, member) in mutable.items():
                dest = view / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_symlink():
                    dest.unlink()  # only our private link, never its source
                if not dest.exists():
                    with zipfile.ZipFile(archive) as zipped, zipped.open(member) as inp, dest.open("xb") as out:
                        shutil.copyfileobj(inp, out)
            marker.write_text("Private Argos tokenizer view; translation weights linked\n")
    os.environ["ARGOS_PACKAGES_DIR"] = str(view)
