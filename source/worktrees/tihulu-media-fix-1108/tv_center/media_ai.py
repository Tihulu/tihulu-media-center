"""Offline ASR/translation for user-selected local video or audio.

Uses exactly the installed TIHULU Whisper CUDA/CPU and translator engines,
not a second cloud model. No network access unless --fetch-lyrics explicitly
requests keyless LRCLIB metadata search. Writes timestamped .srt/.lrc
sidecars without overwriting existing work by default.

Examples:
  tihulu-tv-center media-captions --input ~/Videos/news.mp4 --source de --targets en,tr
  tihulu-tv-center media-captions --input ~/Music/song.flac --lyrics --track Title --artist Artist --fetch-lyrics
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from .ai_settings import AISettings
from .captions import translate
from .lyrics_sync import (LyricCue, LiveLyricMatcher, local_lrc, lookup_synced_lyrics,
                          parse_lrc, write_srt, srt_timestamp)
from .language_codes import language_code

CHUNK_SECONDS = 8
CHUNK_SAMPLES = 32000
CHUNK_BYTES = CHUNK_SECONDS * CHUNK_SAMPLES * 2
AUDIO_EXT = frozenset(
    (".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg", ".opus",
     ".wma", ".alac", ".aiff", ".mp4", ".mkv", ".avi", ".mov",
     ".webm", ".ts", ".m2ts", ".mpeg", ".mpg", ".m4v"))


def validate_local_media(filename: str) -> Path:
    if not isinstance(filename,str) or not filename.strip():
        raise ValueError("Choose a local video/audio file")
    media=Path(filename).expanduser().resolve(strict=True)
    if not media.is_file() or media.suffix.lower() not in AUDIO_EXT:
        raise ValueError("Unsupported local media format; expected a video/audio file")
    return media


def media_metadata(media: Path) -> dict:
    proc=subprocess.run([
        "ffprobe","-v","error","-show_entries",
        "format=duration:format_tags=title,artist,album",
        "-of","json",str(media)],
        capture_output=True,text=True,timeout=18,check=False)
    if proc.returncode:
        raise RuntimeError("FFprobe could not read this media file")
    result=json.loads(proc.stdout)
    tags=(result.get("format") or {}).get("tags") or {}
    return {"title":tags.get("title") or tags.get("TITLE") or media.stem,
            "artist":tags.get("artist") or tags.get("ARTIST") or "",
            "album":tags.get("album") or tags.get("ALBUM") or "",
            "duration":float((result.get("format") or {}).get("duration") or 0)}


def _choose_model(ai: AISettings):
    from textcenter.compute import detect_devices,choose_backend
    profile=detect_devices()
    selected=choose_backend(profile,ai.values["backend"])
    if not selected["ready"]:
        raise RuntimeError(
            "No usable offline speech model; install model in AI Market")
    return profile,selected["selected"]


def _near_silent_pcm(pcm: bytes) -> bool:
    """Fail closed only on effectively inaudible signed 16-bit 32kHz PCM.

    Whisper can hallucinate speech (especially when music mode disables VAD)
    over dead-air/silent receiver buffers. Sample a bounded number of native
    little-endian PCM frames; no third-party package or network is needed.
    This is not a voice activity detector: normal quiet speech/music stays
    eligible for Whisper, and music with audible instruments may still
    produce uncertain transcripts.
    """
    if not pcm or len(pcm) % 2:
        return True
    from array import array
    import sys as _sys
    samples = array("h")
    samples.frombytes(pcm)
    if _sys.byteorder != "little":
        samples.byteswap()
    step = max(1, len(samples) // 4096)
    subset = samples[::step]
    if not subset:
        return True
    squared = sum(int(value) * int(value) for value in subset)
    peak = max(abs(int(value)) for value in subset)
    return (squared / len(subset) < 22.0 ** 2 and peak < 65)


def _chunk_cues(pcm: bytes, *, position: float, lang: str, profile:dict,
                backend: str, music:bool=False, detection:dict|None=None) -> list[LyricCue]:
    """Real GPU word cues; legacy CPU models use honest eight-second chunks."""
    text=""
    words=[]
    recognized_language=lang

    if (backend=="gpu" and profile["speech"].get("gpu_engine") ==
            "faster_whisper_managed"):
        from .cuda_faster_whisper import transcribe_cuda_details
        result=transcribe_cuda_details(
            pcm,lang,str(profile["speech"]["gpu_model_path"]),
            music_mode=music)
        text=str(result.get("text") or "").strip()
        words=result.get("words") or []
        recognized_language=result.get("language") if lang=="auto" else lang
        if detection is not None:
            detected=result.get("language")
            if isinstance(detected,str) and len(detected) in (2,3):
                detection["language"]=detected
                detection["confidence"]=result.get("language_probability",0.0)
            detection["recognition_rejected"]=result.get("recognition_rejected")
    else:
        # CPU whisper.cpp can transcribe with -l auto, but this API does
        # not provide a verified language code. Never guess a translation
        # source from an unspecified language; keep original words only.
        from textcenter.speech import transcribe_pcm
        text=transcribe_pcm(pcm,lang,backend,profile).strip()
        if lang=="auto":
            recognized_language="und"
            if detection is not None:
                detection["language"]=None
                detection["confidence"]=0.0
    if not text:
        return []
    duration=len(pcm)/(2*CHUNK_SAMPLES)
    if words:
        # Keep true Whisper word timestamps. No artificial fine alignment
        # of translations: translation is generated for each short group.
        out=[]
        current=[]
        start=None
        end=None
        for word in words:
            token=str(word.get("text") or "").strip()
            ws=word.get("start")
            we=word.get("end")
            if (not token or type(ws) not in (float,int) or
                    type(we) not in (float,int) or
                    not 0 <= ws <= we <= duration+0.5):
                continue
            if start is None:
                start=float(ws)
            end=float(we)
            current.append(token)
            if len(current)>=7 or end-start>=2.4 or token.endswith((".","?","!")):
                out.append(LyricCue(position+start,
                                    position+max(end,start+.3),
                                    " ".join(current),"Whisper/CUDA",recognized_language))
                current=[];start=None;end=None
        if current and start is not None:
            out.append(LyricCue(position+start,
                                position+max(float(end),start+.3),
                                " ".join(current),"Whisper/CUDA",recognized_language))
        return out
    return [LyricCue(position,position+max(.4,min(duration,8)),
                     text,"Whisper chunk / not word-aligned",recognized_language)]


def transcribe_local_media(filename: str, *, source: str="auto",
                           targets=(), music:bool=False,
                           max_seconds:int=7200):
    media=validate_local_media(filename)
    source=("auto" if source=="auto" else language_code(source))
    targets=tuple(dict.fromkeys(language_code(t,nllb=True) for t in targets))
    if len(targets)>3:
        raise ValueError("Choose at most three translation targets")
    ai=AISettings()
    ai.configure_environment()
    if not ai.values["asr_enabled"]:
        raise RuntimeError("Enable offline Whisper in AI Model Market first")
    profile,backend=_choose_model(ai)
    proc=subprocess.Popen([
        "ffmpeg","-nostdin","-hide_banner","-loglevel","error",
        "-i",str(media),"-map","0:a:0","-vn","-ac","1",
        "-ar","32000","-f","s16le","pipe:1"],
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    cues=[]
    pcm_seconds=0
    try:
        while pcm_seconds<max_seconds:
            pcm=proc.stdout.read(CHUNK_BYTES)
            if not pcm:
                break
            if len(pcm)<6400:
                break
            cues.extend(_chunk_cues(pcm,position=pcm_seconds,lang=source,
                                    profile=profile,backend=backend,music=music))
            pcm_seconds+=len(pcm)/(2*CHUNK_SAMPLES)
            if len(cues)>6000:
                raise RuntimeError("Subtitle cue limit reached")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
        if proc.stdout:
            proc.stdout.close()
    if not cues:
        raise RuntimeError("No transcribable speech was detected in this file")
    return cues,targets,backend



def _align_plain_lyrics_to_local_audio(lines, transcript_cues):
    """No guessed lyric positions. Only approximate times where local ASR confirms words."""
    matcher=LiveLyricMatcher(lines)
    aligned=[]
    window=[]
    window_start=None
    def evaluate():
        if not window:
            return
        evidence=matcher.observe(" ".join(c.text for c in window))
        if evidence is None:
            return
        start=min(c.start for c in window)
        end=max(c.end for c in window)
        lang=next((c.language for c in window if c.language),None)
        aligned.append(LyricCue(max(0.,start),max(end,start+1.5),
                                evidence["text"],"plain lyrics / observed ASR",lang))
    for cue in transcript_cues:
        if window_start is None:
            window_start=cue.start
        if window and (cue.start-window_start>=6 or
                       sum(len(c.text) for c in window)>290):
            evaluate()
            window=[]
            window_start=cue.start
        window.append(cue)
    evaluate()
    return aligned


def _lyrics_for_file(media:Path, meta:dict, *,
                     fetch_lyrics:bool=False,artist:str="",track:str="",source:str="auto"):
    local=local_lrc(media)
    if local:
        cues=parse_lrc(local.read_text(encoding="utf-8"),
                       duration=meta.get("duration") or None,
                       provenance=f"local:{local.name}")
        if cues:
            return cues,{"source":"local LRC","path":str(local)}
    if not fetch_lyrics:
        raise RuntimeError(
            "No synced local .lrc found. Explicitly choose --fetch-lyrics "
            "to search LRCLIB online by artist/title.")
    title=track.strip() or meta.get("title","")
    singer=artist.strip() or meta.get("artist","")
    if not singer:
        raise ValueError("Artist metadata missing; provide --artist")
    lines,provenance=lookup_synced_lyrics(
        title=title,artist=singer,album=meta.get("album",""),
        duration=meta.get("duration") or None,online=True,
        allow_plain=True)
    if lines:
        return lines,provenance
    plain=provenance.get("plain_lines",[])
    if plain and provenance.get("status")=="plain":
        heard,_,engine=transcribe_local_media(str(media),source=source,
                                               targets=(),music=True)
        aligned=_align_plain_lyrics_to_local_audio(plain,heard)
        if not aligned:
            raise RuntimeError("Plain lyrics found, but no reliable match with "
                               "heard vocals; not inventing subtitle timestamps")
        return aligned,{"provider":"LRCLIB",
                        "status":"plain_matched_approximate",
                        "matched_lines":len(aligned),
                        "total_plain_lines":len(plain),
                        "alignment":"observed_local_ASR_audio",
                        "backend":engine}
    raise RuntimeError("No matching lyrics: "+provenance.get("status","unknown"))


def _translate_cues(cues:list[LyricCue],targets,source):
    warnings=[]
    translated={}
    for i,cue in enumerate(cues,1):
        if not targets:
            break
        lines=[]
        for dest in targets:
            if dest==source:
                continue
            cue_source=cue.language or source
            if cue_source in ("auto", "und"):
                warnings.append({"cue":i,"target":dest,"warning":
                    "Lyrics language not identified: choose an ISO source code"})
                continue
            if dest==cue_source:
                continue
            output,issue=translate(cue.text,cue_source,dest)
            if output:
                lines.append("["+dest.upper()+"] "+output.strip())
            if issue:
                warnings.append({"cue":i,"target":dest,"warning":issue[:150]})
        if lines:
            translated[i]="\n".join(lines)
    return translated,warnings


def create_subtitles(filename, *, source="auto", targets=(),music=False,
                     lyrics=False,fetch_lyrics=False,artist="",track="",
                     output=None,overwrite=False):
    media=validate_local_media(filename)
    source=("auto" if source=="auto" else language_code(source))
    target_codes=tuple(dict.fromkeys(language_code(t,nllb=True)
                                     for t in targets))
    if len(target_codes)>3:
        raise ValueError("At most three translation languages supported")
    if lyrics:
        meta=media_metadata(media)
        cues,origin=_lyrics_for_file(media,meta,fetch_lyrics=fetch_lyrics,
                                     artist=artist,track=track,source=source)
        backend=("ASR-based approximate lyric alignment"
                 if origin.get("status")=="plain_matched_approximate"
                 else "time-coded lyrics")
    else:
        if fetch_lyrics:
            raise ValueError("--fetch-lyrics requires --lyrics")
        cues,target_codes,backend=transcribe_local_media(
            str(media),source=source,targets=target_codes,music=music)
        origin={"source":"local Whisper", "backend":backend}
    translations,warnings=_translate_cues(cues,target_codes,source)
    output_path=Path(output).expanduser() if output else media.with_suffix(".srt")
    write_srt(cues,output_path,overwrite=overwrite,translations=translations)
    return {
        "status":"completed","input":str(media),"output":str(output_path),
        "source_language":source,"targets":list(target_codes),
        "cues":len(cues),"provenance":origin,
        "backend":backend,
        "translation_warnings":warnings[:12],
        "translation_warning_count":len(warnings),
        "note":"Local timed SRT created. Reopen/refresh file playback in Kaffeine "
               "to pick up sidecar subtitles. No lyrics were invented.",
    }


def main(args=None):
    parser=argparse.ArgumentParser(description=
        "Offline Kaffeine video/audio subtitles using installed AI models")
    parser.add_argument("--input",required=True)
    parser.add_argument("--source",default="auto",
                        help="Automatic per-chunk speech language detection, or ISO code")
    parser.add_argument("--targets",default="",help="CSV such as en,tr")
    parser.add_argument("--music",action="store_true",
                        help="Transcribe singing as well as speech; accuracy varies")
    parser.add_argument("--lyrics",action="store_true",
                        help="Prefer time-coded .lrc by exact metadata, not ASR")
    parser.add_argument("--fetch-lyrics",action="store_true",
                        help="Explicitly authorize keyless LRCLIB HTTPS request")
    parser.add_argument("--track",default="")
    parser.add_argument("--artist",default="")
    parser.add_argument("--output")
    parser.add_argument("--overwrite",action="store_true")
    options=parser.parse_args(args)
    try:
        result=create_subtitles(
            options.input,source=options.source,
            targets=[x.strip() for x in options.targets.split(",") if x.strip()],
            music=options.music,lyrics=options.lyrics,
            fetch_lyrics=options.fetch_lyrics,artist=options.artist,
            track=options.track,output=options.output,
            overwrite=options.overwrite)
    except (ValueError,OSError,RuntimeError,FileExistsError,
            subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status":"error","reason":str(exc)[:300]},
                         ensure_ascii=False),file=sys.stderr)
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
