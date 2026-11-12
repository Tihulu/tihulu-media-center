# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit PIN-paired phone access using Kaffeine's *current* MPEG-TS stream.

No separate DVB frontend, no remote channel tuning, no cloud service. HTTP
is only for trusted LAN; do not forward the exposed port.
"""
from __future__ import annotations
from threading import RLock
import time
from .mpegts import current_program_id
from tv_center.lan import MobileLAN
from tv_center.streaming import HLSStreamer

class KaffeineMobile:
    def __init__(self, options, notify, caption=None, gui_commands=None):
        self.options = options
        self.notify = notify
        self.gui_commands = gui_commands
        self.caption = caption or {"original":"", "translated":"", "source":"none"}
        self.caption_sequence = 0
        self.caption_history = []
        self.caption_timing = {}
        self.remote_access_mode = "phone"  # owner may still play on host
        self.last_native_status = None
        self.service_id = None
        self.last_packet_at = 0.0
        self.http = None
        self.hls = None
        self.lock = RLock()

    def receive(self, datagram: bytes):
        pid = current_program_id(datagram)
        self.last_packet_at = time.monotonic()
        stream_to_stop = None
        with self.lock:
            if pid is not None and self.service_id != pid:
                if self.hls is not None:
                    stream_to_stop = self.hls
                    self.hls = None
                self.service_id = pid
            active = self.hls
        # Channel switching cannot relay the former service to phones.
        if stream_to_stop:
            stream_to_stop.stop()
            self.notify("Live channel changed; restart mobile video deliberately.")
        if active and active is not stream_to_stop:
            active.offer(datagram)

    def snapshot(self):
        with self.lock:
            sid = self.service_id
            live = bool(sid and time.monotonic() - self.last_packet_at < 8)
            streaming = live and self.hls is not None and self.hls.get_dir() is not None
            self.caption_history = [
                item for item in self.caption_history
                if item["received_epoch_ms"] > int(time.time()*1000)-90000]
            caption = dict(self.caption)
            timing = dict(self.caption_timing)
            history = [dict(item) for item in self.caption_history]
            mode = self.remote_access_mode
        return {
            "source": "live_native_dvb" if live else "offline",
            "channel": "Kaffeine DVB service "+str(sid) if live else None,
            "caption": caption,
            "desktop_caption_settings":{
                "mode":self.options().get("mode","off"),
                "source":self.options().get("source","auto"),
                "targets":list(self.options().get("targets",())),
                "page":self.options().get("page",150),
                "requested_buffer_ms":self.options().get("playback_delay_ms",0),
                "offset_ms":self.options().get("offset_ms",0),
                "on_video":self.options().get("on_video",True),
            },
            "caption_timing": timing,
            "caption_events": history,
            "server_epoch_ms":round(time.time()*1000),
            "mobile_video": streaming,
            "playback_target": mode,
            "mobile_sources": [
                {"id":"dvb","label":"Current host DVB-T2 channel",
                 "available":live,
                 "streamable":streaming,
                 "reason":("" if live else "No DVB MPEG-TS packets from tuned host channel")},
                {"id":"captions","label":"Captions only (no phone audio/video)",
                 "available":True,"streamable":True},
            ],
            "stream_disclaimer":("Phone HLS and desktop libVLC use independent "
                 "buffers. Host buffer settings are inherited as caption timing "
                 "metadata, not a claim of synchronized audiovisual PTS."),
            "subtitle_mode": self.options()["mode"],
            "teletext_page": self.options()["page"],
            "supported_languages":["de","en","tr"],
            "web_video":"local_hls_from_Kaffeine_only",
            "pi5_hardware_verified":False,
        }

    def set_caption(self, result, cue=None, config=None, native_state=None):
        """Publish one REAL decoded caption with its measured host timings.

        Mobile video is encoded from the pre-playback TS and therefore must
        not inherit the desktop libVLC buffer a second time. Both clocks and
        the explicitly confirmed native buffer are exposed to the browser.
        """
        if not isinstance(result, dict):
            raise ValueError("Caption event must be a decoded mapping")
        now_mono = time.monotonic()
        now_wall = time.time()
        def stamp(monotonic):
            try:
                number = float(monotonic)
            except (ValueError, TypeError, OverflowError):
                return None
            return round((now_wall + number - now_mono)*1000)
        original = str(result.get("original") or "")[:1200]
        translations = result.get("translations") or {}
        if not isinstance(translations, dict):
            translations = {}
        translations = {str(k)[:8]: str(v)[:1200]
                        for k,v in list(translations.items())[:6]
                        if isinstance(v,str) and v.strip()}
        with self.lock:
            if result.get("source") in ("stopped","channel_changed"):
                self.caption_history.clear()
                self.caption_timing = {}
            self.caption_sequence += 1
            self.caption = {
                "original":original,
                "translated":"\n".join(
                    f"[{key.upper()}] {value}" for key,value in translations.items()),
                "translations":translations,
                "source":str(result.get("source") or "none")[:50],
                "source_language":str(result.get("source_language") or "und")[:12],
                "sequence":self.caption_sequence,
            }
            if config is not None:
                requested = int(config.playback_delay_ms)
                effective = (native_state.get("effective_ms")
                             if isinstance(native_state,dict)
                             and native_state.get("requested_ms")==requested
                             and native_state.get("primed") is True else None)
                self.caption_timing = {
                    "host_requested_buffer_ms":requested,
                    "host_effective_buffer_ms":effective,
                    "host_buffer_verified":effective is not None,
                    "host_caption_offset_ms":int(config.offset_ms),
                    "host_caption_due_epoch_ms":stamp(
                        cue.get("due") if isinstance(cue,dict) else None),
                    "capture_start_epoch_ms":stamp(result.get("captured_start")),
                    "capture_end_epoch_ms":stamp(result.get("captured_end")),
                    "decode_done_epoch_ms":stamp(result.get("decoded_at")),
                    "cue_expiry_epoch_ms":stamp(
                        cue.get("expires") if isinstance(cue,dict) else None),
                    "caption_sequence":self.caption_sequence,
                    "latency_note":("Desktop and phone HLS buffers are independent; "
                                    "use phone-video mode while playing HLS."),
                }
                if original or translations:
                    self.caption_history.append({
                        "sequence":self.caption_sequence,
                        "received_epoch_ms":round(now_wall*1000),
                        "caption":dict(self.caption),
                        "timing":dict(self.caption_timing),
                    })
                    self.caption_history = self.caption_history[-24:]

    def enable_lan(self, change_page):
        with self.lock:
            if self.http is not None:
                raise RuntimeError("Phone sharing already enabled")
            server = MobileLAN(self.snapshot, change_page, self.stream_dir,
                               commands=self.remote_command)
            data = server.start()
            self.http = server
        return data

    def remote_command(self, action, params):
        """Allowlisted host player controls. Never spawn a second tuner."""
        if not isinstance(params,dict) or type(action) is not str:
            raise ValueError("Invalid remote media control")
        if action == "sources":
            return {"items":self.snapshot()["mobile_sources"]}
        if action == "player_target":
            mode = params.get("target")
            if mode not in ("phone","host","both"):
                raise ValueError("Target must be phone, host or both")
            with self.lock:
                self.remote_access_mode = mode
            return {"target":mode,
                    "note":"Playback target preference; phone HLS remains opt-in on host"}
        if action == "video":
            enabled = params.get("enabled")
            if type(enabled) is not bool:
                raise ValueError("Video enabled must be boolean")
            if enabled:self.enable_video()
            else:self.stop_video()
            return {"video_enabled":bool(self.hls)}
        if action in ("set_desktop_caption_mode", "set_desktop_caption_offset",
                      "set_desktop_tv_buffer", "desktop_subtitles_running"):
            if not callable(self.gui_commands):
                raise RuntimeError("Desktop caption control is not attached")
            if action == "set_desktop_caption_mode":
                if params.get("mode") not in ("off","teletext","page","asr","auto"):
                    raise ValueError("Invalid desktop caption mode")
            elif action == "set_desktop_caption_offset":
                value = params.get("offset_ms")
                if type(value) is not int or not -10000<=value<=10000:
                    raise ValueError("Desktop caption offset must be ±10000 ms")
            elif action == "set_desktop_tv_buffer":
                value = params.get("buffer_ms")
                if type(value) is not int or not 0<=value<=20000:
                    raise ValueError("Desktop TV buffer must be 0–20000 ms")
            else:
                if type(params.get("running")) is not bool:
                    raise ValueError("Desktop subtitle running must be boolean")
            self.gui_commands(action,dict(params))
            return {"queued":True,"action":action,
                    "note":"Queued for native Qt GUI; wait for status confirmation"}
        if action in ("play", "pause", "stop", "next", "previous", "volume",
                      "tv_channel"):
            from tv_center.remote_controls import native_player_command
            return native_player_command(action, params)
        raise RuntimeError(
            "This control needs the desktop's native DVB bridge; "
            "not available from the caption sidecar. No action taken.")

    def enable_video(self):
        with self.lock:
            if self.http is None:
                raise RuntimeError("Enable trusted Wi-Fi sharing before video")
            if not self.service_id or time.monotonic() - self.last_packet_at >= 8:
                raise RuntimeError("Watch a TV channel first; no current MPEG-TS service detected")
            if self.hls is not None:
                return
            runner = HLSStreamer(lambda kind, detail: self.notify(str(detail)))
            runner.start(self.service_id)
            self.hls = runner

    def stop_video(self):
        with self.lock:
            runner = self.hls
            self.hls = None
        if runner:
            runner.stop()

    def expire_if_idle(self):
        with self.lock:
            stale = self.service_id is not None and (time.monotonic() - self.last_packet_at >= 12)
            has_stream = self.hls is not None
            if stale:
                self.service_id = None
        if stale and has_stream:
            self.stop_video()
            self.notify("Kaffeine TS ended or signal lost; mobile HLS stopped")

    def stream_dir(self):
        with self.lock:
            runner = self.hls
        return runner.get_dir() if runner else None

    def stop_lan(self):
        # Ensure HLS is stopped before revoking phone sessions.
        self.stop_video()
        with self.lock:
            http = self.http
            self.http = None
        if http:
            http.stop()

    def close(self):
        self.stop_lan()
