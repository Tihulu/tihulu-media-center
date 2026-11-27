# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only discovery of an already installed local speech model.

Never downloads, never enables anything in the user's settings: only reports a
path the user already installed, so an explicitly requested caption session can
start instead of demanding a Market round-trip.
"""
from __future__ import annotations
from pathlib import Path


def installed_speech_model() -> str:
    from .ai_settings import AISettings
    from .local_assets import existing_asset
    settings = AISettings()
    chosen = settings.values.get("model_path")
    if chosen and Path(chosen).is_file():
        return chosen
    candidates = []
    try:
        from .cuda_faster_whisper import FasterWhisperCUDA
        if FasterWhisperCUDA().installed():
            return "__cuda_managed__"
    except (ImportError, OSError, RuntimeError, ValueError):
        pass
    root = settings.values.get("model_dir")
    folders = [Path(root)] if root else []
    folders.append(existing_asset(
        Path.home() / ".local/share/TIHULU/tihulu-media-center/models"))
    for folder in folders:
        if not folder.is_dir():
            continue
        for pattern in ("ggml*.bin", "*.bin"):
            for path in sorted(folder.rglob(pattern)):
                try:
                    if path.stat().st_size > 1024 * 1024:
                        candidates.insert(0, path)
                except OSError:
                    continue
    return str(candidates[0]) if candidates else ""
