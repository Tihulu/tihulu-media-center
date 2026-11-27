# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit release of optional local AI workers after a stop.

Only stops resident workers and frees accelerator caches. Settings, installed
models and TV/radio playback are untouched; starting subtitles again loads
what it needs on demand. Used by player Stop in every mode, so idle Whisper or
translator processes never keep VRAM/RAM busy.
"""
from __future__ import annotations


def release_local_ai() -> list[str]:
    released = []
    try:
        from .translation_service import _service, _argos_service, _madlad_service
    except ImportError:
        _service = _argos_service = _madlad_service = ()
    for service in (_service, _argos_service, _madlad_service):
        try:
            service.close()
            released.append(type(service).__name__)
        except (OSError, RuntimeError, ValueError):
            continue
    try:
        from .cuda_faster_whisper import _worker
        _worker.close()
        released.append("faster-whisper")
    except (ImportError, OSError, RuntimeError, ValueError):
        pass
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            released.append("cuda-cache")
    except (ImportError, RuntimeError, ValueError):
        pass
    return released
