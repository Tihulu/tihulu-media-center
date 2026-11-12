import tempfile
import time
from pathlib import Path
import unittest
from textcenter.core import Store
from textcenter.transcripts import TranscriptStore
from textcenter.postprocess import RecordingTranscriber,PostProcessError,decode_audio_command


class Saved:
    def __init__(self,path):self.path=path
    def recording(self,name):
        return self.path if name==self.path.name else None


class OfflineTests(unittest.TestCase):
    def test_saved_recording_requires_local_file_and_real_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/"20261106-FM-a.mp3"
            file.write_bytes(b"a")
            tr=RecordingTranscriber(transcripts=TranscriptStore(Store(Path(tmp)/"db")),
                radio=Saved(file),tv=Saved(file),lookup=lambda n:None)
            with self.assertRaises(PostProcessError):
                tr.start(medium="fm",filename=file.name,language="de")
            with self.assertRaises(PostProcessError):
                tr.start(medium="fm",filename="../secret.mp3",language="de")
            with self.assertRaises(ValueError):
                tr.start(medium="unknown",filename=file.name,language="de")
            self.assertIn("pipe:1",decode_audio_command("/usr/bin/ffmpeg",file))

    def test_mock_pcm_is_not_claimed_as_real_hardware_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            recording=base/"20261106-FM-test.mp3"
            recording.write_bytes(b"synthetic placeholder for fixture only")
            executable=base/"mock-ffmpeg"
            executable.write_text("#!/usr/bin/env python3\n"
                "import sys\n"
                "sys.stdout.buffer.write(b'\\x00\\x00'*(32000*8))\n"
                "sys.stdout.buffer.flush()\n")
            executable.chmod(0o700)
            tr=TranscriptStore(Store(base/"db.sqlite"))
            profile={"devices":[{"id":"cpu","name":"Fixture CPU","detected":True}],
                     "speech":{"ready_cpu":True,"model_path":"/fixture"}}
            worker=RecordingTranscriber(
                transcripts=tr,radio=Saved(recording),tv=Saved(recording),
                lookup=lambda _:str(executable),detect=lambda:profile,
                transcriber=lambda pcm,lang,backend,p:"Merhaba",
                translator=lambda text,src,tgt:"Hallo")
            start=worker.start(medium="fm",filename=recording.name,
                language="tr",target_language="de",backend="auto")
            self.assertEqual(start["device"],"Fixture CPU")
            deadline=time.monotonic()+4
            while time.monotonic()<deadline and worker.status()["active"]:
                time.sleep(.03)
            self.assertFalse(worker.status()["active"],worker.status())
            self.assertEqual(worker.status()["segments"],1)
            segments=tr.list(start["session"])
            self.assertEqual(segments[0]["original_text"],"Merhaba")
            self.assertEqual(segments[0]["translated_text"],"Hallo")
            self.assertEqual(segments[0]["medium"],"fm")
            worker.stop(wait=True)


if __name__=="__main__":
    unittest.main()
