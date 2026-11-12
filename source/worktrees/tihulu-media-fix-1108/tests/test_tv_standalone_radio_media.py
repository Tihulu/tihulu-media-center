"""Regression tests for standalone TIHULU player, full DAB catalogue and cross-lang ASR."""
from __future__ import annotations
from pathlib import Path
import unittest
from unittest.mock import patch

from tv_center.media_ai import _chunk_cues, _translate_cues
from kaffeine_next.patch_upstream import transform


ROOT=Path(__file__).resolve().parent.parent


class StandaloneNativePlayerTests(unittest.TestCase):
    def test_native_radio_never_reparents_video_widget(self):
        radio=(ROOT/"kaffeine_next/native_radio_tab.h").read_text()
        self.assertIn("void activate() override",radio)
        activation=radio.split("void activate() override",1)[1].split("private:",1)[0]
        self.assertNotIn("playerHostLayout_->addWidget(player_)",activation)
        self.assertIn("radioCanvas_->setFocus()",activation)
        self.assertIn("player_->play(QUrl(base()+stream))",radio)
        self.assertIn("radioCanvas_->setText",radio)

    def test_combined_library_favorites_search_all_blocks_and_live_welle(self):
        radio=(ROOT/"kaffeine_next/native_radio_tab.h").read_text()
        for term in ("All DAB blocks","favorites_.contains(key)",
                     "dabFavorites","filterStations()",
                     "stationSearch_->setPlaceholderText",
                     "QHeaderView::Stretch", "toggleFavorite(",
                     "showWidgets_->setChecked(false)",
                     "plotKind_->addItem(tr(\"Waterfall\")",
                     "livePlot_->isChecked()", "QImage waterfall_",
                     "slideHistory_", "slideMove(",
                     "stopLyrics()","lyricsProcess_.start(",
                     "autoSync_->isChecked()", "bufferMs_->setRange(0,60000)",
                     "lagSamples_.size()>=4",
                     "QSettings radioSettings"):
            self.assertIn(term,radio)

    def test_start_page_app_identity_and_in_player_local_ai(self):
        patches=(ROOT/"kaffeine_next/patch_upstream.py").read_text()
        for term in ('"tihulu-media-center"', "TIHULU Media Center",
                     "setApplicationName", "setOrganizationName",
                     "DAB+ Radio", "Open Media + Offline AI",
                     "tihulu_media_panel.h", "setLocalFile(copy)",
                     "insertWidget(0, mediaWidget, 1)",
                     "localStreamUrl.startsWith(\"http://127.0.0.1:\")",
                     "fileCacheMs"):
            self.assertIn(term,patches)
        self.assertNotIn('QStringList() << QLatin1String("media-captions-ui")',patches)
        installer=(ROOT/"kaffeine_next/install.sh").read_text()
        self.assertTrue("Icon=tihulu-media-center" in installer or
                        "Icon=$DESKTOP_ICON" in installer)
        self.assertIn("tihulu-media-center.svg",installer)
        self.assertIn("Name=TIHULU Media Center",installer)
        self.assertIn('ln -sfn kaffeine "$PREFIX/bin/tihulu-media-center"',installer)
        self.assertIn("tihulu-media-centerrc",installer)
        self.assertTrue((ROOT/"kaffeine_next/assets/tihulu-media-center.svg").is_file())
        media=(ROOT/"kaffeine_next/native_media_panel.h").read_text()
        self.assertIn("player_->setSubtitle(QUrl::fromLocalFile(srtPath_))",media)
        self.assertIn("Preprocess before playback",media)
        self.assertIn("fileCacheMs",media)
        self.assertIn("lyricsOnline_",media)

    def test_radio_lyrics_use_real_lrc_times_and_translate_only_known_language(self):
        import json
        import os
        import tempfile
        from tv_center.radio_ai import lyrics_lookup_to_file
        from tv_center.lyrics_sync import LyricCue
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/"tihulu-radio-lyrics-900.json")
            with patch.dict(os.environ,{"XDG_RUNTIME_DIR":temp}), (
                    patch("tv_center.radio_ai.lookup_synced_lyrics",
                          return_value=([LyricCue(1.0,3.0,"Hello everyone")],
                                        {"provider":"LRCLIB","id":77}))), (
                    patch("tv_center.captions.translate",
                          side_effect=lambda text,src,dst:(
                              "Hallo zusammen" if dst=="de" else "Merhaba",None))):
                code=lyrics_lookup_to_file(
                    artist="Test Artist",track="Test Song",output=path,
                    online=True,source="en",targets=("en","de","tr"))
                self.assertEqual(code,0)
                record=json.loads(Path(path).read_text())
                self.assertEqual(record["alignment_mode"],"timed_lrc")
                self.assertEqual(record["plain_lines"],["Hello everyone"])
                cue=record["cues"][0]
                self.assertEqual((cue["start"],cue["end"]),(1.0,3.0))
                self.assertNotIn("en",cue["translations"])
                self.assertEqual(cue["translations"]["de"],"Hallo zusammen")
                self.assertEqual(cue["translations"]["tr"],"Merhaba")
            Path(path).unlink()
            with patch.dict(os.environ,{"XDG_RUNTIME_DIR":temp}), (
                    patch("tv_center.radio_ai.lookup_synced_lyrics",
                          return_value=([LyricCue(1.0,3.0,"Hello everyone")],
                                        {"provider":"LRCLIB","id":77}))):
                self.assertEqual(lyrics_lookup_to_file(
                    artist="Test Artist",track="Test Song",output=path,
                    online=True,source="auto",targets=("de",)),0)
                record=json.loads(Path(path).read_text())
                self.assertEqual(record["alignment_mode"],"timed_lrc")
                self.assertNotIn("translations",record["cues"][0])

    def test_untimed_song_lyrics_retain_targets_for_later_asr_matching(self):
        import json
        import os
        import tempfile
        from tv_center.radio_ai import lyrics_lookup_to_file
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/"tihulu-radio-lyrics-901.json")
            with patch.dict(os.environ,{"XDG_RUNTIME_DIR":temp}), (
                    patch("tv_center.radio_ai.lookup_synced_lyrics",
                          return_value=([],{
                              "provider":"LRCLIB","status":"plain",
                              "plain_lines":["Hello everyone","Next refrain"]}))):
                result=lyrics_lookup_to_file(
                    artist="Artist",track="Track",output=path,online=True,
                    source="en",targets=("de","tr"))
                self.assertEqual(result,0)
                record=json.loads(Path(path).read_text())
                self.assertEqual(record["alignment_mode"],"asr_lexical")
                self.assertEqual(record["source_language"],"en")
                self.assertEqual(record["translation_targets"],["de","tr"])
                self.assertEqual(record["plain_lines"],
                                 ["Hello everyone","Next refrain"])
                self.assertEqual(record["cues"],[])

    def test_auto_detected_en_translates_de_and_tr_with_correct_source(self):
        profile={"speech":{"gpu_engine":"faster_whisper_managed",
                           "gpu_model_path":"/test/turbo"}}
        samples=bytes(32000*2*2)
        details={"text":"Hello everybody",
                 "words":[{"start":.2,"end":.9,"text":"Hello"},
                          {"start":1.0,"end":1.8,"text":"everybody"}],
                 "language":"en","language_probability":.94}
        meta={}
        with patch("tv_center.cuda_faster_whisper.transcribe_cuda_details",
                   return_value=details) as whisper:
            cues=_chunk_cues(samples,position=2,lang="auto",
                             profile=profile,backend="gpu",detection=meta)
            self.assertTrue(cues)
            self.assertEqual(cues[0].language,"en")
            self.assertEqual(meta["language"],"en")
            self.assertAlmostEqual(meta["confidence"],.94)
            self.assertEqual(whisper.call_args.args[1],"auto")
        calls=[]
        def fake_translate(text,source,target):
            calls.append((source,target))
            return {"de":"Hallo","tr":"Merhaba"}.get(target),None
        with patch("tv_center.media_ai.translate",side_effect=fake_translate):
            result,warnings=_translate_cues(cues,("en","de","tr"),"auto")
        self.assertEqual(calls,[("en","de"),("en","tr")])
        self.assertIn("[DE]",result[1])
        self.assertIn("[TR]",result[1])
        self.assertEqual(warnings,[])


if __name__=="__main__":
    unittest.main()
