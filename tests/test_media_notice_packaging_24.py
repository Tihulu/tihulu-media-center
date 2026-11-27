#!/usr/bin/env python3
"""Distribution notice delivery QA — disposable fixtures only; no owner system."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("notice24_safety",
                                              ROOT / "installer/preview_safety.py")
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


@unittest.skipIf(os.geteuid() == 0, "Disposable security fixtures must run unprivileged")
class LegalNoticeDelivery24(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="media-notice24-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "owner"
        self.home.mkdir()
        self.owner_file = self.home / "private-recording.wav"
        self.owner_file.write_bytes(b"PRIVATE-NOTICE24-DO-NOT-DELETE")
        self.stage = self.base / "new-stage"
        self.stage.mkdir()

    def owner_intact(self):
        self.assertEqual(self.owner_file.read_bytes(),
                         b"PRIVATE-NOTICE24-DO-NOT-DELETE")

    def packaged(self, path: Path | None = None):
        path = path or self.stage
        (path / "native/bin").mkdir(parents=True)
        native = path / "native/bin/kaffeine"
        native.write_bytes(b"DISPOSABLE-NO-REAL-EXECUTABLE")
        native.chmod(0o755)
        m.stage_legal_notice_bundle(ROOT, path)
        m.prepare_release(path)
        m.verify_release(path)
        return path

    def expect_hold(self, path: Path | None = None):
        with self.assertRaises((m.SafetyError, OSError, ValueError)):
            m.verify_release(path or self.stage)
        self.owner_intact()

    def owner_install(self):
        root = self.home / ".local/opt/tihulu-media-stable"
        release = root / "releases/r-7821769eb7ae-20261113T010000-24"
        release.mkdir(parents=True)
        self.packaged(release)
        (root / m.MARKER).write_text(m.MARKER_VALUE)
        (root / "current").symlink_to(str(release))
        launcher = self.home / ".local/bin/tihulu-media-stable"
        desktop = self.home / ".local/share/applications/tihulu-media-stable.desktop"
        launcher.parent.mkdir(parents=True)
        desktop.parent.mkdir(parents=True)
        launcher.write_text(m.LAUNCH)
        launcher.chmod(0o755)
        desktop.write_text(m.desktop_text(self.home, root))
        return root, release

    def test_01_pr16_blobs_are_pinned_and_actual(self):
        self.assertEqual(set(m.LEGAL_NOTICE_BLOBS),
                         {"LICENSE", "NOTICE", "LICENSES/GPL-2.0-only.txt"})
        for rel, oid in m.LEGAL_NOTICE_BLOBS.items():
            with self.subTest(rel=rel):
                contents = m._legal_file_bytes(ROOT, rel, oid)
                self.assertEqual(m._legal_blob_oid(contents), oid)
        self.owner_intact()

    def test_02_complete_stage_has_three_exact_notices_and_marker(self):
        self.packaged()
        for rel, oid in m.LEGAL_NOTICE_BLOBS.items():
            file = self.stage / rel
            self.assertTrue(file.is_file())
            self.assertEqual(m._legal_blob_oid(file.read_bytes()), oid)
            self.assertEqual(stat.S_IMODE(file.lstat().st_mode), 0o644)
            self.assertEqual(file.lstat().st_nlink, 1)
        marker = self.stage / m.LEGAL_MARKER
        self.assertEqual(marker.read_bytes(), m.LEGAL_MARKER_BYTES)
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        self.owner_intact()

    def test_03_manifest_contains_all_notices_and_marker(self):
        self.packaged()
        manifest = json.loads((self.stage / m.MANIFEST).read_text())
        for rel in (*m.LEGAL_NOTICE_BLOBS, "LICENSES", m.LEGAL_MARKER):
            self.assertIn(rel, manifest["entries"])
        self.owner_intact()

    def test_04_missing_notice_prevents_trust(self):
        self.packaged()
        (self.stage / "NOTICE").unlink()
        self.expect_hold()

    def test_05_missing_gpl_notice_prevents_trust(self):
        self.packaged()
        (self.stage / "LICENSES/GPL-2.0-only.txt").unlink()
        self.expect_hold()

    def test_06_altered_notice_prevents_trust(self):
        self.packaged()
        (self.stage / "LICENSE").write_text("ALTERED, NOT PR16")
        self.expect_hold()

    def test_07_notice_symlink_to_private_data_fails_closed(self):
        self.packaged()
        f = self.stage / "NOTICE"
        f.unlink()
        f.symlink_to(self.owner_file)
        self.expect_hold()
        self.assertEqual(f.readlink(), self.owner_file)

    def test_08_notice_hardlink_to_owned_private_data_fails_closed(self):
        self.packaged()
        f = self.stage / "NOTICE"
        f.unlink()
        os.link(self.owner_file, f)
        self.expect_hold()

    def test_09_weak_or_wrong_notice_mode_fails_closed(self):
        self.packaged()
        f = self.stage / "LICENSE"
        for mode in (0o666, 0o600, 0o755):
            with self.subTest(mode=oct(mode)):
                f.chmod(mode)
                self.expect_hold()
        self.owner_intact()

    def test_10_foreign_uid_notice_stat_is_rejected(self):
        self.packaged()
        original = os.stat
        def forged(path, *args, **kwargs):
            s = original(path, *args, **kwargs)
            if path == "NOTICE" and kwargs.get("follow_symlinks") is False:
                vals = list(s)
                vals[4] = os.geteuid() + 100
                return os.stat_result(vals)
            return s
        with patch.object(m.os, "stat", side_effect=forged):
            self.expect_hold()
        self.owner_intact()

    def test_11_staging_refuses_existing_foreign_notice_no_overwrite(self):
        foreign = self.stage / "NOTICE"
        foreign.write_text("OWNER-FILE")
        with self.assertRaises((m.SafetyError, OSError)):
            m.stage_legal_notice_bundle(ROOT, self.stage)
        self.assertEqual(foreign.read_text(), "OWNER-FILE")
        self.assertFalse((self.stage / "LICENSE").exists())
        self.owner_intact()

    def test_12_stage_refuses_symlinked_source_license(self):
        src = self.base / "source-fixture"
        src.mkdir()
        (src / "LICENSES").mkdir()
        for rel in m.LEGAL_NOTICE_BLOBS:
            dst = src / rel
            dst.write_bytes((ROOT / rel).read_bytes())
            dst.chmod(0o644)
        f = src / "NOTICE"
        f.unlink()
        f.symlink_to(self.owner_file)
        with self.assertRaises((m.SafetyError, OSError)):
            m.stage_legal_notice_bundle(src, self.stage)
        self.assertFalse(any(self.stage.iterdir()))
        self.owner_intact()

    def test_13_stage_refuses_source_digest_alteration(self):
        src = self.base / "source-fixture"
        src.mkdir()
        (src / "LICENSES").mkdir()
        for rel in m.LEGAL_NOTICE_BLOBS:
            f = src / rel
            f.write_bytes((ROOT / rel).read_bytes())
            f.chmod(0o644)
        (src / "NOTICE").write_text("TAMPERED SOURCE")
        with self.assertRaises((m.SafetyError, OSError)):
            m.stage_legal_notice_bundle(src, self.stage)
        self.assertFalse(any(self.stage.iterdir()))
        self.owner_intact()

    def test_14_missing_marker_refuses_and_keeps_private_data(self):
        self.packaged()
        (self.stage / m.LEGAL_MARKER).unlink()
        self.expect_hold()

    def test_15_modified_notice_refuses_uninstall_before_release_delete(self):
        root, release = self.owner_install()
        (release / "NOTICE").write_bytes(b"tampered notice")
        with self.assertRaises((m.SafetyError, OSError, ValueError)):
            m.uninstall(self.home)
        self.assertTrue(release.exists())
        self.assertTrue((root / "current").is_symlink())
        self.assertFalse((root / m.UNINSTALL_TXN).exists())
        self.owner_intact()

    def test_16_missing_notice_refuses_uninstall_before_release_delete(self):
        root, release = self.owner_install()
        (release / "LICENSE").unlink()
        with self.assertRaises((m.SafetyError, OSError, ValueError)):
            m.uninstall(self.home)
        self.assertTrue(release.exists())
        self.assertFalse((root / m.UNINSTALL_TXN).exists())
        self.owner_intact()

    def test_17_symlinked_notice_refuses_uninstall_before_release_delete(self):
        root, release = self.owner_install()
        (release / "LICENSES/GPL-2.0-only.txt").unlink()
        (release / "LICENSES/GPL-2.0-only.txt").symlink_to(self.owner_file)
        with self.assertRaises((m.SafetyError, OSError, ValueError)):
            m.uninstall(self.home)
        self.assertTrue(release.exists())
        self.assertFalse((root / m.UNINSTALL_TXN).exists())
        self.owner_intact()

    def test_18_valid_complete_notice_release_uninstalls_owned_only(self):
        root, release = self.owner_install()
        m.uninstall(self.home)
        self.assertFalse(release.exists())
        self.assertFalse((root / m.UNINSTALL_TXN).exists())
        self.assertFalse((root / "current").is_symlink())
        self.owner_intact()

    def test_19_foreign_source_hardlink_refuses_without_mutation(self):
        src = self.base / "source-fixture"
        src.mkdir()
        (src / "LICENSES").mkdir()
        for rel in m.LEGAL_NOTICE_BLOBS:
            f = src / rel
            f.write_bytes((ROOT / rel).read_bytes())
            f.chmod(0o644)
        os.link(src / "NOTICE", src / "unapproved-hardlink")
        with self.assertRaises((m.SafetyError, OSError)):
            m.stage_legal_notice_bundle(src, self.stage)
        self.assertFalse(any(self.stage.iterdir()))
        self.owner_intact()


    def test_20_critical_security_functions_unchanged_ast(self):
        import ast
        import subprocess
        upstream = subprocess.check_output(
            ["git", "-C", str(ROOT), "show",
             "03a566a57f76428c7fab86fc56e41ac03f011cc2:installer/preview_safety.py"],
            text=True)
        current = (ROOT / "installer/preview_safety.py").read_text()
        critical = ("_read_owned_uninstall_plan", "_read_uninstall_plan",
                    "_stage_uninstall_path", "_preflight_committed_quarantine",
                    "_committed_uninstall_cleanup", "validate_existing",
                    "guard_command", "publish_entrypoints", "uninstall")
        def functions(txt):
            return {n.name: ast.dump(n, include_attributes=False)
                    for n in ast.parse(txt).body
                    if isinstance(n, ast.FunctionDef)}
        oldf, newf = functions(upstream), functions(current)
        for name in critical:
            with self.subTest(name=name):
                self.assertIn(name, newf)
                self.assertEqual(newf[name], oldf[name],
                                 "SEC12/guard critical function changed")

    def test_21_parity_shell_patch_is_one_narrow_insert(self):
        import subprocess
        upstream = subprocess.check_output(
            ["git", "-C", str(ROOT), "show",
             "03a566a57f76428c7fab86fc56e41ac03f011cc2:installer/media-stable-first.sh"],
            text=True)
        shell = (ROOT / "installer/media-stable-first.sh").read_text()
        needle = ('sha256sum "$stage/native/bin/kaffeine" > "$stage/NATIVE-BINARY-SHA256.txt"\n'
                  'python3 "$SCRIPT_DIR/preview_safety.py" prepare-release "$stage"')
        injected = ('sha256sum "$stage/native/bin/kaffeine" > "$stage/NATIVE-BINARY-SHA256.txt"\n'
                    '# Legal notices must be present as exact pinned PR16 blobs in the COMPLETE\n'
                    '# versioned stage, before release manifest creation and irreversible promotion.\n'
                    '# No automatic copyright/license approval or owner-data changes implied.\n'
                    'python3 "$SCRIPT_DIR/preview_safety.py" stage-notices "$REPO" "$stage" ||\n'
                    "  die 'Legal notice package staging refused; owner release untouched'\n"
                    'python3 "$SCRIPT_DIR/preview_safety.py" verify-notices "$stage" ||\n'
                    "  die 'Staged legal bundle altered; owner release untouched'\n"
                    'python3 "$SCRIPT_DIR/preview_safety.py" prepare-release "$stage"')
        self.assertEqual(upstream.count(needle), 1)
        self.assertEqual(shell, upstream.replace(needle, injected))
        self.owner_intact()



if __name__ == "__main__":
    unittest.main()
