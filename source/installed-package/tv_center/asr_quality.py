# SPDX-License-Identifier: GPL-2.0-or-later
"""Conservative post-decode quality gate for optional live-TV Whisper captions.

Do not turn music, silence, corrupted RF audio or short low-confidence guesses
into translated subtitles. Real words with credible confidence still pass.
This only filters model output and does not edit the broadcast transport.
"""
from __future__ import annotations
import re


def _number(field, value, default):
    try:
        return float(value if value is not None else default)
    except (ValueError, TypeError, OverflowError):
        return default


def accepted_whisper_segments(
    segments, *, source_language="auto", detected_probability=None,
    music_mode=False, speech_priority=False,
):
    """Return (accepted segments, suppression reason or None).

    Whisper confidence is heuristic, not a certainty of transcription.
    Short captions are rejected only with additional measurable concerns.
    """
    if source_language == "auto" and detected_probability is not None:
        confidence = _number("lang", detected_probability, 0.0)
        if confidence < 0.50:
            return [], "uncertain_auto_detect_language"

    accepted = []
    reasons = []
    for segment in segments:
        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        tokens = text.split()
        no_speech = _number("no_speech", getattr(segment, "no_speech_prob", 0.), 0.)
        logprob = _number("logprob", getattr(segment, "avg_logprob", 0.), 0.)
        compression = _number("compression", getattr(segment, "compression_ratio", 0.), 0.)
        start = _number("start", getattr(segment, "start", 0.), 0.)
        end = _number("end", getattr(segment, "end", start), start)
        duration = max(0., end - start)
        reason = None
        # Accompaniment increases the measured no-speech probability even
        # when a real human is talking. Do not open the floodgates for
        # music-only clips: require sustained, confidently decoded words
        # before exempting a mixed-audio phrase from the normal VAD gate.
        confident_mixed_dialogue = (
            speech_priority and not music_mode and
            len(tokens) >= 4 and duration >= 1.2 and
            no_speech < 0.78 and logprob >= -0.38 and
            compression <= 2.5)
        silence_limit = (0.87 if music_mode else 0.65)
        if (no_speech >= silence_limit and not confident_mixed_dialogue) or (
                not music_mode and no_speech >= 0.43
                and logprob < -0.35):
            reason = "probable_silence_or_background_audio"
        elif logprob < -1.0:
            reason = "low_ASR_confidence"
        elif compression > 2.8:
            reason = "repetitive_ASR_hallucination"
        elif (not music_mode and len(tokens) <= 3 and duration < 1.1
              and (no_speech > 0.18 or logprob < -0.40)
              and not (speech_priority and duration >= 0.65
                       and no_speech < 0.48 and logprob >= -0.18)):
            reason = "unverified_short_phrase"
        elif (not music_mode and len(tokens) <= 3
              and sum(c.isdigit() for c in text) >= 2
              and (no_speech > 0.12 or logprob < -0.35
                   or duration < 1.3)):
            # Broadcast logos, clipped years and jingles are common
            # hallucination patterns. An explicit long, confident spoken
            # year may still pass.
            reason = "unverified_short_numeric_phrase"
        if reason:
            reasons.append(reason)
        else:
            accepted.append(segment)
    return accepted, (None if accepted else
                      reasons[0] if reasons else "no_speech_detected")


# Some DVB test pages/jingles and Whisper loop errors emit the title
# T E S T S E I T E letter by letter before genuine German dialogue.
# Remove ONLY that distinctive spelled-out prefix, not the spoken word
# "Testseite" in an ordinary sentence. No generic upper-case filters.
_SPELLED_TESTSEITE = re.compile(
    r"^\s*T[\s.\-]+E[\s.\-]+S[\s.\-]+T[\s.\-]+"
    r"S[\s.\-]+E[\s.\-]+I[\s.\-]+T[\s.\-]+E"
    r"(?=\s|[,.!?;:\u2013\u2014]|$)[\s,.:;!\?\-\u2013\u2014]*",
    re.IGNORECASE)
_TEST_PAGE_ONLY = re.compile(
    r"^\s*(?:testseite|t[\s.\-]+e[\s.\-]+s[\s.\-]+t"
    r"[\s.\-]+s[\s.\-]+e[\s.\-]+i[\s.\-]+t[\s.\-]+e)"
    r"\s*[:.\-]?\s*$", re.IGNORECASE)


def strip_test_page_artifact(text, *, broadcaster=False):
    """Return (clean text, removed). Preserve real dialogue after the marker.

    An isolated broadcaster test-page title is not subtitle speech. For ASR,
    suppress only the unnatural nine-letter spelled prefix. Never strip an
    ordinary "Testseite" word out of a genuine spoken German sentence.
    """
    if not isinstance(text,str) or not text:
        return text, False
    if broadcaster and _TEST_PAGE_ONLY.fullmatch(text):
        return "", True
    cleaned, removed = _SPELLED_TESTSEITE.subn("",text,count=1)
    return (cleaned.strip(),True) if removed else (text,False)
