# SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in spoken-dialogue focus for live DVB Whisper; no source separation.

This is a reversible ASR-input-only filter. It does NOT modify audio heard
from Kaffeine, the MPEG-TS stream or any user recordings. It cannot guarantee
speech/music separation: both can occupy the same frequencies. Keep OFF by
default and never require a second model, download, or second tuner.
"""

# Moderate speech-band conditioning for mixed dialogue + soundtrack.
# Using ffmpeg's common built-in filters avoids special Python/GPU packages.
# No tempo-changing or noncausal temporal enhancement is applied; preserve
# the captured clip's approximate timebase for subtitle scheduling.
DIALOGUE_FILTER = (
    "highpass=f=140,"
    "lowpass=f=5200,"
    "equalizer=f=2000:width_type=h:width=1300:g=2.5,"
    "acompressor=threshold=0.10:ratio=2:attack=15:release=125"
)


def ffmpeg_audio_filter(*, speech_priority=False, music_transcription=False):
    """Return optional audio filter argument for private ASR PCM decode."""
    if type(speech_priority) is not bool or type(music_transcription) is not bool:
        raise ValueError("Speech focus and singing preferences must be booleans")
    # Singing mode and dialogue mode are different. A caller attempting both
    # gets the existing singing behavior rather than silent model changes.
    if not speech_priority or music_transcription:
        return ()
    return ("-af", DIALOGUE_FILTER)


def whisper_vad_settings(*, speech_priority=False, music_transcription=False):
    """Silero VAD sensitivity for dialogue mixed with music; bounded choices."""
    if music_transcription:
        return {"vad_filter": False, "vad_parameters": None}
    if speech_priority:
        return {"vad_filter": True,
                "vad_parameters": {
                    "threshold": 0.35,
                    "min_speech_duration_ms": 230,
                    "min_silence_duration_ms": 450,
                    "speech_pad_ms": 200}}
    return {"vad_filter": True,
            "vad_parameters": {
                "threshold": 0.52,
                "min_speech_duration_ms": 350,
                "min_silence_duration_ms": 450,
                "speech_pad_ms": 180}}
