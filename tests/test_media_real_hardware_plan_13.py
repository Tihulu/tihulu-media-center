# SPDX-License-Identifier: GPL-2.0-or-later
"""C0 documentation-only contract. NOT a tuner/Whisper/hardware test.

May run on disposable GitHub Actions: uses only checked-out repository text
and git object metadata. Never inspects /dev, /sys, HOME settings, processes,
USB, models, recordings, hardware, services or network.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = "2f5699eeb47505468bf3327be4dbdd89fed3dff1"
FROZEN = "7821769eb7aed576dd426ec18ffce3696d93a00d"
PLAN = ROOT / "docs/MEDIA_REAL_HARDWARE_ACCEPTANCE_13.md"
CHECKLIST = ROOT / "docs/MEDIA_REAL_HARDWARE_CHECKLIST_13.md"
CASES = re.compile(
    r"^\| ((?:PRE|TV|RAD|AI|NEG|END)-\d{2}) \| "
    r"(C[1-4](?:\+C[1-4])?) \| (P[01]) \| .* \| NOT RUN \|$",
    re.M,
)
EXPECTED = {
    "PRE": 4,
    "TV": 13,
    "RAD": 11,
    "AI": 6,
    "NEG": 5,
    "END": 2,
}


def git(*args):
    p = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True, text=True, check=False, timeout=20,
    )
    if p.returncode:
        raise AssertionError(
            "git command failed or source identity diverged: "
            + " ".join(args) + "\n" + p.stderr
        )
    return p.stdout


class HardwarePlanIsNotHardwareAcceptance(unittest.TestCase):
    def test_exact_baseline_and_frozen_source_unchanged(self):
        git("cat-file", "-e", BASE + "^{commit}")
        git("cat-file", "-e", FROZEN + "^{commit}")
        git("merge-base", "--is-ancestor", BASE, "HEAD")
        # No source or installer could have changed on this QA branch.
        for subtree in ("source/installed-package/", "installer/"):
            self.assertEqual(
                git("diff", "--name-only", BASE, "HEAD", "--", subtree).strip(),
                "", "protected source/installer modified: " + subtree,
            )
        self.assertEqual(
            git("diff", "--name-only", FROZEN, "HEAD", "--",
                "source/installed-package/").strip(), "",
            "frozen source diverges",
        )

    def test_only_dedicated_qa_docs_and_no_device_execution(self):
        modified = set(git("diff", "--name-only", BASE, "HEAD").splitlines())
        allowed = {
            "docs/MEDIA_REAL_HARDWARE_ACCEPTANCE_13.md",
            "docs/MEDIA_REAL_HARDWARE_CHECKLIST_13.md",
            "tests/test_media_real_hardware_plan_13.py",
            ".github/workflows/media-real-hardware-plan-13.yml",
        }
        self.assertEqual(modified, allowed)
        self.assertNotIn("source/installed-package/", "\n".join(modified))

    def test_all_41_owner_cases_remain_not_run(self):
        text = CHECKLIST.read_text(encoding="utf-8")
        ids = re.findall(r"^\| ((?:PRE|TV|RAD|AI|NEG|END)-\d{2}) \|", text, re.M)
        matched = CASES.findall(text)
        self.assertEqual(len(ids), 41)
        self.assertEqual(len(matched), len(ids), "All owner rows must be NOT RUN")
        self.assertEqual(len(set(ids)), 41, "Duplicate case IDs")
        for prefix, expected in EXPECTED.items():
            self.assertEqual(sum(k.startswith(prefix+"-") for k in ids), expected)
        for _id, tier, priority in matched:
            self.assertRegex(tier, r"^C[1-4](?:\+C[1-4])?$")
            self.assertIn(priority, ("P0", "P1"))

    def test_ci_history_never_claimed_as_real_hardware_pass(self):
        c = CHECKLIST.read_text(encoding="utf-8")
        p = PLAN.read_text(encoding="utf-8")
        for text in (c, p):
            self.assertIn("2f5699eeb47505468bf3327be4dbdd89fed3dff1", text)
            self.assertIn("7821769eb7aed576dd426ec18ffce3696d93a00d", text)
            self.assertIn("151/151", text)
            self.assertIn("HOLD", text)
        self.assertIn("zero owner-hardware cases executed", c)

    def test_tuner_ownership_and_real_qa_scope_present(self):
        p = PLAN.read_text(encoding="utf-8")
        c = CHECKLIST.read_text(encoding="utf-8")
        for item in ("2040:8268", "0bda:2838", "Si2168",
                     "DVB-T2", "FM", "DAB", "Teletext",
                     "Whisper", "Lyrics", "Karaoke",
                     "COSMIC", "readsb", "fuser",
                     "signal", "recording", "C4",
                     "PR #11"):
            self.assertIn(item.casefold(), (p + c).casefold())
        self.assertIn("No owner machine operations", p)
        self.assertIn("existing working Media Center", p)
        self.assertIn("no merge", p.lower())

    def test_each_operator_tier_requires_owner_authorization(self):
        p = PLAN.read_text(encoding="utf-8")
        c = CHECKLIST.read_text(encoding="utf-8")
        for tier in ("C1", "C2", "C3", "C4"):
            self.assertIn(tier, p)
            self.assertIn(tier, c)
        self.assertIn("Owner", c)
        self.assertIn("Gate G0", c)
        self.assertIn("Gate G6", c)
        self.assertIn("original Media Center", c)

    def test_no_real_hardware_run_is_claimed(self):
        c = CHECKLIST.read_text(encoding="utf-8")
        self.assertIn("0/41", c)
        self.assertNotIn("| OWNER-RF PASS |", c)
        self.assertNotIn("| OWNER-AI PASS |", c)


if __name__ == "__main__":
    unittest.main()
