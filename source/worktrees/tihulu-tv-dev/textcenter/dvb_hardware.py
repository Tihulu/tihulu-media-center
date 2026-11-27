"""Read-only Linux DVB diagnostics for Hauppauge WinTV-soloHD 01589.

No tuning, firmware loading, module changes or TV service interruption.
USB vendor 2040 identifies Hauppauge, not a proven model 01589;
a frontend path doesn't imply the claimed USB device owns it.
"""
from __future__ import annotations
from pathlib import Path
import platform
import shutil

DVB_TOOLS=("dvbv5-scan","dvbv5-zap","dvb-fe-tool","ffmpeg","dvbsnoop")
FIRMWARE_CANDIDATES=("dvb-demod-si2168-b40-01.fw","dvb-demod-si2168-d60-01.fw")


def _read(path:Path,limit=100)->str:
    try:return path.read_text(encoding="utf-8",errors="replace").strip()[:limit]
    except OSError:return ""


def diagnose_dvb(*, usb_root:Path|None=None, dvb_root:Path|None=None,
                 class_root:Path|None=None, firmware_root:Path|None=None,
                 which=None, system_name=None)->dict:
    system=system_name or platform.system()
    usbs=Path("/sys/bus/usb/devices") if usb_root is None else Path(usb_root)
    frontends=Path("/dev/dvb") if dvb_root is None else Path(dvb_root)
    dvb_class=Path("/sys/class/dvb") if class_root is None else Path(class_root)
    firm=Path("/lib/firmware") if firmware_root is None else Path(firmware_root)
    lookup=which or shutil.which
    hauppauge=[]
    if system=="Linux" and usbs.is_dir():
        try: entries=sorted(usbs.iterdir())
        except OSError: entries=[]
        for entry in entries:
            vid=_read(entry/"idVendor").lower()
            if vid!="2040": continue
            pid=_read(entry/"idProduct").lower()
            product=_read(entry/"product",100) or "Hauppauge USB device"
            hauppauge.append({
                "usb_path":entry.name[:100],
                "usb_id":"2040:"+pid,
                "product":product,
                "is_solohd_identified":"solohd" in product.lower().replace("-","").replace(" ",""),
            })
    connected=[]
    if system=="Linux" and frontends.is_dir():
        try:paths=sorted(frontends.glob("adapter*/frontend*"))[:16]
        except OSError:paths=[]
        for path in paths:
            ident=path.parent.name+"/"+path.name
            class_name=path.parent.name.replace("adapter","dvb")+".frontend"+path.name.replace("frontend","")
            node=dvb_class/class_name
            # sysfs names vary by driver/kernel; never equate adapter0 to Hauppauge
            connected.append({
                "frontend":ident,
                "kernel_name":_read(node/"name") or "Not reported",
                "driver":_read(node/"device"/"uevent",160) or "Driver not verified",
                "ownership_verified":False,
                "lock_verified":False,
            })
    firmware={name:(firm/name).is_file() for name in FIRMWARE_CANDIDATES}
    tools={name:bool(lookup(name)) for name in DVB_TOOLS}
    return {
        "platform":system,
        "hauppauge_usb":hauppauge,
        "dvb_frontends":connected,
        "firmware_candidates":firmware,
        "tools":tools,
        "model_requested":"Hauppauge WinTV-soloHD 01589 (DVB-T/T2/C)",
        "model_confirmed":any(x["is_solohd_identified"] for x in hauppauge),
        "broadcast_locked":False,
        "teletext_decoder_connected":False,
        "service_scan_enabled":False,
        "note":"Passive checks only. USB manufacturer is not proof of soloHD model or frontend ownership; verified reception requires driver, firmware, tuner lease, DVB service lock and TS/Teletext parser.",
    }
