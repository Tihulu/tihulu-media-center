"""Lyrics from opt-in online metadata or local LRC.

The client only requests LRCLIB with explicit opt-in. Plain lyrics are
allowed as *text*, not fabricated timestamps. Optional locally recognized
speech can provide approximate, evidence-based sequential line alignment;
unmatched lyrics remain hidden and are not given invented times.
"""
from __future__ import annotations

from dataclasses import dataclass
import bisect
import json
import os
from pathlib import Path
import re
import difflib
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request


_LRC_LINE = re.compile(r"^\[(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?\](.*)$")
_MAX_RECORD_BYTES = 2_000_000
_CLIENT = "TIHULU-Kaffeine/0.2 (+https://github.com/Tihulu/TIHULU-TEXT-CENTER)"


@dataclass(frozen=True)
class LyricCue:
    start: float
    end: float
    text: str
    provenance: str = "local"
    language: str | None = None


def parse_lrc(content: str, *, duration: float | None = None,
              provenance: str = "local") -> list[LyricCue]:
    """Parse synced LRC lines, including multiple leading time tags.

    Preserve order at equal timestamps and truncate pathological inputs.
    A lyric cue is shown only after its own timestamp; labels/metadata are
    ignored and are never mistaken for song lines.
    """
    if not isinstance(content, str) or len(content) > _MAX_RECORD_BYTES:
        raise ValueError("LRC content missing or exceeds safety limit")
    lines = []
    for line in content.splitlines()[:6000]:
        remainder = line.strip()
        stamps = []
        while True:
            match = _LRC_LINE.match(remainder)
            if not match:
                break
            mins, secs, fraction, rest = match.groups()
            if int(secs) >= 60:
                break
            decimal = (fraction or "0").ljust(3, "0")[:3]
            timestamp = 60 * int(mins) + int(secs) + int(decimal) / 1000
            stamps.append(timestamp)
            remainder = rest.strip()
        lyric = remainder.strip()
        if not stamps or not lyric:
            continue
        if lyric.startswith("[") and lyric.endswith("]"):
            continue
        if len(lyric) > 700:
            lyric = lyric[:700]
        for stamp in stamps:
            if 0 <= stamp <= 36000:
                lines.append((stamp, lyric))
    lines = sorted(set(lines), key=lambda item: item[0])[:1500]
    cues = []
    for i, (stamp, text) in enumerate(lines):
        following = lines[i+1][0] if i+1 < len(lines) else stamp + 5
        if duration is not None:
            following = min(following, float(duration))
        end = max(stamp + 0.1, min(stamp + 12, following))
        cues.append(LyricCue(stamp, end, text, provenance))
    return cues



_KARAOKE_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", flags=re.UNICODE)


def aligned_karaoke_word_anchors(
    lyric_line: str, observed_words: list[dict], *,
    capture_end_epoch_ms: int, window_seconds: float = 6.0,
) -> list[dict]:
    """Map actual GPU Whisper word timestamps onto an ASR-confirmed lyric line.

    This does NOT determine whether a lyric line was heard: callers must
    independently verify the whole line with LiveLyricMatcher first. Only
    exact, order-preserving ASR word evidence receives timing. Unmatched
    words, translations, CPU chunk cues and metadata never get fake times.
    Epochs use the PCM capture clock, NOT a measured speaker/DAC clock.
    """
    from difflib import SequenceMatcher
    import math

    if (not isinstance(lyric_line, str) or not 1 <= len(lyric_line) <= 240
            or not isinstance(observed_words, list)
            or type(capture_end_epoch_ms) is not int
            or capture_end_epoch_ms <= 0
            or type(window_seconds) not in (int, float)
            or not math.isfinite(window_seconds)
            or not 1 <= window_seconds <= 15):
        return []

    def key(text: str) -> str:
        return "".join(char for char in unicodedata.normalize(
            "NFKD", text).casefold()
            if char.isalnum() and not unicodedata.combining(char))

    lyric_tokens = [
        (match, key(match.group()))
        for match in list(_KARAOKE_WORD.finditer(lyric_line))[:90]
    ]
    lyric_tokens = [(span, text) for span, text in lyric_tokens if text]
    if len(lyric_tokens) < 2:
        return []

    heard = []
    for record in observed_words[:120]:
        if not isinstance(record, dict):
            continue
        word = record.get("text")
        start, end = record.get("start"), record.get("end")
        if (not isinstance(word, str) or len(word) > 100
                or len(_KARAOKE_WORD.findall(word)) != 1
                or type(start) not in (float, int)
                or type(end) not in (float, int)
                or not math.isfinite(start) or not math.isfinite(end)
                or not 0 <= start < end <= window_seconds + .5):
            continue
        normalized = key(word)
        if normalized:
            heard.append((normalized, float(start)))
    if len(heard) < 2:
        return []

    matches = SequenceMatcher(
        None, [word for _, word in lyric_tokens],
        [word for word, _ in heard], autojunk=False,
    ).get_matching_blocks()
    pairs = [(line_index + step, heard_index + step)
             for block in matches
             for line_index, heard_index, step in (
                 (block.a, block.b, offset)
                 for offset in range(block.size))]
    if (len(pairs) < 2 or len(pairs) / len(heard) < .4
            or len({heard[j][0] for _, j in pairs}) < 2):
        return []

    anchors = []
    last_epoch = -1
    for line_index, heard_index in pairs:
        match = lyric_tokens[line_index][0]
        epoch = capture_end_epoch_ms - round(
            (window_seconds - heard[heard_index][1]) * 1000)
        if epoch <= last_epoch:
            continue
        # Qt QString indices are UTF-16 code units (not Python codepoints).
        start_utf16 = len(lyric_line[:match.start()].encode("utf-16-le")) // 2
        end_utf16 = len(lyric_line[:match.end()].encode("utf-16-le")) // 2
        anchors.append({"start": start_utf16, "end": end_utf16,
                        "epoch_ms": epoch})
        last_epoch = epoch
    return anchors if len(anchors) >= 2 else []


