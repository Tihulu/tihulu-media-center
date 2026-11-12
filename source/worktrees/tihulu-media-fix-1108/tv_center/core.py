"""Linux DVB receiver controller, without WebUSB, VLC or an RTL-SDR dependency.

The TV frontend and the unrelated RTL-SDR receiver are never conflated.
All tuning is owner-triggered. Capture writes short bounded temporary TS
segments only while captions/Teletext are explicitly enabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from .ts import ServiceFilter
import fcntl
import json
import os
import socket
import queue
import re
import select
import shutil
import subprocess
import tempfile
import threading
import time

@dataclass(frozen=True)
class Channel:
    name: str
    path: Path
    frequency: int
    service_id: int | None
    encrypted: bool = False
    delivery: str = ""
    kind: str = "tv"

def read_channels(files: list[Path]) -> list[Channel]:
    result = []
    seen = set()
    for path in files:
        path = Path(path).expanduser()
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        name = None
        attrs = {}
        def commit():
            if not name or not attrs:
                return
            try:
                freq = int(attrs.get("FREQUENCY", "0"), 0)
                sid = int(attrs["SERVICE_ID"], 0) if "SERVICE_ID" in attrs else None
            except ValueError:
                return
            delivery = attrs.get("DELIVERY_SYSTEM", "").upper()
            satellite = "DVBS" in delivery or "DVB-S" in delivery
            if satellite:
                # DVBv5 satellite tuning files conventionally use kHz
                # (e.g. 11508500), though some exports use Hz.
                if not (3_000_000 <= freq <= 20_000_000 or
                        3_000_000_000 <= freq <= 20_000_000_000):
                    return
            elif not 40_000_000 <= freq <= 1_000_000_000:
                return
            service_type = attrs.get("SERVICE_TYPE", "").upper()
            radio = ("RADIO" in service_type or service_type in ("2", "0X02", "10", "0X0A"))
            key = (freq, sid, name, delivery)
            if key not in seen:
                seen.add(key)
                result.append(Channel(name, path, freq, sid,
                          attrs.get("SCRAMBLED", "0").upper() not in ("0", "FALSE", "NO"),
                          delivery, "radio" if radio else "tv"))
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("[") and s.endswith("]") and len(s) < 140:
                commit()
                name, attrs = s[1:-1].strip(), {}
            elif "=" in s and name:
                k, v = s.split("=", 1)
                attrs[k.strip().upper()] = v.strip()
        commit()
    return result

def discover_channels() -> list[Channel]:
    home = Path.home()
    files = sorted(home.glob("tv-*-channels.conf"))
    extra = home / ".config/tihulu-tv-center/channels.conf"
    if extra.is_file():
        files.append(extra)
    return read_channels(files)

def format_frequency(channel: Channel) -> str:
    if ("DVBS" in channel.delivery or "DVB-S" in channel.delivery) and channel.frequency < 100_000_000:
        return f"{channel.frequency / 1_000_000:g} GHz"
    if channel.frequency >= 1_000_000_000:
        return f"{channel.frequency / 1_000_000_000:.3f} GHz"
    return f"{channel.frequency / 1_000_000:g} MHz"

def zap_argv(channel: Channel, adapter: int = 0) -> list[str]:
    if adapter not in range(0, 16):
        raise ValueError("Adapter must be between 0 and 15")
    if not channel.name or len(channel.name) > 120 or any(
            ord(c) < 32 or ord(c) == 127 for c in channel.name):
        raise ValueError("Unsafe DVB service name")
    return ["dvbv5-zap", "-a", str(adapter), "-c", str(channel.path),
            "-p", "-P", "-r", channel.name]

def isolated_channel_file(channel: Channel, destination: Path) -> Channel:
    """Give dvbv5-zap exactly one real service, not a duplicate display name.

    A scan source can contain identical channel names on several frequencies.
    dvbv5-zap's name lookup would otherwise tune the first match. Preserve
    *all* modulation/PLP/PID properties from the selected source section.
    """
    if not channel.path or not Path(channel.path).is_file():
        raise RuntimeError("Selected channel has no readable DVBv5 scan file; rescan or import one")
    source=Path(channel.path)
    if source.stat().st_size>2_000_000:
        raise RuntimeError("DVB channel file exceeds the 2 MB safety limit")
    matches=[]
    title=None
    block=[]
    def accept():
        if title!=channel.name or not block:
            return
        attrs={}
        for line in block:
            if "=" in line:
                key,value=line.split("=",1)
                attrs[key.strip().upper()]=value.strip()
        try:
            frequency=int(attrs.get("FREQUENCY","0"),0)
            sid=int(attrs.get("SERVICE_ID","-1"),0)
        except ValueError:
            return
        if frequency==channel.frequency and (channel.service_id is None or sid==channel.service_id):
            matches.append("["+title+"]\n"+"\n".join(block)+"\n")
    for line in source.read_text(encoding="utf-8",errors="replace").splitlines():
        item=line.strip()
        if item.startswith("[") and item.endswith("]"):
            accept()
            title=item[1:-1].strip()
            block=[]
        elif title is not None:
            block.append(line)
    accept()
    if len(matches)!=1:
        raise RuntimeError("Expected exactly one matching DVB service in scan file "
                           f"({len(matches)} found for {channel.name!r} "
                           f"on {channel.frequency} Hz). Rescan this source.")
    destination=Path(destination)
    destination.write_text(matches[0],encoding="utf-8")
    return Channel(channel.name,destination,channel.frequency,channel.service_id,
                   channel.encrypted,channel.delivery,channel.kind)


def player_argv(channel: Channel, window_id: int, hwdec: str = "no", ipc_path: str | None = None, renderer: str = "x11-gpu") -> list[str]:
    if hwdec not in ("no", "auto-safe"):
        raise ValueError("Unsupported hardware decoding mode")
    if not isinstance(window_id, int) or window_id < 1:
        raise ValueError("A native X11 window ID is required")
    if renderer not in ("x11-gpu", "x11-compat"):
        raise ValueError("Unknown native renderer")
    # Wayland-native MPV may ignore a Qt/XWayland XID and make another window.
    # Force the *same* X11 display backend that owns QWidget.winId().
    vo = (["--vo=gpu", "--gpu-api=opengl", "--gpu-context=x11"]
          if renderer == "x11-gpu" else ["--vo=x11", "--profile=sw-fast"])
    args = ["mpv", "--no-config", "--no-terminal", "--force-window=no",
            "--no-border", "--osc=no", "--cache=yes", "--cache-secs=4",
            "--demuxer-lavf-format=mpegts",
            "--cache-pause-wait=0.3", "--hwdec=" + hwdec,
            "--wid=" + str(window_id), "--audio-spdif=no", *vo]
    # MPV's MPEG-TS 'program' is a runtime write-only property, NOT a CLI
    # --program option. Select it using the local JSON IPC socket on startup.
    if ipc_path:
        args.append("--input-ipc-server=" + ipc_path)
    return args + ["-"]

def receiver_status(adapter: int = 0) -> dict:
    root = Path(f"/dev/dvb/adapter{adapter}")
    frontend, dvr = root / "frontend0", root / "dvr0"
    hauppauge = False
    usbroot = Path("/sys/bus/usb/devices")
    if usbroot.is_dir():
        for dev in usbroot.iterdir():
            try:
                if ((dev / "idVendor").read_text().strip().lower() == "2040" and
                    (dev / "idProduct").read_text().strip().lower() == "8268"):
                    hauppauge = True
                    break
            except OSError:
                continue
    return {
        "win_tv_solohd_usb_present": hauppauge,
        "usb_identity_does_not_prove_frontend_ownership": True,
        "si2168_d60_firmware_present": Path("/lib/firmware/dvb-demod-si2168-d60-01.fw").is_file(),
        "adapter": adapter,
        "frontend": str(frontend),
        "frontend_present": frontend.exists(),
        "dvr_present": dvr.exists(),
        "dvbv5_zap": bool(shutil.which("dvbv5-zap")),
        "mpv": bool(shutil.which("mpv")),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "other_sdr_touched": False,
        "dvb_firmware_note": "For WinTV-soloHD verify em28xx/Si2168-D60 and dvb-demod-si2168-d60-01.fw."
    }

def parse_signal_log(raw: str) -> dict:
    """Summarize actual dvb-fe-tool -m readings (no fabricated signal values)."""
    if not isinstance(raw, str):
        raise ValueError("Monitor output must be text")
    locks = [line for line in raw.splitlines() if line.startswith("Lock")]
    cn, ucb, levels = [], [], []
    for line in locks:
        match_cn = re.search(r"C/N=\s*([\d.]+)dB", line)
        match_level = re.search(r"Signal=\s*(-?[\d.]+)dBm", line)
        match_ucb = re.search(r"UCB=\s*(\d+)", line)
        if match_cn:
            cn.append(float(match_cn.group(1)))
        if match_level:
            levels.append(float(match_level.group(1)))
        if match_ucb:
            ucb.append(int(match_ucb.group(1)))
    no_lock = sum(("Carrier(0x03)" in line or "(0x00)" in line)
                  for line in raw.splitlines())
    return {"lock_readings": len(locks), "loss_indications": no_lock,
            "cn_min_db": min(cn) if cn else None,
            "cn_max_db": max(cn) if cn else None,
            "cn_last_db": cn[-1] if cn else None,
            "signal_last_dbm": levels[-1] if levels else None,
            "ucb_first": ucb[0] if ucb else None,
            "ucb_last": ucb[-1] if ucb else None,
            "ucb_delta": ucb[-1] - ucb[0] if len(ucb) >= 2 else None}

class ReceiverBusy(RuntimeError):
    pass

class TVCapture:
    """One reader owns a DVB DVR fd and fans TS out to mpv + bounded workers."""
    def __init__(self, adapter: int = 0):
        self.adapter = adapter
        self.channel = None
        self.zap = None
        self.player = None
        self.thread = None
        self.stop_flag = threading.Event()
        self.events = queue.Queue(maxsize=24)
        self.lockfile = None
        self.caption_mode = "off"
        self.page = 150
        self.source_lang, self.target_lang = "de", "tr"
        self.model = ""
        self.hwdec = "no"
        self._lock = threading.Lock()
        self._pending = False
        self._player_queue = queue.Queue(maxsize=24)
        self._writer_thread = None
        self._ipc_dir = None
        self.mobile_stream = None
        self.mpv_log_path = None
        self.zap_log_path = None
        self._mpv_log_handle = None
        self._zap_log_handle = None
        self._queue_drop_count = 0
        self._stream_verified = False

    def _log_dir(self):
        folder = Path.home() / ".cache" / "tihulu-tv-center"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        return folder

    def _mpv_exit_error(self):
        code = self.player.poll() if self.player else None
        return (f"MPV exited ({code}). Check playback log: {self.mpv_log_path}. "
                "Inspect antenna C/N and UCB as well; an absent DVB lock can "
                "produce the same input-stream error.")

    def start_mobile_video(self):
        if not self.channel or not self.zap or self.zap.poll() is not None:
            raise RuntimeError('Tune a channel before enabling mobile video')
        if self.channel.encrypted or not self.channel.service_id:
            raise RuntimeError('Mobile video needs a free-to-air scanned service ID')
        if self.mobile_stream is not None:
            return
        from .streaming import HLSStreamer
        stream = HLSStreamer(self.emit)
        stream.start(self.channel.service_id)
        self.mobile_stream = stream

    def stop_mobile_video(self):
        stream = self.mobile_stream
        self.mobile_stream = None
        if stream is not None:
            stream.stop()

    def mobile_stream_dir(self):
        stream = self.mobile_stream
        return stream.get_dir() if stream else None

    def emit(self, kind, value):
        try:
            self.events.put_nowait((kind, value))
        except queue.Full:
            pass

    def set_captions(self, mode: str, page=150, source="de", target="tr", model=""):
        if mode not in ("off", "teletext", "asr", "auto", "page"):
            raise ValueError("Invalid caption mode")
        if type(page) is not int or not (100 <= page <= 899):
            raise ValueError("Teletext page must be 100-899")
        if source not in ("tr", "de", "en") or target not in ("tr", "de", "en"):
            raise ValueError("Unsupported language")
        with self._lock:
            self.caption_mode, self.page = mode, page
            self.source_lang, self.target_lang, self.model = source, target, model

    def _lease(self):
        frontend = f"/dev/dvb/adapter{self.adapter}/frontend0"
        if not Path(frontend).exists():
            raise ReceiverBusy("DVB frontend is not connected")
        # Check non-cooperating programs too (Kaffeine, Tvheadend, dvbv5-zap).
        if shutil.which("fuser"):
            check = subprocess.run(["fuser", "-s", frontend], timeout=3, check=False)
            if check.returncode == 0:
                raise ReceiverBusy("Frontend already opened by another TV application")
        lock = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())) / f"tihulu-tv-adapter{self.adapter}-{os.getuid()}.lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise ReceiverBusy("Another TIHULU TV session owns this adapter") from exc
        self.lockfile = fd

    def start(self, channel: Channel, window_id: int, hwdec: str = "no", renderer: str = "x11-gpu"):
        if self.thread and self.thread.is_alive():
            raise ReceiverBusy("Stop the current TV session before changing channel")
        st = receiver_status(self.adapter)
        if not all(st[k] for k in ("frontend_present", "dvr_present", "dvbv5_zap", "mpv")):
            raise RuntimeError("Missing DVB device or required dvb-tools/mpv dependency")
        self._lease()
        self.stop_flag.clear()
        self.channel = channel
        self.hwdec = hwdec
        self._stream_verified = False
        try:
            logs = self._log_dir()
            self.mpv_log_path = logs / "mpv.log"
            self.zap_log_path = logs / "dvbv5-zap.log"
            self._mpv_log_handle = self.mpv_log_path.open("wb", buffering=0)
            self._zap_log_handle = self.zap_log_path.open("wb", buffering=0)
            self._mpv_log_handle.write(("Opening service: " + channel.name + "\n").encode("utf-8"))
            self._zap_log_handle.write(("Tuning service: " + channel.name + "\n").encode("utf-8"))
            self._ipc_dir = tempfile.TemporaryDirectory(prefix="tihulu-tv-mpv-")
            # Match the exact scanned service including frequency and
            # SERVICE_ID. Duplicate public channel names are common.
            exact = isolated_channel_file(
                channel, Path(self._ipc_dir.name) / "selected-channel.conf")
            self.zap = subprocess.Popen(zap_argv(exact, self.adapter),
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=self._zap_log_handle, start_new_session=True)
            time.sleep(0.8)
            if self.zap.poll() is not None:
                raise RuntimeError(f"dvbv5-zap exited before tuning. Inspect: {self.zap_log_path}")
            sock_path = str(Path(self._ipc_dir.name) / "mpv.sock")
            env = os.environ.copy()
            env.pop("WAYLAND_DISPLAY", None)
            env["XDG_SESSION_TYPE"] = "x11"
            env["SDL_VIDEODRIVER"] = "x11"
            env["GDK_BACKEND"] = "x11"
            self.player = subprocess.Popen(player_argv(channel, window_id, hwdec, sock_path, renderer),
                              stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                              stderr=self._mpv_log_handle, start_new_session=True, env=env)
            # The ServiceFilter rewrites PAT to advertise only the selected
            # service. Forcing MPV's program property before the first PAT/PMT
            # is parsed can fail prematurely, so let it auto-select the one
            # service from the verified filtered stream.
            os.set_blocking(self.player.stdin.fileno(), False)
            self._player_queue = queue.Queue(maxsize=128)
            self._writer_thread = threading.Thread(target=self._write_player, daemon=True,
                                                    name="tihulu-tv-mpv-writer")
            self._writer_thread.start()
            self.thread = threading.Thread(target=self._pump, daemon=True, name="tihulu-tv-dvb")
            self.thread.start()
            self.emit("status", "Tuning " + channel.name +
                      " · waiting for actual MPEG-TS packets, PAT and PMT")
        except BaseException:
            self.stop()
            raise

    def _select_program(self, service_id: int, sock_path: str):
        """Choose DVB service by its actual MPEG-TS program ID, not list order."""
        until = time.monotonic() + 12
        while time.monotonic() < until and not self.stop_flag.is_set():
            if self.player and self.player.poll() is not None:
                return
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(1.2)
                    client.connect(sock_path)
                    client.sendall((json.dumps({"command": ["set_property", "program", service_id]}) + "\n").encode())
                    message = client.recv(8192).decode("utf-8", "replace")
                    if '"error":"success"' in message.replace(" ", ""):
                        self.emit("status", f"Selected MPEG-TS service {service_id}")
                        return
            except (OSError, ValueError):
                pass
            time.sleep(0.4)
        if not self.stop_flag.is_set():
            self.emit("warning", "MPV program switch not confirmed; verify video matches selected channel")

    def _write_player(self):
        """Write *all* bytes of a TS chunk or explicitly report a dropped queue.

        A single nonblocking os.write can write only part of a chunk; silently
        ignoring that result would create continuity errors inside our app.
        """
        fd = self.player.stdin.fileno()
        while not self.stop_flag.is_set():
            try:
                chunk = self._player_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            data = memoryview(chunk)
            try:
                while data and not self.stop_flag.is_set():
                    try:
                        n = os.write(fd, data)
                        if n > 0:
                            data = data[n:]
                        else:
                            raise BrokenPipeError()
                    except BlockingIOError:
                        select.select([], [fd], [], 0.25)
            except (BrokenPipeError, OSError, ValueError):
                if not self.stop_flag.is_set():
                    self.emit("error", self._mpv_exit_error())
                break
            finally:
                self._player_queue.task_done()

    def _pump(self):
        dvr = None
        failure = False
        try:
            dvr = os.open(f"/dev/dvb/adapter{self.adapter}/dvr0", os.O_RDONLY | os.O_NONBLOCK)
            service_filter = ServiceFilter(self.channel.service_id if self.channel else None)
            self._queue_drop_count = 0
            started = time.monotonic()
            with tempfile.TemporaryDirectory(prefix="tihulu-tv-") as tmp:
                clip = None
                start = time.monotonic()
                total = 0
                while not self.stop_flag.is_set():
                    if self.zap.poll() is not None:
                        raise RuntimeError(f"DVB tuner process stopped. Log: {self.zap_log_path}")
                    if self.player and self.player.poll() is not None:
                        raise RuntimeError(self._mpv_exit_error())
                    if time.monotonic() - started > 15:
                        if service_filter.seen_packets == 0:
                            raise RuntimeError("No MPEG-TS packets received in 15 seconds. "
                                               "Check DVB lock/antenna and " + str(self.zap_log_path))
                        if not service_filter.ready:
                            raise RuntimeError("Selected DVB service ID not found in PAT/PMT "
                                               "after 15 seconds. Rescan this frequency or "
                                               "check channel SERVICE_ID. MPV log: " + str(self.mpv_log_path))
                    readable, _, _ = select.select([dvr], [], [], 0.25)
                    if not readable:
                        continue
                    try:
                        buf = os.read(dvr, 188 * 512)
                    except BlockingIOError:
                        continue
                    if not buf:
                        continue
                    buf = service_filter.feed(buf)
                    if not self._stream_verified and service_filter.ready and service_filter.seen_packets:
                        self._stream_verified = True
                        self.emit("verified_stream", {
                            "channel":self.channel.name,
                            "service_id":self.channel.service_id,
                            "packets":service_filter.seen_packets,
                            "note":"Real DVB transport packets and service tables observed. "
                                   "Video/audio decoding not independently confirmed."
                        })
                    if not buf:
                        continue
                    if self.mobile_stream is not None:
                        self.mobile_stream.offer(buf)
                    if self.player and self.player.poll() is None:
                        try:
                            self._player_queue.put_nowait(buf)
                        except queue.Full:
                            # Never block DVR reads; make packet loss explicit.
                            self._queue_drop_count += 1
                            if self._queue_drop_count == 1 or self._queue_drop_count % 100 == 0:
                                self.emit("warning", f"MPV TS queue overflow: {self._queue_drop_count} chunks dropped. "
                                                     f"Check {self.mpv_log_path} and receiver UCB; try x11-compat.")
                    with self._lock:
                        mode, page = self.caption_mode, self.page
                        source, target, model = self.source_lang, self.target_lang, self.model
                    if mode == "off":
                        if clip:
                            clip.close()
                            clip = None
                        continue
                    if clip is None:
                        clip = open(Path(tmp) / "segment.ts", "wb")
                        start, total = time.monotonic(), 0
                    clip.write(buf)
                    total += len(buf)
                    if time.monotonic() - start >= 12 or total >= 24 * 1024 * 1024:
                        clip.close()
                        clip = None
                        if not self._pending:
                            self._pending = True
                            path = str(Path(tmp) / "segment.ts")
                            data = Path(path).read_bytes()
                            sid = self.channel.service_id if self.channel else None
                            threading.Thread(target=self._decode, args=(data, mode, page, source, target, model, sid),
                                             daemon=True, name="tihulu-tv-captions").start()
                        # If analysis is slower than reception, skip this segment.
                if clip:
                    clip.close()
        except (OSError, RuntimeError) as exc:
            failure = True
            self.emit("error", str(exc))
        finally:
            if dvr is not None:
                os.close(dvr)
            # Do NOT overwrite a meaningful no-lock/PAT/PMT/MPV error with
            # the old generic "TV capture ended" message.
            if not failure:
                self.emit("status", "TV capture stopped" if self.stop_flag.is_set()
                          else "TV stream closed; inspect tuner and playback logs")

    def _decode(self, data, mode, page, source, target, model, service_id):
        try:
            from .captions import decode_segment
            result = decode_segment(data, mode=mode, page=page, source=source,
                                    target=target, model=model, service_id=service_id)
            if result.get("original"):
                self.emit("caption", result)
            elif result.get("error"):
                self.emit("warning", result["error"])
        except Exception as exc:
            self.emit("warning", "Caption engine: " + str(exc)[:180])
        finally:
            self._pending = False

    def stop(self):
        self.stop_flag.set()
        self.stop_mobile_video()
        for proc in (self.player, self.zap):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
        self.player, self.zap = None, None
        for attr in ("_mpv_log_handle", "_zap_log_handle"):
            handle = getattr(self, attr)
            if handle:
                handle.close()
                setattr(self, attr, None)
        if self._ipc_dir:
            self._ipc_dir.cleanup()
            self._ipc_dir = None
        if self.thread and self.thread.is_alive() and threading.current_thread() != self.thread:
            self.thread.join(timeout=1.0)
        if self._writer_thread and self._writer_thread.is_alive() and threading.current_thread() != self._writer_thread:
            self._writer_thread.join(timeout=1.0)
        if self.lockfile is not None:
            fcntl.flock(self.lockfile, fcntl.LOCK_UN)
            os.close(self.lockfile)
            self.lockfile = None
        self.emit("status", "Receiver released")
