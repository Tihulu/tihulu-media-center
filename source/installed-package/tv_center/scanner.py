"""Opt-in DVB-T/T2/C/S2 scan, with real progress and passive signal readings.

Country-based terrestrial/cable sweeps use w_scan_cpp. Satellite uses the
selected orbital position and a real DVB-S/S2 frontend, not country
frequencies. A successfully resolved channel file is atomically promoted.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from .satellite import SATELLITES, satellite_scan_args, satellite_followup_args

PROFILES = {
    "DE": {"name":"Germany"},
    "TR": {"name":"Türkiye"},
}
MODES = {"t":"Antenna · DVB-T/T2", "c":"Cable · DVB-C", "s":"Satellite · DVB-S/S2"}

class ScanError(RuntimeError):
    pass


def scan_commands(country: str, medium: str, adapter: int,
                  transponder_file: Path, channel_file: Path,
                  satellite: str = "S42E0", diseqc_port: int | None = None):
    if country not in PROFILES or medium not in MODES or type(adapter) is not int or not 0 <= adapter <= 15:
        raise ValueError("Invalid scan country, delivery mode or DVB adapter")
    if medium == "s":
        return (satellite_scan_args(adapter, satellite, diseqc_port),
                satellite_followup_args(adapter, transponder_file, channel_file,
                                        diseqc_port=diseqc_port))
    return (
        ["w_scan_cpp", "-f", medium, "-c", country, "-a", str(adapter),
         "-R", "1", "-T", "1", "-E", "1", "-x", "-v"],
        ["dvbv5-scan", "-a", str(adapter), "-C", country,
         "-T", "2", "-o", str(channel_file), str(transponder_file)],
    )


def check_dependencies():
    return {name: bool(shutil.which(name)) for name in
            ("w_scan_cpp", "dvbv5-scan", "fuser")}


def parse_scan_progress(line: str):
    """Accept genuine RF tuning reports, never C++ source line numbers or dates."""
    line = re.sub(r"[\x00-\x08\x0b-\x1f\x7f\x1b]", "", line).strip()[-320:]
    if not line:
        return None
    # w_scan_cpp typically emits "538000: (time: 00:..." or
    # "... f = 538000 kHz". Log timestamps/line numbers are NOT frequencies.
    khz = re.search(r"^\s*(\d{5,7}):\s*\(time:", line)
    if not khz:
        khz = re.search(r"\bf\s*=\s*(\d{5,7})\s*kHz\b", line, re.I)
    hz = re.search(r"\b(?:frequency|freq)\s*[:=]\s*(\d{8,10})\s*(?:Hz)?\b", line, re.I)
    mhz = re.search(r"\b(?:frequency|freq)\s*[:=]\s*(\d{2,4}(?:\.\d+)?)\s*MHz\b", line, re.I)
    frequency = None
    if khz:
        value = int(khz.group(1)) / 1000
        if 40 <= value <= 3000:
            frequency = f"{value:.3f} MHz"
    elif hz:
        value = int(hz.group(1)) / 1_000_000
        if 40 <= value <= 3000:
            frequency = f"{value:.3f} MHz"
    elif mhz:
        value = float(mhz.group(1))
        if 40 <= value <= 3000:
            frequency = f"{value:.3f} MHz"
    # dvbv5-scan prints "Scanning frequency #1 573000000" and
    # "Service Foo, provider Bar", not merely "frequency=...".
    if frequency is None:
        scan_hz = re.search(r"\bScanning frequency #\d+\s+(\d{8,10})\b", line, re.I)
        if scan_hz and 40 <= int(scan_hz.group(1))/1000000 <= 3000:
            frequency = f"{int(scan_hz.group(1))/1000000:.3f} MHz"
    name = re.search(r"(?:new channel|service(?:_name)?|channel|program)\s*[:=]\s*(.{2,90})", line, re.I)
    if not name:
        name = re.search(r"^Service\s+(.{2,90}?)(?:,\s*provider\b|:\s*(?:digital|radio)|$)", line, re.I)
    lock = re.search(r"\bLock\s*\((0x[0-9a-f]+)\)", line, re.I)
    lock_mask = int(lock.group(1),16) if lock else None
    cn = re.search(r"\bC/N=\s*(-?[0-9.]+)\s*dB",line,re.I)
    strength = re.search(r"\bSignal=\s*(-?[0-9.]+)\s*(dBm|%)",line,re.I)
    ucb = re.search(r"\bUCB=\s*(\d+)",line,re.I)
    return {"kind": "log", "text": line,
            "frequency_reported": frequency,
            "service_reported": name.group(1).strip() if name else None,
            "demod_lock": bool(lock_mask & 0x10) if lock_mask is not None else None,
            "cn_db": float(cn.group(1)) if cn else None,
            "signal_reading": (strength.group(1)+" "+strength.group(2)) if strength else None,
            "uncorrected_blocks": int(ucb.group(1)) if ucb else None}


class IncrementalScanLog:
    """Read only newly appended scanner stderr; never replay the same tail."""
    def __init__(self, path):
        self.path = Path(path)
        self.offset = 0
        self.pending = b""

    def poll(self):
        try:
            size = self.path.stat().st_size
            if size < self.offset:
                self.offset, self.pending = 0, b""
            with self.path.open("rb") as f:
                f.seek(self.offset)
                data = f.read(65536)
                self.offset = f.tell()
        except OSError:
            return []
        # Progress may use CR rather than LF; both are valid delimiters.
        parts = re.split(rb"[\r\n]", self.pending + data)
        self.pending = parts.pop()[-4096:]
        return [item.decode("utf-8", "replace") for item in parts if item.strip()]


def passive_signal(adapter: int):
    """Best-effort read-only frontend statistic sampling; never retunes."""
    if not shutil.which("dvb-fe-tool"):
        return {"available": False, "reason": "dvb-fe-tool not installed"}
    try:
        p = subprocess.run(["dvb-fe-tool", "-a", str(adapter), "-m"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=1.6, check=False)
        raw = p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        raw = (exc.stdout or b"").decode("utf-8", "replace")
    except (OSError, ValueError) as exc:
        return {"available": False, "reason": str(exc)[:100]}
    from .core import parse_signal_log
    parsed = parse_signal_log(raw)
    if not parsed["lock_readings"]:
        return {"available": False, "reason": "Driver did not expose usable simultaneous frontend statistics"}
    parsed["available"] = True
    return parsed


class AutoScanner:
    def __init__(self):
        self.cancelled = threading.Event()
        self.running = False
        self.process = None
        self._mutex = threading.Lock()
        self._latest = {}

    def cancel(self):
        self.cancelled.set()
        with self._mutex:
            proc = self.process
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def _stage(self, args, stdout: Path, stderr: Path, limit: int,
               notify=None, stage=1, adapter=0, partial_file=None):
        if self.cancelled.is_set():
            raise ScanError("Scan cancelled")
        with stdout.open("wb") as out, stderr.open("wb") as err:
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=err, start_new_session=True)
            with self._mutex:
                self.process = proc
            started = time.monotonic()
            last_tail = 0
            last_signal = 0
            last_names = set()
            log_reader = IncrementalScanLog(stderr)
            try:
                while proc.poll() is None:
                    if self.cancelled.is_set():
                        proc.terminate()
                        raise ScanError("Scan cancelled; previous channel list preserved")
                    if time.monotonic() - started > limit:
                        proc.terminate()
                        raise ScanError("Scan timed out; previous channel list preserved")
                    now = time.monotonic()
                    if now - last_tail >= 0.65:
                        last_tail = now
                        # Follow only fresh stderr bytes. The old tail reader
                        # replayed previous lines indefinitely and showed fake
                        # scanner restarts / misleading frequencies in the UI.
                        for line in log_reader.poll():
                            obj = parse_scan_progress(line)
                            if obj and notify:
                                notify({"stage": stage, **obj})
                        if partial_file and partial_file.is_file():
                            from .core import read_channels
                            for channel in read_channels([partial_file]):
                                key = (channel.name, channel.service_id, channel.frequency)
                                if key not in last_names:
                                    last_names.add(key)
                                    if notify: notify({"stage": stage, "kind":"found",
                                                       "channel": channel.name,
                                                       "frequency": channel.frequency,
                                                       "delivery": channel.delivery,
                                                       "count": len(last_names)})
                    if now - last_signal >= 5.0:
                        last_signal = now
                        # The scanner owns the frontend. A second process
                        # cannot reliably collect simultaneous DVB statistics.
                        if notify: notify({"stage": stage, "kind":"signal",
                                           "metrics":{"available":False,
                                           "reason":"Scanner owns the DVB frontend; measure C/N/UCB after scanning"}})
                    time.sleep(0.35)
                # Process the final unread bytes too, including trailing log
                # output which arrived after the last polling interval.
                for line in log_reader.poll():
                    obj = parse_scan_progress(line)
                    if obj and notify:
                        notify({"stage": stage, **obj})
                if self.cancelled.is_set():
                    raise ScanError("Scan cancelled; previous channel list preserved")
                if proc.returncode != 0:
                    message = stderr.read_text(errors="replace")[-600:]
                    raise ScanError(f"Scanner exited {proc.returncode}: {message}")
            finally:
                with self._mutex:
                    self.process = None
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(timeout=3)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()

    def run_from_initial_file(self, path, country="DE", medium="t",
                              adapter=0, directory=None, notify=None):
        """Kaffeine-style scan source: scan an operator-selected DVBv5 table.

        A region/scanfile is only *tuning input*: never present the
        frequencies/services as received until dvbv5-scan decodes them.
        Save the same profile file as the automatic scan, atomically.
        """
        from .core import read_channels
        if self.running:
            raise ScanError("Another scan is already active")
        if country not in PROFILES or medium not in ("t","c") or type(adapter) is not int or not 0<=adapter<=15:
            raise ValueError("Invalid DVB source profile")
        source=Path(path).expanduser()
        if not source.is_file() or not 0<source.stat().st_size<=2_000_000:
            raise ScanError("Select a valid local DVBv5 initial tuning file (up to 2 MB)")
        required=("dvbv5-scan","fuser")
        missing=[x for x in required if not shutil.which(x)]
        if missing:
            raise ScanError("Missing DVB scanning dependencies: "+", ".join(missing))
        frontend=f"/dev/dvb/adapter{adapter}/frontend0"
        if not Path(frontend).exists():
            raise ScanError("Selected Linux DVB frontend missing")
        if subprocess.run(["fuser","-s",frontend],timeout=3,check=False).returncode==0:
            raise ScanError("Tuner busy: stop live TV/Kaffeine/Tvheadend before scanning")
        output=Path(directory or Path.home()/".config/tihulu-tv-center").expanduser()
        output.mkdir(parents=True,exist_ok=True)
        target=output/("channels-"+country+"-"+medium+".conf")
        self.running=True
        self.cancelled.clear()
        try:
            with tempfile.TemporaryDirectory(prefix="tihulu-dvb-source-") as tmp:
                root=Path(tmp)
                staged=root/"channels.conf"
                if notify:notify({"stage":1,"kind":"status","text":
                    "Scanning actual tuner using selected DVBv5 source: "+source.name})
                argv=["dvbv5-scan","-a",str(adapter),"-C",country,
                      "-T","2","-o",str(staged),str(source)]
                self._stage(argv,root/"scan.stdout",root/"scan.log",900,
                            notify,1,adapter,staged)
                scanned=read_channels([staged])
                if not scanned:
                    raise ScanError("No services decoded from selected scan source. "
                                    "This is not a channel list: check antenna, "
                                    "transmitter region, DVB mode and RF lock.")
                for pos,c in enumerate(scanned):
                    if notify:notify({"stage":2,"kind":"found","channel":c.name,
                                      "frequency":c.frequency,"delivery":c.delivery,
                                      "count":pos+1})
                # Never clobber the user's previous successful scan on failure.
                atomic=output/(target.name+".staging")
                atomic.write_bytes(staged.read_bytes())
                os.replace(atomic,target)
                if notify:notify({"stage":3,"kind":"complete","count":len(scanned)})
                return {"country":country,"medium":medium,"path":str(target),
                        "channels":len(scanned),
                        "frequencies":len({c.frequency for c in scanned}),
                        "method":"operator-selected-dvbv5-source"}
        finally:
            self.running=False

    def run(self, country="DE", medium="t", adapter=0, directory=None, notify=None,
            satellite="S42E0", diseqc_port=None):
        if self.running:
            raise ScanError("Another scan is already active")
        if country not in PROFILES or medium not in MODES or type(adapter) is not int or not 0 <= adapter <= 15:
            raise ValueError("Invalid scan profile")
        if medium == "s" and satellite not in SATELLITES:
            raise ValueError("Unsupported satellite")
        deps = check_dependencies()
        if not all(deps.values()):
            raise ScanError("Missing: " + ", ".join(k for k, ok in deps.items() if not ok))
        frontend = f"/dev/dvb/adapter{adapter}/frontend0"
        if not Path(frontend).exists():
            raise ScanError("Selected Linux DVB frontend missing")
        if subprocess.run(["fuser", "-s", frontend], timeout=3,
                          check=False).returncode == 0:
            raise ScanError("Tuner busy. Stop TV/Kaffeine/Tvheadend before scanning.")
        # This is an explicit action. A satellite-mode capable frontend
        # has to be connected; the tuner itself rejects unsupported systems.
        output = Path(directory or Path.home()/".config/tihulu-tv-center").expanduser()
        output.mkdir(parents=True, exist_ok=True)
        suffix = country + "-" + medium + ("-" + satellite if medium == "s" else "")
        target = output / ("channels-" + suffix + ".conf")
        self.running = True
        self.cancelled.clear()
        self._latest.clear()
        try:
            with tempfile.TemporaryDirectory(prefix="tihulu-dvbscan-") as tmp:
                root = Path(tmp)
                initial = root / "transponders.conf"
                channels_file = root / "channels.conf"
                first, second = scan_commands(country, medium, adapter, initial,
                                               channels_file, satellite, diseqc_port)
                if notify: notify({"stage":1, "kind":"status", "text":"Discovering real RF transponders"})
                self._stage(first, initial, root/"search.log", 1200, notify, 1, adapter)
                if not initial.is_file() or initial.stat().st_size < 20:
                    raise ScanError("No RF transponders found by w_scan_cpp. "
                                    "Check antenna connection, broadcast coverage, "
                                    "DVB-T/T2 delivery mode and frontend lock. "
                                    "Previous channel list preserved.")
                if notify: notify({"stage":2, "kind":"status", "text":"Resolving services from discovered transponders"})
                self._stage(second, root/"channels.stdout", root/"channels.log", 900,
                            notify, 2, adapter, channels_file)
                from .core import read_channels
                discovered = read_channels([channels_file])
                if not discovered:
                    raise ScanError("dvbv5-scan did not decode any real services. "
                                    "Review scan log, local coverage and antenna; "
                                    "previous channel list retained.")
                for n, c in enumerate(discovered):
                    if notify: notify({"stage":2, "kind":"found", "channel":c.name,
                                       "frequency":c.frequency, "delivery":c.delivery,
                                       "count":n+1})
                # Preserve the owner's channel preferences in a separate file.
                staged = output / (target.name + ".staging")
                staged.write_bytes(channels_file.read_bytes())
                os.replace(staged, target)
                if notify: notify({"stage":3, "kind":"complete", "count":len(discovered)})
                return {"country": country, "medium": medium, "satellite":satellite,
                        "path":str(target), "channels":len(discovered),
                        "frequencies":len({c.frequency for c in discovered})}
        finally:
            self.running = False
