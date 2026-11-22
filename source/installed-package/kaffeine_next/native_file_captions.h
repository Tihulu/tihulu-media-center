// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef TIHULU_FILE_CAPTIONS_H
#define TIHULU_FILE_CAPTIONS_H
#include "mediawidget.h"
#include <QBoxLayout>
#include <QFile>
#include <QLabel>
#include <QRegularExpression>
#include <QTimer>
#include <QVector>
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
        setStyleSheet(QStringLiteral("QLabel{background:#101820;color:#ffffff;padding:10px;font-size:22px;}"));
        setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Minimum);
        player->layout()->addWidget(this);hide();
        connect(&clock_,&QTimer::timeout,this,[this](){updateCaption();});
        clock_.start(100);
    }
    // A live caption session keeps the strip open even between phrases: it
    // closes only when playback is idle or a new file replaces it.
    void setSticky(bool sticky) { sticky_=sticky;updateCaption(); }
    void clearCues() { cues_.clear();updateCaption(); }
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
private:
    void updateCaption() {
        if(!sticky_ && player_->getPlaybackStatus()==MediaWidget::Idle) {setText(QString());hide();return;}
        const qint64 now=player_->getPosition();QStringList lines;
        for(const auto &cue:cues_)if(cue.start<=now && now<cue.end)lines<<cue.text;
        QString text=lines.join(QLatin1Char('\n'));
        if(text!=this->text())setText(text);
        if(text.isEmpty())text=sticky_?tr("Live captions \u00b7 listening on the current playback position"):QString();
        setText(text);setVisible(!text.isEmpty());
    }
    MediaWidget *player_;QVector<Cue> cues_;QTimer clock_;bool sticky_=false;
};
#endif