def cue_at(cues: list[LyricCue], position: float) -> LyricCue | None:
    if not cues or position < 0:
        return None
    starts = [cue.start for cue in cues]
    i = bisect.bisect_right(starts, position) - 1
    return cues[i] if i >= 0 and position < cues[i].end else None


def local_lrc(media_path: str | Path) -> Path | None:
    target = Path(media_path).expanduser().resolve(strict=True)
    if not target.is_file():
        raise ValueError("Expected a local audio file")
    candidate = target.with_suffix(".lrc")
    if candidate.is_file() and not candidate.is_symlink() and (
            candidate.stat().st_size <= _MAX_RECORD_BYTES):
        return candidate
    return None


def _get_json(url: str, *, allow_list: bool=False):
    # No external redirect to other origins; do not send metadata to a
    # redirected host. This lookup is triggered only at user request.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request(
        url, headers={"User-Agent":_CLIENT, "Accept":"application/json"})
    try:
        with opener.open(request, timeout=8) as response:
            if response.status != 200:
                raise RuntimeError(f"Lyrics service HTTP {response.status}")
            data = response.read(_MAX_RECORD_BYTES + 1)
            if len(data) > _MAX_RECORD_BYTES:
                raise ValueError("Lyrics lookup response too large")
            record = json.loads(data)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        if exc.code == 429:
            raise RuntimeError(
                "Lyrics lookup rate-limited. Retry later; no automatic loop.") from exc
        raise RuntimeError(f"Lyrics lookup unavailable: HTTP {exc.code}") from exc
    if allow_list:
        if isinstance(record,list):
            return [item for item in record[:20] if isinstance(item,dict)]
        if not record:
            return []
        raise ValueError("Unexpected LRCLIB catalog search response")
    if not isinstance(record, dict):
        raise ValueError("Unexpected LRCLIB response")
    return record


def lookup_alternative_plain(*, artist: str, title: str,
                             online: bool=False) -> tuple[list[str],dict]:
    """Best-effort second provider for non-time-coded lyrics.

    lyrics.ovh returns only words, not a reliable artist/title identity or
    timestamps. NEVER present its text as a verified audio match until local
    Whisper independently recognizes the actual spoken/sung words.
    """
    if not online:
        raise PermissionError("Alternative lyrics lookup requires opt-in")
    if not isinstance(artist,str) or not isinstance(title,str) or (
            not artist.strip() or not title.strip() or
            len(artist)>160 or len(title)>160):
        raise ValueError("Valid artist/title required")
    url=("https://api.lyrics.ovh/v1/"+
         urllib.parse.quote(artist.strip(),safe="")+"/"+
         urllib.parse.quote(title.strip(),safe=""))
    try:
        result=_get_json(url)
    except (OSError,ValueError,RuntimeError,urllib.error.URLError):
        return [],{"status":"alternative_unavailable",
                  "provider":"lyrics.ovh"}
    raw=result.get("lyrics") if isinstance(result,dict) else None
    if not isinstance(raw,str):
        return [],{"status":"alternative_not_found","provider":"lyrics.ovh"}
    cleaned=[]
    for row in raw.splitlines()[:350]:
        line=" ".join(row.strip().split())
        if (3<=len(line)<=240 and
                not (line.startswith("[") and line.endswith("]"))):
            cleaned.append(line)
        if len(cleaned)>=150:
            break
    if not cleaned:
        return [],{"status":"alternative_empty","provider":"lyrics.ovh"}
    return cleaned,{"status":"plain","provider":"lyrics.ovh",
        "online_lookup":True,"alignment":"awaiting_real_audio_ASR",
        "metadata_verification":"none; exact artist/title request only"}


