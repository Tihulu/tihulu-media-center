"""Source-attributed offline transcript persistence and *real* local translation.

No placeholder translations: Argos models must be installed for the selected
language pair. Original and translated text are stored separately. Captions
can be exported as SRT/VTT, including later off-line translation.
"""
from __future__ import annotations
from datetime import datetime,timezone
import importlib.util
import json
import os
import subprocess
import sys
import re
import sqlite3
import uuid

from .compute import LANGUAGES,validate_language
from .core import Store,clean_text,utc_now


class TranslatorUnavailable(RuntimeError):
    pass


def installed_translation_pairs() -> list[dict]:
    if importlib.util.find_spec("argostranslate") is None:
        return []
    try:
        import argostranslate.translate as translate
        languages=translate.get_installed_languages()
        pairs=[]
        for source in languages:
            if source.code not in LANGUAGES:continue
            for target in languages:
                if target.code not in LANGUAGES or target.code==source.code:
                    continue
                try:
                    source.get_translation(target)
                except (ValueError,LookupError,AttributeError):
                    continue
                pairs.append({"source":source.code,"target":target.code,
                              "engine":"argos_offline"})
        return pairs
    except (ImportError,RuntimeError,OSError):
        return []


def translation_devices() -> dict:
    """Real Argos package/pair availability, separate from speech readiness."""
    pairs=installed_translation_pairs()
    cuda=False
    try:
        import ctranslate2
        cuda=ctranslate2.get_cuda_device_count()>0
    except (ImportError,OSError,RuntimeError,ValueError):
        pass
    return {
        "pairs":pairs,
        "cpu_available":bool(pairs),
        "gpu_available":bool(pairs) and cuda,
        "npu_available":False,
        "npu_note":"No verified NPU translator backend; ASR NPU support is separate",
        "engines":["argos_cpu","argos_cuda" if cuda else "argos_cuda_unavailable"],
        "no_automatic_download":True,
    }


# Run CTranslate2 CUDA in its own Python process: its device choice is
# initialized on import, and never changes the main server process's CPU
# Argos translation setting. Source text is sent over stdin, NOT argv.
_GPU_WORKER = """
import json,sys
import argostranslate.translate as argos
r=json.load(sys.stdin)
langs={x.code:x for x in argos.get_installed_languages()}
src,dst=langs[r['source']],langs[r['target']]
result=src.get_translation(dst).translate(r['text'])
json.dump({'translated':result},sys.stdout)
"""


