# SPDX-License-Identifier: GPL-2.0-or-later
"""Caption overlay for the *already tuned* DVB service in Kaffeine.

The patched Kaffeine v2.0.19 sends optional best-effort 188-byte-aligned
MPEG-TS datagrams to this user-owned AF_UNIX endpoint. This process never
opens /dev/dvb, never changes the channel, never makes network requests
during captions, and never runs on startup without owner action.
"""
from __future__ import annotations
from pathlib import Path
import os
import queue
from collections import deque
import re
import socket
import sys
import threading
import time

from .tv_tune_state import read_native_tune

# Longer contiguous phrases improve Whisper context; overlap covers words
# spanning boundaries. Queued capture lets CPU inference finish without
# *immediately* discarding the next 6-second segment.
CHUNK_SECONDS = 6
OVERLAP_SECONDS = 1.0
MAX_TS_BYTES = 24 * 1024 * 1024
LANGS = ("de", "en", "tr", "fr")

def validate_socket(path: str) -> Path:
    location = Path(os.environ.get("XDG_RUNTIME_DIR", ""))
    p = Path(path)
    if not location.is_dir() or not p.is_absolute() or p.parent != location:
        raise ValueError("Captions socket must be in the current user's XDG_RUNTIME_DIR")
    if not re.fullmatch(r"tihulu-dvb-[0-9]{1,10}\.sock", p.name):
        raise ValueError("Expected a private Kaffeine DVB socket from this session")
    return p

