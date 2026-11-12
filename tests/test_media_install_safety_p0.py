# SPDX-License-Identifier: GPL-2.0-or-later
"""Negative safety tests: no real models, tuner, services or user settings."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import os
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "installer/preview_safety.py"
spec = importlib.util.spec_from_file_location("media_preview_safety", MODULE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@unittest.skipIf(os.geteuid() == 0, "Ownership tests run with non-root CI runner")
class UninstallSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = self.home / ".local/opt/tihulu-media-stable"
        self.release = self.root / "releases/r-7821769eb7ae-20261112T080000-1"
        self.launch = self.home / ".local/bin/tihulu-media-stable"
        self.desktop = self.home / ".local/share/applications/tihulu-media-stable.desktop"
        self.release.joinpath("native/bin").mkdir(parents=True)
        self.launch.parent.mkdir(parents=True)
        self.desktop.parent.mkdir(parents=True)
        (self.root / m.MARKER).write_text(m.MARKER_VALUE)
        (self.release / "native/bin/kaffeine").write_bytes(b"synthetic bin")
        self.release.joinpath("py").mkdir()
        (self.release / "py/ai.json").write_text("owned source\n")
        (self.root / "preview-home/.config/tihulu-tv-center").mkdir(parents=True)
        (self.root / "preview-home/.config/tihulu-tv-center/ai-settings.json").write_text("private preview settings\n")
        (self.home / ".config/TIHULU").mkdir(parents=True)
        (self.home / ".config/TIHULU/KaffeineRadio.conf").write_text("OWNER-KEEP\n")
        (self.home / ".config/tihulu-tv-center").mkdir(parents=True)
        (self.home / ".config/tihulu-tv-center/ai-settings.json").write_text("OWNER-AI-KEEP\n")
        m.prepare_release(self.release)
        (self.root / "current").symlink_to(str(self.release))
        self.launch.write_text(m.LAUNCH)
        self.desktop.write_text(m.desktop_text(self.home, self.root))

    def assert_preserved(self):
        self.assertEqual((self.home / ".config/TIHULU/KaffeineRadio.conf").read_text(), "OWNER-KEEP\n")
        self.assertEqual((self.home / ".config/tihulu-tv-center/ai-settings.json").read_text(), "OWNER-AI-KEEP\n")

    def test_uninstall_owned_binaries_preserves_private_preview_and_owner(self):
        m.uninstall(self.home)
        self.assertFalse(self.release.exists())
        self.assertFalse(self.launch.exists())
        self.assertFalse(self.desktop.exists())
        self.assertFalse((self.root / "current").exists())
        self.assertEqual((self.root / "preview-home/.config/tihulu-tv-center/ai-settings.json").read_text(),
                         "private preview settings\n")
        self.assert_preserved()

    def test_second_uninstall_idempotent_preserves_private_home(self):
        m.uninstall(self.home)
        m.uninstall(self.home)
        self.assertTrue((self.root / m.MARKER).is_file())
        self.assertFalse(self.release.exists())
        self.assert_preserved()

    def test_modified_launcher_causes_total_refusal(self):
        self.launch.write_text("#!/bin/sh\nexec arbitrary\n")
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertTrue(self.release.exists())
        self.assert_preserved()

    def test_modified_desktop_causes_total_refusal(self):
        self.desktop.write_text(self.desktop.read_text() + "\nExec=/usr/bin/other\n")
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertTrue(self.launch.exists())
        self.assert_preserved()

    def test_changed_file_in_release_refuses_uninstall(self):
        (self.release / "py/ai.json").write_text("USER MODIFIED\n")
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertTrue(self.launch.exists())
        self.assert_preserved()

    def test_extra_user_file_in_release_refuses_uninstall(self):
        (self.release / "my-recording.wav").write_text("USER\n")
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertEqual((self.release / "my-recording.wav").read_text(), "USER\n")
        self.assert_preserved()

    def test_foreign_symlink_in_release_refuses_uninstall(self):
        outside = self.home / "precious.txt"
        outside.write_text("DO NOT DELETE")
        (self.release / "foreign").symlink_to(outside)
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertEqual(outside.read_text(), "DO NOT DELETE")
        self.assert_preserved()

    def test_current_pointer_external_refuses(self):
        (self.root / "current").unlink()
        (self.root / "current").symlink_to(self.home / ".config")
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertTrue(self.launch.exists())
        self.assert_preserved()

    def test_incomplete_install_directory_refuses(self):
        stage = self.root / ".stage.interrupted"
        stage.mkdir()
        (stage / "draft.txt").write_text("interrupted")
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertEqual((stage / "draft.txt").read_text(), "interrupted")
        self.assert_preserved()

    def test_symlink_profile_refuses(self):
        profile = self.root / "preview-home"
        # Deliberately test a hostile replacement of the preview profile root.
        private_data = self.home / "retained-backup"
        profile.rename(private_data)
        profile.symlink_to(private_data, target_is_directory=True)
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertTrue(private_data.joinpath(".config/tihulu-tv-center/ai-settings.json").is_file())
        self.assert_preserved()

    def test_symlink_install_lock_refuses_uninstall_and_rollback(self):
        import subprocess
        original = self.home / "precious-lock-target"
        original.write_text("PRIVATE UNCHANGED\n")
        (self.root / ".install.lock").symlink_to(original)
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        env = {**os.environ, "HOME": str(self.home)}
        p = subprocess.run(["bash", str(ROOT / "installer/media-stable-first.sh"),
                            "--rollback"], capture_output=True, text=True, env=env)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(original.read_text(), "PRIVATE UNCHANGED\n")
        self.assertTrue(self.launch.exists())
        self.assert_preserved()

    def test_missing_owner_marker_refuses(self):
        (self.root / m.MARKER).unlink()
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assert_preserved()

    def rollback_cli(self):
        import subprocess
        return subprocess.run(
            ["bash", str(ROOT / "installer/media-stable-first.sh"), "--rollback"],
            capture_output=True, text=True,
            env={**os.environ, "HOME": str(self.home)},
        )

    def test_rollback_previous_traversal_is_rejected_without_mutation(self):
        # The old glob allowed releases/../preview-home, redirecting current
        # to arbitrary directories outside the releases subtree.
        other = str(self.root / "releases/../preview-home")
        (self.root / "previous").symlink_to(other)
        original = os.readlink(self.root / "current")
        proc = self.rollback_cli()
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(os.readlink(self.root / "current"), original)
        self.assertEqual(os.readlink(self.root / "previous"), other)
        self.assertTrue(self.release.exists())
        self.assert_preserved()

    def test_rollback_current_traversal_is_rejected_without_mutation(self):
        old = str(self.root / "releases/../preview-home")
        (self.root / "current").unlink()
        (self.root / "current").symlink_to(old)
        (self.root / "previous").symlink_to(str(self.release))
        proc = self.rollback_cli()
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(os.readlink(self.root / "current"), old)
        self.assertTrue(self.release.exists())
        self.assert_preserved()

    def test_rollback_requires_valid_owner_marker(self):
        (self.root / m.MARKER).unlink()
        (self.root / "previous").symlink_to(str(self.release))
        original = os.readlink(self.root / "current")
        proc = self.rollback_cli()
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("ownership marker", proc.stderr)
        self.assertEqual(os.readlink(self.root / "current"), original)
        self.assertFalse((self.root / ".install.lock").exists())
        self.assert_preserved()

    def test_rollback_rejects_symlinked_app_parent(self):
        opt = self.home / ".local/opt"
        original = self.home / ".local/opt-preserved"
        opt.rename(original)
        opt.symlink_to(original, target_is_directory=True)
        proc = self.rollback_cli()
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("Unsafe rollback parent", proc.stderr)
        self.assertTrue((original / "tihulu-media-stable/current").is_symlink())
        self.assert_preserved()

    def test_rollback_valid_direct_release_still_works(self):
        second = self.root / "releases/r-7821769eb7ae-20261112T080001-2"
        second.mkdir()
        (self.root / "previous").symlink_to(str(second))
        proc = self.rollback_cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(os.readlink(self.root / "current"), str(second))
        self.assertEqual(os.readlink(self.root / "previous"), str(self.release))
        self.assert_preserved()

    def test_modified_release_manifest_refuses_uninstall(self):
        manifest = self.release / m.MANIFEST
        manifest.write_text('{"schema": 1, "entries": {}}\\n')
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertTrue(self.launch.exists())
        self.assertTrue(self.release.exists())
        self.assert_preserved()


if __name__ == "__main__":
    unittest.main()
