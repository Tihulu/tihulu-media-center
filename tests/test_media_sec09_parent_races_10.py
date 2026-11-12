# SPDX-License-Identifier: GPL-2.0-or-later
"""SEC-09: non-root, disposable managed-directory and adversarial race probes.

No physical receivers, owner machine, GPU, service or model access.
"""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "installer/preview_safety.py"
spec = importlib.util.spec_from_file_location("media_sec09", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@unittest.skipIf(os.geteuid() == 0, "Requires an unprivileged disposable CI user")
class SEC09DirectoryAndRaceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="media-sec09-")
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "ordinary-home"
        self.root = self.home / ".local/opt/tihulu-media-stable"
        self.release = self.root / "releases/r-7821769eb7ae-20261112T090001-42"
        (self.release / "native/bin").mkdir(parents=True)
        (self.release / "native/bin/kaffeine").write_bytes(b"synthetic-media-binary")
        m.prepare_release(self.release)
        (self.root / m.MARKER).write_text(m.MARKER_VALUE)
        (self.root / "current").symlink_to(str(self.release))
        self.launcher = self.home / ".local/bin/tihulu-media-stable"
        self.desktop = self.home / ".local/share/applications/tihulu-media-stable.desktop"
        self.launcher.parent.mkdir(parents=True)
        self.desktop.parent.mkdir(parents=True)
        self.launcher.write_text(m.LAUNCH)
        self.launcher.chmod(0o755)
        self.desktop.write_text(m.desktop_text(self.home, self.root))
        (self.root / "preview-home/.config").mkdir(parents=True)
        self.owner = self.home / "private-owner-recording.bin"
        self.owner.write_bytes(b"OWNER PRIVATE NEVER DELETE")
        self.env = {**os.environ, "HOME": str(self.home)}

    def owner_safe(self):
        self.assertEqual(self.owner.read_bytes(), b"OWNER PRIVATE NEVER DELETE")

    def rejects_writable(self, path, mode):
        initial = stat.S_IMODE(path.stat().st_mode)
        path.chmod(mode)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
        with self.assertRaises((m.SafetyError, OSError)):
            m.validate_existing(self.home)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode,
                         "SEC09 must refuse, never chmod or auto-repair")
        self.assertFalse((self.home / ".local/opt" / m.SERIAL_LOCK).exists())
        self.owner_safe()
        path.chmod(initial)
        m.validate_existing(self.home)

    def test_ordinary_secure_0700_and_0755_directories_pass(self):
        for folder in (self.home, self.home / ".local",
                       self.home / ".local/opt", self.root):
            folder.chmod(0o700)
        m.validate_existing(self.home)
        for folder in (self.home, self.home / ".local",
                       self.home / ".local/opt", self.root):
            folder.chmod(0o755)
        m.validate_existing(self.home)
        self.owner_safe()

    def test_group_writable_local_parent_refused(self):
        self.rejects_writable(self.home / ".local", 0o770)

    def test_world_writable_local_parent_refused(self):
        self.rejects_writable(self.home / ".local", 0o777)

    def test_group_writable_lock_parent_opt_refused(self):
        self.rejects_writable(self.home / ".local/opt", 0o770)

    def test_world_writable_lock_parent_opt_refused(self):
        self.rejects_writable(self.home / ".local/opt", 0o777)

    def test_group_writable_application_root_refused(self):
        self.rejects_writable(self.root, 0o770)

    def test_world_writable_application_root_refused(self):
        self.rejects_writable(self.root, 0o777)

    def test_group_writable_home_refused_without_scanning_tmp_ancestor(self):
        self.rejects_writable(self.home, 0o770)

    def test_group_writable_launcher_parent_refused(self):
        self.rejects_writable(self.launcher.parent, 0o770)

    def test_world_writable_desktop_parent_refused(self):
        self.rejects_writable(self.desktop.parent, 0o777)

    def test_group_writable_releases_parent_refused(self):
        self.rejects_writable(self.root / "releases", 0o770)

    def test_world_writable_release_dir_refused(self):
        self.rejects_writable(self.release, 0o777)

    def test_group_writable_nested_release_path_refused(self):
        nested = self.release / "native/bin"
        self.rejects_writable(nested, 0o770)

    def test_world_writable_private_preview_profile_refused(self):
        self.rejects_writable(self.root / "preview-home", 0o777)

    def test_secure_lock_never_created_in_writable_parent(self):
        p = self.home / ".local/opt"
        p.chmod(0o777)
        with self.assertRaises(m.SafetyError):
            m.secure_lock(self.home)
        self.assertFalse((p / m.SERIAL_LOCK).exists())
        self.owner_safe()

    def test_held_lock_refuses_later_chmod_of_parent(self):
        fd = m.secure_lock(self.home)
        try:
            opt = self.home / ".local/opt"
            opt.chmod(0o770)
            with self.assertRaises((m.SafetyError, OSError)):
                m.verify_guard(self.home, fd)
            self.assertEqual(stat.S_IMODE(opt.stat().st_mode), 0o770)
            self.owner_safe()
        finally:
            os.close(fd)

    def test_lock_parent_replaced_while_held_is_detected(self):
        fd = m.secure_lock(self.home)
        opt = self.home / ".local/opt"
        moved = self.home / ".local/opt-old"
        try:
            opt.rename(moved)
            opt.mkdir(mode=0o700)
            with self.assertRaises((m.SafetyError, OSError)):
                m.verify_guard(self.home, fd)
            self.assertFalse((opt / m.SERIAL_LOCK).exists())
            self.assertTrue((moved / m.SERIAL_LOCK).exists())
            self.owner_safe()
        finally:
            os.close(fd)

    def test_desktop_symlink_injection_during_exclusive_publish(self):
        self.desktop.unlink()
        raw_open = os.open
        def inject(path, flags, mode=0o777, *args, **kwargs):
            if str(path) == str(self.desktop) and flags & os.O_EXCL:
                self.desktop.symlink_to(self.owner)
            return raw_open(path, flags, mode, *args, **kwargs)
        with patch.object(m.os, "open", side_effect=inject):
            with self.assertRaises((OSError, m.SafetyError)):
                m.publish_entrypoints(self.home)
        self.assertTrue(self.desktop.is_symlink())
        self.owner_safe()

    def test_release_tampered_after_first_verify_before_uninstall_deletion(self):
        original = m.verify_release
        count = 0
        def inject(path):
            nonlocal count
            original(path)
            if Path(path) == self.release:
                count += 1
                if count == 1:
                    (self.release / "attacker-file").write_bytes(b"FOREIGN DATA")
        with patch.object(m, "verify_release", side_effect=inject):
            with self.assertRaises(m.SafetyError):
                m.uninstall(self.home)
        self.assertTrue(self.launcher.is_file())
        self.assertTrue(self.desktop.is_file())
        self.assertTrue((self.release / "attacker-file").is_file())
        self.owner_safe()

    def test_releases_fd_scoped_delete_rejects_last_moment_symlink(self):
        original = m.shutil.rmtree
        moved = self.root / "releases/r-moved-safely"
        def inject(path, *args, **kwargs):
            if path == self.release.name and kwargs.get("dir_fd") is not None:
                self.release.rename(moved)
                self.release.symlink_to(self.home, target_is_directory=True)
            return original(path, *args, **kwargs)
        with patch.object(m.shutil, "rmtree", side_effect=inject):
            with self.assertRaises((OSError, m.SafetyError)):
                m.uninstall(self.home)
        self.assertTrue(moved.is_dir())
        self.owner_safe()

    def test_sigkill_interrupted_stage_stays_untouched_and_manual_recovery_works(self):
        # Kill a disposable process that genuinely holds the operations FD.
        # Do NOT ever recover by deleting stage content automatically.
        stage = self.root / ".stage.simulated-kill"
        sentinel = stage / "keep-owner-file"
        code = (
            "import importlib.util, pathlib, time; "
            f"spec=importlib.util.spec_from_file_location('sec09_killed', {str(SCRIPT)!r}); "
            "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
            f"fd=m.secure_lock(pathlib.Path({str(self.home)!r})); "
            f"p=pathlib.Path({str(stage)!r}); p.mkdir(); "
            "(p/'keep-owner-file').write_text('PRESERVE STAGE'); "
            "time.sleep(30)"
        )
        process = subprocess.Popen([sys.executable, "-c", code], env=self.env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(150):
                if sentinel.exists() or process.poll() is not None:
                    break
                time.sleep(0.02)
            self.assertTrue(sentinel.exists(), "Disposable lock-holder never created stage")
            process.kill()
            process.communicate(timeout=5)
            self.assertIsNotNone(process.returncode)
            with self.assertRaises(m.SafetyError):
                m.validate_existing(self.home)
            self.assertEqual(sentinel.read_text(), "PRESERVE STAGE")
            # Recovery explicitly simulated by owner in disposable CI ONLY.
            shutil.rmtree(stage)
            m.validate_existing(self.home)
            self.assertEqual(m.guard_command(self.home, ["/usr/bin/true"]), 0)
            self.owner_safe()
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
