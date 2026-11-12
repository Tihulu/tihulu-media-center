"""Qt-main-thread controller for the PIN-paired phone and local Pages web apps.

Neither the HTTP server nor browser clients ever touch Qt widgets or DVB
devices directly; WebCommandQueue handles serialization and timeouts.
"""
from __future__ import annotations
from .lan import MobileLAN
from .web_control import WebCommandQueue
from .core import receiver_status
from .scanner import check_dependencies
from .satellite import SATELLITES
from pathlib import Path

class TVWebMixin:
    def setup_mobile_ui(self, form):
        from PyQt5.QtWidgets import QCheckBox,QLabel
        self.web_commands=WebCommandQueue()
        self.mobile=None
        self.web_scan_events=[]
        self.web_scan_requested=False
        self.web_scan_remote=False
        self.web_target="host"
        self.web_muted_host=False
        self.mobile_toggle=QCheckBox("Allow phone / tablet on trusted Wi-Fi · PIN pairing")
        self.mobile_toggle.toggled.connect(self.toggle_mobile)
        form.addRow("Local mobile TV app",self.mobile_toggle)
        self.mobile_info=QLabel("OFF. No LAN listener.")
        self.mobile_info.setWordWrap(True)
        form.addRow("URL and pairing PIN",self.mobile_info)
        self.mobile_video_toggle=QCheckBox("Share live video (H.264/AAC · high CPU)")
        self.mobile_video_toggle.toggled.connect(self.toggle_mobile_video)
        form.addRow("Live HLS encoder",self.mobile_video_toggle)

    def toggle_mobile(self,enabled):
        from PyQt5.QtWidgets import QMessageBox
        if enabled:
            try:
                self.mobile=MobileLAN(self.snapshot,
                    lambda p:self.web_commands.submit("teletext",{"page":p}),
                    self.capture.mobile_stream_dir,commands=self.web_commands.submit)
                data=self.mobile.start()
                self.mobile_info.setText(
                    data["url"]+"  |  PIN: "+data["pin"]+
                    "  |  TRUSTED Wi-Fi ONLY (no HTTPS)")
            except OSError as exc:
                if self.mobile:self.mobile.stop()
                self.mobile=None
                self.mobile_toggle.blockSignals(True)
                self.mobile_toggle.setChecked(False)
                self.mobile_toggle.blockSignals(False)
                QMessageBox.warning(self,"Mobile TV",str(exc))
        else:
            if self.mobile:
                self.mobile.stop()
                self.mobile=None
            if self.mobile_video_toggle.isChecked():
                self.mobile_video_toggle.setChecked(False)
            self.mobile_info.setText("OFF. No LAN listener.")

    def toggle_mobile_video(self,enabled):
        if enabled:
            try:
                if not self.mobile:
                    raise RuntimeError("Enable PIN-paired local web first")
                self.capture.start_mobile_video()
                self.statusbar.setText("Live HLS encoder enabled. Check CPU load.")
            except (RuntimeError,OSError,ValueError) as exc:
                self.mobile_video_toggle.blockSignals(True)
                self.mobile_video_toggle.setChecked(False)
                self.mobile_video_toggle.blockSignals(False)
                self.statusbar.setText("Mobile stream unavailable: "+str(exc))
        else:
            self.capture.stop_mobile_video()

    def reset_mobile_video_ui(self):
        if hasattr(self,"mobile_video_toggle") and self.mobile_video_toggle.isChecked():
            self.mobile_video_toggle.blockSignals(True)
            self.mobile_video_toggle.setChecked(False)
            self.mobile_video_toggle.blockSignals(False)

    def native_web_snapshot(self):
        """Real, non-fabricated native DVB receiver capabilities for mobile."""
        import time
        verified=bool(self.capture._stream_verified and self.capture.zap
                      and self.capture.zap.poll() is None)
        return {
            "server_epoch_ms":round(time.time()*1000),
            "backend":"native_tv_center",
            "mobile_video":bool(self.capture.mobile_stream_dir()),
            "playback_target":self.web_target,
            "mobile_sources":[
                {"id":"dvb","label":"Verified native DVB service",
                 "available":verified,
                 "streamable":bool(self.capture.mobile_stream_dir()),
                 "reason":("" if verified else
                     "No verified current DVB transport. Tune a real service.")},
                {"id":"captions","label":"Captions only",
                 "available":True,"streamable":True}
            ],
            "desktop_control_capabilities":{
                "mode":True,"offset":False,"buffer":False,"start_stop":True,
                "backend":"native_tv_center_mpv"},
            "desktop_caption_settings":{
                "mode":self.capture.caption_mode,
                "source":self.capture.source_lang,
                "targets":[self.capture.target_lang],
                "page":self.capture.page,
                "requested_buffer_ms":0,
                "offset_ms":0,
                "on_video":True},
            "caption_timing":{
                "host_requested_buffer_ms":0,
                "host_effective_buffer_ms":None,
                "host_buffer_verified":False,
                "host_caption_offset_ms":0,
                "latency_note":"Native mpv and phone HLS run independent clocks; "+
                     "media PTS calibration not available"},
            "stream_disclaimer":"Mobile HLS latency is estimated from the "+
                    "actual browser buffer, not measured against broadcast PTS."
        }

    def web_action(self,action,params):
        if action in ("play","tv_channel","next","previous") and (
                self.scanner.running or self.web_scan_requested):
            raise RuntimeError("Do not retune the native frontend during an RF scan")
        if action=="sources":
            return {"items":self.native_web_snapshot()["mobile_sources"]}
        if action=="video":
            enabled=params.get("enabled")
            if type(enabled) is not bool:
                raise ValueError("Video enabled must be boolean")
            if not self.mobile:
                raise RuntimeError("PIN-paired native mobile service not active")
            self.mobile_video_toggle.setChecked(enabled)
            actual=bool(self.capture.mobile_stream_dir())
            if enabled and not actual:
                raise RuntimeError("Native DVB HLS encoding could not start; "+
                                   self.statusbar.text())
            return {"video_enabled":actual,
                    "note":"Host HLS encoder "+("enabled" if actual else "stopped")}
        if action=="player_target":
            target=params.get("target")
            if target not in ("phone","host","both"):
                raise ValueError("Playback target must be phone, host or both")
            player=bool(self.capture.player and self.capture.player.poll() is None)
            if player and target=="phone":
                self.capture.control_player("mute",True)
                self.web_muted_host=True
            elif player and self.web_muted_host:
                self.capture.control_player("mute",False)
                self.web_muted_host=False
            self.web_target=target
            return {"target":target,
                    "note":("Native mpv host audio muted; tuner continues "+
                            "to feed phone HLS" if player and target=="phone" else
                            "Host audio unmuted" if player else
                            "Output preference stored; no host player is running")}
        if action=="pause":
            return self.capture.control_player("pause")
        if action=="volume":
            return self.capture.control_player("volume",params.get("value"))
        if action=="tv_channel":
            name=params.get("channel")
            if not isinstance(name,str) or not 1<=len(name.strip())<=90:
                raise ValueError("Enter the exact scanned channel name")
            matches=[(idx,row) for idx,row in enumerate(self.visible_rows)
                     if row["name"].casefold()==name.strip().casefold()]
            if len(matches)!=1:
                raise ValueError("Enter a unique channel name from the scanned "+
                                 "channel list; multiple or no matches found")
            index,row=matches[0]
            self.channel_list.setCurrentRow(index)
            self.play()
            return {"channel":row["name"],"tuning_requested":True}
        if action in ("next","previous"):
            rows=getattr(self,"visible_rows",[])
            if not rows:
                raise RuntimeError("No included scanned channels available")
            current=self.channel_list.currentRow()
            offset=1 if action=="next" else -1
            next_row=(current+offset)%len(rows)
            self.channel_list.setCurrentRow(next_row)
            self.play()
            return {"tuning_requested":True,"channel":rows[next_row]["name"]}
        if action=="channels":
            return {"profile":self.current_profile(),
                    "country":self.country.currentData(),
                    "medium":self.delivery.currentData(),
                    "satellite":self.satellite.currentData(),
                    "diseqc_port":self.diseqc.currentData(),
                    "backend":"native_tv_center",
                    "channels":[{
                       "key":r["key"],"name":r["name"],"kind":r["kind"],
                       "favorite":r["favorite"],"included":r["included"],
                       "new":r["new"],"encrypted":r["encrypted"],
                       "frequency":r["channel"].frequency
                    } for r in getattr(self,"current_rows",[])]}
        if action=="scan_status":
            import time
            device=receiver_status(self.capture.adapter)
            measured_at=getattr(self,"last_signal_measure_epoch_ms",None)
            measured_recently=bool(type(measured_at) is int and
                0<=round(time.time()*1000)-measured_at<60000)
            playing=bool(self.capture.thread and self.capture.thread.is_alive())
            running=bool(self.scanner.running or self.web_scan_requested)
            events=self.web_scan_events[-80:]
            last=next((e for e in reversed(events)
                       if e.get("kind") in ("frequency","status","found","signal",
                                            "complete","failed")),None)
            signal_event=next((e.get("metrics") for e in reversed(events)
                               if e.get("kind")=="signal"),None)
            signal_text=("Scanning owns the tuner: independent live C/N "
                         "measurement is unavailable until scan completes"
                         if running else self.signal_result.text())
            return {"running":running,
                    "backend":"native_tv_center",
                    "frontend_present":device["frontend_present"],
                    "selected_adapter":device["adapter"],
                    "frontend":device["frontend"],
                    "adapters":[int(p.parent.name.removeprefix("adapter"))
                                for p in sorted(Path("/dev/dvb").glob("adapter*/frontend0"))
                                if p.parent.name.removeprefix("adapter").isdigit()],
                    "busy":playing,
                    "scanning_dependencies":check_dependencies(),
                    "profile":self.current_profile(),
                    "country":self.country.currentData(),
                    "medium":self.delivery.currentData(),
                    "satellite":self.satellite.currentData(),
                    "diseqc_port":self.diseqc.currentData(),
                    "events":events,
                    "last_event":last,
                    "discovered_services":max((int(e.get("count") or 0)
                                                for e in events
                                                if e.get("kind")=="found"),default=0),
                    "status":self.statusbar.text(),
                    "signal":signal_text,
                    "signal_metrics":signal_event,
                    "signal_measured_epoch_ms":measured_at,
                    "signal_is_live":bool(measured_recently and playing and not running),
                    "signal_note":("Most recent real dvb-fe-tool measurement, not a "
                                   "continuous signal feed" if measured_recently and playing
                                   else "No C/N/UCB measurement for this tuned service. "
                                   "The scanner cannot share its locked frontend.")}
        if action=="models":
            from .model_market import ModelLibrary
            return {"models":ModelLibrary(self.ai.values["model_dir"] or None).installed(),
                    "asr_enabled":self.ai.values["asr_enabled"],
                    "translation_enabled":self.ai.values["translation_enabled"],
                    "backend":self.ai.values["backend"],
                    "note":"Native AI downloads require approval in desktop Settings; browser models managed separately."}
        if action=="channel_update":
            key=params.get("key")
            operation=params.get("operation")
            if not isinstance(key,str) or operation not in ("favorite","included","up","down"):
                raise ValueError("Invalid channel change")
            self.preferences.update(self.current_profile(),self.current_rows,key,operation)
            self.refresh_channels()
            return {"saved":True}
        if action=="play":
            key=params.get("key")
            if key is None:
                return self.capture.control_player("resume")
            match=next((i for i,r in enumerate(self.visible_rows) if r["key"]==key),None)
            if match is None:
                raise ValueError("Channel not included in active DVB profile")
            self.channel_list.setCurrentRow(match)
            self.play()
            return {"tuning_requested":True,"channel":self.channels[match].name}
        if action=="stop":
            self.stop()
            self.reset_mobile_video_ui()
            self.web_muted_host=False
            return {"released":True}
        if action=="teletext":
            page=params.get("page")
            if type(page) is not int or not 100<=page<=899:
                raise ValueError("Teletext page must be between 100 and 899")
            self.page.setValue(page)
            self.mode.setCurrentIndex(4)
            return {"page":page}
        if action=="scan_cancel":
            if not (self.scanner.running or self.web_scan_requested):
                return {"cancel_requested":False,
                        "note":"No active RF scan to cancel"}
            self.cancel_scan()
            return {"cancel_requested":True}
        if action=="measure_signal":
            if self.scanner.running or self.web_scan_requested:
                raise RuntimeError("Cannot measure signal while scanning owns the tuner")
            if not (self.capture.zap and self.capture.zap.poll() is None):
                raise RuntimeError("Tune an actual channel on the computer before measuring signal")
            self.measure_signal()
            return {"measurement_requested":True,"note":"Await real dvb-fe-tool readings"}
        if action=="scan_start":
            if (self.scanner.running or self.web_scan_requested or
                    (self.capture.thread and self.capture.thread.is_alive())):
                raise RuntimeError("Stop playing TV or scanning before starting a new scan")
            country=params.get("country")
            medium=params.get("medium")
            if country not in ("DE","TR") or medium not in ("t","c","s"):
                raise ValueError("Invalid country or DVB delivery")
            ci=self.country.findData(country)
            mi=self.delivery.findData(medium)
            if ci<0 or mi<0:raise ValueError("Unsupported scan profile")
            self.country.setCurrentIndex(ci)
            self.delivery.setCurrentIndex(mi)
            if medium=="s":
                satellite=params.get("satellite","S42E0")
                si=self.satellite.findData(satellite)
                if si<0:raise ValueError("Unsupported satellite")
                self.satellite.setCurrentIndex(si)
            if medium=="s":
                port=params.get("diseqc_port")
                if port is not None and (type(port) is not int or not 0<=port<=3):
                    raise ValueError("DiSEqC port must be direct or 1–4")
                idx=self.diseqc.findData(port)
                if idx<0:
                    raise ValueError("Unsupported DiSEqC input")
                self.diseqc.setCurrentIndex(idx)
            self.web_scan_events.clear()
            self.web_scan_remote=True
            started=self.scan_channels(confirmed=True)
            if started is not True:
                self.web_scan_remote=False
                raise RuntimeError("Native tuner did not start a scan")
            self.web_scan_events.append({
                "kind":"status","stage":0,
                "text":"Queued actual tuner scan: "+self.current_profile()})
            return {"scan_requested":True,"profile":self.current_profile(),
                    "backend":"native_tv_center",
                    "note":"Real RF scan started on host, existing channel data preserved on failure"}
        if action=="set_desktop_caption_mode":
            choice=params.get("mode")
            modes=["off","teletext","asr","auto","page"]
            if choice not in modes:
                raise ValueError("Invalid native subtitle mode")
            self.mode.setCurrentIndex(modes.index(choice))
            self.apply_mode()
            if self.capture.caption_mode!="off":
                self.last_desktop_caption_mode=self.capture.caption_mode
            return {"actual_mode":self.capture.caption_mode,
                    "note":"Applied native caption mode on host"}
        if action=="desktop_subtitles_running":
            should_run=params.get("running")
            if type(should_run) is not bool:
                raise ValueError("Subtitle Start/Stop requires a boolean")
            modes=["off","teletext","asr","auto","page"]
            current=self.capture.caption_mode
            if should_run:
                choice=(current if current!="off" else
                        getattr(self,"last_desktop_caption_mode","teletext"))
            else:
                if current!="off":
                    self.last_desktop_caption_mode=current
                choice="off"
            self.mode.setCurrentIndex(modes.index(choice))
            self.apply_mode()
            return {"running":self.capture.caption_mode!="off",
                    "actual_mode":self.capture.caption_mode,
                    "note":"Native caption state is "+
                    ("running" if self.capture.caption_mode!="off" else "off")}
        if action=="set_captions":
            mode=params.get("mode")
            modes=["off","teletext","asr","auto","page"]
            if mode not in modes:raise ValueError("Unknown caption mode")
            self.mode.setCurrentIndex(modes.index(mode))
            self.apply_mode()
            return {"actual_mode":self.capture.caption_mode}
        raise ValueError("Unsupported native TV web action")

    def close_mobile(self):
        if hasattr(self,"web_commands"):self.web_commands.close()
        if getattr(self,"mobile",None):
            self.mobile.stop()
            self.mobile=None
