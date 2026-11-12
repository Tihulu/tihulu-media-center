"""Fail-safe, time-bounded live-TV translation selection.

NLLB is optional and may be unusable despite model files existing (e.g.
unmaterialized PyTorch meta parameters). A broken translator must not block
new broadcast captions every six seconds or silently invent translations.
After an actual NLLB failure, try a genuinely installed Argos language pack.
Retry NLLB only after a cooldown or user restart; never download at runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class TranslationOutcome:
    text: str | None
    error: str | None = None
    warning: str | None = None
    engine: str | None = None


class TranslationFailover:
    def __init__(self, *, retry_seconds=180, clock=None):
        self._clock = clock or time.monotonic
        self._retry_seconds = float(retry_seconds)
        self._lock = threading.Lock()
        self._blocked_until = 0.0
        self._last_reason = ""

    def reset(self):
        with self._lock:
            self._blocked_until = 0.0
            self._last_reason = ""

    def translate(self, text, source, target, *, preferred, nllb, argos):
        if preferred not in ("nllb", "argos"):
            return TranslationOutcome(None, "Unsupported translator engine")
        if source == target:
            return TranslationOutcome(text, engine="original")
        nllb_issue = None
        if preferred == "nllb":
            with self._lock:
                now = self._clock()
                blocked = now < self._blocked_until
                if blocked:
                    nllb_issue = self._last_reason or "NLLB previously failed"
            if not blocked:
                try:
                    translated = nllb(text, source, target)
                    if not isinstance(translated, str) or not translated.strip():
                        raise RuntimeError("NLLB returned no translation")
                    self.reset()
                    return TranslationOutcome(translated.strip(), engine="nllb")
                except (RuntimeError, ValueError, OSError, TimeoutError,
                        ImportError, NotImplementedError) as exc:
                    # The warning stays in diagnostics, NEVER subtitle text.
                    nllb_issue = str(exc)[:180]
                    with self._lock:
                        self._last_reason = nllb_issue
                        self._blocked_until = self._clock() + self._retry_seconds
        try:
            translated = argos(text, source, target)
            if not isinstance(translated, str) or not translated.strip():
                raise RuntimeError("Argos returned no translation")
            return TranslationOutcome(
                translated.strip(),
                warning="NLLB failed; switched to installed Argos pack"
                        if nllb_issue is not None else None,
                engine="argos-fallback" if nllb_issue is not None else "argos",
            )
        except (RuntimeError, ValueError, OSError, TimeoutError, ImportError,
                KeyError, NotImplementedError) as exc:
            if nllb_issue is not None:
                return TranslationOutcome(
                    None,
                    "NLLB unavailable; no compatible Argos language pack for " +
                    source.upper() + " → " + target.upper() +
                    ". Open AI Model Market.")
            return TranslationOutcome(
                None, "Argos language pack unavailable for " +
                      source.upper() + " → " + target.upper() +
                      ". Open AI Model Market.")


_live_failover = TranslationFailover()


def live_failover():
    return _live_failover
