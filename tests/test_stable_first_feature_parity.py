# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolated snapshot parity gates for TIHULU TV and Radio UI / AI contracts.

Runs on CI without receivers, model files, a desktop session, network, user
settings, or background services. A PASS proves source-level parity only.
Real TV/DAB, GPU inference, private preferences, and installed binary equality
remain separate release blockers.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "source" / "installed-package"
SNAPSHOT = "7821769eb7aed576dd426ec18ffce3696d93a00d"

TV = SRC / "kaffeine_next" / "captions_overlay.py"
RADIO = SRC / "kaffeine_next" / "native_radio_tab.h"
LYRICS = SRC / "tv_center" / "lyrics_sync.py"
RADIO_AI = SRC / "tv_center" / "radio_ai.py"
ROUTER = SRC / "tv_center" / "radio_karaoke_router.py"
MODELS = SRC / "tv_center" / "ai_settings.py"
PROFILES = SRC / "tv_center" / "ai_profiles.py"
LOCAL_MEDIA = SRC / "kaffeine_next" / "native_media_panel.h"
INSTALLER = ROOT / "installer" / "media-stable-first.sh"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True, text=True, check=False, timeout=25,
    )


def load_pure_module(path: Path, module_name: str):
    """Load a self-contained module without importing receiver/model runtimes."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load source-only module: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


class FrozenSourceParity(unittest.TestCase):
    """Fail if the installer PR quietly swaps any frozen installed source."""

    def test_full_installed_package_tree_is_unchanged(self):
        check = git("cat-file", "-e", SNAPSHOT + "^{commit}")
        self.assertEqual(check.returncode, 0, "Frozen snapshot commit missing in CI")
        # The only authorized source of the installer is frozen
        # source/installed-package; changes here require a NEW audited snapshot.
        changed = git("diff", "--name-status", SNAPSHOT, "HEAD", "--",
                      "source/installed-package/")
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertEqual(changed.stdout.strip(), "",
                         "Frozen installed source changed; do not silently substitute development")
        manifest = git("show", f"{SNAPSHOT}:manifest.json")
        self.assertEqual(manifest.returncode, 0, manifest.stderr)
        self.assertIn('"source_files_staged": 455', manifest.stdout)

    def test_installer_extracts_only_frozen_installed_variant(self):
        code = read(INSTALLER)
        self.assertIn("SNAPSHOT=" + SNAPSHOT, code)
        self.assertIn('git -C "$REPO" archive "$SNAPSHOT" -- source/installed-package',
                      code)
        self.assertIn('cp -a -- "$work/snapshot/source/installed-package/$module"', code)
        self.assertIn("for module in tv_center textcenter kaffeine_next", code)
        self.assertIn('python3 "$stage/py/kaffeine_next/patch_upstream.py"', code)
        self.assertNotIn("source/worktrees/", code)
        self.assertNotIn("TIHULU-TEXT-CENTER.git", code)

    def test_installer_is_separate_from_existing_application(self):
        code = read(INSTALLER)
        self.assertIn('APPROOT="${HOME}/.local/opt/tihulu-media-stable"', code)
        self.assertIn('LAUNCHER="${HOME}/.local/bin/tihulu-media-stable"', code)
        self.assertIn("--dry-run", code)
        self.assertIn("--rollback", code)
        self.assertIn("no_automatic_models=true", code)
        self.assertNotIn('APPROOT="${HOME}/.local/opt/tihulu-kaffeine"', code)


class TelevisionModesParity(unittest.TestCase):
    def test_all_five_tv_caption_source_modes(self):
        src = read(TV)
        for item in (
            'mode.addItem("Teletext subtitles → Whisper fallback", "auto")',
            'mode.addItem("Teletext Hard · broadcaster subtitles (no Whisper test)", "teletext")',
            'mode.addItem("Whisper live transcription", "asr")',
            'mode.addItem("Manual Teletext page", "page")',
            'mode.addItem("Off", "off")',
        ):
            with self.subTest(mode=item):
                self.assertIn(item, src)

    def test_reading_and_live_timing_controls_wired(self):
        src = read(TV)
        for required in (
            "Comfort reading · stable phrases, no flashing words, readable hold",
            "comfort_reading.setChecked(True)",
            "readable_pacing=comfort_reading.isChecked()",
            "Prefer spoken dialogue over background music",
            "Include singing / music vocals in Whisper",
            "Protect live speech · skip heavy voice/sound extras if lag builds",
            "live_priority=live_priority.isChecked()",
            "Auto-size TV buffer if too short (increase only; not lip-sync)",
            "playback_delay_ms=round(playback_delay.value()*1000)",
            "offset_ms=round(caption_offset.value()*1000)",
        ):
            with self.subTest(feature=required):
                self.assertIn(required, src)

    def test_teletext_audio_mismatch_and_recovery_not_removed(self):
        src = read(TV)
        audit = read(SRC / "kaffeine_next" / "teletext_match.py")
        for text in (
            "self.teletext_audit.observe(",
            "self.teletext_audit.prefer_asr",
            "No usable broadcaster Teletext, switched to real Whisper",
        ):
            self.assertIn(text, src)
        self.assertIn("class TeletextAudit:", audit)
        self.assertIn("def compare_text(", audit)


class RadioLyricsParity(unittest.TestCase):
    def test_four_reading_presets_and_both_refreshes(self):
        src = read(RADIO)
        for required in (
            'radioReadingPreset_->addItem(tr("Live · fast"),0)',
            'radioReadingPreset_->addItem(tr("Comfort · recommended"),1)',
            'radioReadingPreset_->addItem(tr("Relaxed · longer hold"),2)',
            '"TV-style Adaptive · readable + live"),3)',
            'QLatin1String("radioReadingPreset")',
            "AI Lip-sync Refresh",
            "Karaoke Lip-sync Refresh",
            "Find lyrics for current song",
        ):
            with self.subTest(feature=required):
                self.assertIn(required, src)

    def test_audio_verified_lyrics_and_alignment_controls(self):
        radio = read(RADIO_AI)
        lyrics = read(LYRICS)
        router = read(ROUTER)
        for required in (
            "lyric_match_threshold",
            "lyric_match_mode",
            "karaoke_aligner",
            "recent_lyric_asr",
            "aligned_karaoke_word_anchors",
            "effective_radio_translation_enabled",
        ):
            self.assertIn(required, radio)
        for required in ("class LiveLyricMatcher:", "def reacquire(",
                         "def lookup_synced_lyrics(", "def parse_lrc("):
            self.assertIn(required, lyrics)
        for required in ("def karaoke_alignment_choice(", "class MusicSpeechRouter:"):
            self.assertIn(required, router)

    def test_radio_alignment_falls_back_to_whisper_for_turkish(self):
        module = load_pure_module(ROUTER, "_tihulu_parity_radio_router")
        try:
            choose = module.karaoke_alignment_choice
            self.assertEqual(choose("tr", qwen_installed=True)["engine"], "whisper")
            self.assertEqual(choose("de", qwen_installed=False)["engine"], "whisper")
            self.assertEqual(choose("de", qwen_installed=True)["engine"], "qwen")
            self.assertEqual(choose("de", qwen_installed=True,
                                    requested="whisper")["engine"], "whisper")
            with self.assertRaises(ValueError):
                choose("de", qwen_installed=True, requested="unknown")
        finally:
            sys.modules.pop("_tihulu_parity_radio_router", None)

    def test_plain_lyrics_are_not_fabricated(self):
        module = load_pure_module(LYRICS, "_tihulu_parity_lyrics")
        try:
            matcher = module.LiveLyricMatcher([
                "We crossed the silent river beneath the morning sky",
                "The lonely windows shone across the empty street",
            ])
            self.assertIsNone(matcher.observe("Radio news announcement and weather report"))
            self.assertIsNone(matcher.observe("hello hello"))
            # Real ASR evidence, not metadata, may validate a lyric line.
            self.assertIsNotNone(
                module.LiveLyricMatcher([
                    "We crossed the silent river beneath the morning sky"
                ]).observe("We crossed the silent river beneath the morning sky"))
            cues = module.parse_lrc("[ar:Example]\n[00:05.20]First sentence\n"
                                    "[00:09.40]Second sentence")
            self.assertEqual(len(cues), 2)
            self.assertAlmostEqual(cues[0].start, 5.2)
        finally:
            sys.modules.pop("_tihulu_parity_lyrics", None)


class ModelAndLocalMediaParity(unittest.TestCase):
    def test_shared_tv_radio_model_configuration_remains_explicit(self):
        src = read(MODELS)
        radio = read(RADIO_AI)
        self.assertIn('".config/tihulu-tv-center/ai-settings.json"', src)
        self.assertIn('"backend": "auto"', src)
        self.assertIn('"translation_model": "argos"', src)
        self.assertIn('ai=AISettings()', radio)
        self.assertIn('ai.configure_environment()', radio)
        self.assertIn('profile,backend=_choose_model(ai)', radio)

    def test_all_five_ai_profiles_and_explicit_activation(self):
        tree = ast.parse(read(PROFILES))
        profiles_expr = next(
            node.value for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "PROFILES"
                    for t in node.targets)
        )
        profiles = ast.literal_eval(profiles_expr)
        self.assertEqual(set(profiles),
                         {"pi5", "pi5_hat2", "normal", "performance", "experimental"})
        self.assertEqual(profiles["normal"]["speech"], "small")
        self.assertEqual(profiles["performance"]["backend"], "gpu")
        self.assertEqual(profiles["experimental"]["translator"], "madlad")
        src = read(SRC / "tv_center" / "settings_ui.py")
        self.assertIn("preview_profile_controls", src)
        self.assertIn("Select mode", src)
        self.assertIn("Save settings", src)

    def test_transcribe_entire_file_before_playback_preserved(self):
        src = read(LOCAL_MEDIA)
        self.assertIn("Entire local file · transcribe/translate first, then play", src)
        self.assertIn('QLatin1String("transcribeBeforeOpen")', src)
        self.assertIn("TV AI preferences", src)
        self.assertIn("Radio AI preferences", src)


if __name__ == "__main__":
    unittest.main()
