"""Explain missing DAB+ translations without inserting fabricated subtitle lines.

This status travels beside original text to the native radio UI. Actual
translation text remains under the per-language 'translations' dictionary.
"""
from __future__ import annotations


def translation_state(*, original: str, source_language: str | None,
                      requested_targets, translated: dict, failures: dict,
                      translator_enabled: bool,
                      language_pending: bool) -> dict:
    targets = tuple(dict.fromkeys(str(lang).lower() for lang in requested_targets))
    source = source_language or "und"
    non_source = tuple(lang for lang in targets if lang != source)
    rendered = {
        lang for lang in non_source
        if isinstance(translated.get(lang), str) and translated[lang].strip()
    }
    missing = [lang for lang in non_source if lang not in rendered]
    if not original.strip():
        state, message = "listening", "Waiting for audible speech or verified lyrics"
    elif not targets:
        state, message = "no_targets", "No translation output languages selected"
    elif not non_source:
        state, message = "original_only", (
            "Only original-language output requested; select a different target")
    elif not translator_enabled:
        state, message = "translator_disabled", (
            "Offline translation is disabled in AI Model Market")
    elif language_pending or source == "und":
        state, message = "language_pending", (
            "Waiting for reliable source language; choose English/German/etc. "
            "manually to translate without automatic language confirmation")
    elif not missing:
        state, message = "translated", "Translations available"
    elif rendered:
        state, message = "partial", (
            "Some target languages unavailable: " + ", ".join(missing).upper())
    elif failures:
        state, message = "failed", (
            "Translator could not produce " + ", ".join(missing).upper()
            + ": " + "; ".join(str(failures.get(lang) or "unavailable")[:110]
                           for lang in missing))
    else:
        state, message = "unavailable", (
            "No verified translation for " + ", ".join(missing).upper()
            + "; check language packs or translator model")
    return {"state": state, "message": message[:350],
            "missing_targets": missing,
            "pending_targets": (missing if state == "language_pending" else [])}
