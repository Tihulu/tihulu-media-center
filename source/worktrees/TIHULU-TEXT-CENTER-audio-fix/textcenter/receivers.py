"""Passive receiver inventory for TIHULU TEXT CENTER.

Linux sysfs and executable presence ONLY. Does not claim RF reception,
open SDR devices, query rtl_test, retune, scan, or start a background process.
"""
from __future__ import annotations

from pathlib import Path
import platform
import shutil
from .core import utc_now
from .conflicts import find_receiver_conflicts

RTL2832U_ID = ("0bda", "2838")
DECODER_BINARIES = (
    "rtl_test", "rtl_fm", "rtl_power", "redsea", "welle-cli", "rtl_433",
    "dvbv5-scan", "dvbv5-zap", "direwolf", "multimon-ng", "fldigi", "dream",
)

def _read(path: Path, max_chars: int = 100) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()[:max_chars]
    except (OSError, UnicodeError):
        return ""

def receiver_inventory(*, sys_usb_root: Path | None = None,
                       sys_dvb_root: Path | None = None,
                       executable_lookup=None, system_name: str | None = None) -> dict:
    """Read-only inventory. Device identification is based on shared USB IDs.

    This identifies candidates, NOT trusted identity, permission, signal lock,
    current tuner ownership, decoder operation or real received text.
    """
    system = system_name or platform.system()
    usb = Path("/sys/bus/usb/devices") if sys_usb_root is None else Path(sys_usb_root)
    dvb = Path("/dev/dvb") if sys_dvb_root is None else Path(sys_dvb_root)
    which = executable_lookup or shutil.which
    devices: list[dict] = []
    if system == "Linux" and usb.is_dir():
        try:
            children = sorted(usb.iterdir(), key=lambda x: x.name)
        except OSError:
            children = []
        for entry in children:
            vid = _read(entry / "idVendor").lower()
            pid = _read(entry / "idProduct").lower()
            if (vid, pid) != RTL2832U_ID:
                continue
            devices.append({
                "usb_path": entry.name[:80],
                "usb_id": "0bda:2838",
                "manufacturer": _read(entry / "manufacturer", 80) or "Not reported",
                "product": _read(entry / "product", 80) or "RTL2832U-compatible receiver",
                "state": "usb_present_not_tuned",
            })
    dvb_frontends: list[str] = []
    if system == "Linux" and dvb.is_dir():
        try:
            adapters = list(dvb.glob("adapter*/frontend*"))
        except OSError:
            adapters = []
        dvb_frontends = [f"{p.parent.name}/{p.name}"[:90] for p in sorted(adapters)[:16]]
    installed = {name: bool(which(name)) for name in DECODER_BINARIES}
    # Injected fixture USB roots must not accidentally report the host's
    # actual /proc process list as belonging to a simulated receiver.
    conflicts = find_receiver_conflicts() if sys_usb_root is None and system == "Linux" else []
    availability = ("sysfs_unavailable" if system != "Linux" or not usb.is_dir()
                    else "usb_candidate_present" if devices else "no_supported_usb_candidate")
    return {
        "checked_at": utc_now(),
        "platform": system,
        "status": availability,
        "rtl_usb_count": len(devices),
        "rtl_usb_devices": devices,
        "dvb_frontends": dvb_frontends,
        "decoders": installed,
        "receiver_conflicts": conflicts,
        "tuner_may_be_busy": bool(conflicts),
        "rds_pipeline_available": bool(devices) and installed["rtl_fm"] and installed["redsea"],
        "active_capture": False,
        "connected_decoder": False,
        "signal_verified": False,
        "note": (
            "Passive USB/tool inventory only. RDS/DAB decoding is not connected. "
            "A shared USB ID cannot prove receiver brand, driver permissions, "
            "live signal, tuner availability or recording ownership."
        ),
    }
