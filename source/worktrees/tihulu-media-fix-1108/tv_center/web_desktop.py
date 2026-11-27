"""Qt-main-thread controller for the PIN-paired phone and local Pages web apps.

Neither the HTTP server nor browser clients ever touch Qt widgets or DVB
devices directly; WebCommandQueue handles serialization and timeouts.
"""
from __future__ import annotations
from .lan import MobileLAN
from .web_control import WebCommandQueue

class TVWebMixin:
    def setup_mobile_ui(self, form):
        from PyQt5.QtWidgets import QCheckBox,QLabel
        self.web_commands=WebCommandQueue()
        self.mobile=None
        self.web_scan_events=[]
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

    def web_action(self,action,params):
        if action=="channels":
            return {"profile":self.current_profile(),
                    "country":self.country.currentData(),
                    "medium":self.delivery.currentData(),
                    "satellite":self.satellite.currentData(),
                    "channels":[{
                       "key":r["key"],"name":r["name"],"kind":r["kind"],
                       "favorite":r["favorite"],"included":r["included"],
                       "new":r["new"],"encrypted":r["encrypted"],
                       "frequency":r["channel"].frequency
                    } for r in getattr(self,"current_rows",[])]}
        if action=="scan_status":
            return {"running":self.scanner.running,
                    "profile":self.current_profile(),
                    "events":self.web_scan_events[-60:],
                    "status":self.statusbar.text(),
                    "signal":self.signal_result.text()}
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
            match=next((i for i,r in enumerate(self.visible_rows) if r["key"]==key),None)
            if match is None:
                raise ValueError("Channel not included in active DVB profile")
            self.channel_list.setCurrentRow(match)
            self.play()
            return {"tuning_requested":True,"channel":self.channels[match].name}
        if action=="stop":
            self.stop()
            self.reset_mobile_video_ui()
            return {"released":True}
        if action=="teletext":
            page=params.get("page")
            if type(page) is not int or not 100<=page<=899:
                raise ValueError("Teletext page must be between 100 and 899")
            self.page.setValue(page)
            self.mode.setCurrentIndex(4)
            return {"page":page}
        if action=="scan_cancel":
            self.cancel_scan()
            return {"cancel_requested":True}
        if action=="scan_start":
            if self.scanner.running or (self.capture.thread and self.capture.thread.is_alive()):
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
            self.web_scan_events.clear()
            self.scan_channels(confirmed=True)
            return {"scan_requested":True,"profile":self.current_profile()}
        if action=="set_captions":
            mode=params.get("mode")
            modes=["off","teletext","asr","auto","page"]
            if mode not in modes:raise ValueError("Unknown caption mode")
            self.mode.setCurrentIndex(modes.index(mode))
            return {"actual_mode":self.capture.caption_mode}
        raise ValueError("Unsupported native TV web action")

    def close_mobile(self):
        if hasattr(self,"web_commands"):self.web_commands.close()
        if getattr(self,"mobile",None):
            self.mobile.stop()
            self.mobile=None
