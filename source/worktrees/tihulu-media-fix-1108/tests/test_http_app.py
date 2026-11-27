import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from textcenter.core import Store
from textcenter.http_app import LocalServer, run_server


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.server=LocalServer(("127.0.0.1",0),Store(Path(self.tmp.name)/"app.db"))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def request(self,method,path,data=None,csrf=None,origin=None):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        headers={}
        body=None
        if data is not None:
            headers["Content-Type"]="application/json"
            body=json.dumps(data).encode()
        if csrf:
            headers["X-Tihulu-CSRF"]=csrf
        if origin:
            headers["Origin"]=origin
        conn.request(method,path,body=body,headers=headers)
        res=conn.getresponse()
        data=res.read()
        result=(res.status,dict(res.getheaders()),data)
        conn.close()
        return result

    def test_ui_and_local_navigation(self):
        code,headers,data=self.request("GET","/")
        self.assertEqual(code,200)
        self.assertIn(b"TIHULU TEXT CENTER",data)
        self.assertNotIn(b"RF adapters not connected",data)
        self.assertIn(b"USB status not checked",data)
        self.assertIn(b"RF text decoder inactive",data)
        self.assertEqual(headers["X-Content-Type-Options"],"nosniff")
        code,_,payload=self.request("GET","/api/page?number=100")
        result=json.loads(payload)
        self.assertEqual(result["kind"],"local_index")
        self.assertEqual(result["title"],"INDEX")
        self.assertEqual(self.request("GET","/api/page?number=999")[0],400)
        self.assertEqual(self.request("GET","/api/page?number=102")[0],404)
        self.assertEqual(self.request("GET","/../README.md")[0],404)

    def test_favicon_is_local_and_served(self):
        code,headers,payload=self.request("GET","/favicon.svg")
        self.assertEqual(code,200)
        self.assertEqual(headers["Content-Type"],"image/svg+xml; charset=utf-8")
        self.assertIn(b"<svg",payload)

    def test_receivers_endpoint_is_passive_and_honest(self):
        code,headers,raw=self.request("GET","/api/receivers")
        self.assertEqual(code,200)
        status=json.loads(raw)
        self.assertIn("rtl_usb_count",status)
        self.assertIn("decoders",status)
        self.assertFalse(status["active_capture"])
        self.assertFalse(status["signal_verified"])
        self.assertFalse(status["connected_decoder"])

    def test_rds_endpoint_fails_closed_without_real_decoder(self):
        status,_,raw=self.request("GET","/api/rds/status")
        self.assertEqual(status,200)
        data=json.loads(raw)
        self.assertEqual(data["status"],"idle")
        self.assertFalse(data["active"])
        self.assertIn("capability",data)
        _,_,bootstrap=self.request("GET","/api/bootstrap")
        csrf=json.loads(bootstrap)["csrf"]
        self.assertEqual(self.request("POST","/api/rds/start",
            {"frequency_mhz":100,"duration_seconds":20})[0],403)
        self.assertEqual(self.request("POST","/api/rds/start",
            {"frequency_mhz":999,"duration_seconds":20},csrf)[0],400)
        self.assertEqual(self.request("POST","/api/rds/start",
            {"frequency_mhz":98.6,"duration_seconds":20},csrf)[0],409)
        self.assertEqual(self.request("POST","/api/rds/stop",{},csrf)[0],200)

    def test_capability_catalog_route(self):
        code,_,raw=self.request("GET","/api/capabilities")
        self.assertEqual(code,200)
        parsed=json.loads(raw)
        self.assertTrue(any(x["id"]=="dab_journaline" for x in parsed))
        self.assertTrue(any(x["id"]=="meshtastic" for x in parsed))
        self.assertEqual(self.request("GET","/api/page?number=860")[0],200)

    def test_discovery_passive_does_not_claim_real_rf(self):
        code,_,data=self.request("GET","/api/discovery/passive")
        self.assertEqual(code,200)
        result=json.loads(data)
        self.assertEqual(result["kind"],"passive_local_inventory")
        self.assertIn("archive_counts",result)
        self.assertIn("receiver",result)
        self.assertIn("unavailable_or_deferred",result)
        code,_,data=self.request("GET","/api/fm-survey/status")
        self.assertEqual(code,200)
        status=json.loads(data)
        self.assertFalse(status["active"])
        self.assertEqual(status["kind"],"spectrum_candidate_not_station")
        _,_,raw=self.request("GET","/api/bootstrap")
        csrf=json.loads(raw)["csrf"]
        self.assertEqual(self.request("POST","/api/fm-survey/start",{})[0],403)
        # An absent rtl_power, missing USB or readsb conflict must not start RF.
        # This CI check can run on hosts with various installed binaries, so
        # inject a deterministic blocked condition rather than asserting hardware.
        self.server.survey.conflicts=lambda:[{"process":"readsb"}]
        self.assertEqual(self.request("POST","/api/fm-survey/start",{},csrf)[0],409)
        self.assertEqual(self.request("POST","/api/fm-survey/stop",{},csrf)[0],200)

    def test_each_scanner_route_denies_unsupported_bands_and_has_no_hidden_tuning(self):
        status,_,raw=self.request("GET","/api/scans")
        self.assertEqual(status,200)
        features=json.loads(raw)["features"]
        self.assertEqual(len(features),31)
        rows={x["id"]:x for x in features}
        self.assertEqual(rows["gemini"]["medium"],"internet_only")
        self.assertEqual(rows["dvb_teletext"]["scan_type"],"dvb_service_adapter_pending")
        self.assertEqual(rows["navtex"]["scan_type"],"rf_spectrum")
        self.assertFalse(rows["dvb_teletext"]["can_survey_now"])
        status,_,raw=self.request("GET","/api/scans/status")
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)["status"],"idle")
        _,_,boot=self.request("GET","/api/bootstrap")
        csrf=json.loads(boot)["csrf"]
        self.assertEqual(self.request("POST","/api/scans/start",{"band":"fm"})[0],403)
        self.assertEqual(self.request("POST","/api/scans/start",{"band":"internet"},csrf)[0],400)
        self.server.survey.conflicts=lambda: [{"process":"readsb"}]
        self.assertEqual(self.request("POST","/api/scans/start",{"band":"dab"},csrf)[0],409)
        self.assertEqual(self.request("POST","/api/scans/stop",{},csrf)[0],200)

    def test_audio_preview_routes_require_auth_and_fail_closed_when_busy(self):
        code,_,raw=self.request("GET","/api/audio/status")
        self.assertEqual(code,200)
        self.assertFalse(json.loads(raw)["clip_ready"])
        self.assertEqual(self.request("GET","/api/audio/clip.wav")[0],404)
        self.assertEqual(self.request("POST","/api/audio/start",{"frequency_mhz":98.6})[0],403)
        _,_,bootstrap=self.request("GET","/api/bootstrap")
        csrf=json.loads(bootstrap)["csrf"]
        self.assertEqual(self.request("POST","/api/audio/start",
            {"frequency_mhz":200.0,"duration_seconds":12},csrf)[0],400)
        self.server.audio.conflicts=lambda: [{"process":"readsb"}]
        self.assertEqual(self.request("POST","/api/audio/start",
            {"frequency_mhz":98.6,"duration_seconds":12},csrf)[0],409)
        self.assertEqual(self.request("POST","/api/audio/stop",{},csrf)[0],200)

    def test_media_and_dvb_inventory_are_honest(self):
        code,_,raw=self.request("GET","/api/dvb/status")
        self.assertEqual(code,200)
        data=json.loads(raw)
        self.assertFalse(data["broadcast_locked"])
        self.assertFalse(data["teletext_decoder_connected"])
        self.assertFalse(data["service_scan_enabled"])
        code,_,raw=self.request("GET","/api/media")
        self.assertEqual(code,200)
        self.assertEqual(json.loads(raw),[])
        self.assertEqual(self.request("GET","/api/media/file/garbage")[0],404)

    def test_dab_connector_never_starts_radio_without_explicit_request(self):
        code,_,raw=self.request("GET","/api/dab/last")
        self.assertEqual(code,200)
        self.assertFalse(json.loads(raw)["connected"])
        self.assertEqual(self.request("POST","/api/dab/refresh",{})[0],403)
        _,_,bootstrap=self.request("GET","/api/bootstrap")
        csrf=json.loads(bootstrap)["csrf"]
        self.assertEqual(self.request("POST","/api/dab/refresh",
             {"include_images":"yes"},csrf)[0],400)
        # A fake non-welle endpoint is refused; never claim a broadcast.
        self.server.dab.fetcher=lambda path,limit: b"11D" if path=="/channel" else b'{"services":[]}'
        self.assertEqual(self.request("POST","/api/dab/refresh",
             {"include_images":False},csrf)[0],409)
        self.assertFalse(self.server.dab_last["connected"])

    def test_live_radio_transcript_and_compute_routes(self):
        status,_,raw=self.request("GET","/api/compute")
        self.assertEqual(status,200)
        self.assertIn("npu",json.loads(raw)["selection"])
        status,_,raw=self.request("GET","/api/live/radio/status")
        self.assertEqual(status,200)
        self.assertFalse(json.loads(raw)["active"])
        self.assertEqual(self.request("GET",
            "/api/live/radio/stream?session=none&token=bad")[0],403)
        self.assertEqual(self.request("POST","/api/live/radio/start",{})[0],403)
        _,_,raw=self.request("GET","/api/bootstrap")
        csrf=json.loads(raw)["csrf"]
        self.assertEqual(self.request("POST","/api/live/radio/start",
            {"frequency_mhz":440},csrf)[0],400)
        self.server.live_fm.conflicts=lambda:[{"process":"readsb"}]
        self.assertEqual(self.request("POST","/api/live/radio/start",
            {"frequency_mhz":98.6},csrf)[0],409)
        self.assertEqual(self.request("POST","/api/live/radio/stop",{},csrf)[0],200)
        self.assertEqual(json.loads(self.request("GET","/api/transcripts")[2]),[])
        self.assertEqual(self.request("GET","/api/transcripts/export?session=bad")[0],400)

    def test_tv_relay_requires_configured_protected_source(self):
        code,_,raw=self.request("GET","/api/live/tv/channels")
        self.assertEqual(code,200)
        self.assertFalse(json.loads(raw)["capability"]["ready"])
        code,_,raw=self.request("GET","/api/live/tv/status")
        self.assertEqual(code,200)
        self.assertFalse(json.loads(raw)["active"])
        self.assertEqual(self.request("GET",
            "/api/live/tv/stream?session=bad&token=bad")[0],403)
        self.assertEqual(self.request("POST","/api/live/tv/start",{})[0],403)
        _,_,raw=self.request("GET","/api/bootstrap")
        csrf=json.loads(raw)["csrf"]
        self.assertEqual(self.request("POST","/api/live/tv/start",
            {"channel_id":"none","upstream_authorized":False},csrf)[0],409)
        self.assertEqual(self.request("POST","/api/live/tv/stop",{},csrf)[0],200)

    def test_local_media_permissions_allow_video_audio_but_not_cross_origin(self):
        code, headers, body=self.request("GET","/")
        self.assertEqual(code,200)
        policy=dict(headers).get("Content-Security-Policy","")
        self.assertIn("media-src 'self'",policy)
        self.assertIn("connect-src 'self'",policy)
        self.assertIn("default-src 'none'",policy)

    def test_recording_postprocess_needs_saved_file_and_valid_language(self):
        status,_,raw=self.request("GET","/api/recordings/transcription/status")
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)["status"],"idle")
        self.assertEqual(self.request("POST","/api/recordings/transcription/start",
            {"medium":"fm","filename":"missing.mp3","original_language":"de"})[0],403)
        _,_,boot=self.request("GET","/api/bootstrap")
        csrf=json.loads(boot)["csrf"]
        self.assertEqual(self.request("POST","/api/recordings/transcription/start",
            {"medium":"fm","filename":"../secret.mp3","original_language":"de"},csrf)[0],409)
        self.assertEqual(self.request("POST","/api/recordings/transcription/start",
            {"medium":"dvb_tv","filename":"x.mp4","original_language":"zz"},csrf)[0],400)
        self.assertEqual(self.request("POST","/api/recordings/transcription/stop",{},csrf)[0],200)

    def test_offline_translator_api_fail_closed(self):
        code,_,raw=self.request("GET","/api/translation/status")
        self.assertEqual(code,200)
        self.assertIn("pairs",json.loads(raw))
        self.assertEqual(self.request("POST","/api/translation/text",{})[0],403)
        _,_,raw=self.request("GET","/api/bootstrap")
        csrf=json.loads(raw)["csrf"]
        self.assertEqual(self.request("POST","/api/translation/text",
            {"text":"Hello","source":"en","target":"zz"},csrf)[0],400)
        self.assertEqual(self.request("POST","/api/translation/text",
            {"text":"Hello","source":"en","target":"de","backend":"npu"},csrf)[0],409)
        self.assertEqual(self.request("POST","/api/translation/text",
            {"text":"Hello","source":"en","target":"en"},csrf)[0],200)

    def test_no_forged_source(self):
        code,_,raw=self.request("GET","/api/page?source_id=ard_text&number=100")
        self.assertEqual(code,404)
        self.assertIn(b"No imported page",raw)
        code,_,raw=self.request("GET","/api/bootstrap")
        self.assertEqual(code,200)
        self.assertEqual(json.loads(raw)["radio_receiver"],"not_connected")

    def test_csrf_and_same_origin_for_local_post(self):
        _,_,raw=self.request("GET","/api/bootstrap")
        csrf=json.loads(raw)["csrf"]
        post={"title":"Test","body":"Body","author":"Local"}
        self.assertEqual(self.request("POST","/api/bulletins",post)[0],403)
        bad="http://evil.example"
        self.assertEqual(self.request("POST","/api/bulletins",post,csrf,origin=bad)[0],403)
        right="http://127.0.0.1:"+str(self.server.server_port)
        self.assertEqual(self.request("POST","/api/bulletins",post,csrf,origin=right)[0],201)
        code,_,raw=self.request("GET","/api/bulletins")
        self.assertEqual(code,200)
        self.assertEqual(json.loads(raw)[0]["title"],"Test")

    def test_feed_registration_without_auto_fetch(self):
        _,_,raw=self.request("GET","/api/bootstrap")
        csrf=json.loads(raw)["csrf"]
        code,_,data=self.request("POST","/api/feeds/add",
            {"title":"Local feed","url":"https://example.org/rss"},csrf)
        self.assertEqual(code,201)
        code,_,data=self.request("GET","/api/feeds")
        self.assertEqual(len(json.loads(data)),1)
        self.assertIsNone(json.loads(data)[0]["last_fetched"])

    def test_server_will_not_bind_lan(self):
        with self.assertRaises(ValueError):
            run_server(Store(Path(self.tmp.name)/"another.db"),host="0.0.0.0",port=0)


if __name__=="__main__":
    unittest.main()
