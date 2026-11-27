# SPDX-License-Identifier: GPL-2.0-or-later
"""MEDIA FINAL ISOLATED INTEGRATION 22 — read-only Git/object contract.

No hardware, services, model downloads or owner HOME touches. This suite
checks exact-source provenance, not legal or real-device acceptance.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SECURITY = "b7d4e7ee820e7969b976a56c9888ba05e676a3b1"
LICENSING = "14b51610d00e12cdf811a8ed6fb416681b4ac58e"
PARITY = "afc70c6fc77d7c0a37d5879abf83fc7e131dd7c6"
FROZEN = "7821769eb7aed576dd426ec18ffce3696d93a00d"

LICENSE_PATHS = (
    "LICENSE",
    "LICENSES/GPL-2.0-only.txt",
    "NOTICE",
    "docs/compliance/AI_MODEL_LICENSES_19.json",
    "docs/compliance/MEDIA_LICENSE_COMPLIANCE_19.md",
    "docs/compliance/PRELIMINARY_SBOM_19.json",
    "docs/compliance/SOURCE_PROVENANCE_19.json",
    "docs/compliance/SPDX_SOURCES_19.spdx.json",
    "tests/test_media_license_artifacts_19.py",
)
PARITY_PATHS = (
    "installer/media-stable-first.sh",
    "docs/MEDIA_PARITY16_DIAGNOSTICS_TV_ROUTING_20.md",
    "tests/test_media_parity16_native_20.py",
    "tests/test_media_parity16_source_20.py",
)
INTEGRATION_PATHS = (
    ".github/workflows/media-final-isolated-integration-22.yml",
    "docs/MEDIA_FINAL_ISOLATED_INTEGRATION_22.md",
    "tests/test_media_final_isolated_integration_22.py",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def oid(commit: str, path: str) -> str:
    return git("rev-parse", f"{commit}:{path}")


class CombinedIntegration22(unittest.TestCase):
    def test_01_baseline_is_ancestor(self):
        subprocess.check_call(["git", "-C", str(ROOT), "merge-base",
                               "--is-ancestor", SECURITY, "HEAD"])

    def test_02_frozen_source_tree_exact_sha(self):
        self.assertEqual(oid("HEAD", "source/installed-package"),
                         oid(FROZEN, "source/installed-package"))
        self.assertEqual(oid("HEAD", "source/worktrees"),
                         oid(SECURITY, "source/worktrees"))

    def test_03_sec12_recovery_code_is_identical_to_independent_review(self):
        self.assertEqual(oid("HEAD", "installer/preview_safety.py"),
                         oid(SECURITY, "installer/preview_safety.py"))

    def test_04_every_inherited_test_blob_is_unchanged(self):
        originals = git("ls-tree", "-r", "--name-only", SECURITY, "tests/").splitlines()
        self.assertTrue(len(originals) >= 6)
        for p in originals:
            with self.subTest(p=p):
                self.assertEqual(oid("HEAD", p), oid(SECURITY, p))

    def test_05_all_licensing_artifact_blobs_are_exact_pr16(self):
        for p in LICENSE_PATHS:
            with self.subTest(p=p):
                self.assertEqual(oid("HEAD", p), oid(LICENSING, p))

    def test_06_parity_installer_and_qa_blobs_are_exact_pr17(self):
        for p in PARITY_PATHS:
            with self.subTest(p=p):
                self.assertEqual(oid("HEAD", p), oid(PARITY, p))

    def test_07_new_delta_contains_only_these_explicit_slices(self):
        actual = set(git("diff", "--name-only", SECURITY, "HEAD").splitlines())
        self.assertEqual(actual, set(LICENSE_PATHS + PARITY_PATHS + INTEGRATION_PATHS))
        # PR16/PR17 old standalone workflows are intentionally not imported;
        # their branch-specific assumptions do NOT apply to a combined tree.
        self.assertNotIn(".github/workflows/media-license-compliance-19.yml", actual)
        self.assertNotIn(".github/workflows/media-parity16-diagnostics-tv-routing-20.yml", actual)

    def test_08_licensing_stays_provisional(self):
        lic = (ROOT / "LICENSE").read_text()
        notice = (ROOT / "NOTICE").read_text()
        models = json.loads((ROOT / "docs/compliance/AI_MODEL_LICENSES_19.json").read_text())
        sbom = json.loads((ROOT / "docs/compliance/PRELIMINARY_SBOM_19.json").read_text())
        self.assertIn("NOT a blanket license grant", lic)
        self.assertIn("NONCOMMERCIAL", notice)
        self.assertEqual(sbom["release_decision"], "HOLD")
        ids = {item["id"]: item for item in models["models"]}
        for id_ in ("nllb-600m", "audeering-voice"):
            self.assertEqual(ids[id_]["redistribution"], "HOLD")


if __name__ == "__main__":
    unittest.main()
