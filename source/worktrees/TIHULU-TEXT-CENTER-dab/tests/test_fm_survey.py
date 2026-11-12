"""No hardware accessed: rtl_power survey parser and subprocess fixture tests."""
import json
from pathlib import Path
import tempfile
import time
import unittest

from textcenter.fm_survey import (
    FMSurveySupervisor, SurveyError, build_survey_command, parse_power_csv,
    dab_blocks_for_peaks
)


def example_csv():
    # A single synthetic 87.5–89.9 MHz sweep. Artificial peaks at 88.1/88.6 MHz.
    values=[-65.0]*24
    values[6],values[11]=-35.0,-28.0
    return "2026-11-06, 01:00:00, 87500000, 89900000, 100000, 1, "+", ".join(map(str,values))+"\n"


class FMSurveyTests(unittest.TestCase):
    def test_parser_distinguishes_energy_from_station(self):
        parsed=parse_power_csv(example_csv())
        self.assertEqual(parsed["bins_analyzed"],24)
        self.assertEqual(len(parsed["candidates"]),2)
        self.assertTrue(all(x["verification"]=="unidentified_rf_energy"
                            for x in parsed["candidates"]))
        self.assertEqual(parsed["candidates"][0]["frequency_mhz"],88.65)
        self.assertNotIn("station",parsed["candidates"][0])
        self.assertEqual(parse_power_csv("not a csv")["candidates"],[])
        self.assertEqual(build_survey_command("/usr/bin/rtl_power")[-1],"-1")
        with self.assertRaises(ValueError):
            parse_power_csv("x"*(256001))

    def test_multiple_bands_do_not_claim_decoded_services(self):
        from textcenter.fm_survey import SURVEY_BANDS
        self.assertEqual(set(SURVEY_BANDS),{
            "fm","dab","aprs","drm","rtty","navtex","weatherfax"
        })
        args=build_survey_command("/usr/bin/rtl_power","navtex")
        self.assertIn("-D",args)
        self.assertIn("450k:560k:2k",args)
        self.assertNotIn("-D",build_survey_command("/usr/bin/rtl_power","dab"))
        with self.assertRaises(ValueError):
            build_survey_command("/usr/bin/rtl_power","ssh")
        # A fake low-frequency peak is still RF energy, not NAVTEX text.
        data=parse_power_csv(
            "2026-11-06, 01:00:00, 490000, 510000, 2000, 1, -40, -42, -43, -44, -45, -46, -47, -48, -49, -50\n",
            band="navtex")
        self.assertEqual(data["sweeps"],1)
        self.assertNotIn("station",data["candidates"][0] if data["candidates"] else {})

    def test_dab_energy_peaks_group_by_raster_not_by_station(self):
        # Values drawn from an example screenshot, not a captured/verified DAB
        # ensemble. Two peaks can belong to one nominal 1.536-MHz DAB block.
        raw = [178_383_000, 197_117_000, 197_805_000,
               207_602_000, 222_039_000, 222_555_000]
        peaks = [{"frequency_hz": hz, "above_median_db": 9.8} for hz in raw]
        blocks = dab_blocks_for_peaks(peaks)
        self.assertEqual({x["block"] for x in blocks}, {"5C", "8B", "9D", "11D"})
        by_block = {x["block"]: x for x in blocks}
        self.assertEqual(by_block["11D"]["center_frequency_hz"], 222_064_000)
        self.assertEqual(by_block["11D"]["peak_count"], 2)
        self.assertEqual(by_block["8B"]["peak_count"], 2)
        self.assertEqual(by_block["5C"]["peak_count"], 1)
        self.assertEqual(by_block["9D"]["peak_count"], 1)
        self.assertTrue(all(x["verification"] == "nominal_raster_match_only" for x in blocks))
        self.assertEqual(dab_blocks_for_peaks([
            {"frequency_hz": 300_000_000, "above_median_db": 8.0}
        ]), [])

    def test_dab_csv_exposes_grouped_block_candidates(self):
        values = [-70.0] * 11
        values[5] = -35.0
        values[9] = -30.0
        csv_line = ("2026-11-06, 01:00:00, 221500000, 222600000, 100000, 1, "
                    + ", ".join(str(v) for v in values) + "\n")
        report = parse_power_csv(csv_line, band="dab")
        self.assertEqual(len(report["candidates"]), 2)
        self.assertEqual(len(report["dab_blocks"]), 1)
        self.assertEqual(report["dab_blocks"][0]["block"], "11D")
        self.assertEqual(report["dab_blocks"][0]["peak_count"], 2)
        self.assertFalse(report["dab_decoder_connected"])
        self.assertNotIn("dab_blocks", parse_power_csv(example_csv(), band="fm"))

    def test_conflict_and_missing_binary_are_denied(self):
        with tempfile.TemporaryDirectory() as td:
            sup=FMSurveySupervisor(
                inventory=lambda:{"platform":"Linux","rtl_usb_count":1},
                conflicts=lambda:[{"process":"readsb"}],
                lookup=lambda _: "/usr/bin/rtl_power",
                lock_dir=Path(td)/"lock")
            self.assertFalse(sup.availability()["ready"])
            self.assertIn("readsb",sup.availability()["reason"])
            with self.assertRaises(SurveyError):
                sup.start()
            self.assertEqual(sup.status()["status"],"idle")
            sup2=FMSurveySupervisor(
                inventory=lambda:{"platform":"Linux","rtl_usb_count":1},
                conflicts=lambda:[],lookup=lambda _:None,
                lock_dir=Path(td)/"lock")
            self.assertIn("rtl_power",sup2.availability()["reason"])

    def test_mock_survey_emits_candidates_then_exits(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            executable=base/"mock_rtl_power"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "sys.stdout.write("+repr(example_csv())+")\n")
            executable.chmod(0o700)
            sup=FMSurveySupervisor(
                inventory=lambda:{"platform":"Linux","rtl_usb_count":1},
                conflicts=lambda:[],lookup=lambda _:str(executable),
                lock_dir=base/"locks",max_seconds=6)
            data=sup.start()
            self.assertTrue(data["active"])
            end=time.monotonic()+4
            while time.monotonic()<end:
                result=sup.status()
                if not result["active"]:
                    break
                time.sleep(0.03)
            else:
                sup.stop(wait=True)
                self.fail("Mock rtl_power never exited")
            self.assertEqual(result["status"],"completed",result)
            self.assertEqual(len(result["candidates"]),2)
            self.assertEqual(result["kind"],"spectrum_candidate_not_station")
            self.assertFalse(result["active"])
            sup.stop(wait=True)


if __name__=="__main__":
    unittest.main()
