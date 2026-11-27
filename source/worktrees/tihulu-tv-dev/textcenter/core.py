"""Persistence, bounded feed decoding, and attributed broadcast imports.

Only local, explicitly requested operations are performed here.
This is NOT an SDR, DVB, Journaline, emergency or RF transmission decoder.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from hashlib import sha256
import ipaddress
import json
from pathlib import Path
import re
import socket
import sqlite3
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

MAX_FEED_BYTES = 1_000_000
MAX_FEED_ITEMS = 60
MAX_IMPORT_ITEMS = 2000
KNOWN_MEDIA = frozenset({
    "dvb_teletext", "dab_dls", "journaline", "fm_rds", "drm",
    "navtex", "hf_weather", "aprs", "other_receiver",
})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: object, limit: int = 4000) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:limit]


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("p", "br", "li", "div") and not self.skip:
            self.fragments.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, value):
        if not self.skip:
            self.fragments.append(value)


def text_only(value: str, limit: int = 20000) -> str:
    p = _Text()
    p.feed(value[:limit * 2])
    return clean_text(" ".join(p.fragments), limit)


def multiline_text(value: object, limit: int = 30000) -> str:
    """Retain meaningful decoder line layout without terminal control bytes."""
    if not isinstance(value, str):
        return ""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value).strip()[:limit]


def validate_timestamp(value: object) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Received timestamp must be an ISO-8601 string")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid ISO-8601 timestamp") from exc
    if stamp.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def safe_https_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 1200:
        raise ValueError("Invalid feed URL")
    p = urllib.parse.urlsplit(value)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment:
        raise ValueError("Only public HTTPS feed URLs without credentials/fragments are allowed")
    if p.port not in (None, 443):
        raise ValueError("Only HTTPS port 443 is allowed")
    hostname = p.hostname.lower().rstrip(".")
    if "." not in hostname or hostname.endswith((".local", ".localhost", ".internal", ".test", ".invalid")):
        raise ValueError("Private or non-public hostname")
    try:
        ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        pass
    else:
        raise ValueError("IP-address feed hosts are disabled")
    if not re.fullmatch(r"[a-z0-9.-]+", hostname) or ".." in hostname:
        raise ValueError("Invalid feed hostname")
    return value


def guard_public_dns(url: str) -> None:
    """Defense in depth: only operator-added feeds, public resolved IPs.

    For truly hostile multi-tenant deployments, use an egress proxy with pinned
    DNS/address policy. This service intentionally has no anonymous URL fetch API.
    """
    host = urllib.parse.urlsplit(safe_https_url(url)).hostname
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not infos:
        raise ValueError("Feed hostname not resolvable")
    for info in infos:
        address = info[4][0]
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("Feed resolved to a non-public address")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_feed(url: str) -> bytes:
    guard_public_dns(url)
    req = urllib.request.Request(
        safe_https_url(url),
        headers={"User-Agent": "TihuluTextCenter/0.1 (+manual feed refresh)", "Accept": "application/rss+xml, application/atom+xml, application/feed+json, application/json, application/xml, text/xml"},
    )
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(req, timeout=9) as response:
        if response.status != 200:
            raise ValueError("Feed responded with non-200 status")
        payload = response.read(MAX_FEED_BYTES + 1)
        if len(payload) > MAX_FEED_BYTES:
            raise ValueError("Feed exceeds one-megabyte limit")
    return payload


def _child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in node:
        if child.tag.split("}")[-1].lower() in names:
            if child.text:
                return clean_text(child.text, 18000)
            return clean_text("".join(child.itertext()), 18000)
    return ""


def _json_feed_items(payload: bytes, *, feed_id: str, feed_title: str,
                     source_url: str) -> list[dict]:
    """JSON Feed 1/1.1, bounded text-only archive; no JSON attachments downloaded."""
    try:
        doc = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid JSON Feed") from exc
    if not isinstance(doc, dict) or doc.get("version") not in (
            "https://jsonfeed.org/version/1", "https://jsonfeed.org/version/1.1"):
        raise ValueError("Unsupported JSON Feed version")
    items = doc.get("items")
    if not isinstance(items, list):
        raise ValueError("JSON Feed items must be an array")
    out = []
    for item in items[:MAX_FEED_ITEMS]:
        if not isinstance(item, dict):
            continue
        title = clean_text(item.get("title"), 220) or "(untitled)"
        content = item.get("content_text")
        if isinstance(content, str):
            body = clean_text(content, 10000)
        else:
            html = item.get("content_html") or item.get("summary") or ""
            body = text_only(html, 10000) if isinstance(html, str) else ""
        link = item.get("url") or item.get("external_url") or ""
        try:
            link = safe_https_url(link)
        except (ValueError, TypeError):
            link = ""
        pub = clean_text(item.get("date_published") or item.get("date_modified"), 100)
        origin_id = clean_text(item.get("id"), 300)
        key = sha256((feed_id+"\n"+origin_id+"\n"+title+"\n"+link+"\n"+pub).encode()).hexdigest()[:32]
        out.append({
            "id":key, "feed_id":feed_id, "source_name":feed_title,
            "source_url":source_url, "title":title, "body":body,
            "url":link, "published_at":pub, "observed_at":utc_now(),
            "medium":"internet_feed",
        })
    return out


def parse_feed(payload: bytes, *, feed_id: str, feed_title: str, source_url: str) -> list[dict]:
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("Feed too large")
    if payload.lstrip().startswith(b"{"):
        return _json_feed_items(payload, feed_id=feed_id,
                                feed_title=feed_title, source_url=source_url)
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ValueError("External or custom XML entities are forbidden")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("Invalid RSS/Atom document") from exc
    kind = root.tag.split("}")[-1].lower()
    if kind == "rss":
        channel = next((x for x in root if x.tag.lower() == "channel"), None)
        if channel is None:
            raise ValueError("RSS channel missing")
        entries = [x for x in channel if x.tag.lower() == "item"]
    elif kind == "feed":
        entries = [x for x in root if x.tag.split("}")[-1].lower() == "entry"]
    else:
        raise ValueError("Only RSS 2.0 and Atom feeds supported")
    result: list[dict] = []
    for item in entries[:MAX_FEED_ITEMS]:
        title = text_only(_child_text(item, ("title",)), 220) or "(untitled)"
        body = text_only(_child_text(item, ("description", "summary", "content", "encoded")), 10000)
        link = _child_text(item, ("link",))
        if kind == "feed":
            for c in item:
                if c.tag.split("}")[-1].lower() == "link" and c.attrib.get("rel", "alternate") == "alternate":
                    link = c.attrib.get("href", "")
                    break
        # Never expose javascript:, data:, local or untrusted network links.
        try:
            link = safe_https_url(link)
        except (ValueError, TypeError):
            link = ""
        published = _child_text(item, ("pubdate", "published", "updated"))
        key = sha256((feed_id + "\n" + title + "\n" + link + "\n" + published).encode()).hexdigest()[:32]
        result.append({
            "id": key, "feed_id": feed_id, "source_name": feed_title,
            "source_url": source_url, "title": title, "body": body,
            "url": link, "published_at": published[:100],
            "observed_at": utc_now(), "medium": "internet_feed",
        })
    return result


def _required_body(obj: dict, key: str, limit: int) -> str:
    s = multiline_text(obj.get(key), limit)
    if not s:
        raise ValueError(f"Missing {key}")
    return s


def _required_string(obj: dict, key: str, limit: int) -> str:
    s = clean_text(obj.get(key), limit)
    if not s or len(s) > limit:
        raise ValueError(f"Missing or invalid {key}")
    return s


class Store:
    def __init__(self, filename: str | Path):
        self.filename = Path(filename).expanduser()
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        self._schema()

    def connect(self):
        db = sqlite3.connect(self.filename, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _schema(self):
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS feeds (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
                    last_fetched TEXT, last_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY, feed_id TEXT NOT NULL, source_name TEXT NOT NULL,
                    source_url TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                    url TEXT NOT NULL, published_at TEXT NOT NULL,
                    observed_at TEXT NOT NULL, medium TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pages (
                    source_id TEXT NOT NULL, page INTEGER NOT NULL, subpage INTEGER NOT NULL,
                    title TEXT NOT NULL, body TEXT NOT NULL, language TEXT NOT NULL,
                    received_at TEXT NOT NULL, station TEXT NOT NULL,
                    frequency_hz INTEGER NOT NULL, medium TEXT NOT NULL,
                    provenance TEXT NOT NULL, PRIMARY KEY (source_id, page, subpage)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, title TEXT NOT NULL,
                    body TEXT NOT NULL, received_at TEXT NOT NULL, station TEXT NOT NULL,
                    language TEXT NOT NULL, frequency_hz INTEGER NOT NULL,
                    medium TEXT NOT NULL, provenance TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bulletins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    body TEXT NOT NULL, author TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bookmarks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT NOT NULL,
                    target_type TEXT NOT NULL, target TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(target_type,target)
                );
            """)

    @staticmethod
    def _rows(db, sql, args=()):
        return [dict(r) for r in db.execute(sql, args).fetchall()]

    def counts(self) -> dict:
        with self.connect() as db:
            return {kind: db.execute("SELECT COUNT(*) FROM " + kind).fetchone()[0]
                    for kind in ("feeds", "articles", "pages", "events", "bulletins", "bookmarks")}

    def feeds(self) -> list[dict]:
        with self.connect() as db:
            return self._rows(db, "SELECT * FROM feeds ORDER BY title")

    def add_feed(self, title: str, url: str) -> str:
        title = clean_text(title, 120)
        url = safe_https_url(url)
        if not title:
            raise ValueError("Feed title cannot be empty")
        fid = sha256(url.encode()).hexdigest()[:16]
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO feeds(id,title,url,last_fetched,last_count) VALUES(?,?,?,COALESCE((SELECT last_fetched FROM feeds WHERE id=?),NULL),COALESCE((SELECT last_count FROM feeds WHERE id=?),0))",
                       (fid, title, url, fid, fid))
        return fid

    def refresh_feed(self, feed_id: str, fetcher=fetch_feed) -> int:
        with self.connect() as db:
            row = db.execute("SELECT * FROM feeds WHERE id=?", (feed_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown feed")
        articles = parse_feed(fetcher(row["url"]), feed_id=feed_id,
                              feed_title=row["title"], source_url=row["url"])
        with self.connect() as db:
            for a in articles:
                db.execute("""INSERT OR REPLACE INTO articles
                    (id,feed_id,source_name,source_url,title,body,url,published_at,observed_at,medium)
                    VALUES(:id,:feed_id,:source_name,:source_url,:title,:body,:url,:published_at,:observed_at,:medium)""", a)
            db.execute("UPDATE feeds SET last_fetched=?,last_count=? WHERE id=?",
                       (utc_now(), len(articles), feed_id))
        return len(articles)

    def articles(self, query: str = "") -> list[dict]:
        with self.connect() as db:
            if query:
                term = "%" + query[:100].replace("~", "~~").replace("%", "~%").replace("_", "~_") + "%"
                return self._rows(db, """SELECT * FROM articles
                    WHERE title LIKE ? ESCAPE '~' OR body LIKE ? ESCAPE '~'
                    ORDER BY observed_at DESC LIMIT 100""", (term, term))
            return self._rows(db, "SELECT * FROM articles ORDER BY observed_at DESC LIMIT 100")

    def pages(self, source_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            if source_id:
                return self._rows(db, "SELECT source_id,page,subpage,title,language,received_at,station,medium FROM pages WHERE source_id=? ORDER BY page,subpage LIMIT 500", (source_id,))
            return self._rows(db, "SELECT source_id,page,subpage,title,language,received_at,station,medium FROM pages ORDER BY received_at DESC LIMIT 500")

    def page(self, source_id: str, page: int, subpage: int) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM pages WHERE source_id=? AND page=? AND subpage=?",
                             (source_id, page, subpage)).fetchone()
            return dict(row) if row else None

    def events(self) -> list[dict]:
        with self.connect() as db:
            return self._rows(db, "SELECT * FROM events ORDER BY received_at DESC LIMIT 150")

    def import_data(self, payload: dict) -> dict:
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("Expected versioned broadcast JSON schema")
        pages, events = payload.get("pages", []), payload.get("events", [])
        if not isinstance(pages, list) or not isinstance(events, list) or len(pages) + len(events) > MAX_IMPORT_ITEMS:
            raise ValueError("Too many items or invalid data")
        valid_pages, valid_events = [], []
        for raw in pages:
            if not isinstance(raw, dict):
                raise ValueError("Page must be an object")
            page, subpage = raw.get("page"), raw.get("subpage", 0)
            if type(page) is not int or not 100 <= page <= 899 or type(subpage) is not int or not 0 <= subpage <= 99:
                raise ValueError("Broadcast page number 100–899 and subpage 0–99 required")
            medium = raw.get("medium")
            if medium not in ("dvb_teletext", "journaline"):
                raise ValueError("Only Teletext/Journaline pages accepted as numbered broadcast pages")
            hz = raw.get("frequency_hz")
            if type(hz) is not int or hz <= 0:
                raise ValueError("Real receiver frequency required")
            valid_pages.append({
                "source_id": _required_string(raw, "source_id", 90), "page": page, "subpage": subpage,
                "title": _required_string(raw, "title", 180), "body": _required_body(raw, "body", 30000),
                "language": _required_string(raw, "language", 20),
                "received_at": validate_timestamp(raw.get("received_at")),
                "station": _required_string(raw, "station", 120),
                "frequency_hz": hz, "medium": medium,
                "provenance": _required_string(raw, "provenance", 400),
            })
        for raw in events:
            if not isinstance(raw, dict) or raw.get("medium") not in KNOWN_MEDIA:
                raise ValueError("Unknown event medium")
            hz = raw.get("frequency_hz")
            if type(hz) is not int or hz <= 0:
                raise ValueError("Real receiver frequency required")
            event = {
                "source_id": _required_string(raw, "source_id", 90),
                "title": _required_string(raw, "title", 180),
                "body": _required_body(raw, "body", 30000),
                "received_at": validate_timestamp(raw.get("received_at")),
                "station": _required_string(raw, "station", 120),
                "language": _required_string(raw, "language", 20),
                "frequency_hz": hz, "medium": raw["medium"],
                "provenance": _required_string(raw, "provenance", 400),
            }
            event["id"] = sha256(("|".join(str(event[k]) for k in ("source_id","received_at","title","body"))).encode()).hexdigest()[:32]
            valid_events.append(event)
        with self.connect() as db:
            for p in valid_pages:
                db.execute("""INSERT OR REPLACE INTO pages
                   (source_id,page,subpage,title,body,language,received_at,station,frequency_hz,medium,provenance)
                   VALUES(:source_id,:page,:subpage,:title,:body,:language,:received_at,:station,:frequency_hz,:medium,:provenance)""", p)
            for e in valid_events:
                db.execute("""INSERT OR REPLACE INTO events
                   (id,source_id,title,body,received_at,station,language,frequency_hz,medium,provenance)
                   VALUES(:id,:source_id,:title,:body,:received_at,:station,:language,:frequency_hz,:medium,:provenance)""", e)
        return {"pages": len(valid_pages), "events": len(valid_events)}

    def bulletins(self) -> list[dict]:
        with self.connect() as db:
            return self._rows(db, "SELECT * FROM bulletins ORDER BY id DESC LIMIT 100")

    def add_bulletin(self, title: str, body: str, author: str) -> int:
        if not all([clean_text(title, 140), multiline_text(body, 4000), clean_text(author, 60)]):
            raise ValueError("Title, message and author required")
        with self.connect() as db:
            return db.execute("INSERT INTO bulletins(title,body,author,created_at) VALUES(?,?,?,?)",
                              (clean_text(title, 140),multiline_text(body, 4000),clean_text(author, 60),utc_now())).lastrowid

    def bookmarks(self) -> list[dict]:
        with self.connect() as db:
            return self._rows(db, "SELECT * FROM bookmarks ORDER BY id DESC LIMIT 100")

    def add_bookmark(self, label: str, target_type: str, target: str) -> None:
        if target_type not in ("page", "article", "broadcast") or not clean_text(label, 140) or not clean_text(target, 180):
            raise ValueError("Invalid bookmark")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO bookmarks(label,target_type,target,created_at) VALUES(?,?,?,?)",
                       (clean_text(label,140),target_type,clean_text(target,180),utc_now()))
