"""Real Teletext and offline STT/translation from short captured TS segments.

Uses ffmpeg with libzvbi; uses existing TEXT CENTER Whisper/Argos workers.
Never invents captions, auto-downloads a model, or sends audio to a cloud API.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import tempfile
import time
import threading
from pathlib import Path

from textcenter.compute import LANGUAGES as SUPPORTED
from .language_codes import language_code

def _run(argv, timeout=30):
    return subprocess.run(argv, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, check=False)

def _program_streams(path, service_id):
    """Choose streams for the tuned DVB service, never another TV in the multiplex."""
    probe = _run(["ffprobe", "-v", "error", "-show_programs", "-show_streams",
                  "-of", "json", str(path)], timeout=15)
    if probe.returncode:
        return []
    try:
        data = json.loads(probe.stdout)
    except (ValueError, UnicodeError):
        return []
    if service_id is None:
        return data.get("streams", [])
    for program in data.get("programs", []):
        try:
            program_id = int(program.get("program_id", program.get("program_num", -1)))
        except (ValueError, TypeError):
            continue
        if program_id == service_id:
            return program.get("streams", [])
    # Do not inadvertently transcribe a neighbouring TV service.
    return []

def _sub_stream(path, service_id, teletext_pid=None):
    streams = _program_streams(path, service_id)
    for stream in streams:
        if stream.get("codec_name") != "dvb_teletext":
            continue
        if teletext_pid is not None:
            try:
                # ffprobe stream id is normally e.g. '0x013f'.
                stream_pid = int(str(stream.get("id","")), 0)
            except (ValueError, TypeError):
                continue
            if stream_pid != teletext_pid:
                continue
        return stream["index"]
    # Never fall back to another language/PID after a user's selection.
    return None

def ass_text(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10:
            continue
        txt = re.sub(r"\{[^}]*\}", "", fields[9])
        # ASS/libzvbi uses \\h for a non-breaking space; do not feed the
        # literal backslash-h into Whisper/Argos or render it on video.
        txt = (txt.replace(r"\N", " ").replace(r"\n", " ")
               .replace(r"\h", " ").replace("\u00a0", " "))
        txt = re.sub(r"[ \t]+", " ", txt).strip()
        # Drop broadcaster test-page titles, never real spoken subtitles.
        from .asr_quality import strip_test_page_artifact
        txt, _ = strip_test_page_artifact(txt,broadcaster=True)
        if txt and (not lines or txt != lines[-1]):
            lines.append(txt)
    return "\n".join(lines[-6:])[:1600]

def teletext_from_clip(path: Path, page: int | str, service_id: int | None = None,
                       teletext_pid: int | None = None) -> str:
    # 'subtitle' is FFmpeg/libzvbi's special selector for broadcaster-marked
    # caption pages. Never treat arbitrary Teletext page 150 news as speech.
    if page != "subtitle" and (type(page) is not int or not 100 <= page <= 899):
        raise ValueError("Teletext page must be 100-899 or 'subtitle'")
    idx = _sub_stream(path, service_id, teletext_pid)
    if idx is None:
        return ""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-txt_page", str(page), "-txt_format", "ass", "-txt_duration", "4000",
           "-i", str(path), "-map", f"0:{idx}", "-c:s", "ass", "-f", "ass", "-"]
    proc = _run(cmd, timeout=25)
    return ass_text(proc.stdout.decode("utf-8", "replace")) if proc.returncode == 0 else ""

def choose_audio_stream(streams, language, preferred_pid=None):
    """Prefer a real matching speech track, or an explicitly selected audio PID.

    German DTV broadcasts can contain accessibility/AD or English audio.
    Transcribing an AD or English track as German can corrupt the captions.
    This does not retune the channel or pick a different TV service.
    """
    if preferred_pid is not None and (
            type(preferred_pid) is not int or not 1 <= preferred_pid <= 8190):
        raise ValueError("Invalid selected audio PID")
    candidates = []
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        if preferred_pid is not None:
            try:
                pid = int(str(stream.get("id", "")), 0)
            except (TypeError, ValueError):
                continue
            if pid != preferred_pid:
                continue
            return stream.get("index") if type(stream.get("index")) is int else None
        tags = stream.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}
        lang = str(tags.get("language","")).lower()
        description = " ".join(str(tags.get(k,"")) for k in ("title","handler_name"))
        disposition = stream.get("disposition") or {}
        bad = any(k in description.lower() for k in
                  ("audio description","audiodeskription","hörfilm","descriptive"))
        bad = bad or bool(disposition.get("visual_impaired"))
        try:
            preferred = language_code(lang) == language
        except ValueError:
            preferred = False
        # Prefer known audio descriptions only when there is no normal track.
        candidates.append((4 if preferred else 0, -10 if bad else 0,
                           stream.get("index")))
    candidates = [x for x in candidates if type(x[2]) is int]
    if not candidates:
        return None
    return max(candidates, key=lambda x:(x[0]+x[1],-x[2]))[2]


def _speaker_details(pcm, transcript, diagnostics, enabled,
                     provider="resemblyzer", channel=None):
    # Never invoke speaker clustering for a silent/rejected ASR result.
    # Short genuine dialogue still supports optional diarization, and its
    # engine/error diagnostics remain visible to the user.
    if not transcript:
        return transcript
    if enabled:
        try:
            if provider == "resemblyzer":
                from .free_speakers import diarize_pcm
                turns = diarize_pcm(pcm, channel=channel)
            elif provider == "pyannote":
                from .speaker_market import diarize_pcm
                turns = diarize_pcm(pcm)
            else:
                raise ValueError("Unknown offline speaker provider")
            if diagnostics is not None:
                diagnostics["speaker_turns"] = turns
                diagnostics["speaker_engine"] = provider
                diagnostics["speaker_note"] = (
                    "Voice clusters are provisional; no reliable age/gender "
                    "identification or persistent real-person identity.")
        except (ImportError, RuntimeError, OSError, ValueError, TimeoutError) as exc:
            if diagnostics is not None:
                diagnostics["speaker_error"] = str(exc)[:180]
    return transcript


def asr_from_clip(path: Path, language: str, model: str,
                  service_id: int | None = None, diagnostics=None,
                  audio_pid: int | None = None,
                  speaker_enabled: bool = False,
                  speaker_provider: str = "resemblyzer",
                  music_transcription: bool = False,
                  speech_priority: bool = False,
                  overlap_separation: bool = False,
                  show_sound_events: bool = False,
                  show_voice_types: bool = False) -> str:
    # "auto" is a speech-detection MODE, not an ISO language code.
    # All existing speech backends except unverified NPUs handle it.
    if language != "auto" and language not in SUPPORTED:
        raise ValueError("Unsupported transcription language: " + str(language))
    selected_backend = os.environ.get("TIHULU_TV_ASR_BACKEND", "auto")
    if selected_backend == "off":
        raise RuntimeError("Offline transcription disabled in Settings")
    if selected_backend not in ("auto", "cpu", "gpu", "npu", "remote"):
        raise RuntimeError("Invalid offline speech backend")
    streams = _program_streams(path, service_id)
    audio_index = choose_audio_stream(streams, language, audio_pid)
    if audio_index is None and audio_pid is not None:
        # A TV retune may remove a selected elementary-stream PID. Only
        # resume automatically if the alternate track explicitly advertises
        # the SAME spoken language; never secretly switch languages.
        same_language = []
        available = set()
        for stream in streams:
            if stream.get("codec_type") != "audio":
                continue
            raw_language = str((stream.get("tags") or {}).get("language","")).lower()
            try:
                code = language_code(raw_language)
            except ValueError:
                continue
            available.add(code)
            if code == language and type(stream.get("index")) is int:
                same_language.append(stream)
        if same_language:
            audio_index = choose_audio_stream(same_language, language)
            if diagnostics is not None:
                diagnostics["audio_notice"] = (
                    "The selected audio PID disappeared; switched to another " +
                    language.upper() + " audio track.")
        else:
            choices = ", ".join(sorted(available)).upper() or "none signalled"
            raise RuntimeError(
                "Selected audio channel is unavailable. Broadcast offers: " +
                choices + ". Select another language/audio channel or use Teletext.")
    if audio_index is None:
        raise RuntimeError("No audio track in the selected TV service")
    from .speech_focus import ffmpeg_audio_filter
    focus_filter = ffmpeg_audio_filter(
        speech_priority=speech_priority, music_transcription=music_transcription)
    audio = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                  "-map", f"0:{audio_index}", "-vn", "-ar", "32000", "-ac", "1",
                  *focus_filter, "-f", "s16le", "-"], timeout=35)
    if diagnostics is not None:
        diagnostics["speech_priority"] = bool(focus_filter)
        diagnostics["speech_priority_note"] = (
            "Gentle dialogue-band ASR conditioning; TV audio unchanged. "
            "This is not music/source separation." if focus_filter else None)
    if audio.returncode or len(audio.stdout) < 32000:
        raise RuntimeError("No usable audio stream in recorded TV segment")
    # Optional acoustic classifiers are independent, offline and opt-in.
    if show_sound_events:
        try:
            from .audio_classifiers import detect_sound_events
            actual_events=detect_sound_events(audio.stdout)
            if diagnostics is not None:
                diagnostics["sound_events"]=actual_events
        except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
            if diagnostics is not None:
                diagnostics["sound_event_note"]=str(exc)[:160]
    if show_voice_types and not overlap_separation:
        try:
            from .audio_classifiers import detect_voice_type
            category=detect_voice_type(audio.stdout)
            if diagnostics is not None and category:
                diagnostics["voice_type_candidate"]=category
        except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
            if diagnostics is not None:
                diagnostics["voice_type_note"]=str(exc)[:160]
    # Remote speech is an explicit user-approved HTTPS+token backend.
    # Device ownership remains local: only the bounded decoded audio PCM
    # is sent to the configured GPU host; video/RF data are NOT uploaded.
    if selected_backend == "remote":
        from .ai_settings import AISettings
        chosen = AISettings().values
        if not chosen["remote_gpu_enabled"]:
            raise RuntimeError("Remote GPU not enabled in AI Model Market")
        try:
            from .remote_gpu import transcribe as remote_transcribe
            details = remote_transcribe(
                audio.stdout, language, chosen["remote_gpu_url"])
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            if not chosen["remote_gpu_fallback"]:
                raise RuntimeError("Remote GPU unavailable: "+str(exc)[:150]) from exc
            if diagnostics is not None:
                diagnostics["remote_error"] = str(exc)[:140]
                diagnostics["remote_fallback"] = "local auto"
            selected_backend = "auto"  # explicit configured fallback
        else:
            if diagnostics is not None:
                diagnostics["backend"] = "remote"
                diagnostics["model"] = "Remote managed Faster-Whisper CUDA"
                diagnostics["engine"] = "authenticated HTTPS remote GPU"
                diagnostics["ready"] = True
                diagnostics["words"] = details["words"]
                diagnostics["detected_language"] = details["language"]
                diagnostics["language_confidence"] = details["language_probability"]
                diagnostics["word_timing_source"] = "remote_cuda_word_timestamps"
                diagnostics["recognition_rejected"] = details.get(
                    "recognition_rejected")
            return _speaker_details(
                audio.stdout, details["text"].strip(), diagnostics,
                speaker_enabled, speaker_provider,
                channel=f"{service_id}:{audio_pid}")
    # Existing TEXT CENTER speech implementation handles local CPU/GPU selection.
    os.environ["TIHULU_WHISPER_MODEL"] = str(Path(model).expanduser())
    from textcenter.compute import detect_devices, choose_backend
    from textcenter.speech import transcribe_pcm
    profile = detect_devices()
    selected = choose_backend(profile, selected_backend)
    # This vendor Whisper Base path currently lacks a proven automatic
    # language-detection contract. Keep spoken=Auto useful via CPU Tiny,
    # instead of labeling an unsupported NPU language mode as working.
    if selected.get("selected")=="npu" and language=="auto":
        from .ai_settings import AISettings
        settings=AISettings().values
        if (settings.get("active_profile")=="pi5_hat2"
                and settings.get("hailo_cpu_fallback")):
            selected=choose_backend(profile,"cpu")
            if diagnostics is not None:
                diagnostics["npu_notice"]=(
                    "Spoken Auto detect uses Pi CPU fallback; set a language "
                    "to test Hailo Whisper Base")
        else:
            raise RuntimeError(
                "Selected NPU Whisper requires a known source language")
    if diagnostics is not None:
        diagnostics["backend"] = selected.get("selected", "unknown")
        # The user may have a GGML Tiny selected for CPU fallback while
        # managed CUDA actually runs a separate CTranslate2 Large-v3 Turbo.
        # Report the model that really receives audio, not the UI fallback.
        speech = profile["speech"]
        actual = (speech.get("gpu_model_path")
                  if selected.get("selected") == "gpu" else
                  speech.get("npu_model_path")
                  if selected.get("selected") == "npu" else model)
        diagnostics["model"] = Path(actual).name if actual else "not configured"
        diagnostics["engine"] = (
            speech.get("gpu_engine") if selected.get("selected") == "gpu" else
            speech.get("npu_engine") if selected.get("selected") == "npu" else
            speech.get("engine", "whisper.cpp CLI"))
        diagnostics["ready"] = bool(selected.get("ready"))
    if not selected.get("ready"):
        raise RuntimeError(selected.get("reason", "Offline speech engine unavailable"))
    if selected["selected"] == "cpu":
        if not model or not Path(model).expanduser().is_file():
            raise RuntimeError("CPU Whisper model missing. Install/select a multilingual GGML model.")
        profile["speech"]["model_path"] = str(Path(model).expanduser())
    if (selected["selected"] == "gpu" and
            profile["speech"].get("gpu_engine") == "faster_whisper_managed"):
        # The CUDA worker returns *measured* word positions within this
        # original pre-playback DVB audio clip. A later subtitle scheduler
        # uses them only when an active native TV delay can be confirmed.
        from .cuda_faster_whisper import transcribe_cuda_details
        details = transcribe_cuda_details(
            audio.stdout, language, str(profile["speech"]["gpu_model_path"]),
            music_mode=music_transcription,
            speech_priority=speech_priority, timeout_s=18)
        if diagnostics is not None:
            diagnostics["words"] = details.get("words", [])
            diagnostics["detected_language"] = details.get("language")
            diagnostics["language_confidence"] = details.get("language_probability")
            diagnostics["word_timing_source"] = "faster_whisper_cuda_word_timestamps"
            diagnostics["recognition_rejected"] = details.get("recognition_rejected")
        if overlap_separation:
            # Experimental actual TWO-source speech separation followed
            # by TWO independent ASR calls. Fail closed; never generate a
            # second line by copying the ordinary Whisper transcript.
            try:
                from .overlap_separation import (
                    separate_pcm, accept_two_transcripts)
                streams=separate_pcm(audio.stdout)
                recognized=[
                    transcribe_cuda_details(
                        track,language,str(profile["speech"]["gpu_model_path"]),
                        music_mode=False,speech_priority=False,
                        timeout_s=6)
                    for track in streams]
                voices=accept_two_transcripts(recognized)
                if voices and show_voice_types:
                    from .audio_classifiers import detect_voice_type
                    for voice in voices:
                        try:
                            track=streams[voice["speaker_index"]-1]
                            candidate=detect_voice_type(track)
                            if candidate:
                                voice.update(candidate)
                        except (OSError,ValueError,RuntimeError,TimeoutError) as exc:
                            if diagnostics is not None:
                                diagnostics["voice_type_note"]=str(exc)[:160]
                if voices:
                    if diagnostics is not None:
                        diagnostics["overlap_lines"]=voices
                        diagnostics["overlap_model"]="SpeechBrain SepFormer-wsj02mix"
                        diagnostics["overlap_note"]=(
                            "Two independent Whisper tracks; provisional A/B "
                            "per clip, not verified speaker identity")
                elif diagnostics is not None:
                    diagnostics["overlap_note"]=(
                        "Separation produced no TWO distinct, source-timed "
                        "transcripts; kept original mixed audio")
            except (OSError,ValueError,RuntimeError,TimeoutError,
                    subprocess.TimeoutExpired) as exc:
                if diagnostics is not None:
                    diagnostics["overlap_note"]=(
                        "Experimental 2-voice separation unavailable; kept "
                        "original mixed audio: "+str(exc)[:130])
        primary_text=details["text"].strip()
        if not primary_text and diagnostics is not None and diagnostics.get(
                "overlap_lines"):
            # The mixed waveform can be unintelligible although source A
            # and B are independently recognized. Use actual source A ASR,
            # not an invented blended transcript, as the original fallback.
            primary_text=diagnostics["overlap_lines"][0]["original"]
        return _speaker_details(audio.stdout,primary_text,
                                diagnostics, speaker_enabled, speaker_provider,
                                channel=f"{service_id}:{audio_pid}")
    try:
        transcription = transcribe_pcm(
            audio.stdout, language, selected["selected"], profile).strip()
    except (RuntimeError, OSError, ValueError, TimeoutError) as exc:
        # A failed Hailo device/model must NOT drop original dialogue when
        # the owner explicitly selected this Pi preset with CPU fallback.
        if selected.get("selected") != "npu":
            raise
        from .ai_settings import AISettings
        settings=AISettings().values
        if (settings.get("active_profile")!="pi5_hat2"
                or not settings.get("hailo_cpu_fallback")):
            raise
        cpu=choose_backend(profile,"cpu")
        if not cpu.get("ready"):
            raise RuntimeError(
                "Hailo ASR failed and Whisper Tiny CPU fallback is unavailable") from exc
        if diagnostics is not None:
            diagnostics["npu_error"]=str(exc)[:180]
            diagnostics["npu_fallback"]="Whisper Tiny CPU"
            diagnostics["backend"]="cpu"
            diagnostics["model"]=Path(model).name if model else "CPU model"
            diagnostics["engine"]="whisper.cpp CPU fallback"
        transcription=transcribe_pcm(
            audio.stdout, language,"cpu",profile).strip()
    return _speaker_details(audio.stdout, transcription,
                            diagnostics, speaker_enabled, speaker_provider,
                            channel=f"{service_id}:{audio_pid}")

def _translate_argos_local(text: str, source: str, target: str) -> str:
    """Use the SAME installed Argos runtime as Model Market and its language list.

    Never prefer system Python when the user-owned Argos environment exists:
    that environment can have different installed language packs. A genuinely
    missing pair or runtime failure must be visible, not silently masked by
    translating from another interpreter or cached package catalog.
    """
    from .runtime import AIRuntime
    if AIRuntime().status()["installed"]:
        from .translation_service import translate_argos
        return translate_argos(text, source, target)
    from textcenter.transcripts import translate_offline
    return translate_offline(text, source, target, backend="cpu")


_live_translator_info = threading.local()


def translate(text: str, source: str, target: str) -> tuple[str | None, str | None]:
    """Public backwards-compatible (text, warning/error) API.

    Keep this call seam for DVB, radio and the existing translators/tests.
    Real-engine diagnostics are stored per worker thread separately.
    """
    translated, issue, actual_engine = translate_with_engine(
        text, source, target)
    _live_translator_info.last = (
        (text, source, target), actual_engine if translated else None)
    return translated, issue


def translation_engine_for(text: str, source: str, target: str):
    """Engine of the actual immediately preceding translation on this thread.

    Never infer engine from selected settings when inference was unavailable.
    """
    key, engine = getattr(_live_translator_info, "last", (None, None))
    return engine if key == (text, source, target) else None


def translate_with_engine(text: str, source: str, target: str):
    """Return (text, warning/error, ACTUAL engine) for honest UI diagnostics.

    Whisper remains ASR, not an invisible English-pivot translator. The
    owner's explicit 'Direct DE→TR' choice uses installed NLLB/MADLAD first,
    only then reports Argos's possible English pivot. Other settings behave
    as before. No language model is downloaded during inference.
    """
    try:
        source = language_code(source, nllb=True)
        target = language_code(target, nllb=True)
    except ValueError as exc:
        return None, str(exc), None
    if source == target:
        return None, None, "original"

    selected = os.environ.get("TIHULU_TRANSLATOR_MODEL", "argos")
    if selected == "auto_offline":
        # Per-language local policy: direct DE→TR is preferred to English
        # pivot; other targets try NLLB with existing circuit breaker, then
        # Argos and finally installed MADLAD. No network or auto-download.
        if source in ("de", "deu_Latn") and target in ("tr", "tur_Latn"):
            from .direct_de_tr import translate_de_tr_direct
            result=translate_de_tr_direct(text)
            return result.text, result.error or result.warning, result.engine
        from .translation_failover import live_failover
        from .translation_service import translate_nllb, translate_madlad
        from .translation_market import TranslationModelMarket
        try:
            nllb_ready=bool(TranslationModelMarket().status().get("installed"))
        except (OSError,ValueError,RuntimeError):
            nllb_ready=False
        outcome=live_failover().translate(
            text,source,target,preferred="nllb" if nllb_ready else "argos",
            nllb=translate_nllb,argos=_translate_argos_local)
        if outcome.text:
            return outcome.text,outcome.error or outcome.warning,outcome.engine
        from .translation_madlad import MadladMarket
        try:
            madlad_ready=bool(MadladMarket().status().get("installed"))
        except (OSError,ValueError,RuntimeError):
            madlad_ready=False
        if madlad_ready:
            try:
                value=translate_madlad(text,source,target)
                if isinstance(value,str) and value.strip():
                    return value.strip(),outcome.error or outcome.warning,"madlad-fallback"
            except (OSError,RuntimeError,ValueError,TimeoutError,ImportError):
                pass
        return None,outcome.error or "No working installed offline translator",None

    if selected == "de_tr_direct":
        if source in ("de", "deu_Latn") and target in ("tr", "tur_Latn"):
            from .direct_de_tr import translate_de_tr_direct
            result = translate_de_tr_direct(text)
            return result.text, result.error or result.warning, result.engine
        # The preference is pair-specific. Keep other requested languages
        # available using local Argos, and label the actual route honestly.
        try:
            return _translate_argos_local(text, source, target), None, "argos"
        except (ImportError, RuntimeError, ValueError, OSError, KeyError):
            return None, "No local Argos route for non-DE→TR language pair", None

    from .translation_failover import live_failover
    from .translation_service import translate_nllb
    if selected == "deepl":
        # Only an EXPLICIT previously authorized DeepL selection sends text.
        try:
            from .deepl_api import translate_deepl
            translated = translate_deepl(text, source, target)
            return translated, None, "deepl"
        except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
            try:
                replacement = _translate_argos_local(text, source, target)
                return (replacement, "DeepL unavailable; offline Argos fallback: "+
                        str(exc)[:100], "argos-fallback")
            except (ImportError, RuntimeError, ValueError, OSError, KeyError):
                return None, "DeepL unavailable; no compatible offline Argos pair", None
    if selected == "madlad":
        from .translation_service import translate_madlad
        import time
        now = time.monotonic()
        blocked = getattr(translate, "_madlad_blocked_until", 0.)
        if now >= blocked:
            try:
                return translate_madlad(text, source, target), None, "madlad"
            except (RuntimeError, OSError, ValueError, TimeoutError, ImportError):
                translate._madlad_blocked_until = now + 180.
        try:
            return (_translate_argos_local(text, source, target),
                    "MADLAD unavailable or too slow; switched to installed offline Argos",
                    "argos-fallback")
        except (RuntimeError, OSError, ValueError, ImportError, KeyError):
            return None, "MADLAD unavailable; offline Argos pair not installed", None
    outcome = live_failover().translate(
        text, source, target, preferred=selected,
        nllb=translate_nllb, argos=_translate_argos_local)
    return outcome.text, outcome.error or outcome.warning, outcome.engine


def decode_segment(ts: bytes, *, mode="auto", page=150, source="de",
                   target="tr", targets=None, model="", service_id: int | None = None,
                   previous_text: str = "",
                   teletext_pid: int | None = None,
                   audio_pid: int | None = None,
                   audio_source: str | None = None,
                   speaker_enabled: bool = False,
                   speaker_provider: str = "resemblyzer",
                   music_transcription: bool = False,
                   speech_priority: bool = False,
                   defer_asr_translation: bool = False,
                   speech_auto: bool = False,
                   auto_teletext_probe: bool = False,
                   auto_teletext_recovery: bool = False,
                   teletext_language: str | None = None,
                   overlap_separation: bool = False,
                   show_sound_events: bool = False,
                   show_voice_types: bool = False) -> dict:
    if mode not in ("teletext", "page", "asr", "auto"):
        raise ValueError("Unsupported caption source")
    if type(page) is not int or not 100 <= page <= 899:
        raise ValueError("Invalid Teletext page")
    source = "auto" if source == "auto" else language_code(source, nllb=True)
    target = language_code(target, nllb=True)
    if audio_pid is not None and (
            type(audio_pid) is not int or not 1 <= audio_pid <= 8190):
        raise ValueError("Invalid selected audio PID")
    if audio_source is not None:
        audio_source = language_code(audio_source)
    if targets is None:
        targets = (target,) if target != source else ()
    if not isinstance(targets, (tuple,list)) or len(targets) > 6:
        raise ValueError("Choose up to six translation languages")
    targets = tuple(language_code(t, nllb=True) for t in targets)
    if len(set(targets)) != len(targets):
        raise ValueError("Duplicate translation languages")
    if not ts:
        return {"original": "", "source": mode, "error": "No live TS data"}
    with tempfile.TemporaryDirectory(prefix="tihulu-tv-captions-") as tmp:
        p = Path(tmp) / "broadcast.ts"
        p.write_bytes(ts)
        original, used, error = "", "", None
        raw_asr_original = ""
        used_language = source
        speech_diagnostics = {}
        timing_started = time.perf_counter()
        teletext_ms = 0
        asr_ms = 0
        translation_ms = 0
        if mode in ("teletext", "page", "auto"):
            # Automatic captions must use *actual* subtitle pages signaled by
            # the broadcaster, not arbitrary Teletext news/information pages.
            # A selected broadcaster Teletext subtitle channel has an
            # explicit DVB page and PID; 'subtitle' would mix languages.
            selected_page = page if mode == "page" or teletext_pid is not None else "subtitle"
            teletext_start = time.perf_counter()
            original = (teletext_from_clip(p, selected_page, service_id, teletext_pid)
                        if teletext_pid is not None else
                        teletext_from_clip(p, selected_page, service_id))
            teletext_ms = round((time.perf_counter()-teletext_start)*1000)
            used = ((f"broadcaster_teletext_subtitles_page_{page}"
                     if teletext_pid is not None else f"teletext_page_{page}")
                    if selected_page != "subtitle"
                    else "broadcaster_teletext_subtitles") if original else ""
        # Auto mode may briefly check the *actual* speech against genuine
        # broadcaster subtitles. Never run this in Teletext Hard or manual
        # page mode. Three consecutive high-confidence conflicts are
        # required by the caller before it may prefer Whisper.
        teletext_probe = None
        teletext_shadow = None
        if (original and mode=="auto" and auto_teletext_probe):
            details = {}
            try:
                opts={"diagnostics":details}
                if audio_pid is not None:
                    opts["audio_pid"]=audio_pid
                probe_language=("auto" if speech_auto else
                                (audio_source or source))
                speech=asr_from_clip(p,probe_language,model,service_id,**opts)
                if speech and isinstance(speech,str):
                    teletext_probe={
                        "text":speech[:2500],
                        "source_language":(
                            details.get("detected_language") or
                            (probe_language if probe_language!="auto" else "und")),
                        "word_timing_source":details.get("word_timing_source"),
                        "words":details.get("words",[]),
                    }
            except (RuntimeError,ValueError,OSError,subprocess.TimeoutExpired):
                # Teletext remains valid if optional test ASR is unavailable.
                pass
        if not original and mode in ("asr", "auto"):
            asr_start = time.perf_counter()
            try:
                asr_kwargs = {"diagnostics": speech_diagnostics}
                if audio_pid is not None:
                    asr_kwargs["audio_pid"] = audio_pid
                if music_transcription:
                    asr_kwargs["music_transcription"] = True
                if speech_priority:
                    asr_kwargs["speech_priority"] = True
                if speaker_enabled:
                    asr_kwargs["speaker_enabled"] = True
                    asr_kwargs["speaker_provider"] = speaker_provider
                if overlap_separation:
                    asr_kwargs["overlap_separation"] = True
                if show_sound_events:
                    asr_kwargs["show_sound_events"] = True
                if show_voice_types:
                    asr_kwargs["show_voice_types"] = True
                # Real DVB audio-language descriptors are a stronger hint
                # than six seconds of noisy live TV speech. Do not ignore
                # the selected/signalled audio language in Auto mode.
                # Explicit GPU/remote Spoken=Auto permits a language
                # switch inside the same TV channel. DVB descriptors remain
                # hints, never a forced Whisper language in this mode.
                speech_language = "auto" if speech_auto else (audio_source or source)
                original = asr_from_clip(p, speech_language, model, service_id,
                                         **asr_kwargs)
                # Filter only unmistakable repeated Whisper loops (often
                # music/jingle hallucinations). Keep real twice-spoken
                # phrases and opt-in singing/lyrics exactly as transcribed.
                from kaffeine_next.continuous_captions import (
                    collapse_asr_repetition_loops)
                cleaned = (original if music_transcription else
                           collapse_asr_repetition_loops(original))
                from .asr_quality import strip_test_page_artifact
                cleaned, page_marker_removed = strip_test_page_artifact(cleaned)
                if cleaned != original:
                    original = cleaned
                    if page_marker_removed:
                        speech_diagnostics["asr_test_page_artifact_removed"] = True
                    else:
                        speech_diagnostics["asr_repetitions_removed"] = True
                    # Removed words break original ASR timestamp indexing.
                    # Prefer an accurate whole-phrase cue to forged timing.
                    speech_diagnostics["words"] = []
                    speech_diagnostics["word_timing_source"] = None
                raw_asr_original = original[:2500]  # private overlap bookkeeping
                if original:
                    used_language = (
                        speech_diagnostics.get("detected_language") or
                        speech_language)
                    if used_language == "auto":
                        # Some CPU speech engines return text but no ASR
                        # language metadata. Use an actual broadcaster audio
                        # language descriptor (or user-selected source) as an
                        # explicitly *hinted* translation source, never a
                        # guessed DE default. If neither exists, keep the
                        # untranslated original instead of fabricating FR.
                        hinted = audio_source or (source if source!="auto" else None)
                        if hinted:
                            used_language = hinted
                            speech_diagnostics["source_language_note"] = (
                                "Translation uses broadcast/user language hint; "
                                "speech language not confirmed by ASR")
                        else:
                            used_language = "und"
                if original and previous_text:
                    from kaffeine_next.continuous_captions import remove_repeated_prefix
                    deduplicated = remove_repeated_prefix(previous_text, original)
                    if deduplicated != original and speech_diagnostics.get("words"):
                        # The 1-second overlapping DVB clip also duplicates
                        # ASR word timestamps. Keep only words proven to be
                        # the surviving transcript suffix; otherwise use the
                        # old chunk cue rather than re-showing earlier speech.
                        import re
                        words = speech_diagnostics["words"]
                        def clean_tokens(items):
                            return [re.sub(r"\W+","",str(x).casefold())
                                    for x in items]
                        target_words = clean_tokens(deduplicated.split())
                        timed_words = clean_tokens(w["text"] for w in words)
                        if (target_words and len(target_words) <= len(timed_words)
                                and timed_words[-len(target_words):] == target_words):
                            speech_diagnostics["words"] = words[-len(target_words):]
                        else:
                            speech_diagnostics["words"] = []
                    original = deduplicated
                used = "local_asr" if original else ""
            except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
                error = str(exc)[:180]
            finally:
                asr_ms = round((time.perf_counter()-asr_start)*1000)
        # While Whisper protects viewers from mismatched Teletext, sample
        # the broadcaster text on the SAME selected TS/SID periodically.
        # The ASR above already ran; do NOT trigger a second expensive ASR
        # or revive stale text from an earlier programme. The caller decides
        # whether two trusted matching probes justify returning to Teletext.
        if auto_teletext_recovery and mode=="asr":
            try:
                shadow_page=page if teletext_pid is not None else "subtitle"
                shadow=teletext_from_clip(p,shadow_page,service_id,teletext_pid)
                if shadow and len(shadow.strip())>=15:
                    teletext_shadow={
                        "text":shadow[:2500],
                        "source_language":teletext_language or
                            (source if source!="auto" else "und")}
            except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired):
                pass
        # A global clip may contain multiple voices; never assign its
        # acoustic category to an individual without a single diarized
        # voice. In an overlap case each isolated stream was classified
        # independently instead.
        candidate=speech_diagnostics.pop("voice_type_candidate",None)
        ids={str(turn.get("id")) for turn in
             speech_diagnostics.get("speaker_turns",[])
             if isinstance(turn,dict) and turn.get("id")}
        if candidate and len(ids)==1:
            speech_diagnostics.update(candidate)
        elif candidate:
            speech_diagnostics["voice_type_note"]=(
                "Multiple/unknown voices; category intentionally withheld")
        translations = {}
        errors = {}
        warnings = {}
        engines = {}
        if original and not (defer_asr_translation and used=="local_asr"):
            # When ASR sentence assembly is enabled, translate only once
            # AFTER completed phrases are joined by the live sidecar.
            # Previously Auto mode translated EN/TR here and discarded
            # those results, translating both languages a second time.
            translate_start = time.perf_counter()
            for language in targets:
                if language == used_language:
                    # Requested language already matches the actual Teletext
                    # or selected audio language; original IS the answer.
                    translations[language] = original
                    continue
                phrase, failed = translate(
                    original, used_language, language)
                real_engine = translation_engine_for(
                    original, used_language, language)
                if phrase:
                    translations[language] = phrase
                    if real_engine:
                        engines[language] = real_engine
                    if failed:
                        warnings[language] = failed
                elif failed:
                    errors[language] = failed
            translation_ms = round((time.perf_counter()-translate_start)*1000)
        translated = translations.get(target)
        return {"original": original, "raw_asr_original":raw_asr_original,
                "teletext_probe":teletext_probe,
                "teletext_shadow":teletext_shadow,
                "translated": translated, "translations": translations,
                "remote_error":speech_diagnostics.get("remote_error"),
                "remote_fallback":speech_diagnostics.get("remote_fallback"),
                "asr_backend": speech_diagnostics.get("backend"),
                "asr_model": speech_diagnostics.get("model"),
                "asr_engine": speech_diagnostics.get("engine"),
                "language_confidence":speech_diagnostics.get("language_confidence"),
                "detected_language":speech_diagnostics.get("detected_language"),
                "source_language_note":speech_diagnostics.get("source_language_note"),
                "audio_notice": speech_diagnostics.get("audio_notice"),
                "words":speech_diagnostics.get("words", []),
                "word_timing_source":speech_diagnostics.get("word_timing_source"),
                "speaker_turns":speech_diagnostics.get("speaker_turns", []),
                "overlap_lines":speech_diagnostics.get("overlap_lines", []),
                "overlap_model":speech_diagnostics.get("overlap_model"),
                "overlap_note":speech_diagnostics.get("overlap_note"),
                "sound_events":speech_diagnostics.get("sound_events",[]),
                "sound_event_note":speech_diagnostics.get("sound_event_note"),
                "voice_type":speech_diagnostics.get("voice_type"),
                "voice_type_confidence":speech_diagnostics.get("voice_type_confidence"),
                "voice_type_note":speech_diagnostics.get("voice_type_note"),
                "speaker_engine":speech_diagnostics.get("speaker_engine"),
                "speaker_error":speech_diagnostics.get("speaker_error"),
                "speaker_note":speech_diagnostics.get("speaker_note"),
                "recognition_rejected":speech_diagnostics.get("recognition_rejected"),
                "asr_repetitions_removed":speech_diagnostics.get("asr_repetitions_removed",False),
                "asr_test_page_artifact_removed":speech_diagnostics.get(
                    "asr_test_page_artifact_removed",False),
                "speech_priority":speech_diagnostics.get("speech_priority", False),
                "speech_priority_note":speech_diagnostics.get("speech_priority_note"),
                "processing_ms": {
                    "teletext":teletext_ms,"asr":asr_ms,
                    "translation":translation_ms,
                    "total":round((time.perf_counter()-timing_started)*1000)
                },
                "translation_errors": errors,
                "translation_warnings": warnings,
                "translation_engines": engines, "source": used,
                "source_language": used_language, "target_language": target,
                "target_languages": list(targets), "page": page,
                # Speech/capture failures are distinct from a missing
                # translator: never elevate a translation package error
                # to a live ASR failure or turn a traceback into subtitles.
                "error": error}

def install_argos_pack(filename: str) -> str:
    p = Path(filename).expanduser()
    if not p.is_file() or p.suffix != ".argosmodel":
        raise ValueError("Choose a local .argosmodel language pack")
    from argostranslate import package
    package.install_from_path(str(p))
    return p.name
