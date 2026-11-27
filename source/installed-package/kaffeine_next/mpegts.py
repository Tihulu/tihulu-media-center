# SPDX-License-Identifier: GPL-2.0-or-later
"""Small, bounded MPEG-TS PAT parser for the *current Kaffeine service*.

No channel catalog, tuning request, network or RF probing. A service ID
comes from the actual program association table in copied TS packets.
"""
from __future__ import annotations

TS_PACKET = 188

def current_program_identity(chunk: bytes) -> tuple[int, int] | None:
    """Return (service ID, transport stream ID) from a complete PAT.

    Works with single-packet PAT sections; refuses truncated data. The
    MPEG-TS reader rechecks each new PAT when the owner switches channels.
    """
    usable = len(chunk) // TS_PACKET * TS_PACKET
    for at in range(0, usable, TS_PACKET):
        packet = chunk[at:at + TS_PACKET]
        if packet[0] != 0x47 or packet[1] & 0x80:  # sync or transport error
            continue
        pid = ((packet[1] & 0x1F) << 8) | packet[2]
        if pid != 0 or not packet[1] & 0x40:
            continue
        control = (packet[3] >> 4) & 3
        if control not in (1, 3):
            continue
        offset = 4
        if control == 3:
            offset += 1 + packet[4]
        if offset >= 188:
            continue
        pointer = packet[offset]
        pos = offset + 1 + pointer
        if pos + 8 > 188 or packet[pos] != 0:
            continue
        length = ((packet[pos + 1] & 15) << 8) | packet[pos + 2]
        if length < 9 or pos + 3 + length > 188:
            continue
        end = pos + 3 + length - 4  # exclude CRC
        i = pos + 8  # PAT header through last section number
        while i + 4 <= end:
            program = int.from_bytes(packet[i:i + 2], "big")
            if program != 0:
                return program, int.from_bytes(packet[pos + 3:pos + 5], "big")
            i += 4
    return None

def current_program_id(chunk: bytes) -> int | None:
    """Backwards-compatible selected service ID (PAT), without guessing."""
    result = current_program_identity(chunk)
    return result[0] if result is not None else None
