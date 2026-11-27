#!/usr/bin/env python3
"""Real installed ELF + notice bundle QA on disposable Ubuntu, no RF/models."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
RAW_RELEASE = os.environ.get("TIHULU_MEDIA_QA_RELEASE", "")
RELEASE = Path(RAW_RELEASE) if RAW_RELEASE else Path("/nonexistent/media-notice-24")
SPEC = importlib.util.spec_from_file_location("installed_notice24",
                                              ROOT / "installer/preview_safety.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

@unittest.skipUnless(RAW_RELEASE, "Requires disposable installed native Kaffeine release")
class InstalledNoticeBundle24(unittest.TestCase):
    def test_01_all_three_notice_blobs_reach_actual_release(self):
        for rel, sha in m.LEGAL_NOTICE_BLOBS.items():
            with self.subTest(rel=rel):
                p = RELEASE / rel
                self.assertTrue(p.is_file(), str(p))
                self.assertFalse(p.is_symlink(), str(p))
                self.assertEqual(m._legal_blob_oid(p.read_bytes()), sha)

    def test_02_exact_inode_ownership_and_modes(self):
        for rel in m.LEGAL_NOTICE_BLOBS:
            p = RELEASE / rel
            with self.subTest(rel=rel):
                st = p.lstat()
                self.assertTrue(stat.S_ISREG(st.st_mode))
                self.assertEqual(st.st_uid, os.geteuid())
                self.assertEqual(st.st_nlink, 1)
                self.assertEqual(stat.S_IMODE(st.st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((RELEASE / m.LEGAL_MARKER).stat().st_mode),
                         0o600)
        m.verify_legal_notice_bundle(RELEASE)

    def test_03_actual_integrity_manifest_contains_bundled_legal_files(self):
        with (RELEASE / m.MANIFEST).open() as stream:
            entries = json.load(stream)["entries"]
        for rel in (*m.LEGAL_NOTICE_BLOBS, "LICENSES", m.LEGAL_MARKER):
            with self.subTest(rel=rel):
                self.assertIn(rel, entries)
        m.verify_release(RELEASE)

    def test_04_no_model_weights_automatically_packed(self):
        prohibited = {".safetensors", ".gguf", ".ggml", ".onnx", ".argosmodel"}
        weights = [str(p.relative_to(RELEASE)) for p in RELEASE.rglob("*")
                   if p.is_file() and p.suffix.lower() in prohibited]
        self.assertEqual(weights, [], "No optional model downloads/bundling")

    def test_05_native_elf_and_pinned_notices_coexist(self):
        native = RELEASE / "native/bin/kaffeine"
        self.assertTrue(native.is_file())
        self.assertGreater(native.stat().st_size, 100_000)
        result = subprocess.run(["/usr/bin/python3",
                                 str(ROOT / "installer/preview_safety.py"),
                                 "verify-release", str(RELEASE)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

if __name__ == "__main__":
    unittest.main()
