"""Optional sound-event tags alongside, never instead of, actual subtitles.

Tags are based only on installed, opt-in acoustic classifier evidence. They
are display decorations applied AFTER ASR, sentence assembly and translation;
they never enter Whisper prompts, translation inputs or diarization. Unknown
or stale events stay hidden, preserving original speech.
"""
from __future__ import annotations

LABELS = {
    "en": {"music": "Music", "hum": "Humming", "applause": "Applause",
           "laughter": "Laughter", "noise": "Noise"},
    "de": {"music": "Musik", "hum": "Summen", "applause": "Applaus",
           "laughter": "Lachen", "noise": "Geräusch"},
    "tr": {"music": "Müzik", "hum": "Mırıldanma", "applause": "Alkış",
           "laughter": "Gülme", "noise": "Gürültü"},
    "fr": {"music": "Musique", "hum": "Fredonnement", "applause": "Applaudissements",
           "laughter": "Rires", "noise": "Bruit"},
}
VALID = frozenset(LABELS["en"])


def sound_prefix(events, language: str = "en") -> str:
    if not isinstance(events, list):
        return ""
    dictionary = LABELS.get(str(language or "en").lower(), LABELS["en"])
    names = []
    for row in events[:5]:
        if not isinstance(row, dict):
            continue
        kind, confidence = row.get("type"), row.get("confidence")
        if (kind not in VALID or
            type(confidence) not in (float, int) or
            not .80 <= confidence <= 1.0 or
            row.get("source") != "AST AudioSet" or kind in names):
            continue
        names.append(kind)
        if len(names) == 2:
            break
    return " ".join("[" + dictionary[kind] + "]" for kind in names)


def decorate_caption(text: str, events, language: str) -> str:
    """Never replace, truncate, translate or remove genuine recognized words."""
    if not isinstance(text, str):
        return ""
    prefix=sound_prefix(events, language)
    if not prefix:
        return text
    # This helper is used by native Radio as a display-only text:
    # the acoustic tag is a separate row, never the first spoken word.
    return prefix + ("\n" + text if text else "")


def decorate_result(result: dict, enabled: bool) -> dict:
    """Attach optional display-only acoustic lines, NEVER rewrite speech.

    Whisper original, translated text, source and measured word positions
    remain byte-for-byte unchanged. In particular an acoustic event alone
    must not masquerade as an ASR transcript or be submitted for translation.
    """
    if not isinstance(result, dict):
        raise ValueError("Expected caption result object")
    output=dict(result)
    if not enabled:
        return output
    events=result.get("sound_events") or []
    if not events:
        return output
    source_language=result.get("source_language") or "en"
    labels={"original":sound_prefix(events,source_language),
            "translations":{
                lang:sound_prefix(events,lang)
                for lang in (result.get("target_languages") or
                             tuple((result.get("translations") or {}).keys()))
                if sound_prefix(events,lang)}}
    if not labels["original"] and not labels["translations"]:
        return output
    output["sound_event_lines"]=labels
    output["sound_event_only"]=not bool(str(result.get("original") or "").strip())
    output["sound_labels_source"]="AST AudioSet · approximate clip"
    # Do not modify original, translations, translated, source, words,
    # or word_timing_source. Native render places labels on another line.
    return output
