// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef TIHULU_FILE_CAPTIONS_H
#define TIHULU_FILE_CAPTIONS_H
#include "mediawidget.h"
#include <QBoxLayout>
#include <QFont>
#include <QFile>
#include <QLabel>
#include <QResizeEvent>
#include <QRegularExpression>
#include <QTimer>
#include <QVector>
#include <algorithm>
#include <QJsonArray>
#include <QJsonObject>

// Independent of VLC's video-only SPU: timed text also works for audio files.
// The strip belongs to MediaWidget, so fullscreen hides controls, not captions.
class TihuluFileCaptions final : public QLabel {
public:
    struct Cue { qint64 start,end;QString text; };
    explicit TihuluFileCaptions(MediaWidget *player):QLabel(player),player_(player) {
        setObjectName(QStringLiteral("tihuluFileCaptionStrip"));
        setTextFormat(Qt::PlainText);setWordWrap(true);setAlignment(Qt::AlignCenter);
        // Readable in both Light and Dark appearances; no fixed dark rectangle.
        applyStyle();
        setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Minimum);
        player->layout()->addWidget(this);hide();
        connect(&clock_,&QTimer::timeout,this,[this](){updateCaption();});
        clock_.start(100);
        // The strip is a layout widget, so without a bound it grows with its
        // text and takes half of the player. Cap it at a quarter of the
        // player height, exactly like the live TV video overlay, and keep it
        // in step when the player is resized or goes fullscreen.
        clampHeight();
        player_->installEventFilter(this);
    }
    // A live caption session keeps the strip open even between phrases: it
    // closes only when playback is idle or a new file replaces it.
    void setOutputVisible(bool visible) { if(outputVisible_!=visible) {outputVisible_=visible;updateCaption();} }
    void setSticky(bool sticky) { sticky_=sticky;updateCaption(); }
    void clearCues() { cues_.clear();updateCaption(); }
    // Karaoke: the active line plus the next line, like the radio karaoke panel.
    void setKaraoke(bool karaoke) { if(karaoke_!=karaoke) {
        karaoke_=karaoke;
        setSizePolicy(QSizePolicy::Expanding,karaoke_?QSizePolicy::Expanding:QSizePolicy::Minimum);
        clampHeight();applyStyle();
    } updateCaption(); }
    void setLyricOffset(int ms) { lyricOffset_=ms;updateCaption(); }
    bool loadSrt(const QString &path) {
        clearCues();QFile file(path);
        if(!file.open(QIODevice::ReadOnly) || file.size()>8*1024*1024)return false;
        QString content=QString::fromUtf8(file.readAll());content.replace(QStringLiteral("\r\n"),QStringLiteral("\n"));
        const QRegularExpression timing(QStringLiteral("(\\d+):(\\d{2}):(\\d{2})[,\\.](\\d{3})\\s+-->\\s+(\\d+):(\\d{2}):(\\d{2})[,\\.](\\d{3})"));
        for(const auto &block:content.split(QRegularExpression(QStringLiteral("\\n\\s*\\n")),Qt::SkipEmptyParts)) {
            const auto match=timing.match(block);if(!match.hasMatch())continue;
            auto ms=[&](int offset){return ((match.captured(offset).toLongLong()*60+match.captured(offset+1).toLongLong())*60+match.captured(offset+2).toLongLong())*1000+match.captured(offset+3).toLongLong();};
            const qint64 start=ms(1),end=ms(5);
            const QString text=block.mid(block.indexOf(QLatin1Char('\n'),match.capturedEnd())+1).trimmed();
            if(end>start && !text.isEmpty())cues_.append({start,end,text});
        }
        updateCaption();return !cues_.isEmpty();
    }
    void append(const QJsonArray &rows) {
        for(const auto &row:rows) {
            const auto item=row.toObject();
            const qint64 start=item.value("start").toDouble(),end=item.value("end").toDouble();
            if(end>start)cues_.append({start,end,item.value("text").toString()});
        }
        while(cues_.size()>300)cues_.removeFirst();
        updateCaption();
    }
    QString activeText(qint64 now) const {
        QStringList lines;
        for(const auto &cue:cues_)if(cue.start<=now && now<cue.end)lines<<cue.text;
        return lines.join(QLatin1Char('\n'));
    }
private:
    void applyStyle() {
        const QPalette skin=palette();
        setStyleSheet(QStringLiteral("QLabel{background:%1;color:%2;padding:10px;font-size:%3px;}")
            .arg(karaoke_?QStringLiteral("#143f74"):skin.color(QPalette::Base).name(),
                 karaoke_?QStringLiteral("#fff6cc"):skin.color(QPalette::Text).name(),
                 QString::number(qBound(14,QFont().pointSize()*2,48))));
    }
    void updateCaption() {
        if(!outputVisible_) {hide();return;}
        if(!sticky_ && player_->getPlaybackStatus()==MediaWidget::Idle) {setText(QString());hide();return;}
        const qint64 now=player_->getPosition()-(karaoke_?lyricOffset_:0);
        QString text=activeText(now);
        if(karaoke_ && text.isEmpty()) {
            const auto next=std::find_if(cues_.begin(),cues_.end(),
                [&now](const Cue &cue){return cue.start>now;});
            if(next!=cues_.end())text=tr("… %1").arg(next->text);
        } else if(karaoke_) {
            const auto next=std::find_if(cues_.begin(),cues_.end(),
                [&now](const Cue &cue){return cue.start>now;});
            if(next!=cues_.end())text+=QLatin1Char('\n')+tr("… %1").arg(next->text);
        }
        if(text!=this->text())setText(text);
        if(text.isEmpty())text=sticky_?tr("Live captions \u00b7 listening on the current playback position"):QString();
        setText(text);setVisible(!text.isEmpty());
    }
    MediaWidget *player_;QVector<Cue> cues_;QTimer clock_;bool sticky_=false,karaoke_=false,outputVisible_=true;int lyricOffset_=0;
protected:
    // The panel may never cover a large part of the video; the owner reported
    // it taking half of the screen. Captions themselves also go into the video
    // with the same engine as live TV, so the panel is supplementary.
    void clampHeight() {
        if(!player_)return;
        const int cap=karaoke_?QWIDGETSIZE_MAX:qMax(56,player_->height()/4);
        if(maximumHeight()!=cap)setMaximumHeight(cap);
    }
    void resizeEvent(QResizeEvent *event) override {
        clampHeight();
        QLabel::resizeEvent(event);
    }
    bool eventFilter(QObject *watched,QEvent *event) override {
        if(watched==player_ && event->type()==QEvent::Resize)clampHeight();
        return QLabel::eventFilter(watched,event);
    }
};
#endif
