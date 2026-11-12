"""Verified-format local archive for decoder-supplied broadcast images.

No network images, arbitrary uploads, HTML, SVG, archives, or content from
RSS are accepted. PNG/JPEG only, max 320 KiB each. Images are attached to
specified decoded RF service & capture timestamp; provenance is retained.
Source itself remains untrusted as an emergency authority.
"""
from __future__ import annotations
import base64
import binascii
from hashlib import sha256
from pathlib import Path
import struct

from .core import Store, clean_text, utc_now, validate_timestamp

MAX_IMAGE = 320*1024
MAX_MEDIA_IMPORT = 40
VALID_MEDIA = {"dab_mot", "fm_rds2_logo"}


def check_image(raw: bytes) -> str:
    if not isinstance(raw,bytes) or not 40 <= len(raw) <= MAX_IMAGE:
        raise ValueError("Received image must be a 40 B–320 KiB PNG/JPEG")
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        if raw[12:16] != b"IHDR" or len(raw) < 33:
            raise ValueError("PNG header invalid")
        w,h=struct.unpack(">II",raw[16:24])
        if not (1 <= w <= 4096 and 1 <= h <= 4096):
            raise ValueError("Unreasonably large PNG dimensions")
        if not raw.endswith(b"IEND\xaeB\x60\x82"):
            raise ValueError("PNG missing final chunk")
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9"):
        return "image/jpeg"
    raise ValueError("Only recognized PNG/JPEG radio images supported")


def _attr(value, label: str, maximum: int):
    content=clean_text(value, maximum)
    if not content:
        raise ValueError("Invalid/missing "+label)
    return content


class MediaStore:
    def __init__(self, store: Store):
        self.store=store
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS radio_media (
                    id TEXT PRIMARY KEY, medium TEXT NOT NULL,
                    station TEXT NOT NULL, source_id TEXT NOT NULL,
                    frequency_hz INTEGER NOT NULL, received_at TEXT NOT NULL,
                    provenance TEXT NOT NULL, mime TEXT NOT NULL, payload BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS radio_media_recent ON radio_media(received_at DESC);
            """)

    def save(self, *, medium: str, station: str, source_id: str,
             frequency_hz: int, received_at: str, provenance: str,
             image_base64: str) -> dict:
        if medium not in VALID_MEDIA:
            raise ValueError("Unsupported broadcast image medium")
        if type(frequency_hz) is not int or frequency_hz<=0:
            raise ValueError("Real receiver frequency required")
        if not isinstance(image_base64,str) or len(image_base64)>450_000:
            raise ValueError("Invalid/oversized base64 image data")
        try:
            raw=base64.b64decode(image_base64,validate=True)
        except (ValueError,binascii.Error) as exc:
            raise ValueError("Image has invalid base64") from exc
        mime=check_image(raw)
        station=_attr(station,"station",120)
        source_id=_attr(source_id,"source_id",90)
        provenance=_attr(provenance,"provenance",400)
        received_at=validate_timestamp(received_at)
        identity=sha256(raw+str(frequency_hz).encode()+source_id.encode()).hexdigest()[:48]
        row={"id":identity, "medium":medium, "station":station,"source_id":source_id,
             "frequency_hz":frequency_hz,"received_at":received_at,"provenance":provenance,
             "mime":mime,"payload":raw}
        with self.store.connect() as db:
            db.execute("""INSERT OR REPLACE INTO radio_media
                (id,medium,station,source_id,frequency_hz,received_at,provenance,mime,payload)
                VALUES(:id,:medium,:station,:source_id,:frequency_hz,:received_at,:provenance,:mime,:payload)""",row)
            # Keep local storage bounded, latest 120 distinct images.
            db.execute("""DELETE FROM radio_media WHERE id NOT IN
                (SELECT id FROM radio_media ORDER BY received_at DESC LIMIT 120)""")
        return {k:v for k,v in row.items() if k!="payload"}

    def list(self) -> list[dict]:
        with self.store.connect() as db:
            rows=db.execute("""SELECT id,medium,station,source_id,frequency_hz,
                 received_at,provenance,mime,length(payload) AS bytes
                 FROM radio_media ORDER BY received_at DESC LIMIT 120""").fetchall()
            return [dict(r) for r in rows]

    def get(self, identity: str) -> tuple[str,bytes] | None:
        if not isinstance(identity,str) or len(identity)!=48 or any(
            ch not in "0123456789abcdef" for ch in identity
        ):
            return None
        with self.store.connect() as db:
            item=db.execute("SELECT mime,payload FROM radio_media WHERE id=?",(identity,)).fetchone()
            return (item["mime"],item["payload"]) if item else None

    def import_images(self, source: dict) -> dict:
        if not isinstance(source,dict) or source.get("schema_version")!=1:
            raise ValueError("Expected versioned decoder-media JSON")
        entries=source.get("images",[])
        if not isinstance(entries,list) or len(entries)>MAX_MEDIA_IMPORT:
            raise ValueError("Image import limit exceeded")
        saved=[]
        for entry in entries:
            if not isinstance(entry,dict):
                raise ValueError("Each broadcast image must be a JSON object")
            saved.append(self.save(
                medium=entry.get("medium"),station=entry.get("station"),
                source_id=entry.get("source_id"),
                frequency_hz=entry.get("frequency_hz"),
                received_at=entry.get("received_at"),
                provenance=entry.get("provenance"),
                image_base64=entry.get("image_base64")))
        return {"images":len(saved)}


def rds2_image_group(data: dict) -> str | None:
    """redsea v1.2 RDS2 RFT output, not RadioVIS/Internet art."""
    rft=data.get("rft") if isinstance(data,dict) else None
    body=rft.get("data") if isinstance(rft,dict) else None
    item=body.get("file_contents") if isinstance(body,dict) else None
    return item if isinstance(item,str) and item else None
