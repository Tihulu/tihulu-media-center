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

    def test_preview_settings_use_private_home_and_xdg(self) -> None:
        # Frozen source identities remain, but the wrapper must relocate HOME
        # and XDG paths before Qt or AI settings are initialized.
        config = (RELEASE / "bin/tihulu-preview-env").read_text()
        self.assertIn('HOME="$preview"', config)
        self.assertIn('XDG_CONFIG_HOME="$preview/.config"', config)
        self.assertIn('XDG_DATA_HOME="$preview/.local/share"', config)
        self.assertIn('XDG_CACHE_HOME="$preview/.cache"', config)
        self.assertIn('XDG_STATE_HOME="$preview/.local/state"', config)
        for name in ("tihulu-kaffeine", "tihulu-tv-center"):
            self.assertIn('. "$release/bin/tihulu-preview-env"',
                          (RELEASE / "bin" / name).read_text())
        self.assertIn('dbus-run-session -- "$release/bin/tihulu-kaffeine"',
                      (RELEASE / "bin/tihulu-kaffeine").read_text())
        self.assertTrue((HOME / ".local/opt/tihulu-media-stable/preview-home/.config").is_dir())
        # Source-level KaffeineRadio / appearance/JSON names are still preserved.
        self.assertIn('QLatin1String("KaffeineRadio")',
                      (RELEASE / "py/kaffeine_next/native_radio_tab.h").read_text())
        self.assertIn('QSettings("TIHULU", "KaffeineCaptionAppearance")',
                      (RELEASE / "py/kaffeine_next/captions_overlay.py").read_text())

    def test_uninstall_support_and_release_integrity_manifest(self) -> None:
        p = run("bash", str(ROOT / "installer/media-stable-first.sh"), "--help")
        self.assertEqual(p.returncode, 0)
        self.assertIn("--uninstall", p.stdout)
        self.assertTrue((RELEASE / ".media-preview-release.json").is_file())
        self.assertTrue((HOME / ".local/opt/tihulu-media-stable/.media-preview-owner-v1").is_file())


    def test_optional_speech_translation_imports_without_models(self) -> None:
        # Import compatibility only; no inference, package installation or download.
        code = (
            "import importlib,json\n"
            "names=['tv_center.whisper_engine','tv_center.cuda_faster_whisper',"
            "'tv_center.translation_service','tv_center.translation_madlad',"
            "'tv_center.translation_worker','tv_center.argos_generation']\n"
            "print(json.dumps({name:importlib.import_module(name).__file__ for name in names}))\n"
        )
        env = {**os.environ, "PYTHONPATH": str(RELEASE / "py"),
               "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1",
               "TRANSFORMERS_OFFLINE": "1"}
        p = subprocess.run(["/usr/bin/python3", "-c", code],
                           capture_output=True, text=True, timeout=30,
                           check=False, env=env, cwd="/")
        self.assertEqual(p.returncode, 0, p.stdout + "\n" + p.stderr)
        results = json.loads(p.stdout)
        self.assertEqual(len(results), 6)
        for module, path in results.items():
            self.assertTrue(Path(path).resolve().is_relative_to(RELEASE.resolve()),
                            f"Optional backend {module} imported outside release: {path}")

    def test_all_five_profiles_fail_closed_without_fallback_weights(self) -> None:
        # Status stubs reporting components "installed" cannot bypass the
        # selection guard for the actual local fallback model path.
        code = (
            "from pathlib import Path\n"
            "from tv_center.ai_profiles import PROFILES, COMPONENTS, selection_patch\n"
            "class Library:\n"
            "    root=Path.home()/'nonexistent-qa-model-root'\n"
            "    def _path(self, key): return self.root/(key+'.bin')\n"
            "hardware={'ram_mib':65536,'raspberry_pi_5':True,"
            "'gpu':{'detected':True,'vram_mib':32768},"
            "'npu':{'devices':['hailo-10h'],'hailo_arch':'HAILO10H'}}\n"
            "statuses={component:True for component in COMPONENTS}\n"
            "assert len(PROFILES)==5, PROFILES\n"
            "for name in PROFILES:\n"
            "    try: selection_patch(name,library=Library(),hardware=hardware,"
            "status=statuses,hailo_ready=True)\n"
            "    except RuntimeError as error:\n"
            "        assert 'Missing local CPU Whisper fallback model' in str(error),"
            "(name,str(error))\n"
            "    else: raise AssertionError('Selected AI profile without weights: '+name)\n"
            "print('Five model-selection guards rejected missing local weights')\n"
        )
        env = {**os.environ, "PYTHONPATH": str(RELEASE / "py"),
               "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1",
               "TRANSFORMERS_OFFLINE": "1"}
        p = subprocess.run(["/usr/bin/python3", "-c", code],
                           capture_output=True, text=True, timeout=30,
                           check=False, env=env, cwd="/")
        self.assertEqual(p.returncode, 0, p.stdout + "\n" + p.stderr)
        self.assertIn("Five model-selection guards rejected", p.stdout)


if __name__ == "__main__":
    unittest.main()
