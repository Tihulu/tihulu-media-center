"""Opt-in authenticated loopback caption and Teletext control for the Pages client.

Never listens on LAN, never owns the tuner, never provides a general proxy.
Cross-origin access is restricted to TIHULU GitHub Pages with a session token.
"""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading

ORIGIN = "https://tihulu.github.io"

class TVBridge:
    def __init__(self, snapshot, change_page, host="127.0.0.1", port=8768, commands=None):
        if host != "127.0.0.1":
            raise ValueError("Bridge is loopback only; no unauthenticated LAN service")
        self.token = secrets.token_urlsafe(32)
        self.snapshot = snapshot
        self.change_page = change_page
        self.commands = commands
        self.host, self.port = host, port
        self.httpd = None
        self.thread = None

    def start(self):
        bridge = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                # Do not log requests or private subtitle text.
                return

            def cors(self):
                if self.headers.get("Origin") == ORIGIN:
                    self.send_header("Access-Control-Allow-Origin", ORIGIN)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Private-Network", "true")

            def reply(self, code, obj):
                b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def authorized(self):
                return secrets.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + bridge.token
                )

            def do_OPTIONS(self):
                self.send_response(204)
                self.cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                if self.path not in ("/api/status", "/api/channels", "/api/scan", "/api/models"):
                    return self.reply(404, {"error": "Unknown route"})
                if not self.authorized():
                    return self.reply(401, {"error": "Session token required"})
                if self.path == "/api/status":
                    return self.reply(200, bridge.snapshot())
                if not bridge.commands:
                    return self.reply(503, {"error": "Native web controller unavailable"})
                action={"/api/channels":"channels","/api/scan":"scan_status",
                        "/api/models":"models"}[self.path]
                try: return self.reply(200, bridge.commands(action,{}))
                except (RuntimeError,TimeoutError,ValueError) as exc:
                    return self.reply(503, {"error": str(exc)[:250]})

            def do_POST(self):
                if self.path not in ("/api/teletext","/api/command"):
                    return self.reply(404, {"error": "Unknown route"})
                if not self.authorized():
                    return self.reply(401, {"error": "Session token required"})
                size = self.headers.get("Content-Length", "")
                if not size.isdigit() or not 0 < int(size) <= 512:
                    return self.reply(413, {"error": "Invalid request length"})
                try:
                    data = json.loads(self.rfile.read(int(size)))
                    if self.path == "/api/command":
                        if not bridge.commands:
                            return self.reply(503, {"error":"Native web controller unavailable"})
                        action,params=data.get("action"),data.get("params",{})
                        if not isinstance(action,str) or not isinstance(params,dict):
                            raise ValueError("Expected action and params")
                        result=bridge.commands(action,params)
                        return self.reply(200,{"ok":True,"result":result})
                    page=data["page"]
                    if type(page) is not int or not 100 <= page <= 899:
                        raise ValueError("Invalid page")
                    bridge.change_page(page)
                except (ValueError,TypeError,KeyError,UnicodeError) as exc:
                    return self.reply(400, {"error": "Invalid command or page: "+str(exc)[:120]})
                except (RuntimeError,TimeoutError) as exc:
                    return self.reply(503, {"error": str(exc)[:250]})
                return self.reply(200, {"page": page, "status": "requested"})

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       name="tihulu-tv-bridge", daemon=True)
        self.thread.start()
        return {"url": f"http://{self.host}:{self.port}/api/status", "token": self.token}

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None
