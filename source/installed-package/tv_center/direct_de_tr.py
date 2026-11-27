"""Explicit direct German-to-Turkish offline translation route for TV/radio/media.

The starter Argos bundle installs DE->EN and EN->TR and Argos can pivot
through English, with possible meaning loss. When the owner chooses this
route, try installed direct multilingual translation models first.

Never download a model, never use Whisper Translate as an implicit English
pivot, never enable a cloud provider, and never claim model file presence
means inference worked. The return value records the *actual* engine.
"""
from __future__ import annotations

from .translation_failover import TranslationOutcome


def direct_de_tr_order(*, nllb_installed: bool, madlad_installed: bool):
    """Prefer a smaller live-friendly direct model; MADLAD remains optional.

    The user can explicitly select MADLAD in Model Market if they prefer its
    quality and can accommodate its higher GPU/latency cost.
    """
    return tuple(
        [name for name, ready in (
            ("nllb", nllb_installed), ("madlad", madlad_installed))
         if ready] + ["argos"])


def translate_de_tr_direct(text: str, *, available=None, translators=None):
    """Return an evidence-based TranslationOutcome for DE -> TR only.

    For real calls, installed markers are checked *without* downloads; each
    service itself validates runtime/model inference. Tests can inject
    availability and functions without loading weights or touching hardware.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 1600:
        return TranslationOutcome(None, "No complete DE→TR text to translate")

    if available is None:
        from .translation_market import TranslationModelMarket
        from .translation_madlad import MadladMarket
        try:
            nllb = bool(TranslationModelMarket().status()["installed"])
        except (OSError, ValueError, RuntimeError):
            nllb = False
        try:
            madlad = bool(MadladMarket().status()["installed"])
        except (OSError, ValueError, RuntimeError):
            madlad = False
        available = {"nllb": nllb, "madlad": madlad}

    order = direct_de_tr_order(
        nllb_installed=bool(available.get("nllb")),
        madlad_installed=bool(available.get("madlad")))
    if translators is None:
        # Imports are deferred until an actual translation request.
        from .translation_service import translate_nllb, translate_madlad
        from .captions import _translate_argos_local
        translators = {"nllb": translate_nllb, "madlad": translate_madlad,
                       "argos": _translate_argos_local}
    problems = []
    for name in order:
        if name not in translators:
            continue
        try:
            translated = translators[name](text, "de", "tr")
            if not isinstance(translated, str) or not translated.strip():
                raise RuntimeError("Empty translation")
            if name == "argos":
                warning = ("No successful direct DE→TR translator; "
                           "Argos fallback may pivot via English")
                return TranslationOutcome(
                    translated.strip(), warning=warning,
                    engine="argos-possible-en-pivot")
            warning = ("Previous DE→TR engine unavailable; used "+name.upper()
                       if problems else None)
            return TranslationOutcome(translated.strip(), warning=warning,
                                      engine=name+"-direct-de-tr")
        except (ValueError, RuntimeError, OSError, TimeoutError, ImportError,
                KeyError, NotImplementedError) as exc:
            problems.append(name+": "+type(exc).__name__)
    return TranslationOutcome(
        None, "Direct DE→TR unavailable; "+("; ".join(problems)[:180] or
            "no installed compatible offline translator")+
        ". Original German text kept.")
