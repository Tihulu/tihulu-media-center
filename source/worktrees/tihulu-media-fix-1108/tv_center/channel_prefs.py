"""Per-profile channel manager: favorites, inclusion, reordering and scan review.

Never overwrite genuine scan data; only metadata for scanned service IDs is
stored. Safe writes are atomic and confined to a user-owned preferences file.
"""
from __future__ import annotations
from pathlib import Path
import json
import os
import tempfile

def profile_key(country: str, medium: str, satellite: str = "") -> str:
    if country not in ("DE", "TR") or medium not in ("t", "c", "s"):
        raise ValueError("Invalid channel profile")
    if medium == "s":
        from .satellite import SATELLITES
        if satellite not in SATELLITES:
            raise ValueError("Unsupported orbital position")
        return country + "-s-" + satellite
    return country + "-" + medium

def channel_key(channel) -> str:
    return "%s:%s:%s:%s" % (channel.frequency, channel.service_id,
                           getattr(channel, "delivery", ""), channel.name.casefold())

def service_type(channel) -> str:
    return getattr(channel, "kind", "tv")

class ChannelPreferences:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or Path.home()/".config/tihulu-tv-center/channel-preferences.json")
        self.data = {"version": 1, "profiles": {}}
        if self.path.is_file():
            if self.path.stat().st_size > 2_000_000:
                raise ValueError("Oversized channel preferences")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") != 1 or not isinstance(raw.get("profiles"), dict):
                raise ValueError("Invalid channel preferences version")
            self.data = raw

    def rows(self, profile: str, channels) -> list[dict]:
        saved = self.data["profiles"].get(profile, {})
        entries = saved.get("entries", {})
        seen_before = bool(saved.get("initialized", False))
        result = []
        for index, channel in enumerate(channels):
            key = channel_key(channel)
            row = entries.get(key, {})
            result.append({"key": key, "channel": channel,
                           "name": channel.name, "kind": service_type(channel),
                           "encrypted": channel.encrypted,
                           "favorite": bool(row.get("favorite", False)),
                           "included": bool(row.get("included", not seen_before)),
                           "order": int(row.get("order", index + 10000)),
                           "new": seen_before and key not in entries})
        return sorted(result, key=lambda row: (row["order"], row["name"].casefold()))

    def save_rows(self, profile: str, rows: list[dict]):
        if len(rows) > 5000:
            raise ValueError("Too many scanned channels")
        entries = {}
        for n, row in enumerate(rows):
            key = row["key"]
            if not isinstance(key, str) or len(key) > 280 or key in entries:
                raise ValueError("Invalid channel identifier")
            if type(row["favorite"]) is not bool or type(row["included"]) is not bool:
                raise ValueError("Invalid channel preferences")
            entries[key] = {"included": row["included"], "favorite": row["favorite"],
                            "order": n}
        self.data["profiles"][profile] = {"initialized": True, "entries": entries}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                         prefix=".channelprefs-", delete=False) as out:
            temporary = Path(out.name)
            json.dump(self.data, out, ensure_ascii=False, indent=2)
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def update(self, profile: str, rows: list[dict], key: str,
               action: str) -> list[dict]:
        pos = next((i for i, row in enumerate(rows) if row["key"] == key), -1)
        if pos == -1:
            raise KeyError("Unknown scanned channel")
        if action == "favorite":
            rows[pos]["favorite"] = not rows[pos]["favorite"]
        elif action == "included":
            rows[pos]["included"] = not rows[pos]["included"]
        elif action in ("up", "down"):
            other = pos + (-1 if action == "up" else 1)
            if 0 <= other < len(rows):
                rows[pos], rows[other] = rows[other], rows[pos]
        else:
            raise ValueError("Unknown channel action")
        self.save_rows(profile, rows)
        return rows
