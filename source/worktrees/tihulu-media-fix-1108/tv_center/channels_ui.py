"""Qt organizer for scanned TV and radio services.

Favorites, explicit inclusion/exclusion and ordering are saved separately
from the real channel scan files. Re-scanning never erases those choices.
"""
from __future__ import annotations


def edit_channels(parent, preferences, profile, channels):
    from .core import format_frequency
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
        QListWidget, QListWidgetItem, QComboBox, QPushButton, QMessageBox)

    class ChannelEditor(QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle("Channel Manager · TV / Radio / Favorites")
            self.resize(760, 620)
            self.rows = preferences.rows(profile, channels)
            self.filter_mode = "All scanned"
            lay = QVBoxLayout(self)
            self.heading = QLabel("Scan results · choose which services to keep")
            lay.addWidget(self.heading)
            filter_line = QHBoxLayout()
            self.filters = QComboBox()
            self.filters.addItems(["All scanned", "Included", "Favorites", "New after scan",
                                   "Television", "Radio", "Encrypted"])
            self.filters.currentTextChanged.connect(self.refresh)
            filter_line.addWidget(self.filters)
            self.counter = QLabel()
            filter_line.addWidget(self.counter)
            lay.addLayout(filter_line)
            self.list = QListWidget()
            self.list.setAlternatingRowColors(True)
            self.list.itemDoubleClicked.connect(lambda _: self.toggle("included"))
            lay.addWidget(self.list, 1)
            actions = QHBoxLayout()
            for label, action in (("★ Favorite", "favorite"), ("Add / Remove", "included"),
                                  ("Move up", "up"), ("Move down", "down")):
                button = QPushButton(label)
                button.clicked.connect(lambda _, a=action: self.toggle(a))
                actions.addWidget(button)
            lay.addLayout(actions)
            bulk = QHBoxLayout()
            for label, action in (("Add all", "all"), ("Remove all", "none"),
                                  ("Add free-to-air", "fta")):
                button = QPushButton(label)
                button.clicked.connect(lambda _, a=action: self.bulk(a))
                bulk.addWidget(button)
            lay.addLayout(bulk)
            foot = QHBoxLayout()
            save = QPushButton("Save channel list & favorites")
            save.clicked.connect(self.save)
            close = QPushButton("Cancel")
            close.clicked.connect(self.reject)
            foot.addWidget(save)
            foot.addWidget(close)
            lay.addLayout(foot)
            self.refresh()

        def match(self, row):
            mode = self.filters.currentText()
            return (mode == "All scanned" or
                    (mode == "Included" and row["included"]) or
                    (mode == "Favorites" and row["favorite"]) or
                    (mode == "New after scan" and row["new"]) or
                    (mode == "Television" and row["kind"] == "tv") or
                    (mode == "Radio" and row["kind"] == "radio") or
                    (mode == "Encrypted" and row["encrypted"]))

        def refresh(self, *_):
            current = self.current_key()
            self.list.clear()
            for row in self.rows:
                if not self.match(row):
                    continue
                name = row["name"]
                icon = "★ " if row["favorite"] else "☆ "
                checkbox = "✓ " if row["included"] else "○ "
                kind = "RADIO" if row["kind"] == "radio" else "TV"
                flag = " [NEW]" if row["new"] else ""
                locked = " [encrypted]" if row["encrypted"] else ""
                label = f"{checkbox}{icon}{name} · {kind} · {format_frequency(row['channel'])}{flag}{locked}"
                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, row["key"])
                self.list.addItem(item)
                if row["key"] == current:
                    self.list.setCurrentItem(item)
            active = sum(bool(x["included"]) for x in self.rows)
            fav = sum(bool(x["favorite"]) for x in self.rows)
            self.counter.setText(f"{len(self.rows)} found · {active} included · {fav} favorites")

        def current_key(self):
            selected = self.list.currentItem()
            return selected.data(Qt.UserRole) if selected else None

        def toggle(self, action):
            key = self.current_key()
            if key is None:
                return
            pos = next((i for i, row in enumerate(self.rows) if row["key"] == key), -1)
            if pos < 0:
                return
            if action == "favorite":
                self.rows[pos]["favorite"] = not self.rows[pos]["favorite"]
            elif action == "included":
                self.rows[pos]["included"] = not self.rows[pos]["included"]
            elif action in ("up", "down"):
                other = pos + (-1 if action == "up" else 1)
                if 0 <= other < len(self.rows):
                    self.rows[pos], self.rows[other] = self.rows[other], self.rows[pos]
            self.refresh()

        def bulk(self, action):
            for row in self.rows:
                if action == "all": row["included"] = True
                elif action == "none": row["included"] = False
                elif action == "fta": row["included"] = not row["encrypted"]
            self.refresh()

        def save(self):
            try:
                preferences.save_rows(profile, self.rows)
            except (OSError, ValueError, TypeError) as exc:
                QMessageBox.warning(self, "Channel list not saved", str(exc))
                return
            self.accept()

    return ChannelEditor().exec_() == 1
