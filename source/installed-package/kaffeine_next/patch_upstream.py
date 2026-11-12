#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Reproducible changes to KDE Kaffeine 2.0.19 (no second DVB tuner).

Kaffeine continues to own scanning, EPG, Teletext, stream filtering and
libVLC. Only explicit user actions start Whisper and translation.
"""
from pathlib import Path
import sys

UPSTREAM = "https://github.com/KDE/kaffeine.git"
TAG = "v2.0.19"
REVISION = "e7ea15b86dafed3b20b151cbcb080578ab8e2d5c"
PATHS = ("src/mainwindow.cpp", "src/mainwindow.h", "src/CMakeLists.txt",
         "src/dvb/dvbliveview.cpp",
         "src/dvb/dvbliveview_p.h", "src/dvb/dvbmanager.cpp", "src/dvb/dvbtab.cpp",
         "src/dvb/dvbtab.h", "src/dvb/dvbconfigdialog.cpp", "src/dvb/dvbscandialog.cpp",
         "src/dvb/dvbscandialog.h", "src/backend-vlc/vlcmediawidget.cpp",
         "src/backend-vlc/vlcmediawidget.h",
         "src/mediawidget.cpp", "src/mediawidget.h", "src/osdwidget.cpp",
         "src/osdwidget.h", "src/main.cpp", "src/dvb/dvbepg.cpp",
         "src/sqlinterface.h")

def fix_sql_free_key(source: str) -> str:
    """Fix Kaffeine 2.0.19's invalid QMap iterator in scan/channel import.

    Guard the expected implementation shape to avoid applying this
    narrowly targeted fix against an unrelated upstream revision.
    """
    old = "std::prev(container.constEnd(), -1)"
    fixed = "std::prev(container.constEnd())"
    if "if (!container.isEmpty()) {" not in source:
        raise ValueError("Unexpected Kaffeine SQL allocator: missing empty-container guard")
    if source.count(old) == 1:
        return source.replace(old, fixed)
    if old not in source and source.count(fixed) == 1:
        return source
    raise ValueError("Unexpected Kaffeine SQL allocator: cannot identify invalid iterator")


def transform(files):
    files = dict(files)
    # Used by the native caption bridge and global player changes.
    # Keep this bound before any source transformation or conditional path.
    mediac = "src/mediawidget.cpp"
    def change(path, before, after):
        source = files[path]
        if after in source:
            return
        if source.count(before) != 1:
            raise ValueError("Unexpected Kaffeine source; patch refused: "+path+" "+repr(before[:48]))
        files[path] = source.replace(before, after)

    # Integrate DAB+ into the same Kaffeine window and its existing
    # libVLC player. The optional upstream welle-cli backend runs only
    # on deliberate Radio -> Start; no second Qt/WebUSB player window.
    main = "src/mainwindow.cpp"
    change(main, '#include "playlist/playlisttab.h"\n',
           '#include "playlist/playlisttab.h"\n#include "tihulu_radio_tab.h"\n')
    change(main, '''#endif /* HAVE_DVB == 1 */
	tabBar->setShape(QTabBar::RoundedWest);''',
           '''#endif /* HAVE_DVB == 1 */
	tabBar->addTab(QIcon::fromTheme(QLatin1String("audio-radio")),
		i18n("Radio (DAB+)"));
	tabBar->setShape(QTabBar::RoundedWest);''')
    change(main, '''#endif /* HAVE_DVB == 1 */

	currentTabIndex = StartTabId;''',
           '''#endif /* HAVE_DVB == 1 */

	// Native radio page shares Kaffeine's existing libVLC MediaWidget.
	// Its optional welle-cli backend is explicitly started and stopped.
	TabBase *radioTab = new TihuluRadioTab(mediaWidget, this);
	tabs.append(radioTab);
	stackedLayout->addWidget(radioTab);

	currentTabIndex = StartTabId;''')
    # Keep original Playback libVLC widget. Local file AI controls live
    # INSIDE its own tab; the older launched media-captions-ui remains
    # available only as an optional legacy menu entry.
    change(main, '#include "tihulu_radio_tab.h"\n',
           '#include "tihulu_radio_tab.h"\n#include "tihulu_media_panel.h"\n'
           '#include "tihulu_web_tv_dialog.h"\n')
    change(main, '''	void activate() override
	{
		layout()->addWidget(mediaWidget);
		mediaWidget->setFocus();
	}

private:
	MediaWidget *mediaWidget;
};''',
           '''	void activate() override
	{
		// Insert at TOP on every activation; re-adding at the end
		// would put video UNDER the AI toolbar after the next tab switch.
		static_cast<QVBoxLayout *>(layout())->insertWidget(0, mediaWidget, 1);
		mediaWidget->setFocus();
	}
	void toggleDisplayMode(MediaWidget::DisplayMode mode) override {
        // Local-video fullscreen must also hide the Playback AI panel;
        // Kaffeine's base PlayerTab has an empty toggleDisplayMode().
        aiPanel->setVisible(mode==MediaWidget::NormalMode);
    }
	void setLocalFile(const QUrl &url) { aiPanel->setLocalFile(url); }
    bool prepareLocalFileOpen(const QUrl &url) {
        return aiPanel->prepareLocalFileOpen(url);
    }

private:
	MediaWidget *mediaWidget;
	TihuluMediaPanel *aiPanel;
};''')
    change(main, '''PlayerTab::PlayerTab(MediaWidget *mediaWidget_) : mediaWidget(mediaWidget_)
{
	QHBoxLayout *layout = new QHBoxLayout(this);
	layout->setContentsMargins(0, 0, 0, 0);
}''',
           '''PlayerTab::PlayerTab(MediaWidget *mediaWidget_) : mediaWidget(mediaWidget_)
{
	QVBoxLayout *layout = new QVBoxLayout(this);
	layout->setContentsMargins(0, 0, 0, 0);
	layout->setSpacing(0);
	aiPanel = new TihuluMediaPanel(mediaWidget, this);
	layout->addWidget(mediaWidget, 1);
	layout->addWidget(aiPanel, 0);
}''')
    change(main, '''	QUrl copy(url);
	actionOpenRecent->addUrl(copy);''',
           '''	QUrl copy(url);
	// Keep local video/audio player *inside* this Playback tab.
	// Its optional AI captions are generated in the bottom panel.
	playerTab->setLocalFile(copy);
    // Optional, user-controlled full-file prepass. Prevent the playlist
    // from starting audible/video playback before the complete SRT exists.
    // On completion the same MediaWidget opens the file with its SRT.
    // Normal live-TV/radio, HTTP streams, Playlist and default file-open
    // behavior remain unchanged.
    if (copy.isLocalFile() && playerTab->prepareLocalFileOpen(copy)) {
        actionOpenRecent->addUrl(copy);
        if (currentTabIndex != PlayerTabId) activateTab(PlayerTabId);
        return;
    }
	actionOpenRecent->addUrl(copy);''')
    hdrmain = "src/mainwindow.h"
    change(hdrmain, '\t\tDvbTabId = 3\n',
           '\t\tDvbTabId = 3,\n\t\tRadioTabId = 4\n')
    change(hdrmain, '\tvoid playDvb();\n',
           '\tvoid playDvb();\n\tvoid playRadio();\n')
    change(main, '''void MainWindow::configureKeys()
{''',
           '''void MainWindow::playRadio()
{
	activateTab(RadioTabId);
}

void MainWindow::configureKeys()
{''')
    # Hardware lives as an actual native tab next to Radio, NOT a floating
    # dialog. The UI never USB-opens to determine a device's state.
    change(main, '#include "tihulu_radio_tab.h"\n',
           '#include "tihulu_radio_tab.h"\n#include "tihulu_hardware_tab.h"\n')
    change(main, '''	tabBar->addTab(QIcon::fromTheme(QLatin1String("audio-radio")),
		i18n("Radio (DAB+)"));
	tabBar->setShape(QTabBar::RoundedWest);''',
    '''	tabBar->addTab(QIcon::fromTheme(QLatin1String("audio-radio")),
		i18n("Radio (DAB+)"));
	tabBar->addTab(QIcon::fromTheme(QLatin1String("drive-removable-media")),
		i18n("Hardware"));
	tabBar->setShape(QTabBar::RoundedWest);''')
    change(main, '''	TabBase *radioTab = new TihuluRadioTab(mediaWidget, this);
	tabs.append(radioTab);
	stackedLayout->addWidget(radioTab);

	currentTabIndex = StartTabId;''',
    '''	TabBase *radioTab = new TihuluRadioTab(mediaWidget, this);
	tabs.append(radioTab);
	stackedLayout->addWidget(radioTab);
	TabBase *hardwareTab = new TihuluHardwareTab(
		static_cast<TihuluRadioTab *>(radioTab), dvbTab, mediaWidget,
		[this]() { activateTab(RadioTabId); },
		[this]() { activateTab(DvbTabId); }, this);
	tabs.append(hardwareTab);
	stackedLayout->addWidget(hardwareTab);

	currentTabIndex = StartTabId;''')
    hdrmain = "src/mainwindow.h"
    change(hdrmain, '''		RadioTabId = 4
''', '''		RadioTabId = 4,
		HardwareTabId = 5
''')
    change(hdrmain, '\tvoid playRadio();\n',
           '\tvoid playRadio();\n\tvoid playHardware();\n')
    change(main, '''void MainWindow::playRadio()
{
	activateTab(RadioTabId);
}

void MainWindow::configureKeys()''',
    '''void MainWindow::playRadio()
{
	activateTab(RadioTabId);
}

void MainWindow::playHardware()
{
	activateTab(HardwareTabId);
}

void MainWindow::configureKeys()''')

    change(main, '''#endif /* HAVE_DVB == 1 */
}

QAbstractButton *StartTab::addShortcut''',
           '''	button = addShortcut(i18n("&6 DAB+ Radio"),
		QIcon::fromTheme(QLatin1String("audio-radio")), this);
	button->setShortcut(Qt::Key_6);
	button->setWhatsThis(i18n("Open the native TIHULU DAB+ station library."));
	connect(button, SIGNAL(clicked(bool)), mainWindow, SLOT(playRadio()));
	gridLayout->addWidget(button, 1, 2);
#endif /* HAVE_DVB == 1 */
}

QAbstractButton *StartTab::addShortcut''')
    # Rebuild Start as a TIHULU home screen, while retaining the
    # original Kaffeine file/CD/DVD/TV actions and shortcuts.
    change(main, '''	setBackgroundRole(QPalette::Base);
	setAutoFillBackground(true);

	QGridLayout *gridLayout = new QGridLayout(this);''',
           '''	setObjectName(QLatin1String("tihuluHome"));
	setStyleSheet(QLatin1String(
		"QWidget#tihuluHome{background:#101d2d;color:#e2f6ff}"
		"QToolButton{background:#1b3b53;color:#f3fbff;"
		"border:1px solid #366b89;border-radius:9px;"
		"min-width:186px;padding:14px}"
		"QToolButton:hover{background:#215875}"
	));
	QVBoxLayout *frame=new QVBoxLayout(this);
	frame->setContentsMargins(24,18,24,18);
	auto *heading=new QLabel(i18n("TIHULU Media Center\\n"
		"TV · Radio · Video / Audio · Offline AI"),this);
	heading->setAlignment(Qt::AlignCenter);
	heading->setStyleSheet(QLatin1String(
		"font-size:24px;font-weight:700;color:#b6f6fe;padding:12px"));
	frame->addWidget(heading,0,Qt::AlignCenter);
	QGridLayout *gridLayout = new QGridLayout();''')
    change(main, '''	gridLayout->setSpacing(15);

	QAbstractButton *button =''',
           '''	gridLayout->setSpacing(12);
	// Keep the launcher near its title instead of sinking to the
	// bottom of large desktop windows. The remaining space is flexible.
	frame->addSpacing(8);
	frame->addLayout(gridLayout,0);
	frame->addStretch(1);
	QAbstractButton *button =''')
    change(main, '''	gridLayout->addWidget(button, 1, 2);
#endif /* HAVE_DVB == 1 */''',
           '''	gridLayout->addWidget(button, 1, 2);
	button = addShortcut(i18n("&7 Open Media + Offline AI"),
		QIcon::fromTheme(QLatin1String("video-x-generic")),this);
	button->setShortcut(Qt::Key_7);
	connect(button,SIGNAL(clicked()),mainWindow,SLOT(open()));
	gridLayout->addWidget(button,2,0,1,3);
#endif /* HAVE_DVB == 1 */''')
    # An explicit shortcut supports keyboard-only use without introducing
    # a second hardware-dialog window.
    change(main, '''	gridLayout->addWidget(button,2,0,1,3);
#endif /* HAVE_DVB == 1 */''',
    '''	gridLayout->addWidget(button,2,0,1,3);
	button = addShortcut(i18n("&8 Hardware and receiver ownership"),
		QIcon::fromTheme(QLatin1String("drive-removable-media")),this);
	button->setShortcut(Qt::Key_8);
	connect(button,SIGNAL(clicked()),mainWindow,SLOT(playHardware()));
	gridLayout->addWidget(button,3,0,1,3);
#endif /* HAVE_DVB == 1 */''')

    # Native Start tile uses Qt5 clicked(bool); clicked() has no matching
    # signal and silently leaves the Radio tile nonfunctional. Normalize
    # other Kaffeine home shortcuts for consistent pointer/keyboard access.
    # Only StartTab connectors are changed, not the general mainwindow.
    home_marker = 'class PlayerTab : public TabBase'
    home_end = files[main].index(home_marker)
    files[main] = (files[main][:home_end].replace(
        'SIGNAL(clicked())', 'SIGNAL(clicked(bool))')+
        files[main][home_end:])

    # Single bottom-bar recorder is available across Playback, TV, Radio
    # and Internet streams. Non-DVB sources are tracked only when libVLC
    # actually receives a URL; no stale source from a previous media type.
    change(main, '#include "tihulu_hardware_tab.h"\n',
           '#include "tihulu_hardware_tab.h"\n#include "tihulu_unified_recorder.h"\n')
    change(main, '''\tstackedLayout->addWidget(hardwareTab);

\tcurrentTabIndex = StartTabId;''',
    '''\tstackedLayout->addWidget(hardwareTab);
\t// Shared Record/Stop and Recordings library remain in the bottom
\t// transport bar on every tab, including Web TV and radio.
\tnew TihuluUnifiedRecorder(mediaWidget,dvbTab,controlBar,
		[this]() { activateTab(PlayerTabId); },this);

\tcurrentTabIndex = StartTabId;''')
    # Show truthful *stage completion*, not estimated USB/SDR timing.
    # Radio and DVB-T2 have separate adapters, but share the libVLC player.
    # Stop only app-owned radio workers before selecting the Television tab.
    change(main, '#include "tihulu_unified_recorder.h"\n',
           '#include "tihulu_unified_recorder.h"\n'
           '#include <QProgressBar>\n#include <QStatusBar>\n'
           '#include <QSignalBlocker>\n')
    change(main, '''	new TihuluUnifiedRecorder(mediaWidget,dvbTab,controlBar,
		[this]() { activateTab(PlayerTabId); },this);

	currentTabIndex = StartTabId;''',
    '''	new TihuluUnifiedRecorder(mediaWidget,dvbTab,controlBar,
		[this]() { activateTab(PlayerTabId); },this);
	// A real stage-based percentage stays visible on every native tab.
	QProgressBar *tihuluReceiverSwitchProgress = new QProgressBar(this);
	tihuluReceiverSwitchProgress->setObjectName(
		QLatin1String("tihuluReceiverSwitchProgress"));
	tihuluReceiverSwitchProgress->setRange(0,100);
	tihuluReceiverSwitchProgress->setValue(0);
	tihuluReceiverSwitchProgress->setFormat(
		i18n("SDR / TV handoff · ready"));
	tihuluReceiverSwitchProgress->setMinimumWidth(240);
	tihuluReceiverSwitchProgress->setVisible(false);
	statusBar()->addPermanentWidget(tihuluReceiverSwitchProgress,1);

	currentTabIndex = StartTabId;''')
    change(main, '''void MainWindow::activateTab(int tabIndex)
{
	currentTabIndex = tabIndex;
	tabBar->setCurrentIndex(tabIndex);''',
    '''void MainWindow::activateTab(int tabIndex)
{
	if (tabIndex < 0 || tabIndex >= tabs.size()) return;
	// Programmatic switches also trigger QTabBar::currentChanged.
	// Prevent nested handoffs and accidental double SDR shutdown.
	if (property("tihuluTabSwitchBusy").toBool()) return;
	setProperty("tihuluTabSwitchBusy",true);
	QProgressBar *progress = findChild<QProgressBar *>(
		QLatin1String("tihuluReceiverSwitchProgress"));
	const bool toTelevision = tabIndex == DvbTabId &&
		currentTabIndex != DvbTabId;
	const bool toRadio = tabIndex == RadioTabId &&
		currentTabIndex != RadioTabId;
	if (toTelevision) {
		const auto *radio = static_cast<TihuluRadioTab *>(tabs.at(RadioTabId));
		const bool radioOwned = radio->hardwareDabOwned() ||
			radio->hardwareAnalogOwned();
		if (progress) {
			progress->show();
			progress->setValue(10);
			progress->setFormat(
				i18n("%p% · TV selected; inspecting owned radio receiver"));
			progress->repaint();
		}
		if (radioOwned) {
			if (progress) {
				progress->setValue(35);
				progress->setFormat(
					i18n("%p% · invalidating radio and releasing SDR"));
				progress->repaint();
			}
			if (!static_cast<TihuluRadioTab *>(
				tabs.at(RadioTabId))->releaseForTelevision()) {
				if (progress) {
					progress->setValue(0);
					progress->setFormat(
						i18n("%p% · SDR release failed; TV switch cancelled"));
				}
				QSignalBlocker keepCurrent(tabBar);
				tabBar->setCurrentIndex(currentTabIndex);
				setProperty("tihuluTabSwitchBusy",false);
				return;
			}
		}
		if (progress) {
			progress->setValue(85);
			progress->setFormat(i18n(
				"%p% · radio released/idle; activating native DVB page"));
			progress->repaint();
		}
	}
	if (toRadio && progress) {
		progress->show();
		progress->setValue(70);
		progress->setFormat(i18n(
			"%p% · opening Radio without claiming SDR yet"));
		progress->repaint();
	}
	currentTabIndex = tabIndex;
	// The side bar may already have selected the target. For direct
	// Start/Home keyboard buttons, set it without recursive currentChanged.
	{
		QSignalBlocker noRecursiveTabChange(tabBar);
		tabBar->setCurrentIndex(tabIndex);
	}''')
    change(main, '''	tabs.at(currentTabIndex)->activate();

	emit displayModeChanged();
}''',
    '''	tabs.at(currentTabIndex)->activate();
	if (progress && (toTelevision || toRadio)) {
		progress->setValue(100);
		progress->setFormat(toTelevision ?
			i18n("%p% · TV tab ready; RF lock not yet measured") :
			i18n("%p% · Radio tab ready; SDR on-demand"));
	}
	setProperty("tihuluTabSwitchBusy",false);
	emit displayModeChanged();
}''')
    # Kaffeine hides the menu/toolbars in fullscreen, but QMainWindow's
    # QStatusBar remains visible by default. Our stage-based cyan handoff
    # widget lives IN that bar and must never overlay fullscreen video.
    # Restore the original status area immediately on leaving fullscreen,
    # including FullScreenReturnToMinimalMode -> MinimalMode transitions.
    change(main, '''\tMediaWidget::DisplayMode displayMode = mediaWidget->getDisplayMode();

\tswitch (displayMode) {''',
    '''\tMediaWidget::DisplayMode displayMode = mediaWidget->getDisplayMode();
\tconst bool tihuluFullVideo =
\t\tdisplayMode == MediaWidget::FullScreenMode ||
\t\tdisplayMode == MediaWidget::FullScreenReturnToMinimalMode;
\tstatusBar()->setVisible(!tihuluFullVideo);
\tif (tihuluFullVideo) {
\t\tQProgressBar *handoff = findChild<QProgressBar *>(
\t\t\tQLatin1String("tihuluReceiverSwitchProgress"));
\t\tif (handoff) handoff->hide();
\t}

\tswitch (displayMode) {''')
    # The main Television shortcut must not tune a DVB frontend when the
    # radio release failed and its tab transition was rejected.
    change(main, '''	activateTab(DvbTabId);
	dvbTab->playLastChannel();
}''',
    '''	activateTab(DvbTabId);
	if (currentTabIndex != DvbTabId) return;
	dvbTab->playLastChannel();
}''')

    media="src/mediawidget.cpp"
    change(media, '''void MediaWidget::play(MediaSource *source_)
{
\tif (source != source_) {''',
    '''void MediaWidget::play(MediaSource *source_)
{
\t// Invalidates a previously played Internet/local URL when a DVB,
\t// disc or other non-URL media source takes ownership of libVLC.
\tsetProperty("tihulu_recordable_url",
\t\tsource_ && source_->getType()==MediaSource::Url ?
\t\tQVariant(source_->getUrl()) : QVariant());
\tif (source != source_) {''')
    change(media, '''\tplay(new MediaSourceUrl(url, subtitleUrl));
}''',
    '''\tplay(new MediaSourceUrl(url, subtitleUrl));
\tsetProperty("tihulu_recordable_url",url);
}''')

    # Window management: default to a usable, contained viewport; restoring
    # a stale large window from another display must never strand controls
    # outside the current COSMIC / XWayland screen.
    change(main, '''        resize(availableGeometry.width() / 3, availableGeometry.height() / 2);''',
           '''        resize(qMax(1,availableGeometry.width()*4/5),
               qMax(1,availableGeometry.height()*4/5));''')
    change(main, '''    } else {
        restoreGeometry(geometry);
    }
}''', '''    } else {
        restoreGeometry(geometry);
        // Keep restored geometry inside the current screen. Preserve
        // smaller user sizes and the normal window manager maximized state.
        const QRect screen=QApplication::desktop()->availableGeometry(this);
        resize(qMin(width(),screen.width()),qMin(height(),screen.height()));
        move(qBound(screen.left(),x(),screen.right()-width()+1),
             qBound(screen.top(),y(),screen.bottom()-height()+1));
    }
}''')

    # Use a unique application ID and KConfig/SQLite user-data path.
    # This is a distinctly installed app, not the system KDE Kaffeine
    # process or a secondary window inside the existing binary.
    appmain = "src/main.cpp"
    change(appmain, '''		QStringLiteral("kaffeine"),
		i18n("Kaffeine"),''',
           '''		QStringLiteral("tihulu-media-center"),
		i18n("TIHULU Media Center"),''')
    change(appmain, '''		i18n("A media player by KDE with digital TV support."),''',
           '''		i18n("TIHULU · TV, DAB+ radio, media and offline AI; built on KDE Kaffeine."),''')
    change(appmain, '''{
	QString path = QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);''',
           '''{
	// Isolate SQL and KSharedConfig BEFORE opening the database.
	setApplicationName("tihulu-media-center");
	setOrganizationName("TIHULU");
	setOrganizationDomain("tihulu.local");
	QString path = QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);''')
    change(appmain, '#include <QPointer>\n',
           '#include <QPointer>\n#include <QFileInfo>\n')
    change(appmain, '''	app.setApplicationName("kaffeine");
	app.setOrganizationDomain("kde.org");
	app.setWindowIcon(QIcon::fromTheme(QLatin1String("kaffeine"), QIcon(":kaffeine")));''',
           '''	app.setApplicationName("tihulu-media-center");
	app.setOrganizationName("TIHULU");
	app.setOrganizationDomain("tihulu.local");
	// A previously installed portrait PNG must not silently override the
	// standalone PLAY-button application icon after an update. Explicit
	// TIHULU_USE_LEGACY_LOGO=1 restores that user-owned PNG without deleting it.
	const QString iconsRoot=QStandardPaths::writableLocation(
		QStandardPaths::GenericDataLocation)+QLatin1String("/icons/hicolor/");
	const QString playerSvg=iconsRoot+
		QLatin1String("scalable/apps/tihulu-media-center.svg");
	const QString legacyPng=iconsRoot+
		QLatin1String("64x64/apps/tihulu-media-center.png");
	const bool preferLegacy=qgetenv("TIHULU_USE_LEGACY_LOGO")=="1" &&
		QFileInfo::exists(legacyPng);
	const QIcon chosen=preferLegacy ? QIcon(legacyPng) :
		QFileInfo::exists(playerSvg) ? QIcon(playerSvg) :
		QIcon::fromTheme(QLatin1String("tihulu-media-center"),QIcon(":kaffeine"));
	app.setWindowIcon(chosen);''')
    change(main, '''	menu = new QMenu(i18n("Kaffeine"), this);''',
           '''	menu = new QMenu(i18n("TIHULU Media Center"), this);''')
    change(main, '''	trayIcon->setToolTip(i18n("Kaffeine"));''',
           '''	trayIcon->setToolTip(i18n("TIHULU Media Center"));''')
    change(main, '''	connect(mediaWidget, SIGNAL(changeCaption(QString)), this, SLOT(setWindowTitle(QString)));''',
           '''	connect(mediaWidget, &MediaWidget::changeCaption, this,
		[this](const QString &caption) {
			setWindowTitle(caption.isEmpty() ? QStringLiteral("TIHULU Media Center")
				: caption + QStringLiteral(" — TIHULU Media Center"));
		});''')
    change(main, '''\ttabBar->addTab(QIcon::fromTheme(QLatin1String("kaffeine"), QIcon(":kaffeine")), i18n("Playback"));''',
           '''\ttabBar->addTab(QIcon::fromTheme(QLatin1String("tihulu-media-center"), QIcon(":kaffeine")), i18n("Playback"));''')
    change(main, '''\ttrayIcon->setIcon(QIcon::fromTheme(QLatin1String("kaffeine"), QIcon(":kaffeine")));''',
           '''\ttrayIcon->setIcon(QIcon::fromTheme(QLatin1String("tihulu-media-center"), QIcon(":kaffeine")));''')
    change(main, '''\tQDBusConnection::sessionBus().registerService(QLatin1String("org.mpris.kaffeine"));''',
           '''\tQDBusConnection::sessionBus().registerService(
\t\tQLatin1String("org.mpris.MediaPlayer2.tihulu_media_center"));''')
    cmake = "src/CMakeLists.txt"
    change(cmake, 'target_link_libraries(kaffeine Qt5::Sql Qt5::X11Extras',
           'target_link_libraries(kaffeine Qt5::Network Qt5::Sql Qt5::X11Extras')
    change(main, "#include <QMainWindow>\n",
           "#include <QMainWindow>\n#include <QCoreApplication>\n"
           "#include <QProcess>\n#include <QMessageBox>\n#include <QStandardPaths>\n")
    change(main, "#include <QStandardPaths>\n",
           "#include <QStandardPaths>\n#include <QLabel>\n#include <QVBoxLayout>\n"
           "#include <QDir>\n#include <QDialog>\n#include <QPlainTextEdit>\n"
           "#include <QPushButton>\n")
    change(main, '''#if HAVE_DVB == 1
	QMenu *dvbMenu = new QMenu(i18n("&Television"), this);
	menuBar->addMenu(dvbMenu);
#endif /* HAVE_DVB == 1 */
''', '''#if HAVE_DVB == 1
	QMenu *dvbMenu = new QMenu(i18n("&Television"), this);
	menuBar->addMenu(dvbMenu);
	QAction *receiverStatus = dvbMenu->addAction(i18n("Receiver / tuner diagnostics..."));
	connect(receiverStatus, &QAction::triggered, this, [this]() {
		// Read-only diagnostics: never force-close another SDR application's tuner.
		QDialog *dialog = new QDialog(this);
		dialog->setAttribute(Qt::WA_DeleteOnClose);
		dialog->setWindowTitle(i18n("DVB tuner ownership and scan setup"));
		dialog->resize(800, 480);
		QVBoxLayout *layout = new QVBoxLayout(dialog);
		QPlainTextEdit *console = new QPlainTextEdit(dialog);
		console->setReadOnly(true);
		console->setPlainText(i18n("Inspecting local DVB frontend ownership..."));
		layout->addWidget(console);
		QPushButton *close = new QPushButton(i18n("Close"), dialog);
		connect(close, &QPushButton::clicked, dialog, &QDialog::accept);
		layout->addWidget(close);
		QProcess *diagnostics = new QProcess(dialog);
		connect(diagnostics, &QProcess::readyReadStandardOutput, dialog,
			[diagnostics, console]() {
				console->appendPlainText(QString::fromLocal8Bit(
					diagnostics->readAllStandardOutput()));
			});
		connect(diagnostics, &QProcess::readyReadStandardError, dialog,
			[diagnostics, console]() {
				console->appendPlainText(QString::fromLocal8Bit(
					diagnostics->readAllStandardError()));
			});
		connect(diagnostics, QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
			dialog, [console](int code, QProcess::ExitStatus) {
				console->appendPlainText(QStringLiteral("\\nCompleted (exit %1).").arg(code));
			});
		dialog->show();
		diagnostics->start(QLatin1String("/bin/bash"),
			QStringList() << QDir::homePath() +
				QLatin1String("/.local/share/tihulu-kaffeine/dvb_diagnostics.sh"));
	});
	QAction *webTvAction = dvbMenu->addAction(i18n("Web TV / Internet channels..."));
	connect(webTvAction, &QAction::triggered, this, [this]() {
		TihuluWebTvDialog *dialog = new TihuluWebTvDialog(mediaWidget,
			[this]() { activateTab(PlayerTabId); }, this);
		dialog->show();
	});
	// Keep native Kaffeine channel switching, Teletext and player unchanged.
	QMenu *aiMenu = new QMenu(i18n("TIHULU &AI"), this);
	menuBar->addMenu(aiMenu);
	QAction *marketAction = aiMenu->addAction(i18n("Whisper + Translator Market"));
	connect(marketAction, &QAction::triggered, this, [this]() {
		if (!QProcess::startDetached(QLatin1String("tihulu-tv-center"),
			QStringList() << QLatin1String("ai-market")))
			QMessageBox::warning(this, i18n("Whisper Market"),
				i18n("Install the TIHULU offline AI companion first."));
	});
	QAction *generatedSrtAction = aiMenu->addAction(i18n("Load generated SRT in native player..."));
	connect(generatedSrtAction, &QAction::triggered, this, [this]() {
		// Use Kaffeine's own libVLC subtitle loader for completed sidecars.
		// A growing SRT is NOT guaranteed to refresh during a live TV stream.
		const QString subtitle = QFileDialog::getOpenFileName(this,
			i18n("Select completed AI subtitles (SRT)"),
			QDir::homePath(), i18n("SubRip subtitles (*.srt);;All files (*)"));
		if (!subtitle.isEmpty())
			mediaWidget->setSubtitle(QUrl::fromLocalFile(subtitle));
	});
	QAction *captionAction = aiMenu->addAction(i18n("Live Teletext / Whisper subtitles"));
	connect(captionAction, &QAction::triggered, this, [this]() {
		const QString runtime = QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
		if (runtime.isEmpty()) {
			QMessageBox::warning(this, i18n("Live captions"),
				i18n("XDG_RUNTIME_DIR is missing; cannot start private capture."));
			return;
		}
		const QString name = runtime + QLatin1String("/tihulu-dvb-")
			+ QString::number(QCoreApplication::applicationPid())
			+ QLatin1String(".sock");
		if (!QProcess::startDetached(QLatin1String("tihulu-tv-center"),
			QStringList() << QLatin1String("kaffeine-captions")
				<< QLatin1String("--socket") << name))
			QMessageBox::warning(this, i18n("Live captions"),
				i18n("Install the TIHULU caption companion first."));
	});
#endif /* HAVE_DVB == 1 */
''')
    # Explicit in-app remote media sharing: default LOOPBACK, not WAN.
    # The Python hub performs host-side HLS conversion and prints a random
    # pairing PIN. Qt captures stdout privately and shows that PIN only
    # in the host GUI. No raw PIN in process arguments, file or GitHub.
    change(main, '''	QAction *marketAction = aiMenu->addAction(i18n("Whisper + Translator Market"));''',
    '''	QAction *hubStart = aiMenu->addAction(i18n("Start paired remote media hub..."));
	QAction *hubStop = aiMenu->addAction(i18n("Stop remote media sharing"));
	hubStop->setEnabled(false);
	QProcess *hubProcess = new QProcess(this);
	connect(hubProcess, &QProcess::readyReadStandardOutput, this,
		[this,hubProcess]() {
			const QByteArray combined=hubProcess->property("partial").toByteArray()+
				hubProcess->readAllStandardOutput();
			const QByteArray marker("Pairing PIN (host terminal only): ");
			const int offset=combined.indexOf(marker);
			if(!hubProcess->property("pinShown").toBool() && offset>=0 &&
			   combined.size()>=offset+marker.size()+8) {
				const QByteArray pin=combined.mid(offset+marker.size(),8);
				bool valid=pin.size()==8;
				for(char digit:pin) if(digit<'0' || digit>'9') valid=false;
				if(valid) {
					hubProcess->setProperty("pinShown",true);
					QMessageBox::information(this,i18n("Paired remote media hub"),
						i18n("Local media remote is active on "
						"127.0.0.1:8788. Pairing PIN: %1\\n\\n"
						"Only your explicitly selected media folder is shared. "
						"Other devices require a private HTTPS proxy, "
						"for example Tailscale Serve. "
						"Live DVB television/DVD is NOT yet rebroadcast."),
						QString::fromLatin1(pin));
				}
			}
			hubProcess->setProperty("partial",combined.right(450));
		});
	connect(hubProcess,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
		this,[hubStop](int,QProcess::ExitStatus) {hubStop->setEnabled(false);});
	connect(hubStart,&QAction::triggered,this,[this,hubProcess,hubStop]() {
		if(hubProcess->state()!=QProcess::NotRunning) {
			QMessageBox::information(this,i18n("Remote hub"),
				i18n("The local paired remote hub is already running."));
			return;
		}
		const QString folder=QFileDialog::getExistingDirectory(this,
			i18n("Choose media directory to share with paired devices"),
			QDir::homePath());
		if(folder.isEmpty()) return;
		hubProcess->setProperty("pinShown",false);
		hubProcess->setProperty("partial",QByteArray());
		hubProcess->start(QLatin1String("tihulu-tv-center"),
			{QLatin1String("remote-hub"),QLatin1String("--media-root"),folder,
			 QLatin1String("--bind"),QLatin1String("127.0.0.1"),
			 QLatin1String("--native-pid"),
			 QString::number(QCoreApplication::applicationPid())});
		if(!hubProcess->waitForStarted(1500)) {
			QMessageBox::warning(this,i18n("Remote hub"),
				i18n("Cannot start Python companion; run "
				"'tihulu-tv-center remote-hub --help' in terminal."));
			return;
		}
		hubStop->setEnabled(true);
	});
	connect(hubStop,&QAction::triggered,this,[hubProcess]() {
		if(hubProcess->state()!=QProcess::NotRunning)
			hubProcess->terminate();
	});
	connect(QCoreApplication::instance(),&QCoreApplication::aboutToQuit,
		hubProcess,[hubProcess]() {
			if(hubProcess->state()!=QProcess::NotRunning) {
				hubProcess->terminate();
				if(!hubProcess->waitForFinished(1200)) hubProcess->kill();
			}
		});
	QAction *marketAction = aiMenu->addAction(i18n("Whisper + Translator Market"));''')

    # Give locally opened video/audio files the SAME managed offline
    # Whisper/translation engines via optional SRT creation dialogue.
    # No file uploads and no interference with native playback.
    change(main, '''	QAction *captionAction = aiMenu->addAction(i18n("Live Teletext / Whisper subtitles"));''',
           '''	QAction *mediaCaptionAction = aiMenu->addAction(
		i18n("Generate AI captions / lyrics for local Video or Audio..."));
	connect(mediaCaptionAction, &QAction::triggered, this, [this]() {
		const QString file = QFileDialog::getOpenFileName(
			this, i18n("Open local video or audio for offline captions"),
			QString(),
			i18n("Media files (*.mp4 *.mkv *.mov *.avi *.webm *.ts *.flac "
			     "*.mp3 *.wav *.m4a *.aac *.ogg *.opus);;All files (*)"));
		if (file.isEmpty()) return;
		// Play in THIS same window; the Playback tab includes the
		// offline GPU/translation/lyrics controls under native libVLC.
		openUrl(QUrl::fromLocalFile(file));
	});
	QAction *captionAction = aiMenu->addAction(i18n("Live Teletext / Whisper subtitles"));''')

    hdr = "src/dvb/dvbliveview_p.h"
    change(hdr, '\tQList<QByteArray> buffers;\n',
           '\tQList<QByteArray> buffers;\n'
           '\tQString tihuluCaptionSocketPath;\n\tint tihuluCaptionFd;\n')

    live = "src/dvb/dvbliveview.cpp"
    change(live, '#include <QDir>\n',
           '#include <QDir>\n#include <QCoreApplication>\n'
           '#include <QSaveFile>\n'
           '#include <sys/socket.h>\n#include <sys/un.h>\n')
    change(live, '\treadFd(-1), writeFd(-1), notifier(NULL)\n{',
           '\treadFd(-1), writeFd(-1), notifier(NULL), tihuluCaptionFd(-1)\n{')
    change(live, '\tfileName = QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation) + QLatin1String("/dvbpipe.m2t");',
           '\tconst QString runtime = QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);\n'
           '\tif (!runtime.isEmpty())\n'
           '\t\ttihuluCaptionSocketPath = runtime + QLatin1String("/tihulu-dvb-")\n'
           '\t\t\t+ QString::number(QCoreApplication::applicationPid()) + QLatin1String(".sock");\n'
           '\tfileName = runtime + QLatin1String("/dvbpipe.m2t");')
    change(live, 'DvbLiveViewInternal::~DvbLiveViewInternal()\n{\n',
           'DvbLiveViewInternal::~DvbLiveViewInternal()\n{\n'
           '\tif (tihuluCaptionFd >= 0)\n\t\t::close(tihuluCaptionFd);\n\tif (!tihuluEffectiveDelayFile.isEmpty())\n\t\tQFile::remove(tihuluEffectiveDelayFile);\n')
    change(live, '''	if (!timeShiftFile.isOpen()) {
		if (writeFd >= 0) {
			buffers.append(buffer);
''', '''	// Best-effort datagrams are dropped when no caption listener exists.
	// No blocking, no extra DVB frontend open, no effect on libVLC output.
	if (!tihuluCaptionSocketPath.isEmpty() && QFile::exists(tihuluCaptionSocketPath)) {
		if (tihuluCaptionFd < 0)
			tihuluCaptionFd = ::socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK, 0);
		if (tihuluCaptionFd >= 0) {
			const QByteArray name = QFile::encodeName(tihuluCaptionSocketPath);
			sockaddr_un peer = {};
			peer.sun_family = AF_UNIX;
			if (name.size() < static_cast<int>(sizeof(peer.sun_path))) {
				qstrncpy(peer.sun_path, name.constData(), sizeof(peer.sun_path));
				for (int pos = 0; pos < buffer.size(); pos += 16 * 188) {
					const int n = qMin(16 * 188, buffer.size() - pos);
					(void)::sendto(tihuluCaptionFd, buffer.constData() + pos,
						static_cast<size_t>(n), MSG_DONTWAIT | MSG_NOSIGNAL,
						reinterpret_cast<sockaddr *>(&peer), sizeof(peer));
				}
			}
		}
	}
	if (!timeShiftFile.isOpen()) {
		if (writeFd >= 0) {
			buffers.append(buffer);
''')
    # A channel switch may release the old DVB frontend and immediately
    # reacquire it for a different multiplex. Allow the USB/backend release
    # to settle, but NEVER retry a nonconfigured source or steal a tuner from
    # recordings. The guard is scoped to the selected channel generation.
    change(hdr, '''\tint retryCounter;
''', '''\tint retryCounter;
\tint tihuluDeviceRetryCount = 0;
\tquint64 tihuluTuneEpoch = 0;
''')
    change(live, '''void DvbLiveView::replay()
{
\tif (device == NULL) {''', '''// One-way notification of the DVB owner's selected channel. It is
// an atomic, private runtime marker, NOT a tuner command or second
// receiver. The captions panel can invalidate old-PID work immediately,
// even before a new multiplex supplies its next PAT packet.
static void tihuluNotifyNativeCaptionTune(quint64 epoch, int sid, int tsid)
{
\tconst QString runtime = QStandardPaths::writableLocation(
\t\tQStandardPaths::RuntimeLocation);
\tif (runtime.isEmpty()) return;
\tQSaveFile file(runtime + QLatin1String("/tihulu-tv-tune-") +
\t\tQString::number(QCoreApplication::applicationPid()) +
\t\tQLatin1String(".txt"));
\tif (file.open(QIODevice::WriteOnly)) {
\t\tQByteArray state = QByteArray::number(epoch) + ' ' +
\t\t\tQByteArray::number(sid) + ' ' + QByteArray::number(tsid) + '\\n';
\t\tif (file.write(state) != state.size()) file.cancelWriting();
\t\telse file.commit();
\t}
}

void DvbLiveView::replay()
{
\tif (channel.constData() == NULL) return;
\tif (device == NULL) {''')
    change(live, '''\tplaybackStatusChanged(MediaWidget::Idle);
\tchannel = channel_;
\tdevice = newDevice;

\treplay();''', '''\t// Invalidate any pending reacquire from the previous channel.
\t// Do not persist a temporary retry across channel switches.
\t++internal->tihuluTuneEpoch;
\tinternal->tihuluDeviceRetryCount = 0;
\tplaybackStatusChanged(MediaWidget::Idle);
\tchannel = channel_;
\tdevice = newDevice;
\t// A native tune epoch makes changes visible even when service IDs are
\t// recycled by a different DVB multiplex or the TS feed is interrupted.
\ttihuluNotifyNativeCaptionTune(internal->tihuluTuneEpoch,
\t\tchannel.constData()!=NULL ? int(channel->serviceId) : 0,
\t\tchannel.constData()!=NULL ? int(channel->transportStreamId) : 0);

\treplay();''')

    # An unrelated Playback, radio, media file or explicit Stop must cancel
    # any pending asynchronous TV reacquire. Otherwise a delayed callback
    # could unexpectedly steal the shared player after leaving Television.
    change(live, '''\tcase MediaWidget::Idle:
\t\tif (device != NULL) {''', '''\tcase MediaWidget::Idle:
\t\t++internal->tihuluTuneEpoch;
\t\t// Stop or retune: invalidate the old captions immediately. The
\t\t// subsequent playChannel event advertises the new selected DVB SID.
\t\ttihuluNotifyNativeCaptionTune(internal->tihuluTuneEpoch, 0, 0);
\t\tinternal->tihuluDeviceRetryCount = 0;
\t\tif (device != NULL) {''')
    # DvbManager only forward-declares DvbConfig; the diagnostic iterates
    # QList<DvbConfig> so include the complete shared-pointer definition.
    change(live, '#include "dvbdevice.h"\n',
           '#include "dvbdevice.h"\n#include "dvbconfig.h"\n')
    # The upstream "Didn't find a device with valid settings..." message
    # conflates disconnected USB, an unassigned channel source, another
    # active consumer and permission-denied. Emit actionable *read-only*
    # source diagnostics without changing device ownership or channel DB.
    change(live, '''\tif (device == NULL) {
\t\tchannel = DvbSharedChannel();
\t\tmediaWidget->stop();

\t\tif (manager->getRecordingModel()->hasActiveRecordings()) {''',
    '''\tif (device == NULL) {
\t\tconst QString requestedSource = channel->source;
\t\tQStringList usableSources;
\t\tint connectedDvbFrontends = 0;
\t\tbool hasConnectedMatchingSource = false;
\t\tfor (const DvbDeviceConfig &entry : manager->getDeviceConfigs()) {
\t\t\tif (entry.device == NULL) continue;
\t\t\t++connectedDvbFrontends;
\t\t\tfor (const DvbConfig &configured : entry.configs) {
\t\t\t\tif (configured->name.isEmpty()) continue;
\t\t\t\tusableSources.append(configured->name);
\t\t\t\tif (configured->name == requestedSource)
\t\t\t\t\thasConnectedMatchingSource = true;
\t\t\t}
\t\t}
\t\tconst bool recording = manager->getRecordingModel()->hasActiveRecordings();
\t\t// The first immediate reacquire may fail while the USB frontend is
\t\t// still releasing. Retry only when the physical tuner and matching
\t\t// named source exist. Never reopen a missing frontend or override a
\t\t// recording, and never loop without an upper bound.
\t\tif (hasConnectedMatchingSource && !recording &&
\t\t    internal->tihuluDeviceRetryCount < 2) {
\t\t\tconst int attempt = ++internal->tihuluDeviceRetryCount;
\t\t\tconst quint64 epoch = internal->tihuluTuneEpoch;
\t\t\tqCWarning(logDvb,
\t\t\t\t"TIHULU DVB channel retune pending: source='%s', "
\t\t\t\t"attempt %d/2; waiting for the previous frontend release.",
\t\t\t\tqPrintable(requestedSource), attempt);
\t\t\tQTimer::singleShot(attempt * 400, this, [this,epoch]() {
\t\t\t\tif (internal->tihuluTuneEpoch != epoch ||
\t\t\t\t    channel.constData() == NULL) return;
\t\t\t\treplay();
\t\t\t});
\t\t\treturn;
\t\t}
\t\tqCWarning(logDvb,
\t\t\t"TIHULU no usable DVB frontend: requested channel source='%s'; "
\t\t\t"connected receivers=%d; configured channel sources='%s'; "
\t\t\t"source matches connected tuner=%d; attempts=%d. "
\t\t\t"Inspect Configure Television and run --diagnose-tuner.",
\t\t\tqPrintable(requestedSource), connectedDvbFrontends,
\t\t\tqPrintable(usableSources.join(QLatin1String(", "))),
\t\t\tint(hasConnectedMatchingSource), internal->tihuluDeviceRetryCount);
\t\tchannel = DvbSharedChannel();
\t\tmediaWidget->stop();

\t\tif (recording) {''')

    # Keep the stock recording-specific explanation, but do not tell the
    # user to randomly change permissions when a tuned channel's Source is
    # absent from the *connected* device configuration. This dialog only
    # appears after transient reacquire attempts were exhausted.
    change(live, '''\t\t} else {
\t\t\tKMessageBox::information(manager->getParentWidget(),
\t\t\t\ti18nc("@info",
\t\t\t\t      "Didn't find a device with valid settings or access permissions are wrong.\\n\\n"
\t\t\t\t      "Please check the Configure Television window."));
\t\t}

\t\treturn;
\t}''', '''\t\t} else if (connectedDvbFrontends == 0) {
\t\t\tKMessageBox::information(manager->getParentWidget(),
\t\t\t\ti18nc("@info", "No connected DVB television tuner is available. "
\t\t\t\t"Check the USB device, its driver, and Television → Receiver / tuner diagnostics."));
\t\t} else if (!hasConnectedMatchingSource) {
\t\t\tKMessageBox::information(manager->getParentWidget(),
\t\t\t\ti18nc("@info", "This TV channel uses the source '%1', but no connected "
\t\t\t\t"DVB tuner has that exact source name. Configured sources: %2.\\n\\n"
\t\t\t\t"Open Television → Configure Television and match the DVB-T2 "
\t\t\t\t"source Name used by the saved channel, or rescan the service.",
\t\t\t\trequestedSource,usableSources.join(QLatin1String(", "))));
\t\t} else {
\t\t\tKMessageBox::information(manager->getParentWidget(),
\t\t\t\ti18nc("@info", "The DVB tuner was detected and its channel source "
\t\t\t\t"matches, but the tuner could not be acquired after a short retry. "
\t\t\t\t"Check whether another TV program, a scan, or a driver operation "
\t\t\t\t"is holding the frontend.\\n\\n"
\t\t\t\t"Run tihulu-media-center --diagnose-tuner. "
\t\t\t\t"No tuner reset or channel settings were performed."));
\t\t}

\t\treturn;
\t}''')

    # Delay *both* audio and video by buffering already-filtered TS bytes
    # before Kaffeine's existing FIFO -> libVLC. The AI tap above stays
    # pre-delay so Whisper can finish nearer to delayed playback.
    # A capped 64 MiB queue prevents uncontrolled memory growth on Pi 5.
    change(hdr, '#include <QFile>\n', '#include <QFile>\n#include <QPair>\n')
    change(hdr, '''\tQString tihuluCaptionSocketPath;
\tint tihuluCaptionFd;
''', '''\tQString tihuluCaptionSocketPath;
\tint tihuluCaptionFd;
\tQString tihuluDelayFile;
\tQString tihuluEffectiveDelayFile;
\tQList<QPair<qint64, QByteArray> > tihuluDelayed;
\tqint64 tihuluDelayedBytes = 0;
\tqint64 tihuluConfigCheckedAt = 0;
\tqint64 tihuluObservedBytes = 0;
\tqint64 tihuluObservedRate = 0;
\tqint64 tihuluDelayCooldownUntil = 0;
\tint tihuluVideoDelayMs = 0;
\tint tihuluPrimedTargetMs = -1;
\tbool tihuluDelayPrimed = false;
\t// Measured oldest DVB TS chunk age at release to libVLC's pipe.
\t// The renderer may add latency; this is NOT video presentation PTS.
\tqint64 tihuluReleasedAgeMs = -1;
\tqint64 tihuluReleasedAtMs = 0;
''')
    change(live, '#include <QCoreApplication>\n',
           '#include <QCoreApplication>\n#include <QDateTime>\n')
    change(live, '''\tfileName = runtime + QLatin1String("/dvbpipe.m2t");''',
           '''\ttihuluDelayFile = runtime + QLatin1String("/tihulu-playback-delay-")
\t\t+ QString::number(QCoreApplication::applicationPid()) + QLatin1String(".txt");
\ttihuluEffectiveDelayFile = runtime + QLatin1String("/tihulu-playback-effective-")
\t\t+ QString::number(QCoreApplication::applicationPid()) + QLatin1String(".txt");
\tfileName = runtime + QLatin1String("/dvbpipe.m2t");''')
    change(live, '''\tretryCounter = 0;
\tnotifier->setEnabled(false);''',
           '''\tretryCounter = 0;
\tnotifier->setEnabled(false);
\t// Never replay a previous channel's delayed TS after switching services.
\ttihuluDelayed.clear();
\ttihuluDelayedBytes = 0;
\ttihuluPrimedTargetMs = -1;
\ttihuluDelayPrimed = false;
\ttihuluReleasedAgeMs = -1;
\ttihuluReleasedAtMs = 0;''')
    change(live, '''\tif (!timeShiftFile.isOpen()) {
\t\tif (writeFd >= 0) {
\t\t\tbuffers.append(buffer);
\t\t\twriteToPipe();
\t\t\tif (emptyBuffer) {''',
    '''\t// Whisper receives the original TS ABOVE, before this playback delay.
\t// A requested delay can exceed the memory-limited native FIFO. Bound the
\t// actual delay to 48 MiB of measured selected-service TS with 16 MiB
\t// headroom and publish effective/native value to the subtitle controller.
\tconst qint64 now = QDateTime::currentMSecsSinceEpoch();
\ttihuluObservedBytes += buffer.size();
\tif (now - tihuluConfigCheckedAt >= 1000) {
\t\tconst qint64 elapsed = now - tihuluConfigCheckedAt;
\t\tif (tihuluConfigCheckedAt > 0 && elapsed > 0) {
\t\t\tconst qint64 instantaneous = tihuluObservedBytes * 1000 / elapsed;
\t\t\t// Keep 75% of the prior rate when DVB bitrate falls temporarily.
\t\t\ttihuluObservedRate = qMax(instantaneous,
\t\t\t\t(tihuluObservedRate * 3) / 4);
\t\t}
\t\ttihuluObservedBytes = 0;
\t\ttihuluConfigCheckedAt = now;
\t\tQFile settings(tihuluDelayFile);
\t\tint requestedMs = 0;
\t\tif (settings.open(QIODevice::ReadOnly) && settings.size() < 16) {
\t\t\tbool ok = false;
\t\t\tconst int requested = settings.readAll().trimmed().toInt(&ok);
\t\t\tif (ok && requested >= 0 && requested <= 20000)
\t\t\t\trequestedMs = requested;
\t\t}
\t\tconst qint64 safeMs = tihuluObservedRate > 0
\t\t\t? qMin(20000LL, 48LL * 1024 * 1024 * 1000 / tihuluObservedRate)
\t\t\t: 20000LL;
\t\tconst int cappedMs = (qMin<qint64>(requestedMs, safeMs) / 500) * 500;
\t\tconst int newTargetMs = (now < tihuluDelayCooldownUntil ||
\t\t\ttimeShiftFile.isOpen()) ? 0 : cappedMs;
\t\tif (newTargetMs != tihuluPrimedTargetMs) {
\t\t\t// A new requested delay is NOT yet an applied playback
\t\t\t// timeline: waiting for 14s of input can take 14 real seconds.
\t\t\ttihuluDelayPrimed = (newTargetMs == 0);
\t\t\ttihuluPrimedTargetMs = newTargetMs;
\t\t}
\t\ttihuluVideoDelayMs = newTargetMs;
\t\tconst qint64 queuedAgeMs = tihuluDelayed.isEmpty() ? 0 :
\t\t\tqMax<qint64>(0, now - tihuluDelayed.first().first);
\t\tif (!tihuluDelayPrimed && tihuluVideoDelayMs > 0 &&
\t\t    queuedAgeMs >= tihuluVideoDelayMs - 250)
\t\t\ttihuluDelayPrimed = true;
\t\tQFile status(tihuluEffectiveDelayFile);
\t\tif (status.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
\t\t\tstatus.setPermissions(QFile::ReadOwner | QFile::WriteOwner);
\t\t\t// request, bounded target, TS bytes/s, buffer primed flag,
\t\t\t// and observed oldest queued TS age. A target does not
\t\t\t// imply libVLC already has delayed video ready.
\t\t\tstatus.write(QByteArray::number(requestedMs) + " " +
\t\t\t\tQByteArray::number(tihuluVideoDelayMs) + " " +
\t\t\t\tQByteArray::number(tihuluObservedRate) + " " +
\t\t\t\tQByteArray::number(tihuluDelayPrimed ? 1 : 0) + " " +
\t\t\t\tQByteArray::number(queuedAgeMs) + " " +
\t\t\t\tQByteArray::number(tihuluReleasedAgeMs) + " " +
\t\t\t\tQByteArray::number(tihuluReleasedAtMs));
\t\t}
\t}
\tif (!timeShiftFile.isOpen()) {
\t\tif (writeFd >= 0) {
\t\t\tconst bool queuedCurrent = (tihuluVideoDelayMs > 0);
\t\t\tif (queuedCurrent) {
\t\t\t\ttihuluDelayed.append(qMakePair(now, buffer));
\t\t\t\ttihuluDelayedBytes += buffer.size();
\t\t\t\tif (tihuluDelayedBytes > 64LL * 1024 * 1024) {
\t\t\t\t\tqCWarning(logDvb, "TIHULU playback delay exceeded 64 MiB; reverting to live for 5s");
\t\t\t\t\ttihuluVideoDelayMs = 0;
\t\t\t\t\ttihuluDelayPrimed = true;
\t\t\t\t\ttihuluPrimedTargetMs = 0;
\t\t\t\t\ttihuluReleasedAgeMs = -1;
\t\t\t\t\ttihuluReleasedAtMs = 0;
\t\t\t\t\ttihuluDelayCooldownUntil = now + 5000;
\t\t\t\t}
\t\t\t}
\t\t\twhile (!tihuluDelayed.isEmpty() &&
\t\t\t       (tihuluVideoDelayMs == 0 ||
\t\t\t        now - tihuluDelayed.first().first >= tihuluVideoDelayMs)) {
\t\t\t\tconst QPair<qint64,QByteArray> released = tihuluDelayed.takeFirst();
\t\t\t\tconst QByteArray chunk = released.second;
\t\t\t\ttihuluDelayedBytes -= chunk.size();
\t\t\t\t// Observe actual residence time IN the FIFO when handed off
\t\t\t\t// to libVLC. Do not confuse this with decoded presentation PTS.
\t\t\t\tif (tihuluVideoDelayMs > 0 && tihuluDelayPrimed) {
\t\t\t\t\ttihuluReleasedAgeMs = qMax<qint64>(0, now - released.first);
\t\t\t\t\ttihuluReleasedAtMs = now;
\t\t\t\t} else {
\t\t\t\t\ttihuluReleasedAgeMs = -1;
\t\t\t\t\ttihuluReleasedAtMs = 0;
\t\t\t\t}
\t\t\t\tbuffers.append(chunk);
\t\t\t}
\t\t\tif (!queuedCurrent)
\t\t\t\tbuffers.append(buffer);
\t\t\tif (!buffers.isEmpty())
\t\t\t\twriteToPipe();
\t\t\tif (emptyBuffer) {''')
    # Kaffeine's timeshift file already implements its own media timeline;
    # never concatenate a second delayed FIFO while timeshift is enabled.
    change(live, '''\t} else {
\t\tnotifier->setEnabled(false);
\t\ttimeShiftFile.write(buffer); // FIXME avoid buffer reallocation''',
    '''\t} else {
\t\ttihuluDelayed.clear();
\t\ttihuluDelayedBytes = 0;
\t\ttihuluReleasedAgeMs = -1;
\t\ttihuluReleasedAtMs = 0;
\t\tnotifier->setEnabled(false);
\t\ttimeShiftFile.write(buffer); // FIXME avoid buffer reallocation''')

    # Keep Kaffeine's native libVLC rendering but offer explicit recovery
    # profiles for broken VA-API/VDPAU/NVIDIA paths and bad live FIFO caching.
    # Every platform remains configurable: original Kaffeine settings take
    # priority whenever user explicitly supplies an equivalent option.
    vlc = "src/backend-vlc/vlcmediawidget.cpp"
    change(vlc, '''\tQString args = Configuration::instance()->getLibVlcArguments();
\tQStringList argList;''', '''\tQString args = Configuration::instance()->getLibVlcArguments();
\tconst QByteArray tihuluProfile = qgetenv("TIHULU_VLC_PROFILE");
\tif (tihuluProfile == "software" || tihuluProfile == "software-no-audio") {
\t\t// Explicit recovery mode MUST override saved --avcodec-hw=any.
\t\t// Otherwise libVLC still loads NVIDIA VDPAU even when the user
\t\t// requested software-no-audio, exactly as seen in the device log.
\t\tQStringList existing = args.split(QLatin1Char(' '), Qt::SkipEmptyParts);
\t\tfor (int n = existing.size() - 1; n >= 0; --n) {
\t\t\tconst QString option = existing.at(n);
\t\t\t// The normal software profile must not inherit the disabling
\t\t\t// --no-audio option from a previous troubleshooting configuration.
\t\t\t// Only an explicit software-no-audio profile may disable sound.
\t\t\tif (tihuluProfile == "software" &&
\t\t\t    option == QLatin1String("--no-audio")) {
\t\t\t\texisting.removeAt(n);
\t\t\t\tcontinue;
\t\t\t}
\t\t\tif (option == QLatin1String("--avcodec-hw")) {
\t\t\t\tif (n+1 < existing.size()) existing.removeAt(n+1);
\t\t\t\texisting.removeAt(n);
\t\t\t} else if (option.startsWith(QLatin1String("--avcodec-hw="))) {
\t\t\t\texisting.removeAt(n);
\t\t\t}
\t\t}
\t\targs = existing.join(QLatin1Char(' '));
\t\targs.append(QLatin1String(" --avcodec-hw=none"));
\t\tif (!args.contains(QLatin1String("--file-caching")))
\t\t\targs.append(QLatin1String(" --file-caching=1500"));
\t\tif (!args.contains(QLatin1String("--no-video-title-show")))
\t\t\targs.append(QLatin1String(" --no-video-title-show"));
\t\tif (tihuluProfile == "software-no-audio" &&
\t\t    !args.contains(QLatin1String("--no-audio")))
\t\t\targs.append(QLatin1String(" --no-audio"));
\t\tqCInfo(logVlc, "TIHULU playback troubleshooting: %s; enforced libVLC: %s",
\t\t       tihuluProfile.constData(), qPrintable(args));
\t}
\tQStringList argList;''')

    # Do not silently fall back to libvlc_new(0,NULL) (which re-enables
    # NVIDIA hardware) when the user requests a software video profile.
    change(vlc, '''\t\targc = 0;
\t\tvlcInstance = libvlc_new(0, NULL);
\t\tif (vlcInstance)
\t\t\tqCInfo(logMediaWidget, "Using libVLC without arguments");''',
    '''\t\targc = 0;
\t\tconst QByteArray profile = qgetenv("TIHULU_VLC_PROFILE");
\t\tif (profile == "software" || profile == "software-no-audio") {
\t\t\tconst char *fallbackArgs[] = { "--avcodec-hw=none",
\t\t\t\t"--no-video-title-show", "--no-audio" };
\t\t\tvlcInstance = libvlc_new(
\t\t\t\tprofile == "software-no-audio" ? 3 : 2, fallbackArgs);
\t\t\tif (vlcInstance)
\t\t\t\tqCWarning(logVlc,
\t\t\t\t\t"TIHULU: extra VLC arguments rejected; safe software decoder still enforced");
\t\t} else {
\t\t\tvlcInstance = libvlc_new(0, NULL);
\t\t\tif (vlcInstance)
\t\t\t\tqCInfo(logMediaWidget, "Using libVLC without arguments");
\t\t}''')
    change(vlc, '#include <QTimer>\n',
           '#include <QTimer>\n#include <QSettings>\n')
    mediaAnchor = '\tvlcMedia = libvlc_media_new_location(vlcInstance, typeOfDevice);'
    if files[vlc].count(mediaAnchor) != 2:
        raise ValueError("Unexpected libVLC media creation count")
    files[vlc] = files[vlc].replace(mediaAnchor, mediaAnchor + '''
\t// This media-creation expression occurs in BOTH play() and CD
\t// track-change methods, but 'source' only exists in play().
\t// Inspect the actual encoded libVLC URL instead.
\tconst QByteArray localStreamUrl(typeOfDevice);
\tif (localStreamUrl.startsWith("http://127.0.0.1:") &&
\t    localStreamUrl.contains("/mp3/")) {
\t\tQSettings radioSettings(QLatin1String("TIHULU"),
\t\t\tQLatin1String("KaffeineRadio"));
\t\tconst int cacheMs=qBound(0,
\t\t\tradioSettings.value(QLatin1String("playbackBufferMs"),0).toInt(),
\t\t\t60000);
\t\t// OFF disables only our extra buffering override. Do not
\t\t// force network-caching=0: libVLC's internal jitter controls
\t\t// still protect audible DAB playback from small packet gaps.
\t\tif (cacheMs > 0) {
\t\t\tconst QByteArray cacheOpt=QByteArray(":network-caching=")+
\t\t\t\tQByteArray::number(cacheMs);
\t\t\tlibvlc_media_add_option(vlcMedia,cacheOpt.constData());
\t\t}
\t} else if (localStreamUrl.startsWith("file://")) {
\t\t// Local file AI may run BEFORE playback by user request.
\t\t// This is only I/O read-ahead, not a fabricated subtitle offset.
\t\tQSettings mediaSettings(QLatin1String("TIHULU"),
\t\t\tQLatin1String("MediaPlayer"));
\t\tconst int cacheMs=qBound(0,
\t\t\tmediaSettings.value(QLatin1String("fileCacheMs"),1500).toInt(),
\t\t\t20000);
\t\tconst QByteArray cacheOpt=QByteArray(":file-caching=")+
\t\t\tQByteArray::number(cacheMs);
\t\tlibvlc_media_add_option(vlcMedia,cacheOpt.constData());
\t}
\t// Per-media option reinforces the instance-level software decode
\t// request; native television and playback controls remain unmodified.
\tconst QByteArray appliedProfile = qgetenv("TIHULU_VLC_PROFILE");
\tif (appliedProfile == "software" || appliedProfile == "software-no-audio")
\t\tlibvlc_media_add_option(vlcMedia, ":avcodec-hw=none");''')

    # Native VLC marquee renders inside the actual decoded video surface.
    # Unlike a full-size transparent QWidget over an X11 video window, this
    # cannot retain stale rectangles from past video frames.
    vlch = "src/backend-vlc/vlcmediawidget.h"
    change(vlch, '''\tvoid setExternalSubtitle(const QUrl &subtitleUrl) override;''',
           '''\tvoid setExternalSubtitle(const QUrl &subtitleUrl) override;
\tvoid setTihuluNativeCaption(const QString &text, bool atTop,
\t\tint fontSize, int textOpacity, const QString &color,
\t\tint backgroundPercent = 0,
\t\tconst QString &backgroundColor = QString());''')
    change(vlch, '''\tQByteArray typeOfDevice;''',
           '''\tQByteArray typeOfDevice;
\tQString tihuluCaptionCacheKey;
\tqint64 tihuluCaptionLastSentMs = 0;
\t// Private temporary PNGs are composited by libVLC's logo filter, not a
\t// QWidget covering live video. Keep recent files until VLC has read them.
\tQTemporaryDir tihuluCaptionLogoDir;
\tQString tihuluCaptionLogoActiveFile;
\tQStringList tihuluCaptionLogoFiles;
\tquint64 tihuluCaptionLogoSequence = 0;''')
    # QTemporaryDir owns short-lived AI caption images and removes them at
    # player destruction; the directory is private to this process.
    change(vlch, '#include "../abstractmediawidget.h"\n',
           '#include "../abstractmediawidget.h"\n'
           '#include <QTemporaryDir>\n#include <QStringList>\n')
    vlcc = "src/backend-vlc/vlcmediawidget.cpp"
    change(vlcc, '#include "vlcmediawidget.h"\n',
           '#include "vlcmediawidget.h"\n#include <QColor>\n#include <QDateTime>\n'
           '#include <QDir>\n#include <QFile>\n#include <QFont>\n'
           '#include <QFontMetrics>\n#include <QImage>\n'
           '#include <QPainter>\n')
    change(vlcc, '''\tlibvlc_media_player_set_media(vlcMediaPlayer, vlcMedia);''',
           '''\tlibvlc_media_player_set_media(vlcMediaPlayer, vlcMedia);
\t// A new media/video compositor invalidates the last caption render.
\ttihuluCaptionCacheKey.clear();
\ttihuluCaptionLogoActiveFile.clear();''')
    change(vlcc, '''void VlcMediaWidget::setExternalSubtitle(const QUrl &url)
{''', '''void VlcMediaWidget::setTihuluNativeCaption(const QString &text, bool atTop,
\tint fontSize, int textOpacity, const QString &color,
\tint backgroundPercent, const QString &backgroundColor)
{
\tif (vlcMediaPlayer == NULL) return;
\tif (text.isEmpty() || textOpacity <= 0) {
\t\tif (!tihuluCaptionCacheKey.isEmpty() ||
\t\t    !tihuluCaptionLogoActiveFile.isEmpty()) {
\t\t\tlibvlc_video_set_marquee_int(vlcMediaPlayer, libvlc_marquee_Enable, 0);
\t\t\tlibvlc_video_set_logo_int(vlcMediaPlayer, libvlc_logo_enable, 0);
\t\t\ttihuluCaptionCacheKey.clear();
\t\t\ttihuluCaptionLogoActiveFile.clear();
\t\t}
\t\treturn;
\t}
\tconst QString requestedKey = text + QLatin1Char('|')
\t\t+ QString::number(int(atTop)) + QLatin1Char('|')
\t\t+ QString::number(fontSize) + QLatin1Char('|')
\t\t+ QString::number(textOpacity) + QLatin1Char('|') + color
\t\t+ QLatin1Char('|') + QString::number(backgroundPercent)
\t\t+ QLatin1Char('|') + backgroundColor;
\t// On a DVB tune, VOUT starts after the UI first publishes the caption.
\t// Do not cache an unrenderable caption, and periodically reassert an active
\t// caption after video-output restarts or renderer reconfiguration.
\tif (libvlc_media_player_has_vout(vlcMediaPlayer) <= 0) {
\t\ttihuluCaptionCacheKey.clear();
\t\treturn;
\t}
\tconst qint64 nowMs = QDateTime::currentMSecsSinceEpoch();
\tif (requestedKey == tihuluCaptionCacheKey &&
\t    nowMs - tihuluCaptionLastSentMs < 2000) return;
\tconst bool changed = requestedKey != tihuluCaptionCacheKey;
\ttihuluCaptionCacheKey = requestedKey;
\ttihuluCaptionLastSentMs = nowMs;
\tconst QColor rawColor(color);
\tconst QColor safeColor = rawColor.isValid() ? rawColor : QColor(Qt::white);
\t// VLC marquee has no background-color or background-alpha option.
\t// For nonzero backing opacity, render BOTH the text and its background into
\t// one transparent PNG and composite it INSIDE the native VLC video using
\t// the logo subpicture filter. No QWidget can freeze pixels on top of DVB.
\tif (backgroundPercent > 0 && tihuluCaptionLogoDir.isValid()) {
\t\tif (changed || tihuluCaptionLogoActiveFile.isEmpty()) {
\t\t\tunsigned int videoWidth = 1280, videoHeight = 720;
\t\t\tif (libvlc_video_get_size(vlcMediaPlayer, 0, &videoWidth, &videoHeight) != 0) {
\t\t\t\tvideoWidth = 1280; videoHeight = 720;
\t\t\t}
\t\t\tvideoWidth = qBound(320u, videoWidth, 3840u);
\t\t\tvideoHeight = qBound(240u, videoHeight, 2160u);
\t\t\tconst int maxWidth = qMin(1350, int(videoWidth * 0.86));
\t\t\tconst int fontPx = qBound(16, fontSize, 44);
\t\t\tQFont font;
\t\t\tfont.setPixelSize(fontPx);
\t\t\tfont.setBold(true);
\t\t\tQFontMetrics metrics(font);
\t\t\tconst QString displayText = text.left(1100);
\t\t\tconst int maxHeight = qMin(320, qMax(60, int(videoHeight / 3)));
\t\t\tconst QRect measured = metrics.boundingRect(
\t\t\t\tQRect(0, 0, maxWidth - 44, maxHeight - 20),
\t\t\t\tQt::AlignHCenter | Qt::TextWordWrap, displayText);
\t\t\tconst int width = qBound(160, measured.width() + 44, maxWidth);
\t\t\tconst int height = qBound(42, measured.height() + 24, maxHeight);
\t\t\t// Transparent inset adds a small safe distance from video edges.
\t\t\tconst int edge = 26;
\t\t\tQImage artwork(width, height + edge, QImage::Format_ARGB32);
\t\t\tartwork.fill(Qt::transparent);
\t\t\t{
\t\t\t\tQPainter painter(&artwork);
\t\t\t\tpainter.setRenderHint(QPainter::Antialiasing, true);
\t\t\t\tpainter.setRenderHint(QPainter::TextAntialiasing, true);
\t\t\t\tconst QRect box(2, atTop ? edge : 0, width - 4, height);
\t\t\t\tQColor backing(backgroundColor);
\t\t\t\tif (!backing.isValid()) backing = QColor(Qt::black);
\t\t\t\tbacking.setAlpha(qBound(0, backgroundPercent, 100)*255/100);
\t\t\t\tpainter.setPen(Qt::NoPen);
\t\t\t\tpainter.setBrush(backing);
\t\t\t\tpainter.drawRoundedRect(box, 9, 9);
\t\t\t\tQColor ink(safeColor);
\t\t\t\tink.setAlpha(qBound(0, textOpacity, 100)*255/100);
\t\t\t\tpainter.setPen(ink);
\t\t\t\tpainter.setFont(font);
\t\t\t\tpainter.drawText(box.adjusted(16, 9, -16, -9),
\t\t\t\t\tQt::AlignCenter | Qt::TextWordWrap, displayText);
\t\t\t}
\t\t\tconst QString png = tihuluCaptionLogoDir.path()
\t\t\t\t+ QLatin1String("/subtitle-")
\t\t\t\t+ QString::number(++tihuluCaptionLogoSequence)
\t\t\t\t+ QLatin1String(".png");
\t\t\tif (artwork.save(png, "PNG")) {
\t\t\t\ttihuluCaptionLogoFiles.append(png);
\t\t\t\ttihuluCaptionLogoActiveFile = png;
\t\t\t\t// Keep older PNGs through an asynchronous filter reload; bound
\t\t\t\t// disk use even for long-running TV sessions.
\t\t\t\twhile (tihuluCaptionLogoFiles.size() > 8)
\t\t\t\t\tQFile::remove(tihuluCaptionLogoFiles.takeFirst());
\t\t\t} else {
\t\t\t\t// Do not lose speech if the private temporary folder is full.
\t\t\t\t// The text-only marquee remains a safe fallback.
\t\t\t\ttihuluCaptionLogoActiveFile.clear();
\t\t\t}
\t\t}
\t\tif (!tihuluCaptionLogoActiveFile.isEmpty()) {
\t\t\tlibvlc_video_set_marquee_int(vlcMediaPlayer, libvlc_marquee_Enable, 0);
\t\t\tconst QByteArray filename = QFile::encodeName(tihuluCaptionLogoActiveFile);
\t\t\tlibvlc_video_set_logo_string(vlcMediaPlayer, libvlc_logo_file,
\t\t\t\tfilename.constData());
\t\t\t// VLC subtitle/logo native placement: 4=top-centre, 8=bottom-centre.
\t\t\tlibvlc_video_set_logo_int(vlcMediaPlayer, libvlc_logo_position,
\t\t\t\tatTop ? 4 : 8);
\t\t\tlibvlc_video_set_logo_int(vlcMediaPlayer, libvlc_logo_opacity, 255);
\t\t\tlibvlc_video_set_logo_int(vlcMediaPlayer, libvlc_logo_repeat, -1);
\t\t\tlibvlc_video_set_logo_int(vlcMediaPlayer, libvlc_logo_enable, 1);
\t\t\treturn;
\t\t}
\t}
\t// Transparently backed subtitles keep the lightweight existing native
\t// marquee renderer. Never leave both video subtitle filters enabled.
\tlibvlc_video_set_logo_int(vlcMediaPlayer, libvlc_logo_enable, 0);
\ttihuluCaptionLogoActiveFile.clear();
\t// Set subtitle text/attributes BEFORE starting the libVLC filter.
\tlibvlc_video_set_marquee_int(vlcMediaPlayer, libvlc_marquee_Size,
\t\tqBound(16,fontSize,44));
\tlibvlc_video_set_marquee_int(vlcMediaPlayer, libvlc_marquee_Color,
\t\t(safeColor.red()<<16) | (safeColor.green()<<8) | safeColor.blue());
\tlibvlc_video_set_marquee_int(vlcMediaPlayer, libvlc_marquee_Opacity,
\t\tqBound(0,textOpacity,100)*255/100);
\t// Marquee positions are BIT FLAGS: 4=top-centre, 8=bottom-centre.
\t// libvlc_position_top/bottom are DIFFERENT sequential enum values.
\t// Passing those enum values incorrectly positioned subtitles off-corner.
\tlibvlc_video_set_marquee_int(vlcMediaPlayer, libvlc_marquee_Position,
\t\tatTop ? 4 : 8);
\tconst QByteArray utf8 = text.left(1100).toUtf8();
\tlibvlc_video_set_marquee_string(vlcMediaPlayer, libvlc_marquee_Text,
\t\tutf8.constData());
\tlibvlc_video_set_marquee_int(vlcMediaPlayer, libvlc_marquee_Enable, 1);
}

void VlcMediaWidget::setExternalSubtitle(const QUrl &url)
{''')

    # Kaffeine's OsdWidget already renders ABOVE libVLC's native video
    # surface. Reuse that mechanism in a *separate* caption OSD so the
    # original channel/volume OSD and DVB Teletext continue to work.
    osdh = "src/osdwidget.h"
    change(osdh, '''\tvoid showText(const QString &text, int duration); // duration: msecs
''', '''\tvoid showText(const QString &text, int duration); // duration: msecs
\tvoid showCaption(const QString &text, bool atTop, int pixelSize, int backgroundPercent, int textPercent,
\t\tconst QString &foregroundColor, const QString &backgroundColor,
\t\tconst QRect &videoViewport);
\tvoid hideCaption();
''')
    change(osdh, '''\tOsdObject *osdObject;
\tQTimer *timer;''', '''\tOsdObject *osdObject;
\tQTimer *timer;
\tbool tihuluCaptionMode = false;
\tbool tihuluCaptionTop = false;
\tint tihuluCaptionSize = 25;
\tint tihuluCaptionOpacity = 70;
\tint tihuluCaptionTextOpacity = 100;
\tQString tihuluCaptionForeground = QLatin1String("#FFFFFF");
\tQString tihuluCaptionBackground = QLatin1String("#000000");
\tQString tihuluCaptionText;''')
    osdc = "src/osdwidget.cpp"
    change(osdc, '#include <QPainter>\n', '#include <QPainter>\n#include <QRegion>\n')
    change(osdc, '''void OsdWidget::showObject(OsdObject *osdObject_, int duration)
{''',
    '''void OsdWidget::showCaption(const QString &text, bool atTop,
\tint pixelSize, int backgroundPercent, int textPercent,
\tconst QString &foregroundColor, const QString &backgroundColor,
\tconst QRect &videoViewport)
{
\tif (text.isEmpty() || (backgroundPercent <= 0 && textPercent <= 0)) {
\t\thideCaption();
\t\treturn;
\t}
\tconst QString cleaned = text.left(1100);
\tif (tihuluCaptionMode && tihuluCaptionText == cleaned &&
\t    tihuluCaptionTop == atTop && tihuluCaptionSize == pixelSize &&
\t    tihuluCaptionOpacity == backgroundPercent &&
\t    tihuluCaptionTextOpacity == textPercent &&
\t    tihuluCaptionForeground == foregroundColor &&
\t    tihuluCaptionBackground == backgroundColor)
\t\treturn;
\ttihuluCaptionMode = true;
\ttihuluCaptionText = cleaned;
\ttihuluCaptionTop = atTop;
\ttihuluCaptionSize = qBound(16, pixelSize, 44);
\ttihuluCaptionOpacity = qBound(0, backgroundPercent, 100);
\ttihuluCaptionTextOpacity = qBound(0, textPercent, 100);
\tconst QColor chosenText(foregroundColor);
\tconst QColor chosenBackground(backgroundColor);
\ttihuluCaptionForeground = chosenText.isValid() ? foregroundColor : QLatin1String("#FFFFFF");
\ttihuluCaptionBackground = chosenBackground.isValid() ? backgroundColor : QLatin1String("#000000");
\t// The legacy Qt mode MUST NOT own an X/Wayland window covering the whole
\t// video. A full-size transparent child was retaining stale video frames.
\t// Anchor to the actual VIDEO widget, not the MediaWidget (which includes
\t// controls and may be letterboxed). The small caption strip cannot cover
\t// the whole video or float over an unrelated part of the application.
\tif (parentWidget() != NULL) {
\t\tconst QRect video = videoViewport.intersected(parentWidget()->rect());
\t\tif (video.width() < 120 || video.height() < 80) {
\t\t\thideCaption();
\t\t\treturn;
\t\t}
\t\tQFont face = font();
\t\tface.setPixelSize(tihuluCaptionSize);
\t\tface.setBold(true);
\t\tQFontMetrics metrics(face);
\t\tconst int stripWidth = qMax(100, video.width()-qMin(56,video.width()/10));
\t\tconst QRect measured = metrics.boundingRect(
\t\t\tQRect(0,0,qMax(80,stripWidth-30),270),
\t\t\tQt::TextWordWrap | Qt::AlignHCenter, tihuluCaptionText);
\t\tconst int stripHeight = qBound(48, measured.height()+30,
\t\t\tqMax(48,video.height()/3));
\t\tconst int left = video.left()+qMax(0,(video.width()-stripWidth)/2);
\t\tconst int top = tihuluCaptionTop ? video.top()+18 :
\t\t\tvideo.bottom()-stripHeight-24;
\t\tsetGeometry(left,qBound(video.top(),top,
\t\t\tqMax(video.top(),video.bottom()-stripHeight)),stripWidth,stripHeight);
\t}
\ttimer->stop();
\tshow();
\traise();
\tupdate();
}

void OsdWidget::hideCaption()
{
\tif (tihuluCaptionMode) {
\t\ttihuluCaptionMode = false;
\t\ttihuluCaptionText.clear();
\t\t// No setMask() here: all pixels are cleared transparently
\t\t// by paintEvent, and hiding no longer reconfigures a native window.
\t\thide();
\t}
}

void OsdWidget::showObject(OsdObject *osdObject_, int duration)
{''')
    change(osdc, '''void OsdWidget::paintEvent(QPaintEvent *)
{
\tif (osdObject == NULL) {''',
    '''void OsdWidget::paintEvent(QPaintEvent *)
{
\tif (tihuluCaptionMode) {
\t\tQFont face = font();
\t\tface.setPixelSize(tihuluCaptionSize);
\t\tface.setBold(true);
\t\t// Geometry is sized and anchored only on caption changes.
\t\t// Do not mutate the mask or geometry inside paintEvent.
\t\tQRect box = QWidget::rect().adjusted(7, 7, -7, -7);
\t\tQPainter painter(this);
\t\t// A child QWidget covering libVLC is opaque by default on some
\t\t// X11/Wayland paths. Explicitly CLEAR every repainted pixel;
\t\t// simply drawing an RGBA(0) rectangle previously left a black box.
\t\tpainter.setCompositionMode(QPainter::CompositionMode_Source);
\t\tpainter.fillRect(QWidget::rect(), Qt::transparent);
\t\tpainter.setCompositionMode(QPainter::CompositionMode_SourceOver);
\t\tpainter.setRenderHint(QPainter::Antialiasing);
\t\tif (tihuluCaptionOpacity > 0) {
\t\t\tQColor backing(tihuluCaptionBackground);
\t\t\tbacking.setAlpha(tihuluCaptionOpacity * 255 / 100);
\t\t\tpainter.setPen(Qt::NoPen);
\t\t\tpainter.setBrush(backing);
\t\t\tpainter.drawRoundedRect(box, 8, 8);
\t\t}
\t\tif (tihuluCaptionTextOpacity > 0) {
\t\t\tpainter.setFont(face);
\t\t\tQColor foreground(tihuluCaptionForeground);
\t\t\tforeground.setAlpha(tihuluCaptionTextOpacity * 255 / 100);
\t\t\tpainter.setPen(foreground);
\t\t\tpainter.drawText(box.adjusted(12, 9, -12, -9),
\t\t\t\tQt::AlignHCenter | Qt::AlignVCenter | Qt::TextWordWrap,
\t\t\t\ttihuluCaptionText);
\t\t}
\t\t// Qt must not repeatedly alter a QWidget mask from paintEvent:
\t\t// that schedules further repaints and makes live subtitles flicker.
\t\t// The child is already WA_TranslucentBackground and mouse-transparent.
\t\treturn;
\t}
\tif (osdObject == NULL) {''')

    mediah = "src/mediawidget.h"
    change(mediah, '''\tQString textSubtitlesOff;''',
           '''\tQString textSubtitlesOff;
\t// AI live subtitle is a virtual, user-selectable DVB track in Kaffeine.
\t// Broadcast Teletext/DVB tracks remain owned by their original providers.
\tbool tihuluAiCaptionAvailable = false;
\tbool tihuluAiCaptionSelected = false;
\tbool tihuluAiCaptionUserOverride = false;''')
    mediac = "src/mediawidget.cpp"
    change(mediac, '''void MediaWidget::currentSubtitleChanged(int currentSubtitle)
{
\tif (blockBackendUpdates)
\t\treturn;
''', '''void MediaWidget::currentSubtitleChanged(int currentSubtitle)
{
\tif (blockBackendUpdates)
\t\treturn;
\tif (source->getType() == MediaSource::Dvb && tihuluAiCaptionAvailable) {
\t\tconst bool aiEntry = currentSubtitle == subtitleModel->rowCount()-1;
\t\ttihuluAiCaptionUserOverride = true;
\t\ttihuluAiCaptionSelected = aiEntry;
\t\tif (aiEntry) {
\t\t\t// Selecting the virtual AI track disables broadcast tracks, but
\t\t\t// NEVER closes the DVB stream nor the user-run Whisper service.
\t\t\tsource->setCurrentSubtitle(-1);
\t\t\tbackend->setCurrentSubtitle(0);
\t\t\tsubtitlesChanged();
\t\t\treturn;
\t\t}
\t\t// Choosing off / broadcaster subtitles hides only our overlay.
\t\ttihuluCaptionWidget->hideCaption();
\t\tif (auto *vlc = qobject_cast<VlcMediaWidget *>(backend))
\t\t\tvlc->setTihuluNativeCaption(QString(),false,25,0,QLatin1String("#FFFFFF"));
\t}
''')
    change(mediac, '''\tblockBackendUpdates = true;

\tif (subtitleModel->stringList() != items) {''',
           '''\tif (source->getType() == MediaSource::Dvb && tihuluAiCaptionAvailable) {
\t\t// Add ONE virtual AI entry after all existing Kaffeine subtitles.
\t\t// It is selectable from Playback -> Subtitle without inventing
\t\t// an MPEG-TS subtitle PID, libVLC SPU or external SRT track.
\t\titems << i18n("TIHULU AI · Live Whisper / translations");
\t\tif (tihuluAiCaptionSelected)
\t\t\tcurrentIndex = items.size()-1;
\t}
\tblockBackendUpdates = true;

\tif (subtitleModel->stringList() != items) {''')

    change(mediah, '''\tOsdWidget *osdWidget;
''', '''\tOsdWidget *osdWidget;
\tOsdWidget *tihuluCaptionWidget;
''')
    mediac = "src/mediawidget.cpp"
    change(mediac, '#include <QComboBox>\n',
           '#include <QComboBox>\n#include <QCoreApplication>\n'
           '#include <QDateTime>\n#include <QFile>\n#include <QJsonDocument>\n'
           '#include <QJsonObject>\n#include <QStandardPaths>\n#include <QSharedPointer>\n')
    change(mediac, '''\tosdWidget = new OsdWidget(this);
''',
    '''\tosdWidget = new OsdWidget(this);
\t// Independent on-video subtitles; native Kaffeine OSD is untouched.
\ttihuluCaptionWidget = new OsdWidget(this);
\t// Transparent *child surface*, not only a translucent painted brush.
\t// Without these, a black video-covering rectangle can remain even
\t// when the user selects background opacity = 0%.
\ttihuluCaptionWidget->setAttribute(Qt::WA_TranslucentBackground, true);
\ttihuluCaptionWidget->setAttribute(Qt::WA_NoSystemBackground, true);
\ttihuluCaptionWidget->setAttribute(Qt::WA_OpaquePaintEvent, false);
\ttihuluCaptionWidget->setAttribute(Qt::WA_StyledBackground, false);
\ttihuluCaptionWidget->setAutoFillBackground(false);
\ttihuluCaptionWidget->setAttribute(Qt::WA_TransparentForMouseEvents);
\t// Leave hidden legacy caption child at its minimal initial geometry.
\t// It is resized only into a small caption strip after an opt-in.
\ttihuluCaptionWidget->resize(1, 1);
\tconst QString runtime = QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
\tif (!runtime.isEmpty()) {
\t\tconst QString captionPath = runtime + QLatin1String("/tihulu-caption-")
\t\t\t+ QString::number(QCoreApplication::applicationPid()) + QLatin1String(".json");
\t\tQTimer *captionPoll = new QTimer(this);
\t\t// Resist transient missing/partially written caption IPC files.
\t\tQSharedPointer<qint64> lastValidMs(new qint64(0));
\t\tconnect(captionPoll, &QTimer::timeout, this, [this, captionPath, lastValidMs]() {
\t\t\tauto clearCaption = [this]() {
\t\t\t\ttihuluCaptionWidget->hideCaption();
\t\t\t\tif (auto *vlc = qobject_cast<VlcMediaWidget *>(backend))
\t\t\t\t\tvlc->setTihuluNativeCaption(QString(),false,25,0,QLatin1String("#FFFFFF"));
\t\t\t};
\t\t\tauto setAiAvailability = [this](bool available) {
\t\t\t\tif (tihuluAiCaptionAvailable == available) return;
\t\t\t\ttihuluAiCaptionAvailable = available;
\t\t\t\tif (available && !tihuluAiCaptionUserOverride) {
\t\t\t\t\t// Existing Live Captions default-on behavior is preserved:
\t\t\t\t\t// the AI track becomes the selected native Kaffeine entry.
\t\t\t\t\ttihuluAiCaptionSelected = true;
\t\t\t\t\tsource->setCurrentSubtitle(-1);
\t\t\t\t\tbackend->setCurrentSubtitle(0);
\t\t\t\t} else if (!available) {
\t\t\t\t\ttihuluAiCaptionSelected = false;
\t\t\t\t\ttihuluAiCaptionUserOverride = false;
\t\t\t\t}
\t\t\t\tsubtitlesChanged();
\t\t\t};
\t\t\tif (source->getType() != MediaSource::Dvb) {
\t\t\t\tclearCaption();
\t\t\t\tsetAiAvailability(false);
\t\t\t\treturn;
\t\t\t}
\t\t\tconst qint64 now = QDateTime::currentMSecsSinceEpoch();
\t\t\tQFile file(captionPath);
\t\t\tif (!file.exists() || !file.open(QIODevice::ReadOnly)) {
\t\t\t\tif (now - *lastValidMs > 1000) {
\t\t\t\t\tclearCaption();
\t\t\t\t\tsetAiAvailability(false);
\t\t\t\t}
\t\t\t\treturn;
\t\t\t}
\t\t\tQByteArray bytes = file.read(16385);
\t\t\tif (bytes.size() > 16384) {
\t\t\t\tif (now - *lastValidMs > 1000) {
\t\t\t\t\tclearCaption();
\t\t\t\t\tsetAiAvailability(false);
\t\t\t\t}
\t\t\t\treturn;
\t\t\t}
\t\t\tQJsonDocument doc = QJsonDocument::fromJson(bytes);
\t\t\tif (!doc.isObject()) {
\t\t\t\tif (now - *lastValidMs > 1000) {
\t\t\t\t\tclearCaption();
\t\t\t\t\tsetAiAvailability(false);
\t\t\t\t}
\t\t\t\treturn;
\t\t\t}
\t\t\tQJsonObject obj = doc.object();
\t\t\tif (!obj.value(QLatin1String("enabled")).toBool(false)) {
\t\t\t\t// An explicit OFF remains immediate.
\t\t\t\t*lastValidMs = 0;
\t\t\t\tclearCaption();
\t\t\t\tsetAiAvailability(false);
\t\t\t\treturn;
\t\t\t}
\t\t\tif (obj.value(QLatin1String("expires_ms")).toDouble(0)
\t\t\t      + 1000 < static_cast<double>(now)) {
\t\t\t\tclearCaption();
\t\t\t\tsetAiAvailability(false);
\t\t\t\treturn;
\t\t\t}
\t\t\t*lastValidMs = now;
\t\t\tsetAiAvailability(true);
\t\t\t// The AI reader may keep recognizing for SRT export even when
\t\t\t// Kaffeine's Subtitle menu selects OFF or a broadcaster track.
\t\t\tif (!tihuluAiCaptionSelected) {
\t\t\t\tclearCaption();
\t\t\t\treturn;
\t\t\t}
\t\t\tconst QString text = obj.value(QLatin1String("text")).toString();
\t\t\tconst QString renderMode = obj.value(QLatin1String("render_mode"))
\t\t\t\t.toString(QLatin1String("native"));
\t\t\tVlcMediaWidget *vlc = qobject_cast<VlcMediaWidget *>(backend);
\t\t\tif (renderMode != QLatin1String("legacy-qt")) {
\t\t\t\t// Native video compositing, never a transparent QWidget over XVideo.
\t\t\t\ttihuluCaptionWidget->hideCaption();
\t\t\t\tif (vlc)
\t\t\t\t\tvlc->setTihuluNativeCaption(text,
\t\t\t\t\t\tobj.value(QLatin1String("position")).toString()==QLatin1String("top"),
\t\t\t\t\t\tobj.value(QLatin1String("size")).toInt(25),
\t\t\t\t\t\tobj.value(QLatin1String("text_opacity")).toInt(100),
\t\t\t\t\t\tobj.value(QLatin1String("text_color")).toString(QLatin1String("#FFFFFF")),
\t\t\t\t\t\tobj.value(QLatin1String("opacity")).toInt(0),
\t\t\t\t\t\tobj.value(QLatin1String("background_color")).toString(QLatin1String("#000000")));
\t\t\t\treturn;
\t\t\t}
\t\t\tif (vlc)
\t\t\t\tvlc->setTihuluNativeCaption(QString(),false,25,0,QLatin1String("#FFFFFF"));
\t\t\ttihuluCaptionWidget->showCaption(
\t\t\t\ttext,
\t\t\t\tobj.value(QLatin1String("position")).toString() == QLatin1String("top"),
\t\t\t\tobj.value(QLatin1String("size")).toInt(25),
\t\t\t\tobj.value(QLatin1String("opacity")).toInt(70),
\t\t\t\tobj.value(QLatin1String("text_opacity")).toInt(100),
\t\t\tobj.value(QLatin1String("text_color")).toString(QLatin1String("#FFFFFF")),
\t\t\tobj.value(QLatin1String("background_color")).toString(QLatin1String("#000000")),
\t\t\tbackend->geometry());
\t\t});
\t\tcaptionPoll->start(150);
\t}
''')
    change(mediac, '''\tosdWidget->resize(event->size());
\tQWidget::resizeEvent(event);''',
    '''\tosdWidget->resize(event->size());
\t// Re-anchor the optional legacy strip on the next caption poll.
\t// Never resize a transparent overlay to cover the native video surface.
\ttihuluCaptionWidget->hideCaption();
\tQWidget::resizeEvent(event);''')

    # Use Kaffeine's OWN DVB scan engine; absolutely no w_scan_cpp,
    # dvbv5-scan background child, or second frontend ownership. These
    # multiplexes were physically detected on the original local setup.
    # The user opts into this targeted source from native Configure Television.
    manager = "src/dvb/dvbmanager.cpp"
    change(manager, '''\treturn scanSources.value(type);
}''', '''\tQStringList list = scanSources.value(type);
\tif (type == DvbT2)
\t\tlist.prepend(QLatin1String("TIHULU tested: 538 / 586 / 626 MHz"));
\treturn list;
}''')
    change(manager, '''\treturn scanData.value(scanSource);
}''', '''\t// Selectable, native Kaffeine scan source based on real DVB-T2
\t// multiplexes previously received with this adapter. Not a fake
\t// channel list, and not a replacement for Auto scan.
\tif (scanSource.first == DvbT2 &&
\t    scanSource.second == QLatin1String("TIHULU tested: 538 / 586 / 626 MHz")) {
\t\tQList<DvbTransponder> known;
\t\tconst int hz[] = { 538000000, 586000000, 626000000 };
\t\tfor (int frequency : hz) {
\t\t\t// Use Kaffeine native typed DVB-T2 properties rather than
\t\t\t// guessed scanfile text that may parse to an empty scan.
\t\t\tDvbTransponder transponder(DvbTransponderBase::DvbT2);
\t\t\tDvbT2Transponder *t2 = transponder.as<DvbT2Transponder>();
\t\t\tt2->frequency = frequency;
\t\t\tt2->bandwidth = DvbT2Transponder::Bandwidth8MHz;
\t\t\tt2->modulation = DvbT2Transponder::ModulationAuto;
\t\t\tt2->fecRateHigh = DvbTransponderBase::FecAuto;
\t\t\tt2->fecRateLow = DvbTransponderBase::FecAuto;
\t\t\tt2->transmissionMode = DvbT2Transponder::TransmissionModeAuto;
\t\t\tt2->guardInterval = DvbT2Transponder::GuardIntervalAuto;
\t\t\tt2->hierarchy = DvbT2Transponder::HierarchyAuto;
\t\t\tt2->streamId = 0; // previously tested PLP 0; other PLPs require discovery
\t\t\tknown.append(transponder);
\t\t}
\t\treturn known;
\t}
\treturn scanData.value(scanSource);
}''')
    # Keep native Kaffeine left channel sidebar + video + playback buttons.
    # Only clarify the built-in "Channels" control also opens scan.
    tab = "src/dvb/dvbtab.cpp"
    change(tab, 'i18n("Channels"), this);',
           'i18n("Channels / Antenna Scan"), this);')
    # A full frequency sweep must not silently shrink to the currently
    # playing mux. Kaffeine's original Channels dialog deliberately
    # provides "Current Transponder" when the live view owns the tuner.
    # Add an explicit, confirmation-protected full scanner instead.
    change(tab, '#include <QMenu>\n',
           '#include <QMenu>\n#include <QMessageBox>\n#include <QTimer>\n')
    change(tab, '''\tmenu->addAction(collection->addAction(QLatin1String("dvb_channels"), channelsAction));
''', '''\tmenu->addAction(collection->addAction(QLatin1String("dvb_channels"), channelsAction));
\tQAction *fullScanAction = new QAction(
\t\tQIcon::fromTheme(QLatin1String("edit-find")),
\t\ti18n("Full Antenna Scan..."), this);
\tconnect(fullScanAction, &QAction::triggered, this, &DvbTab::showFullScanDialog);
\tmenu->addAction(collection->addAction(QLatin1String("tihulu_dvb_full_scan"), fullScanAction));
''')
    change(tab, '''void DvbTab::showChannelDialog()
{
\tQDialog *dialog = new DvbScanDialog(manager, this);
''', '''void DvbTab::showFullScanDialog()
{
\t// A running scan owns the sole frontend: resume its existing window.
\tif (scanDialog) {
\t\tscanDialog->show();
\t\tscanDialog->raise();
\t\tscanDialog->activateWindow();
\t\treturn;
\t}
\t// The native DVB scanner needs exclusive tuner ownership for
\t// changing frequencies; Kaffeine's Channels editor can instead
\t// stay attached to a single currently playing transponder.
\tif (manager->getLiveView()->getDevice() != NULL) {
\t\tif (QMessageBox::question(this, i18n("Full Antenna Scan"),
\t\t\ti18n("Stop live TV temporarily to scan multiple frequencies?"),
\t\t\tQMessageBox::Yes | QMessageBox::No, QMessageBox::No) != QMessageBox::Yes)
\t\t\treturn;
\t\tmediaWidget->stop();
\t\t// Give Kaffeine's asynchronous player status updates one event
\t\t// loop turn to release the DVB frontend before the scan dialog opens.
\t\tQTimer::singleShot(750, this, [this]() { showChannelDialog(); });
\t\treturn;
\t}
\tshowChannelDialog();
}

void DvbTab::showChannelDialog()
{
\tQDialog *dialog = new DvbScanDialog(manager, this);
''')

    # Kaffeine's stock Channels dialog is application-modal even while the
    # scanner runs asynchronously. Make it modeless so the user may navigate
    # local media, online radio, subtitles and settings during a long RF sweep.
    # Keep exactly ONE scan dialog / frontend owner, and protect live DVB tuning
    # from stealing the single receiver while it is scanning.
    change(tab, '''void DvbTab::showChannelDialog()
{
\tQDialog *dialog = new DvbScanDialog(manager, this);
\tdialog->setAttribute(Qt::WA_DeleteOnClose, true);
\tdialog->setModal(true);
\tdialog->show();
}''', '''void DvbTab::showChannelDialog()
{
\tif (scanDialog) {
\t\t// Reopening Channels focuses the original running scan.
\t\tscanDialog->show();
\t\tscanDialog->raise();
\t\tscanDialog->activateWindow();
\t\treturn;
\t}
\tDvbScanDialog *dialog = new DvbScanDialog(manager, this);
\tscanDialog = dialog; // QPointer clears when WA_DeleteOnClose destroys it.
\tdialog->setAttribute(Qt::WA_DeleteOnClose, true);
\tdialog->setModal(false);
\tdialog->show();
}''')
    change(tab, '''DvbTab::~DvbTab()
{
\tKSharedConfig::openConfig()->group("DVB")''', '''DvbTab::~DvbTab()
{
\t// Child QObjects may otherwise destroy the manager BEFORE the dialog.
\t// Stop the scanner / release the tuner while its manager still exists.
\tif (scanDialog) {
\t\tdelete scanDialog;
\t\tscanDialog = NULL;
\t}
\tKSharedConfig::openConfig()->group("DVB")''')
    change(tab, '''void DvbTab::playChannel(const DvbSharedChannel &channel, const QModelIndex &index)
{
\tQIcon *icon;''', '''void DvbTab::playChannel(const DvbSharedChannel &channel, const QModelIndex &index)
{
\tif (scanDialog && scanDialog->isScanning()) {
\t\tQMessageBox::information(this, i18n("Antenna scan in progress"),
\t\t\ti18n("Stop or finish the antenna scan before tuning another TV channel. "
\t\t\t     "Other media and application tools remain available."));
\t\treturn;
\t}
\tQIcon *icon;''')
    change(tab, '''void DvbTab::configureDvb()
{
\tQDialog *dialog = new DvbConfigDialog(manager, this);''', '''void DvbTab::configureDvb()
{
\tif (scanDialog) {
\t\t// Changing DVB sources while its channel editor is open would race
\t\t// the editor's cloned channel model or active tuner ownership.
\t\tscanDialog->raise();
\t\tQMessageBox::information(this, i18n("Channel editor is open"),
\t\t\ti18n("Close the Channels window before changing DVB receiver settings."));
\t\treturn;
\t}
\tQDialog *dialog = new DvbConfigDialog(manager, this);''')
    change(tab, '''void DvbTab::instantRecord(bool checked)
{
\tif (checked) {''', '''void DvbTab::instantRecord(bool checked)
{
\tif (checked && scanDialog && scanDialog->isScanning()) {
\t\tinstantRecordAction->setChecked(false);
\t\tQMessageBox::information(this, i18n("Antenna scan in progress"),
\t\t\ti18n("An instant DVB recording cannot start on the tuner during its scan."));
\t\treturn;
\t}
\tif (checked) {''')
    tabhdr = "src/dvb/dvbtab.h"
    change(tabhdr, 'class DvbEpgDialog;', 'class DvbEpgDialog;\nclass DvbScanDialog;')
    change(tabhdr, '\tQPointer<DvbEpgDialog> epgDialog;',
           '\tQPointer<DvbEpgDialog> epgDialog;\n\tQPointer<DvbScanDialog> scanDialog;')
    scan_hdr = "src/dvb/dvbscandialog.h"
    change(scan_hdr, '''\t~DvbScanDialog();

private slots:''', '''\t~DvbScanDialog();
\t// When true, this dialog has a real DvbScan worker and must retain its frontend.
\tbool isScanning() const { return internal != NULL; }

private slots:''')

    # Upstream Kaffeine 2.0.19 returns a pointer to a local QSharedPointer
    # copy in getInstantRecording(). The dangling pointer is dereferenced
    # during channel changes and can crash immediately after scan/import.
    change(tab, '''DvbSharedRecording *DvbTab::getInstantRecording(DvbSharedChannel ch) {
	DvbSharedRecording *ret = NULL;

	QListIterator<DvbSharedRecording> i(instantRecordings);
	while (i.hasNext()) {
		DvbSharedRecording r = i.next();
		if(r.constData()->channel == ch) {
			ret = &r;
			break;
		}
	}

	return ret;
}''', '''DvbSharedRecording *DvbTab::getInstantRecording(DvbSharedChannel ch) {
	// Return the address of an element OWNED by the container, never
	// the address of a loop-local QSharedPointer which dies at scope exit.
	for (int index = 0; index < instantRecordings.size(); ++index) {
		DvbSharedRecording &recording = instantRecordings[index];
		if (recording.constData() != NULL && recording.constData()->channel == ch)
			return &recording;
	}
	return NULL;
}''')

    # Kaffeine 2.0.19 upstream crash in DVB scan result import:
    # sqlFindFreeKey() uses std::prev(end, -1), which tries to move
    # FORWARD from end() rather than backwards to the final QMap entry.
    # With two or more channel additions DvbChannelModel::cloneFrom()
    # dereferences an invalid map iterator and can SIGSEGV. Reported as
    # KDE #503740 / Debian #1110405 / #1103728; fix the actual cause.
    # This is idempotent with change(), so an already-corrected upstream
    # checkout also remains valid. The original empty-container check is
    # retained so prev(end) is never evaluated for an empty map.
    sql_hdr = "src/sqlinterface.h"
    files[sql_hdr] = fix_sql_free_key(files[sql_hdr])

    # Critical guard for native scan/channel-import crashes.
    # The pinned upstream DvbScanDialog releases its exclusive tuner *before*
    # destroying the DvbScan worker in ~DvbScanDialog. The worker can still
    # reference the frontend during destruction. Stop it before releasing.
    scan_cpp = "src/dvb/dvbscandialog.cpp"
    change(scan_cpp, '''DvbScanDialog::~DvbScanDialog()
{
	if (!isLive && device)
		manager->releaseDevice(device, DvbManager::Exclusive);
	delete internal;
}''', '''DvbScanDialog::~DvbScanDialog()
{
	// Stop pending signal/quality polling while the frontend is torn down.
	statusTimer.stop();
	// A live scan must stop using the frontend BEFORE exclusive release.
	delete internal;
	internal = NULL;
	if (!isLive && device) {
		manager->releaseDevice(device, DvbManager::Exclusive);
		device = NULL;
	}
}''')
    change(scan_cpp, '''void DvbScanDialog::dialogAccepted()
{
	manager->getChannelModel()->cloneFrom(channelModel);''',
    '''void DvbScanDialog::dialogAccepted()
{
	// Never mutate/flush the channel model while the scanner is still
	// delivering foundChannels and holding a backend tuner.
	if (internal != NULL) {
		QSignalBlocker blocker(scanButton);
		scanButton->setChecked(false);
		scanButtonClicked(false);
	}
	manager->getChannelModel()->cloneFrom(channelModel);''')
    change(scan_cpp, '#include <QComboBox>\n',
           '#include <QComboBox>\n#include <QSignalBlocker>\n')
    change(scan_cpp, '''void DvbScanDialog::updateStatus()
{
	if (device->getDeviceState() != DvbDevice::DeviceIdle) {''',
    '''void DvbScanDialog::updateStatus()
{
	// A queued status tick can arrive just after stop/release.
	if (device == NULL) return;
	if (device->getDeviceState() != DvbDevice::DeviceIdle) {''')
    change(scan_cpp, '''			DvbChannel newChannel(*channel);
			channelModel->addChannel(newChannel);''',
    '''			if (channel == NULL) continue; // removed during scan/selection
			DvbChannel newChannel(*channel);
			channelModel->addChannel(newChannel);''')
    change(scan_cpp, '''void DvbScanDialog::scanFinished()
{
	// the state may have changed because the signal is queued''',
    '''void DvbScanDialog::scanFinished()
{
	// A previously queued completion must not stop a different scan.
	if (internal == NULL) return;
	// the state may have changed because the signal is queued''')

    # Selecting a fresh DVB-T2 tuner must be immediately scannable.
    # Do not override a saved user-selected source; use Kaffeine's own
    # real full-frequency AUTO-T2-Normal scan only if none is configured.
    config_page = "src/dvb/dvbconfigdialog.cpp"
    change(config_page,
           '''	sourceBox->setCurrentIndex(sourceIndex + 1);''',
           '''	// No Source is not a usable default for an auto-scannable T2 tuner.
	// Keep all explicit saved scan sources unchanged.
	if (isGen2 && config->getTransmissionType() == DvbConfigBase::DvbT &&
	    config->scanSource.isEmpty())
		sourceBox->setCurrentIndex(1); // Kaffeine AUTO-T2-Normal
	else
		sourceBox->setCurrentIndex(sourceIndex + 1);''')

    tabhdr = "src/dvb/dvbtab.h"
    change(tabhdr, '\tvoid showChannelDialog();',
           '\tvoid showChannelDialog();\n\tvoid showFullScanDialog();')

    # KAboutData already registers --help/--help-all/--version; avoid
    # duplicate h, help-all and v aliases observed in the user's logs.
    appmain = "src/main.cpp"
    change(appmain, '''\tapp.parser.addVersionOption();
\tapp.parser.addHelpOption();
\taboutData->setupCommandLine(&app.parser);''',
    '''\t// KAboutData registers Qt help/version aliases exactly once.
\taboutData->setupCommandLine(&app.parser);''')

    # Global EPG category tables previously executed kli18n().toString()
    # BEFORE main initialized KLocalizedString's application domain.
    # Lazy function-local statics preserve all existing translations.
    epg = "src/dvb/dvbepg.cpp"
    source_epg = files[epg]
    for name, dimensions in (
        ("contentStr", "[16][16]"),
        ("nibble1Str", "[16]"),
        ("braNibble1Str", "[16]"),
        ("braNibble2Str", "[16][16]"),
    ):
        qualifier = "const " if name != "braNibble2Str" else ""
        declaration = "static " + qualifier + "QByteArray " + name + dimensions + " = {"
        first = source_epg.find(declaration)
        if first < 0:
            raise ValueError("Missing EPG genre table: " + name)
        close = source_epg.find("};", first)
        if close < 0:
            raise ValueError("Unterminated EPG genre table: " + name)
        original = source_epg[first:close+2]
        function = ("static " + qualifier + "QByteArray (&" + name + "())" +
            dimensions + "\n{\n\tstatic " + qualifier + "QByteArray values" +
            dimensions + " = {" + original.split("= {",1)[1][:-2] +
            "};\n\treturn values;\n}")
        source_epg = source_epg[:first] + function + source_epg[close+2:]
        source_epg = source_epg.replace(name + "[nibble1]", name + "()[nibble1]")
    files[epg] = source_epg

    return files

def apply(root: Path):
    root = root.resolve(strict=True)
    source = {path: (root / path).read_text(encoding="utf-8") for path in PATHS}
    new = transform(source)
    for path in PATHS:
        (root / path).write_text(new[path], encoding="utf-8")
        print("Patched upstream Kaffeine:", path)
    # Header is original TIHULU Qt integration, not copied from welle.io.
    # Rebuilds use a detached clean upstream Kaffeine worktree.
    widget = Path(__file__).with_name("native_radio_tab.h")
    if not widget.is_file():
        raise RuntimeError("Native radio tab template missing from pinned source")
    dest = root / "src/tihulu_radio_tab.h"
    if dest.exists() and dest.read_text(encoding="utf-8") != widget.read_text(encoding="utf-8"):
        raise RuntimeError("Refusing to overwrite unrelated native radio header")
    dest.write_text(widget.read_text(encoding="utf-8"),encoding="utf-8")
    print("Installed native Kaffeine radio page:", dest)
    hardware = Path(__file__).with_name("native_hardware_tab.h")
    if not hardware.is_file():
        raise RuntimeError("Native hardware tab template missing")
    hardware_dest = root / "src/tihulu_hardware_tab.h"
    if hardware_dest.exists() and (
            hardware_dest.read_text(encoding="utf-8") != hardware.read_text(encoding="utf-8")):
        raise RuntimeError("Refusing to overwrite unrelated native hardware header")
    hardware_dest.write_text(hardware.read_text(encoding="utf-8"),encoding="utf-8")
    print("Installed native Hardware page:",hardware_dest)
    recording_template=Path(__file__).with_name("native_unified_recorder.h")
    if not recording_template.is_file():
        raise RuntimeError("Native universal recorder template missing")
    record_dest=root / "src/tihulu_unified_recorder.h"
    if record_dest.exists() and (
        record_dest.read_text(encoding="utf-8") != recording_template.read_text(encoding="utf-8")):
        raise RuntimeError("Refusing to overwrite unrelated recording header")
    record_dest.write_text(recording_template.read_text(encoding="utf-8"),encoding="utf-8")
    print("Installed native unified Record/Stop + Library:",record_dest)
    panel = Path(__file__).with_name("native_media_panel.h")
    if not panel.is_file():
        raise RuntimeError("In-player local media AI template is missing")
    media_dest = root / "src/tihulu_media_panel.h"
    if media_dest.exists() and media_dest.read_text(encoding="utf-8") != panel.read_text(encoding="utf-8"):
        raise RuntimeError("Refusing to overwrite unrelated native media panel")
    media_dest.write_text(panel.read_text(encoding="utf-8"),encoding="utf-8")
    print("Installed in-player offline media AI controls:",media_dest)
    web_template = Path(__file__).with_name("native_web_tv_dialog.h")
    if not web_template.is_file():
        raise RuntimeError("Native internet television dialog is missing")
    web_dest = root / "src/tihulu_web_tv_dialog.h"
    if web_dest.exists() and web_dest.read_text(encoding="utf-8") != web_template.read_text(encoding="utf-8"):
        raise RuntimeError("Refusing to overwrite unrelated internet television header")
    web_dest.write_text(web_template.read_text(encoding="utf-8"), encoding="utf-8")
    print("Installed native internet television catalogue:", web_dest)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 patch_upstream.py /path/to/pinned/kaffeine")
    apply(Path(sys.argv[1]))
