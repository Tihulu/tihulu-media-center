"""Cross-process cache invalidation for owner-installed Argos language packs.

The Model Market and live-caption Argos worker use the same user-owned
virtual environment. An atomic generation marker lets the long-running
translator reload installed model metadata after installs/removals without
polling model packages or invoking Python during TV capture.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile

from .runtime import AIRuntime

MARKER_NAME = ".tihulu-argos-pack-generation"


def marker_path(root=None):
    return Path(root if root is not None else AIRuntime().root) / MARKER_NAME


def generation(root=None):
    """Return a cheap filesystem revision; zero import cost for Argos itself."""
    marker = marker_path(root)
    try:
        info = marker.stat()
        if not marker.is_file() or marker.is_symlink():
            return None
        return (info.st_ino, info.st_mtime_ns, info.st_size)
    except OSError:
        return None


def changed(root=None):
    """Atomic, owner-triggered marker update, never a model installation."""
    marker = marker_path(root)
    folder = marker.parent
    if not folder.is_dir() or folder.is_symlink():
        raise RuntimeError("Managed Argos runtime directory not installed")
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=folder, prefix=".argos-generation-", delete=False,
            mode="w", encoding="ascii"
        ) as stream:
            temp = Path(stream.name)
            stream.write(str(os.getpid()) + "\n")
        os.chmod(temp, 0o600)
        os.replace(temp, marker)
        return generation(root)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
