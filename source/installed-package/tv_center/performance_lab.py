# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit offline ASR/translation benchmark using an *existing local file*.

It does not access DVB/SDR devices, download models, alter preferences, or
upload any text/audio. Each candidate runs in a bounded child process so an
incompatible CUDA or transformer runtime cannot hang the settings window.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def recommend(measurements, current_buffer_ms=0, clip_seconds=6):
    """Measured speed recommendation; never assume GPU availability = speed."""
    asr = [m for m in measurements if m.get("kind")=="asr"
           and m.get("status")=="ok" and m.get("nonempty_text",True)
           and m.get("elapsed_s",1e9)>0]
    translations = [m for m in measurements if m.get("kind")=="translation"
                    and m.get("status")=="ok"]
    fastest = min(asr,key=lambda m:m["elapsed_s"]) if asr else None
    # A translator is recommendable only when *every requested direction*
    # was actually tested successfully, not just historical DE→EN / DE→TR.
    requested_pairs = {
        (m.get("source","de"),m.get("target"))
        for m in translations if m.get("target")
    }
    engine_scores = {}
    for eng in ("argos","nllb"):
        successful = {
            (m.get("source","de"),m.get("target")):m
            for m in translations
            if m.get("engine")==eng and m.get("status")=="ok"
        }
        if requested_pairs and requested_pairs.issubset(successful):
            engine_scores[eng] = sum(
                successful[pair]["elapsed_s"] for pair in requested_pairs)
    engine = min(engine_scores,key=engine_scores.get) if engine_scores else None
    translation_s = engine_scores.get(engine,0)
    latency = (fastest["elapsed_s"]+translation_s+0.8) if fastest else None
    suggested_buffer = (max(int(current_buffer_ms),
                          math.ceil(latency*2)/2*1000)
                        if latency is not None else int(current_buffer_ms))
    return {
        "backend":fastest["backend"] if fastest else None,
        "model_path":fastest.get("model_path") if fastest else None,
        "translation_model":engine,
        "measured_asr_s":round(fastest["elapsed_s"],2) if fastest else None,
        "measured_translation_s":round(translation_s,2) if engine else None,
        "estimated_end_to_end_s":round(latency,2) if latency else None,
        "minimum_buffer_ms":int(suggested_buffer),
        "realtime_sustainable":bool(latency is not None and latency<clip_seconds),
        "note":("One local six-second file is a sample, not guaranteed live DVB "
                "throughput. Existing buffer is never decreased and settings "
                "change only after explicit GUI confirmation."),
    }


def diagnose_live(samples, *, capture_seconds=6, queue_overflows=0,
                  ts_audio_gaps=0):
    """Find observed bottlenecks; do not infer the cause from a stale caption.

    Worker timings come from the real TV caption sidecar, not synthetic
    hardware estimates. These include queued time and actual decode time,
    but cannot measure unreported lost RF frames or the speaker DAC clock.
    """
    valid=[s for s in list(samples)[-16:] if isinstance(s,dict)
           and type(s.get("compute_ms")) in (int,float)
           and type(s.get("queue_wait_ms")) in (int,float)
           and s["compute_ms"]>=0 and s["queue_wait_ms"]>=0]
    if not valid:
        return {"samples":0,"state":"waiting_for_real_live_samples",
                "causes":[],"recommendations":[],
                "hardware_proven":False}
    def median(values):
        values=sorted(values)
        n=len(values)
        return (values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2)
    compute_ms=median([x["compute_ms"] for x in valid])
    wait_ms=median([x["queue_wait_ms"] for x in valid])
    rtf=(compute_ms/1000)/capture_seconds
    causes=[]
    recommendation=[]
    if queue_overflows:
        causes.append("caption_capture_queue_overflow")
        recommendation.append("Reduce live ASR workload or use a measured faster installed model; more TV delay cannot restore missing captures.")
    if ts_audio_gaps:
        causes.append("dvb_audio_continuity_gaps")
        recommendation.append("Check RF reception and MPEG-TS audio PID; buffer cannot recreate lost RF packets.")
    if rtf>=0.9:
        causes.append("inference_or_translation_too_slow")
        recommendation.append("Benchmark installed CPU/GPU Whisper and translators on a six-second recorded sample.")
    if wait_ms>=1000:
        causes.append("caption_queue_backlog")
        recommendation.append("Caption worker has queued work; inspect CPU/GPU usage, speech model and translator.")
    if not causes:
        recommendation.append("No sustained compute overload in the measured samples; inspect sentence waiting and native-buffer confirmation.")
    return {"samples":len(valid),
            "state":"measured" if len(valid)>=4 else "collecting",
            "median_compute_ms":round(compute_ms),
            "median_queue_wait_ms":round(wait_ms),
            "median_compute_realtime_factor":round(rtf,2),
            "causes":causes,"recommendations":recommendation,
            "hardware_proven":False,
            "note":"Real local pipeline timings only. No actual DAC lip-sync/accuracy asserted."}


