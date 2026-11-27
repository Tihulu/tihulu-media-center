# SPDX-License-Identifier: GPL-2.0-or-later
"""SEC12-01/02: non-root, disposable-only committed recovery adversarial tests.

The actual SIGKILL tests terminate a CI-only Python subprocess after the
durable committed marker; NO physical owner app, RF, services or models.
"""
from __future__ import annotations

import errno
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SAFETY = ROOT / "installer/preview_safety.py"
spec = importlib.util.spec_from_file_location("media_sec12", SAFETY)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@unittest.skipIf(os.geteuid() == 0, "Disposable security fixtures need an unprivileged user")
class SEC12CommittedRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="media-sec12-recovery-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "owner-fixture"
        self.root = self.home / ".local/opt/tihulu-media-stable"
        self.a = self.root / "releases/r-7821769eb7ae-20261112T190000-11"
        self.b = self.root / "releases/r-7821769eb7ae-20261112T190001-22"
        for p, marker in ((self.a, b"synthetic-a"), (self.b, b"synthetic-b")):
            (p / "native/bin").mkdir(parents=True)
            (p / "native/bin/kaffeine").write_bytes(marker)
            (p / "py").mkdir()
            (p / "py/source.txt").write_text("immutably owned fixture\n")
            m.prepare_release(p)
        (self.root / m.MARKER).write_text(m.MARKER_VALUE)
        (self.root / "current").symlink_to(str(self.b))
        (self.root / "previous").symlink_to(str(self.a))
        self.launcher = self.home / ".local/bin/tihulu-media-stable"
        self.desktop = self.home / ".local/share/applications/tihulu-media-stable.desktop"
        self.launcher.parent.mkdir(parents=True)
        self.desktop.parent.mkdir(parents=True)
        self.launcher.write_text(m.LAUNCH)
        self.launcher.chmod(0o755)
        self.desktop.write_text(m.desktop_text(self.home, self.root))
        self.private = self.home / "OWNER-PRIVATE-RECORDING.wav"
        self.private.write_bytes(b"NEVER-TOUCH-OWNER")
        (self.root / "preview-home/.config").mkdir(parents=True)
        (self.root / "preview-home/.config/private.json").write_text("KEEP PRIVATE")
        self.txn = self.root / m.UNINSTALL_TXN
        self.env = {**os.environ, "HOME": str(self.home)}

    def private_intact(self):
        self.assertEqual(self.private.read_bytes(), b"NEVER-TOUCH-OWNER")
        self.assertEqual((self.root / "preview-home/.config/private.json").read_text(),
                         "KEEP PRIVATE")

    def assert_committed_stage(self):
        self.assertTrue((self.txn / m.TXN_PLAN).is_file())
        self.assertTrue((self.txn / m.TXN_COMMITTED).is_file())
        self.assertFalse(m.present(self.launcher))
        self.assertFalse(m.present(self.desktop))
        self.assertFalse(m.present(self.root / "current"))
        self.assertFalse(m.present(self.root / "previous"))
        self.assertEqual((self.txn / "launcher").read_text(), m.LAUNCH)
        self.assertEqual((self.txn / "desktop").read_text(),
                         m.desktop_text(self.home, self.root))
        self.assertEqual(os.readlink(self.txn / "current"), str(self.b))
        self.assertEqual(os.readlink(self.txn / "previous"), str(self.a))
        self.private_intact()

    def committed_after_second_release_failure(self):
        original = m.shutil.rmtree
        count = 0

        def fail_second(name, *args, **kwargs):
            nonlocal count
            if kwargs.get("dir_fd") is not None:
                count += 1
                if count == 2:
                    raise OSError(errno.EIO, "synthetic second release deletion failure")
            return original(name, *args, **kwargs)

        with patch.object(m.shutil, "rmtree", side_effect=fail_second):
            with self.assertRaises(OSError):
                m.uninstall(self.home)
        self.assertEqual(count, 2)
        self.assert_committed_stage()
        self.assertFalse(self.a.exists())
        self.assertTrue(self.b.exists())
        m.verify_release(self.b)

    def refuse_before_another_delete(self):
        # Explicit spy: an invalid recovery must not even ENTER shutil.rmtree,
        # as opposed to merely catching an exception afterwards.
        with patch.object(m.shutil, "rmtree",
                          side_effect=AssertionError("IRREVERSIBLE DELETE ENTERED")) as rm:
            with self.assertRaises((m.SafetyError, OSError)):
                m.uninstall(self.home)
            rm.assert_not_called()
        self.assertTrue(self.b.exists())
        m.verify_release(self.b)
        self.private_intact()

    def test_corrupted_quarantined_launcher_refuses_before_release_delete(self):
        self.committed_after_second_release_failure()
        (self.txn / "launcher").write_text("CORRUPTED QUARANTINED FILE")
        self.refuse_before_another_delete()
        self.assertEqual((self.txn / "launcher").read_text(),
                         "CORRUPTED QUARANTINED FILE")
        self.assertTrue((self.txn / m.TXN_COMMITTED).exists())

    def test_corrupted_quarantined_desktop_refuses_before_release_delete(self):
        self.committed_after_second_release_failure()
        (self.txn / "desktop").write_text("WRONG DESKTOP")
        self.refuse_before_another_delete()
        self.assertTrue((self.txn / m.TXN_COMMITTED).exists())

    def test_corrupted_quarantined_current_pointer_refuses_before_delete(self):
        self.committed_after_second_release_failure()
        link = self.txn / "current"
        link.unlink()
        link.symlink_to(self.private)
        self.refuse_before_another_delete()
        self.assertEqual(os.readlink(link), str(self.private))

    def test_corrupted_quarantined_previous_pointer_refuses_before_delete(self):
        self.committed_after_second_release_failure()
        link = self.txn / "previous"
        link.unlink()
        link.symlink_to(self.private)
        self.refuse_before_another_delete()
        self.assertEqual(os.readlink(link), str(self.private))

    def test_missing_expected_quarantine_entry_refuses_before_delete(self):
        self.committed_after_second_release_failure()
        (self.txn / "launcher").rename(self.home / "owner-review-staged-launcher")
        self.refuse_before_another_delete()
        self.assertEqual((self.home / "owner-review-staged-launcher").read_text(), m.LAUNCH)

    def test_symlinked_quarantine_launcher_never_follows_private_data(self):
        self.committed_after_second_release_failure()
        (self.txn / "launcher").unlink()
        (self.txn / "launcher").symlink_to(self.private)
        self.refuse_before_another_delete()
        self.assertEqual(self.private.read_bytes(), b"NEVER-TOUCH-OWNER")

    def test_plan_0644_and_0666_are_refused_without_auto_chmod(self):
        self.committed_after_second_release_failure()
        plan = self.txn / m.TXN_PLAN
        for mode in (0o644, 0o666, 0o400, 0o700):
            with self.subTest(mode=oct(mode)):
                plan.chmod(mode)
                self.refuse_before_another_delete()
                self.assertEqual(plan.stat().st_mode & 0o777, mode)
        plan.chmod(0o600)
        m.uninstall(self.home)
        self.assertFalse(m.present(self.txn))
        self.private_intact()

    def test_transaction_directory_nonprivate_mode_fails_closed(self):
        self.committed_after_second_release_failure()
        self.txn.chmod(0o755)
        self.refuse_before_another_delete()
        self.assertEqual(self.txn.stat().st_mode & 0o777, 0o755)

    def test_hardlinked_uninstall_plan_refuses_before_delete(self):
        self.committed_after_second_release_failure()
        os.link(self.txn / m.TXN_PLAN, self.home / "saved-plan-hardlink")
        self.refuse_before_another_delete()
        self.assertTrue((self.home / "saved-plan-hardlink").is_file())

    def test_symlinked_uninstall_plan_never_follows_owner_file(self):
        self.committed_after_second_release_failure()
        plan = self.txn / m.TXN_PLAN
        plan.rename(self.home / "owner-review-original-plan")
        plan.symlink_to(self.private)
        self.refuse_before_another_delete()
        self.assertEqual(self.private.read_bytes(), b"NEVER-TOUCH-OWNER")

    def test_plan_substitution_between_lstat_and_open_refused(self):
        self.committed_after_second_release_failure()
        original = m.os.open
        exchanged = False
        plan = self.txn / m.TXN_PLAN

        def substitute(path, flags, mode=0o777, *args, **kwargs):
            nonlocal exchanged
            if (path == m.TXN_PLAN and kwargs.get("dir_fd") is not None
                    and not exchanged):
                exchanged = True
                value = plan.read_bytes()
                plan.rename(self.home / "owner-review-old-plan")
                plan.write_bytes(value)
                plan.chmod(0o600)
            return original(path, flags, mode, *args, **kwargs)

        with patch.object(m.os, "open", side_effect=substitute):
            self.refuse_before_another_delete()
        self.assertTrue(exchanged)
        self.assertEqual((self.home / "owner-review-old-plan").stat().st_mode & 0o777,
                         0o600)

    def test_strict_schema_and_types_are_checked_before_delete(self):
        self.committed_after_second_release_failure()
        plan = self.txn / m.TXN_PLAN
        baseline = json.loads(plan.read_text())
        cases = [
            ("schema-boolean", {"schema": True}),
            ("schema-string", {"schema": "1"}),
            ("entrypoints-list", {"entrypoints": ["launcher", "desktop"]}),
            ("entrypoints-bool-values", {"entrypoints": {"launcher": 1, "desktop": True}}),
            ("entrypoints-inconsistent", {"entrypoints": {"launcher": True, "desktop": False}}),
            ("pointers-list", {"pointers": ["current", "previous"]}),
            ("pointers-invalid-type", {"pointers": {"current": True, "previous": None}}),
            ("had-releases-int", {"had_releases": 1}),
            ("release-name-int", {"releases": [34]}),
            ("duplicate-release-name", {"releases": [self.b.name, self.b.name]}),
            ("unexpected-key", {"unexpected": "PRIVATE"}),
        ]
        for title, changes in cases:
            with self.subTest(title=title):
                candidate = dict(baseline)
                candidate.update(changes)
                plan.write_text(json.dumps(candidate))
                self.refuse_before_another_delete()
        plan.write_text('{"schema":1,' + json.dumps(baseline)[1:])
        with self.subTest(title="duplicate-schema-JSON-key"):
            self.refuse_before_another_delete()
        plan.write_text(json.dumps(baseline))
        m.uninstall(self.home)
        self.assertFalse(m.present(self.txn))
        self.private_intact()

    def test_real_sigkill_after_committed_marker_and_first_release_delete(self):
        # Actual SIGKILL from child process after first real, dirfd-scoped
        # rmtree completed. Not a synthetic EIO or an exception injection.
        code = "\n".join([
            "import importlib.util, os, signal",
            "from pathlib import Path",
            f"p={str(SAFETY)!r}",
            "spec=importlib.util.spec_from_file_location('sec12_killed',p)",
            "m=importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(m)",
            "original=m.shutil.rmtree",
            "def kill_after_first(name,*args,**kwargs):",
            "    result=original(name,*args,**kwargs)",
            "    if kwargs.get('dir_fd') is not None:",
            "        assert name.endswith('-11')",
            "        os.kill(os.getpid(), signal.SIGKILL)",
            "    return result",
            "m.shutil.rmtree=kill_after_first",
            f"m.uninstall(Path({str(self.home)!r}))",
        ])
        process = subprocess.run([sys.executable, "-c", code], env=self.env,
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, -signal.SIGKILL, process.stderr)
        self.assert_committed_stage()
        self.assertFalse(self.a.exists(), "First release must already be gone when killed")
        self.assertTrue(self.b.exists(), "Second release must survive the real kill")
        m.verify_release(self.b)
        # An explicit owner-triggered action resumes known-good forward cleanup.
        m.uninstall(self.home)
        self.assertFalse(self.b.exists())
        self.assertFalse(m.present(self.txn))
        self.assertFalse(m.present(self.launcher))
        self.private_intact()

    def test_real_sigkill_during_final_quarantine_unlink_recovers(self):
        # All releases gone, first quarantined entrypoint unlinked, real SIGKILL.
        # Recovery can safely recognize already-done final cleanup, but never
        # silently delete a missing stage while a release still remains.
        code = "\n".join([
            "import importlib.util, os, signal",
            "from pathlib import Path",
            f"p={str(SAFETY)!r}",
            "spec=importlib.util.spec_from_file_location('sec12_final_kill',p)",
            "m=importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(m)",
            "original=m.unlink_verified_entrypoint",
            "def kill_after_unlink(path,expected):",
            "    original(path,expected)",
            "    if path.name=='launcher': os.kill(os.getpid(), signal.SIGKILL)",
            "m.unlink_verified_entrypoint=kill_after_unlink",
            f"m.uninstall(Path({str(self.home)!r}))",
        ])
        process = subprocess.run([sys.executable, "-c", code], env=self.env,
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, -signal.SIGKILL, process.stderr)
        self.assertFalse(self.a.exists())
        self.assertFalse(self.b.exists())
        self.assertTrue((self.txn / m.TXN_COMMITTED).is_file())
        self.assertFalse(m.present(self.txn / "launcher"))
        self.assertTrue((self.txn / "desktop").is_file())
        self.private_intact()
        m.uninstall(self.home)
        self.assertFalse(m.present(self.txn))
        self.private_intact()

    def test_recovery_on_valid_transaction_still_succeeds(self):
        self.committed_after_second_release_failure()
        m.uninstall(self.home)
        self.assertFalse(self.b.exists())
        self.assertFalse(m.present(self.txn))
        self.private_intact()


if __name__ == "__main__":
    unittest.main()
