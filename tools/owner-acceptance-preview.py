#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Owner-operated preview: writable private profile, read-only host filesystem.

The owner's display, audio, network and receivers are intentionally shared for
acceptance. A private D-Bus prevents activating the installed player. This is
not the RF/device-isolated automated test runner and never installs anything.
"""
import argparse
import os
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--asset-home", type=Path, default=Path.home())
    parser.add_argument("media", nargs="*")
    options = parser.parse_args()
    native = options.native.resolve(strict=True)
    source = options.source.resolve(strict=True)
    state = options.state.absolute()
    if not native.is_file() or not os.access(native, os.X_OK):
        parser.error("Compiled candidate executable is missing")
    if not (source / "tv_center/__main__.py").is_file():
        parser.error("Candidate Python companion is missing")
    if state.is_symlink() or state.resolve() in (Path.home().resolve(), Path("/")):
        parser.error("Choose a dedicated private preview directory")
    marker = state / ".tihulu-owner-preview"
    if state.exists() and any(state.iterdir()) and not marker.is_file():
        parser.error("Preview directory already contains unrelated files")
    if not Path("/usr/bin/bwrap").is_file() or not Path("/usr/bin/dbus-run-session").is_file():
        parser.error("bubblewrap and dbus-run-session are required for this preview")
    os.umask(0o077)
    state.mkdir(parents=True, exist_ok=True)
    marker.write_text("TIHULU owner acceptance profile\n", encoding="utf-8")
    for rel in (".config", ".cache", ".local/share", ".local/state", ".run", "bin", "Videos", "Music"):
        (state / rel).mkdir(exist_ok=True, parents=True)
    shim = state / "bin/tihulu-tv-center"
    shim.write_text('#!/bin/sh\nexec /usr/bin/python3 -m tv_center "$@"\n')
    shim.chmod(0o700)
    real_runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env = {key: value for key, value in os.environ.items() if key in
           ("DISPLAY", "XAUTHORITY", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "USER", "LOGNAME")}
    # Keep the private runtime path short: AF_UNIX sun_path is bounded by the
    # platform (Linux 108 bytes). A very long project path must not break
    # Kaffeine's loopback caption/recording sockets in owner acceptance.
    runtime = f"/tmp/tihulu-owner-{os.getuid()}"
    env.update(HOME=str(state), XDG_CONFIG_HOME=str(state / ".config"),
               XDG_DATA_HOME=str(state / ".local/share"), XDG_CACHE_HOME=str(state / ".cache"),
               XDG_STATE_HOME=str(state / ".local/state"), XDG_RUNTIME_DIR=runtime,
               KDEHOME=str(state / ".kde"), PYTHONPATH=str(source),
               PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1",
               PATH=str(state / "bin") + ":/usr/bin:/bin", QT_QPA_PLATFORM="xcb",
               QT_X11_NO_MITSHM="1", TIHULU_ASSET_HOME=str(options.asset_home.resolve()),
               DBUS_SYSTEM_BUS_ADDRESS="unix:path=/nonexistent-tihulu-test-system-bus",
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    # Keep the desktop sound server attached. The application keeps a private
    # short XDG_RUNTIME_DIR for its own sockets, not the session sound socket.
    env["PULSE_SERVER"] = os.environ.get(
        "PULSE_SERVER", "unix:" + str(Path(real_runtime, "pulse/native")))
    env["PIPEWIRE_RUNTIME_DIR"] = real_runtime
    # The private /tmp is a fresh tmpfs; create the short runtime directory
    # inside it with strict 0700 permissions instead of bwrap's 0755 --dir.
    inner = ('umask 077; mkdir -p "$1"; chmod 700 "$1"; shift; '
             'exec /usr/bin/dbus-run-session -- "$@"')
    cmd = ["/usr/bin/bwrap", "--die-with-parent", "--new-session", "--unshare-pid",
           "--ro-bind", "/", "/", "--proc", "/proc", "--dev-bind", "/dev", "/dev",
           "--tmpfs", "/tmp", "--bind", str(state), str(state),
           "--chdir", str(state)]
    # Argos extracts stanzas while translating. Reuse the existing installed
    # packages, but keep their own directory writable exactly like the real app.
    argos_packages = options.asset_home.resolve() / ".local/share/argos-translate/packages"
    if argos_packages.is_dir():
        cmd += ["--bind", str(argos_packages), str(argos_packages)]
    if Path("/tmp/.X11-unix").is_dir():
        cmd += ["--ro-bind", "/tmp/.X11-unix", "/tmp/.X11-unix"]
    # Xauthority may live in /tmp on some desktops; preserve only that file.
    auth = env.get("XAUTHORITY", "")
    if auth.startswith("/tmp/") and Path(auth).is_file():
        cmd += ["--ro-bind", auth, auth]
    # Explicit environment overrides remain useful for software/no-audio diagnosis.
    if os.environ.get("TIHULU_VLC_PROFILE") in ("auto", "software", "software-no-audio"):
        env["TIHULU_VLC_PROFILE"] = os.environ["TIHULU_VLC_PROFILE"]
    cmd += ["--", "/bin/sh", "-c", inner, "tihulu-preview", runtime,
            str(native), *options.media]
    print("Preview settings/recordings:", state, flush=True)
    print("Existing models: read-only. Display/audio/network/receivers: shared for owner testing.", flush=True)
    os.execve(cmd[0], cmd, env)


if __name__ == "__main__":
    main()
