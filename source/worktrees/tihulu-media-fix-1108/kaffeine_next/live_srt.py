# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional local DVB subtitle-session recorder.

Writes only finished, actually displayed captions as SRT sidecars. The
recorder does not touch the tuner, libVLC or any video/audio stream, and does
not claim that libVLC hot-reloads a growing SRT file for live television.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import re
import time


def srt_timestamp(seconds: float) -> str:
    """SRT HH:MM:SS,mmm format using nonnegative monotonic elapsed time."""
    ms = max(0, int(round(float(seconds) * 1000)))
    hours, rem = divmod(ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def subtitle_line(value) -> str:
    """Clean control characters without translating or inventing speech."""
    if not isinstance(value, str):
        return ""
    return "\n".join(" ".join(part.split()) for part in
                     value.replace("\r", "").split("\n")).strip()[:1200]


class LiveSRTRecorder:
    """Independent original/translation tracks saved inside a new session folder."""

    def __init__(self):
        self.folder: Path | None = None
        self.started_at: float | None = None
        self.files: dict[str, object] = {}
        self.previous_end: dict[str, float] = {}
        self.counts: dict[str, int] = {}

    @property
    def active(self) -> bool:
        return self.started_at is not None

    @property
    def paths(self) -> tuple[Path, ...]:
        if self.folder is None:
            return ()
        return tuple(self.folder / (name + ".srt") for name in self.files)

    def start(self, directory, name="live-TV", now=None) -> Path:
        if self.active:
            raise RuntimeError("Stop the current SRT recording first")
        parent = Path(directory).expanduser().resolve()
        if not parent.is_dir():
            raise ValueError("Select an existing local subtitle output folder")
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(name))[:50].strip("-") or "live-TV"
        stem = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + safe
        for suffix in range(1, 1000):
            folder = parent / (stem if suffix == 1 else stem + "-" + str(suffix))
            try:
                folder.mkdir(mode=0o700)
            except FileExistsError:
                continue
            self.folder = folder
            self.started_at = time.monotonic() if now is None else float(now)
            self.counts.clear()
            self.previous_end.clear()
            return folder
        raise FileExistsError("Cannot allocate a unique SRT session folder")

    def append(self, cue, config):
        if not self.active:
            return
        result = cue.get("result", {})
        if not isinstance(result, dict):
            return
        begin = max(0.0, float(cue["due"]) - self.started_at)
        finish = max(begin + 1.0, float(cue["expires"]) - self.started_at)
        captions: dict[str, str] = {}
        original = subtitle_line(result.get("original"))
        if original and config.show_original:
            captions["original"] = original
        translations = result.get("translations") or {}
        if config.show_translation and isinstance(translations, dict):
            for lang in config.target_languages:
                if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{1,19}", lang):
                    translated = subtitle_line(translations.get(lang))
                    if translated:
                        captions["translation-" + lang.lower()] = translated
        for track, line in captions.items():
            previous = self.previous_end.get(track, 0.0)
            start = max(begin, previous)
            end = max(start + 0.8, min(start + 8.0, finish))
            if track not in self.files:
                # Exclusive creation: never overwrite manually supplied subtitles.
                self.files[track] = (self.folder / (track + ".srt")).open(
                    "x", encoding="utf-8", newline="\n")
                self.counts[track] = 0
            fp = self.files[track]
            number = self.counts[track] + 1
            fp.write(f"{number}\n{srt_timestamp(start)} --> "
                     f"{srt_timestamp(end)}\n{line}\n\n")
            fp.flush()
            self.counts[track] = number
            self.previous_end[track] = end

    def stop(self) -> tuple[Path, ...]:
        paths = self.paths
        for fp in self.files.values():
            fp.close()
        self.files = {}
        self.started_at = None
        self.previous_end = {}
        self.counts = {}
        return paths