def _metadata_key(value: str) -> str:
    """Tolerate radio punctuation/Unicode differences, not different songs."""
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def _matches_record(record: dict, title: str, artist: str) -> bool:
    return (_metadata_key(record.get("trackName", "")) == _metadata_key(title)
            and _metadata_key(record.get("artistName", "")) == _metadata_key(artist))


def _clean_plain(raw: str) -> list[str]:
    if not isinstance(raw, str):
        return []
    cleaned = []
    for row in raw.splitlines()[:350]:
        line = " ".join(row.strip().split())
        if 3 <= len(line) <= 240 and not (
                line.startswith("[") and line.endswith("]")):
            cleaned.append(line)
        if len(cleaned) >= 150:
            break
    return cleaned


def lookup_musixmatch_licensed_plain(*, artist: str, title: str,
                                      online: bool = False) -> tuple[list[str], dict]:
    """Official licensed API only, never unofficial Android keys or scraping.

    A consumer's own contract must authorize use. The service may return
    only previews; reject those rather than misrepresenting partial lyrics.
    Un-timed text still must be independently matched to the heard audio.
    """
    if not online:
        raise PermissionError("Musixmatch requires explicit online search consent")
    key = os.environ.get("TIHULU_MUSIXMATCH_API_KEY", "").strip()
    if not key:
        return [], {"provider": "Musixmatch official API",
                    "status": "not_configured", "license": "API key required"}
    if not artist.strip() or not title.strip() or len(key) > 512:
        return [], {"provider": "Musixmatch official API",
                    "status": "unavailable"}
    url = ("https://api.musixmatch.com/ws/1.1/matcher.lyrics.get?"
           + urllib.parse.urlencode({"q_track": title, "q_artist": artist,
                                     "apikey": key}))
    try:
        payload = _get_json(url)
        message = payload.get("message", {})
        header = message.get("header", {}) if isinstance(message, dict) else {}
        if header.get("status_code") != 200:
            return [], {"provider": "Musixmatch official API",
                        "status": "unavailable"}
        body = message.get("body", {})
        lyrics = body.get("lyrics", {}) if isinstance(body, dict) else {}
        raw = lyrics.get("lyrics_body", "") if isinstance(lyrics, dict) else ""
        if not isinstance(raw, str) or not raw.strip() or (
                "*******" in raw or "NOT for Commercial use" in raw):
            return [], {"provider": "Musixmatch official API",
                        "status": "no_full_licensed_lyrics"}
        lines = _clean_plain(raw)
        return lines, {"provider": "Musixmatch official API",
                       "status": "plain" if lines else "empty",
                       "alignment": "awaiting_real_audio_ASR",
                       "metadata_verification": "audio_match_required",
                       "online_lookup": True,
                       "copyright": str(lyrics.get("lyrics_copyright", ""))[:240]}
    except (OSError, ValueError, RuntimeError, urllib.error.URLError):
        return [], {"provider": "Musixmatch official API",
                    "status": "unavailable"}


