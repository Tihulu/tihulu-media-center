#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail-closed ownership audit and removal for the isolated Media preview.

The release manifests are generated from *built* files. Unknown files, changed
bytes, redirected links or incomplete staging refuse removal; user profile
data is always kept. No hardware, model or service actions.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

MARKER = ".media-preview-owner-v1"
MARKER_VALUE = "TIHULU_MEDIA_PREVIEW_OWNED_V1\n"
MANIFEST = ".media-preview-release.json"
RELEASE_NAME = re.compile(r"r-[0-9a-f]{12}-[0-9]{8}T[0-9]{6}-[0-9]+$")
LAUNCH = '''#!/bin/sh
set -eu
exec "$HOME/.local/opt/tihulu-media-stable/current/bin/tihulu-kaffeine" "$@"
'''


class SafetyError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise SafetyError(message)


def regular(path: Path, *, optional: bool = False) -> bool:
    try:
        st = path.lstat()
    except FileNotFoundError:
        if optional:
            return False
        fail(f"Missing owned file: {path}")
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid():
        fail(f"Not owned regular file: {path}")
    return True


def directory(path: Path, *, optional: bool = False) -> bool:
    try:
        st = path.lstat()
    except FileNotFoundError:
        if optional:
            return False
        fail(f"Missing owned directory: {path}")
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
        fail(f"Not owned real directory: {path}")
    return True


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_entries(root: Path):
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(folder) / name
            rel = path.relative_to(root).as_posix()
            st = path.lstat()
            if st.st_uid != os.geteuid():
                fail(f"Foreign owner in preview release: {rel}")
            if stat.S_ISDIR(st.st_mode):
                yield rel, {"type": "dir"}
            elif stat.S_ISREG(st.st_mode):
                yield rel, {"type": "file", "sha256": digest(path)}
            elif stat.S_ISLNK(st.st_mode):
                resolved = path.resolve(strict=False)
                if not resolved.is_relative_to(root.resolve()):
                    fail(f"Symlink escapes owned release: {rel}")
                yield rel, {"type": "link", "to": os.readlink(path)}
            else:
                fail(f"Unsupported special file: {rel}")


def release_manifest(root: Path) -> dict:
    directory(root)
    entries = dict(iter_entries(root))
    entries.pop(MANIFEST, None)
    return {"schema": 1, "entries": entries}


def prepare_release(root: Path) -> None:
    directory(root)
    target = root / MANIFEST
    if target.exists() or target.is_symlink():
        fail("Refusing existing release manifest")
    data = release_manifest(root)
    if not data["entries"].get("native/bin/kaffeine", {}).get("type") == "file":
        fail("Missing native executable")
    target.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    target.chmod(0o600)
    print(f"Recorded {len(data['entries'])} owned release entries")


def verify_release(root: Path) -> None:
    directory(root)
    manifest = root / MANIFEST
    regular(manifest)
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError) as exc:
        fail(f"Invalid release manifest: {exc}")
    if data.get("schema") != 1 or not isinstance(data.get("entries"), dict):
        fail("Invalid release manifest schema")
    actual = release_manifest(root)
    if actual != data:
        missing = set(data["entries"]) - set(actual["entries"])
        extra = set(actual["entries"]) - set(data["entries"])
        fail(f"Release file/sha/link changed: missing={sorted(missing)[:3]}, extra={sorted(extra)[:3]}")
    if not (root / "native/bin/kaffeine").is_file():
        fail("No native player in owned release")


def paths(home: Path):
    directory(home)
    # Never follow HOME/.local, HOME/.local/opt, or the owned launcher parents.
    for part in (".local", ".local/opt", ".local/bin", ".local/share",
                 ".local/share/applications"):
        directory(home / part, optional=True)
    root = home / ".local/opt/tihulu-media-stable"
    return root, home / ".local/bin/tihulu-media-stable", home / ".local/share/applications/tihulu-media-stable.desktop"


def verify_links(root: Path, names: set[str]) -> None:
    for name in ("current", "previous"):
        path = root / name
        if not (path.exists() or path.is_symlink()):
            continue
        if not path.is_symlink():
            fail(f"Non-symlink owned release pointer: {name}")
        dest = os.readlink(path)
        if dest not in names:
            fail(f"Unknown/outside owned release pointer: {name}")


def uninstall(home: Path) -> None:
    if os.geteuid() == 0:
        fail("Refusing root uninstall")
    root, launcher, desktop = paths(home)
    directory(root)
    marker = root / MARKER
    regular(marker)
    if marker.read_text() != MARKER_VALUE:
        fail("Wrong installer ownership marker")
    lock = root / ".install.lock"
    if lock.is_symlink() or (lock.exists() and not regular(lock)):
        fail("Unsafe installer lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        releases = root / "releases"
        exists = directory(releases, optional=True)
        names = {}
        for entry in releases.iterdir() if exists else ():
            if not RELEASE_NAME.fullmatch(entry.name):
                fail(f"Unknown release entry: {entry.name}")
            directory(entry)
            verify_release(entry)
            names[str(entry)] = entry
        verify_links(root, set(names))
        if launcher.exists() or launcher.is_symlink():
            regular(launcher)
            if launcher.read_text() != LAUNCH:
                fail("Launcher is modified/shared; refusing uninstall")
        if desktop.exists() or desktop.is_symlink():
            regular(desktop)
            if desktop.read_text() != desktop_text(home, root):
                fail("Desktop entry is modified/shared; refusing uninstall")
        allowed = {"releases", "current", "previous", ".install.lock", MARKER, "preview-home"}
        extra = set(p.name for p in root.iterdir()) - allowed
        if extra:
            fail(f"Unknown/incomplete install files in app root: {sorted(extra)}")
        profile = root / "preview-home"
        if profile.exists() or profile.is_symlink():
            directory(profile)
        # No deletion until *all* paths and contents pass ownership audit.
        for file in (launcher, desktop):
            if file.exists():
                file.unlink()
        for name in ("current", "previous"):
            pointer = root / name
            if pointer.is_symlink():
                pointer.unlink()
        for release in names.values():
            shutil.rmtree(release)
        if exists:
            releases.rmdir()
        # Deliberately preserve ownership marker and lock for safe reinstall.
        # Deliberately retain preview-home: may contain recordings, settings,
        # model selections or user data. Do not auto-purge or import them.
        if profile.exists():
            print(f"Preserved private preview settings/data: {profile}")
        print("Owned preview launcher, desktop entry and built releases removed.")
    finally:
        os.close(fd)


def desktop_text(home: Path, root: Path) -> str:
    launcher = home / ".local/bin/tihulu-media-stable"
    return f"""[Desktop Entry]
Type=Application
Name=TIHULU Media Center (Stable-First Preview)
GenericName=TV · DAB+ · Radio · AI subtitles
Exec={launcher}
TryExec={launcher}
Icon={root}/current/py/kaffeine_next/assets/tihulu-media-center.svg
StartupWMClass=tihulu-media-center
Terminal=false
Categories=AudioVideo;Video;TV;Audio;Player;
X-TIHULU-StableFirst=true
"""


def main() -> int:
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "prepare-release":
            prepare_release(Path(sys.argv[2]))
        elif len(sys.argv) == 2 and sys.argv[1] == "uninstall":
            uninstall(Path.home())
        else:
            fail("Usage: preview_safety.py prepare-release STAGE | uninstall")
    except (SafetyError, BlockingIOError, OSError) as exc:
        print(f"PREVIEW-SAFETY HOLD: {exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
