"""Read-only DAB service/DLS/MOT bridge to an ALREADY-RUNNING welle-cli.

Only fixed 127.0.0.1:7979 GET /mux.json, /channel and /slide/<safe sid>.
Never starts welle-cli, posts /channel, retunes, or opens the SDR. Explicit
user refresh only, no background polling. Archive requires a known channel
frequency and original decoder-reported time. Journaline is not implemented.
"""
from __future__ import annotations

import base64
from datetime import datetime,timezone
import json
import re
import urllib.request

from .core import Store, clean_text, utc_now
from .media import MediaStore,MAX_IMAGE

# Verified channel presets used by this initial bridge; other channels can be
# viewed, but are NOT archived with a fabricated receive frequency.
DAB_HZ={"5C":178_352_000,"11D":222_064_000}
BASE="http://127.0.0.1:7979"
MUX_LIMIT=350_000


class DABError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def _local_get(path:str,limit:int)->bytes:
    if not (path in ("/mux.json","/channel") or re.fullmatch(r"/slide/0x[0-9a-fA-F]{4,8}",path)):
        raise DABError("Unsupported local welle-cli path")
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
    req=urllib.request.Request(BASE+path,method="GET",headers={"Accept":"application/json,image/png,image/jpeg,text/plain"})
    try:
        with opener.open(req,timeout=1.3) as response:
            if response.status!=200:
                raise DABError("welle-cli returned non-200 response")
            raw=response.read(limit+1)
    except (OSError,ValueError) as exc:
        raise DABError("welle-cli local web receiver not reachable on port 7979") from exc
    if len(raw)>limit:
        raise DABError("welle-cli response exceeds size limit")
    return raw


def _label(value,limit=160):
    if isinstance(value,str):
        return clean_text(value,limit)
    if isinstance(value,dict):
        for key in ("utf8label","utf8_label","label","text","shortlabel"):
            if key in value:
                return _label(value[key],limit)
    return ""


def _safe_sid(value):
    if isinstance(value,str) and re.fullmatch(r"0x[0-9a-fA-F]{4,8}",value):
        return value
    return None


def _real_timestamp(epoch):
    if type(epoch) not in (int,float) or not 1_500_000_000 <= epoch <= 4_100_000_000:
        return None
    try:
        return datetime.fromtimestamp(epoch,timezone.utc).isoformat(timespec="seconds")
    except (ValueError,OverflowError,OSError):
        return None


def parse_mux(payload:bytes,channel:str)->dict:
    if len(payload)>MUX_LIMIT:
        raise DABError("DAB service JSON too large")
    try:obj=json.loads(payload)
    except (ValueError,UnicodeError) as exc:
        raise DABError("Invalid welle-cli JSON") from exc
    if not isinstance(obj,dict):
        raise DABError("Invalid DAB mux object")
    software=(obj.get("receiver") or {}).get("software") if isinstance(obj.get("receiver"),dict) else None
    name=software.get("name","") if isinstance(software,dict) else ""
    if not isinstance(name,str) or not name.lower().startswith("welle"):
        raise DABError("Refusing non-welle-cli local endpoint")
    services=obj.get("services")
    if not isinstance(services,list) or len(services)>128:
        raise DABError("Invalid or excessive DAB service records")
    if not re.fullmatch(r"(?:[5-9]|1[0-3])[A-F]",channel):
        channel="UNKNOWN"
    ensemble=_label((obj.get("ensemble") or {}).get("label") if isinstance(obj.get("ensemble"),dict) else None)
    items=[]
    for svc in services:
        if not isinstance(svc,dict):
            continue
        sid=_safe_sid(svc.get("sid"))
        if not sid:continue
        items.append({
            "sid":sid,
            "name":_label(svc.get("label")) or "Unlabelled decoded service",
            "dls":_label(svc.get("dls_label"),512),
            "dls_received_at":_real_timestamp(svc.get("dls_time")),
            "mot_received_at":_real_timestamp(svc.get("mot_time")),
            "program_type":_label(svc.get("ptystring"),80),
            "audio_advertised":bool(svc.get("url_mp3")),
        })
    return {
        "receiver":"already_running_welle_cli","channel":channel,
        "frequency_hz":DAB_HZ.get(channel),
        "ensemble":ensemble,"services":items,
        "checked_at":utc_now(),"radio_not_retuned":True,
        "not_official_alert":True,
    }


class DABReader:
    def __init__(self,store:Store,*,fetcher=None):
        self.store=store
        self.media=MediaStore(store)
        self.fetcher=fetcher or _local_get

    def refresh(self,*,include_images:bool=True)->dict:
        channel=self.fetcher("/channel",64).decode("ascii",errors="ignore").strip().upper()
        mux=parse_mux(self.fetcher("/mux.json",MUX_LIMIT),channel)
        imported=0
        saved=0
        freq=mux["frequency_hz"]
        for service in mux["services"][:48]:
            if not freq:continue
            sid=service["sid"]
            source=f"welle:{channel}:{sid}"
            if service["dls"] and service["dls_received_at"]:
                event={
                    "source_id":source, "title":"DAB+ DLS dynamic label",
                    "body":service["dls"],"station":service["name"],
                    "language":"und","frequency_hz":freq,"medium":"dab_dls",
                    "provenance":"welle-cli mux.json; read-only local DAB decoder bridge",
                    "received_at":service["dls_received_at"],
                }
                self.store.import_data({"schema_version":1,"events":[event]})
                imported+=1
            if include_images and service["mot_received_at"]:
                try:
                    raw=self.fetcher("/slide/"+sid,MAX_IMAGE)
                    if len(raw)<40:continue
                    self.media.save(
                        medium="dab_mot",station=service["name"],source_id=source,
                        frequency_hz=freq,received_at=service["mot_received_at"],
                        provenance="welle-cli MOT slideshow; read-only local receiver",
                        image_base64=base64.b64encode(raw).decode())
                    saved+=1
                except (DABError,OSError,ValueError):
                    continue
        mux["imported_dls"]=imported
        mux["saved_mot_images"]=saved
        if not freq:
            mux["archive_notice"]="Unknown channel frequency; displayed data not archived"
        return mux
