#!/usr/bin/env python3
"""PARITY16 source guard: exact frozen blobs and packaging-only deviations."""
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FROZEN = "7821769eb7aed576dd426ec18ffce3696d93a00d"


class Parity16SourceTests(unittest.TestCase):
    def test_immutable_frozen_source_and_companion_bytes(self):
        result = subprocess.run(
            ["git", "diff", "--exit-code", FROZEN, "HEAD", "--",
             "source/installed-package/"],
            cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # The original hardcoded reference is preserved in the frozen source.
        patch = ROOT / "source/installed-package/kaffeine_next/patch_upstream.py"
        self.assertIn('"/.local/share/tihulu-kaffeine/dvb_diagnostics.sh"',
                      patch.read_text())
        self.assertTrue((ROOT / "source/installed-package/kaffeine_next/dvb_diagnostics.sh").is_file())

    def test_build_time_native_only_relocation_is_strict_and_versioned(self):
        installer = (ROOT / "installer/media-stable-first.sh").read_text()
        self.assertIn('DVB_DIAGNOSTICS_ROUTE', installer)
        self.assertIn('Expected exactly one original DVB diagnostics action; refused', installer)
        self.assertIn('QCoreApplication::applicationDirPath()', installer)
        self.assertIn('/../../py/kaffeine_next/dvb_diagnostics.sh', installer)
        self.assertIn('Built native Kaffeine lacks bundled DVB diagnostics route', installer)

    def test_direct_module_shim_is_private_and_fail_closed(self):
        installer = (ROOT / "installer/media-stable-first.sh").read_text()
        self.assertIn('TV_COMPAT', installer)
        self.assertIn('os.O_DIRECTORY | os.O_NOFOLLOW', installer)
        self.assertIn('Refusing foreign preview TV entrypoint', installer)
        self.assertIn('Refusing unexpected preview TV entrypoint target', installer)
        self.assertIn('str(app / "current/bin/tihulu-kaffeine")', installer)
        self.assertIn('profile / ".local/bin"', installer)
        self.assertIn('resolved="$(readlink -f -- "$0")"', installer)


if __name__ == "__main__":
    unittest.main()
