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
    return files