class CaptionTap:
    def __init__(self, path, current_options, events, packet_sink=None,
                 owner_tune_changed=None):
        self.path = validate_socket(path)
        self.packet_sink = packet_sink
        self.owner_tune_changed = owner_tune_changed
        self.current_options = current_options
        self.events = events
        self.stop = threading.Event()
        from .continuous_captions import BufferedCaptionQueue
        from .transport_health import TransportContinuityMeter
        from .ts_capture_integrity import CaptionPacketGuard
        from .subtitle_tracks import TeletextSubtitleDiscovery
        self.transport_health = TransportContinuityMeter()
        self.packet_guard = CaptionPacketGuard()
        self.subtitle_discovery = TeletextSubtitleDiscovery()
        from .teletext_match import TeletextAudit
        self.teletext_audit = TeletextAudit()
        self.teletext_audit_session = None
        self._teletext_return_pending=False
        self.program_epoch = 0
        self.native_tune_state = None
        self.recv_buffer_bytes = None
        self.work_queue = BufferedCaptionQueue(
            maximum_bytes=(48 if Path("/proc/device-tree/model").is_file()
                           else 96) * 1024 * 1024, max_clips=24)
        self.thread = None
        self.worker = None
        self.previous_original = ""
        self.previous_revision = -1
        from tv_center.sentence_joiner import LiveSentenceJoiner
        # Two 6-second clips are the maximum natural-sentence wait;
        # unpunctuated speech must not remain silently withheld for ~18 s.
        self.sentence_joiner = LiveSentenceJoiner(max_words=90,max_chunks=2)
        self.sentence_session = None
        self.sentence_captured_start = None
        self.program_id = None
        self.sock = None
        self.packet_count = 0
        self.bad_packets = 0
        self._last_ts_at = None
        self._last_clip_at = None
        self._active_clip_at = None
        self._rate_start = None
        self._rate_bytes = 0
        self.bytes_per_second = None
        self._performance_lock = threading.Lock()
        self._performance_samples = deque(maxlen=48)
        self._decoded_count = 0
        self._lost_caption_events = 0
        self._last_degrade_warning_at = 0.0

    def performance_snapshot(self):
        with self._performance_lock:
            samples = [dict(row) for row in self._performance_samples]
            decoded = self._decoded_count
            lost_events = self._lost_caption_events
            last_ts=self._last_ts_at
            last_clip=self._last_clip_at
            active=self._active_clip_at
        return {"samples":samples,"completed_clips":decoded,
                "last_ts_at":last_ts,"last_clip_at":last_clip,
                "active_clip_at":active,
                "lost_ui_caption_events":lost_events,
                "queue":self.work_queue.snapshot(),
                "ts":self.transport_health.snapshot()}

    def start(self):
        if self.path.exists():
            raise RuntimeError("Another captions window uses this Kaffeine socket")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(str(self.path))
        os.chmod(self.path, 0o600)
        # No sysctl changes: Linux clamps SO_RCVBUF to a safe local maximum.
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4*1024*1024)
        except OSError:
            pass
        self.recv_buffer_bytes = self.sock.getsockopt(
            socket.SOL_SOCKET, socket.SO_RCVBUF)
        self.sock.settimeout(0.3)
        self.thread = threading.Thread(target=self._reader, name="tihulu-kaffeine-ts",
                                       daemon=True)
        self.thread.start()
        self.worker = threading.Thread(target=self._worker,
            name="tihulu-kaffeine-caption-worker", daemon=True)
        self.worker.start()

    def _worker(self):
        from .continuous_captions import remove_repeated_prefix
        while not self.stop.is_set():
            clip = self.work_queue.get(timeout=0.3)
            if clip is None:
                continue
            began = time.monotonic()
            with self._performance_lock:
                self._active_clip_at=began
            queue_wait = max(0.0,began-clip.ended)
            options=dict(clip.options)
            queue_state=self.work_queue.snapshot()
            # Speech and translations are more important than optional
            # speaker separation/sound classifiers if those extra GPU/CPU
            # jobs make the six-second capture queue fall behind broadcast.
            # This is opt-out, not a covert change to the selected AI model.
            if options.get("live_priority",True):
                behind=(queue_wait>3.0 or queue_state["queued_clips"]>=1)
                severely_behind=(queue_wait>8.0 or
                                 queue_state["queued_clips"]>=2)
                extras=("separate_overlapping_voices","show_sound_events",
                        "show_voice_types")
                skipped=[name for name in extras if behind and options.get(name)]
                for name in skipped:
                    options[name]=False
                if severely_behind and options.get("speaker_enabled"):
                    options["speaker_enabled"]=False
                    skipped.append("speaker_enabled")
                if skipped and began-self._last_degrade_warning_at>12:
                    self._last_degrade_warning_at=began
                    self._note_warning(
                        "LIVE PRIORITY: omitted slow optional "+
                        ", ".join(skipped)+" for this clip; "
                        "Whisper speech and chosen translations still run. "
                        f"Queue: {queue_state['queued_clips']} clips, "
                        f"wait {queue_wait:.1f}s")
            try:
                from tv_center.translation_service import live_translation_budget
                # One bounded budget for ALL selected output languages,
                # beginning at the FIRST translation request, not before
                # Whisper. An unavailable translator cannot hold the TV
                # subtitle worker for 10–30s PER target.
                with live_translation_budget(
                        7.0 if options.get("live_priority",True) else 30.0):
                    self._decode(clip.data, options, clip.started, clip.ended)
            except Exception as error:
                self._note_warning("Caption worker failed: "+str(error)[:120])
            finally:
                finished=time.monotonic()
                with self._performance_lock:
                    self._active_clip_at=None
                    self._decoded_count += 1
                    self._performance_samples.append({
                        "compute_ms":round(1000*(finished-began)),
                        "queue_wait_ms":round(1000*queue_wait),
                        "total_latency_ms":round(1000*max(0,finished-clip.ended)),
                        "clip_seconds":round(max(0,clip.ended-clip.started),2)})

    def _note_warning(self, message):
        try:
            self.events.put_nowait(("warning", str(message)[:240]))
        except queue.Full:
            pass

    def poll_owner_tune(self) -> bool:
        """Owner tune changes invalidate decoded captions even with no TS."""
        observed = read_native_tune(self.path)
        if observed is None or observed == self.native_tune_state:
            return False
        self.native_tune_state = observed
        self.program_epoch += 1
        self.program_id = None
        self.work_queue.clear()
        self.subtitle_discovery.clear()
        self.packet_guard.reset()
        self.transport_health.reset()
        self.previous_original = ""
        self.previous_revision = -1
        if self.owner_tune_changed is not None:
            try:
                self.owner_tune_changed(observed)
            except (OSError, RuntimeError, ValueError) as exc:
                self._note_warning("Paired phone stream reset failed: "+str(exc)[:120])
        try:
            self.events.put_nowait(("native_tv_tune", {
                "owner_epoch": observed[0],
                "service_id": observed[1],
                "transport_stream_id": observed[2],
                "program_epoch": self.program_epoch}))
        except queue.Full:
            self._note_warning("Native TV tune observed; UI will resynchronize.")
        return True

    def _reader(self):
        chunks = bytearray()
        last = time.monotonic()
        last_revision = -1
        previous_segment = b""
        previous_duration = 0.0
        quality = {"invalid":0,"duplicates":0,"gaps":0,"critical_gaps":0}
        from .continuous_captions import CapturedClip, prepended_overlap, estimate_overlap_seconds
        from .mpegts import current_program_identity
        last_owner_poll = 0.0
        while not self.stop.is_set():
            tick = time.monotonic()
            if tick - last_owner_poll >= 0.15:
                last_owner_poll = tick
                if self.poll_owner_tune():
                    chunks.clear()
                    last = tick
                    last_revision = -1
                    previous_segment = b""
                    previous_duration = 0.0
                    quality = {"invalid":0,"duplicates":0,"gaps":0,
                               "critical_gaps":0}
            try:
                data = self.sock.recv(188 * 32)
            except socket.timeout:
                continue
            except OSError:
                break
            # Each datagram is independently 188-byte aligned; reject partial
            # packets rather than inserting invalid bytes into the MPEG-TS clip.
            if not data or len(data) % 188:
                self.bad_packets += 1
                continue
            # A corrupt packet in a 16-packet Unix datagram must not
            # destroy 15 healthy neighbors. The caption-only guard below
            # validates and filters each packet individually.
            self.packet_count += len(data) // 188
            with self._performance_lock:
                self._last_ts_at=time.monotonic()
            self.transport_health.inspect(data)
            rate_now = time.monotonic()
            if self._rate_start is None:
                self._rate_start = rate_now
            self._rate_bytes += len(data)
            if rate_now - self._rate_start >= 8.0:
                measured_rate = self._rate_bytes / (rate_now - self._rate_start)
                # Smooth the actual forwarded selected-service TS bitrate;
                # overhead and bursts mean this is only a safety estimate.
                if self.bytes_per_second is None:
                    self.bytes_per_second = measured_rate
                else:
                    self.bytes_per_second = 0.7 * self.bytes_per_second + 0.3 * measured_rate
                self._rate_start = rate_now
                self._rate_bytes = 0
            # Validate native owner-selected SID + TSID before accepting
            # any packets. Old multiplex data can remain in a Unix socket
            # after a tune; a matching service ID alone is insufficient.
            identity = current_program_identity(data)
            if self.native_tune_state is not None:
                expected = self.native_tune_state[1:]
                if expected[0] == 0:
                    continue  # Kaffeine stopped TV; never reuse old TS.
                if self.program_id is None and identity != expected:
                    continue  # Await PAT for the NEW owner-selected service.
                if identity is not None and identity != expected:
                    continue  # Stale old service or recycled SID/multiplex.
            # Kaffeine may switch services without reopening this sidecar.
            # Never concatenate clips or deduplicate speech across TV channels.
            observed_program = identity[0] if identity is not None else None
            if observed_program and observed_program != self.program_id:
                if self.program_id is not None:
                    chunks.clear()
                    self.work_queue.clear()
                    last = time.monotonic()
                    previous_segment = b""
                    previous_duration = 0.0
                    self.previous_original = ""
                    self.previous_revision = -1
                    self.transport_health.reset()
                    self.packet_guard.reset()
                    quality = {"invalid":0,"duplicates":0,"gaps":0,
                               "critical_gaps":0}
                    self.subtitle_discovery.clear()
                    self.program_epoch += 1
                    self._note_warning(
                        "TV service changed; cleared previous-channel ASR queue.")
                self.program_id = observed_program
            if self.subtitle_discovery.offer(data, preferred_service_id=self.program_id):
                try:
                    self.events.put_nowait((
                        "teletext_tracks",
                        {"service_id":self.subtitle_discovery.service_id,
                         "program_epoch":self.program_epoch,
                         "tracks":self.subtitle_discovery.snapshot(),
                         "audio_tracks":self.subtitle_discovery.snapshot_audio()}))
                except queue.Full:
                    self._note_warning("Teletext subtitle channel list refresh delayed")
            if self.packet_sink:
                try:
                    self.packet_sink(data)
                except (OSError, RuntimeError, ValueError) as exc:
                    self._note_warning("Mobile packet relay: "+str(exc)[:100])
            options = self.current_options()
            if options.get("revision", 0) != last_revision:
                chunks.clear()
                self.work_queue.clear()
                last_revision = options.get("revision", 0)
                last = time.monotonic()
                previous_segment = b""
                previous_duration = 0.0
                quality = {"invalid":0,"duplicates":0,"gaps":0,
                           "critical_gaps":0}
                self.packet_guard.reset()
            if options["mode"] == "off":
                chunks.clear()
                last = time.monotonic()
                continue
            actual_audio_pid = options.get("audio_pid")
            if actual_audio_pid is None:
                audio_signals = self.subtitle_discovery.snapshot_audio()
                if len(audio_signals)==1:
                    actual_audio_pid = audio_signals[0].get("pid")
            clean, measured = self.packet_guard.filter(
                data, audio_pid=actual_audio_pid,
                teletext_pid=options.get("teletext_pid"))
            self.bad_packets += measured["invalid"]
            for key in quality:
                quality[key] += measured[key]
            if not clean:
                continue
            if len(chunks) + len(clean) > MAX_TS_BYTES:
                chunks.clear()
                self._note_warning(
                    "RF caption capture exceeded 24 MiB; audio may be incomplete")
                last = time.monotonic()
                previous_segment = b""
                previous_duration = 0.0
                quality = {"invalid":0,"duplicates":0,"gaps":0,
                           "critical_gaps":0}
                self.packet_guard.reset()
            chunks.extend(clean)
            now = time.monotonic()
            if now - last >= CHUNK_SECONDS and len(chunks) >= 188 * 300:
                raw = bytes(chunks)
                # The 1 MiB overlap cap may make the actual pre-roll
                # shorter than 1s on high-bitrate TV. Measure it from
                # the retained TS size/rate so Whisper word times are not
                # shifted before the video's real speech.
                overlap = estimate_overlap_seconds(
                    previous_segment, previous_duration, OVERLAP_SECONDS)
                capture = prepended_overlap(
                    raw, previous_segment, previous_duration, OVERLAP_SECONDS)
                started = last - overlap
                previous_segment = raw
                previous_duration = max(0.5, now-last)
                chunks.clear()
                last = now
                segment_quality = dict(quality)
                quality = {"invalid":0,"duplicates":0,"gaps":0,
                           "critical_gaps":0}
                if (segment_quality["critical_gaps"] >= 3 or
                        segment_quality["invalid"] >= 12):
                    # Incomplete audio PES fragments can trigger repeated
                    # ASR hallucinations. Never feed a severely damaged
                    # clip as though it were intact broadcast dialogue.
                    self.previous_original = ""
                    self.previous_revision = -1
                    previous_segment = b""
                    previous_duration = 0.0
                    self._note_warning(
                        "Subtitle TS audio packet integrity compromised; "
                        "discarded damaged sample and will resume on "
                        "the next complete capture.")
                    continue
                captured_options = dict(options)
                # On TV the broadcast audio PID normally advertises its
                # language. A six-second ASR language guess can be wildly
                # wrong under music, narration or damaged reception.
                # Trust an unambiguous real DVB descriptor first, without
                # changing the actual track or opening another tuner.
                if (options.get("source") == "auto" and
                        options.get("mode") in ("auto", "asr") and
                        not options.get("audio_source")):
                    signaled = self.subtitle_discovery.snapshot_audio()
                    selected_pid = options.get("audio_pid")
                    if selected_pid is not None:
                        matches = [item for item in signaled
                                   if item.get("pid") == selected_pid]
                    else:
                        # Exclude audio-description tracks; if all regular
                        # audio streams agree on a language, it is a safe
                        # broadcast hint even with multiple audio PIDs.
                        regular = [item for item in signaled
                                   if not item.get("visual_impaired")]
                        codes = {item.get("source_hint") or item.get("language")
                                 for item in regular}
                        codes.discard(None)
                        codes.discard("und")
                        matches = regular[:1] if len(codes) == 1 else []
                    if len(matches) == 1:
                        from tv_center.language_codes import language_code
                        hinted = matches[0].get("source_hint") or matches[0].get("language")
                        try:
                            code = language_code(hinted)
                        except (ValueError, TypeError):
                            code = None
                        if code and code != "und":
                            captured_options["audio_source"] = code
                captured_options["ts_integrity"] = segment_quality
                captured_options["service_id"] = self.program_id
                captured_options["program_epoch"] = self.program_epoch
                captured_options["native_tune_state"] = self.native_tune_state
                with self._performance_lock:
                    self._last_clip_at=now
                queued = self.work_queue.offer(
                    CapturedClip(capture, captured_options, started, now))
                if not queued:
                    health = self.work_queue.snapshot()
                    self._note_warning(
                        "Whisper slower than live TV: queue full; "
                        f"{health['missed_seconds']:.1f} s of captions could not "
                        "be retained. Select CUDA GPU/smaller model or fewer translations.")

    def _decode(self, capture, options, captured_start, captured_end):
        decode_clock=time.perf_counter()
        try:
            from tv_center.ai_settings import AISettings
            from tv_center.captions import decode_segment
            ai = AISettings()
            ai.configure_environment()
            selected = options["mode"]
            audit_session=(options.get("program_epoch"),
                           options.get("revision",0))
            if audit_session!=self.teletext_audit_session:
                self.teletext_audit.reset()
                self.teletext_audit_session=audit_session
                self._teletext_return_pending=False
            if selected=="auto":
                self.teletext_audit.mark_clip()
            probe_due=(selected=="auto" and
                       self.teletext_audit.needs_probe())
            recovery_probe=bool(probe_due and self.teletext_audit.prefer_asr)
            if selected=="auto" and self.teletext_audit.prefer_asr:
                selected="asr"
            if selected in ("asr", "auto") and not ai.values["asr_enabled"]:
                if selected == "asr":
                    raise RuntimeError("Whisper disabled. Enable in AI Model Market.")
                selected = "teletext"
            source = options["source"]
            targets = tuple(options.get("targets", ()))
            # Selecting OUT targets + translation display is explicit LOCAL
            # consent. Do not require a second hidden Market toggle; do not
            # silently opt in to DeepL/cloud if global translation is OFF.
            translation_allowed=bool(ai.values["translation_enabled"] or (
                options.get("translation_requested",False) and
                ai.values.get("translation_model") in
                ("argos","nllb","madlad","de_tr_direct","auto_offline")))
            enabled = targets if translation_allowed else ()
            primary = targets[0] if targets else source
            previous = (self.previous_original
                        if self.previous_revision == options.get("revision", 0)
                        else "")
            result = decode_segment(capture, mode=selected, page=options["page"],
                source=source, target=primary,
                targets=(() if selected=="asr" and not options.get(
                    "music_transcription",False) else enabled),
                model=ai.values["model_path"],
                service_id=options.get("service_id"),
                teletext_pid=(options.get("teletext_pid")
                              if selected in ("auto", "teletext", "page")
                              or recovery_probe else None),
                teletext_language=options.get("teletext_language"),
                audio_pid=(options.get("audio_pid")
                           if selected in ("auto", "asr") else None),
                audio_source=(options.get("audio_source")
                              if selected in ("auto", "asr") else None),
                speech_auto=bool(options.get("spoken_auto")),
                speaker_enabled=bool(options.get("speaker_enabled",False))
                                and selected in ("auto","asr"),
                speaker_provider=options.get("speaker_provider","resemblyzer"),
                music_transcription=bool(options.get("music_transcription",False)),
                speech_priority=bool(options.get("speech_priority",False)),
                overlap_separation=(
                    selected=="asr" and bool(options.get(
                        "separate_overlapping_voices",False))),
                show_sound_events=bool(options.get("show_sound_events",False)),
                show_voice_types=(bool(options.get("show_voice_types",False))
                                  and selected in ("auto","asr")),
                previous_text=previous,
                defer_asr_translation=not bool(
                    options.get("music_transcription",False)),
                auto_teletext_probe=(
                    selected=="auto" and ai.values["asr_enabled"] and
                    probe_due),
                auto_teletext_recovery=bool(
                    recovery_probe and ai.values["asr_enabled"]))
            probe=result.pop("teletext_probe",None)
            shadow=result.pop("teletext_shadow",None)
            if (probe and selected=="auto" and
                    str(result.get("source","")).startswith("broadcaster_teletext")):
                previous_teletext_state=self.teletext_audit.status
                verdict=self.teletext_audit.observe(
                    result.get("original"),probe.get("text"),
                    options.get("teletext_language") or result.get("source_language"),
                    probe.get("source_language"))
                result["teletext_audit"]=(
                    f"{self.teletext_audit.attempts} speech checks · "
                    f"{verdict} · {self.teletext_audit.last_reason}")
                if verdict=="delayed" and previous_teletext_state!=(
                        "TELETEXT · DELAY CHECK"):
                    # Re-sample *actual available* transport/audio clocks.
                    # We do not have trusted decoded Teletext PTS or sound
                    # card presentation PTS, so NEVER manufacture a 6s jump.
                    result["teletext_sync_recheck"]=True
                if verdict=="switched":
                    result["teletext_source_transition"]="whisper"
                    # The real concurrent ASR audio is already available.
                    # Discard OLD Teletext translations; translate the heard
                    # speech after natural sentence assembly below.
                    result["original"]=probe["text"]
                    result["raw_asr_original"]=probe["text"]
                    result["source_language"]=probe["source_language"]
                    result["source"]="local_asr"
                    result["word_timing_source"]=probe.get("word_timing_source")
                    result["words"]=probe.get("words",[])
                    result["translations"]={}
                    result["translation_errors"]={}
                    result["translation_warnings"]={}
                    result["translation_engines"]={}
            elif selected=="asr" and options["mode"]=="auto" and shadow:
                verdict=self.teletext_audit.observe(
                    shadow.get("text"),result.get("original"),
                    shadow.get("source_language"),
                    result.get("source_language"))
                result["teletext_audit"]=(
                    "Whisper safe fallback · sampled actual broadcaster text: "+
                    verdict+" · "+self.teletext_audit.last_reason)
                if verdict=="recovered":
                    result["teletext_return_pending"]=True
                    self._teletext_return_pending=True
                    self.previous_original=""
                    self.previous_revision=-1
                # If recovered, keep THIS segment's genuine ASR; begin
                # broadcasting Teletext from the NEXT capture only.
            elif (selected=="auto" and options["mode"]=="auto"
                  and result.get("source")=="local_asr"):
                self.teletext_audit.missing()
                result["teletext_audit"]=(
                    "No usable broadcaster Teletext, switched to real Whisper")
            if (options["mode"]=="auto" and
                    str(result.get("source","")).startswith("broadcaster_teletext")
                    and self._teletext_return_pending):
                # Accept the first NEW verified Teletext from this tune, then
                # replace only the stale Whisper cues; do not clear early.
                result["teletext_source_transition"]="teletext"
                self._teletext_return_pending=False
            if options["mode"]=="auto":
                result["teletext_status"]=(
                    "WHISPER · AUTO FALLBACK"
                    if result.get("source")=="local_asr" else
                    self.teletext_audit.status)
                result["teletext_detail"]=self.teletext_audit.last_reason
                result["teletext_probe_attempts"]=self.teletext_audit.attempts
            else:
                result["teletext_status"]=(
                    "WHISPER · MANUAL" if selected=="asr" else
                    "TELETEXT · MANUAL")
            if options.get("program_epoch") != self.program_epoch:
                return  # old channel's caption must never appear on new TV
            if result.get("source") == "local_asr" and result.get("original"):
                # The decoder must remove duplicated overlap before translation.
                self.previous_original = (result.get("raw_asr_original") or
                                          result["original"])
                self.previous_revision = options.get("revision", 0)
            if (selected=="asr" and not result.get("original") and
                    not result.get("error") and
                    not result.get("recognition_rejected") and
                    self.sentence_joiner.pending and
                    self.sentence_session==(
                        options.get("program_epoch"),options.get("revision"))):
                # A complete silent capture can close the previous original
                # phrase. It is not invented speech; only stored words appear.
                result["source"]="local_asr"
                result["source_language"]=(
                    self.sentence_joiner.language or source)
            if str(result.get("source","")).startswith("broadcaster_teletext"):
                self.sentence_joiner.reset()
                self.sentence_session=None
                self.sentence_captured_start=None
            # Valid Faster-Whisper word positions must survive the joiner.
            # With native playback buffering these can follow real dialogue.
            from .word_cues import word_groups
            actual_overlaps=bool(
                selected=="asr" and options.get("separate_overlapping_voices")
                and isinstance(result.get("overlap_lines"),list)
                and len(result["overlap_lines"])==2)
            source_word_timed = (
                not actual_overlaps
                and result.get("source") == "local_asr"
                and not options.get("music_transcription",False)
                and bool(result.get("word_timing_source"))
                and not (options.get("ts_integrity") or {}).get("critical_gaps")
                and bool(word_groups(result)))
            if (result.get("source") == "local_asr" and not options.get(
                    "music_transcription",False) and not source_word_timed
                    and not actual_overlaps):
                # Without valid word positions, keep the natural sentence
                # joiner; those sentences are not speaker-word aligned.
                # Only completed spoken phrases are sent to the TV subtitle
                # queue. Word timestamps from separate six-second clips
                # cannot be claimed as an exact word clock for merged text.
                session=(options.get("program_epoch"),options.get("revision"))
                if session!=self.sentence_session:
                    self.sentence_joiner.reset()
                    self.sentence_session=session
                    self.sentence_captured_start=None
                if self.sentence_captured_start is None:
                    self.sentence_captured_start=captured_start
                observed=result.get("original","")
                previous_language=self.sentence_joiner.language
                joined=self.sentence_joiner.push(
                    observed,
                    language=result.get("source_language"),
                    silent=not bool(observed),
                    prefer_readable=bool(options.get("readable_pacing",True)))
                if not joined["text"]:
                    # Tell the UI why nothing appeared; this is NOT evidence
                    # of silence or a hardware failure.
                    try:
                        self.events.put_nowait(("sentence_pending",{
                            "chunks":joined.get("chunks",0),
                            "maximum_chunks":self.sentence_joiner.max_chunks,
                            "program_epoch":options.get("program_epoch"),
                            "revision":options.get("revision"),
                            "captured_end":captured_end}))
                    except queue.Full:
                        pass
                    return  # Keep words for the next clip.
                if joined.get("language_switched") and previous_language:
                    # The emitted phrase belongs to the OLD language.
                    # New-language words remain held in the joiner; never
                    # translate a French clause with the old German code.
                    result["source_language"]=previous_language
                    result["language_switch"]="pending new-language sentence"
                # A loop may span several otherwise valid Whisper clips.
                # Filter the FINAL assembled sentence too, after overlap
                # removal, before the translation engine receives it.
                from .continuous_captions import collapse_asr_repetition_loops
                result["original"] = collapse_asr_repetition_loops(joined["text"])
                from tv_center.asr_quality import strip_test_page_artifact
                result["original"], removed_page_marker=strip_test_page_artifact(
                    result["original"])
                if removed_page_marker:
                    result["asr_test_page_artifact_removed"]=True
                elif result["original"] != joined["text"]:
                    result["asr_repetitions_removed"] = True
                result["words"]=[]
                result["word_timing_source"]=None
                result["sentence_complete"]=bool(joined.get("complete"))
                result["sentence_continuation"]=bool(joined.get("continued"))
                result["timing_note"]="Sentence carried across live TV chunks; "
                result["timing_note"]+="word-by-word alignment not asserted"
                captured_start=self.sentence_captured_start
                self.sentence_captured_start=(
                    captured_end if joined.get("pending") else None)
            elif actual_overlaps:
                # Each line has its own verified source waveform and Whisper
                # word positions. A single sentence joiner cannot merge two
                # simultaneous speakers without losing one of them.
                self.sentence_joiner.reset()
                self.sentence_session=None
                self.sentence_captured_start=None
                result["words"]=[]
                result["word_timing_source"]=None
                result["caption_alignment"]=(
                    "Separate audio sources · provisional voice A/B per clip")
            elif source_word_timed:
                # Mixing an old untimed sentence with source-timed speech
                # would reintroduce late or mixed-speaker captions.
                self.sentence_joiner.reset()
                self.sentence_session=None
                self.sentence_captured_start=None
                result["caption_alignment"]="Source audio word timestamps"
                result["timing_note"]=(
                    "Live source-word timing; labels estimated from voice "
                    "windows; libVLC video PTS not yet calibrated")
            if (result.get("source") == "local_asr" and
                    not options.get("music_transcription",False) and
                    result.get("original") and not actual_overlaps):
                # Translate ONCE after untimed sentence joining OR while
                # preserving the real Whisper word timestamps for this clip.
                # Never join partial independent translations: German/English
                # word ordering can be destroyed by chunkwise translation.
                from tv_center.captions import translate as translate_sentence
                result["translations"]={}
                result["translation_errors"]={}
                result["translation_warnings"]={}
                result["translation_engines"]={}
                used=result.get("source_language")
                translate_clock=time.perf_counter()
                translation_languages_ms={}
                if enabled and used in (None,"und","auto"):
                    result["translation_errors"]={
                        target:"Source language not confirmed for full sentence"
                        for target in enabled}
                elif enabled:
                    for target in enabled:
                        one_clock=time.perf_counter()
                        if target==used:
                            result["translations"][target]=result["original"]
                            translation_languages_ms[target]=0
                            continue
                        text,issue=translate_sentence(
                            result["original"],used,target)
                        translation_languages_ms[target]=round(
                            (time.perf_counter()-one_clock)*1000)
                        if text:
                            result["translations"][target]=text
                        if issue:
                            if text:
                                result["translation_warnings"][target]=issue[:180]
                            else:
                                result["translation_errors"][target]=issue[:180]
                result["translated"]=result["translations"].get(primary)
                spent=round((time.perf_counter()-translate_clock)*1000)
                result.setdefault("processing_ms",{})["translation"]=spent
                result["translation_languages_ms"]=translation_languages_ms
            if actual_overlaps:
                # Translate each separated voice INDEPENDENTLY; do not
                # translate the original mixed waveform as a single sentence.
                # This is permitted only when the owner enabled dual voices
                # and SepFormer+both Whisper passes produced distinct text.
                from tv_center.captions import translate as translate_sentence
                for channel in result["overlap_lines"]:
                    channel["translations"]={}
                    channel["translation_errors"]={}
                    used=channel.get("source_language")
                    for target in enabled:
                        if used not in (None,"und","auto"):
                            if target==used:
                                channel["translations"][target]=channel["original"]
                                continue
                            text,issue=translate_sentence(
                                channel["original"],used,target)
                            if text:
                                channel["translations"][target]=text
                            if issue and not text:
                                channel["translation_errors"][target]=issue[:180]
                        else:
                            channel["translation_errors"][target]=(
                                "Separated source language unconfirmed")
                result["overlap_note"]=(
                    "Two independently recognized tracks; order and speaker "
                    "IDs are provisional, not fixed identity")
            if targets and not translation_allowed:
                result["translation_errors"] = {
                    lang: "Translation disabled in Model Market." for lang in targets}
            if targets and not result.get("translations"):
                result["translation_error"] = (
                    next(iter(result.get("translation_errors", {}).values()), None)
                    or result.get("error") or
                    "Language packs unavailable. Install via Model Market.")
            quality = options.get("ts_integrity") or {}
            result["ts_integrity"] = quality
            if quality.get("critical_gaps", 0) > 0:
                # Audio gaps break the assumption that raw ASR word offsets
                # map continuously to the captured transport stream.
                # Show coherent fallback phrases, never fake word-sync.
                result["words"] = []
                result["word_timing_source"] = None
                result["timing_note"] = "Audio PID discontinuity: word timing disabled"
            result["captured_start"] = captured_start
            result["captured_end"] = captured_end
            result["decoded_at"] = time.monotonic()
            result.setdefault("processing_ms",{})["total"]=round(
                (time.perf_counter()-decode_clock)*1000)
            result["revision"] = options.get("revision", 0)
            result["program_epoch"] = options.get("program_epoch")
            result["native_tune_state"] = options.get("native_tune_state")
            # Sound detector tags are added only AFTER Whisper recognition,
            # sentence assembly and translation. They never erase/replace
            # genuine lyrics or speech, and do not enter translator inputs.
            if options.get("show_sound_events") and result.get("sound_events"):
                from tv_center.sound_event_captions import decorate_result
                result=decorate_result(result,enabled=True)
            # Recheck before publishing. Decoder/translator can take
            # seconds; no result from a previous tune may be displayed.
            if options.get("program_epoch") != self.program_epoch:
                return
            try:
                # Captions, unlike status notices, are irreplaceable ASR
                # results. Wait briefly for the Qt loop to drain before
                # declaring an actual lost subtitle. Still bounded: if
                # processing cannot match broadcast speed the user gets an
                # explicit loss counter rather than false "listening".
                self.events.put(("caption", result), timeout=1.25)
            except queue.Full:
                with self._performance_lock:
                    self._lost_caption_events += 1
                self._note_warning(
                    "LIVE CAPTION LOST: Qt event queue saturated for 1.25s; "
                    "reduce simultaneous voice/translation model workload")
        except (OSError, RuntimeError, ImportError, ValueError) as error:
            self._note_warning(str(error)[:180])

    def close(self):
        self.stop.set()
        if self.sock:
            self.sock.close()
        self.work_queue.close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2)
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=2)
        # Only unlink our own previously bound socket.
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] != "--socket":
        raise SystemExit("Usage: tihulu-tv-center kaffeine-captions --socket $XDG_RUNTIME_DIR/tihulu-dvb-PID.sock")
    endpoint = validate_socket(argv[1])
    from .caption_control import CaptionServiceControl
    from tv_center.language_codes import language_code
    from textcenter.compute import LANGUAGES as WHISPER_LANGUAGES
    pid = int(endpoint.stem.rsplit("-", 1)[-1])
    if CaptionServiceControl.request_show(endpoint.parent, pid):
        # Reopening the TIHULU AI menu focuses the existing controller.
        # Do not create a competing DVB/Whisper reader.
        return 0
    from .caption_timing import (CaptionConfig, CueQueue, KaffeineOSD,
                                 AutoSyncEstimator, AutoSyncController,
                                 effective_cue_config, confirmed_cue_config,
                                 buffer_fill_progress, NativeReleaseClock)
    from .word_cues import enqueue_word_cues
    from .track_preferences import recommended_track, _signaled_language
    from PyQt5.QtCore import Qt, QTimer, QSettings, QProcess
    from PyQt5.QtGui import QColor
    from PyQt5.QtWidgets import (QApplication, QWidget, QDialog, QDialogButtonBox,
        QMessageBox, QPlainTextEdit, QVBoxLayout, QHBoxLayout,
        QLabel, QComboBox, QPushButton, QToolButton, QMenu, QWidgetAction,
        QSpinBox, QDoubleSpinBox,
        QCheckBox, QGroupBox, QFormLayout, QLineEdit, QColorDialog,
        QScrollArea, QFrame, QGridLayout, QFileDialog, QTabWidget,
        QProgressBar)
    app = QApplication.instance() or QApplication(["TIHULU Kaffeine Live Captions"])
    # Hiding the only QWidget must NOT quit the Qt event loop: audio capture,
    # auto-sync and video-overlay publishing continue independently of UI.
    app.setQuitOnLastWindowClosed(False)
    window_state = QSettings("TIHULU", "CaptionWindowGeometry")

    class CaptionSettingsWindow(QWidget):
        terminating = False
        def closeEvent(self, event):
            window_state.setValue("geometry", self.saveGeometry())
            if self.terminating:
                event.accept()
                return
            self.hide()
            event.ignore()

    window = CaptionSettingsWindow()
    window.setWindowTitle(
        "TIHULU · Live captions · GPU Whisper + translation failover")
    window.setMinimumWidth(620)
    window.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
    # This is a separate controller, never a modal Kaffeine channel-switch
    # dialog. Alt-Tab and the pinned Back-to-TV control preserve capture.
    window.setWindowModality(Qt.NonModal)
    window.setStyleSheet(
        "QWidget{background:#0c1722;color:#e8f3fa;font-size:13px}"
        "QGroupBox{border:1px solid #304b63;border-radius:8px;margin-top:14px;padding:10px}"
        "QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 5px}"
        "QComboBox,QSpinBox,QDoubleSpinBox,QPushButton{background:#173449;"
        "border:1px solid #356784;border-radius:6px;padding:7px}"
        "QPushButton#apply{background:#207796;font-weight:700}"
        "QLabel#subtitle{font-size:20px;max-height:86px}"
        "QProgressBar{border:1px solid #356784;border-radius:6px;"
        "background:#122533;color:#e8f3fa;text-align:center;"
        "min-height:22px;font-weight:600}"
        "QProgressBar::chunk{background:#38b8d2;border-radius:5px}"
    )
    desktop = app.primaryScreen().availableGeometry()
    window.resize(min(780, max(620, desktop.width()-90)),
                  min(690, max(480, desktop.height()-100)))
    saved_geometry = window_state.value("geometry")
    if saved_geometry:
        try:
            window.restoreGeometry(saved_geometry)
        except (TypeError, ValueError):
            saved_geometry = None
    if not saved_geometry or not window.frameGeometry().intersects(desktop):
        window.move(max(desktop.left()+10, desktop.right()-window.width()-18),
                    desktop.top()+28)
    app.aboutToQuit.connect(
        lambda: window_state.setValue("geometry", window.saveGeometry()))
    root = QVBoxLayout(window)
    root.setContentsMargins(12,10,12,10)
    root.setSpacing(8)
    control_body = QWidget()
    control_layout = QVBoxLayout(control_body)
    control_layout.setContentsMargins(6,8,6,8)
    control_layout.setSpacing(12)

    settings = QGroupBox("Live caption source & language")
    settings_layout = QFormLayout(settings)
    settings_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
    settings_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    row = QHBoxLayout()
    mode = QComboBox()
    mode.addItem("Teletext subtitles → Whisper fallback", "auto")
    mode.addItem("Teletext Hard · broadcaster subtitles (no Whisper test)", "teletext")
    mode.addItem("Whisper live transcription", "asr")
    mode.addItem("Manual Teletext page", "page")
    mode.addItem("Off", "off")
    source = QComboBox()
    source.setEditable(True)
    source.addItem("Auto detect", "auto")
    source.addItems(LANGS)
    source.setCurrentIndex(0)
    source.setToolTip(
        "Automatically identify the broadcast audio language or use a genuine " 
        "Whisper detection. This is the SOURCE language; English is the " 
        "initial OUTPUT language. Type an ISO code such as pl, es, ja, ar. " 
        "Broadcast Teletext "
        "can be displayed in its original language; 100 source-language "
        "codes are supported by multilingual Whisper, provided the chosen "
        "speech model and runtime are installed.")
    page = QSpinBox(); page.setRange(100, 899); page.setValue(150)
    for name, widget in (("Source",mode),("Spoken",source),("Teletext",page)):
        row.addWidget(QLabel(name)); row.addWidget(widget, 1)
    settings_layout.addRow(row)
    output_row = QHBoxLayout()
    display_mode = QComboBox()
    display_mode.addItem("Original only", "original")
    display_mode.addItem("Original + translations", "both")
    display_mode.addItem("Translations only", "translated")
    display_mode.setCurrentIndex(1)
    output_row.addWidget(QLabel("Display"))
    output_row.addWidget(display_mode, 2)
    output_row.addWidget(QLabel("Output languages"))
    # Multi-check dropdown, populated from installed offline translator packs.
    # Discovery runs in a child process to avoid blocking live DVB playback.
    language_boxes = {}
    output_button = QToolButton()
    output_button.setText("Checking installed languages…")
    output_button.setPopupMode(QToolButton.InstantPopup)
    output_button.setMinimumWidth(170)
    output_menu = QMenu(output_button)
    output_button.setMenu(output_menu)
    output_row.addWidget(output_button,1)
    settings_layout.addRow(output_row)
    output_catalog_status = QLabel("Checking locally installed output languages…")
    output_catalog_status.setWordWrap(True)
    settings_layout.addRow(output_catalog_status)
    requested_languages = {"en"}
    # Show the familiar language checkboxes immediately. Whether a
    # translator for a particular source→target pair is *installed* is a
    # separate asynchronous fact and must never gate the selection menu.
    baseline = ("en", "tr", "de", "fr")
    catalog_in_flight = False
    catalog_timed_out = False
    language_stage = "idle"
    known_models = {}

    def summarize_languages(*_):
        checked = [code.upper() for code,box in language_boxes.items()
                   if box.isChecked()]
        output_button.setText(", ".join(checked) or "Choose output languages")
        output_button.setToolTip(
            "Multiple selections; only locally available models can translate "
            "a particular broadcast source language. Choose from the dropdown.")

    def on_language_toggled(code, checked):
        if checked:
            requested_languages.add(code)
        else:
            requested_languages.discard(code)
        summarize_languages()
        set_pending()

    def fill_languages(result, *, pending=False):
        """Rebuild the menu without clearing the user's existing choices."""
        items = result.get("languages",()) if isinstance(result,dict) else ()
        available=known_models
        for item in items:
            if not isinstance(item,dict):
                continue
            try:
                code=language_code(item.get("code",""),nllb=True)
            except (ValueError,TypeError):
                continue
            if code in available:
                old=available[code]
                engines=sorted(set(old.get("engines",())) |
                               set(item.get("engines",())))
                available[code]={**old,**item,"engines":engines}
            else:
                available[code]=item
        # Keep Spoken choices in sync with the actual output-language
        # catalog while respecting Whisper's *source* language support.
        # Discovery never changes the viewer's current Spoken selection.
        previous_source=source.currentText()
        previous_index=source.currentIndex()
        source.blockSignals(True)
        try:
            for code in dict.fromkeys([*baseline,*sorted(available),
                                           *sorted(requested_languages)]):
                if code in WHISPER_LANGUAGES and source.findText(code)<0:
                    source.addItem(code,code)
            if previous_index==0:
                source.setCurrentIndex(0)
            elif source.findText(previous_source)>=0:
                source.setCurrentIndex(source.findText(previous_source))
            else:
                source.setEditText(previous_source)
        finally:
            source.blockSignals(False)
        output_menu.clear()
        language_boxes.clear()
        content=QWidget(output_menu)
        content_layout=QVBoxLayout(content)
        content_layout.setContentsMargins(10,8,10,8)
        content_layout.setSpacing(5)
        # Explicitly distinguish selectable codes from real installed packs.
        for code in list(dict.fromkeys(
                [*baseline,*sorted(available),*sorted(requested_languages)])):
            model=available.get(code)
            engines=model.get("engines",[]) if model else []
            label=(str(model.get("label","")) if model else
                   {"en":"English","tr":"Turkish","de":"German",
                    "fr":"French"}.get(code,code.upper()))
            remote=[str(x) for x in engines if
                    str(x).startswith("DeepL API")]
            offline=[str(x) for x in engines if
                     not str(x).startswith("DeepL API")]
            status_text=(
                (" · local model: "+", ".join(offline) if offline else
                 " · no offline translation pack confirmed")+
                (" · online option: "+", ".join(remote) if remote else ""))
            cb=QCheckBox(code.upper()+" · "+label,content)
            cb.setChecked(code in requested_languages)
            cb.setToolTip(
                code.upper()+status_text+
                ". A working translation direction is checked when decoding.")
            language_boxes[code]=cb
            content_layout.addWidget(cb)
            cb.toggled.connect(
                lambda checked,lang=code:on_language_toggled(lang,checked))
        refresh_languages=QPushButton("Refresh installed languages",content)
        content_layout.addWidget(refresh_languages)
        refresh_languages.clicked.connect(start_language_catalog)
        scroll=QScrollArea(output_menu)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMaximumHeight(320)
        scroll.setMinimumWidth(260)
        scroll.setWidget(content)
        action=QWidgetAction(output_menu)
        action.setDefaultWidget(scroll)
        output_menu.addAction(action)
        summarize_languages()
        if pending:
            output_catalog_status.setText(
                "EN is the initial output, Spoken is Auto detect. All four "
                "common languages can be selected immediately. Checking local "
                "NLLB/MADLAD first; slow Argos inventory follows…")
        elif isinstance(result,dict) and result.get("errors"):
            output_catalog_status.setText(
                "Language choices available; installed model check incomplete: "+
                "; ".join(str(x) for x in result["errors"])[:180]+
                ". Open Model Market to install/verify packs.")
        else:
            output_catalog_status.setText(
                str(len(available))+" destination candidates from discovered "
                "local packs and any explicitly configured ONLINE API. "
                "Installed weights do not prove usable translation. "
                "Select languages, then Apply.")

    language_process=QProcess(window)
    language_timeout=QTimer(window)
    language_timeout.setSingleShot(True)

    def language_catalog_finished(*_):
        nonlocal catalog_in_flight
        language_timeout.stop()
        catalog_in_flight=False
        if catalog_timed_out:
            output_catalog_status.setText(
                "Installed-model inventory timed out (stage: "+
                language_stage+"). Language boxes are ready; manually "
                "refresh to retry. No model, source or channel changed.")
            return
        try:
            payload=bytes(language_process.readAllStandardOutput()).decode(
                "utf-8","replace")
            if language_process.exitCode()!=0 or len(payload)>75000:
                stderr=bytes(language_process.readAllStandardError()).decode(
                    "utf-8","replace")
                raise ValueError("Local model scan failed: "+stderr[-130:])
            result=json.loads(payload)
            if not isinstance(result,dict):
                raise ValueError("Invalid local model metadata")
        except (ValueError,TypeError) as exc:
            result={"languages":[],"errors":[str(exc)[:160]]}
        # Keep all previously discovered engines, and do not reset a
        # checkbox when the slower Argos result finally arrives.
        fill_languages(result)
        if language_stage=="fast":
            output_catalog_status.setText(
                "NLLB/MADLAD and configured DeepL candidates listed. "
                "Checking installed Argos packs without blocking selection…")
            QTimer.singleShot(30,start_argos_catalog)

    def language_catalog_error(error):
        nonlocal catalog_in_flight
        if language_process.state()==QProcess.NotRunning:
            catalog_in_flight=False
            language_timeout.stop()
            output_catalog_status.setText(
                "Installed model scan could not start (Qt process error "+
                str(int(error))+"). Language checkboxes remain available.")

    def language_catalog_timeout():
        nonlocal catalog_timed_out
        if language_process.state()!=QProcess.NotRunning:
            catalog_timed_out=True
            output_catalog_status.setText(
                "Installed model scan exceeded its safety deadline. "
                "EN/TR/DE/FR and already detected local models stay available.")
            language_process.kill()

    def start_argos_catalog():
        nonlocal catalog_in_flight,language_stage,catalog_timed_out
        if catalog_in_flight or language_process.state()!=QProcess.NotRunning:
            return
        catalog_in_flight=True
        catalog_timed_out=False
        language_stage="argos"
        output_catalog_status.setText(
            "Local large-model destinations available. Optional Argos "
            "language-pack inventory (max 11 seconds)…")
        language_process.start(sys.executable,
            ["-m","tv_center.installed_languages"])
        language_timeout.start(11000)

    def start_language_catalog():
        nonlocal catalog_in_flight,catalog_timed_out,language_stage
        if catalog_in_flight or language_process.state()!=QProcess.NotRunning:
            return
        known_models.clear()
        catalog_in_flight=True
        catalog_timed_out=False
        language_stage="fast"
        output_catalog_status.setText(
            "Languages ready. Reading local NLLB/MADLAD checkpoint metadata "
            "and any configured DeepL key (no API request)…")
        language_process.start(sys.executable,
            ["-m","tv_center.installed_languages","--fast"])
        language_timeout.start(3500)

    language_process.finished.connect(language_catalog_finished)
    language_process.errorOccurred.connect(language_catalog_error)
    language_timeout.timeout.connect(language_catalog_timeout)
    fill_languages({"languages":[]},pending=True)
    QTimer.singleShot(150,start_language_catalog)
    extra_targets = QLineEdit()
    extra_targets.setPlaceholderText(
        "Optional extra target codes: es, pl, ar, ja or zho_Hant")
    extra_targets.setToolTip(
         "Up to six distinct targets including checked presets. "
        "Actual translation requires a matching installed Argos pack or "
        "NLLB model. Missing packs never hide the source captions.")
    settings_layout.addRow("Additional translation languages", extra_targets)
    translation_health = QLabel(
        "Translation model: selected in AI Model Market. "
        "NLLB errors trigger installed Argos backup; subtitles stay visible.")
    translation_health.setWordWrap(True)
    settings_layout.addRow("Translation status", translation_health)
    def update_language_choices(*_):
        summarize_languages()
    source.currentTextChanged.connect(update_language_choices)
    update_language_choices()
    tracks_row = QHBoxLayout()
    tracks_row.addWidget(QLabel("Broadcast subtitle channel"))
    subtitle_track = QComboBox()
    subtitle_track.addItem("Automatic broadcaster subtitles (no selected page)", None)
    subtitle_track.setToolTip(
        "Detected from the tuned TV service's DVB Teletext descriptor. "
        "Only actual signalled subtitle pages are offered. Select a "
        "language/page, then Apply. Whisper mode transcribes audio instead.")
    tracks_row.addWidget(subtitle_track, 1)
    track_status = QLabel("Scanning this channel's real DVB subtitle descriptors…")
    track_status.setWordWrap(True)
    settings_layout.addRow(tracks_row)
    settings_layout.addRow(track_status)
    teletext_speech_status = QLabel(
        "TELETEXT · CHECKING · waiting for live same-language audio evidence")
    teletext_speech_status.setWordWrap(True)
    teletext_speech_status.setToolTip(
        "Auto source: periodically verifies broadcaster subtitle words "
        "against real Whisper speech. Text-only/PTSs alone do not prove "
        "content sync; separate languages are not treated as mismatches. "
        "Three conflicts trigger Whisper and two later matches allow "
        "return to Teletext.")
    audio_row = QHBoxLayout()
    audio_row.addWidget(QLabel("Whisper source audio channel"))
    audio_track = QComboBox()
    audio_track.addItem("Automatic · prefer spoken language / regular audio", None)
    audio_track.setToolTip(
        "Real audio elementary streams signalled in the tuned DVB service. "
        "Choose a PID for Whisper transcription; TV audio playback remains "
        "under Kaffeine's own control. No second tuner is opened.")
    audio_row.addWidget(audio_track, 1)
    settings_layout.addRow(audio_row)
    audio_track_status = QLabel("Scanning broadcaster audio track descriptors…")
    audio_track_status.setWordWrap(True)
    settings_layout.addRow(audio_track_status)
    control_layout.addWidget(settings)

    timing = QGroupBox("Playback timing, subtitle reading & voice extras")
    timing_layout = QFormLayout(timing)
    quick = QGroupBox("Quick subtitle appearance · always visible")
    quick_layout = QFormLayout(quick)
    quick_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
    timing_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
    timing_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
    timing_layout.addRow(QLabel("<b>1 · Timing — affects when captions appear</b>"))
    offsets = QHBoxLayout()
    caption_offset = QDoubleSpinBox()
    caption_offset.setRange(-10.0, 10.0)
    caption_offset.setSingleStep(0.1)
    caption_offset.setSuffix(" s")
    caption_offset.setToolTip("Positive = later subtitle; negative = earlier. Cannot show before decoding completes.")
    playback_delay = QDoubleSpinBox()
    playback_delay.setRange(0.0, 20.0)
    playback_delay.setSingleStep(0.5)
    playback_delay.setSuffix(" s")
    playback_delay.setToolTip("Buffers audio and video together (0–20 s); this is NOT calibrated lip-sync. Long buffers consume RAM; "
                               "use CUDA models to reduce lag rather than excessive buffering.")
    offsets.addWidget(QLabel("Caption offset"))
    offsets.addWidget(caption_offset)
    offsets.addWidget(QLabel("TV playback buffer"))
    offsets.addWidget(playback_delay)
    timing_layout.addRow(offsets)
    auto_row = QHBoxLayout()
    automatic = QCheckBox("Auto-size TV buffer if too short (increase only; not lip-sync)")
    automatic.setChecked(True)
    automatic.setToolTip(
        "ON: before any Whisper sample, use a provisional 10s desktop or "
        "6s Pi 5 buffer (native bitrate/RAM limits still apply). After 3 real "
        "Whisper samples, estimates speech-caption "
        "availability and suggests a conservative delay. When enabled and Applied, "
        "only raises an insufficient TV buffer. It NEVER reduces an existing "
        "larger user buffer; lowering it requires an explicit manual change. "
        "ASR availability is not exact spoken-word alignment.")
    auto_row.addWidget(automatic)
    timing_layout.addRow(auto_row)
    timing_layout.addRow(QLabel("<b>2 · Subtitle quality & reading</b>"))
    music_transcription = QCheckBox(
        "Include singing / music vocals in Whisper (optional; less accurate)")
    music_transcription.setChecked(False)
    music_transcription.setToolTip(
        "Available for live TV audio, too. CUDA Whisper disables voice activity "
        "filtering when checked. This is ASR, not a guarantee of exact lyrics.")
    timing_layout.addRow(music_transcription)
    speech_priority = QCheckBox(
        "Prefer spoken dialogue over background music (optional)")
    speech_priority.setChecked(False)
    speech_priority.setToolTip(
        "When music overlaps actual speech, apply gentle speech-band "
        "conditioning to the private Whisper input and use a more "
        "permissive voice-activity threshold with conservative ASR "
        "confidence checks. Does not change TV audio or guarantee "
        "true music/speech source separation. May increase errors "
        "on some broadcasts; disable it if accuracy becomes worse.")
    timing_layout.addRow(speech_priority)
    comfort_reading=QCheckBox(
        "Comfort reading · stable phrases, no flashing words, readable hold")
    comfort_reading.setChecked(True)
    comfort_reading.setToolTip(
        "Default ON. Longer, naturally paced clauses; decoded subtitles "
        "remain on screen long enough to read. This does not guarantee "
        "video-frame PTS lip synchronization.")
    timing_layout.addRow(comfort_reading)
    live_priority=QCheckBox(
        "Protect live speech · skip heavy voice/sound extras if lag builds")
    live_priority.setChecked(True)
    live_priority.setToolTip(
        "Default ON. If optional SepFormer or audio classifiers make the "
        "caption worker fall behind broadcast, temporarily omit ONLY those "
        "enhancements. Keep primary Whisper and selected translations. "
        "Cannot overcome a core speech engine slower than real time.")
    timing_layout.addRow(live_priority)
    # Voice/music-vocal recognition is a separate experiment; the two
    # goals conflict and must not be advertised as identical features.
    def choose_speech_priority(checked):
        if checked:
            music_transcription.setChecked(False)
    def choose_music_vocals(checked):
        if checked:
            speech_priority.setChecked(False)
    speech_priority.toggled.connect(choose_speech_priority)
    music_transcription.toggled.connect(choose_music_vocals)
    timing_layout.addRow(QLabel("<b>3 · Optional voice separation & sound tags</b>"))
    speakers_row = QHBoxLayout()
    speaker_enabled = QCheckBox(
        "Detect distinct voices · Resemblyzer (name labels optional)")
    speaker_enabled.setChecked(True)
    speaker_enabled.setToolTip(
        "Checked by default. Install the public Resemblyzer model in "
        "Model Market to activate local offline voice clustering. "
        "No token or microphone. Detect voice changes independently from "
        "whether speaker ID labels are shown. Resemblyzer cannot estimate "
        "gender/age and cannot separate overlapping speech.")
    speakers_row.addWidget(speaker_enabled)
    timing_layout.addRow(speakers_row)
    speaker_provider = QComboBox()
    speaker_provider.addItem(
        "Resemblyzer · public pretrained model · no token", "resemblyzer")
    speaker_provider.addItem(
        "pyannote Community-1 · requires HF model access", "pyannote")
    speaker_provider.setToolTip(
        "You can switch auto-labeling OFF. Resemblyzer "
        "runs locally without any Hugging Face token. It estimates "
        "voice similarity, not real identity, gender or age.")
    timing_layout.addRow("Speaker model", speaker_provider)
    # Speaker separation, display names, approximate voice categories and
    # environmental sound labels are INDEPENDENT owner preferences.
    speaker_numbers=QCheckBox("Show speaker names/numbers · [Speaker 1]")
    speaker_numbers.setChecked(False)
    speaker_numbers.setToolTip(
        "Optional. Leave OFF to show different speakers on separate lines "
        "WITHOUT [Speaker 1] labels. Manual names are optional overrides.")
    timing_layout.addRow(speaker_numbers)
    speaker_lines=QCheckBox(
        "New subtitle line when Resemblyzer detects a different speaker")
    speaker_lines.setChecked(True)
    timing_layout.addRow(speaker_lines)
    voice_types=QCheckBox(
        "Estimated voice type · [Male voice?] / [Female voice?] / [Child voice?]")
    voice_types.setChecked(False)
    voice_types.setToolTip(
        "Requires a separate licensed age/gender acoustic classifier. "
        "Resemblyzer cannot predict these categories. With no reliable "
        "classifier score, this option displays NO guessed category. "
        "Adult and child voices may overlap acoustically; uncertain or "
        "contradictory predictions are hidden rather than labeled.")
    timing_layout.addRow(voice_types)
    sound_events=QCheckBox(
        "Show sound labels · [Music] / [Humming] / [Applause] (subtitle language)")
    sound_events.setChecked(False)
    sound_events.setToolTip(
        "Independent from speaker names; only real detector-backed events "
        "with sufficient confidence are displayed in the chosen output "
        "subtitle language. No guess from silence.")
    timing_layout.addRow(sound_events)
    classifier_install_queue=queue.Queue(maxsize=4)
    from tv_center.audio_classifiers import AudioLabels
    classifier_status=QLabel(
        "Optional sound: "+("installed" if AudioLabels().installed("sound")
                             else "not installed")+
        " · Voice type: "+("installed" if AudioLabels().installed("voice")
                           else "not installed")+
        ". Models load ONLY when the corresponding box is checked.")
    classifier_status.setWordWrap(True)
    timing_layout.addRow(classifier_status)
    classifier_actions=QHBoxLayout()
    event_install_button=QPushButton("Install sound detector · ~346 MB weights")
    voice_install_button=QPushButton(
        "Install voice-type estimator · ~363 MB · noncommercial license")
    def install_classifier(kind):
        lic=("This audEERING model is CC BY-NC-SA 4.0, NON-COMMERCIAL "
             "ONLY. Its child/female/male predictions are uncertain "
             "voice characteristics, NOT actual identities. "
             if kind=="voice" else
             "The MIT AudioSet AST classifier is BSD-3-Clause. ")
        reply=QMessageBox.question(
            window,"Install optional audio model?",
            lic+"Download model weights and CPU PyTorch dependencies (may "
            "use several GB total)? Runs offline only when enabled. Continue?",
            QMessageBox.Yes | QMessageBox.No,QMessageBox.No)
        if reply!=QMessageBox.Yes:
            return
        button=voice_install_button if kind=="voice" else event_install_button
        button.setEnabled(False)
        classifier_status.setText(
            "Owner-approved "+kind+" classifier installation in background…")
        def install_worker():
            try:
                info=AudioLabels().install(
                    kind,noncommercial_acknowledged=(kind=="voice"))
                classifier_install_queue.put((kind,"ok",info))
            except Exception as exc:
                classifier_install_queue.put((kind,"error",str(exc)[:220]))
        threading.Thread(target=install_worker,daemon=True,
                         name="tihulu-"+kind+"-classifier-install").start()
    event_install_button.clicked.connect(lambda:install_classifier("sound"))
    voice_install_button.clicked.connect(lambda:install_classifier("voice"))
    classifier_actions.addWidget(event_install_button)
    classifier_actions.addWidget(voice_install_button)
    timing_layout.addRow(classifier_actions)
    overlap_enabled=QCheckBox(
        "Experimental · separate TWO simultaneous voices (SepFormer + 2× Whisper)")
    overlap_enabled.setChecked(False)
    overlap_enabled.setToolTip(
        "Runs real SpeechBrain SepFormer audio-source separation in an "
        "isolated worker and transcribes each source separately. Requires "
        "an owner-installed model, extra GPU/CPU time and TV buffer. "
        "Not verified on multilingual TV; never invents a second transcript.")
    timing_layout.addRow(overlap_enabled)
    overlap_status=QLabel(
        "Overlap separation OFF · model installed separately on demand; "
        "English-trained SepFormer, quality and GPU speed not yet verified.")
    overlap_status.setWordWrap(True)
    timing_layout.addRow(overlap_status)
    overlap_install_queue=queue.Queue(maxsize=2)
    overlap_install_button=QPushButton(
        "Install SepFormer · ~113 MB weights + larger Torch dependencies")
    def install_sepformer_clicked():
        from tv_center.overlap_separation import OverlapSeparation
        if OverlapSeparation().installed():
            overlap_status.setText("SepFormer already installed · inference untested")
            return
        response=QMessageBox.question(
            window,"Install experimental two-speaker separation?",
            "Download SepFormer weights (~113 MB) and potentially several GB "
            "of isolated PyTorch dependencies? This English-trained model "
            "is NOT verified for multilingual TV or real-time CUDA use. "
            "Install only after owner approval.",
            QMessageBox.Yes | QMessageBox.No,QMessageBox.No)
        if response!=QMessageBox.Yes:
            return
        overlap_install_button.setEnabled(False)
        overlap_status.setText("Owner-approved model setup running off UI thread")
        def owner_install():
            try:
                text=OverlapSeparation().install()
                overlap_install_queue.put(("ok",text))
            except Exception as exc:
                overlap_install_queue.put(("error",str(exc)[:250]))
        threading.Thread(target=owner_install,daemon=True,
                         name="tihulu-sepformer-owner-install").start()
    overlap_install_button.clicked.connect(install_sepformer_clicked)
    timing_layout.addRow(overlap_install_button)
    speaker_health = QLabel(
        "Auto labels: checking installed local speaker model…")
    speaker_health.setWordWrap(True)
    timing_layout.addRow("Voice status", speaker_health)
    # Cluster IDs are provisional; names are user-authored, never guessed
    # as adult/child/gender based on pitch or voice embeddings.
    voice_label_store = QSettings("TIHULU", "KaffeineSpeakerLabelNames")
    speaker_alias_inputs = []
    label_fields = QWidget()
    label_fields_layout = QGridLayout(label_fields)
    label_fields_layout.setContentsMargins(0,0,0,0)
    for i in range(4):
        name_input = QLineEdit()
        name_input.setMaxLength(30)
        name_input.setPlaceholderText(
            ("e.g. Adam 1" if i == 0 else "e.g. Çocuk 2" if i == 1
             else f"Optional name {i+1}"))
        saved = voice_label_store.value(f"speaker_{i+1}","",type=str)
        name_input.setText(saved if isinstance(saved,str) else "")
        name_input.setToolTip(
            f"Optional display label for provisional voice cluster {i+1}. "
            "Examples are user-entered, not inferred age, gender or identity.")
        label_fields_layout.addWidget(QLabel(f"Voice {i+1}"),i,0)
        label_fields_layout.addWidget(name_input,i,1)
        speaker_alias_inputs.append(name_input)
    label_fields.setVisible(False)
    manual_names=QCheckBox("Optional manual voice name overrides · advanced")
    manual_names.setChecked(False)
    manual_names.toggled.connect(label_fields.setVisible)
    timing_layout.addRow(manual_names)
    timing_layout.addRow(label_fields)
    voice_label_explanation=QLabel(
        "Speaker names are optional, not required. Leave names OFF for "
        "unlabelled voice changes. Age/gender categories require a separate "
        "acoustic model and are never inferred from Resemblyzer clusters. "
        "Two simultaneous lines require real separated audio and two "
        "different Whisper transcripts.")
    voice_label_explanation.setWordWrap(True)
    timing_layout.addRow(voice_label_explanation)
    sync_estimate = QLabel("Automatic timing: collecting real ASR samples (0/3). "
                           "Live TV and manually entered delay are unchanged.")
    sync_estimate.setWordWrap(True)
    timing_layout.addRow(sync_estimate)
    effective_status = QLabel("Native TV delay: waiting for Kaffeine's applied buffer status…")
    effective_status.setWordWrap(True)
    timing_layout.addRow(effective_status)
    buffer_progress = QProgressBar()
    buffer_progress.setObjectName("tvBufferFillProgress")
    buffer_progress.setRange(0, 0)
    buffer_progress.setTextVisible(True)
    buffer_progress.setFormat("Awaiting native TV buffer status")
    buffer_progress.setToolTip(
        "Real MPEG-TS queue age from Kaffeine, not an estimate based on "
        "elapsed wall-clock time. The percentage stays unknown until a "
        "matching native buffer acknowledgement is received.")
    # Place the actual progress bar below the tabs, visible in every view.
    visibility = QHBoxLayout()
    renderer = QComboBox()
    renderer.addItem("Native libVLC · in-video compositor (preferred)", "native")
    renderer.addItem("Legacy Qt · bounded video strip (fallback)", "legacy-qt")
    renderer.setToolTip("Native libVLC avoids frozen video frames. "
                        "Legacy Qt stays inside the current video rectangle and supports "
                        "background opacity, but may still be limited by Wayland compositing.")
    quick_layout.addRow("Renderer", renderer)
    show_video = QCheckBox("On-video subtitles"); show_video.setChecked(True)
    position = QComboBox(); position.addItems(("bottom", "top"))
    font = QSpinBox(); font.setRange(16, 44); font.setValue(25)
    opacity = QSpinBox(); opacity.setRange(0, 100); opacity.setValue(0); opacity.setSuffix("%")
    text_opacity = QSpinBox()
    text_opacity.setRange(0, 100); text_opacity.setValue(100)
    text_opacity.setSuffix("%")
    visibility.addWidget(show_video)
    for name, widget in (("Position",position),("Size",font)):
        visibility.addWidget(QLabel(name)); visibility.addWidget(widget)
    quick_layout.addRow(visibility)
    appearance_row = QGridLayout()
    appearance_row.addWidget(QLabel("Background opacity"),0,0)
    appearance_row.addWidget(opacity,0,1)
    appearance_row.addWidget(QLabel("Text opacity"),0,2)
    appearance_row.addWidget(text_opacity,0,3)
    background_button = QPushButton("Background · #000000")
    text_button = QPushButton("Text · #FFFFFF")
    active_colors = {"background":"#000000", "text":"#FFFFFF"}
    background_button.setToolTip(
        "Choose the solid subtitle backing color; opacity is independent "
        "and supports 0% (completely transparent)")
    text_button.setToolTip(
        "Choose the text color separately from its opacity (0–100%)")
    appearance_row.addWidget(background_button,1,0,1,2)
    appearance_row.addWidget(text_button,1,2,1,2)
    quick_layout.addRow("Subtitle appearance", appearance_row)
    preset_row = QHBoxLayout()
    presets = QComboBox()
    presets.addItem("No background · white text visible", ("#FFFFFF","#000000",0,100))
    presets.addItem("White text · translucent black", ("#FFFFFF","#000000",70,100))
    presets.addItem("Yellow text · black", ("#FFE45C","#000000",75,100))
    presets.addItem("Cyan text · navy", ("#6EE7F8","#0B2540",60,100))
    presets.addItem("Yellow text · no background", ("#FFE45C","#000000",0,100))
    presets.addItem("Hide ALL subtitles · both opacities 0%", ("#FFFFFF","#000000",0,0))
    presets.addItem("Custom colors / transparency", None)
    presets.setToolTip(
        "A preset can be changed with either color picker, or "
        "use individual background and text transparency controls.")
    preset_row.addWidget(presets,1)
    appearance_preview = QLabel("DE: Guten Morgen   ·   TR: Günaydın")
    appearance_preview.setAlignment(Qt.AlignCenter)
    appearance_preview.setMinimumHeight(55)
    appearance_preview.setWordWrap(True)
    preset_row.addWidget(appearance_preview,2)
    quick_layout.addRow("Appearance presets", preset_row)
    transparent_help = QLabel(
        "No background = Background 0% and Text 100%. "
        "Text 0% hides the letters too. The chosen appearance is saved "
        "locally and restored next time; it does NOT change DVB subtitles "
        "drawn independently by the broadcaster.")
    transparent_help.setWordWrap(True)
    quick_layout.addRow(transparent_help)
    native_note = QLabel(
        "Native video renderer: subtitle text and an optional colored "
        "background are composited into the VLC video itself. "
        "Background 0% is fully transparent; use 60–80% for a readable "
        "translucent backing. All colors, opacity, position and size "
        "apply without enabling the experimental Qt overlay.")
    native_note.setWordWrap(True)
    quick_layout.addRow(native_note)
    appearance_store = QSettings("TIHULU", "KaffeineCaptionAppearance")

    def update_appearance_preview(*_):
        fg = QColor(active_colors["text"])
        bg = QColor(active_colors["background"])
        bg.setAlpha(round(opacity.value()*255/100))
        fg.setAlpha(round(text_opacity.value()*255/100))
        appearance_preview.setStyleSheet(
            "QLabel{border:1px solid #36556a;border-radius:8px;"
            f"background-color:rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});"
            f"color:rgba({fg.red()},{fg.green()},{fg.blue()},{fg.alpha()});"
            "font-weight:700;padding:8px;}")
        background_button.setText("Background · "+active_colors["background"])
        text_button.setText("Text · "+active_colors["text"])

    def apply_appearance_preset(*_):
        selected = presets.currentData()
        if selected is None:
            return
        foreground, background, back_alpha, text_alpha = selected
        active_colors["text"] = foreground
        active_colors["background"] = background
        opacity.setValue(back_alpha)
        text_opacity.setValue(text_alpha)
        update_appearance_preview()

    def pick_appearance_color(which):
        selected = QColorDialog.getColor(
            QColor(active_colors[which]), window,
            "Choose subtitle " + which + " color",
            QColorDialog.DontUseNativeDialog)
        if not selected.isValid():
            return
        active_colors[which] = selected.name().upper()
        presets.setCurrentIndex(presets.count()-1)
        update_appearance_preview()
        set_pending()

    background_button.clicked.connect(lambda: pick_appearance_color("background"))
    text_button.clicked.connect(lambda: pick_appearance_color("text"))
    presets.currentIndexChanged.connect(apply_appearance_preset)
    def appearance_opacity_changed(*_):
        presets.blockSignals(True)
        presets.setCurrentIndex(presets.count()-1)
        presets.blockSignals(False)
        update_appearance_preview()
    opacity.valueChanged.connect(appearance_opacity_changed)
    text_opacity.valueChanged.connect(appearance_opacity_changed)
    # Restore only an explicitly SAVED appearance. Never reset a viewer's
    # no-background preference when they reopen the captions controller.
    for channel in ("text", "background"):
        stored = str(appearance_store.value(channel+"_color",
                     active_colors[channel]))
        if QColor(stored).isValid() and len(stored)==7:
            active_colors[channel] = stored.upper()
    try:
        opacity.setValue(int(appearance_store.value("background_opacity", 0)))
        text_opacity.setValue(int(appearance_store.value("text_opacity", 100)))
    except (ValueError,TypeError):
        opacity.setValue(0)
        text_opacity.setValue(100)
    presets.setCurrentIndex(presets.count()-1)
    saved_renderer = str(appearance_store.value("renderer", "native"))
    renderer.setCurrentIndex(1 if saved_renderer == "legacy-qt" else 0)
    update_appearance_preview()
    control_layout.addWidget(timing)
    control_layout.addStretch(1)
    control_scroll = QScrollArea()
    control_scroll.setWidgetResizable(True)
    control_scroll.setFrameShape(QFrame.NoFrame)
    control_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    control_scroll.setWidget(control_body)
    pages = QTabWidget()
    appearance_scroll = QScrollArea()
    appearance_scroll.setWidgetResizable(True)
    appearance_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    appearance_scroll.setWidget(quick)
    pages.addTab(appearance_scroll, "Appearance")
    pages.addTab(control_scroll, "Source & sync")
    tools_page = QWidget()
    tools_layout = QVBoxLayout(tools_page)
    tools_layout.setContentsMargins(8, 8, 8, 8)
    tools_layout.setSpacing(8)
    pages.addTab(tools_page, "Diagnostics & network")
    pages.setCurrentIndex(0)
    root.addWidget(pages, 1)
    # A compact pinned buffer meter remains visible on every settings tab.
    # Source & sync also contains the detailed native status explanation.
    pinned_progress = QLabel("TV buffer: waiting for receiver")
    pinned_progress.setWordWrap(True)
    root.addWidget(pinned_progress)
    native_channel_status = QLabel("TV source: waiting for native Kaffeine channel")
    native_channel_status.setWordWrap(True)
    root.addWidget(native_channel_status)
    caption_pipeline_health=QLabel(
        "Live captions: preparing TV audio and offline speech worker…")
    caption_pipeline_health.setWordWrap(True)
    caption_pipeline_health.setToolTip(
        "Real queued six-second clips, caption delivery losses, and time "
        "since a subtitle was shown. Not a speech/silence detector.")
    root.addWidget(caption_pipeline_health)
    # Always visible on every tab, including Caption preview and diagnostics.
    # Never merely equate Teletext existence or PTS with spoken correctness.
    root.addWidget(teletext_speech_status)
    root.addWidget(buffer_progress)
    buttons = QHBoxLayout()
    apply = QPushButton("Apply")
    apply.setObjectName("apply")
    reset = QPushButton("Reset")
    pending = QLabel("Pending: Spoken Auto detect · output English · "
                     "apply to begin; broadcast language may change")
    buttons.addWidget(apply); buttons.addWidget(reset); buttons.addWidget(pending, 1)
    root.addLayout(buttons)
    behavior = QHBoxLayout()
    hide_panel = QPushButton("Hide settings")
    back_to_tv = QPushButton("Back to TV · keep captions running")
    back_to_tv.setToolTip(
        "Minimize these non-modal settings so Kaffeine has keyboard focus "
        "for channel numbers, arrows and its channel list. Whisper and "
        "translations continue in this process.")
    start_subtitles = QPushButton("Start subtitles")
    stop_subtitles = QPushButton("Stop subtitles")
    caption_refresh = QPushButton("AI Caption Refresh")
    sync_refresh = QPushButton("Lip-sync Refresh")
    caption_refresh.setToolTip("Re-read AI settings and replace only subtitle session; Kaffeine TV remains playing")
    sync_refresh.setToolTip("Reset estimated subtitle timing samples without touching media audio or your manual offset")
    exit_subtitles = QPushButton("Exit caption service")
    start_subtitles.setEnabled(False)
    behavior.addWidget(start_subtitles)
    behavior.addWidget(stop_subtitles)
    behavior.addWidget(caption_refresh)
    behavior.addWidget(sync_refresh)
    behavior.addWidget(back_to_tv)
    behavior.addWidget(hide_panel)
    behavior.addWidget(exit_subtitles)
    root.addLayout(behavior)
    persistence = QLabel("Closing or minimizing this non-modal settings panel keeps "
                         "on-video subtitles, Whisper and translation running. "
                         "When settings have keyboard focus, use Back to TV to "
                         "change channels in Kaffeine. Reopen with Kaffeine → "
                         "TIHULU AI → Live Teletext / Whisper subtitles. "
                         "Stop pauses ASR without closing settings; Start resumes. "
                         "Exit closes the caption service entirely.")
    persistence.setWordWrap(True)
    tools_layout.addWidget(persistence)

    original = QLabel("Waiting for real Kaffeine DVB stream…")
    original.setObjectName("subtitle"); original.setWordWrap(True)
    translated = QLabel("")
    translated.setObjectName("subtitle"); translated.setWordWrap(True)
    translated.setToolTip(
        "Translations are computed offline. Missing or broken NLLB "
        "automatically uses installed Argos language packs. Model errors "
        "are never shown as captions.")
    preview_body = QWidget()
    preview_layout = QVBoxLayout(preview_body)
    preview_layout.setContentsMargins(5, 4, 5, 4)
    preview_layout.addWidget(original)
    preview_layout.addWidget(translated)
    # Acoustic cues are a separate row; never mutate ASR/translated words.
    sound_line = QLabel("")
    sound_line.setObjectName("sound_event_subtitle")
    sound_line.setWordWrap(True)
    sound_line.setVisible(False)
    sound_line.setToolTip(
        "Detector-backed sound cues are display-only, independent of "
        "real Whisper speech and translations.")
    preview_layout.addWidget(sound_line)
    preview_scroll = QScrollArea()
    preview_scroll.setWidgetResizable(True)
    preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    preview_scroll.setMaximumHeight(150)
    preview_scroll.setMinimumHeight(58)
    preview_scroll.setWidget(preview_body)
    root.addWidget(preview_scroll)
    srt_controls = QHBoxLayout()
    srt_start = QPushButton("Start SRT recording")
    srt_stop = QPushButton("Stop SRT recording")
    srt_stop.setEnabled(False)
    srt_controls.addWidget(srt_start)
    srt_controls.addWidget(srt_stop)
    root.addLayout(srt_controls)
    srt_status = QLabel("SRT: off · originals and translations saved as separate tracks.")
    srt_status.setWordWrap(True)
    root.addWidget(srt_status)
    status = QLabel("Whisper captions use 6-second overlapping audio chunks plus processing time. "
                    "Audio and video remain synchronized with each other.")
    status.setWordWrap(True)
    diagnostics_toggle = QPushButton("Show detailed ASR / translator diagnostics")
    diagnostics_toggle.setCheckable(True)
    status.setMinimumHeight(48)
    status.setWordWrap(True)
    status.setVisible(False)
    diagnostics_toggle.toggled.connect(status.setVisible)
    tools_layout.addWidget(diagnostics_toggle)
    tools_layout.addWidget(status)

    market = QPushButton("Whisper + Translator Model Market")
    def launch_market():
        import subprocess
        subprocess.Popen(["tihulu-tv-center","ai-market"],close_fds=True)
    market.clicked.connect(launch_market)
    tools_layout.addWidget(market)
    benchmark_button = QPushButton(
        "Test installed AI models on a local audio sample…")
    benchmark_button.setToolTip(
        "Offline opt-in: select your own local recording. Real Whisper/Argos/NLLB "
        "candidates are timed with six seconds of audio, without tuning the "
        "DVB receiver, downloading anything or changing settings. The result "
        "is editable and requires your confirmation.")
    benchmark_status = QLabel(
        "AI performance test: not run on this computer. No model speed assumed.")
    benchmark_status.setWordWrap(True)
    tools_layout.addWidget(benchmark_button)
    cancel_benchmark_button=QPushButton("Stop AI model test")
    cancel_benchmark_button.setEnabled(False)
    tools_layout.addWidget(cancel_benchmark_button)
    live_test_button=QPushButton("Measure current live subtitle pipeline · 4 clips")
    live_test_button.setToolTip(
        "Passive: observes the existing caption worker over four real "
        "six-second clips. No extra Whisper inference, tuner access, "
        "backend switch or playback-buffer change.")
    tools_layout.addWidget(live_test_button)
    tools_layout.addWidget(benchmark_status)
    phone = QCheckBox("Allow phone/tablet on trusted Wi-Fi (OFF by default)")
    video = QCheckBox("Share the live channel as H.264/AAC HLS (CPU intensive)")
    lan_note = QLabel("Mobile access OFF. No network listener.")
    lan_note.setWordWrap(True)
    tools_layout.addWidget(phone)
    tools_layout.addWidget(video)
    tools_layout.addWidget(lan_note)
    tools_layout.addStretch(1)

    ipc = KaffeineOSD(pid, runtime=endpoint.parent)
    events = queue.Queue(maxsize=32)
    control = CaptionServiceControl(endpoint.parent, pid, events)
    try:
        control.start()
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("Cannot start private caption controller: " + str(exc)) from exc
    lock = threading.Lock()
    applied = CaptionConfig().validate()
    service_running = True
    from .live_srt import LiveSRTRecorder
    srt_recorder = LiveSRTRecorder()
    cues = CueQueue(maximum=32)
    from .caption_timing import SpeakerLineHistory
    recent_voice_lines=SpeakerLineHistory()
    # A six-second Whisper clip plus inference/translation may arrive more
    # than six seconds after speaking began. On desktop allow up to 15s,
    # but still obey the measured 48 MiB memory budget and native FIFO cap.
    # Raspberry Pi 5 stays at a conservative six-second maximum.
    pi5 = False
    try:
        model = Path("/proc/device-tree/model")
        pi5 = model.is_file() and "Raspberry Pi 5" in model.read_bytes().decode(
            "utf-8", "replace")
    except OSError:
        pass
    estimator = AutoSyncEstimator(ceiling_ms=6000 if pi5 else 15000)
    auto_controller = AutoSyncController()
    startup_buffer_pending = True
    last_service_id = None
    last_ui_program_epoch = 0
    last_effective_check = 0.0
    last_applied_effective_ms = None
    pending_buffer_retime_ms = None
    native_release_clock=NativeReleaseClock()
    last_sync_audit_at = 0.0
    def options():
        with lock:
            values = applied.options()
            if not service_running:
                values["mode"] = "off"  # no new Whisper jobs while paused
            return values
    from .mobile import KaffeineMobile
    mobile = KaffeineMobile(
        options, lambda msg: events.put(("warning",str(msg))),
        gui_commands=lambda action,params: events.put_nowait(
            ("remote_gui_command",{"action":action,"params":params})))
    tap = CaptionTap(str(endpoint), options, events, packet_sink=mobile.receive,
                     owner_tune_changed=mobile.owner_tune_changed)
    try:
        tap.start()
    except (OSError, RuntimeError) as exc:
        control.close()
        # No receiver means nothing to preserve in the background.
        # Let the error window close normally instead of leaving an
        # invisible Qt process running forever with no subtitle source.
        window.terminating = True
        app.setQuitOnLastWindowClosed(True)
        status.setText("Cannot receive Kaffeine DVB stream: "+str(exc))
        window.show()
        return app.exec_()

    current_text = ""
    current_until = 0.0
    last_published = 0.0
    current_cue = None
    last_cue_shown_at=time.monotonic()
    last_pipeline_health_at=0.0
    # Captions decoded during a temporary native-buffer ACK delay are
    # HELD rather than silently dropped. They remain bounded in memory
    # and are discarded on actual channel/source changes.
    deferred_captions = deque(maxlen=48)

    def from_controls():
        selected = subtitle_track.currentData()
        # A Teletext subtitle channel's language is signalled by the
        # broadcaster. Never run French captions through a German
        # translator merely because the prior Spoken box said 'de'.
        chosen_track = (selected if isinstance(selected, dict) and
                        mode.currentData() in ("auto","teletext","page") else None)
        selected_audio = audio_track.currentData()
        chosen_audio = (selected_audio if isinstance(selected_audio, dict) and
                        mode.currentData() in ("asr", "auto") else None)
        broadcast_hint = (chosen_track.get("source_hint") or
                          chosen_track.get("language")) if chosen_track else (
                          chosen_audio.get("source_hint") or
                          chosen_audio.get("language")) if chosen_audio else None
        try:
            hinted = language_code(broadcast_hint) if broadcast_hint else None
        except (TypeError, ValueError):
            hinted = None
        if hinted == "und" or (mode.currentData() in ("auto","asr") and
                                hinted and hinted not in WHISPER_LANGUAGES and
                                chosen_track is None):
            hinted = None
        automatic_source = source.currentData() == "auto" and source.currentIndex()==0
        # An explicitly selected speech language takes precedence. With Auto,
        # use a trustworthy DVB audio/subtitle language BEFORE asking Whisper
        # to guess from a noisy six-second chunk. With no reliable descriptor,
        # retain real Whisper auto-detection (never quietly assume German).
        spoken = (hinted or "auto") if automatic_source else (
            language_code(source.currentText()))
        if not automatic_source and mode.currentData() in ("auto","asr") and (
                spoken not in WHISPER_LANGUAGES):
            raise ValueError("This source language is not supported by Whisper: " +
                             spoken.upper())
        raw_targets = [
            lang for lang, check in language_boxes.items() if check.isChecked()]
        raw_targets.extend(x.strip() for x in extra_targets.text().replace(
            ";", ",").split(",") if x.strip())
        # Never remove the explicitly checked EN/TR checkbox when the
        # broadcaster changes its actual Teletext or audio source language:
        # requested output EN is valid even when EN is already the original.
        target_langs = tuple(dict.fromkeys(
            language_code(lang, nllb=True) for lang in raw_targets))
        output = display_mode.currentData()
        return CaptionConfig(
            mode=mode.currentData(), source=spoken,
            target=target_langs[0] if target_langs else spoken,
            target_languages=target_langs if output != "original" else (),
            page=chosen_track["page"] if chosen_track else page.value(),
            teletext_pid=chosen_track["pid"] if chosen_track else None,
            teletext_language=(hinted if chosen_track else None),
            audio_pid=chosen_audio["pid"] if chosen_audio else None,
            audio_language=(hinted if automatic_source and chosen_audio and
                            hinted in WHISPER_LANGUAGES else None),
            spoken_auto=automatic_source,
            speaker_enabled=speaker_enabled.isChecked(),
            show_speaker_numbers=speaker_numbers.isChecked(),
            show_voice_types=voice_types.isChecked(),
            break_speaker_lines=speaker_lines.isChecked(),
            show_sound_events=sound_events.isChecked(),
            separate_overlapping_voices=overlap_enabled.isChecked(),
            music_transcription=music_transcription.isChecked(),
            speech_priority=speech_priority.isChecked(),
            readable_pacing=comfort_reading.isChecked(),
            live_priority=live_priority.isChecked(),
            speaker_provider=speaker_provider.currentData(),
            speaker_aliases=tuple(entry.text().strip()
                                  for entry in speaker_alias_inputs),
            offset_ms=round(caption_offset.value()*1000),
            playback_delay_ms=round(playback_delay.value()*1000),
            automatic_sync=automatic.isChecked(),
            on_video=show_video.isChecked(),
            show_original=output in ("original","both"),
            show_translation=output in ("translated","both"),
            position=position.currentText(),font_px=font.value(),
            render_mode=renderer.currentData(),
            opacity=opacity.value(),text_opacity=text_opacity.value(),
            text_color=active_colors["text"],
            background_color=active_colors["background"]
        ).validate()

    def set_pending(*_):
        pending.setText("Unsaved changes — press Apply")
        pending.setStyleSheet("color:#f7bf6e")
    for w in (mode,source,display_mode,position,renderer,subtitle_track,
              audio_track,speaker_provider):
        w.currentIndexChanged.connect(set_pending)
    def subtitle_source_selected(*_):
        selected = subtitle_track.currentData()
        if isinstance(selected,dict):
            language = selected.get("source_hint")
            if mode.currentData() in ("auto","teletext","page"):
                # An audio/Teletext descriptor is an input-language hint,
                # not a request to replace the user's Auto/English UI choice
                # or an explicitly chosen manual language.
                if language not in LANGS:
                    track_status.setText(
                        "Original broadcaster subtitles remain available. "
                        "Choose a matching language pack in Model Market if "
                        "you also want these captions translated.")
        set_pending()
    subtitle_track.currentIndexChanged.connect(subtitle_source_selected)
    def audio_source_selected(*_):
        selected = audio_track.currentData()
        if isinstance(selected, dict):
            language = selected.get("source_hint")
            if mode.currentData() in ("asr", "auto"):
                detected = selected.get("source_hint") or selected.get("language")
                if (not detected or
                        language_code(detected) not in WHISPER_LANGUAGES):
                    audio_track_status.setText(
                        "This audio language is not in Whisper's supported "
                        "language set. You can display broadcast Teletext "
                        "instead or select another available soundtrack.")
        set_pending()
    audio_track.currentIndexChanged.connect(audio_source_selected)
    extra_targets.textChanged.connect(set_pending)
    presets.currentIndexChanged.connect(set_pending)
    source.currentTextChanged.connect(set_pending)
    for w in (page,playback_delay,font,opacity,text_opacity):
        w.valueChanged.connect(set_pending)
    def apply_offset_immediately(value):
        nonlocal applied, current_text, current_until
        # Only the caption presentation clock is modified here.
        # An unsaved change to source, model or audio buffer remains pending.
        new_offset = round(float(value)*1000)
        old_offset = applied.offset_ms
        if new_offset == old_offset:
            return
        with lock:
            applied = __import__("dataclasses").replace(
                applied, offset_ms=new_offset)
        cues.retime(new_offset-old_offset,applied)
        if current_cue is not None:
            current_cue["config"] = applied
            current_text = applied.render(current_cue["result"])
            ipc.publish(current_text,applied,ttl_ms=4000)
            current_until = max(current_until,time.monotonic()+1.8)
        pending.setText("Caption offset applied live · " +
                        str(new_offset/1000) + "s. Other changes: Apply")
    caption_offset.valueChanged.connect(apply_offset_immediately)
    for w in (show_video,automatic,speaker_enabled,speaker_numbers,
              speaker_lines,voice_types,sound_events,overlap_enabled,
              music_transcription,speech_priority,comfort_reading,
              live_priority):
        w.toggled.connect(set_pending)
    for entry in speaker_alias_inputs:
        entry.textChanged.connect(set_pending)

    def apply_settings():
        nonlocal applied, current_text, current_until, current_cue
        nonlocal startup_buffer_pending,pending_buffer_retime_ms
        try:
            if startup_buffer_pending:
                startup_buffer_pending=False
                if (automatic.isChecked() and mode.currentData() in ("auto","asr")
                        and playback_delay.value()==0):
                    from .caption_timing import provisional_ai_buffer_ms
                    playback_delay.setValue(
                        provisional_ai_buffer_ms(pi5)/1000.0)
            selected = from_controls()
            previous = applied
            source_changed = any(
                getattr(selected, key) != getattr(previous, key)
                for key in ("mode", "source", "target_languages", "page",
                            "teletext_pid", "audio_pid", "audio_language",
                            "music_transcription", "speech_priority"))
            # Speaker labels/diarization choices are optional per-clip
            # processing, NOT a new TV channel or a reason to throw away
            # incoming speech. New options apply on the next captured clip.
            # The native video/audio buffer really changes the media clock.
            # Unlike a cosmetic change, that requires fresh cue calibration.
            playback_changed = (selected.playback_delay_ms !=
                                previous.playback_delay_ms)
            if source_changed:
                estimator.clear()
            if selected.automatic_sync != previous.automatic_sync:
                auto_controller.reset()
            with lock:
                applied = __import__("dataclasses").replace(
                    selected, revision=previous.revision +
                    int(source_changed))
            if source_changed:
                # Only a genuine source/channel change invalidates speech.
                cues.clear()
                deferred_captions.clear()
                recent_voice_lines.clear()
                native_release_clock.clear()
                pending_buffer_retime_ms = None
                current_cue = None
                current_text = ""
                current_until = 0.0
                original.setText("Waiting for captions under the new source settings…")
                translated.setText("")
                sound_line.clear()
                sound_line.setVisible(False)
                ipc.publish("", applied if service_running else
                            __import__("dataclasses").replace(applied, mode="off"))
            elif playback_changed:
                # Keep REAL decoded sentences during temporary FIFO re-prime.
                # Do NOT replay them against the old playback clock; the
                # pump gates the cue queue until native status confirms.
                pending_buffer_retime_ms = (
                    last_applied_effective_ms if
                    last_applied_effective_ms is not None else
                    previous.playback_delay_ms)
                cues.retime(0,applied)
                native_release_clock.clear()
                pending.setText(
                    "TV buffer re-priming · decoded captions retained, "
                    "timeline paused until native confirmation")
            else:
                # Font, opacity, position, visible languages and caption
                # offset are display-time changes, NOT a new ASR source.
                cues.retime(applied.offset_ms - previous.offset_ms, applied)
                if current_cue is not None:
                    current_cue["config"] = applied
                    current_text = applied.render(current_cue["result"])
                    ipc.publish(current_text, applied, ttl_ms=4000)
                    current_until = max(current_until, time.monotonic()+1.8)
            if playback_changed:
                ipc.set_playback_delay(applied)
            automatic_active = applied.automatic_sync and applied.mode not in ("off","page","teletext")
            sync_estimate.setText(
                ("Automatic timing (increase-only) · provisional startup buffer "
                 "10s desktop / 6s Pi; awaiting real ASR samples and native "
                 "TS-release confirmation ("
                 + str(len(estimator.values)) + "/3); conservative maximum "
                 + str(estimator.ceiling_ms / 1000) + " s.")
                if automatic_active else
                "Automatic timing OFF; measured recommendations will not change playback.")
            for channel in ("text", "background"):
                appearance_store.setValue(
                    channel+"_color",active_colors[channel])
            appearance_store.setValue("background_opacity",applied.opacity)
            appearance_store.setValue("text_opacity",applied.text_opacity)
            appearance_store.setValue("renderer",applied.render_mode)
            appearance_store.sync()
            # File playback inherits the user's applied TV language / output
            # choices, not the DVB transport, Teletext PIDs, live buffer or
            # channel-specific audio clock. The native Playback tab reads this
            # preset when it opens a local video. Audio-only files instead
            # read the independently saved KaffeineRadio language choices.
            file_video_defaults = QSettings("TIHULU", "KaffeineTVFileCaptionDefaults")
            file_video_defaults.setValue("spokenSource",
                                         "auto" if applied.spoken_auto else applied.source)
            file_video_defaults.setValue("outputLanguages",
                                         list(applied.target_languages))
            file_video_defaults.setValue("showOriginal", applied.show_original)
            file_video_defaults.setValue("showTranslation", applied.show_translation)
            file_video_defaults.setValue("musicTranscription",
                                         applied.music_transcription)
            file_video_defaults.setValue("readablePacing", applied.readable_pacing)
            file_video_defaults.setValue("soundEvents", applied.show_sound_events)
            file_video_defaults.setValue("speakerEnabled", applied.speaker_enabled)
            file_video_defaults.sync()
            for i,alias in enumerate(applied.speaker_aliases,1):
                voice_label_store.setValue(f"speaker_{i}",alias)
            voice_label_store.sync()
            pending.setText("Applied · " + applied.mode + " · " + applied.source.upper() +
                            " → " + (" + ".join(lang.upper() for lang in
                                applied.target_languages) or "original only") +
                            " · playback buffer " + str(applied.playback_delay_ms/1000) + " s")
            from tv_center.ai_settings import AISettings
            from tv_center.free_speakers import FreeSpeakerMarket
            from tv_center.speaker_market import SpeakerMarket
            active_ai = AISettings().values
            provider_ready = (FreeSpeakerMarket().status()["installed"]
                              if applied.speaker_provider == "resemblyzer"
                              else SpeakerMarket().status()["installed"])
            speaker_health.setText(
                ("Voice model installed · " + applied.speaker_provider +
                 " · accurate speaker-to-text labels require usable ASR "
                 "word timestamps; an untimed full sentence remains "
                 "unassigned" if (
                    applied.speaker_enabled and provider_ready) else
                 "Auto labels selected, but "+applied.speaker_provider+
                 " is NOT installed: open Model Market → Speaker separation"
                 if applied.speaker_enabled else "Voice labels OFF"))
            translation_health.setText(
                "Selected translator: " +
                (active_ai.get("translation_model","argos").upper()
                 if active_ai.get("translation_enabled") else "OFF") +
                " · waiting for real subtitle/translation status")
            pending.setStyleSheet("color:#9ed7ba")
            status.setText("Applied. Caption offset: "+str(applied.offset_ms/1000)+
                           "s; TV playback buffer: "+str(applied.playback_delay_ms/1000)+
                           "s. Real ASR timing varies with model CPU/GPU performance.")
        except (ValueError, OSError) as exc:
            status.setText("Settings were not applied: " + str(exc))

    live_test_started_at=0.0
    live_test_baseline=0
    live_test_baseline_overflows=0
    live_test_baseline_ts_gaps=0
    def begin_live_test():
        nonlocal live_test_started_at,live_test_baseline
        nonlocal live_test_baseline_overflows,live_test_baseline_ts_gaps
        state=tap.performance_snapshot()
        live_test_baseline=state["completed_clips"]
        live_test_baseline_overflows=state["queue"]["overflows"]
        live_test_baseline_ts_gaps=state["ts"].get("continuity_gaps",0)
        live_test_started_at=time.monotonic()
        live_test_button.setEnabled(False)
        benchmark_status.setText(
            "Observing four NEW real DVB caption clips. "
            "TV tuner, installed models and buffer unchanged.")
    live_test_button.clicked.connect(begin_live_test)

    benchmark_process = QProcess(window)
    benchmark_cancelled=False
    def cancel_benchmark():
        nonlocal benchmark_cancelled
        if benchmark_process.state()!=QProcess.NotRunning:
            benchmark_cancelled=True
            cancel_benchmark_button.setEnabled(False)
            benchmark_status.setText(
                "Stopping local AI test and its model worker… "
                "No settings have been changed.")
            benchmark_process.terminate()
            QTimer.singleShot(3500,lambda:
                benchmark_process.kill() if
                benchmark_process.state()!=QProcess.NotRunning else None)
    cancel_benchmark_button.clicked.connect(cancel_benchmark)

    def run_benchmark_clicked():
        nonlocal benchmark_cancelled
        benchmark_cancelled=False
        if benchmark_process.state()!=QProcess.NotRunning:
            return
        answer=QMessageBox.question(
            window,"Local AI performance test",
            "Test the Whisper models and translators already installed on "
            "this computer using a six-second excerpt from a local audio/"
            "video file you choose?\n\n"
            "This can use CPU/GPU heavily for several minutes. It will not "
            "touch DVB tuning, download models, upload media or change any "
            "settings. Results require your explicit approval.",
            QMessageBox.Yes | QMessageBox.No,QMessageBox.No)
        if answer!=QMessageBox.Yes:
            return
        chosen=QFileDialog.getOpenFileName(
            window,"Select local recording for AI timing",
            str(Path.home()),
            "Audio/video (*.wav *.flac *.mp3 *.m4a *.mp4 *.mkv *.ts *.ogg);;"
            "All files (*)")[0]
        if not chosen:
            return
        benchmark_button.setEnabled(False)
        cancel_benchmark_button.setEnabled(True)
        try:
            requested=from_controls()
            # With Spoken=Auto, benchmark all four primary languages in
            # both directions actually requested. Do not hardwire DE→EN/TR.
            sources=(("de","en","tr","fr") if requested.spoken_auto else
                     (requested.source,))
            targets=requested.target_languages or ("en",)
            from tv_center.performance_lab import translation_pairs
            selected_pairs,omitted=translation_pairs(sources,targets)
        except ValueError as exc:
            QMessageBox.warning(window,"Benchmark languages",str(exc))
            benchmark_button.setEnabled(True)
            cancel_benchmark_button.setEnabled(False)
            return
        benchmark_status.setText(
            "Testing selected translation directions: "+
            ", ".join(a.upper()+"→"+b.upper() for a,b in selected_pairs)+
            (" · additional pairs omitted by 12-pair benchmark limit"
             if omitted else "")+
            ". Main DVB player remains independent.")
        benchmark_process.start(
            sys.executable,["-m","tv_center.performance_lab","--audio",chosen,
                           "--buffer-ms",str(applied.playback_delay_ms),
                           "--sources",",".join(sources),
                           "--targets",",".join(targets)])
        if not benchmark_process.waitForStarted(700):
            benchmark_status.setText(
                "Could not start the local benchmark process.")
            benchmark_button.setEnabled(True)
            cancel_benchmark_button.setEnabled(False)

    def benchmark_finished(*_):
        benchmark_button.setEnabled(True)
        cancel_benchmark_button.setEnabled(False)
        if benchmark_cancelled:
            benchmark_status.setText(
                "AI test canceled. Original model, translator and buffer settings kept.")
            return
        raw=bytes(benchmark_process.readAllStandardOutput()).decode(
            "utf-8","replace")
        if benchmark_process.exitCode()!=0 or len(raw)>100000:
            error=bytes(benchmark_process.readAllStandardError()).decode(
                "utf-8","replace")[-450:]
            benchmark_status.setText(
                "AI benchmark failed: "+(error or "No verified model result"))
            return
        try:
            report=json.loads(raw)
            if report.get("version")!=1 or not report.get("offline"):
                raise ValueError("Untrusted benchmark result")
            rows=report["samples"]
            proposal=report["recommendation"]
            tested_pairs={
                tuple(item) for item in report.get("tested_directions",[])
                if isinstance(item,list) and len(item)==2}
            skipped_pairs={
                tuple(item) for item in report.get("not_tested_directions",[])
                if isinstance(item,list) and len(item)==2}
        except (ValueError,TypeError,KeyError) as exc:
            benchmark_status.setText(
                "AI benchmark returned no valid performance report: "+str(exc))
            return
        labels=[]
        for row in rows:
            name=(row.get("name") or row.get("engine") or
                  row.get("backend") or "model")
            label=str(name)[:70]
            if row.get("target"):
                label+=(" "+str(row.get("source") or "de").upper()+
                        " → "+str(row["target"]).upper())
            if row.get("status")=="ok":
                label+=f": {float(row['elapsed_s']):.2f}s"
                if row.get("kind")=="asr":
                    label+=" / 6s captured audio"
                    if not row.get("nonempty_text",True):
                        label+=" · NO recognized speech; not recommended"
            else:
                label+=": "+str(row.get("status"))+" · "+str(
                    row.get("reason",""))[:130]
            labels.append(label)
        benchmark_status.setText(
            "Local test completed. No options were changed. Review "
            "per-model results and edit before applying.")
        dialogue=QDialog(window)
        window.ai_benchmark_dialog=dialogue
        dialogue.setWindowTitle("Offline AI performance · review before applying")
        dialogue.setWindowModality(Qt.NonModal)
        dialogue.resize(660,490)
        pane=QVBoxLayout(dialogue)
        intro=QLabel(
            "Real local 6-second-file test; not a guarantee for continuous "
            "DVB throughput. Old settings remain unchanged until Apply.")
        intro.setWordWrap(True)
        pane.addWidget(intro)
        results=QPlainTextEdit()
        results.setReadOnly(True)
        results.setPlainText("\n".join(labels) or
            "No compatible installed AI models detected.")
        pane.addWidget(results)
        choice=QComboBox()
        eligible=[m for m in rows if m.get("kind")=="asr" and
                  m.get("status")=="ok" and m.get("nonempty_text",True)]
        for m in eligible:
            choice.addItem(
                m["backend"].upper()+" · "+Path(m["model_path"]).name+
                f" · {m['elapsed_s']:.2f}s",
                (m["backend"],m["model_path"]))
        choice.setEnabled(bool(eligible))
        pane.addWidget(QLabel("Whisper engine and model (editable):"))
        pane.addWidget(choice)
        translator=QComboBox()
        translator.addItem("Keep current translator",None)
        for eng in ("argos","nllb"):
            measured={(m.get("source","de"),m.get("target")):m
                      for m in rows if m.get("kind")=="translation" and
                      m.get("engine")==eng and m.get("status")=="ok"}
            if tested_pairs and not skipped_pairs and tested_pairs<=set(measured):
                elapsed=sum(float(measured[p]["elapsed_s"]) for p in tested_pairs)
                translator.addItem(
                    eng.upper()+f" · {len(tested_pairs)} tested language routes · "+
                    f"{elapsed:.2f}s total",eng)
        proposed_engine=proposal.get("translation_model")
        if proposed_engine:
            for i in range(translator.count()):
                if translator.itemData(i)==proposed_engine:
                    translator.setCurrentIndex(i)
        pane.addWidget(QLabel(
            "Translation engine (only ALL selected directions verified):"+
            (" · "+", ".join(a.upper()+"→"+b.upper()
                              for a,b in sorted(tested_pairs))
             if tested_pairs else " · no direction tested")+
            (" · "+str(len(skipped_pairs))+" untested (not recommended)"
             if skipped_pairs else "")))
        pane.addWidget(translator)
        suggested_buffer=QDoubleSpinBox()
        suggested_buffer.setRange(0,60)
        suggested_buffer.setSingleStep(.5)
        suggested_buffer.setSuffix(" seconds")
        suggested_buffer.setValue(min(60,max(
            applied.playback_delay_ms,
            int(proposal.get("minimum_buffer_ms",0)))/1000))
        pane.addWidget(QLabel(
            "TV playback buffer · editable; never reduced automatically:"))
        pane.addWidget(suggested_buffer)
        detail=QLabel(
            "Estimated sustainable per 6s clip: "+(
                "YES" if proposal.get("realtime_sustainable") else
                "NOT PROVEN")+" · benchmark excludes DVB packet loss, "
            "speech-language detection errors and 2+ concurrent workloads. "
            "Only the selected backend/model/translator and explicitly edited "
            "buffer will be changed. Output languages stay as chosen above.")
        detail.setWordWrap(True)
        pane.addWidget(detail)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok |
                                 QDialogButtonBox.Cancel,dialogue)
        buttons.button(QDialogButtonBox.Ok).setText(
            "Apply these settings (user approved)")
        pane.addWidget(buttons)
        buttons.rejected.connect(dialogue.reject)
        def apply_benchmark_choice():
            nonlocal applied,current_text,current_cue,current_until
            from tv_center.ai_settings import AISettings
            update={}
            if choice.currentIndex()>=0 and eligible:
                backend,path=choice.currentData()
                update["backend"]=backend
                # CPU uses GGML file. A managed CUDA directory is selected
                # internally by the ready GPU runtime; never write its CT2
                # folder into the GGML model_path setting.
                if backend=="cpu":
                    update["model_path"]=path
            if translator.currentData() in ("argos","nllb"):
                update["translation_model"]=translator.currentData()
            try:
                if update:
                    AISettings().update(update)
                # Native playback delay is changed ONLY as part of this
                # explicit user-approved plan, not by background tests.
                desired_ms=round(suggested_buffer.value()*1000)
                if desired_ms!=applied.playback_delay_ms:
                    playback_delay.setValue(desired_ms/1000)
                    apply_settings()
                with lock:
                    applied=__import__("dataclasses").replace(
                        applied,revision=applied.revision+1)
                cues.clear()
                current_cue=None
                current_text=""
                current_until=0
                ipc.publish("",applied)
            except (OSError,RuntimeError,ValueError) as exc:
                QMessageBox.warning(dialogue,"AI configuration failed",
                                    str(exc)[:250])
                return
            benchmark_status.setText(
                "User-approved local AI settings applied. Retesting live "
                "caption timing is still recommended. Nothing downloaded.")
            dialogue.accept()
        buttons.accepted.connect(apply_benchmark_choice)
        dialogue.show()

    benchmark_button.clicked.connect(run_benchmark_clicked)
    benchmark_process.finished.connect(benchmark_finished)

    def reset_settings():
        mode.setCurrentIndex(0)
        source.setCurrentIndex(0); display_mode.setCurrentIndex(1)
        for lang, check in language_boxes.items():
            check.setChecked(lang == "en")
        subtitle_track.setCurrentIndex(0)
        audio_track.setCurrentIndex(0)
        extra_targets.clear()
        page.setValue(150)
        caption_offset.setValue(0.0); playback_delay.setValue(0.0)
        automatic.setChecked(False)
        speaker_enabled.setChecked(True)
        music_transcription.setChecked(False)
        speech_priority.setChecked(False)
        speaker_provider.setCurrentIndex(0)
        speaker_numbers.setChecked(False)
        speaker_lines.setChecked(True)
        voice_types.setChecked(False)
        sound_events.setChecked(False)
        overlap_enabled.setChecked(False)
        manual_names.setChecked(False)
        for entry in speaker_alias_inputs:
            entry.clear()
        show_video.setChecked(True)
        position.setCurrentText("bottom"); font.setValue(25)
        renderer.setCurrentIndex(0)
        presets.setCurrentIndex(0)
        apply_appearance_preset()
        set_pending()
    apply.clicked.connect(apply_settings)
    reset.clicked.connect(reset_settings)

    def set_phone(enabled):
        if enabled:
            try:
                data = mobile.enable_lan(lambda num: events.put(("remote_page",int(num))))
                lan_note.setText("Phone: "+data["url"]+" | Pair: "+data["pin"]+
                                  "\nTrusted Wi-Fi only; HTTP is not encrypted.")
            except (OSError, RuntimeError) as exc:
                phone.blockSignals(True); phone.setChecked(False); phone.blockSignals(False)
                lan_note.setText("LAN sharing unavailable: "+str(exc))
        else:
            mobile.stop_lan()
            video.blockSignals(True); video.setChecked(False); video.blockSignals(False)
            lan_note.setText("Mobile access OFF; phone sessions revoked.")

    def set_video(enabled):
        if enabled:
            try:
                mobile.enable_video()
                lan_note.setText(lan_note.text()+"\nLive HLS enabled for paired phones.")
            except (RuntimeError,OSError,ValueError) as exc:
                video.blockSignals(True); video.setChecked(False); video.blockSignals(False)
                lan_note.setText("Mobile HLS unavailable: "+str(exc))
        else:
            mobile.stop_video()
    phone.toggled.connect(set_phone)
    video.toggled.connect(set_video)
    apply_settings()

    def set_subtitles_running(should_run):
        nonlocal service_running, applied, current_cue, current_text, current_until
        nonlocal last_published
        with lock:
            if service_running == should_run:
                return
            service_running = should_run
            # Reject in-flight decode results from an older session.
            applied = __import__("dataclasses").replace(
                applied, revision=applied.revision + 1)
        cues.clear()
        recent_voice_lines.clear()
        deferred_captions.clear()
        current_cue = None
        current_text = ""
        current_until = 0.0
        mobile.set_caption({"original":"","source":"stopped"})
        estimator.clear()
        auto_controller.reset()
        # Pausing recognition is not the same as leaving a selectable AI
        # caption track active in Kaffeine. Keep the DVB player untouched.
        ipc.publish("", applied if should_run else
                    __import__("dataclasses").replace(applied, mode="off"))
        last_published = time.monotonic()
        if not should_run and srt_recorder.active:
            recorded = srt_recorder.stop()
            srt_status.setText("SRT saved: " + ", ".join(str(p) for p in recorded))
            srt_start.setEnabled(True)
            srt_stop.setEnabled(False)
        start_subtitles.setEnabled(not should_run)
        stop_subtitles.setEnabled(should_run)
        original.setText("Listening for new captions…" if should_run else
                         "Subtitles stopped · click Start to resume.")
        translated.setText("")
        status.setText("Caption worker active." if should_run else
                       "Subtitle recognition paused. No new Whisper clips queued.")

    def refresh_tv_captions():
        """Reset stale *AI* state and re-read configured local models.

        Keep the DVB tap, channel, native audio/video FIFO, offset, and
        existing SRT file untouched. Revision gates discard late ASR jobs.
        """
        nonlocal applied, current_cue, current_text, current_until
        if not service_running:
            status.setText("Enable subtitles first; TV remains playing.")
            return
        try:
            from tv_center.ai_settings import AISettings
            AISettings().configure_environment()
        except (ValueError, RuntimeError, OSError) as exc:
            status.setText("AI settings refresh failed: "+str(exc)[:170])
            return
        with lock:
            applied = __import__("dataclasses").replace(
                applied, revision=applied.revision + 1)
        cues.clear()
        deferred_captions.clear()
        recent_voice_lines.clear()
        tap.work_queue.clear() # no old audio windows after model change
        current_cue = None
        current_text = ""
        current_until = 0.0
        mobile.set_caption({"original":"","source":"caption_refresh"})
        ipc.publish("", applied)
        original.setText("AI Caption Refresh · waiting for NEW TV audio…")
        translated.setText("")
        translation_health.setText(
            "Model settings reloaded; next confirmed ASR/translation shown.")
        status.setText("TV AI refreshed without stopping the receiver or video. "
                       "Pending older ASR results rejected by revision.")

    def refresh_tv_sync():
        """Resample timebase; do not pretend we measured output PTS."""
        nonlocal last_sync_audit_at
        estimator.clear()
        auto_controller.reset()
        last_sync_audit_at = 0.0
        sync_estimate.setText(
            "Lip-sync Refresh · awaiting fresh TV TS/ASR samples. "
            f"Manual subtitle offset {applied.offset_ms:+d} ms preserved. "
            "Video/audio/DAC presentation PTS remains unmeasured.")
        status.setText("TV sync estimates reset. No tuner retune, no buffer "
                       "reopen and no AI transcript dropped.")

    caption_refresh.clicked.connect(refresh_tv_captions)
    sync_refresh.clicked.connect(refresh_tv_sync)

    def begin_srt_recording():
        if not service_running:
            srt_status.setText("Start subtitles before recording an SRT.")
            return
        destination = QFileDialog.getExistingDirectory(
            window, "Choose private SRT subtitle folder",
            str(Path.home() / "Videos" if (Path.home() / "Videos").is_dir()
                else Path.home()))
        if not destination:
            return
        try:
            folder = srt_recorder.start(destination, "live-TV")
        except (OSError, ValueError, RuntimeError) as exc:
            srt_status.setText("Cannot create SRT: " + str(exc))
            return
        srt_status.setText("Recording real timed subtitles to: " + str(folder))
        srt_start.setEnabled(False)
        srt_stop.setEnabled(True)

    def end_srt_recording():
        paths = srt_recorder.stop()
        srt_status.setText("SRT complete · load through Playback → Open Subtitle: " +
                           (", ".join(str(p) for p in paths) if paths
                            else "No spoken captions received"))
        srt_start.setEnabled(True)
        srt_stop.setEnabled(False)

    start_subtitles.clicked.connect(lambda: set_subtitles_running(True))
    stop_subtitles.clicked.connect(lambda: set_subtitles_running(False))
    srt_start.clicked.connect(begin_srt_recording)
    srt_stop.clicked.connect(end_srt_recording)

    def reset_channel_captions(epoch, native_state):
        """Keep UI open but detach *every* selected old-channel PID.

        The only source of tune truth is native Kaffeine (or decoded PAT
        for older installations). A user-selected output language,
        subtitle appearance and buffer preference survive this reset.
        """
        nonlocal applied, current_cue, current_text, current_until
        nonlocal last_published, last_service_id, last_applied_effective_ms
        nonlocal pending_buffer_retime_ms,last_cue_shown_at
        nonlocal live_test_started_at
        last_cue_shown_at=time.monotonic()
        if live_test_started_at:
            live_test_started_at=0
            live_test_button.setEnabled(True)
            benchmark_status.setText(
                "Live performance sampling cancelled: TV channel changed. "
                "Restart the four-clip test on the new channel.")
        # Stop cross-channel sentence/cue contamination before the NEXT
        # audio/Teletext descriptor even arrives.
        with lock:
            applied = __import__("dataclasses").replace(
                applied, teletext_pid=None, audio_pid=None, audio_language=None,
                # A manually selected Teletext page belongs to the old
                # service. Do not continue decoding it after a TV tune.
                mode="auto" if applied.mode == "page" else applied.mode,
                revision=applied.revision+1)
        cues.clear()
        deferred_captions.clear()
        estimator.clear()
        auto_controller.reset()
        current_cue = None
        current_text = ""
        current_until = 0.0
        last_published = time.monotonic()
        last_service_id = None
        last_applied_effective_ms = None
        pending_buffer_retime_ms = None
        native_release_clock.clear()
        recent_voice_lines.clear()
        subtitle_track.blockSignals(True)
        subtitle_track.clear()
        subtitle_track.addItem(
            "Automatic broadcaster subtitles (new TV service)", None)
        subtitle_track.blockSignals(False)
        audio_track.blockSignals(True)
        audio_track.clear()
        audio_track.addItem(
            "Automatic · select audio from new TV service", None)
        audio_track.blockSignals(False)
        if mode.currentData() == "page":
            # An explicitly chosen old service's Teletext page must not
            # silently become a real caption channel in the next service.
            mode.setCurrentIndex(0)
        track_status.setText("Switched service · waiting for fresh Teletext descriptors.")
        teletext_speech_status.setText(
            "TELETEXT · CHECKING · new programme; previous subtitles invalidated")
        audio_track_status.setText("Switched service · waiting for new audio PID/language.")
        original.setText("TV channel changed · waiting for NEW channel captions…")
        translated.setText("")
        translation_health.setText("Translation will resume after new source confirmation.")
        native_channel_status.setText(
            ("Kaffeine TV: SID %s · TSID %s · tune %s · waiting for TS/ASR"
             % (native_state[1], native_state[2], native_state[0]))
            if native_state is not None and native_state[1] else
            "Kaffeine TV: stopped or retuning · old subtitles cleared")
        sync_estimate.setText("Channel changed · clearing timing measurements.")
        ipc.publish("",applied if service_running else
                    __import__("dataclasses").replace(applied,mode="off"))
        # A live SRT file cannot silently stitch two unrelated TV shows.
        if srt_recorder.active:
            files = srt_recorder.stop()
            srt_status.setText("TV channel changed; saved previous SRT: " +
                               ", ".join(str(p) for p in files))
            srt_start.setEnabled(True)
            srt_stop.setEnabled(False)
        pending.setText("New TV service detected · automatic PID reset")
        status.setText("New Kaffeine TV tune observed: stale ASR/Teletext "
                       "cue queue discarded; retuning does NOT stop subtitles.")

    def pump():
        nonlocal current_cue, current_text, current_until, last_published
        nonlocal applied, last_service_id, last_effective_check
        nonlocal last_applied_effective_ms, last_sync_audit_at
        nonlocal last_ui_program_epoch,live_test_started_at
        nonlocal pending_buffer_retime_ms
        nonlocal last_cue_shown_at,last_pipeline_health_at
        try:
            state,message=overlap_install_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            overlap_install_button.setEnabled(True)
            overlap_status.setText(
                ("SepFormer installed · " if state=="ok" else
                 "SepFormer setup failed · ")+message)
        try:
            kind,state,message=classifier_install_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            if kind=="sound": event_install_button.setEnabled(True)
            elif kind=="voice": voice_install_button.setEnabled(True)
            classifier_status.setText(
                (kind+" installed · " if state=="ok" else
                 kind+" install failed · ")+str(message)[:200])
        # Kaffeine is the DVB owner. Terminate sidecar when it disappears,
        # including when the settings window has been hidden.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            window.terminating = True
            app.quit()
            return
        except PermissionError:
            pass
        mobile.expire_if_idle()
        now = time.monotonic()
        if live_test_started_at and (now-live_test_started_at>=0.5):
            state=tap.performance_snapshot()
            observed=state["completed_clips"]-live_test_baseline
            if observed>=4 or now-live_test_started_at>=75:
                from tv_center.performance_lab import diagnose_live
                report=diagnose_live(
                    state["samples"][-min(observed,16):] if observed>0 else [],
                    queue_overflows=max(0,state["queue"]["overflows"]-
                                        live_test_baseline_overflows),
                    ts_audio_gaps=max(0,state["ts"].get("continuity_gaps",0)-
                                     live_test_baseline_ts_gaps))
                live_test_started_at=0.0
                live_test_button.setEnabled(True)
                if report["samples"]:
                    benchmark_status.setText(
                        "Measured "+str(report["samples"])+" live caption clips"
                        " · median compute "+str(report["median_compute_ms"])+"ms"
                        " · queue wait "+str(report["median_queue_wait_ms"])+"ms"
                        " · compute realtime factor "+
                        str(report["median_compute_realtime_factor"])+"x"
                        " · reasons: "+(", ".join(report["causes"]) or
                                       "no clear overload")+
                        ". "+("; ".join(report["recommendations"])))
                else:
                    benchmark_status.setText(
                        "No completed live caption clips during the test. "
                        "Check TV channel, DVB TS capture, audio PID, "
                        "Whisper settings and backend readiness.")
            elif state["completed_clips"]>live_test_baseline:
                benchmark_status.setText(
                    "Live performance: "+str(observed)+
                    "/4 freshly decoded clips observed. No settings changed.")
        # The native channel epoch is published at tune time, even when
        # no MPEG-TS bytes flow yet. Handle it BEFORE queued caption events.
        if tap.program_epoch != last_ui_program_epoch:
            last_ui_program_epoch = tap.program_epoch
            reset_channel_captions(last_ui_program_epoch,tap.native_tune_state)
        if now - last_effective_check >= 1.0:
            last_effective_check = now
            effective = native_release_clock.stabilized(
                ipc.read_effective_delay())
            progress = buffer_fill_progress(effective, applied.playback_delay_ms)
            percent = progress["percent"]
            if percent is None:
                buffer_progress.setRange(0, 0)
                buffer_progress.setFormat("Waiting for native buffer measurements")
            else:
                buffer_progress.setRange(0, 100)
                buffer_progress.setValue(percent)
                queued_ms = progress["queued_ms"]
                effective_ms = progress["effective_ms"]
                requested_ms = progress["requested_ms"]
                state = progress["state"]
                if state == "live":
                    buffer_progress.setFormat("Live TV · buffer disabled")
                elif state == "unavailable":
                    buffer_progress.setFormat("Buffer unavailable · 0%")
                else:
                    buffer_progress.setFormat(
                        f"{queued_ms/1000:.1f} / {effective_ms/1000:.1f} s "
                        f"({percent}%) · " + ("Ready" if state == "ready"
                                            else "Filling"))
                    if effective_ms < requested_ms:
                        buffer_progress.setToolTip(
                            f"Requested {requested_ms/1000:.1f} s; "
                            f"receiver memory / timeshift capped the "
                            f"effective delay at {effective_ms/1000:.1f} s.")
            if effective is None:
                pinned_progress.setText("TV buffer: waiting for native receiver telemetry")
                effective_status.setText(
                    "Native TV delay: Kaffeine has not reported its active MPEG-TS "
                    "buffer yet; requested value is not confirmed.")
            else:
                actual = effective["effective_ms"] / 1000
                requested = effective["requested_ms"] / 1000
                rate = effective["ts_bytes_per_second"] / 1024 / 1024
                if percent is None:
                    pinned_progress.setText("TV buffer: measurements unavailable or resetting")
                elif progress["state"] == "live":
                    pinned_progress.setText("TV buffer: OFF · live playback")
                else:
                    pinned_progress.setText(
                        "TV buffer: " + buffer_progress.format())
                confirmed = (
                    effective["requested_ms"] == applied.playback_delay_ms
                    and bool(effective["primed"]))
                if confirmed:
                    current_actual = effective["effective_ms"]
                    old_clock = (
                        pending_buffer_retime_ms if
                        pending_buffer_retime_ms is not None else
                        last_applied_effective_ms)
                    if old_clock is not None and current_actual!=old_clock:
                        # Preserve decoded text and shift its pending due
                        # dates to the NEW acknowledged FIFO time instead
                        # of deleting subtitles on every bitrate adjustment.
                        cues.retime(current_actual-old_clock,applied)
                        status.setText(
                            "Native buffer changed · retained queued captions "
                            "and re-timed "+str(current_actual-old_clock)+" ms.")
                    pending_buffer_retime_ms = None
                    last_applied_effective_ms = current_actual
                else:
                    last_applied_effective_ms = None
                if now-last_sync_audit_at >= 25 and confirmed:
                    last_sync_audit_at = now
                    sync_estimate.setToolTip(
                        f"Periodic Kaffeine buffer audit: {actual:.1f}s actual, "
                        f"{requested:.1f}s requested. ASR/translation "
                        "samples are continuously measured; this is not "
                        "sample-accurate lip synchronization.")
                queue_age = effective.get("queue_age_ms",0) / 1000
                effective_status.setText(
                    (f"Filling TV playback buffer: {queue_age:.1f}s "
                     f"of {actual:.1f}s TS queued · subtitles held safely."
                     if not effective["primed"] and actual > 0
                     else
                     f"Native TV delay: {actual:.1f}s primed / "
                     f"{requested:.1f}s requested · TS {rate:.2f} MiB/s" +
                     (" · Waiting for new buffer acknowledgement."
                      if not confirmed else
                      " · Memory/timeshift limit; rechecking."
                      if effective["capped"] else
                      " · Primed and periodically rechecked.")))
        # Never reuse an ASR processing estimate across distinct TV services.
        if mobile.service_id != last_service_id:
            if last_service_id is not None:
                estimator.clear()
                auto_controller.reset()
                mobile.set_caption({"original":"","source":"channel_changed"})
                sync_estimate.setText("Channel changed · recalibrating automatic sync.")
            last_service_id = mobile.service_id
        # Never lose decoded speech merely because the native video buffer
        # needs another acknowledgement. Replay older held results before
        # newer events as soon as the relevant buffer is verified.
        buffer_ready = confirmed_cue_config(
            applied,native_release_clock.stabilized(
                ipc.read_effective_delay())) is not None
        for _ in range(8):
            if buffer_ready and deferred_captions:
                kind, data = "caption", deferred_captions.popleft()
            else:
                try:
                    kind, data = events.get_nowait()
                except queue.Empty:
                    break
            if kind == "native_tv_tune":
                # A previous queued event must never reset a newer tune.
                if data.get("program_epoch") == tap.program_epoch:
                    if data["service_id"]:
                        native_channel_status.setText(
                            "Kaffeine TV: new SID %s / TSID %s · tune %s" % (
                                data["service_id"], data["transport_stream_id"],
                                data["owner_epoch"]))
                    else:
                        native_channel_status.setText(
                            "Kaffeine TV stopped/retuning · old caption source cleared")
            elif kind == "show_settings":
                window.showNormal()
                window.raise_()
                window.activateWindow()
            elif kind == "remote_gui_command":
                # HTTP worker cannot touch QWidgets. Apply only validated
                # allowlisted controls on the existing Qt GUI event loop.
                action = data.get("action")
                params = data.get("params") or {}
                if action == "desktop_subtitles_running":
                    set_subtitles_running(params["running"])
                elif action == "set_desktop_caption_mode":
                    index = mode.findData(params["mode"])
                    if index >= 0:
                        mode.setCurrentIndex(index)
                        apply_settings()
                elif action == "set_desktop_caption_offset":
                    caption_offset.setValue(params["offset_ms"]/1000)
                    apply_settings()
                elif action == "set_desktop_tv_buffer":
                    playback_delay.setValue(params["buffer_ms"]/1000)
                    apply_settings()
                status.setText(
                    "Paired phone requested desktop caption control: " +
                    str(action) + ". Native status will confirm the effect.")
            elif kind == "teletext_tracks":
                if data.get("program_epoch") != tap.program_epoch:
                    continue
                selected = subtitle_track.currentData()
                previous_identity = ((selected.get("pid"),selected.get("page"),
                                      selected.get("language"))
                                     if isinstance(selected,dict) else None)
                subtitle_track.blockSignals(True)
                subtitle_track.clear()
                subtitle_track.addItem(
                    "Automatic broadcaster subtitles (no selected page)", None)
                current = 0
                for desc in data.get("tracks", ()):
                    if not isinstance(desc,dict):
                        continue
                    item = dict(desc)
                    subtitle_track.addItem(item["label"], item)
                    if (item["pid"],item["page"],item["language"]) == previous_identity:
                        current = subtitle_track.count()-1
                new_subtitle_track = None
                if current == 0 and mode.currentData() in ("auto","teletext"):
                    new_subtitle_track = recommended_track(
                        [subtitle_track.itemData(i)
                         for i in range(1,subtitle_track.count())],
                        source.currentText(), kind="teletext")
                    if new_subtitle_track is not None:
                        for i in range(1,subtitle_track.count()):
                            item = subtitle_track.itemData(i)
                            if (isinstance(item,dict) and
                                    item.get("pid")==new_subtitle_track.get("pid") and
                                    item.get("page")==new_subtitle_track.get("page")):
                                current=i
                                break
                subtitle_track.setCurrentIndex(current)
                subtitle_track.blockSignals(False)
                old_audio = audio_track.currentData()
                previous_audio_pid = (
                    old_audio.get("pid") if isinstance(old_audio, dict) else None)
                audio_track.blockSignals(True)
                audio_track.clear()
                audio_track.addItem(
                    "Automatic · prefer spoken language / regular audio", None)
                selected_audio_index = 0
                for desc in data.get("audio_tracks", ()):
                    if not isinstance(desc, dict):
                        continue
                    item = dict(desc)
                    audio_track.addItem(item["label"], item)
                    if item.get("pid") == previous_audio_pid:
                        selected_audio_index = audio_track.count()-1
                new_audio_track = None
                if selected_audio_index == 0 and mode.currentData() in ("auto","asr"):
                    new_audio_track = recommended_track(
                        [audio_track.itemData(i)
                         for i in range(1,audio_track.count())],
                        source.currentText(), kind="audio")
                    if new_audio_track is not None:
                        for i in range(1,audio_track.count()):
                            item = audio_track.itemData(i)
                            if isinstance(item,dict) and item.get("pid") == new_audio_track.get("pid"):
                                selected_audio_index=i
                                break
                audio_track.setCurrentIndex(selected_audio_index)
                audio_track.blockSignals(False)
                audio_count = audio_track.count()-1
                audio_track_status.setText(
                    f"{audio_count} broadcast-signalled audio channel(s). " +
                    ("Automatically matched signalled audio language/PID."
                     if new_audio_track else
                     "Choose a PID for Whisper if automatic selection is ambiguous.")
                    )
                if previous_audio_pid is not None and selected_audio_index == 0:
                    with lock:
                        applied = __import__("dataclasses").replace(
                            applied, audio_pid=None, revision=applied.revision+1)
                    cues.clear()
                    set_pending()
                count = subtitle_track.count()-1
                track_status.setText(
                    (f"{count} broadcast-signalled Teletext subtitle "
                     f"channel(s) detected. Choose one, then Apply."
                     if count else
                     "No Teletext subtitle descriptor detected on this service. "
                     "You can still use Whisper or manual page mode."))
                if ((new_subtitle_track is not None or new_audio_track is not None)
                        and last_service_id == mobile.service_id):
                    # One uniquely signalled DVB track can be auto-applied.
                    # This updates both the UI source-language label and
                    # actual decoder options; never silently show EN as DE.
                    chosen = (new_subtitle_track
                              if mode.currentData() in ("auto","teletext")
                              and new_subtitle_track is not None
                              else new_audio_track)
                    lang = _signaled_language(chosen)
                    # A broadcast hint is a property of THIS TV channel.
                    # Do not replace a user's Auto source with a hardcoded
                    # language or silently override an explicit manual choice.
                    # from_controls() uses fresh DVB descriptors per tune.
                    apply_settings()
                    if chosen is new_audio:
                        audio_track_status.setText(
                            "Broadcast audio " + (lang.upper() if lang else "unknown") +
                            " · PID " + str(new_audio["pid"]) +
                            " automatically selected. Whisper uses this "
                            "signalled language instead of guessing "
                            "from six seconds of live television audio.")
                    else:
                        track_status.setText(
                            "Automatically selected broadcaster subtitle language " +
                            (lang.upper() if lang else "") +
                            "; original source and requested output languages "
                            "stay synchronized.")
                if previous_identity is not None and current == 0:
                    # On a channel change, never reuse stale PID/page settings.
                    # Revert the applied subtitle selection immediately to
                    # neutral while preserving other active user settings.
                    with lock:
                        applied = __import__("dataclasses").replace(
                            applied, teletext_pid=None, revision=applied.revision+1)
                    cues.clear()
                    set_pending()
            elif kind == "remote_page":
                subtitle_track.setCurrentIndex(0)
                mode.setCurrentIndex(3)
                page.setValue(int(data))
                apply_settings()
            elif kind == "caption":
                if (data.get("revision") != applied.revision or
                        data.get("program_epoch") != tap.program_epoch):
                    continue
                if data.get("teletext_source_transition") in (
                        "whisper","teletext"):
                    # Drop OLD Teletext cues in this same channel once
                    # audio has disproved them; don't show them while new
                    # Whisper and translations are being assembled.
                    cues.clear()
                    deferred_captions.clear()
                    recent_voice_lines.clear()
                    current_cue=None
                    current_text=""
                    current_until=0.0
                    ipc.publish("",applied)
                    original.setText(
                        ("WHISPER · AUTO FALLBACK · real spoken audio replacing "
                         "mismatched Teletext…")
                        if data.get("teletext_source_transition")=="whisper" else
                        "TELETEXT · SYNCED · broadcaster subtitles verified again…")
                    translated.clear()
                if data.get("teletext_sync_recheck"):
                    estimator.clear()
                    auto_controller.reset()
                    sync_estimate.setText(
                        "Teletext appears shifted relative to adjacent "
                        "verified speech. Re-sampling native TS buffer and "
                        "ASR timing before changing source. No trusted "
                        "libVLC/DAC PTS; no forced subtitle time jump.")
                if data.get("teletext_status"):
                    teletext_speech_status.setText(
                        str(data["teletext_status"])+
                        (" · "+str(data["teletext_detail"])[:190]
                         if data.get("teletext_detail") else ""))
                if data.get("original"):
                    real_source = data.get("source", "")
                    estimator.observe(
                        data["captured_start"], data["captured_end"],
                        data["decoded_at"], real_source)
                    recommendation = estimator.recommend(
                        bytes_per_second=tap.bytes_per_second)
                    if recommendation:
                        safe_existing = (
                            applied.automatic_sync and
                            applied.playback_delay_ms >= recommendation.suggested_delay_ms)
                        sync_estimate.setText(
                            recommendation.summary +
                            (" · AUTO HOLD: current TV buffer "+
                             f"{applied.playback_delay_ms/1000:.1f}s already exceeds "+
                             "the required minimum; not reducing it."
                             if safe_existing else
                             " · AUTO INCREASE-ONLY" if applied.automatic_sync else
                             " · automatic OFF; manual playback unchanged") +
                            " · This is a chunk-based estimate, not exact word alignment.")
                        active_auto = applied.automatic_sync and applied.mode in ("asr","auto")
                        desired = auto_controller.next_delay(
                            recommendation, applied.playback_delay_ms, now, active_auto)
                        if desired is not None:
                            revised = __import__("dataclasses").replace(
                                applied, playback_delay_ms=desired)
                            try:
                                ipc.set_playback_delay(revised)
                            except OSError as error:
                                status.setText("Automatic playback adjustment failed: " + str(error))
                            else:
                                with lock:
                                    applied = revised
                                # New native buffer ACK is pending. Keep
                                # already decoded subtitles and defer fresh
                                # words; otherwise automatic 500ms increases
                                # can erase whole scenes of dialogue.
                                pending_buffer_retime_ms = (
                                    last_applied_effective_ms if
                                    last_applied_effective_ms is not None else
                                    applied.playback_delay_ms)
                                native_release_clock.clear()
                                last_applied_effective_ms = None
                                buffer_ready = False
                                # The text field mirrors the *active* delay,
                                # not an uncommitted manual change.
                                playback_delay.blockSignals(True)
                                playback_delay.setValue(desired / 1000)
                                playback_delay.blockSignals(False)
                                pending.setText("Auto sync active · TV buffer " +
                                                f"{desired/1000:.1f} s")
                    else:
                        sync_estimate.setText(
                            f"Automatic timing: {len(estimator.values)}/3 real Whisper "
                            "samples. No recommendation yet; playback unchanged.")
                    # The native 64-MiB MPEG-TS FIFO may apply less delay
                    # than the UI requested. Schedule text against the
                    # confirmed playback delay when its status matches the
                    # current request; never reuse a stale channel setting.
                    native_state = native_release_clock.stabilized(
                        ipc.read_effective_delay())
                    cue_config = confirmed_cue_config(applied, native_state)
                    if cue_config is None:
                        if len(deferred_captions)>=deferred_captions.maxlen:
                            # No data recovery is possible past this bound;
                            # expose loss instead of falsely saying 'silence'.
                            status.setText(
                                "Native TV buffer ACK missing; deferred-caption "
                                "queue overflow. Real spoken phrases may be lost.")
                        deferred_captions.append(data)
                        status.setText(
                            "Waiting for real TV buffer confirmation · "+
                            str(len(deferred_captions))+
                            " decoded phrases held, NOT dropped. "
                            "If this persists, inspect the native buffer and "
                            "TV channel state; increasing delay alone cannot "
                            "recover broken data.")
                        continue
                    cue = (None if (
                        applied.separate_overlapping_voices and
                        len(data.get("overlap_lines") or [])==2)
                        else enqueue_word_cues(
                        cues, data, cue_config,
                        data["captured_start"],data["captured_end"],
                        data["decoded_at"]))
                    if cue is None:
                        cue = cues.add(data, cue_config,
                                       data["captured_start"],data["captured_end"],
                                       data["decoded_at"])
                    if not cue.get("skipped_duplicate"):
                        # Phone HLS takes the PRE-buffer native MPEG-TS stream.
                        # Publish cue capture/due/host-delay metadata now,
                        # rather than waiting for the desktop subtitle to
                        # become visible after the host TV buffer.
                        mobile.set_caption(data, cue, cue_config, native_state)
                    delay_verified = (
                        native_state is not None and
                        native_state.get("requested_ms") == applied.playback_delay_ms)
                    actual_backend = data.get("asr_backend")
                    backend_info = (
                        " | Whisper: "+actual_backend.upper() +
                        " · "+str(data.get("asr_model") or "unknown model") +
                        (" ("+str(data["asr_engine"])+")" if data.get("asr_engine") else "")
                        if actual_backend else "")
                    status.setText("Real "+data.get("source","unknown")+backend_info+
                        " | ASR+translate latency: "+
                        f"{int((data['decoded_at']-data['captured_end'])*1000)}ms" +
                        " | Caption lateness vs "+(
                            "applied TV delay: " if delay_verified else
                            "requested TV delay (unconfirmed): ") +
                        str(cue["lateness_ms"])+"ms" +
                        " | DVB TS packets: "+str(tap.packet_count) +
                        " | Backlog: "+str(tap.work_queue.snapshot()["queued_clips"]) +
                        " clips ("+str(tap.work_queue.snapshot()["queued_mib"])+" MiB)")
                    timing = data.get("processing_ms") or {}
                    if timing:
                        status.setText(status.text() +
                            " | Stages: TT "+str(timing.get("teletext",0))+"ms"+
                            " / ASR "+str(timing.get("asr",0))+"ms"+
                            " / translation "+str(timing.get("translation",0))+"ms")
                    used_engines=data.get("translation_engines") or {}
                    if used_engines:
                        status.setText(status.text()+" | Translator actual: "+
                            " / ".join(str(k).upper()+" "+
                                     str(v)[:65] for k,v in
                                     sorted(used_engines.items())))
                    by_language=data.get("translation_languages_ms") or {}
                    if by_language:
                        status.setText(status.text()+" | Per target: "+
                            " + ".join(str(lang).upper()+" "+
                                str(milliseconds)+"ms" for lang,milliseconds
                                in sorted(by_language.items())))
                    ts_health = tap.transport_health.snapshot()
                    status.setText(status.text()+
                        " | TS continuity gaps: "+str(ts_health["continuity_gaps"])+
                        " (RF or nonblocking sidecar loss; not distinguished)")
                    segment_health = data.get("ts_integrity") or {}
                    if segment_health:
                        status.setText(status.text() +
                            " | TS duplicates filtered: " +
                            str(segment_health.get("duplicates",0)) +
                            " · audio PID gaps: " +
                            str(segment_health.get("critical_gaps",0)))
                    if data.get("timing_note"):
                        status.setText(status.text() + " | " +
                                       str(data["timing_note"]))
                    elif data.get("word_timing_source"):
                        status.setText(status.text() +
                            " | Speech-follow: real GPU word timestamps; "
                            "non-overlapping translated phrases are estimates")
                    if data.get("npu_notice"):
                        status.setText(
                            status.text()+" | "+str(data["npu_notice"])[:170])
                    if data.get("npu_error"):
                        status.setText(
                            status.text()+" | Hailo-10H ASR failed: "+
                            str(data["npu_error"])[:140]+
                            " · using "+str(data.get("npu_fallback") or "no fallback"))
                    if data.get("remote_error"):
                        status.setText(
                            status.text()+" | Remote GPU unavailable: "+
                            str(data["remote_error"])[:140]+
                            " · fallback: "+
                            str(data.get("remote_fallback") or "disabled"))
                    if data.get("teletext_audit"):
                        status.setText(
                            status.text()+" | "+str(data["teletext_audit"])[:200])
                    if data.get("sound_event_note"):
                        status.setText(status.text() + " | Sound model: " +
                            str(data["sound_event_note"])[:140])
                    if data.get("asr_test_page_artifact_removed"):
                        status.setText(status.text() +
                            " | TESTSEITE letter-spaced artifact removed "
                            "before translation; speech retained")
                    if data.get("voice_type_note"):
                        status.setText(status.text() + " | Voice type: " +
                            str(data["voice_type_note"])[:140])
                    if data.get("overlap_note"):
                        status.setText(status.text() +
                            " | Dual voices: "+str(data["overlap_note"])[:180])
                    if data.get("speaker_error"):
                        status.setText(status.text() +
                            " | Diarization unavailable: " +
                            str(data["speaker_error"]))
                    elif data.get("speaker_turns"):
                        aligned = (data.get("caption_alignment") ==
                                   "Source audio word timestamps")
                        speaker_health.setText(
                            "Voice clusters detected · " +
                            str(data.get("speaker_engine") or "offline") +
                            (" · words split by provisional speaker turns; "
                             "unknown/ambiguous turns remain unlabelled"
                             if aligned else
                             " · NO usable source-word times: cannot "
                             "attribute whole joined sentences to individuals"))
                        status.setText(status.text() +
                            " | Offline speakers: " +
                            ("provisional word/voice alignment" if aligned else
                             "unassigned voice turns; use timed CUDA ASR"))
                    if data.get("audio_notice"):
                        status.setText(status.text() + "\n" + data["audio_notice"])
                    if data.get("speech_priority_note"):
                        status.setText(status.text() + "\nSpeech priority: " +
                                       str(data["speech_priority_note"]))
                    if sound_events.isChecked():
                        if data.get("sound_labels_source"):
                            status.setText(status.text() + " | Sound tags: " +
                                str(data["sound_labels_source"]) +
                                " (speech transcription kept)")
                        elif data.get("sound_event_note"):
                            status.setText(status.text() +
                                " | Sound labels unavailable: " +
                                str(data["sound_event_note"])[:130] +
                                " · spoken subtitles unaffected")
                    failures = data.get("translation_errors") or {}
                    backup = data.get("translation_warnings") or {}
                    actual_engines = data.get("translation_engines") or {}
                    if actual_engines:
                        translation_health.setText(
                            "Live translation: " +
                            " · ".join(lang.upper()+" → "+
                                str(engine).replace("-", " ")
                                for lang, engine in actual_engines.items()))
                    elif failures:
                        translation_health.setText(
                            "Requested translation unavailable: " +
                            ", ".join(sorted(failures)).upper() +
                            " · showing original " +
                            str(data.get("source_language") or applied.source).upper())
                    if backup:
                        status.setText(status.text() +
                            " | Translator: Argos fallback (" +
                            ", ".join(sorted(backup)).upper() + ")")
                    elif failures:
                        status.setText(status.text() +
                            " | Translation unavailable (" +
                            ", ".join(sorted(failures)).upper() +
                            ") · original speech retained")
                    if data.get("error"):
                        status.setText(status.text()+"\n"+data["error"])
                elif data.get("error"):
                    status.setText("Caption/translator: "+data["error"])
                elif data.get("recognition_rejected"):
                    status.setText(
                        "Whisper suppressed an uncertain TV audio result ("
                        + str(data["recognition_rejected"]) +
                        "). No subtitle was fabricated. "
                        "Use broadcast Teletext when available.")
            elif kind == "sentence_pending":
                if (data.get("program_epoch")==tap.program_epoch and
                        data.get("revision")==applied.revision):
                    status.setText(
                        "Whisper recognized an incomplete sentence · "+
                        str(data.get("chunks",0))+"/"+str(
                            data.get("maximum_chunks",2))+
                        " audio chunks held for natural phrasing. "
                        "Original speech is pending, not confirmed lost.")
                    original.setText(
                        "Building a sentence from real Whisper audio…")
            elif kind == "warning":
                status.setText(str(data))
        cue = (cues.poll(now, applied.revision)
               if service_running and buffer_ready else None)
        if cue:
            current_cue = cue
            last_cue_shown_at=now
            result = cue["result"]
            if srt_recorder.active:
                try:
                    srt_recorder.append(cue, applied)
                    srt_status.setText("SRT recording · " +
                                       ", ".join(str(p) for p in srt_recorder.paths))
                except (OSError, ValueError) as error:
                    end_srt_recording()
                    srt_status.setText("SRT save error: " + str(error))
            current_text = recent_voice_lines.compose(
                result,applied.render(result),applied,now,tap.program_epoch)
            current_until = cue["expires"]
            source_language = str(result.get("source_language") or applied.source).upper()
            label_prefix = ""
            if applied.speaker_enabled and result.get("speaker_index"):
                n=result["speaker_index"]
                if type(n) is int and 1<=n<=len(applied.speaker_aliases):
                    alias=applied.speaker_aliases[n-1].strip()
                    if alias:
                        label_prefix=f"[{alias}] "
                if not label_prefix:
                    label_prefix=str(result.get("speaker_label") or "").strip()+" "
            original.setText(label_prefix+"ORIGINAL [" + source_language +
                             "]: " + result.get("original", ""))
            # Sound classes are visual-only and independent of translation.
            event_language=(applied.target_languages[0]
                            if applied.show_translation and
                            applied.target_languages else
                            result.get("source_language") or applied.source)
            acoustic=(applied._event_lines(result,event_language)
                      if applied.show_sound_events else [])
            sound_line.setText(" ".join(dict.fromkeys(acoustic)))
            sound_line.setVisible(bool(acoustic))
            translations = result.get("translations") or {}
            failures = result.get("translation_errors") or {}
            fallback = result.get("translation_warnings") or {}
            if applied.show_translation and applied.target_languages:
                available = [
                    lang.upper() + ": " + translations[lang]
                    for lang in applied.target_languages
                    if isinstance(translations.get(lang), str) and
                    translations[lang].strip()]
                if available:
                    heading = ("TRANSLATIONS · Argos backup: " if fallback else
                               "TRANSLATIONS: ")
                    missing = [
                        lang.upper() for lang in applied.target_languages
                        if lang in failures and lang not in translations]
                    translated.setText(
                        label_prefix + heading + " · ".join(available) +
                        (" · " + ", ".join(missing) + " unavailable"
                         if missing else ""))
                else:
                    requested = ", ".join(applied.target_languages).upper()
                    translated.setText(
                        "Translation unavailable for " + requested +
                        " · original " + source_language +
                        " subtitles remain visible.")
                if failures:
                    translated.setToolTip(
                        "Offline translator diagnostics (not subtitles):\n" +
                        "\n".join(lang.upper()+": "+str(message)[:180]
                                  for lang,message in failures.items()))
                elif fallback:
                    translated.setToolTip(
                        "NLLB could not produce output; the installed Argos "
                        "language pack handled this phrase.")
                else:
                    translated.setToolTip("Translation output is local/offline.")
            else:
                translated.setText("")
                translated.setToolTip("Translations are not selected.")
            if (applied.separate_overlapping_voices and
                    len(result.get("overlap_lines") or [])==2):
                original.setText(current_text)
                translated.setText("")
            ipc.publish(current_text,applied,ttl_ms=3000)
            last_published = now
        elif current_cue and now >= current_until + 1.0:
            # Clear expired speech without stopping the capture service.
            current_cue = None
            current_text = ""
            ipc.publish("",applied if service_running else
                        __import__("dataclasses").replace(applied, mode="off"))
            last_published = now
            pending_words = bool(tap.sentence_joiner.pending)
            original.setText(
                "Preparing the next recognized sentence…"
                if pending_words else
                "No subtitle available for this interval · checking TV audio / ASR…")
            translated.setText("")
            sound_line.clear()
            sound_line.setVisible(False)
        elif now-last_published >= 1.5:
            # A real local caption-service heartbeat keeps Kaffeine's
            # virtual subtitle entry stable BETWEEN spoken phrases, including
            # extended silences. An empty cue means "available, no speech".
            heartbeat = (applied if service_running else
                         __import__("dataclasses").replace(applied, mode="off"))
            ipc.publish(current_text if current_cue and service_running else "",
                        heartbeat, ttl_ms=3500)
            last_published = now

        if now-last_pipeline_health_at>=2.0:
            last_pipeline_health_at=now
            snap=tap.performance_snapshot()
            backlog=snap["queue"]
            shown_gap=max(0.0,now-last_cue_shown_at)
            lost=snap.get("lost_ui_caption_events",0)
            missed=backlog.get("missed_seconds",0.0)
            recent=snap["samples"][-1] if snap["samples"] else {}
            if not service_running:
                message="Live captions paused."
            elif lost:
                message=(
                    f"CAPTION DELIVERY LOSS: {lost} actual decoded events "
                    "could not reach the UI; check system load.")
            elif missed:
                message=(
                    f"CAPTURE OVERFLOW: {missed:.1f}s of real TV audio "
                    "could not be retained; current scene may have no "
                    "subtitles. Reduce optional AI load.")
            elif snap.get("active_clip_at") is not None:
                elapsed=max(0.0,now-snap["active_clip_at"])
                message=(
                    f"Whisper / translation processing ({elapsed:.1f}s) · "
                    f"{backlog['queued_clips']} following clip(s) queued. "
                    "Speech may be delayed; no silence inferred.")
            elif backlog["queued_clips"]:
                message=(
                    f"ASR CATCH-UP: {backlog['queued_clips']} real audio "
                    f"clips queued, last wait {recent.get('queue_wait_ms','?')}ms. "
                    "TV playback may be ahead of captions.")
            elif (shown_gap>=10 and snap.get("last_ts_at") is not None
                  and now-snap["last_ts_at"]>4.0):
                message=(
                    f"No fresh DVB transport packets for "
                    f"{now-snap['last_ts_at']:.0f}s. Check TV playback and "
                    "sidecar receiver connection.")
            elif (shown_gap>=10 and snap.get("last_clip_at") is not None
                  and now-snap["last_clip_at"]>12.0):
                message=(
                    f"TS packets present but no completed caption audio "
                    f"clip for {now-snap['last_clip_at']:.0f}s. Check audio "
                    "PID, TS integrity and channel tune state.")
            elif shown_gap>=10 and tap.packet_count:
                message=(
                    f"NO SUBTITLE SHOWN for {shown_gap:.0f}s while DVB TS "
                    "packets are received. Could be speech recognition, "
                    "an incomplete sentence, silence, wrong audio PID or "
                    "native buffer ACK; inspect Diagnostics. "
                    f"Last compute {recent.get('compute_ms','?')}ms.")
            elif shown_gap>=10:
                message=(
                    "No subtitles and no confirmed live TV packet flow; "
                    "check the native TV channel and selected audio PID.")
            else:
                message=(
                    f"Live captions · last shown {shown_gap:.1f}s ago · "
                    f"queue {backlog['queued_clips']} clip(s) · "
                    f"last compute {recent.get('compute_ms','?')}ms")
            caption_pipeline_health.setText(message)
            if current_cue is None and service_running and shown_gap>=10:
                # Display diagnostics, not a fabricated claim of silence.
                original.setText(message)

    timer = QTimer(window)
    timer.timeout.connect(pump)
    timer.start(120)
    # The small status area or tray can reopen a hidden panel; the main
    # Kaffeine menu can always do this even on COSMIC without a system tray.
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QApplication as QtApplication, QStyle
    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(QIcon.fromTheme("video-display",
            app.style().standardIcon(QStyle.SP_MediaPlay)), window)
        tray.setToolTip("TIHULU subtitles active · click to reopen settings")
        menu = QMenu()
        reopen_action = menu.addAction("Show subtitle settings")
        reopen_action.triggered.connect(
            lambda: (window.showNormal(), window.raise_(), window.activateWindow()))
        quit_action = menu.addAction("Stop subtitles & Exit")
        quit_action.triggered.connect(app.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: (
            window.showNormal(), window.raise_(), window.activateWindow())
            if reason == QSystemTrayIcon.Trigger else None)
        tray.show()

    def stop_caption_service():
        window.terminating = True
        app.quit()

    hide_panel.clicked.connect(window.hide)
    back_to_tv.clicked.connect(window.showMinimized)
    exit_subtitles.clicked.connect(stop_caption_service)

    def cleanup():
        if tray:
            tray.hide()
        if srt_recorder.active:
            srt_recorder.stop()
        mobile.close()
        tap.close()
        ipc.close()
        control.close()
    app.aboutToQuit.connect(cleanup)
    window.show()
    return app.exec_()

if __name__ == "__main__":
    raise SystemExit(main())
