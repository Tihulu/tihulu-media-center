"""On-demand, single-shot FM *spectrum* survey using rtl_power.

This finds candidate RF energy peaks only, not named stations or decoded
RadioText. It does not auto-tune to peaks, retune an existing lease, preempt
Flight Radar, or claim RF access in the background. User must explicitly start.

Linux + single RTL2832U + rtl_power required. The scan uses the same flock
path as FM RDS; third-party tools do not honor it, so we also refuse known
conflicting SDR processes and USB handle owners.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import fcntl
import io
import math
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import tempfile
from threading import Event, Lock, Thread
import time
import uuid

from .conflicts import find_receiver_conflicts
from .receivers import receiver_inventory

MAX_SURVEY_BYTES = 256_000
MAX_SURVEY_SECONDS = 18
MIN_FM = 87_500_000
MAX_FM = 108_000_000

# Fixed, non-user-editable survey profiles. Measurements are energy peaks,
# never validated station names or decoded text. HF profiles require Q-branch.
SURVEY_BANDS = {
    "fm": {"label":"FM broadcast / RDS", "bounds":(87_500_000,108_000_000),
           "range":"87.5M:108M:125k", "direct_sampling":False},
    "dab": {"label":"DAB Band III / DLS / Journaline / MOT", "bounds":(174_000_000,240_000_000),
           "range":"174M:240M:250k", "direct_sampling":False},
    "aprs": {"label":"Amateur VHF / APRS energy (EU candidate region)", "bounds":(144_000_000,146_000_000),
           "range":"144M:146M:12k", "direct_sampling":False},
    "drm": {"label":"DRM MF/HF energy survey", "bounds":(1_000_000,22_000_000),
           "range":"1M:22M:50k", "direct_sampling":True},
    "rtty": {"label":"HF RTTY / Radiotelex energy survey", "bounds":(2_000_000,18_000_000),
           "range":"2M:18M:25k", "direct_sampling":True},
    "navtex": {"label":"NAVTEX LF/MF energy survey (not decoding)", "bounds":(450_000,560_000),
           "range":"450k:560k:2k", "direct_sampling":True},
    "weatherfax": {"label":"HF WeatherFAX energy survey", "bounds":(2_000_000,18_000_000),
           "range":"2M:18M:25k", "direct_sampling":True},
}


# Published European DAB Band III nominal centre raster (Hz). This is a
# frequency lookup, NOT a database of currently broadcasting ensembles.
# Candidate spectral peaks within a nominal 1.536-MHz DAB block can share
# the same label. Without DAB synchronization no block is "received".
DAB_BLOCKS = (
    ("5A", 174_928_000), ("5B", 176_640_000), ("5C", 178_352_000), ("5D", 180_064_000),
    ("6A", 181_936_000), ("6B", 183_648_000), ("6C", 185_360_000), ("6D", 187_072_000),
    ("7A", 188_928_000), ("7B", 190_640_000), ("7C", 192_352_000), ("7D", 194_064_000),
    ("8A", 195_936_000), ("8B", 197_648_000), ("8C", 199_360_000), ("8D", 201_072_000),
    ("9A", 202_928_000), ("9B", 204_640_000), ("9C", 206_352_000), ("9D", 208_064_000),
    ("10A", 209_936_000), ("10B", 211_648_000), ("10C", 213_360_000), ("10D", 215_072_000),
    ("11A", 216_928_000), ("11B", 218_640_000), ("11C", 220_352_000), ("11D", 222_064_000),
    ("12A", 223_936_000), ("12B", 225_648_000), ("12C", 227_360_000), ("12D", 229_072_000),
    ("13A", 230_784_000), ("13B", 232_496_000), ("13C", 234_208_000),
    ("13D", 235_776_000), ("13E", 237_488_000), ("13F", 239_200_000),
)
DAB_HALF_BANDWIDTH_HZ = 768_000


def dab_blocks_for_peaks(peaks: list[dict]) -> list[dict]:
    """Group RF energy peaks by nearest nominal Band III block, never station identity.

    1.536 MHz is the nominal occupied DAB frequency block; a peak anywhere
    inside it is only an ambiguous possible block candidate. An energy-only
    scan cannot confirm OFDM synchronization, FIC or an ensemble/service.
    """
    grouped: dict[str, dict] = {}
    for peak in peaks:
        hz = peak.get("frequency_hz")
        if type(hz) is not int:
            continue
        block, center = min(DAB_BLOCKS, key=lambda pair: abs(pair[1] - hz))
        if abs(center - hz) > DAB_HALF_BANDWIDTH_HZ:
            continue
        item = grouped.setdefault(block, {
            "block": block, "center_frequency_hz": center,
            "center_frequency_mhz": round(center / 1_000_000, 3),
            "peak_count": 0, "peak_frequencies_mhz": [],
            "max_above_median_db": 0.0,
            "verification": "nominal_raster_match_only",
        })
        item["peak_count"] += 1
        item["peak_frequencies_mhz"].append(round(hz / 1_000_000, 3))
        item["max_above_median_db"] = max(
            item["max_above_median_db"], float(peak.get("above_median_db", 0.0))
        )
    for item in grouped.values():
        item["peak_frequencies_mhz"].sort()
        item["max_above_median_db"] = round(item["max_above_median_db"], 1)
    return sorted(grouped.values(), key=lambda row: (-row["max_above_median_db"], row["block"]))


def survey_band(band: str) -> dict:
    if not isinstance(band,str) or band not in SURVEY_BANDS:
        raise ValueError("Unsupported spectrum band; use a fixed preset")
    return SURVEY_BANDS[band]


class SurveyError(RuntimeError):
    pass


def build_survey_command(executable: str, band: str = "fm") -> list[str]:
    """Single-shot rtl_power band scan with fixed allow-listed arguments."""
    profile = survey_band(band)
    command = [executable, "-d", "0", "-f", profile["range"], "-i", "2s", "-1"]
    if profile["direct_sampling"]:
        # In the osmocom rtl_power build -D requests direct sampling. Some
        # forks use other syntax; those are not guaranteed compatible.
        command.append("-D")
    return command


def parse_power_csv(payload: str, *, limit: int = 24, band: str = "fm") -> dict:
    """Convert bounded rtl_power CSV measurements to *candidate* spectrum peaks.

    Relative power can be affected by gain, front-end filters and noise.
    No measurement identifies a broadcast service or confirms successful RDS.
    """
    profile = survey_band(band)
    min_hz,max_hz = profile["bounds"]
    if len(payload.encode("utf-8")) > MAX_SURVEY_BYTES:
        raise ValueError("Spectrum CSV exceeds the capture limit")
    bins: list[tuple[float, float]] = []
    sweeps = 0
    for row in csv.reader(io.StringIO(payload)):
        if len(row) < 8:
            continue
        try:
            low, high, step = map(float, row[2:5])
            values = [float(s) for s in row[6:]]
        except (TypeError, ValueError):
            continue
        if not values or step < 1000 or step > 1_000_000:
            continue
        if not (math.isfinite(low) and math.isfinite(high) and math.isfinite(step)):
            continue
        sweeps += 1
        for idx, power in enumerate(values[:1000]):
            center = low + (idx + 0.5) * step
            if min_hz <= center <= max_hz and math.isfinite(power):
                bins.append((center, power))
    if not bins:
        return {"sweeps": sweeps, "bins_analyzed":0, "candidates": [],
                "note":"No usable measurements for selected RF band"}
    # More than one CSV row may cover the same bin; keep strongest observed.
    # This is for discovery only, not a dBm calibration.
    merged: dict[int, float] = {}
    for hz, power in bins:
        # Keep measured bin centers separate: 100-kHz rounding can collapse
        # adjacent bin centers (e.g. 87.55 and 87.65 MHz on a 100-kHz grid).
        key = int(round(hz))
        merged[key] = max(power, merged.get(key, -1e9))
    frequencies = sorted(merged)
    readings = [merged[hz] for hz in frequencies]
    baseline = statistics.median(readings)
    deviation = statistics.median(abs(x - baseline) for x in readings)
    threshold = baseline + max(8.0, deviation * 3)
    peaks = []
    for index, hz in enumerate(frequencies):
        reading = merged[hz]
        prev = merged.get(frequencies[index-1], -1e9) if index else -1e9
        following = merged.get(frequencies[index+1], -1e9) if index + 1 < len(frequencies) else -1e9
        # Local maxima only (flat plateaux get one candidate).
        if reading >= threshold and reading >= prev and reading > following:
            peaks.append({
                "frequency_hz": hz,
                "frequency_mhz": round(hz / 1_000_000, 3),
                "relative_power_db": round(reading, 1),
                "above_median_db": round(reading - baseline, 1),
                "verification": "unidentified_rf_energy",
            })
    peaks.sort(key=lambda x: x["above_median_db"], reverse=True)
    candidates = peaks[:min(limit, 24)]
    result = {
        "sweeps":sweeps,
        "bins_analyzed":len(readings),
        "relative_baseline_db":round(baseline,1),
        "threshold_above_median_db":round(threshold-baseline,1),
        "candidates":candidates,
        "note":"Candidate RF energy only; no broadcast service, RDS, DAB, NAVTEX or APRS decode is verified.",
    }
    if band == "dab":
        result["dab_blocks"] = dab_blocks_for_peaks(candidates)
        result["dab_decoder_connected"] = False
    return result


class FMSurveySupervisor:
    def __init__(self, *, rds=None, inventory=None, lookup=None,
                 conflicts=None, lock_dir: Path | None = None,
                 max_seconds: float = MAX_SURVEY_SECONDS):
        self.rds = rds
        self.inventory = inventory or receiver_inventory
        self.lookup = lookup or shutil.which
        self.conflicts = conflicts or find_receiver_conflicts
        self.lock_dir = lock_dir or Path.home()/".local/share/tihulu-text-center/.receiver-locks"
        self.max_seconds = max_seconds
        self._mutex = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._process: subprocess.Popen | None = None
        self._lock_fd: int | None = None
        self._last_poll = 0.0
        self._state = {
            "status":"idle", "active":False, "session":None, "band":"fm",
            "started_at":None, "ended_at":None, "error":None,
            "sweeps":0, "bins_analyzed":0, "candidates":[], "dab_blocks":[],
            "note":"No spectrum survey has been run",
        }

    def availability(self, band: str = "fm") -> dict:
        profile=survey_band(band)
        inv = self.inventory()
        if inv.get("platform") != "Linux":
            return {"ready":False,"reason":"RF spectrum survey requires Linux"}
        if inv.get("rtl_usb_count") != 1:
            return {"ready":False,"reason":"Exactly one RTL2832U USB candidate required"}
        if self.rds is not None and self.rds.status(heartbeat=False)["active"]:
            return {"ready":False,"reason":"An FM RDS capture is already using the receiver"}
        conflicts = self.conflicts()
        if conflicts:
            names=", ".join(sorted({p["process"] for p in conflicts}))
            return {"ready":False,"reason":
                f"Receiver may be in use by: {names}. Scan blocked to protect ongoing reception.",
                "conflicts":conflicts}
        if not self.lookup("rtl_power"):
            return {"ready":False,"reason":"rtl_power is missing (normally included with rtl-sdr)"}
        return {"ready":True,
                "reason":"Manual single-shot "+profile["label"]+" energy survey available; transmissions cannot be identified by power"}

    def _lock(self) -> None:
        self.lock_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chmod(self.lock_dir,0o700)
        flags=os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os,"O_NOFOLLOW",0)
        fd=os.open(self.lock_dir/"rtl_fm_rds.lock",flags,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise SurveyError("Receiver reserved by a cooperating Text Center capture")
        self._lock_fd=fd

    def _unlock(self) -> None:
        fd=self._lock_fd
        self._lock_fd=None
        if fd is not None:
            try:
                fcntl.flock(fd,fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def start(self, band: str = "fm") -> dict:
        profile=survey_band(band)
        with self._mutex:
            if self._state["active"]:
                raise SurveyError("A spectrum survey is already running")
            avail=self.availability(band)
            if not avail["ready"]:
                raise SurveyError(avail["reason"])
            self._lock()
            try:
                if self.conflicts() or (
                    self.rds is not None and self.rds.status(heartbeat=False)["active"]
                ):
                    raise SurveyError("Receiver was occupied during preflight; scan cancelled")
                self._state={
                    "status":"running","active":True,"session":uuid.uuid4().hex,
                    "band":band,
                    "started_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "ended_at":None,"error":None,"sweeps":0,"bins_analyzed":0,
                    "candidates":[], "dab_blocks":[], "note":"Measuring RF energy in "+profile["label"]+"; not decoding services",
                }
                self._stop.clear()
                self._last_poll=time.monotonic()
                self._thread=Thread(target=self._worker,daemon=True,name="tihulu-fm-spectrum")
                self._thread.start()
                return self._snapshot()
            except BaseException:
                self._unlock()
                self._state["active"]=False
                self._state["status"]="error"
                raise

    def _snapshot(self) -> dict:
        return {**self._state,"candidates":list(self._state["candidates"]),
                "kind":"spectrum_candidate_not_station"}

    def status(self, *, heartbeat: bool = True) -> dict:
        with self._mutex:
            if heartbeat and self._state["active"]:
                self._last_poll=time.monotonic()
            return self._snapshot()

    def stop(self, *, wait: bool = False) -> dict:
        with self._mutex:
            if self._state["active"]:
                self._stop.set()
                self._state["status"]="stopping"
            thread=self._thread
            snapshot=self._snapshot()
        if wait and thread and thread.is_alive():
            thread.join(timeout=4)
        return snapshot

    @staticmethod
    def _terminate(process: subprocess.Popen | None) -> None:
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid,signal.SIGTERM)
            process.wait(timeout=1)
        except (ProcessLookupError,ChildProcessError):
            pass
        except (OSError,subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid,signal.SIGKILL)
                process.wait(timeout=0.5)
            except (OSError,subprocess.TimeoutExpired):
                pass

    def _worker(self) -> None:
        process=None
        status="completed"
        error=None
        data={}
        try:
            binary=self.lookup("rtl_power")
            if not binary:
                raise SurveyError("rtl_power no longer installed")
            if self.conflicts() or (
                self.rds is not None and self.rds.status(heartbeat=False)["active"]
            ):
                raise SurveyError("SDR became occupied before starting rtl_power")
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                process=subprocess.Popen(
                    build_survey_command(binary, self._state["band"]),stdin=subprocess.DEVNULL,
                    stdout=stdout,stderr=stderr,start_new_session=True,close_fds=True)
                with self._mutex:
                    self._process=process
                deadline=time.monotonic()+self.max_seconds
                while process.poll() is None:
                    if self._stop.is_set():
                        status,error="cancelled","Scan stopped by user"
                        break
                    with self._mutex:
                        idle=time.monotonic()-self._last_poll
                    if idle>12:
                        status,error="cancelled","Scan stopped because the browser stopped polling"
                        break
                    if time.monotonic()>=deadline:
                        status,error="error","RF band survey exceeded its maximum time"
                        break
                    time.sleep(0.1)
                if process.poll() is None:
                    self._terminate(process)
                process.wait(timeout=1)
                if status=="completed" and process.returncode != 0:
                    stderr.seek(0)
                    snippet=stderr.read(360).decode("utf-8","replace")
                    # Avoid feeding arbitrary decoder output into exception details.
                    error=("rtl_power exited unsuccessfully. SDR may be busy or lack "
                           "permissions. "+snippet.replace("\n"," ")[:180])
                    status="error"
                if status=="completed":
                    stdout.seek(0)
                    payload=stdout.read(MAX_SURVEY_BYTES+1)
                    if len(payload)>MAX_SURVEY_BYTES:
                        raise SurveyError("Spectrum output exceeded 256 KB")
                    data=parse_power_csv(payload.decode("utf-8","replace"),band=self._state["band"])
        except (OSError,ValueError,SurveyError,subprocess.TimeoutExpired) as exc:
            status,error="error",str(exc)[:250]
        finally:
            self._terminate(process)
            with self._mutex:
                self._process=None
                self._unlock()
                self._state.update(data)
                self._state["status"]=status
                self._state["active"]=False
                self._state["ended_at"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._state["error"]=error
