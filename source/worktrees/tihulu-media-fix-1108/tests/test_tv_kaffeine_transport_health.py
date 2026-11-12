"""MPEG-TS continuity detects missing sidecar packets but not legitimate PCR repeats."""
import unittest
from kaffeine_next.transport_health import TransportContinuityMeter


def ts(pid, cc, payload=True, discontinuity=False):
    header = bytes([0x47, 0x40 | (pid >> 8), pid & 0xff,
                    (0x30 if discontinuity else 0x10 if payload else 0x20) | cc])
    if discontinuity:
        return header + bytes([1, 0x80]) + bytes(182)
    if payload:
        return header + bytes(184)
    return header + bytes([183]) + bytes(183)


class TransportContinuityTests(unittest.TestCase):
    def test_clean_stream_with_cc_wrap_no_gaps(self):
        monitor=TransportContinuityMeter()
        monitor.inspect(b"".join(ts(200, n & 15) for n in range(40)))
        self.assertEqual(monitor.snapshot()["continuity_gaps"],0)
        self.assertEqual(monitor.snapshot()["ts_packets"],40)

    def test_gap_duplicate_and_adaptation_only(self):
        monitor=TransportContinuityMeter()
        monitor.inspect(ts(350,0)+ts(350,1)+ts(350,3))
        self.assertEqual(monitor.snapshot()["continuity_gaps"],1)
        monitor.inspect(ts(350,3))
        self.assertEqual(monitor.snapshot()["duplicate_packets"],1)
        monitor.inspect(ts(350,3,payload=False)+ts(350,4))
        self.assertEqual(monitor.snapshot()["continuity_gaps"],1)

    def test_discontinuity_flag_resets_expectations(self):
        monitor=TransportContinuityMeter()
        monitor.inspect(ts(200,2)+ts(200,9,payload=True,discontinuity=True)+ts(200,10))
        self.assertEqual(monitor.snapshot()["continuity_gaps"],0)
        self.assertEqual(monitor.snapshot()["explicit_discontinuities"],1)

    def test_null_pid_ignored_and_channel_switch_reset(self):
        monitor=TransportContinuityMeter()
        monitor.inspect(ts(0x1fff,1)+ts(0x1fff,8)+ts(100,5))
        monitor.reset()
        monitor.inspect(ts(100,12))
        self.assertEqual(monitor.snapshot()["continuity_gaps"],0)

    def test_invalid_packet_is_not_fabricated_gap(self):
        monitor=TransportContinuityMeter()
        monitor.inspect(b"\0"*188)
        monitor.inspect(b"\x47"*9)
        self.assertEqual(monitor.snapshot()["invalid_packets"],2)
