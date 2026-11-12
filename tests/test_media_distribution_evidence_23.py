"""14 synthetic fail-closed regressions; actual build separate CI job."""
import copy,importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location("distribution23",ROOT/"tools/compliance/media_distribution_evidence_23.py")
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def models():
    return {"models":[{"id":"nllb-600m","declared_license":"CC-BY-NC-4.0","noncommercial":True,"redistribution":"HOLD","bundled":False,"commercial":"commercial HOLD"},
                      {"id":"audeering-voice","declared_license":"CC-BY-NC-SA-4.0","noncommercial":True,"redistribution":"HOLD","bundled":False,"commercial":"commercial HOLD"}]}
def evidence():
    return {"gates":{k:"HOLD" for k in ("complete_corresponding_source_delivery","real_binary_notice_delivery","file_level_license_rights","noncommercial_model_redistribution","public_release")},
            "bundled_model_files":[],"selected_source_spdx_header_gaps":{"total":133},
            "native_binary":{"elf_direct_needed":["libc.so.6"]},"source_candidate_required_missing":[]}
class Distribution23(unittest.TestCase):
    def test_01_pinned_ids(self): self.assertEqual(len(m.BASE),40);self.assertEqual(len(m.UPSTREAM),40)
    def test_02_elf_needed(self): self.assertEqual(m.needed("0x1 (NEEDED) Shared library: [libc.so.6]"),["libc.so.6"])
    def test_03_ldd_resolved(self): self.assertTrue(m.ldd_lines("libx.so => /usr/lib/libx.so (0x123)")[0]["resolved"])
    def test_04_ldd_unresolved(self): self.assertFalse(m.ldd_lines("libx.so => not found")[0]["resolved"])
    def test_05_missing_notices_hold(self):
        with TemporaryDirectory() as d:self.assertEqual(m.notices(d)["delivery"],"HOLD")
    def test_06_complete_notice_still_review(self):
        with TemporaryDirectory() as d:
            for path in m.REQUIRED_NOTICE:
                f=Path(d)/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_text("fixture")
            self.assertEqual(m.notices(d)["delivery"],"REVIEW_REQUIRED")
    def test_07_detect_spdx_gaps(self):
        with TemporaryDirectory() as d:
            (Path(d)/"a.py").write_text("# SPDX-License-Identifier: MIT")
            (Path(d)/"b.py").write_text("print(1)")
            self.assertEqual(len(m.spdx_headers(Path(d))["missing_headers"]),1)
    def test_08_detect_bundled_weights(self):
        with TemporaryDirectory() as d:
            (Path(d)/"x.safetensors").write_bytes(b"synthetic")
            self.assertEqual(m.weights(d),["x.safetensors"])
    def test_09_noncommercial_positive(self): self.assertTrue(m.models_ok(models()))
    def test_10_noncommercial_license_relax_fails(self):
        n=models();n["models"][0]["declared_license"]="MIT"
        with self.assertRaises(ValueError):m.models_ok(n)
    def test_11_noncommercial_bundling_fails(self):
        n=models();n["models"][1]["bundled"]=True
        with self.assertRaises(ValueError):m.models_ok(n)
    def test_12_fail_closed_schema_pass(self):self.assertTrue(m.verify(evidence()))
    def test_13_forged_gpl_delivery_go_fails(self):
        e=evidence();e["gates"]["complete_corresponding_source_delivery"]="PASS"
        with self.assertRaises(ValueError):m.verify(e)
    def test_14_missing_source_candidate_fails(self):
        e=evidence();e["source_candidate_required_missing"]=["COPYING"]
        with self.assertRaises(ValueError):m.verify(e)
    def test_15_dpkg_diversion_not_fake_package(self):
        listing="diversion by libc6 from: /lib64/ld-linux-x86-64.so.2\nlibc6:amd64: /lib64/ld-linux-x86-64.so.2\n"
        self.assertEqual(m.parse_dpkg_owner(listing),"libc6:amd64")
        self.assertIsNone(m.parse_dpkg_owner("diversion by libc6 from: /lib64/ld-linux-x86-64.so.2\n"))
if __name__=="__main__":unittest.main()
