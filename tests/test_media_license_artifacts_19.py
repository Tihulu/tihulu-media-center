"""MEDIA-LICENSE-COMPLIANCE-ARTIFACTS-19: static, disposable tests ONLY."""
import copy
import json
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = "2f5699eeb47505468bf3327be4dbdd89fed3dff1"
FROZEN = "7821769eb7aed576dd426ec18ffce3696d93a00d"
COMPLIANCE = ROOT / "docs" / "compliance"


def load(name):
    return json.loads((COMPLIANCE / name).read_text(encoding="utf-8"))


def selected_git_files(commit):
    out = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-tree", "-r", commit, "--",
         "source/installed-package/"], text=True)
    records = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        mode, kind, oid = meta.split()
        if kind == "blob":
            records[path] = oid
    return records


def validate_model_restrictions(data):
    by_id = {m["id"]: m for m in data["models"]}
    for ident, license_id in (
        ("nllb-600m", "CC-BY-NC-4.0"),
        ("audeering-voice", "CC-BY-NC-SA-4.0")
    ):
        m = by_id[ident]
        if m["declared_license"] != license_id:
            raise ValueError("Noncommercial license must not be weakened")
        if m.get("noncommercial") is not True or m.get("redistribution") != "HOLD":
            raise ValueError("Noncommercial model restriction must remain HOLD")
        if m["bundled"] is not False or "commercial" not in m["commercial"].lower():
            raise ValueError("Unsafe commercial clearance or packaging claim")


def validate_spdx_file_set(spdx, records):
    files = spdx["files"]
    if len(files) != len(records):
        raise ValueError("SPDX file count does not match selected snapshot")
    names = [f["fileName"].removeprefix("./") for f in files]
    if len(names) != len(set(names)) or set(names) != set(records):
        raise ValueError("SPDX file inventory does not match selected snapshot")
    for f in files:
        n = f["fileName"].removeprefix("./")
        if "git-blob-oid:" + records[n] not in f["fileComment"]:
            raise ValueError("SPDX Git blob identity mismatch")
        if f["licenseConcluded"] != "NOASSERTION" or f["copyrightText"] != "NOASSERTION":
            raise ValueError("A license/copyright conclusion was invented")


class LicenseArtifacts19(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spdx = load("SPDX_SOURCES_19.spdx.json")
        cls.sbom = load("PRELIMINARY_SBOM_19.json")
        cls.models = load("AI_MODEL_LICENSES_19.json")
        cls.provenance = load("SOURCE_PROVENANCE_19.json")
        cls.records = selected_git_files(BASE)

    def test_01_selected_snapshot_has_133_files(self):
        self.assertEqual(len(self.records), 133)
        counts = [sum(p.startswith(f"source/installed-package/{d}/")
                      for p in self.records)
                  for d in ("kaffeine_next", "tv_center", "textcenter")]
        self.assertEqual(counts, [34, 79, 20])

    def test_02_spdx_identity_and_file_completeness(self):
        self.assertEqual(self.spdx["spdxVersion"], "SPDX-2.3")
        self.assertEqual(self.spdx["dataLicense"], "CC0-1.0")
        validate_spdx_file_set(self.spdx, self.records)

    def test_03_spdx_relationships(self):
        self.assertEqual(len(self.spdx["relationships"]), 134)
        files = {f["SPDXID"] for f in self.spdx["files"]}
        rels = [r["relatedSpdxElement"] for r in self.spdx["relationships"]
                if r["relationshipType"] == "CONTAINS"]
        self.assertEqual(set(rels), files)
        self.assertEqual(len(rels), len(files))

    def test_04_selected_snapshot_is_byte_identical_to_frozen(self):
        self.assertEqual(self.records, selected_git_files(FROZEN))

    def test_05_provenance_and_upstream_pin(self):
        self.assertEqual(self.provenance["evaluated_base_commit"], BASE)
        self.assertEqual(self.provenance["immutable_frozen_commit"], FROZEN)
        self.assertEqual(self.provenance["selected_source_file_count"], 133)
        self.assertEqual(self.provenance["kde_kaffeine"]["git_commit"],
                         "e7ea15b86dafed3b20b151cbcb080578ab8e2d5c")

    def test_06_only_new_compliance_artifacts_changed(self):
        changed = subprocess.check_output(
            ["git", "-C", str(ROOT), "diff", "--name-only", BASE, "HEAD"], text=True)
        for path in changed.splitlines():
            allowed = (
                path in ("LICENSE", "NOTICE", "LICENSES/GPL-2.0-only.txt",
                         "tests/test_media_license_artifacts_19.py",
                         ".github/workflows/media-license-compliance-19.yml")
                or path.startswith("docs/compliance/"))
            self.assertTrue(allowed, path + " would modify protected source")

    def test_07_nc_model_evidence_remains_hold(self):
        validate_model_restrictions(self.models)

    def test_08_models_are_separately_acquired(self):
        self.assertTrue(self.models["models"])
        for m in self.models["models"]:
            self.assertFalse(m["bundled"], m["id"])
            self.assertTrue(m["source_path"].startswith("source/installed-package/"))
            self.assertTrue(m["origin"].startswith("https://"))

    def test_09_preliminary_sbom_not_install_assertion(self):
        self.assertEqual(self.sbom["baseline_commit"], BASE)
        self.assertIn("INCOMPLETE", self.sbom["completeness"])
        self.assertGreaterEqual(len(self.sbom["components"]), 25)
        self.assertEqual(self.sbom["release_decision"], "HOLD")

    def test_10_license_notice_must_not_grant_approval(self):
        lic = (ROOT / "LICENSE").read_text()
        note = (ROOT / "NOTICE").read_text()
        self.assertIn("NOT a blanket license grant", lic)
        self.assertIn("PUBLIC RELEASE", lic)
        self.assertIn("NONCOMMERCIAL", note)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", (ROOT / "LICENSES/GPL-2.0-only.txt").read_text())

    def test_11_negative_fixture_missing_spdx_file_rejected(self):
        bad = copy.deepcopy(self.spdx)
        bad["files"].pop()
        with self.assertRaises(ValueError):
            validate_spdx_file_set(bad, self.records)

    def test_12_negative_fixture_nc_license_relaxation_rejected(self):
        bad = copy.deepcopy(self.models)
        target = next(m for m in bad["models"] if m["id"] == "nllb-600m")
        target["declared_license"] = "MIT"
        target["redistribution"] = "PASS"
        with self.assertRaises(ValueError):
            validate_model_restrictions(bad)

    def test_13_negative_fixture_wrong_git_oid_rejected(self):
        bad = copy.deepcopy(self.spdx)
        bad["files"][0]["fileComment"] = "git-blob-oid:" + ("0" * 40)
        with self.assertRaises(ValueError):
            validate_spdx_file_set(bad, self.records)

    def test_14_provenance_ids_are_full_git_hashes(self):
        for name in ("evaluated_base_commit", "base_tree_git_oid",
                     "immutable_frozen_commit", "frozen_commit_tree_git_oid"):
            self.assertRegex(self.provenance[name], r"^[a-f0-9]{40}$")


if __name__ == "__main__":
    unittest.main()
