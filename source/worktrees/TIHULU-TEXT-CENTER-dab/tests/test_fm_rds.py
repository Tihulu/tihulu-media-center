"""Synthetic FM RDS tests. No real SDR, actual RF or broadcast data required."""
import fcntl
import json
from pathlib import Path
import tempfile
import time
import unittest

from textcenter.core import Store
from textcenter.fm_rds import (
    CaptureError, FMRSDSupervisor, build_commands, decode_rds_group,
    validate_request,
)


class RdsSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.store = Store(self.path / "archive.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def inventory():
        return {"platform": "Linux", "rtl_usb_count": 1}

    def test_frequency_validation_and_command_allowlist(self):
        self.assertEqual(validate_request(98.6, 30), (98_600_000, 30))
        for value in (False, None, "98.6", 0, 87.4, 108.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_request(value, 30)
        for seconds in (0, 9, 91, 31.5, True):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                validate_request(98.6, seconds)
        radio, decoder = build_commands("/usr/bin/rtl_fm", "/usr/bin/redsea", 98_600_000)
        self.assertEqual(radio[-2:], ["-f", "98600000"])
        self.assertEqual(decoder, ["/usr/bin/redsea", "--input", "mpx", "-r", "171k"])

    def test_real_json_field_parsing_does_not_invent_signal(self):
        group={"pi":"0xD3C2","group":"2A", "ps":"TEST FM",
               "radiotext":"Actual transmitter content is unspecified"}
        r=decode_rds_group(group, 98_600_000, "2026-11-06T00:00:00Z")
        self.assertEqual(r["title"],"FM RadioText")
        self.assertEqual(r["body"],"Actual transmitter content is unspecified")
        self.assertEqual(r["station"],"TEST FM")
        self.assertEqual(r["language"],"und")
        self.assertIn("0xD3C2",r["provenance"])
        self.assertIsNone(decode_rds_group({"pi":"0xD3C2","group":"2A"},98_600_000))
        self.assertIsNone(decode_rds_group("not-json",98_600_000))
        r=decode_rds_group({"ps":"STA\x1bTION"},98_600_000)
        self.assertEqual(r["body"],"STATION")

    def test_actual_redsea_rtplus_fields_preserved_not_guessed(self):
        group={
            "pi":"0xD3C2","group":"12A",
            "radiotext_plus":{"tags":[
                {"content-type":"item.artist","data":"Silbermond"},
                {"content-type":"item.title","data":"Das Leichteste der Welt"},
                {"content-type":"unsupported","data":"UNTRUSTED EXTRA"}]}
        }
        event=decode_rds_group(group, 98_600_000, "2026-11-06T01:00:00Z")
        self.assertEqual(event["title"],"FM RadioText+")
        self.assertIn("Artist: Silbermond",event["body"])
        self.assertIn("Title: Das Leichteste der Welt",event["body"])
        self.assertNotIn("UNTRUSTED EXTRA",event["body"])
        self.assertEqual(event["language"],"und")

    def test_RDS2_logo_option_default_off_and_verified_file_persisted(self):
        import base64
        rtl,decoder=build_commands("/usr/bin/rtl_fm","/usr/bin/redsea",98_600_000)
        self.assertNotIn("--streams",decoder)
        rtl,decoder=build_commands("/usr/bin/rtl_fm","/usr/bin/redsea",98_600_000,True)
        self.assertIn("--streams",decoder)
        from textcenter.media import MediaStore
        png=(b"\x89PNG\r\n\x1a\n"+b"\x00\x00\x00\x0dIHDR"+
             b"\x00\x00\x00\x01\x00\x00\x00\x01"+b"\x08\x02\x00\x00\x00"+
             b"\x90\x77\x53\xde"+b"\x00\x00\x00\x00IEND\xae\x42\x60\x82")
        image=base64.b64encode(png).decode()
        supervisor=FMRSDSupervisor(self.store,inventory=self.inventory,
            lookup=lambda _:None,lock_dir=self.path/"locks")
        supervisor._state["rds2_images"]=True
        supervisor._save_group(json.dumps({"rft":{"data":{"file_contents":image}}}).encode(),98_600_000)
        self.assertEqual(supervisor.status()["saved_images"],1)
        self.assertEqual(len(MediaStore(self.store).list()),1)

    def test_missing_decoder_prevents_spawn(self):
        supervisor=FMRSDSupervisor(self.store,
                inventory=self.inventory,
                lookup=lambda name: "/usr/bin/rtl_fm" if name=="rtl_fm" else None,
                lock_dir=self.path/"locks")
        self.assertFalse(supervisor.availability()["ready"])
        with self.assertRaises(CaptureError):
            supervisor.start(frequency_mhz=98.6,duration=15)
        self.assertEqual(supervisor.status()["status"],"idle")
        self.assertEqual(self.store.counts()["events"],0)

    def test_exclusive_cooperative_lock_fails_closed(self):
        first=FMRSDSupervisor(self.store, inventory=self.inventory,
                             lock_dir=self.path/"locks")
        second=FMRSDSupervisor(self.store, inventory=self.inventory,
                              lock_dir=self.path/"locks")
        fd=first._acquire_lock()
        try:
            with self.assertRaises(CaptureError):
                second._acquire_lock()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            import os
            os.close(fd)
        other=second._acquire_lock()
        fcntl.flock(other,fcntl.LOCK_UN)
        import os
        os.close(other)

    def test_synthetic_decoder_subprocess_emits_attributed_event(self):
        # Two executable fixtures pretend to be rtl_fm and redsea.
        # These scripts are NOT physical RF reception evidence.
        rt=self.path/"mock_rtl_fm"
        rd=self.path/"mock_redsea"
        rt.write_text('#!/usr/bin/env python3\n'
                      'import sys,time\n'
                      'sys.stdout.buffer.write(b"\\\\x00"*4096)\n'
                      'sys.stdout.buffer.flush()\n'
                      'time.sleep(0.6)\n')
        rd.write_text('#!/usr/bin/env python3\n'
                      'import sys,json,time\n'
                      'sys.stdin.buffer.read(64)\n'
                      'print(json.dumps({"pi":"0xD3C2","group":"2A",'
                      '"ps":"FAKE TEST","radiotext":"SYNTHETIC TEST ONLY"}),flush=True)\n'
                      'time.sleep(0.2)\n')
        rt.chmod(0o700)
        rd.chmod(0o700)
        binaries={"rtl_fm":str(rt),"redsea":str(rd)}
        supervisor=FMRSDSupervisor(self.store,inventory=self.inventory,
                     lookup=lambda name: binaries.get(name),
                     lock_dir=self.path/"locks",idle_seconds=30)
        response=supervisor.start(frequency_mhz=98.6,duration=10)
        self.assertTrue(response["active"])
        self.assertIn("session",response)
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            state=supervisor.status()
            if not state["active"]:
                break
            time.sleep(.04)
        else:
            supervisor.stop(wait=True)
            self.fail("Synthetic decoder worker did not terminate")
        self.assertEqual(state["saved_items"],1,state)
        self.assertEqual(state["received_groups"],1,state)
        events=self.store.events()
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["body"],"SYNTHETIC TEST ONLY")
        self.assertEqual(events[0]["medium"],"fm_rds")
        self.assertEqual(events[0]["frequency_hz"],98_600_000)
        self.assertFalse(state["active"])
        supervisor.stop(wait=True)


if __name__=="__main__":
    unittest.main()
