# SPDX-License-Identifier: GPL-2.0-or-later
"""Independent installed-runtime QA. CI only; no receivers, models or user machine.

This suite must run with TIHULU_MEDIA_QA_RELEASE pointing to an installer-created
release in a disposable HOME. It checks *installed* source and actual entrypoints,
rather than merely looking for names in a repository checkout. No inference is
performed, and successful tests are NOT TV/radio or release acceptance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
FROZEN = "7821769eb7aed576dd426ec18ffce3696d93a00d"
RELEASE = Path(os.environ.get("TIHULU_MEDIA_QA_RELEASE") or "/nonexistent/tihulu-media-qa")
HOME = Path(os.environ.get("HOME", "/nonexistent"))
HAS_INSTALLED_RELEASE = bool(os.environ.get("TIHULU_MEDIA_QA_RELEASE"))


def run(*args: str, timeout: int = 35) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), capture_output=True, text=True, timeout=timeout,
        check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


@unittest.skipUnless(HAS_INSTALLED_RELEASE, "requires disposable installed release")
class ExactInstalledRuntime(unittest.TestCase):
    def test_all_frozen_installed_package_bytes_match(self) -> None:
        # Verify the actual staged files, not only the HEAD source files.
        inventory = run(
            "git", "-C", str(ROOT), "ls-tree", "-r", "--name-only",
            FROZEN, "--", "source/installed-package",
        )
        self.assertEqual(inventory.returncode, 0, inventory.stderr)
        paths = [p for p in inventory.stdout.splitlines()
                 if p.startswith("source/installed-package/")
                 and p.split("/")[2] in ("tv_center", "textcenter", "kaffeine_next")]
        self.assertGreater(len(paths), 80, "Frozen installed-source inventory too small")
        for srcpath in paths:
            dest = RELEASE / "py" / srcpath.removeprefix("source/installed-package/")
            with self.subTest(path=srcpath):
                self.assertTrue(dest.is_file(), "Missing staged installed file: " + str(dest))
                orig = subprocess.run(
                    ["git", "-C", str(ROOT), "show", FROZEN + ":" + srcpath],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=15, check=False,
                )
                self.assertEqual(orig.returncode, 0, orig.stderr.decode(errors="replace"))
                self.assertEqual(dest.read_bytes(), orig.stdout,
                                 "Installed source diverges from frozen: " + srcpath)

    def test_isolated_release_provenance_and_launchers(self) -> None:
        provenance = (RELEASE / "SOURCE-PROVENANCE.txt").read_text()
        self.assertIn("snapshot_commit=" + FROZEN, provenance)
        self.assertIn("source_variant=installed-package", provenance)
        self.assertIn("no_automatic_models=true", provenance)
        self.assertTrue((RELEASE / "native/bin/kaffeine").is_file())
        for name in ("tihulu-tv-center", "tihulu-kaffeine", "tihulu-media-stable"):
            self.assertTrue((RELEASE / "bin" / name).is_file(), name)
        self.assertTrue((HOME / ".local/bin/tihulu-media-stable").is_file())
        self.assertTrue((HOME / ".local/share/applications/tihulu-media-stable.desktop").is_file())

    def test_staged_python_modules_resolve_into_release(self) -> None:
        # Import pure helpers via the installed wrapper's Python, not repo PYTHONPATH.
        code = (
            "import importlib, json\n"
            "names=['tv_center','textcenter','kaffeine_next',"
            "'tv_center.ai_profiles','tv_center.ai_settings',"
            "'tv_center.radio_karaoke_router','tv_center.lyrics_sync',"
            "'kaffeine_next.teletext_match','kaffeine_next.caption_timing',"
            "'textcenter.fm_rds']\n"
            "result={name:importlib.import_module(name).__file__ for name in names}\n"
            "print(json.dumps(result))\n"
        )
        env = {**os.environ, "PYTHONPATH": str(RELEASE / "py"),
               "PYTHONDONTWRITEBYTECODE": "1"}
        p = subprocess.run(["/usr/bin/python3", "-c", code], capture_output=True,
                           text=True, check=False, timeout=30, env=env, cwd="/")
        self.assertEqual(p.returncode, 0, p.stdout + "\n" + p.stderr)
        results = json.loads(p.stdout)
        self.assertEqual(len(results), 10)
        for name, srcpath in results.items():
            self.assertTrue(Path(srcpath).resolve().is_relative_to(RELEASE.resolve()),
                            f"{name} imported from outside staged release: {srcpath}")

    def test_installed_companion_language_catalog_is_real_command(self) -> None:
        # These queries may show NO MODELS. Presence must not be called inference.
        for option in ("ai-radio-languages", "ai-pairs"):
            with self.subTest(command=option):
                p = run(str(RELEASE / "bin/tihulu-tv-center"), option, timeout=45)
                self.assertEqual(p.returncode, 0, p.stdout + "\n" + p.stderr)
                info = json.loads(p.stdout)
                self.assertIsInstance(info, dict)
                self.assertIn("selected_translator", info)

    def test_native_kaffeine_version_executable(self) -> None:
        p = run(str(HOME / ".local/bin/tihulu-media-stable"), "--version", timeout=20)
        self.assertEqual(p.returncode, 0, p.stdout + "\n" + p.stderr)
        self.assertTrue((p.stdout + p.stderr).strip(), "No native --version response")

    def test_headless_gui_starts_without_crash(self) -> None:
        # CI runs inside xvfb-run + dbus-run-session, without RF devices.
        self.assertTrue(os.environ.get("DISPLAY"), "DISPLAY required for Xvfb GUI smoke")
        argv = [str(HOME / ".local/bin/tihulu-media-stable")]
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, start_new_session=True, cwd="/",
            env={**os.environ, "QT_QPA_PLATFORM": "xcb"},
        )
        try:
            time.sleep(4)
            if proc.poll() is not None:
                stderr = proc.stderr.read(10000).decode(errors="replace")
                self.fail(f"Native Kaffeine exited during GUI smoke: {proc.returncode}: {stderr}")
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=6)
            proc.stderr.close()

    def test_settings_collision_is_explicit_hold(self) -> None:
        # This audit records a confirmed blocker; it must never be labelled GO
        # merely because the installer creates a separately named launcher.
        ai_settings = (RELEASE / "py/tv_center/ai_settings.py").read_text()
        native_radio = (RELEASE / "py/kaffeine_next/native_radio_tab.h").read_text()
        captions = (RELEASE / "py/kaffeine_next/captions_overlay.py").read_text()
        self.assertIn('.config/tihulu-tv-center/ai-settings.json', ai_settings)
        self.assertIn('QLatin1String("KaffeineRadio")', native_radio)
        self.assertIn('QSettings("TIHULU", "KaffeineCaptionAppearance")', captions)
        print("HOLD: preview shares legacy AI JSON and QSettings identities; "
              "do not install alongside an existing user profile", flush=True)

    def test_uninstall_absent_is_explicit_hold(self) -> None:
        # Missing --uninstall is not a successful uninstall implementation.
        p = run("bash", str(ROOT / "installer/media-stable-first.sh"), "--uninstall")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("Unknown argument", p.stderr)
        print("HOLD: reversible current symlink is not an uninstall operation", flush=True)


if __name__ == "__main__":
    unittest.main()
