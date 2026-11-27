"""Optional GUI for offline media subtitles, launched from native Kaffeine menu.

The processing runs in a Qt worker thread and uses the same installed GPU
Whisper/Argos/NLLB engines as TV. Only user-selected local media are read.
Lyrics HTTPS queries happen only after a user explicitly authorizes them.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys


def main(args=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",default="")
    options=parser.parse_args(args)

    from PyQt5.QtCore import Qt, QThread, QObject, pyqtSignal
    from PyQt5.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
        QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
        QVBoxLayout, QWidget, QProgressBar)

    if os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    app=QApplication.instance() or QApplication(["TIHULU offline media AI"])

    class Runner(QObject):
        done=pyqtSignal(object)
        def __init__(self, params):
            super().__init__()
            self.params=params
        def run(self):
            from .media_ai import create_subtitles
            try:
                self.done.emit(create_subtitles(**self.params))
            except Exception as exc:
                self.done.emit({"status":"error","reason":str(exc)[:550]})

    class Window(QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("TIHULU · Offline Video / Audio AI + Timed Lyrics")
            self.resize(780, 450)
            self.setMinimumWidth(550)
            self.thread=None
            self.worker=None
            self.setStyleSheet(
                "QDialog{background:#0e1b27;color:#dcebf4}"
                "QGroupBox{border:1px solid #365266;border-radius:7px;"
                "margin-top:15px;padding-top:8px}"
                "QGroupBox::title{left:12px;color:#bcdbef}"
                "QPushButton{background:#22415a;color:#fff;border-radius:5px;"
                "border:1px solid #395e78;padding:8px}"
                "QPushButton:hover{background:#296184}"
                "QLineEdit,QComboBox{background:#192c3b;color:#fff;"
                "border:1px solid #4a6476;padding:6px}"
                "QCheckBox,QLabel{color:#dcebf4}")
            outer=QVBoxLayout(self)
            intro=QLabel(
                "Your media stays local. GPU Whisper and installed offline "
                "translators generate a timed .SRT subtitle sidecar. "
                "Music transcription is optional; synced lyrics need a "
                "matching .LRC file or an explicitly approved metadata search.")
            intro.setWordWrap(True)
            outer.addWidget(intro)

            inputRow=QHBoxLayout()
            self.path=QLineEdit(str(Path(options.input).expanduser()))
            self.path.setPlaceholderText("Choose a video, recording or music file…")
            browse=QPushButton("Browse…")
            browse.clicked.connect(self.pick_file)
            inputRow.addWidget(self.path,1)
            inputRow.addWidget(browse)
            outer.addLayout(inputRow)

            group=QGroupBox("Speech / Translation")
            form=QFormLayout(group)
            self.lang=QComboBox()
            self.lang.setEditable(True)
            self.lang.addItems(["auto","de","en","tr","fr","es","pl","ar","ja"])
            self.lang.setCurrentText("auto")
            self.original=QCheckBox("Include original transcript")
            self.original.setChecked(True)
            self.en=QCheckBox("Translate to English")
            self.tr=QCheckBox("Translate to Turkish")
            self.en.setChecked(True)
            self.tr.setChecked(True)
            self.singing=QCheckBox("Include song vocals / music · lower accuracy")
            form.addRow("Spoken / sung language",self.lang)
            form.addRow(self.original)
            form.addRow(self.en)
            form.addRow(self.tr)
            form.addRow(self.singing)
            outer.addWidget(group)

            song=QGroupBox("Optional synced lyrics")
            sf=QFormLayout(song)
            self.useLyrics=QCheckBox(
                "Use timed lyrics instead of ASR (look for .lrc next to media)")
            self.artist=QLineEdit()
            self.title=QLineEdit()
            self.fetch=QCheckBox("Find lyrics online (LRCLIB · metadata only · no token)")
            self.fetch.setToolTip(
                "Your artist/title and optional duration are transmitted "
                "to LRCLIB only when this box is checked and you press Generate.")
            sf.addRow(self.useLyrics)
            sf.addRow("Artist",self.artist)
            sf.addRow("Track",self.title)
            sf.addRow(self.fetch)
            outer.addWidget(song)
            self.overwrite=QCheckBox("Replace existing .srt (off by default)")
            outer.addWidget(self.overwrite)

            buttons=QHBoxLayout()
            self.go=QPushButton("Generate offline subtitles")
            self.go.clicked.connect(self.start)
            buttons.addStretch()
            buttons.addWidget(self.go)
            outer.addLayout(buttons)
            self.status=QLabel("Choose a local media file to begin.")
            self.status.setWordWrap(True)
            outer.addWidget(self.status)
            self.busy=QProgressBar()
            self.busy.setRange(0,1)
            self.busy.setValue(0)
            outer.addWidget(self.busy)

        def pick_file(self):
            selected,_=QFileDialog.getOpenFileName(
                self,"Open local media",str(Path.home()),
                "Media (*.mkv *.mp4 *.mov *.webm *.avi *.ts *.m2ts "
                "*.flac *.mp3 *.wav *.m4a *.aac *.ogg *.opus);;All files (*)")
            if selected:
                self.path.setText(selected)

        def start(self):
            source=self.lang.currentText().strip()
            targets=tuple(
                value for value,widget in (("en",self.en),("tr",self.tr))
                if widget.isChecked())
            if not self.original.isChecked() and not targets:
                QMessageBox.information(
                    self,"Subtitle output","Select original and/or a translated language.")
                return
            if self.fetch.isChecked() and not self.useLyrics.isChecked():
                QMessageBox.information(
                    self,"Lyrics mode","Check Use timed lyrics to authorize this lookup.")
                return
            if self.fetch.isChecked() and QMessageBox.question(
                self,"Confirm lyric metadata lookup",
                "Send the selected artist/title (and duration if available) "
                "to LRCLIB to find synchronized lyrics? No audio is uploaded."
                )!=QMessageBox.Yes:
                return
            params={
                "filename":self.path.text().strip(),"source":source,
                "targets":targets,"music":self.singing.isChecked(),
                "lyrics":self.useLyrics.isChecked(),
                "fetch_lyrics":self.fetch.isChecked(),
                "artist":self.artist.text().strip(),
                "track":self.title.text().strip(),
                "overwrite":self.overwrite.isChecked()
            }
            self.go.setEnabled(False)
            self.busy.setRange(0,0)
            self.status.setText("Processing locally · please keep this window open. "
                                "No remote audio or text inference.")
            self.thread=QThread(self)
            self.worker=Runner(params)
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.done.connect(self.completed)
            self.worker.done.connect(self.thread.quit)
            self.thread.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            self.thread.start()

        def completed(self, outcome):
            self.go.setEnabled(True)
            self.busy.setRange(0,1)
            self.busy.setValue(1)
            if outcome.get("status")=="completed":
                self.status.setText(
                    "Created: " + str(outcome.get("output")) +
                    "\nSubtitle cues: " + str(outcome.get("cues")) +
                    " · source: " + str(outcome.get("backend")) +
                    "\nOpen the same media in Kaffeine and choose its .srt. "
                    "Model availability/translation errors: " +
                    str(outcome.get("translation_warning_count",0)))
            else:
                self.status.setText(
                    "Unable to generate subtitles: "+str(outcome.get("reason","unknown")))

        def closeEvent(self,event):
            if self.thread is not None and self.thread.isRunning():
                event.ignore()
                QMessageBox.information(
                    self,"Processing ongoing",
                    "Processing is still running. The local subtitle worker "
                    "must finish before closing the window.")
                return
            super().closeEvent(event)

    window=Window()
    window.show()
    return app.exec_()


if __name__=="__main__":
    raise SystemExit(main())
