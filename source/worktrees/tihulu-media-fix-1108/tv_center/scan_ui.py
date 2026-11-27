"""Owner-triggered scan monitor: measured signal, frequencies and discovered services.

Indeterminate progress is intentional: radio frequency sweeps do not report
a trustworthy total number of frequencies/channels to be found.
"""
from __future__ import annotations
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QListWidget, QTextEdit, QPushButton)


class ScanMonitor(QDialog):
    def __init__(self, parent, cancel_scan, title="Live channel scan"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(770, 620)
        self.seen = set()
        layout = QVBoxLayout(self)
        self.stage = QLabel("Waiting for real DVB scan")
        self.stage.setWordWrap(True)
        layout.addWidget(self.stage)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # no fake percentage
        layout.addWidget(self.progress)
        self.signal = QLabel("Signal/C/N/UCB: not measured yet")
        self.signal.setWordWrap(True)
        layout.addWidget(self.signal)
        self.frequency = QLabel("Frequency: waiting for scanner")
        layout.addWidget(self.frequency)
        self.counter = QLabel("Services resolved: 0 (expected during Stage 1)")
        layout.addWidget(self.counter)
        self.channels = QListWidget()
        layout.addWidget(self.channels, 2)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(400)
        self.log.setMaximumHeight(160)
        layout.addWidget(self.log, 1)
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel scan")
        self.cancel_button.clicked.connect(cancel_scan)
        self.close_button = QPushButton("Close monitor")
        self.close_button.clicked.connect(self.hide)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def feed(self, info):
        kind = info.get("kind")
        stage = info.get("stage", 1)
        if kind == "status":
            description = info.get("text", "")
            if stage == 1:
                description += " · service names are resolved in Stage 2"
            self.stage.setText("Stage " + str(stage) + " · " + description)
        elif kind == "found":
            name = info.get("channel", "")
            freq = info.get("frequency")
            key = (name, freq)
            if key not in self.seen:
                self.seen.add(key)
                from .core import Channel, format_frequency
                suffix = (" · " + format_frequency(Channel(name, None, freq, None,
                            delivery=info.get("delivery", "")))) if freq else ""
                self.channels.addItem(name + suffix)
                self.channels.scrollToBottom()
            self.counter.setText("Services resolved: " + str(len(self.seen)))
        elif kind == "log":
            line = info.get("text", "")
            if line:
                self.log.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            if info.get("frequency_reported"):
                self.frequency.setText("Scanning actual frequency: "+str(info["frequency_reported"]))
            if info.get("demod_lock") is not None:
                lock="LOCKED (measured)" if info["demod_lock"] else "NO LOCK (measured)"
                parts=[lock]
                if info.get("cn_db") is not None:
                    parts.append("C/N "+str(info["cn_db"])+" dB")
                if info.get("signal_reading"):
                    parts.append("Signal "+str(info["signal_reading"]))
                if info.get("uncorrected_blocks") is not None:
                    parts.append("UCB "+str(info["uncorrected_blocks"]))
                self.signal.setText("  ·  ".join(parts))
        elif kind == "signal":
            m = info.get("metrics", {})
            if not m.get("available"):
                self.signal.setText("Signal metrics unavailable: " + m.get("reason", "not reported"))
            else:
                self.signal.setText(
                    "Signal receiver: lock samples " + str(m.get("lock_readings")) +
                    " · Power " + str(m.get("signal_last_dbm")) + " dBm" +
                    " · C/N " + str(m.get("cn_last_db")) + " dB" +
                    " · UCB increase " + str(m.get("ucb_delta")) +
                    " · loss signs " + str(m.get("loss_indications")))
        elif kind == "complete":
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self.cancel_button.setEnabled(False)
            self.stage.setText("Completed · "+str(info.get("count",0))+
                               " services decoded from actual DVB transport tables")
        elif kind == "failed":
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            self.cancel_button.setEnabled(False)
            self.stage.setText("Scan failed · "+info.get("text","Unknown error")+
                               " · previous saved channels were preserved")
