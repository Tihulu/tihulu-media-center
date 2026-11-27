"""Independent synthetic future pairing fixtures; no native build/hardware/models."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "tools/compliance/media_gpl_delivery_guard_27.py"
SPEC = importlib.util.spec_from_file_location("media_gpl_delivery_guard_27", FILE)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

def json_file(p, o):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(o, sort_keys=True, indent=2) + "\n")

def ledger():
    return m.read_json(ROOT / "docs/compliance/MEDIA_GPL_SOURCE_DELIVERY_GATES_27.json")

def data_for(path):
    if path in ("legal/LICENSE", "legal/NOTICE", "legal/LICENSES/GPL-2.0-only.txt"):
        return (ROOT / path.replace("legal/", "", 1)).read_bytes()
    if path == "modified_kaffeine/COPYING":
        return (ROOT / "LICENSES/GPL-2.0-only.txt").read_bytes()
    return ("SYNTHETIC FIXTURE ONLY: " + path + "\n").encode()

def source_files():
    names = ["modified_kaffeine/CMakeLists.txt", "modified_kaffeine/COPYING"]
    names += [f"modified_kaffeine/src/synthetic_{i:03d}.cpp" for i in range(350)]
    names += ["selected/source/installed-package/kaffeine_next/patch_upstream.py"]
    names += [f"selected/source/installed-package/tv_center/synthetic_{i:03d}.py"
              for i in range(132)]
    names += ["build_scripts/media-stable-first.sh", "build_scripts/preview_safety.py"]
    names += ["legal/LICENSE", "legal/NOTICE", "legal/LICENSES/GPL-2.0-only.txt"]
    names += ["patches/kaffeine-from-pinned-upstream.patch", "candidate-manifest.json"]
    assert len(names) == 492 and len(set(names)) == 492
    return sorted(names)

def write_source(pair, names):
    records = []
    with tarfile.open(pair / "corresponding-source.tar.gz", "w:gz") as tar:
        for path in names:
            content = data_for(path)
            mode = 0o755 if path.endswith("build_scripts/media-stable-first.sh") else 0o644
            info = tarfile.TarInfo(path)
            info.size = len(content)
            info.mode = mode
            tar.addfile(info, io.BytesIO(content))
            records.append({"path": path, "type": "file", "sha256": m.sha256_bytes(content),
                            "size": len(content), "mode": oct(mode)})
    json_file(pair / "source-inventory.json", {"source_inventory": records})
    return records

def make_pair(pair):
    (pair / "binary/native/bin").mkdir(parents=True)
    (pair / "binary/native/bin/kaffeine").write_bytes(b"\x7fELF SYNTHETIC TEST ONLY\n")
    for name in m.NOTICE_BLOBS:
        dst = pair / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((ROOT / name).read_bytes())
    write_source(pair, source_files())
    json_file(pair / "build-provenance.json", {
        "build_commit": m.BASE, "kde_commit": m.KDE,
        "binary_sha256": m.sha256_file(pair / "binary/native/bin/kaffeine"),
        "compiler_identity": "SYNTHETIC TEST ONLY",
        "full_build_commands": "SYNTHETIC TEST ONLY"})
    json_file(pair / "SBOM-observation.json", {
        "scope": "SYNTHETIC TEST ONLY", "legal_completeness": "HOLD"})
    manifest = {"schema": "TIHULU-PAIRED-GPL-DELIVERY-27-DRAFT",
                "build_source_commit": m.BASE, "frozen_commit": m.FROZEN,
                "kde_commit": m.KDE, "recipient_delivery": "NOT_PUBLISHED",
                "legal_clearance": "HOLD", "public_release": "HOLD",
                "sha256": {
                    key: m.sha256_file(pair / p)
                    for key, p in {
                        "binary": "binary/native/bin/kaffeine",
                        "source_archive": "corresponding-source.tar.gz",
                        "source_inventory": "source-inventory.json",
                        "build_provenance": "build-provenance.json",
                        "sbom_observation": "SBOM-observation.json"}.items()}}
    json_file(pair / "SOURCE-DELIVERY-MANIFEST.json", manifest)
    return manifest

class SourceDelivery27(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.base_tmp.name)
        cls.manifest = make_pair(cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.base_tmp.cleanup()

    def clone(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        pair = Path(tmp.name) / "pair"
        shutil.copytree(self.base, pair)
        return pair

    def test_01_ledger_invariant(self):
        ai = m.read_json(ROOT / "docs/compliance/AI_MODEL_LICENSES_19.json")
        spdx = m.read_json(ROOT / "docs/compliance/SPDX_SOURCES_19.spdx.json")
        self.assertEqual(m.audit_ledger(ledger(), ai, spdx)["public_release"], "HOLD")

    def test_02_nc_licenses_cannot_be_relaxed(self):
        ai = m.read_json(ROOT / "docs/compliance/AI_MODEL_LICENSES_19.json")
        spdx = m.read_json(ROOT / "docs/compliance/SPDX_SOURCES_19.spdx.json")
        ai["models"][3]["declared_license"] = "MIT"  # NLLB
        with self.assertRaises(ValueError):
            m.audit_ledger(ledger(), ai, spdx)

    def test_03_owner_approval_cannot_be_forged(self):
        d = ledger()
        d["owner_decisions"][0]["answer"] = "APPROVED"
        with self.assertRaises(ValueError):
            m.audit_ledger(d, m.read_json(ROOT / "docs/compliance/AI_MODEL_LICENSES_19.json"),
                           m.read_json(ROOT / "docs/compliance/SPDX_SOURCES_19.spdx.json"))

    def test_04_public_release_cannot_be_promoted(self):
        d = ledger()
        d["gates"]["public_release"] = "PASS"
        with self.assertRaises(ValueError):
            m.audit_ledger(d, m.read_json(ROOT / "docs/compliance/AI_MODEL_LICENSES_19.json"),
                           m.read_json(ROOT / "docs/compliance/SPDX_SOURCES_19.spdx.json"))

    def test_05_original_notice_blob_sha_matches(self):
        for p, expected in m.NOTICE_BLOBS.items():
            self.assertEqual(m.blob_oid((ROOT / p).read_bytes()), expected)

    def test_06_synthetic_pair_is_only_scoped_pass(self):
        result = m.audit_pair(self.base, ledger())
        self.assertEqual(result["technical_candidate_byte_pair"], "SCOPED_PASS_ONLY")
        self.assertEqual(result["candidate_regular_files"], 492)
        self.assertEqual(result["complete_gpl_corresponding_source"], "HOLD")
        self.assertEqual(result["real_recipient_delivery"], "NOT_PERFORMED")
        self.assertEqual(result["public_release"], "HOLD")

    def test_07_changed_elf_bytes_refused(self):
        pair = self.clone()
        (pair / "binary/native/bin/kaffeine").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            m.audit_pair(pair, ledger())

    def test_08_missing_entire_source_archive_refused(self):
        pair = self.clone()
        (pair / "corresponding-source.tar.gz").unlink()
        with self.assertRaises((ValueError, OSError)):
            m.audit_pair(pair, ledger())

    def test_09_changed_source_bytes_refused(self):
        pair = self.clone()
        with (pair / "corresponding-source.tar.gz").open("ab") as out:
            out.write(b"foreign source mutation")
        with self.assertRaises(ValueError):
            m.audit_pair(pair, ledger())

    def test_10_tampered_inventory_refused(self):
        pair = self.clone()
        invent = m.read_json(pair / "source-inventory.json")
        invent["source_inventory"][0]["sha256"] = "0" * 64
        json_file(pair / "source-inventory.json", invent)
        man = m.read_json(pair / "SOURCE-DELIVERY-MANIFEST.json")
        man["sha256"]["source_inventory"] = m.sha256_file(pair / "source-inventory.json")
        json_file(pair / "SOURCE-DELIVERY-MANIFEST.json", man)
        with self.assertRaises(ValueError):
            m.audit_pair(pair, ledger())

    def test_11_symlinked_release_notice_refused(self):
        pair = self.clone()
        target = pair / "NOTICE"
        target.unlink()
        target.symlink_to(ROOT / "NOTICE")
        with self.assertRaises(ValueError):
            m.audit_pair(pair, ledger())

    def test_12_altered_legal_notice_refused(self):
        pair = self.clone()
        (pair / "NOTICE").write_bytes(b"not pinned")
        with self.assertRaises(ValueError):
            m.audit_pair(pair, ledger())

    def test_13_fake_legal_signoff_refused(self):
        pair = self.clone()
        man = m.read_json(pair / "SOURCE-DELIVERY-MANIFEST.json")
        man["legal_clearance"] = "PASS"
        json_file(pair / "SOURCE-DELIVERY-MANIFEST.json", man)
        with self.assertRaises(ValueError):
            m.audit_pair(pair, ledger())

    def test_14_fake_source_delivery_refused(self):
        pair = self.clone()
        man = m.read_json(pair / "SOURCE-DELIVERY-MANIFEST.json")
        man["recipient_delivery"] = "CONFIRMED"
        json_file(pair / "SOURCE-DELIVERY-MANIFEST.json", man)
        with self.assertRaises(ValueError):
            m.audit_pair(pair, ledger())

    def test_15_unverified_model_extension_detected(self):
        for path in ("models/nllb-600m/model.safetensors", "whisper-ggml.bin",
                     "assets/model_weights/downloaded.weights", "model.pt"):
            self.assertTrue(m.model_path(path))
        self.assertFalse(m.model_path("modified_kaffeine/src/main.cpp"))

    def test_16_duplicate_manifest_keys_refused(self):
        pair = self.clone()
        (pair / "SOURCE-DELIVERY-MANIFEST.json").write_text(
            '{"schema":"x","schema":"y"}')
        with self.assertRaises(ValueError):
            m.audit_pair(pair, ledger())

    def test_17_missing_build_provenance_refused(self):
        pair = self.clone()
        (pair / "build-provenance.json").unlink()
        with self.assertRaises((ValueError, OSError)):
            m.audit_pair(pair, ledger())

    def test_18_archive_traversal_rejected(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            arc = Path(d) / "evil.tar.gz"
            with tarfile.open(arc, "w:gz") as tf:
                b = b"attacker path"
                info = tarfile.TarInfo("../escape")
                info.size = len(b)
                tf.addfile(info, io.BytesIO(b))
            with self.assertRaises(ValueError):
                m.archive_inventory(arc)

    def test_19_archive_symlink_rejected(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            arc = Path(d) / "evil.tar.gz"
            with tarfile.open(arc, "w:gz") as tf:
                info = tarfile.TarInfo("modified_kaffeine/fake")
                info.type = tarfile.SYMTYPE
                info.linkname = "/tmp/private"
                tf.addfile(info)
            with self.assertRaises(ValueError):
                m.archive_inventory(arc)

    def test_20_archive_duplicate_member_rejected(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            arc = Path(d) / "dupe.tar.gz"
            with tarfile.open(arc, "w:gz") as tf:
                for _ in range(2):
                    b = b"x"
                    info = tarfile.TarInfo("modified_kaffeine/fake.cpp")
                    info.size = 1
                    tf.addfile(info, io.BytesIO(b))
            with self.assertRaises(ValueError):
                m.archive_inventory(arc)

if __name__ == "__main__":
    unittest.main()