def inventory(settings=None, library=None, profile=None):
    from .ai_settings import AISettings
    from .model_market import ModelLibrary
    from textcenter.compute import detect_devices,choose_backend
    ai = settings or AISettings()
    ai.configure_environment()
    market = library or ModelLibrary()
    opts = ai.values
    models = []
    for row in market.installed():
        if row["installed"] and Path(row["path"]).is_file():
            models.append({"backend":"cpu","model_path":row["path"],
                           "name":row["name"]})
    custom = opts.get("model_path","")
    if custom and Path(custom).is_file() and custom not in {m["model_path"] for m in models}:
        models.append({"backend":"cpu","model_path":custom,
                       "name":"Selected local GGML model"})
    capabilities = profile or detect_devices(model_path=custom)
    try:
        gpu=choose_backend(capabilities,"gpu")
    except (OSError,ValueError,RuntimeError):
        gpu={"ready":False}
    if gpu.get("ready"):
        gpu_model = capabilities["speech"].get("gpu_model_path")
        if gpu_model:
            models.append({"backend":"gpu","model_path":str(gpu_model),
                           "name":"Installed verified GPU Whisper runtime"})
    # Bound workload; two CPU models and one GPU model, no downloads.
    cpu=[m for m in models if m["backend"]=="cpu"][:2]
    gpu=[m for m in models if m["backend"]=="gpu"][:1]
    from .translation_market import TranslationModelMarket
    return {"models":cpu+gpu,
            "engines":["argos"]+
             (["nllb"] if TranslationModelMarket().status()["installed"] else []),
            "settings":dict(opts)}


_running_child = None


def _cancel_benchmark(signum, frame):
    """Stop benchmark and its local model subprocess on user cancellation."""
    global _running_child
    if _running_child is not None and _running_child.poll() is None:
        try:
            os.killpg(_running_child.pid,signal.SIGTERM)
        except (OSError,ProcessLookupError):
            pass
    raise SystemExit(130)


def _child(args,timeout):
    global _running_child
    try:
        _running_child=subprocess.Popen(
            [sys.executable,"-m","tv_center.performance_lab",
             "--worker",*args],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,start_new_session=True,env={
                **os.environ,"HF_HUB_OFFLINE":"1",
                "TRANSFORMERS_OFFLINE":"1",
                "TOKENIZERS_PARALLELISM":"false"})
        try:
            stdout,stderr=_running_child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(_running_child.pid,signal.SIGKILL)
            except (OSError,ProcessLookupError):
                pass
            _running_child.communicate()
            return {"status":"timeout","reason":"Model exceeded time budget"}
        if _running_child.returncode:
            return {"status":"failed","reason":
                    stderr.decode("utf-8","replace")[-250:] or
                    "Worker returned "+str(_running_child.returncode)}
        payload=json.loads(stdout.decode("utf-8","replace"))
        if not isinstance(payload,dict) or payload.get("status")!="ok":
            return {"status":"failed","reason":"Invalid AI worker result"}
        return payload
    except (OSError,ValueError) as exc:
        return {"status":"failed","reason":str(exc)[:180]}
    finally:
        _running_child=None


# Benchmark examples are honest source-language samples, not synthetic
# translated output or a claim of comprehensive language coverage.
_TRANSLATION_SAMPLES = {
    "de": "Guten Morgen. Heute sprechen wir über das Wetter.",
    "en": "Good morning. Today we are talking about the weather.",
    "tr": "Günaydın. Bugün hava durumu hakkında konuşuyoruz.",
    "fr": "Bonjour. Aujourd'hui, nous parlons de la météo.",
    "es": "Buenos días. Hoy hablamos del tiempo.",
    "pl": "Dzień dobry. Dzisiaj rozmawiamy o pogodzie.",
    "ar": "صباح الخير. اليوم نتحدث عن الطقس.",
    "ja": "おはようございます。今日は天気について話します。",
}


def translation_pairs(sources=("de",), targets=("en","tr"), *, maximum=12):
    """User-selected cross-language directions, no duplicates/same-language.

    Explicitly omitted languages are not silently reported as benchmarked.
    More languages may still be configured for actual playback; this
    six-second benchmark deliberately caps heavy model loads at 12 pairs.
    """
    from .language_codes import language_code
    normalized_sources=tuple(dict.fromkeys(language_code(s) for s in sources))
    normalized_targets=tuple(dict.fromkeys(language_code(t) for t in targets))
    if not normalized_sources or not normalized_targets:
        raise ValueError("Choose a source and at least one destination language")
    if len(normalized_sources)>6 or len(normalized_targets)>6:
        raise ValueError("Benchmark accepts up to six source/target languages")
    pairs=[(src,dst) for src in normalized_sources for dst in normalized_targets
           if src!=dst]
    return pairs[:maximum],pairs[maximum:]


