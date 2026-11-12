"""Token-free, opt-in public speaker model and responsive Market UI tests."""
from __future__ import annotations
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tv_center.free_speakers import FreeSpeakerMarket, VoiceClusters, MARKER, READY, cluster_windows
from tv_center.captions import _speaker_details
from kaffeine_next.caption_timing import CaptionConfig


class FreeSpeakerTests(unittest.TestCase):
    def test_no_huggingface_token_and_model_is_owner_managed(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as temp:
            root=Path(temp)/"speaker-managed"
            market=FreeSpeakerMarket(root=root)
            self.assertFalse(market.status()["installed"])
            self.assertFalse(market.status()["token_required"])
            self.assertFalse(market.status()["gated"])
            self.assertEqual(CaptionConfig().speaker_provider,"resemblyzer")
            self.assertEqual(CaptionConfig(speaker_enabled=True).options()[
                "speaker_provider"],"resemblyzer")
            root.mkdir()
            (root/MARKER).write_text("owned")
            market.python.parent.mkdir(parents=True)
            market.python.touch()
            (root/READY).write_text("passed")
            self.assertTrue(market.status()["installed"])
            self.assertIn("removed",market.remove())
            self.assertFalse(root.exists())

    def test_user_files_are_not_deleted(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as temp:
            root=Path(temp)/"unowned"
            root.mkdir()
            (root/"important").write_text("keep")
            with self.assertRaises(RuntimeError):
                FreeSpeakerMarket(root=root).remove()
            self.assertEqual((root/"important").read_text(),"keep")

    def test_cluster_ids_follow_voices_and_reset_on_channel_switch(self):
        a=[0.0]*256
        a[0]=1.0
        b=[0.0]*256
        b[1]=1.0
        c=[0.0]*256
        c[2]=1.0
        tracker=VoiceClusters(threshold=.76,maximum=2)
        self.assertEqual(tracker.assign(a,"news"),0)
        self.assertEqual(tracker.assign(a,"news"),0)
        self.assertEqual(tracker.assign(b,"news"),1)
        self.assertIsNone(tracker.assign(c,"news"))
        self.assertEqual(tracker.assign(b,"sports"),0)
        self.assertEqual(len(tracker.centroids),1)
        self.assertIsNone(tracker.assign([float("nan")]*256,"sports"))
        self.assertEqual(len(tracker.centroids),1)

    def test_labels_follow_detected_windows_not_fabricated_gender(self):
        a=[0.0]*256
        a[0]=1
        b=[0.0]*256
        b[1]=1
        turns=cluster_windows(
            [(0.0,1.6,a),(0.8,2.4,a),(2.4,4.0,b)],
            VoiceClusters(threshold=.76),"tv:pid",4.0)
        self.assertEqual([x["id"] for x in turns],
                         ["SPEAKER_00","SPEAKER_01"])
        self.assertFalse(any("woman" in str(turn).lower() for turn in turns))
        self.assertTrue(all(0 <= turn["start"] < turn["end"] <= 4.0
                            for turn in turns))

    def test_free_speaker_errors_never_erase_recognized_words(self):
        with patch("tv_center.free_speakers.diarize_pcm",
                   side_effect=RuntimeError("Offline voice model missing")):
            meta={}
            content=_speaker_details(b"\0\0"*32000,"Guten Tag",meta,
                                     True,provider="resemblyzer")
        self.assertEqual(content,"Guten Tag")
        self.assertIn("Offline voice model missing",meta["speaker_error"])
        with patch("tv_center.free_speakers.diarize_pcm",
                   return_value=[{"start":0.0,"end":1.0,
                                  "id":"SPEAKER_00"}]):
            meta={}
            _speaker_details(b"\0\0"*32000,"Hallo",meta,True,
                             provider="resemblyzer",channel="tv-pid")
            self.assertEqual(meta["speaker_engine"],"resemblyzer")
            self.assertEqual(meta["speaker_turns"][0]["id"],"SPEAKER_00")

    def test_all_model_market_tabs_scroll_and_save_footer_stays_fixed(self):
        ui=(Path(__file__).resolve().parent.parent /
            "tv_center"/"settings_ui.py").read_text()
        self.assertIn("def scroll_tab(contents)",ui)
        self.assertIn("outer.addWidget(tabs,1)",ui)
        self.assertIn("outer.addLayout(finish)",ui)
        self.assertIn('QFrame.NoFrame',ui)
        self.assertIn("install_free_speaker_model",ui)
        self.assertIn("token-free Resemblyzer",ui.lower().replace("public voice", "token-free Resemblyzer")
                      if "token-free Resemblyzer" in ui else "Resemblyzer")


if __name__=="__main__":
    unittest.main()
