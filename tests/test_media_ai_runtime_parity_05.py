"""MEDIA-AI-RUNTIME-PARITY-05: synthetic/metadata-only, NO model inference."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source/installed-package"
sys.path.insert(0, str(SOURCE))
MODULE = ROOT / "installer/media-ai-compat.py"
spec = importlib.util.spec_from_file_location("media_ai_compat_05", MODULE)
assert spec and spec.loader
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)

from tv_center.ai_profiles import (PROFILES, COMPONENTS, hardware_issue,
                                   missing_components, selection_patch)
from tv_center.ai_settings import AISettings, DEFAULTS
from tv_center.radio_karaoke_router import karaoke_alignment_choice
from textcenter.compute import choose_backend


class AICompatSyntheticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="media-ai-compat-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "owner"
        self.home.mkdir()
        self.original = self.home / ".config/tihulu-tv-center/ai-settings.json"
        self.original.parent.mkdir(parents=True)
        self.original.write_text('{"OWNER_PRIVATE": "UNTOUCHED"}\n')
        self.qsettings = self.home / ".config/TIHULU/KaffeineRadio.conf"
        self.qsettings.parent.mkdir(parents=True)
        self.qsettings.write_text("OWNER_RADIO_UNTOUCHED\n")
        self.recording = self.home / "Recordings/private.wav"
        self.recording.parent.mkdir(parents=True)
        self.recording.write_bytes(b"OWNER_AUDIO_UNTOUCHED")
        self.app = self.home / ".local/opt/tihulu-media-stable"
        self.preview = self.app / "preview-home"
        (self.preview / ".config").mkdir(parents=True)
        (self.app / compat.MARKER).write_text(compat.MARKER_VALUE)
        self.ssd = self.home / "synthetic-ssd-model-folder"
        self.ssd.mkdir()
        self.model = self.ssd / "ggml-small-fixture.bin"
        # A mock placeholder tests metadata decisions, NEVER actual Whisper.
        self.model.write_bytes(b"F" * 2048)
        self.home_patch = patch.object(Path, "home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def supplied(self, **kw):
        return compat.plan(model_path=str(self.model), model_dir=str(self.ssd),
                           backend=kw.get("backend", "auto"),
                           translator=kw.get("translator", "argos"))

    def assert_owner_untouched(self):
        self.assertEqual(self.original.read_text(), '{"OWNER_PRIVATE": "UNTOUCHED"}\n')
        self.assertEqual(self.qsettings.read_text(), "OWNER_RADIO_UNTOUCHED\n")
        self.assertEqual(self.recording.read_bytes(), b"OWNER_AUDIO_UNTOUCHED")
        self.assertEqual(self.model.read_bytes(), b"F" * 2048)

    def test_all_five_profiles_explicit_and_unactivated(self):
        self.assertEqual(set(PROFILES), {"pi5", "pi5_hat2", "normal", "performance", "experimental"})
        for key, value in PROFILES.items():
            self.assertIn(value["speech"], ("tiny", "small"))
            self.assertEqual(value["backend"], "gpu" if key in ("performance", "experimental") else "cpu")
            self.assertTrue(all(component in COMPONENTS for component in value["components"]))
        self.assertEqual(DEFAULTS["active_profile"], "")
        self.assertFalse(DEFAULTS["asr_enabled"])
        self.assertFalse(DEFAULTS["translation_enabled"])

    def test_profiles_do_not_claim_missing_gpu_or_models(self):
        low_gpu = {"ram_mib": 32000, "gpu": {"detected": True, "vram_mib": 16000}}
        self.assertIsNone(hardware_issue("performance", low_gpu))
        self.assertIn("VRAM", hardware_issue("experimental", low_gpu))
        self.assertIn("required", hardware_issue(
            "performance", {"ram_mib": 64000, "gpu": {"detected": False}}))
        self.assertIn("whisper_cpu", missing_components("pi5", {}))
        self.assertRaises(RuntimeError, selection_patch, "normal",
            library=object(), hardware={"ram_mib": 16000}, status={})

    def test_auto_cpu_fallback_is_compatibility_not_inference(self):
        devices = [{"id": x, "name": x, "detected": True} for x in ("cpu", "gpu", "npu")]
        synthetic = {"devices": devices,
                     "speech": {"ready_cpu": True, "ready_gpu": False, "ready_npu": False}}
        self.assertEqual(choose_backend(synthetic, "auto")["selected"], "cpu")
        self.assertFalse(choose_backend(synthetic, "gpu")["ready"])
        synthetic["speech"]["ready_cpu"] = False
        self.assertFalse(choose_backend(synthetic, "auto")["ready"])

    def test_qwen_unsupported_language_does_not_replace_whisper(self):
        tr = karaoke_alignment_choice("tr", requested="auto", qwen_installed=True)
        self.assertEqual(tr["engine"], "whisper")
        self.assertTrue(tr["whisper_caption_independent"])

    def test_dry_plan_never_reads_or_writes_private_settings(self):
        result = self.supplied()
        self.assertEqual(set(result), set(DEFAULTS))
        self.assertEqual(result["model_path"], str(self.model))
        self.assertEqual(result["model_dir"], str(self.ssd))
        self.assertEqual(result["backend"], "auto")
        self.assertFalse(result["asr_enabled"])
        self.assertFalse(result["translation_enabled"])
        self.assertEqual(result["active_profile"], "")
        self.assertFalse((self.preview/".config/tihulu-tv-center").exists())
        self.assert_owner_untouched()

    def test_apply_new_preview_only_is_mode_0600_and_valid_ai_json(self):
        result = self.supplied(backend="gpu", translator="nllb")
        target = compat.apply_to_new_preview(result)
        self.assertEqual(target, self.preview/".config/tihulu-tv-center/ai-settings.json")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(json.loads(target.read_text()), result)
        settings = AISettings(path=target)
        self.assertFalse(settings.values["asr_enabled"])
        self.assertEqual(settings.values["translation_model"], "nllb")
        self.assert_owner_untouched()

    def test_apply_refuses_existing_preview_preferences(self):
        target = self.preview/".config/tihulu-tv-center/ai-settings.json"
        target.parent.mkdir()
        target.write_text("EXISTING_PRIVATE_PREVIEW", encoding="utf-8")
        with self.assertRaises(compat.CompatibilityError):
            compat.apply_to_new_preview(self.supplied())
        self.assertEqual(target.read_text(), "EXISTING_PRIVATE_PREVIEW")
        self.assert_owner_untouched()

    def test_apply_refuses_symlinked_preview_settings_and_parent(self):
        folder = self.preview/".config/tihulu-tv-center"
        folder.mkdir()
        target = folder/"ai-settings.json"
        target.symlink_to(self.original)
        with self.assertRaises(compat.CompatibilityError):
            compat.apply_to_new_preview(self.supplied())
        self.assert_owner_untouched()
        target.unlink()
        folder.rmdir()
        folder.symlink_to(self.original.parent, target_is_directory=True)
        with self.assertRaises(compat.CompatibilityError):
            compat.apply_to_new_preview(self.supplied())
        self.assert_owner_untouched()

    def test_apply_refuses_missing_or_foreign_marker(self):
        marker = self.app/compat.MARKER
        marker.unlink()
        with self.assertRaises(compat.CompatibilityError):
            compat.apply_to_new_preview(self.supplied())
        marker.write_text("FOREIGN_MARKER")
        with self.assertRaises(compat.CompatibilityError):
            compat.apply_to_new_preview(self.supplied())
        self.assert_owner_untouched()

    def test_model_symlink_or_missing_path_refused(self):
        link = self.home/"legacy-model-link.bin"
        link.symlink_to(self.model)
        with self.assertRaises(compat.CompatibilityError):
            compat.checked_path(str(link), "file")
        with self.assertRaises(compat.CompatibilityError):
            compat.checked_path(str(self.home/"not-a-file.bin"), "file")
        with self.assertRaises(compat.CompatibilityError):
            compat.checked_path(str(self.ssd/".."/"synthetic-ssd-model-folder"), "directory")
        self.assert_owner_untouched()

    def test_cli_requires_explicit_confirmation(self):
        # No user settings or model file is ever loaded, even on refused --apply.
        code = compat.main(["--model-path", str(self.model), "--apply"])
        self.assertEqual(code, 2)
        self.assertFalse((self.preview/".config/tihulu-tv-center").exists())
        self.assert_owner_untouched()

    def test_cli_default_is_read_only_and_no_private_access(self):
        code = compat.main(["--model-path", str(self.model), "--model-dir", str(self.ssd)])
        self.assertEqual(code, 0)
        self.assertFalse((self.preview/".config/tihulu-tv-center").exists())
        self.assert_owner_untouched()

    @unittest.skipIf(os.geteuid() == 0, "Apply test requires a non-root disposable runner")
    def test_cli_approved_apply_remains_disabled(self):
        code = compat.main(["--model-path", str(self.model), "--model-dir", str(self.ssd),
                            "--apply", "--confirm-preview-only"])
        self.assertEqual(code, 0)
        target = self.preview/".config/tihulu-tv-center/ai-settings.json"
        self.assertTrue(target.is_file())
        self.assertFalse(json.loads(target.read_text())["asr_enabled"])
        self.assert_owner_untouched()


if __name__ == "__main__":
    unittest.main()
