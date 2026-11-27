import os
from pathlib import Path
import tempfile
import unittest

from textcenter.conflicts import find_receiver_conflicts
from textcenter.core import Store
from textcenter.fm_rds import FMRSDSupervisor, CaptureError


class ConflictsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.proc=self.root/"proc"
        self.proc.mkdir()
        self.usb=self.root/"usb"
        self.usb.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def addproc(self, pid, name):
        folder=self.proc/str(pid)
        folder.mkdir()
        (folder/"comm").write_text(name)
        (folder/"fd").mkdir()
        return folder

    def test_known_adsb_and_sdr_process_are_detected(self):
        self.addproc(500,"readsb")
        self.addproc(501,"gqrx")
        self.addproc(503,"firefox")
        found=find_receiver_conflicts(proc_root=self.proc,
                                      sys_usb_root=self.usb, self_pid=999)
        self.assertEqual([x["process"] for x in found],["readsb","gqrx"])
        self.assertEqual(found[0]["reason"],"known_receiver_process")

    def test_direct_usb_owner_detected_even_with_generic_process_name(self):
        usb=self.usb/"1-4"
        usb.mkdir()
        (usb/"idVendor").write_text("0bda")
        (usb/"idProduct").write_text("2838")
        (usb/"busnum").write_text("1")
        (usb/"devnum").write_text("7")
        p=self.addproc(555,"python3")
        (p/"fd"/"3").symlink_to("/dev/bus/usb/001/007")
        found=find_receiver_conflicts(proc_root=self.proc,
                                      sys_usb_root=self.usb,self_pid=999)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]["reason"],"rtl_usb_handle_open")

    def test_rds_start_blocked_before_usb_open(self):
        store=Store(self.root/"archive.db")
        sup=FMRSDSupervisor(
            store, inventory=lambda: {"platform":"Linux","rtl_usb_count":1},
            lookup=lambda name:"/usr/bin/"+name,
            conflicts=lambda: [{"pid":500,"process":"readsb",
                                 "reason":"known_receiver_process"}],
            lock_dir=self.root/"locks")
        self.assertFalse(sup.availability()["ready"])
        self.assertIn("readsb",sup.availability()["reason"])
        with self.assertRaises(CaptureError):
            sup.start(frequency_mhz=98.6,duration=10)
        self.assertEqual(sup.status()["status"],"idle")
        self.assertEqual(store.counts()["events"],0)


if __name__=="__main__":
    unittest.main()
