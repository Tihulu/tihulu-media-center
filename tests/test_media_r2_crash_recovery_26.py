#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""P2-QA25-01: real r2 subprocess SIGKILL, explicit restart, journal HOLD.

All paths are within an isolated disposable ordinary-user HOME. No application
installation, actual hardware, models, services, owner data, or network calls.
SIGKILL is applied ONLY to the disposable Python worker subprocess.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SAFETY = ROOT / "installer" / "preview_safety.py"
spec = importlib.util.spec_from_file_location("r2_crash_under_test", SAFETY)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SNAP = "7821769eb7ae"
STAMP = "20261113T040000"


@unittest.skipIf(os.geteuid() == 0, "Refuse all disposable install fixtures as root")
class R2CrashRecovery(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="media-r2-crash-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "isolated-owner"
        self.home.mkdir(mode=0o700)
        self.app = self.home / ".local/opt/tihulu-media-stable"
        self.releases = self.app / "releases"
        self.releases.mkdir(parents=True)
        self.first = self.make_release("11", b"release-1-not-real-binary")
        self.second = self.make_release("22", b"release-2-not-real-binary")
        (self.app / m.MARKER).write_text(m.MARKER_VALUE)
        (self.app / "current").symlink_to(str(self.second))
        (self.app / "previous").symlink_to(str(self.first))
        self.launcher = self.home / ".local/bin/tihulu-media-stable"
        self.desktop = self.home / ".local/share/applications/tihulu-media-stable.desktop"
        self.launcher.parent.mkdir(parents=True)
        self.desktop.parent.mkdir(parents=True)
        self.launcher.write_text(m.LAUNCH)
        self.launcher.chmod(0o755)
        self.desktop.write_text(m.desktop_text(self.home, self.app))
        self.txn = self.app / m.UNINSTALL_TXN
        self.private = {
            self.home / "Recordings/owner.ts": b"KEEP OWNER RECORDING\n",
            self.home / ".config/TIHULU/private.conf": b"KEEP OWNER CONFIG\n",
            self.app / "preview-home/.config/private.json": b"KEEP PREVIEW STATE\n",
            self.home / "Models/owner-model.gguf": b"KEEP OWNER MODEL PLACEHOLDER\n",
        }
        for name, value in self.private.items():
            name.parent.mkdir(parents=True, exist_ok=True)
            name.write_bytes(value)
        self.digest_before = {
            str(name): hashlib.sha256(value).hexdigest()
            for name, value in self.private.items()
        }
        self.env = {**os.environ, "HOME": str(self.home),
                    "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1",
                    "TRANSFORMERS_OFFLINE": "1"}
        for release in (self.first, self.second):
            m.verify_release(release)
            manifest = (release / m.MANIFEST).read_text()
            self.assertIn(m.RELEASE_V2_FORMAT, manifest)
            self.assertIn(release.name, manifest)

    def make_release(self, pid: str, blob: bytes) -> Path:
        release = self.releases / ("r2-" + SNAP + "-" + STAMP + "-" + pid)
        (release / "native/bin").mkdir(parents=True)
        (release / "native/bin/kaffeine").write_bytes(blob)
        (release / "native/bin/kaffeine").chmod(0o755)
        (release / "py").mkdir()
        (release / "py/source.txt").write_bytes(b"synthetic preview fixture")
        m.stage_legal_notice_bundle(ROOT, release)
        m.prepare_release(release, v2_release_name=release.name)
        return release

    def assert_private(self):
        for name, expected in self.private.items():
            self.assertEqual(name.read_bytes(), expected, str(name))
            self.assertEqual(hashlib.sha256(name.read_bytes()).hexdigest(),
                             self.digest_before[str(name)])
        self.assertFalse((self.home / ".local/bin/kaffeine").exists())

    def kill_worker(self, point: str):
        hooks = {
            "plan": """
old = m._write_owned_exclusive
def inject(path, value):
    old(path, value)
    if path.name == m.TXN_PLAN:
        os.kill(os.getpid(), signal.SIGKILL)
m._write_owned_exclusive = inject
""",
            "commit": """
old = m._write_owned_exclusive
def inject(path, value):
    old(path, value)
    if path.name == m.TXN_COMMITTED:
        os.kill(os.getpid(), signal.SIGKILL)
m._write_owned_exclusive = inject
""",
            "first-release": """
old = m.shutil.rmtree
def inject(name, *args, **kwargs):
    answer = old(name, *args, **kwargs)
    if kwargs.get("dir_fd") is not None:
        assert name.endswith("-11"), name
        os.kill(os.getpid(), signal.SIGKILL)
    return answer
m.shutil.rmtree = inject
""",
            "launcher-unlink": """
old = m.unlink_verified_entrypoint
def inject(path, expected):
    old(path, expected)
    if path.name == "launcher":
        os.kill(os.getpid(), signal.SIGKILL)
m.unlink_verified_entrypoint = inject
""",
            "plan-final-unlink": """
old = Path.unlink
def inject(self, *args, **kwargs):
    answer = old(self, *args, **kwargs)
    if self.name == m.TXN_PLAN:
        os.kill(os.getpid(), signal.SIGKILL)
    return answer
Path.unlink = inject
""",
        }
        script = "\n".join([
            "import importlib.util, os, signal",
            "from pathlib import Path",
            "spec=importlib.util.spec_from_file_location('real_r2_installer',"
                + repr(str(SAFETY)) + ")",
            "m=importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(m)",
            hooks[point],
            "m.uninstall(Path(" + repr(str(self.home)) + "))",
        ])
        process = subprocess.run(
            [sys.executable, "-c", script], env=self.env,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, -signal.SIGKILL,
                         "point=" + point + " stdout=" + process.stdout
                         + " stderr=" + process.stderr)
        self.assertTrue(self.txn.is_dir())
        self.assert_private()

    def restart(self):
        return subprocess.run(
            [sys.executable, str(SAFETY), "uninstall"], env=self.env,
            capture_output=True, text=True, timeout=30)

    def assert_manual_hold(self):
        # A local spy additionally proves the verifier did not enter
        # irreversible deletion when the remaining release is untrusted.
        with patch.object(m.shutil, "rmtree",
                          side_effect=AssertionError("RELEASE DELETE ENTERED")) as spy:
            with self.assertRaises((m.SafetyError, OSError)):
                m.uninstall(self.home)
            spy.assert_not_called()
        process = self.restart()
        self.assertNotEqual(process.returncode, 0, process.stdout)
        self.assertIn("PREVIEW-SAFETY HOLD", process.stderr)
        self.assertTrue(self.second.is_dir(),
                        "A corrupt journal must not delete remaining release")
        self.assertTrue(self.txn.is_dir())
        self.assert_private()

    def assert_clean_recovery(self):
        process = self.restart()
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(self.first.exists())
        self.assertFalse(self.second.exists())
        self.assertFalse(m.present(self.txn))
        self.assertFalse(m.present(self.launcher))
        self.assertFalse(m.present(self.desktop))
        self.assertFalse(m.present(self.app / "current"))
        self.assertFalse(m.present(self.app / "previous"))
        self.assert_private()
        retry = self.restart()
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assert_private()

    def test_01_real_sigkill_after_durable_plan_before_staging(self):
        self.kill_worker("plan")
        self.assertTrue((self.txn / m.TXN_PLAN).is_file())
        self.assertFalse(m.present(self.txn / m.TXN_COMMITTED))
        self.assertTrue(self.first.is_dir())
        self.assertTrue(self.second.is_dir())
        self.assertTrue(self.launcher.is_file())
        self.assert_clean_recovery()

    def test_02_real_sigkill_after_committed_marker_before_release_delete(self):
        self.kill_worker("commit")
        self.assertTrue((self.txn / m.TXN_COMMITTED).is_file())
        self.assertTrue(self.first.is_dir())
        self.assertTrue(self.second.is_dir())
        self.assertFalse(m.present(self.launcher))
        self.assert_clean_recovery()

    def test_03_real_sigkill_after_first_r2_dirfd_removal(self):
        self.kill_worker("first-release")
        self.assertTrue((self.txn / m.TXN_COMMITTED).is_file())
        self.assertFalse(self.first.exists())
        self.assertTrue(self.second.is_dir())
        m.verify_release(self.second)
        self.assert_clean_recovery()

    def test_04_real_sigkill_after_final_quarantine_launcher_unlink(self):
        self.kill_worker("launcher-unlink")
        self.assertFalse(self.first.exists())
        self.assertFalse(self.second.exists())
        self.assertTrue((self.txn / m.TXN_COMMITTED).is_file())
        self.assertFalse(m.present(self.txn / "launcher"))
        self.assertTrue((self.txn / "desktop").is_file())
        self.assert_clean_recovery()

    def test_05_kill_after_final_plan_unlink_requires_manual_hold(self):
        # Even a completed release cleanup must not silently remove a
        # surviving, plan-less journal directory on a fresh restart.
        self.kill_worker("plan-final-unlink")
        self.assertFalse(self.first.exists())
        self.assertFalse(self.second.exists())
        self.assertTrue(self.txn.is_dir())
        self.assertFalse(m.present(self.txn / m.TXN_PLAN))
        result = self.restart()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PREVIEW-SAFETY HOLD", result.stderr)
        self.assertTrue(self.txn.is_dir())
        self.assert_private()

    def test_06_truncated_plan_on_restart_is_manual_hold(self):
        self.kill_worker("first-release")
        (self.txn / m.TXN_PLAN).write_bytes(b'{"schema":')
        self.assert_manual_hold()

    def test_07_foreign_journal_bytes_are_preserved_on_restart(self):
        self.kill_worker("first-release")
        foreign = self.txn / "personal-note.txt"
        foreign.write_bytes(b"OWNER UNKNOWN FILE NEVER DELETE")
        self.assert_manual_hold()
        self.assertEqual(foreign.read_bytes(), b"OWNER UNKNOWN FILE NEVER DELETE")

    def test_08_modified_staged_current_pointer_is_manual_hold(self):
        self.kill_worker("first-release")
        current = self.txn / "current"
        current.unlink()
        current.symlink_to(self.home / "Recordings/owner.ts")
        self.assert_manual_hold()
        self.assertEqual(os.readlink(current), str(self.home / "Recordings/owner.ts"))

    def test_09_missing_staged_launcher_with_release_remaining_is_hold(self):
        self.kill_worker("first-release")
        rescued = self.home / "owner-staged-launcher-preserve"
        (self.txn / "launcher").rename(rescued)
        self.assert_manual_hold()
        self.assertEqual(rescued.read_text(), m.LAUNCH)

    def test_10_corrupted_r2_release_before_restart_is_hold(self):
        self.kill_worker("first-release")
        foreign = self.second / "foreign-private-bytes"
        foreign.write_bytes(b"FOREIGN BYTES NEVER DELETE")
        self.assert_manual_hold()
        self.assertEqual(foreign.read_bytes(), b"FOREIGN BYTES NEVER DELETE")

    def test_11_committed_marker_tamper_before_restart_is_hold(self):
        self.kill_worker("first-release")
        (self.txn / m.TXN_COMMITTED).write_bytes(b"INVALID COMMIT")
        self.assert_manual_hold()

    def test_12_insecure_plan_mode_not_repaired_or_deleted(self):
        self.kill_worker("first-release")
        plan = self.txn / m.TXN_PLAN
        plan.chmod(0o644)
        self.assert_manual_hold()
        self.assertEqual(plan.stat().st_mode & 0o777, 0o644)

    def test_13_interrupted_plan_before_commit_with_foreign_bytes_holds(self):
        self.kill_worker("plan")
        foreign = self.txn / "owner-unknown.bin"
        foreign.write_bytes(b"PRIVATE JOURNAL DATA")
        # No committed releases have been removed in this case.
        self.assert_manual_hold()
        self.assertTrue(self.first.is_dir())
        self.assertEqual(foreign.read_bytes(), b"PRIVATE JOURNAL DATA")


if __name__ == "__main__":
    unittest.main()
