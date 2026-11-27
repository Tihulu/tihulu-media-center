"""Continuous user-controlled local FM radio stream, optionally recorded.

This connects REAL rtl_fm PCM to ffmpeg MP3; the browser consumes an HTTP
audio/mpeg stream. No synthetic audio or Internet stations. One receiver,
one listener, explicit start/stop. Readsb/dump1090 and other known SDR
owners are protected by conservative checks and a cooperative lock.
A browser heartbeat is required; leaving the page stops capture.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
import uuid

from .conflicts import find_receiver_conflicts
from .fm_audio import audio_argv
from .fm_rds import validate_request
from .receivers import receiver_inventory
from .compute import detect_devices
from .speech import SpeechPipeline,SpeechError
from .transcripts import TranscriptStore

MAX_RECORD_BYTES = 1_073_741_824  # 1 GiB, recording stops, never fills storage
SESSION_TIMEOUT = 18
LOCK_NAME = "rtl_fm_rds.lock"


class LiveError(RuntimeError):
    pass


def encode_argv(ffmpeg: str) -> list[str]:
    return [ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "s16le", "-ar", "32000", "-ac", "1", "-i", "pipe:0",
            "-vn", "-codec:a", "libmp3lame", "-b:a", "96k",
            "-f", "mp3", "pipe:1"]


class LiveFM:
    def __init__(self, *, archive_dir:Path, inventory=None, lookup=None,
                 conflicts=None, lock_dir:Path|None=None,
                 timeout:float=SESSION_TIMEOUT, transcripts:TranscriptStore|None=None):
        self.transcripts=transcripts
        self.speech=None
        self.archive=Path(archive_dir)
        self.lock_dir=lock_dir or (self.archive.parent/".receiver-locks")
        self.inventory=inventory or receiver_inventory
        self.lookup=lookup or shutil.which
        self.conflicts=conflicts or find_receiver_conflicts
        self.timeout=timeout
        self.mutex=threading.RLock()
        self.stop_flag=threading.Event()
        self.listener=False
        self.receiver=None
        self.encoder=None
        self.worker=None
        self.watchdog=None
        self.lock_fd=None
        self.last_seen=0.0
        self.record_file=None
        self.state={
            "active":False,"status":"idle","session":None,"frequency_hz":None,
            "started_at":None,"ended_at":None,"error":None,
            "recording":False,"recording_name":None,"recorded_bytes":0,
            "listener_connected":False,
            "format":"audio/mpeg","backend":"rtl_fm → ffmpeg libmp3lame",
        }

    def availability(self):
        inv=self.inventory()
        if inv.get("platform")!="Linux" or inv.get("rtl_usb_count")!=1:
            return {"ready":False,"reason":"One local RTL2832U device on Linux required"}
        if self.state["active"]:
            return {"ready":False,"reason":"Live FM is already active; stop before changing frequency"}
        if not self.lookup("rtl_fm"):
            return {"ready":False,"reason":"rtl_fm missing"}
        if not self.lookup("ffmpeg"):
            return {"ready":False,"reason":"ffmpeg missing; cannot encode browser MP3"}
        busy=self.conflicts()
        if busy:
            return {"ready":False,"reason":"SDR busy or possibly reserved by: "+
                    ", ".join(sorted({x["process"] for x in busy}))}
        return {"ready":True,"reason":"Real FM radio streaming available after user approval"}

    def _acquire_lock(self):
        self.lock_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        os.chmod(self.lock_dir,0o700)
        fd=os.open(self.lock_dir/LOCK_NAME,
                   os.O_RDWR|os.O_CREAT|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0),0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise LiveError("A cooperating receiver has reserved this RTL-SDR") from exc
        self.lock_fd=fd

    def _release_lock(self):
        fd,self.lock_fd=self.lock_fd,None
        if fd is not None:
            try:fcntl.flock(fd,fcntl.LOCK_UN)
            finally:os.close(fd)

    def start(self, frequency_mhz, *, record=False, subtitles=False,
              language="en", translate_to=None, backend="auto", translation_backend="auto"):
        hz,_=validate_request(frequency_mhz,10)
        if type(record) is not bool or type(subtitles) is not bool:
            raise ValueError("Record/subtitles flags must be Boolean")
        if subtitles and self.transcripts is None:
            raise LiveError("Transcript store unavailable")
        with self.mutex:
            if self.state["active"]:
                raise LiveError("Live radio session already active")
            ready=self.availability()
            if not ready["ready"]:
                raise LiveError(ready["reason"])
            self._acquire_lock()
            try:
                if self.conflicts():
                    raise LiveError("Receiver became busy before tuning")
                rtl=self.lookup("rtl_fm")
                ffmpeg=self.lookup("ffmpeg")
                if not rtl or not ffmpeg:
                    raise LiveError("Audio tools disappeared before launch")
                self.stop_flag.clear()
                session=uuid.uuid4().hex
                self.archive.mkdir(parents=True,exist_ok=True,mode=0o700)
                os.chmod(self.archive,0o700)
                now=datetime.now(timezone.utc)
                name=now.strftime("%Y%m%dT%H%M%SZ")+"-FM-"+str(hz)+"-"+session[:10]+".mp3" if record else None
                # Open output under owned archive only, never a user-supplied path.
                self.record_file=(open(self.archive/name,"xb") if name else None)
                self.receiver=subprocess.Popen(audio_argv(rtl,hz),stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    start_new_session=True,close_fds=True)
                self.encoder=subprocess.Popen(encode_argv(ffmpeg),stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    start_new_session=True,close_fds=True)
                self.state={
                    "active":True,"status":"running","session":session,"frequency_hz":hz,
                    "started_at":now.isoformat(timespec="seconds"),"ended_at":None,
                    "error":None,"recording":record,"recording_name":name,
                    "recorded_bytes":0,"listener_connected":False,"format":"audio/mpeg",
                    "backend":"rtl_fm → ffmpeg libmp3lame",
                }
                self.listener=False
                self.speech=None
                if subtitles:
                    self.speech=SpeechPipeline(
                        store=self.transcripts,session=session,
                        source_id=f"fm:{hz}",source_language=language,
                        target_language=translate_to,backend=backend,profile=detect_devices(),
                        translation_backend=translation_backend)
                self.state["subtitles_requested"]=subtitles
                self.last_seen=time.monotonic()
                self.worker=threading.Thread(target=self._feed,daemon=True,name="tihulu-live-fm-pcm")
                self.watchdog=threading.Thread(target=self._watch,daemon=True,name="tihulu-live-fm-watchdog")
                self.worker.start()
                self.watchdog.start()
                return dict(self.state)
            except BaseException:
                self._shutdown("error","Unable to initialize FM stream")
                raise

    @staticmethod
    def _terminate(proc):
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid,signal.SIGTERM)
            proc.wait(timeout=0.6)
        except (OSError,subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid,signal.SIGKILL)
                proc.wait(timeout=0.4)
            except (OSError,subprocess.TimeoutExpired):
                pass

    def _feed(self):
        try:
            with self.mutex:
                rtl,enc=self.receiver,self.encoder
            assert rtl is not None and enc is not None
            assert rtl.stdout is not None and enc.stdin is not None
            while not self.stop_flag.is_set():
                pcm=rtl.stdout.read(8192)
                if not pcm:
                    break
                if self.speech is not None:
                    self.speech.feed(pcm)
                enc.stdin.write(pcm)
                enc.stdin.flush()
        except (OSError,BrokenPipeError,ValueError):
            pass
        finally:
            with self.mutex:
                if self.state["active"] and not self.stop_flag.is_set():
                    self._shutdown("error","FM hardware/encoder ended before Stop")

    def _watch(self):
        while not self.stop_flag.wait(0.5):
            with self.mutex:
                if not self.state["active"]:
                    return
                if time.monotonic()-self.last_seen>self.timeout:
                    self._shutdown("stopped","Browser heartbeat expired")
                    return

    def _shutdown(self,status="stopped",reason=None):
        # Must hold self.mutex. Only session process groups are terminated.
        self.stop_flag.set()
        self._terminate(self.receiver)
        self._terminate(self.encoder)
        for obj in (self.receiver,self.encoder):
            if obj:
                for channel in (obj.stdin,obj.stdout):
                    if channel:
                        try:channel.close()
                        except OSError:pass
        self.receiver=self.encoder=None
        if self.record_file:
            try:self.record_file.close()
            except OSError:pass
        self.record_file=None
        if self.speech is not None:
            self.speech.stop()
        self._release_lock()
        self.state.update(active=False,status=status,error=reason,
            ended_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            listener_connected=False)
        self.listener=False

    def status(self,heartbeat=False):
        with self.mutex:
            if heartbeat and self.state["active"]:
                self.last_seen=time.monotonic()
            snapshot=dict(self.state)
            snapshot["speech"]=self.speech.status() if self.speech else {
                "enabled":False,"reason":"Speech transcription not requested or unavailable"}
            return snapshot

    def stop(self,*,wait=False):
        with self.mutex:
            if self.state["active"]:
                self._shutdown("stopped")
            status=dict(self.state)
        if wait and self.worker and self.worker.is_alive() and threading.current_thread()!=self.worker:
            self.worker.join(timeout=2)
        return status

    def stream(self,session:str):
        """Yield real MP3 data to a single browser listener; stop upon disconnect."""
        with self.mutex:
            if not self.state["active"] or session != self.state["session"]:
                raise LiveError("Live FM session not active or mismatched")
            if self.listener:
                raise LiveError("This RTL-SDR live stream already has a listener")
            self.listener=True
            self.state["listener_connected"]=True
            self.last_seen=time.monotonic()
            enc=self.encoder
        try:
            assert enc is not None and enc.stdout is not None
            while not self.stop_flag.is_set():
                chunk=enc.stdout.read(8192)
                if not chunk:
                    break
                with self.mutex:
                    if self.record_file:
                        if self.state["recorded_bytes"]+len(chunk)<=MAX_RECORD_BYTES:
                            self.record_file.write(chunk)
                            self.state["recorded_bytes"]+=len(chunk)
                        else:
                            self.record_file.close()
                            self.record_file=None
                            self.state["recording"]=False
                            self.state["error"]="Recording size limit reached; live play continues"
                yield chunk
        finally:
            # Listener leaving must stop tuner and recording promptly.
            self.stop()

    def recordings(self):
        try:
            names=sorted(self.archive.glob("*-FM-*.mp3"),reverse=True)[:100]
        except OSError:
            return []
        return [{"name":p.name,"bytes":p.stat().st_size}
                for p in names if p.is_file() and p.stat().st_size>0]

    def recording(self,name:str):
        if not isinstance(name,str) or "/" in name or "\\" in name or ".." in name:
            return None
        if not name.endswith(".mp3") or "-FM-" not in name or len(name)>120:
            return None
        path=self.archive/name
        return path if path.is_file() and path.stat().st_size>0 else None
