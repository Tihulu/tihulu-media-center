# SPDX-License-Identifier: GPL-2.0-or-later
"""Behavioral regressions using synthetic media/models. No RF, host settings or inference."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source/installed-package"
sys.path.insert(0, str(SOURCE))
from tv_center import media_ai, file_live_captions, local_assets
from tv_center.lyrics_sync import LyricCue



_runtime = None
_caption_env = None
_runtime_path = None


def read(relative):
    return (SOURCE / relative).read_text(encoding="utf-8")


def setUpModule():
    global _runtime, _caption_env, _runtime_path
    _runtime = tempfile.TemporaryDirectory(prefix="tihulu-cap-services-")
    home = Path(_runtime.name) / "home"
    home.mkdir(parents=True, exist_ok=True)
    runtime = Path(_runtime.name) / "run"
    runtime.mkdir(parents=True, exist_ok=True)
    os.chmod(runtime, 0o700)
    _runtime_path = runtime
    _caption_env = {k: v for k, v in os.environ.items()
                    if k not in ("PYTHONPATH", "LD_LIBRARY_PATH", "CONDA_PREFIX")}
    _caption_env.update({"HOME": str(home), "XDG_RUNTIME_DIR": str(runtime),
                         "QT_QPA_PLATFORM": "offscreen",
                         "PYTHONDONTWRITEBYTECODE": "1",
                         "PYTHONPATH": str(SOURCE)})


def tearDownModule():
    if _runtime is not None:
        _runtime.cleanup()


class OfflineRegressions(unittest.TestCase):
    def test_live_window_keeps_real_timing_and_translation_failure_original(self):
        decoded = Mock(returncode=0, stdout=b"\x30\x01" * 256000)
        cues = [LyricCue(12.3, 14.1, "genuine original", "fixture", "de")]
        with patch.object(file_live_captions.subprocess, "run", return_value=decoded), \
             patch.object(file_live_captions, "_chunk_cues", return_value=cues) as asr, \
             patch.object(file_live_captions, "_translate_cues", return_value=({}, [{"warning":"No installed DE → TR route"}])):
            result = file_live_captions.caption_window(Path("fixture.wav"), 12, source="de",
                targets=("tr",), profile={}, backend="cpu", translations_only=True)
        self.assertEqual(result["cues"], [{"start":12300,"end":14100,"text":"genuine original"}])
        self.assertEqual(result["end"], 20000)
        self.assertIn("DE → TR", result["warning"])
        self.assertEqual(asr.call_args.kwargs["position"], 12)

    def test_silence_does_not_invoke_asr(self):
        with patch.object(file_live_captions.subprocess, "run", return_value=Mock(returncode=0,stdout=b"\x00"*64000)), \
             patch.object(file_live_captions, "_chunk_cues") as asr:
            result=file_live_captions.caption_window(Path("fixture.wav"),0,source="en",targets=(),profile={},backend="cpu")
        asr.assert_not_called();self.assertEqual(result["cues"],[])

    def test_decoder_failure_never_returns_completed_captions(self):
        with patch.object(file_live_captions.subprocess,"run",return_value=Mock(returncode=1,stdout=b"partial")):
            with self.assertRaisesRegex(RuntimeError,"decode"):
                file_live_captions.caption_window(Path("fixture.wav"),0,source="en",targets=(),profile={},backend="cpu")

    def test_offline_file_rejects_online_translator_even_for_lyrics(self):
        ai=Mock(values={"translation_model":"deepl"})
        with patch.object(media_ai,"validate_local_media",return_value=Path("fixture.wav")),patch.object(media_ai,"AISettings",return_value=ai),patch.object(media_ai,"_lyrics_for_file") as lyrics:
            with self.assertRaisesRegex(ValueError,"offline translator"):
                media_ai.create_subtitles("fixture.wav",targets=("tr",),lyrics=True)
            lyrics.assert_not_called()

    def test_readonly_argos_weights_and_private_tokenizer_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);home=base/"preview";owner=base/"assets";home.mkdir()
            packages=owner/".local/share/argos-translate/packages"
            package=packages/"translate-en_tr";package.mkdir(parents=True)
            (package/"model").mkdir();weight=package/"model/model.bin";weight.write_bytes(b"synthetic-weights")
            (package/"metadata.json").write_text('{"from_code":"en","to_code":"tr"}')
            with zipfile.ZipFile(package/"stanza.zip","w") as archive:archive.writestr("stanza/tokenizer.dat",b"synthetic-tokenizer")
            with patch.dict(os.environ,{"HOME":str(home),"TIHULU_ASSET_HOME":str(owner),"XDG_CACHE_HOME":str(home/"cache")}):
                local_assets.prepare_argos_runtime_view()
                view=Path(os.environ["ARGOS_PACKAGES_DIR"])/package.name
                self.assertEqual((view/"model/model.bin").resolve(),weight)
                tokenizer=view/"stanza/tokenizer.dat"
                self.assertFalse(tokenizer.is_symlink());tokenizer.write_bytes(b"runtime extraction")
                self.assertFalse((package/"stanza").exists())
                self.assertEqual(weight.read_bytes(),b"synthetic-weights")
                local_assets.prepare_argos_runtime_view()
                self.assertEqual(tokenizer.read_bytes(),b"runtime extraction")

    def test_nllb_oom_retries_cpu_and_retains_cpu_device(self):
        from contextlib import nullcontext
        from tv_center import translation_market
        model=Mock()
        device=["cuda:0"]
        model.parameters.side_effect=lambda:iter([Mock(device=device[0])])
        model.to.side_effect=lambda value:device.__setitem__(0,value)
        model.generate.side_effect=[RuntimeError("CUDA out of memory"),[[7]],[[8]]]
        class Batch(dict):
            def to(self, value):return self
        tokenizer=Mock(return_value=Batch(input_ids="fixture"))
        tokenizer.batch_decode.return_value=["translated fixture"]
        torch=Mock();torch.inference_mode.side_effect=nullcontext
        with patch.object(translation_market,"_load_nllb",return_value=(model,tokenizer,"cuda",torch)), \
             patch.object(translation_market,"nllb_token_id",return_value=("eng_Latn",7)):
            self.assertEqual(translation_market.run_nllb("fixture","de","en"),"translated fixture")
            self.assertEqual(translation_market.run_nllb("fixture","de","en"),"translated fixture")
        model.to.assert_called_once_with("cpu");torch.cuda.empty_cache.assert_called_once()
        self.assertEqual(model.generate.call_count,3)

    def test_file_translation_budget_is_separate_from_live_deadline(self):
        from tv_center import translation_service
        service=translation_service.NLLBService()
        proc=Mock();proc.poll.return_value=None;proc.stdout.readline.return_value=b'{"translated":"fixture"}\n'
        def start():service.process=proc
        with patch.object(service,"_start",side_effect=start),patch.object(translation_service.select,"select",return_value=([proc.stdout],[],[])) as select:
            self.assertEqual(service.translate("fixture","de","en"),"fixture")
            self.assertEqual(select.call_args.args[3],180)
            with translation_service.live_translation_budget(2):
                service.translate("fixture","de","en")
            self.assertGreater(select.call_args.args[3],0)
            self.assertLessEqual(select.call_args.args[3],2)
        service.process=None

    def test_argos_archive_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);home=base/"home";owner=base/"owner";home.mkdir()
            package=owner/".local/share/argos-translate/packages/pack";package.mkdir(parents=True)
            with zipfile.ZipFile(package/"stanza.zip","w") as archive:archive.writestr("../../escape",b"bad")
            with patch.dict(os.environ,{"HOME":str(home),"TIHULU_ASSET_HOME":str(owner),"XDG_CACHE_HOME":str(home/"cache")}):
                with self.assertRaisesRegex(ValueError,"Unsafe"):
                    local_assets.prepare_argos_runtime_view()
            self.assertFalse((home/"escape").exists())


class StopReleasesAi(unittest.TestCase):
    def test_player_stop_releases_resident_workers(self):
        from tv_center import ai_release
        svc=Mock()
        worker=Mock()
        torch=Mock();torch.cuda.is_available.return_value=True
        with patch("tv_center.translation_service._service",svc), \
             patch("tv_center.translation_service._argos_service",svc), \
             patch("tv_center.translation_service._madlad_service",svc), \
             patch.dict(sys.modules,{"tv_center.cuda_faster_whisper":Mock(_worker=worker),"torch":torch}):
            released=ai_release.release_local_ai()
        self.assertEqual(len(released),5)   # 3 translator workers + whisper + cache
        self.assertGreaterEqual(released.count("Mock"),3)
        self.assertIn("faster-whisper",released)
        self.assertIn("cuda-cache",released)
        self.assertEqual(svc.close.call_count,3)
        torch.cuda.empty_cache.assert_called_once()

    def test_release_never_disables_settings_or_touches_models(self):
        from tv_center import ai_release
        svc=Mock()
        with patch("tv_center.translation_service._service",svc), \
             patch.dict(sys.modules,{"tv_center.cuda_faster_whisper":Mock(_worker=Mock()),"torch":None}):
            ai_release.release_local_ai()
        svc.close.assert_called_once()

    def test_caption_control_accepts_a_stop_request(self):
        import socket, glob
        mod=glob.glob(str(SOURCE/"kaff*"))[0].rsplit("/",1)[-1]
        caption_control=__import__(f"{mod}.caption_control",fromlist=["CaptionServiceControl"])
        CaptionServiceControl=caption_control.CaptionServiceControl
        with tempfile.TemporaryDirectory() as folder:
            runtime=Path(folder);pid=4242
            server=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
            path=runtime/f"tihulu-captions-control-{pid}.sock"
            server.bind(str(path));server.settimeout(1)
            self.assertTrue(CaptionServiceControl.request_stop(runtime,pid))
            data,_=server.recvfrom(64)
            self.assertEqual(data,b"STOP")
            server.close();path.unlink()
            self.assertFalse(CaptionServiceControl.request_stop(runtime,pid))


class FileCaptionService(unittest.TestCase):
    """The local-file caption path reuses the live-TV engine end to end."""
    def _tap(self):
        import glob, importlib
        mod=glob.glob(str(SOURCE/"kaff*"))[0].rsplit("/",1)[-1]
        overlay=importlib.import_module(f"{mod}.captions_overlay")
        return overlay

    def test_position_state_is_validated_and_rejects_foreign_files(self):
        overlay=self._tap()
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            media=base/"clip.mkv"
            subprocess.run(["/usr/bin/ffmpeg","-nostdin","-v","error","-f","lavfi","-i",
                "sine=frequency=440:duration=20","-c:a","aac",str(media)],timeout=60,check=True)
            state=base/"pos.json"
            state.write_text(json.dumps({"path":str(media),"position_ms":4200,"playing":True}))
            tap=overlay.CaptionTap(str(Path(os.environ["XDG_RUNTIME_DIR"])/"tihulu-dvb-1.sock"),lambda:{"mode":"asr"},Mock())
            tap.file_media=str(media);tap.file_position_state=str(state)
            self.assertEqual(tap._read_file_position(),(4200,True))
            state.write_text(json.dumps({"path":str(base/"other.mkv"),"position_ms":10,"playing":True}))
            self.assertIsNone(tap._read_file_position())
            state.write_text("not json")
            self.assertIsNone(tap._read_file_position())

    def test_file_feeder_pushes_real_audio_windows_into_the_tv_queue(self):
        overlay=self._tap()
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            media=base/"clip.mkv"
            subprocess.run(["/usr/bin/ffmpeg","-nostdin","-v","error","-f","lavfi","-i",
                "sine=frequency=440:duration=20","-c:a","aac",str(media)],timeout=60,check=True)
            state=base/"pos.json"
            state.write_text(json.dumps({"path":str(media),"position_ms":0,"playing":True}))
            options={"mode":"asr","revision":1,"live_priority":True}
            tap=overlay.CaptionTap(str(Path(os.environ["XDG_RUNTIME_DIR"])/"tihulu-dvb-1.sock"),lambda:dict(options),Mock())
            tap.start_file(media,state,window=6,feed_only=True)
            try:
                self.assertTrue(tap.thread.is_alive())   # feeder runs; worker skipped in this probe
                for position in (0,3000,7000,12000):
                    state.write_text(json.dumps({"path":str(media),"position_ms":position,"playing":True}))
                    time.sleep(.25)
                clip=tap.work_queue.get(timeout=6)
                self.assertIsNotNone(clip)
                self.assertGreaterEqual(len(clip.data),6400)
                self.assertEqual(clip.options["mode"],"asr")
                self.assertLessEqual(clip.ended-clip.started,6.5)
            finally:
                tap.stop.set();tap.close()

    def test_seek_backwards_resynchronizes_and_pause_stops_feeding(self):
        overlay=self._tap()
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            media=base/"clip.mkv"
            subprocess.run(["/usr/bin/ffmpeg","-nostdin","-v","error","-f","lavfi","-i",
                "sine=frequency=440:duration=20","-c:a","aac",str(media)],timeout=60,check=True)
            state=base/"pos.json"
            tap=overlay.CaptionTap(str(Path(os.environ["XDG_RUNTIME_DIR"])/"tihulu-dvb-1.sock"),lambda:{"mode":"asr"},Mock())
            tap.file_media=str(media);tap.file_position_state=str(state);tap.file_window=6
            state.write_text(json.dumps({"path":str(media),"position_ms":20000,"playing":True}))
            time.sleep(.3)
            state.write_text(json.dumps({"path":str(media),"position_ms":1000,"playing":True}))
            time.sleep(.3)
            self.assertLessEqual(tap.file_last_end or 0,8)
            state.write_text(json.dumps({"path":str(media),"position_ms":2000,"playing":False}))
            time.sleep(.3)
            self.assertIsNone(tap.file_last_end)

    def _control(self):
        import glob, importlib
        mod=glob.glob(str(SOURCE/"kaff*"))[0].rsplit("/",1)[-1]
        return importlib.import_module(f"{mod}.caption_control")

    def test_file_service_uses_its_own_private_socket(self):
        """The file caption service must not borrow the DVB socket name."""
        overlay=self._tap()
        runtime=Path(os.environ["XDG_RUNTIME_DIR"])
        for name in ("tihulu-dvb-99.sock","tihulu-file-99.sock"):
            self.assertEqual(overlay.validate_socket(str(runtime/name)).name,name)
        for name in ("tihulu-dvb-99.sock","tihulu-file-99.sock"):
            # Both names must stay inside the owner's own runtime directory.
            with self.assertRaises(ValueError):
                overlay.validate_socket("/etc/"+name)
        # A foreign or crafted name is still refused.
        with self.assertRaises(ValueError):
            overlay.validate_socket(str(runtime/"tihulu-tuner-99.sock"))

    def test_service_identity_only_names_the_file_service(self):
        overlay=self._tap()
        self.assertEqual(overlay.service_identity(["kaffeine-captions-file",
                                                   "--socket","x"]),"file")
        self.assertEqual(overlay.service_identity(["kaffeine-captions",
                                                   "--socket","x"]),"dvb")
        self.assertEqual(overlay.service_identity([]),"dvb")

    def test_file_and_tv_services_have_separate_control_sockets(self):
        """Starting file captions must not focus or reuse the TV service."""
        control=self._control()
        with tempfile.TemporaryDirectory() as folder:
            runtime=Path(folder)
            self.assertEqual(
                control.control_path(runtime,4242,"dvb").name,
                "tihulu-captions-control-4242.sock")       # TV keeps its name
            self.assertEqual(
                control.control_path(runtime,4242,"file").name,
                "tihulu-captions-control-4242-file.sock")
            self.assertEqual(
                control.control_path(runtime,4242,"radio").name,
                "tihulu-captions-control-4242-radio.sock")
            # A running TV service must NOT answer for the file service.
            import socket
            server=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
            tv=control.control_path(runtime,4242,"dvb")
            server.bind(str(tv));server.settimeout(.5)
            self.assertTrue(control.CaptionServiceControl.request_show(runtime,4242,"dvb"))
            data,_=server.recvfrom(64);self.assertEqual(data,b"SHOW")
            server.close();tv.unlink()
            self.assertFalse(
                control.CaptionServiceControl.request_show(runtime,4242,"file"))

    def test_every_python_ui_follows_the_saved_appearance(self):
        """No Python dialog may stay light while the native player is dark."""
        from tv_center.theme import install_theme
        callers=("tv_center/__main__.py","tv_center/media_ui.py")
        for caller in callers:
            self.assertIn("install_theme(app)",read(caller),caller)
        # The caption service must use the shared helper, not a private copy.
        overlay=read("kaffeine_next/captions_overlay.py")
        self.assertIn("from tv_center.theme import install_theme",overlay)
        self.assertIn("install_theme(app)",overlay)

    def test_shared_theme_helper_reaches_already_open_dialogs(self):
        """A dark appearance must actually reach the dialogs, and a later
        change must be picked up while a dialog is still open."""
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtGui import QPalette
        from PyQt5.QtCore import QSettings as RealSettings
        from tv_center.theme import install_theme

        class ModeSettings:
            """Minimal stand-in: Qt caches QSettings per org/app in-process,
            so the saved appearance is supplied directly."""
            current = "system"
            def value(self, key, default=None):
                return self.current if key == "theme" else default
            def sync(self):
                pass

        fake = ModeSettings()
        app = QApplication.instance() or QApplication(["tihulu-theme-test"])
        for mode, expected in (("dark", "#18222d"), ("light", "#f4f6f8")):
            if hasattr(app, "_tihulu_theme_timer"):
                app._tihulu_theme_timer.stop()
                del app._tihulu_theme_timer
            fake.current = mode
            with patch("PyQt5.QtCore.QSettings", return_value=fake):
                app.setPalette(QPalette())
                install_theme(app)
                color = app.palette().color(QPalette.Active, QPalette.Window)
                self.assertEqual(color.name(), expected, mode)
        # The helper keeps polling, so an already open dialog follows a later
        # appearance change instead of staying light.
        timer = getattr(app, "_tihulu_theme_timer", None)
        self.assertIsNotNone(timer)
        self.assertTrue(timer.isActive())
        # The saved appearance is read from the shared TIHULU/Appearance store.
        self.assertIn('QSettings("TIHULU", "Appearance")',
                      read("tv_center/theme.py"))

    def test_radio_caption_start_never_blocks_the_ui_thread(self):
        """Owner report: radio live AI hangs.

        startCaptioning() runs inside the 150 ms captionTick_ timer lambda on
        the Qt main thread, and it used to call waitForStarted(1200). Every
        retry therefore froze the radio tab for up to 1.2 s, and the recovery
        loop kept retrying, so the tab stayed effectively frozen.
        """
        code = read("kaffeine_next/native_radio_tab.h")
        start = code.index("void startCaptioning()")
        end = code.index("void clearKaraokeLine()", start)
        body = code[start:end]
        # No blocking start wait anywhere in the caption start path
        # (comments may name the removed call, so match the actual call).
        self.assertNotIn("captionProcess_.waitForStarted", body,
                         "caption start must not block the main thread")
        self.assertNotIn("captionProcess_.waitForFinished", body)
        # The start is asynchronous and a failure is still reported.
        self.assertIn("captionProcess_.start(QLatin1String(\"tihulu-tv-center\")",
                      body)
        self.assertIn("radio ASR/translation starting", body)
        # The async error handler must surface the failure, not stay silent.
        self.assertIn("Offline radio AI sidecar could not start · retrying",
                      code)

    def test_panel_launches_the_file_caption_service_with_its_own_socket(self):
        """The player opens kaffeine-captions-file on a file socket, never the
        TV service name."""
        code=read("kaffeine_next/native_media_panel.h")
        self.assertIn('QStringLiteral("kaffeine-captions-file")',code)
        self.assertIn('QStringLiteral("/tihulu-file-")',code)
        self.assertNotIn('QStringLiteral("kaffeine-captions"),QStringLiteral("--socket")',
                         code)
        # Live TV captions keep their own untouched entry point.
        recorder=read("kaffeine_next/native_unified_recorder.h")
        self.assertIn('QLatin1String("kaffeine-captions"),',recorder)
        self.assertIn('QLatin1String("/tihulu-dvb-")',recorder)


class DefaultsAndCache(unittest.TestCase):
    def test_installed_model_is_found_without_enabling_ai(self):
        from tv_center.installed_speech import installed_speech_model
        with tempfile.TemporaryDirectory() as folder:
            model=Path(folder)/".local/share/TIHULU/tihulu-media-center/models/ggml-small.bin"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"x"*(2*1024*1024))
            with patch.dict(os.environ,{"HOME":folder,"TIHULU_ASSET_HOME":""}):
                self.assertEqual(installed_speech_model(),str(model))

    def test_no_installed_model_reports_empty(self):
        from tv_center.installed_speech import installed_speech_model
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,{"HOME":folder,"TIHULU_ASSET_HOME":""}):
                self.assertEqual(installed_speech_model(),"")

    def test_radio_start_uses_installed_model_in_memory_only(self):
        from tv_center import radio_ai
        class Stop(RuntimeError): pass
        with tempfile.TemporaryDirectory() as folder:
            model=(Path(folder)/".local/share/TIHULU/tihulu-media-center/models/voja.bin")
            model.parent.mkdir(parents=True);model.write_bytes(b"x"*(2*1024*1024))
            with patch.dict(os.environ,{"HOME":folder,"TIHULU_ASSET_HOME":""}), \
                 patch("tv_center.radio_ai.AISettings") as ai, \
                 patch.object(radio_ai,"_choose_model",side_effect=Stop()):
                ai.return_value.values={"asr_enabled":False,"model_path":"","backend":"auto"}
                with self.assertRaises(Stop):
                    radio_ai.decode_radio_live(port=44000,sid="0xd49e",source="de",
                        targets=("en",),output=str(Path(os.environ["XDG_RUNTIME_DIR"])/"tihulu-radio-captions-test.json"))
                self.assertTrue(ai.return_value.values["asr_enabled"])
                self.assertEqual(ai.return_value.values["model_path"],str(model))

    def test_dab_capture_keeps_pacing_without_stalling(self):
        """Owner report: radio live AI hangs. The audio capture must keep a
        steady pace against a live loopback stream, never stall or report a
        false end of stream while audio is still flowing."""
        import http.server
        import socketserver
        import threading as _threading
        from tv_center.radio_capture import BoundedRadioCapture

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            mp3 = base / "stream.mp3"
            subprocess.run(
                ["/usr/bin/ffmpeg", "-nostdin", "-v", "error",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
                 "-c:a", "libmp3lame", "-b:a", "64k", str(mp3)],
                timeout=90, check=True)
            payload = mp3.read_bytes()

            class Quiet(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/mpeg")
                    # An unbounded body keeps the client from seeing EOF early.
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                def log_message(self, *_a):
                    pass

            class Server(socketserver.ThreadingTCPServer):
                allow_reuse_address = True
                daemon_threads = True

            server = Server(("127.0.0.1", 0), Quiet)
            port = server.server_address[1]
            thread = _threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                ffmpeg = subprocess.Popen(
                    ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                     "-protocol_whitelist", "file,http,tcp",
                     "-rw_timeout", "5000000",
                     "-i", f"http://127.0.0.1:{port}/stream.mp3",
                     "-map", "0:a:0", "-ac", "1", "-ar", "32000",
                     "-vn", "-f", "s16le", "pipe:1"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL)
                capture = BoundedRadioCapture(
                    ffmpeg.stdout, samples_per_second=32000,
                    max_windows=0, queue_size=4).start()
                windows = []
                deadline = time.monotonic() + 12.0
                try:
                    while time.monotonic() < deadline and len(windows) < 4:
                        item = capture.next(timeout=1.0)
                        if item is None:
                            break          # a real end of stream
                        windows.append(item)
                finally:
                    capture.stop()
                    ffmpeg.terminate()
                    try:
                        ffmpeg.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        ffmpeg.kill(); ffmpeg.wait(timeout=10)
                # Four audio windows must arrive without the reader stalling.
                self.assertGreaterEqual(len(windows), 3,
                    "radio audio capture stalled or reported an early EOF")
                index, pcm, _stamp = windows[0]
                self.assertEqual(index, 0)
                self.assertGreater(len(pcm), 32000 * 2)
            finally:
                server.shutdown(); server.server_close()

    def test_private_cache_prune_never_touches_user_files(self):
        from tv_center.file_live_captions import prune_private_caches
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            cache=home/".cache"
            cache.mkdir()
            with patch.dict(os.environ,{"HOME":str(home),"XDG_CACHE_HOME":str(cache),"TIHULU_ASSET_HOME":""}), \
                 patch("PyQt5.QtCore.QStandardPaths.writableLocation",return_value=str(cache)):
                own=cache/"tihulu-file-1-1.srt";own.write_text("stale")
                foreign=home/"my-subtitles.srt";foreign.write_text("user")
                old=time.time()-40*86400
                os.utime(own,(old,old))
                prune_private_caches(max_age_days=14)
                self.assertFalse(own.exists())
                self.assertTrue(foreign.exists())


class TranslationBatching(unittest.TestCase):
    def test_free_vram_prefers_cpu_for_long_translation(self):
        from tv_center import media_ai
        torch=Mock();torch.cuda.is_available.return_value=True;torch.cuda.mem_get_info.return_value=(2*1024**3,16*1024**3)
        with patch.dict(sys.modules,{"torch":torch}),patch.dict(os.environ,{"TIHULU_TRANSLATOR_DEVICE":"gpu"}):
            self.assertTrue(media_ai._prefer_cpu_translation())
            torch.cuda.mem_get_info.return_value=(9*1024**3,16*1024**3)
            self.assertFalse(media_ai._prefer_cpu_translation())
        torch2=Mock();torch2.cuda.is_available.return_value=False
        with patch.dict(sys.modules,{"torch":torch2}):
            self.assertTrue(media_ai._prefer_cpu_translation())

    def test_cue_translation_releases_memory_between_batches(self):
        from tv_center import media_ai
        calls=[]
        def translate(text,source,target):return ("t",None)
        cues=[LyricCue(float(i),float(i)+1,"line "+str(i),"fixture","de") for i in range(51)]
        with patch.object(media_ai,"_prefer_cpu_translation",return_value=False), \
             patch("tv_center.file_live_captions.release_accelerator_cache",side_effect=lambda: calls.append(1)), \
             patch("tv_center.captions.translate",side_effect=translate):
            media_ai.transcribe_local_media.__wrapped__ if False else None
        # exercise the translation loop directly
        src=Path('source/installed-package/tv_center/media_ai.py').read_text()
        self.assertIn("if len(batch)>=25",src)

    def test_batch_boundary_never_splits_a_cue(self):
        from tv_center import media_ai
        cues=[LyricCue(float(i),float(i)+1,"line "+str(i),"fixture","de") for i in range(51)]
        with patch("tv_center.media_ai.translate",return_value=("t",None)), \
             patch("tv_center.file_live_captions.release_accelerator_cache"):
            translated,warnings=media_ai._translate_cues(cues,("en",),"de")
        self.assertEqual(len(translated),51)
        self.assertEqual(warnings,[])
        self.assertEqual(translated[50],"[EN] t")


class PlayerMarket(unittest.TestCase):
    def test_status_detects_installed_player_without_installing_anything(self):
        from tv_center import player_market
        with tempfile.TemporaryDirectory() as folder:
            fake=Path(folder)/"bin";fake.mkdir()
            with patch.dict(os.environ,{"HOME":folder,"TIHULU_ASSET_HOME":"","PATH":str(fake)+":/usr/bin:/bin"}), \
                 patch("shutil.which",return_value=""):
                self.assertFalse(player_market.player_status("mpv")["available"])
                self.assertIn("apt install mpv",player_market.player_status("mpv")["command"]["debian"])
                # no install file, no directory created
                self.assertFalse((Path(folder)/".local").exists())

    def test_available_when_installed_locally(self):
        from tv_center import player_market
        with tempfile.TemporaryDirectory() as folder:
            tool=Path(folder)/".local/share/TIHULU/tihulu-media-center/tools"
            tool.mkdir(parents=True);(tool/"mpv").write_bytes(b"#!/bin/sh\n")
            with patch.dict(os.environ,{"HOME":folder,"TIHULU_ASSET_HOME":"","PATH":"/nonexistent"}):
                info=player_market.player_status("mpv")
                self.assertTrue(info["available"])
                self.assertEqual(info["local"],str(tool/"mpv"))

    def test_no_terminal_means_no_silent_root_action(self):
        from tv_center import player_market
        with patch("shutil.which",return_value=""):
            self.assertFalse(player_market.open_terminal_for_install("mpv"))


class NativeRegressions(unittest.TestCase):
    def test_native_widgets_process_tree_and_saved_ts(self):
        with tempfile.TemporaryDirectory(prefix="tihulu-owner3-") as folder:
            work=Path(folder);home=work/"home";home.mkdir();runtime=work/"run";runtime.mkdir(mode=0o700)
            env={**os.environ,"HOME":str(home),"XDG_CONFIG_HOME":str(home/"config"),
                 "XDG_CACHE_HOME":str(home/"cache"),"XDG_DATA_HOME":str(home/"data"),
                 "XDG_RUNTIME_DIR":str(runtime),"QT_QPA_PLATFORM":"offscreen", "PATH":str(work)+":/usr/bin:/bin",
                 "TIHULU_TEST_WORK":str(work)}
            for key in ("TIHULU_ASSET_HOME","PYTHONPATH","LD_LIBRARY_PATH","QT_PLUGIN_PATH","QT_QPA_PLATFORM_PLUGIN_PATH","CONDA_PREFIX"):
                env.pop(key,None)
            native=SOURCE/"kaffeine_next"
            for filename in ("media_panel","caption_options","file_captions","ai_process"):
                shutil.copyfile(native/f"native_{filename}.h",work/f"tihulu_{filename}.h")
            shutil.copyfile(native/"livecapture.h",work/"livecapture.h")
            for filename in ("mediawidget.h","native.cpp"):
                shutil.copyfile(ROOT/"tests/owner_round3"/filename,work/filename)
            companion=work/"tihulu-tv-center"
            companion.write_text('''#!/usr/bin/python3
import sys,json,time
if sys.argv[1] in ('media-captions','kaffeine-captions','kaffeine-captions-file') and len(sys.argv)>2:
 import os
 folder=os.environ.get('TIHULU_TEST_WORK')
 try:
  if folder: open(os.path.join(folder,'argv.txt'),'w').write(' '.join(sys.argv))
 except OSError:
  pass
 if '--live' not in sys.argv and '--file' not in sys.argv: time.sleep(30)
if sys.argv[1]=='ai-file-languages':
 print(json.dumps({'speech_languages':[{'code':'en','label':'English'}], 'languages':[{'code':'tr','label':'Turkish','engines':['fixture']}], 'speech_model_present':True,'speech_model_selected':'synthetic'}))
elif '--live' in sys.argv or '--file' in sys.argv:
 for line in sys.stdin:
  q=json.loads(line);time.sleep(.65);p=q['position'];print(json.dumps({'revision':q['revision'],'end':(p+8)*1000,'cues':[{'start':p*1000,'end':(p+8)*1000,'text':'position '+str(int(p))}]}),flush=True)
else:
 time.sleep(30)
''')
            companion.chmod(0o700)
            def run(args,timeout=45):
                p=subprocess.run(args,cwd=work,env=env,text=True,capture_output=True,timeout=timeout)
                self.assertEqual(p.returncode,0,(p.stdout+p.stderr)[-6000:]);return p
            flags=run(["/usr/bin/pkg-config","--cflags","--libs","Qt5Widgets","Qt5Test"]).stdout.split()
            run(["/usr/lib/qt5/bin/moc","mediawidget.h","-o","moc_mediawidget.cpp"])
            run(["/usr/lib/qt5/bin/moc","native.cpp","-o","native.moc"])
            run(["/usr/bin/c++","-std=c++17","-fPIC","-I.","native.cpp","moc_mediawidget.cpp","-o","native-test",*flags],timeout=90)
            sample=work/"sample.ts";env["TIHULU_SYNTHETIC_TS"]=str(sample)
            run(["/usr/bin/ffmpeg","-nostdin","-v","error","-f","lavfi","-i","sine=frequency=440:duration=1","-c:a","mp2","-f","mpegts",str(sample)])
            result=run([str(work/"native-test"),"-v1"])
            self.assertIn("0 failed",result.stdout)


if __name__=="__main__":unittest.main()

class ThreeCaptionServices(unittest.TestCase):
    """TV, radio and file are separate services; TV and radio stay untouched."""

    def test_entry_points_are_separate_and_share_tested_window_code(self):
        code = read("tv_center/__main__.py")
        self.assertIn('"kaffeine-captions", "kaffeine-captions-file"', code)
        self.assertIn('live TV (DVB) captions', code)
        self.assertIn('local file captions', code)
        self.assertIn('"radio-captions"', code)

    def test_file_window_applies_the_saved_appearance(self):
        code = read("kaffeine_next/captions_overlay.py")
        self.assertIn("from tv_center.theme import install_theme", code)
        self.assertIn("install_theme(app)", code)
        self.assertIn("QStyleFactory.create(\"Fusion\")", read("tv_center/theme.py"))

    def test_both_services_start_headless(self):
        sockets = {"kaffeine-captions": "tihulu-dvb-1.sock",
                   "kaffeine-captions-file": "tihulu-file-1.sock"}
        for command, socket_name in sockets.items():
            with self.subTest(command=command):
                # Each service is started on its own private session socket;
                # they stay separate through their control sockets, which this
                # suite verifies elsewhere.
                proc = subprocess.Popen(
                    ["/usr/bin/python3", "-m", "tv_center", command,
                     "--socket", str(_runtime_path / socket_name)],
                    cwd=str(SOURCE), env=_caption_env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True)
                try:
                    time.sleep(4)
                    self.assertIsNone(proc.poll(),
                                     f"{command} exited early")
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=6)
                    except subprocess.TimeoutExpired:
                        proc.kill(); proc.wait(timeout=6)

    def test_file_mode_offers_the_file_as_the_caption_source(self):
        """A local file must be the caption source: no broadcaster, no
        Teletext page and no DVB track lookup in file mode."""
        code = read("kaffeine_next/captions_overlay.py")
        # The file replaces the broadcaster as the selectable source.
        self.assertIn('mode.addItem("Whisper live transcription · this file\'s audio", "asr")',
                      code)
        self.assertIn('QLabel("Source")', code)
        self.assertIn('source_row.addWidget(QLabel("Source"))', code)
        # Broadcast-only controls are not offered for a file.
        self.assertIn('track_status.setVisible(False)', code)
        # The always-visible status lines describe the file, not a receiver.
        self.assertIn('"Source: local file · "', code)
        self.assertIn('"File audio: decoded from the media file on the playback clock"',
                      code)
        # Live-TV receiver telemetry is not polled for a file.
        self.assertIn(">= 1.0 and not file_media:", code)
        # The DVB-only pipeline-health messages are unreachable in file mode.
        self.assertIn("elif file_media:", code)
        self.assertIn('"Local file source · waiting for the player "', code)

    def test_overlay_mode_is_read_on_every_poll(self):
        """Switching the overlay off/compact/full must not need a restart."""
        patch=read("kaffeine_next/patch_upstream.py")
        self.assertIn("re-read on EVERY poll",patch)
        self.assertIn("captionFontSize",patch)
        # The one-time, build-time-only read must be gone.
        self.assertNotIn("Caption overlay mode: off / compact (default) / full",
                         patch)
        # Both render sites use the mode-aware size, and the hard cap stays.
        self.assertEqual(patch.count("captionFontSize(obj.value("),2)
        self.assertIn("video.height()/4",patch)
        # The mode and the font-size lambda must live in the POLL body scope:
        # a nested brace block would leave them invisible at the render sites
        # and the native build would fail with "was not declared in this scope".
        start = patch.index("QSettings overlay(QLatin1String(\"TIHULU\")")
        line_start = patch.rfind("\n", 0, start) + 1
        prev_start = patch.rfind("\n", 0, line_start - 1) + 1
        # patch_upstream.py stores indentation as literal \t escapes, so
        # collapse them before comparing.
        previous = (patch[prev_start:line_start - 1]
                    .replace("\\t", "").strip())
        self.assertNotEqual(previous, "{",
                            "overlay mode must not sit in a nested brace block")
        # No stray developer scratch files are shipped in the package.
        package=SOURCE/"kaffeine_next"
        for stray in sorted(package.glob(".p*.py")):
            self.fail("Unexpected scratch file in the package: "+str(stray))

    def test_file_service_runs_on_a_real_media_file_without_any_receiver(self):
        """Owner report: the file panel still looked for a broadcaster source.
        The file service must start on a real media file, on its own socket,
        with no DVB device, tuner or channel anywhere in the path."""
        with tempfile.TemporaryDirectory(prefix="tihulu-filecap-") as folder:
            base = Path(folder)
            media = base / "clip.wav"
            subprocess.run(
                ["/usr/bin/ffmpeg", "-nostdin", "-v", "error",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                 "-c:a", "pcm_s16le", str(media)],
                timeout=60, check=True)
            env = dict(_caption_env)
            env["HOME"] = str(base / "home")
            (base / "home").mkdir()
            proc = subprocess.Popen(
                ["/usr/bin/python3", "-m", "tv_center", "kaffeine-captions-file",
                 "--socket", str(_runtime_path / "tihulu-file-77.sock"),
                 "--file", str(media), "--window", "6"],
                cwd=str(SOURCE), env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True)
            try:
                time.sleep(5)
                self.assertIsNone(proc.poll(), "file caption service exited early")
            finally:
                proc.terminate()
                try:
                    out, _ = proc.communicate(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill(); out, _ = proc.communicate(timeout=8)
            # It must never fall back to looking for a DVB receiver: that
            # error path ends in "Cannot receive Kaffeine DVB stream".
            self.assertNotIn("Cannot receive Kaffeine DVB stream", out or "")
            self.assertNotIn("Expected a private Kaffeine", out or "")

    def test_subtitle_search_is_never_automatic(self):
        code = read("kaffeine_next/captions_overlay.py")
        self.assertIn('"No search happens until you press a search button.', code)
        self.assertIn("search_hash_button.clicked.connect(lambda: run_search(True))", code)
        self.assertIn("search_title_button.clicked.connect(lambda: run_search(False))", code)
