import tempfile
import time
from pathlib import Path
import unittest
import wave
import io
from textcenter.fm_audio import FMPreview,AudioError,audio_argv,pcm_to_wav


class AudioTests(unittest.TestCase):
    @staticmethod
    def inv():return {"platform":"Linux","rtl_usb_count":1}

    def test_commands_and_wav_headers(self):
        args=audio_argv("/usr/bin/rtl_fm",98_600_000)
        self.assertIn("wbfm",args)
        self.assertEqual(args[-2:],["-E","deemp"])
        with self.assertRaises(ValueError):
            audio_argv("/bin/rtl_fm",1)
        wav=pcm_to_wav(b"\x00\x00"*(32000*2))
        with wave.open(io.BytesIO(wav)) as stream:
            self.assertEqual(stream.getnchannels(),1)
            self.assertEqual(stream.getframerate(),32000)
            self.assertEqual(stream.getnframes(),64000)

    def test_existing_readsb_prevents_audio_without_opening_usb(self):
        with tempfile.TemporaryDirectory() as td:
            preview=FMPreview(inventory=self.inv,lookup=lambda _:"/bin/rtl_fm",
                              conflicts=lambda:[{"process":"readsb"}],lock_dir=Path(td))
            self.assertFalse(preview.availability()["ready"])
            with self.assertRaises(AudioError):
                preview.start(98.6,10)
            self.assertEqual(preview.status()["status"],"idle")

    def test_mock_real_pcm_preview(self):
        # The fixture emits synthetic PCM; no actual SDR reception is claimed.
        with tempfile.TemporaryDirectory() as td:
            binary=Path(td)/"rtl_fm_fake"
            binary.write_text("#!/usr/bin/env python3\n"
              "import sys\n"
              "sys.stdout.buffer.write(b'\\x00\\x00'*32000*2)\n"
              "sys.stdout.buffer.flush()\n")
            binary.chmod(0o700)
            preview=FMPreview(inventory=self.inv,lookup=lambda _:str(binary),
                              conflicts=lambda:[],lock_dir=Path(td)/"locks")
            preview.start(98.6,10)
            for _ in range(150):
                if not preview.status()["active"]:
                    break
                time.sleep(0.02)
            state=preview.status()
            self.assertEqual(state["status"],"completed",state)
            self.assertTrue(state["clip_ready"])
            audio=preview.wav_clip()
            self.assertIsNotNone(audio)
            with wave.open(io.BytesIO(audio)) as f:
                self.assertEqual(f.getframerate(),32000)
                self.assertGreater(f.getnframes(),32000)
            preview.stop(wait=True)


if __name__=="__main__":
    unittest.main()
