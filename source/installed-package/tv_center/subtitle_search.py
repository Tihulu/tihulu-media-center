# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional subtitle search for local films (explicit owner action only).

Keyless OpenSubtitles XML-RPC plus the classic movie-hash algorithm. The
network is touched ONLY when the owner presses the search button; nothing is
searched, uploaded or downloaded automatically. No API key and no account.
"""
from __future__ import annotations
import gzip
import json
import os
from pathlib import Path
import struct
import urllib.request
import urllib.error

ENDPOINT = "https://api.opensubtitles.org/xml-rpc"
USER_AGENT = "TIHULU Media Center 1.1"


def movie_hash(path: str | os.PathLike, chunk: int = 65536) -> str:
    """OpenSubtitles hash: little-endian sums of the head and tail blocks."""
    size = os.path.getsize(path)
    if size < chunk:
        raise ValueError("File is too small for a subtitle search hash")
    total = size
    with open(path, "rb") as handle:
        head = handle.read(chunk)
        handle.seek(-chunk, os.SEEK_END)
        tail = handle.read(chunk)
    for block in (head, tail):
        for value in struct.unpack("<%dQ" % (len(block) // 8), block[:len(block) // 8 * 8]):
            total = (total + value) & 0xFFFFFFFFFFFFFFFF
    return "%016x" % total


def _rpc(method: str, params: list, timeout: int = 25) -> dict:
    body = json.dumps({"method": method, "params": params}).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": USER_AGENT,
                 "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    if payload.get("status") != "200 OK":
        raise RuntimeError("Subtitle search service refused: " +
                           str(payload.get("status")))
    return payload.get("result", {})


def login() -> str:
    result = _rpc("LogIn", ["", "", "en", USER_AGENT])
    token = result.get("token")
    if not token:
        raise RuntimeError("Subtitle search did not return a session token")
    return token


def search(*, path: str | None = None, title: str = "",
           language: str = "en") -> list[dict]:
    token = login()
    query = {"sublanguageid": language or "en"}
    if path:
        query["moviehash"] = movie_hash(path)
        query["moviebytesize"] = str(os.path.getsize(path))
    elif title.strip():
        query["query"] = title.strip()
    else:
        raise ValueError("Provide a file to hash or a title to search")
    result = _rpc("SearchSubtitles", [token, [query]])
    found = []
    for row in result.get("data", []) or []:
        found.append({
            "name": row.get("SubFileName", "unknown"),
            "language": row.get("SubLanguageID", "?"),
            "downloads": row.get("SubDownloadsCnt", "0"),
            "format": row.get("SubFormat", "srt"),
            "link": row.get("SubDownloadLink", ""),
            "rating": row.get("SubRating", "0"),
        })
    return found[:40]


def download(entry: dict, destination: str | os.PathLike) -> str:
    link = entry.get("link")
    if not link:
        raise ValueError("Search result has no download link")
    destination = Path(destination)
    request = urllib.request.Request(link, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read(5 * 1024 * 1024)
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    text = payload.decode("utf-8", "replace")
    if "WEBVTT" in text[:40] and ".vtt" not in destination.suffix:
        destination = destination.with_suffix(".vtt")
    destination.write_text(text, encoding="utf-8")
    return str(destination)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args[:1] == ["--hash"]:
            print(json.dumps({"hash": movie_hash(args[1])}))
            return 0
        if args[:2] == ["--search", "hash"] or args[:2] == ["--search", "title"]:
            kind = args[1]
            query = args[2] if len(args) > 2 else ""
            language = args[3] if len(args) > 3 else "en"
            rows = search(path=query if kind == "hash" else None,
                          title=query if kind == "title" else "",
                          language=language)
            print(json.dumps({"results": rows}, ensure_ascii=False))
            return 0
        if args[:2] == ["--download"]:
            entry = json.loads(args[2])
            print(json.dumps({"saved": download(entry, args[3])}, ensure_ascii=False))
            return 0
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
        print(json.dumps({"error": str(exc)[:220]}), file=sys.stderr)
        return 1
    raise SystemExit("Usage: python -m tv_center.subtitle_search "
                     "[--hash FILE | --search hash|title QUERY [LANG] | --download JSON DEST]")


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
