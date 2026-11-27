"""Read-only Linux TV/SDR hardware inventory for native TIHULU Hardware tab.

Never opens a USB/DVB frontend, claims SDR, changes driver binding or stops
other applications. Presence, permissions and receiver ownership are
independent: a USB listing cannot prove a usable RF demodulator.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from datetime import datetime, timezone

_USB_NAME = re.compile(r"^(?:[0-9]+-[0-9.]+)$")
_DVB_NAME = re.compile(r"^adapter[0-9]+$")
_FRONTEND = re.compile(r"^frontend[0-9]+$")
_RADIO_HINT = re.compile(r"rtl.?sdr|rtl283[28]|r820t|airspy|hackrf|sdrplay|"
                         r"hauppauge|wintv|dvb|digital.?tv|em28178|"
                         r"funcube|sdr dongle",re.I)


def _read(path: Path) -> str:
    try:
        if path.is_symlink():
            return ""
        if path.stat().st_size > 8192:
            return ""
        return path.read_text(encoding="utf-8",errors="replace").strip()[:300]
    except (OSError,UnicodeError,ValueError):
        return ""


def _access(path: Path) -> str:
    if not path.exists():
        return "node missing"
    if os.access(path,os.R_OK | os.W_OK):
        return "user read/write"
    if os.access(path,os.R_OK):
        return "user read only"
    return "no user access"


def inspect(*, usb_root="/sys/bus/usb/devices", dvb_root="/dev/dvb",
            usb_nodes="/dev/bus/usb", sys_dvb="/sys/class/dvb"):
    usb=[]
    base=Path(usb_root)
    try:
        candidates=sorted(base.iterdir(),key=lambda p:p.name)
    except OSError:
        candidates=[]
    for entry in candidates:
        if not _USB_NAME.fullmatch(entry.name):
            continue
        # /sys/bus/usb/devices entries are symlinks to kernel-maintained
        # device trees; follow this fixed sysfs root, not user input.
        vendor=_read(entry/"idVendor").lower()
        product=_read(entry/"idProduct").lower()
        if not re.fullmatch(r"[0-9a-f]{4}",vendor or "") or not re.fullmatch(
                r"[0-9a-f]{4}",product or ""):
            continue
        name=_read(entry/"product") or _read(entry/"manufacturer") or "USB device"
        manufacturer=_read(entry/"manufacturer")
        bus=_read(entry/"busnum")
        device=_read(entry/"devnum")
        node=None
        if bus.isdigit() and device.isdigit() and 1<=int(bus)<=999 and 1<=int(device)<=999:
            node=Path(usb_nodes)/f"{int(bus):03d}"/f"{int(device):03d}"
        known=(vendor=="0bda" and product in {"2832","2838","283f"}) or (
            vendor=="2040") or (vendor=="1d50" and product in {"6089","604b"})
        is_receiver=known or bool(_RADIO_HINT.search(name+" "+manufacturer))
        usb.append({
            "id":entry.name,"kind":"USB receiver" if is_receiver else "USB peripheral",
            "name":name[:120],"vidpid":vendor+":"+product,
            "path":str(node) if node else "unknown",
            "permission":_access(node) if node else "node unknown",
            "receiver_candidate":is_receiver,
            "physical":"connected (kernel USB enumeration)",
            "ownership":"not checked; receiver session reported separately"})
    frontend=[]
    db=Path(dvb_root)
    try:
        adapters=sorted((p for p in db.iterdir() if _DVB_NAME.fullmatch(p.name)),
                        key=lambda p:p.name)
    except OSError:
        adapters=[]
    for adapter in adapters:
        try:
            children=sorted((p for p in adapter.iterdir() if _FRONTEND.fullmatch(p.name)),
                            key=lambda p:p.name)
        except OSError:
            children=[]
        for node in children:
            if not node.exists():continue
            sysname="dvb"+adapter.name.removeprefix("adapter")+"."+node.name
            frontend.append({
                "id":str(node),"kind":"DVB frontend",
                "name":_read(Path(sys_dvb)/sysname/"name") or "DVB frontend",
                "path":str(node),"permission":_access(node),
                "physical":"registered by kernel (RF lock unverified)",
                "ownership":"not checked; frontend may be used by another process"})
    return {"timestamp":datetime.now(timezone.utc).isoformat(),
            "platform":"linux" if os.name=="posix" else "unsupported",
            "usb":usb[:150],"dvb":frontend[:30],
            "summary":{"usb_count":len(usb),"receiver_candidates":sum(
                1 for device in usb if device["receiver_candidate"]),
                "dvb_frontends":len(frontend)},
            "note":"Detection never claims hardware. USB present != driver ready; "
                   "frontend present != RF lock; access != exclusive ownership."}


def check_owners(snapshot):
    """Bounded, explicit read-only fuser report for DVB and SDR USB nodes.

    Even if no process is listed, firmware/driver/kernel locks may exist.
    Never kill, SIGTERM, unbind, reset, or disconnect another process.
    """
    dvb=[x["path"] for x in snapshot.get("dvb",[]) if
         isinstance(x.get("path"),str) and re.fullmatch(
             r"/dev/dvb/adapter[0-9]+/frontend[0-9]+",x["path"])]
    usb=[x["path"] for x in snapshot.get("usb",[]) if
         x.get("receiver_candidate") and isinstance(x.get("path"),str) and
         re.fullmatch(r"/dev/bus/usb/[0-9]{3}/[0-9]{3}",x["path"])]
    nodes=list(dict.fromkeys(dvb[:6]+usb[:6]))
    if not nodes:
        return "No DVB/SDR device nodes to inspect. USB presence is not proof of ownership."
    fuser=shutil.which("fuser")
    if not fuser:
        return "fuser unavailable (install psmisc); no process was terminated."
    reports=[]
    for path in nodes:
        try:
            outcome=subprocess.run([fuser,"-v",path],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,timeout=3,check=False)
            details=(outcome.stderr+outcome.stdout).decode(
                "utf-8","replace").strip()[:2200]
            if outcome.returncode not in (0,1):
                details+="\nRead-only owner check returned "+str(outcome.returncode)
            reports.append(path+"\n"+(details or "No visible owner; other sessions may be hidden"))
        except (OSError,subprocess.TimeoutExpired) as exc:
            reports.append(path+"\nOwner check unavailable: "+type(exc).__name__)
    return "\n\n".join(reports)[:12000]


def main(argv=None):
    parser=argparse.ArgumentParser(description="Read-only Linux TV/SDR inventory")
    parser.add_argument("--owners",action="store_true",
                        help="Explicitly query DVB and SDR USB node owners using read-only fuser")
    args=parser.parse_args(argv)
    snapshot=inspect()
    if args.owners:
        snapshot["owner_report"]=check_owners(snapshot)
    print(json.dumps(snapshot,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
