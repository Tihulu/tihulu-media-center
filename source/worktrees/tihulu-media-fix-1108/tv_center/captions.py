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
                  speech_priority: bool = False) -> str:
    # "auto" is a speech-detection MODE, not an ISO language code.
    # All existing speech backends except unverified NPUs handle it.
    if language != "auto" and language not in SUPPORTED:
        raise ValueError("Unsupported transcription language: " + str(language))
    selected_backend = os.environ.get("TIHULU_TV_ASR_BACKEND", "auto")
    if selected_backend == "off":
        raise RuntimeError("Offline transcription disabled in Settings")
    if selected_backend not in ("auto", "cpu", "gpu", "npu"):
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
    # Existing TEXT CENTER speech implementation handles local CPU/GPU selection.
    os.environ["TIHULU_WHISPER_MODEL"] = str(Path(model).expanduser())
    from textcenter.compute import detect_devices, choose_backend
    from textcenter.speech import transcribe_pcm
    profile = detect_devices()
    selected = choose_backend(profile, selected_backend)
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
            speech_priority=speech_priority)
        if diagnostics is not None:
            diagnostics["words"] = details.get("words", [])
            diagnostics["detected_language"] = details.get("language")
            diagnostics["language_confidence"] = details.get("language_probability")
            diagnostics["word_timing_source"] = "faster_whisper_cuda_word_timestamps"
            diagnostics["recognition_rejected"] = details.get("recognition_rejected")
        return _speaker_details(audio.stdout, details["text"].strip(),
                                diagnostics, speaker_enabled, speaker_provider,
                                channel=f"{service_id}:{audio_pid}")
    transcription = transcribe_pcm(
        audio.stdout, language, selected["selected"], profile).strip()
    return _speaker_details(audio.stdout, transcription,
                            diagnostics, speaker_enabled, speaker_provider,
                            channel=f"{service_id}:{audio_pid}")

def _translate_argos_local(text: str, source: str, target: str) -> str:
    """Translate offline through available system Argos or managed worker."""
    try:
        from textcenter.transcripts import translate_offline
        return translate_offline(text, source, target)
    except (ImportError, RuntimeError, ValueError, KeyError):
        # The user-managed Argos venv is independent of the system Python
        # used by Qt. Reuse its persistent worker for live caption windows.
        from .translation_service import translate_argos
        return translate_argos(text, source, target)


def translate(text: str, source: str, target: str) -> tuple[str | None, str | None]:
    """Return (verified translated text, error/warning), never made-up output.

    If NLLB cannot materialize its weights or exceeds the live time budget,
    the user still gets the requested translation when a suitable Argos pack
    exists. A circuit breaker prevents a bad 2.5-GB NLLB cold start from
    blocking every following live audio segment. Any fallback is reported
    explicitly in diagnostics, not embedded in the on-video subtitle text.
    """
    try:
        source = language_code(source, nllb=True)
        target = language_code(target, nllb=True)
    except ValueError as exc:
        return None, str(exc)
    if source == target:
        return None, None

    from .translation_failover import live_failover
    from .translation_service import translate_nllb
    selected = os.environ.get("TIHULU_TRANSLATOR_MODEL", "argos")
    if selected=="deepl":
        # Explicit online-provider opt-in. Only the decoded text is sent;
        # live RF, TV transport and original audio never leave this device.
        try:
            from .deepl_api import translate_deepl
            translated=translate_deepl(text,source,target)
            return translated,None
        except (ValueError,RuntimeError,OSError,TimeoutError) as exc:
            try:
                replacement=_translate_argos_local(text,source,target)
                return replacement,"DeepL unavailable; offline Argos fallback: "+str(exc)[:100]
            except (ImportError,RuntimeError,ValueError,OSError,KeyError):
                return None,"DeepL unavailable; no compatible offline Argos pair"
    if selected=="madlad":
        from .translation_service import translate_madlad
        import time
        now=time.monotonic()
        blocked=getattr(translate,"_madlad_blocked_until",0.)
        if now>=blocked:
            try:
                return translate_madlad(text,source,target),None
            except (RuntimeError,OSError,ValueError,TimeoutError,ImportError):
                translate._madlad_blocked_until=now+180.
        try:
            return _translate_argos_local(text,source,target),(
                "MADLAD unavailable or too slow; switched to installed offline Argos")
        except (RuntimeError,OSError,ValueError,ImportError,KeyError):
            return None,"MADLAD unavailable; offline Argos pair not installed"
    outcome = live_failover().translate(
        text, source, target, preferred=selected,
        nllb=translate_nllb, argos=_translate_argos_local)
    return outcome.text, outcome.error or outcome.warning


