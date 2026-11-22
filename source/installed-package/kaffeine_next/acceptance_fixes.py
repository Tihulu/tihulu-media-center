# SPDX-License-Identifier: GPL-2.0-or-later
"""Owner round-2 corrections, applied to the pinned transformed upstream."""
def transform(files):
    def replace(path, old, new):
        if files[path].count(old) != 1:
            raise ValueError("Unexpected acceptance source: " + path + " " + repr(old[:60]))
        files[path] = files[path].replace(old, new, 1)

    main = "src/mainwindow.cpp"
    replace(main, '#include "tihulu_media_panel.h"',
            '#include "tihulu_media_panel.h"\n#include "tihulu_theme.h"')
    replace(main, '\tmenu = new QMenu(i18n("&Settings"), this);\n\tmenuBar->addMenu(menu);',
            '\tmenu = new QMenu(i18n("&Settings"), this);\n\tmenuBar->addMenu(menu);\n'
            '\tTihuluTheme::install(menu);')
    vlc = "src/backend-vlc/vlcmediawidget.cpp"
    replace(vlc, '#include <QSettings>', '#include <QSettings>\n#include "../tihulu_playback_profile.h"')
    if files[vlc].count('qgetenv("TIHULU_VLC_PROFILE")') != 4:
        raise ValueError("Unexpected libVLC playback profile sites")
    files[vlc] = files[vlc].replace('qgetenv("TIHULU_VLC_PROFILE")', 'tihuluPlaybackProfile()')
    replace(vlc, 'if (option == QLatin1String("--avcodec-hw")) {',
            'if (option == QLatin1String("--avcodec-hw") || option == QLatin1String("--vout")) {')
    replace(vlc, 'option.startsWith(QLatin1String("--avcodec-hw="))) {',
            'option.startsWith(QLatin1String("--avcodec-hw=")) || option.startsWith(QLatin1String("--vout="))) {')
    replace(vlc, 'args.append(QLatin1String(" --avcodec-hw=none"));',
            'args.append(QLatin1String(" --avcodec-hw=none --vout=xcb_x11"));')
    replace(vlc, '"--no-video-title-show", "--no-audio" };',
            '"--no-video-title-show", "--vout=xcb_x11", "--no-audio" };')
    replace(vlc, 'profile == "software-no-audio" ? 3 : 2, fallbackArgs);',
            'profile == "software-no-audio" ? 4 : 3, fallbackArgs);')

    # Seed only the FIRST newly discovered terrestrial device, so the
    # ordinary Terrestrial (T2) entry replaces the shorter Terrestrial
    # entry that alphabetical QMap ordering would otherwise select first.
    manager = "src/dvb/dvbmanager.cpp"
    before = '\t\t\tdeviceConfigs.append(DvbDeviceConfig(deviceId, frontendName, device));\n\t\t\tbreak;'
    replace(manager, before, '\t\t\tDvbDeviceConfig added(deviceId, frontendName, device);\n\t\t\tstatic bool tihuluTerrestrialSeedDone = false;\n\t\t\t// Existing saved configs, including an intentional No Source,\n\t\t\t// remain authoritative. New devices are made ready ONE time.\n\t\t\tif (!tihuluTerrestrialSeedDone &&\n\t\t\t    (device->getTransmissionTypes() & (DvbDevice::DvbT | DvbDevice::DvbT2))) {\n\t\t\t\ttihuluTerrestrialSeedDone = true;\n\t\t\t\tconst bool t2 = device->getTransmissionTypes() & DvbDevice::DvbT2;\n\t\t\t\tDvbConfig config(new DvbConfigBase(DvbConfigBase::DvbT));\n\t\t\t\tconfig->name = t2 ? i18n("Terrestrial (T2)") : i18n("Terrestrial");\n\t\t\t\tconfig->scanSource = t2 ? QLatin1String("AUTO-T2-Normal") : QLatin1String("AUTO-T-Normal");\n\t\t\t\tconfig->timeout = 1500;\n\t\t\t\tconfig->numberOfTuners = 1;\n\t\t\t\tadded.configs.append(config);\n\t\t\t}\n\t\t\tdeviceConfigs.append(added);\n\t\t\tupdateSourceMapping();\n\t\t\tbreak;\n')
    # Lazy table initialization avoids translations before application domain setup.
    epg = "src/dvb/dvbepg.cpp"
    begin = files[epg].index("static const QByteArray braRating[] = {")
    end = files[epg].index("};", begin) + 2
    table = files[epg][begin:end]
    replacement = ("static const QByteArray (&braRating())[7]\n{\n\t" +
        table.replace("static const QByteArray braRating[]", "static const QByteArray values[7]", 1) +
        "\n\treturn values;\n}")
    files[epg] = files[epg][:begin] + replacement + files[epg][end:]
    files[epg] = files[epg].replace("braRating[", "braRating()[").replace("ARRAY_SIZE(braRating)", "ARRAY_SIZE(braRating())")
    replace("src/main.cpp", "\tKAboutData::setApplicationData(aboutData);",
            "\taboutData.setOrganizationDomain(\"tihulu.local\");\n\tKAboutData::setApplicationData(aboutData);")
    # 5) Live TV recording without a second tuner: tee the already-filtered
    # service TS into a user-chosen file. Silence creates nothing, an existing
    # file is never overwritten, I/O failure keeps the partial file.
    replace("src/dvb/dvbliveview_p.h", '#include <QFile>',
           '#include <QFile>\n#include "livecapture.h"')
    replace("src/dvb/dvbliveview_p.h", '\tQFile timeShiftFile;',
           '\tLiveCapture capture;\n\tQFile timeShiftFile;')
    live = "src/dvb/dvbliveview.cpp"
    replace(live, 'void DvbLiveView::insertPatPmt()\n{\n\tinternal->buffer.append(internal->patGenerator.generatePackets());\n\tinternal->buffer.append(internal->pmtGenerator.generatePackets());\n}',
           'bool DvbLiveView::beginCapture(const QString &path)\n'
           '{\n'
           '\treturn device && channel.isValid() && internal->capture.begin(path);\n'
           '}\n\n'
           'void DvbLiveView::endCapture()\n'
           '{\n'
           '\tif (!internal->capture.active()) return;\n'
           '\tQString reason;\n'
           '\tconst QString path = internal->capture.finish(reason);\n'
           '\temit captureFinished(path, reason);\n'
           '}\n\n'
           'QString DvbLiveView::captureError() const { return internal->capture.failure(); }\n'
           'bool DvbLiveView::waitingForDevice() const { return channel.isValid() && !device && internal->tihuluDeviceRetryCount > 0; }\n\n'
           'void DvbLiveView::insertPatPmt()\n'
           '{\n'
           '\tconst QByteArray pat = internal->patGenerator.generatePackets();\n'
           '\tconst QByteArray pmt = internal->pmtGenerator.generatePackets();\n'
           '\tinternal->capture.tables(pat, pmt);\n'
           '\tinternal->buffer.append(pat);\n'
           '\tinternal->buffer.append(pmt);\n'
           '}')
    replace(live, 'void DvbLiveViewInternal::processData(const char data[188])\n{\n\tbuffer.append(data, 188);',
           'void DvbLiveViewInternal::processData(const char data[188])\n{\n\tcapture.packet(data);\n\tbuffer.append(data, 188);')
    replace(live, 'void DvbLiveView::stopDevice()\n{', 'void DvbLiveView::stopDevice()\n{\n\tendCapture(); // finalize the old service before retune or device release')
    replace(live, 'DvbLiveView::~DvbLiveView()\n{\n}', 'DvbLiveView::~DvbLiveView()\n{\n\tendCapture();\n}')
    replace("src/dvb/dvbliveview.h", '\tDvbDevice *getDevice() const;',
           '\tDvbDevice *getDevice() const;\n'
           '\tbool beginCapture(const QString &path);\n'
           '\tvoid endCapture();\n'
           '\tQString captureError() const;\n'
           '\tbool waitingForDevice() const;')
    replace("src/dvb/dvbliveview.h", 'signals:\n',
           'signals:\n\tvoid captureFinished(const QString &path, const QString &error);\n')

    # 6) Never leak a DVB frontend fd into exec'd helper processes.
    dev = "src/dvb/dvbdevice_linux.cpp"
    legacy_open = 'dvb_fe_open2(adapter, index, verbose, 0, dvbv5_log)'
    if files[dev].count(legacy_open) != 2:
        raise ValueError("Unexpected DVB frontend open sites")
    files[dev] = files[dev].replace(legacy_open,
        'dvb_fe_open_flags(adapter, index, verbose, 0, dvbv5_log, O_RDWR | O_CLOEXEC)')



    # The TV toolbar and shared REC button use the same selected-stream writer.
    replace("src/dvb/dvbtab.h", "public slots:\n", "signals:\n\tvoid quickRecordRequested();\n\npublic slots:\n")
    replace("src/dvb/dvbtab.cpp", "\tinstantRecordAction->setCheckable(true);", "\tinstantRecordAction->setCheckable(false);")
    replace("src/dvb/dvbtab.cpp", "\tconnect(instantRecordAction, SIGNAL(triggered(bool)), this, SLOT(instantRecord(bool)));",
            "\tconnect(instantRecordAction,&QAction::triggered,this,[this](){emit quickRecordRequested();});")

    # Central media events cover File/Open, playlist, drag-drop and recordings.
    media = "src/mediawidget.cpp"
    replace("src/mediawidget.h", "signals:\n", "signals:\n"
            "\tvoid stopRequested();\n"
            "\tvoid sourceOpened(const QUrl &url);\n"
            "\tvoid fileOpenRequested(const QUrl &url, bool *handled);\n"
            "\tvoid subtitleOpened(const QUrl &url, bool *handled);\n")
    replace(media, "void MediaWidget::stop()\n{", "void MediaWidget::stop()\n{\n\temit stopRequested();")
    replace(media, "void MediaWidget::playbackFinished()\n{", "void MediaWidget::playbackFinished()\n{\n\temit stopRequested();")
    replace(media, "\tactionStop->setEnabled(playing);", "\tactionStop->setEnabled(true); // Stop also cancels an offline AI job.")
    replace(media, "void MediaWidget::play(const QUrl &url, const QUrl &subtitleUrl)\n{",
            "void MediaWidget::play(const QUrl &url, const QUrl &subtitleUrl)\n{\n"
            "\tbool handled=false; emit fileOpenRequested(url,&handled); if(handled)return;")
    replace(media, "\tsource->setMediaWidget(this);", "\temit sourceOpened(source->getType()==MediaSource::Url ? source->getUrl() : QUrl());\n\tsource->setMediaWidget(this);")
    replace(media, "\tbackend->setExternalSubtitle(url);", "\tbool handled=false; emit subtitleOpened(url,&handled);\n\tif(!handled)backend->setExternalSubtitle(url);")
    # Remove the old File/Open-only gate: the player now routes every source.
    begin=files[main].index("\t// Keep local video/audio player *inside* this Playback tab.")
    end=files[main].index("\n\tactionOpenRecent->addUrl(copy);",begin)+1
    files[main]=files[main][:begin]+files[main][end:]
    # The old gate contains an earlier indented addUrl; validate its removal.
    if "playerTab->prepareLocalFileOpen(copy)" in files[main]:
        raise ValueError("Old file-only gate survived")

    replace(main, '#include "tihulu_theme.h"', '#include "tihulu_theme.h"\n#include "tihulu_ai_process.h"')
    # Explicit repair action for a stray VLC window after a reparent.
    replace(media, "\tvideoMenu->addMenu(autoResizeMenu);",
            "\tvideoMenu->addMenu(autoResizeMenu);\n"
            "\tQAction *reembedAction = videoMenu->addAction(i18n(\"Re-embed video surface\"));\n"
            "\tconnect(reembedAction, &QAction::triggered, this, [this]() {\n"
            "\t\tif (auto *vlc = qobject_cast<VlcMediaWidget *>(backend))\n"
            "\t\t\tif (vlc->tihuluReassertSurface())\n"
            "\t\t\t\tosdWidget->showText(i18nc(\"osd message\", \"Video surface re-embedded\"), 2000);\n"
            "\t});")

    # Video surface: embedded (default) or a separate VLC window, plus a
    # self-healing re-assert of the embedded surface when the video output
    # restarts after a reparent (previously produced a stray VLC window).
    vlc = "src/backend-vlc/vlcmediawidget.cpp"
    replace(vlc, "libvlc_media_player_set_xwindow(vlcMediaPlayer, quint32(winId()));",
            "if(!tihuluSeparateVideoSurface())libvlc_media_player_set_xwindow(vlcMediaPlayer, quint32(winId()));")
    replace(vlc, "libvlc_media_player_set_media(vlcMediaPlayer, vlcMedia);",
            "libvlc_media_player_set_media(vlcMediaPlayer, vlcMedia);\n"
            "\tif(!tihuluSeparateVideoSurface())libvlc_media_player_set_xwindow(vlcMediaPlayer, quint32(winId()));")
    replace("src/backend-vlc/vlcmediawidget.h", "bool registerEvents();",
            "bool registerEvents();\n"
            "\tbool tihuluReassertSurface();\n")
    # Self-healing: rebind the embedded surface when the video output restarts.
    replace(vlc, "void VlcMediaWidget::playDirection(int direction)",
            "bool VlcMediaWidget::tihuluReassertSurface()\n"
            "{\n"
            "\tif(tihuluSeparateVideoSurface() || vlcMediaPlayer==nullptr)return false;\n"
            "\tif(libvlc_media_player_get_state(vlcMediaPlayer)!=libvlc_Playing)return false;\n"
            "\tif(libvlc_media_player_has_vout(vlcMediaPlayer)>0)return false;\n"
            "\tlibvlc_media_player_set_xwindow(vlcMediaPlayer, quint32(winId()));\n"
            "\tsetAttribute(Qt::WA_NativeWindow);\n"
            "\treturn true;\n"
            "}\n\n"
            "void VlcMediaWidget::playDirection(int direction)")
    # A local file with a sidecar <name>.srt plays with it attached, so a
    # finished recording or an exported file never starts without subtitles.
    replace("src/mediawidget.cpp", "\tbool handled=false; emit fileOpenRequested(url,&handled); if(handled)return;",
            "\tbool handled=false; emit fileOpenRequested(url,&handled); if(handled)return;\n"
            "\tQUrl effectiveSubtitle=subtitleUrl;\n"
            "\tif(effectiveSubtitle.isEmpty() && url.isLocalFile()) {\n"
            "\t\tconst QString media=url.toLocalFile();\n"
            "\t\tconst int dot=media.lastIndexOf(QLatin1Char('.'));\n"
            "\t\tconst QString sidecar=(dot>0?media.left(dot):media)+QLatin1String(\".srt\");\n"
            "\t\tif(QFileInfo::exists(sidecar))effectiveSubtitle=QUrl::fromLocalFile(sidecar);\n"
            "\t}")
    replace("src/mediawidget.cpp", "\tplay(new MediaSourceUrl(url, subtitleUrl));",
            "\tplay(new MediaSourceUrl(url, effectiveSubtitle));")

    replace(main, '#include "tihulu_ai_process.h"',
            '#include "tihulu_ai_process.h"\n#include <QLocalSocket>')
    replace(main, '\tconnect(captionAction, &QAction::triggered, this, [this]() {',
            '\tauto *tvCaptionJob = new TihuluAiProcess(this);\n'
            '\t// Stop in any mode also tells the caption service to stop ASR and\n'
            '\t// release Whisper/translator work; the panel stays usable.\n'
            '\tauto tihuluStopCaptionService=[](){\n'
            '\t\tconst QString runtime=QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);\n'
            '\t\tif(runtime.isEmpty())return;\n'
            '\t\tconst QString path=runtime+QLatin1String("/tihulu-captions-control-")+\n'
            '\t\t\tQString::number(QCoreApplication::applicationPid())+QLatin1String(".sock");\n'
            '\t\tif(!QFileInfo::exists(path))return;\n'
            '\t\tQLocalSocket request;\n'
            '\t\trequest.connectToServer(path);\n'
            '\t\tif(request.waitForConnected(250)){\n'
            '\t\t\trequest.write("STOP");request.flush();request.waitForBytesWritten(250);\n'
            '\t\t\trequest.disconnectFromServer();\n'
            '\t\t}\n'
            '\t};\n'
            '\tconnect(mediaWidget,&MediaWidget::stopRequested,this,[tvCaptionJob,tihuluStopCaptionService](){tvCaptionJob->stopJob();tihuluStopCaptionService();});\n'
            '\tconnect(mediaWidget,&MediaWidget::sourceOpened,this,[tvCaptionJob](const QUrl &url){if(url.isValid())tvCaptionJob->stopJob();});\n'
            '\tconnect(captionAction, &QAction::triggered, this, [this,tvCaptionJob]() {')
    replace(main, '\t\tif (!QProcess::startDetached(QLatin1String("tihulu-tv-center"),\n'
            '\t\t\tQStringList() << QLatin1String("kaffeine-captions")\n'
            '\t\t\t\t<< QLatin1String("--socket") << name))',
            '\t\tif(tvCaptionJob->state()!=QProcess::NotRunning) {\n'
            '\t\t\t// A short focus request uses the existing controller socket.\n'
            '\t\t\tQProcess::startDetached(QLatin1String("tihulu-tv-center"), {QLatin1String("kaffeine-captions"),QLatin1String("--socket"),name,QLatin1String("--show-only")});\n'
            '\t\t\treturn;\n\t\t}\n'
            '\t\ttvCaptionJob->start(QLatin1String("tihulu-tv-center"), {QLatin1String("kaffeine-captions"),QLatin1String("--socket"),name});\n'
            '\t\tif (!tvCaptionJob->waitForStarted(800))')

    # Private playback-position file: the local-file caption service reads
    # the real player clock instead of guessing timestamps.
    replace("src/mediawidget.h", '\tQMenu *angleMenu;',
            '\tQMenu *angleMenu;\n\tQTimer *tihuluFilePositionTimer=nullptr;\n\tQUrl tihuluFilePositionUrl;\n\tvoid startFilePositionPublishing(const QUrl &url);\n\tvoid writeFilePositionState();\n\tvoid stopFilePositionPublishing();')
    replace("src/mediawidget.cpp", 'void MediaWidget::play(const QUrl &url, const QUrl &subtitleUrl)\n{',
            'void MediaWidget::startFilePositionPublishing(const QUrl &url)\n{\n\tif(!url.isLocalFile() || !QFileInfo(url.toLocalFile()).isFile()) {\n\t\tstopFilePositionPublishing();\n\t\treturn;\n\t}\n\tif(!tihuluFilePositionTimer) {\n\t\ttihuluFilePositionTimer=new QTimer(this);\n\t\ttihuluFilePositionTimer->setInterval(400);\n\t\tconnect(tihuluFilePositionTimer,&QTimer::timeout,this,&MediaWidget::writeFilePositionState);\n\t}\n\ttihuluFilePositionUrl=url;\n\twriteFilePositionState();\n\ttihuluFilePositionTimer->start();\n}\n\nvoid MediaWidget::writeFilePositionState()\n{\n\tconst QString runtime=QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);\n\tif(runtime.isEmpty() || !tihuluFilePositionUrl.isLocalFile())return;\n\tconst QString path=tihuluFilePositionUrl.toLocalFile();\n\tconst bool playing=getPlaybackStatus()!=MediaWidget::Idle;\n\tconst QByteArray state=QByteArrayLiteral("{\\"path\\":\\"")+path.toUtf8()+\n\t\tQByteArrayLiteral("\\",\\"position_ms\\":")+QByteArray::number(getPosition())+\n\t\tQByteArrayLiteral(",\\"playing\\":")+(playing?QByteArrayLiteral("true"):QByteArrayLiteral("false"))+\n\t\tQByteArrayLiteral("}");\n\tQFile file(runtime+QLatin1String("/tihulu-file-position-")+\n\t\tQString::number(QCoreApplication::applicationPid())+QLatin1String(".json"));\n\tif(!file.open(QIODevice::WriteOnly|QIODevice::Truncate))return;\n\tfile.write(state);file.flush();file.close();\n}\n\nvoid MediaWidget::stopFilePositionPublishing()\n{\n\tif(tihuluFilePositionTimer)tihuluFilePositionTimer->stop();\n\ttihuluFilePositionUrl.clear();\n\tconst QString runtime=QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);\n\tif(runtime.isEmpty())return;\n\tQFile::remove(runtime+QLatin1String("/tihulu-file-position-")+\n\t\tQString::number(QCoreApplication::applicationPid())+QLatin1String(".json"));\n}\n\nvoid MediaWidget::play(const QUrl &url, const QUrl &subtitleUrl)\n{')
    replace(media, '\tplay(new MediaSourceUrl(url, effectiveSubtitle));',
            '\tplay(new MediaSourceUrl(url, effectiveSubtitle));\n\tstartFilePositionPublishing(url);\n\t// A local recording or export should start with OUR generated SRT track\n\t// (the last one); broadcaster tracks stay selectable after it.\n\tQTimer::singleShot(1800,this,[this](){\n\t\tif(!tihuluFilePositionUrl.isLocalFile() ||\n\t\t   getPlaybackStatus()==MediaWidget::Idle)return;\n\t\tif(subtitleBox && subtitleBox->count()>1 &&\n\t\t   subtitleBox->currentIndex()==0)\n\t\t\tsubtitleBox->setCurrentIndex(subtitleBox->count()-1);\n\t});')
    replace(media, 'void MediaWidget::stop()\n{\n\temit stopRequested();',
            'void MediaWidget::stop()\n{\n\temit stopRequested();\n\tstopFilePositionPublishing();')
    replace(media, 'void MediaWidget::playbackFinished()\n{\n\temit stopRequested();',
            'void MediaWidget::playbackFinished()\n{\n\temit stopRequested();\n\tstopFilePositionPublishing();')
    return files
