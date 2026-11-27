"""Paired phone playback routing, real buffered captions and security.

Tests use an existing virtual TV service and fake FFmpeg; no USB, DRM, or
Internet services are contacted. The UI must never pretend to mirror a desktop.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from kaffeine_next.mobile import KaffeineMobile
from tv_center.lan import MobileLAN
from tv_center.remote_hub import RemoteHub, create_handler


def opts():
    return {"mode":"asr","page":150}


class PairedTvClockTests(unittest.TestCase):
    def test_bounded_caption_history_respects_verified_native_delay(self):
        phone=KaffeineMobile(opts,lambda _:None)
        now=time.monotonic()
        config=SimpleNamespace(playback_delay_ms=15000,offset_ms=-1250)
        native={"requested_ms":15000,"effective_ms":12000,"primed":True}
        for i in range(26):
            cue={"due":now+13+i,"expires":now+17+i}
            clip={"original":"A real sentence number "+str(i),
                  "translations":{"tr":"Doğrulanmış çeviri "+str(i)},
                  "source":"local_asr","source_language":"en",
                  "captured_start":now-6,"captured_end":now,
                  "decoded_at":now+0.6}
            phone.set_caption(clip,cue,config,native)
        state=phone.snapshot()
        self.assertEqual(len(state["caption_events"]),24)
        self.assertEqual(state["caption_events"][-1]["caption"]["sequence"],26)
        self.assertEqual(state["caption_timing"]["host_effective_buffer_ms"],12000)
        self.assertEqual(state["caption_timing"]["host_requested_buffer_ms"],15000)
        self.assertTrue(state["caption_timing"]["host_buffer_verified"])
        self.assertEqual(state["caption_timing"]["host_caption_offset_ms"],-1250)
        self.assertLess(abs(state["caption_timing"]["capture_end_epoch_ms"]-time.time()*1000),2000)
        self.assertIn("caption_events",state)
        self.assertIn("server_epoch_ms",state)

    def test_unverified_buffer_is_not_reported_as_applied_and_stop_clears(self):
        phone=KaffeineMobile(opts,lambda _:None)
        config=SimpleNamespace(playback_delay_ms=15000,offset_ms=0)
        phone.set_caption({"original":"Hallo"},cue={"due":time.monotonic()+2},
            config=config,native_state={"requested_ms":15000,"effective_ms":1000,
                                        "primed":False})
        self.assertIsNone(phone.snapshot()["caption_timing"]["host_effective_buffer_ms"])
        self.assertFalse(phone.snapshot()["caption_timing"]["host_buffer_verified"])
        phone.set_caption({"original":"","source":"channel_changed"})
        self.assertEqual(phone.snapshot()["caption_events"],[])

    def test_native_caption_controls_are_queued_and_validate_limits(self):
        requests=[]
        phone=KaffeineMobile(opts,lambda _:None,
             gui_commands=lambda action,params:requests.append((action,params)))
        for action,params in (
            ("set_desktop_caption_mode",{"mode":"asr"}),
            ("set_desktop_caption_offset",{"offset_ms":-2500}),
            ("set_desktop_tv_buffer",{"buffer_ms":15000}),
            ("desktop_subtitles_running",{"running":False}),
        ):
            response=phone.remote_command(action,params)
            self.assertTrue(response["queued"])
        self.assertEqual(len(requests),4)
        with self.assertRaises(ValueError):
            phone.remote_command("set_desktop_caption_mode",{"mode":"root"})
        with self.assertRaises(ValueError):
            phone.remote_command("set_desktop_caption_offset",{"offset_ms":99999})
        with self.assertRaises(ValueError):
            phone.remote_command("set_desktop_tv_buffer",{"buffer_ms":-1})
        with self.assertRaises(ValueError):
            phone.remote_command("desktop_subtitles_running",{"running":"false"})
        self.assertEqual(len(requests),4)
        from kaffeine_next import captions_overlay
        import inspect
        ui=inspect.getsource(captions_overlay.main)
        self.assertIn('elif kind == "remote_gui_command":',ui)
        self.assertIn('mode.findData(params["mode"])',ui)
        self.assertIn('playback_delay.setValue(params["buffer_ms"]/1000)',ui)
        self.assertIn('set_subtitles_running(params["running"])',ui)

    def test_remote_source_and_device_routing_not_tuner_duplicate(self):
        phone=KaffeineMobile(opts,lambda _:None)
        self.assertEqual(phone.remote_command("player_target",{"target":"host"})["target"],"host")
        self.assertEqual(phone.snapshot()["playback_target"],"host")
        self.assertFalse(phone.snapshot()["mobile_video"])
        with self.assertRaisesRegex(ValueError,"Target"):
            phone.remote_command("player_target",{"target":"internet"})
        with self.assertRaises(RuntimeError):
            phone.remote_command("scan_start",{"country":"DE"})
        with self.assertRaises(RuntimeError):
            phone.remote_command("video",{"enabled":True})
        self.assertIn("captions",[
            item["id"] for item in phone.remote_command("sources",{})["items"]])


class PairedLanSecurityTests(unittest.TestCase):
    def test_pair_disconnect_really_revokes_server_cookie(self):
        lan=MobileLAN(lambda:{"source":"offline"},lambda _:None,lambda:None,port=0)
        lan.start()
        url="http://127.0.0.1:"+str(lan.httpd.server_port)
        def post(endpoint,data,cookie="",origin=None):
            h={"Content-Type":"application/json"}
            if cookie:h["Cookie"]=cookie
            if origin:h["Origin"]=origin
            return Request(url+endpoint,data=json.dumps(data).encode(),
                           headers=h,method="POST")
        try:
            with self.assertRaises(HTTPError) as unauth:
                urlopen(url+"/api/status",timeout=3)
            self.assertEqual(unauth.exception.code,401)
            with urlopen(post("/api/pair",{"pin":lan.pin},
                                  origin=url),timeout=3) as r:
                cookie=r.headers["Set-Cookie"].split(";",1)[0]
            with urlopen(Request(url+"/api/status",headers={"Cookie":cookie}),
                         timeout=3) as r:
                self.assertEqual(r.status,200)
            with urlopen(post("/api/disconnect",{},cookie,origin=url),
                         timeout=3) as r:
                self.assertTrue(json.loads(r.read())["disconnected"])
                self.assertIn("Max-Age=0",r.headers["Set-Cookie"])
            with self.assertRaises(HTTPError) as revoked:
                urlopen(Request(url+"/api/status",headers={"Cookie":cookie}),timeout=3)
            self.assertEqual(revoked.exception.code,401)
        finally:
            lan.stop()

    def test_https_reverse_proxy_same_host_is_accepted_not_foreign(self):
        lan=MobileLAN(lambda:{"hello":"world"},lambda _:None,lambda:None,port=0)
        lan.start()
        host="127.0.0.1:"+str(lan.httpd.server_port)
        url="http://"+host
        def request(origin):
            return Request(url+"/api/pair",
                           data=json.dumps({"pin":lan.pin}).encode(),
                           headers={"Content-Type":"application/json",
                                    "Origin":origin},method="POST")
        try:
            with self.assertRaises(HTTPError) as foreign:
                urlopen(request("https://attacker.invalid"),timeout=3)
            self.assertEqual(foreign.exception.code,403)
            with urlopen(request("https://"+host),timeout=3) as accepted:
                self.assertTrue(json.loads(accepted.read())["paired"])
        finally:
            lan.stop()


class PairedHubTests(unittest.TestCase):
    def test_approved_image_sniffing_and_no_symlink_exfiltration(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/"art.png").write_bytes(b"\x89PNG\r\n\x1a\n"+b"PNGbytes")
            (path/"fake.jpg").write_bytes(b"not-image")
            (path/"sound.mp3").write_bytes(b"radio")
            hub=RemoteHub(path)
            try:
                images={v.name:k for k,v in hub.files.items()}
                data,kind=hub.read_approved_picture(images["art.png"])
                self.assertEqual(kind,"image/png")
                self.assertEqual(data[:8],b"\x89PNG\r\n\x1a\n")
                with self.assertRaises(ValueError):
                    hub.read_approved_picture(images["fake.jpg"])
                with self.assertRaises(ValueError):
                    hub.read_approved_picture(images["sound.mp3"])
            finally:hub.close()

    def test_images_require_hub_pairing_cookie_and_reject_bad_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/"slide.png").write_bytes(b"\x89PNG\r\n\x1a\n"+b"image")
            hub=RemoteHub(root)
            server=ThreadingHTTPServer(("127.0.0.1",0),create_handler(hub))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base="http://127.0.0.1:"+str(server.server_port)
            identifier=next(iter(hub.files))
            from urllib.parse import quote
            path="/api/image?id="+quote(identifier)
            try:
                with self.assertRaises(HTTPError) as missing:
                    urlopen(base+path,timeout=3)
                self.assertEqual(missing.exception.code,401)
                pair=Request(base+"/api/pair",
                    data=json.dumps({"pin":hub.pin}).encode(),
                    headers={"Content-Type":"application/json"},method="POST")
                with urlopen(pair,timeout=3) as result:
                    cookie=result.headers["Set-Cookie"].split(";",1)[0]
                with urlopen(Request(base+path,headers={"Cookie":cookie}),
                             timeout=3) as picture:
                    self.assertEqual(picture.status,200)
                    self.assertEqual(picture.headers["Content-Type"],"image/png")
                    self.assertTrue(picture.read().startswith(b"\x89PNG"))
                with self.assertRaises(HTTPError) as fake:
                    urlopen(Request(base+"/api/image?id=not-found",
                                    headers={"Cookie":cookie}),timeout=3)
                self.assertEqual(fake.exception.code,404)
            finally:
                server.shutdown();server.server_close()
                thread.join(timeout=4);hub.close()

    def test_host_only_does_not_terminate_other_phone_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/"song.mp3").write_bytes(b"audio")
            hub=RemoteHub(root)
            try:
                file_id=next(iter(hub.files))
                current=mock.Mock()
                current.poll.return_value=None
                hub.proc=current
                hub.current_source="remote-song"
                hub.serial=4
                with mock.patch.object(hub,"play_local",return_value=True):
                    result=hub.start("file",file_id,target="host")
                self.assertTrue(result["remote_stream_unchanged"])
                self.assertEqual(result["target"],"host")
                self.assertEqual(hub.serial,4)
                self.assertFalse(current.terminate.called)
                self.assertEqual(hub.current_source,"remote-song")
            finally:hub.close()

    def test_mobile_and_hub_web_have_fullscreen_real_media_not_fake_screen(self):
        root=Path(__file__).resolve().parents[1]/"tv_center/web"
        phone=(root/"mobile.js").read_text()
        hub=(root/"hub.js").read_text()
        for source in (phone,hub):
            self.assertIn("requestFullscreen",source)
            self.assertIn("VTTCue",source)
            self.assertIn("video",source.lower())
        self.assertIn("host_caption_due_epoch_ms",phone)
        self.assertIn("hlsLagEstimateMs()",phone)
        self.assertIn('"/api/slide?sid="',hub)
        self.assertIn('"/api/image?id="',hub)
        self.assertIn('target:$("target").value',hub)


if __name__=="__main__":unittest.main()
