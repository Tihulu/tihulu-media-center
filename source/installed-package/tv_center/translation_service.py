"""Single persistent private NLLB worker, so a large model loads only once.

Per-segment Python subprocesses would reload ~2.5 GB weights and make
live subtitles unusably slow. This service runs only after explicit NLLB
selection and never accesses the network during inference.
"""
from __future__ import annotations
import atexit
from contextlib import contextmanager
from contextvars import ContextVar
import time
import json
import os
import select
import subprocess
import threading
from pathlib import Path
from .runtime import AIRuntime
from .language_codes import language_code

_live_translation_budget = ContextVar("tihulu_live_translation_budget",default=None)


@contextmanager
def live_translation_budget(seconds=7.0):
    """One bounded time budget for ALL selected live subtitle languages.

    Does not affect offline file translation or Model Market selftests.
    Starts on first actual model call, AFTER Whisper has recognized speech.
    This must never run network downloads in the caption worker.
    """
    if not 1.0 <= float(seconds) <= 60.0:
        raise ValueError("Invalid live translation budget")
    token=_live_translation_budget.set(
        {"seconds":float(seconds),"started":None})
    try:
        yield
    finally:
        _live_translation_budget.reset(token)


def _remaining_live_budget(default_seconds):
    budget=_live_translation_budget.get()
    if budget is None:
        return default_seconds
    now=time.monotonic()
    if budget["started"] is None:
        budget["started"]=now
    remaining=budget["seconds"]-(now-budget["started"])
    if remaining < 0.10:
        raise TimeoutError(
            "Combined live-translation budget exhausted; original "
            "Whisper words retained while other target languages catch up")
    return min(default_seconds,remaining)


class NLLBService:
    def __init__(self):
        self.lock=threading.Lock()
        self.process=None

    def _start(self):
        runtime=AIRuntime().status()
        if not runtime["installed"]:
            raise RuntimeError("Managed Python runtime missing; install NLLB in Model Market")
        root=str(Path(__file__).resolve().parent.parent)
        env=os.environ.copy()
        env["PYTHONPATH"]=root+os.pathsep+env.get("PYTHONPATH","")
        env["HF_HUB_OFFLINE"]="1"
        env["TRANSFORMERS_OFFLINE"]="1"
        self.process=subprocess.Popen(
            [runtime["python"],"-u","-m","tv_center.translation_worker","--serve-nllb"],
            cwd=root,env=env,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            bufsize=0,close_fds=True)

    def translate(self,text,source,target):
        if not isinstance(text,str) or len(text)>1600:
            raise ValueError("Caption text invalid")
        source = language_code(source, nllb=True)
        target = language_code(target, nllb=True)
        if source == target:
            return text
        with self.lock:
            cold=self.process is None or self.process.poll() is not None
            if cold:
                self._start()
            try:
                payload=json.dumps({"text":text,"source":source,"target":target},
                    ensure_ascii=False).encode("utf-8")+b"\n"
                self.process.stdin.write(payload)
                self.process.stdin.flush()
                # A 6-s audio chunk with an ~11-s TV playback delay
                # cannot tolerate an 80-s translator stall. Time out fast,
                # stop the stale worker and let the Argos circuit-breaker
                # take over while the original transcript continues.
                time_budget = (10 if isinstance(self, ArgosService) else
                               30 if cold and isinstance(self, MadladService) else 12)
                time_budget=_remaining_live_budget(time_budget)
                ready,_,_=select.select(
                    [self.process.stdout],[],[],time_budget)
                if not ready:
                    self.close_locked()
                    raise TimeoutError(
                        f"Offline {type(self).__name__} exceeded {time_budget}s "
                        "live-caption budget")
                reply=self.process.stdout.readline(65536)
                if not reply or not reply.endswith(b"\n"):
                    self.close_locked()
                    raise RuntimeError("NLLB translation worker exited without a complete response")
                result=json.loads(reply.decode("utf-8","replace"))
                if "error" in result:
                    raise RuntimeError(result["error"][:280])
                translated=result.get("translated")
                if not isinstance(translated,str) or not translated.strip():
                    raise RuntimeError("NLLB produced no translated text")
                return translated[:1600]
            except (OSError,BrokenPipeError,ValueError) as exc:
                self.close_locked()
                raise RuntimeError("NLLB offline service unavailable: "+str(exc)[:160]) from exc

    def close_locked(self):
        p=self.process
        self.process=None
        if p and p.poll() is None:
            p.terminate()
            try: p.wait(timeout=3)
            except subprocess.TimeoutExpired: p.kill()

    def close(self):
        with self.lock:
            self.close_locked()

class ArgosService(NLLBService):
    """One private Argos worker with cache refresh after package changes."""

    def __init__(self):
        super().__init__()
        self._generation = None

    def _start(self):
        runtime=AIRuntime().status()
        if not runtime["installed"]:
            raise RuntimeError("Managed Argos runtime missing; install in Model Market")
        root=str(Path(__file__).resolve().parent.parent)
        env=os.environ.copy()
        env["PYTHONPATH"]=root+os.pathsep+env.get("PYTHONPATH","")
        env["ARGOS_DEVICE_TYPE"]="cpu"
        env["HF_HUB_OFFLINE"]="1"
        env["TRANSFORMERS_OFFLINE"]="1"
        self.process=subprocess.Popen(
            [runtime["python"],"-u","-m",
             "tv_center.translation_worker","--serve-argos"],
            cwd=root,env=env,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            bufsize=0,close_fds=True)
        from .argos_generation import generation
        self._generation = generation()

    def translate(self, text, source, target):
        # Installation/removal happens in a DIFFERENT Python process.
        # Argos caches installed-language metadata after the first import.
        # Restart the private worker if the Market's generation changed.
        from .argos_generation import generation
        with self.lock:
            current = generation()
            if self.process is not None and current != self._generation:
                self.close_locked()
        try:
            return super().translate(text,source,target)
        except RuntimeError as exc:
            # A pack installed without using our Market (e.g. user pip) has
            # no marker. If the worker reports missing languages, retry ONCE
            # in a fresh interpreter before diagnosing a missing package.
            message = str(exc).lower()
            missing = any(term in message for term in (
                "argos language packages unavailable",
                "argos translate model missing",
                "argos direct translation package missing",
                "argos route missing",
                "translation package missing",
                "no installed", "not installed", "language is not available"))
            if not missing:
                raise
            with self.lock:
                self.close_locked()
            return super().translate(text,source,target)


class MadladService(NLLBService):
    def _start(self):
        runtime=AIRuntime().status()
        if not runtime["installed"]:
            raise RuntimeError("Managed translator Python missing")
        root=str(Path(__file__).resolve().parent.parent)
        env=os.environ.copy()
        env["PYTHONPATH"]=root+os.pathsep+env.get("PYTHONPATH","")
        env["HF_HUB_OFFLINE"]="1"
        env["TRANSFORMERS_OFFLINE"]="1"
        self.process=subprocess.Popen(
            [runtime["python"],"-u","-m","tv_center.translation_worker",
             "--serve-madlad"],cwd=root,env=env,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0,close_fds=True)


_service=NLLBService()
_argos_service=ArgosService()
_madlad_service=MadladService()
atexit.register(_service.close)
atexit.register(_argos_service.close)
atexit.register(_madlad_service.close)


def translate_nllb(text,source,target):
    return _service.translate(text,source,target)


def translate_argos(text,source,target):
    from .language_codes import language_code
    source=language_code(source)
    target=language_code(target)
    return _argos_service.translate(text,source,target)


def translate_madlad(text,source,target):
    return _madlad_service.translate(text,source,target)
