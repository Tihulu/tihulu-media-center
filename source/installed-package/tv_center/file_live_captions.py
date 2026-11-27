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
from dataclasses import replace

from .ai_settings import AISettings
from .captions import _speaker_details
from .lyrics_sync import LyricCue
from .media_ai import (validate_local_media, _choose_model, _chunk_cues,
                       _translate_cues, _near_silent_pcm)
from .speech_focus import ffmpeg_audio_filter


READING_MODES = {"fast": (7, 2.7), "comfort": (10, 3.5), "relaxed": (14, 4.8)}


def _reading_cues(cues, pcm, position, duration, detection, reading, speaker_provider):
    words = detection.get("asr_words") or []
    # Do not claim a specific speaker for a CPU transcript that has no
    # word-level timing. A missing model or ambiguous cluster is non-fatal.
    notes = []
    details = {}
    if speaker_provider != "off" and cues:
        if words:
            _speaker_details(pcm, cues[0].text, details, True, provider=speaker_provider)
            if details.get("speaker_error"):
                notes.append("Speaker detection unavailable: " + details["speaker_error"])
        else:
            notes.append("Speaker labels need a speech backend with word timestamps.")
    if not cues or not words:
        return cues, {}, notes
    from kaffeine_next.word_cues import word_groups
    maximum_words, maximum_span = READING_MODES[reading]
    groups = word_groups({"source":"local_asr", "words":words,
                          "speaker_turns":details.get("speaker_turns", [])},
                         maximum_words=maximum_words, maximum_span=maximum_span)
    if not groups:
        return cues, {}, notes
    paced, labels = [], {}
    for start, end, item in groups:
        if start >= duration:
            continue
        paced.append(LyricCue(position+start, position+min(end,duration),
                              item["original"], "Whisper/CUDA", cues[0].language))
        if item.get("speaker_label"):
            labels[len(paced)] = item["speaker_label"]
    return (paced, labels, notes) if paced else (cues, {}, notes)


def _reading_end(cue, text, limit, mode):
    """Extend reading into gaps, never past the next cue or decoded audio."""
    if mode == "fast":
        return min(cue.end, limit)
    rate, minimum, maximum = (16, 1.8, 5) if mode == "comfort" else (12, 2.5, 7)
    hold = min(maximum, max(minimum, .65 + len(text)/rate))
    return min(limit, max(cue.end, cue.start+hold))


def caption_window(media, position, *, source, targets, profile, backend,
                   music=False, translations_only=False, window=8, reading="fast",
                   speaker_provider="off", speech_priority=False):
    if not math.isfinite(position) or not 0 <= position <= 21600:
        raise ValueError("Playback position outside the six-hour caption limit")
    if not 2 <= window <= 20:
        raise ValueError("Playback buffer must be 2–20 seconds")
    focus_filter = ffmpeg_audio_filter(speech_priority=speech_priority,
                                       music_transcription=music)
    decoded = subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-ss", str(position), "-i", str(media), "-t", str(window), "-map", "0:a:0",
        "-vn", "-ac", "1", "-ar", "32000", *focus_filter, "-f", "s16le", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=35, check=False)
    if decoded.returncode:
        raise RuntimeError("Cannot decode this local audio window")
    pcm = decoded.stdout
    duration = len(pcm) / 64000.
    detection = {}
    cues = [] if _near_silent_pcm(pcm) else _chunk_cues(
        pcm, position=position, lang=source, profile=profile,
        backend=backend, music=music, detection=detection,
        speech_priority=speech_priority)
    if len(cues) == 1 and cues[0].provenance == "Whisper chunk / not word-aligned":
        cues = [replace(cues[0], end=position+duration)]
    labels, notes = {}, []
    if reading != "fast" or speaker_provider != "off":
        cues, labels, notes = _reading_cues(cues, pcm, position, duration,
                                           detection, reading, speaker_provider)
    translated, warnings = _translate_cues(cues, targets, source)
    rows = []
    for i, cue in enumerate(cues, 1):
        translation = translated.get(i, "")
        # Preserve genuine source text when a requested translation failed.
        text = translation if translations_only and translation else cue.text
        if translation and not translations_only:
            text += "\n" + translation
        if i in labels:
            text = labels[i] + " " + text
        limit = min(position+duration, cues[i].start if i < len(cues) else position+duration)
        end = _reading_end(cue, text, limit, reading)
        if round(end*1000) > round(cue.start*1000):
            rows.append({"start": round(cue.start * 1000),
                         "end": round(end * 1000), "text": text})
    return {"cues": rows, "end": round((position + duration) * 1000),
            "eof": duration < .1,
            "warning": " · ".join(notes + [warnings[0]["warning"]] if warnings else notes)}


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
                window=options.window or 8, reading=options.reading,
                speaker_provider=options.speaker_provider,
                speech_priority=options.speech_priority)
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
