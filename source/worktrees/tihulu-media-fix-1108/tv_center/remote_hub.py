"""Opt-in paired remote media hub. No DVB/SDR device ownership, no Internet bind.

This first server slice exposes a PIN-protected browser, shared host-encoded
HLS for user-approved local files and verified local welle DAB services,
and optional MPRIS control of the existing TIHULU player. It does NOT
re-broadcast DVD, unshared DVB-TS, all desktop windows or arbitrary files.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from urllib.request import urlopen

MEDIA_EXTS=frozenset({".mkv",".mp4",".webm",".mov",".avi",".ts",
                      ".mp3",".flac",".wav",".m4a",".ogg",".opus",".aac"})
IMAGE_EXTS=frozenset({".png",".jpg",".jpeg",".webp"})
STATIC_REMOTE={"":("hub.html","text/html; charset=utf-8"),
               "hub.js":("hub.js","text/javascript; charset=utf-8"),
               "style.css":("style.css","text/css; charset=utf-8")}
MPRIS_DEST="org.mpris.MediaPlayer2.tihulu_media_center"
# Pinned KDE Kaffeine v2.0.19 uses MPRIS 1, NOT MPRIS 2.
# Its native Qt DBus objects are /Player, /TrackList and /Television.
MPRIS_INTERFACE="org.freedesktop.MediaPlayer"
MPRIS_PLAYER_PATH="/Player"
MPRIS_TRACKLIST_PATH="/TrackList"
MPRIS_TV_PATH="/Television"

# Paired web assets live in the same tested web folder, with no inline
# script or automatic third-party HTTP requests.
PAGE = (Path(__file__).resolve().parent / "web" / "hub.html").read_text(encoding="utf-8")


class RemoteHub:
    def __init__(self,media_root,*,welle_port=None,caption_pid=None,
                 native_pid=None):
        self.root=Path(media_root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Media root must be a directory")
        self.welle_port=welle_port
        self.native_pid=native_pid
        if native_pid is not None and (type(native_pid)!=int or
                not 1<=native_pid<=999999999):
            raise ValueError("Invalid local native player PID")
        if welle_port is not None and (type(welle_port)!=int or not 1024<=welle_port<=65535):
            raise ValueError("Invalid local welle port")
        self.caption_pid=caption_pid if caption_pid is not None else native_pid
        self.pin=f"{secrets.randbelow(100000000):08d}"
        self.sessions={}
        self.failures={}
        self.lock=threading.RLock()
        self.proc=None
        self.started=time.monotonic()
        self.serial=0
        self.current_source="none"
        self.current_kind="none"
        self.current_identifier=None
        self.current_target="phone"
        self.last_host_command="none"
        self.cache=Path(tempfile.mkdtemp(prefix="tihulu-remote-hls-"))
        os.chmod(self.cache,0o700)
        self.files=self._catalog()

    def _catalog(self):
        found={}
        for p in self.root.rglob("*"):
            if len(found)>=500: break
            if not p.is_file() or p.is_symlink() or p.suffix.lower() not in (MEDIA_EXTS | IMAGE_EXTS):
                continue
            if self.root not in p.resolve().parents:
                continue
            token=hashlib.sha256(str(p.relative_to(self.root)).encode()).hexdigest()[:20]
            found[token]=p
        return found

    def active_welle_port(self):
        if self.welle_port:return self.welle_port
        if self.native_pid is None:return None
        runtime=Path(os.environ.get("XDG_RUNTIME_DIR",""))
        if not runtime.is_absolute() or not runtime.is_dir():
            return None
        file=runtime/f"tihulu-welle-{self.native_pid}.port"
        try:
            if file.is_symlink() or file.stat().st_uid!=os.getuid() or (
                    file.stat().st_size>8):
                return None
            number=int(file.read_text().strip())
            return number if 1024<=number<=65535 else None
        except (OSError,ValueError):
            return None

    def dab_services(self):
        port=self.active_welle_port()
        if port is None:return []
        try:
            with urlopen(f"http://127.0.0.1:{port}/mux.json",timeout=2) as r:
                data=json.loads(r.read(250000))
        except (OSError,ValueError,TimeoutError):
            return []
        services=[]
        import re
        for entry in data.get("services",[]):
            if not isinstance(entry,dict):continue
            sid=entry.get("sid","")
            stream=entry.get("url_mp3","")
            if (isinstance(sid,str) and isinstance(stream,str) and
                    re.fullmatch(r"(?:0x)?[A-Fa-f0-9]{1,8}",sid) and
                    re.fullmatch(r"/mp3/[A-Fa-f0-9x]+",stream)):
                label=entry.get("label")
                name=label.get("label") if isinstance(label,dict) else label
                services.append({"sid":sid,"url":stream,
                                 "name":str(name or sid)[:90]})
        return services[:100]

    def read_approved_picture(self, identifier):
        """Return ONLY bytes of a previously cataloged, non-symlink image."""
        path=self.files.get(identifier)
        if (not isinstance(identifier,str) or path is None
                or path.is_symlink() or not path.is_file()
                or path.suffix.lower() not in IMAGE_EXTS
                or self.root not in path.resolve().parents
                or path.stat().st_size > 8*1024*1024):
            raise ValueError("No approved image available for this identifier")
        data=path.read_bytes()
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return data,"image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return data,"image/jpeg"
        if data.startswith(b"RIFF") and data[8:12]==b"WEBP":
            return data,"image/webp"
        raise ValueError("Image data failed strict content sniffing")

    def read_dab_slide(self, sid):
        """Verify receiver-reported DAB service before fetching its real slide."""
        entry=next((item for item in self.dab_services()
                    if item["sid"]==sid),None)
        if entry is None:
            raise ValueError("DAB slideshow service is not present in live mux")
        import re
        if not isinstance(sid,str) or not re.fullmatch(
                r"(?:0x)?[A-Fa-f0-9]{1,8}",sid):
            raise ValueError("Invalid service")
        port=self.active_welle_port()
        if port is None:
            raise RuntimeError("Native DAB receiver is offline")
        try:
            with urlopen(f"http://127.0.0.1:{port}/slide/{sid}",timeout=2) as output:
                data=output.read(3*1024*1024+1)
        except (OSError,TimeoutError) as exc:
            raise RuntimeError("Native DAB slideshow unavailable") from exc
        if len(data)>3*1024*1024:
            raise ValueError("DAB slide exceeds safety size")
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return data,"image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return data,"image/jpeg"
        raise ValueError("Receiver did not provide a PNG/JPEG slide")

    def play_local(self,url):
        if shutil.which("dbus-send") is None:
            return False
        args=["dbus-send","--session","--print-reply","--reply-timeout=2000",
              "--dest="+MPRIS_DEST,MPRIS_TRACKLIST_PATH,
              MPRIS_INTERFACE+".AddTrack","string:"+url,"boolean:true"]
        try:
            done=subprocess.run(args,stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                timeout=3,check=False)
            return done.returncode==0
        except (OSError,subprocess.TimeoutExpired):
            return False

    def control(self,action,*,channel=None,value=None):
        known={"PlayPause":"Pause","Play":"Play","Pause":"Pause",
               "Stop":"Stop","Next":"Next","Previous":"Prev",
               "VolumeSet":"VolumeSet","TVChannel":"PlayChannel"}
        if action not in known:
            raise ValueError("Invalid native MPRIS control action")
        if shutil.which("dbus-send") is None:
            raise RuntimeError("DBus tools not installed")
        is_tv=action=="TVChannel"
        if is_tv:
            if not isinstance(channel,str) or not 0<len(channel.strip())<=90 or (
                    any(ord(c)<32 for c in channel)):
                raise ValueError("Enter valid native TV channel name or number")
        if action=="VolumeSet":
            if type(value)!=int or not 0<=value<=100:
                raise ValueError("Native volume must be integer 0–100")
        args=["dbus-send","--session","--print-reply","--reply-timeout=2000",
              "--dest="+MPRIS_DEST,
              MPRIS_TV_PATH if is_tv else MPRIS_PLAYER_PATH,
              MPRIS_INTERFACE+"."+known[action]]
        if is_tv:args+=["string:"+channel.strip()]
        elif action=="VolumeSet":args+=["int32:"+str(value)]
        try:
            run=subprocess.run(args,stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                timeout=3,check=False)
        except (OSError,subprocess.TimeoutExpired):
            raise RuntimeError("Native Kaffeine DBus command unavailable")
        if run.returncode:
            raise RuntimeError("Native TIHULU DBus command failed. "
                               "Is the standalone player running on this login?")

    def start(self,kind,identifier,host=False,target=None):
        # Backwards-compatible host boolean, now explicit device selection.
        if target is None:
            target = "both" if host else "phone"
        if target not in ("phone","host","both"):
            raise ValueError("Playback target must be phone, host, or both")
        if kind not in ("file","dab"):
            raise ValueError("Select a real approved media file or verified DAB service")
        if target!="host" and shutil.which("ffmpeg") is None:
            raise RuntimeError("FFmpeg not installed on host")
        if kind=="file":
            path=self.files.get(identifier)
            if path is None or path.is_symlink() or not path.is_file() or (
                    self.root not in path.resolve().parents):
                raise ValueError("File not in explicitly shared media catalog")
            if path.suffix.lower() not in MEDIA_EXTS:
                raise ValueError("Shared pictures use the authenticated image viewer")
            source=str(path)
            host_source=path.as_uri()
        elif kind=="dab":
            entry=next((e for e in self.dab_services() if e["sid"]==identifier),None)
            if entry is None:
                raise ValueError("DAB service not present in live mux; cannot stream")
            source=f"http://127.0.0.1:{self.active_welle_port()}"+entry["url"]
            host_source=source
        else:
            raise ValueError("Unsupported source type")
        if target=="host":
            if not self.play_local(host_source):
                raise RuntimeError("Host-only playback could not reach native TIHULU MPRIS")
            self.last_host_command="Play approved "+kind+" on computer"
            return {"serial":self.serial,"status":"Host-only player command accepted",
                    "target":"host","remote_stream_unchanged":True,
                    "note":"Other paired phones are not disconnected"}
        with self.lock:
            self.stop()
            self.serial+=1
            for child in self.cache.iterdir():
                if child.is_file() and child.name.startswith(("stream.","seg_")):
                    child.unlink()
            args=["ffmpeg","-nostdin","-hide_banner","-loglevel","error"]
            if kind=="file":args+=["-re"]
            args+=["-i",source,"-map","0:v:0?","-map","0:a:0?",
                   "-c:v","libx264","-preset","veryfast",
                   "-pix_fmt","yuv420p","-c:a","aac","-b:a","128k",
                   "-f","hls","-hls_time","4","-hls_list_size","8",
                   "-hls_flags","delete_segments+independent_segments",
                   "-hls_segment_filename",str(self.cache/"seg_%06d.ts"),
                   str(self.cache/"stream.m3u8")]
            self.proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.current_source=(str(path.relative_to(self.root)) if kind=="file"
                                 else "DAB "+identifier)
            self.current_kind=kind
            self.current_identifier=identifier
            self.current_target=target
            on_host=self.play_local(host_source) if target=="both" else False
            self.last_host_command=("Play approved "+kind+" on computer"
                                    if on_host else "none")
            return {"serial":self.serial,"status":"HLS source starting on host",
                    "target":target, "host_play_requested":on_host,
                    "note":("Host playback command was unavailable; phone HLS may still play"
                            if target=="both" and not on_host else
                            "Host playback is unchanged" if target=="phone"
                            else "Phone and host playback requested")}

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc=None
        self.current_source="none"
        self.current_kind="none"
        self.current_identifier=None

    def status(self):
        with self.lock:
            state=("idle" if self.proc is None else
                   "encoding on host" if self.proc.poll() is None else
                   "encoder exited (check source or FFmpeg codecs)")
            return {"state":state,"source":self.current_source,
                    "source_kind":self.current_kind,
                    "source_id":self.current_identifier,
                    "playback_target":self.current_target,
                    "serial":self.serial,
                    "server_epoch_ms":round(time.time()*1000),
                    "playlist_ready":(self.cache/"stream.m3u8").is_file(),
                    "capabilities":{
                      "paired_media_files":True,
                      "verified_dab":self.active_welle_port() is not None,
                      "approved_images":True,
                      "native_host_controls":True,
                      "live_dvb_rebroadcast":False,
                      "arbitrary_desktop_mirroring":False,
                      "protected_video_capture":False},
                    "sync_note":("Host TV/radio buffering and remote HLS have "
                        "independent presentation clocks. Live DAB caption sync "
                        "is approximate until PTS correlation is available.")}

    def captions(self):
        if self.caption_pid is None:return {}
        path=Path(os.environ.get("XDG_RUNTIME_DIR",""))/(
            f"tihulu-radio-captions-{self.caption_pid}.json")
        try:
            if path.is_symlink() or path.stat().st_uid!=os.getuid() or (
                    path.stat().st_size>15000):return {}
            data=json.loads(path.read_text(encoding="utf-8"))
            original=str(data.get("original",""))[:800]
            translations=data.get("translations",{})
            if not isinstance(translations,dict):translations={}
            kind="live_radio_asr"
            # A verified lyric may use a different language from the live
            # presenter, so use only high-confidence ASR/lyric matches and
            # the translations generated for THAT matched lyric.
            observed=data.get("lyric_match")
            lyric_translations=data.get("lyric_translations")
            if (isinstance(observed,dict) and
                    observed.get("kind")=="observed_ASR_chunk_match" and
                    isinstance(observed.get("confidence"),(float,int)) and
                    observed["confidence"]>=0.74 and
                    isinstance(lyric_translations,dict) and
                    lyric_translations):
                original=str(observed.get("text") or original)[:800]
                translations=lyric_translations
                kind="verified_dab_lyric"
            text="\n".join([original]+[
                "["+str(k)[:5]+"] "+str(v)[:800]
                for k,v in list(translations.items())[:5]])
            return {"text":text[:3000],
                    "original":original,
                    "content_type":kind,
                    "translations":{str(k)[:8]:str(v)[:800]
                                    for k,v in list(translations.items())[:5]
                                    if isinstance(v,str)},
                    "source_language":str(data.get("source_language") or "und")[:12],
                    "timestamp":data.get("timestamp"),
                    "source_capture_epoch_ms":data.get("source_capture_epoch_ms"),
                    "host_audio_cache_ms":data.get("host_audio_cache_ms"),
                    "host_caption_offset_ms":data.get("host_caption_offset_ms"),
                    "chunk_index":data.get("chunk_index"),
                    "sync_note":"Radio captions follow host ASR and audio-buffer estimates; not PTS-calibrated."}
        except (OSError,ValueError,TypeError):
            return {}

    def close(self):
        with self.lock:
            self.stop()
            shutil.rmtree(self.cache,ignore_errors=True)


def create_handler(hub):
    class Handler(BaseHTTPRequestHandler):
        server_version="TIHULU-Hub/0.1"
        def log_message(self,fmt,*args):
            # Do not log raw PIN, cookie or token-bearing URLs.
            pass
        def send_data(self,code,payload,mime="application/json",headers=None):
            raw=(json.dumps(payload,ensure_ascii=False).encode("utf-8")
                 if mime=="application/json" else payload)
            self.send_response(code)
            self.send_header("Content-Type",mime)
            self.send_header("Content-Length",str(len(raw)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Referrer-Policy","no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
                             "style-src 'self'; media-src 'self' blob:; "
                             "img-src 'self' blob: data:; connect-src 'self'; "
                             "frame-ancestors 'none'; base-uri 'none'")
            if headers:
                for k,v in headers.items():self.send_header(k,v)
            self.end_headers()
            self.wfile.write(raw)
        def session(self):
            jar=SimpleCookie()
            try:jar.load(self.headers.get("Cookie",""))
            except Exception:return None
            item=jar.get("tihulu_session")
            if not item:return None
            token=item.value
            with hub.lock:
                current=hub.sessions.get(token)
            return current if current and current["expires"]>time.time() else None
        def require(self,csrf=False):
            session=self.session()
            if not session:
                self.send_data(401,{"error":"Pair with host PIN first"})
                return None
            if csrf and not hmac.compare_digest(
                self.headers.get("X-CSRF-Token",""),session["csrf"]):
                self.send_data(403,{"error":"Bad CSRF token"})
                return None
            return session
        def do_GET(self):
            path=urlsplit(self.path).path
            asset=STATIC_REMOTE.get(path.lstrip("/"))
            if asset is not None:
                filename,mime=asset
                source=Path(__file__).resolve().parent/"web"/filename
                if not source.is_file() or source.is_symlink():
                    return self.send_data(404,{"error":"Web UI component missing"})
                self.send_data(200,source.read_bytes(),mime)
                return
            if not self.require():return
            if path=="/api/catalog":
                items=[{"id":k,"name":str(v.relative_to(hub.root))[:240],
                        "kind":"image" if v.suffix.lower() in IMAGE_EXTS else "file"}
                       for k,v in hub.files.items()]
                self.send_data(200,{"items":items})
            elif path=="/api/dab":
                self.send_data(200,{"items":[{"sid":e["sid"],"name":e["name"]}
                    for e in hub.dab_services()]})
            elif path=="/api/captions":
                self.send_data(200,hub.captions())
            elif path=="/api/image":
                query=parse_qs(urlsplit(self.path).query)
                try:
                    identifier=query.get("id",[None])[0]
                    raw,kind=hub.read_approved_picture(identifier)
                    self.send_data(200,raw,kind)
                except (ValueError,OSError):
                    self.send_data(404,{"error":"Approved image unavailable"})
            elif path=="/api/slide":
                query=parse_qs(urlsplit(self.path).query)
                try:
                    identifier=query.get("sid",[None])[0]
                    raw,kind=hub.read_dab_slide(identifier)
                    self.send_data(200,raw,kind)
                except (ValueError,OSError,RuntimeError):
                    self.send_data(404,{"error":"Live DAB slide unavailable"})
            elif path=="/api/status":
                self.send_data(200,hub.status())
            elif path.startswith("/hls/"):
                name=path.removeprefix("/hls/")
                if not (name=="stream.m3u8" or
                        __import__("re").fullmatch(r"seg_\d{6}\.ts",name)):
                    self.send_data(404,{"error":"Unknown stream object"})
                    return
                file=hub.cache/name
                if not file.is_file() or file.is_symlink():
                    self.send_data(404,{"error":"HLS not ready or segment rotated"})
                    return
                data=file.read_bytes()
                if len(data)>8*1024*1024:
                    self.send_data(413,{"error":"Segment too large"});return
                mime=("application/vnd.apple.mpegurl" if name.endswith(".m3u8")
                      else "video/mp2t")
                self.send_data(200,data,mime)
            else:
                self.send_data(404,{"error":"Unknown route"})
        def do_POST(self):
            length=int(self.headers.get("Content-Length","0") or 0)
            if not 0<length<2500:
                self.send_data(413,{"error":"Invalid request size"});return
            source=self.headers.get("Origin")
            if source and urlsplit(source).netloc!=self.headers.get("Host"):
                self.send_data(403,{"error":"Cross-site request refused"});return
            try:payload=json.loads(self.rfile.read(length))
            except (ValueError,TypeError):
                self.send_data(400,{"error":"Invalid JSON"});return
            if not isinstance(payload,dict):
                self.send_data(400,{"error":"Expected object"});return
            path=urlsplit(self.path).path
            if path=="/api/pair":
                remote=self.client_address[0]
                now=time.monotonic()
                with hub.lock:
                    recent=[x for x in hub.failures.get(remote,[]) if now-x<600]
                    if len(recent)>=5:
                        self.send_data(429,{"error":"Too many pairing attempts"});return
                    if not isinstance(payload.get("pin"),str) or not hmac.compare_digest(
                            payload["pin"],hub.pin):
                        recent.append(now)
                        hub.failures[remote]=recent
                        self.send_data(403,{"error":"Incorrect PIN"});return
                    hub.failures.pop(remote,None)
                    token=secrets.token_urlsafe(32)
                    session={"csrf":secrets.token_urlsafe(24),
                             "expires":time.time()+8*3600}
                    hub.sessions[token]=session
                self.send_data(200,{"csrf":session["csrf"]},headers={
                    "Set-Cookie":"tihulu_session="+token+
                    "; Path=/; HttpOnly; SameSite=Strict"})
                return
            if not self.require(csrf=True):return
            if path=="/api/disconnect":
                jar=SimpleCookie()
                try:
                    jar.load(self.headers.get("Cookie",""))
                    ticket=jar["tihulu_session"].value
                except (ValueError,KeyError):
                    ticket=None
                if ticket:
                    with hub.lock:
                        hub.sessions.pop(ticket,None)
                self.send_data(200,{"disconnected":True},headers={
                    "Set-Cookie":"tihulu_session=; Path=/; HttpOnly; "
                                 "SameSite=Strict; Max-Age=0"})
                return
            try:
                if path=="/api/start":
                    result=hub.start(payload.get("kind"),payload.get("id"),
                        payload.get("host") is True,target=payload.get("target"))
                    self.send_data(200,result)
                elif path=="/api/stop":
                    with hub.lock:hub.stop()
                    self.send_data(200,{"status":"remote stopped"})
                elif path=="/api/control":
                    hub.control(payload.get("action"),
                                channel=payload.get("channel"),value=payload.get("value"))
                    self.send_data(200,{"status":"sent to native MPRIS player"})
                else:self.send_data(404,{"error":"Unknown route"})
            except (RuntimeError,ValueError,OSError) as exc:
                self.send_data(400,{"error":str(exc)[:180]})
    return Handler


def main(argv=None):
    parser=argparse.ArgumentParser(description="Opt-in local paired TIHULU media hub")
    parser.add_argument("--media-root",default=str(Path.home()/"Videos"),
                        help="Explicit directory to share; no arbitrary client paths")
    parser.add_argument("--bind",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8788)
    parser.add_argument("--welle-port",type=int,default=None,
                        help="Already-running local welle port (does NOT own SDR)")
    parser.add_argument("--native-pid",type=int,default=None,
                        help="Existing TIHULU native app PID for attached DAB/AI (no USB access)")
    parser.add_argument("--caption-pid",type=int,default=None,
                        help="Explicit app PID to share radio AI caption JSON")
    parser.add_argument("--unsafe-lan",action="store_true",
                        help="EXPERT: bind without TLS; use HTTPS reverse proxy instead")
    args=parser.parse_args(argv)
    if not 1024<=args.port<=65535:parser.error("Port out of range")
    if args.bind not in ("127.0.0.1","::1","localhost") and not args.unsafe_lan:
        parser.error("Non-loopback bind requires --unsafe-lan; prefer Tailscale HTTPS Serve")
    hub=RemoteHub(args.media_root,welle_port=args.welle_port,
                  caption_pid=args.caption_pid,native_pid=args.native_pid)
    server=ThreadingHTTPServer((args.bind,args.port),create_handler(hub))
    print(f"TIHULU Remote Hub: http://{args.bind}:{args.port}",flush=True)
    print("Pairing PIN (host terminal only): "+hub.pin,flush=True)
    print("Only user-approved media folder and VERIFIED local DAB; "
          "no DVB tuner stealing, no universal TV/DVD mirroring.",flush=True)
    try:server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:pass
    finally:
        server.server_close()
        hub.close()
    return 0

if __name__=="__main__":
    raise SystemExit(main())
