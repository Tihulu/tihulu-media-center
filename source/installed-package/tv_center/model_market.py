"""Owner-triggered, local-first, replaceable Whisper + Argos model library.

No background downloads. Only checked HTTPS upstream Whisper files in this
curated list are downloadable. Own files are never touched: removal is limited
to files directly inside the app-managed model directory.
"""
from __future__ import annotations
import hashlib
import json
import re
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request

CATALOG = {
    "tiny": {
        "name": "Whisper Tiny multilingual", "size_mb": 78, "backend": "whisper.cpp CPU",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin",
        "sha256": "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21",
        "filename": "ggml-tiny.bin", "max_bytes": 90000000,
    },
    "small": {
        "name": "Whisper Small multilingual", "size_mb": 488, "backend": "whisper.cpp CPU",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
        "sha256": "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b",
        "filename": "ggml-small.bin", "max_bytes": 550000000,
    },
}


class ModelError(RuntimeError):
    pass


class ModelLibrary:
    def __init__(self, root=None):
        self.root = Path(root or Path.home()/".local/share/tihulu-tv-center/models").expanduser()
        # Explicit alternate folder can be selected for external SSDs.
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self.catalog = dict(CATALOG)
        self.manifest = self.root / ".tihulu-verified-market.json"
        if self.manifest.is_file() and not self.manifest.is_symlink():
            try:
                if self.manifest.stat().st_size <= 80_000:
                    saved = json.loads(self.manifest.read_text(encoding="utf-8"))
                    if isinstance(saved, dict):
                        from .online_models import ALLOWED, BASE
                        for key, desc in saved.items():
                            if (key in ALLOWED and isinstance(desc, dict)
                                and desc.get("filename") == f"ggml-{key}.bin"
                                and desc.get("url") == BASE + f"ggml-{key}.bin"
                                and isinstance(desc.get("sha256"), str)
                                and re.fullmatch(r"[a-f0-9]{64}", desc["sha256"])
                                and type(desc.get("max_bytes")) is int
                                and 1_000_000 < desc["max_bytes"] <= 4_200_000_000):
                                self.catalog[key] = desc
            except (OSError, ValueError, UnicodeError):
                pass

    def refresh_online(self, query=""):
        from .online_models import search_official_models
        results = search_official_models(query)
        if not results:
            return []
        self.catalog.update(results)
        # Remember trusted checksum metadata so a downloaded model remains
        # selectable after restarting without network access.
        metadata = {key: value for key,value in self.catalog.items()
                    if key not in CATALOG}
        tmp = self.manifest.with_suffix(".tmp")
        tmp.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        os.chmod(tmp,0o600)
        os.replace(tmp,self.manifest)
        return list(results)

    def _path(self, key):
        if key not in self.catalog:
            raise ModelError("Unknown curated/verified model")
        return self.root / self.catalog[key]["filename"]

    def installed(self):
        return [
            {"id": key, "name": desc["name"], "size_mb": desc["size_mb"],
             "path": str(self._path(key)), "installed": self._path(key).is_file()}
            for key, desc in self.catalog.items()
        ]

    def add_local(self, key, file):
        src = Path(file).expanduser().resolve(strict=True)
        dest = self._path(key)
        if src.is_dir() or src.stat().st_size > self.catalog[key]["max_bytes"]:
            raise ModelError("Invalid Whisper model size")
        if src == dest:
            return str(dest)
        self._copy_verified(src, key)
        return str(dest)

    def _copy_verified(self, source, key):
        desc = self.catalog[key]
        digest = hashlib.sha256()
        with tempfile.NamedTemporaryFile(dir=self.root, prefix=".tihulu-model-",
                                         delete=False) as out:
            staged = Path(out.name)
            try:
                with Path(source).open("rb") as inp:
                    total = 0
                    while chunk := inp.read(1024 * 1024):
                        total += len(chunk)
                        if total > desc["max_bytes"]:
                            raise ModelError("Model exceeds size limit")
                        digest.update(chunk)
                        out.write(chunk)
            except Exception:
                staged.unlink(missing_ok=True)
                raise
        if digest.hexdigest() != desc["sha256"]:
            staged.unlink(missing_ok=True)
            raise ModelError("SHA-256 mismatch: refusing unverified model")
        os.chmod(staged, 0o600)
        os.replace(staged, self._path(key))

    def download(self, key, progress=None):
        desc = self.catalog.get(key)
        if desc is None:
            raise ModelError("Unknown model catalog entry")
        if self._path(key).exists():
            raise ModelError("This model is already installed")
        # Only a fixed, vetted HTTPS source; redirects may go to a CDN.
        req = urllib.request.Request(desc["url"], headers={"User-Agent":"TIHULU-TV-Center/0.1"})
        tmp = None
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                if response.url.split("/")[0] != "https:":
                    raise ModelError("Insecure model download redirect")
                # Max_bytes is a safety cap, NOT the content's true size.
                # Only display a percentage when the server supplies a
                # plausible Content-Length; otherwise show bytes received.
                raw_length = response.headers.get("Content-Length")
                try:
                    expected = int(raw_length)
                except (TypeError, ValueError):
                    expected = None
                if expected is not None and not 0 < expected <= desc["max_bytes"]:
                    expected = None
                with tempfile.NamedTemporaryFile(dir=self.root, prefix=".tihulu-download-",
                                                 delete=False) as out:
                    tmp = Path(out.name)
                    total = 0
                    while chunk := response.read(256 * 1024):
                        total += len(chunk)
                        if total > desc["max_bytes"]:
                            raise ModelError("Download exceeds size limit")
                        out.write(chunk)
                        if progress:
                            progress(total, expected)
            self._copy_verified(tmp, key)
            return str(self._path(key))
        except (OSError, TimeoutError, ValueError) as exc:
            raise ModelError(str(exc)) from exc
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)

    def remove(self, key):
        file = self._path(key)
        if file.is_symlink():
            raise ModelError("Refusing to follow model symlink")
        if file.is_file():
            file.unlink()
        return str(file)

    def capability(self):
        from textcenter.compute import detect_devices
        from textcenter.transcripts import installed_translation_pairs
        profile = detect_devices()
        return {
            "devices": profile["devices"],
            "speech": profile["speech"],
            "argos_pairs": installed_translation_pairs(),
            "models": self.installed(),
        }


