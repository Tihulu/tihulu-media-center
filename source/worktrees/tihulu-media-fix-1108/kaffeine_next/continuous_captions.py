# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded real DVB capture queue with contiguous clips, overlap, and telemetry.

Inference may be slower than broadcast. Unlike the old 'busy => drop 4s'
logic, each chunk is placed in FIFO and processed in chronological order.
The memory cap is explicit; sustained CPU overload eventually exceeds
finite resources and is reported rather than silently inventing captions.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class CapturedClip:
    data: bytes
    options: dict
    started: float
    ended: float

    @property
    def bytes(self):
        return len(self.data)


class BufferedCaptionQueue:
    def __init__(self, maximum_bytes=96*1024*1024, max_clips=24):
        if maximum_bytes <= 0 or max_clips <= 0:
            raise ValueError("Invalid capture queue limits")
        self.limit = int(maximum_bytes)
        self.max_clips = int(max_clips)
        self.items = deque()
        self.bytes = 0
        self.overflow_seconds = 0.0
        self.overflow_count = 0
        self.cv = threading.Condition()
        self.closed = False

    def offer(self, clip: CapturedClip):
        if not isinstance(clip, CapturedClip):
            raise TypeError("Expected captured DVB TS clip")
        with self.cv:
            if self.closed:
                return False
            if (clip.bytes > self.limit or len(self.items) >= self.max_clips or
                    self.bytes + clip.bytes > self.limit):
                self.overflow_count += 1
                self.overflow_seconds += max(0.0, clip.ended-clip.started)
                return False
            self.items.append(clip)
            self.bytes += clip.bytes
            self.cv.notify()
            return True

    def get(self, timeout=None):
        with self.cv:
            if not self.items and not self.closed:
                self.cv.wait(timeout)
            if not self.items:
                return None
            clip = self.items.popleft()
            self.bytes -= clip.bytes
            return clip

    def clear(self):
        with self.cv:
            self.items.clear()
            self.bytes = 0

    def close(self):
        with self.cv:
            self.closed = True
            self.items.clear()
            self.bytes = 0
            self.cv.notify_all()

    def snapshot(self):
        with self.cv:
            return {"queued_clips": len(self.items), "queued_mib": round(self.bytes/1048576,1),
                    "missed_seconds": round(self.overflow_seconds,1),
                    "overflows":self.overflow_count, "queue_cap_mib":round(self.limit/1048576)}


def estimate_overlap_seconds(previous: bytes, preceding_duration: float,
                             overlap_seconds=0.75, cap_bytes=1024*1024) -> float:
    """Actual TS pre-roll seconds, using the very same packet cap as capture.

    The old code always subtracted one second even when the 1 MiB cap
    included much less at high DVB rates. This moved source word cues
    too early relative to delayed video.
    """
    if not previous or preceding_duration <= 0:
        return 0.0
    packets = int(min(len(previous)/max(0.2,preceding_duration)*overlap_seconds,
                      cap_bytes) // 188)
    if packets <= 0:
        return 0.0
    return min(float(preceding_duration),
               packets*188*float(preceding_duration)/len(previous))


def prepended_overlap(current: bytes, previous: bytes, preceding_duration: float,
                       overlap_seconds=0.75, cap_bytes=1024*1024) -> bytes:
    """Carry a short packet-aligned previous tail across speech boundaries.

    This covers words cut between chunks without hallucinating time samples.
    The separate text-level de-duplicator removes repeat words when they occur.
    """
    if not previous or not current or preceding_duration <= 0:
        return current
    packets = int(min(len(previous)/max(0.2, preceding_duration)*overlap_seconds,
                      cap_bytes) // 188)
    if packets <= 0:
        return current
    return previous[-packets*188:]+current


def _words(text):
    return [w for w in text.split() if w]


def _normalized_word(word: str) -> str:
    """Compare case/punctuation-insensitive ASR word boundaries."""
    import re
    return re.sub(r"^[^\w]+|[^\w]+$", "", word, flags=re.UNICODE).casefold()


def remove_repeated_prefix(previous: str, current: str, maximum_words=64,
                           minimum_words=1) -> str:
    """Trim ONLY a matching suffix/prefix from adjacent overlapping clips.

    The earlier 16-word limit missed repeating long sentences from Whisper.
    Sentence assembly uses a larger minimum to preserve genuinely repeated
    short expressions; no fuzzy matching or guessing missing speech.
    """
    if not isinstance(previous, str) or not isinstance(current, str):
        raise TypeError("Transcription overlap expects strings")
    if not isinstance(maximum_words, int) or maximum_words < 1:
        raise ValueError("Invalid transcription overlap word limit")
    if not isinstance(minimum_words, int) or not 1 <= minimum_words <= maximum_words:
        raise ValueError("Invalid transcription overlap minimum")
    before = _words(previous)
    now = _words(current)
    if not before or not now:
        return current.strip()
    old_normalized = [_normalized_word(w) for w in before]
    new_normalized = [_normalized_word(w) for w in now]
    for n in range(min(maximum_words, len(before), len(now)),
                   minimum_words-1, -1):
        if old_normalized[-n:] == new_normalized[:n] and all(old_normalized[-n:]):
            if n == 1 and len(now) > 2:
                continue
            return " ".join(now[n:]).strip()
    return current.strip()


def collapse_asr_repetition_loops(text: str, *, enabled=True) -> str:
    """Suppress obvious contiguous ASR loops, not normal doubled speech.

    Only patterns repeated 3+ times (3+ words), 4+ times (2 words), or
    6+ times (one word) are collapsed. Preserve an original instance
    (two for single-word emphasis). Do NOT use for real broadcaster subtitles,
    song lyrics, or to rewrite genuine spoken twofold repetition.
    """
    if not isinstance(text, str):
        raise TypeError("Expected an ASR transcript")
    if not enabled or not text.strip():
        return text.strip()
    words = text.split()
    if len(words) < 6:
        return " ".join(words)
    norm = [_normalized_word(w) for w in words]
    out = []
    i = 0
    while i < len(words):
        best_block = 0
        copies = 0
        # Prefer the smallest repeated unit, otherwise 18 identical words
        # may appear as three copies of a six-word block and only shrink
        # from 18 to six, rather than the intended two-word emphasis.
        for block in range(1, min(48, (len(words)-i)//3) + 1):
            threshold = 6 if block == 1 else 4 if block == 2 else 3
            if i + block * threshold > len(words):
                continue
            pattern = norm[i:i+block]
            if not all(pattern):
                continue
            repeats = 1
            while (i + (repeats+1)*block <= len(words) and
                   norm[i+repeats*block:i+(repeats+1)*block] == pattern):
                repeats += 1
            if repeats >= threshold:
                best_block, copies = block, repeats
                break
        if copies:
            retained = 2 if best_block == 1 else 1
            out.extend(words[i:i+best_block*retained])
            i += best_block * copies
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)
