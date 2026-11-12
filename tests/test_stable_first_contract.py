# SPDX-License-Identifier: GPL-2.0-or-later
"""No-hardware acceptance tests for the frozen Media snapshot installer."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "installer/media-stable-first.sh"
SNAPSHOT = "7821769eb7aed576dd426ec18ffce3696d93a00d"
TREE = "d471b3aa4e546e8d790512df37fad763254023c6"
KAFFEINE = "e7ea15b86dafed3b20b151cbcb080578ab8e2d5c"
REQUIRED = (
    "source/installed-package/tv_center/__main__.py",
    "source/installed-package/tv_center/radio_ai.py",
    "source/installed-package/tv_center/whisper_engine.py",
    "source/installed-package/tv_center/cuda_faster_whisper.py",
    "source/installed-package/tv_center/translation_service.py",
    "source/installed-package/textcenter/fm_rds.py",
    "source/installed-package/textcenter/dab_bridge.py",
    "source/installed-package/kaffeine_next/patch_upstream.py",
    "source/installed-package/kaffeine_next/native_radio_tab.h",
    "source/installed-package/kaffeine_next/native_unified_recorder.h",
    "source/installed-package/kaffeine_next/subtitle_tracks.py",
    "source/installed-package/kaffeine_next/teletext_match.py",
)

def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, check=False)

class StableFirstContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.code = SCRIPT.read_text(encoding="utf-8")

    def test_script_syntax(self) -> None:
        p = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_pins_and_single_variant(self) -> None:
        for pin in ("SNAPSHOT=" + SNAPSHOT, "SNAPSHOT_TREE=" + TREE,
                    "KAFFEINE=" + KAFFEINE):
            self.assertIn(pin, self.code)
        self.assertIn('git -C "$REPO" archive "$SNAPSHOT" -- source/installed-package', self.code)
        self.assertNotIn("source/worktrees/", self.code)
        self.assertNotIn("TIHULU-TEXT-CENTER.git", self.code)
        self.assertIn('cp -a -- "$work/snapshot/source/installed-package/$module"', self.code)

    def test_consent_and_dryrun_precede_any_write(self) -> None:
        self.assertLess(self.code.index('if [[ "$MODE" == --dry-run ]]'),
                        self.code.index("sudo apt-get update"))
        self.assertLess(self.code.index('if [[ "$MODE" == --check ]]'),
                        self.code.index("sudo apt-get update"))
        self.assertIn('[[ -t 0 && -t 1 ]]', self.code)
        self.assertIn("'INSTALL APT'", self.code)
        for forbidden in ("curl -fsSL", "/dev/dvb", "rtl_test", "systemctl",
                          "ai install-baseline", "pip install"):
            self.assertNotIn(forbidden, self.code)

    def test_rollback_non_destructive_contract(self) -> None:
        self.assertIn('APPROOT="${HOME}/.local/opt/tihulu-media-stable"', self.code)
        self.assertIn('atomic_link "$target" "$current"', self.code)
        self.assertIn('rm -- "$current"', self.code)
        self.assertNotIn('rm -rf -- "$APPROOT"', self.code)
        self.assertNotIn(".config/kaffeinerc", self.code)
        self.assertIn("no_automatic_models=true", self.code)

    def test_help_has_no_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as fakehome:
            p = subprocess.run(["bash", str(SCRIPT), "--help"],
                               capture_output=True, text=True,
                               env={**os.environ, "HOME": fakehome})
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("--rollback", p.stdout)
            self.assertEqual(list(Path(fakehome).iterdir()), [])

    def test_rollback_in_temporary_home(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("Root intentionally refused; CI uses unprivileged runner")
        with tempfile.TemporaryDirectory() as fakehome:
            root = Path(fakehome) / ".local/opt/tihulu-media-stable"
            release1 = root / "releases/r-7821769eb7ae-20261112T080000-1"
            release2 = root / "releases/r-7821769eb7ae-20261112T080001-2"
            (root / ".media-preview-owner-v1").parent.mkdir(parents=True)
            (root / ".media-preview-owner-v1").write_text("TIHULU_MEDIA_PREVIEW_OWNED_V1\\n")
            for release in (release1, release2):
                (release / "native/bin").mkdir(parents=True)
                (release / "native/bin/kaffeine").write_bytes(b"synthetic native Kaffeine")
                p_prepare = subprocess.run(
                    ["python3", str(ROOT / "installer/preview_safety.py"),
                     "prepare-release", str(release)],
                    capture_output=True, text=True,
                )
                self.assertEqual(p_prepare.returncode, 0, p_prepare.stderr)
            (root / "current").symlink_to(str(release2))
            (root / "previous").symlink_to(str(release1))
            p = subprocess.run(["bash", str(SCRIPT), "--rollback"],
                               capture_output=True, text=True,
                               env={**os.environ, "HOME": fakehome})
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual((root / "current").resolve(), release1)
            self.assertEqual((root / "previous").resolve(), release2)
            self.assertTrue(release1.is_dir())
            self.assertTrue(release2.is_dir())

    def test_snapshot_identity_and_required_feature_files(self) -> None:
        p = git("rev-parse", f"{SNAPSHOT}^{{tree}}")
        if p.returncode != 0:
            self.skipTest("Pinned snapshot unavailable in local checkout")
        self.assertEqual(p.stdout.strip(), TREE)
        for path in REQUIRED:
            self.assertEqual(git("cat-file", "-e", f"{SNAPSHOT}:{path}").returncode,
                             0, path)
        p = git("show", f"{SNAPSHOT}:manifest.json")
        self.assertEqual(p.returncode, 0)
        manifest = json.loads(p.stdout)
        self.assertEqual(manifest["snapshot_name"], "stable-first-local-2026-11-12")
        self.assertEqual(manifest["upstream_kaffeine_commit_reported"], KAFFEINE)

    def test_dryrun_in_checkout_never_writes(self) -> None:
        if git("cat-file", "-e", f"{SNAPSHOT}^{{commit}}").returncode != 0:
            self.skipTest("Pinned snapshot unavailable")
        if os.geteuid() == 0:
            self.skipTest("Installer intentionally refuses root; CI runs as runner")
        with tempfile.TemporaryDirectory() as fakehome:
            p = subprocess.run(["bash", str(SCRIPT), "--dry-run", "--no-ai"],
                               capture_output=True, text=True,
                               env={**os.environ, "HOME": fakehome})
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn("DRY RUN ONLY", p.stdout)
            self.assertFalse((Path(fakehome) / ".local").exists())

if __name__ == "__main__":
    unittest.main()
