"""Best-effort, read-only Linux SDR contention checks.

Never kill, stop, retune or claim other processes. Linux /proc visibility
depends on uid/hidepid/container boundaries. This is an additional fail-closed
check for known active receiver programs, not a cross-app tuner lease broker.
"""
from __future__ import annotations
import os
from pathlib import Path
import sys

SDR_NAMES = frozenset({
    "readsb", "dump1090", "dump1090-fa", "dump1090-mutabil",
    "rtl_1090", "rtl_adsb", "rtl_fm", "rtl_tcp", "rtl_433", "rtl_sdr",
    "gqrx", "welle-io", "welle-cli", "welle.io", "sdrangel",
    "airspy_adsb", "soapy_power", "multimon-ng",
})
SDR_PREFIXES = ("dump1090", "readsb", "rtl_", "welle", "gqrx")
SCAN_LIMIT = 2048


def _candidate_usb_nodes(usb_root: Path) -> set[str]:
    nodes = set()
    try:
        dirs = list(usb_root.iterdir())
    except OSError:
        return nodes
    for path in dirs:
        try:
            vendor = (path / "idVendor").read_text().strip().lower()
            product = (path / "idProduct").read_text().strip().lower()
            if (vendor, product) != ("0bda", "2838"):
                continue
            bus = int((path / "busnum").read_text().strip())
            dev = int((path / "devnum").read_text().strip())
            nodes.add(f"/dev/bus/usb/{bus:03d}/{dev:03d}")
        except (OSError, ValueError):
            continue
    return nodes


def find_receiver_conflicts(*, proc_root: Path = Path("/proc"),
                            sys_usb_root: Path = Path("/sys/bus/usb/devices"),
                            self_pid: int | None = None) -> list[dict]:
    """Detect common SDR/ADS-B program names or open RTL USB file descriptors.

    Returns only a short process name and reason; never command lines or data.
    Other unrecognized SDR programs might be invisible, so false negatives
    remain possible. Call immediately before each real receiver launch.
    """
    if sys.platform != "linux" and proc_root == Path("/proc"):
        return []
    own = os.getpid() if self_pid is None else self_pid
    nodes = _candidate_usb_nodes(sys_usb_root)
    try:
        pids = sorted((p for p in proc_root.iterdir() if p.name.isdigit()),
                      key=lambda p: int(p.name))[:SCAN_LIMIT]
    except OSError:
        return []
    conflicts = []
    for p in pids:
        if int(p.name) == own:
            continue
        try:
            name = (p / "comm").read_text(encoding="utf-8", errors="replace").strip()[:64]
        except OSError:
            continue
        if not name:
            continue
        known = name.lower() in SDR_NAMES or name.lower().startswith(SDR_PREFIXES)
        usb_open = False
        if nodes:
            try:
                handles = list((p / "fd").iterdir())[:256]
            except OSError:
                handles = []
            for handle in handles:
                try:
                    if os.readlink(handle) in nodes:
                        usb_open = True
                        break
                except OSError:
                    pass
        if known or usb_open:
            conflicts.append({
                "pid": int(p.name), "process": name,
                "reason": "rtl_usb_handle_open" if usb_open else "known_receiver_process",
            })
            if len(conflicts) >= 20:
                break
    return conflicts
