# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional local player inventory for the AI Model Market.

No engine is ever embedded in this application and nothing is installed without
an explicit owner action. When mpv is already present (system-wide or in the
private TIHULU tools directory) the player options in the app use it; the Market
shows the status and offers the distribution command plus a terminal launcher,
so the password prompt stays with the owner.
"""
from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path


def local_player_dir() -> Path:
    from .local_assets import existing_asset
    return existing_asset(
        Path.home() / ".local/share/TIHULU/tihulu-media-center/tools")


def system_player(name: str) -> str:
    found = shutil.which(name)
    return found or ""


def local_player(name: str) -> str:
    candidate = local_player_dir() / name
    return str(candidate) if candidate.is_file() else ""


def player_status(name: str = "mpv") -> dict:
    system = system_player(name)
    local = local_player(name)
    about = ""
    if system:
        try:
            about = subprocess.run([system, "--version"], capture_output=True,
                                   text=True, timeout=10, check=False
                                   ).stdout.splitlines()[0][:120]
        except (OSError, subprocess.SubprocessError, IndexError):
            about = ""
    return {
        "name": name,
        "available": bool(system or local),
        "system": system,
        "local": local,
        "about": about,
        "command": {
            "debian": f"sudo apt install {name}",
            "fedora": f"sudo dnf install {name}",
            "arch": f"sudo pacman -S {name}",
            "flatpak": f"flatpak install flathub io.mpv.Mpv",
        },
        "note": ("Optional player: nothing is embedded in this application and "
                 "no root action is performed by us. The built-in VLC engine "
                 "stays the default."),
    }


def install_command() -> str:
    return player_status()["command"]["debian"]


def open_terminal_for_install(name: str = "mpv") -> bool:
    """Open a terminal with the distribution command for the owner to approve.

    Never runs a password prompt by itself; the owner types the password in
    their own terminal.
    """
    command = player_status(name)["command"]["debian"]
    terminals = ("kgx", "gnome-terminal", "konsole", "xfce4-terminal", "xterm")
    for terminal in terminals:
        path = shutil.which(terminal)
        if not path:
            continue
        try:
            if os.path.basename(path) == "xterm":
                argv = [path, "-e", f"{command}; echo; read -n1 -p 'press any key'"]
            else:
                argv = [path, "--", "bash", "-lc",
                        f"{command}; echo; read -n1 -p 'press any key'"]
            return subprocess.Popen(argv, close_fds=True).poll() is None
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def main(argv=None) -> int:
    import json
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--status"]:
        print(json.dumps(player_status(args[1] if len(args) > 1 else "mpv"),
                         ensure_ascii=False))
        return 0
    if args[:1] == ["--open-install"]:
        ok = open_terminal_for_install(args[1] if len(args) > 1 else "mpv")
        print(json.dumps({"terminal_opened": ok}, ensure_ascii=False))
        return 0 if ok else 1
    raise SystemExit("Usage: python -m tv_center.player_market [--status [name] | --open-install [name]]")


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
