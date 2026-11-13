#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""NOTICE20-P2-01: adversarial generation-downgrade regression on disposable HOME."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PR20="3d7aae9c3fa23c785b178208a8e32ced590b703e"
sp=importlib.util.spec_from_file_location("notice20_recovery", ROOT/"installer/preview_safety.py")
m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
SNAP="7821769eb7ae"
DATE="20261113T023000"

@unittest.skipIf(os.geteuid()==0,"Must never operate as root")
class Notice20P2(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="notice20-p2-")
        self.addCleanup(tmp.cleanup)
        self.home=Path(tmp.name)/"owner"
        self.home.mkdir()
        self.private=self.home/"My recordings/private.ts"
        self.private.parent.mkdir()
        self.private.write_bytes(b"OWNER PRIVATE SENTINEL")
        self.app=self.home/".local/opt/tihulu-media-stable"
        self.releases=self.app/"releases"
        self.releases.mkdir(parents=True)
        (self.app/m.MARKER).write_text(m.MARKER_VALUE)
        self.launch=self.home/".local/bin/tihulu-media-stable"
        self.desktop=self.home/".local/share/applications/tihulu-media-stable.desktop"
        self.launch.parent.mkdir(parents=True)
        self.desktop.parent.mkdir(parents=True)
        self.launch.write_text(m.LAUNCH)
        self.desktop.write_text(m.desktop_text(self.home,self.app))
        self.current=self.app/"current"
        self.previous=self.app/"previous"
    def intact(self):
        self.assertEqual(self.private.read_bytes(),b"OWNER PRIVATE SENTINEL")
    def make(self,*,modern=True,legal=True):
        prefix="r2" if modern else "r"
        dest=self.releases/(prefix+"-"+SNAP+"-"+DATE+"-"+str(len(list(self.releases.iterdir()))+1))
        dest.mkdir()
        binary=dest/"native/bin/kaffeine"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"CI-SYNTHETIC-BINARY-NOT-A-REAL-EXECUTABLE")
        binary.chmod(0o755)
        if legal:m.stage_legal_notice_bundle(ROOT,dest)
        m.prepare_release(dest,v2_release_name=dest.name if modern else None)
        m.verify_release(dest,audit_unattested_legacy=not legal)
        return dest
    def activate(self,current,previous=None):
        self.current.symlink_to(str(current))
        if previous:self.previous.symlink_to(str(previous))
    def erase_all_and_rewrite(self,release):
        for path in m.LEGAL_NOTICE_BLOBS:(release/path).unlink()
        (release/"LICENSES").rmdir()
        (release/m.LEGAL_MARKER).unlink()
        fake=m.release_manifest(release)
        self.assertEqual(fake["schema"],1)
        for name in (*m.LEGAL_NOTICE_BLOBS,"LICENSES",m.LEGAL_MARKER):
            self.assertNotIn(name,fake["entries"])
        (release/m.MANIFEST).write_text(json.dumps(fake,sort_keys=True,indent=2)+"\n")
        (release/m.MANIFEST).chmod(0o600)
        self.intact()
    def refuse(self,release,contains=None):
        with self.assertRaises(m.SafetyError) as cm:m.verify_release(release)
        if contains:self.assertIn(contains,str(cm.exception))
        self.intact()
    def no_deletion(self,releases):
        with patch.object(m.shutil,"rmtree",side_effect=AssertionError("DELETE ATTEMPT")) as spy:
            with self.assertRaises(m.SafetyError):m.uninstall(self.home)
            spy.assert_not_called()
        self.assertFalse((self.app/m.UNINSTALL_TXN).exists())
        for p in releases:self.assertTrue(p.is_dir(),str(p))
        self.intact()
    def rollback_refused(self,old,current):
        self.activate(current,old)
        proc=subprocess.run(["bash",str(ROOT/"installer/media-stable-first.sh"),"--rollback"],
                            env={**os.environ,"HOME":str(self.home),"PYTHONDONTWRITEBYTECODE":"1"},
                            capture_output=True,text=True,timeout=20)
        self.assertNotEqual(proc.returncode,0,proc.stdout)
        self.assertEqual(os.readlink(self.current),str(current))
        self.assertEqual(os.readlink(self.previous),str(old))
        self.intact()

    def test_01_new_schema_is_independent_generation_v2(self):
        p=self.make()
        d=json.loads((p/m.MANIFEST).read_text())
        self.assertEqual((d["schema"],d["format"],d["release_name"]),
                         (2,m.RELEASE_V2_FORMAT,p.name))
        for k in (*m.LEGAL_NOTICE_BLOBS,"LICENSES",m.LEGAL_MARKER):
            self.assertIn(k,d["entries"])
    def test_02_complete_legal_removal_and_schema1_rewrite_refused(self):
        p=self.make();self.erase_all_and_rewrite(p);self.refuse(p,"downgrade")
    def test_03_original_pr20_accepts_same_downgrade_negative_control(self):
        p=self.make();self.erase_all_and_rewrite(p)
        code=subprocess.check_output(["git","-C",str(ROOT),"show",
                                      PR20+":installer/preview_safety.py"],text=True)
        old=types.ModuleType("original_pr20")
        exec(compile(code,"original-pr20","exec"),old.__dict__)
        old.verify_release(p) # Demonstrates the original conditional gap, read-only.
        self.refuse(p,"downgrade")
    def test_04_v2_manifest_rewrite_without_notices_still_refused(self):
        p=self.make();self.erase_all_and_rewrite(p)
        new=m.release_manifest(p,v2_release_name=p.name)
        (p/m.MANIFEST).write_text(json.dumps(new)+"\n")
        self.refuse(p)
    def test_05_absent_legal_files_original_v2_manifest_refused(self):
        p=self.make()
        for x in m.LEGAL_NOTICE_BLOBS:(p/x).unlink()
        (p/"LICENSES").rmdir();(p/m.LEGAL_MARKER).unlink()
        self.refuse(p)
    def test_06_forged_format_or_name_cannot_reclaim_v2(self):
        for which,val in (("format","fake-legacy"),("release_name","r2-"+SNAP+"-"+DATE+"-999")):
            with self.subTest(which=which):
                p=self.make()
                data=json.loads((p/m.MANIFEST).read_text())
                data[which]=val
                (p/m.MANIFEST).write_text(json.dumps(data)+"\n")
                self.refuse(p,"downgrade")
    def test_07_rename_modern_v2_into_legacy_namespace_does_not_help(self):
        p=self.make()
        old=self.releases/("r-"+SNAP+"-"+DATE+"-47")
        p.rename(old)
        self.erase_all_and_rewrite(old)
        self.refuse(old,"UNATTESTED")
    def test_08_preexisting_true_legacy_unnotified_is_unattested(self):
        p=self.make(modern=False,legal=False)
        self.refuse(p,"UNATTESTED")
        before=(p/m.MANIFEST).read_bytes()
        m.verify_release(p,audit_unattested_legacy=True)
        self.assertEqual(before,(p/m.MANIFEST).read_bytes())
    def test_09_existing_old_named_with_intact_pinned_notices_still_accepted(self):
        p=self.make(modern=False,legal=True)
        m.verify_release(p)
        self.assertEqual(json.loads((p/m.MANIFEST).read_text())["schema"],1)
    def test_10_v2_prepare_refuses_missing_notices_no_manifest_written(self):
        p=self.releases/("r2-"+SNAP+"-"+DATE+"-99")
        p.mkdir();bin=p/"native/bin/kaffeine";bin.parent.mkdir(parents=True)
        bin.write_bytes(b"FIXTURE")
        with self.assertRaises(m.SafetyError):m.prepare_release(p,v2_release_name=p.name)
        self.assertFalse((p/m.MANIFEST).exists())
        self.intact()
    def test_11_v2_mint_refuses_legacy_basename(self):
        p=self.make(modern=False,legal=True)
        (p/m.MANIFEST).unlink()
        with self.assertRaises(m.SafetyError):m.prepare_release(p,v2_release_name=p.name)
        self.assertFalse((p/m.MANIFEST).exists())
        self.intact()
    def test_12_two_release_uninstall_old_downgraded_no_delete(self):
        old=self.make();cur=self.make();self.activate(cur,old)
        self.erase_all_and_rewrite(old)
        self.no_deletion((old,cur))
        self.assertTrue(self.current.is_symlink())
    def test_13_two_release_uninstall_current_downgraded_no_delete(self):
        old=self.make();cur=self.make();self.activate(cur,old)
        self.erase_all_and_rewrite(cur)
        self.no_deletion((old,cur))
        self.assertTrue(self.previous.is_symlink())
    def test_14_mixed_legacy_unattested_uninstall_no_delete(self):
        old=self.make(modern=False,legal=False)
        cur=self.make()
        self.activate(cur,old)
        self.no_deletion((old,cur))
    def test_15_rollback_refuses_downgraded_previous(self):
        old=self.make();cur=self.make()
        self.erase_all_and_rewrite(old)
        self.rollback_refused(old,cur)
    def test_16_rollback_refuses_unattested_legacy(self):
        old=self.make(modern=False,legal=False)
        cur=self.make()
        self.rollback_refused(old,cur)
    def test_17_valid_mixed_v2_and_notified_old_uninstall_preserves_private(self):
        old=self.make(modern=False,legal=True)
        cur=self.make();self.activate(cur,old)
        m.uninstall(self.home)
        self.assertFalse(old.exists());self.assertFalse(cur.exists());self.intact()
    def test_18_valid_two_v2_uninstall_preserves_private(self):
        old=self.make();cur=self.make();self.activate(cur,old)
        m.uninstall(self.home)
        self.assertFalse(old.exists());self.assertFalse(cur.exists());self.intact()
    def test_19_readonly_legacy_audit_cli_reports_ambiguity(self):
        p=self.make(modern=False,legal=False)
        before=(p/m.MANIFEST).read_bytes()
        r=subprocess.run(["/usr/bin/python3",str(ROOT/"installer/preview_safety.py"),
                          "audit-unattested-legacy",str(p)],capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("UNATTESTED LEGACY OR REWRITTEN PR20",r.stdout)
        self.assertEqual(before,(p/m.MANIFEST).read_bytes());self.intact()
    def test_20_shell_creates_v2_release_and_binds_name_to_manifest(self):
        s=(ROOT/"installer/media-stable-first.sh").read_text()
        self.assertIn('final="$APPROOT/releases/r2-',s)
        self.assertIn('prepare-release "$stage" ',s)
        self.assertIn('(r|r2)-',s)
        self.intact()
    def test_21_verify_release_cli_refuses_downgraded_old_namespace(self):
        p=self.make();q=self.releases/("r-"+SNAP+"-"+DATE+"-66")
        p.rename(q);self.erase_all_and_rewrite(q)
        r=subprocess.run(["/usr/bin/python3",str(ROOT/"installer/preview_safety.py"),
                          "verify-release",str(q)],capture_output=True,text=True,timeout=15)
        self.assertNotEqual(r.returncode,0)
        self.assertIn("PREVIEW-SAFETY HOLD",r.stderr);self.intact()


    def test_22_native_release_name_contains_numeric_pid_expression(self):
        shell=(ROOT/"installer/media-stable-first.sh").read_text()
        final_line=next(line for line in shell.splitlines() if line.startswith('final='))
        self.assertIn('$(date -u +%Y%m%dT%H%M%S)-$$"',final_line)
        self.assertNotIn('$(date -u +%Y%m%dT%H%M%S)-$"',final_line)
        self.intact()

if __name__=="__main__":unittest.main()
