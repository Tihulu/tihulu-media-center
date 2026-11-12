"""Short on-demand FM listening previews, from REAL rtl_fm PCM, no demo audio.

Only one local RTL-SDR at a time. This is a bounded WAV preview, NOT an
indefinite live audio stream. User must consent before USB retune; running
readsb/Gqrx/other receiver conflicts refuse capture. No external audio files
or Internet stream is used. No archive or background recording is created.
"""
from __future__ import annotations
from datetime import datetime, timezone
import fcntl
import io
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
from threading import Event, Lock, Thread
import time
import uuid
import wave

from .conflicts import find_receiver_conflicts
from .fm_rds import validate_request
from .receivers import receiver_inventory

AUDIO_RATE = 32_000
MAX_CAPTURE = 20
MAX_BYTES = AUDIO_RATE * 2 * MAX_CAPTURE
LOCK_NAME = "rtl_fm_rds.lock"


class AudioError(RuntimeError):
    pass


def audio_argv(exe: str, hz: int) -> list[str]:
    if type(hz) is not int or not 87_500_000 <= hz <= 108_000_000:
        raise ValueError("FM tuning only")
    # wbfm is a documented rtl_fm preset. Signed 16-bit mono @32kHz.
    return [exe, "-d", "0", "-M", "wbfm", "-f", str(hz),
            "-l", "0", "-s", "170k", "-o", "4", "-A", "fast",
            "-r", "32k", "-E", "deemp"]


