"""Explicit OFFLINE post-processing of a previously saved FM/TV recording.

Never accesses RF hardware, retunes a receiver, or downloads language models.
Bounded to 10 minutes/150 MiB decoded PCM per job, one worker and 30s? per
segment speech engine timeout. Saved original text and translations remain
available in SRT/VTT after stream is stopped.
"""
from __future__ import annotations

from datetime import datetime,timezone
import os
from pathlib import Path
import shutil
import signal
import subprocess
from threading import Event,Lock,Thread
import time
import uuid

from .compute import choose_backend,detect_devices,validate_language
from .speech import transcribe_pcm,SpeechError,SAMPLE_RATE,WINDOW_BYTES,WINDOW_SECONDS
from .transcripts import TranscriptStore,translate_offline,TranslatorUnavailable

MAX_OFFLINE_SECONDS=600
MAX_INPUT_BYTES=1_073_741_824


class PostProcessError(RuntimeError):
    pass


def decode_audio_command(ffmpeg:str,file:Path) -> list[str]:
    return [ffmpeg,"-hide_banner","-loglevel","error","-nostdin",
            "-i",str(file),"-map","0:a:0","-vn","-ac","1",
            "-ar",str(SAMPLE_RATE),"-f","s16le","pipe:1"]


class RecordingTranscriber:
    def __init__(self,*,transcripts:TranscriptStore,radio,tv,
                 lookup=None,detect=None,transcriber=None,translator=None,
                 max_seconds=MAX_OFFLINE_SECONDS):
        self.transcripts=transcripts
        self.radio=radio
        self.tv=tv
        self.lookup=lookup or shutil.which
        self.detect=detect or detect_devices
        self.transcriber=transcriber or transcribe_pcm
        self.translator=translator or translate_offline
        self.max_seconds=min(MAX_OFFLINE_SECONDS,max_seconds)
        self._lock=Lock()
        self._stop=Event()
        self._thread=None
        self._process=None
        self._state={"active":False,"status":"idle","session":None,
                     "source":None,"filename":None,"segments":0,
                     "seconds_processed":0.0,"error":None,
                     "backend":None,"device":None,"language":None,
                     "target_language":None}

    def _snapshot(self):
        return dict(self._state)

    def status(self):
        with self._lock:
            return self._snapshot()

    def _lookup_file(self,medium:str,name:str):
        if medium=="fm":
            return self.radio.recording(name)
        if medium=="dvb_tv":
            return self.tv.recording(name)
        return None

    def start(self,*,medium:str,filename:str,language:str,
              target_language:str|None=None,backend:str="auto"):
        lang=validate_language(language)
        target=validate_language(target_language) if target_language else None
        if medium not in ("fm","dvb_tv"):
            raise ValueError("Only local FM/TV recordings are supported")
        if not isinstance(filename,str) or len(filename)>150:
            raise ValueError("Invalid recording filename")
        file=self._lookup_file(medium,filename)
        if not file or not file.is_file():
            raise PostProcessError("Only previously recorded local FM/TV files may be processed")
        if file.stat().st_size>MAX_INPUT_BYTES:
            raise PostProcessError("Recording exceeds the permitted input size")
        ffmpeg=self.lookup("ffmpeg")
        if not ffmpeg:
            raise PostProcessError("ffmpeg is not installed")
        profile=self.detect()
        selection=choose_backend(profile,backend)
        if not selection["ready"]:
            raise PostProcessError(selection.get("reason") or "ASR model not ready")
        with self._lock:
            if self._state["active"]:
                raise PostProcessError("A saved-recording transcription is already running")
            session=uuid.uuid4().hex
            self._stop.clear()
            self._state={
                "active":True,"status":"running","session":session,
                "source":medium,"filename":filename,"segments":0,
                "seconds_processed":0.0,"error":None,
                "backend":selection["selected"],"device":selection["detected_device"],
                "language":lang,"target_language":target,
            }
            self._thread=Thread(target=self._worker,
                args=(session,medium,file,ffmpeg,lang,target,selection["selected"],profile),
                daemon=True,name="tihulu-offline-asr")
            self._thread.start()
            return self._snapshot()

    def _worker(self,session,medium,file,ffmpeg,language,target,backend,profile):
        process=None
        status="completed"
        error=None
        elapsed=0.0
        try:
            process=subprocess.Popen(decode_audio_command(ffmpeg,file),
                stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)
            with self._lock:
                self._process=process
            assert process.stdout
            while not self._stop.is_set() and elapsed<self.max_seconds:
                pcm=process.stdout.read(WINDOW_BYTES)
                if not pcm:
                    break
                # No unbounded memory growth: process each real decoded window
                # sequentially (backpressure against ffmpeg).
                duration=len(pcm)/(SAMPLE_RATE*2)
                if duration<0.4:
                    break
                text=self.transcriber(pcm,language,backend,profile)
                if isinstance(text,str) and text.strip():
                    translated=None
                    if target:
                        try: translated=self.translator(text,language,target)
                        except (TranslatorUnavailable,ValueError,RuntimeError,ImportError) as exc:
                            with self._lock:self._state["error"]="Translation unavailable: "+str(exc)[:170]
                    self.transcripts.add(
                        session=session,medium=medium,
                        source_id="saved_recording:"+file.name,
                        language=language,text=text,backend=backend,
                        start=elapsed,end=min(self.max_seconds,elapsed+duration),
                        target=target if translated else None,
                        translated=translated)
                    with self._lock:self._state["segments"]+=1
                elapsed+=duration
                with self._lock:self._state["seconds_processed"]=round(elapsed,2)
            if self._stop.is_set():status="cancelled"
            elif elapsed>=self.max_seconds:status="limited"
            elif process.poll() not in (None,0):
                status="error"
                error="Audio decoder exited unsuccessfully"
        except (OSError,ValueError,SpeechError,PostProcessError,RuntimeError) as exc:
            status,error="error",str(exc)[:250]
        finally:
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid,signal.SIGTERM)
                    process.wait(timeout=1)
                except (OSError,subprocess.TimeoutExpired):
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except OSError:pass
            if process and process.stdout:
                process.stdout.close()
            with self._lock:
                self._process=None
                self._state["active"]=False
                self._state["status"]=status
                if error:self._state["error"]=error

    def stop(self,wait=False):
        with self._lock:
            self._stop.set()
            thread=self._thread
            result=self._snapshot()
        if wait and thread and thread.is_alive():
            thread.join(timeout=2)
        return result