def argos_available_pairs(refresh=False):
    try:
        from argostranslate import package
    except ImportError as exc:
        raise ModelError("Argos Translate Python package unavailable") from exc
    if refresh:
        package.update_package_index()  # only after explicit user click
    try:
        found = package.get_available_packages()
    except Exception as exc:
        raise ModelError("Argos catalog not available") from exc
    return [{"source": p.from_code, "target": p.to_code,
             "version": getattr(p, "package_version", ""),
             "name": str(p)}
            for p in found if p.from_code in ("tr", "de", "en")
            and p.to_code in ("tr", "de", "en") and p.from_code != p.to_code
            and getattr(p, "type", "translate") == "translate"]


def argos_install(source, target):
    if source not in ("de", "en", "tr") or target not in ("de", "en", "tr") or source == target:
        raise ModelError("Invalid Argos language pair")
    from argostranslate import package
    found = next((p for p in package.get_available_packages()
                  if p.from_code == source and p.to_code == target
                  and getattr(p, "type", "translate") == "translate"), None)
    if found is None:
        raise ModelError("Requested translation package is unavailable from official Argos index")
    # Official Argos download + install; only run after interactive confirmation.
    path = found.download()
    package.install_from_path(path)
    return f"{source} -> {target}"


def argos_installed_pairs():
    try:
        from argostranslate import package
    except ImportError:
        return []
    return [{"source": p.from_code, "target": p.to_code,
             "name": str(p), "path": str(p.package_path)}
            for p in package.get_installed_packages()
            if p.from_code in ("tr", "de", "en") and p.to_code in ("tr", "de", "en")]


def argos_remove(source, target):
    from argostranslate import package
    installed = [p for p in package.get_installed_packages()
                 if p.from_code == source and p.to_code == target]
    if len(installed) != 1:
        raise ModelError("Expected exactly one installed Argos package for this language pair")
    location = Path(installed[0].package_path).resolve()
    if not location.is_relative_to(Path.home().resolve()):
        raise ModelError("Refusing to uninstall Argos package outside the user's home directory")
    package.uninstall(installed[0])
    return f"{source} -> {target}"
