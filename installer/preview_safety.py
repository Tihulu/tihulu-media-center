#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail-closed ownership audit and removal for the isolated Media preview.

The release manifests are generated from *built* files. Unknown files, changed
bytes, redirected links or incomplete staging refuse removal; user profile
data is always kept. No hardware, model or service actions.
"""
from __future__ import annotations

import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import stat
import sys

MARKER = ".media-preview-owner-v1"
MARKER_VALUE = "TIHULU_MEDIA_PREVIEW_OWNED_V1\n"
MANIFEST = ".media-preview-release.json"
SERIAL_LOCK = ".tihulu-media-stable-operations.lock"
UNINSTALL_TXN = ".media-uninstall-transaction-v1"
TXN_PLAN = "plan.json"
TXN_COMMITTED = "committed"
TXN_COMMIT_TEXT = "TIHULU_MEDIA_UNINSTALL_COMMITTED_V1\n"

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
    if st.st_mode & 0o022:
        fail(f"Insecure group/other-writable managed directory: {path}")
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
                if st.st_mode & 0o022:
                    fail(f"Writable release directory: {rel}")
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


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_owned_exclusive(path: Path, value: bytes) -> None:
    directory(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(os.dup(fd), "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    _sync_dir(path.parent)


def _rename_noreplace(srcfd: int, src: str, dstfd: int, dst: str) -> None:
    """Linux renameat2(NO_REPLACE): never overwrite a raced destination."""
    libc = ctypes.CDLL(None, use_errno=True)
    operation = getattr(libc, "renameat2", None)
    if operation is None:
        fail("Linux renameat2(NO_REPLACE) unavailable: refusing unsafe rename")
    operation.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                          ctypes.c_char_p, ctypes.c_uint)
    operation.restype = ctypes.c_int
    # RENAME_NOREPLACE=1. No shell-based mv and no overwrite fallback.
    if operation(srcfd, os.fsencode(src), dstfd, os.fsencode(dst), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), f"{src} -> {dst}")


def _known_uninstall_paths(root: Path, launcher: Path, desktop: Path) -> dict:
    return {"launcher": launcher, "desktop": desktop,
            "current": root / "current", "previous": root / "previous"}


def _expected_uninstall_content(home: Path, root: Path, plan: dict, slot: str) -> str:
    if slot == "launcher":
        return LAUNCH
    if slot == "desktop":
        return desktop_text(home, root)
    return plan["pointers"][slot]


def _audit_before_uninstall(home: Path, root: Path, launcher: Path, desktop: Path) -> dict:
    """All old checks happen before the transaction directory is created."""
    directory(root)
    exact_owned_text(root / MARKER, MARKER_VALUE, "owner marker")
    release_parent = root / "releases"
    existing_releases = directory(release_parent, optional=True)
    names = []
    if existing_releases:
        for entry in release_parent.iterdir():
            if not RELEASE_NAME.fullmatch(entry.name):
                fail(f"Unknown release entry: {entry.name}")
            directory(entry)
            verify_release(entry)
            names.append(entry.name)
    names.sort()
    expected_targets = {str(release_parent / n) for n in names}
    verify_links(root, expected_targets)
    entrypoints = {}
    for name, path in (("launcher", launcher), ("desktop", desktop)):
        entrypoints[name] = present(path)
        if entrypoints[name]:
            exact_owned_text(path, LAUNCH if name == "launcher" else
                             desktop_text(home, root), name)
    if entrypoints["launcher"] != entrypoints["desktop"]:
        fail("Incomplete launcher and desktop pair")
    pointers = {}
    for key in ("current", "previous"):
        link = root / key
        pointers[key] = os.readlink(link) if present(link) else None
    allowed = {"releases", "current", "previous", ".install.lock",
               MARKER, "preview-home"}
    extras = {entry.name for entry in root.iterdir()} - allowed
    if extras:
        fail(f"Unknown/incomplete install files in app root: {sorted(extras)}")
    directory(root / "preview-home", optional=True)
    return {"schema": 1, "releases": names, "had_releases": existing_releases,
            "entrypoints": entrypoints, "pointers": pointers}


def _read_uninstall_plan(root: Path) -> dict:
    txn = root / UNINSTALL_TXN
    directory(txn)
    expected = {TXN_PLAN, TXN_COMMITTED, "launcher", "desktop", "current", "previous"}
    unknown = {p.name for p in txn.iterdir()} - expected
    if unknown:
        fail(f"Unknown private data in uninstall transaction: {sorted(unknown)}")
    plan_file = txn / TXN_PLAN
    regular(plan_file)
    if plan_file.lstat().st_nlink != 1:
        fail("Hardlinked uninstall transaction plan")
    try:
        data = json.loads(plan_file.read_bytes())
    except (OSError, ValueError) as exc:
        fail(f"Malformed uninstall transaction plan: {exc}")
    if not isinstance(data, dict) or set(data) != {
            "schema", "releases", "had_releases", "entrypoints", "pointers"}:
        fail("Unexpected uninstall transaction schema")
    names = data["releases"]
    if (data["schema"] != 1 or not isinstance(names, list)
            or any(not isinstance(n, str) or not RELEASE_NAME.fullmatch(n)
                   for n in names)
            or names != sorted(set(names))
            or type(data["had_releases"]) is not bool):
        fail("Untrusted release names in uninstall transaction")
    if (data["entrypoints"] is None or set(data["entrypoints"]) != {"launcher", "desktop"}
            or any(type(v) is not bool for v in data["entrypoints"].values())):
        fail("Invalid uninstall entrypoint plan")
    if set(data["pointers"]) != {"current", "previous"}:
        fail("Invalid uninstall release pointer plan")
    expected_targets = {str(root / "releases" / n) for n in names}
    for value in data["pointers"].values():
        if value is not None and (not isinstance(value, str) or value not in expected_targets):
            fail("Untrusted release pointer in uninstall plan")
    if not data["had_releases"] and names:
        fail("Missing planned release root")
    if present(txn / TXN_COMMITTED):
        exact_owned_text(txn / TXN_COMMITTED, TXN_COMMIT_TEXT, "uninstall commit")
    return data


def validate_uninstall_recovery(home: Path) -> None:
    """Read-only gate for EXPLICIT --uninstall with an existing known plan."""
    root, launcher, desktop = paths(home)
    directory(root)
    exact_owned_text(root / MARKER, MARKER_VALUE, "owner marker")
    txn = root / UNINSTALL_TXN
    directory(txn)
    _read_uninstall_plan(root)
    allowed = {"releases", "current", "previous", ".install.lock",
               MARKER, "preview-home", UNINSTALL_TXN}
    extras = {entry.name for entry in root.iterdir()} - allowed
    if extras:
        fail(f"Foreign files obstruct uninstall recovery: {sorted(extras)}")
    directory(root / "releases", optional=True)
    directory(root / "preview-home", optional=True)
    directory(launcher.parent)
    directory(desktop.parent)


def _stage_uninstall_path(home: Path, root: Path, plan: dict, slot: str) -> None:
    """Quarantine a verified INODE by no-replace rename; no destructive unlink.

    A raced foreign inode is never deleted. Attempt a non-overwriting reversal;
    any ambiguity is a permanent HOLD pending owner inspection.
    """
    source = _known_uninstall_paths(root, home / ".local/bin/tihulu-media-stable",
                                    home / ".local/share/applications/tihulu-media-stable.desktop")[slot]
    destination = root / UNINSTALL_TXN / slot
    exists = (plan["entrypoints"][slot] if slot in ("launcher", "desktop")
              else plan["pointers"][slot] is not None)
    if not exists:
        if present(source) or present(destination):
            fail(f"Unplanned file appeared during uninstall: {slot}")
        return
    expected = _expected_uninstall_content(home, root, plan, slot)
    if present(destination):
        if present(source):
            fail(f"Duplicate live/staged uninstall entry: {slot}")
        if slot in ("launcher", "desktop"):
            exact_owned_text(destination, expected, slot)
        elif not destination.is_symlink() or os.readlink(destination) != expected:
            fail(f"Modified quarantined pointer: {slot}")
        return
    if not present(source):
        fail(f"Missing live/staged uninstall entry: {slot}")
    directory(source.parent)
    directory(destination.parent)
    if slot in ("launcher", "desktop"):
        exact_owned_text(source, expected, slot)
    elif not source.is_symlink() or os.readlink(source) != expected:
        fail(f"Modified release pointer: {slot}")
    source_fd = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    target_fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    pinned_fd = -1
    try:
        original_parent = source.parent.lstat()
        if (original_parent.st_dev, original_parent.st_ino) != (
                os.fstat(source_fd).st_dev, os.fstat(source_fd).st_ino):
            fail(f"Replaced parent before quarantine: {slot}")
        if slot in ("launcher", "desktop"):
            pinned_fd = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW,
                                dir_fd=source_fd)
            pinned = os.fstat(pinned_fd)
            if (not stat.S_ISREG(pinned.st_mode) or pinned.st_uid != os.geteuid()
                    or pinned.st_nlink != 1 or pinned.st_mode & 0o022):
                fail(f"Foreign entrypoint before quarantine: {slot}")
            with os.fdopen(os.dup(pinned_fd), "rb") as stream:
                if stream.read() != expected.encode():
                    fail(f"Modified entrypoint before quarantine: {slot}")
        else:
            pinned = os.stat(source.name, dir_fd=source_fd, follow_symlinks=False)
            if not stat.S_ISLNK(pinned.st_mode):
                fail(f"Foreign pointer before quarantine: {slot}")
        _rename_noreplace(source_fd, source.name, target_fd, destination.name)
        moved = os.stat(destination.name, dir_fd=target_fd, follow_symlinks=False)
        if (moved.st_ino, moved.st_dev) != (pinned.st_ino, pinned.st_dev):
            # Do not unlink/delete the substituted file. Best effort reversal
            # guarded by no-replace; if it fails leave journal and HOLD.
            try:
                _rename_noreplace(target_fd, destination.name, source_fd, source.name)
            finally:
                fail(f"Entrypoint/pointer inode changed during quarantine: {slot}")
        if slot in ("launcher", "desktop"):
            exact_owned_text(destination, expected, slot)
        elif os.readlink(destination) != expected:
            fail(f"Pointer text changed during quarantine: {slot}")
        os.fsync(source_fd)
        os.fsync(target_fd)
    finally:
        if pinned_fd >= 0:
            os.close(pinned_fd)
        os.close(source_fd)
        os.close(target_fd)


def _stage_all_uninstall(home: Path, root: Path, plan: dict) -> None:
    txn = root / UNINSTALL_TXN
    for slot in ("launcher", "desktop", "current", "previous"):
        _stage_uninstall_path(home, root, plan, slot)
    expected = set(plan["releases"])
    releases = root / "releases"
    if directory(releases, optional=True):
        actual = {p.name for p in releases.iterdir()}
        if actual != expected:
            fail(f"Release set changed during uninstall stage: {sorted(actual ^ expected)}")
        for name in sorted(expected):
            verify_release(releases / name)
    elif plan["had_releases"]:
        fail("Release root vanished before uninstall commit")
    if not present(txn / TXN_COMMITTED):
        _write_owned_exclusive(txn / TXN_COMMITTED, TXN_COMMIT_TEXT.encode())
        _sync_dir(root)


def _committed_uninstall_cleanup(home: Path, root: Path, plan: dict) -> None:
    """Irreversible phase; a failure leaves a COMMITTED journal to resume.

    Never auto-delete a partially modified release or unknown/private files.
    """
    txn = root / UNINSTALL_TXN
    exact_owned_text(txn / TXN_COMMITTED, TXN_COMMIT_TEXT, "uninstall commit")
    for slot, path in _known_uninstall_paths(
            root, home / ".local/bin/tihulu-media-stable",
            home / ".local/share/applications/tihulu-media-stable.desktop").items():
        if present(path):
            fail(f"Committed uninstall unexpectedly has live entry: {slot}")
    releases = root / "releases"
    if directory(releases, optional=True):
        actual = {p.name for p in releases.iterdir()}
        if not actual <= set(plan["releases"]):
            fail(f"Unexpected release obstructs uninstall cleanup: {sorted(actual - set(plan['releases']))}")
        releases_fd = os.open(releases, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(releases_fd)
            for name in plan["releases"]:
                current_parent = releases.lstat()
                if (current_parent.st_dev, current_parent.st_ino) != (
                        opened.st_dev, opened.st_ino):
                    fail("Release parent replaced while removing releases")
                release = releases / name
                if not present(release):
                    continue  # Already irrevocably removed in an earlier attempt.
                directory(releases)
                verify_release(release)
                lstat = release.lstat()
                pinned = os.stat(name, dir_fd=releases_fd, follow_symlinks=False)
                if ((lstat.st_dev, lstat.st_ino) != (pinned.st_dev, pinned.st_ino)
                        or not stat.S_ISDIR(pinned.st_mode)):
                    fail("Release substituted between verification and deletion")
                parent = releases.lstat()
                if (parent.st_dev, parent.st_ino) != (opened.st_dev, opened.st_ino):
                    fail("Release parent switched before deletion")
                shutil.rmtree(name, dir_fd=releases_fd)
                # Do not continue if another same-UID actor replaced the
                # visible releases parent during a destructive operation.
                after = releases.lstat()
                if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
                    fail("Release parent replaced during committed cleanup")
                os.fsync(releases_fd)
        finally:
            os.close(releases_fd)
        if any(releases.iterdir()):
            fail("Nonempty release root after committed cleanup")
        releases.rmdir()
        _sync_dir(root)
    elif plan["had_releases"] and any((root / "releases" / n).exists()
                                      for n in plan["releases"]):
        fail("Inconsistent committed release directory")
    # Only after *all* verified releases are gone may quarantined
    # entrypoints be unlinked. The original live paths remain absent.
    for slot in ("launcher", "desktop"):
        path = txn / slot
        if present(path):
            exact_owned_text(path, _expected_uninstall_content(home, root, plan, slot), slot)
            unlink_verified_entrypoint(path,
                _expected_uninstall_content(home, root, plan, slot))
    for slot in ("current", "previous"):
        pointer = txn / slot
        if present(pointer):
            if not pointer.is_symlink() or os.readlink(pointer) != plan["pointers"][slot]:
                fail(f"Modified staged release pointer: {slot}")
            pointer.unlink()
    # If interrupted while deleting journal metadata, refuse future cleanup
    # of any unknown path; no owner profile is ever removed automatically.
    (txn / TXN_COMMITTED).unlink()
    (txn / TXN_PLAN).unlink()
    txn.rmdir()
    _sync_dir(root)
    print("Owned preview launcher, desktop entry and built releases removed.")
    if directory(root / "preview-home", optional=True):
        print(f"Preserved private preview settings/data: {root / 'preview-home'}")


def _resume_uninstall(home: Path, root: Path) -> None:
    validate_uninstall_recovery(home)
    plan = _read_uninstall_plan(root)
    committed = present(root / UNINSTALL_TXN / TXN_COMMITTED)
    if not committed:
        _stage_all_uninstall(home, root, plan)
    _committed_uninstall_cleanup(home, root, plan)


def uninstall(home: Path) -> None:
    if os.geteuid() == 0:
        fail("Refusing root uninstall")
    root, launcher, desktop = paths(home)
    directory(root)
    exact_owned_text(root / MARKER, MARKER_VALUE, "owner marker")
    lock = root / ".install.lock"
    if present(lock):
        regular(lock)
        if lock.lstat().st_nlink != 1:
            fail("Hardlinked legacy install lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        txn = root / UNINSTALL_TXN
        if present(txn):
            _resume_uninstall(home, root)
            return
        plan = _audit_before_uninstall(home, root, launcher, desktop)
        # Recheck after audit before any entrypoint is quarantined. If a
        # manifest was modified during first verification, NOTHING is moved.
        for name in plan["releases"]:
            verify_release(root / "releases" / name)
        txn.mkdir(mode=0o700)
        _sync_dir(root)
        _write_owned_exclusive(txn / TXN_PLAN, (json.dumps(
            plan, sort_keys=True, separators=(",", ":")) + "\n").encode())
        _stage_all_uninstall(home, root, plan)
        _committed_uninstall_cleanup(home, root, plan)
    finally:
        os.close(fd)


def unlink_verified_entrypoint(path: Path, expected: str) -> None:
    """Final unlink is allowed ONLY inside the owned, committed quarantine.

    Pin the regular file on O_NOFOLLOW fd; verify its entire bytes and inode
    both before and immediately before unlink. POSIX unlinkat is pathname-
    based, so a hostile same-UID inode swap *after* the final stat remains
    outside this limited guarantee and is a documented full-security HOLD.
    """
    if path.parent.name != UNINSTALL_TXN:
        fail("Refusing live-path unlink outside committed uninstall transaction")
    directory(path.parent)
    exact_owned_text(path.parent / TXN_COMMITTED, TXN_COMMIT_TEXT, "uninstall commit")
    pfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    opened_file = -1
    try:
        parent = path.parent.lstat()
        pinned_parent = os.fstat(pfd)
        if (parent.st_ino, parent.st_dev) != (pinned_parent.st_ino, pinned_parent.st_dev):
            fail("Quarantine parent replaced before unlink")
        opened_file = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=pfd)
        pinned = os.fstat(opened_file)
        if (not stat.S_ISREG(pinned.st_mode) or pinned.st_uid != os.geteuid()
                or pinned.st_nlink != 1 or pinned.st_mode & 0o022):
            fail("Untrusted quarantined entrypoint inode")
        with os.fdopen(os.dup(opened_file), "rb") as stream:
            if stream.read() != expected.encode():
                fail("Modified quarantined entrypoint content")
        exact_owned_text(path, expected, path.name)
        current = os.stat(path.name, dir_fd=pfd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
            fail("Quarantined entrypoint replaced before unlink")
        os.unlink(path.name, dir_fd=pfd)
        os.fsync(pfd)
    finally:
        if opened_file >= 0:
            os.close(opened_file)
        os.close(pfd)

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



def present(path: Path) -> bool:
    """lstat-based existence: dangling symlinks are NEVER treated as missing."""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def exact_owned_text(path: Path, expected: str, label: str) -> None:
    """Compare whole bytes on O_NOFOLLOW fd and reject foreign/hardlinked files."""
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
            or before.st_nlink != 1 or before.st_mode & 0o022):
        fail(f"Foreign, linked or writable {label}: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        if (opened.st_ino != before.st_ino or opened.st_dev != before.st_dev
                or opened.st_uid != os.geteuid() or opened.st_nlink != 1
                or not stat.S_ISREG(opened.st_mode)):
            fail(f"Replaced or foreign {label}: {path}")
        with os.fdopen(os.dup(fd), "rb") as stream:
            value = stream.read()
        after = path.lstat()
        if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
            fail(f"Replaced {label} during verification: {path}")
        if value != expected.encode("utf-8"):
            fail(f"Modified {label}; refusing to overwrite: {path}")
    finally:
        os.close(fd)


def validate_existing(home: Path, *, allow_build: bool = False) -> None:
    """READ-ONLY check, including on initial install, before lock creation."""
    try:
        root, launcher, desktop = paths(home)
    except SafetyError as exc:
        fail(f"Unsafe rollback parent or install parent: {exc}")
    root_exists = directory(root, optional=True)
    if root_exists:
        marker = root / MARKER
        if not present(marker):
            fail("Missing installer ownership marker")
        exact_owned_text(marker, MARKER_VALUE, "installer ownership marker")
        old_lock = root / ".install.lock"
        if present(old_lock):
            regular(old_lock)
            if old_lock.stat().st_nlink != 1:
                fail("Hardlinked legacy install lock")
        releases = root / "releases"
        release_names = set()
        if directory(releases, optional=True):
            for entry in releases.iterdir():
                if not RELEASE_NAME.fullmatch(entry.name):
                    fail(f"Unknown or interrupted release directory: {entry.name}")
                directory(entry)
                verify_release(entry)
                release_names.add(str(entry))
        # Existing release links must already target fully verified releases,
        # before the installer stages or builds anything new.
        verify_links(root, release_names)
        profile = root / "preview-home"
        directory(profile, optional=True)
        if present(profile):
            for part in (".config", ".local", ".local/share", ".cache", ".local/state"):
                directory(profile / part, optional=True)
        # Incomplete/suspicious stages are never swept up or silently resumed.
        if not allow_build:
            extra = [p.name for p in root.iterdir()
                     if p.name not in {"releases", "current", "previous",
                                       ".install.lock", MARKER, "preview-home"}]
            if extra:
                fail(f"Ambiguous/incomplete preview root: {sorted(extra)}")
        for pointer in ("current", "previous"):
            p = root / pointer
            if present(p) and not p.is_symlink():
                fail(f"Foreign release pointer: {pointer}")
    elif present(root):
        fail("Existing application root is not a real owned directory")
    launch_exists, desktop_exists = present(launcher), present(desktop)
    if launch_exists != desktop_exists:
        fail("Incomplete launcher/desktop pair; manual owner review required")
    if launch_exists:
        if not root_exists:
            fail("Orphaned launcher/desktop not owned by an installation")
        exact_owned_text(launcher, LAUNCH, "launcher")
        exact_owned_text(desktop, desktop_text(home, root), "desktop entry")
    # Refuse a present executable entrypoint with no source release pointer.
    if launch_exists and not present(root / "current") and not present(root / "previous"):
        # A first-release rollback intentionally deactivates current. It leaves
        # releases available; permit that fully-owned case for reinstallation.
        if not directory(root / "releases", optional=True) or not any((root / "releases").iterdir()):
            fail("Entrypoint exists without a valid owned release")


def secure_lock(home: Path) -> int:
    """Per-app sibling lock predates APPROOT, so install/uninstall share it."""
    for part in (home / ".local", home / ".local/opt"):
        if not present(part):
            part.mkdir(mode=0o700)
        directory(part)
    lock = home / ".local/opt" / SERIAL_LOCK
    # Open lock relative to a verified directory FD; pathname substitution
    # cannot redirect open() through a new symlinked lock-parent directory.
    parent = lock.parent
    directory(parent)
    parentfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened_parent, pathname_parent = os.fstat(parentfd), parent.lstat()
        if (opened_parent.st_dev, opened_parent.st_ino) != (pathname_parent.st_dev, pathname_parent.st_ino):
            fail("Operations lock parent was replaced before opening")
        fd = os.open(SERIAL_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parentfd)
    finally:
        os.close(parentfd)
    try:
        directory(parent)
        st, pathst = os.fstat(fd), lock.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid()
                or st.st_nlink != 1 or st.st_mode & 0o077
                or (st.st_dev, st.st_ino) != (pathst.st_dev, pathst.st_ino)):
            fail("Foreign, hardlinked, or insecure operations lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("Another Media install, rollback or uninstall is active")
        if (lock.lstat().st_dev, lock.lstat().st_ino) != (st.st_dev, st.st_ino):
            fail("Operations lock replaced during acquisition")
        return fd
    except BaseException:
        os.close(fd)
        raise


def verify_guard(home: Path, fd: int) -> None:
    # Recheck ancestors on every mutating CLI boundary, not just the lock
    # inode: a renamed or writable parent invalidates the guard.
    root, _, _ = paths(home)
    directory(root, optional=True)
    directory(root / "releases", optional=True)
    lock = home / ".local/opt" / SERIAL_LOCK
    opened, current = os.fstat(fd), lock.lstat()
    if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1 or opened.st_mode & 0o077
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)):
        fail("Missing/insecure inherited operations lock")
    # Re-locking the SAME inherited open file description is idempotent.
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fail("Operations lock descriptor is not owned by this operation")


def guard_command(home: Path, command: list[str], *, inherited_env: dict | None = None) -> int:
    if os.geteuid() == 0:
        fail("Refusing root operation")
    # A committed or interrupted explicit uninstall has an owned transaction
    # record. Install/rollback stay blocked until that transaction is resolved.
    root = home / ".local/opt/tihulu-media-stable"
    recovering = (command[-1] in ("uninstall", "--uninstall")
                  and present(root / UNINSTALL_TXN))
    gate = validate_uninstall_recovery if recovering else validate_existing
    gate(home)
    fd = secure_lock(home)
    try:
        gate(home)
        env = dict(os.environ if inherited_env is None else inherited_env)
        env["TIHULU_MEDIA_GUARD_FD"] = str(fd)
        # FD remains open in child while this parent holds the same lock until
        # the *entire* build, rollback, or uninstall finishes.
        return subprocess.run(command, env=env, pass_fds=(fd,), check=False).returncode
    finally:
        os.close(fd)


def publish_entrypoints(home: Path) -> None:
    """Never truncate/overwrite: create exact files with exclusive open only."""
    validate_existing(home, allow_build=True)
    root, launcher, desktop = paths(home)
    directory(root)
    for path, expected, mode in ((launcher, LAUNCH, 0o755),
                                 (desktop, desktop_text(home, root), 0o644)):
        directory(path.parent)
        if present(path):
            exact_owned_text(path, expected, path.name)
            continue
        # O_EXCL defeats the post-check symlink/file replacement race.
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
        try:
            os.fchmod(fd, mode)
            with os.fdopen(os.dup(fd), "wb") as stream:
                stream.write(expected.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        exact_owned_text(path, expected, path.name)
    validate_existing(home, allow_build=True)

def main() -> int:
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "prepare-release":
            prepare_release(Path(sys.argv[2]))
        elif len(sys.argv) == 3 and sys.argv[1] == "verify-release":
            # Read-only gate used for rollback and any existing current pointer.
            verify_release(Path(sys.argv[2]))
        elif len(sys.argv) == 2 and sys.argv[1] == "uninstall":
            fd = os.environ.get("TIHULU_MEDIA_GUARD_FD")
            if fd is None:
                return guard_command(Path.home(), [sys.executable, str(Path(__file__).resolve()), "uninstall"])
            verify_guard(Path.home(), int(fd))
            uninstall(Path.home())
        elif len(sys.argv) == 2 and sys.argv[1] == "preflight-install":
            validate_existing(Path.home())
        elif len(sys.argv) == 2 and sys.argv[1] == "publish-entrypoints":
            fd = os.environ.get("TIHULU_MEDIA_GUARD_FD")
            if fd is None:
                fail("Publishing launchers requires locked installer operation")
            verify_guard(Path.home(), int(fd))
            publish_entrypoints(Path.home())
        elif len(sys.argv) == 3 and sys.argv[1] == "verify-guard":
            verify_guard(Path.home(), int(sys.argv[2]))
        elif len(sys.argv) >= 4 and sys.argv[1] == "guarded-exec":
            return guard_command(Path.home(), ["bash", sys.argv[2], *sys.argv[3:]])
        else:
            fail("Usage: preview_safety.py prepare-release STAGE | verify-release RELEASE | uninstall")
    except (SafetyError, BlockingIOError, OSError, ValueError) as exc:
        print(f"PREVIEW-SAFETY HOLD: {exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