def translate_offline(text:str,source:str,target:str,backend:str="auto")->str:
    source,target=validate_language(source),validate_language(target)
    if backend not in ("auto","cpu","gpu","npu"):
        raise ValueError("Translator backend must be auto, cpu, gpu or npu")
    if not isinstance(text,str) or not text.strip() or len(text)>12000:
        raise ValueError("Translation text must be 1–12000 characters")
    if source==target:
        return text
    devices=translation_devices()
    if backend=="npu":
        raise TranslatorUnavailable("No tested NPU translation engine/model installed")
    if backend=="auto":
        backend="gpu" if devices["gpu_available"] else "cpu"
    if backend=="gpu":
        if not devices["gpu_available"]:
            raise TranslatorUnavailable("CUDA CTranslate2 GPU translation unavailable or models missing")
        env=os.environ.copy()
        env["ARGOS_DEVICE_TYPE"]="cuda"
        env["TRANSFORMERS_OFFLINE"]="1"
        env["HF_HUB_OFFLINE"]="1"
        try:
            output=subprocess.run([sys.executable,"-c",_GPU_WORKER],
                input=json.dumps({"text":text,"source":source,"target":target}).encode("utf-8"),
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                timeout=55,env=env,check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise TranslatorUnavailable("CUDA translation subprocess unavailable") from exc
        if output.returncode!=0 or len(output.stdout)>64000:
            raise TranslatorUnavailable("Local CUDA translation failed")
        try:translated=json.loads(output.stdout)["translated"]
        except (ValueError,KeyError,TypeError) as exc:
            raise TranslatorUnavailable("Invalid local CUDA translation result") from exc
        if not isinstance(translated,str) or not translated.strip():
            raise TranslatorUnavailable("CUDA translation produced no text")
        return translated[:12000]
    try:
        import argostranslate.translate as translate
        languages={x.code:x for x in translate.get_installed_languages()}
        source_lang=languages[source]
        target_lang=languages[target]
        model=source_lang.get_translation(target_lang)
        output=model.translate(text)
    except (ImportError,KeyError,AttributeError,ValueError,LookupError) as exc:
        raise TranslatorUnavailable("Argos Translate model for "+
            source+" → "+target+" is not installed") from exc
    if not isinstance(output,str) or not output.strip():
        raise TranslatorUnavailable("Translation engine did not return text")
    return output[:12000]


class TranscriptStore:
    def __init__(self,store:Store):
        self.store=store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS captions (
                    id TEXT PRIMARY KEY, session TEXT NOT NULL, medium TEXT NOT NULL,
                    source_id TEXT NOT NULL, original_language TEXT NOT NULL,
                    original_text TEXT NOT NULL, translated_language TEXT,
                    translated_text TEXT, translator_engine TEXT,
                    compute_backend TEXT NOT NULL, started_seconds REAL NOT NULL,
                    ended_seconds REAL NOT NULL, captured_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS captions_recent
                    ON captions(session,started_seconds);
            """)

    def add(self,*,session:str,medium:str,source_id:str,language:str,
            text:str,backend:str,start:float,end:float,
            translated=None,target=None,translation_engine=None)->str:
        if not isinstance(session,str) or not re.fullmatch(r"[0-9a-f]{32}",session):
            raise ValueError("Invalid session")
        if medium not in ("fm","dab","dvb_tv"):
            raise ValueError("Invalid stream medium")
        if language not in (*LANGUAGES,"und") or (target is not None and target not in LANGUAGES):
            raise ValueError("Unsupported subtitle language")
        if type(start) not in (int,float) or type(end) not in (int,float) or not (0<=start<end<86400):
            raise ValueError("Invalid subtitle timing")
        original=clean_text(text,3000)
        if not original:
            raise ValueError("Empty speech transcript")
        row={
            "id":uuid.uuid4().hex,"session":session,"medium":medium,
            "source_id":clean_text(source_id,120),"original_language":language,
            "original_text":original,
            "translated_language":target if isinstance(translated,str) and translated.strip() else None,
            "translated_text":clean_text(translated,12000) if isinstance(translated,str) and translated.strip() else None,
            "translator_engine":(translation_engine or "argos_offline") if translated else None,
            "compute_backend":clean_text(backend,80),"started_seconds":float(start),
            "ended_seconds":float(end),"captured_at":utc_now(),
        }
        with self.store.connect() as db:
            db.execute("""INSERT INTO captions
              (id,session,medium,source_id,original_language,original_text,
               translated_language,translated_text,translator_engine,compute_backend,
               started_seconds,ended_seconds,captured_at)
              VALUES(:id,:session,:medium,:source_id,:original_language,:original_text,
                :translated_language,:translated_text,:translator_engine,:compute_backend,
                :started_seconds,:ended_seconds,:captured_at)""",row)
        return row["id"]

    def list(self,session:str|None=None,limit:int=200)->list[dict]:
        limit=max(1,min(limit,2000))
        with self.store.connect() as db:
            if session:
                return [dict(x) for x in db.execute(
                    "SELECT * FROM captions WHERE session=? ORDER BY started_seconds LIMIT ?",
                    (session,limit)).fetchall()]
            return [dict(x) for x in db.execute(
                "SELECT * FROM captions ORDER BY captured_at DESC LIMIT ?",
                (limit,)).fetchall()]

    def translate_later(self,caption_id:str,target_language:str,
                        translator=None,backend:str="auto")->dict:
        target=validate_language(target_language)
        with self.store.connect() as db:
            row=db.execute("SELECT * FROM captions WHERE id=?",(caption_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown caption")
        original=row["original_language"]
        if original not in LANGUAGES:
            raise TranslatorUnavailable("Original speech language unknown; select language before translating")
        if translator is None:
            result=translate_offline(row["original_text"],original,target,backend=backend)
        else:
            result=translator(row["original_text"],original,target)
        with self.store.connect() as db:
            db.execute("""UPDATE captions SET translated_language=?,translated_text=?,
                 translator_engine=? WHERE id=?""",
                       (target,result,("argos_"+backend if backend!="auto" else "argos_auto")
                        if target!=original else "identity",caption_id))
            updated=db.execute("SELECT * FROM captions WHERE id=?",(caption_id,)).fetchone()
            return dict(updated)

    @staticmethod
    def _clock(seconds,separator=",")->str:
        millis=round(seconds*1000)
        hours,millis=divmod(millis,3_600_000)
        mins,millis=divmod(millis,60_000)
        secs,millis=divmod(millis,1000)
        return f"{hours:02}:{mins:02}:{secs:02}{separator}{millis:03}"

    def export(self,session:str,*,fmt:str="srt",translated:bool=False)->str:
        if fmt not in ("srt","vtt"):raise ValueError("Only SRT or VTT export")
        items=self.list(session,limit=2000)
        lines=["WEBVTT",""] if fmt=="vtt" else []
        for i,row in enumerate(items,1):
            original=row["original_text"]
            translated_text=row["translated_text"] if translated else None
            content=translated_text if translated_text else (
                f"[UNTRANSLATED {row['original_language'].upper()}] {original}"
                if translated else original
            )
            # Make untrusted source text a single plain subtitle line.
            content=re.sub(r"[\x00-\x1f\x7f]"," ",content).strip()
            if fmt=="srt":lines.append(str(i))
            sep="." if fmt=="vtt" else ","
            lines.append(self._clock(row["started_seconds"],sep)+
                " --> "+self._clock(row["ended_seconds"],sep))
            lines.extend((content,""))
        return "\n".join(lines)
