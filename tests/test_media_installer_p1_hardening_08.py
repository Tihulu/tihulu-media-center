# SPDX-License-Identifier: GPL-2.0-or-later
"""P1 red-team identity, race and concurrency regressions. Disposable HOME only."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "installer/media-stable-first.sh"
module_path = ROOT / "installer/preview_safety.py"
spec = importlib.util.spec_from_file_location("media_p1_safety", module_path)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@unittest.skipIf(os.geteuid() == 0, "Uses an unprivileged disposable CI user")
class P1InstallerSafety(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="media-p1-ci-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.root = self.home / ".local/opt/tihulu-media-stable"
        self.release = self.root / "releases/r-7821769eb7ae-20261112T090001-77"
        (self.release / "native/bin").mkdir(parents=True)
        (self.release / "native/bin/kaffeine").write_bytes(b"disposable synthetic executable")
        m.prepare_release(self.release)
        (self.root / m.MARKER).write_text(m.MARKER_VALUE)
        (self.root / "current").symlink_to(str(self.release))
        self.launch = self.home / ".local/bin/tihulu-media-stable"
        self.desktop = self.home / ".local/share/applications/tihulu-media-stable.desktop"
        self.launch.parent.mkdir(parents=True)
        self.desktop.parent.mkdir(parents=True)
        self.launch.write_text(m.LAUNCH)
        self.launch.chmod(0o755)
        self.desktop.write_text(m.desktop_text(self.home, self.root))
        self.root.joinpath("preview-home/.config").mkdir(parents=True)
        self.private = self.home / ".config/private-owner.txt"
        self.private.parent.mkdir(parents=True)
        self.private.write_text("OWNER UNTOUCHED\n")
        self.env = {**os.environ, "HOME": str(self.home)}

    def safe(self):
        m.validate_existing(self.home)
        self.assertEqual(self.private.read_text(), "OWNER UNTOUCHED\n")

    def reject(self):
        with self.assertRaises((m.SafetyError, OSError)):
            m.validate_existing(self.home)
        self.assertEqual(self.private.read_text(), "OWNER UNTOUCHED\n")

    def run_mode(self, flag):
        return subprocess.run(
            ["bash", str(SCRIPT), flag], env=self.env,
            capture_output=True, text=True, timeout=20
        )

    def test_exact_full_owned_entrypoints_pass(self):
        self.safe()
        self.assertEqual(m.guard_command(self.home, ["/usr/bin/true"]), 0)

    def test_launcher_matching_exec_line_plus_malicious_tail_refused(self):
        self.launch.write_text(m.LAUNCH + "\nexec /bin/sh -c 'exit 0'\n")
        self.reject()
        result = self.run_mode("--install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Modified launcher", result.stderr)

    def test_desktop_marker_plus_modified_exec_refused(self):
        self.desktop.write_text(self.desktop.read_text() + "Exec=/usr/bin/foreign\n")
        self.reject()

    def test_desktop_marker_plus_modified_icon_refused(self):
        self.desktop.write_text(self.desktop.read_text().replace(
            "StartupWMClass=tihulu-media-center", "StartupWMClass=untrusted"))
        self.reject()

    def test_foreign_launcher_without_matching_full_header_refused(self):
        self.launch.write_text('exec "$HOME/.local/opt/tihulu-media-stable/current/bin/tihulu-kaffeine" "$@"\n')
        self.reject()

    def test_symlinked_launcher_never_followed(self):
        self.launch.unlink()
        self.launch.symlink_to(self.private)
        self.reject()
        self.assertEqual(self.private.read_text(), "OWNER UNTOUCHED\n")

    def test_symlinked_desktop_never_followed(self):
        self.desktop.unlink()
        self.desktop.symlink_to(self.private)
        self.reject()

    def test_hardlinked_launcher_never_treated_as_owned_unique_file(self):
        alias = self.home / "launcher-foreign-alias"
        os.link(self.launch, alias)
        self.reject()

    def test_symlinked_launcher_parent_refuses(self):
        parent = self.launch.parent
        moved = self.home / "saved-bin"
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
        self.reject()

    def test_missing_marker_refuses_install_before_other_writes(self):
        (self.root / m.MARKER).unlink()
        self.reject()
        result = self.run_mode("--install")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.release.is_dir())
        self.assertEqual(self.launch.read_text(), m.LAUNCH)

    def test_orphaned_entrypoints_refuse_unclaimed_root(self):
        self.root.rename(self.home / "previous-foreign-root")
        self.reject()

    def test_partially_installed_launcher_desktop_pair_is_ambiguous(self):
        self.desktop.unlink()
        self.reject()

    def test_interrupted_stage_refuses_reinstall_without_removing_user_files(self):
        incomplete = self.root / ".stage.interrupted"
        incomplete.mkdir()
        (incomplete / "private.txt").write_text("PRESERVE")
        self.reject()
        self.assertEqual((incomplete / "private.txt").read_text(), "PRESERVE")

    def test_symlink_operations_lock_cannot_overwrite_owner_file(self):
        lock = self.home / ".local/opt" / m.SERIAL_LOCK
        lock.symlink_to(self.private)
        with self.assertRaises(OSError):
            m.secure_lock(self.home)
        self.assertEqual(self.private.read_text(), "OWNER UNTOUCHED\n")

    def test_hardlinked_operations_lock_refused(self):
        lock = self.home / ".local/opt" / m.SERIAL_LOCK
        lock.write_text("owned-but-hardlinked")
        lock.chmod(0o600)
        os.link(lock, self.home / "other-lock-link")
        with self.assertRaises(m.SafetyError):
            fd = m.secure_lock(self.home)
            os.close(fd)

    def test_exclusive_publish_rejects_post_check_symlink_injection(self):
        self.launch.unlink()
        self.desktop.unlink()
        original_open = os.open
        def injected_open(path, flags, mode=0o777, *args, **kwargs):
            if str(path) == str(self.launch) and flags & os.O_EXCL:
                if not self.launch.is_symlink():
                    self.launch.symlink_to(self.private)
            return original_open(path, flags, mode, *args, **kwargs)
        with patch.object(m.os, "open", side_effect=injected_open):
            with self.assertRaises(OSError):
                m.publish_entrypoints(self.home)
        self.assertEqual(self.private.read_text(), "OWNER UNTOUCHED\n")

    def test_exclusive_publish_produces_exact_bytes_without_overwriting(self):
        self.launch.unlink()
        self.desktop.unlink()
        m.publish_entrypoints(self.home)
        self.safe()
        self.assertEqual(self.launch.read_text(), m.LAUNCH)
        self.assertEqual(self.desktop.read_text(), m.desktop_text(self.home, self.root))
        m.publish_entrypoints(self.home)
        self.safe()

    def test_concurrent_install_rollback_uninstall_all_fail_closed(self):
        signal = self.home / "guard-active"
        errors = []
        def holder():
            try:
                cmd = ["/usr/bin/python3", "-c",
                       "from pathlib import Path; import time; "
                       f"Path({str(signal)!r}).write_text('active'); time.sleep(1.2)"]
                self.assertEqual(m.guard_command(self.home, cmd), 0)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=holder)
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=5))
        for _ in range(100):
            if signal.exists():
                break
            time.sleep(0.02)
        self.assertTrue(signal.exists(), "Lock-holder process did not start")
        old = os.readlink(self.root / "current")
        for mode in ("--install", "--rollback", "--uninstall"):
            result = self.run_mode(mode)
            self.assertNotEqual(result.returncode, 0, (mode, result.stdout, result.stderr))
        self.assertEqual(os.readlink(self.root / "current"), old)
        self.assertTrue(self.release.is_dir())
        self.assertTrue(self.launch.is_file())
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors, str(errors))
        self.safe()
        self.assertEqual(m.guard_command(self.home, ["/usr/bin/true"]), 0)

    def test_invalid_guard_fd_cannot_skip_operation_lock(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "--rollback"],
            env={**self.env, "TIHULU_MEDIA_GUARD_FD": "12345"},
            capture_output=True, text=True, timeout=20
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(os.readlink(self.root / "current"), str(self.release))

    def test_locked_rollback_and_idempotent_uninstall(self):
        first = self.run_mode("--rollback")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertFalse((self.root / "current").is_symlink())
        self.assertTrue(self.release.is_dir())
        self.safe()
        first_remove = self.run_mode("--uninstall")
        self.assertEqual(first_remove.returncode, 0, first_remove.stderr)
        second_remove = self.run_mode("--uninstall")
        self.assertEqual(second_remove.returncode, 0, second_remove.stderr)
        self.assertEqual(self.private.read_text(), "OWNER UNTOUCHED\n")
        self.assertTrue((self.root / m.MARKER).is_file())


if __name__ == "__main__":
    unittest.main()