def run_benchmark(audio_path, *, current_buffer_ms=0,
                  source_languages=("de",),
                  target_languages=("en","tr")):
    """Use up to six seconds of explicit local audio; no TV tuner interaction."""
    media = Path(audio_path).expanduser()
    if (not media.is_file() or media.is_symlink() or
            not 1024 <= media.stat().st_size <= 2_000_000_000):
        raise ValueError("Choose a local readable audio/video file (1 KiB–2 GiB)")
    if not 0 <= current_buffer_ms <= 60000:
        raise ValueError("Invalid buffer")
    found = inventory()
    pairs,not_tested=translation_pairs(source_languages,target_languages)
    measurements = []
    with tempfile.TemporaryDirectory(prefix="tihulu-private-ai-benchmark-") as root:
        sample=Path(root)/"six_seconds.wav"
        cmd=["ffmpeg","-hide_banner","-nostdin","-v","error",
             "-i",str(media),"-t","6","-vn","-ar","32000","-ac","1",
             "-c:a","pcm_s16le","-y",str(sample)]
        try:
            p=subprocess.run(cmd,stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=25,check=False)
        except (subprocess.TimeoutExpired,OSError) as exc:
            raise RuntimeError("Local six-second audio extraction failed: "+str(exc)) from exc
        if p.returncode or not sample.is_file() or sample.stat().st_size<64000:
            raise RuntimeError("Input has no usable audio in the first six seconds")
        for candidate in found["models"]:
            result=_child(["asr",candidate["backend"],candidate["model_path"],
                           str(sample)],timeout=65)
            measurements.append({**candidate,"kind":"asr",**result})
        for engine in found["engines"]:
            for source,target in pairs:
                if source not in _TRANSLATION_SAMPLES:
                    result={"status":"not-tested","reason":
                            "No verified offline benchmark sample for "+source.upper()}
                else:
                    result=_child(["translation",engine,source,target],
                                  timeout=45)
                measurements.append({"kind":"translation","engine":engine,
                                     "source":source,"target":target,**result})
    return {"version":1,"audio_duration_s":6,"offline":True,
            "tested_directions":pairs,
            "not_tested_directions":not_tested,
            "samples":measurements,
            "recommendation":recommend(
                measurements,current_buffer_ms=current_buffer_ms),
            "machine_settings":found["settings"],
            "policy":"Read-only benchmark. Nothing was installed, tuned, or modified."}


def worker(kind,one,two=None,three=None):
    started=time.monotonic()
    if kind=="asr":
        backend,model,clip=one,two,three
        if backend not in ("cpu","gpu") or not model or not clip:
            raise ValueError("Invalid ASR worker")
        from .ai_settings import AISettings
        AISettings().configure_environment()
        os.environ["TIHULU_TV_ASR_BACKEND"]=backend
        os.environ["TIHULU_WHISPER_MODEL"]=model
        from .captions import asr_from_clip
        heard=asr_from_clip(Path(clip),"auto",model)
        return {"status":"ok","elapsed_s":round(time.monotonic()-started,3),
                "nonempty_text":bool(str(heard).strip()),
                "speech_proven":bool(str(heard).strip())}
    if kind=="translation":
        from .language_codes import language_code
        engine,source,target=one,language_code(two),language_code(three)
        if (engine not in ("argos","nllb") or source==target or
                source not in _TRANSLATION_SAMPLES):
            raise ValueError("Invalid translator direction or sample")
        os.environ["TIHULU_TRANSLATOR_MODEL"]=engine
        from .captions import translate
        text,error=translate(_TRANSLATION_SAMPLES[source],
                             source,target)
        if not text:
            raise RuntimeError("No real local translation: "+str(error)[:140])
        return {"status":"ok","elapsed_s":round(time.monotonic()-started,3),
                "nonempty_text":True}
    raise ValueError("Unknown benchmark worker")


def main(argv=None):
    parser=argparse.ArgumentParser(description="Local offline AI model benchmark")
    parser.add_argument("--audio",default="")
    parser.add_argument("--buffer-ms",type=int,default=0)
    parser.add_argument("--sources",default="de")
    parser.add_argument("--targets",default="en,tr")
    parser.add_argument("--worker",nargs="+")
    args=parser.parse_args(argv)
    try:
        if not args.worker:
            # Qt Stop AI model test terminates the orchestrator; clean up
            # its verified model worker process group rather than leaving
            # CUDA/CPU inference running after the UI says canceled.
            signal.signal(signal.SIGTERM,_cancel_benchmark)
        if args.worker:
            result=worker(*args.worker)
        elif args.audio:
            result=run_benchmark(
                args.audio,current_buffer_ms=args.buffer_ms,
                source_languages=tuple(filter(None,args.sources.split(","))),
                target_languages=tuple(filter(None,args.targets.split(","))))
        else:
            parser.error("Choose --audio FILE; no model will download")
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (ValueError,RuntimeError,OSError) as error:
        print(str(error)[:450],file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
