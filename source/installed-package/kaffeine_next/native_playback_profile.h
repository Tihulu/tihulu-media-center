// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef TIHULU_PLAYBACK_PROFILE_H
#define TIHULU_PLAYBACK_PROFILE_H
#include <QByteArray>
#include <QSettings>
inline QByteArray tihuluPlaybackProfile() {
    const QByteArray requested=qgetenv("TIHULU_VLC_PROFILE");
    if(!requested.isEmpty())return requested;
    QSettings prefs(QStringLiteral("TIHULU"),QStringLiteral("Playback"));
    return prefs.value(QStringLiteral("profile"),QStringLiteral("software")).toByteArray();
}
inline bool tihuluSeparateVideoSurface() {
    QSettings prefs(QStringLiteral("TIHULU"),QStringLiteral("Playback"));
    return prefs.value(QStringLiteral("videoSurface"),QStringLiteral("embedded"))
        .toString()==QLatin1String("separate");
}
#endif
