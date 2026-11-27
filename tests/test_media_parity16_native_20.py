#!/usr/bin/env python3
"""Real installed Ubuntu Kaffeine execution checks; synthetic/no RF devices."""
import os
from pathlib import Path
import signal
import subprocess
import time
import unittest

RELEASE = Path(os.environ["TIHULU_MEDIA_QA_RELEASE"]).resolve()
OWNER = Path(os.environ["HOME"]).resolve()
APP = OWNER / ".local/opt/tihulu-media-stable"
PREVIEW = APP / "preview-home"
SCRIPT = RELEASE / "py/kaffeine_next/dvb_diagnostics.sh"
NATIVE = RELEASE / "native/bin/kaffeine"
PRIVATE_LINK = PREVIEW / ".local/bin/tihulu-kaffeine"
EXPECTED = str(APP / "current/bin/tihulu-kaffeine")


def env():
    e = dict(os.environ)
    e.update(HOME=str(PREVIEW), TIHULU_MEDIA_OWNER_HOME=str(OWNER),
             XDG_CONFIG_HOME=str(PREVIEW / ".config"),
             XDG_DATA_HOME=str(PREVIEW / ".local/share"),
             XDG_CACHE_HOME=str(PREVIEW / ".cache"),
             XDG_STATE_HOME=str(PREVIEW / ".local/state"),
             PYTHONPATH=str(RELEASE / "py"),
             PYTHONDONTWRITEBYTECODE="1",
             QT_QPA_PLATFORM="xcb")
    return e


class Parity16NativeTests(unittest.TestCase):
    def test_01_native_binary_routes_to_packaged_dvb_script(self):
        self.assertTrue(SCRIPT.is_file(), SCRIPT)
        code = NATIVE.read_bytes()
        self.assertIn(b'/../../py/kaffeine_next/dvb_diagnostics.sh', code)
        self.assertNotIn(b'/.local/share/tihulu-kaffeine/dvb_diagnostics.sh', code)
        self.assertFalse((PREVIEW / ".local/share/tihulu-kaffeine/dvb_diagnostics.sh").exists())
        self.assertEqual((NATIVE.parent / "../../py/kaffeine_next/dvb_diagnostics.sh").resolve(), SCRIPT)

    def test_02_bundled_dvb_script_executes_without_real_hardware(self):
        # Strictly refuse a runner with real /dev/dvb. No owner device access.
        self.assertFalse(list(Path("/dev/dvb").glob("adapter*/frontend*")),
                         "Real DVB nodes present: test must not inspect tuner")
        p = subprocess.run(["/bin/bash", str(SCRIPT)], cwd="/",
                           env=env(), capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("DVB frontend diagnostics", p.stdout)
        self.assertIn("No /dev/dvb/adapter*/frontend* devices found", p.stdout)

    def test_03_direct_module_uses_owned_private_compat_entrypoint(self):
        self.assertTrue(PRIVATE_LINK.is_symlink())
        self.assertEqual(os.readlink(PRIVATE_LINK), EXPECTED)
        self.assertTrue(PRIVATE_LINK.is_file())
        self.assertFalse((OWNER / ".local/bin/tihulu-kaffeine").exists())

    def test_04_supported_tv_center_wrapper_is_native(self):
        p = subprocess.run([str(RELEASE / "bin/tihulu-tv-center"), "tv", "--version"],
                           cwd="/", env=env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue((p.stdout + p.stderr).strip(), "Expected native version output")

    def test_05_direct_python_tv_command_starts_real_native_gui(self):
        self.assertTrue(os.environ.get("DISPLAY"), "Xvfb DISPLAY required")
        process = subprocess.Popen(
            ["/usr/bin/python3", "-m", "tv_center", "tv"],
            cwd="/", env=env(), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            start_new_session=True)
        try:
            time.sleep(4)
            if process.poll() is not None:
                err = process.stderr.read(10000).decode(errors="replace")
                self.fail(f"Direct Python TV launch exited {process.returncode}: {err}")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=8)
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
