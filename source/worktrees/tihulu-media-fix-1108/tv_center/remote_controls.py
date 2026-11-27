"""Strictly allowlisted native TIHULU player controls for paired mobile UI.

The caption sidecar only sends MPRIS D-Bus commands to an already-running
native player; it NEVER owns a second DVB/SDR tuner or a television encoder.
"""
from __future__ import annotations
import re
import shutil
import subprocess


COMMANDS = {
    "play":("Play","/Player"),
    "pause":("Pause","/Player"),
    "stop":("Stop","/Player"),
    "next":("Next","/Player"),
    "previous":("Prev","/Player"),
    "volume":("VolumeSet","/Player"),
    "tv_channel":("PlayChannel","/Television"),
}
DEST="org.mpris.MediaPlayer2.tihulu_media_center"


def native_player_command(action: str, params: dict) -> dict:
    if action not in COMMANDS:
        raise ValueError("Unsupported native player command")
    if not isinstance(params,dict):
        raise ValueError("Invalid remote player options")
    if shutil.which("dbus-send") is None:
        raise RuntimeError("Native D-Bus command unavailable on host")
    method,path=COMMANDS[action]
    command=[
        "dbus-send","--session","--print-reply","--reply-timeout=2000",
        "--dest="+DEST,path,"org.freedesktop.MediaPlayer."+method,
    ]
    if action=="volume":
        volume=params.get("value")
        if type(volume) is not int or not 0<=volume<=100:
            raise ValueError("Volume must be an integer 0–100")
        command.append("int32:"+str(volume))
    if action=="tv_channel":
        channel=params.get("channel")
        if (not isinstance(channel,str) or not 1<=len(channel.strip())<=90
                or not re.fullmatch(r"[^\r\n\x00-\x1f]{1,90}",channel.strip())):
            raise ValueError("Invalid native TV channel name or number")
        command.append("string:"+channel.strip())
    try:
        result=subprocess.run(
            command, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=3, check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Native player did not respond to remote command") from exc
    if result.returncode != 0:
        raise RuntimeError("Native Kaffeine did not accept the remote command")
    return {"ok":True, "action":action,
            "device":"host",
            "note":"Accepted by D-Bus; actual playback is verified separately"}
