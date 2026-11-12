"""Native Qt Widgets television application for Debian/Ubuntu/Pop!_OS/Pi OS.

No embedded browser, WebUSB, libVLC or hidden polling. MPV is embedded as a
separate native X11 child window; on Wayland set QT_QPA_PLATFORM=xcb.
"""
from __future__ import annotations
from pathlib import Path
import json
import os
import tempfile
import queue
import subprocess
import sys
import threading

from . import __version__
from .core import TVCapture, discover_channels, read_channels, receiver_status, parse_signal_log, format_frequency, Channel
from .bridge import TVBridge
from .captions import install_argos_pack
from .scanner import AutoScanner, ScanError, PROFILES, MODES
from .satellite import SATELLITES, satellite_hardware_note
from .channel_prefs import ChannelPreferences, profile_key
from .ai_settings import AISettings
from .channels_ui import edit_channels
from .settings_ui import open_ai_settings
from .scan_ui import ScanMonitor

def main():
    if os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    try:
        from PyQt5.QtCore import Qt, QTimer
        from PyQt5.QtWidgets import (
            QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
            QPushButton, QListWidget, QComboBox, QSpinBox, QFileDialog, QLineEdit,
            QMessageBox, QSplitter, QGroupBox, QFormLayout, QCheckBox, QInputDialog,
            QTabWidget, QScrollArea, QTextEdit, QListWidgetItem
        )
    except ImportError:
        print("Qt desktop dependency missing: sudo apt install python3-pyqt5", file=sys.stderr)
        return 2

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("TIHULU TV Center · Native DVB")
            self.resize(1280, 795)
            self.capture = TVCapture()
            self.scanner = AutoScanner()
            self.ai = AISettings()
            self.ai.configure_environment()
            self.preferences = ChannelPreferences()
            self.scan_monitor = None
            self.bridge = None
            self.last_playback_error = False
            self.latest = {"original": "", "translated": "", "source": "none"}
            self.channels = []
            self.setStyleSheet("""
                QMainWindow, QWidget {background:#101823;color:#e5edf4;font-family:Sans;font-size:13px}
                QLabel {background:transparent}
                QGroupBox {border:1px solid #334658;border-radius:10px;margin-top:14px;
                           padding:14px 8px 8px;font-weight:600}
                QGroupBox::title {subcontrol-origin:margin;left:13px;padding:0 7px;color:#a7d2e9}
                QPushButton {background:#24374b;border:1px solid #39536a;border-radius:8px;
                             padding:9px 12px;color:#eaf5ff}
                QPushButton:hover {background:#30506c;border-color:#5488a6}
                QPushButton:pressed {background:#19354d}
                QPushButton:disabled {color:#8291a3;background:#182332;border-color:#273545}
                QPushButton#primary {background:#166d91;color:white;border:1px solid #249ec7;font-weight:600}
                QPushButton#primary:hover {background:#1d85ae}
                QComboBox, QLineEdit, QSpinBox, QListWidget, QTextEdit {
                    background:#172637;border:1px solid #33485c;border-radius:7px;
                    padding:6px;color:#eaf1f8;selection-background-color:#196c8d}
                QListWidget {alternate-background-color:#1d2d3e;outline:0}
                QListWidget::item {padding:7px 5px;border-radius:4px}
                QListWidget::item:selected {background:#246c8a;color:white}
                QTabWidget::pane {border:1px solid #314557;border-radius:8px;background:#142130}
                QTabBar::tab {background:#1a2b3c;padding:9px 16px;margin:3px 3px 0 0;
                              border-top-left-radius:7px;border-top-right-radius:7px}
                QTabBar::tab:selected {background:#265873;color:white}
                QLabel#caption {background:#152435;border:1px solid #314759;
                                border-radius:8px;padding:10px;color:#f4f8fb;font-size:14px}
                QLabel#receiverNotice {color:#b2c8d8;padding:5px;font-size:12px}
                QLabel#playerHint {background:#070d14;color:#b9c8d6;font-size:18px;padding:20px}
            """)
            root = QWidget()
            self.setCentralWidget(root)
            outer = QVBoxLayout(root)
            title = QLabel("TIHULU  /  TV CENTER")
            title.setStyleSheet("font-size:22px;font-weight:700;color:#76d6ee;padding:4px 2px")
            outer.addWidget(title)
            self.header_market = QPushButton("WHISPER + TRANSLATOR  ·  AI MODEL MARKET")
            self.header_market.setObjectName("primary")
            self.header_market.setToolTip("Manage built-in offline model suite, German/English/Turkish packs and external SSD")
            self.header_market.clicked.connect(self.open_ai_settings)
            outer.addWidget(self.header_market)
            description = QLabel("LIVE DIGITAL TV   /   LOCAL DVBv5   /   NO WEBUSB")
            description.setObjectName("receiverNotice")
            outer.addWidget(description)
            splitter = QSplitter(Qt.Horizontal)
            outer.addWidget(splitter, 1)
            left = QWidget()
            left.setMinimumWidth(280)
            left.setMaximumWidth(390)
            splitter.addWidget(left)
            l = QVBoxLayout(left)
            self.devices = QLabel("Receiver status pending")
            self.devices.setWordWrap(True)
            l.addWidget(self.devices)
            self.adapter_choice = QComboBox()
            available = sorted(Path("/dev/dvb").glob("adapter*/frontend0"))
            for path in available:
                number = int(path.parent.name.replace("adapter", ""))
                self.adapter_choice.addItem("DVB adapter " + str(number), number)
            if not available:
                self.adapter_choice.addItem("DVB adapter 0 (not detected)", 0)
            self.adapter_choice.currentIndexChanged.connect(self.change_adapter)
            l.addWidget(self.adapter_choice)
            channel_search_row = QHBoxLayout()
            self.channel_search = QLineEdit()
            self.channel_search.setPlaceholderText("Find channel or frequency…")
            self.channel_search.textChanged.connect(self.display_channels)
            channel_search_row.addWidget(self.channel_search,3)
            self.channel_filter = QComboBox()
            self.channel_filter.addItems(["All","Favorites","Television","Radio","Free-to-air"])
            self.channel_filter.currentIndexChanged.connect(self.display_channels)
            channel_search_row.addWidget(self.channel_filter,2)
            l.addLayout(channel_search_row)
            self.channel_list = QListWidget()
            self.channel_list.setAlternatingRowColors(True)
            self.channel_list.itemDoubleClicked.connect(lambda *_: self.play())
            l.addWidget(self.channel_list, 2)
            source_card = QGroupBox("SOURCE / CHANNEL SCAN")
            l.addWidget(source_card, 2)
            scan_scroll = QScrollArea()
            scan_scroll.setWidgetResizable(True)
            scan_scroll.setFrameShape(QScrollArea.NoFrame)
            source_layout = QVBoxLayout()
            source_host = QWidget()
            source_host.setLayout(source_layout)
            scan_scroll.setWidget(source_host)
            source_card_layout = QVBoxLayout(source_card)
            source_card_layout.setContentsMargins(5,7,5,5)
            source_card_layout.addWidget(scan_scroll)
            import_btn = QPushButton("Import existing DVBv5 channels.conf")
            import_btn.clicked.connect(self.import_channels)
            source_layout.addWidget(import_btn)
            self.country = QComboBox()
            self.country.addItem("Germany (DE)", "DE")
            self.country.addItem("Türkiye (TR)", "TR")
            self.country.currentIndexChanged.connect(self.refresh_channels)
            source_layout.addWidget(self.country)
            self.delivery = QComboBox()
            self.delivery.addItem("Antenna · DVB-T / DVB-T2", "t")
            self.delivery.addItem("Cable · DVB-C", "c")
            self.delivery.addItem("Satellite dish · DVB-S/S2", "s")
            self.delivery.currentIndexChanged.connect(self.update_delivery)
            source_layout.addWidget(self.delivery)
            self.satellite = QComboBox()
            for orbital, label in SATELLITES.items():
                self.satellite.addItem(label, orbital)
            self.satellite.currentIndexChanged.connect(self.refresh_channels)
            source_layout.addWidget(self.satellite)
            self.diseqc = QComboBox()
            self.diseqc.addItem("LNB direct · no DiSEqC switch", None)
            for port in range(4):
                self.diseqc.addItem("DiSEqC port " + str(port + 1), port)
            source_layout.addWidget(self.diseqc)
            self.satellite.setVisible(False)
            self.diseqc.setVisible(False)
            self.satellite_help = QPushButton("Dish / Raspberry Pi 5 setup guide")
            self.satellite_help.clicked.connect(self.show_satellite_guide)
            self.satellite_help.setVisible(False)
            source_layout.addWidget(self.satellite_help)
            scan_btn = QPushButton("Scan all local frequencies")
            scan_btn.setObjectName("primary")
            scan_btn.clicked.connect(self.scan_channels)
            source_layout.addWidget(scan_btn)
            self.stop_scan_btn = QPushButton("Cancel running scan")
            self.stop_scan_btn.setEnabled(False)
            self.stop_scan_btn.clicked.connect(self.cancel_scan)
            source_layout.addWidget(self.stop_scan_btn)
            self.list_origin = QLabel("Previously saved frequencies. Run automatic scan to verify.")
            self.list_origin.setWordWrap(True)
            source_layout.addWidget(self.list_origin)
            manager_btn = QPushButton("Manage scanned channels · ★ Favorites")
            manager_btn.clicked.connect(self.open_channel_manager)
            source_layout.addWidget(manager_btn)
            manual_btn = QPushButton("Scan with DVBv5 regional source file")
            manual_btn.clicked.connect(self.scan_from_file)
            source_layout.addWidget(manual_btn)
            self.signal_btn = QPushButton("Measure current signal / C/N")
            self.signal_btn.clicked.connect(self.measure_signal)
            source_layout.addWidget(self.signal_btn)
            self.signal_result = QLabel("C/N and UCB: not yet measured")
            self.signal_result.setWordWrap(True)
            source_layout.addWidget(self.signal_result)
            self.play_btn = QPushButton("▶  Watch selected channel")
            self.play_btn.setObjectName("primary")
            self.play_btn.clicked.connect(self.play)
            l.addWidget(self.play_btn)
            stop_btn = QPushButton("■  Stop / release tuner")
            stop_btn.clicked.connect(self.stop)
            l.addWidget(stop_btn)

            right = QWidget()
            splitter.addWidget(right)
            r = QVBoxLayout(right)
            self.video = QWidget()
            self.video.setAttribute(Qt.WA_NativeWindow, True)
            self.video.setMinimumSize(540, 305)
            self.video.setStyleSheet("background:#05080d;border-radius:9px")
            video_layout = QVBoxLayout(self.video)
            self.player_hint = QLabel("Select a channel and press Watch")
            self.player_hint.setObjectName("playerHint")
            self.player_hint.setAlignment(Qt.AlignCenter)
            self.player_hint.setWordWrap(True)
            video_layout.addWidget(self.player_hint)
            r.addWidget(self.video, 8)
            self.subtitle = QLabel("Captions off — video is real local DVB, never a demo stream.")
            self.subtitle.setObjectName("caption")
            self.subtitle.setWordWrap(True)
            self.subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.subtitle.setMinimumHeight(70)
            r.addWidget(self.subtitle)
            self.details_tabs = QTabWidget()
            r.addWidget(self.details_tabs, 3)
            reception_tab = QWidget()
            reception_layout = QVBoxLayout(reception_tab)
            self.playback_detail = QLabel("No channel tuned · no transport packets verified")
            self.playback_detail.setWordWrap(True)
            reception_layout.addWidget(self.playback_detail)
            self.playback_diagnostics = QTextEdit()
            self.playback_diagnostics.setReadOnly(True)
            self.playback_diagnostics.document().setMaximumBlockCount(120)
            self.playback_diagnostics.setPlaceholderText(
                "Tuner, service tables, live MPEG-TS and playback errors appear here.")
            reception_layout.addWidget(self.playback_diagnostics, 1)
            diagnostics_actions=QHBoxLayout()
            compat=QPushButton("Retry selected channel · compatible renderer")
            compat.clicked.connect(self.retry_compat)
            diagnostics_actions.addWidget(compat)
            logs=QPushButton("View actual tuner / MPV logs")
            logs.clicked.connect(self.open_playback_logs)
            diagnostics_actions.addWidget(logs)
            reception_layout.addLayout(diagnostics_actions)
            self.details_tabs.addTab(reception_tab,"Reception & diagnostics")
            captions_tab = QWidget()
            captions_layout = QVBoxLayout(captions_tab)
            self.settings_button = QPushButton("AI MODEL MARKET  ·  Whisper + Translator  ·  Install / Remove")
            self.settings_button.clicked.connect(self.open_ai_settings)
            captions_layout.addWidget(self.settings_button)
            self.ai_banner = QLabel("Installed AI status: checking…")
            self.ai_banner.setWordWrap(True)
            captions_layout.addWidget(self.ai_banner)
            self.refresh_ai_banner()
            controls = QGroupBox("Broadcast subtitles · Teletext · Offline speech / translation")
            captions_layout.addWidget(controls)
            self.details_tabs.addTab(captions_tab,"Subtitles & AI")
            form = QFormLayout(controls)
            self.mode = QComboBox()
            self.mode.addItems(["Off", "Broadcast Teletext", "Live transcription", "Teletext first → ASR fallback", "Teletext page viewer"])
            self.mode.currentIndexChanged.connect(self.apply_mode)
            form.addRow("Subtitle source", self.mode)
            self.page = QSpinBox()
            self.page.setRange(100, 899)
            self.page.setValue(150)
            self.page.valueChanged.connect(self.apply_mode)
            form.addRow("Teletext page (100–899)", self.page)
            self.lang_in = QComboBox()
            self.lang_in.addItems(["de", "en", "tr"])
            self.lang_in.currentIndexChanged.connect(self.apply_mode)
            form.addRow("Broadcast / speech language", self.lang_in)
            self.lang_out = QComboBox()
            self.lang_out.addItems(["tr", "de", "en"])
            self.lang_out.currentIndexChanged.connect(self.apply_mode)
            form.addRow("Subtitle output language", self.lang_out)
            self.model = QLineEdit(self.ai.values["model_path"])
            self.model.setPlaceholderText("Select an installed multilingual GGML Whisper model")
            self.model.editingFinished.connect(self.apply_mode)
            browse = QPushButton("Choose offline ASR model…")
            browse.clicked.connect(self.choose_model)
            form.addRow(browse, self.model)
            pack = QPushButton("Install local .argosmodel language pack…")
            pack.clicked.connect(self.install_pack)
            form.addRow("Offline translation", pack)
            self.hw = QComboBox()
            self.hw.addItems(["no", "auto-safe"])
            form.addRow("MPV hardware decode (next tune)", self.hw)
            self.renderer = QComboBox()
            self.renderer.addItems(["x11-gpu", "x11-compat"])
            form.addRow("Embedded video renderer", self.renderer)
            self.bridge_toggle = QCheckBox("Enable token-protected local web bridge")
            self.bridge_toggle.toggled.connect(self.toggle_bridge)
            form.addRow("GitHub Pages / local web", self.bridge_toggle)
            self.bridge_token = QLineEdit()
            self.bridge_token.setReadOnly(True)
            self.bridge_token.setPlaceholderText("Bridge OFF — no local server")
            form.addRow("Temporary bridge token", self.bridge_token)
            self.statusbar = QLabel("Idle. No active tuner or AI worker.")
            self.statusbar.setWordWrap(True)
            outer.addWidget(self.statusbar)
            splitter.setSizes([335, 935])
            self.refresh_channels()
            self.update_device_status()
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.poll)
            self.timer.start(250)

        def update_device_status(self):
            s = receiver_status(self.capture.adapter)
            self.devices.setText("DVB frontend: " + ("connected" if s["frontend_present"] else "missing")
                                 + "  |  WinTV USB 2040:8268: " + ("detected" if s["win_tv_solohd_usb_present"] else "not seen")
                                 + "  |  Si2168 D60 firmware: " + ("yes" if s["si2168_d60_firmware_present"] else "no")
                                 + "  |  MPV: " + ("yes" if s["mpv"] else "no")
                                 + "  |  ffmpeg: " + ("yes" if s["ffmpeg"] else "no"))

        def change_adapter(self):
            if self.capture.thread and self.capture.thread.is_alive():
                self.statusbar.setText("Stop playback before switching the DVB adapter.")
                return
            self.capture.adapter = int(self.adapter_choice.currentData() or 0)
            self.update_device_status()

        def measure_signal(self):
            if not (self.capture.zap and self.capture.zap.poll() is None):
                self.signal_result.setText("Tune a live DVB channel before measuring.")
                return
            if not receiver_status(self.capture.adapter)["frontend_present"]:
                self.signal_result.setText("DVB frontend unavailable.")
                return
            self.signal_result.setText("Measuring receiver… do not move antenna during each comparison.")
            adapter = self.capture.adapter
            def worker():
                try:
                    p = subprocess.run(["dvb-fe-tool", "-a", str(adapter), "-m"],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       timeout=15, check=False)
                    raw = p.stdout.decode("utf-8", "replace")
                except subprocess.TimeoutExpired as exc:
                    raw = (exc.stdout or b"").decode("utf-8", "replace")
                except OSError as exc:
                    self.capture.emit("measurement", {"error": str(exc)})
                    return
                self.capture.emit("measurement", parse_signal_log(raw))
            threading.Thread(target=worker, daemon=True, name="tihulu-tv-signal").start()

        def update_delivery(self, *_):
            satellite = self.delivery.currentData() == "s"
            self.satellite.setVisible(satellite)
            self.diseqc.setVisible(satellite)
            self.satellite_help.setVisible(satellite)
            self.refresh_channels()

        def show_satellite_guide(self):
            from PyQt5.QtWidgets import QDialog, QTextBrowser
            dialogue = QDialog(self)
            dialogue.setWindowTitle("Dish satellite / Raspberry Pi 5 connection guide")
            dialogue.resize(780, 620)
            lay = QVBoxLayout(dialogue)
            viewer = QTextBrowser(dialogue)
            path = Path(__file__).parent / "docs/SATELLITE_PI5_DISH.md"
            viewer.setMarkdown(path.read_text(encoding="utf-8") if path.is_file()
                               else satellite_hardware_note())
            lay.addWidget(viewer)
            close = QPushButton("Close")
            close.clicked.connect(dialogue.accept)
            lay.addWidget(close)
            dialogue.exec_()

        def current_profile(self):
            country, medium = self.country.currentData(), self.delivery.currentData()
            return profile_key(country, medium, self.satellite.currentData() if medium == "s" else "")

        def display_channels(self, *_):
            """Filter the owner-curated channel list without losing scan data."""
            rows=getattr(self,"current_rows",[])
            query=self.channel_search.text().strip().casefold()
            filter_name=self.channel_filter.currentText()
            selected=self.channel_list.currentItem()
            current_key=selected.data(Qt.UserRole) if selected else None
            self.visible_rows=[row for row in rows if row["included"] and
                (not query or query in row["name"].casefold() or
                 query in format_frequency(row["channel"]).casefold()) and
                (filter_name=="All" or
                 (filter_name=="Favorites" and row["favorite"]) or
                 (filter_name=="Television" and row["kind"]=="tv") or
                 (filter_name=="Radio" and row["kind"]=="radio") or
                 (filter_name=="Free-to-air" and not row["encrypted"]))]
            self.channels=[row["channel"] for row in self.visible_rows]
            self.channel_list.clear()
            restore=None
            for idx,row in enumerate(self.visible_rows):
                channel=row["channel"]
                label=("★ " if row["favorite"] else "")+channel.name
                label+=("  🔒" if channel.encrypted else "")
                entry=QListWidgetItem(label)
                entry.setToolTip(("Radio" if row["kind"]=="radio" else "Television")+
                    " · "+format_frequency(channel)+
                    " · service ID "+str(channel.service_id)+
                    (" · Encrypted" if channel.encrypted else ""))
                entry.setData(Qt.UserRole,row["key"])
                self.channel_list.addItem(entry)
                if row["key"]==current_key:restore=idx
            if restore is not None:self.channel_list.setCurrentRow(restore)
            self.channel_list.setToolTip(
                "Double-click a channel to tune. Only verified scan results "
                "prove actual service discovery; old imported lists are unverified.")

        def refresh_channels(self, *_):
            country,medium=self.country.currentData(),self.delivery.currentData()
            profile=self.current_profile()
            expected=Path.home()/".config/tihulu-tv-center"/("channels-"+profile+".conf")
            if expected.is_file():
                scanned=read_channels([expected])
                source_label="Saved DVBv5 scan · "+profile
            elif country=="DE" and medium=="t":
                scanned=discover_channels()
                source_label="Historical Germany imports · UNVERIFIED"
            else:
                scanned=[]
                source_label="No scanned services for "+profile
            self.all_channels=sorted(scanned,key=lambda c:(c.frequency,c.name.casefold()))
            curated=self.preferences.rows(profile,self.all_channels)
            self.current_rows=curated
            self.display_channels()
            new_count=sum(1 for r in curated if r["new"])
            self.list_origin.setText(
                source_label+"\n"+
                str(len(self.all_channels))+" stored · "+
                str(len(self.channels))+" visible · "+
                str(new_count)+" awaiting review"+
                ("\nOld channel names are not evidence of current RF lock."
                 if "UNVERIFIED" in source_label else ""))
            if not self.scanner.running:
                self.statusbar.setText(source_label)

        def open_channel_manager(self):
            if not getattr(self, "all_channels", []):
                QMessageBox.information(self, "No channels", "Scan first or import an existing channel file.")
                return
            if edit_channels(self, self.preferences, self.current_profile(), self.all_channels):
                self.refresh_channels()

        def open_ai_settings(self):
            open_ai_settings(self, self.ai, self.sync_ai_settings)

        def refresh_ai_banner(self):
            try:
                from .ai_provision import StarterAI
                state = StarterAI(self.ai).status()
                ready = (state["whisper_engine_ready"] and state["tiny_model_ready"]
                         and state["translation_three_languages_ready"])
                self.ai_banner.setText(
                    ("Offline AI ready · Whisper + DE/EN/TR Translator"
                     if ready else "Offline AI incomplete · Open AI Model Market to install starter pack")
                    + " · ASR " + ("ON" if self.ai.values["asr_enabled"] else "OFF")
                    + " / Translation " + ("ON" if self.ai.values["translation_enabled"] else "OFF"))
            except (ImportError, OSError, RuntimeError) as exc:
                self.ai_banner.setText("AI setup check failed: " + str(exc)[:120])

        def sync_ai_settings(self):
            self.refresh_ai_banner()
            self.model.setText(self.ai.values["model_path"])
            self.apply_mode()
            self.statusbar.setText("AI settings saved. Transcription/translation operate only when enabled.")

        def import_channels(self):
            file, _ = QFileDialog.getOpenFileName(
                self, "Choose DVBv5 channels.conf", str(Path.home()),
                "DVBv5 config (*.conf);;All files (*)")
            if not file:
                return
            target = Path.home() / ".config/tihulu-tv-center/channels.conf"
            target.parent.mkdir(parents=True, exist_ok=True)
            from shutil import copyfile
            if Path(file).resolve() != target.resolve():
                copyfile(file, target)
            self.refresh_channels()

        def scan_channels(self):
            if self.scanner.running:
                QMessageBox.information(self, "Scan running", "A scan is already active.")
                return
            if self.capture.thread and self.capture.thread.is_alive():
                QMessageBox.warning(self, "Receiver busy", "Stop live TV before scanning.")
                return
            country, medium = self.country.currentData(), self.delivery.currentData()
            satellite = self.satellite.currentData() if medium == "s" else "S42E0"
            port = self.diseqc.currentData() if medium == "s" else None
            adapter = self.capture.adapter
            label = (SATELLITES[satellite] + " · DVB-S/S2" if medium == "s" else
                     f"{PROFILES[country]['name']} · {MODES[medium]}")
            if medium == "s":
                question = (label + "\n\n" + satellite_hardware_note() +
                            "\n\nOnly continue with a dedicated DVB-S/S2 tuner connected to the LNB.")
            else:
                question = (label + "\n\nScan the real connected antenna/cable now?")
            if QMessageBox.question(self, "Automatic full scan",
                question + "\n\nExisting channels and favorites are preserved if no results are found."
            ) != QMessageBox.Yes:
                return
            self.stop_scan_btn.setEnabled(True)
            self.scan_monitor = ScanMonitor(self, self.cancel_scan, label)
            self.scan_monitor.show()
            self.statusbar.setText(label + " · scanning")
            def worker():
                try:
                    result = self.scanner.run(
                        country, medium, adapter, satellite=satellite, diseqc_port=port,
                        notify=lambda obj: self.capture.emit("scan_progress", obj))
                    self.capture.emit("scan", (True, f"{result['channels']} services on "
                                        f"{result['frequencies']} real frequencies ({label})"))
                except (ScanError, ValueError, OSError, RuntimeError) as exc:
                    self.capture.emit("scan", (False, str(exc)))
            threading.Thread(target=worker, daemon=True, name="tihulu-tv-auto-scan").start()

        def cancel_scan(self):
            self.scanner.cancel()
            self.stop_scan_btn.setEnabled(False)
            self.statusbar.setText("Cancelling scan; existing channel lists remain preserved")

        def scan_from_file(self):
            """Kaffeine-style regional DVBv5 scan source; real tuner still scans."""
            if self.delivery.currentData() == "s":
                QMessageBox.information(self, "Satellite scanning",
                    "Select a satellite and its LNB/DiSEqC source above, then use automatic satellite scan.")
                return
            if self.scanner.running or (self.capture.thread and self.capture.thread.is_alive()):
                QMessageBox.warning(self, "Receiver busy", "Stop TV or an existing scan first.")
                return
            initial, _ = QFileDialog.getOpenFileName(
                self, "Kaffeine-style DVBv5 initial frequency table — choose local transmitter",
                "/usr/share/dvb", "DVBv5 scan tables (*)")
            if not initial:
                return
            country, medium = self.country.currentData(), self.delivery.currentData()
            label = f"{PROFILES[country]['name']} · {MODES[medium]} · {Path(initial).name}"
            self.scan_monitor = ScanMonitor(self, self.cancel_scan, label)
            self.scan_monitor.show()
            self.stop_scan_btn.setEnabled(True)
            self.statusbar.setText("Scanning real tuner with " + str(Path(initial).name))
            adapter = self.capture.adapter
            def worker():
                try:
                    result = self.scanner.run_from_initial_file(
                        initial, country, medium, adapter,
                        notify=lambda obj: self.capture.emit("scan_progress", obj))
                    self.capture.emit("scan", (True,
                        f"{result['channels']} services decoded on "
                        f"{result['frequencies']} frequencies from {Path(initial).name}"))
                except (ScanError, ValueError, OSError, RuntimeError) as exc:
                    self.capture.emit("scan", (False, str(exc)))
            threading.Thread(target=worker, daemon=True,
                             name="tihulu-tv-region-scan").start()

        def play(self):
            idx=self.channel_list.currentRow()
            if not 0<=idx<len(self.channels):
                QMessageBox.information(self,"Select a channel",
                    "Choose a channel from the list; stored channel names alone do not verify reception.")
                return
            channel=self.channels[idx]
            self.stop()
            self.last_playback_error=False
            self.player_hint.setText(
                "Tuning "+channel.name+"…\nWaiting for real DVB transport packets")
            self.player_hint.show()
            self.playback_detail.setText(
                "TUNE REQUESTED · "+channel.name+" · "+
                format_frequency(channel)+" · service "+str(channel.service_id))
            self.playback_diagnostics.append(
                "Tune request: "+channel.name+" / "+format_frequency(channel)+
                " · Scan file: "+str(channel.path))
            try:
                self.capture.start(channel,int(self.video.winId()),
                                   self.hw.currentText(),self.renderer.currentText())
                self.apply_mode()
            except (RuntimeError,OSError,ValueError) as exc:
                self.last_playback_error=True
                message="Tune failed: "+str(exc)
                self.player_hint.setText(message)
                self.playback_detail.setText(message)
                self.playback_diagnostics.append(message)
                QMessageBox.warning(self,"DVB tune failed",message)

        def stop(self):
            self.capture.stop()
            if hasattr(self,"player_hint"):
                self.player_hint.setText("Receiver stopped · select a channel to watch")
                self.player_hint.show()
            if hasattr(self,"playback_detail") and not self.last_playback_error:
                self.playback_detail.setText(
                    "Receiver stopped · USB/DVB device released by this application")

        def retry_compat(self):
            """Explicit fallback for XWayland/GL renderer problems."""
            self.renderer.setCurrentText("x11-compat")
            self.play()

        def open_playback_logs(self):
            from PyQt5.QtWidgets import QDialog
            dialog=QDialog(self)
            dialog.setWindowTitle("Real DVB tuning and MPV logs")
            dialog.resize(800,540)
            layout=QVBoxLayout(dialog)
            viewer=QTextEdit(dialog)
            viewer.setReadOnly(True)
            parts=[]
            for name,path in (("DVBv5 tuner",self.capture.zap_log_path),
                              ("MPV player",self.capture.mpv_log_path)):
                if not path or not Path(path).is_file():
                    parts.append(name+": No log file for this session")
                else:
                    try:
                        # Read only a bounded tail; never claim success based
                        # on process startup or a historical channel name.
                        with Path(path).open("rb") as stream:
                            stream.seek(0,2)
                            stream.seek(max(0,stream.tell()-16000))
                            txt=stream.read(16000).decode("utf-8","replace")
                        parts.append(name+" · "+str(path)+"\n"+txt)
                    except OSError as exc:
                        parts.append(name+": "+str(exc))
            viewer.setPlainText("\n\n".join(parts))
            layout.addWidget(viewer)
            close=QPushButton("Close")
            close.clicked.connect(dialog.accept)
            layout.addWidget(close)
            dialog.exec_()

        def choose_model(self):
            file, _ = QFileDialog.getOpenFileName(self, "Select installed multilingual Whisper GGML model", str(Path.home()), "Whisper GGML models (*.bin);;All files (*)")
            if file:
                self.model.setText(file)
                self.ai.update({"model_path": file})
                self.ai.configure_environment()
                self.apply_mode()

        def install_pack(self):
            file, _ = QFileDialog.getOpenFileName(self, "Install offline Argos language pack", str(Path.home()), "Argos packages (*.argosmodel)")
            if not file:
                return
            if QMessageBox.question(self, "Install local package", "Install the selected local translation package? No network download occurs.") != QMessageBox.Yes:
                return
            try:
                name = install_argos_pack(file)
                QMessageBox.information(self, "Installed", name + " installed for offline translation.")
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                QMessageBox.warning(self, "Translation pack", str(exc))

        def apply_mode(self, *_):
            modes = ["off", "teletext", "asr", "auto", "page"]
            mode = modes[self.mode.currentIndex()]
            if mode in ("asr", "auto") and not self.ai.values["asr_enabled"]:
                self.statusbar.setText("ASR is optional and OFF. Enable in Settings → Model Market.")
                mode = "off" if mode == "asr" else "teletext"
            target = (self.lang_out.currentText() if self.ai.values["translation_enabled"]
                      else self.lang_in.currentText())
            self.capture.set_captions(mode, self.page.value(),
                                      self.lang_in.currentText(), target,
                                      self.model.text())

        def snapshot(self):
            return {"source": "live_native_dvb" if self.capture.zap and self.capture.zap.poll() is None else "offline",
                    "channel": self.capture.channel.name if self.capture.channel else None,
                    "caption": dict(self.latest),
                    "subtitle_mode": self.capture.caption_mode,
                    "teletext_page": self.capture.page,
                    "supported_languages": ["tr", "de", "en"],
                    "web_video": "not_available_in_pages_preview",
                    "pi5_hardware_verified": False}

        def toggle_bridge(self, enabled):
            if enabled:
                try:
                    self.bridge = TVBridge(self.snapshot, lambda p: self.capture.set_captions(
                        "page", p, self.lang_in.currentText(), self.lang_out.currentText(), self.model.text()),
                        commands=self.web_commands.submit)
                    info = self.bridge.start()
                    self.bridge_token.setText(info["token"])
                    self.statusbar.setText("Local bridge: " + info["url"] + " — loopback only")
                except OSError as exc:
                    self.bridge_toggle.blockSignals(True)
                    self.bridge_toggle.setChecked(False)
                    self.bridge_toggle.blockSignals(False)
                    QMessageBox.warning(self, "Web bridge", str(exc))
            elif self.bridge:
                self.bridge.stop()
                self.bridge = None
                self.bridge_token.clear()

        def poll(self):
            for _ in range(15):
                try:
                    kind, info = self.capture.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "caption":
                    self.latest = info
                    original = info.get("original", "")
                    translated = info.get("translated")
                    if translated and translated != original:
                        body = (info.get("source_language", "Broadcast").upper() + ": " + original +
                                "\n" + info.get("target_language", "Translation").upper() + ": " + translated)
                    else:
                        body = original
                    self.subtitle.setText(body + "\nSource: " + info.get("source", "unknown"))
                elif kind == "scan_progress":
                    if isinstance(info, dict) and self.scan_monitor:
                        self.scan_monitor.feed(info)
                        if info.get("kind") == "status":
                            self.statusbar.setText(info.get("text", "Scanning…"))
                elif kind == "scan":
                    ok, message = info
                    self.stop_scan_btn.setEnabled(False)
                    if self.scan_monitor:
                        self.scan_monitor.feed({"kind": "complete" if ok else "failed",
                                                "count": len(getattr(self.scan_monitor, "seen", [])),
                                                "text": message})
                    self.refresh_channels()
                    self.statusbar.setText("Scan: " + ("completed" if ok else "failed") + " — " + message)
                    if ok:
                        self.open_channel_manager()
                elif kind == "measurement":
                    if "error" in info:
                        self.signal_result.setText("Signal tool error: " + info["error"])
                    else:
                        self.signal_result.setText(
                            f"C/N: {info['cn_min_db']}–{info['cn_max_db']} dB | "
                            f"UCB change: {info['ucb_delta']} | "
                            f"Loss indications: {info['loss_indications']} | "
                            f"Readings: {info['lock_readings']}")
                elif kind == "verified_stream":
                    self.player_hint.hide()
                    self.playback_detail.setText(
                        "REAL DVB TRANSPORT VERIFIED · "+str(info.get("channel"))+
                        " · service "+str(info.get("service_id"))+
                        " · "+str(info.get("packets"))+" packets inspected")
                    self.playback_diagnostics.append(
                        "Real MPEG-TS packets and selected PAT/PMT observed. "
                        "Video rendering is a separate step.")
                    self.last_playback_error=False
                elif kind in ("status", "warning", "error"):
                    message=str(info)
                    if kind=="error":
                        self.last_playback_error=True
                        self.player_hint.setText(
                            "Cannot play this DVB service\\n\\n"+
                            message+"\\n\\nSee Reception & diagnostics.")
                        self.player_hint.show()
                        self.playback_detail.setText("PLAYBACK FAILED · "+message)
                        self.playback_diagnostics.append("ERROR · "+message)
                        self.statusbar.setText("Playback error · "+message)
                        # Release only our own tuner/player processes.
                        self.capture.stop()
                    elif kind=="warning":
                        self.playback_diagnostics.append("WARNING · "+message)
                        if not self.last_playback_error:
                            self.statusbar.setText(message)
                    elif not self.last_playback_error:
                        self.playback_diagnostics.append("STATUS · "+message)
                        self.statusbar.setText(message)

        def closeEvent(self, event):
            self.scanner.cancel()
            if self.bridge:
                self.bridge.stop()
            self.stop()
            event.accept()

    app = QApplication(sys.argv)
    w = Window()
    w.show()
    return app.exec_()
