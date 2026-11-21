// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef TIHULU_NATIVE_THEME_H
#define TIHULU_NATIVE_THEME_H
#include <QApplication>
#include <QActionGroup>
#include <QMenu>
#include <QPalette>
#include <QSettings>
#include <QStyleFactory>

namespace TihuluTheme {
inline QPalette palette(bool dark) {
    QPalette p;
    const QColor window(dark?"#18222d":"#f4f6f8");
    const QColor text(dark?"#ecf1f6":"#17212b");
    const QColor base(dark?"#111a23":"#ffffff");
    const QColor button(dark?"#293b4b":"#e5ebf1");
    for(auto group:{QPalette::Active,QPalette::Inactive,QPalette::Disabled}) {
        const QColor ink=group==QPalette::Disabled?QColor(dark?"#a6b3c0":"#596673"):text;
        p.setColor(group,QPalette::Window,window);
        p.setColor(group,QPalette::WindowText,ink);
        p.setColor(group,QPalette::Base,base);
        p.setColor(group,QPalette::AlternateBase,button);
        p.setColor(group,QPalette::Text,ink);
        p.setColor(group,QPalette::Button,button);
        p.setColor(group,QPalette::ButtonText,ink);
        p.setColor(group,QPalette::ToolTipBase,base);
        p.setColor(group,QPalette::ToolTipText,text);
        p.setColor(group,QPalette::Highlight,QColor("#145c8e"));
        p.setColor(group,QPalette::HighlightedText,Qt::white);
        p.setColor(group,QPalette::Link,QColor(dark?"#83cbff":"#075d96"));
        p.setColor(group,QPalette::Mid,QColor(dark?"#637589":"#8999a9"));
        p.setColor(group,QPalette::Light,QColor(dark?"#42576a":"#ffffff"));
        p.setColor(group,QPalette::Dark,QColor(dark?"#0d141b":"#687787"));
    }
    return p;
}
inline void install(QMenu *settingsMenu) {
    const QPalette system=qApp->palette();
    qApp->setStyle(QStyleFactory::create(QStringLiteral("Fusion")));
    auto apply=[system](const QString &mode) {
        qApp->setPalette(mode==QStringLiteral("system")?system:palette(mode==QStringLiteral("dark")));
    };
    QSettings prefs(QStringLiteral("TIHULU"),QStringLiteral("Appearance"));
    const QString selected=prefs.value(QStringLiteral("theme"),QStringLiteral("system")).toString();
    auto *menu=settingsMenu->addMenu(QObject::tr("Appearance / Görünüm"));
    auto *group=new QActionGroup(menu);
    for(const QString &key:{QStringLiteral("system"),QStringLiteral("light"),QStringLiteral("dark")}) {
        auto *action=menu->addAction(key==QStringLiteral("dark")?QObject::tr("Dark / Koyu"):
            key==QStringLiteral("light")?QObject::tr("Light / Açık"):QObject::tr("System / Sistem"));
        action->setCheckable(true); action->setChecked(key==selected); group->addAction(action);
        QObject::connect(action,&QAction::triggered,menu,[apply,key](){
            QSettings saved(QStringLiteral("TIHULU"),QStringLiteral("Appearance"));
            saved.setValue(QStringLiteral("theme"),key); saved.sync(); apply(key);
        });
    }
    apply(selected);
    auto *playback=settingsMenu->addMenu(QObject::tr("Video decoding (restart required)"));
    auto *profiles=new QActionGroup(playback);
    QSettings videoPrefs(QStringLiteral("TIHULU"),QStringLiteral("Playback"));
    const QString current=videoPrefs.value(QStringLiteral("profile"),QStringLiteral("software")).toString();
    for(const QString &key:{QStringLiteral("software"),QStringLiteral("auto")}) {
        auto *action=playback->addAction(key==QStringLiteral("software")?
            QObject::tr("Software · compatibility default"):QObject::tr("Hardware · automatic"));
        profiles->addAction(action);action->setCheckable(true);action->setChecked(key==current);
        QObject::connect(action,&QAction::triggered,playback,[key](){
            QSettings saved(QStringLiteral("TIHULU"),QStringLiteral("Playback"));
            saved.setValue(QStringLiteral("profile"),key);saved.sync();
        });
    }

}
}
#endif
