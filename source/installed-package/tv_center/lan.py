"""Optional PIN-paired, LAN-only mobile web UI and HLS endpoint.

Not exposed unless explicitly enabled by the desktop owner.
No cloud, open proxy, automatic remote tuning, or anonymous live-TV API.
Use only on trusted LAN; HTTP traffic is not encrypted. HTTPS reverse proxy
(e.g. Tailscale Serve) is required for any untrusted network.
"""
from __future__ import annotations
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import json
import mimetypes
import re
import secrets
import socket
import threading
import time

MIME = {".m3u8": "application/vnd.apple.mpegurl", ".ts": "video/mp2t",
        ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8"}
STATIC = {"": "mobile.html", "mobile.html": "mobile.html",
          "mobile.js": "mobile.js", "web-controls.js": "web-controls.js",
          "style.css": "style.css"}

def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            ip = sock.getsockname()[0]
            return ip if ip != "0.0.0.0" else "127.0.0.1"
    except OSError:
        return "127.0.0.1"

class MobileLAN:
    def __init__(self, snapshot, change_page, stream_dir, port=8769, commands=None):
        self.snapshot = snapshot
        self.change_page = change_page
        self.stream_dir = stream_dir
        self.commands = commands
        self.port = port
        self.pin = f"{secrets.randbelow(1000000):06d}"
        self.clients = {}
        self.attempts = {}
        self.httpd = None
        self.thread = None
        self.lock = threading.Lock()

    def session_token(self, header):
        cookie=SimpleCookie()
        try:
            cookie.load(header)
            return cookie["tihulu_tv"].value
        except (KeyError,ValueError):
            return None

    def revoke(self, header):
        token=self.session_token(header)
        with self.lock:
            if token is not None:
                self.clients.pop(token,None)

    def authorized(self, header):
        cookie = SimpleCookie()
        try:
            cookie.load(header)
            ticket = cookie["tihulu_tv"].value
        except (KeyError, ValueError):
            return False
        with self.lock:
            expiry = self.clients.get(ticket, 0)
        return bool(expiry > time.monotonic())

    def accept_pin(self, ip, supplied):
        now = time.monotonic()
        with self.lock:
            history = [t for t in self.attempts.get(ip, []) if now-t < 180]
            if len(history) >= 5:
                self.attempts[ip] = history
                return None, "Too many attempts: retry in 3 minutes"
            if not isinstance(supplied, str) or not re.fullmatch(r"\d{6}", supplied):
                self.attempts[ip] = history + [now]
                return None, "Enter the six-digit code displayed on the host"
            if not secrets.compare_digest(supplied, self.pin):
                self.attempts[ip] = history + [now]
                return None, "Pairing code is incorrect"
            self.attempts.pop(ip, None)
            ticket = secrets.token_urlsafe(32)
            self.clients[ticket] = now+3600
            return ticket, None

    def start(self):
        owner = self
        root = (Path(__file__).resolve().parent / "web").resolve()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def headers_safe(self):
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy",
                    "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
                    "script-src 'self' https://cdn.jsdelivr.net; style-src 'self'; "
                    "media-src 'self' blob:; worker-src 'self' blob:; base-uri 'none'; "
                    "frame-ancestors 'none'")

            def reply(self, status, data, cookie=None):
                raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.headers_safe()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                if cookie is not None:
                    suffix=("; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
                            if cookie=="" else
                            "; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600")
                    self.send_header("Set-Cookie", "tihulu_tv=" + cookie + suffix)
                self.end_headers()
                self.wfile.write(raw)

            def allowed(self):
                return owner.authorized(self.headers.get("Cookie", ""))

            def send_file(self, path, kind, range_ok=False):
                if not path.is_file() or not path.stat().st_size <= 20 * 1024 * 1024:
                    return self.reply(404, {"error": "No stream segment currently available"})
                size = path.stat().st_size
                begin, end = 0, size - 1
                partial = False
                header = self.headers.get("Range", "") if range_ok else ""
                if header:
                    found = re.fullmatch(r"bytes=(\d+)-(\d*)", header)
                    if not found:
                        return self.reply(416, {"error": "Unsupported byte range"})
                    begin = int(found.group(1))
                    end = min(int(found.group(2)), size - 1) if found.group(2) else size - 1
                    if begin > end or begin >= size:
                        return self.reply(416, {"error": "Range outside file"})
                    partial = True
                self.send_response(206 if partial else 200)
                self.headers_safe()
                self.send_header("Content-Type", kind)
                self.send_header("Accept-Ranges", "bytes")
                if partial:
                    self.send_header("Content-Range", f"bytes {begin}-{end}/{size}")
                self.send_header("Content-Length", str(end - begin + 1))
                self.end_headers()
                with path.open("rb") as f:
                    f.seek(begin)
                    remaining = end - begin + 1
                    while remaining > 0:
                        chunk = f.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)

            def do_GET(self):
                url = urlsplit(self.path).path
                if url in ("/api/status", "/api/channels", "/api/scan", "/api/models"):
                    if not self.allowed():
                        return self.reply(401, {"error": "Pair with the host first"})
                    if url == "/api/status":
                        return self.reply(200, owner.snapshot())
                    if not owner.commands:
                        return self.reply(503, {"error": "Native web controls unavailable"})
                    action={"/api/channels":"channels","/api/scan":"scan_status",
                            "/api/models":"models"}[url]
                    try: return self.reply(200, owner.commands(action,{}))
                    except (RuntimeError,ValueError,TimeoutError) as exc:
                        return self.reply(503, {"error": str(exc)[:250]})
                if url == "/api/capabilities":
                    return self.reply(200, {"pairing_required": True,
                        "mobile_source": "native_host_dvb", "pin_required": True,
                        "video": "HLS if enabled on host", "platform": "linux_only_in_preview"})
                if url.startswith("/hls/"):
                    if not self.allowed():
                        return self.reply(401, {"error": "Pairing required"})
                    name = url[5:]
                    if not (name == "index.m3u8" or re.fullmatch(r"segment_\d{6}\.ts", name)):
                        return self.reply(404, {"error": "No such media file"})
                    folder = owner.stream_dir()
                    if folder is None:
                        return self.reply(404, {"error": "HLS streaming is off"})
                    suffix = Path(name).suffix
                    return self.send_file(Path(folder) / name, MIME[suffix], range_ok=True)
                name = url.lstrip("/")
                if name not in STATIC:
                    return self.reply(404, {"error": "No such path"})
                filename = STATIC[name]
                return self.send_file(root / filename, MIME[Path(filename).suffix])

            def do_POST(self):
                url = urlsplit(self.path).path
                if url not in ("/api/pair", "/api/teletext", "/api/command", "/api/disconnect"):
                    return self.reply(404, {"error": "No such route"})
                # Same-origin browser requests only, for protection against
                # drive-by form submission and cross-site reading.
                origin = self.headers.get("Origin", "")
                host = self.headers.get("Host", "")
                # HTTPS private reverse proxies legitimately send an HTTPS
                # Origin to this localhost HTTP server. Compare the hostname
                # and port, rather than demanding the external HTTP scheme.
                if origin:
                    request_origin=urlsplit(origin)
                    if (request_origin.scheme not in ("http","https") or
                            request_origin.netloc != host):
                        return self.reply(403, {"error":"Cross-origin request blocked"})
                length = self.headers.get("Content-Length", "")
                if not length.isdigit() or not 0 < int(length) <= 512:
                    return self.reply(400, {"error": "Invalid request length"})
                try:
                    body = json.loads(self.rfile.read(int(length)))
                except (ValueError, UnicodeError):
                    return self.reply(400, {"error": "Expected JSON"})
                if url == "/api/pair":
                    ticket, err = owner.accept_pin(self.client_address[0], body.get("pin"))
                    if err:
                        return self.reply(429 if "Too many" in err else 403, {"error": err})
                    return self.reply(200, {"paired": True}, ticket)
                if not self.allowed():
                    return self.reply(401, {"error": "Pair before changing Teletext"})
                if url == "/api/disconnect":
                    owner.revoke(self.headers.get("Cookie",""))
                    return self.reply(200, {"disconnected":True}, "")
                if url == "/api/command":
                    if not owner.commands:
                        return self.reply(503, {"error": "Native TV control unavailable"})
                    action,params=body.get("action"),body.get("params",{})
                    if not isinstance(action,str) or not isinstance(params,dict):
                        return self.reply(400, {"error": "Expected action and params"})
                    try: return self.reply(200, {"ok":True,
                        "result":owner.commands(action,params)})
                    except (RuntimeError,ValueError,TimeoutError,KeyError) as exc:
                        return self.reply(422, {"error": str(exc)[:250]})
                page = body.get("page")
                if type(page) is not int or not (100 <= page <= 899):
                    return self.reply(400, {"error": "Page must be integer 100–899"})
                try: owner.change_page(page)
                except (RuntimeError,ValueError,TimeoutError) as exc:
                    return self.reply(503, {"error": str(exc)[:250]})
                return self.reply(200, {"page": page})

        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True, name="tihulu-tv-mobile-lan")
        self.thread.start()
        return {"url": f"http://{lan_ip()}:{self.port}/", "pin": self.pin}

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None
        with self.lock:
            self.clients.clear()
            self.attempts.clear()
