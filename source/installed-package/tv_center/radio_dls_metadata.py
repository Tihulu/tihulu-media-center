"""Conservative radio song identity, shared with native DAB Radio tab.

Service / programme labels identify the *station*, not a song.
Only broadcaster-supplied, paired song artist/title hints are eligible for
explicit opt-in lyrics queries. Hints are NOT acoustic verification.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

_PREFIX = re.compile(
    r"^(?:jetzt\s+on\s+air|now\s+(?:on\s+air|playing)|"
    r"jetzt\s+läuft|aktuell|şimdi\s+çalıyor|simdi\s+caliyor)\s*:\s*",
    re.I,
)
_EXTRA = re.compile(
    r"\s+(?:\[(?:live|radio\s+edit)\]|\((?:live|radio\s+edit)\))$", re.I
)
_SEP = re.compile(r"\s+[-–—]\s+")
_NAMED = re.compile(
    r"^(?:artist|interpret|künstler)\s*:\s*(.+?)\s*[|;]\s*"
    r"(?:title|titel|song|track)\s*:\s*(.+)$", re.I
)
_TRACK_FIRST = {
    "jetzt on air", "now on air", "now playing", "şimdi çalıyor",
    "simdi caliyor",
}


def _norm(part: str) -> str:
    plain = unicodedata.normalize("NFKD", part).casefold()
    return " ".join(re.findall(r"[^\W_]+", plain))


@dataclass(frozen=True)
class SongHint:
    artist: str
    title: str
    format: str

    @property
    def key(self) -> str:
        return _norm(self.artist) + "|" + _norm(self.title)


def _validated(artist: str, title: str, source: str,
               station: str = "") -> SongHint | None:
    artist = artist.strip(" :-")
    title = _EXTRA.sub("", title.strip(" :-")).strip()
    if not artist or not title or max(len(artist), len(title)) > 130:
        return None
    a, t, st = _norm(artist), _norm(title), _norm(station)
    if not a or not t or a == t or a.startswith("www ") or t.startswith("www "):
        return None
    if st and (
        a == st or t == st or a.startswith(st + " ") or t.startswith(st + " ")
        or (len(a) >= 4 and st.startswith(a + " "))
        or (len(t) >= 4 and st.startswith(t + " "))
    ):
        return None
    return SongHint(artist, title, source)


def parse_dls_song(text: str, station: str = "") -> SongHint | None:
    """Extract songs from actual dynamic radio text, never raw service labels."""
    if not isinstance(text, str) or not 5 <= len(text) <= 330:
        return None
    text = " ".join(text.strip().split())
    if "::" in text:
        fields = [piece.strip(" :-") for piece in text.split("::")]
        if len(fields) >= 3 and fields[0].casefold() in _TRACK_FIRST:
            return _validated(fields[2], fields[1], "DLS track-first", station)
        return None
    text = _PREFIX.sub("", text)
    named = _NAMED.match(text)
    if named:
        return _validated(named[1], named[2], "DLS named fields", station)
    parts = _SEP.split(text, maxsplit=1)
    if len(parts) == 2:
        return _validated(parts[0], parts[1], "DLS artist-first", station)
    return None


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict) and isinstance(value.get("label"), str):
        return value["label"].strip()
    return ""


def _field(item: dict, *names: str) -> str:
    for name in names:
        text = _text(item.get(name))
        if text:
            return text
    return ""


def _pair(item: Any, source: str, station: str) -> SongHint | None:
    if not isinstance(item, dict):
        return None
    artist = _field(
        item, "artist", "item_artist", "itemArtist", "item.artist",
        "performer", "song_artist", "track_artist"
    )
    title = _field(
        item, "title", "item_title", "itemTitle", "item.title",
        "trackTitle", "song_title", "track_title"
    )
    nested = item.get("item")
    if isinstance(nested, dict):
        artist = artist or _field(nested, "artist", "performer")
        title = title or _field(nested, "title", "track")
    return _validated(artist, title, source, station)


def parse_service_song(service: dict) -> SongHint | None:
    """Prefer typed song data; fall back to DLS/RadioText only when convincing.

    Receiver-specific fields are optional; upstream welle-cli commonly exposes
    only dls.label. No inference from station label, programme, MOT or image.
    """
    if not isinstance(service, dict):
        return None
    station = _text(service.get("label"))
    dls = service.get("dls")
    dls = dls if isinstance(dls, dict) else {}
    sources = (
        ("Now playing", service.get("now_playing")),
        ("Now playing", service.get("nowPlaying")),
        ("Track tags", service.get("song")),
        ("Track tags", service.get("track")),
        ("DLS+", service.get("dlplus")),
        ("DLS+", service.get("dl_plus")),
        ("DLS+", dls.get("dlplus")),
        ("DLS+", dls.get("dl_plus")),
        ("DLS", dls),
        ("RDS RadioText+", service.get("rtplus")),
        ("Radio metadata", service.get("metadata")),
        ("Radio info", service.get("radio_info")),
        ("Track fields", service),
    )
    for source, obj in sources:
        song = _pair(obj, source, station)
        if song is not None:
            return song

    for obj in (dls, service, dls.get("dlplus"), dls.get("dl_plus"),
                service.get("dlplus"), service.get("rtplus")):
        if not isinstance(obj, dict) or not isinstance(obj.get("tags"), list):
            continue
        artist = title = ""
        for tag in obj["tags"]:
            if not isinstance(tag, dict):
                continue
            kind = _field(tag, "type", "tag", "name").casefold()
            value = _field(tag, "text", "value", "label")
            if kind.endswith("artist"):
                artist = value
            elif kind.endswith("title"):
                title = value
        song = _validated(artist, title, "DL+/RT+ tags", station)
        if song is not None:
            return song

    for value in (
        dls.get("label"), dls.get("text"),
        service.get("radiotext"), service.get("radio_text"),
        service.get("radioText"), service.get("dls"), service.get("now_playing"),
    ):
        song = parse_dls_song(_text(value), station=station)
        if song is not None:
            return song
    return None
