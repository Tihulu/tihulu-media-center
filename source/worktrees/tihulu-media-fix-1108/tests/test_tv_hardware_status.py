"""USB/DVB discovery regression tests. Only synthetic sysfs/dev trees; no USB is opened."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tv_center.hardware_status import inspect, check_owners


class HardwareDiscoveryTests(unittest.TestCase):
    def test_inventory_matches_real_frontend_and_rtlsdr_without_claiming_usb(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            sysusb=root/"sys"/"bus"/"usb"/"devices"
            usb=sysusb/"2-3"
            usb.mkdir(parents=True)
            for name,text in (("idVendor","0bda"),("idProduct","2838"),
                              ("product","RTL2838U"),("manufacturer","Realtek"),
                              ("busnum","2"),("devnum","7")):
                (usb/name).write_text(text)
            harmless=sysusb/"2-4"
            harmless.mkdir()
            for name,text in (("idVendor","aaaa"),("idProduct","bbbb"),
                              ("product","USB keyboard")):
                (harmless/name).write_text(text)
            node=root/"dev"/"bus"/"usb"/"002"
            node.mkdir(parents=True)
            (node/"007").write_bytes(b"")
            dvb=root/"dev"/"dvb"/"adapter0"
            dvb.mkdir(parents=True)
            (dvb/"frontend0").write_bytes(b"")
            sysdvb=root/"sys"/"class"/"dvb"/"dvb0.frontend0"
            sysdvb.mkdir(parents=True)
            (sysdvb/"name").write_text("Silicon Labs Si2168")
            output=inspect(usb_root=sysusb,dvb_root=dvb.parent,
                           usb_nodes=node.parent,sys_dvb=sysdvb.parent)
            self.assertEqual(output["summary"]["usb_count"],2)
            self.assertEqual(output["summary"]["receiver_candidates"],1)
            self.assertEqual(output["summary"]["dvb_frontends"],1)
            radio=next(u for u in output["usb"] if u["vidpid"]=="0bda:2838")
            self.assertEqual(radio["path"],str(node/"007"))
            self.assertTrue(radio["receiver_candidate"])
            self.assertIn("connected",radio["physical"])
            self.assertEqual(output["dvb"][0]["name"],"Silicon Labs Si2168")
            self.assertIn("RF lock unverified",output["dvb"][0]["physical"])
            self.assertIn("never claims hardware",output["note"])

    def test_missing_devices_are_not_reported_as_bad_rf_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            status=inspect(usb_root=path/"no-usb",dvb_root=path/"no-dvb",
                           usb_nodes=path/"usb-nodes",sys_dvb=path/"no-sys")
            self.assertEqual(status["usb"],[])
            self.assertEqual(status["dvb"],[])
            self.assertEqual(status["summary"]["dvb_frontends"],0)

    def test_owner_check_is_read_only_and_never_runs_kill_or_sudo(self):
        data={"dvb":[{"path":"/dev/dvb/adapter0/frontend0"}]}
        fake=mock.Mock(returncode=0,stdout=b"1234\n",stderr=b"frontend: app\n")
        with mock.patch("shutil.which",return_value="/usr/bin/fuser"),\
             mock.patch("subprocess.run",return_value=fake) as runner:
            report=check_owners(data)
            args=runner.call_args.args[0]
            self.assertEqual(args,["/usr/bin/fuser","-v",
                                   "/dev/dvb/adapter0/frontend0"])
            self.assertIn("frontend:",report)

    def test_owner_check_no_dvb_never_starts_subprocess(self):
        with mock.patch("subprocess.run") as runner:
            self.assertIn("No DVB/SDR device nodes",check_owners({"dvb":[],"usb":[]}))
            runner.assert_not_called()


if __name__=="__main__":
    unittest.main()
