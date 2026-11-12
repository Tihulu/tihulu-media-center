"""Radio music/presenter routing with conservative local-only fallbacks.

Broadcaster DLS announces a song, not the time vocals actually begin/end.
This router never touches PCM, downloads models or claims that a lexical
overlap proves acoustic music. Whisper remains the caption owner throughout.
"""
from __future__ import annotations

from dataclasses import dataclass

# Qwen3-ForcedAligner-0.6B official languages; Turkish is NOT supported.
QWEN_ALIGN_LANGUAGES = frozenset((
    "zh", "en", "yue", "fr", "de", "it", "ja", "ko", "pt", "ru", "es",
))

LANGUAGE_NAMES = {
    "zh":"Chinese", "en":"English", "yue":"Cantonese",
    "fr":"French", "de":"German", "it":"Italian", "ja":"Japanese",
    "ko":"Korean", "pt":"Portuguese", "ru":"Russian", "es":"Spanish",
}


def karaoke_alignment_choice(language: str | None, *,
                             qwen_installed: bool,
                             requested: str = "auto") -> dict:
    """Choose by actual detected song/voice language, never by DLS artist.

    'whisper' is a real fallback using recognized words/observed word times.
    The Qwen aligner is not eligible until its separate model is verified.
    Unsupported/undetected languages remain in Whisper even with Qwen installed.
    """
    if requested not in ("auto", "whisper", "qwen"):
        raise ValueError("Unknown karaoke aligner mode")
    code = (language or "").strip().lower().replace("_", "-").split("-")[0]
    if code == "cn":
        code = "zh"
    if requested == "whisper":
        reason = "manually_selected"
    elif code not in QWEN_ALIGN_LANGUAGES:
        reason = "unsupported_or_undetected_language"
    elif not qwen_installed:
        reason = "qwen_model_not_installed"
    else:
        return {"engine":"qwen", "reason":"compatible_installed_model",
                "language":code, "language_name":LANGUAGE_NAMES[code],
                "whisper_caption_independent":True}
    return {"engine":"whisper", "reason":reason, "language":code or "und",
            "language_name":LANGUAGE_NAMES.get(code,code or "und"),
            "whisper_caption_independent":True}


@dataclass
class MusicSpeechRouter:
    """Bound music-oriented ASR probes; preserve speech after a presenter cut.

    The voice transcriber is always Whisper. No song mode remains latched to
    metadata. Without an audio classifier a catalog match is evidence of
    vocals, *not* of all music. Occasional probes allow mid-song acquisition.
    """
    song_present: bool = False
    matching_active: bool = False
    consecutive_unmatched: int = 0
    windows_since_probe: int = 0
    last_verified_chunk: int = -1

    def change_song(self, song_present: bool) -> None:
        self.song_present = bool(song_present)
        self.matching_active = False
        self.consecutive_unmatched = 0
        self.windows_since_probe = 0
        self.last_verified_chunk = -1

    def use_music_vocals(self, *, enabled: bool, manual_music: bool = False) -> bool:
        if manual_music:
            return True
        if not enabled or not self.song_present:
            return False
        # Once speech takes over, return to ordinary Whisper VAD; occasional
        # vocal probes can still recover songs without a second audio stream.
        if self.matching_active:
            return True
        if self.windows_since_probe >= 3:
            self.windows_since_probe = 0
            return True
        self.windows_since_probe += 1
        return False

    def observe(self, *, matched: bool, recognized_speech: bool,
                sound_events: tuple[str, ...] = (), chunk: int = 0) -> str:
        if not self.song_present:
            self.matching_active = False
            return "speech_whisper"
        if matched:
            self.consecutive_unmatched = 0
            self.last_verified_chunk = chunk
            self.matching_active = True
            return "music_verified_lyrics"
        # AST music is a hint, not proof: a presenter may talk over a song.
        speech_hint = recognized_speech and "music" not in sound_events
        self.consecutive_unmatched += 1 if speech_hint else 0
        if "speech" in sound_events:
            self.consecutive_unmatched = max(self.consecutive_unmatched,2)
        if self.consecutive_unmatched >= 2:
            self.matching_active = False
            return "speech_whisper"
        if self.matching_active:
            return "waiting_vocal_match"
        return "speech_whisper"
