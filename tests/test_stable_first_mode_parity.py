# SPDX-License-Identifier: GPL-2.0-or-later
"""Frozen-source parity and safe pure-functional tests, no GUI/RF/model launch.

These tests verify source identity, UI contracts and one pure karaoke fallback;
they do NOT replace owner-approved clean-install or hardware acceptance.
"""
from __future__ import annotations
import ast
import importlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "source/installed-package"
SNAPSHOT = "7821769eb7aed576dd426ec18ffce3696d93a00d"
PROTECTED = (
    "kaffeine_next/captions_overlay.py",
    "kaffeine_next/caption_timing.py",
    "kaffeine_next/native_media_panel.h",
    "kaffeine_next/native_radio_tab.h",
    "kaffeine_next/native_unified_recorder.h",
    "kaffeine_next/patch_upstream.py",
    "kaffeine_next/subtitle_tracks.py",
    "kaffeine_next/teletext_match.py",
    "tv_center/ai_profiles.py",
    "tv_center/settings_ui.py",
    "tv_center/radio_ai.py",
    "tv_center/lyrics_sync.py",
    "tv_center/radio_karaoke_router.py",
    "tv_center/cuda_faster_whisper.py",
    "tv_center/whisper_engine.py",
    "tv_center/translation_service.py",
    "textcenter/fm_rds.py",
    "textcenter/dab_bridge.py",
)

def source(path: str) -> str:
    return (SRC / path).read_text(encoding="utf-8")

class FrozenModeParity(unittest.TestCase):
    def test_full_frozen_source_blobs_are_identical(self) -> None:
        # Compare Git object identity, not just names or heuristic feature tags.
        for path in PROTECTED:
            current = subprocess.run(["git", "-C", str(ROOT), "rev-parse",
                                      f"HEAD:source/installed-package/{path}"],
                                     capture_output=True, text=True, check=True)
            frozen = subprocess.run(["git", "-C", str(ROOT), "rev-parse",
                                     f"{SNAPSHOT}:source/installed-package/{path}"],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(current.stdout.strip(), frozen.stdout.strip(), path)

    def test_tv_modes_and_comfort_defaults(self) -> None:
        ui = source("kaffeine_next/captions_overlay.py")
        modes = [
            ('Teletext subtitles → Whisper fallback', "auto"),
            ('Teletext Hard · broadcaster subtitles (no Whisper test)', "teletext"),
            ('Whisper live transcription', "asr"),
            ('Manual Teletext page', "page"),
            ('Off', "off"),
        ]
        for title, value in modes:
            self.assertIn(f'mode.addItem("{title}", "{value}")', ui)
        self.assertIn('comfort_reading.setChecked(True)', ui)
        self.assertIn('speech_priority.setChecked(False)', ui)
        self.assertIn('readable_pacing=comfort_reading.isChecked()', ui)
        self.assertIn('teletext_source_transition', ui)
        self.assertIn('self.teletext_audit.prefer_asr', ui)
        self.assertIn('TV playback buffer · editable; never reduced automatically:', ui)
        self.assertIn('QSettings("TIHULU", "KaffeineCaptionAppearance")', ui)
        self.assertIn('QSettings("TIHULU", "KaffeineTVFileCaptionDefaults")', ui)

    def test_ai_profiles_are_exactly_preserved(self) -> None:
        text = source("tv_center/ai_profiles.py")
        module = ast.parse(text)
        assignments = [
            n for n in module.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "PROFILES" for t in n.targets)
        ]
        self.assertEqual(len(assignments), 1)
        profiles = ast.literal_eval(assignments[0].value)
        self.assertEqual(tuple(profiles), (
            "pi5", "pi5_hat2", "normal", "performance", "experimental"))
        self.assertEqual(profiles["pi5"]["backend"], "cpu")
        self.assertEqual(profiles["pi5_hat2"]["backend"], "cpu")
        self.assertEqual(profiles["performance"]["backend"], "gpu")
        self.assertEqual(profiles["experimental"]["translator"], "madlad")
        self.assertIn("selection_patch", text)
        self.assertIn('raise RuntimeError("Install all first; missing: "', text)
        settings = source("tv_center/settings_ui.py")
        for word in ("self.profile_choice.addItem", "self.profile_install.clicked.connect",
                     "self.profile_select.clicked.connect", "self.inspect_profile",
                     "self.select_profile", "self.profile_changed"):
            self.assertIn(word, settings)

    def test_radio_reading_modes_and_user_settings(self) -> None:
        radio = source("kaffeine_next/native_radio_tab.h")
        for label, value in (
            ("Live · fast", 0),
            ("Comfort · recommended", 1),
            ("Relaxed · longer hold", 2),
            ("TV-style Adaptive · readable + live", 3),
        ):
            self.assertRegex(radio, re.compile(r'addItem\([\s\S]{0,45}?' +
                              re.escape(label) + r'"\),' + str(value) + r'\);'))
        self.assertIn('QLatin1String("radioReadingPreset"),3', radio)
        self.assertIn('QLatin1String("KaffeineRadio")', radio)
        self.assertIn('karaokeSyncHistorySeconds', radio)
        self.assertIn('Karaoke Lip-sync Refresh', radio)
        self.assertIn('speech', radio.lower())

    def test_local_media_preprocess_is_opt_in(self) -> None:
        media = source("kaffeine_next/native_media_panel.h")
        self.assertIn("Entire local file · transcribe/translate first, then play", media)
        self.assertIn('QLatin1String("transcribeBeforeOpen"),false', media)
        self.assertIn('QLatin1String("MediaPlayer")', media)
        self.assertIn('beforeOpenMode_=beforeOpen', media)
        self.assertIn("DVB live buffer/Teletext clock are NOT applied to a file.", media)
        self.assertIn("source untouched", media)

    def test_karaoke_pure_fallback_without_models_or_hardware(self) -> None:
        sys.path.insert(0, str(SRC))
        try:
            router = importlib.import_module("tv_center.radio_karaoke_router")
            select = router.karaoke_alignment_choice
            self.assertEqual(select("tr", qwen_installed=True)["engine"], "whisper")
            self.assertEqual(select("de", qwen_installed=False)["engine"], "whisper")
            self.assertEqual(select("de", qwen_installed=True)["engine"], "qwen")
            self.assertEqual(select("en", qwen_installed=True,
                                    requested="whisper")["engine"], "whisper")
            self.assertTrue(select("de", qwen_installed=True)["whisper_caption_independent"])
            with self.assertRaises(ValueError):
                select("de", qwen_installed=True, requested="other")
        finally:
            sys.path.remove(str(SRC))

    def test_private_preferences_cannot_be_recovered_from_public_snapshot(self) -> None:
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertIs(manifest["models_recordings_settings_in_public_repo"], False)
        self.assertIs(manifest["compiled_binary_in_public_repo"], False)

if __name__ == "__main__":
    unittest.main()
