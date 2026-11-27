"""Radio / local video / audio tests: no RF, GPU, network or Qt required."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tv_center.lyrics_sync import (
    LyricCue, parse_lrc, cue_at, lookup_synced_lyrics,
    srt_timestamp, write_srt)
from tv_center.radio_ai import checked_runtime_output, write_runtime_json
from tv_center.media_ai import validate_local_media, _chunk_cues
from kaffeine_next.patch_upstream import PATHS


class RadioAndLocalMediaTests(unittest.TestCase):
    def test_lrc_uses_real_timestamps_and_no_guess(self):
        cues=parse_lrc(
            "[00:02.50]Hello\n[00:05.000][00:08.0]World\n"
            "[ar:Not a lyric]\n[00:12.1]Song")
        self.assertEqual([round(c.start,2) for c in cues],[2.5,5,8,12.1])
        self.assertIsNone(cue_at(cues,1.99))
        self.assertEqual(cue_at(cues,5.01).text,"World")
        self.assertEqual(cue_at(cues,6.0).text,"World")
        self.assertEqual(srt_timestamp(62.034),"00:01:02,034")
        with self.assertRaises(ValueError):
            parse_lrc("a"*2_100_000)

    def test_online_lyrics_are_never_fetched_without_explicit_consent(self):
        with patch("tv_center.lyrics_sync._get_json") as http:
            with self.assertRaises(PermissionError):
                lookup_synced_lyrics(title="Song",artist="Artist",online=False)
            http.assert_not_called()
            http.return_value={
                "trackName":"Song","artistName":"Artist",
                "syncedLyrics":"[00:00.50]Hello",
                "duration":180,"id":11}
            cues,meta=lookup_synced_lyrics(
                title="Song",artist="Artist",duration=180,online=True)
            self.assertEqual(len(cues),1)
            self.assertEqual(meta["provider"],"LRCLIB")
            with self.assertRaises(ValueError):
                lookup_synced_lyrics(
                    title="Song",artist="Artist",duration=199,online=True)

    def test_srt_export_and_existing_media_are_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/"film.mkv"
            file.write_bytes(b"fake")
            self.assertEqual(validate_local_media(str(file)),file.resolve())
            target=Path(temp)/"film.srt"
            write_srt([LyricCue(1.0,2.2,"Hello"),
                       LyricCue(3.0,3.5,"Goodbye")],target,
                      translations={1:"[TR] Merhaba"})
            data=target.read_text()
            self.assertIn("00:00:01,000 --> 00:00:02,200",data)
            self.assertIn("[TR] Merhaba",data)
            with self.assertRaises(FileExistsError):
                write_srt([LyricCue(1,2,"replace")],target)
            self.assertEqual(target.read_text(),data)
            wrong=Path(temp)/"unknown.xyz"
            wrong.write_bytes(b"media")
            with self.assertRaises(ValueError):
                validate_local_media(str(wrong))

    def test_live_radio_near_silent_pcm_does_not_train_or_hallucinate_whisper(self):
        from tv_center.media_ai import _near_silent_pcm
        import struct
        self.assertTrue(_near_silent_pcm(b""))
        self.assertTrue(_near_silent_pcm(b"\x00" * (32000 * 6 * 2)))
        self.assertFalse(_near_silent_pcm(struct.pack("<h",500) * 32000))
        self.assertFalse(_near_silent_pcm(struct.pack("<h",-2000) * 32000))
        code=(Path(__file__).resolve().parent.parent / "tv_center"/"radio_ai.py").read_text()
        self.assertIn("if _near_silent_pcm(pcm):",code)
        self.assertIn('detection["recognition_rejected"]="near_silent_pcm"',code)
        self.assertLess(code.index("if _near_silent_pcm(pcm):"),
                        code.index("cues=_chunk_cues(pcm,position=chunks*5"))

    def test_gpu_music_flag_is_explicitly_passed_not_auto_enabled(self):
        data=bytes(32000*2*2)
        profile={"speech":{"gpu_engine":"faster_whisper_managed",
                           "gpu_model_path":"/fake/turbo"}}
        words=[{"text":"Hallo","start":.1,"end":.6},
               {"text":"Welt","start":.8,"end":1.5}]
        with patch("tv_center.cuda_faster_whisper.transcribe_cuda_details",
                   return_value={"text":"Hallo Welt","words":words}) as cuda:
            cues=_chunk_cues(data,position=10,lang="de",profile=profile,
                            backend="gpu",music=True)
            self.assertGreaterEqual(len(cues),1)
            self.assertEqual(cues[0].start,10.1)
            self.assertIn("Hallo Welt",cues[0].text)
            self.assertTrue(cuda.call_args.kwargs["music_mode"])
            _chunk_cues(data,position=1,lang="de",profile=profile,
                        backend="gpu",music=False)
            self.assertFalse(cuda.call_args.kwargs["music_mode"])

    def test_radio_ipc_is_private_only_not_any_path(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ,{"XDG_RUNTIME_DIR":root}):
                path=Path(root)/"tihulu-radio-captions-334.json"
                checked_runtime_output(str(path),
                                       prefix="tihulu-radio-captions-")
                write_runtime_json(path,{"original":"Guten Tag","translations":{
                    "en":"Good day","tr":"İyi günler"}})
                self.assertEqual(json.loads(path.read_text())["original"],
                                 "Guten Tag")
                with self.assertRaises(ValueError):
                    checked_runtime_output(
                        str(Path(root)/"other.json"),
                        prefix="tihulu-radio-captions-")
                with self.assertRaises(ValueError):
                    checked_runtime_output(
                        "/tmp/tihulu-radio-captions-334.json",
                        prefix="tihulu-radio-captions-")

    def test_native_kaffeine_radio_and_localhost_only_welle_builder(self):
        directory=Path(__file__).resolve().parent.parent/"kaffeine_next"
        radio=(directory/"native_radio_tab.h").read_text()
        patch_source=(directory/"patch_upstream.py").read_text()
        builder=(directory/"install_welle.sh").read_text()
        self.assertIn("class TihuluRadioTab final : public TabBase",radio)
        self.assertIn("Radio (DAB+)",patch_source)
        self.assertIn("mediaCaptionAction",patch_source)
        self.assertIn("tihulu_radio_tab.h",patch_source)
        self.assertIn("src/mainwindow.h",PATHS)
        self.assertIn("src/CMakeLists.txt",PATHS)
        self.assertIn("INADDR_LOOPBACK",builder)
        self.assertIn("Socket.cpp",builder)
        self.assertIn("-DBUILD_WELLE_IO=OFF",builder)
        self.assertIn("Resemblyzer",(directory/"README.md").read_text())


if __name__=="__main__":
    unittest.main()
