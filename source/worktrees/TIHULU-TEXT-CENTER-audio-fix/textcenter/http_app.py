"""Local HTTP application. No WAN listener, no CORS and no decoder/transmitter."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .core import Store, safe_https_url
from .receivers import receiver_inventory
from .fm_rds import FMRSDSupervisor, CaptureError
from .fm_audio import FMPreview, AudioError
from .media import MediaStore
from .dvb_hardware import diagnose_dvb
from .dab_bridge import DABReader,DABError
from .capabilities import capability_catalog
from .fm_survey import FMSurveySupervisor, SurveyError
from .scan_catalog import scan_capabilities

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

DIRECTORY = [
    {"name": "ARD Text", "category": "Teletext on the web", "url": "https://www.ard-text.de/", "note": "Publisher website, internet only; not antenna reception."},
    {"name": "TRT TELEGÜN", "category": "Teletext information", "url": "https://www.trt.net.tr/corporate/teletext", "note": "Publisher information; no Turkish broadcast reception claimed."},
    {"name": "Teletext Art", "category": "Teletext-style community", "url": "https://teletextart.co.uk/teletext-links", "note": "External web directory; community sites have their own permissions."},
    {"name": "LK0NOD", "category": "Packet/BBS community", "url": "https://www.lk0nod.de/lk0nod-hilfe-online.html", "note": "Public information; no radio TX or BBS gateway built in."},
    {"name": "Gemini protocol", "category": "Text-first internet", "url": "https://geminiprotocol.net/", "note": "Information about Gemini; a dedicated Gemini client is not bundled."},
    {"name": "Gopher", "category": "Text-first internet", "url": "https://gopher.floodgap.com/", "note": "Browser-accessible introductory directory; native Gopher client not bundled."},
]

INDEX_PAGES = {
    100: ("INDEX", "Browse local content, source-attributed RF imports, offline notes and opt-in internet feeds."),
    200: ("HEADLINES", "Cached RSS/Atom articles. Refresh only when requested."),
    300: ("WEATHER", "Weather text must be received from a genuine source; no synthetic forecast is displayed."),
    400: ("RADIO DATA", "FM RDS, DAB DLS, Journaline, NAVTEX and others require separately installed, tested decoders."),
    500: ("EMERGENCY", "Imported RF text is not an authenticated official alert. Use verified emergency sources."),
    600: ("LOCAL BOARD", "Offline bulletin board on loopback. No multi-user login and no radio transmission."),
    700: ("LIBRARY", "Stored articles, bookmarks and previously imported pages remain on this device."),
    800: ("NETWORKS", "Web directories for Teletext, blogs, BBS, Gemini and Gopher."),
    850: ("ABOUT", "Standalone service with on-demand workers and no default polling or RF receiver."),
    860: ("PROTOCOLS", "See the complete requested protocol and service coverage, dependencies and readiness."),
}

class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store: Store):
        self.store = store
        self.media = MediaStore(store)
        self.dab = DABReader(store)
        self.dab_last = {"connected":False,"message":"No welle-cli web receiver checked yet"}
        self.csrf_token = secrets.token_urlsafe(32)
        self.rds = FMRSDSupervisor(store)
        self.survey = FMSurveySupervisor(
            rds=self.rds, lock_dir=store.filename.parent / ".receiver-locks"
        )
        self.audio = FMPreview(
            rds=self.rds, survey=self.survey,
            lock_dir=store.filename.parent / ".receiver-locks"
        )
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: LocalServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Local diagnostic only; do not log bulletin contents or feed payloads.
        super().log_message(format, *args)

    def _send(self, status: int, body: bytes, content_type: str, *, cache: str = "no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.close_connection = True
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; media-src 'self'; connect-src 'self'; form-action 'self'; "
                         "base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        parsed = urlsplit(self.path)
        route = parsed.path
        q = parse_qs(parsed.query, keep_blank_values=True)
        try:
            if route in ("/", "/index.html", "/assets/app.js", "/assets/styles.css", "/favicon.svg"):
                mapping = {"/": "index.html", "/index.html": "index.html",
                           "/assets/app.js": "app.js", "/assets/styles.css": "styles.css",
                           "/favicon.svg": "favicon.svg"}
                data = (WEB_DIR / mapping[route]).read_bytes()
                kind = ("image/svg+xml" if route == "/favicon.svg"
                        else "text/html" if route in ("/", "/index.html")
                        else "text/javascript" if route.endswith(".js") else "text/css")
                return self._send(200, data, kind + "; charset=utf-8", cache="no-cache")
            if route == "/api/bootstrap":
                return self._json(200, {
                    "version": __version__, "mode": "local_offline_first",
                    "csrf": self.server.csrf_token,
                    "counts": self.server.store.counts(),
                    "background_refresh": False,
                    "radio_receiver": ("fm_rds_capture_running"
                                       if self.server.rds.status(heartbeat=False)["active"]
                                       else "not_connected"),
                    "fm_spectrum_survey": ("running"
                                           if self.server.survey.status(heartbeat=False)["active"]
                                           else "inactive"),
                    "dvb_receiver": "not_connected",
                    "warning": "FM decoder and survey are opt-in only; no authenticated emergency feed is bundled."
                })
            if route == "/api/receivers":
                inventory = receiver_inventory()
                rds_state = self.server.rds.status(heartbeat=False)
                survey_state = self.server.survey.status(heartbeat=False)
                inventory["fm_survey_active"] = survey_state["active"]
                inventory["fm_candidate_count"] = len(survey_state["candidates"])
                inventory["rds_capture_active"] = rds_state["active"]
                inventory["rds_groups_decoded"] = rds_state["received_groups"] if rds_state["active"] else 0
                inventory["fm_audio_active"] = self.server.audio.status()["active"]
                inventory["active_capture"] = rds_state["active"] or survey_state["active"] or inventory["fm_audio_active"]
                inventory["connected_decoder"] = bool(
                    rds_state["active"] and rds_state["received_groups"] > 0
                )
                # RDS JSON decoding is not calibrated RF signal-strength measurement.
                inventory["signal_verified"] = False
                return self._json(200, inventory)
            if route == "/api/discovery/passive":
                inventory = receiver_inventory()
                catalog = capability_catalog(inventory)
                return self._json(200, {
                    "kind":"passive_local_inventory",
                    "receiver":inventory,
                    "archive_counts":self.server.store.counts(),
                    "features_total":len(catalog),
                    "software_ready":[x["title"] for x in catalog
                                      if x["state"] in ("implemented","single_owner_only")],
                    "unavailable_or_deferred":[
                        {"title":x["title"],"state":x["state"],"requirements":x["requirements"]}
                        for x in catalog
                        if x["state"] not in ("implemented","single_owner_only","manual_capture")
                    ],
                    "note":"No tuner accessed, no frequencies retuned, no internet fetched, no RF reception claimed",
                })
            if route == "/api/scans":
                return self._json(200, {
                    "features": scan_capabilities(receiver_inventory(), self.server.survey),
                    "survey": self.server.survey.status(heartbeat=False),
                    "warning": "Antenna scanning only finds RF energy; it cannot fetch Internet pages, identify decoded services or bypass receiver leases",
                })
            if route == "/api/scans/status":
                current = self.server.survey.status()
                current["capability"] = self.server.survey.availability(current.get("band", "fm"))
                return self._json(200, current)
            if route == "/api/fm-survey/status":
                status = self.server.survey.status()
                status["capability"] = self.server.survey.availability()
                return self._json(200, status)
            if route == "/api/dab/last":
                return self._json(200,self.server.dab_last)
            if route == "/api/dvb/status":
                return self._json(200,diagnose_dvb())
            if route == "/api/media":
                return self._json(200,self.server.media.list())
            if route.startswith("/api/media/file/"):
                identity=route[len("/api/media/file/"):]
                file=self.server.media.get(identity)
                if not file:
                    return self._json(404, {"error":"No such decoded broadcast image"})
                mime, raw=file
                return self._send(200,raw,mime)
            if route == "/api/audio/status":
                state=self.server.audio.status()
                state["capability"]=self.server.audio.availability()
                return self._json(200,state)
            if route == "/api/audio/clip.wav":
                # If a session token is supplied, bind the request to that
                # specific in-memory capture. A stale browser player must
                # never silently play a newer recording instead.
                requested=q.get("session")
                state=self.server.audio.status()
                if requested is not None and (
                    len(requested)!=1 or requested[0]!=state.get("session")
                ):
                    return self._json(404, {"error":"FM audio session is no longer available"})
                data=self.server.audio.wav_clip()
                if data is None:
                    return self._json(404, {"error":"No completed FM audio preview"})
                return self._send(200, data, "audio/wav")
            if route == "/api/rds/status":
                status = self.server.rds.status()
                status["capability"] = self.server.rds.availability()
                return self._json(200, status)
            if route == "/api/capabilities":
                return self._json(200, capability_catalog(receiver_inventory()))
            if route == "/api/index":
                return self._json(200, [{"page": k, "title": v[0], "description": v[1]} for k,v in INDEX_PAGES.items()])
            if route == "/api/page":
                try:
                    page = int(q.get("number", ["100"])[0])
                    subpage = int(q.get("subpage", ["0"])[0])
                except ValueError:
                    raise ValueError("Page/subpage must be numbers")
                if not (100 <= page <= 899 and 0 <= subpage <= 99):
                    raise ValueError("Page outside supported 100–899 range")
                source = q.get("source_id", [""])[0][:90]
                if source:
                    data = self.server.store.page(source, page, subpage)
                    if not data:
                        return self._json(404, {"error": "No imported page with this source/number/subpage"})
                    return self._json(200, {"kind": "broadcast", **data, "source_status": "decoder_imported_not_authority_verified"})
                if page not in INDEX_PAGES:
                    return self._json(404, {"error": "Page not present in local index; select an imported source if available"})
                return self._json(200, {"kind": "local_index", "page": page, "subpage": 0,
                                        "title": INDEX_PAGES[page][0], "body": INDEX_PAGES[page][1]})
            if route == "/api/pages":
                return self._json(200, self.server.store.pages(q.get("source_id", [""])[0][:90] or None))
            if route == "/api/events":
                return self._json(200, self.server.store.events())
            if route == "/api/articles":
                return self._json(200, self.server.store.articles(q.get("q", [""])[0]))
            if route == "/api/feeds":
                return self._json(200, self.server.store.feeds())
            if route == "/api/bulletins":
                return self._json(200, self.server.store.bulletins())
            if route == "/api/bookmarks":
                return self._json(200, self.server.store.bookmarks())
            if route == "/api/directory":
                return self._json(200, DIRECTORY)
            return self._json(404, {"error": "Not found"})
        except (ValueError, TypeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "Internal error. See local server logs."})

    def do_POST(self):
        route = urlsplit(self.path).path
        allowed = {"/api/feeds/add", "/api/feeds/refresh", "/api/bulletins", "/api/bookmarks", "/api/rds/start", "/api/rds/stop", "/api/fm-survey/start", "/api/fm-survey/stop", "/api/scans/start", "/api/scans/stop", "/api/audio/start", "/api/audio/stop", "/api/dab/refresh"}
        if route not in allowed:
            return self._json(404, {"error": "Not found"})
        if self.headers.get("X-Tihulu-CSRF") != self.server.csrf_token:
            return self._json(403, {"error": "Missing or invalid local write token"})
        # Reject browser cross-site POSTs; same-origin JS provides an Origin header.
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            return self._json(403, {"error": "Origin mismatch"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json(400, {"error": "Invalid length"})
        if not 0 < length <= 16_384 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._json(413, {"error": "Require bounded application/json body"})
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object")
            if route == "/api/scans/start":
                return self._json(202, self.server.survey.start(payload.get("band")))
            if route == "/api/scans/stop":
                return self._json(200, self.server.survey.stop())
            if route == "/api/fm-survey/start":
                return self._json(202, self.server.survey.start())
            if route == "/api/fm-survey/stop":
                return self._json(200, self.server.survey.stop())
            if route == "/api/dab/refresh":
                if type(payload.get("include_images",True)) is not bool:
                    raise ValueError("Invalid DAB image option")
                result=self.server.dab.refresh(include_images=payload.get("include_images",True))
                self.server.dab_last={"connected":True,**result}
                return self._json(200,self.server.dab_last)
            if route == "/api/audio/start":
                return self._json(202,self.server.audio.start(
                    payload.get("frequency_mhz"),payload.get("duration_seconds",12)))
            if route == "/api/audio/stop":
                return self._json(200,self.server.audio.stop())
            if route == "/api/rds/start":
                return self._json(202, self.server.rds.start(
                    frequency_mhz=payload.get("frequency_mhz"),
                    duration=payload.get("duration_seconds"),
                    rds2_images=payload.get("rds2_images",False),
                ))
            if route == "/api/rds/stop":
                return self._json(200, self.server.rds.stop())
            if route == "/api/feeds/add":
                fid = self.server.store.add_feed(payload.get("title"), payload.get("url"))
                return self._json(201, {"id": fid})
            if route == "/api/feeds/refresh":
                fid = payload.get("id")
                if not isinstance(fid, str) or len(fid) > 100:
                    raise ValueError("Invalid feed ID")
                count = self.server.store.refresh_feed(fid)
                return self._json(200, {"imported": count})
            if route == "/api/bulletins":
                bid = self.server.store.add_bulletin(payload.get("title"),payload.get("body"),payload.get("author"))
                return self._json(201, {"id": bid})
            if route == "/api/bookmarks":
                self.server.store.add_bookmark(payload.get("label"),payload.get("target_type"),payload.get("target"))
                return self._json(201, {"saved": True})
        except (CaptureError, SurveyError, AudioError, DABError) as exc:
            self._json(409, {"error": str(exc)})
        except KeyError as exc:
            self._json(404, {"error": str(exc)})
        except (ValueError, TypeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(502, {"error": "Feed request or local operation failed; no live data assumed."})


def run_server(store: Store, *, host: str = "127.0.0.1", port: int = 8787):
    if host != "127.0.0.1":
        raise ValueError("This standalone service is loopback-only")
    server = LocalServer((host, port), store)
    print(f"TIHULU TEXT CENTER v{__version__}: http://{host}:{server.server_port}/")
    print("Local mode. Background polling OFF. No receiver capture active at startup.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.audio.stop(wait=True)
        server.survey.stop(wait=True)
        server.rds.stop(wait=True)
        server.server_close()