def lookup_synced_lyrics(*, title: str, artist: str,
                         album: str = "", duration: float | None = None,
                         online: bool = False,
                         allow_plain: bool = False) -> tuple[list[LyricCue],dict]:
    """User-authorized keyless lookup with optional unsynced plain lines.

    Plain lines are data for a *subsequent* real ASR matcher; never
    pass them off as synchronized lyric timestamps.
    """
    if not online:
        raise PermissionError(
            "Online lyrics search is OFF by default; ask explicitly to search")
    if (not isinstance(title,str) or not isinstance(artist,str) or
            not title.strip() or not artist.strip() or
            max(len(title),len(artist),len(album)) > 180):
        raise ValueError("Artist and song title are required for safe matching")
    params = {"track_name":title.strip(), "artist_name":artist.strip()}
    if album.strip():
        params["album_name"] = album.strip()
    if duration is not None and 1 <= float(duration) <= 3600:
        params["duration"] = round(float(duration))
    url = "https://lrclib.net/api/get?" + urllib.parse.urlencode(params)
    # A temporary LRCLIB DNS/HTTP/timeout failure must not prevent the
    # explicitly authorized lyrics.ovh / licensed-provider fallback. Never
    # retry the same failed origin in a busy loop; if the exact GET failed,
    # bypass its search endpoint and proceed directly to plain sources.
    lrclib_issue = None
    try:
        record = _get_json(url)
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        if not allow_plain:
            raise
        record = {}
        lrclib_issue = str(exc)[:120]
    # LRCLIB occasionally returns a fuzzy result for a structured /api/get,
    # especially for RDS/DLS spelling and punctuation. Never crash the
    # lookup worker or display another song; search the catalog for a
    # metadata-matching candidate instead.
    if not record or not _matches_record(record, title, artist):
        search_url = ("https://lrclib.net/api/search?"
                      + urllib.parse.urlencode({
                          "track_name": title.strip(),
                          "artist_name": artist.strip()}))
        try:
            results = (_get_json(search_url, allow_list=True)
                       if lrclib_issue is None else [])
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            if not allow_plain:
                raise
            results = []
            lrclib_issue = str(exc)[:120]
        exact = [item for item in results
                 if _matches_record(item, title, artist)
                 and not item.get("instrumental")]
        record = next((item for item in exact if item.get("syncedLyrics")),
                      exact[0] if exact else {})
    if not record:
        if allow_plain:
            # Prefer open keyless LRCLIB; licensed Musixmatch is optional
            # only when the user explicitly supplied their official API key.
            lines, alternative = lookup_musixmatch_licensed_plain(
                artist=artist, title=title, online=online)
            if lines:
                return [], {**alternative, "plain_lines": lines,
                            "artist": artist, "track": title}
            lines, alternative = lookup_alternative_plain(
                artist=artist, title=title, online=online)
            if lines:
                return [], {**alternative, "plain_lines": lines,
                            "artist": artist, "track": title}
        return [], {"status": "lrclib_unavailable" if lrclib_issue else "not_found",
                    "provider": "LRCLIB; licensed Musixmatch; lyrics.ovh",
                    "message": ("LRCLIB unavailable; alternative text sources also "
                                "did not return usable song words" if lrclib_issue else
                                "No trusted matching lyric metadata")}
    if duration is not None and isinstance(record.get("duration"),(int,float)):
        if abs(float(record["duration"])-float(duration)) > 3:
            raise ValueError("Lyrics duration mismatch; refusing unsafe auto-sync")
    if record.get("instrumental"):
        return [], {"status":"instrumental","provider":"LRCLIB"}
    synced = record.get("syncedLyrics")
    if not synced or not isinstance(synced,str):
        raw = record.get("plainLyrics")
        if allow_plain and isinstance(raw,str):
            # Newlines only; reject headers/tags and enforce tight bounds.
            cleaned = []
            for line in raw.splitlines()[:300]:
                line = " ".join(line.strip().split())
                if (3 <= len(line) <= 240 and
                        not (line.startswith("[") and line.endswith("]"))):
                    cleaned.append(line)
                if len(cleaned) >= 150:
                    break
            if cleaned:
                return [], {
                    "status":"plain","provider":"LRCLIB",
                    "record_id":record.get("id"),
                    "track":title,"artist":artist,
                    "plain_lines":cleaned,
                    "alignment":"awaiting_real_audio_ASR",
                    "online_lookup":True}
        if allow_plain:
            lines,alternate=lookup_musixmatch_licensed_plain(
                artist=artist,title=title,online=online)
            if lines:
                return [],{**alternate,"plain_lines":lines,
                           "artist":artist,"track":title}
            lines,alternate=lookup_alternative_plain(
                artist=artist,title=title,online=online)
            if lines:
                return [],{**alternate,"plain_lines":lines,
                           "artist":artist,"track":title}
        return [], {"status":"unsynced_only","provider":"LRCLIB; licensed Musixmatch; lyrics.ovh",
                    "message":"No usable lyrics from allowed sources"}
    cues = parse_lrc(synced,duration=duration,provenance="LRCLIB")
    if not cues and allow_plain:
        # Some catalogs advertise syncedLyrics but deliver invalid LRC tags.
        # Preserve genuine plainLyrics rather than pretending no lyrics exist.
        lines = _clean_plain(record.get("plainLyrics",""))
        if lines:
            return [], {"status":"plain","provider":"LRCLIB",
                        "record_id":record.get("id"),
                        "track":title,"artist":artist,
                        "plain_lines":lines,
                        "alignment":"awaiting_real_audio_ASR",
                        "online_lookup":True}
    return cues, {"status":"synced" if cues else "invalid",
                  "provider":"LRCLIB","record_id":record.get("id"),
                  "track":title,"artist":artist,
                  "online_lookup":True}



