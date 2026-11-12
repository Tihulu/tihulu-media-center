# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only, owner-published DVB tune generation for the caption sidecar.

Kaffeine alone owns the tuner. Its atomic runtime marker announces a channel
change immediately, before another PAT or PCM clip becomes available.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

_TUNE = re.compile(rb"([0-9]{1,19}) ([0-9]{1,5}) ([0-9]{1,5})\n?\Z")
_SOCKET = re.compile(r"tihulu-dvb-([0-9]{1,10})\.sock\Z")


def read_native_tune(socket_path: str | Path) -> tuple[int, int, int] | None:
    """Return (owner_epoch, service_id, transport_stream_id), or unavailable.

    Invalid and older app markers are ignored; never infer a new TV channel
    from the current subtitle UI selection or open an additional tuner.
    """
    path = Path(socket_path)
    match = _SOCKET.fullmatch(path.name)
    if not match or not path.is_absolute():
        return None
    candidate = path.with_name(f"tihulu-tv-tune-{match.group(1)}.txt")
    try:
        # The runtime directory is private to the desktop user; prevent an
        # accidental symlink and refuse unexpectedly large or foreign files.
        st = candidate.lstat()
        if not candidate.is_file() or candidate.is_symlink() or (
                st.st_uid != os.getuid() or st.st_size > 80):
            return None
        with candidate.open("rb") as stream:
            raw = stream.read(81)
    except (OSError, ValueError):
        return None
    found = _TUNE.fullmatch(raw)
    if not found:
        return None
    epoch, service, multiplex = (int(v) for v in found.groups())
    if (epoch < 1 or service > 65535 or multiplex > 65535 or
            (service == 0 and multiplex != 0)):
        return None
    return epoch, service, multiplex