def pcm_to_wav(raw: bytes) -> bytes:
    if len(raw) % 2:
        raw = raw[:-1]
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Invalid/oversized PCM recording")
    with io.BytesIO() as output:
        with wave.open(output, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(AUDIO_RATE)
            wf.writeframes(raw)
        return output.getvalue()


class FMPreview:
    def __init__(self, *, inventory=None, lookup=None, conflicts=None,
                 rds=None, survey=None, lock_dir: Path | None = None,
                 max_duration: int = MAX_CAPTURE):
        self.inventory = inventory or receiver_inventory
        self.lookup = lookup or shutil.which
        self.conflicts = conflicts or find_receiver_conflicts
        self.rds, self.survey = rds, survey
        self.lock_dir = lock_dir or Path.home() / ".local/share/tihulu-text-center/.receiver-locks"
        self.max_duration = max_duration
        self._mutex = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock_fd: int | None = None
        self._process: subprocess.Popen | None = None
        self._wav: bytes | None = None
        self._state = {
            "status":"idle", "active":False, "frequency_hz":None,
            "recorded_seconds":0, "session":None, "error":None,
            "started_at":None, "ended_at":None, "clip_ready":False,
        }

    def availability(self):
        inv = self.inventory()
        if inv.get("platform") != "Linux" or inv.get("rtl_usb_count") != 1:
            return {"ready":False, "reason":"Exactly one local Linux RTL2832U candidate required"}
        if not self.lookup("rtl_fm"):
            return {"ready":False, "reason":"rtl_fm is not installed"}
        if (self.rds and self.rds.status(heartbeat=False)["active"]) or (
            self.survey and self.survey.status(heartbeat=False)["active"]
        ):
            return {"ready":False, "reason":"Other Text Center receiver session is running"}
        busy = self.conflicts()
        if busy:
            return {"ready":False, "reason":"Receiver may be busy: "+
                    ", ".join(sorted({x["process"] for x in busy}))}
        return {"ready":True, "reason":"Manual 10–20 second FM listening preview available"}

    def _unlock(self):
        fd, self._lock_fd = self._lock_fd, None
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def start(self, frequency_mhz: object, duration_seconds: object = 12):
        hz, duration = validate_request(frequency_mhz, duration_seconds)
        if duration > self.max_duration:
            raise ValueError("FM audio preview limited to 20 seconds")
        with self._mutex:
            if self._state["active"]:
                raise AudioError("A listening preview is already in progress")
            ready = self.availability()
            if not ready["ready"]:
                raise AudioError(ready["reason"])
            self.lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.lock_dir, 0o700)
            flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.lock_dir / LOCK_NAME, flags, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                raise AudioError("Shared SDR lock is occupied")
            self._lock_fd = fd
            try:
                if self.conflicts() or (self.rds and self.rds.status(heartbeat=False)["active"]) or (
                    self.survey and self.survey.status(heartbeat=False)["active"]
                ):
                    raise AudioError("Receiver became busy before audio capture")
                self._wav = None
                self._stop.clear()
                self._state = {
                    "status":"running", "active":True, "frequency_hz":hz,
                    "recorded_seconds":0, "session":uuid.uuid4().hex,
                    "error":None,
                    "started_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "ended_at":None, "clip_ready":False,
                }
                self._thread = Thread(target=self._worker,args=(hz,duration),
                                      name="tihulu-fm-audio",daemon=True)
                self._thread.start()
                return self._snapshot()
            except BaseException:
                self._unlock()
                self._state["status"]="error"
                self._state["active"]=False
                raise

    def _snapshot(self):
        return dict(self._state)

    def status(self):
        with self._mutex:
            return self._snapshot()

    def wav_clip(self):
        with self._mutex:
            if self._state["active"] or not self._state["clip_ready"]:
                return None
            return self._wav

    def stop(self, *, wait=False):
        with self._mutex:
            if self._state["active"]:
                self._stop.set()
                self._state["status"]="stopping"
            thread=self._thread
            result=self._snapshot()
        if wait and thread and thread.is_alive():
            thread.join(timeout=3)
        return result

    @staticmethod
    def _terminate(proc):
        if not proc or proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=0.8)
        except (ProcessLookupError, ChildProcessError):
            pass
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid,signal.SIGKILL)
                proc.wait(timeout=0.5)
            except (OSError,subprocess.TimeoutExpired):
                pass

    def _worker(self, hz:int, duration:int):
        process=None
        status="completed"
        error=None
        samples=bytearray()
        try:
            if self.conflicts():
                raise AudioError("Receiver is now in use; preview refused")
            executable=self.lookup("rtl_fm")
            if not executable:
                raise AudioError("rtl_fm disappeared")
            process=subprocess.Popen(audio_argv(executable,hz),stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                     start_new_session=True,close_fds=True)
            with self._mutex:
                self._process=process
            assert process.stdout is not None
            os.set_blocking(process.stdout.fileno(),False)
            with selectors.DefaultSelector() as sel:
                sel.register(process.stdout,selectors.EVENT_READ)
                deadline=time.monotonic()+duration
                while time.monotonic()<deadline and len(samples)<MAX_BYTES:
                    if self._stop.is_set():
                        status="cancelled"
                        break
                    if process.poll() is not None:
                        # Collect the final buffered data.
                        try:
                            more=os.read(process.stdout.fileno(),65536)
                            samples.extend(more[:MAX_BYTES-len(samples)])
                        except BlockingIOError:
                            pass
                        break
                    for item,_ in sel.select(timeout=0.15):
                        try:
                            chunk=os.read(item.fileobj.fileno(),65536)
                        except BlockingIOError:
                            continue
                        if chunk:
                            samples.extend(chunk[:MAX_BYTES-len(samples)])
                if process.poll() not in (None,0) and len(samples)<AUDIO_RATE*2:
                    raise AudioError("rtl_fm exited early; device may be busy or driver permission missing")
            if status=="completed" and len(samples)<AUDIO_RATE*2:
                raise AudioError("Less than one second of real radio audio was captured")
        except (OSError,AudioError,ValueError) as exc:
            status,error="error",str(exc)[:240]
        finally:
            self._terminate(process)
            if process and process.stdout:
                process.stdout.close()
            with self._mutex:
                self._process=None
                if status=="completed":
                    try:
                        self._wav=pcm_to_wav(bytes(samples[:MAX_BYTES]))
                    except ValueError as exc:
                        status,error="error",str(exc)
                self._state["recorded_seconds"]=round(len(samples)/(AUDIO_RATE*2),1)
                self._state["status"]=status
                self._state["active"]=False
                self._state["clip_ready"]=self._wav is not None and status=="completed"
                self._state["error"]=error
                self._state["ended_at"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._unlock()
