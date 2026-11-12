"""Read-only Kaffeine-native DVB receiver and source-configuration diagnostics.

Never opens any DVB device, writes user settings, retunes the tuner or kills
a competing process. Distinguishes missing frontends, bad permissions,
another owner, and configured-source mismatches.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess


def _read_configs(file: Path):
    result = {"path": str(file), "exists": file.is_file(), "devices": []}
    if not file.is_file():
        return result
    try:
        data = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        result["read_error"] = "Cannot read Kaffeine config.dvb"
        return result
    current = None
    item = None
    for line in data.splitlines():
        line = line.strip()
        if line == "[device]":
            current = {"frontend_name": None, "sources": []}
            result["devices"].append(current)
            item = None
        elif line == "[config]" and current is not None:
            item = {"name": None, "scan_source": None}
            current["sources"].append(item)
        elif "=" in line:
            key, value = (x.strip() for x in line.split("=", 1))
            # Kaffeine's device data contains IDs and other personal device
            # metadata; expose only human-readable frontend & source names.
            if key == "frontendName" and current is not None:
                current["frontend_name"] = value[:100]
            elif key == "name" and item is not None:
                item["name"] = value[:100]
            elif key == "scanSource" and item is not None:
                item["scan_source"] = value[:120]
    return result


def inspect(home: Path | None = None, dev: Path | None = None):
    home = Path.home() if home is None else Path(home)
    dev = Path("/dev/dvb") if dev is None else Path(dev)
    launcher = home / ".local/bin/tihulu-kaffeine"
    binary = home / ".local/opt/tihulu-kaffeine/bin/kaffeine"
    scan = home / ".local/opt/tihulu-kaffeine/share/kaffeine/scanfile.dvb"
    devices = sorted(dev.glob("adapter*/frontend*")) if dev.is_dir() else []
    all_nodes = sorted(p for p in dev.glob("adapter*/*") if p.is_file() or p.is_char_device()) if dev.is_dir() else []
    paths = [str(p) for p in devices]
    result = {
        "backend": "Kaffeine native DVBv5; no WebUSB or w_scan_cpp",
        "launcher_installed": launcher.is_file(),
        "native_kaffeine_binary": binary.is_file(),
        "native_scanfile": {"path": str(scan), "exists": scan.is_file(),
                            "bytes": scan.stat().st_size if scan.is_file() else None},
        "frontend_devices": paths,
        "frontend_permissions": [
            {"path": str(p), "readable": os.access(p, os.R_OK),
             "writable": os.access(p, os.W_OK)} for p in devices
        ],
        "frontend_busy": "unknown",
        "frontend_owner_pids": [],
        "configured_sources": _read_configs(home / ".local/share/kaffeine/config.dvb"),
        "checked_device_files_without_opening": True,
        "expected_test_multiplexes_mhz": [538, 586, 626],
        "config_hint": ("TV > Configure Television > Device 1: DVB-C No Source; "
                        "DVB-T2 Autoscan; keep the previous terrestrial Name "
                        "matching your saved channel source"),
        "note": "Does not tune, inspect RF quality or change USB permissions",
    }
    if all_nodes and shutil.which("fuser"):
        try:
            p = subprocess.run(["fuser", *map(str, all_nodes)],
                text=True, capture_output=True, timeout=4, check=False)
            pids = sorted({int(v) for v in p.stdout.split() if v.isdecimal()})
            result["frontend_owner_pids"] = pids
            # A silent fuser is not proof of no owner (e.g. hidepid or ACL).
            result["frontend_busy"] = bool(pids) if p.returncode in (0, 1) else "unknown"
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not devices:
        result["hint"] = "No /dev/dvb frontend: reconnect WinTV USB and check driver/firmware"
    elif not all(os.access(p, os.R_OK | os.W_OK) for p in devices):
        result["hint"] = "Frontend access denied: inspect user video group and /dev/dvb permissions"
    elif result["frontend_busy"] is True:
        result["hint"] = "Another process owns a DVB node; close competing TV/SDR tools"
    elif not result["configured_sources"]["devices"]:
        result["hint"] = "No saved Kaffeine device source; configure DVB-T2 and save"
    elif all(not d["sources"] for d in result["configured_sources"]["devices"]):
        result["hint"] = "All saved Kaffeine device sources empty; enable DVB-T2 source"
    elif not binary.is_file():
        result["hint"] = "Native Kaffeine build missing; reinstall the fork"
    else:
        result["hint"] = ("Compare the current DVB-T2 source Name with your saved "
                          "channel source. If identical, check tuner ownership and debug logs")
    return result


def main(argv=None):
    print(json.dumps(inspect(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
