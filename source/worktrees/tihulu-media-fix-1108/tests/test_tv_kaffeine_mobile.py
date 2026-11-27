"""Single-tuner MPEG-TS program identity and mobile safety checks."""
import unittest
from kaffeine_next.mpegts import current_program_id
from kaffeine_next.mobile import KaffeineMobile

def pat(program):
    section = bytes([0, 0xb0, 0x0d, 0, 1, 0xc1, 0, 0,
        program >> 8, program & 255, 0xe1, 1, 0, 0, 0, 0])
    p = bytes([0x47, 0x40, 0, 0x10, 0]) + section
    return p + b"\xff" * (188 - len(p))

class KaffeineProgramTests(unittest.TestCase):
    def test_pat_service_identity(self):
        self.assertEqual(current_program_id(pat(771)), 771)
        self.assertEqual(current_program_id(pat(1001)), 1001)
        self.assertIsNone(current_program_id(b"\x47" * 188))
        self.assertIsNone(current_program_id(pat(1001)[:180]))

    def test_mobile_requires_owner_and_tuned_program(self):
        app = KaffeineMobile(lambda: {"mode":"off", "page":150}, lambda m: None)
        with self.assertRaises(RuntimeError):
            app.enable_video()
        self.assertIsNone(app.snapshot()["channel"])
        app.receive(pat(771))
        self.assertIn("771", app.snapshot()["channel"])
        with self.assertRaises(RuntimeError):
            app.enable_video()

    def test_channel_switch_stops_old_hls(self):
        notes = []
        app = KaffeineMobile(lambda: {"mode":"off", "page":150}, notes.append)
        class Stream:
            def __init__(self): self.closed = False
            def stop(self): self.closed = True
            def offer(self, data): pass
            def get_dir(self): return "/tmp/live"
        app.receive(pat(771))
        old = Stream()
        app.hls = old
        app.receive(pat(866))
        self.assertTrue(old.closed)
        self.assertIsNone(app.hls)
        self.assertEqual(app.service_id, 866)
        self.assertIn("restart", notes[0].lower())
