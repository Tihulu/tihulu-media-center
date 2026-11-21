# SPDX-License-Identifier: GPL-2.0-or-later
"""Follow the native player's explicit theme, including already-open AI dialogs."""
def install_theme(app):
    if hasattr(app, "_tihulu_theme_timer"):
        return
    from PyQt5.QtCore import QSettings, QTimer
    from PyQt5.QtGui import QColor, QPalette
    from PyQt5.QtWidgets import QStyleFactory
    system = QPalette(app.palette())
    app.setStyle(QStyleFactory.create("Fusion"))
    prefs = QSettings("TIHULU", "Appearance")
    state = [None]

    def refresh():
        prefs.sync()
        mode = prefs.value("theme", "system")
        if mode == state[0]:
            return
        state[0] = mode
        if mode == "system":
            app.setPalette(system)
            return
        dark = mode == "dark"
        p = QPalette()
        colors = {
            QPalette.Window: "#18222d" if dark else "#f4f6f8",
            QPalette.Base: "#111a23" if dark else "#ffffff",
            QPalette.AlternateBase: "#293b4b" if dark else "#e5ebf1",
            QPalette.Button: "#293b4b" if dark else "#e5ebf1",
            QPalette.ToolTipBase: "#111a23" if dark else "#ffffff",
            QPalette.ToolTipText: "#ecf1f6" if dark else "#17212b",
            QPalette.Highlight: "#145c8e", QPalette.HighlightedText: "#ffffff",
            QPalette.Link: "#83cbff" if dark else "#075d96",
            QPalette.Mid: "#637589" if dark else "#8999a9",
            QPalette.Light: "#42576a" if dark else "#ffffff",
            QPalette.Dark: "#0d141b" if dark else "#687787",
        }
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            for role, color in colors.items():
                p.setColor(group, role, QColor(color))
            for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
                ink = ("#a6b3c0" if dark else "#596673") if group == QPalette.Disabled else ("#ecf1f6" if dark else "#17212b")
                p.setColor(group, role, QColor(ink))
        app.setPalette(p)

    timer = QTimer(app)
    timer.timeout.connect(refresh)
    app._tihulu_theme_timer = timer
    refresh()
    timer.start(750)