def _lyric_tokens(text: str) -> list[str]:
    # NFKD gives case/accent-insensitive candidates, including Turkish.
    plain = unicodedata.normalize("NFKD", text).casefold()
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.findall(r"[^\W_]+", plain, flags=re.UNICODE)[:90]


class LiveLyricMatcher:
    """Conservative forward-only match of verified lyrics to *heard* ASR.

    Does not detect a song by itself and makes no timestamps where no
    recognizable vocal phrase is present. One or two generic words are
    insufficient evidence for a match. This is approximate chunk timing,
    NOT sample-accurate forced alignment.
    """
    def __init__(self, lines: list[str], *, threshold: float=0.74,
                 mode: str="lexical"):
        if not isinstance(threshold,(int,float)) or isinstance(threshold,bool) or not 0.0 <= threshold <= 1.0:
            raise ValueError("Lyrics lexical match threshold must be 0–100%")
        if mode not in ("lexical","fuzzy"):
            raise ValueError("Unsupported Lyrics Match method")
        self.threshold=float(threshold)
        self.mode=mode
        if not isinstance(lines,list) or len(lines)>150:
            raise ValueError("Invalid plain lyric line catalog")
        self.lines=[line for line in lines if isinstance(line,str) and
                    3<=len(line)<=240]
        self.position=0
        self.seen_chunks=0
        self.previous_text=""
        self.unmatched_chunks=0
        self.last_match_index=-1
        self.last_match_text=""
        self.last_match_at_chunk=-999

    def set_threshold(self, threshold: float):
        if not isinstance(threshold,(int,float)) or isinstance(threshold,bool) or not 0.0 <= threshold <= 1.0:
            raise ValueError("Lyrics lexical match threshold must be 0–100%")
        self.threshold=float(threshold)

    def set_mode(self, mode: str):
        if mode not in ("lexical","fuzzy"):
            raise ValueError("Unsupported Lyrics Match method")
        if self.mode!=mode:
            self.mode=mode
            self.previous_text=""
            self.unmatched_chunks=0

    def _matches_token(self, token: str, heard: set[str]) -> bool:
        if token in heard:
            return True
        if self.mode!="fuzzy" or len(token)<5:
            return False
        # A fuzzy spelling match is not acoustic evidence on its own:
        # normal lyric lines still require THREE distinct overlapping words.
        return any(len(word)>=5 and abs(len(word)-len(token))<=2
                   and difflib.SequenceMatcher(None,token,word).ratio()>=0.83
                   for word in heard)

    def reacquire(self, recognized: str) -> dict | None:
        """Reposition on genuinely heard words after an explicit Sync Refresh.

        Unlike the normal forward-only matcher, this searches the whole
        catalog with >=89% lexical confidence. It consumes NO new audio and
        leaves the existing match position untouched if evidence is weak.
        Never use lyrics metadata or a previous catalog line as `recognized`.
        """
        if not isinstance(recognized, str) or not recognized.strip():
            return None
        candidate=LiveLyricMatcher(self.lines,
            threshold=self.threshold,mode=self.mode)
        match=candidate.observe(recognized)
        if match is None:
            return None
        # Identical refrains can appear several times in one song. Text
        # similarity alone cannot identify which chorus is playing, so
        # reject a long-range ambiguous seek instead of jumping to verse 1.
        same=[index for index,line in enumerate(self.lines)
              if _metadata_key(line)==_metadata_key(match["text"])]
        if len(same)>1:
            nearby=[index for index in same
                    if abs(index-max(0,self.position-1))<=8]
            if len(nearby)!=1:
                return None
            match["index"]=nearby[0]
            candidate.position=nearby[0]+1
            candidate.last_match_index=nearby[0]
        self.position=candidate.position
        self.previous_text=recognized[-480:]
        self.unmatched_chunks=0
        self.last_match_index=candidate.last_match_index
        self.last_match_text=candidate.last_match_text
        self.last_match_at_chunk=self.seen_chunks
        return {**match, "refresh_reacquired":True}

    def observe(self, recognized: str) -> dict | None:
        if not isinstance(recognized,str) or not recognized.strip():
            return None
        self.seen_chunks += 1
        heard = _lyric_tokens(self.previous_text + " " + recognized)
        self.previous_text = recognized[-480:]
        if len(heard)<3:
            return None
        hearing=set(heard)
        best=None
        # Users can enable Auto Lyrics after joining a song already in
        # progress. Its first heard verse may be line 40, not line 1.
        # Initial acquisition can search all lyrics only with stronger
        # lexical evidence; once locked, remain forward-only (up to 8)
        # to avoid matching unrelated adverts or distant repetitions.
        acquiring=self.position==0 and self.seen_chunks<=8
        if acquiring:
            indexes=range(len(self.lines))
        else:
            indexes=range(self.position,min(len(self.lines),self.position+8))
        for index in indexes:
            original=self.lines[index]
            expected=_lyric_tokens(original)
            if len(expected)<3:
                continue
            distinctive={word for word in expected if len(word)>=3}
            evidence=sum(1 for word in distinctive
                         if self._matches_token(word,hearing))
            # Short refrains such as "Gül kokar gül" contain only two
            # DISTINCTIVE words. Require BOTH, with higher confidence;
            # do not match "Rose kokar rose" to "Gül kokar gül".
            short_refrain=len(expected)<=4 and len(distinctive)==2
            required=2 if short_refrain else 3
            if evidence<required:
                continue
            coverage=evidence/max(1,len(distinctive))
            precision=evidence/max(1,len(hearing))
            confidence=0.82*coverage+0.18*min(1.,precision*2.)
            threshold=self.threshold
            if acquiring and index>=8:
                # A broad search needs a distinctive multiword phrase;
                # generic 2-word refrains may only match near the start.
                if len(distinctive)<3 or evidence<3:
                    continue
                # Broad seeks still require three distinctive matching
                # tokens; 0% does not mean auto-progress on silence.
                threshold=max(threshold,0.40)
            # Avoid replaying the same recognized line in consecutive
            # overlapping 5 s chunks. A later real refrain stays possible.
            if (index==self.last_match_index or
                _metadata_key(original)==_metadata_key(self.last_match_text)) and (
                    self.seen_chunks-self.last_match_at_chunk<=2):
                continue
            if confidence>=threshold and (best is None or confidence>best[0]):
                best=(confidence,index,original)
        if best is None:
            self.unmatched_chunks+=1
            return None
        score,index,line=best
        self.unmatched_chunks=0
        self.position=index+1
        self.last_match_index=index
        self.last_match_text=line
        self.last_match_at_chunk=self.seen_chunks
        return {"index":index,"text":line,"confidence":round(score,3),
                "threshold":round(self.threshold,3),
                "metric":"lexical_overlap_not_audio_sync_probability",
                "mode":self.mode,
                "kind":"observed_ASR_chunk_match","approximate":True}

