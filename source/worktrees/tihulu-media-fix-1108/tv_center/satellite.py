"""Satellite dish setup and DVB-S/S2 scan profiles for real DVB frontends.

Linux DVB-S/S2 frontend, satellite LNB voltage/tone and (optional) DiSEqC
are required. Do NOT wire coax directly to a Pi GPIO, HDMI or USB port.
"""
from __future__ import annotations

SATELLITES = {
    "S42E0": "Türksat 42.0°E",
    "S13E0": "Hot Bird 13.0°E",
    "S19E2": "Astra 19.2°E",
    "S7E0": "Eutelsat 7.0°E",
}

LNB_TYPES = ("UNIVERSAL",)  # Safe, common starting profile; custom LNB not guessed.
DISEQC_PORTS = {None: None, 0: "0c", 1: "1c", 2: "2c", 3: "3c"}


def satellite_scan_args(adapter: int, satellite: str = "S42E0",
                        diseqc_port: int | None = None, lnb: str = "UNIVERSAL") -> list[str]:
    if type(adapter) is not int or not 0 <= adapter <= 15:
        raise ValueError("Invalid DVB adapter")
    if satellite not in SATELLITES:
        raise ValueError("Unknown satellite orbital position")
    if lnb not in LNB_TYPES:
        raise ValueError("Unsupported LNB preset")
    if diseqc_port not in DISEQC_PORTS:
        raise ValueError("DiSEqC port must be 0–3 or disabled")
    args = ["w_scan_cpp", "-f", "s", "-s", satellite, "-a", str(adapter),
            "-l", lnb, "-R", "1", "-T", "1", "-E", "1", "-x"]
    if diseqc_port is not None:
        args += ["-D", DISEQC_PORTS[diseqc_port]]
    return args


def satellite_followup_args(adapter: int, initial, destination, diseqc_port=None,
                            lnb="UNIVERSAL") -> list[str]:
    if diseqc_port not in DISEQC_PORTS or lnb not in LNB_TYPES:
        raise ValueError("Invalid satellite LNB or DiSEqC")
    args = ["dvbv5-scan", "-a", str(adapter), "-l", lnb, "-T", "5",
            "-o", str(destination)]
    if diseqc_port is not None:
        args += ["-S", str(diseqc_port)]
    return args + [str(initial)]


def satellite_hardware_note():
    return ("Requires a separately powered Linux DVB-S/S2 tuner with LNB coax input "
            "(or compatible SAT>IP network receiver). Raspberry Pi GPIO is 3.3 V "
            "logic and cannot power/demodulate a satellite LNB. Never attach "
            "13/18 V LNB feeds directly to GPIO.")
