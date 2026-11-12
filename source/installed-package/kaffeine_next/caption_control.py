# SPDX-License-Identifier: GPL-2.0-or-later
"""Private single-instance control channel for a persistent Kaffeine caption service.

The DVB packet receiver and Whisper workers remain alive when the settings
window is hidden. Reopening Kaffeine's TIHULU AI menu sends SHOW to this
existing process rather than starting a second subtitle engine.
"""
from __future__ import annotations
import os
from pathlib import Path
import socket
import stat
import threading


class CaptionServiceControl:
    def __init__(self, runtime: Path, kaffeine_pid: int, events):
        self.root = Path(runtime)
        if (not self.root.is_dir() or self.root.is_symlink() or
                type(kaffeine_pid) is not int or kaffeine_pid <= 0):
            raise ValueError("Expected the current user's private runtime directory")
        self.path = self.root / f"tihulu-captions-control-{kaffeine_pid}.sock"
        self.events = events
        self.pid = kaffeine_pid
        self.sock = None
        self.stop = threading.Event()
        self.reader = None

    @staticmethod
    def request_show(runtime, kaffeine_pid):
        path = Path(runtime) / f"tihulu-captions-control-{int(kaffeine_pid)}.sock"
        if not path.exists():
            return False
        if path.is_symlink():
            raise RuntimeError("Unsafe caption control socket path")
        meta = path.stat()
        if meta.st_uid != os.getuid() or not stat.S_ISSOCK(meta.st_mode):
            raise RuntimeError("Caption socket is not a user-owned UNIX socket")
        request = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            request.settimeout(0.5)
            request.sendto(b"SHOW", str(path))
            return True
        except (ConnectionRefusedError, FileNotFoundError):
            # Stale sockets can remain after a crashed subtitle worker.
            return False
        finally:
            request.close()

    def start(self):
        if os.path.lexists(self.path):
            if self.request_show(self.root, self.pid):
                raise RuntimeError("Caption settings are already running; shown existing panel")
            meta = self.path.lstat()
            if meta.st_uid != os.getuid() or not stat.S_ISSOCK(meta.st_mode):
                raise RuntimeError("Refusing to replace an unsafe caption socket")
            self.path.unlink()
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            self.sock.bind(str(self.path))
            os.chmod(self.path, 0o600)
            self.sock.settimeout(0.3)
        except OSError:
            self.sock.close()
            self.sock = None
            raise
        self.reader = threading.Thread(target=self._run, name="tihulu-caption-settings-control", daemon=True)
        self.reader.start()

    @property
    def kaffeine_pid(self):
        return int(self.path.name.rsplit("-", 1)[-1].split(".")[0])

    def _run(self):
        while not self.stop.is_set():
            try:
                data = self.sock.recv(64)
            except socket.timeout:
                continue
            except OSError:
                break
            if data == b"SHOW":
                try:
                    self.events.put_nowait(("show_settings", None))
                except Exception:
                    # The UI queue is bounded; silently dropping a redundant
                    # wake request must not kill active subtitles.
                    pass

    def close(self):
        self.stop.set()
        if self.sock:
            self.sock.close()
        if self.reader and self.reader.is_alive():
            self.reader.join(timeout=1.5)
        if self.path.exists():
            try:
                if not self.path.is_symlink() and self.path.stat().st_uid == os.getuid():
                    self.path.unlink()
            except OSError:
                pass
