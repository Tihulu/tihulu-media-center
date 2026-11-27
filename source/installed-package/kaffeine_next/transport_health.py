# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only end-to-end MPEG-TS packet continuity meter.

Measure the Kaffeine -> subtitle Unix socket stream (which may lose data
from RF reception OR nonblocking sidecar sends). Transport gaps are not
claimed to be RF faults and must not be confused with Whisper CPU latency.
"""
from __future__ import annotations


class TransportContinuityMeter:
    def __init__(self):
        self.last_payload_cc = {}
        self.packets = 0
        self.continuity_gaps = 0
        self.duplicated_payload_packets = 0
        self.discontinuity_signals = 0
        self.invalid_packets = 0

    def reset(self):
        self.last_payload_cc.clear()

    def inspect(self, data: bytes):
        if not isinstance(data, bytes) or len(data) % 188:
            self.invalid_packets += 1
            return
        for offset in range(0, len(data), 188):
            packet = data[offset:offset+188]
            if packet[0] != 0x47:
                self.invalid_packets += 1
                continue
            self.packets += 1
            if packet[1] & 0x80:  # transport_error_indicator
                self.invalid_packets += 1
                continue
            pid = ((packet[1] & 0x1f) << 8) | packet[2]
            if pid == 0x1fff:
                continue
            afc = (packet[3] >> 4) & 3
            if afc == 0:
                self.invalid_packets += 1
                continue
            has_adaptation = afc in (2, 3)
            has_payload = afc in (1, 3)
            cc = packet[3] & 15
            if has_adaptation:
                length = packet[4]
                if length > 183:
                    self.invalid_packets += 1
                    continue
                if length >= 1 and (packet[5] & 0x80):
                    self.last_payload_cc.pop(pid, None)
                    self.discontinuity_signals += 1
            if not has_payload:
                # Adaptation-only packets can repeat the same CC without loss.
                continue
            previous = self.last_payload_cc.get(pid)
            if previous is not None:
                expected = (previous + 1) & 15
                if cc == previous:
                    self.duplicated_payload_packets += 1
                elif cc != expected:
                    self.continuity_gaps += 1
            self.last_payload_cc[pid] = cc

    def snapshot(self):
        return {
            "ts_packets": self.packets,
            "continuity_gaps": self.continuity_gaps,
            "duplicate_packets": self.duplicated_payload_packets,
            "explicit_discontinuities": self.discontinuity_signals,
            "invalid_packets": self.invalid_packets,
            "note": "Gaps indicate TS loss between antenna and subtitle consumer, not necessarily RF."
        }
