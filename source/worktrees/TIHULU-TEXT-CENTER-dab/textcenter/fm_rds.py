"""Explicit, bounded FM RDS receive-only capture: rtl_fm -> redsea JSON.

No background scanning or preemptive retuning. The cooperative file lock
protects only clients that use this app's lock protocol: Gqrx, welle.io,
readsb and arbitrary RTL-SDR programs are NOT guaranteed to honor it.

RDS groups remain broadcaster-provided, unauthenticated text and must
never be promoted into trusted Emergency Center warnings.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
from threading import Event, Lock, Thread
import time
import uuid

from .core import Store
from .receivers import receiver_inventory
from .conflicts import find_receiver_conflicts
from .media import MediaStore, rds2_image_group

MAX_DURATION = 90
MAX_JSON_LINE = 500_000  # only accepted for source-supplied RDS2 image groups
MAX_EVENT_ITEMS = 100
IDLE_SECONDS = 12.0


def validate_request(frequency_mhz: object, duration: object) -> tuple[int, int]:
    if type(frequency_mhz) not in (int, float) or not 87.5 <= frequency_mhz <= 108.0:
        raise ValueError("Frequency must be 87.500–108.000 MHz")
    hz = round(float(frequency_mhz) * 1_000_000)
    if not 87_500_000 <= hz <= 108_000_000:
        raise ValueError("FM broadcast frequency out of bounds")
    if type(duration) is not int or not 10 <= duration <= MAX_DURATION:
        raise ValueError("Capture duration must be 10–90 seconds")
    return hz, duration


def build_commands(rtl_fm: str, redsea: str, hz: int, rds2_images: bool = False) -> tuple[list[str], list[str]]:
    if type(hz) is not int or not 87_500_000 <= hz <= 108_000_000:
        raise ValueError("Unsupported FM frequency")
    # redsea's own documented 171-kHz multiplex format. No shell interpolation.
    return (
        [rtl_fm, "-d", "0", "-M", "fm", "-l", "0", "-A", "std",
         "-p", "0", "-s", "171k", "-g", "20", "-F", "9", "-f", str(hz)],
        [redsea, "--input", "mpx", "-r", "171k"] + (["--streams"] if rds2_images else []),
    )


def decode_rds_group(group: object, hz: int, observed_at: str | None = None) -> dict | None:
    if not isinstance(group, dict):
        return None
    ps = group.get("ps")
    rt = group.get("radiotext")
    station = ps.strip()[:80] if isinstance(ps, str) and ps.strip() else f"FM {hz / 1e6:g} MHz"
    is_text = isinstance(rt, str) and bool(rt.strip())
    is_label = isinstance(ps, str) and bool(ps.strip())
    # Official redsea JSON represents RT+ as radiotext_plus.tags with
    # content-type item.title / item.artist and data delivered by the broadcaster.
    plus = group.get("radiotext_plus")
    tags = plus.get("tags") if isinstance(plus, dict) else None
    rich: list[str] = []
    if isinstance(tags, list):
        for tag in tags[:12]:
            if not isinstance(tag, dict):
                continue
            kind, value = tag.get("content-type"), tag.get("data")
            if kind in ("item.artist", "item.title") and isinstance(value, str):
                val = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()[:250]
                if val:
                    rich.append(("Artist" if kind == "item.artist" else "Title") + ": " + val)
    if not is_text and not is_label and not rich:
        return None
    original = (rt if is_text else ps if is_label else "").strip()[:1000]
    # Do not fabricate metadata or infer artists from free-text RadioText.
    body = original + ("\n" if original and rich else "") + "\n".join(rich)
    # Disallow nonprinting terminal escapes, retaining line breaks for RT+ tags.
    body = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", body)
    pi = group.get("pi", "")
    valid_pi = pi if isinstance(pi, str) and re.fullmatch(r"0x[0-9a-fA-F]{4}", pi) else None
    stamp = observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "source_id": f"fm_rds:{hz}" + (f":{valid_pi}" if valid_pi else ""),
        "title": "FM RadioText+" if rich else "FM RadioText" if is_text else "RDS station label",
        "body": body,
        "language": "und",  # no invented language detection
        "station": station,
        "received_at": stamp,
        "frequency_hz": hz,
        "medium": "fm_rds",
        "provenance": "redsea JSON via local rtl_fm receiver" + (f"; RDS PI {valid_pi}" if valid_pi else ""),
    }


class CaptureError(RuntimeError):
    pass


class FMRSDSupervisor:
    """Single bounded session, explicitly started/stopped by loopback browser user."""

    def __init__(self, store: Store, *, inventory=None, lookup=None,
                 conflicts=None, lock_dir: Path | None = None,
                 idle_seconds: float = IDLE_SECONDS):
        self.store = store
        self.media = MediaStore(store)
        self.inventory = inventory or receiver_inventory
        self.conflicts = conflicts or find_receiver_conflicts
        self.lookup = lookup or shutil.which
        self.lock_dir = lock_dir or (store.filename.parent / ".receiver-locks")
        self.idle_seconds = idle_seconds
        self._mutex = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._rtlfm: subprocess.Popen | None = None
        self._redsea: subprocess.Popen | None = None
        self._lock_fd: int | None = None
        self._last_poll = 0.0
        self._seen: set[tuple[str, str, str]] = set()
        self._recent: deque[dict] = deque(maxlen=20)
        self._state: dict = {
            "status": "idle", "active": False, "frequency_hz": None,
            "duration_seconds": None, "received_groups": 0,
            "saved_items": 0, "started_at": None, "ended_at": None,
            "session": None, "error": None, "last_text": None,
            "rds2_images": False, "saved_images": 0,
        }

    def availability(self) -> dict:
        inventory = self.inventory()
        if inventory.get("platform") != "Linux":
            return {"ready": False, "reason": "This RF backend currently supports Linux only"}
        if inventory.get("rtl_usb_count") != 1:
            return {"ready": False, "reason": "Exactly one RTL2832U-compatible USB device is required"}
        conflicts = self.conflicts()
        if conflicts:
            names=", ".join(sorted(set(x["process"] for x in conflicts)))
            return {"ready": False, "reason":
                    f"SDR reserved/possibly in use by {names}. Stop it manually or use a separate receiver.",
                    "conflicts": conflicts}
        if not self.lookup("rtl_fm"):
            return {"ready": False, "reason": "rtl_fm is missing"}
        if not self.lookup("redsea"):
            return {"ready": False, "reason": "redsea is missing: install it before starting FM RadioText"}
        return {"ready": True,
                "reason": "Executable and USB checks passed; device ownership and RF reception unverified"}

    def _acquire_lock(self) -> int:
        self.lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.lock_dir, 0o700)
        flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.lock_dir / "rtl_fm_rds.lock", flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            os.close(fd)
            raise CaptureError("Another cooperating Text Center capture owns the SDR lock")
        return fd

    def start(self, *, frequency_mhz: object, duration: object, rds2_images: bool = False) -> dict:
        hz, seconds = validate_request(frequency_mhz, duration)
        if type(rds2_images) is not bool:
            raise ValueError("RDS2 image option must be a Boolean")
        with self._mutex:
            if self._state["active"]:
                raise CaptureError("An FM RDS capture is already running")
            ok = self.availability()
            if not ok["ready"]:
                raise CaptureError(ok["reason"])
            try:
                fd = self._acquire_lock()
            except OSError as exc:
                raise CaptureError(f"Cannot reserve cooperative SDR lock: {exc}") from exc
            self._lock_fd = fd
            # Race-aware second preflight after our cooperative lock is held.
            try:
                busy = self.conflicts()
            except Exception:
                self._unlock()
                raise CaptureError("Cannot verify SDR ownership; refusing to tune")
            if busy:
                self._unlock()
                raise CaptureError(
                    "SDR contention detected: " + ", ".join(sorted(set(x["process"] for x in busy)))
                )
            self._stop.clear()
            self._last_poll = time.monotonic()
            self._recent.clear()
            self._seen.clear()
            self._state = {
                "status": "running", "active": True, "frequency_hz": hz,
                "duration_seconds": seconds, "received_groups": 0,
                "saved_items": 0, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ended_at": None, "session": uuid.uuid4().hex,
                "error": None, "last_text": None,
                "rds2_images":rds2_images, "saved_images":0,
            }
            self._thread = Thread(target=self._worker, args=(hz, seconds, rds2_images),
                                  name="tihulu-fm-rds", daemon=True)
            try:
                self._thread.start()
            except BaseException:
                self._unlock()
                self._state["active"] = False
                self._state["status"] = "error"
                raise
            return self._snapshot()

    def _snapshot(self) -> dict:
        return {**self._state, "recent": list(self._recent),
                "decoder_kind": "rtl_fm_plus_redsea",
                "source_trust": "received_rf_not_official_alert"}

    def status(self, *, heartbeat: bool = True) -> dict:
        with self._mutex:
            if heartbeat and self._state["active"]:
                self._last_poll = time.monotonic()
            return self._snapshot()

    def stop(self, *, wait: bool = False) -> dict:
        with self._mutex:
            if self._state["active"]:
                self._stop.set()
                self._state["status"] = "stopping"
            thread = self._thread
            result = self._snapshot()
        if wait and thread and thread.is_alive():
            thread.join(timeout=4.0)
        return result

    def _unlock(self) -> None:
        fd = self._lock_fd
        self._lock_fd = None
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _save_group(self, line: bytes, hz: int) -> None:
        try:
            obj = json.loads(line.decode("utf-8", errors="replace"))
        except (ValueError, UnicodeError):
            return
        if not isinstance(obj, dict):
            return
        with self._mutex:
            self._state["received_groups"] += 1
            image_enabled=self._state.get("rds2_images",False)
        if image_enabled:
            embedded=rds2_image_group(obj)
            if embedded:
                pi=obj.get("pi") if isinstance(obj.get("pi"),str) else ""
                station=obj.get("ps") if isinstance(obj.get("ps"),str) else ""
                station=(station.strip()[:80] if station.strip() else f"FM {hz/1e6:g} MHz")
                source_id=f"fm_rds2:{hz}"+(":"+pi if pi.startswith("0x") and len(pi)==6 else "")
                try:
                    self.media.save(
                        medium="fm_rds2_logo",source_id=source_id,station=station,
                        frequency_hz=hz,
                        received_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        provenance="redsea RDS2 RFT image via local RTL-SDR; source not authenticated",
                        image_base64=embedded)
                except (ValueError,OSError):
                    pass
                else:
                    with self._mutex:
                        self._state["saved_images"]+=1
        event = decode_rds_group(obj, hz)
        if not event:
            return
        fingerprint = (event["source_id"], event["title"], event["body"])
        with self._mutex:
            if fingerprint in self._seen or self._state["saved_items"] >= MAX_EVENT_ITEMS:
                return
            self._seen.add(fingerprint)
        try:
            # The decoder has produced actual group JSON, not a synthetic station.
            self.store.import_data({"schema_version": 1, "events": [event]})
        except (ValueError, OSError):
            return
        with self._mutex:
            self._state["saved_items"] += 1
            self._state["last_text"] = event["body"]
            self._recent.append({
                "title": event["title"], "text": event["body"],
                "station": event["station"], "received_at": event["received_at"],
            })

    @staticmethod
    def _end_process(process: subprocess.Popen | None) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            process.terminate()
        try:
            process.wait(timeout=1.2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                process.kill()
            try:
                process.wait(timeout=0.7)
            except subprocess.TimeoutExpired:
                pass

    def _worker(self, hz: int, seconds: int, rds2_images: bool = False) -> None:
        rtl: subprocess.Popen | None = None
        redsea: subprocess.Popen | None = None
        selector = selectors.DefaultSelector()
        state = "completed"
        reason: str | None = None
        deadline = time.monotonic() + seconds
        buffers: dict[int, bytearray] = {}
        stderr_tail: deque[str] = deque(maxlen=5)
        try:
            rtl_bin = self.lookup("rtl_fm")
            red_bin = self.lookup("redsea")
            if not rtl_bin or not red_bin:
                raise CaptureError("Decoder executable disappeared before launch")
            if self.conflicts():
                raise CaptureError("Another SDR or plane-tracker process appeared before the tuner opened")
            rtl_argv, red_argv = build_commands(rtl_bin, red_bin, hz, rds2_images)
            rtl = subprocess.Popen(rtl_argv, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                   start_new_session=True, close_fds=True)
            with self._mutex:
                self._rtlfm = rtl
            redsea = subprocess.Popen(red_argv, stdin=rtl.stdout, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, start_new_session=True,
                                      close_fds=True)
            with self._mutex:
                self._redsea = redsea
            assert rtl.stdout is not None
            rtl.stdout.close()  # decoder owns the read side
            for stream, tag in ((redsea.stdout, "json"), (redsea.stderr, "rds_err"),
                                (rtl.stderr, "rtl_err")):
                if stream is None:
                    continue
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, tag)
                buffers[stream.fileno()] = bytearray()
            while True:
                if self._stop.is_set():
                    state = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    state = "completed"
                    break
                with self._mutex:
                    idle = time.monotonic() - self._last_poll
                if idle > self.idle_seconds:
                    state, reason = "cancelled", "Capture stopped because the browser session stopped polling"
                    break
                for key, _ in selector.select(timeout=0.2):
                    stream = key.fileobj
                    tag = key.data
                    try:
                        data = os.read(stream.fileno(), 4096)
                    except (BlockingIOError, InterruptedError):
                        continue
                    if not data:
                        selector.unregister(stream)
                        continue
                    buf = buffers[stream.fileno()]
                    buf.extend(data)
                    if len(buf) > (MAX_JSON_LINE if rds2_images else 8192) * 3:
                        del buf[:len(buf) - (MAX_JSON_LINE if rds2_images else 8192)]
                    while b"\n" in buf:
                        raw, _, remaining = buf.partition(b"\n")
                        buffers[stream.fileno()] = buf = bytearray(remaining)
                        if tag == "json" and len(raw) <= (MAX_JSON_LINE if rds2_images else 8192):
                            self._save_group(raw, hz)
                        elif tag != "json":
                            stderr_tail.append(raw.decode("utf-8", errors="replace")[:240])
                if redsea.poll() is not None or rtl.poll() is not None:
                    # Drain buffered decoder stdout before deciding outcome.
                    if redsea.stdout is not None:
                        try:
                            extra = os.read(redsea.stdout.fileno(), 8192)
                            if extra:
                                buf = buffers[redsea.stdout.fileno()]
                                buf.extend(extra)
                                while b"\n" in buf:
                                    raw, _, remaining = buf.partition(b"\n")
                                    buffers[redsea.stdout.fileno()] = buf = bytearray(remaining)
                                    if len(raw) <= (MAX_JSON_LINE if rds2_images else 8192):
                                        self._save_group(raw, hz)
                        except (OSError, BlockingIOError):
                            pass
                    rc = rtl.poll()
                    rd = redsea.poll()
                    if (rc not in (None, 0)) or (rd not in (None, 0)):
                        state = "error"
                        reason = "Receiver or decoder exited unexpectedly. The SDR may be busy, disconnected, or missing permissions."
                    elif self.status(heartbeat=False)["received_groups"] == 0:
                        state = "error"
                        reason = "Receiver/decoder exited without decoded RDS groups"
                    else:
                        state = "completed"
                    break
            if state == "completed" and self.status(heartbeat=False)["received_groups"] == 0:
                reason = "No RDS groups were decoded during the capture window; tune a strong FM broadcaster"
        except (OSError, CaptureError, ValueError) as exc:
            state, reason = "error", str(exc)[:350]
        finally:
            selector.close()
            self._end_process(redsea)
            self._end_process(rtl)
            if rtl:
                for pipe in (rtl.stdout, rtl.stderr):
                    if pipe:
                        pipe.close()
            if redsea:
                for pipe in (redsea.stdout, redsea.stderr):
                    if pipe:
                        pipe.close()
            with self._mutex:
                self._redsea = None
                self._rtlfm = None
                self._unlock()
                self._state["status"] = state
                self._state["active"] = False
                self._state["ended_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._state["error"] = reason