def decode_segment(ts: bytes, *, mode="auto", page=150, source="de",
                   target="tr", targets=None, model="", service_id: int | None = None,
                   previous_text: str = "",
                   teletext_pid: int | None = None,
                   audio_pid: int | None = None,
                   audio_source: str | None = None,
                   speaker_enabled: bool = False,
                   speaker_provider: str = "resemblyzer",
                   music_transcription: bool = False,
                   speech_priority: bool = False) -> dict:
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
                # Real DVB audio-language descriptors are a stronger hint
                # than six seconds of noisy live TV speech. Do not ignore
                # the selected/signalled audio language in Auto mode.
                speech_language = audio_source or source
                original = asr_from_clip(p, speech_language, model, service_id,
                                         **asr_kwargs)
                # Filter only unmistakable repeated Whisper loops (often
                # music/jingle hallucinations). Keep real twice-spoken
                # phrases and opt-in singing/lyrics exactly as transcribed.
                from kaffeine_next.continuous_captions import (
                    collapse_asr_repetition_loops)
                cleaned = (original if music_transcription else
                           collapse_asr_repetition_loops(original))
                if cleaned != original:
                    original = cleaned
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
                        # No invented translation source: display original
                        # speech until the real model reports a language.
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
        translations = {}
        errors = {}
        warnings = {}
        engines = {}
        if original:
            translate_start = time.perf_counter()
            for language in targets:
                if language == used_language:
                    # Requested language already matches the actual Teletext
                    # or selected audio language; original IS the answer.
                    translations[language] = original
                    continue
                phrase, failed = translate(original, used_language, language)
                if phrase:
                    translations[language] = phrase
                    if failed:
                        warnings[language] = failed
                        engines[language] = "argos-fallback"
                    else:
                        engines[language] = os.environ.get(
                            "TIHULU_TRANSLATOR_MODEL", "argos")
                elif failed:
                    errors[language] = failed
            translation_ms = round((time.perf_counter()-translate_start)*1000)
        translated = translations.get(target)
        return {"original": original, "raw_asr_original":raw_asr_original,
                "translated": translated, "translations": translations,
                "asr_backend": speech_diagnostics.get("backend"),
                "asr_model": speech_diagnostics.get("model"),
                "asr_engine": speech_diagnostics.get("engine"),
                "language_confidence":speech_diagnostics.get("language_confidence"),
                "detected_language":speech_diagnostics.get("detected_language"),
                "audio_notice": speech_diagnostics.get("audio_notice"),
                "words":speech_diagnostics.get("words", []),
                "word_timing_source":speech_diagnostics.get("word_timing_source"),
                "speaker_turns":speech_diagnostics.get("speaker_turns", []),
                "speaker_engine":speech_diagnostics.get("speaker_engine"),
                "speaker_error":speech_diagnostics.get("speaker_error"),
                "speaker_note":speech_diagnostics.get("speaker_note"),
                "recognition_rejected":speech_diagnostics.get("recognition_rejected"),
                "asr_repetitions_removed":speech_diagnostics.get("asr_repetitions_removed",False),
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
