# SPDX-License-Identifier: GPL-2.0-or-later
"""Applied caption controls, bounded cue scheduling and private Kaffeine OSD IPC.

Only the current user's runtime directory is used. A caption never moves
audio relative to video: both remain in the DVB transport stream. The optional
native playback buffer is a separate, explicit setting.

Whisper works in chunks; the cue is anchored to capture timestamps and is
displayed as soon as possible, never deceptively described as sample-accurate.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from collections import deque
from statistics import median
import json
import os
from pathlib import Path
import queue
import re
import tempfile
import time

MODE = ("auto", "teletext", "asr", "page", "off")
LANGS = ("de", "en", "tr", "fr")  # quick-select presets only
from tv_center.language_codes import language_code

# Internal event/category codes are language-neutral. Translate only at
# rendering time to the selected visible subtitle language, never hard-code
# Turkish labels into German, English or French broadcasts.
VOICE_NAMES = {
    "en": {"male":"Male voice?","female":"Female voice?","child":"Child voice?"},
    "de": {"male":"Männliche Stimme?","female":"Weibliche Stimme?","child":"Kinderstimme?"},
    "tr": {"male":"Erkek sesi?","female":"Kadın sesi?","child":"Çocuk sesi?"},
    "fr": {"male":"Voix masculine ?","female":"Voix féminine ?","child":"Voix d’enfant ?"},
}
SOUND_NAMES = {
    "en": {"music":"Music","hum":"Humming","applause":"Applause",
           "noise":"Noise","laughter":"Laughter"},
    "de": {"music":"Musik","hum":"Summen","applause":"Applaus",
           "noise":"Rauschen","laughter":"Lachen"},
    "tr": {"music":"Müzik","hum":"Uğultu","applause":"Alkış",
           "noise":"Gürültü","laughter":"Gülüşme"},
    "fr": {"music":"Musique","hum":"Bourdonnement","applause":"Applaudissements",
           "noise":"Bruit","laughter":"Rires"},
}

def _label_language(code):
    return str(code or "en").lower().split("-")[0].split("_")[0]


@dataclass(frozen=True)
class CaptionConfig:
    mode: str = "auto"
    source: str = "de"
    target: str = "tr"
    target_languages: tuple[str, ...] = ("tr",)
    page: int = 150
    teletext_pid: int | None = None
    teletext_language: str | None = None
    audio_pid: int | None = None
    audio_language: str | None = None
    spoken_auto: bool = False  # user requests real ASR language re-detection
    speaker_enabled: bool = False
    show_speaker_numbers: bool = True
    show_voice_types: bool = False
    break_speaker_lines: bool = False
    show_sound_events: bool = False
    separate_overlapping_voices: bool = False
    readable_pacing: bool = True  # prefer natural sentence display over flashing fragments
    live_priority: bool = True  # reduce expensive optional models during ASR backlogs
    music_transcription: bool = False
    speech_priority: bool = False  # optional dialogue focus when background music overlaps
    speaker_provider: str = "resemblyzer"
    speaker_aliases: tuple[str, ...] = ()
    offset_ms: int = 0
    playback_delay_ms: int = 0
    automatic_sync: bool = False
    on_video: bool = True
    render_mode: str = "native"  # libVLC compositor, never a QWidget over video
    show_original: bool = True
    show_translation: bool = True
    position: str = "bottom"
    font_px: int = 25
    opacity: int = 70
    text_opacity: int = 100
    text_color: str = "#FFFFFF"
    background_color: str = "#000000"
    revision: int = 0

    def validate(self):
        if self.mode not in MODE:
            raise ValueError("Unknown caption source")
        if self.source != "auto":
            language_code(self.source, nllb=True)
        language_code(self.target, nllb=True)
        if type(self.page) is not int or not 100 <= self.page <= 899:
            raise ValueError("Teletext page must be an integer 100–899")
        if self.teletext_pid is not None and (
                type(self.teletext_pid) is not int or not 1 <= self.teletext_pid <= 8190):
            raise ValueError("Invalid broadcaster Teletext subtitle PID")
        if self.teletext_language is not None:
            language_code(self.teletext_language)
        if self.audio_pid is not None and (
                type(self.audio_pid) is not int or not 1 <= self.audio_pid <= 8190):
            raise ValueError("Invalid selected broadcaster audio PID")
        if self.audio_language is not None:
            language_code(self.audio_language)
        if self.speaker_provider not in ("resemblyzer", "pyannote"):
            raise ValueError("Choose an available offline speaker backend")
        if (not isinstance(self.speaker_aliases,tuple) or
                len(self.speaker_aliases)>4 or
                any(not isinstance(alias,str) or len(alias)>32 or
                    "\n" in alias or "\r" in alias
                    for alias in self.speaker_aliases)):
            raise ValueError("Speaker labels must be four short names or fewer")
        if type(self.offset_ms) is not int or not -10000 <= self.offset_ms <= 10000:
            raise ValueError("Caption offset must be -10 to +10 seconds")
        if type(self.playback_delay_ms) is not int or not 0 <= self.playback_delay_ms <= 20000:
            raise ValueError("Playback buffering must be 0–20 seconds")
        if (not isinstance(self.target_languages, tuple) or
                len(self.target_languages) > 6 or
                len(set(self.target_languages)) != len(self.target_languages)):
            raise ValueError("Output languages must be distinct (up to six)")
        if not self.show_original and not self.show_translation:
            raise ValueError("Select original transcript and/or translation")
        if self.render_mode not in ("native", "legacy-qt"):
            raise ValueError("Unknown subtitle renderer")
        if self.position not in ("bottom", "top"):
            raise ValueError("Unknown caption position")
        if type(self.font_px) is not int or not 16 <= self.font_px <= 44:
            raise ValueError("Font size must be 16–44 pixels")
        if type(self.opacity) is not int or not 0 <= self.opacity <= 100:
            raise ValueError("Background opacity must be 0–100%")
        if type(self.text_opacity) is not int or not 0 <= self.text_opacity <= 100:
            raise ValueError("Text opacity must be 0–100%")
        for field in ("text_color", "background_color"):
            chosen = getattr(self,field)
            if (not isinstance(chosen,str) or
                    re.fullmatch(r"#[0-9A-Fa-f]{6}",chosen) is None):
                raise ValueError(
                    field + " must be an RGB hex color such as #FFFFFF")
        for key in ("automatic_sync", "on_video", "show_original", "show_translation",
                    "speaker_enabled", "music_transcription", "speech_priority",
                    "spoken_auto", "show_speaker_numbers",
                    "show_voice_types", "break_speaker_lines",
                    "show_sound_events", "separate_overlapping_voices",
                    "readable_pacing", "live_priority"):
            if type(getattr(self, key)) is not bool:
                raise ValueError("Caption display toggles must be boolean")
        return self

    def options(self):
        return {"mode":self.mode,"source":self.source,
                "target":self.target,"targets":self.target_languages,
                "translation_requested":bool(self.show_translation),
                "page":self.page,"teletext_pid":self.teletext_pid,
                "teletext_language":self.teletext_language,
                "audio_pid":self.audio_pid,"audio_source":self.audio_language,
                "spoken_auto":self.spoken_auto,
                "speaker_enabled":self.speaker_enabled,
                "show_speaker_numbers":self.show_speaker_numbers,
                "show_voice_types":self.show_voice_types,
                "break_speaker_lines":self.break_speaker_lines,
                "show_sound_events":self.show_sound_events,
                "separate_overlapping_voices":self.separate_overlapping_voices,
                "readable_pacing":self.readable_pacing,
                "live_priority":self.live_priority,
                "music_transcription":self.music_transcription,
                "speech_priority":self.speech_priority,
                "speaker_provider":self.speaker_provider,
                "revision":self.revision}

    def _voice_prefix(self,result,language="en"):
        if not self.speaker_enabled:
            return ""
        index=result.get("speaker_index")
        category=str(result.get("voice_type") or "").lower()
        score=result.get("voice_type_confidence")
        threshold=0.95 if category=="child" else 0.88
        if (self.show_voice_types and category in ("male","female","child")
                and isinstance(score,(float,int)) and score>=threshold):
            names=VOICE_NAMES.get(_label_language(language),VOICE_NAMES["en"])
            return ("["+names[category]+
                    (f" {index}" if type(index) is int else "")+"]")
        if not self.show_speaker_numbers:
            return ""
        if type(index) is int and 1<=index<=len(self.speaker_aliases):
            alias=self.speaker_aliases[index-1].strip()
            if alias:
                return "["+alias+"]"
        return str(result.get("speaker_label") or "").strip()[:55]

    @staticmethod
    def _event_lines(result,language="en"):
        # Show only detector-backed events (AST), never invent noise from
        # silence/voice pitch. Sound tags are INDEPENDENT of speaker labels.
        names=SOUND_NAMES.get(_label_language(language),SOUND_NAMES["en"])
        labels=[]
        for event in (result.get("sound_events") or [])[:3]:
            if isinstance(event,dict):
                kind=str(event.get("type","")).lower()
                score=event.get("confidence")
                if (kind in names and isinstance(score,(float,int))
                        and score>=0.80 and
                        event.get("source")=="AST AudioSet"):
                    labels.append("["+names[kind]+"]")
        return labels

    def render(self, result):
        """Produce independently selectable original/translated subtitle lines."""
        original = (result.get("original") or "").strip()
        original_language=result.get("source_language") or self.source
        speaker=self._voice_prefix(result,original_language)
        speaker_index=result.get("speaker_index")
        raw = result.get("translations")
        translated = raw if isinstance(raw, dict) else {}
        lines = []
        # Real overlap: independently separated audio and independently
        # recognized texts only. No fabricated second speaker.
        streams=result.get("overlap_lines")
        if (self.separate_overlapping_voices and isinstance(streams,list)
                and len(streams)==2):
            for item in streams:
                if not isinstance(item,dict):
                    continue
                label=self._voice_prefix(
                    item,item.get("source_language") or original_language)
                speech=str(item.get("original") or "").strip()
                translation=item.get("translations") or {}
                chunks=[]
                if self.show_original and speech:
                    chunks.append(speech)
                if self.show_translation:
                    for code in self.target_languages:
                        phrase=translation.get(code)
                        if isinstance(phrase,str) and phrase.strip():
                            if not (self.show_original and phrase.strip()==speech):
                                chunks.append(f"[{code.upper()}] "+phrase.strip())
                if chunks:
                    lines.append((label+" " if label else "")+" | ".join(chunks))
            if lines:
                if self.show_sound_events:
                    event_language=(self.target_languages[0]
                                    if self.show_translation and self.target_languages
                                    else original_language)
                    detected=self._event_lines(result,event_language)
                    if detected:
                        lines.append(" ".join(dict.fromkeys(detected)))
                return "\n".join(lines[:4])[:1100]
        if self.show_original and original:
            original_language = result.get("source_language") or self.source
            prefix = (f"[{original_language.upper()}] " if
                      self.show_translation and self.target_languages and translated else "")
            lines.append((speaker + "  " if speaker else "") + prefix + original)
        if self.show_translation:
            if translated:
                for language in self.target_languages:
                    phrase = translated.get(language)
                    source_language = result.get("source_language") or self.source
                    already_original = (
                        isinstance(phrase, str) and phrase.strip() == original)
                    # Requested original-language output is meaningful when
                    # translation-only was chosen, but avoid duplicate lines
                    # when 'Original + translations' already shows it.
                    if (isinstance(phrase, str) and phrase.strip() and (
                            not already_original or (
                                not self.show_original and language == source_language))):
                        translated_speaker=self._voice_prefix(result,language)
                        lines.append(
                            (translated_speaker + "  " if translated_speaker else "") +
                            f"[{language.upper()}] " + phrase.strip())
            else:
                legacy = (result.get("translated") or "").strip()
                if legacy and legacy != original:
                    lines.append(legacy)
        if self.show_sound_events:
            # Independent acoustic evidence is a NEW line after speech and
            # translations, not a prefix to ASR or translator input.
            event_language=(self.target_languages[0]
                            if self.show_translation and self.target_languages
                            else original_language)
            detected=self._event_lines(result,event_language)
            if detected:
                lines.append(" ".join(dict.fromkeys(detected)))
        # If the viewer requested translated-only subtitles but no model
        # could translate into the selected language, never blank the screen.
        # Broadcast / Whisper original remains visible with an explicit label.
        if not lines and original and self.show_translation:
            actual = (result.get("source_language") or self.source).upper()
            if self.target_languages:
                codes = ", ".join(self.target_languages).upper()
                lines.append(f"[{actual} · original; {codes} unavailable] " + original)
            else:
                lines.append(f"[{actual} · original] " + original)
        return "\n".join(lines)[:1100]

def effective_cue_config(config: CaptionConfig, native_status: dict | None) -> CaptionConfig:
    """Use the delay Kaffeine actually applies, not a requested but capped delay.

    Kaffeine's 64-MiB DVB buffer can temporarily shrink for high-bitrate
    services, timeshift, or recovery. A fresh status is already checked by
    KaffeineOSD.read_effective_delay(). Reject a status from an older
    user request: the C++ player may not have processed Apply yet.
    This is best effort; libVLC's own output latency is not measured.
    """
    if (not isinstance(native_status, dict) or
            type(native_status.get("requested_ms")) is not int or
            native_status["requested_ms"] != config.playback_delay_ms):
        return config
    actual = native_status.get("effective_ms")
    if type(actual) is not int or not 0 <= actual <= config.playback_delay_ms:
        return config
    observed = native_status.get("released_age_ms")
    # The native FIFO's measured TS age is more informative than the
    # *target* duration, but the player may add further decode latency.
    # Only trust an acknowledged, fresh release measurement.
    if (native_status.get("primed") and
            type(observed) is int and 0 <= observed <= config.playback_delay_ms
            and native_status.get("release_fresh")):
        actual=observed
    return replace(config, playback_delay_ms=actual)


class NativeReleaseClock:
    """Damp TS-release measurement jitter without claiming actual video PTS.

    Kaffeine's FIFO age is refreshed many times per second. A single low
    sample would advance subtitles relative to video, while a single high
    sample would make them late. Median + bounded slew rate prevents
    intermittent "perfect then suddenly early" subtitle jumps.
    """

    def __init__(self, window=7, max_step_ms=220):
        if not 3 <= window <= 15 or not 50 <= max_step_ms <= 500:
            raise ValueError("Invalid native release-clock filter")
        self.window=window
        self.max_step_ms=max_step_ms
        self.clear()

    def clear(self):
        self.samples=deque(maxlen=self.window)
        self.last_stamp=None
        self.last_target=None
        self.current_ms=None

    def stabilized(self, state):
        if not isinstance(state,dict):
            return state
        request=state.get("requested_ms")
        effective=state.get("effective_ms")
        if (type(request) is not int or type(effective) is not int or
                request<0 or effective<0 or effective>request):
            return state
        key=(request,effective)
        if self.last_target != key:
            self.clear()
            self.last_target=key
        observed=state.get("released_age_ms")
        stamp=state.get("released_at_ms")
        if (not state.get("release_fresh") or
                type(observed) is not int or type(stamp) is not int):
            return state
        if stamp!=self.last_stamp:
            self.last_stamp=stamp
            self.samples.append(observed)
            import statistics
            target=int(statistics.median(self.samples))
            target=max(0,min(request,target))
            if self.current_ms is None:
                # Stay near actual applied FIFO target until repeated
                # observations establish a trustworthy release age.
                self.current_ms=max(0,min(
                    request,max(effective-350,min(effective+350,target))))
            else:
                delta=max(-self.max_step_ms,
                          min(self.max_step_ms,target-self.current_ms))
                self.current_ms=max(0,min(request,self.current_ms+delta))
        adjusted=dict(state)
        adjusted["raw_released_age_ms"]=observed
        adjusted["released_age_ms"]=self.current_ms
        adjusted["release_clock_filtered"]=True
        return adjusted


def confirmed_cue_config(config: CaptionConfig,
                         native_status: dict | None) -> CaptionConfig | None:
    """Do not schedule captions ahead of an unacknowledged delay change.

    If a 15-second TV buffer is REQUESTED but the player still reports the
    old 3-second buffer, using '15' would display text up to 12 seconds
    ahead of the video. No number is safe until the native status matches.
    No-buffer mode can function without a native acknowledgement.
    """
    if config.playback_delay_ms <= 0 and native_status is None:
        return config
    if (not isinstance(native_status,dict) or
            native_status.get("requested_ms") != config.playback_delay_ms or
            type(native_status.get("effective_ms")) is not int or
            native_status.get("primed") is False):
        return None
    # Current native builds report the *actual* TS release age. Do not send
    # early subtitles after the FIFO says "primed" but before the first
    # measured TS release sample is available. Legacy 3/5-field builds
    # remain supported with reduced synchronization accuracy.
    if (config.playback_delay_ms > 0
            and native_status.get("has_release_clock")
            and not native_status.get("release_fresh")):
        return None
    return effective_cue_config(config,native_status)


# The audio/video native queue reports TS buffering, not the exact
# libVLC presentation timestamp. Bias captions slightly BEHIND speech rather
# than revealing the next line too early while dialogue is still playing.
def provisional_ai_buffer_ms(is_pi5):
    """One-time, conservative ASR startup delay; NEVER pretend it is a
    measured lip-sync or sustained inference benchmark. The native TS FIFO
    may cap it according to bitrate/RAM and must acknowledge priming.
    """
    if type(is_pi5) is not bool:
        raise ValueError("Raspberry Pi flag must be boolean")
    return 6000 if is_pi5 else 10000


def readable_display_seconds(result, config):
    """Human reading time, without asserting word-perfect source timing.

    Translating can double the visible text. A cue is allowed to remain
    AFTER its audio slot; it must not flash away because ASR was late.
    Pacing is capped so another complete sentence can still make progress.
    """
    if not config.readable_pacing:
        return 1.75 if result.get("word_progress") else 2.3
    original = str(result.get("original") or "").strip()
    translated = result.get("translations") or {}
    visible = []
    if config.show_original and original:
        visible.append(original)
    if config.show_translation:
        visible.extend(str(translated[lang]) for lang in config.target_languages
                       if isinstance(translated.get(lang),str) and
                       translated[lang].strip() and
                       not (config.show_original and
                            translated[lang].strip()==original))
    chars=sum(len(line) for line in visible)
    # Around 16 visible characters per second incl. reading transitions.
    # Short timed snippets are not overwritten at 200ms intervals.
    if result.get("word_progress"):
        return max(1.35,min(3.8,0.65+chars/19.0))
    return max(2.8,min(8.0,0.85+chars/16.0))


CAPTION_SAFETY_HOLD_SEC = 0.55
# Faster-Whisper word boundaries already describe the source audio timeline.
# An additional half-second safety hold noticeably desynchronizes dialogue.
# A modest bias remains until libVLC video PTS is calibrated end-to-end.
WORD_TIMESTAMP_HOLD_SEC = 0.15


def cue_window(started, ended, finished, config: CaptionConfig, result=None):
    """Schedule from observed speech, never the Whisper-completion wall clock.

    Multi-chunk/sentence ASR outputs describe completed speech near the END
    of the captured audio, not the beginning of a six-second (or longer)
    collection window. Starting the clock at the first TS packet made live
    transcriptions lead speech by several seconds. Genuine word groups still
    use their source-relative start timestamps. This is a coarse alignment
    without calibrated DVB PTS, not lip-sync accuracy.
    """
    anchor = float(started)
    if (isinstance(result,dict) and result.get("source")=="local_asr"
            and not result.get("word_progress")):
        # A completed *whole sentence* can still have real source-word
        # timestamps even when the reader chose not to show flashing word
        # fragments. Reveal that finished sentence near the first VERIFIED
        # spoken word, allowing longer text to be read naturally. Never
        # reuse this for untimed CPU ASR or merged multi-clip text.
        first_word = None
        if (result.get("word_timing_source") and
                isinstance(result.get("words"),list) and result["words"]):
            first_word=result["words"][0]
        duration=max(0.0,float(ended)-float(started))
        words=result.get("words")
        last_word=words[-1] if isinstance(words,list) and words else None
        if (isinstance(first_word,dict) and isinstance(last_word,dict)
                and type(first_word.get("start")) in (int,float)
                and type(last_word.get("end")) in (int,float)
                and 0<=first_word["start"]<=last_word["end"]<=duration+0.25
                and not (result.get("ts_integrity") or {}).get("critical_gaps")):
            # Complete source-timed sentences are useful slightly ahead,
            # but must never reveal a six-second scene five seconds early.
            anchor=float(started)+max(
                float(first_word["start"]),float(last_word["end"])-2.5)
        else:
            # CPU/untimed ASR cannot claim word alignment. Show near the
            # end of the observed six-second window as a conservative guess.
            anchor=max(float(started),float(ended)-0.75)
    source_due = anchor + (
        config.playback_delay_ms + config.offset_ms) / 1000.0
    timed = bool(isinstance(result, dict) and result.get("word_progress"))
    source_due += (WORD_TIMESTAMP_HOLD_SEC if timed else CAPTION_SAFETY_HOLD_SEC)
    due = max(float(finished), source_due)
    spoken = max(0.0,float(ended)-float(started))
    # A chunk/word snippet should be readable before replacement. A
    # Teletext line naturally persists longer than a rapidly changing word.
    duration = max(readable_display_seconds(result or {},config),
                   max(2.3,min(7.0,spoken+1.0)))
    return {
        "due":due,
        "expires":due+duration,
        "lateness_ms":max(0,round((float(finished)-source_due)*1000)),
        "revision":config.revision,
    }


class CueQueue:
    """Monotonic, ordered, readable subtitle phrases (never latest-due jump).

    A 120-ms Qt poll previously selected due[-1] and *discarded* earlier
    phrases. Several word groups due at decoder completion therefore flashed
    or disappeared, and nearby rolling translations repeated. Reserve a
    minimum reading slot for each segment and retain chronological order.
    """
    def __init__(self, maximum=36, minimum_hold=1.75):
        if maximum < 1 or not 0.5 <= minimum_hold <= 10:
            raise ValueError("Invalid natural subtitle queue limits")
        self.maximum = maximum
        self.minimum_hold = float(minimum_hold)
        self.items = []
        self.last_shown_at = None
        self._recent = {}

    def add(self, result, config, captured_start, captured_end, finished):
        when = cue_window(captured_start, captured_end, finished, config, result)
        original = str(result.get("original") or "").strip()
        key = (" ".join(original.casefold().split()),
               str(result.get("source") or ""))
        # Repeated broadcaster subtitle pages or overlap in Whisper clips
        # must not re-emit identical complete phrases. Never suppress short
        # acknowledgements like 'ja', which can really be spoken twice.
        # Overlap or near-immediate duplicates only, not genuine repeats
        # many seconds later.
        if len(key[0]) >= 12:
            recent = self._recent.get(key)
            if recent and (float(captured_start) <= recent[1]+1.5
                           and float(captured_start)-recent[0] < 30):
                # Continuous broadcaster repeats can span many 6-second
                # clips. Extend the prior window only for genuinely
                # overlapping identical text; a later repeat remains valid.
                self._recent[key]=(recent[0],
                                   max(recent[1],float(captured_end)))
                return {"result":dict(result),"config":config,
                        "skipped_duplicate":True, **when}
            self._recent[key]=(float(captured_start),float(captured_end))
            if len(self._recent)>80:
                self._recent={k:v for k,v in self._recent.items()
                              if float(captured_start)-v[1]<12}
        # Expiration means the END of the preferred media display slot,
        # NOT permission to discard a decoded phrase that has never been
        # seen. Late ASR, UI stalls or one slow translation must not erase
        # already-queued real speech. The maximum queue bound still applies.
        self.items = [item for item in self.items
                      if item["revision"] == config.revision]
        # Untimed phrases need reading slots; source-word-timed groups do
        # NOT. Stacking a fixed 1.75s gap per group can accumulate several
        # seconds of lag during fast alternating speakers, even with 20s
        # of video buffer. Respect the speech clock for timed groups.
        timed = bool(result.get("word_progress"))
        if self.items and not timed:
            last = max(item["due"] for item in self.items)
            when["due"] = max(when["due"], last+self.minimum_hold)
            when["expires"] = max(when["expires"],
                                  when["due"]+self.minimum_hold+0.45)
        cue = {"result":dict(result),"config":config,**when}
        self.items.append(cue)
        self.items.sort(key=lambda item:item["due"])
        # Keep *earliest* chronological cues if a background engine produces
        # too much work; never drop every earlier phrase for the newest one.
        self.items = self.items[:self.maximum]
        return cue

    def poll(self, now, revision):
        self.items=[item for item in self.items
                    if item["revision"]==revision]
        if not self.items or self.items[0]["due"]>now:
            return None
        next_timed = bool(self.items[0]["result"].get("word_progress"))
        # A 200-ms word flash is almost impossible to read, especially
        # with two translated languages. Apply a modest minimum without
        # serially adding 1.75s to every source-timed word.
        hold = (min(self.minimum_hold,0.8) if next_timed
                and self.items[0]["config"].readable_pacing
                else min(self.minimum_hold,0.2) if next_timed
                else self.minimum_hold)
        if (self.last_shown_at is not None and
                now-self.last_shown_at < hold):
            return None
        selected=self.items.pop(0)
        # Expiry is a DISPLAY deadline, not merely an ASR speech-clock
        # deadline. If the GUI is briefly busy, don't show a subtitle that
        # is already expired or make it vanish before humans can read it.
        selected["expires"]=max(
            selected["expires"],
            float(now)+readable_display_seconds(
                selected["result"],selected["config"]))
        self.last_shown_at=float(now)
        return selected

    def retime(self, offset_delta_ms, config):
        """Shift pending caption display times without re-running ASR.

        A user changing subtitle offset or appearance must not delete
        already decoded speech. Revalidate the cue's revision at rendering,
        and apply even negative offsets to the pending display deadlines.
        """
        if type(offset_delta_ms) is not int or abs(offset_delta_ms) > 20000:
            raise ValueError("Invalid subtitle offset adjustment")
        delta = offset_delta_ms / 1000.0
        for item in self.items:
            item["due"] += delta
            item["expires"] = max(item["due"] + 0.6,
                                  item["expires"] + delta)
            item["config"] = config
            item["revision"] = config.revision
        self.items.sort(key=lambda item: item["due"])

    def clear(self):
        self.items.clear()
        self.last_shown_at=None
        self._recent.clear()


class SpeakerLineHistory:
    """Keep the previous actually transcribed voice on a separate line.

    This NEVER generates overlap: both lines are captions emitted by ASR.
    A true overlapping-source result is handled by CaptionConfig.render and
    has two verified independently transcribed tracks already.
    """
    def __init__(self):
        self.previous = None

    def clear(self):
        self.previous = None

    def compose(self, result, rendered, config, now, epoch=None):
        if (not config.break_speaker_lines or
                not config.speaker_enabled or
                result.get("source")!="local_asr" or
                result.get("overlap_lines")):
            self.clear()
            return rendered
        index=result.get("speaker_index")
        if type(index) is not int or not 1<=index<=4:
            self.clear()
            return rendered
        recent=self.previous
        # Speaker history contains only genuine utterances. A sound tag
        # belongs to its own acoustic window and must never be replayed
        # as a previous speaker's words on the next speaker change.
        history_text=rendered
        if config.show_sound_events:
            event_language=(config.target_languages[0]
                            if config.show_translation and config.target_languages
                            else result.get("source_language") or config.source)
            tags=config._event_lines(result,event_language)
            suffix="\n"+" ".join(dict.fromkeys(tags)) if tags else ""
            if suffix and history_text.endswith(suffix):
                history_text=history_text[:-len(suffix)]
        current=(index,history_text,float(now),config.revision,epoch)
        self.previous=current
        if (recent and recent[0]!=index and
                recent[3]==config.revision and recent[4]==epoch
                and 0 <= float(now)-recent[2] <= 3.5):
            return recent[1]+"\n"+rendered
        return rendered


@dataclass(frozen=True)
class SyncRecommendation:
    """Coarse caption-availability timing, *not* word-aligned lip sync."""
    samples: int
    observed_lag_ms: int
    safe_min_ms: int
    safe_max_ms: int
    suggested_delay_ms: int
    safety_cap_ms: int
    saturated: bool

    @property
    def summary(self):
        band = f"{self.safe_min_ms / 1000:.1f}–{self.safe_max_ms / 1000:.1f} s"
        suffix = (" · processing exceeds safe TV buffer; late text is possible"
                  if self.saturated else "")
        return (f"Estimated caption availability lag: "
                f"{self.observed_lag_ms / 1000:.1f} s · "
                f"safe playback delay: {band} · "
                f"suggested: {self.suggested_delay_ms / 1000:.1f} s "
                f"({self.samples} live ASR samples){suffix}")


class AutoSyncEstimator:
    """Measure real Whisper+translation completion vs sampled DVB timeline.

    The spoken-word start inside a multi-second chunk is unknown. This only
    estimates *when the caption becomes available*, not the precise phoneme
    offset. Native Teletext captions should not train an ASR estimate.
    """
    def __init__(self, minimum=3, maximum=12, ceiling_ms=15000):
        if not 1 <= minimum <= maximum or not 0 <= ceiling_ms <= 20000:
            raise ValueError("Invalid automatic sync limits")
        self.minimum = minimum
        self.ceiling_ms = ceiling_ms
        self.values = deque(maxlen=maximum)

    def clear(self):
        self.values.clear()

    def observe(self, captured_start, captured_end, decoded_at, source):
        if source != "local_asr":
            return False
        try:
            start = float(captured_start)
            end = float(captured_end)
            done = float(decoded_at)
        except (TypeError, ValueError):
            return False
        # Unrealistic or discontinuous segment durations must not teach
        # automatic buffering or silently adjust a live DVB player.
        if not 0.5 <= end - start <= 12 or not end <= done <= end + 30:
            return False
        self.values.append(round((done - start) * 1000))
        return True

    def recommend(self, *, bytes_per_second=None, platform_cap_ms=None):
        if len(self.values) < self.minimum:
            return None
        cap = self.ceiling_ms
        if platform_cap_ms is not None:
            cap = min(cap, max(0, int(platform_cap_ms)))
        # Native delayed MPEG-TS queue is capped at 64 MiB; reserve 16 MiB
        # for bursts/other TV buffers. The byte-rate is a coarse estimate.
        if bytes_per_second is not None and bytes_per_second > 0:
            cap = min(cap, max(0, int(48 * 1024 * 1024 * 1000 /
                                       float(bytes_per_second))))
        cap = max(0, min(20000, (cap // 500) * 500))
        ordered = sorted(self.values)
        med = int(median(ordered))
        p80 = ordered[int(round(0.8 * (len(ordered) - 1)))]
        def up500(value):
            return max(0, ((max(0, int(value)) + 499) // 500) * 500)
        lower = min(cap, up500(med + 250))
        upper = min(cap, max(lower, up500(p80 + 1400)))
        suggested = min(cap, max(lower, up500(p80 + 900)))
        return SyncRecommendation(
            samples=len(ordered), observed_lag_ms=med,
            safe_min_ms=lower, safe_max_ms=upper,
            suggested_delay_ms=suggested, safety_cap_ms=cap,
            saturated=(p80 + 900 > cap),
        )


class AutoSyncController:
    """Keep live playback stable: opt-in + initial settle + slow adjustments.

    A user-specified caption offset remains manual fine-tuning because chunk
    timestamps do not identify individual words in a sentence.
    """
    def __init__(self, cooldown_seconds=30, deadband_ms=750, step_ms=500):
        self.cooldown_seconds = cooldown_seconds
        self.deadband_ms = deadband_ms
        self.step_ms = step_ms
        self.last_change_at = None
        self.has_applied = False

    def reset(self):
        self.last_change_at = None
        self.has_applied = False

    def next_delay(self, recommendation, current_ms, now, enabled):
        """Automatic mode can ONLY raise an insufficient user TV delay.

        A previously configured 14.5-second buffer must never be reduced to
        a fresh 9-second ASR recommendation, even if the estimator's bitrate
        memory cap subsequently drops. Too much existing delay is not a
        subtitle safety problem; too little can show text prematurely.
        Only an explicit manual user action may lower playback buffering.
        """
        if not enabled or recommendation is None:
            return None
        current_ms = int(current_ms)
        desired = int(recommendation.suggested_delay_ms)
        # The measured safe capacity may be below the existing buffer. That
        # does not authorize erasing the user's larger stable configuration.
        if desired <= current_ms or recommendation.safety_cap_ms <= current_ms:
            return None
        if not self.has_applied:
            self.has_applied = True
            self.last_change_at = now
            return desired
        if self.last_change_at is not None and (
                now - self.last_change_at < self.cooldown_seconds):
            return None
        if desired - current_ms < self.deadband_ms:
            return None
        next_ms = min(recommendation.safety_cap_ms,
                      current_ms + self.step_ms)
        next_ms = max(current_ms, (next_ms // 500) * 500)
        if next_ms <= current_ms:
            return None
        self.last_change_at = now
        return next_ms


def buffer_fill_progress(native: dict | None, requested_ms: int) -> dict:
    """Measured native DVB playback-buffer fill, never a GUI-timer estimate.

    Return None for percent if the receiver status is missing, stale, for an
    earlier request, or from an old native build lacking queue-age telemetry.
    100% means the native producer explicitly marked the buffer primed.
    """
    if type(requested_ms) is not int or not 0 <= requested_ms <= 20000:
        raise ValueError("Invalid requested TV buffer")
    unknown = {"percent": None, "state": "waiting", "queued_ms": None,
               "effective_ms": None, "requested_ms": requested_ms}
    if not isinstance(native, dict) or native.get("requested_ms") != requested_ms:
        return unknown
    effective = native.get("effective_ms")
    if type(effective) is not int or not 0 <= effective <= requested_ms:
        return unknown
    if requested_ms == 0:
        return {"percent": 100, "state": "live", "queued_ms": 0,
                "effective_ms": 0, "requested_ms": 0}
    if effective == 0:
        return {"percent": 0, "state": "unavailable", "queued_ms": 0,
                "effective_ms": 0, "requested_ms": requested_ms}
    if not native.get("has_queue_age", True):
        return unknown
    queued = native.get("queue_age_ms")
    if type(queued) is not int or queued < 0 or queued > 60000:
        return unknown
    primed = native.get("primed") is True
    percentage = (100 if primed else
                  max(0, min(99, round(100 * queued / effective))))
    return {"percent": percentage,
            "state": "ready" if primed else "filling",
            "queued_ms": min(queued, effective),
            "effective_ms": effective,
            "requested_ms": requested_ms}


class KaffeineOSD:
    def __init__(self, pid, runtime=None):
        runtime = Path(runtime or os.environ.get("XDG_RUNTIME_DIR", ""))
        if not runtime.is_dir() or runtime.is_symlink():
            raise ValueError("XDG_RUNTIME_DIR unavailable or unsafe")
        if type(pid) is not int or pid <= 0 or pid > 2**31-1:
            raise ValueError("Invalid Kaffeine PID")
        self.root = runtime
        self.path = runtime / f"tihulu-caption-{pid}.json"
        self.delay = runtime / f"tihulu-playback-delay-{pid}.txt"
        self.effective = runtime / f"tihulu-playback-effective-{pid}.txt"
        self.last_delay = 0

    def _atomic(self, path, content):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix=".tihulu-",
                                         dir=self.root, delete=False) as fp:
            temp = Path(fp.name)
            fp.write(content)
        try:
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def publish(self, text, config: CaptionConfig, ttl_ms=2000):
        config.validate()
        if not config.on_video or config.mode == "off":
            text = ""
        obj = {"text":str(text)[:1100], "position":config.position,
               "render_mode":config.render_mode,
               "size":config.font_px, "opacity":config.opacity,
               "text_opacity":config.text_opacity,
               "text_color":config.text_color,
               "background_color":config.background_color,
               "enabled":bool(config.on_video and config.mode != "off"),
               "expires_ms":int(time.time()*1000) + min(max(int(ttl_ms),0),15000)}
        self._atomic(self.path, json.dumps(obj,ensure_ascii=False,separators=(",",":")))

    def set_playback_delay(self, config: CaptionConfig):
        config.validate()
        self._atomic(self.delay, str(config.playback_delay_ms) + "\n")
        self.last_delay = config.playback_delay_ms

    def read_effective_delay(self):
        """Native Kaffeine reports its queue setting, not end-to-end VLC delay.

        Return None if the player has not reported recently; never claim the
        user-requested number is the *actual* delayed broadcast.
        """
        try:
            info = self.effective.stat()
            if not info.st_uid == os.getuid() or time.time()-info.st_mtime > 3.5:
                return None
            if info.st_size > 120 or info.st_size < 3:
                return None
            values = list(map(int, self.effective.read_text().split()))
            released_age_ms = None
            released_at_ms = None
            release_fresh = False
            has_release_clock = len(values)==7
            if len(values) in (5,7):
                requested, actual, bps, primed_flag, queue_age = values[:5]
                if primed_flag not in (0,1) or not 0 <= queue_age <= 60000:
                    return None
                primed = bool(primed_flag)
                has_queue_age = True
                if len(values)==7:
                    measured_age, released_at = values[5:7]
                    now_ms=int(time.time()*1000)
                    if (0 <= measured_age <= 60000 and
                            0 <= now_ms-released_at <= 3500):
                        released_age_ms = measured_age
                        released_at_ms = released_at
                        release_fresh = True
            elif len(values) == 3:
                # Old native builds report ONLY the target queue setting.
                requested, actual, bps = values
                primed = (actual == 0)
                queue_age = 0
                has_queue_age = False
            else:
                return None
            if (not 0 <= requested <= 20000 or not 0 <= actual <= requested or
                    not 0 <= bps <= 500_000_000):
                return None
            return {"requested_ms": requested, "effective_ms": actual,
                    "ts_bytes_per_second": bps,
                    "primed":primed, "queue_age_ms":queue_age,
                    "has_queue_age":has_queue_age,
                    "released_age_ms":released_age_ms,
                    "released_at_ms":released_at_ms,
                    "release_fresh":release_fresh,
                    "has_release_clock":has_release_clock,
                    "capped": actual < requested}
        except (OSError, ValueError, UnicodeError):
            return None

    def close(self):
        for path in (self.path, self.delay):
            path.unlink(missing_ok=True)
