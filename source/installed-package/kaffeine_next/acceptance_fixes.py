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
    replace(main, '\tconnect(captionAction, &QAction::triggered, this, [this]() {',
            '\tauto *tvCaptionJob = new TihuluAiProcess(this);\n'
            '\tconnect(mediaWidget,&MediaWidget::stopRequested,this,[tvCaptionJob](){tvCaptionJob->stopJob();});\n'
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

    return files
