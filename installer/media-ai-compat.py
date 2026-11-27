#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit, local-only AI path compatibility for the isolated Media preview.

No legacy settings lookup, copying, downloads, GPU probes, inference or service
access. Only an owner-supplied model reference is written, and only into a new
preview AI JSON file after --apply --confirm-preview-only.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

SOURCE = Path(__file__).resolve().parent.parent / "source" / "installed-package"
sys.path.insert(0, str(SOURCE))
from tv_center.ai_settings import DEFAULTS  # noqa: E402; pure standard-library import

MARKER = ".media-preview-owner-v1"
MARKER_VALUE = "TIHULU_MEDIA_PREVIEW_OWNED_V1\n"


class CompatibilityError(ValueError):
    pass


def no_link_components(path: Path) -> None:
    """Reject symlinks anywhere in a user-supplied or installer-owned path."""
    if not path.is_absolute() or ".." in path.parts:
        raise CompatibilityError("Only absolute, traversal-free paths are accepted")
    for part in reversed((path, *path.parents)):
        if part.is_symlink():
            raise CompatibilityError("Symlinked path component refused")


def checked_path(value: str, kind: str) -> str:
    if not value:
        return ""
    candidate = Path(value).expanduser()
    no_link_components(candidate)
    try:
        info = candidate.lstat()
    except OSError as exc:
        raise CompatibilityError("Explicit model path does not exist") from exc
    if kind == "file":
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 1024:
            raise CompatibilityError("Expected an existing regular model file >1 KiB")
    elif not stat.S_ISDIR(info.st_mode):
        raise CompatibilityError("Expected an existing model directory")
    # Metadata-only check. Never open/checksum/import/scan a private model.
    return str(candidate)


def owned_dir(path: Path) -> None:
    no_link_components(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise CompatibilityError("Isolated preview install/profile missing") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise CompatibilityError("Preview directory is not owned by current user")


def preview_target() -> Path:
    owner = Path.home()
    no_link_components(owner)
    root = owner / ".local/opt/tihulu-media-stable"
    preview = root / "preview-home"
    for directory in (root, preview, preview / ".config"):
        owned_dir(directory)
    marker = root / MARKER
    no_link_components(marker)
    try:
        info = marker.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_size > 128 or marker.read_text(encoding="utf-8") != MARKER_VALUE):
            raise CompatibilityError("Preview ownership marker invalid")
    except OSError as exc:
        raise CompatibilityError("Preview ownership marker missing") from exc
    target_parent = preview / ".config/tihulu-tv-center"
    if target_parent.exists() or target_parent.is_symlink():
        owned_dir(target_parent)
    return target_parent / "ai-settings.json"


def plan(*, model_path: str, model_dir: str, backend: str,
         translator: str) -> dict:
    if not (model_path or model_dir):
        raise CompatibilityError("Explicit --model-path or --model-dir required")
    settings = dict(DEFAULTS)
    settings.update({
        "model_path": checked_path(model_path, "file"),
        "model_dir": checked_path(model_dir, "directory"),
        "backend": backend,
        "translation_model": translator,
        # Deliberate: references are NOT activation or proof of inference.
        "asr_enabled": False,
        "translation_enabled": False,
        "active_profile": "",
        "remote_gpu_enabled": False,
        "remote_gpu_url": "",
    })
    return settings


def apply_to_new_preview(settings: dict) -> Path:
    if os.geteuid() == 0:
        raise CompatibilityError("Never apply compatibility as root")
    target = preview_target()
    parent = target.parent
    if target.exists() or target.is_symlink():
        raise CompatibilityError(
            "Preview AI settings already exist; refusing to overwrite private choices. "
            "Use the preview AI Settings UI for manual changes.")
    if not parent.exists():
        parent.mkdir(mode=0o700)
    owned_dir(parent)
    if target.exists() or target.is_symlink():
        raise CompatibilityError("Preview AI settings appeared; refusing to overwrite")
    # Stage in the *same* checked preview directory; os.link is atomic and
    # fails if a settings file (including a symlink) appears concurrently.
    temp = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=parent, prefix=".ai-compat-",
                                         encoding="utf-8", delete=False) as handle:
            temp = Path(handle.name)
            os.chmod(temp, 0o600)
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        no_link_components(target)
        os.link(temp, target, follow_symlinks=False)
        return target
    except FileExistsError as exc:
        raise CompatibilityError("Existing preview AI file preserved; nothing replaced") from exc
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", default="", help="Explicit pre-existing GGML model file")
    parser.add_argument("--model-dir", default="", help="Explicit pre-existing model directory (SSD allowed)")
    parser.add_argument("--backend", choices=("auto", "cpu", "gpu", "npu"), default="auto")
    parser.add_argument("--translator",
                        choices=("argos", "nllb", "madlad", "de_tr_direct", "auto_offline"),
                        default="argos")
    parser.add_argument("--apply", action="store_true", help="Write only a new isolated preview AI file")
    parser.add_argument("--confirm-preview-only", action="store_true",
                        help="Explicit consent to create preview-only references")
    args = parser.parse_args(argv)
    try:
        settings = plan(model_path=args.model_path, model_dir=args.model_dir,
                        backend=args.backend, translator=args.translator)
        if args.apply:
            if not args.confirm_preview_only:
                raise CompatibilityError("Use --apply --confirm-preview-only for explicit consent")
            apply_to_new_preview(settings)
            print("Preview-only model references saved; ASR and translation remain OFF.")
        else:
            print("PLAN ONLY: specified paths exist (metadata). No files written.")
        print("No legacy settings read; no models copied, loaded or downloaded.")
        print("Runtime/model inference and language pairs remain UNVERIFIED (release HOLD).")
        return 0
    except (CompatibilityError, OSError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
