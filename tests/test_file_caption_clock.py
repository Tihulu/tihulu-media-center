# SPDX-License-Identifier: GPL-2.0-or-later
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"source/installed-package"))
from kaffeine_next.file_caption_timeline import FileCaptionTimeline

class FileClockTests(unittest.TestCase):
    def test_buffer_and_synchronized_caption(self):
        t=FileCaptionTimeline()
        t.sync(1,0,(4200,True,7))
        t.accept("file_window",dict(generation=1,revision=0,session=7,start=4200,end=12200,eof=False,
                                    cues=[dict(start=4500,end=6100,text="translated")]))
        self.assertTrue(t.snapshot((4200,True,7),8,True)[1]["file_ready"])
        self.assertEqual(t.snapshot((5000,True,7),8,True)[0],"translated")
        self.assertEqual(t.snapshot((6200,True,7),8,True)[0],"")
    def test_silence_and_eof_are_valid_ready_intervals(self):
        t=FileCaptionTimeline()
        t.sync(1,0,(0,True,1))
        t.accept("file_window",dict(generation=1,revision=0,session=1,start=0,end=2000,eof=True,cues=[]))
        self.assertTrue(t.snapshot((0,True,1),8,True)[1]["file_ready"])
    def test_seek_and_revision_clear_old_cues(self):
        t=FileCaptionTimeline()
        t.sync(1,0,(0,True,1))
        t.accept("file_window",dict(generation=1,revision=0,session=1,start=0,end=8000,eof=False,
                                    cues=[dict(start=0,end=8000,text="old")]))
        t.sync(2,0,(1000,True,2))
        self.assertFalse(t.snapshot((1000,True,2),8,True)[1]["file_ready"])
        self.assertEqual(t.snapshot((1000,True,2),8,True)[0],"")
    def test_error_not_ready(self):
        t=FileCaptionTimeline()
        t.sync(1,0,(0,True,1))
        t.accept("file_window_error",dict(generation=1,revision=0,session=1,error="ASR failed"))
        self.assertFalse(t.snapshot((0,True,1),8,True)[1]["file_ready"])
        self.assertEqual(t.snapshot((0,True,1),8,True)[1]["file_error"],"ASR failed")

    def test_translation_selection_and_fallback(self):
        t=FileCaptionTimeline()
        state=(1000,True,1)
        t.sync(1,0,state)
        t.accept("file_window",dict(generation=1,revision=0,session=1,start=1000,end=9000,eof=False,
            cues=[dict(start=1000,end=3000,text="Hallo\nMerhaba",original="Hallo",translation="Merhaba"),
                  dict(start=3000,end=4000,text="Welt",original="Welt",translation="")],
            warning="translation unavailable"))
        self.assertEqual(t.snapshot(state,8,True,show_original=False)[0],"Merhaba")
        self.assertEqual(t.snapshot(state,8,True,show_translation=False)[0],"Hallo")
        self.assertEqual(t.snapshot((3500,True,1),8,True,show_original=False)[0],"Welt")
        self.assertEqual(t.snapshot(state,8,True)[1]["file_warning"],"translation unavailable")

    def test_no_analyzed_window_is_not_ready_and_gap_fails(self):
        t=FileCaptionTimeline()
        t.sync(1,0,(0,True,1))
        self.assertFalse(t.snapshot((0,True,1),8,True)[1]["file_ready"])
        t.accept("file_window",dict(generation=1,revision=0,session=1,start=0,end=8000,eof=False,cues=[]))
        t.accept("file_window",dict(generation=1,revision=0,session=1,start=9000,end=17000,eof=False,cues=[]))
        self.assertFalse(t.snapshot((0,True,1),8,True)[1]["file_ready"])
        self.assertIn("Non-contiguous",t.snapshot((0,True,1),8,True)[1]["file_error"])

    def test_real_ffmpeg_pcm_then_mocked_asr_and_translation(self):
        import tempfile,subprocess
        from unittest.mock import patch
        from types import SimpleNamespace
        from tv_center.file_live_captions import caption_window
        with tempfile.TemporaryDirectory() as d:
            media=Path(d)/"sample.wav"
            subprocess.run(["ffmpeg","-nostdin","-v","error","-f","lavfi","-i",
                "sine=frequency=440:duration=5","-ar","32000","-ac","1",str(media)],check=True,timeout=20)
            def recognize(pcm,position,*args,**kwargs):
                self.assertEqual(len(pcm),128000)
                self.assertNotEqual(set(pcm),{0})
                return [SimpleNamespace(start=position+.25,end=position+1,text="Hallo",language="de")]
            with patch("tv_center.file_live_captions._chunk_cues",side_effect=recognize) as asr, \
                 patch("tv_center.file_live_captions._translate_cues",return_value=({1:"Merhaba"},[])):
                result=caption_window(media,1.,source="de",targets=("tr",),profile={},backend="cpu",window=2)
            self.assertEqual(asr.call_count,1)
            self.assertEqual(result["end"],3000)
            self.assertEqual(result["cues"],[dict(start=1250,end=2000,text="Hallo\nMerhaba")])
