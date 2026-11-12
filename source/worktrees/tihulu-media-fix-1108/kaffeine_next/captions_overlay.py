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
import re
import socket
import sys
import threading
import time

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
    def __init__(self, path, current_options, events, packet_sink=None):
        self.path = validate_socket(path)
        self.packet_sink = packet_sink
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
        self.program_epoch = 0
        self.recv_buffer_bytes = None
        self.work_queue = BufferedCaptionQueue(
            maximum_bytes=(48 if Path("/proc/device-tree/model").is_file()
                           else 96) * 1024 * 1024, max_clips=24)
        self.thread = None
        self.worker = None
        self.previous_original = ""
        self.previous_revision = -1
        from tv_center.sentence_joiner import LiveSentenceJoiner
        self.sentence_joiner = LiveSentenceJoiner(max_words=90,max_chunks=3)
        self.sentence_session = None
        self.sentence_captured_start = None
        self.program_id = None
        self.sock = None
        self.packet_count = 0
        self.bad_packets = 0
        self._rate_start = None
        self._rate_bytes = 0
        self.bytes_per_second = None

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
            try:
                self._decode(clip.data, clip.options, clip.started, clip.ended)
            except Exception as error:
                self._note_warning("Caption worker failed: "+str(error)[:120])

    def _note_warning(self, message):
        try:
            self.events.put_nowait(("warning", str(message)[:240]))
        except queue.Full:
            pass

    def _reader(self):
        chunks = bytearray()
        last = time.monotonic()
        last_revision = -1
        previous_segment = b""
        previous_duration = 0.0
        quality = {"invalid":0,"duplicates":0,"gaps":0,"critical_gaps":0}
        from .continuous_captions import CapturedClip, prepended_overlap, estimate_overlap_seconds
        from .mpegts import current_program_id
        while not self.stop.is_set():
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
            # Kaffeine may switch services without reopening this sidecar.
            # Never concatenate clips or deduplicate speech across TV channels.
            observed_program = current_program_id(data)
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
                queued = self.work_queue.offer(
                    CapturedClip(capture, captured_options, started, now))
                if not queued:
                    health = self.work_queue.snapshot()
                    self._note_warning(
                        "Whisper slower than live TV: queue full; "
                        f"{health['missed_seconds']:.1f} s of captions could not "
                        "be retained. Select CUDA GPU/smaller model or fewer translations.")

    def _decode(self, capture, options, captured_start, captured_end):
        try:
            from tv_center.ai_settings import AISettings
            from tv_center.captions import decode_segment
            ai = AISettings()
            ai.configure_environment()
            selected = options["mode"]
            if selected in ("asr", "auto") and not ai.values["asr_enabled"]:
                if selected == "asr":
                    raise RuntimeError("Whisper disabled. Enable in AI Model Market.")
                selected = "teletext"
            source = options["source"]
            targets = tuple(options.get("targets", ()))
            enabled = targets if ai.values["translation_enabled"] else ()
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
                              if selected in ("auto", "teletext", "page") else None),
                audio_pid=(options.get("audio_pid")
                           if selected in ("auto", "asr") else None),
                audio_source=(options.get("audio_source")
                              if selected in ("auto", "asr") else None),
                speaker_enabled=bool(options.get("speaker_enabled",False))
                                and selected in ("auto","asr"),
                speaker_provider=options.get("speaker_provider","resemblyzer"),
                music_transcription=bool(options.get("music_transcription",False)),
                speech_priority=bool(options.get("speech_priority",False)),
                previous_text=previous)
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
            if result.get("source") == "local_asr" and not options.get(
                    "music_transcription",False):
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
                joined=self.sentence_joiner.push(
                    observed,
                    language=result.get("source_language"),
                    silent=not bool(observed))
                if not joined["text"]:
                    return  # Retain the incomplete sentence, not a cut-off cue.
                # A loop may span several otherwise valid Whisper clips.
                # Filter the FINAL assembled sentence too, after overlap
                # removal, before the translation engine receives it.
                from .continuous_captions import collapse_asr_repetition_loops
                result["original"] = collapse_asr_repetition_loops(joined["text"])
                if result["original"] != joined["text"]:
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
                # Translate AFTER reassembling the original full sentence.
                # Never join partial independent translations: German/English
                # word ordering can be destroyed by chunkwise translation.
                from tv_center.captions import translate as translate_sentence
                result["translations"]={}
                result["translation_errors"]={}
                result["translation_warnings"]={}
                result["translation_engines"]={}
                used=result.get("source_language")
                if enabled and used in (None,"und","auto"):
                    result["translation_errors"]={
                        target:"Source language not confirmed for full sentence"
                        for target in enabled}
                elif enabled:
                    for target in enabled:
                        if target==used:
                            result["translations"][target]=result["original"]
                            continue
                        text,issue=translate_sentence(
                            result["original"],used,target)
                        if text:
                            result["translations"][target]=text
                        if issue:
                            if text:
                                result["translation_warnings"][target]=issue[:180]
                            else:
                                result["translation_errors"][target]=issue[:180]
                result["translated"]=result["translations"].get(primary)
            if targets and not ai.values["translation_enabled"]:
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
            result["revision"] = options.get("revision", 0)
            try:
                self.events.put_nowait(("caption", result))
            except queue.Full:
                self._note_warning("Caption UI event backlog full; output delayed")
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
                                 buffer_fill_progress)
    from .word_cues import enqueue_word_cues
    from .track_preferences import recommended_track, _signaled_language
    from PyQt5.QtCore import Qt, QTimer, QSettings
    from PyQt5.QtGui import QColor
    from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QComboBox, QPushButton, QSpinBox, QDoubleSpinBox,
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
    mode.addItem("Broadcaster Teletext subtitles", "teletext")
    mode.addItem("Whisper live transcription", "asr")
    mode.addItem("Manual Teletext page", "page")
    mode.addItem("Off", "off")
    source = QComboBox()
    source.setEditable(True)
    source.addItem("Auto detect · Whisper", "auto")
    source.addItems(LANGS)
    source.setCurrentIndex(0)
    source.setToolTip(
        "Type an ISO code such as pl, es, ja, ar. Broadcast Teletext "
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
    language_boxes = {lang: QCheckBox(lang.upper()) for lang in LANGS}
    for lang, check in language_boxes.items():
        check.setChecked(lang == "tr")
        output_row.addWidget(check)
    settings_layout.addRow(output_row)
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
        for lang, check in language_boxes.items():
            check.setEnabled(True)
            check.setToolTip(
                ("Same as spoken language · display original under " +
                 lang.upper() + " label (no translator needed)"
                 if lang == source.currentText() else
                 "Translate to " + lang.upper() + " when a local model exists; "
                 "otherwise keep the original readable"))
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

    timing = QGroupBox("Synchronization & video overlay")
    timing_layout = QFormLayout(timing)
    quick = QGroupBox("Quick subtitle appearance · always visible")
    quick_layout = QFormLayout(quick)
    quick_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
    timing_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
    timing_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
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
    playback_delay.setToolTip("Buffers audio and video together (0–20 s). Long buffers consume RAM; "
                               "use CUDA models to reduce lag rather than excessive buffering.")
    offsets.addWidget(QLabel("Caption offset"))
    offsets.addWidget(caption_offset)
    offsets.addWidget(QLabel("TV playback buffer"))
    offsets.addWidget(playback_delay)
    timing_layout.addRow(offsets)
    auto_row = QHBoxLayout()
    automatic = QCheckBox("Automatic sync · detect caption lag & adjust safe TV buffer")
    automatic.setChecked(False)
    automatic.setToolTip(
        "OFF by default. After 3 real Whisper samples, estimates speech-caption "
        "availability and suggests a conservative delay. When enabled and Applied, "
        "only raises an insufficient TV buffer. It NEVER reduces an existing "
        "larger user buffer; lowering it requires an explicit manual change. "
        "ASR availability is not exact spoken-word alignment.")
    auto_row.addWidget(automatic)
    timing_layout.addRow(auto_row)
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
    speakers_row = QHBoxLayout()
    speaker_enabled = QCheckBox(
        "Auto-label distinct voices · Speaker 1, Speaker 2, …")
    speaker_enabled.setChecked(True)
    speaker_enabled.setToolTip(
        "Checked by default. Install the public Resemblyzer model in "
        "Model Market to activate local offline voice clustering. "
        "No token required, no microphone or remote voice API. Labels "
        "are automatically generated and provisional; gender and age "
        "cannot be identified reliably from audio alone.")
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
    speaker_health = QLabel(
        "Auto labels: checking installed local speaker model…")
    speaker_health.setWordWrap(True)
    timing_layout.addRow("Voice status", speaker_health)
    # Automatic speaker names are generated by the local detector.
    # No user-entered labels are required or offered by default.
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
    root.addWidget(buffer_progress)
    buttons = QHBoxLayout()
    apply = QPushButton("Apply")
    apply.setObjectName("apply")
    reset = QPushButton("Reset")
    pending = QLabel("Applied: broadcaster auto · German → Turkish · video captions ON")
    buttons.addWidget(apply); buttons.addWidget(reset); buttons.addWidget(pending, 1)
    root.addLayout(buttons)
    behavior = QHBoxLayout()
    hide_panel = QPushButton("Hide settings")
    start_subtitles = QPushButton("Start subtitles")
    stop_subtitles = QPushButton("Stop subtitles")
    exit_subtitles = QPushButton("Exit caption service")
    start_subtitles.setEnabled(False)
    behavior.addWidget(start_subtitles)
    behavior.addWidget(stop_subtitles)
    behavior.addWidget(hide_panel)
    behavior.addWidget(exit_subtitles)
    root.addLayout(behavior)
    persistence = QLabel("Closing this settings panel keeps on-video subtitles, "
                         "Whisper and translation running. Reopen with Kaffeine → "
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
    last_service_id = None
    last_effective_check = 0.0
    last_applied_effective_ms = None
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
    tap = CaptionTap(str(endpoint), options, events, packet_sink=mobile.receive)
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
        automatic_source = source.currentText() == "Auto detect · Whisper"
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
            audio_pid=chosen_audio["pid"] if chosen_audio else None,
            audio_language=(hinted if automatic_source and chosen_audio and
                            hinted in WHISPER_LANGUAGES else None),
            speaker_enabled=speaker_enabled.isChecked(),
            music_transcription=music_transcription.isChecked(),
            speech_priority=speech_priority.isChecked(),
            speaker_provider=speaker_provider.currentData(),
            speaker_aliases=(),
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
                chosen = selected.get("source_hint") or selected.get("language")
                if chosen:
                    source.setCurrentText(language_code(chosen))
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
                chosen = selected.get("source_hint") or selected.get("language")
                if chosen and chosen != "und" and (
                        source.currentText() != "Auto detect · Whisper"):
                    source.setCurrentText(language_code(chosen))
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
    for w in (show_video,automatic,speaker_enabled,music_transcription,
              speech_priority,*language_boxes.values()):
        w.toggled.connect(set_pending)

    def apply_settings():
        nonlocal applied, current_text, current_until, current_cue
        try:
            selected = from_controls()
            previous = applied
            source_changed = any(
                getattr(selected, key) != getattr(previous, key)
                for key in ("mode", "source", "target_languages", "page",
                            "teletext_pid", "audio_pid", "audio_language",
                            "music_transcription", "speech_priority",
                            "speaker_enabled", "speaker_provider", "speaker_aliases"))
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
                    int(source_changed or playback_changed))
            if source_changed or playback_changed:
                cues.clear()
                current_cue = None
                current_text = ""
                current_until = 0.0
                original.setText("Waiting for captions under the new source settings…")
                translated.setText("")
                ipc.publish("", applied if service_running else
                            __import__("dataclasses").replace(applied, mode="off"))
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
                ("Automatic timing (increase-only) · collecting live Whisper samples ("
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
                ("Automatic voice labels ON · installed offline " +
                 applied.speaker_provider + " model" if (
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

    def reset_settings():
        mode.setCurrentIndex(0)
        source.setCurrentIndex(0); display_mode.setCurrentIndex(1)
        for lang, check in language_boxes.items():
            check.setChecked(lang == "tr")
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

    def pump():
        nonlocal current_cue, current_text, current_until, last_published
        nonlocal applied, last_service_id, last_effective_check
        nonlocal last_applied_effective_ms, last_sync_audit_at
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
        if now - last_effective_check >= 1.0:
            last_effective_check = now
            effective = ipc.read_effective_delay()
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
                    if (last_applied_effective_ms is not None and
                            abs(current_actual-last_applied_effective_ms) >= 500):
                        # The 64MiB queue may cap/shrink/change delay even
                        # without the controls changing. Old timed cues
                        # are no longer tied to the true playback timeline.
                        cues.clear()
                        current_cue = None
                        current_text = ""
                        current_until = 0.0
                        ipc.publish("",applied)
                        status.setText(
                            "TV buffer changed on the native player: "
                            "old subtitle timestamps cleared; re-synchronizing.")
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
        for _ in range(8):
            try:
                kind, data = events.get_nowait()
            except queue.Empty:
                break
            if kind == "show_settings":
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
                    if lang and source.currentText() != "Auto detect · Whisper":
                        source.setCurrentText(lang)
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
                if data.get("revision") != applied.revision:
                    continue
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
                                # The control request is not the native
                                # buffer ACK. Discard old queued word cues
                                # and pause scheduling until player confirms.
                                cues.clear()
                                current_cue = None
                                current_text = ""
                                current_until = 0.0
                                last_applied_effective_ms = None
                                ipc.publish("",applied)
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
                    native_state = ipc.read_effective_delay()
                    cue_config = confirmed_cue_config(applied, native_state)
                    if cue_config is None:
                        status.setText(
                            "Waiting for actual TV buffer confirmation "
                            "before publishing another subtitle. "
                            "This prevents early captions while auto-sync "
                            "changes are being applied.")
                        continue
                    cue = enqueue_word_cues(
                        cues, data, cue_config,
                        data["captured_start"],data["captured_end"],
                        data["decoded_at"])
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
                    if data.get("speaker_error"):
                        status.setText(status.text() +
                            " | Diarization unavailable: " +
                            str(data["speaker_error"]))
                    elif data.get("speaker_turns"):
                        status.setText(status.text() +
                            " | Offline speakers: " +
                            str(data.get("speaker_engine") or "local model") +
                            " · provisional voice clusters")
                    if data.get("audio_notice"):
                        status.setText(status.text() + "\n" + data["audio_notice"])
                    if data.get("speech_priority_note"):
                        status.setText(status.text() + "\nSpeech priority: " +
                                       str(data["speech_priority_note"]))
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
            elif kind == "warning":
                status.setText(str(data))
        cue = cues.poll(now, applied.revision) if service_running else None
        if cue:
            current_cue = cue
            result = cue["result"]
            if srt_recorder.active:
                try:
                    srt_recorder.append(cue, applied)
                    srt_status.setText("SRT recording · " +
                                       ", ".join(str(p) for p in srt_recorder.paths))
                except (OSError, ValueError) as error:
                    end_srt_recording()
                    srt_status.setText("SRT save error: " + str(error))
            current_text = applied.render(result)
            current_until = cue["expires"]
            source_language = str(result.get("source_language") or applied.source).upper()
            original.setText("ORIGINAL [" + source_language + "]: " +
                             result.get("original", ""))
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
                        heading + " · ".join(available) +
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
            ipc.publish(current_text,applied,ttl_ms=3000)
            last_published = now
        elif current_cue and now >= current_until + 1.0:
            # Clear expired speech without stopping the capture service.
            current_cue = None
            current_text = ""
            ipc.publish("",applied if service_running else
                        __import__("dataclasses").replace(applied, mode="off"))
            last_published = now
            original.setText("Waiting for next live phrase…")
            translated.setText("")
        elif now-last_published >= 1.5:
            # A real local caption-service heartbeat keeps Kaffeine's
            # virtual subtitle entry stable BETWEEN spoken phrases, including
            # extended silences. An empty cue means "available, no speech".
            heartbeat = (applied if service_running else
                         __import__("dataclasses").replace(applied, mode="off"))
            ipc.publish(current_text if current_cue and service_running else "",
                        heartbeat, ttl_ms=3500)
            last_published = now

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
