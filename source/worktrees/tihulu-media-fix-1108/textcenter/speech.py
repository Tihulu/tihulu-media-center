"""Opt-in real offline speech chunks from a shared PCM radio stream.

No fake transcripts. Whisper.cpp CLI is CPU fallback; optional Faster-Whisper
CUDA backend is used only if CTranslate2 reports a real CUDA device, matching
local model and installed package. An NPU node alone is NOT a valid ASR engine.
"""
from __future__ import annotations
import importlib.util
from functools import lru_cache
import io
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
from threading import Event,Thread,Lock
import wave

from .compute import choose_backend,detect_devices,validate_language
from .transcripts import TranscriptStore,TranslatorUnavailable,translate_offline

SAMPLE_RATE=32000
WINDOW_SECONDS=8
WINDOW_BYTES=SAMPLE_RATE*2*WINDOW_SECONDS


class SpeechError(RuntimeError):
    pass


def _wav_bytes(pcm:bytes,sample_rate:int=SAMPLE_RATE)->bytes:
    with io.BytesIO() as b:
        with wave.open(b,"wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)
        return b.getvalue()


def _whisper_cli_wav(pcm:bytes)->bytes:
    """Convert existing signed 16-bit 32-kHz mono PCM to CLI-required 16 kHz.

    Adjacent-sample averaging provides a minimal low-pass stage rather than
    simply relabeling sample rate or dropping samples with no filtering.
    """
    from array import array
    samples=array("h")
    samples.frombytes(pcm[:len(pcm)-(len(pcm)%2)])
    count=len(samples)-(len(samples)%2)
    downsampled=array("h",((int(samples[i])+int(samples[i+1]))//2
                            for i in range(0,count,2)))
    return _wav_bytes(downsampled.tobytes(),sample_rate=16000)


def _whisper_model(profile):
    p=profile["speech"]["model_path"]
    return str(p) if p else None


# Keep a single loaded CTranslate2 Whisper model across short live DVB chunks.
# Creating WhisperModel on every 6-second clip reloaded model weights and
# caused avoidable multi-second stalls even with an RTX GPU.
_faster_whisper_lock = Lock()

@lru_cache(maxsize=1)
def _cached_cuda_whisper(model_path: str):
    from faster_whisper import WhisperModel
    return WhisperModel(model_path,device="cuda",compute_type="float16",
                        local_files_only=True)


def transcribe_pcm(pcm:bytes,language:str,backend:str,profile:dict)->str:
    if not pcm:
        raise SpeechError("Empty received audio")
    if backend not in ("cpu","gpu","npu"):
        raise ValueError("Invalid compute backend")
    if language != "auto":
        validate_language(language)
    elif backend=="npu":
        raise SpeechError("Automatic speech language detection is not verified "
                          "for this NPU model; choose a source language")
    model=(_whisper_model(profile) if backend=="cpu" else
           profile["speech"].get("gpu_model_path") if backend=="gpu" else
           profile["speech"].get("npu_model_path"))
    npu_engine=profile["speech"].get("npu_engine") if backend=="npu" else None
    if not model and npu_engine!="hailo_whisper":
        raise SpeechError("Offline Whisper model for selected backend not installed")
    if backend=="npu" and npu_engine=="hailo_whisper":
        if not profile["speech"].get("ready_npu"):
            raise SpeechError("Hailo model files or device runtime not available")
        try:
            import numpy as np
            from array import array
            from hailo_apps.python.standalone_apps.speech_recognition.whisper_pipeline import WhisperPipeline
            from hailo_apps.python.standalone_apps.speech_recognition.audio_utils import (
                preprocess_audio,improve_audio)
            from hailo_apps.python.standalone_apps.speech_recognition.postprocessing import clean_transcription
            xs=array("h")
            xs.frombytes(pcm[:len(pcm)-(len(pcm)%2)])
            audio=np.array([(xs[i]+xs[i+1])/65536.0
                            for i in range(0,len(xs)-1,2)],dtype=np.float32)
            pipeline=WhisperPipeline(
                profile["speech"]["hailo_encoder_hef"],
                profile["speech"]["hailo_decoder_hef"],
                variant="base",npy_dir=profile["speech"]["hailo_npy_dir"],
                add_embed=False)
            try:
                processed,start=improve_audio(audio)
                if start is None:
                    return ""
                start_offset=max(start-0.2,0)
                mels=preprocess_audio(processed,chunk_length=pipeline.get_chunk_length(),
                                      chunk_offset=start_offset)
                outputs=[]
                for mel in mels:
                    pipeline.send_data(mel)
                    import time
                    time.sleep(.1)
                    outputs.append(pipeline.get_transcription())
                return clean_transcription(" ".join(outputs)).strip()[:3000]
            finally:
                pipeline.stop()
        except (ImportError,OSError,RuntimeError,ValueError,TypeError) as exc:
            raise SpeechError("Hailo-10H ASR inference unavailable: "+str(exc)[:200]) from exc
    if backend=="npu":
        if npu_engine!="openvino_genai" or not profile["speech"].get("ready_npu"):
            raise SpeechError("No verified local NPU Whisper model/runtime")
        try:
            import openvino_genai
            from array import array
            # OpenVINO GenAI Whisper requires normalized 16-kHz mono samples.
            # PCM source is mono signed 16-bit at 32-kHz.
            samples=array("h")
            samples.frombytes(pcm[:len(pcm)-(len(pcm)%2)])
            normalized=[(samples[i]+samples[i+1])/65536.0
                        for i in range(0,len(samples)-1,2)]
            pipe=openvino_genai.WhisperPipeline(model,"NPU")
            result=pipe.generate(normalized,max_new_tokens=120,
                                 language="<|"+language+"|>",task="transcribe")
            text=" ".join(getattr(result,"texts",[]) or []).strip()
            return text[:3000]
        except (ImportError,RuntimeError,ValueError,OSError,TypeError) as exc:
            raise SpeechError("OpenVINO NPU transcription failed: "+str(exc)[:200]) from exc
    if backend=="gpu" and profile["speech"].get("gpu_engine") == "faster_whisper_managed":
        try:
            from tv_center.cuda_faster_whisper import transcribe_cuda
            return transcribe_cuda(pcm, language, str(model))
        except (ImportError, OSError, RuntimeError, TimeoutError) as exc:
            raise SpeechError("Managed CUDA Faster-Whisper failed: "+str(exc)[:180]) from exc
    if backend=="gpu" and profile["speech"].get("gpu_engine") != "whisper_cpp_cuda":
        if importlib.util.find_spec("faster_whisper") is None:
            raise SpeechError("faster-whisper CUDA package is not installed")
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count()<1:
                raise SpeechError("CUDA ASR runtime not available")
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/"speech.wav"
                path.write_bytes(_whisper_cli_wav(pcm))
                with _faster_whisper_lock:
                    decoder=_cached_cuda_whisper(str(model))
                    segments,_=decoder.transcribe(
                        str(path),language=(None if language=="auto" else language),
                                                 beam_size=3,vad_filter=True)
                    # Faster-Whisper decodes lazily; iterate under the lock.
                    return " ".join(s.text.strip() for s in segments).strip()[:3000]
        except (ImportError,OSError,RuntimeError) as exc:
            raise SpeechError("CUDA speech backend failed: "+str(exc)[:150]) from exc
    executable=(profile["speech"].get("gpu_executable")
                if backend=="gpu" else profile["speech"]["executable"])
    if not executable:
        raise SpeechError("whisper.cpp CLI executable unavailable")
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        src=root/"speech.wav"
        out=root/"transcript"
        src.write_bytes(_whisper_cli_wav(pcm))
        argv=[executable,"-m",model,"-f",str(src),"-l",language,
              "-nt","-otxt","-of",str(out)]
        try:
            result=subprocess.run(argv,stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                  timeout=65,check=False)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise SpeechError("Local speech inference timed out or failed") from exc
        if result.returncode!=0 or not (root/"transcript.txt").is_file():
            raise SpeechError("whisper.cpp returned no successful transcript file")
        return re.sub(r"\s+"," ",(root/"transcript.txt").read_text(
            encoding="utf-8",errors="replace")[:5000]).strip()[:3000]


class SpeechPipeline:
    """One bounded queued stream with no raw audio retained after processing."""
    def __init__(self,*,store:TranscriptStore,session:str,source_id:str,
                 source_language:str,target_language:str|None,
                 backend:str="auto",profile:dict|None=None,
                 transcriber=None,translator=None,medium:str="fm",translation_backend:str="auto"):
        self.store=store
        self.session=session
        self.source_id=source_id
        if medium not in ("fm","dab","dvb_tv"):
            raise ValueError("Unsupported audio medium")
        self.medium=medium
        self.lang=validate_language(source_language)
        self.target=validate_language(target_language) if target_language else None
        self.profile=profile or detect_devices()
        self.selection=choose_backend(self.profile,backend)
        if not self.selection["ready"]:
            raise SpeechError(self.selection.get("reason") or "No configured local speech backend")
        self.backend=self.selection["selected"]
        self.transcriber=transcriber or transcribe_pcm
        self.translation_backend=translation_backend
        self.translator=translator or (
            lambda text,src,dst:translate_offline(text,src,dst,backend=translation_backend))
        self.buffer=bytearray()
        self.samples=0
        self.queue=queue.Queue(maxsize=2)
        self.stopping=Event()
        self.completed=0
        self.dropped=0
        self.last_error=None
        self.thread=Thread(target=self._worker,daemon=True,name="tihulu-speech-asr")
        self.thread.start()

    def feed(self,pcm:bytes):
        if self.stopping.is_set():return
        self.buffer.extend(pcm)
        while len(self.buffer)>=WINDOW_BYTES:
            chunk=bytes(self.buffer[:WINDOW_BYTES])
            del self.buffer[:WINDOW_BYTES]
            begin=self.samples/SAMPLE_RATE
            self.samples+=WINDOW_SECONDS*SAMPLE_RATE
            try:self.queue.put_nowait((chunk,begin,begin+WINDOW_SECONDS))
            except queue.Full:self.dropped+=1

    def _worker(self):
        while not self.stopping.is_set() or not self.queue.empty():
            try:pcm,start,end=self.queue.get(timeout=0.3)
            except queue.Empty:continue
            try:
                text=self.transcriber(pcm,self.lang,self.backend,self.profile)
                if not isinstance(text,str) or not text.strip():
                    continue
                translated=None
                if self.target:
                    try:translated=self.translator(text,self.lang,self.target)
                    except (TranslatorUnavailable,ImportError,ValueError,RuntimeError) as exc:
                        self.last_error="Live translation unavailable: "+str(exc)[:200]
                self.store.add(session=self.session,medium=self.medium,source_id=self.source_id,
                    language=self.lang,text=text,backend=self.backend,start=start,end=end,
                    translated=translated,target=self.target if translated else None,
                    translation_engine="argos_"+self.translation_backend if translated else None)
                self.completed+=1
            except (SpeechError,ValueError,OSError,RuntimeError) as exc:
                self.last_error="Speech transcription unavailable: "+str(exc)[:180]
            finally:
                self.queue.task_done()

    def status(self):
        return {"enabled":True,"selected_backend":self.backend,
                "detected_device":self.selection["detected_device"],
                "source_language":self.lang,"target_language":self.target,
                "translation_backend":self.translation_backend,
                "segments_completed":self.completed,"dropped_windows":self.dropped,
                "queued_windows":self.queue.qsize(),"error":self.last_error}

    def stop(self):
        self.stopping.set()
        # Worker finishes at most two bounded windows, without blocking Stop.
