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
if sys.argv[1] in ('media-captions','kaffeine-captions') and len(sys.argv)>2:
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
