# SPDX-License-Identifier: GPL-2.0-or-later
"""Position-driven local-file captions; shares ASR/translators, never controls playback.

One bounded request is accepted at a time. The player supplies a revision on
seek; stale replies are discarded by the player. No temporary audio or automatic
transcript archive is written. Child processes belong to the native AI job group.
"""
import json
import math
import subprocess
import sys
from .ai_settings import AISettings
from .media_ai import (validate_local_media, _choose_model, _chunk_cues,
                       _translate_cues, _near_silent_pcm)


def caption_window(media, position, *, source, targets, profile, backend,
                   music=False, translations_only=False, window=8):
    if not math.isfinite(position) or not 0 <= position <= 21600:
        raise ValueError("Playback position outside the six-hour caption limit")
    decoded = subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-ss", str(position), "-i", str(media), "-t", "8", "-map", "0:a:0",
        "-vn", "-ac", "1", "-ar", "32000", "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=35, check=False)
    if decoded.returncode:
        raise RuntimeError("Cannot decode this local audio window")
    pcm = decoded.stdout
    duration = len(pcm) / 64000.
    cues = [] if _near_silent_pcm(pcm) else _chunk_cues(
        pcm, position=position, lang=source, profile=profile,
        backend=backend, music=music)
    translated, warnings = _translate_cues(cues, targets, source)
    rows = []
    for i, cue in enumerate(cues, 1):
        translation = translated.get(i, "")
        # Preserve genuine source text when a requested translation failed.
        text = translation if translations_only and translation else cue.text
        if translation and not translations_only:
            text += "\n" + translation
        rows.append({"start": round(cue.start * 1000),
                     "end": round(cue.end * 1000), "text": text})
    return {"cues": rows, "end": round((position + duration) * 1000),
            "eof": duration < .1,
            "warning": warnings[0]["warning"] if warnings else ""}


def release_accelerator_cache():
    """Drop cached CUDA blocks after a finished batch without touching playback.

    Only an explicit cache release; the loaded model itself stays resident for
    the next request so we never pay the multi-second load time twice.
    """
    try:
        import torch
    except ImportError:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except (RuntimeError, ValueError):
        pass


def serve(options, input_stream=None, output_stream=None):
    media = validate_local_media(options.input)
    ai = AISettings()
    ai.configure_environment()
    if not ai.values["asr_enabled"]:
        raise RuntimeError("Enable the installed speech model in AI Market first")
    from .language_codes import language_code
    source = "auto" if options.source == "auto" else language_code(options.source)
    targets = tuple(dict.fromkeys(language_code(x.strip(), nllb=True)
                    for x in options.targets.split(",") if x.strip()))
    if len(targets) > 6:
        raise ValueError("Choose up to six output languages")
    if targets and ai.values["translation_model"] == "deepl":
        raise ValueError("Choose an offline translator in AI Market for local live captions")
    profile, backend = _choose_model(ai, options.record_model or "configured", options.whisper_file)
    inp, out = input_stream or sys.stdin, output_stream or sys.stdout
    while True:
        line = inp.readline(4097)
        if not line:
            return 0
        if len(line) > 4096:
            raise ValueError("Oversized playback position request")
        revision = -1
        try:
            request = json.loads(line)
            revision = int(request["revision"])
            result = caption_window(media, float(request["position"]),
                source=source, targets=targets, profile=profile,
                backend=backend, music=options.music,
                translations_only=options.translations_only,
                window=options.window or 8)
        except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            result = {"error": str(exc)[:240]}
        result["revision"] = revision
        print(json.dumps(result, ensure_ascii=False), file=out, flush=True)
        release_accelerator_cache()


def prune_private_caches(max_age_days=14, max_files=200):
    """Remove our own stale generated SRT/JSON sidecars, never user files.

    Only files this application created inside the private subtitle cache are
    considered; a user's own .srt beside their media is never touched.
    """
    import time
    from pathlib import Path
    from .local_assets import existing_asset
    from PyQt5.QtCore import QStandardPaths
    app = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
    roots = [Path(app)] if app else []
    extra = Path.home() / ".local/share/TIHULU/tihulu-media-center"
    if extra.is_dir():
        roots.append(existing_asset(extra))
    cutoff = time.time() - max_age_days * 86400
    for root in roots:
        if not root.is_dir():
            continue
        ours = sorted((f for f in root.iterdir()
                       if f.is_file() and f.name.startswith("tihulu-file-")
                       and f.stat().st_mtime < cutoff),
                      key=lambda f: f.stat().st_mtime)
        for f in ours:
            try:
                f.unlink()
            except OSError:
                pass
