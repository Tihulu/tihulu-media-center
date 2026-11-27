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
from pathlib import Path

SUPPORTED = ("de", "en", "tr")

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

def _sub_stream(path, service_id):
    streams = _program_streams(path, service_id)
    return next((s["index"] for s in streams
                 if s.get("codec_name") == "dvb_teletext"), None)

def ass_text(raw: str) -> str:
    lines = []
    for line in raw.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10:
            continue
        txt = re.sub(r"\{[^}]*\}", "", fields[9])
        txt = txt.replace(r"\N", " ").replace(r"\n", " ").strip()
        if txt and (not lines or txt != lines[-1]):
            lines.append(txt)
    return "\n".join(lines[-6:])[:1600]

def teletext_from_clip(path: Path, page: int, service_id: int | None = None) -> str:
    if not 100 <= page <= 899:
        raise ValueError("Teletext page must be 100-899")
    idx = _sub_stream(path, service_id)
    if idx is None:
        return ""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-txt_page", str(page), "-txt_format", "ass", "-txt_duration", "4000",
           "-i", str(path), "-map", f"0:{idx}", "-c:s", "ass", "-f", "ass", "-"]
    proc = _run(cmd, timeout=25)
    return ass_text(proc.stdout.decode("utf-8", "replace")) if proc.returncode == 0 else ""

def asr_from_clip(path: Path, language: str, model: str,
                  service_id: int | None = None) -> str:
    if language not in SUPPORTED:
        raise ValueError("Unsupported transcription language")
    if not model or not Path(model).expanduser().is_file():
        raise RuntimeError("Whisper model not installed. Select a local multilingual GGML model.")
    streams = _program_streams(path, service_id)
    audio_index = next((s["index"] for s in streams if s.get("codec_type") == "audio"), None)
    if audio_index is None:
        raise RuntimeError("No audio track in the selected TV service")
    audio = _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                  "-map", f"0:{audio_index}", "-vn", "-ar", "32000", "-ac", "1",
                  "-f", "s16le", "-"], timeout=35)
    if audio.returncode or len(audio.stdout) < 32000:
        raise RuntimeError("No usable audio stream in recorded TV segment")
    # Existing TEXT CENTER speech implementation handles local CPU/GPU selection.
    os.environ["TIHULU_WHISPER_MODEL"] = str(Path(model).expanduser())
    from textcenter.compute import detect_devices, choose_backend
    from textcenter.speech import transcribe_pcm
    profile = detect_devices()
    selected = choose_backend(profile, "auto")
    if not selected.get("ready"):
        raise RuntimeError(selected.get("reason", "Offline speech engine unavailable"))
    return transcribe_pcm(audio.stdout, language, selected["selected"], profile).strip()

def translate(text: str, source: str, target: str) -> tuple[str | None, str | None]:
    if source == target:
        return text, None
    try:
        from textcenter.transcripts import translate_offline
        return translate_offline(text, source, target), None
    except (ImportError, RuntimeError, ValueError, KeyError) as exc:
        return None, "Translation pack missing or failed: " + str(exc)[:120]

def decode_segment(ts: bytes, *, mode="auto", page=150, source="de",
                   target="tr", model="", service_id: int | None = None) -> dict:
    if mode not in ("teletext", "page", "asr", "auto"):
        raise ValueError("Unsupported caption source")
    if not 100 <= page <= 899 or source not in SUPPORTED or target not in SUPPORTED:
        raise ValueError("Invalid language or page")
    if not ts:
        return {"original": "", "source": mode, "error": "No live TS data"}
    with tempfile.TemporaryDirectory(prefix="tihulu-tv-captions-") as tmp:
        p = Path(tmp) / "broadcast.ts"
        p.write_bytes(ts)
        original, used, error = "", "", None
        if mode in ("teletext", "page", "auto"):
            original = teletext_from_clip(p, page, service_id)
            used = f"teletext_page_{page}" if original else ""
        if not original and mode in ("asr", "auto"):
            try:
                original = asr_from_clip(p, source, model, service_id)
                used = "local_asr" if original else ""
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                error = str(exc)[:180]
        translated, translation_error = translate(original, source, target) if original else (None, None)
        return {"original": original, "translated": translated, "source": used,
                "source_language": source, "target_language": target,
                "page": page, "error": error or translation_error}

def install_argos_pack(filename: str) -> str:
    p = Path(filename).expanduser()
    if not p.is_file() or p.suffix != ".argosmodel":
        raise ValueError("Choose a local .argosmodel language pack")
    from argostranslate import package
    package.install_from_path(str(p))
    return p.name
