"""Conservative radio auto-language lock for intermittent music and dialogue.

Whisper's short music/mixed-audio windows can report a different language or
no detection at all. Preserve a previously verified source language until a
different source is corroborated; never treat DAB DLS metadata as language.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RadioLanguageDecision:
    language: str | None
    pending: bool
    reason: str
    confidence: float
    locked: bool


class RadioLanguageLock:
    """High-confidence initial lock, two-window confirmation for weaker speech.

    An initial >= 0.92 confidence language is usable immediately; an initial
    0.72–0.92 confidence candidate requires two consecutive observations.
    A source switch always takes two strong matching observations. A single
    musical false positive must not make an already-verified language vanish.
    """

    def __init__(self):
        self.language: str | None = None
        self.candidate: str | None = None
        self.candidate_runs = 0

    def observe(self, detected: str | None, confidence: float) -> RadioLanguageDecision:
        if not isinstance(detected, str) or not (
            2 <= len(detected) <= 3 and detected.isalpha()):
            detected = None
        else:
            detected = detected.lower()
            if detected in ("und", "auto"):
                detected = None
        try:
            probability = float(confidence)
        except (ValueError, TypeError, OverflowError):
            probability = 0.
        if not 0. <= probability <= 1.:
            probability = 0.
        if detected is None or probability < 0.72:
            self.candidate = None
            self.candidate_runs = 0
            return RadioLanguageDecision(
                self.language, self.language is None,
                "waiting_for_reliable_whisper_language" if self.language is None
                else "retained_confirmed_language_during_music",
                probability, self.language is not None)
        if detected == self.language:
            self.candidate = None
            self.candidate_runs = 0
            return RadioLanguageDecision(self.language, False,
                                         "confirmed_language", probability, True)
        if detected == self.candidate:
            self.candidate_runs += 1
        else:
            self.candidate = detected
            self.candidate_runs = 1
        if self.language is None and probability >= 0.92:
            self.language = detected
            self.candidate = None
            self.candidate_runs = 0
            return RadioLanguageDecision(detected, False,
                                         "strong_initial_language", probability, True)
        if self.candidate_runs >= 2:
            self.language = detected
            self.candidate = None
            self.candidate_runs = 0
            return RadioLanguageDecision(detected, False,
                                         "confirmed_two_matching_windows",
                                         probability, True)
        return RadioLanguageDecision(
            self.language, self.language is None,
            "initial_language_confirmation_pending" if self.language is None
            else "retained_confirmed_language_while_switch_is_unverified",
            probability, self.language is not None)