def srt_timestamp(seconds: float) -> str:
    ms=max(0,int(round(seconds*1000)))
    return f"{ms//3600000:02}:{(ms//60000)%60:02}:{(ms//1000)%60:02},{ms%1000:03}"


def write_srt(cues: list[LyricCue], path: str | Path, *,
              overwrite: bool = False, translations: dict[int,str] | None = None,
              include_original: bool = True):
    target=Path(path).expanduser()
    if target.is_symlink() or not target.parent.is_dir():
        raise ValueError("Output directory invalid or destination is symlink")
    lines = []
    for i, cue in enumerate(cues,1):
        if cue.end <= cue.start:
            continue
        translated = translations.get(i) if translations else None
        # "translated only" mirrors the TV output preference. Never write
        # an empty subtitle if the chosen translator has no usable result.
        text = cue.text if include_original or not translated else ""
        if translated:
            text += ("\n" if text else "") + translated
        lines.append(f"{i}\n{srt_timestamp(cue.start)} --> {srt_timestamp(cue.end)}\n{text}\n")
    if len(lines) > 12000:
        raise ValueError("Subtitle cue budget exceeded (12000 cues)")
    flags = "w" if overwrite else "x"
    with target.open(flags,encoding="utf-8") as output:
        output.write("\n".join(lines))
    return target
