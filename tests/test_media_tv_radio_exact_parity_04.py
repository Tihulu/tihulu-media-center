# SPDX-License-Identifier: GPL-2.0-or-later
"""MEDIA-TV-RADIO-EXACT-PARITY-04: installed, no-tuner deterministic acceptance.

Only run after the pinned installer has built and installed a disposable release.
Tests execute imports from RELEASE/py, never from the checkout; mocks substitute
only decoded RF/model *inputs*, not the production matching, queue, routing or
timing algorithms. An actual receiver, inference weights and full native TV/DAB
GUI operation remain HOLD.
"""
from __future__ import annotations

from dataclasses import replace
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RELEASE = Path(os.environ.get("TIHULU_MEDIA_QA_RELEASE", "/nonexistent")).resolve()
ENABLED = bool(os.environ.get("TIHULU_MEDIA_QA_RELEASE"))


@unittest.skipUnless(ENABLED, "requires pinned disposable installed release")
class InstalledTVRadioBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.py = RELEASE / "py"
        if not (RELEASE / "native/bin/kaffeine").is_file():
            raise AssertionError("No native Kaffeine installation: " + str(RELEASE))
        sys.path.insert(0, str(cls.py))
        names = ("tv_center.captions", "tv_center.lyrics_sync",
                 "tv_center.radio_dls_metadata", "tv_center.radio_karaoke_router",
                 "tv_center.sentence_joiner", "kaffeine_next.teletext_match",
                 "kaffeine_next.caption_timing")
        cls.mods = {name: importlib.import_module(name) for name in names}
        for name, module in cls.mods.items():
            if not Path(module.__file__).resolve().is_relative_to(cls.py.resolve()):
                raise AssertionError("Non-installed module imported: " + name)

    @classmethod
    def tearDownClass(cls):
        if str(cls.py) in sys.path:
            sys.path.remove(str(cls.py))

    def test_five_modes_real_configuration_and_off_ipc(self):
        timing = self.mods["kaffeine_next.caption_timing"]
        self.assertEqual(set(timing.MODE), {"off", "teletext", "asr", "auto", "page"})
        with tempfile.TemporaryDirectory() as temp:
            osd = timing.KaffeineOSD(19004, runtime=temp)
            for mode in timing.MODE:
                config = timing.CaptionConfig(mode=mode, font_px=32,
                    opacity=46, text_opacity=83, text_color="#FFCC00",
                    background_color="#112233", playback_delay_ms=4200,
                    offset_ms=-750, target_languages=("en", "tr"),
                    source="de", target="en").validate()
                self.assertEqual(config.options()["mode"], mode)
                osd.publish("Verified synthetic caption", config)
                data = json.loads(osd.path.read_text())
                self.assertEqual(data["enabled"], mode != "off")
                self.assertEqual(data["text"], "" if mode == "off" else
                                 "Verified synthetic caption")
                self.assertEqual((data["size"], data["opacity"],
                                  data["text_opacity"], data["text_color"]),
                                 (32, 46, 83, "#FFCC00"))
                osd.set_playback_delay(config)
                self.assertEqual(osd.delay.read_text(), "4200\n")
            osd.close()
        with self.assertRaises(ValueError):
            timing.CaptionConfig(playback_delay_ms=21000).validate()
        with self.assertRaises(ValueError):
            timing.CaptionConfig(page=99).validate()

    def test_actual_decoder_modes_with_synthetic_inputs(self):
        captions = self.mods["tv_center.captions"]
        seen = []
        def teletext(_path, page, sid, *extra):
            seen.append(("tt", page, sid, extra))
            return "A complete line spoken by this programme today"
        def asr(_path, language, _model, sid, **opts):
            seen.append(("asr", language, sid, tuple(sorted(opts))))
            opts["diagnostics"]["detected_language"] = "en"
            return "A complete line spoken by this programme today"
        with patch.object(captions, "teletext_from_clip", side_effect=teletext), \
             patch.object(captions, "asr_from_clip", side_effect=asr):
            common = dict(ts=b"synthetic-not-an-RF-signal", source="en",
                          target="en", targets=(), service_id=201)
            hard = captions.decode_segment(mode="teletext", **common)
            self.assertEqual(hard["original"], "A complete line spoken by this programme today")
            self.assertEqual(hard["source"], "broadcaster_teletext_subtitles")
            self.assertEqual([x[0] for x in seen], ["tt"])
            seen.clear()
            manual = captions.decode_segment(mode="page", page=777,
                                              teletext_pid=156, **common)
            self.assertEqual(manual["source"], "broadcaster_teletext_subtitles_page_777")
            self.assertEqual(seen[0][1:3], (777, 201))
            seen.clear()
            whisper = captions.decode_segment(mode="asr", **common)
            self.assertEqual(whisper["source"], "local_asr")
            self.assertEqual([x[0] for x in seen], ["asr"])
            seen.clear()
            auto = captions.decode_segment(mode="auto",
                                            auto_teletext_probe=True, **common)
            self.assertEqual(auto["source"], "broadcaster_teletext_subtitles")
            self.assertEqual(auto["teletext_probe"]["source_language"], "en")
            self.assertEqual([x[0] for x in seen], ["tt", "asr"])
            seen.clear()
            shadow = captions.decode_segment(mode="asr",
                auto_teletext_recovery=True, teletext_language="en", **common)
            self.assertEqual(shadow["source"], "local_asr")
            self.assertEqual(shadow["teletext_shadow"]["source_language"], "en")
            self.assertEqual([x[0] for x in seen], ["asr", "tt"])

    def test_auto_missing_teletext_uses_actual_asr_only(self):
        captions = self.mods["tv_center.captions"]
        with patch.object(captions, "teletext_from_clip", return_value="") as tt, \
             patch.object(captions, "asr_from_clip", return_value=
                          "Weather warning includes rain and a strong wind") as asr:
            result = captions.decode_segment(b"fixture", mode="auto", source="en",
                                             target="en", targets=())
        self.assertEqual(result["source"], "local_asr")
        self.assertTrue(result["original"])
        tt.assert_called_once()
        asr.assert_called_once()
        with patch.object(captions, "teletext_from_clip", return_value="") as tt, \
             patch.object(captions, "asr_from_clip") as asr:
            hard = captions.decode_segment(b"fixture", mode="teletext",
                                            source="en", target="en", targets=())
        self.assertFalse(hard["original"])
        self.assertNotEqual(hard["source"], "local_asr")
        asr.assert_not_called()

    def test_teletext_conflicts_hysteresis_recovery_language_and_channel_reset(self):
        matching = self.mods["kaffeine_next.teletext_match"]
        tt = "The mountain railway begins service after the morning storm"
        speech = "A distant ocean vessel moves steadily beneath cold night skies"
        self.assertEqual(matching.compare_text(tt, speech, "de", "en"), "unknown")
        self.assertEqual(matching.compare_text(tt, tt, "en", "en"), "matching")
        self.assertEqual(matching.compare_text(tt, speech, "en", "en"), "conflicting")
        audit = matching.TeletextAudit()
        for n in range(3):
            audit.mark_clip()
            verdict = audit.observe(tt, speech, "en", "en")
            if n < 2:
                self.assertFalse(audit.prefer_asr)
        self.assertEqual(verdict, "switched")
        self.assertTrue(audit.prefer_asr)
        audit.mark_clip()
        audit.observe(tt, tt, "en", "en")
        self.assertTrue(audit.prefer_asr, "one lucky phrase cannot restore old Teletext")
        audit.mark_clip()
        self.assertEqual(audit.observe(tt, tt, "en", "en"), "recovered")
        self.assertFalse(audit.prefer_asr)
        audit.missing()
        self.assertTrue(audit.prefer_asr)
        audit.reset()  # controller invokes reset on a new programme epoch
        self.assertFalse(audit.prefer_asr)
        self.assertEqual(audit.attempts, 0)

    def test_tv_sentence_hold_queue_order_duplicate_and_channel_clear(self):
        timing = self.mods["kaffeine_next.caption_timing"]
        cfg = timing.CaptionConfig(target_languages=("en",), readable_pacing=True)
        q = timing.CueQueue(minimum_hold=1.75)
        one = {"original":"The first synthetic statement is now complete.",
               "source":"local_asr"}
        two = {"original":"The next synthetic statement follows the first.",
               "source":"local_asr"}
        q.add(one, cfg, 100, 106, 107)
        duplicate = q.add(one, cfg, 100.5, 106.5, 107.4)
        self.assertTrue(duplicate.get("skipped_duplicate"))
        q.add(two, cfg, 106, 112, 113)
        self.assertEqual(len(q.items), 2)
        first = q.poll(120, cfg.revision)
        self.assertEqual(first["result"]["original"], one["original"])
        self.assertIsNone(q.poll(120.1, cfg.revision))
        next_cue = q.poll(122, cfg.revision)
        self.assertEqual(next_cue["result"]["original"], two["original"])
        q.add(one, cfg, 125, 131, 132)
        self.assertEqual(len(q.items), 1)
        q.clear()  # new SID/TSID invalidates old channel captions
        self.assertEqual(q.items, [])

    def test_real_capture_clock_offset_buffer_and_live_translation_render(self):
        timing = self.mods["kaffeine_next.caption_timing"]
        base = timing.CaptionConfig(source="de", target="en",
              target_languages=("en", "tr"), playback_delay_ms=2000, offset_ms=0)
        shifted = replace(base, playback_delay_ms=7000, offset_ms=1200)
        result = {"original":"Die Sendung beginnt jetzt.",
                  "translations":{"en":"The programme begins now.",
                                  "tr":"Program şimdi başlıyor."},
                  "source_language":"de", "source":"local_asr"}
        earlier = timing.cue_window(100, 106, 107, base, result)
        later = timing.cue_window(100, 106, 107, shifted, result)
        self.assertAlmostEqual(later["due"] - earlier["due"], 6.2, places=3)
        self.assertGreaterEqual(timing.readable_display_seconds(result, shifted), 2.8)
        displayed = shifted.render(result)
        self.assertIn("[EN]", displayed)
        self.assertIn("[TR]", displayed)
        self.assertIn("Die Sendung", displayed)
        translated_only = replace(shifted, show_original=False)
        self.assertNotIn("Die Sendung", translated_only.render(result))
        q = timing.CueQueue()
        q.add(result, base, 100, 106, 107)
        target = replace(base, offset_ms=-750, revision=1)
        q.retime(-750, target)
        self.assertEqual(q.items[0]["revision"], 1)

    def test_sentence_continuations_do_not_cross_channel_or_language(self):
        joiner = self.mods["tv_center.sentence_joiner"].LiveSentenceJoiner(max_chunks=2)
        self.assertTrue(joiner.push("We have a short", language="en")["pending"])
        joined = joiner.push("message for tonight.", language="en")
        self.assertTrue(joined["complete"])
        self.assertIn("short message", joined["text"])
        joiner.push("An old channel", language="en")
        joiner.reset()  # exact same operation as channel switch's queue reset
        self.assertTrue(joiner.push("Das neue Programm beginnt.", language="de")["complete"])
        self.assertNotIn("old channel", joiner.pending)

    def test_lyrics_wrong_song_delayed_dls_and_refresh(self):
        lyrics = self.mods["tv_center.lyrics_sync"]
        dls = self.mods["tv_center.radio_dls_metadata"]
        song = "We crossed the silent river beneath the morning sky"
        bridge = "The lonely windows shone across the empty street"
        match = lyrics.LiveLyricMatcher([song, bridge])
        self.assertIsNone(match.observe("A weather bulletin for commuters in Berlin"))
        hint = dls.parse_dls_song("Example Artist - Example Track")
        self.assertIsNotNone(hint)
        self.assertEqual(match.position, 0, "DLS metadata is not an acoustic match")
        self.assertIsNone(match.observe("silent river"))
        proven = match.observe(song)
        self.assertIsNotNone(proven)
        self.assertEqual(proven["index"], 0)
        self.assertEqual(proven["kind"], "observed_ASR_chunk_match")
        self.assertIsNone(match.observe(song), "overlapping ASR cannot replay same verse")
        self.assertIsNotNone(match.reacquire(bridge))
        self.assertIsNone(match.reacquire("sports and weather briefing"))
        new_song = lyrics.LiveLyricMatcher(["Sunrise brings another quiet day"])
        self.assertIsNone(new_song.observe(song), "old ASR cannot verify new song")

    def test_lyrics_repeated_chorus_and_karaoke_time_evidence(self):
        lyrics = self.mods["tv_center.lyrics_sync"]
        chorus = "The golden lantern dances across the silver sea"
        verse = "Another mountain railway passes beneath the northern sky"
        matcher = lyrics.LiveLyricMatcher([chorus, verse, chorus])
        self.assertIsNotNone(matcher.observe(chorus))
        self.assertIsNone(matcher.reacquire(chorus),
                          "ambiguous repeated chorus must not seek to wrong verse")
        self.assertEqual(lyrics.aligned_karaoke_word_anchors(
            chorus, [], capture_end_epoch_ms=180000), [])
        observed = [
            {"text":"golden", "start":1.0, "end":1.3},
            {"text":"lantern", "start":1.4, "end":1.7},
            {"text":"dances", "start":1.9, "end":2.2},
            {"text":"across", "start":2.5, "end":2.9},
            {"text":"silver", "start":3.0, "end":3.2},
        ]
        anchors = lyrics.aligned_karaoke_word_anchors(
            chorus, observed, capture_end_epoch_ms=180000, window_seconds=6.0)
        self.assertGreaterEqual(len(anchors), 2)
        self.assertTrue(all(x["epoch_ms"] <= 180000 for x in anchors))
        self.assertTrue(all(anchors[i]["epoch_ms"] < anchors[i+1]["epoch_ms"]
                            for i in range(len(anchors)-1)))

    def test_radio_worker_routing_does_not_mutate_caption_owner(self):
        router = self.mods["tv_center.radio_karaoke_router"]
        self.assertTrue(router.karaoke_alignment_choice(
            "tr", qwen_installed=True)["whisper_caption_independent"])
        self.assertEqual(router.karaoke_alignment_choice(
            "tr", qwen_installed=True)["engine"], "whisper")
        instance = router.MusicSpeechRouter()
        instance.change_song(True)
        self.assertEqual(instance.observe(matched=True, recognized_speech=True,
                                         chunk=4), "music_verified_lyrics")
        self.assertEqual(instance.observe(matched=False, recognized_speech=True,
                                         chunk=5), "waiting_vocal_match")
        self.assertEqual(instance.observe(matched=False, recognized_speech=True,
                                         chunk=6), "speech_whisper")

    def test_actual_native_radio_reading_method_compiles_and_executes_four_presets(self):
        # Compile the exact unchanged method body from the INSTALLED C++ header
        # against Qt5, not a copied Python approximation.
        source = (self.py / "kaffeine_next/native_radio_tab.h").read_text()
        start = source.index("    int radioCaptionReadingHoldMs(")
        end = source.index("    void setRadioLyricMatchStatus", start)
        method = source[start:end]
        wrapper = """
#include <QtWidgets/QApplication>
#include <QtWidgets/QComboBox>
#include <QtCore/QList>
#include <algorithm>
#include <iostream>
class NativeReadingProbe {
public:
    QComboBox picker;
    QComboBox *radioReadingPreset_ = &picker;
    QList<int> cueQueue_;
    QList<int> lagSamples_;
    NativeReadingProbe() {
        for (int i=0;i<4;i++) picker.addItem(QString::number(i),i);
    }
""" + method + """
};
int main(int argc,char **argv) {
    QApplication app(argc,argv);
    NativeReadingProbe n;
    const QString sentence(90, QChar('A'));
    int holds[4];
    for (int i=0;i<4;i++) {
        n.picker.setCurrentIndex(i);
        holds[i]=n.radioCaptionReadingHoldMs(sentence);
    }
    if (!(holds[0] < holds[1] && holds[1] < holds[2] &&
          holds[3] >= 2800)) return 3;
    n.picker.setCurrentIndex(3);
    n.cueQueue_={1,2,3,4};
    if (n.radioCaptionReadingHoldMs(sentence)>2500) return 4;
    n.cueQueue_.clear();
    int nominal=n.radioCaptionReadingHoldMs(sentence);
    n.lagSamples_={6000,6000,6000,6000,6000};
    if (n.radioCaptionReadingHoldMs(sentence)>=nominal) return 5;
    std::cout<<"native four-presets PASS";
    return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="tihulu-native-radio-") as tmp:
            cpp = Path(tmp) / "radio_exact.cpp"
            exe = Path(tmp) / "radio_exact"
            cpp.write_text(wrapper)
            flags = subprocess.run(["pkg-config", "--cflags", "--libs", "Qt5Widgets"],
                                   capture_output=True, text=True, check=True).stdout.split()
            compiled = subprocess.run(["g++", "-std=c++17", "-fPIC", str(cpp),
                                       "-o", str(exe), *flags],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            ran = subprocess.run([str(exe)], capture_output=True, text=True,
                                 timeout=20, env={**os.environ, "QT_QPA_PLATFORM":"xcb"})
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertIn("four-presets PASS", ran.stdout)

    def test_native_refresh_separation_and_local_preprocess_default_contract(self):
        # Native refresh handlers depend on a live player: structural gate only;
        # report runtime interaction as HOLD in the acceptance matrix.
        source = (self.py / "kaffeine_next/native_radio_tab.h").read_text()
        left = source.split("    void refreshRadioCaptionLipSync()", 1)[1].split(
            "    void refreshRadioLipSync()", 1)[0]
        right = source.split("    void refreshRadioLipSync()", 1)[1].split(
            "    int radioCaptionReadingHoldMs(", 1)[0]
        self.assertIn("cueQueue_", left)
        self.assertNotIn("verifiedLyricQueue_", left)
        self.assertIn("verifiedLyricQueue_", right)
        self.assertIn("karaokeSyncRefreshToken_", right)
        media = (self.py / "kaffeine_next/native_media_panel.h").read_text()
        self.assertIn('QLatin1String("transcribeBeforeOpen"),false', media)
        self.assertIn("prevent", media.lower())
        self.assertIn("TV AI preferences", media)
        self.assertIn("Radio AI preferences", media)

    def test_native_caption_settings_dialog_widgets_without_receiver(self):
        # Launch the installed Qt controller with a synthetic private AF_UNIX
        # endpoint. Inspect actual QWidget instances after event loop startup.
        # No TS packet, receiver, model or network connection is provided.
        script = textwrap.dedent(r"""
            import json,os
            from PyQt5.QtCore import QTimer
            from PyQt5.QtWidgets import QApplication,QComboBox,QSpinBox,QCheckBox
            from kaffeine_next import captions_overlay
            app=QApplication([])
            def inspect():
                combos=[w for w in app.allWidgets() if isinstance(w,QComboBox)]
                modes=[]
                for combo in combos:
                    vals=[combo.itemData(i) for i in range(combo.count())]
                    if set(("off","auto","asr","teletext","page")).issubset(set(
                            x for x in vals if isinstance(x,str))):
                        modes=vals
                pages=[w for w in app.allWidgets() if isinstance(w,QSpinBox)
                       and w.minimum()==100 and w.maximum()==899]
                comfort=[w for w in app.allWidgets() if isinstance(w,QCheckBox)
                         and "Comfort reading" in w.text()]
                print(json.dumps({"modes":modes,"pages":len(pages),
                                  "comfort":[w.isChecked() for w in comfort]}),
                      flush=True)
                app.quit()
            QTimer.singleShot(2500,inspect)
            socket=os.path.join(os.environ["XDG_RUNTIME_DIR"],
                                "tihulu-dvb-%d.sock" % os.getpid())
            captions_overlay.main(["--socket",socket])
        """)
        with tempfile.TemporaryDirectory(prefix="tihulu-caption-gui-") as runtime:
            os.chmod(runtime, 0o700)
            env = {**os.environ, "PYTHONPATH":str(self.py),
                   "XDG_RUNTIME_DIR":runtime, "QT_QPA_PLATFORM":"xcb",
                   "PYTHONDONTWRITEBYTECODE":"1", "HF_HUB_OFFLINE":"1",
                   "TRANSFORMERS_OFFLINE":"1"}
            run = subprocess.run(["/usr/bin/python3", "-c", script],
                                 env=env, cwd="/", text=True,
                                 capture_output=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout+"\n"+run.stderr)
            records = [json.loads(row) for row in run.stdout.splitlines()
                       if row.strip().startswith("{") and '"modes"' in row]
            self.assertEqual(len(records), 1, run.stdout)
            self.assertEqual(set(records[0]["modes"]),
                             {"off", "auto", "asr", "teletext", "page"})
            self.assertTrue(records[0]["pages"])
            self.assertEqual(records[0]["comfort"], [True])


if __name__ == "__main__":
    unittest.main()
