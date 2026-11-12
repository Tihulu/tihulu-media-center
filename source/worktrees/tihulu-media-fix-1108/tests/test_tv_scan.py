import unittest
import tempfile
from pathlib import Path
from tv_center.scanner import PROFILES, MODES, scan_commands, parse_scan_progress, IncrementalScanLog

class CountryAutoScanTest(unittest.TestCase):
    def test_de_terrestrial(self):
        cmd, second = scan_commands("DE", "t", 0, Path("/tmp/freq.conf"), Path("/tmp/channels.conf"))
        self.assertEqual(cmd[:7], ["w_scan_cpp", "-f", "t", "-c", "DE", "-a", "0"])
        self.assertIn("-x", cmd)
        self.assertEqual(second[0], "dvbv5-scan")
        self.assertIn("DE", second)
    def test_tr_cable(self):
        cmd, second = scan_commands("TR", "c", 1, Path("/tmp/freq.conf"), Path("/tmp/channels.conf"))
        self.assertEqual(cmd[1:5], ["-f", "c", "-c", "TR"])
        self.assertIn("TR", second)
        self.assertEqual(set(PROFILES), {"DE", "TR"})
        self.assertEqual(set(MODES), {"t", "c", "s"})
    def test_reject_invalid_country_medium_adapter(self):
        for country, medium, adapter in [("FR", "t", 0), ("TR", "x", 0), ("DE", "c", -1), ("DE", "t", 100)]:
            with self.subTest(country=country, medium=medium, adapter=adapter), self.assertRaises(ValueError):
                scan_commands(country, medium, adapter, Path("/tmp/a"), Path("/tmp/b"))

    def test_progress_rejects_cpp_code_line_and_version_as_rf_frequency(self):
        logs = [
            "w_scan_cpp Version 20231015",
            "21:34:08 int COUNTRY::choose_country(std::string):386 DVB aerial",
            "21:34:08 cDevice* GetPreferredDevice(TChannel*):100 testing",
        ]
        for line in logs:
            with self.subTest(line=line):
                self.assertIsNone(parse_scan_progress(line)["frequency_reported"])

    def test_progress_recognizes_genuine_frequency(self):
        self.assertEqual(parse_scan_progress("538000: (time: 00:52.000)")["frequency_reported"],
                         "538.000 MHz")
        self.assertEqual(parse_scan_progress("signal ok: QAM_AUTO f = 626000 kHz")["frequency_reported"],
                         "626.000 MHz")

    def test_dvbv5_sweep_reports_real_frequency_services_and_lock(self):
        sample=parse_scan_progress("Scanning frequency #1 573000000")
        self.assertEqual(sample["frequency_reported"],"573.000 MHz")
        service=parse_scan_progress("Service KiKA HD, provider ZDF: digital television")
        self.assertEqual(service["service_reported"],"KiKA HD")
        self.assertIs(parse_scan_progress("Lock   (0x1f) Quality= Good")["demod_lock"],True)
        self.assertIs(parse_scan_progress("Lock   (0x03) Quality= Poor")["demod_lock"],False)

    def test_operator_source_scan_is_available_without_w_scan_cpp(self):
        from tv_center.scanner import AutoScanner
        self.assertTrue(callable(AutoScanner.run_from_initial_file))
        cmd,stage2=scan_commands("DE","t",0,Path("/tmp/initial"),Path("/tmp/list"))
        self.assertEqual(stage2[stage2.index("-T")+1],"2")

    def test_scan_logs_are_not_replayed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scan.log"
            path.write_bytes(b"w_scan_cpp Version 20231015\n21:34:08 scan started\n")
            reader = IncrementalScanLog(path)
            first = reader.poll()
            self.assertEqual(len(first), 2)
            self.assertEqual(reader.poll(), [])
            with path.open("ab") as f:
                f.write(b"538000: (time: 00:51.0)\r")
            self.assertEqual(reader.poll(), ["538000: (time: 00:51.0)"])
            self.assertEqual(reader.poll(), [])
