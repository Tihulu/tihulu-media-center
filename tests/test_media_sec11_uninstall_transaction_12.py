# SPDX-License-Identifier: GPL-2.0-or-later
"""SEC11 uninstall journal, failure injection, inode binding and SIGKILL recovery.

All mutations are confined to disposable non-root HOME fixtures. No hardware,
models, services or owner-machine data is accessed.
"""
from __future__ import annotations

import errno
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "installer/preview_safety.py"
spec = importlib.util.spec_from_file_location("media_sec11", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@unittest.skipIf(os.geteuid() == 0, "Requires a disposable ordinary-user HOME")
class SEC11UninstallTransaction(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="media-sec11-")
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "ordinary-home"
        self.root = self.home / ".local/opt/tihulu-media-stable"
        self.release_a = self.root / "releases/r-7821769eb7ae-20261112T090001-10"
        self.release_b = self.root / "releases/r-7821769eb7ae-20261112T090002-20"
        for release, content in ((self.release_a, b"native-a"),
                                 (self.release_b, b"native-b")):
            (release / "native/bin").mkdir(parents=True)
            (release / "native/bin/kaffeine").write_bytes(content)
            (release / "py").mkdir()
            (release / "py/source.txt").write_text("FROZEN PREVIEW SOURCE")
            m.prepare_release(release)
        (self.root / m.MARKER).write_text(m.MARKER_VALUE)
        (self.root / "current").symlink_to(str(self.release_b))
        (self.root / "previous").symlink_to(str(self.release_a))
        self.launcher = self.home / ".local/bin/tihulu-media-stable"
        self.desktop = self.home / ".local/share/applications/tihulu-media-stable.desktop"
        self.launcher.parent.mkdir(parents=True)
        self.desktop.parent.mkdir(parents=True)
        self.launcher.write_text(m.LAUNCH)
        self.launcher.chmod(0o755)
        self.desktop.write_text(m.desktop_text(self.home, self.root))
        (self.root / "preview-home/.config/tihulu-tv-center").mkdir(parents=True)
        (self.root / "preview-home/.config/tihulu-tv-center/ai-settings.json").write_text("PRIVATE PREVIEW KEEP")
        self.owner = self.home / "OWNER-PRIVATE-RECORDING.wav"
        self.owner.write_bytes(b"OWNER-PRIVATE-KEEP")
        self.txn = self.root / m.UNINSTALL_TXN
        self.env = {**os.environ, "HOME": str(self.home)}

    def assert_private(self):
        self.assertEqual(self.owner.read_bytes(), b"OWNER-PRIVATE-KEEP")
        self.assertEqual((self.root / "preview-home/.config/tihulu-tv-center/ai-settings.json").read_text(),
                         "PRIVATE PREVIEW KEEP")

    def assert_staged(self):
        self.assertTrue((self.txn / m.TXN_COMMITTED).is_file())
        self.assertTrue((self.txn / m.TXN_PLAN).is_file())
        self.assertFalse(m.present(self.launcher))
        self.assertFalse(m.present(self.desktop))
        self.assertFalse(m.present(self.root / "current"))
        self.assertFalse(m.present(self.root / "previous"))
        self.assertEqual((self.txn / "launcher").read_text(), m.LAUNCH)
        self.assertEqual((self.txn / "desktop").read_text(),
                         m.desktop_text(self.home, self.root))
        self.assertEqual(os.readlink(self.txn / "current"), str(self.release_b))
        self.assertEqual(os.readlink(self.txn / "previous"), str(self.release_a))
        self.assert_private()

    def second_delete_failure(self):
        old = m.shutil.rmtree
        seen = []
        def fail_second(name, *args, **kwargs):
            if kwargs.get("dir_fd") is not None:
                seen.append(name)
                if len(seen) == 2:
                    raise OSError(errno.EIO, "synthetic second release removal failure")
            return old(name, *args, **kwargs)
        with patch.object(m.shutil, "rmtree", side_effect=fail_second):
            with self.assertRaises(OSError):
                m.uninstall(self.home)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen, [self.release_a.name, self.release_b.name])

    def test_second_release_failure_is_committed_not_half_active(self):
        self.second_delete_failure()
        self.assert_staged()
        self.assertFalse(self.release_a.exists())
        self.assertTrue(self.release_b.exists())
        m.verify_release(self.release_b)
        with self.assertRaises(m.SafetyError):
            m.validate_existing(self.home)
        self.assert_private()

    def test_explicit_retry_cleans_only_verified_remaining_release(self):
        self.second_delete_failure()
        m.uninstall(self.home)
        self.assertFalse(m.present(self.txn))
        self.assertFalse(self.release_a.exists())
        self.assertFalse(self.release_b.exists())
        self.assertFalse((self.root / "releases").exists())
        self.assertFalse(m.present(self.launcher))
        self.assertFalse(m.present(self.desktop))
        self.assertFalse(m.present(self.root / "current"))
        self.assertFalse(m.present(self.root / "previous"))
        self.assertTrue((self.root / m.MARKER).is_file())
        self.assert_private()
        m.uninstall(self.home)  # repeat uninstall remains idempotent
        self.assert_private()

    def test_cli_explicit_retry_runs_through_shared_operations_lock(self):
        self.second_delete_failure()
        result = subprocess.run(
            ["bash", str(ROOT / "installer/media-stable-first.sh"), "--uninstall"],
            env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(m.present(self.txn))
        self.assert_private()

    def test_pending_committed_state_blocks_install_and_rollback(self):
        self.second_delete_failure()
        for arg in ("--install", "--rollback"):
            result = subprocess.run(
                ["bash", str(ROOT / "installer/media-stable-first.sh"), arg],
                env=self.env, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
        self.assert_staged()

    def test_second_release_partially_mutated_fails_closed_on_retry(self):
        original = m.shutil.rmtree
        count = 0
        def corrupt_then_fail(name, *args, **kwargs):
            nonlocal count
            if kwargs.get("dir_fd") is not None:
                count += 1
                if count == 2:
                    (self.release_b / "unexpected-owner-data").write_bytes(b"NEVER DELETE")
                    raise OSError(errno.EIO, "synthetic interrupted second removal")
            return original(name, *args, **kwargs)
        with patch.object(m.shutil, "rmtree", side_effect=corrupt_then_fail):
            with self.assertRaises(OSError):
                m.uninstall(self.home)
        self.assert_staged()
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertEqual((self.release_b / "unexpected-owner-data").read_bytes(), b"NEVER DELETE")
        self.assert_staged()

    def test_failure_during_first_quarantine_move_stays_precommit(self):
        original = m._stage_uninstall_path
        def injected(home, root, plan, slot):
            if slot == "desktop":
                raise OSError(errno.EIO, "staging interrupted before desktop move")
            return original(home, root, plan, slot)
        with patch.object(m, "_stage_uninstall_path", side_effect=injected):
            with self.assertRaises(OSError):
                m.uninstall(self.home)
        self.assertTrue((self.txn / m.TXN_PLAN).is_file())
        self.assertFalse((self.txn / m.TXN_COMMITTED).exists())
        self.assertTrue((self.txn / "launcher").is_file())
        self.assertFalse(self.launcher.exists())
        self.assertTrue(self.desktop.is_file())
        self.assertTrue(self.release_a.exists())
        self.assertTrue(self.release_b.exists())
        self.assert_private()
        m.uninstall(self.home)  # resume precommit staging deterministically
        self.assertFalse(m.present(self.txn))
        self.assert_private()

    def test_tampered_pending_transaction_does_not_auto_delete(self):
        original = m._stage_uninstall_path
        def inject(home, root, plan, slot):
            if slot == "desktop":
                raise OSError(errno.EIO, "simulated precommit interruption")
            return original(home, root, plan, slot)
        with patch.object(m, "_stage_uninstall_path", side_effect=inject):
            with self.assertRaises(OSError):
                m.uninstall(self.home)
        other = self.txn / "private-user-file.txt"
        other.write_text("UNKNOWN USER DATA")
        with self.assertRaises(m.SafetyError):
            m.uninstall(self.home)
        self.assertEqual(other.read_text(), "UNKNOWN USER DATA")
        self.assertTrue(self.release_a.exists())
        self.assertTrue(self.release_b.exists())
        self.assert_private()

    def test_bad_plan_or_symlink_journal_refuses_recovery(self):
        original = m._stage_uninstall_path
        with patch.object(m, "_stage_uninstall_path",
                          side_effect=OSError(errno.EIO, "stop after durable plan")):
            with self.assertRaises(OSError):
                m.uninstall(self.home)
        plan = self.txn / m.TXN_PLAN
        plan.unlink()
        plan.symlink_to(self.owner)
        with self.assertRaises((m.SafetyError, OSError)):
            m.uninstall(self.home)
        self.assertTrue(self.launcher.exists())
        self.assertTrue(self.release_a.exists())
        self.assert_private()

    def test_inode_substitution_between_verification_and_quarantine_is_reversed(self):
        orig = m._rename_noreplace
        swapped = False
        saved = self.home / "saved-original-launcher"
        def injected(srcfd, src, dstfd, dst):
            nonlocal swapped
            if src == self.launcher.name and not swapped:
                swapped = True
                self.launcher.rename(saved)
                self.launcher.write_text("FOREIGN REPLACEMENT NEVER DELETE")
                self.launcher.chmod(0o755)
            return orig(srcfd, src, dstfd, dst)
        with patch.object(m, "_rename_noreplace", side_effect=injected):
            with self.assertRaises(m.SafetyError):
                m.uninstall(self.home)
        self.assertTrue(swapped)
        self.assertEqual(self.launcher.read_text(), "FOREIGN REPLACEMENT NEVER DELETE")
        self.assertEqual(saved.read_text(), m.LAUNCH)
        self.assertFalse((self.txn / "launcher").exists())
        self.assertFalse((self.txn / m.TXN_COMMITTED).exists())
        self.assertTrue(self.release_a.exists())
        self.assert_private()

    def test_rename_noreplace_refuses_concurrent_destination_injection(self):
        original = m._rename_noreplace
        fired = False
        def injected(srcfd, src, dstfd, dst):
            nonlocal fired
            if src == self.launcher.name and not fired:
                fired = True
                (self.txn / "launcher").write_text("FOREIGN QUARANTINE COLLISION")
            return original(srcfd, src, dstfd, dst)
        with patch.object(m, "_rename_noreplace", side_effect=injected):
            with self.assertRaises(FileExistsError):
                m.uninstall(self.home)
        self.assertTrue(self.launcher.exists())
        self.assertEqual((self.txn / "launcher").read_text(), "FOREIGN QUARANTINE COLLISION")
        self.assertTrue(self.release_b.exists())
        self.assert_private()

    def test_final_unlink_inode_swap_detected_before_delete(self):
        real_stat = m.os.stat
        original_rmtree = m.shutil.rmtree
        # Keep the transaction after release cleanup by substituting a
        # symlink at the final fstat-vs-lstat decision on quarantined launcher.
        changed = False
        def injected_stat(path, *args, **kwargs):
            nonlocal changed
            if (path == "launcher" and kwargs.get("dir_fd") is not None
                    and kwargs.get("follow_symlinks") is False and not changed
                    and (self.txn / m.TXN_COMMITTED).is_file()
                    and (self.txn / "launcher").exists()):
                changed = True
                (self.txn / "launcher").rename(self.home / "saved-quarantine-launcher")
                (self.txn / "launcher").symlink_to(self.owner)
            return real_stat(path, *args, **kwargs)
        with patch.object(m.os, "stat", side_effect=injected_stat):
            with self.assertRaises(m.SafetyError):
                m.uninstall(self.home)
        self.assertTrue(changed)
        self.assertTrue((self.txn / "launcher").is_symlink())
        self.assertEqual((self.home / "saved-quarantine-launcher").read_text(), m.LAUNCH)
        self.assert_private()

    def test_release_parent_replacement_during_delete_is_detected(self):
        original = m.shutil.rmtree
        fired = False
        moved = self.root / "releases-parent-preserved-by-race"
        def injected(name, *args, **kwargs):
            nonlocal fired
            if kwargs.get("dir_fd") is not None and not fired:
                fired = True
                (self.root / "releases").rename(moved)
                (self.root / "releases").mkdir(mode=0o700)
            return original(name, *args, **kwargs)
        with patch.object(m.shutil, "rmtree", side_effect=injected):
            with self.assertRaises(m.SafetyError):
                m.uninstall(self.home)
        self.assertTrue(fired)
        self.assert_staged()
        self.assertTrue(moved.is_dir())
        self.assert_private()

    def test_sigkill_precommit_quarantine_is_resumable_without_private_cleanup(self):
        # This deliberately terminates a disposable subprocess, never a live
        # installer, and demonstrates recoverable precommit movement.
        code = (
            "import importlib.util, os; "
            f"p={str(SCRIPT)!r}; "
            "spec=importlib.util.spec_from_file_location('sec11_kill',p); "
            "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
            "original=m._stage_uninstall_path; "
            "defn=''; "
            "def stop(h,r,plan,slot):\n"
            "    original(h,r,plan,slot)\n"
            "    if slot == 'launcher': os.kill(os.getpid(), 9)\n"
            "m._stage_uninstall_path=stop; "
            f"m.uninstall(__import__('pathlib').Path({str(self.home)!r}))"
        )
        # Python's compound function syntax must begin on a new logical line.
        code = code.replace("defn=''; def stop", "\ndef stop")
        process = subprocess.run([sys.executable, "-c", code], env=self.env,
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, -signal.SIGKILL, process.stderr)
        self.assertTrue((self.txn / m.TXN_PLAN).is_file())
        self.assertFalse((self.txn / m.TXN_COMMITTED).exists())
        self.assertTrue((self.txn / "launcher").is_file())
        self.assertTrue(self.desktop.exists())
        self.assertTrue(self.release_a.exists())
        self.assert_private()
        m.uninstall(self.home)
        self.assertFalse(m.present(self.txn))
        self.assert_private()

    def test_verified_two_release_normal_uninstall_and_repeat(self):
        m.uninstall(self.home)
        self.assertFalse(self.release_a.exists())
        self.assertFalse(self.release_b.exists())
        self.assertFalse((self.root / "releases").exists())
        self.assertFalse(m.present(self.launcher))
        self.assertFalse(m.present(self.desktop))
        self.assertFalse(m.present(self.root / "current"))
        self.assertFalse(m.present(self.root / "previous"))
        self.assertFalse(m.present(self.txn))
        self.assert_private()
        m.uninstall(self.home)
        self.assert_private()


if __name__ == "__main__":
    unittest.main()
