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
import subprocess
import shutil
import stat
import sys

MARKER = ".media-preview-owner-v1"
MARKER_VALUE = "TIHULU_MEDIA_PREVIEW_OWNED_V1\n"
MANIFEST = ".media-preview-release.json"
SERIAL_LOCK = ".tihulu-media-stable-operations.lock"
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
            exact_owned_text(launcher, LAUNCH, "launcher")
        if desktop.exists() or desktop.is_symlink():
            exact_owned_text(desktop, desktop_text(home, root), "desktop entry")
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
        directory(releases, optional=True)
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
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
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
    validate_existing(home)
    fd = secure_lock(home)
    try:
        validate_existing(home)
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
