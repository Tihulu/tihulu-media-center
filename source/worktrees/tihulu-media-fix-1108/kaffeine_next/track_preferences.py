"""Make automatic DVB subtitle/audio selection match real broadcast descriptors.

Never fabricate source-language tags and never guess among multiple
incompatible tracks. When there is exactly one broadcaster-signalled
language, choose it rather than treating the selected playback language
as an arbitrary 'German' default.
"""
from __future__ import annotations

from tv_center.language_codes import language_code


def _signaled_language(track):
    if not isinstance(track,dict):
        return None
    raw = track.get("source_hint") or track.get("language")
    if not isinstance(raw,str) or raw.lower() in ("", "und", "unknown"):
        return None
    try:
        return language_code(raw)
    except ValueError:
        return None


def recommended_track(tracks, preferred, *, kind="teletext"):
    """Choose only a broadcaster-labelled, unambiguous language and PID."""
    if kind not in ("teletext","audio") or not isinstance(tracks,(list,tuple)):
        return None
    checked=[]
    for track in tracks[:30]:
        if not isinstance(track,dict):
            continue
        if type(track.get("pid")) is not int or not 1 <= track["pid"] <= 8190:
            continue
        if kind=="teletext" and (
                type(track.get("page")) is not int or
                not 100 <= track["page"] <= 899):
            continue
        lang=_signaled_language(track)
        if lang:
            checked.append((track,lang))
    if not checked:
        return None
    try:
        source=language_code(preferred)
    except ValueError:
        source=None
    matches=[entry for entry in checked if entry[1]==source]
    # A clear matching source is preferred. Otherwise accept ONE and only
    # ONE language-signalled track; multilingual ambiguity stays manual.
    if len(matches)==1:
        return matches[0][0]
    if len(checked)==1:
        return checked[0][0]
    return None
