import tempfile
from pathlib import Path
import unittest
from textcenter.live_fm import LiveFM, LiveError,encode_argv


class LiveFMTests(unittest.TestCase):
    def test_audio_encoding_has_safe_args(self):
        args=encode_argv("/usr/bin/ffmpeg")
        self.assertIn("libmp3lame",args)
        self.assertEqual(args[-2:],["mp3","pipe:1"])
        self.assertNotIn("-y",args)

    def test_readsb_blocks_start_without_process(self):
        with tempfile.TemporaryDirectory() as t:
            live=LiveFM(archive_dir=Path(t)/"rec",
                inventory=lambda:{"platform":"Linux","rtl_usb_count":1},
                lookup=lambda n:"/usr/bin/"+n,
                conflicts=lambda:[{"process":"readsb"}],
                lock_dir=Path(t)/"lock")
            self.assertFalse(live.availability()["ready"])
            with self.assertRaises(LiveError):
                live.start(98.6)
            self.assertFalse(live.status()["active"])
            self.assertIsNone(live.recording("../secret.mp3"))
            self.assertIsNone(live.recording("bad.mp3"))

    def test_no_model_or_dongle_is_not_fake_radio(self):
        with tempfile.TemporaryDirectory() as t:
            live=LiveFM(archive_dir=Path(t)/"rec",
                inventory=lambda:{"platform":"Linux","rtl_usb_count":0},
                lookup=lambda _:None,conflicts=lambda:[])
            self.assertFalse(live.availability()["ready"])
            with self.assertRaises(LiveError):
                live.start(98.6)
            self.assertEqual(live.recordings(),[])


if __name__=="__main__":
    unittest.main()
