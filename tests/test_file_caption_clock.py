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
