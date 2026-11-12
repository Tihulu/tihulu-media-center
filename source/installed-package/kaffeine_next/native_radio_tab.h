/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Embedded TIHULU Radio (DAB+) tab for pinned KDE Kaffeine v2.0.19.
 * Uses native Kaffeine/libVLC for station playback; welle-cli owns DAB
 * demodulation in its own optional, LOOPBACK-ONLY local subprocess.
 * No WebUSB, no cloud SDR service, no receiver use until explicit Start.
 */
#ifndef TIHULU_NATIVE_RADIO_TAB_H
#define TIHULU_NATIVE_RADIO_TAB_H

#include "tabbase.h"
#include "mediawidget.h"

#include <QCheckBox>
#include <QComboBox>
#include <QCompleter>
#include <QDateTime>
#include <QDesktopServices>
#include <QDial>
#include <QDoubleSpinBox>
#include <QDialog>
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QNetworkRequest>
#include <QVector>
#include <QFile>
#include <QFileDialog>
#include <QFormLayout>
#include <QGridLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QHostAddress>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLocale>
#include <QLineEdit>
#include <QListWidget>
#include <QSet>
#include <QHash>
#include <QSignalBlocker>
#include <QHeaderView>
#include <QInputDialog>
#include <QMap>
#include <QMessageBox>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QPainter>
#include <QPen>
#include <QPixmap>
#include <QProgressBar>
#include <QPointer>
#include <QSizePolicy>
#include <QTcpSocket>
#include <QLinearGradient>
#include <QPlainTextEdit>
#include <QProcess>
#include <QPushButton>
#include <QRegularExpression>
#include <QSettings>
#include <QSaveFile>
#include <QScrollArea>
#include <QScrollBar>
#include <QUrlQuery>
#include <QSlider>
#include <QSpinBox>
#include <QSplitter>
#include <QTabWidget>
#include <QTabBar>
#include <QResizeEvent>
#include <QStandardPaths>
#include <QTcpServer>
#include <QTimer>
#include <QTreeWidget>
#include <QUrl>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <functional>
#include <memory>
#include <limits>

// Retuned analog radio: functional wheel/mouse QDial with a retro brass face.
// Broadcaster DLS is a search hint only, never proof of heard song lyrics.
// Support common DE/TR station formats without blindly splitting slogans.
struct TihuluDlsSong {
    QString artist,title,format;
    bool valid() const {return !artist.isEmpty() && !title.isEmpty();}
    QString normalizedKey() const {
        // Ignore DLS case, accents and punctuation variation across repeats.
        // Match the offline Python song-hint key without conflating distinct
        // artist and title tokens.
        const auto canonical=[](const QString &text)->QString {
            QString value=text.normalized(QString::NormalizationForm_KD)
                .toCaseFolded();
            value.remove(QRegularExpression(QLatin1String("[\\p{M}]")));
            value.replace(QRegularExpression(
                QLatin1String("[^\\p{L}\\p{N}]+")),QLatin1String(" "));
            return value.simplified();
        };
        return canonical(artist)+QLatin1Char('|')+canonical(title);
    }
};
inline bool tihuluStationSong(const TihuluDlsSong &song,const QString &station) {
    if(!song.valid()) return true;
    auto normalize=[](QString s)->QString {
        s=s.normalized(QString::NormalizationForm_KD).toCaseFolded();
        s.remove(QRegularExpression(QLatin1String("[\\p{M}]")));
        s.replace(QRegularExpression(QLatin1String("[^\\p{L}\\p{N}]+")),
                  QLatin1String(" "));
        return s.simplified();
    };
    const QString st=normalize(station);
    const QString a=normalize(song.artist),t=normalize(song.title);
    if(!st.isEmpty() && (a==st || t==st ||
       a.startsWith(st+QLatin1Char(' ')) ||
       t.startsWith(st+QLatin1Char(' ')) ||
       (a.size()>=4 && st.startsWith(a+QLatin1Char(' '))) ||
       (t.size()>=4 && st.startsWith(t+QLatin1Char(' ')))))
        return true;
    return a==t || a.startsWith(QLatin1String("www ")) ||
        t.startsWith(QLatin1String("www "));
}
inline TihuluDlsSong tihuluDlsSong(const QString &dls,
                                   const QString &station=QString()) {
    TihuluDlsSong result;
    if(dls.size()<5 || dls.size()>330) return result;
    QString text=dls.simplified();
    if(text.contains(QLatin1String("::"))) {
        const QStringList parts=text.split(QLatin1String("::"));
        if(parts.size()>=3) {
            const QString prefix=parts.first().trimmed().toCaseFolded();
            if(prefix==QLatin1String("jetzt on air") ||
               prefix==QLatin1String("now on air") ||
               prefix==QLatin1String("now playing") ||
               prefix==QLatin1String("şimdi çalıyor") ||
               prefix==QLatin1String("simdi caliyor")) {
                result.title=parts.at(1).trimmed();
                result.artist=parts.at(2).trimmed();
                result.format=QLatin1String("DLS track-first");
            }
        }
    } else {
        text.remove(QRegularExpression(QLatin1String(
            "^(?:jetzt on air|now on air|now playing|jetzt läuft|"
            "aktuell|şimdi çalıyor|simdi caliyor)\\s*:\\s*"),
            QRegularExpression::CaseInsensitiveOption));
        const QRegularExpression named(QLatin1String(
            "^(?:artist|interpret|künstler)\\s*:\\s*(.+?)\\s*[|;]\\s*"
            "(?:title|titel|song|track)\\s*:\\s*(.+)$"),
            QRegularExpression::CaseInsensitiveOption);
        const auto match=named.match(text);
        if(match.hasMatch()) {
            result.artist=match.captured(1).trimmed();
            result.title=match.captured(2).trimmed();
            result.format=QLatin1String("DLS named fields");
        } else {
            const auto sep=QRegularExpression(QLatin1String(
                "\\s+[-–—]\\s+")).match(text);
            if(sep.hasMatch()) {
                result.artist=text.left(sep.capturedStart()).trimmed();
                result.title=text.mid(sep.capturedEnd()).trimmed();
                result.format=QLatin1String("DLS artist-first");
            }
        }
    }
    if(result.artist.size()>130 || result.title.size()>130 ||
       tihuluStationSong(result,station)) return TihuluDlsSong();
    return result;
}
// welle-cli generally emits dls.label only. If a richer DAB/RDS receiver
// exposes typed artist/title or DL+/RT+ tags, use those fields instead.
// Station/PS labels, MOT captions and promotional text never become titles.
inline TihuluDlsSong tihuluDlsSongFromService(const QJsonObject &service) {
    auto str=[](const QJsonValue &v)->QString {
        if(v.isString()) return v.toString().trimmed();
        if(v.isObject()) return v.toObject().value(
            QLatin1String("label")).toString().trimmed();
        return QString();
    };
    auto field=[&](const QJsonObject &o,const QStringList &names)->QString {
        for(const QString &key:names) {
            const QString value=str(o.value(key));
            if(!value.isEmpty()) return value;
        }
        return QString();
    };
    const QString station=str(service.value(QLatin1String("label")));
    const QJsonObject dls=service.value(QLatin1String("dls")).toObject();
    auto typed=[&](const QJsonObject &o,const QString &source)->TihuluDlsSong {
        TihuluDlsSong song;
        song.artist=field(o,{QLatin1String("artist"),
            QLatin1String("item_artist"),QLatin1String("itemArtist"),
            QLatin1String("item.artist"),QLatin1String("performer"),
            QLatin1String("song_artist"),QLatin1String("track_artist")});
        song.title=field(o,{QLatin1String("title"),
            QLatin1String("item_title"),QLatin1String("itemTitle"),
            QLatin1String("item.title"),QLatin1String("trackTitle"),
            QLatin1String("song_title"),QLatin1String("track_title")});
        const QJsonObject item=o.value(QLatin1String("item")).toObject();
        if(song.artist.isEmpty()) song.artist=field(item,
            {QLatin1String("artist"),QLatin1String("performer")});
        if(song.title.isEmpty()) song.title=field(item,
            {QLatin1String("title"),QLatin1String("track")});
        song.format=source;
        if(song.artist.size()>130 || song.title.size()>130 ||
           tihuluStationSong(song,station)) return TihuluDlsSong();
        return song;
    };
    const QList<QPair<QString,QJsonObject>> objects={
        {QLatin1String("Now playing"),
            service.value(QLatin1String("now_playing")).toObject()},
        {QLatin1String("Now playing"),
            service.value(QLatin1String("nowPlaying")).toObject()},
        {QLatin1String("Track tags"),
            service.value(QLatin1String("song")).toObject()},
        {QLatin1String("Track tags"),
            service.value(QLatin1String("track")).toObject()},
        {QLatin1String("DLS+"),
            service.value(QLatin1String("dlplus")).toObject()},
        {QLatin1String("DLS+"),
            service.value(QLatin1String("dl_plus")).toObject()},
        {QLatin1String("DLS+"),
            dls.value(QLatin1String("dlplus")).toObject()},
        {QLatin1String("DLS+"),
            dls.value(QLatin1String("dl_plus")).toObject()},
        {QLatin1String("DLS"),dls},
        {QLatin1String("RDS RadioText+"),
            service.value(QLatin1String("rtplus")).toObject()},
        {QLatin1String("Radio metadata"),
            service.value(QLatin1String("metadata")).toObject()},
        {QLatin1String("Radio info"),
            service.value(QLatin1String("radio_info")).toObject()},
        {QLatin1String("Track fields"),service}
    };
    for(const auto &source:objects) {
        const TihuluDlsSong song=typed(source.second,source.first);
        if(song.valid()) return song;
    }
    // Some receivers represent DL+/RT+ as ITEM.ARTIST / ITEM.TITLE tags.
    const QList<QJsonObject> tagged={dls,service,
        dls.value(QLatin1String("dlplus")).toObject(),
        dls.value(QLatin1String("dl_plus")).toObject(),
        service.value(QLatin1String("dlplus")).toObject(),
        service.value(QLatin1String("rtplus")).toObject()};
    for(const QJsonObject &root:tagged) {
        QString artist,title;
        for(const QJsonValue &v:root.value(QLatin1String("tags")).toArray()) {
            const QJsonObject tag=v.toObject();
            const QString name=field(tag,{QLatin1String("type"),
                QLatin1String("tag"),QLatin1String("name")}).toCaseFolded();
            const QString value=field(tag,{QLatin1String("text"),
                QLatin1String("value"),QLatin1String("label")});
            if(name.endsWith(QLatin1String("artist"))) artist=value;
            else if(name.endsWith(QLatin1String("title"))) title=value;
        }
        TihuluDlsSong song{artist,title,QLatin1String("DL+/RT+ tags")};
        if(song.artist.size()<=130 && song.title.size()<=130 &&
           !tihuluStationSong(song,station)) return song;
    }
    const QStringList texts={
        str(dls.value(QLatin1String("label"))),
        str(dls.value(QLatin1String("text"))),
        str(service.value(QLatin1String("radiotext"))),
        str(service.value(QLatin1String("radio_text"))),
        str(service.value(QLatin1String("radioText"))),
        str(service.value(QLatin1String("dls"))),
        str(service.value(QLatin1String("now_playing")))};
    for(const QString &text:texts) {
        const TihuluDlsSong song=tihuluDlsSong(text,station);
        if(song.valid()) return song;
    }
    return TihuluDlsSong();
}

class TihuluBrassDial final : public QDial {
public:
    explicit TihuluBrassDial(QWidget *parent=nullptr):QDial(parent) {
        setMinimumSize(88,88);
        setMaximumSize(100,100);
        setNotchesVisible(false);
        setFocusPolicy(Qt::StrongFocus);
    }
protected:
    void paintEvent(QPaintEvent *) override {
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing);
        const QRectF bounds=QRectF(rect()).adjusted(5,5,-5,-5);
        const QPointF center=bounds.center();
        const double radius=qMin(bounds.width(),bounds.height())/2;
        QLinearGradient gold(bounds.topLeft(),bounds.bottomRight());
        gold.setColorAt(0,QColor("#f8db94"));
        gold.setColorAt(.45,QColor("#b48c44"));
        gold.setColorAt(1,QColor("#5e461f"));
        painter.setPen(QPen(QColor("#6d502b"),3));
        painter.setBrush(gold);
        painter.drawEllipse(bounds);
        painter.setPen(QPen(QColor("#fff2b9"),1));
        painter.drawEllipse(bounds.adjusted(8,8,-8,-8));
        const double turn=(maximum()>minimum())
          ?double(value()-minimum())/(maximum()-minimum()):0;
        const double angle=(225.-270.*turn)*3.141592653589793/180.;
        painter.setPen(QPen(QColor("#542d10"),4,Qt::SolidLine,Qt::RoundCap));
        painter.drawLine(center,QPointF(center.x()+radius*.68*std::cos(angle),
                                      center.y()-radius*.68*std::sin(angle)));
        painter.setPen(Qt::NoPen);
        painter.setBrush(QColor("#34291d"));
        painter.drawEllipse(center,4,4);
    }
};

class TihuluAnalogScale final : public QWidget {
public:
    explicit TihuluAnalogScale(QWidget *parent=nullptr):QWidget(parent) {
        setMinimumHeight(95);
        setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Fixed);
    }
    void updateFrequency(double minValue,double maxValue,double current,
                         const QString &units) {
        minimum_=minValue;maximum_=maxValue;value_=current;units_=units;update();
    }
protected:
    void paintEvent(QPaintEvent *) override {
        QPainter p(this);
        p.setRenderHint(QPainter::Antialiasing);
        const QRectF frame=QRectF(rect()).adjusted(2,2,-2,-2);
        p.setPen(QPen(QColor("#a97a36"),2));
        p.setBrush(QColor("#171814"));
        p.drawRoundedRect(frame,9,9);
        const double left=20,right=qMax(25,width()-21);
        p.setPen(QColor("#ebcf94"));
        for(int i=0;i<=20;++i) {
            const double x=left+(right-left)*i/20.;
            const int yEnd=(i%5==0?52:45);
            p.drawLine(QPointF(x,32),QPointF(x,yEnd));
            if(i%5==0)
                p.drawText(QRectF(x-33,54,66,20),Qt::AlignCenter,
                           QString::number(minimum_+(maximum_-minimum_)*i/20.,'f',
                                           maximum_>200?0:1));
        }
        p.setPen(QColor("#f6dca9"));
        p.drawText(QRectF(left,8,right-left,22),Qt::AlignCenter,units_);
        const double f=qBound(0.,(value_-minimum_)/qMax(1e-6,maximum_-minimum_),1.);
        const double marker=left+(right-left)*f;
        p.setPen(QPen(QColor("#ff674c"),3));
        p.drawLine(QPointF(marker,22),QPointF(marker,77));
    }
private:
    double minimum_=87.5,maximum_=108.,value_=99.2;
    QString units_=QStringLiteral("FM · MHz");
};

class TihuluRadioTab final : public TabBase
{
public:
	explicit TihuluRadioTab(MediaWidget *player, QWidget *parent = nullptr)
		: TabBase(), player_(player), backend_(this), captionProcess_(this),
		  recorder_(this), lyricsProcess_(this), network_(this), tick_(this)
	{
		setParent(parent);
		// Keep every radio control reachable on laptop-sized windows.
		auto *outer = new QVBoxLayout(this);
		outer->setContentsMargins(0, 0, 0, 0);
		auto *scroll = new QScrollArea(this);
		scroll->setWidgetResizable(true);
		scroll->setFrameShape(QFrame::NoFrame);
		outer->addWidget(scroll);
		auto *page = new QWidget(scroll);
		auto *root = new QVBoxLayout(page);
		root->setContentsMargins(9, 9, 9, 9);
		root->setSpacing(8);
		scroll->setWidget(page);
        // Single compact dashboard: independent radio modes no longer
        // stack all advanced settings under one enormous scrolling page.
        auto *selected = new QLabel(tr("Selected source: none · choose DAB+, Internet or FM/MW/LW"),page);
        selected->setWordWrap(true);
        selected->setStyleSheet(QLatin1String(
            "background:#142e3b;color:#c0edf6;border:1px solid #385a67;"
            "border-radius:6px;padding:7px;font-weight:600;"));
        selectedSource_=selected;
        root->addWidget(selectedSource_);
        radioCaptionBanner_=new QLabel(tr("Live radio subtitles OFF · DLS is not speech"),page);
        radioCaptionBanner_->setTextFormat(Qt::PlainText);
        radioCaptionBanner_->setWordWrap(true);
        radioCaptionBanner_->setMaximumHeight(120);
        radioCaptionBanner_->setStyleSheet(QLatin1String(
            "background:#14242e;color:#f5e6bb;border:1px solid #405365;"
            "border-radius:6px;padding:7px;"));
        root->addWidget(radioCaptionBanner_);
        // Translation diagnostics are never represented as spoken lyrics.
        // This slim status line remains visible even when AI settings
        // are collapsed and the radio station art occupies most of the tab.
        radioTranslationBanner_=new QLabel(page);
        radioTranslationBanner_->setWordWrap(true);
        radioTranslationBanner_->setTextFormat(Qt::PlainText);
        radioTranslationBanner_->setStyleSheet(QLatin1String(
            "QLabel{color:#adcbe0;background:transparent;font-size:12px;"
            "padding:4px 8px;}"));
        radioTranslationBanner_->setVisible(false);
        root->addWidget(radioTranslationBanner_);
        modes_=new QTabWidget(page);
        modes_->setDocumentMode(true);
        modes_->setUsesScrollButtons(true);
        modes_->tabBar()->setExpanding(false);
        modes_->setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Preferred);
        root->addWidget(modes_,1);
        auto *dabPage=new QWidget(modes_);
        auto *dabLayout=new QVBoxLayout(dabPage);
        dabLayout->setContentsMargins(8,8,8,8);
        dabLayout->setSpacing(7);
        modes_->addTab(dabPage,tr("DAB+ · stations"));
        auto *header = new QHBoxLayout();
		auto *name = new QLabel(tr("Radio · DAB+ (powered by welle.io)"), this);
		name->setStyleSheet(QLatin1String("font-weight:700;font-size:16px"));
		header->addWidget(name, 1);
		channel_ = new QComboBox(this);
		const QStringList blocks = {
			"5A","5B","5C","5D","6A","6B","6C","6D",
			"7A","7B","7C","7D","8A","8B","8C","8D",
			"9A","9B","9C","9D","10A","10B","10C","10D",
			"11A","11B","11C","11D","12A","12B","12C","12D",
			"13A","13B","13C","13D","13E","13F"};
		channel_->addItems(blocks);
		channel_->setCurrentText(QLatin1String("11D"));
		channel_->setToolTip(tr("European Band III blocks. No tuning until Start."));
		header->addWidget(channel_);
		driver_ = new QComboBox(this);
		driver_->addItem(tr("Auto SDR"), QLatin1String("auto"));
		driver_->addItem(tr("RTL-SDR"), QLatin1String("rtl_sdr"));
		driver_->addItem(tr("SoapySDR"), QLatin1String("soapysdr"));
		driver_->addItem(tr("Airspy"), QLatin1String("airspy"));
		driver_->setToolTip(tr("Choose the DAB-capable receiver driver. "
			"An ordinary DVB-T2 frontend alone cannot be assumed to work."));
		header->addWidget(driver_);
		start_ = new QPushButton(tr("Start receiver"), this);
		start_->setToolTip(tr("Open an actual DAB-capable RTL-SDR/Soapy device on demand."));
		stop_ = new QPushButton(tr("Stop radio"), this);
        stop_->setToolTip(tr("Stop DAB audio, AI captions and recordings. "
            "By default also terminate welle-cli and release the RTL-SDR. "
            "Use the option below to keep the receiver ready."));
		record_ = new QPushButton(tr("Record station"), this);
		record_->setToolTip(tr("Save selected radio service to a local MP3; "
			"stop recording to release the file."));
		scan_ = new QPushButton(tr("Scan all blocks"), this);
		scan_->setToolTip(tr("Retunes across Band III blocks; can take minutes."));
		dabLayout->addLayout(header);
		// Two-row responsive operation grid; large monitors no longer stretch
		// every action across 400 px, and laptop windows do not clip controls.
		auto *receiverActions=new QGridLayout();
		receiverActions->setHorizontalSpacing(9);
		for(QPushButton *button:{start_,scan_,record_,stop_})
			button->setMaximumWidth(200);
		receiverActions->addWidget(start_,0,0);
		receiverActions->addWidget(scan_,0,1);
		receiverActions->addWidget(stop_,0,2);
        releaseOnStop_=new QCheckBox(
            tr("Release SDR when radio stops (default)"),page);
        QSettings radioResourceSettings(QLatin1String("TIHULU"),
                                        QLatin1String("KaffeineRadio"));
        releaseOnStop_->setChecked(radioResourceSettings.value(
            QLatin1String("releaseSdrOnStop"),true).toBool());
        releaseOnStop_->setToolTip(tr("ON (recommended): stopping radio, "
            "including the main Kaffeine Stop button, ends TIHULU's "
            "welle-cli receiver and releases the RTL-SDR to other apps. "
            "OFF keeps this application's DAB receiver occupying the SDR "
            "after playback stops; full application exit still releases."));
        receiverActions->addWidget(releaseOnStop_,1,2);
        forceRelease_=new QPushButton(tr("Release SDR now"),page);
        forceRelease_->setToolTip(tr("Always stop this app-owned radio receiver "
            "and release the RTL-SDR, regardless of the keep-ready preference. "
            "Does not stop other applications' SDR processes."));
        receiverActions->addWidget(forceRelease_,2,2);
        subtitledRecord_=new QCheckBox(tr("Make subtitled recording"),this);
		subtitledRecord_->setToolTip(tr("On Stop, create offline time-coded SRT from the "
			"saved audio and mux a selectable-subtitle MKV. Never fake live synchronization."));
		receiverActions->addWidget(record_,1,0);
		receiverActions->addWidget(subtitledRecord_,1,1);
		receiverActions->setColumnStretch(2,1);
		dabLayout->addLayout(receiverActions);
		// Keep actual scan progress + SNR in view even when the RF graph and
		// AI settings are far down the scroll area.
		auto *scanReadouts=new QHBoxLayout();
		scanProgress_=new QProgressBar(page);
		scanProgress_->setRange(0,channel_->count());
		scanProgress_->setValue(0);
		scanProgress_->setFormat(tr("DAB scan · not started"));
		scanProgress_->setMinimumWidth(160);
		scanSNR_=new QProgressBar(page);
		scanSNR_->setRange(0,100);
		scanSNR_->setValue(0);
		scanSNR_->setFormat(tr("RF SNR: no live measurement"));
		scanSNR_->setToolTip(tr("Actual reported DAB signal-to-noise ratio converted "
			"to a relative progress indicator, NOT a measured RF power level."));
		scanReadouts->addWidget(scanProgress_,1);
		scanReadouts->addWidget(scanSNR_,1);
		dabLayout->addLayout(scanReadouts);

		state_ = new QLabel(tr("Receiver disconnected. A separate DAB-capable SDR is required; "
			"the DVB-T2 television adapter is not automatically a DAB receiver."), this);
		state_->setWordWrap(true);
		state_->setTextFormat(Qt::PlainText);
		dabLayout->addWidget(state_);
        receiverOwnership_=new QLabel(tr(
            "SDR: RELEASED by TIHULU · select a DAB station or Start "
            "receiver to acquire it"),page);
        receiverOwnership_->setWordWrap(true);
        dabLayout->addWidget(receiverOwnership_);
		playStatus_=new QLabel(tr("Station: no live stream verified"),page);
		playStatus_->setWordWrap(true);
		dabLayout->addWidget(playStatus_);
		stationOpenProgress_=new QProgressBar(page);
		stationOpenProgress_->setRange(0,4);
		stationOpenProgress_->setValue(0);
		stationOpenProgress_->setFormat(tr("Stream status · choose a station"));
		dabLayout->addWidget(stationOpenProgress_);
        radioAudioHealth_=new QLabel(tr(
            "Audio health · awaiting real RF error-counter deltas; "
            "libVLC output clock not measured"),page);
        radioAudioHealth_->setWordWrap(true);
        dabLayout->addWidget(radioAudioHealth_);
        // Sound leaves through shared libVLC; the independent Whisper/FFmpeg
        // capture can transcribe perfectly while the actual speaker is muted.
        auto *audioOutputRow=new QHBoxLayout();
        radioAudioOutputStatus_=new QLabel(
            tr("Output unverified · check Volume, mute and system sink"),page);
        radioAudioOutputStatus_->setWordWrap(true);
        audioOutputRow->addWidget(radioAudioOutputStatus_,2);
        audioOutputRow->addWidget(new QLabel(tr("Volume"),page));
        radioOutputVolume_=new QSlider(Qt::Horizontal,page);
        radioOutputVolume_->setRange(0,100);
        radioOutputVolume_->setValue(player_->getVolume());
        radioOutputVolume_->setMinimumWidth(80);
        radioOutputVolume_->setMaximumWidth(160);
        radioOutputVolume_->setToolTip(tr("Shared Kaffeine/libVLC output volume, not microphone or ASR input."));
        audioOutputRow->addWidget(radioOutputVolume_,1);
        radioMuteButton_=new QPushButton(tr("Toggle mute"),page);
        radioMuteButton_->setToolTip(tr("Toggle the native Kaffeine speaker mute action."));
        radioReconnectAudio_=new QPushButton(tr("Retry DAB sound"),page);
        radioReconnectAudio_->setToolTip(tr("Reopen local DAB MP3 in libVLC only; do not retune SDR or stop Whisper."));
        radioAudioDiagnostics_=new QPushButton(tr("Audio outputs..."),page);
        radioAudioDiagnostics_->setToolTip(tr("Read-only PipeWire/PulseAudio output routing diagnostics."));
        audioOutputRow->addWidget(radioMuteButton_);
        audioOutputRow->addWidget(radioReconnectAudio_);
        audioOutputRow->addWidget(radioAudioDiagnostics_);
        dabLayout->addLayout(audioOutputRow);
        // DAB playback is RF/audio first. Heavy AI and EXTRA network cache
        // are opt-in; they must never be required just to tune or scan.
        radioQuickRow_=new QHBoxLayout();
        quickAi_=new QCheckBox(tr("AI captions · OFF"),page);
        quickAi_->setChecked(false);
        quickAi_->setToolTip(tr("Whisper and translation are OFF at startup. "
            "When enabled, captions follow station changes; scanning disables them."));
        quickBuffer_=new QCheckBox(tr("Extra buffer · OFF"),page);
        quickBuffer_->setChecked(false);
        quickBuffer_->setToolTip(tr("Enable a user-selected libVLC network cache. "
            "OFF means no EXTRA cache request; demodulator and device "
            "latency cannot be disabled. Changing this while playing "
            "reopens the audio stream once."));
        radioQuickRow_->addWidget(quickAi_);
        quickTranslate_=new QCheckBox(tr("Radio translate · OFF"),page);
        QSettings radioTranslatePrefs(QLatin1String("TIHULU"),
                                      QLatin1String("KaffeineRadio"));
        quickTranslate_->setChecked(radioTranslatePrefs.value(
            QLatin1String("radioTranslationOptIn"),false).toBool());
        quickTranslate_->setText(quickTranslate_->isChecked()?
            tr("Radio translate · ON"):tr("Radio translate · OFF"));
        quickTranslate_->setToolTip(tr(
            "Explicitly use installed local Argos, NLLB or MADLAD for radio. "
            "Never downloads models or opts into DeepL. Select OUT languages "
            "using Edit; actual model availability is reported after processing."));
        radioQuickRow_->addWidget(quickTranslate_);
        quickLanguageButton_=new QPushButton(
            tr("IN: AUTO · OUT: EN, DE, TR · Edit"),page);
        quickLanguageButton_->setToolTip(tr(
            "Choose original speech and translation languages; "
            "updates reach the current radio ASR worker live."));
        radioQuickRow_->addWidget(quickLanguageButton_);
        radioQuickRow_->addStretch(1);
        dabLayout->addLayout(radioQuickRow_);
        radioPlaybackRow_=new QHBoxLayout();
        radioPlaybackRow_->addWidget(quickBuffer_);
        radioPlaybackRow_->addStretch(1);
        dabLayout->addLayout(radioPlaybackRow_);
        // Moving a buffer slider is only a PENDING preference. No retune.
        auto *mainBufferRow=new QHBoxLayout();
        dabLayout->addLayout(mainBufferRow);
        auto *mainOffsetRow=new QHBoxLayout();
        dabLayout->addLayout(mainOffsetRow);
        auto *mainMatchRow=new QHBoxLayout();
        dabLayout->addLayout(mainMatchRow);
        auto *mainModelRow=new QHBoxLayout();
        dabLayout->addLayout(mainModelRow);
        auto *mainLyricOffsetRow=new QHBoxLayout();
        dabLayout->addLayout(mainLyricOffsetRow);
        // Common controls must be reachable while listening, without
        // opening the advanced Whisper/AI menu. Radio has no video lips:
        // this is audio-to-subtitle timing, not a measured DAC clock.
        auto *captionComfortRow=new QHBoxLayout();
        captionComfortRow->addWidget(new QLabel(tr(
            "AI captions ↔ audio (estimated):"),page));
        captionEarlier_=new QPushButton(tr("−250 ms"),page);
        captionLater_=new QPushButton(tr("+250 ms"),page);
        captionEarlier_->setToolTip(tr(
            "Text appears 250 ms earlier. Does not retune radio audio."));
        captionLater_->setToolTip(tr(
            "Text appears 250 ms later. Does not retune radio audio."));
        captionOffsetReadout_=new QLabel(tr("Offset +0 ms"),page);
        captionOffsetReadout_->setToolTip(tr(
            "Your manual subtitle offset (negative = earlier). "
            "Actual libVLC/ALSA audio presentation time is unmeasured."));
        captionComfortRow->addWidget(captionEarlier_);
        captionComfortRow->addWidget(captionLater_);
        captionComfortRow->addWidget(captionOffsetReadout_);
        captionRefresh_=new QPushButton(tr("AI Caption Refresh"),page);
        captionRefresh_->setToolTip(tr(
            "Restart this radio's ASR and clear stale results without "
            "retuning the receiver or restarting radio audio."));
        aiSyncRefresh_=new QPushButton(tr("AI Lip-sync Refresh"),page);
        aiSyncRefresh_->setToolTip(tr(
            "Re-time ONLY pending normal Whisper speech/translated subtitles "
            "with the current requested audio cache and caption offset. "
            "Does not change karaoke words, lyric position or model. "
            "No ASR restart, old speech replay, audio rebuffer or SDR retune."));
        radioSyncRefresh_=new QPushButton(tr("Karaoke Lip-sync Refresh"),page);
        radioSyncRefresh_->setToolTip(tr(
            "Recheck the current song using installed Qwen3 ForcedAligner "
            "when language and evidence permit, otherwise Whisper word timing. "
            "Does not modify normal speech subtitle timing. "
            "No audio/SDR/Whisper restart or buffer refill."));
        captionComfortRow->addWidget(captionRefresh_);
        captionComfortRow->addWidget(aiSyncRefresh_);
        captionComfortRow->addWidget(radioSyncRefresh_);
        // The Karaoke history control belongs by Karaoke offset below,
        // not in the already crowded AI/Reading quick-control row.
        karaokeSyncHistorySeconds_=new QSpinBox(page);
        karaokeSyncHistorySeconds_->setRange(3,30);
        karaokeSyncHistorySeconds_->setSuffix(tr(" s"));
        QSettings karaokeHistoryPrefs(QLatin1String("TIHULU"),
                                      QLatin1String("KaffeineRadio"));
        karaokeSyncHistorySeconds_->setValue(qBound(3,
            karaokeHistoryPrefs.value(QLatin1String("karaokeSyncHistorySeconds"),
                                     10).toInt(),30));
        karaokeSyncHistorySeconds_->setToolTip(tr(
            "Default 10s of recent real Whisper lyric matches/word timestamps. "
            "The Karaoke matcher also retains at most 3–30 seconds of "
            "decoded PCM in RAM solely for its own alignment refresh. "
            "This is NOT a playback buffer, extra receiver or added audio delay."));
        connect(karaokeSyncHistorySeconds_,
            QOverload<int>::of(&QSpinBox::valueChanged),this,
            [this](int seconds){
                QSettings prefs(QLatin1String("TIHULU"),
                                QLatin1String("KaffeineRadio"));
                prefs.setValue(QLatin1String("karaokeSyncHistorySeconds"),seconds);
                pruneRecentKaraokeEvidence(QDateTime::currentMSecsSinceEpoch());
                writeRadioLanguageControls(); // next radio audio hop, no retune
            });
        captionComfortRow->addSpacing(12);
        captionComfortRow->addWidget(new QLabel(tr("Reading:"),page));
        radioReadingPreset_=new QComboBox(page);
        radioReadingPreset_->addItem(tr("Live · fast"),0);
        radioReadingPreset_->addItem(tr("Comfort · recommended"),1);
        radioReadingPreset_->addItem(tr("Relaxed · longer hold"),2);
        radioReadingPreset_->addItem(
            tr("TV-style Adaptive · readable + live"),3);
        radioReadingPreset_->setToolTip(tr(
            "TV-style Adaptive (recommended) uses whole-sentence captions "
            "and a character-per-second reading budget, then shortens holds "
            "when live speech is queued. Live is fastest; Relaxed is slowest. "
            "Radio audio and the SDR are never delayed."));
        QSettings captionPreferences(QLatin1String("TIHULU"),
                                     QLatin1String("KaffeineRadio"));
        const int readingPreference=qBound(0,captionPreferences.value(
            QLatin1String("radioReadingPreset"),3).toInt(),3);
        radioReadingPreset_->setCurrentIndex(readingPreference);
        captionComfortRow->addWidget(radioReadingPreset_);
        captionComfortRow->addWidget(new QLabel(tr("Text:"),page));
        radioCaptionFontSize_=new QSpinBox(page);
        radioCaptionFontSize_->setRange(14,28);
        radioCaptionFontSize_->setSuffix(tr(" pt"));
        radioCaptionFontSize_->setValue(qBound(14,captionPreferences.value(
            QLatin1String("radioCaptionFontPt"),18).toInt(),28));
        captionComfortRow->addWidget(radioCaptionFontSize_);
        captionComfortRow->addStretch(1);
        dabLayout->addLayout(captionComfortRow);
        connect(radioReadingPreset_,QOverload<int>::of(
            &QComboBox::currentIndexChanged),this,[this](int){
            QSettings prefs(QLatin1String("TIHULU"),
                            QLatin1String("KaffeineRadio"));
            prefs.setValue(QLatin1String("radioReadingPreset"),
                           radioReadingPreset_->currentData().toInt());
            // Live/fast halves caption polling jitter. Other modes keep
            // the quieter 300-ms update cadence. Neither alters Karaoke
            // word timestamps nor SDR/libVLC buffering.
            captionTick_.setInterval(
                radioReadingPreset_->currentData().toInt()==0?150:300);
            // Apply selection immediately to the currently displayed cue.
            if(radioCanvasCaption_ && radioCanvasCaption_->isVisible() &&
               captionDisplayedStartedMs_>0) {
                const qint64 now=QDateTime::currentMSecsSinceEpoch();
                captionReadingHoldUntilMs_=qMax(now,
                    captionDisplayedStartedMs_+
                    radioCaptionReadingHoldMs(radioCanvasCaption_->text()));
                displayDueRadioCues(now);
            }
        });
        connect(radioCaptionFontSize_,QOverload<int>::of(
            &QSpinBox::valueChanged),this,[this](int size){
            QSettings prefs(QLatin1String("TIHULU"),
                            QLatin1String("KaffeineRadio"));
            prefs.setValue(QLatin1String("radioCaptionFontPt"),size);
            updateRadioCaptionTypography();
        });
        quickBufferProgress_=new QProgressBar(page);
        quickBufferProgress_->setRange(0,100);
        quickBufferProgress_->setValue(0);
        quickBufferProgress_->setFormat(tr(
            "Extra buffer OFF · enable it to view startup progress"));
        quickBufferProgress_->setToolTip(tr(
            "This is a bounded PLAYER STARTUP timer, NOT actual libVLC "
            "buffer occupancy. It stops with a clear error if playback "
            "never reaches PLAYING. No automatic SDR/audio restart."));
        quickBufferProgress_->setVisible(false);
        dabLayout->addWidget(quickBufferProgress_);

		// Public internet radio requires no SDR, welle-cli or DVB frontend.
		// Search happens only when clicked, and uses HTTPS Radio Browser API.
		auto *webGroup = new QGroupBox(tr("Internet radio · independent of tuner"), page);
		auto *webLayout = new QVBoxLayout(webGroup);
		auto *webSearchRow = new QGridLayout();
		webSearch_ = new QLineEdit(webGroup);
		webSearch_->setPlaceholderText(tr("Search station name · e.g. WDR, BBC, TRT"));
		webCountry_ = new QComboBox(webGroup);
		webCountry_->setMinimumWidth(175);
		webCountry_->setMaximumWidth(300);
		webCountry_->setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Fixed);
		webCountry_->addItem(tr("All countries · worldwide"),QString());
		QMap<QString,QString> world;
		const auto locales=QLocale::matchingLocales(
			QLocale::AnyLanguage,QLocale::AnyScript,QLocale::AnyCountry);
		for(const QLocale &loc:locales) {
			const QString code=loc.name().section(QLatin1Char('_'),1).toUpper();
			if(!QRegularExpression(QLatin1String("^[A-Z]{2}$")).match(code).hasMatch())
				continue;
			QString countryName=QLocale::countryToString(loc.country());
			if(countryName.isEmpty()) continue;
			world.insert(countryName+QLatin1String(" (")+code+QLatin1Char(')'),code);
		}
		// Debian's ISO-3166 source supplements locales with territories
		// for which Qt does not ship a user-interface locale.
		QFile countries(QLatin1String("/usr/share/iso-codes/json/iso_3166-1.json"));
		if(countries.open(QIODevice::ReadOnly) && countries.size()<512*1024) {
			const QJsonDocument catalog=QJsonDocument::fromJson(countries.readAll());
			const QJsonArray entries=catalog.object().value(
				QLatin1String("3166-1")).toArray();
			for(const QJsonValue &v:entries) {
				const QJsonObject e=v.toObject();
				const QString code=e.value(QLatin1String("alpha_2")).toString();
				const QString title=e.value(QLatin1String("name")).toString();
				if(QRegularExpression(QLatin1String("^[A-Z]{2}$"))
				   .match(code).hasMatch() && !title.isEmpty())
					world.insert(title+QLatin1String(" (")+code+QLatin1Char(')'),code);
			}
		}
		for(auto it=world.constBegin();it!=world.constEnd();++it)
			webCountry_->addItem(it.key(),it.value());
		webCountry_->setEditable(true);
		webCountry_->setInsertPolicy(QComboBox::NoInsert);
		webCountry_->setMaxVisibleItems(20);
		webCountry_->setToolTip(tr("Choose a country or type its name/ISO code; "
			"the online directory is searched after selecting a country."));
		webCountry_->completer()->setFilterMode(Qt::MatchContains);
		webCountry_->completer()->setCaseSensitivity(Qt::CaseInsensitive);
		webCountry_->setCurrentIndex(0);
		webSearchButton_ = new QPushButton(tr("Find stations online"), webGroup);
		webSearchRow->addWidget(webSearch_,0,0,1,2);
        webSearchRow->addWidget(webCountry_,1,0);
        webSearchRow->addWidget(webSearchButton_,1,1);
        webSearchRow->setColumnStretch(0,1);
		webLayout->addLayout(webSearchRow);
		webStations_ = new QTreeWidget(webGroup);
		webStations_->setHeaderLabels({tr("★"),tr("Station"),tr("Country"),tr("Codec")});
		webStations_->setRootIsDecorated(false);
		webStations_->setAlternatingRowColors(true);
		webStations_->setMinimumHeight(105);
		webStations_->setMaximumHeight(170);
		webStations_->header()->setSectionResizeMode(0, QHeaderView::ResizeToContents);
		webStations_->header()->setSectionResizeMode(1, QHeaderView::Stretch);
		webLayout->addWidget(webStations_);
		auto *webPlayRow = new QGridLayout();
		webSource_ = new QLineEdit(webGroup);
		webSource_->setPlaceholderText(tr("Or paste an HTTP(S) radio stream URL"));
		webPlay_ = new QPushButton(tr("Play stream"), webGroup);
		webAlternate_=new QPushButton(tr("Try alternate station URL"),webGroup);
		webAlternate_->setToolTip(tr("If the resolved stream is broken, explicitly try the "
			"station's original Radio Browser URL, when it differs."));
		webProbeButton_=new QPushButton(tr("Test stream / codec"),webGroup);
		webProbeButton_->setToolTip(tr("Ask local FFprobe to inspect the station URL "
			"without opening DVB or claiming that audio is audible."));
		webStop_ = new QPushButton(tr("Stop stream"), webGroup);
		webFavoritesOnly_ = new QCheckBox(tr("★ Favorites"),webGroup);
		webPlayRow->addWidget(webSource_,0,0,1,3);
        webPlayRow->addWidget(webPlay_,1,0);
        webPlayRow->addWidget(webProbeButton_,1,1);
        webPlayRow->addWidget(webAlternate_,1,2);
        webPlayRow->addWidget(webStop_,2,0);
        webPlayRow->addWidget(webFavoritesOnly_,2,1,1,2);
        webPlayRow->setColumnStretch(0,1);
		webLayout->addLayout(webPlayRow);
		webStatus_ = new QLabel(tr("Internet radio is ready. No tuner connection required."),webGroup);
		webStatus_->setWordWrap(true);
		webLayout->addWidget(webStatus_);
		modes_->addTab(webGroup,tr("Internet radio"));

		// The analog radio is optional hardware; keep a bounded, collapsible
		// retro cabinet so the DAB channel table stays visible.
		auto *analogGroup=new QGroupBox(tr("Vintage analogue tuner · enable FM / MW / LW"),page);
		analogGroup->setCheckable(true);
		analogGroup->setChecked(false);
		analogGroup->setStyleSheet(QLatin1String(
			"QGroupBox{background:#30251b;color:#f1d6a1;border:2px solid #8d6634;"
			"border-radius:11px;margin-top:16px;padding-top:8px;font-weight:600;}"
			"QGroupBox::title{subcontrol-origin:margin;left:15px;padding:2px 8px;}"
			"QLabel{color:#f2d4a0;}"
			"QComboBox,QDoubleSpinBox{background:#171b1b;color:#efc783;"
			"border:1px solid #ac8042;border-radius:5px;padding:5px;}"
			"QPushButton{background:#6a4928;color:#fff0ce;border:1px solid #b69358;"
			"border-radius:6px;padding:6px 11px;min-height:30px;}"));
		auto *analogLayout=new QVBoxLayout(analogGroup);
		analogLayout->setSpacing(9);
		analogLayout->setContentsMargins(14,22,14,10);
		auto *analogCabinet=new QWidget(analogGroup);
		auto *cabinetLayout=new QVBoxLayout(analogCabinet);
		cabinetLayout->setContentsMargins(2,2,2,2);
        selectedStationVintage_=new QLabel(
            tr("Selected station: none · analogue dial controls FM/MW/LW only"),
            analogCabinet);
        selectedStationVintage_->setWordWrap(true);
        selectedStationVintage_->setTextFormat(Qt::PlainText);
        selectedStationVintage_->setStyleSheet(QLatin1String(
            "background:#141c1a;color:#eaca90;border:1px solid #96704a;"
            "border-radius:5px;padding:5px;font-weight:600;"));
        cabinetLayout->addWidget(selectedStationVintage_);
        vintageDabReadout_=new QLabel(analogCabinet);
        vintageDabReadout_->setWordWrap(true);
        vintageDabReadout_->setTextFormat(Qt::PlainText);
        vintageDabReadout_->setStyleSheet(QLatin1String(
            "background:#102b32;color:#c5f0fa;border:1px solid #47717d;"
            "border-radius:5px;padding:7px;font-weight:600;"));
        vintageDabReadout_->setVisible(false);
        vintageDabReadout_->setToolTip(tr(
            "Current/selected DAB+ Band III ensemble centre frequency. "
            "The brass analogue FM/MW/LW dial below remains independent."));
        cabinetLayout->addWidget(vintageDabReadout_);
		auto *analogHead=new QGridLayout();
		analogBand_=new QComboBox(analogCabinet);
		analogBand_->addItem(tr("FM · 87.5–108 MHz"),QLatin1String("fm"));
		analogBand_->addItem(tr("AM / MW · 531–1602 kHz"),QLatin1String("mw"));
		analogBand_->addItem(tr("LW · 150–280 kHz"),QLatin1String("lw"));
		analogBand_->setMinimumWidth(115);
        analogBand_->setMaximumWidth(260);
		analogFrequency_=new QDoubleSpinBox(analogCabinet);
		analogFrequency_->setDecimals(2);
		analogFrequency_->setRange(87.5,108.0);
		analogFrequency_->setValue(99.2);
		analogFrequency_->setSuffix(tr(" MHz"));
		analogFrequency_->setMinimumWidth(100);
        analogFrequency_->setMaximumWidth(160);
		analogDigital_=new QLabel(tr("99.20 MHz"),analogCabinet);
		analogDigital_->setStyleSheet(QLatin1String(
			"font: bold 20px monospace;color:#ffe1a1;background:#131916;"
			"border:1px solid #ac8042;border-radius:6px;padding:7px;"));
		analogHead->addWidget(analogBand_,0,0);
        analogHead->addWidget(analogFrequency_,0,1);
        analogHead->addWidget(analogDigital_,1,0,1,2);
        analogHead->setColumnStretch(1,1);
		cabinetLayout->addLayout(analogHead);
		auto *analogFace=new QHBoxLayout();
		analogScale_=new TihuluAnalogScale(analogCabinet);
		analogDial_=new TihuluBrassDial(analogCabinet);
		analogDial_->setRange(8750,10800);
		analogDial_->setValue(9920);
		analogDial_->setToolTip(tr("Turn with mouse wheel/drag; live retune after "
			"brief 450ms pause. RF hardware must reopen and may briefly go silent."));
		analogFace->addWidget(analogScale_,1);
		analogFace->addWidget(analogDial_);
		cabinetLayout->addLayout(analogFace);
		analogAudioVu_=new QProgressBar(analogCabinet);
		analogAudioVu_->setRange(0,100);
		analogAudioVu_->setValue(0);
		analogAudioVu_->setFormat(tr("Audio VU: no input (not an RF strength reading)"));
		analogAudioVu_->setToolTip(tr("Actual signed-PCM audio RMS level from rtl_fm. "
			"It does not measure SDR RSSI, DAB lock, or antenna RF power."));
		cabinetLayout->addWidget(analogAudioVu_);
		auto *buttons=new QGridLayout();
		analogStart_=new QPushButton(tr("Tune / play"),analogCabinet);
		analogStop_=new QPushButton(tr("Stop / release"),analogCabinet);
		analogStart_->setMaximumWidth(155);
		analogStop_->setMaximumWidth(155);
		buttons->addWidget(analogStart_,0,0);
        buttons->addWidget(analogStop_,0,1);
        buttons->addWidget(new QLabel(tr("Volume"),analogCabinet),1,0);
		analogVolume_=new QSlider(Qt::Horizontal,analogCabinet);
		analogVolume_->setRange(0,100);
		analogVolume_->setValue(player_->getVolume());
		analogVolume_->setMaximumWidth(170);
		analogVolume_->setToolTip(tr("Real libVLC player volume; controls the "
			"same stream as the main TIHULU media transport."));
		analogMute_=new QPushButton(tr("Toggle mute"),analogCabinet);
		analogMute_->setMaximumWidth(125);
		buttons->addWidget(analogVolume_,1,1);
        buttons->addWidget(analogMute_,1,2);
        buttons->setColumnStretch(1,1);
		buttons->setColumnStretch(3,1);
		connect(analogVolume_,&QSlider::valueChanged,player_,&MediaWidget::setVolume);
		connect(analogMute_,&QPushButton::clicked,player_,&MediaWidget::toggleMuted);
		cabinetLayout->addLayout(buttons);
		directSampling_=new QCheckBox(
			tr("Use hardware-specific direct sampling for MW/LW (opt-in)"),analogCabinet);
		directSampling_->setToolTip(tr("For compatible HF RTL-SDR hardware only."));
		cabinetLayout->addWidget(directSampling_);
		analogStatus_=new QLabel(tr("Optional RTL-SDR required. Built-in Kaffeine volume/"
			"mute controls the local analog stream; DVB-T2 Si2168 does not tune FM."),analogCabinet);
		analogStatus_->setWordWrap(true);
		cabinetLayout->addWidget(analogStatus_);
		analogLayout->addWidget(analogCabinet);
		modes_->addTab(analogGroup,tr("Vintage FM / AM / LW"));
		analogRetune_.setSingleShot(true);
		analogRetune_.setInterval(450);
		connect(&analogRetune_,&QTimer::timeout,this,[this](){
			if(analogServer_.isListening()) retuneAnalogDemod();
		});
		connect(analogBand_,QOverload<int>::of(&QComboBox::currentIndexChanged),
			this,[this](){configureAnalogBand();});
		connect(analogDial_,&QDial::valueChanged,this,[this](int v){
			analogFrequency_->setValue(v/100.);
		});
		connect(analogFrequency_,QOverload<double>::of(&QDoubleSpinBox::valueChanged),
			this,[this](double v){
			analogDial_->setValue(qRound(v*100.));
			analogDigital_->setText(QString::number(v,'f',
				analogBand_->currentData().toString()==QLatin1String("fm")?2:0)+
				analogFrequency_->suffix());
			analogScale_->updateFrequency(
				analogFrequency_->minimum(),analogFrequency_->maximum(),v,
				analogBand_->currentText());
			if(analogServer_.isListening()) analogRetune_.start();
		});
		connect(analogStart_,&QPushButton::clicked,this,[this](){
            startAnalog();
            if(analogServer_.isListening()) showSelectedSource(
                tr("Live analogue SDR"),analogBand_->currentText(),
                QString::number(analogFrequency_->value(),'f',2)+
                    analogFrequency_->suffix());
        });
		connect(analogStop_,&QPushButton::clicked,this,[this](){stopAnalog();});
		connect(&analogDemod_,&QProcess::readyReadStandardError,this,[this](){
			const QString msg=QString::fromLocal8Bit(analogDemod_.readAllStandardError());
            if(!msg.trimmed().isEmpty()) lastAnalogError_=msg.trimmed().right(600);
			if(msg.contains(QLatin1String("Failed"),Qt::CaseInsensitive) ||
			   msg.contains(QLatin1String("error"),Qt::CaseInsensitive))
				analogStatus_->setText(msg.right(320));
		});
		connect(&analogDemod_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
			this,[this](int code,QProcess::ExitStatus){
				if(!analogStopping_) {
                    lastAnalogError_=tr("rtl_fm exited (%1). %2")
                        .arg(code).arg(lastAnalogError_).right(600);
                    analogStatus_->setText(tr("Analog SDR exited (%1). "
                        "Open Hardware tab for USB presence and owner scan.").arg(code));
                }
			});
		configureAnalogBand();

		auto *split = new QSplitter(Qt::Horizontal, page);
		auto *library = new QWidget(split);
		auto *libraryLayout = new QVBoxLayout(library);
		libraryLayout->setContentsMargins(1,1,1,1);
		libraryLayout->setSpacing(5);
		auto *libraryHeader = new QLabel(tr("All scanned DAB stations"),library);
		libraryHeader->setStyleSheet(QLatin1String("font-weight:600;font-size:15px"));
		libraryLayout->addWidget(libraryHeader);
		stationSearch_ = new QLineEdit(library);
		stationSearch_->setPlaceholderText(tr("Search every saved DAB ensemble…"));
		stationSearch_->setClearButtonEnabled(true);
		libraryLayout->addWidget(stationSearch_);
		auto *libraryFilters = new QHBoxLayout();
		libraryBlock_ = new QComboBox(library);
		libraryBlock_->addItem(tr("All DAB blocks"),QString());
		for (const QString &block : blocks)
			libraryBlock_->addItem(block,block);
		favoritesOnly_ = new QCheckBox(tr("★ Favorites only"),library);
		libraryFilters->addWidget(libraryBlock_,1);
		libraryFilters->addWidget(favoritesOnly_);
		libraryLayout->addLayout(libraryFilters);
        // User-created playlists are local; only a station double-click tunes.
        auto *listPickerRow=new QHBoxLayout();
        listPickerRow->addWidget(new QLabel(tr("My station lists:"),library));
        stationListPicker_=new QComboBox(library);
        stationListPicker_->setToolTip(tr(
            "Choose a list to edit. Uncheck Show only list to browse "
            "all scanned stations and add them to this list."));
        listPickerRow->addWidget(stationListPicker_,1);
        newStationList_=new QPushButton(tr("New list"),library);
        deleteStationList_=new QPushButton(tr("Delete list"),library);
        listPickerRow->addWidget(newStationList_);
        listPickerRow->addWidget(deleteStationList_);
        libraryLayout->addLayout(listPickerRow);
        auto *listActions=new QHBoxLayout();
        addStationList_=new QPushButton(tr("+ Add selected"),library);
        removeStationList_=new QPushButton(tr("− Remove selected"),library);
        stationListOnly_=new QCheckBox(tr("Show only list"),library);
        stationListOnly_->setChecked(false);
        listActions->addWidget(addStationList_);
        listActions->addWidget(removeStationList_);
        listActions->addWidget(stationListOnly_);
        libraryLayout->addLayout(listActions);
		stations_ = new QTreeWidget(library);
		stations_->setHeaderLabels({tr("★"),tr("Station"),tr("DAB block"),tr("Service ID")});
		stations_->setRootIsDecorated(false);
		stations_->setAlternatingRowColors(true);
		stations_->setSortingEnabled(true);
		stations_->setMinimumWidth(200);
        stations_->setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Expanding);
		stations_->header()->setSectionResizeMode(0,QHeaderView::Fixed);
		stations_->header()->resizeSection(0,29);
		stations_->header()->setSectionResizeMode(1,QHeaderView::Stretch);
		stations_->header()->setSectionResizeMode(2,QHeaderView::ResizeToContents);
		stations_->header()->setSectionResizeMode(3,QHeaderView::ResizeToContents);
		stations_->setSortingEnabled(true);
		libraryLayout->addWidget(stations_,1);
		libraryStatus_ = new QLabel(tr("Scan every Band III block or open a saved station"),library);
		libraryLayout->addWidget(libraryStatus_);
		split->addWidget(library);

		auto *right = new QWidget(split);
		auto *rightLayout = new QVBoxLayout(right);
		rightLayout->setContentsMargins(5, 4, 5, 4);
		rightLayout->setSpacing(6);
		playerHost_ = new QWidget(right);
		playerHostLayout_ = new QVBoxLayout(playerHost_);
		playerHostLayout_->setContentsMargins(0, 0, 0, 0);
		rightLayout->addWidget(playerHost_, 3);
		// The radio is audio-only. Keep Kaffeine's global libVLC MediaWidget
		// owned by Playback/Playlist/Television. Reparenting it into Radio
		// broke file playback and left a duplicate transport bar in the
		// video canvas. This is a radio visualization and caption surface.
		radioCanvas_ = new QLabel(QString(), playerHost_);
		radioCanvas_->setAlignment(Qt::AlignCenter);
		radioCanvas_->setWordWrap(true);
		radioCanvas_->setMinimumHeight(300);
		radioCanvas_->setStyleSheet(QLatin1String(
			"QLabel{background:#122637;color:#eef9fc;font-size:19px;"
			"border:1px solid #2b566b;border-radius:8px;padding:12px;}"));
		playerHostLayout_->addWidget(radioCanvas_);
        // Radio subtitles belong INSIDE the large station surface, not
        // in the settings-only panel. Preserve radioCanvas_'s station art/
        // receiver text; a separate bottom child overlays real cues.
        auto *captionSurface=new QVBoxLayout(radioCanvas_);
        captionSurface->setContentsMargins(12,12,12,12);
        radioCanvasStation_=new QLabel(tr("Radio · choose a station to listen"),radioCanvas_);
        radioCanvasStation_->setTextFormat(Qt::PlainText);
        radioCanvasStation_->setWordWrap(true);
        radioCanvasStation_->setAlignment(Qt::AlignLeft | Qt::AlignVCenter);
        radioCanvasStation_->setMaximumHeight(66);
        radioCanvasStation_->setStyleSheet(QLatin1String(
            "QLabel{color:#a6dbe9;background:#17384b;border:none;"
            "border-radius:6px;padding:5px 9px;font-size:12px;}"));
        captionSurface->addWidget(radioCanvasStation_,0,Qt::AlignTop);
        captionSurface->addStretch(1);
        // A separate karaoke layer occupies the BLUE DAB station canvas.
        // The bottom subtitles remain a distinct Whisper/translation
        // display. Match confidence is measured at LINE level, not words.
        karaokePanel_=new QWidget(radioCanvas_);
        karaokePanel_->setObjectName(QStringLiteral("radioKaraokePanel"));
        karaokePanel_->setStyleSheet(QLatin1String(
            "QWidget#radioKaraokePanel{background:rgba(8,26,44,236);"
            "border:1px solid #385c75;border-radius:12px;}"));
        auto *karaokeLayout=new QVBoxLayout(karaokePanel_);
        karaokeLayout->setContentsMargins(14,12,14,12);
        karaokeLayout->setSpacing(5);
        karaokeSource_=new QLabel(karaokePanel_);
        karaokeSource_->setTextFormat(Qt::PlainText);
        karaokeSource_->setWordWrap(true);
        karaokeSource_->setAlignment(Qt::AlignCenter);
        karaokeSource_->setStyleSheet(QLatin1String(
            "color:#aec4d6;font-size:11pt;font-weight:500;"));
        karaokePrevious_=new QLabel(karaokePanel_);
        karaokePrevious_->setTextFormat(Qt::PlainText);
        karaokePrevious_->setWordWrap(true);
        karaokePrevious_->setAlignment(Qt::AlignCenter);
        karaokePrevious_->setStyleSheet(QLatin1String(
            "color:#94a7b9;font-size:13pt;"));
        karaokeCurrent_=new QLabel(karaokePanel_);
        karaokeCurrent_->setTextFormat(Qt::PlainText);
        karaokeCurrent_->setWordWrap(true);
        karaokeCurrent_->setAlignment(Qt::AlignCenter);
        karaokeCurrent_->setStyleSheet(QLatin1String(
            "color:#ffe17c;font-size:24pt;font-weight:700;"));
        karaokeNext_=new QLabel(karaokePanel_);
        karaokeNext_->setTextFormat(Qt::PlainText);
        karaokeNext_->setWordWrap(true);
        karaokeNext_->setAlignment(Qt::AlignCenter);
        karaokeNext_->setStyleSheet(QLatin1String(
            "color:#a8b9c6;font-size:13pt;"));
        karaokeTranslation_=new QLabel(karaokePanel_);
        karaokeTranslation_->setTextFormat(Qt::PlainText);
        karaokeTranslation_->setWordWrap(true);
        karaokeTranslation_->setAlignment(Qt::AlignCenter);
        karaokeTranslation_->setStyleSheet(QLatin1String(
            "color:#ffdc61;font-size:15pt;font-weight:600;"));
        karaokeTranslation_->setToolTip(tr(
            "Only real lyric translations from the selected model appear. "
            "Source words remain prominent above; ordinary caption "
            "translations remain independently in the bottom bar."));
        karaokeLayout->addWidget(karaokeSource_);
        karaokeLayout->addWidget(karaokePrevious_);
        karaokeLayout->addWidget(karaokeCurrent_);
        karaokeLayout->addWidget(karaokeTranslation_);
        karaokeLayout->addWidget(karaokeNext_);
        karaokePanel_->setMinimumHeight(235);
        karaokePanel_->setVisible(false);
        captionSurface->addWidget(karaokePanel_,2,Qt::AlignVCenter);
        captionSurface->addStretch(1);
        radioCanvasCaption_=new QLabel(radioCanvas_);
        radioCanvasCaption_->setTextFormat(Qt::PlainText);
        radioCanvasCaption_->setWordWrap(true);
        radioCanvasCaption_->setAlignment(Qt::AlignHCenter | Qt::AlignVCenter);
        radioCanvasCaption_->setStyleSheet(QLatin1String(
            "QLabel{background:rgba(0,0,0,205);color:white;"
            "border-radius:5px;padding:8px;font-size:16px;}"));
        radioCanvasCaption_->setVisible(false);
        radioCanvasCaption_->setMaximumHeight(210);
        radioCanvasCaption_->setToolTip(tr(
            "Original heard audio + selected translation outputs. "
            "Captions are aligned to captured PCM timestamps, not "
            "measured libVLC audio presentation timestamps."));
        radioLyricMatchStatus_=new QLabel(radioCanvas_);
        radioLyricMatchStatus_->setTextFormat(Qt::PlainText);
        radioLyricMatchStatus_->setWordWrap(true);
        radioLyricMatchStatus_->setAlignment(Qt::AlignCenter);
        radioLyricMatchStatus_->setStyleSheet(QLatin1String(
            "QLabel{background:rgba(0,0,0,205);color:#cdebf5;"
            "border-radius:5px;padding:4px;font-size:13px;}"));
        radioLyricMatchStatus_->setVisible(false);
        radioLyricMatchStatus_->setToolTip(tr(
            "Lyrics FOUND means matching song metadata. Audio MATCHED "
            "requires a real Whisper lyric line match; when no match "
            "exists, actual speech stays visible as a transcription."));
        captionSurface->addWidget(radioLyricMatchStatus_);
        captionSurface->addWidget(radioCanvasCaption_);
        updateRadioCaptionTypography();

		auto *meta = new QHBoxLayout();
		slide_ = new QLabel(tr("No DAB slideshow"), right);
		slide_->setAlignment(Qt::AlignCenter);
		slide_->setFixedSize(185, 112);
		slide_->setStyleSheet(QLatin1String("border:1px solid #466;"));
		auto *slides = new QVBoxLayout();
		slides->addWidget(slide_);
		auto *slideControls=new QHBoxLayout();
		slidePrev_=new QPushButton(tr("◀"),right);
		slideNext_=new QPushButton(tr("▶"),right);
		slideControls->addWidget(slidePrev_);
		slideControls->addWidget(slideNext_);
		slides->addLayout(slideControls);
		meta->addLayout(slides);
		auto *textBlock = new QVBoxLayout();
		dls_ = new QLabel(tr("DLS radio text will appear here."), right);
		dls_->setTextFormat(Qt::PlainText);
		dls_->setWordWrap(true);
		signal_ = new QLabel(tr("SNR / FIC / ensemble diagnostics: no RF readings."), right);
		signal_->setTextFormat(Qt::PlainText);
		signal_->setWordWrap(true);
		rfQuality_=new QProgressBar(right);
		rfQuality_->setRange(0,100);
		rfQuality_->setValue(0);
		rfQuality_->setFormat(tr("DAB signal: unmeasured"));
		rfQuality_->setToolTip(tr("Relative indication derived from receiver-reported "
			"SNR, not calibrated RF power or signal strength."));
		textBlock->addWidget(dls_);
		textBlock->addWidget(signal_);
		textBlock->addWidget(rfQuality_);
		meta->addLayout(textBlock, 1);
		rightLayout->addLayout(meta);
		split->addWidget(right);
		split->setStretchFactor(0,1);
		split->setStretchFactor(1,2);
		stationSplit_=split;
        dabLayout->addWidget(split, 4);

		auto *lab = new QGroupBox(tr("Captions · input language / output translations / lyrics"), this);
		auto *v = new QVBoxLayout(lab);
		auto *row = new QGridLayout();
        row->setHorizontalSpacing(7);
        row->setVerticalSpacing(5);
        v->addWidget(new QLabel(
            tr("<b>1 · Heard audio (IN)</b> · Auto detect or choose English, German, etc."),lab));
		speechLanguage_ = new QComboBox(lab);
		speechLanguage_->addItem(tr("Auto detect · Whisper (selected local model)"),"auto");
        // The complete supported Whisper input set is filled from the
        // shared catalog. Keep a usable offline fallback until it arrives.
        for(const QString &code:QStringList{"de","en","tr","fr","es","pl","ar","ja"})
            speechLanguage_->addItem(code.toUpper(),code);
        speechLanguage_->setEditable(false);
        speechLanguage_->setToolTip(tr(
            "Auto detect uses the selected Whisper model. Every other IN "
            "language is supported by a multilingual speech model, NOT a "
            "separately installed translation package. Actual source "
            "detection confidence depends on engine and the audio."));
        spokenModelStatus_=new QLabel(tr(
            "Checking locally installed Whisper model…"),lab);
        spokenModelStatus_->setWordWrap(true);
        QSettings initialRadioLanguages(QLatin1String("TIHULU"),
                                       QLatin1String("KaffeineRadio"));
        const int savedSpeechIndex=speechLanguage_->findData(
            initialRadioLanguages.value(
                QLatin1String("radioSpeechLanguage"),"auto").toString());
        speechLanguage_->setCurrentIndex(savedSpeechIndex>=0?savedSpeechIndex:0);
		captionSource_=new QComboBox(lab);
		captionSource_->addItem(tr("Whisper ASR · recognized live audio"),
			QLatin1String("asr"));
		captionSource_->addItem(tr("Broadcaster DLS · metadata only, NOT subtitles"),
			QLatin1String("dls"));
		captionSource_->setToolTip(tr("DAB DLS is program/song metadata, not a "
			"guaranteed subtitle channel. Whisper generates spoken-word subtitles "
			"from actual audio; timed lyrics are separate."));
		german_ = new QCheckBox(tr("German"), lab); german_->setChecked(true);
		english_ = new QCheckBox(tr("English"), lab); english_->setChecked(true);
		turkish_ = new QCheckBox(tr("Turkish"), lab); turkish_->setChecked(true);
		music_ = new QCheckBox(tr("Transcribe singing / music vocals"), lab);
        music_->setChecked(initialRadioLanguages.value(
            QLatin1String("radioMusicTranscription"),false).toBool());
        connect(music_,&QCheckBox::toggled,this,[](bool enabled){
            QSettings prefs(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
            prefs.setValue(QLatin1String("radioMusicTranscription"),enabled);
        });
        music_->setToolTip(tr("Show original sung words and selected translations "
            "when Whisper confirms song language. If matched lyrics exist, "
            "prefer their text; uncertain language is NEVER guessed. "
            "Choose a specific language for immediate lyric translation."));
		speakerLabels_=new QCheckBox(tr("Label different speakers · offline"),lab);
		speakerLabels_->setToolTip(tr("Optional installed voice-clustering model. "
			"Outputs Speaker 1/2, NOT inferred woman/man/child labels. "
			"Disable when music is playing."));
		connect(music_,&QCheckBox::toggled,speakerLabels_,[this](bool enabled){
			speakerLabels_->setEnabled(!enabled);
			if(enabled) speakerLabels_->setChecked(false);
		});
		caption_ = new QPushButton(tr("Start offline live captions"), lab);
        applyCaptions_=new QPushButton(tr("Apply caption settings"),lab);
        applyCaptions_->setToolTip(tr("Restart only local Whisper/translation "
            "with the current speech language, music, source and targets. "
            "Keeps receiver tuning, radio playback and requested cache untouched."));
		stopCaption_ = new QPushButton(tr("Stop AI captions"), lab);
		row->addWidget(new QLabel(tr("Caption source:"),lab),0,0);
        row->addWidget(captionSource_,0,1,1,2);
        row->addWidget(new QLabel(tr("Speech language:"),lab),1,0);
        row->addWidget(speechLanguage_,1,1,1,2);
        row->addWidget(spokenModelStatus_,2,0,1,3);
        // Legacy quick checkboxes are retained as disabled compatibility
        // objects only. ONE checkable multi-output list below owns targets.
        english_->hide(); german_->hide(); turkish_->hide();
        row->addWidget(music_,3,0,1,2);
        row->addWidget(speakerLabels_,3,2);
        row->setColumnStretch(1,1);
		v->addLayout(row);
        v->addWidget(new QLabel(tr(
            "<b>2 · Subtitle languages (OUT)</b> · check multiple languages. "
            "The original is always shown; missing translations are reported."),lab));
        translationStatus_=new QLabel(tr(
            "Translations: show original audio first. Select output languages; "
            "automatic source translation waits for reliable Whisper detection."),lab);
        translationStatus_->setWordWrap(true);
        translationStatus_->setTextFormat(Qt::PlainText);
        v->addWidget(translationStatus_);
		extraTargets_=new QLineEdit(lab);
		extraTargets_->setPlaceholderText(
			tr("Advanced · additional ISO targets not listed (comma-separated)"));
        extraTargets_->setToolTip(tr(
            "Advanced override for NLLB/MADLAD-supported ISO codes. "
            "A model weight file is not proof of real translation ability."));
        extraTargets_->setVisible(false);
        advancedLanguages_=new QCheckBox(tr("Advanced · enter other output language codes"),lab);
        connect(advancedLanguages_,&QCheckBox::toggled,extraTargets_,
                &QWidget::setVisible);
        v->addWidget(advancedLanguages_);
		v->addWidget(extraTargets_);
		auto *targetRow=new QHBoxLayout();
		installedTargets_=new QListWidget(lab);
		installedTargets_->setMinimumHeight(110);
        installedTargets_->setMaximumHeight(180);
		installedTargets_->setToolTip(tr("Shared TV/Radio Model Market catalog: "
            "Argos pairs, NLLB/MADLAD installed weights and explicitly configured "
            "online DeepL. Check up to six outputs. Listed does not guarantee "
            "the selected source-to-target translation will succeed."));
		refreshTargets_=new QPushButton(tr("Refresh installed models / languages"),lab);
		refreshTargets_->setToolTip(tr("Read-only local model catalog; never downloads models."));
		targetRow->addWidget(installedTargets_,1);
        auto *modelButtons=new QVBoxLayout();
        modelButtons->addWidget(refreshTargets_);
        auto *openModelMarket=new QPushButton(tr("Open AI Model Market"),lab);
        openModelMarket->setToolTip(tr(
            "Open the same Whisper / translator manager used by TV. "
            "Refresh this radio catalog after applying another model."));
        connect(openModelMarket,&QPushButton::clicked,this,[this](){
            if(!QProcess::startDetached(QLatin1String("tihulu-tv-center"),
                {QLatin1String("ai-market")}))
                translationStatus_->setText(tr(
                    "Could not open Model Market; use the TIHULU AI menu."));
        });
        modelButtons->addWidget(openModelMarket);
		targetRow->addLayout(modelButtons);
		v->addLayout(targetRow);
		connect(refreshTargets_,&QPushButton::clicked,this,[this](){refreshLanguagePacks();});
        connect(&languagePackWorker_,
            QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),this,
            [this](int status,QProcess::ExitStatus exitStatus){
                refreshTargets_->setEnabled(true);
                if(status!=0 || exitStatus!=QProcess::NormalExit){
                    translationStatus_->setText(tr(
                        "Language catalog unavailable. Refresh to retry; "
                        "current checked outputs are preserved."));
                    return;
                }
                const QJsonDocument doc=QJsonDocument::fromJson(
                    languagePackWorker_.readAllStandardOutput());
                const QJsonObject info=doc.object();
                const QJsonArray catalog=info.value(
                    QLatin1String("languages")).toArray();
                if(catalog.isEmpty() && !info.contains(
                    QLatin1String("speech_languages"))) {
                    translationStatus_->setText(tr(
                        "No model catalog returned; previous language choices kept."));
                    return;
                }
                QSet<QString> selected;
                if(installedTargets_->count()>0) {
                    for(int i=0;i<installedTargets_->count();++i) {
                        const QListWidgetItem *item=installedTargets_->item(i);
                        if(item->checkState()==Qt::Checked)
                            selected.insert(item->data(Qt::UserRole).toString());
                    }
                } else {
                    QSettings preferences(QLatin1String("TIHULU"),
                                         QLatin1String("KaffeineRadio"));
                    const QStringList saved=preferences.value(
                        QLatin1String("radioOutputs"),
                        QStringList{QLatin1String("en"),QLatin1String("de"),
                                    QLatin1String("tr")}).toStringList();
                    for(const QString &code:saved) selected.insert(code);
                }
                {
                    const QSignalBlocker block(installedTargets_);
                    installedTargets_->clear();
                    QSet<QString> available;
                    for(const QJsonValue &value:catalog) {
                        const QJsonObject model=value.toObject();
                        const QString code=model.value(
                            QLatin1String("code")).toString();
                        if(!QRegularExpression(QLatin1String("^[a-z]{2,3}$"))
                           .match(code).hasMatch()) continue;
                        available.insert(code);
                        QStringList engines;
                        for(const QJsonValue &engine:model.value(
                            QLatin1String("engines")).toArray())
                            engines<<engine.toString();
                        auto *item=new QListWidgetItem(
                            code.toUpper()+QLatin1String(" · ")+
                            model.value(QLatin1String("label")).toString()+
                            QLatin1String(" · ")+engines.join(QLatin1String(" / ")),
                            installedTargets_);
                        item->setData(Qt::UserRole,code);
                        item->setFlags(item->flags()|Qt::ItemIsUserCheckable);
                        item->setCheckState(selected.contains(code)?
                            Qt::Checked:Qt::Unchecked);
                        item->setToolTip(tr(
                            "Installed/local model metadata, NOT verified "
                            "source-to-target inference. Online DeepL sends "
                            "text only with existing consent and API key."));
                    }
                    // Keep saved languages visible even if the translator
                    // catalog cannot find any compatible installed model.
                    for(const QString &code:selected) {
                        if(available.contains(code) || !QRegularExpression(
                            QLatin1String("^[a-z]{2,3}$"))
                            .match(code).hasMatch()) continue;
                        auto *item=new QListWidgetItem(
                            code.toUpper()+tr(" · selected · model not found"),
                            installedTargets_);
                        item->setData(Qt::UserRole,code);
                        item->setFlags(item->flags()|Qt::ItemIsUserCheckable);
                        item->setCheckState(Qt::Checked);
                        item->setToolTip(tr(
                            "You requested this output language, but no "
                            "installed translation model candidate was found. "
                            "Install a compatible model and refresh. "
                            "Unavailable text will never be invented."));
                    }
                }
                const QString previous=speechLanguage_->currentData().isValid()?
                    speechLanguage_->currentData().toString():
                    speechLanguage_->currentText().trimmed().toLower();
                const QJsonArray inputLanguages=info.value(
                    QLatin1String("speech_languages")).toArray();
                if(!inputLanguages.isEmpty()){
                    const QSignalBlocker block(speechLanguage_);
                    speechLanguage_->clear();
                    speechLanguage_->addItem(tr("Auto detect · Whisper (selected local model)"),"auto");
                    for(const QJsonValue &value:inputLanguages){
                        const QJsonObject entry=value.toObject();
                        const QString code=entry.value(
                            QLatin1String("code")).toString();
                        if(code.isEmpty()) continue;
                        speechLanguage_->addItem(
                            entry.value(QLatin1String("label")).toString()+
                            QLatin1String(" (")+code.toUpper()+QLatin1Char(')'),
                            code);
                    }
                    const int index=speechLanguage_->findData(previous);
                    speechLanguage_->setCurrentIndex(index>=0?index:0);
                }
                spokenModelStatus_->setText(info.value(
                    QLatin1String("speech_model_present")).toBool()?
                    tr("IN · Whisper model files found: %1. Listed spoken "
                       "languages use the selected multilingual model "
                       "(not installed one by one). Auto detect remains available.")
                        .arg(info.value(QLatin1String("speech_models_installed"))
                            .toArray().size()):
                    tr("IN · No local Whisper model found. Choose or install "
                       "one in Model Market. Auto detect is listed but "
                       "cannot run until a speech model is available."));
                translationStatus_->setText(tr(
                    "Selected TV/Radio translator: %1 · speech backend: %2. "
                    "%3 candidate outputs from installed model metadata. "
                    "Check up to six; inference is verified only during playback.")
                    .arg(info.value(QLatin1String("selected_translator"))
                            .toString(QLatin1String("unknown")),
                         info.value(QLatin1String("selected_speech_backend"))
                            .toString(QLatin1String("auto")))
                    .arg(installedTargets_->count()));
            });
        // Keep output selections stable across AI tab and station changes.
        connect(installedTargets_,&QListWidget::itemChanged,this,
            [this](QListWidgetItem *changed){
                if(!changed || changed->data(Qt::UserRole).toString().isEmpty())
                    return;
                QStringList selected;
                for(int i=0;i<installedTargets_->count();++i) {
                    QListWidgetItem *item=installedTargets_->item(i);
                    if(item->checkState()==Qt::Checked)
                        selected<<item->data(Qt::UserRole).toString();
                }
                if(selected.size()>6) {
                    const QSignalBlocker block(installedTargets_);
                    changed->setCheckState(Qt::Unchecked);
                    translationStatus_->setText(tr(
                        "Select at most six output languages."));
                    return;
                }
                QSettings preferences(QLatin1String("TIHULU"),
                                     QLatin1String("KaffeineRadio"));
                preferences.setValue(QLatin1String("radioOutputs"),selected);
                refreshRadioLanguageSummary();
                if(writeRadioLanguageControls() &&
                   captionProcess_.state()!=QProcess::NotRunning)
                    translationStatus_->setText(tr(
                        "Output languages updated LIVE. New selections "
                        "apply on the next decoded 5 s audio hop; no "
                        "Whisper or radio restart."));
            });
        connect(speechLanguage_,QOverload<int>::of(&QComboBox::currentIndexChanged),
            this,[this](int){
                QSettings settings(QLatin1String("TIHULU"),
                                   QLatin1String("KaffeineRadio"));
                settings.setValue(QLatin1String("radioSpeechLanguage"),
                    speechLanguage_->currentData().toString());
                refreshRadioLanguageSummary();
                writeRadioLanguageControls();
            });
        connect(extraTargets_,&QLineEdit::editingFinished,this,[this](){
            refreshRadioLanguageSummary();
            writeRadioLanguageControls();
        });
        connect(advancedLanguages_,&QCheckBox::toggled,this,[this](bool){
            refreshRadioLanguageSummary();
            writeRadioLanguageControls();
        });
		auto *syncControls=new QGridLayout();
		bufferMs_=new QSpinBox(lab);
		bufferMs_->setRange(0,60000);
		bufferMs_->setSingleStep(500);
		bufferMs_->setSuffix(tr(" ms"));
		QSettings radioSettings(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
		bufferMs_->setValue(qBound(0,
            radioSettings.value(QLatin1String("radioBufferDesiredMs"),
                radioSettings.value(QLatin1String("playbackBufferMs"),12000)).toInt(),
            60000));
        quickBuffer_->setChecked(
            radioSettings.value(QLatin1String("radioBufferEnabled"),false).toBool());
        quickBuffer_->setText(quickBuffer_->isChecked()?
            tr("Extra buffer · ON"):tr("Extra buffer · OFF"));
        // Legacy 12s network cache is intentionally NOT reenabled just
        // because an earlier installation had saved it. Preserve its
        // numeric preference for the next explicit user enable.
        activePlaybackCacheMs_=quickBuffer_->isChecked()?bufferMs_->value():0;
        radioSettings.setValue(QLatin1String("playbackBufferMs"),activePlaybackCacheMs_);
        mainBufferSlider_=new QSlider(Qt::Horizontal,page);
        mainBufferSlider_->setRange(0,120);
        mainBufferSlider_->setValue(qBound(0,(bufferMs_->value()+250)/500,120));
        mainBufferSlider_->setMinimumWidth(150);
        mainBufferSlider_->setToolTip(tr(
            "Requested extra audio cache 0–60 s, 0.5 s steps. "
            "Remains pending until Apply buffer, which may briefly restart audio. "
            "Not a measurement of actual speaker/DAC delay."));
        mainBufferReadout_=new QLabel(page);
        auto *applyMainBuffer=new QPushButton(tr("Apply buffer"),page);
        mainBufferRow->addWidget(new QLabel(tr("Extra buffer:"),page));
        mainBufferRow->addWidget(mainBufferSlider_,1);
        mainBufferRow->addWidget(mainBufferReadout_);
        mainBufferRow->addWidget(applyMainBuffer);
        const auto updateMainBuffer=[this](){
            mainBufferReadout_->setText(tr("%1 s · %2")
                .arg(QString::number(selectedBufferMs()/1000.,'f',1))
                .arg(selectedBufferMs()==activePlaybackCacheMs_?
                     tr("applied"):tr("pending Apply")));
        };
        updateMainBuffer();
        connect(mainBufferSlider_,&QSlider::valueChanged,this,
            [this,updateMainBuffer](int value){
                setBufferDisplayMs(value*500);
                updateMainBuffer();
            });
        connect(bufferMs_,QOverload<int>::of(&QSpinBox::valueChanged),
            this,[this,updateMainBuffer](int){
                const QSignalBlocker hold(mainBufferSlider_);
                mainBufferSlider_->setValue(qBound(0,
                    (selectedBufferMs()+250)/500,120));
                updateMainBuffer();
            });
        connect(applyMainBuffer,&QPushButton::clicked,this,
            [this,updateMainBuffer](){
                applyRadioBuffer();
                updateMainBuffer();
            });
		bufferMs_->setToolTip(tr("Radio libVLC network cache requested at stream OPEN. "
            "Range 0–60000 ms (safety limit, 60 s). If changed during playback "
            "it remains PENDING until Apply or the next station; not verified "
            "physical DAC/ALSA delay."));
        autoSync_=new QCheckBox(tr("Auto size · ASR + safety"),page);
        autoSync_->setChecked(quickBuffer_->isChecked() &&
            radioSettings.value(QLatin1String("radioAutoBufferEnabled"),false).toBool());
        autoSync_->setToolTip(tr("Optional. Estimate extra playback cache from "
            "five-second speech capture, observed ASR/translation workload "
            "and a three-second margin. NOT a measured DAC clock or RF "
            "dropout detector. Does NOT restart live audio by default."));
        radioPlaybackRow_->insertWidget(1,autoSync_);
		radioOffsetMs_=new QSpinBox(lab);
		radioOffsetMs_->setRange(-12000,12000);
		radioOffsetMs_->setSingleStep(250);
		radioOffsetMs_->setSuffix(tr(" ms"));
		radioOffsetMs_->setValue(qBound(-12000,
			radioSettings.value(QLatin1String("captionOffsetMs"),0).toInt(),12000));
        radioOffsetMs_->setToolTip(tr("AI captions ONLY: positive moves speech "
            "subtitles later; negative earlier. Pending spoken captions move "
            "without re-running Whisper; Karaoke stays independent."));
        mainCaptionOffsetSlider_=new QSlider(Qt::Horizontal,page);
        mainCaptionOffsetSlider_->setRange(-48,48);
        mainCaptionOffsetSlider_->setValue(radioOffsetMs_->value()/250);
        mainCaptionOffsetSlider_->setMinimumWidth(150);
        mainCaptionOffsetSlider_->setToolTip(tr(
            "Caption timing ±12 seconds in 250 ms steps. "
            "The radio audio never restarts."));
        mainOffsetRow->addWidget(new QLabel(tr("AI captions offset (only):"),page));
        mainOffsetRow->addWidget(mainCaptionOffsetSlider_,1);
        connect(mainCaptionOffsetSlider_,&QSlider::valueChanged,
            this,[this](int n){ radioOffsetMs_->setValue(n*250); });
        connect(radioOffsetMs_,QOverload<int>::of(&QSpinBox::valueChanged),
            this,[this](int n){
                const QSignalBlocker hold(mainCaptionOffsetSlider_);
                mainCaptionOffsetSlider_->setValue(n/250);
            });
		autoRestartAudio_=new QCheckBox(tr("Allow automatic radio audio restart"),lab);
		autoRestartAudio_->setChecked(false);
		autoRestartAudio_->setToolTip(tr("OFF (recommended) never disrupts ongoing audio. "
            "When ON, a large compute-driven increase can reopen the stream "
            "at most once per 3 minutes. Restarting can still cause dropouts."));
		auto *applyBuffer=new QPushButton(tr("Apply radio buffer"),lab);
		syncControls->addWidget(new QLabel(tr("Audio buffer:"),lab),0,0);
		syncControls->addWidget(bufferMs_,0,1);
        bufferUnit_=new QComboBox(lab);
        bufferUnit_->addItem(tr("Milliseconds"),1);
        bufferUnit_->addItem(tr("Seconds"),1000);
        bufferUnit_->setToolTip(tr("Display and enter extra buffer in ms or s; "
            "saved setting remains milliseconds."));
        syncControls->addWidget(bufferUnit_,0,2);
		syncControls->addWidget(applyBuffer,0,3);
		syncControls->addWidget(new QLabel(tr("Caption offset:"),lab),1,0);
		syncControls->addWidget(radioOffsetMs_,1,1);
        syncControls->addWidget(new QLabel(tr(
            "Timing is estimated; no sound-card sample clock"),lab),1,2,1,2);
		syncControls->setColumnStretch(2,1);
        // Keep latency diagnostics available without turning the normal
        // caption/lyrics workflow into a wall of timing controls.
        auto *advancedSyncToggle=new QCheckBox(
            tr("Advanced · audio cache, timing & diagnostics"),lab);
        advancedSyncToggle->setChecked(false);
        auto *advancedSyncPanel=new QWidget(lab);
        auto *advancedSyncLayout=new QVBoxLayout(advancedSyncPanel);
        advancedSyncLayout->setContentsMargins(0,2,0,2);
        advancedSyncLayout->addLayout(syncControls);
        advancedSyncLayout->addWidget(autoRestartAudio_);
        connect(bufferUnit_,QOverload<int>::of(&QComboBox::currentIndexChanged),
            this,[this](int){
                const int previousMs=bufferMs_->value()*
                    (bufferUnitsSeconds_?1000:1);
                bufferUnitsSeconds_=(bufferUnit_->currentData().toInt()==1000);
                const QSignalBlocker block(bufferMs_);
                bufferMs_->setRange(0,bufferUnitsSeconds_?60:60000);
                bufferMs_->setSingleStep(bufferUnitsSeconds_?1:500);
                bufferMs_->setSuffix(bufferUnitsSeconds_?tr(" s"):tr(" ms"));
                bufferMs_->setValue(bufferUnitsSeconds_?
                    qBound(0,(previousMs+500)/1000,60):
                    qBound(0,previousMs,60000));
            });
        advancedSyncPanel->setVisible(false);
        connect(advancedSyncToggle,&QCheckBox::toggled,
                advancedSyncPanel,&QWidget::setVisible);
        v->addWidget(advancedSyncToggle);
        v->addWidget(advancedSyncPanel);
        lastCaptionOffsetMs_=radioOffsetMs_->value();
        const auto updateOffsetReadout=[this](){
            if(captionOffsetReadout_) captionOffsetReadout_->setText(
                tr("Offset %1%2 ms")
                .arg(radioOffsetMs_->value()>=0?QLatin1String("+"):QString())
                .arg(radioOffsetMs_->value()));
        };
        updateOffsetReadout();
        connect(captionEarlier_,&QPushButton::clicked,this,[this](){
            radioOffsetMs_->setValue(qMax(-12000,radioOffsetMs_->value()-250));
        });
        connect(captionLater_,&QPushButton::clicked,this,[this](){
            radioOffsetMs_->setValue(qMin(12000,radioOffsetMs_->value()+250));
        });
        connect(radioOffsetMs_,QOverload<int>::of(&QSpinBox::valueChanged),
            this,[updateOffsetReadout](int){ updateOffsetReadout(); });
		connect(radioOffsetMs_,QOverload<int>::of(&QSpinBox::valueChanged),
			this,[this](int newOffset){
				QSettings saved(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
				saved.setValue(QLatin1String("captionOffsetMs"),newOffset);
				const int adjustment=newOffset-lastCaptionOffsetMs_;
				lastCaptionOffsetMs_=newOffset;
				for(auto &cue:cueQueue_) cue.dueMs+=adjustment;
			});
		syncStatus_=new QLabel(tr("Sync: requested playback cache %1 ms, "
            "unverified physical audio clock. No automatic audio restarts.")
            .arg(activePlaybackCacheMs_),lab);
		syncStatus_->setWordWrap(true);
        advancedSyncLayout->addWidget(syncStatus_);
		audioCacheProgress_=new QProgressBar(lab);
		audioCacheProgress_->setRange(0,100);
		audioCacheProgress_->setValue(0);
		audioCacheProgress_->setFormat(tr("Requested audio cache · not started"));
		audioCacheProgress_->setToolTip(tr("Estimated time since opening a stream, NOT "
			"verified buffer fill, actual DAC output clock or lip sync."));
        advancedSyncLayout->addWidget(audioCacheProgress_);
		bufferRecommendation_=new QLabel(tr("Buffer recommendation: awaiting real ASR timing"),lab);
		bufferRecommendation_->setWordWrap(true);
        advancedSyncLayout->addWidget(bufferRecommendation_);
		captionProgress_=new QProgressBar(lab);
		captionProgress_->setRange(0,100);
		captionProgress_->setValue(0);
		captionProgress_->setFormat(tr("Caption timeline · waiting for decoded audio"));
		captionProgress_->setToolTip(tr("Estimated time to hear the decoded phrase. "
			"Audio cache is requested, not independently measured at the sound card."));
        captionProgress_->setVisible(false);
        // Progress belongs next to the actual radio subtitle overlay,
        // not underneath all Model Market / language settings. Hide it
        // completely while ASR is off.
        rightLayout->addWidget(captionProgress_);
        connect(applyBuffer,&QPushButton::clicked,this,[this](){ applyRadioBuffer(); });
        connect(quickBuffer_,&QCheckBox::toggled,this,[this](bool enabled){
            quickBuffer_->setText(enabled?
                tr("Extra audio buffer · ON"):tr("Extra audio buffer · OFF"));
            if(!enabled && autoSync_->isChecked()) {
                const QSignalBlocker block(autoSync_);
                autoSync_->setChecked(false);
            }
            QSettings saved(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
            saved.setValue(QLatin1String("radioBufferEnabled"),enabled);
            saved.setValue(QLatin1String("radioAutoBufferEnabled"),autoSync_->isChecked());
            if(active() && !playingKey_.isEmpty()) applyRadioBuffer();
            else {
                activePlaybackCacheMs_=0;
                saved.setValue(QLatin1String("playbackBufferMs"),0);
            }
            refreshRadioBufferProgress();
        });
        connect(autoSync_,&QCheckBox::toggled,this,[this](bool enabled){
            QSettings saved(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
            // TV-style separation: checking ASR processing time is
            // diagnostic ONLY, never enable Extra Buffer or change its
            // chosen value. Radio sound and captions continue uninterrupted.
            saved.setValue(QLatin1String("radioAutoBufferEnabled"),enabled);
            bufferRecommendation_->setText(enabled?
                tr("ASR estimate ON · advice only; fixed audio cache/offset "
                   "unchanged. Apply buffer manually if desired."):
                tr("ASR estimate OFF · audio buffer unchanged."));
            refreshRadioBufferProgress();
        });
		auto *captionActions=new QHBoxLayout();
		captionActions->addStretch(1);
		captionActions->addWidget(caption_);
        captionActions->addWidget(applyCaptions_);
		captionActions->addWidget(stopCaption_);
		v->addLayout(captionActions);
		radioCaption_ = new QLabel(tr("Radio AI is OFF; it never starts without your request."), lab);
		radioCaption_->setTextFormat(Qt::PlainText);
		radioCaption_->setWordWrap(true);
		v->addWidget(radioCaption_);
		auto *lyricsRow = new QGridLayout();
		lyrics_ = new QPushButton(tr("Find lyrics (timed OR plain, optional online)"), lab);
		lyricsImport_=new QPushButton(tr("Import local TXT / LRC"),lab);
		lyricsImport_->setToolTip(tr("Use your own legally obtained lyric file. "
			"Plain TXT lines can be matched to audible Whisper speech; "
			"timed LRC can be rechecked against actual vocals."));
		lyricsArtist_=new QLineEdit(lab);
		lyricsArtist_->setPlaceholderText(tr("Artist correction (optional)"));
		lyricsTitle_=new QLineEdit(lab);
		lyricsTitle_->setPlaceholderText(tr("Song title correction (optional)"));
		lyricsArtist_->setMaximumWidth(240);
		lyricsTitle_->setMaximumWidth(320);
		stopLyrics_=new QPushButton(tr("Stop lyrics / listening"),lab);
		stopLyrics_->setEnabled(false);
        listenLyrics_=new QPushButton(tr("Listen & transcribe vocals offline"),lab);
        listenLyrics_->setToolTip(tr("Use the playing DAB audio with Whisper "
            "singing mode, without online metadata. Heard words are "
            "approximate, not synchronized reference lyrics."));
        listenFallbackOnMiss_=new QCheckBox(tr("On miss: listen offline"),lab);
        listenFallbackOnMiss_->setChecked(true);
        listenFallbackOnMiss_->setToolTip(tr("After an authorized lyrics search "
            "returns no matching text, fall back to local audio transcription. "
            "No radio audio is sent to online lyrics services."));
		lyricsOffset_ = new QSlider(Qt::Horizontal, lab);
		lyricsOffset_->setRange(-90000, 90000);
		lyricsOffset_->setValue(0);
        lyricsOffset_->setToolTip(tr("Manual lyric sync offset, milliseconds (-90s to +90s)."));
        mainLyricOffsetSlider_=new QSlider(Qt::Horizontal,page);
        mainLyricOffsetSlider_->setRange(-360,360); // 250 ms steps
        mainLyricOffsetSlider_->setValue(lyricsOffset_->value()/250);
        mainLyricOffsetSlider_->setMinimumWidth(150);
        mainLyricOffsetSlider_->setToolTip(tr(
            "Karaoke ONLY: 250 ms steps, ±90 s. Positive lyrics later, "
            "negative earlier. Independent of the AI caption offset. "
            "No ASR subtitle shift, no buffer change or SDR restart."));
        mainLyricOffsetReadout_=new QLabel(tr("0.00 s"),page);
        karaokePreviewSpeed_=new QSpinBox(page);
        karaokePreviewSpeed_->setRange(50,200);
        karaokePreviewSpeed_->setSingleStep(5);
        karaokePreviewSpeed_->setSuffix(tr("%"));
        QSettings karaokeSpeedPreferences(QLatin1String("TIHULU"),
                                          QLatin1String("KaffeineRadio"));
        karaokePreviewSpeed_->setValue(qBound(50,
            karaokeSpeedPreferences.value(
                QLatin1String("karaokePreviewSpeedPercent"),100).toInt(),200));
        previewPreviousSpeedPercent_=karaokePreviewSpeed_->value();
        karaokePreviewSpeed_->setToolTip(tr(
            "Legacy estimated speed is disabled: no autoplay word sweep "
            "without real Whisper audio evidence. The separate Karaoke "
            "sync history (default 10 seconds) is adjustable instead."));
        karaokePreviewSpeed_->setEnabled(false);
        connect(karaokePreviewSpeed_,QOverload<int>::of(&QSpinBox::valueChanged),
            this,[this](int percent){
                // A speed change must not multiply elapsed time since the
                // beginning of the song and skip whole Karaoke verses.
                // Preserve the current estimated playhead before applying
                // the new preview speed. No DAC alignment is claimed.
                const qint64 now=QDateTime::currentMSecsSinceEpoch();
                if(previewStartedMs_>0) {
                    const bool timed=!plainLyricMode_ && !lyricCues_.isEmpty();
                    const qint64 anchor=timed?
                        (autoLyricSync_->isChecked() && songStartMs_>0?
                            songStartMs_:manualSongStartMs_>0?
                            manualSongStartMs_:previewStartedMs_):
                        previewStartedMs_;
                    previewSpeedCompensationMs_+=qRound64(
                        (now-anchor)*(previewPreviousSpeedPercent_-percent)/100.);
                }
                previewPreviousSpeedPercent_=percent;
                QSettings prefs(QLatin1String("TIHULU"),
                                QLatin1String("KaffeineRadio"));
                prefs.setValue(QLatin1String("karaokePreviewSpeedPercent"),
                               percent);
                previewLastIndex_=-1;
                previewLastHighlightedWord_=-2;
                updateLyrics(); // refresh Karaoke independently of Reading
            });
        mainLyricOffsetRow->addWidget(new QLabel(tr("Karaoke offset (only):"),page));
        mainLyricOffsetRow->addWidget(mainLyricOffsetSlider_,1);
        mainLyricOffsetRow->addWidget(mainLyricOffsetReadout_);
        // The old speed control is obsolete: no unverified word sweep.
        karaokePreviewSpeed_->hide();
        mainLyricOffsetRow->addWidget(new QLabel(tr(
            "Karaoke sync history:"),page));
        mainLyricOffsetRow->addWidget(karaokeSyncHistorySeconds_);
        karaokeEngineStatus_=new QLabel(tr(
            "Karaoke model: checking · Qwen if available, Whisper fallback"),
            page);
        karaokeEngineStatus_->setToolTip(tr(
            "Qwen ForcedAligner improves word timing for supported "
            "languages and CONFIRMED lyric lines; cannot recognize song "
            "lines alone. Whisper speech captions are always independent."));
        mainLyricOffsetRow->addWidget(karaokeEngineStatus_);
        connect(mainLyricOffsetSlider_,&QSlider::valueChanged,
            this,[this](int n){ lyricsOffset_->setValue(n*250); });
        connect(lyricsOffset_,&QSlider::valueChanged,this,[this](int ms){
            const QSignalBlocker hold(mainLyricOffsetSlider_);
            mainLyricOffsetSlider_->setValue(ms/250);
            mainLyricOffsetReadout_->setText(
                tr("%1%2 s").arg(ms>=0?QLatin1String("+"):QString())
                .arg(QString::number(ms/1000.,'f',2)));
        });
        QSettings matchPrefs(QLatin1String("TIHULU"),
                             QLatin1String("KaffeineRadio"));
        lyricMatchThreshold_=new QSpinBox(page);
        lyricMatchThreshold_->setRange(0,100);
        lyricMatchThreshold_->setSuffix(tr(" %"));
        lyricMatchThreshold_->setValue(qBound(0,matchPrefs.value(
            QLatin1String("lyricMatchThresholdPercent"),74).toInt(),100));
        lyricMatchThreshold_->setToolTip(tr(
            "Minimum lexical overlap of heard Whisper tokens and known "
            "lyric words (0–100%). NOT calibrated accuracy or sync. "
            "0% does not auto-progress during silence; at least 2–3 actual "
            "matching distinctive words are still required. Very low "
            "thresholds can yield false Karaoke matches."));
        mainMatchRow->addWidget(new QLabel(tr("Lyrics MATCH ≥"),page));
        mainMatchRow->addWidget(lyricMatchThreshold_);
        mainMatchRow->addWidget(new QLabel(tr(
            "Whisper text similarity · not timing accuracy"),page));
        mainMatchRow->addStretch(1);
        lyricMatchMode_=new QComboBox(page);
        lyricMatchMode_->addItem(tr("Whisper · exact word overlap"),
                                 QLatin1String("lexical"));
        lyricMatchMode_->addItem(tr("Whisper · tolerant word overlap"),
                                 QLatin1String("fuzzy"));
        lyricMatchMode_->setToolTip(tr(
            "Choose how actual Whisper ASR words are compared with retrieved "
            "Lyrics. Tolerant mode accepts limited spelling differences in "
            "long words. Neither method invents audio evidence, and Qwen3 "
            "ForcedAligner only aligns word timestamps AFTER a text match."));
        const QString savedMatchMode=matchPrefs.value(
            QLatin1String("lyricMatchMode"),QLatin1String("lexical")).toString();
        const int matchIndex=lyricMatchMode_->findData(savedMatchMode);
        lyricMatchMode_->setCurrentIndex(matchIndex>=0?matchIndex:0);
        mainModelRow->addWidget(new QLabel(tr("Lyrics Match AI:"),page));
        mainModelRow->addWidget(lyricMatchMode_);
        connect(lyricMatchMode_,QOverload<int>::of(&QComboBox::currentIndexChanged),
            this,[this](int){
                QSettings prefs(QLatin1String("TIHULU"),
                                QLatin1String("KaffeineRadio"));
                prefs.setValue(QLatin1String("lyricMatchMode"),
                               lyricMatchMode_->currentData().toString());
                writeRadioLanguageControls(); // live worker, no caption restart
            });
        connect(lyricMatchThreshold_,QOverload<int>::of(&QSpinBox::valueChanged),
            this,[this](int percent){
                QSettings prefs(QLatin1String("TIHULU"),
                                QLatin1String("KaffeineRadio"));
                prefs.setValue(QLatin1String("lyricMatchThresholdPercent"),percent);
                writeRadioLanguageControls();
            });
		autoLyrics_=new QCheckBox(tr("Auto search lyrics on new DLS song"),lab);
        // Restore previously granted *metadata-only* online consent.
        // No network work starts on this UI creation. Station DLS debounce
        // triggers a lookup only for owners who enabled this previously.
        QSettings lyricConsentPrefs(QLatin1String("TIHULU"),
                                   QLatin1String("KaffeineRadio"));
        autoLyrics_->setChecked(lyricConsentPrefs.value(
            QLatin1String("lyricsOnlineOptIn"),false).toBool());
		autoLyrics_->setToolTip(tr("OFF by default. When enabled, the current radio DLS "
			"artist/title is sent to LRCLIB on each new song. No audio or private RF data are uploaded."));
		connect(autoLyrics_,&QCheckBox::toggled,this,[this](bool enabled){
            if(enabled && active() && !playingKey_.isEmpty() &&
               !lyricLoaded_ && !lastSongMetadataKey_.isEmpty() &&
               pendingSongKey_.isEmpty() &&
               lyricsProcess_.state()==QProcess::NotRunning)
                QTimer::singleShot(100,this,[this](){
                    if(autoLyrics_->isChecked() && !lyricLoaded_) {
                        // This toggle is an explicit request to retry the
                        // current song; it may override the 90s automatic
                        // provider cooldown once, not loop in background.
                        lyricsLookupCooldownUntilMs_=0;
                        fetchLyrics(true);
                    }
                });
            else if(!enabled && !lastSongMetadataKey_.isEmpty() && !lyricLoaded_)
                setRadioLyricMatchStatus(tr(
                    "DLS SONG DETECTED · automatic online lyrics OFF · "
                    "enable Auto search or use Lyrics Refresh"));
        });
		autoLyricSync_=new QCheckBox(tr("Auto lyric timing (DLS estimate)"),lab);
		autoLyricSync_->setChecked(true);
		autoLyricSync_->setToolTip(tr("Use song metadata change and requested audio "
			"buffer as an estimated timeline, not a verified sound-card timebase."));
		preferLyrics_=new QCheckBox(tr("Prefer matched lyrics / hide uncertain sung words"),lab);
		preferLyrics_->setChecked(true);
        preferLyrics_->setToolTip(tr(
            "Prefer actual retrieved and audio-matched lyric lines. "
            "Unverified sung words are not invented or shown as [music] "
            "in the on-screen radio caption. Presenter speech is unaffected."));
        lyricsSourceLanguage_=new QComboBox(lab);
        lyricsSourceLanguage_->addItem(
            tr("Auto · wait for confirmed sung audio language"),QLatin1String("auto"));
        const QStringList lyricSources={"de","en","tr","fr","es","it","pl","ar","ja","pt"};
        for(const QString &lang:lyricSources)
            lyricsSourceLanguage_->addItem(lang.toUpper(),lang);
        lyricsSourceLanguage_->setToolTip(tr(
            "Independent song lyric language. Explicitly choose it for immediate "
            "translation of retrieved lyrics; Auto never reuses an unverified "
            "presenter's language for the singer."));
		lyricsOffsetValue_=new QLabel(tr("Offset: +0.00 s"),lab);
		lyricsOffsetValue_->setMinimumWidth(120);
		lyricsOffsetValue_->setToolTip(tr("Signed manual correction in seconds "
			"(+ delays lyrics; - displays earlier)."));
		lyricsSyncState_=new QLabel(tr("Audio lyric sync: no verified vocal match"),lab);
		lyricsSyncState_->setWordWrap(true);
		connect(lyricsOffset_,&QSlider::valueChanged,this,[this](int value){
			lyricsOffsetValue_->setText(
				tr("Offset: %1%2 s").arg(value>=0?QLatin1String("+"):QString())
				.arg(QString::number(value/1000.,'f',2)));
			const int delta=value-lastLyricOffsetMs_;
			lastLyricOffsetMs_=value;
			for(auto &cue:plainLyricQueue_) cue.dueMs+=delta;
            for(auto &cue:verifiedLyricQueue_) cue.dueMs+=delta;
		});
		lyricsRow->addWidget(lyrics_,0,0);
		lyricsRow->addWidget(stopLyrics_,0,1);
		radioPlaybackRow_->insertWidget(2,autoLyrics_);
        autoLyrics_->setText(tr("Auto lyrics · online opt-in"));
        karaokeEnabled_=new QCheckBox(tr("Karaoke · blue screen"),page);
        karaokeTranslationsEnabled_=new QCheckBox(
            tr("Lyrics translations · yellow"),page);
        QSettings lyricDisplaySettings(QLatin1String("TIHULU"),
                                       QLatin1String("KaffeineRadio"));
        karaokeEnabled_->setChecked(lyricDisplaySettings.value(
            QLatin1String("karaokeDisplayEnabled"),true).toBool());
        karaokeTranslationsEnabled_->setChecked(lyricDisplaySettings.value(
            QLatin1String("karaokeTranslationsEnabled"),true).toBool());
        karaokeEnabled_->setToolTip(tr(
            "AUDIO-MATCHED song lines in the big blue station panel. "
            "The normal Whisper/translated subtitles stay independently "
            "in the bottom caption bar."));
        karaokeTranslationsEnabled_->setToolTip(tr(
            "Show existing lyric translations in yellow under the active "
            "karaoke line. OFF hides only these duplicates, not the "
            "normal bottom subtitles."));
        radioPlaybackRow_->insertWidget(3,karaokeEnabled_);
        radioPlaybackRow_->insertWidget(4,karaokeTranslationsEnabled_);
        karaokePolicy_=new QComboBox(page);
        karaokePolicy_->addItem(tr("Karaoke · Audio matched"),"verified");
        karaokePolicy_->addItem(tr("Karaoke · Lyrics found (preview)"),"found");
        karaokePolicy_->addItem(tr("Karaoke · Lyrics found + lip-sync (audio gated)"),"found-sync");
        karaokePolicy_->addItem(tr("Karaoke · Timed LRC flow (estimated)"),"estimated");
        karaokePolicy_->setToolTip(tr(
            "Audio matched: use actually heard Whisper lyrics + installed "
            "Qwen word timing where supported. Lyrics Found: static preview. "
            "Lyrics Found + lip-sync: acoustic evidence required to move. "
            "Timed LRC flow: opt-in estimated LINE flow based only on REAL "
            "source timestamps (never guessed 6-second lines or word sweeps); "
            "DLS song clock can be late, manual offset may be needed. "
            "No timed LRC means no estimated flow. Whisper presenter speech "
            "and translations remain independent below."));
        const QString savedPolicy=lyricDisplaySettings.value(
            QLatin1String("karaokeMatchPolicy"),
            QLatin1String("verified")).toString();
        const int policyIndex=karaokePolicy_->findData(savedPolicy);
        karaokePolicy_->setCurrentIndex(policyIndex<0?0:policyIndex);
        mainMatchRow->addWidget(new QLabel(tr("Karaoke trigger:"),page));
        mainMatchRow->addWidget(karaokePolicy_);
        karaokeAligner_=new QComboBox(page);
        karaokeAligner_->addItem(tr("Auto · Qwen3 → Whisper"),
                                QLatin1String("auto"));
        karaokeAligner_->addItem(tr("Whisper word timing"),
                                QLatin1String("whisper"));
        karaokeAligner_->addItem(tr("Qwen3 ForcedAligner (Whisper fallback)"),
                                QLatin1String("qwen"));
        karaokeAligner_->setToolTip(tr(
            "Word timing engine for the selected Karaoke trigger mode. "
            "Preference is saved separately per trigger mode. Qwen3 "
            "ForcedAligner cannot identify singing or select lyric lines: "
            "it needs audio-matched text, compatible language and installed "
            "weights; otherwise Whisper word timestamps are used. "
            "Lyrics Found preview and Timed LRC flow do not fabricate word sync."));
        const auto loadModeAligner=[this](){
            QSettings prefs(QLatin1String("TIHULU"),
                            QLatin1String("KaffeineRadio"));
            const QString mode=karaokePolicy_->currentData().toString();
            const QString engine=prefs.value(
                QLatin1String("karaokeAligner_")+mode,
                QLatin1String("auto")).toString();
            const int index=karaokeAligner_->findData(engine);
            const QSignalBlocker block(karaokeAligner_);
            karaokeAligner_->setCurrentIndex(index>=0?index:0);
            writeRadioLanguageControls();
        };
        mainModelRow->addWidget(new QLabel(tr("Karaoke timing AI (per trigger):"),page));
        mainModelRow->addWidget(karaokeAligner_);
        mainModelRow->addStretch(1);
        loadModeAligner();
        connect(karaokeAligner_,QOverload<int>::of(
            &QComboBox::currentIndexChanged),this,[this](int){
                QSettings prefs(QLatin1String("TIHULU"),
                                QLatin1String("KaffeineRadio"));
                const QString mode=karaokePolicy_->currentData().toString();
                prefs.setValue(QLatin1String("karaokeAligner_")+mode,
                               karaokeAligner_->currentData().toString());
                writeRadioLanguageControls();
        });
        fullLyricsButton_=new QPushButton(tr("Full Lyrics"),page);
        fullLyricsButton_->setToolTip(tr(
            "Show all currently loaded lyrics in a separate resizable window, "
            "with real source and available translations. No online search."));
        mainMatchRow->addWidget(fullLyricsButton_);
        lyricsRefresh_=new QPushButton(tr("Lyrics Refresh"),page);
        lyricsRefresh_->setToolTip(tr(
            "Explicitly re-search current song lyrics after consent. Bypass "
            "cache, retain current Karaoke during lookup, and never discard "
            "good lyrics when online search fails."));
        mainMatchRow->addWidget(lyricsRefresh_);
        connect(fullLyricsButton_,&QPushButton::clicked,this,
                [this](){showFullLyricsWindow();});
        connect(lyricsRefresh_,&QPushButton::clicked,this,
                [this](){refreshCurrentLyrics();});
        previewPrevious_=new QPushButton(tr("◀ Lyric"),page);
        previewNext_=new QPushButton(tr("Lyric ▶"),page);
        previewPrevious_->setToolTip(tr(
            "Manually move the UNVERIFIED lyric preview one line back."));
        previewNext_->setToolTip(tr(
            "Manually move the UNVERIFIED lyric preview one line forward."));
        mainMatchRow->addWidget(previewPrevious_);
        mainMatchRow->addWidget(previewNext_);
        const auto updatePreviewControls=[this](){
            const QString policy=karaokePolicy_->currentData().toString();
            const bool active=policy==QLatin1String("found") ||
                policy==QLatin1String("found-sync") ||
                (policy==QLatin1String("estimated") && lyricCues_.isEmpty());
            previewPrevious_->setVisible(active);
            previewNext_->setVisible(active);
        };
        updatePreviewControls();
        connect(karaokePolicy_,QOverload<int>::of(&QComboBox::currentIndexChanged),
            this,[this,updatePreviewControls,loadModeAligner](int){
                QSettings prefs(QLatin1String("TIHULU"),
                                QLatin1String("KaffeineRadio"));
                prefs.setValue(QLatin1String("karaokeMatchPolicy"),
                               karaokePolicy_->currentData().toString());
                previewIndexShift_=0;
                clearKaraokeLine();
                updatePreviewControls();
                loadModeAligner();
                if(karaokePolicy_->currentData().toString()==
                   QLatin1String("estimated") && lyricCues_.isEmpty() &&
                   lyricsSyncState_)
                    lyricsSyncState_->setText(tr(
                        "Timed LRC needs real timestamps. Plain lyrics: choose "
                        "Audio matched or Lyrics Found; Whisper speech continues."));
                updateLyrics(); // switching mode never restarts the radio
            });
        connect(previewPrevious_,&QPushButton::clicked,this,[this](){
            const QString policy=karaokePolicy_->currentData().toString();
            if(policy!=QLatin1String("found") &&
               policy!=QLatin1String("found-sync") &&
               !(policy==QLatin1String("estimated") && lyricCues_.isEmpty()))
               return;
            previewIndexShift_=qMax(-200,previewIndexShift_-1);
            previewLastIndex_=-1;
            updateLyrics();
        });
        connect(previewNext_,&QPushButton::clicked,this,[this](){
            const QString policy=karaokePolicy_->currentData().toString();
            if(policy!=QLatin1String("found") &&
               policy!=QLatin1String("found-sync")) return;
            previewIndexShift_=qMin(200,previewIndexShift_+1);
            previewLastIndex_=-1;
            updateLyrics();
        });
        soundLabels_=new QCheckBox(tr("Sound labels · [Music] / [Humming] / [Applause]"),page);
        soundLabels_->setChecked(lyricDisplaySettings.value(
            QLatin1String("radioSoundLabelsEnabled"),false).toBool());
        soundLabels_->setToolTip(tr(
            "Optional INSTALLED local AST AudioSet model classifies music, "
            "humming and applause; labels are shown beside, not instead of, "
            "Whisper words. OFF by default. If model is missing, no guessed "
            "labels or downloads; speech still transcribes normally."));
        radioPlaybackRow_->insertWidget(5,soundLabels_);
        connect(soundLabels_,&QCheckBox::toggled,this,[this](bool enabled){
            QSettings prefs(QLatin1String("TIHULU"),
                            QLatin1String("KaffeineRadio"));
            prefs.setValue(QLatin1String("radioSoundLabelsEnabled"),enabled);
            writeRadioLanguageControls(); // next ASR window; no radio restart
            if(enabled && radioCaptionBanner_) radioCaptionBanner_->setText(tr(
                "Optional local sound labels requested · independent from "
                "Whisper. No audio-classifier model is downloaded."));
        });
        connect(karaokeEnabled_,&QCheckBox::toggled,this,[this](bool enabled){
            QSettings prefs(QLatin1String("TIHULU"),
                            QLatin1String("KaffeineRadio"));
            prefs.setValue(QLatin1String("karaokeDisplayEnabled"),enabled);
            writeRadioLanguageControls(); // live vocal mode only when user opted in
            if(karaokePanel_) karaokePanel_->setVisible(enabled &&
                lastKaraokeUntilMs_>QDateTime::currentMSecsSinceEpoch() &&
                karaokeCurrent_ && !karaokeCurrent_->text().isEmpty());
            if(enabled) updateLyrics();
        });
        connect(karaokeTranslationsEnabled_,&QCheckBox::toggled,
            this,[this](bool enabled){
                QSettings prefs(QLatin1String("TIHULU"),
                                QLatin1String("KaffeineRadio"));
                prefs.setValue(QLatin1String("karaokeTranslationsEnabled"),
                               enabled);
                if(karaokeTranslation_)
                    karaokeTranslation_->setVisible(enabled &&
                        !karaokeTranslation_->text().isEmpty());
            });
        lyricsRow->addWidget(listenLyrics_,5,0,1,2);
        lyricsRow->addWidget(listenFallbackOnMiss_,5,2);
		lyricsRow->addWidget(autoLyricSync_,1,0,1,2);
		lyricsRow->addWidget(new QLabel(tr("Lyric timing:"), lab),1,2);
		lyricsRow->addWidget(lyricsOffset_,2,0,1,2);
		lyricsRow->addWidget(lyricsOffsetValue_,2,2);
		lyricsRow->addWidget(lyricsImport_,3,0);
		lyricsRow->addWidget(lyricsArtist_,3,1);
		lyricsRow->addWidget(lyricsTitle_,3,2);
        lyricsRow->addWidget(new QLabel(tr("Song lyric language:"),lab),4,0);
        lyricsRow->addWidget(lyricsSourceLanguage_,4,1,1,2);
		lyricsRow->setColumnStretch(1,1);
        v->addWidget(new QLabel(tr(
            "<b>3 · Lyrics</b> · optional; no search until you choose Find lyrics"),lab));
        auto *quickLyrics=new QPushButton(tr("Find lyrics for current song"),lab);
        v->addWidget(quickLyrics);
        auto *fullLyricsInOptions=new QPushButton(
            tr("Full Lyrics · separate window"),lab);
        v->addWidget(fullLyricsInOptions);
        connect(fullLyricsInOptions,&QPushButton::clicked,this,
                [this](){showFullLyricsWindow();});
        // Regional catalogs without a licensed retrieval API are discovery
        // links only: no scraping, automated extraction or caching of lyrics.
        // A click sends ONLY the user-visible artist/title query to browser.
        auto *regionalLyrics=new QHBoxLayout();
        auto addRegional=[this,lab,regionalLyrics](
                const QString &label,const QString &site){
            auto *button=new QPushButton(label,lab);
            button->setToolTip(tr(
                "Open a browser search on %1 for current DLS artist/title. "
                "No lyrics are copied automatically; import only a locally "
                "authorized TXT/LRC file.").arg(site));
            connect(button,&QPushButton::clicked,this,[this,site](){
                const TihuluDlsSong song=lastAcceptedSongHint_;
                const QString artist=lyricsArtist_->text().trimmed().isEmpty()?
                    song.artist:lyricsArtist_->text().trimmed();
                const QString title=lyricsTitle_->text().trimmed().isEmpty()?
                    song.title:lyricsTitle_->text().trimmed();
                if(artist.isEmpty() || title.isEmpty()) {
                    lyricText_->setText(tr(
                        "Choose a song or fill Artist and Title before opening a catalog."));
                    return;
                }
                QUrl url(QLatin1String("https://www.google.com/search"));
                QUrlQuery query;
                query.addQueryItem(QLatin1String("q"),
                    QLatin1String("site:")+site+QLatin1Char(' ')+
                    artist+QLatin1Char(' ')+title+QLatin1String(" lyrics"));
                url.setQuery(query);
                QDesktopServices::openUrl(url);
            });
            regionalLyrics->addWidget(button);
        };
        addRegional(tr("Global · Genius"),QLatin1String("genius.com"));
        addRegional(tr("DE · SoundChapter"),QLatin1String("soundchapter.com"));
        addRegional(tr("DE · Liedertexte"),QLatin1String("liedertexte.com"));
        addRegional(tr("TR · Müzik Sözleri"),QLatin1String("muziksozleri.com.tr"));
        addRegional(tr("TR · Söz Müzik"),QLatin1String("sarki.sozmuzik.net"));
        v->addLayout(regionalLyrics);
        auto *regionalInfo=new QLabel(tr(
            "Regional sites open as browser searches only (copyright/licence). "
            "Automatic in-app lyrics: LRCLIB, lyrics.ovh, official Musixmatch "
            "with your licensed API key. TXT/LRC import remains available."),lab);
        regionalInfo->setWordWrap(true);
        v->addWidget(regionalInfo);
        auto *showLyricsOptions=new QCheckBox(
            tr("Advanced · lyrics source, timing, import and auto search"),lab);
        showLyricsOptions->setChecked(false);
        // A quick lookup must expose Stop lyrics while it is active.
        connect(quickLyrics,&QPushButton::clicked,this,[this,showLyricsOptions](){
            showLyricsOptions->setChecked(true);
            fetchLyrics();
        });
        v->addWidget(showLyricsOptions);
        auto *lyricsPanel=new QWidget(lab);
        auto *lyricsLayout=new QVBoxLayout(lyricsPanel);
        lyricsLayout->setContentsMargins(0,2,0,2);
        lyricsLayout->addLayout(lyricsRow);
        lyricsLayout->addWidget(lyricsSyncState_);
        lyricsLayout->addWidget(preferLyrics_);
        lyricsPanel->setVisible(false);
        connect(showLyricsOptions,&QCheckBox::toggled,
                lyricsPanel,&QWidget::setVisible);
        v->addWidget(lyricsPanel);
        lyricProvider_=new QLabel(tr("Sources: LRCLIB; lyrics.ovh; optional "
            "licensed Musixmatch API. Plain text must match heard audio."),lab);
        lyricProvider_->setWordWrap(true);
        lyricProvider_->setTextFormat(Qt::PlainText);
        v->addWidget(lyricProvider_);
		lyricText_ = new QLabel(tr("No synchronized lyrics loaded."), lab);
		lyricText_->setTextFormat(Qt::PlainText);
		lyricText_->setWordWrap(true);
		v->addWidget(lyricText_);
		modes_->addTab(lab,tr("AI subtitles / lyrics"));
        connect(quickLanguageButton_,&QPushButton::clicked,this,[this,lab](){
            modes_->setCurrentWidget(lab);
            installedTargets_->setFocus();
        });
        refreshRadioLanguageSummary();

		auto *diagnosticCard = new QGroupBox(tr("DAB receiver diagnostics / welle.io"),this);
		auto *diagnosticLayout=new QVBoxLayout(diagnosticCard);
		auto *diagnostics = new QGridLayout();
		plotKind_ = new QComboBox(this);
		plotKind_->addItem(tr("Spectrum"), "spectrum");
		plotKind_->addItem(tr("Waterfall"), "waterfall");
		plotKind_->addItem(tr("Null spectrum"), "nullspectrum");
		plotKind_->addItem(tr("CIR / impulse response"), "impulseresponse");
		plotKind_->addItem(tr("Constellation phase"), "constellation");
		fftPlacement_ = new QComboBox(this);
		fftPlacement_->addItem(tr("FFT earliest"),QLatin1String("EarliestPeakWithBinning"));
		fftPlacement_->addItem(tr("FFT strongest"),QLatin1String("StrongestPeak"));
		fftPlacement_->addItem(tr("FFT threshold"),QLatin1String("ThresholdBeforePeak"));
		fftPlacement_->setToolTip(tr("Original welle.io FFT synchronization placement; "
			"changes are applied only on explicit click."));
		coarseCorrector_ = new QCheckBox(tr("Coarse correction"),this);
		coarseCorrector_->setChecked(true);
		coarseCorrector_->setToolTip(tr("Toggle welle.io coarse frequency corrector "
			"using the local receiver only."));
		plot_ = new QLabel(tr("On-demand RF plots"), this);
		plot_->setMinimumSize(200,110);
        plot_->setMaximumHeight(110);
        plot_->setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Fixed);
		plot_->setAlignment(Qt::AlignCenter);
		plot_->setStyleSheet(QLatin1String("border:1px solid #456;"));
		auto *plotButton = new QPushButton(tr("Capture RF plot"), this);
		livePlot_=new QCheckBox(tr("Live RF"),this);
		livePlot_->setToolTip(tr("Update spectrum/waterfall every 1.6 seconds while enabled"));
		showWidgets_=new QCheckBox(tr("Show welle.io RF widgets"),this);
		showWidgets_->setChecked(false);
		multiRf_=new QCheckBox(tr("Multi-widget live RF dashboard"),this);
		multiRf_->setChecked(false);
		multiRf_->setToolTip(tr("Rotate real welle.io receiver samples across spectrum, "
			"waterfall and constellation without blocking the GUI. "
			"Requires DAB SDR; does not show invented values."));
		auto *detailsButton = new QPushButton(tr("Receiver / TII details"),this);
		auto *applyRf = new QPushButton(tr("Apply RF options"),this);
		diagnostics->addWidget(plotKind_,0,0);
        diagnostics->addWidget(plotButton,0,1);
        diagnostics->addWidget(livePlot_,0,2);
        diagnostics->addWidget(plot_,1,0,1,3);
        diagnostics->setColumnStretch(0,1);
		diagnosticLayout->addLayout(diagnostics);
		diagnosticLayout->addWidget(multiRf_);
		multiPanel_=new QWidget(diagnosticCard);
		auto *multiGrid=new QGridLayout(multiPanel_);
		const QStringList kinds={tr("Live spectrum"),tr("Live waterfall"),
			tr("Live constellation")};
		for(int i=0;i<3;++i) {
			auto *frame=new QWidget(multiPanel_);
			auto *column=new QVBoxLayout(frame);
			column->setContentsMargins(2,2,2,2);
			column->addWidget(new QLabel(kinds[i],frame));
			auto *image=new QLabel(tr("Waiting for real RF samples"),frame);
			image->setMinimumSize(180,110);
            image->setMaximumHeight(110);
            image->setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Fixed);
			image->setAlignment(Qt::AlignCenter);
			image->setStyleSheet(QLatin1String("border:1px solid #456;"));
			column->addWidget(image);
			multiPlots_.append(image);
			multiGrid->addWidget(frame,i/2,i%2);
		}
		multiPanel_->setVisible(false);
		diagnosticLayout->addWidget(multiPanel_);
		auto *rfOptions=new QGridLayout();
		rfOptions->addWidget(fftPlacement_,0,0);
        rfOptions->addWidget(coarseCorrector_,0,1);
        rfOptions->addWidget(applyRf,1,0);
        rfOptions->addWidget(detailsButton,1,1);
        rfOptions->setColumnStretch(0,1);
		diagnosticLayout->addLayout(rfOptions);
        auto *rfPage=new QWidget(modes_);
        auto *rfLayout=new QVBoxLayout(rfPage);
        rfLayout->setContentsMargins(5,5,5,5);
        rfLayout->addWidget(showWidgets_);
        rfLayout->addWidget(diagnosticCard);
        modes_->addTab(rfPage,tr("RF Lab · advanced"));
		diagnosticCard->setVisible(false);
		connect(showWidgets_,&QCheckBox::toggled,diagnosticCard,&QWidget::setVisible);
		connect(multiRf_,&QCheckBox::toggled,this,[this](bool enabled){
			multiPanel_->setVisible(enabled);
			if(enabled) {
				showWidgets_->setChecked(true);
				livePlot_->setChecked(true);
			}
			if(enabled) rfTick_.start();
			else rfTick_.stop();
		});

		connect(start_, &QPushButton::clicked, this, [this](){ startReceiver(); });
        connect(stop_, &QPushButton::clicked, this, [this](){ stopRadioListening(); });
        connect(radioOutputVolume_,&QSlider::valueChanged,player_,&MediaWidget::setVolume);
        connect(radioMuteButton_,&QPushButton::clicked,player_,&MediaWidget::toggleMuted);
        connect(radioReconnectAudio_,&QPushButton::clicked,this,[this](){retryDabAudioPlayback();});
        connect(radioAudioDiagnostics_,&QPushButton::clicked,this,[this](){showRadioAudioDiagnostics();});
        connect(forceRelease_,&QPushButton::clicked,this,[this](){
            stopReceiver();
            state_->setText(active()?
                tr("Radio Stop requested, but welle-cli has not exited; "
                   "the SDR may still be in use. Check the receiver PID."):
                tr("Radio stopped · TIHULU released its DAB receiver. "
                   "Other applications may now claim the device."));
            updateReceiverOwnership();
        });
        connect(releaseOnStop_,&QCheckBox::toggled,this,[this](bool enabled){
            QSettings settings(QLatin1String("TIHULU"),
                               QLatin1String("KaffeineRadio"));
            settings.setValue(QLatin1String("releaseSdrOnStop"),enabled);
            updateReceiverOwnership();
        });
		connect(record_, &QPushButton::clicked, this, [this](){ toggleRecording(); });
		connect(&recordAi_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
			this,[this](int result,QProcess::ExitStatus status){
				const QString srt=QFileInfo(recordedPath_).absolutePath()+QLatin1Char('/')+
					QFileInfo(recordedPath_).completeBaseName()+QLatin1String(".srt");
				if(result!=0 || status!=QProcess::NormalExit || !QFileInfo(srt).isFile()){
					state_->setText(tr("Recording preserved, offline SRT failed: %1")
						.arg(QString::fromUtf8(recordAi_.readAllStandardError()).right(180)));
					return;
				}
				const QString output=QFileInfo(recordedPath_).absolutePath()+QLatin1Char('/')+
					QFileInfo(recordedPath_).completeBaseName()+QLatin1String("-subtitled.mkv");
				if(QFileInfo(output).exists()) {
					state_->setText(tr("SRT saved; subtitled MKV destination already exists. "
						"Existing files will not be overwritten."));
					return;
				}
				recordMux_.start(QLatin1String("ffmpeg"),
					{QLatin1String("-nostdin"),QLatin1String("-hide_banner"),
					 QLatin1String("-loglevel"),QLatin1String("error"),
					 QLatin1String("-n"),QLatin1String("-i"),recordedPath_,
					 QLatin1String("-i"),srt,
					 QLatin1String("-map"),QLatin1String("0:a:0"),
					 QLatin1String("-map"),QLatin1String("1:0"),
					 QLatin1String("-c:a"),QLatin1String("copy"),
					 QLatin1String("-c:s"),QLatin1String("srt"),output});
				state_->setText(tr("Offline SRT generated; creating MKV with subtitle track…"));
			});
		connect(&recordMux_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
			this,[this](int result,QProcess::ExitStatus status){
				state_->setText(result==0 && status==QProcess::NormalExit?
					tr("Subtitled recording complete. Audio, SRT and MKV saved.") :
					tr("Recorded audio and SRT saved; MKV mux failed (check FFmpeg)."));
			});
		connect(scan_, &QPushButton::clicked, this, [this](){ beginScan(); });
		connect(webSearchButton_, &QPushButton::clicked, this, [this](){ searchInternetRadio(); });
		connect(webCountry_,QOverload<int>::of(&QComboBox::activated),
			this,[this](int){
				QSettings saved(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
				saved.setValue(QLatin1String("webCountry"),webCountry_->currentData());
				searchInternetRadio();
			});
		connect(webSearch_, &QLineEdit::returnPressed, this, [this](){ searchInternetRadio(); });
		connect(webPlay_, &QPushButton::clicked, this, [this](){ playInternetRadio(webSource_->text()); });
		connect(webProbeButton_, &QPushButton::clicked, this,[this](){probeInternetRadio();});
		connect(webAlternate_,&QPushButton::clicked,this,[this](){
			QTreeWidgetItem *current=webStations_->currentItem();
			if(!current) { webStatus_->setText(tr("Choose a directory station first."));return; }
			const QString fallback=current->data(1,Qt::UserRole+1).toString();
			const QUrl url(fallback);
			if(!url.isValid() || url.host().isEmpty() ||
			   (url.scheme()!=QLatin1String("http") &&
			    url.scheme()!=QLatin1String("https")) ||
			   fallback==current->data(1,Qt::UserRole).toString()) {
				webStatus_->setText(tr("No different valid alternate station URL."));
				return;
			}
			webSource_->setText(fallback);
			playInternetRadio(fallback);
			webStatus_->setText(tr("Trying original directory URL. "
				"Use Test stream to inspect its decoder/audio availability."));
		});
		connect(&internetProbe_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
			this,[this](int code,QProcess::ExitStatus status){
				webProbeButton_->setEnabled(true);
				if(webSource_->text().trimmed()!=testedWebUrl_) return;
				const QByteArray bytes=internetProbe_.readAllStandardOutput();
				const QJsonDocument doc=QJsonDocument::fromJson(bytes);
				QStringList audioCodecs;
				for(const auto &entry:doc.object().value(QLatin1String("streams")).toArray()){
					const auto stream=entry.toObject();
					if(stream.value(QLatin1String("codec_type")).toString()!=QLatin1String("audio")) continue;
					const QString codec=stream.value(QLatin1String("codec_name")).toString();
					if(!codec.isEmpty()) audioCodecs<<codec;
				}
				if(code==0 && status==QProcess::NormalExit && !audioCodecs.isEmpty()) {
					webStatus_->setText(tr("URL provides audio codecs: %1. "
						"FFprobe succeeded, but live VLC playback still depends on station availability.")
						.arg(audioCodecs.join(QLatin1String(", "))));
				} else {
					const QString problem=QString::fromLocal8Bit(
						internetProbe_.readAllStandardError()).right(260);
					webStatus_->setText(tr("Station stream could not be decoded: %1")
						.arg(problem.isEmpty()?tr("timeout / no audio stream"):problem));
				}
			});
		connect(webSource_, &QLineEdit::returnPressed, this, [this](){ playInternetRadio(webSource_->text()); });
		connect(webStop_, &QPushButton::clicked, this, [this](){ stopInternetRadio(); });
		connect(webStations_, &QTreeWidget::itemDoubleClicked, this,
			[this](QTreeWidgetItem *item, int column) {
				if (column != 0 && item)
					playInternetRadio(item->data(1,Qt::UserRole).toString());
			});
		connect(webStations_, &QTreeWidget::itemClicked, this,
			[this](QTreeWidgetItem *item, int column) {
				if (column == 0 && item) toggleInternetFavorite(item);
				else if (item) {
                    webSource_->setText(item->data(1,Qt::UserRole).toString());
                    showSelectedSource(item->text(1),tr("Internet radio · selected"),
                        tr("Internet stream · no FM frequency"));
                }
			});
		connect(webFavoritesOnly_, &QCheckBox::toggled, this,
			[this](){ filterInternetStations(); });
		QSettings webSettings(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
		for (const QString &url : webSettings.value(QLatin1String("internetFavorites")).toStringList())
			internetFavorites_.insert(url);
		connect(stations_, &QTreeWidget::itemDoubleClicked, this,
			[this](QTreeWidgetItem *item, int column){
				if (column!=0) selectStation(item);
			});
		connect(stations_, &QTreeWidget::itemClicked, this,
			[this](QTreeWidgetItem *item, int column){
				if(!item)return;
                if(column==0)toggleFavorite(item);
                else showSelectedSource(item->text(1),tr("DAB+ · selected"),
                    tr("Block %1 · %2 · SID %3 · double-click to tune")
                        .arg(item->text(2),dabCenterFrequencyMHz(item->text(2)),
                             item->text(3)));
			});
		connect(stationSearch_, &QLineEdit::textChanged,this,
			[this](){ filterStations(); });
		connect(libraryBlock_,QOverload<int>::of(&QComboBox::currentIndexChanged),
			this,[this](){ filterStations(); });
		connect(favoritesOnly_,&QCheckBox::toggled,this,
			[this](){ filterStations(); });
        connect(stationListPicker_,QOverload<int>::of(
            &QComboBox::currentIndexChanged),this,
            [this](int){ filterStations(); });
        connect(stationListOnly_,&QCheckBox::toggled,this,
            [this](bool){ filterStations(); });
        connect(newStationList_,&QPushButton::clicked,this,
            [this](){ createNamedStationList(); });
        connect(deleteStationList_,&QPushButton::clicked,this,
            [this](){ deleteNamedStationList(); });
        connect(addStationList_,&QPushButton::clicked,this,
            [this](){ changeSelectedStationList(true); });
        connect(removeStationList_,&QPushButton::clicked,this,
            [this](){ changeSelectedStationList(false); });
        // User overrides remain sticky across subsequent AI ON/OFF cycles.
        // The master toggle may enable local features, never silently opt a
        // person into third-party lyric lookups or switch a cloud provider on.
        auto rememberAuto=[this](QCheckBox *check,const char *name){
            connect(check,&QCheckBox::clicked,this,[name](bool on){
                QSettings prefs(QLatin1String("TIHULU"),
                                QLatin1String("KaffeineRadio"));
                prefs.setValue(QLatin1String(name),on);
            });
        };
        rememberAuto(quickTranslate_,"radioAiAutoTranslate");
        rememberAuto(quickBuffer_,"radioAiAutoBuffer");
        rememberAuto(autoSync_,"radioAiAutoSync");
        rememberAuto(karaokeEnabled_,"radioAiAutoKaraoke");
        rememberAuto(karaokeTranslationsEnabled_,"radioAiAutoKaraokeTranslations");
        connect(autoLyrics_,&QCheckBox::clicked,this,[](bool allowed){
            QSettings prefs(QLatin1String("TIHULU"),
                            QLatin1String("KaffeineRadio"));
            prefs.setValue(QLatin1String("lyricsOnlineOptIn"),allowed);
        });
        connect(quickTranslate_,&QCheckBox::toggled,this,[this](bool enabled){
            QSettings prefs(QLatin1String("TIHULU"),
                            QLatin1String("KaffeineRadio"));
            prefs.setValue(QLatin1String("radioTranslationOptIn"),enabled);
            quickTranslate_->setText(enabled?
                tr("Radio translate · ON"):tr("Radio translate · OFF"));
            if(captionProcess_.state()!=QProcess::NotRunning)
                writeRadioLanguageControls();
            if(radioTranslationBanner_) {
                radioTranslationBanner_->setText(enabled?
                    tr("Offline translation requested · checking local model "
                       "and selected OUT languages on next audio chunk"):
                    tr("Radio-only translation OFF · global AI Market "
                       "setting still applies"));
                radioTranslationBanner_->setVisible(true);
            }
        });
        connect(captionRefresh_,&QPushButton::clicked,this,[this](){
            if(!quickAi_->isChecked() || playingKey_.isEmpty()) {
                radioCaptionBanner_->setText(tr(
                    "Select a DAB station and enable AI Captions before refresh."));
                return;
            }
            stopCaptioning();
            cueQueue_.clear();
            plainLyricQueue_.clear();
            verifiedLyricQueue_.clear();
            lastRadioChunk_=-1;
            lastRadioRevision_=-1;
            displayedRadioChunk_=-1;
            lastDetectedLanguage_.clear();
            lastCaptionUpdateMs_=0;
            lastCaptionVisibleMs_=0;
            if(radioCanvasCaption_) radioCanvasCaption_->clear();
            startCaptioning(); // re-read shared AI settings, no RF retune
            radioCaptionBanner_->setText(tr(
                "Radio ASR refreshed · waiting for new captured audio; "
                "DAB playback, Lyrics consent and manual offsets retained."));
        });
        connect(aiSyncRefresh_,&QPushButton::clicked,
                this,[this](){refreshRadioCaptionLipSync();});
        connect(radioSyncRefresh_,&QPushButton::clicked,
                this,[this](){refreshRadioLipSync();});
		connect(quickAi_,&QCheckBox::toggled,this,[this](bool enabled){
            quickAi_->setText(enabled?tr("AI captions · ON"):tr("AI captions · OFF"));
            if(enabled) {
                QSettings prefs(QLatin1String("TIHULU"),
                                QLatin1String("KaffeineRadio"));
                if(prefs.value(QLatin1String("radioAiAutoTranslate"),true).toBool())
                    quickTranslate_->setChecked(true);
                // Starting AI captions NEVER toggles Auto Size or Extra
                // Buffer. TV likewise keeps playback controls separate
                // from Whisper worker lifecycle.
                if(prefs.value(QLatin1String("radioAiAutoKaraoke"),true).toBool())
                    karaokeEnabled_->setChecked(true);
                if(prefs.value(QLatin1String("radioAiAutoKaraokeTranslations"),true).toBool())
                    karaokeTranslationsEnabled_->setChecked(true);
                // AI captions mean real audio transcription. An earlier
                // metadata-only DLS selection must NOT make AI ON look
                // enabled while no Whisper worker exists until Karaoke
                // later changes the source back to ASR.
                if(captionSource_ &&
                   captionSource_->currentData().toString()==
                       QLatin1String("dls")) {
                    const int asr=captionSource_->findData(QLatin1String("asr"));
                    if(asr>=0) {
                        const QSignalBlocker block(captionSource_);
                        captionSource_->setCurrentIndex(asr);
                    }
                }
                // Just as with TV, establish the independent Whisper
                // audio worker BEFORE any optional Lyrics consent prompt.
                // Slow lookups, karaoke matches and metadata are not
                // prerequisites for the first spoken subtitle.
                if(active() && !playingKey_.isEmpty()) startCaptioning();
                else radioCaptionBanner_->setText(tr(
                    "AI armed for the next station. No speech processing "
                    "until a DAB station is playing."));
                // Online metadata is shared with external providers only
                // after one informed user click/consent.
                bool onlineConsent=prefs.value(
                    QLatin1String("lyricsOnlineOptIn"),false).toBool();
                if(!onlineConsent && !prefs.value(
                        QLatin1String("lyricsOnlineConsentAsked"),false).toBool()) {
                    onlineConsent=(QMessageBox::question(this,
                        tr("Enable automatic online song lyrics?"),
                        tr("When AI captions is ON, send station DLS song "
                           "artist/title (never radio audio) to LRCLIB, "
                           "lyrics.ovh and optional licensed Musixmatch? "
                           "Offline Whisper still works if you decline."))==
                        QMessageBox::Yes);
                    prefs.setValue(QLatin1String("lyricsOnlineConsentAsked"),true);
                    prefs.setValue(QLatin1String("lyricsOnlineOptIn"),onlineConsent);
                }
                if(onlineConsent) {
                    autoLyrics_->setChecked(true);
                    // Existing DLS should be searched on AI activation too.
                    if(!lastSongMetadataKey_.isEmpty() &&
                       pendingSongKey_.isEmpty() && !lyricLoaded_ &&
                       lyricsProcess_.state()==QProcess::NotRunning)
                        QTimer::singleShot(100,this,[this](){
                            if(autoLyrics_->isChecked() && !lyricLoaded_)
                                fetchLyrics(true);
                        });
                }
                setRadioLyricMatchStatus(tr(
                    "KARAOKE · AI ON · waiting for verified lyrics / Whisper"));
            } else {
                stopCaptioning();
                if(captionProgress_) captionProgress_->setVisible(false);
                radioCaptionBanner_->setText(tr("Live radio AI OFF · audio only"));
                // Disable only the automatic search behaviour; keep user's
                // stored consent, lists, Karaoke and buffer preferences.
                const QSignalBlocker block(autoLyrics_);
                autoLyrics_->setChecked(false);
                if(karaokePanel_) karaokePanel_->setVisible(false);
            }
        });
        connect(caption_, &QPushButton::clicked, this, [this](){
            if(!quickAi_->isChecked()) quickAi_->setChecked(true);
            else startCaptioning();
        });
        connect(applyCaptions_,&QPushButton::clicked,this,[this](){
            if(!quickAi_->isChecked()) {
                radioCaption_->setText(tr("AI is OFF. Choose Start captions "
                    "or enable the AI switch first."));
                return;
            }
            if(captionProcess_.state()!=QProcess::NotRunning) stopCaptioning();
            cueQueue_.clear();
            lastRadioChunk_=-1; lastRadioRevision_=-1;
            displayedRadioChunk_=-1;
            startCaptioning();
            radioCaptionBanner_->setText(tr("Applying local caption options; "
                "waiting for a new real audio segment…"));
        });
		connect(stopCaption_, &QPushButton::clicked, this, [this](){
            const QSignalBlocker block(quickAi_);
            quickAi_->setChecked(false);
            quickAi_->setText(tr("AI captions · OFF"));
            const bool lyricOnly=lyricsAudioFallbackActive_;
            if(lyricOnly) {
                lyricsAudioFallbackActive_=false;
                lyricsFallbackStartedAi_=false;
                lyricText_->setText(tr("Offline lyric listening stopped."));
            }
            stopCaptioning();
            radioCaptionBanner_->setText(tr("Live radio captions stopped."));
            lastCaptionVisibleMs_=0;
        });
        connect(&captionProcess_,QOverload<int,QProcess::ExitStatus>::of(
            &QProcess::finished),this,
            [this](int code,QProcess::ExitStatus exitState){
                if(captionsStopping_ || shuttingDown_ || tvHandoffInProgress_)
                    return;
                if(!quickAi_ || !quickAi_->isChecked()) return;
                // An AI HTTP client EOF is not a user OFF request. Preserve
                // the requested ON state and recover ONLY the caption worker.
                // Never retune the SDR or restart libVLC/radio audio.
                const QString stderrText=QString::fromLocal8Bit(
                    captionProcess_.readAllStandardError()).right(190);
                if(captionProgress_) {
                    captionProgress_->setVisible(true);
                    captionProgress_->setRange(0,100);
                    captionProgress_->setValue(0);
                    captionProgress_->setFormat(tr(
                        "AI captions ON · recovering local Whisper input"));
                }
                const QString reason=code==0 &&
                    exitState==QProcess::NormalExit?
                    tr("audio reader reached EOF"):tr("Whisper/FFmpeg exited");
                if(radioCaptionBanner_) {
                    radioCaptionBanner_->setText(tr(
                        "AI captions ON · %1 · retrying local ASR only. %2")
                        .arg(reason,stderrText));
                    radioCaptionBanner_->setVisible(true);
                }
                if(lyricsAudioFallbackActive_ && lyricText_)
                    lyricText_->setText(tr(
                        "Whisper reconnecting · Karaoke lyrics remain loaded."));
                scheduleCaptionRecovery();
            });
        connect(&captionProcess_,&QProcess::errorOccurred,this,
            [this](QProcess::ProcessError){
                if(captionsStopping_ || shuttingDown_ || !quickAi_ ||
                   !quickAi_->isChecked()) return;
                // FailedToStart may never emit finished: periodic tick
                // checks this same deadline. Do not spin in errorOccurred.
                scheduleCaptionRecovery();
            });

		connect(lyrics_, &QPushButton::clicked, this, [this](){ fetchLyrics(); });
		connect(lyricsImport_,&QPushButton::clicked,this,[this](){
			const QString path=QFileDialog::getOpenFileName(
				this,tr("Import your plain text or timed song lyrics"),QString(),
				tr("Lyric files (*.txt *.lrc)"));
			if(path.isEmpty()) return;
			stopLyrics();
            lyricsRequestKey_.clear(); // imports never poison online cache
			const QString runtime=QStandardPaths::writableLocation(
				QStandardPaths::RuntimeLocation);
			if(runtime.isEmpty()) {
				lyricText_->setText(tr("Cannot import: private runtime directory missing."));
				return;
			}
			lyricPath_=runtime+QLatin1String("/tihulu-radio-lyrics-")+
				QString::number(QCoreApplication::applicationPid())+QLatin1String(".json");
			QFile::remove(lyricPath_);
			lyricsEnabled_=true;
			lyricLoaded_=false;
			lyricsProcess_.start(QLatin1String("tihulu-tv-center"),{
				QLatin1String("lyrics-import"),QLatin1String("--file"),path,
				QLatin1String("--output"),lyricPath_});
			if(!lyricsProcess_.waitForStarted(900)) {
				lyricsEnabled_=false;
				lyricText_->setText(tr("Local lyrics companion failed to start."));
				return;
			}
			lyrics_->setEnabled(false);
			stopLyrics_->setEnabled(true);
			lyricText_->setText(tr("Importing plain TXT / timed LRC; no network lookup."));
		});
		connect(stopLyrics_, &QPushButton::clicked, this, [this](){ stopLyrics(); });
        connect(listenLyrics_,&QPushButton::clicked,this,[this](){
            beginLyricListening();
        });
		connect(slidePrev_,&QPushButton::clicked,this,[this](){slideMove(-1);});
		connect(slideNext_,&QPushButton::clicked,this,[this](){slideMove(1);});
		connect(plotButton, &QPushButton::clicked, this, [this](){ fetchPlot(); });
		connect(applyRf, &QPushButton::clicked, this, [this](){ applyRfOptions(); });
		connect(detailsButton, &QPushButton::clicked, this, [this](){ showReceiverDetails(); });
		connect(&backend_, &QProcess::readyReadStandardError, this, [this]() {
            const QString tail=QString::fromUtf8(backend_.readAllStandardError());
            if(!tail.trimmed().isEmpty()) lastWelleError_=tail.trimmed().right(600);
            const bool busy=tail.contains(QLatin1String("busy"),Qt::CaseInsensitive) ||
                tail.contains(QLatin1String("No device"),Qt::CaseInsensitive) ||
                tail.contains(QLatin1String("usb_claim"),Qt::CaseInsensitive) ||
                tail.contains(QLatin1String("Failed to open"),Qt::CaseInsensitive);
            if(busy) state_->setText(tr("DAB RTL-SDR not accessible · %1")
                .arg(apiFailureDetails()));
            else if(tail.contains(QLatin1String("Cannot")) ||
                    tail.contains(QLatin1String("Failed")))
                state_->setText(tail.right(250));
        });
        connect(&backend_,&QProcess::errorOccurred,this,[this](QProcess::ProcessError){
            lastWelleError_=backend_.errorString().right(600);
            if(!shuttingDown_) state_->setText(
                tr("welle-cli process failure: %1 · no RF measurement")
                .arg(lastWelleError_));
        });
		connect(&backend_, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished),
			this, [this](int exitCode, QProcess::ExitStatus){
                if(!shuttingDown_)
                    lastWelleError_=tr("welle-cli exited (%1) · %2")
                        .arg(exitCode).arg(lastWelleError_).right(600);
				stopCaptioning();
				tick_.stop();
                apiReady_=false;
                scanning_=false;
                scan_->setEnabled(true);
                scanProgress_->setValue(0);
                scanProgress_->setFormat(tr("Scan stopped: receiver exited"));
                scanSNR_->setValue(0);
                scanSNR_->setFormat(tr("DAB SNR NOT MEASURED · welle-cli exited"));
                rfQuality_->setValue(0);
                rfQuality_->setFormat(tr("DAB RF unmeasured · receiver exited"));
                lastMux_=QJsonObject();
                dabPlaybackObserved_=false;
                dabIdleSinceMs_=0;
                updateReceiverOwnership();
				if (!shuttingDown_) state_->setText(tr("welle-cli stopped (%1): %2")
                    .arg(exitCode).arg(lastWelleError_));
			});
		tick_.setInterval(1400);
		// Audio captions no longer wait for the expensive 1600-ms RF poll.
		captionTick_.setInterval(
            radioReadingPreset_ && radioReadingPreset_->currentData().toInt()==0
                ?150:300);
		connect(&captionTick_,&QTimer::timeout,this,[this](){
            monitorRadioPlaybackStop();
            checkCaptionRecovery();
			pollCaption();updateLyrics();
            pollLyricsRefreshResult();
            refreshRadioBufferProgress();
		});
		captionTick_.start();
		rfTick_.setInterval(300);
		connect(&rfTick_,&QTimer::timeout,this,[this](){
			if(!active() || plotPending_) return;
			if(multiRf_->isChecked() && multiPlots_.size()==3) {
				const QStringList kinds={
					QLatin1String("spectrum"),QLatin1String("waterfall"),
					QLatin1String("constellation")};
				const int index=(multiRfIndex_++)%3;
				fetchPlot(kinds[index],multiPlots_.at(index));
			} else if(livePlot_->isChecked()) {
				fetchPlot();
			}
		});
		connect(livePlot_,&QCheckBox::toggled,this,[this](bool enabled){
			if(enabled || multiRf_->isChecked()) rfTick_.start();
			else rfTick_.stop();
		});
		connect(&tick_, &QTimer::timeout, this, [this](){pollMux();});
        QSettings uiSettings(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
        modes_->setCurrentIndex(qBound(0,uiSettings.value(
            QLatin1String("radioModeTab"),0).toInt(),modes_->count()-1));
        connect(modes_,&QTabWidget::currentChanged,this,[](int tab){
            QSettings config(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
            config.setValue(QLatin1String("radioModeTab"),tab);
        });
		loadStations();
        loadStationLists();
		stations_->sortItems(1,Qt::AscendingOrder);
		filterStations();
	}

	~TihuluRadioTab() override { stopReceiver(); }

	void activate() override {
		// Never move the shared video MediaWidget into this radio panel.
		radioCanvas_->setFocus();
		if(!languagePacksLoaded_) {
			languagePacksLoaded_=true;
			QTimer::singleShot(0,this,[this](){refreshLanguagePacks();});
		}
		if(!webCatalogRequested_) {
			webCatalogRequested_=true;
			QSettings saved(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
			const QString preference=saved.value(QLatin1String("webCountry")).toString();
			const int index=webCountry_->findData(preference);
			webCountry_->setCurrentIndex(index>=0?index:0);
			QTimer::singleShot(100,this,[this](){searchInternetRadio();});
		}
	}

protected:
    void resizeEvent(QResizeEvent *event) override {
        TabBase::resizeEvent(event);
        if(stationSplit_)
            stationSplit_->setOrientation(width()<930?Qt::Vertical:Qt::Horizontal);
    }
public:
    // Native hardware operations stop only processes owned by this tab.
    // Never unbind USB drivers or terminate unrelated SDR applications.
    bool hardwareDabOwned() const {
        return backend_.state()!=QProcess::NotRunning;
    }
    bool hardwareAnalogOwned() const {
        return analogServer_.isListening() ||
               analogDemod_.state()!=QProcess::NotRunning;
    }
    QString hardwareDabStatus() const {
        const QString error=lastWelleError_.isEmpty()?
            tr("No receiver error captured"):lastWelleError_.right(230);
        if(backend_.state()==QProcess::NotRunning)
            return tr("RELEASED · welle-cli stopped. Last diagnostic: %1").arg(error);
        if(!apiReady_)
            return tr("STARTING / DEGRADED · welle-cli PID %1; loopback API not ready. %2")
                .arg(backend_.processId()).arg(error);
        return tr("ACTIVE · welle-cli PID %1, DAB %2, localhost API port %3%4")
            .arg(backend_.processId()).arg(activeChannel_).arg(port_)
            .arg(scanning_?tr(" · scanning"):QString());
    }
    QString hardwareAnalogStatus() const {
        const QString error=lastAnalogError_.isEmpty()?
            tr("No rtl_fm error captured"):lastAnalogError_.right(230);
        if(analogDemod_.state()==QProcess::NotRunning)
            return tr("RELEASED / FAILED · rtl_fm not running. %1").arg(error);
        return tr("ACTIVE · rtl_fm PID %1 · %2 Hz · local audio endpoint %3")
            .arg(analogDemod_.processId())
            .arg(qRound64(analogFrequency_->value()*
                 (analogBand_->currentData().toString()==QLatin1String("fm")?1000000.:1000.)))
            .arg(analogServer_.isListening()?tr("ready"):tr("not listening"));
    }
    // Shared libVLC and receiver ownership must be settled before native
    // Television takes over playback. Merely changing Qt tabs leaves
    // welle-cli / RTL-SDR and delayed station callbacks alive.
    // This never touches the DVB-T2 frontend or another application's SDR.
    bool releaseForTelevision() {
        if(tvHandoffInProgress_) return false;
        tvHandoffInProgress_=true;
        const bool hadOwnedSdr=hardwareDabOwned() || hardwareAnalogOwned();
        const bool hadAudio=!playingKey_.isEmpty() || webPlaying_;
        const bool hadWork=scanning_ || captionProcess_.state()!=QProcess::NotRunning;
        if(hadOwnedSdr || hadAudio || hadWork) {
            // Invalidate old welle HTTP replies and station timers before
            // any new DVB request can take the shared MediaWidget.
            ++stationRequestId_;
            ++scanRequestId_;
            stopReceiver();
        }
        const bool released=!hardwareDabOwned() && !hardwareAnalogOwned();
        if(!released && state_)
            state_->setText(tr(
                "TV handoff blocked: TIHULU radio SDR not released. "
                "Use Release SDR now; no DVB tuner was claimed by this method."));
        else if(state_) state_->setText(tr(
            "TV handoff: radio processes and shared audio stopped; "
            "SDR released by TIHULU. DVB-T2 remains independently managed."));
        tvHandoffInProgress_=false;
        return released;
    }
    void hardwareStartDab() { startReceiver(); }
    void hardwareStopDab() { stopReceiver(); }
    void hardwareStartAnalog() { startAnalog(); }
    void hardwareStopAnalog() { stopAnalog(); }

private:
	struct TimedRadioCue {
        int chunkIndex;
        qint64 dueMs;
        qint64 queuedMs;
        QString text;
        // Original estimated presentation timestamp, before the user offset.
        // No change to the device clock or current speaker's DAC.
        qint64 unoffsetDueMs;
        int requestedCacheAtQueueMs;
        TimedRadioCue(int chunk,qint64 due,qint64 queued,
                      const QString &value,qint64 unoffset=0,int cache=-1)
            : chunkIndex(chunk),dueMs(due),queuedMs(queued),text(value),
              unoffsetDueMs(unoffset),requestedCacheAtQueueMs(cache) {}
    };
    struct TimedPlainLyric {
        qint64 dueMs;
        QString text;
        double confidence;
        int lineIndex;
        QString original;
        QJsonObject translations;
        QJsonArray wordAnchors;
        // Qt5/C++11 builds do not treat a struct with default member
        // initializers as an aggregate. Accept old 3-field cues as well
        // as newer 6-field verified karaoke cues.
        TimedPlainLyric(qint64 due,const QString &rendered,double certainty,
                        int index=-1,const QString &source=QString(),
                        const QJsonObject &translated=QJsonObject(),
                        const QJsonArray &alignedWords=QJsonArray())
            : dueMs(due),text(rendered),confidence(certainty),
              lineIndex(index),original(source),translations(translated),
              wordAnchors(alignedWords) {}
    };
    struct RecentKaraokeEvidence {
        qint64 receivedMs;
        QString stationKey;
        QString songKey;
        TimedPlainLyric cue;
        RecentKaraokeEvidence(qint64 seen,const QString &station,
                              const QString &song,
                              const TimedPlainLyric &matched)
            : receivedMs(seen),stationKey(station),songKey(song),
              cue(matched) {}
    };
	static QString label(const QJsonValue &value) {
		if (value.isString()) return value.toString();
		if (value.isObject()) return value.toObject().value(QLatin1String("label")).toString();
		return QString();
	}
	QString base() const {
		return QLatin1String("http://127.0.0.1:") + QString::number(port_);
	}
	QString binaryPath() const {
		return QDir::homePath() + QLatin1String("/.local/opt/tihulu-welle/bin/welle-cli");
	}
	bool prepared() const {
		return QFile::exists(binaryPath()) &&
			QFile::exists(QDir::homePath() +
			  QLatin1String("/.local/opt/tihulu-welle/.tihulu-loopback-welle-revision"));
	}
	bool active() const { return backend_.state() == QProcess::Running; }

	void filterInternetStations() {
		if (!webStations_) return;
		for (int i=0;i<webStations_->topLevelItemCount();++i) {
			auto *item=webStations_->topLevelItem(i);
			const QString url=item->data(1,Qt::UserRole).toString();
			item->setHidden(webFavoritesOnly_->isChecked() &&
				!internetFavorites_.contains(url));
		}
	}
	void toggleInternetFavorite(QTreeWidgetItem *item) {
		const QString url=item->data(1,Qt::UserRole).toString();
		if (url.isEmpty()) return;
		if (internetFavorites_.contains(url)) internetFavorites_.remove(url);
		else internetFavorites_.insert(url);
		item->setText(0,internetFavorites_.contains(url)?QStringLiteral("★"):QStringLiteral("☆"));
		QSettings settings(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
		settings.setValue(QLatin1String("internetFavorites"),QStringList(internetFavorites_.values()));
		filterInternetStations();
	}
	void searchInternetRadio() {
		const QString name=webSearch_->text().trimmed();
		QString country=webCountry_->currentData().toString();
		const QString typed=webCountry_->currentText().trimmed();
		const QString selected=webCountry_->itemText(webCountry_->currentIndex());
		if(typed!=selected) {
			if(QRegularExpression(QLatin1String("^[a-zA-Z]{2}$")).match(typed).hasMatch())
				country=typed.toUpper();
			else {
				const int selectedIndex=webCountry_->findText(typed,Qt::MatchExactly);
				if(selectedIndex>=0) country=webCountry_->itemData(selectedIndex).toString();
				else {
					webStatus_->setText(tr("Choose a country from the list, "
						"or type its two-letter ISO code."));
					return;
				}
			}
		}
		QUrl url(QLatin1String("https://de1.api.radio-browser.info/json/stations/search"));
		QUrlQuery query;
		if (!name.isEmpty()) query.addQueryItem(QLatin1String("name"),name.left(90));
		if (!country.isEmpty()) query.addQueryItem(QLatin1String("countrycode"),country);
		query.addQueryItem(QLatin1String("hidebroken"),QLatin1String("true"));
		query.addQueryItem(QLatin1String("order"),QLatin1String("votes"));
		query.addQueryItem(QLatin1String("reverse"),QLatin1String("true"));
		query.addQueryItem(QLatin1String("limit"),QLatin1String("120"));
		url.setQuery(query);
		QNetworkRequest request(url);
		request.setRawHeader("User-Agent","TIHULU-Media-Center/0.2 (desktop; station discovery)");
		request.setTransferTimeout(15000);
		webSearchButton_->setEnabled(false);
		webStatus_->setText(tr("Searching the online station directory…"));
		QNetworkReply *reply=network_.get(request);
		connect(reply,&QNetworkReply::finished,this,[this,reply]() {
			webSearchButton_->setEnabled(true);
			const QByteArray data=reply->readAll();
			const bool ok=reply->error()==QNetworkReply::NoError && data.size()<2*1024*1024;
			const QString error=reply->errorString();
			reply->deleteLater();
			if (!ok) { webStatus_->setText(tr("Online search failed: %1").arg(error)); return; }
			QJsonParseError parsed;
			const QJsonDocument doc=QJsonDocument::fromJson(data,&parsed);
			if (parsed.error!=QJsonParseError::NoError || !doc.isArray()) {
				webStatus_->setText(tr("Invalid station directory response.")); return;
			}
			webStations_->clear();
			for(const QJsonValue &value:doc.array()) {
				const QJsonObject station=value.toObject();
				const QString link=station.value(QLatin1String("url_resolved")).toString();
				const QUrl stream(link);
				if (!stream.isValid() || !stream.host().size() ||
				    (stream.scheme()!=QLatin1String("http") && stream.scheme()!=QLatin1String("https")))
					continue;
				const QString name=station.value(QLatin1String("name")).toString().trimmed();
				if (name.isEmpty()) continue;
				const QString country=station.value(QLatin1String("countrycode")).toString();
				const QString codec=station.value(QLatin1String("codec")).toString();
				auto *item=new QTreeWidgetItem(webStations_);
				item->setText(0,internetFavorites_.contains(link)?QStringLiteral("★"):QStringLiteral("☆"));
				item->setText(1,name.left(120));
				item->setText(2,country);
				item->setText(3,codec);
				item->setData(1,Qt::UserRole,link);
				const QUrl originalUrl(station.value(QLatin1String("url")).toString());
				if(originalUrl.isValid() && !originalUrl.host().isEmpty() &&
				  (originalUrl.scheme()==QLatin1String("http") ||
				   originalUrl.scheme()==QLatin1String("https")))
					item->setData(1,Qt::UserRole+1,originalUrl.toString());
			}
			filterInternetStations();
			webStatus_->setText(tr("%1 real stations discovered. Double-click to play; click ★ to save.")
				.arg(webStations_->topLevelItemCount()));
		});
	}
    void refreshRadioLanguageSummary() {
        if(!quickLanguageButton_ || !speechLanguage_) return;
        const QStringList langs=selectedRadioTargets();
        const QString source=speechLanguage_->currentData().toString();
        quickLanguageButton_->setText(tr("IN: %1 · OUT: %2 · Edit")
            .arg(source.isEmpty()?tr("AUTO"):source.toUpper(),
                 langs.isEmpty()?tr("none"):langs.join(
                     QLatin1String(", ")).toUpper()));
    }
    bool writeRadioLanguageControls() {
        if(captionControlsPath_.isEmpty() || !speechLanguage_) return false;
        QJsonArray targets;
        for(const QString &code:selectedRadioTargets()) targets.append(code);
        const QString source=speechLanguage_->currentData().isValid()?
            speechLanguage_->currentData().toString():
            speechLanguage_->currentText().trimmed().toLower();
        const QJsonDocument document(QJsonObject{
            {QStringLiteral("source"),source},
            {QStringLiteral("targets"),targets},
            {QStringLiteral("radio_translations"),
             quickTranslate_ && quickTranslate_->isChecked()},
            {QStringLiteral("karaoke_enabled"),
             karaokeEnabled_ && karaokeEnabled_->isChecked()},
            {QStringLiteral("lyric_match_threshold"),
             lyricMatchThreshold_?lyricMatchThreshold_->value()/100.:0.74},
            {QStringLiteral("lyric_match_mode"),
             lyricMatchMode_?lyricMatchMode_->currentData().toString():
                              QLatin1String("lexical")},
            {QStringLiteral("karaoke_aligner"),
             karaokeAligner_?karaokeAligner_->currentData().toString():
                              QLatin1String("auto")},
            {QStringLiteral("karaoke_sync_refresh_token"),
             karaokeSyncRefreshToken_},
            {QStringLiteral("karaoke_sync_history_seconds"),
             karaokeSyncHistorySeconds_?karaokeSyncHistorySeconds_->value():10},
            {QStringLiteral("sound_labels"),
             soundLabels_ && soundLabels_->isChecked()}});
        QSaveFile file(captionControlsPath_);
        if(!file.open(QIODevice::WriteOnly)) {
            if(translationStatus_) translationStatus_->setText(tr(
                "Live radio language preferences could not be written. "
                "Check your private runtime directory."));
            return false;
        }
        if(file.write(document.toJson(QJsonDocument::Compact))<0 ||
           !file.commit()) {
            if(translationStatus_) translationStatus_->setText(tr(
                "Language changes were NOT applied; keep previous worker settings."));
            return false;
        }
        return true;
    }
    QStringList selectedRadioTargets() const {
        // One output selection for live ASR, recorded SRT and lyric lookup.
        // No hidden legacy checkboxes or duplicated language paths.
        QStringList codes;
        if(installedTargets_->count()==0) {
            QSettings preferences(QLatin1String("TIHULU"),
                                 QLatin1String("KaffeineRadio"));
            codes=preferences.value(QLatin1String("radioOutputs"),
                QStringList{QLatin1String("en"),QLatin1String("de"),
                            QLatin1String("tr")}).toStringList();
        } else {
            for(int i=0;i<installedTargets_->count();++i) {
                const QListWidgetItem *item=installedTargets_->item(i);
                if(item->checkState()==Qt::Checked)
                    codes<<item->data(Qt::UserRole).toString();
            }
        }
        if(advancedLanguages_->isChecked()) {
            for(const QString &part:extraTargets_->text().split(
                QLatin1Char(','),Qt::SkipEmptyParts))
                codes<<part.trimmed().toLower();
        }
        QStringList unique;
        const QRegularExpression code(QLatin1String("^[a-z]{2,3}$"));
        for(const QString &candidate:codes)
            if(code.match(candidate).hasMatch() && !unique.contains(candidate)
                    && unique.size()<6)
                unique<<candidate;
        return unique;
    }
	void refreshLanguagePacks() {
		if(languagePackWorker_.state()!=QProcess::NotRunning) return;
		refreshTargets_->setEnabled(false);
		languagePackWorker_.start(QLatin1String("tihulu-tv-center"),
			{QLatin1String("ai-radio-languages")});
		if(!languagePackWorker_.waitForStarted(1000)) {
			refreshTargets_->setEnabled(true);
			translationStatus_->setText(tr(
                "AI companion not installed; radio language catalog unavailable."));
		}
	}
	void configureAnalogBand() {
		const QString band=analogBand_->currentData().toString();
		const bool fm=band==QLatin1String("fm");
		const bool mw=band==QLatin1String("mw");
		const QSignalBlocker blockFreq(analogFrequency_);
		const QSignalBlocker blockDial(analogDial_);
		analogFrequency_->setDecimals(fm?2:0);
		analogFrequency_->setRange(fm?87.5:(mw?531:150),fm?108:(mw?1602:280));
		analogFrequency_->setSuffix(fm?tr(" MHz"):tr(" kHz"));
		analogFrequency_->setSingleStep(fm?0.1:(mw?9:1));
		analogDial_->setRange(fm?8750:(mw?53100:15000),
			fm?10800:(mw?160200:28000));
		analogFrequency_->setValue(fm?99.2:(mw?999:198));
		analogDial_->setValue(qRound(analogFrequency_->value()*100));
		analogDigital_->setText(QString::number(analogFrequency_->value(),'f',fm?2:0)+
			analogFrequency_->suffix());
		analogScale_->updateFrequency(analogFrequency_->minimum(),
			analogFrequency_->maximum(),analogFrequency_->value(),
			analogBand_->currentText());
		directSampling_->setEnabled(!fm);
		if(analogServer_.isListening()) analogRetune_.start();
	}
	static QByteArray analogWavHeader() {
		QByteArray wav(44,'\0');
		auto put16=[&wav](int i,quint16 value){
			wav[i]=char(value&255);wav[i+1]=char((value>>8)&255);
		};
		auto put32=[&wav](int i,quint32 value){
			for(int p=0;p<4;++p) wav[i+p]=char((value>>(8*p))&255);
		};
		memcpy(wav.data(),"RIFF",4);put32(4,0x7fffffffu);
		memcpy(wav.data()+8,"WAVEfmt ",8);put32(16,16);
		put16(20,1); // PCM, mono 48 kHz signed 16-bit
		put16(22,1);put32(24,48000);put32(28,96000);
		put16(32,2);put16(34,16);
		memcpy(wav.data()+36,"data",4);put32(40,0x7fffffffu-36);
		return wav;
	}
	void prepareAnalogLocalStream() {
		if(analogSocketsWired_) return;
		analogSocketsWired_=true;
		connect(&analogServer_,&QTcpServer::newConnection,this,[this](){
			while(analogServer_.hasPendingConnections()) {
				QTcpSocket *socket=analogServer_.nextPendingConnection();
				// One browser/player + one recorder. The bounded third slot
				// supports a graceful reconnect without evicting playback.
				if(analogSockets_.size()>=3) {
					socket->disconnectFromHost();
					socket->deleteLater();
					continue;
				}
				analogSockets_.insert(socket);
				analogRequests_.insert(socket,QByteArray());
				connect(socket,&QTcpSocket::readyRead,this,[this,socket](){
					const QByteArray request=socket->readAll();
					if(!analogSockets_.contains(socket) || analogStreaming_.contains(socket))
						return;
					QByteArray &pending=analogRequests_[socket];
					pending+=request;
					if(pending.size()>4096) {
						socket->disconnectFromHost();return;
					}
					if(!pending.contains("\r\n\r\n"))return;
					if(!pending.startsWith("GET /analog.wav ")) {
						socket->disconnectFromHost();return;
					}
					QByteArray response("HTTP/1.1 200 OK\r\n"
						"Content-Type: audio/wav\r\n"
						"Cache-Control: no-store\r\n"
						"Connection: keep-alive\r\n\r\n");
					response+=analogWavHeader();
					socket->write(response);
					analogRequests_.remove(socket);
					analogStreaming_.insert(socket);
				});
				connect(socket,&QTcpSocket::disconnected,this,[this,socket](){
					analogSockets_.remove(socket);
					analogStreaming_.remove(socket);
					analogRequests_.remove(socket);
					socket->deleteLater();
				});
			}
		});
		connect(&analogDemod_,&QProcess::readyReadStandardOutput,this,[this](){
			const QByteArray pcm=analogDemod_.readAllStandardOutput();
			const qint64 now=QDateTime::currentMSecsSinceEpoch();
			if(analogAudioVu_ && now-lastAnalogVuUpdateMs_>=170 && pcm.size()>200) {
				lastAnalogVuUpdateMs_=now;
				double squared=0.;
				int sampled=0;
				for(int i=0;i+1<pcm.size();i+=32) {
					const quint16 raw=quint16(quint8(pcm.at(i))) |
						(quint16(quint8(pcm.at(i+1)))<<8);
					const double level=double(qint16(raw))/32768.;
					squared+=level*level;
					++sampled;
				}
				if(sampled>0) {
					const double db=20*std::log10(qMax(1e-6,std::sqrt(squared/sampled)));
					analogAudioVu_->setValue(qBound(0,qRound((db+60.)*100./60.),100));
					analogAudioVu_->setFormat(tr("Audio VU %1 dBFS · audio, NOT RF strength")
						.arg(db,0,'f',1));
				}
			}
			// Share exactly the same PCM samples with VLC and FFmpeg;
			// recording must never steal or restart the analog receiver.
			for(QTcpSocket *socket : analogStreaming_) {
				if(socket && socket->state()==QAbstractSocket::ConnectedState) {
					if(socket->bytesToWrite()<262144) socket->write(pcm);
					else socket->disconnectFromHost(); // bounded backpressure
				}
			}
		});
	}
	void retuneAnalogDemod() {
		if(!analogServer_.isListening()) return;
		analogRetune_.stop();
		const QString band=analogBand_->currentData().toString();
		const bool fm=band==QLatin1String("fm");
		if(!fm && !directSampling_->isChecked()) {
			analogStatus_->setText(tr("MW/LW require compatible direct-sampling hardware "
				"or an external upconverter."));
			return;
		}
		analogStopping_=true;
		if(analogDemod_.state()!=QProcess::NotRunning) {
			analogDemod_.terminate();
			if(!analogDemod_.waitForFinished(500)) analogDemod_.kill();
		}
		analogDemod_.readAllStandardOutput();
		analogStopping_=false;
		const quint64 hz=qRound64(analogFrequency_->value()*(fm?1000000.:1000.));
		QStringList args{QLatin1String("-M"),fm?QLatin1String("wbfm"):
			QLatin1String("am"),QLatin1String("-f"),QString::number(hz),
			QLatin1String("-s"),fm?QLatin1String("170000"):QLatin1String("48000"),
			QLatin1String("-r"),QLatin1String("48000")};
		if(!fm && directSampling_->isChecked())
			args<<QLatin1String("-D")<<QLatin1String("2");
		analogDemod_.start(QLatin1String("rtl_fm"),args);
		if(!analogDemod_.waitForStarted(1000)) {
			analogStatus_->setText(tr("RTL-SDR retune failed; device disconnected or busy."));
			return;
		}
		analogStatus_->setText(tr("Live analog frequency %1 Hz · volume/mute through "
			"TIHULU player · RF retune briefly interrupts decoding.").arg(hz));
        analogPlaybackObserved_=false;
        analogIdleSinceMs_=0;
        updateReceiverOwnership();
	}
	void stopAnalog() {
		analogRetune_.stop();
		const bool wasPlaying=analogServer_.isListening();
		analogStopping_=true;
		if(analogDemod_.state()!=QProcess::NotRunning) {
			analogDemod_.terminate();
			if(!analogDemod_.waitForFinished(850)) analogDemod_.kill();
		}
		for(QTcpSocket *client : analogSockets_) {
			if(client)client->disconnectFromHost();
		}
		analogSockets_.clear();
		analogStreaming_.clear();
		analogRequests_.clear();
		analogServer_.close();
		if(analogAudioVu_) {
			analogAudioVu_->setValue(0);
			analogAudioVu_->setFormat(tr("Audio VU: stopped (not RF strength)"));
		}
		if(wasPlaying) { player_->stop(); audioStartedMs_=0; }
        analogPlaybackObserved_=false;
        analogIdleSinceMs_=0;
		if(analogStatus_) analogStatus_->setText(tr("Analogue SDR released."));
        updateReceiverOwnership();
	}
	void startAnalog() {
		if(QStandardPaths::findExecutable(QLatin1String("rtl_fm")).isEmpty()) {
			analogStatus_->setText(tr("Optional rtl-sdr package missing. Install it to tune."));
			return;
		}
		if(analogBand_->currentData().toString()!=QLatin1String("fm") &&
		   !directSampling_->isChecked()) {
			analogStatus_->setText(tr("MW/LW need compatible direct sampling or upconverter."));
			return;
		}
		if(analogServer_.isListening()) {
			retuneAnalogDemod();
			return;
		}
		stopReceiver();
		stopAnalog();
		prepareAnalogLocalStream();
		if(!analogServer_.listen(QHostAddress::LocalHost,0)) {
			analogStatus_->setText(tr("Could not bind private local analog stream server."));
			return;
		}
		// Reuse Kaffeine/libVLC's own audio sink so the main player volume,
		// mute and audio-device selection work, unlike the former aplay fork.
		retuneAnalogDemod();
		audioStartedMs_=QDateTime::currentMSecsSinceEpoch();
		player_->play(QUrl(QLatin1String("http://127.0.0.1:")+
			QString::number(analogServer_.serverPort())+QLatin1String("/analog.wav")));
	}
	void probeInternetRadio() {
		if(internetProbe_.state()!=QProcess::NotRunning) return;
		const QUrl url=QUrl::fromUserInput(webSource_->text().trimmed());
		if(!url.isValid() || url.host().isEmpty() ||
			(url.scheme()!=QLatin1String("http") && url.scheme()!=QLatin1String("https"))) {
			webStatus_->setText(tr("Select an HTTP(S) station before testing."));return;
		}
		testedWebUrl_=webSource_->text().trimmed();
		webProbeButton_->setEnabled(false);
		webStatus_->setText(tr("Testing stream via FFprobe (timeout 8 seconds)…"));
		internetProbe_.start(QLatin1String("ffprobe"),{
			QLatin1String("-v"),QLatin1String("error"),
			QLatin1String("-rw_timeout"),QLatin1String("6000000"),
			QLatin1String("-analyzeduration"),QLatin1String("1500000"),
			QLatin1String("-probesize"),QLatin1String("262144"),
			QLatin1String("-show_entries"),QLatin1String("stream=codec_type,codec_name"),
			QLatin1String("-of"),QLatin1String("json"),
			QLatin1String("-i"),url.toString()});
		if(!internetProbe_.waitForStarted(700)) {
			webProbeButton_->setEnabled(true);
			webStatus_->setText(tr("FFprobe executable unavailable; install ffmpeg."));
			return;
		}
		QTimer::singleShot(8500,this,[this](){
			if(internetProbe_.state()!=QProcess::NotRunning) internetProbe_.kill();
		});
	}
	void playInternetRadio(const QString &address) {
		stopAnalog();
		const QUrl url=QUrl::fromUserInput(address.trimmed());
		if (!url.isValid() || url.host().isEmpty() ||
		    (url.scheme()!=QLatin1String("http") && url.scheme()!=QLatin1String("https"))) {
			webStatus_->setText(tr("Enter a valid HTTP or HTTPS stream URL.")); return;
		}
		// Internet playback has no reason to lock a TV/DAB tuner.
		if (active()) stopReceiver();
		else if (webPlaying_) player_->stop();
		playingKey_.clear();
		webPlaying_=true;
		webSource_->setText(url.toString());
        const QTreeWidgetItem *entry=webStations_->currentItem();
        const QString knownName=(entry &&
            entry->data(1,Qt::UserRole).toString()==url.toString())?
            entry->text(1):url.host();
        showSelectedSource(knownName,tr("Internet radio · opening"),
            tr("Online stream · not an FM/MW/LW frequency"));
		player_->play(url);
		audioStartedMs_=QDateTime::currentMSecsSinceEpoch();
		radioCanvasStation_->setText(tr("♪ Internet radio\\n%1\\nAudio uses the built-in player.")
			.arg(url.host()));
		webStatus_->setText(tr("Opening internet radio stream · no DVB device required."));
	}
	void stopInternetRadio() {
		if (!webPlaying_) return;
		player_->stop();
		webPlaying_=false;
		audioStartedMs_=0;
		webStatus_->setText(tr("Internet radio stopped."));
	}
	void startReceiver() {
		stopAnalog();
		if (webPlaying_) stopInternetRadio();
		if (active() && apiReady_) {
            state_->setText(tr("DAB+ receiver already running · localhost API ready."));
            return;
        }
        if(active() && !apiReady_) {
            // Only an explicit Start restarts this app's owned backend.
            // Never kill readsb, rtl_tcp, WebUSB or arbitrary USB users.
            stopReceiver();
            state_->setText(tr("Restarting this app-owned DAB backend…"));
        }
		if (!prepared()) {
			QMessageBox::information(this,tr("Optional local DAB+ receiver"),
				tr("Install the pinned loopback-only welle-cli backend first:\n"
				   "bash ~/.local/share/tihulu-kaffeine/install_welle.sh\n"
				   "Or run the documented TIHULU install_welle.sh from the repo.\n\n"
				   "A DAB-capable RTL-SDR/SoapySDR device is required."));
			return;
		}
		// Port discovery is local. The patched receiver itself is *guaranteed*
		// to bind 127.0.0.1, not the unauthenticated INADDR_ANY default.
		QTcpServer temp;
		if (!temp.listen(QHostAddress::LocalHost, 0)) {
			state_->setText(tr("Cannot reserve localhost receiver control port."));
			return;
		}
		port_ = temp.serverPort();
		temp.close();
		const QString current = channel_->currentText();
		if (!QRegularExpression(QLatin1String("^(?:[5-9]|1[0-3])[A-F]$"))
			.match(current).hasMatch()) {
			state_->setText(tr("Invalid DAB frequency block.")); return;
		}
		shuttingDown_ = false;
        lastWelleError_.clear();
        lastMux_=QJsonObject(); // Old mux is NOT new live RF evidence.
        apiReady_=false;apiWaitCount_=0;
        scanSNR_->setValue(0);
        scanSNR_->setFormat(tr("DAB receiver starting · SNR not measured"));
        rfQuality_->setValue(0);
        rfQuality_->setFormat(tr("DAB SNR unmeasured · receiver starting"));
		QStringList receiverArgs{QLatin1String("-c"),current,
			QLatin1String("-w"),QString::number(port_)};
		const QString device=driver_->currentData().toString();
		if (device != QLatin1String("auto"))
			receiverArgs<<QLatin1String("-F")<<device;
		backend_.start(binaryPath(), receiverArgs);
		if (!backend_.waitForStarted(1800)) {
            lastWelleError_=backend_.errorString();
            state_->setText(tr("Cannot start welle-cli: %1. This does NOT measure antenna signal.")
                .arg(lastWelleError_));
            updateReceiverOwnership();
			return;
		}
		activeChannel_ = current;
		// The remote hub can attach to this already running loopback backend
		// without opening USB or stealing the receiver. Runtime file is 0600
		// and scoped to this native application's PID.
		const QString runtimeDir=QStandardPaths::writableLocation(
			QStandardPaths::RuntimeLocation);
		if(!runtimeDir.isEmpty()) {
			wellePortFile_=runtimeDir+QLatin1String("/tihulu-welle-")+
				QString::number(QCoreApplication::applicationPid())+
				QLatin1String(".port");
			QFile file(wellePortFile_);
			if(file.open(QIODevice::WriteOnly|QIODevice::Truncate)) {
				file.setPermissions(QFile::ReadOwner|QFile::WriteOwner);
				file.write(QByteArray::number(port_));
			}
		}
		apiReady_=false;
		apiWaitCount_=0;
        ++receiverGeneration_;
		state_->setText(tr("welle-cli PID %1 · block %2 · API 127.0.0.1:%3; "
            "waiting for SDR and localhost control…")
            .arg(backend_.processId()).arg(current).arg(port_));
        tick_.start();
        updateReceiverOwnership();
		probeReceiverApi();
	}

    void updateReceiverOwnership() {
        if(!receiverOwnership_) return;
        const bool dab=backend_.state()!=QProcess::NotRunning;
        const bool analog=analogDemod_.state()!=QProcess::NotRunning ||
                          analogServer_.isListening();
        if(dab) {
            receiverOwnership_->setText(tr(
                "SDR: IN USE by TIHULU DAB · welle-cli PID %1%2")
                .arg(backend_.processId())
                .arg(releaseOnStop_ && !releaseOnStop_->isChecked()?
                    tr(" · keep receiver ready enabled"):
                    tr(" · releases on radio Stop")));
        } else if(analog) {
            receiverOwnership_->setText(tr(
                "SDR: IN USE by TIHULU analogue · rtl_fm PID %1")
                .arg(analogDemod_.processId()));
        } else {
            receiverOwnership_->setText(tr(
                "SDR: RELEASED by TIHULU · other applications may "
                "claim the device"));
        }
    }
    void stopRadioListening() {
        // Scanning uses the receiver itself and always needs a hard stop.
        if(scanning_ || !releaseOnStop_ || releaseOnStop_->isChecked()) {
            stopReceiver();
            if(state_) state_->setText(active()?
                tr("Radio Stop requested, but the DAB receiver process "
                   "is still active; SDR release not verified."):
                tr("Radio stopped · this application's DAB receiver released."));
            updateReceiverOwnership();
            return;
        }
        // Optional keep-ready: stop all playback/AI/recording resources,
        // leaving only our welle-cli receiver process alive.
        ++stationRequestId_;
        ++scanRequestId_;
        stopCaptioning();
        stopLyrics();
        stopRecording();
        if(!playingKey_.isEmpty()) player_->stop();
        playingKey_.clear();
        audioStartedMs_=0;
        dabPlaybackObserved_=false;
        dabIdleSinceMs_=0;
        {
            const QSignalBlocker block(quickAi_);
            quickAi_->setChecked(false);
            quickAi_->setText(tr("AI captions · OFF"));
        }
        if(stationOpenProgress_) {
            stationOpenProgress_->setValue(0);
            stationOpenProgress_->setFormat(tr(
                "Radio stopped · SDR held (keep-ready selected)"));
        }
        if(playStatus_) playStatus_->setText(tr(
            "Radio playback stopped. TIHULU still owns the SDR "
            "because release-on-stop was unchecked."));
        if(state_) state_->setText(tr(
            "Receiver kept ready by choice. Use Release SDR now "
            "before starting another SDR application."));
        updateReceiverOwnership();
    }
    void monitorRadioPlaybackStop() {
        if(shuttingDown_) return;
        const qint64 now=QDateTime::currentMSecsSinceEpoch();
        // Mirror the native volume control without asserting sound was heard.
        if(radioOutputVolume_ && player_) {
            const int volume=player_->getVolume();
            if(radioOutputVolume_->value()!=volume) {
                const QSignalBlocker block(radioOutputVolume_);
                radioOutputVolume_->setValue(volume);
            }
            if(volume==0 && active() && !playingKey_.isEmpty())
                radioAudioOutputStatus_->setText(
                    tr("Volume is 0% · raise volume; ASR captions do not prove audio output."));
        }
        const auto playback=player_->getPlaybackStatus();
        if(playback==MediaWidget::Playing) {
            if(active() && !playingKey_.isEmpty())
                dabPlaybackObserved_=true;
            if(analogServer_.isListening())
                analogPlaybackObserved_=true;
            dabIdleSinceMs_=0;
            analogIdleSinceMs_=0;
            return;
        }
        if(playback!=MediaWidget::Idle) {
            // Paused/buffering is not user Stop.
            dabIdleSinceMs_=0;
            analogIdleSinceMs_=0;
            return;
        }
        // Kaffeine main playback Stop can leave welle-cli holding USB.
        // Debounce only when this station was actually Playing before:
        // transient Idle while tuning must not release the receiver.
        if(active() && !playingKey_.isEmpty() && dabPlaybackObserved_
           && !scanning_) {
            if(!dabIdleSinceMs_) dabIdleSinceMs_=now;
            if(now-dabIdleSinceMs_>=2300) {
                stopRadioListening();
                return;
            }
        } else dabIdleSinceMs_=0;
        if(analogServer_.isListening() && analogPlaybackObserved_) {
            if(!analogIdleSinceMs_) analogIdleSinceMs_=now;
            if(now-analogIdleSinceMs_>=2300) {
                analogPlaybackObserved_=false;
                analogIdleSinceMs_=0;
                if(releaseOnStop_ && releaseOnStop_->isChecked())
                    stopAnalog();
                else if(analogStatus_)
                    analogStatus_->setText(tr(
                        "Playback stopped; analogue SDR is still reserved. "
                        "Press Stop / release to free it."));
                updateReceiverOwnership();
            }
        } else analogIdleSinceMs_=0;
    }
	void stopReceiver() {
        dabPlaybackObserved_=false;
        analogPlaybackObserved_=false;
        dabIdleSinceMs_=0;
        analogIdleSinceMs_=0;
        ++receiverGeneration_; // Invalidate delayed replies from old process/port.
		stopAnalog();
		stopInternetRadio();
		shuttingDown_ = true;
		++stationRequestId_;
		scanning_ = false;
        // Stopping radio disarms optional AI, even when the next station
        // is selected later. No hidden background capture survives Stop.
        if(quickAi_) {
            const QSignalBlocker block(quickAi_);
            quickAi_->setChecked(false);
            quickAi_->setText(tr("AI captions · OFF"));
        }
		stopCaptioning();
		stopLyrics();
		stopRecording();
		tick_.stop();
		if (!playingKey_.isEmpty()) player_->stop();
		playingKey_.clear();
		audioStartedMs_=0;
		if (active()) {
			backend_.terminate();
			if (!backend_.waitForFinished(1200)) {
				backend_.kill();
				backend_.waitForFinished(1200);
			}
		}
		port_ = 0;
		if(!wellePortFile_.isEmpty()) QFile::remove(wellePortFile_);
		wellePortFile_.clear();
		apiReady_=false;apiWaitCount_=0;
        scanSNR_->setValue(0);
        scanSNR_->setFormat(tr("DAB SNR unmeasured · receiver stopped"));
        rfQuality_->setValue(0);
        rfQuality_->setFormat(tr("DAB RF unmeasured · receiver stopped"));
        lastMux_=QJsonObject();
        if(stationOpenProgress_) {
            stationOpenProgress_->setValue(0);
            stationOpenProgress_->setFormat(tr(
                "Radio stopped · DAB receiver released"));
        }
        updateReceiverOwnership();
	}


    QString apiFailureDetails() const {
        const QString stderrTail=lastWelleError_.trimmed().right(320);
        const bool busy=stderrTail.contains(QLatin1String("busy"),Qt::CaseInsensitive) ||
            stderrTail.contains(QLatin1String("usb_claim"),Qt::CaseInsensitive) ||
            stderrTail.contains(QLatin1String("no device"),Qt::CaseInsensitive) ||
            stderrTail.contains(QLatin1String("cannot open"),Qt::CaseInsensitive) ||
            stderrTail.contains(QLatin1String("failed to open"),Qt::CaseInsensitive);
        const QString cause=busy?
            tr("SDR may be owned by readsb, rtl_tcp, WebUSB or a kernel DVB driver. "
               "Release only the actual owner deliberately.") :
            tr("Check the pinned welle-cli driver, SDR permissions and startup log.");
        return tr("127.0.0.1:%1 · PID %2 · %3%4")
            .arg(port_).arg(backend_.processId())
            .arg(cause).arg(stderrTail.isEmpty()?QString():
                 tr(" · welle-cli stderr: %1").arg(stderrTail));
    }
    void probeReceiverApi() {
        if(!active() || apiReady_ || port_==0) return;
        const quint64 generation=receiverGeneration_;
        const quint16 targetPort=port_;
        QNetworkRequest request(QUrl(base()+QLatin1String("/channel")));
        request.setTransferTimeout(850);
        QNetworkReply *reply=network_.get(request);
        connect(reply,&QNetworkReply::finished,this,[this,reply,generation,targetPort]() {
            const bool ready=reply->error()==QNetworkReply::NoError;
            const QString networkError=reply->errorString();
            reply->deleteLater();
            // A delayed answer must never activate a new backend/port by mistake.
            if(generation!=receiverGeneration_ || targetPort!=port_ || !active()) return;
            if(ready) {
                apiReady_=true;apiWaitCount_=0;
                state_->setText(tr("DAB API READY · 127.0.0.1:%1 · %2. "
                    "Live station scans are available.").arg(port_).arg(activeChannel_));
            } else if(++apiWaitCount_<18) {
                // welle-cli may be running before USB claim/server startup.
                QTimer::singleShot(450,this,[this,generation](){
                    if(generation==receiverGeneration_) probeReceiverApi();
                });
            } else {
                apiReady_=false;
                scanSNR_->setValue(0);
                scanSNR_->setFormat(tr("DAB SNR NOT MEASURED · API unreachable"));
                rfQuality_->setValue(0);
                rfQuality_->setFormat(tr("DAB RF unmeasured · API unreachable"));
                state_->setText(tr("DAB API unreachable (%1): %2. "
                    "Press Start receiver to retry only this app's backend.")
                    .arg(networkError,apiFailureDetails()));
            }
        });
    }

	void callJson(const QString &endpoint,
	              const std::function<void(const QJsonObject&)> &done) {
        if(!active() || !apiReady_ || !port_) return;
        const quint64 generation=receiverGeneration_;
        const quint16 sourcePort=port_;
		QNetworkRequest request(QUrl(base() + endpoint));
		request.setTransferTimeout(1200);
		QNetworkReply *reply = network_.get(request);
		connect(reply, &QNetworkReply::finished, this, [this,reply,done,generation,sourcePort]() {
			const QByteArray bytes = reply->readAll();
			const bool ok = reply->error()==QNetworkReply::NoError &&
				bytes.size() < 1024 * 1024;
			reply->deleteLater();
            // Never paint stale 0.0 dB/mux data from a stopped or restarted
            // radio. Station cache is separate and remains available offline.
			if (!ok || !active() || !apiReady_ ||
                generation!=receiverGeneration_ || sourcePort!=port_) return;
			QJsonParseError error;
			const QJsonDocument doc = QJsonDocument::fromJson(bytes,&error);
			if (error.error==QJsonParseError::NoError && doc.isObject())
				done(doc.object());
		});
	}
	void pollMux() {
		if (!active() || !apiReady_ || scanning_) return;
		const QString channel = activeChannel_;
		callJson(QLatin1String("/mux.json"), [this,channel](const QJsonObject &object){
			consumeMux(object,channel);
		});
	}
	void consumeMux(const QJsonObject &mux, const QString &ch) {
		lastMux_=mux;
		const auto receiver = mux.value(QLatin1String("receiver")).toObject();
		const auto hardware = receiver.value(QLatin1String("hardware")).toObject();
		const auto demod = mux.value(QLatin1String("demodulator")).toObject();
		const auto fic = demod.value(QLatin1String("fic")).toObject();
		const auto ensemble = mux.value(QLatin1String("ensemble")).toObject();
		const QString stationGroup = label(ensemble.value(QLatin1String("label")));
		const bool snrValid=demod.value(QLatin1String("snr")).isDouble();
		const double snr=demod.value(QLatin1String("snr")).toDouble();
		const QString quality=!snrValid?tr("not measured"):
			(snr>=15?tr("strong"):snr>=8?tr("moderate"):tr("weak / uncertain"));
		if(scanSNR_) {
			scanSNR_->setValue(snrValid?qBound(0,qRound(snr*4),100):0);
			scanSNR_->setFormat(snrValid?
				tr("%1 · actual SNR %2 dB (%3)").arg(ch)
					.arg(snr,0,'f',1).arg(quality):
				tr("%1 · no verified SNR measurement").arg(ch));
		}
		if(scanning_ && snrValid)
			scanSnrByBlock_[ch]=snr;
		rfQuality_->setValue(snrValid?qBound(0,qRound(snr*4),100):0);
		rfQuality_->setFormat(
			snrValid ? tr("DAB SNR: %1 dB · relative %2%").arg(snr,0,'f',1)
				.arg(qBound(0,qRound(snr*4),100)) :
			tr("DAB SNR unavailable · tuner not locked"));
		signal_->setText(tr("DAB+ block %1 · centre %2\n"
                "Ensemble: %3  |  SNR: %4 dB (%5)  |  FIC errors: %6  |  Gain: %7\nSDR: %8")
            .arg(ch,dabCenterFrequencyMHz(ch),
                 stationGroup.isEmpty()?tr("not locked"):stationGroup,
                 snrValid?QString::number(snr,'f',1):tr("unknown"),quality,
                 fic.value(QLatin1String("numcrcerrors")).toVariant().toString(),
                 hardware.value(QLatin1String("gain")).toVariant().toString(),
                 hardware.value(QLatin1String("name")).toString()));
		const auto tii=mux.value(QLatin1String("tii")).toArray();
		if (!tii.isEmpty())
			signal_->setToolTip(tr("welle.io TII transmitters: %1 entries")
				.arg(tii.size()));
		const auto stations = mux.value(QLatin1String("services")).toArray();
		for (const QJsonValue &v : stations) {
			const auto service = v.toObject();
			const QString sid = service.value(QLatin1String("sid")).toString();
			const QString serviceLabel=label(service.value(QLatin1String("label")));
			const QString stream = service.value(QLatin1String("url_mp3")).toString();
			if (serviceLabel.isEmpty() ||
			    !QRegularExpression(QLatin1String("^/mp3/[A-Fa-f0-9x]+$"))
			     .match(stream).hasMatch() || sid.isEmpty()) continue;
			const QString key = ch + QLatin1Char(':') + sid;
			if(scanning_ && !stationGroup.isEmpty() && snrValid)
				scanObserved_.insert(key);
			if (!stationChannels_.contains(key)) {
				auto *item = new QTreeWidgetItem(
					{favorites_.contains(key)?QStringLiteral("★"):QStringLiteral("☆"),
					 serviceLabel, ch, sid});
				item->setData(0,Qt::UserRole,key);
				stations_->addTopLevelItem(item);
				stationData_[key] = service;
				stationChannels_[key] = ch;
				filterStations();
			}
			stationData_[key] = service;
			if (key==playingKey_) {
				const QString dls = label(service.value(QLatin1String("dls"))
				                         .toObject().value(QLatin1String("label")));
				if (!dls.isEmpty() && lastDls_ != dls) {
					lastDls_=dls;
					if(metadataCaptions_) {
						const qint64 received=QDateTime::currentMSecsSinceEpoch();
						cueQueue_.append({++dlsCaptionIndex_,received+
							activePlaybackCacheMs_+radioOffsetMs_->value(),received,
							tr("[DLS broadcaster metadata] %1").arg(dls).left(700)});
						while(cueQueue_.size()>12) cueQueue_.removeFirst();
					}
				}
                // Check all radio metadata on EVERY mux update, even if
                // rotating dls.label has not changed this cycle.
                const TihuluDlsSong newSong=tihuluDlsSongFromService(service);
                if(newSong.valid()) {
                    lastObservedSongHint_=newSong;
                    lastObservedSongMs_=QDateTime::currentMSecsSinceEpoch();
                    const QString candidate=newSong.normalizedKey();
                    if(candidate==lastSongMetadataKey_) {
                        pendingSongKey_.clear();
                        pendingSongDls_.clear();
                        pendingSongObservations_=0;
                    } else if(candidate!=pendingSongKey_) {
                        pendingSongKey_=candidate;
                        pendingSongHint_=newSong;
                        pendingSongDls_=dls;
                        pendingSongObservations_=1;
                        pendingSongSinceMs_=lastObservedSongMs_;
                        const QString station=playingKey_;
                        const quint64 ticket=stationRequestId_;
                        QTimer::singleShot(5100,this,
                            [this,candidate,station,ticket](){
                                commitPendingDlsSong(candidate,station,ticket);
                            });
                        if(lyricsSyncState_) lyricsSyncState_->setText(tr(
                            "Song candidate (%1) · verifying; Karaoke preserved")
                            .arg(newSong.format));
                    } else pendingSongObservations_=
                        qMin(20,pendingSongObservations_+1);
                } // Unknown text/station slogans leave current song intact.
                const QJsonObject errs=service.value(
                    QLatin1String("errorcounters")).toObject();
                const qint64 frames=errs.value(
                    QLatin1String("frameerrors")).toVariant().toLongLong();
                const qint64 rs=errs.value(
                    QLatin1String("rserrors")).toVariant().toLongLong();
                const qint64 aac=errs.value(
                    QLatin1String("aacerrors")).toVariant().toLongLong();
                if(lastErrorStation_==key && lastRfFrameErrors_>=0) {
                    const qint64 frameDelta=frames>=lastRfFrameErrors_?
                        frames-lastRfFrameErrors_:0;
                    const qint64 rsDelta=rs>=lastRfRsErrors_?
                        rs-lastRfRsErrors_:0;
                    const qint64 aacDelta=aac>=lastRfAacErrors_?
                        aac-lastRfAacErrors_:0;
                    if(frameDelta+rsDelta+aacDelta>0)
                        radioAudioHealth_->setText(tr(
                            "DAB decoder error counters increased since "
                            "last live mux: frame +%1 / RS +%2 / AAC +%3. "
                            "Signal/demodulation may be causing audio gaps; "
                            "more VLC buffering cannot repair RF errors.")
                            .arg(frameDelta).arg(rsDelta).arg(aacDelta));
                    else radioAudioHealth_->setText(tr(
                        "DAB error counters stable this sample · "
                        "audible audio/DAC buffer still unmeasured"));
                }
                lastErrorStation_=key;
                lastRfFrameErrors_=frames;
                lastRfRsErrors_=rs;
                lastRfAacErrors_=aac;
				const QString technical=tr("Frame / RS / AAC: %1 / %2 / %3")
					.arg(errs.value(QLatin1String("frameerrors")).toVariant().toString())
					.arg(errs.value(QLatin1String("rserrors")).toVariant().toString())
					.arg(errs.value(QLatin1String("aacerrors")).toVariant().toString());
				dls_->setText(tr("Now playing: %1\n"
                    "DAB+ block %2 · %3 (centre frequency)\nDLS: %4\n%5")
                    .arg(serviceLabel,ch,dabCenterFrequencyMHz(ch),dls,technical));
				requestSlide(sid);
			}
		}
		if (!stations.isEmpty())
			state_->setText(tr("DAB+ %1 · %2 total known stations · local receiver")
				.arg(ch).arg(stations_->topLevelItemCount()));
	}
    void loadStationLists() {
        QSettings settings(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
        const QByteArray raw=settings.value(QLatin1String("dabNamedLists")).toByteArray();
        if(raw.size()>100000) return; // reject unbounded corrupt preferences
        const QJsonDocument stored=QJsonDocument::fromJson(raw);
        if(!stored.isObject()) return;
        const QJsonObject lists=stored.object();
        for(auto it=lists.begin();it!=lists.end() && stationLists_.size()<20;++it) {
            const QString name=it.key().trimmed();
            if(name.isEmpty() || name.size()>48 || !it.value().isArray())
                continue;
            QSet<QString> members;
            for(const QJsonValue &entry:it.value().toArray()) {
                const QString key=entry.toString();
                if(members.size()<700 && stationChannels_.contains(key))
                    members.insert(key);
            }
            stationLists_.insert(name,members);
            stationListPicker_->addItem(name,name);
        }
    }
    void saveStationLists() {
        QJsonObject stored;
        for(auto it=stationLists_.constBegin();it!=stationLists_.constEnd();++it) {
            QJsonArray entries;
            QStringList keys=it.value().values();
            keys.sort();
            for(const QString &key:keys)
                if(stationChannels_.contains(key))
                    entries.append(key);
            stored.insert(it.key(),entries);
        }
        QSettings settings(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
        settings.setValue(QLatin1String("dabNamedLists"),
            QJsonDocument(stored).toJson(QJsonDocument::Compact));
    }
    void createNamedStationList() {
        if(stationLists_.size()>=20) {
            libraryStatus_->setText(tr("Maximum 20 personal station lists."));
            return;
        }
        bool ok=false;
        const QString name=QInputDialog::getText(this,tr("New DAB station list"),
            tr("List name (e.g. NRW favourites):"),QLineEdit::Normal,
            QString(),&ok).trimmed();
        if(!ok) return;
        if(name.isEmpty() || name.size()>48 ||
           name.contains(QLatin1Char('\n')) ||
           name.contains(QLatin1Char('\r'))) {
            libraryStatus_->setText(tr("Use a list name of 1–48 characters."));
            return;
        }
        for(const QString &existing:stationLists_.keys())
            if(existing.compare(name,Qt::CaseInsensitive)==0) {
                libraryStatus_->setText(tr("This station list already exists."));
                return;
            }
        stationLists_.insert(name,QSet<QString>());
        stationListPicker_->addItem(name,name);
        stationListPicker_->setCurrentIndex(stationListPicker_->count()-1);
        stationListOnly_->setChecked(false);
        saveStationLists();
        filterStations();
        libraryStatus_->setText(tr("Created '%1'. Select any scanned station "
            "and choose + Add selected.").arg(name));
    }
    void deleteNamedStationList() {
        const QString name=stationListPicker_->currentData().toString();
        if(!stationLists_.contains(name)) return;
        if(QMessageBox::question(this,tr("Delete station list"),
              tr("Delete the list '%1'? Saved stations and favourites "
                 "will not be removed.").arg(name))!=QMessageBox::Yes)
            return;
        stationLists_.remove(name);
        stationListPicker_->removeItem(stationListPicker_->currentIndex());
        if(stationListPicker_->count()==0)
            stationListOnly_->setChecked(false);
        saveStationLists();
        filterStations();
    }
    void changeSelectedStationList(bool add) {
        const QString name=stationListPicker_->currentData().toString();
        const QTreeWidgetItem *selected=stations_->currentItem();
        if(!stationLists_.contains(name)) {
            libraryStatus_->setText(tr("Create or select a station list first."));
            return;
        }
        if(!selected) {
            libraryStatus_->setText(tr("Select a scanned station first."));
            return;
        }
        const QString key=selected->data(0,Qt::UserRole).toString();
        if(!stationChannels_.contains(key)) return;
        if(add) stationLists_[name].insert(key);
        else stationLists_[name].remove(key);
        saveStationLists();
        filterStations();
        libraryStatus_->setText(tr("%1 · %2 station(s) in personal list")
            .arg(name).arg(stationLists_.value(name).size()));
    }
	void filterStations() {
		const QString query=stationSearch_->text().trimmed();
		const QString block=libraryBlock_->currentData().toString();
        const QString listName=stationListPicker_?
            stationListPicker_->currentData().toString():QString();
        const bool onlyList=stationListOnly_ && stationListOnly_->isChecked() &&
            stationLists_.contains(listName);
		int visible=0, total=stations_->topLevelItemCount();
		for (int i=0;i<total;++i) {
			QTreeWidgetItem *item=stations_->topLevelItem(i);
			const QString key=item->data(0,Qt::UserRole).toString();
			const bool match=(query.isEmpty() ||
				item->text(1).contains(query,Qt::CaseInsensitive) ||
				item->text(2).contains(query,Qt::CaseInsensitive)) &&
				(block.isEmpty() || item->text(2)==block) &&
				(!favoritesOnly_->isChecked() || favorites_.contains(key)) &&
                (!onlyList || stationLists_.value(listName).contains(key));
			item->setHidden(!match);
			if (match) ++visible;
		}
		libraryStatus_->setText(tr("%1 visible / %2 saved stations · all DAB blocks")
			.arg(visible).arg(total));
	}
	void toggleFavorite(QTreeWidgetItem *item) {
		if (!item) return;
		const QString key=item->data(0,Qt::UserRole).toString();
		if (key.isEmpty()) return;
		if (favorites_.contains(key)) favorites_.remove(key);
		else favorites_.insert(key);
		item->setText(0,favorites_.contains(key)?
			QStringLiteral("★"):QStringLiteral("☆"));
		saveStations();
		filterStations();
	}
	void loadStations() {
		QSettings settings(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
		favorites_ = QSet<QString>::fromList(
			settings.value(QLatin1String("dabFavorites")).toStringList());
		const QByteArray raw=settings.value(QLatin1String("dabStationCache")).toByteArray();
		if (raw.size() > 150000) return;
		const auto doc=QJsonDocument::fromJson(raw);
		if (!doc.isArray()) return;
		for (const QJsonValue &v : doc.array()) {
			const auto obj=v.toObject();
			const QString ch=obj.value(QLatin1String("channel")).toString();
			const QString sid=obj.value(QLatin1String("sid")).toString();
			const QString name=obj.value(QLatin1String("name")).toString();
			if (ch.size()>3 || sid.size()>16 || name.size()>150 ||
				sid.isEmpty() || ch.isEmpty() || name.isEmpty()) continue;
			const QString key=ch+QLatin1Char(':')+sid;
			if(stationChannels_.contains(key)) continue; // old cache may repeat services
			auto *item = new QTreeWidgetItem(
				{favorites_.contains(key)?QStringLiteral("★"):QStringLiteral("☆"),
				 name,ch,sid});
			item->setData(0,Qt::UserRole,key);
			stations_->addTopLevelItem(item);
			stationChannels_[key]=ch;
		}
	}
	void saveStations() {
		QJsonArray list;
		QSet<QString> written;
		for (int i=0;i<stations_->topLevelItemCount() && i<700;++i) {
			const auto *item=stations_->topLevelItem(i);
			const QString key=item->data(0,Qt::UserRole).toString();
			if(written.contains(key)) continue;
			written.insert(key);
			QJsonObject obj;
			obj[QLatin1String("channel")]=item->text(2);
			obj[QLatin1String("sid")]=item->text(3);
			obj[QLatin1String("name")]=item->text(1);
			list.append(obj);
		}
		QSettings settings(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
		settings.setValue(QLatin1String("dabStationCache"),
			QJsonDocument(list).toJson(QJsonDocument::Compact));
		settings.setValue(QLatin1String("dabFavorites"),
			QStringList(favorites_.values()));
	}
    bool currentTuneRequest(bool scanningRequest,quint64 ticket) const {
        return active() && (scanningRequest?
            (scanning_ && ticket==scanRequestId_):
            (!scanning_ && ticket==stationRequestId_));
    }
    void confirmTunedBlock(const QString &block,
                           const std::function<void()> &ready,
                           bool scanningRequest,quint64 ticket,int retry=0) {
        if(!currentTuneRequest(scanningRequest,ticket)) return;
        QNetworkReply *reply=network_.get(
            QNetworkRequest(QUrl(base()+QLatin1String("/channel"))));
        connect(reply,&QNetworkReply::finished,this,
            [this,reply,block,ready,scanningRequest,ticket,retry](){
                if(!currentTuneRequest(scanningRequest,ticket)) {
                    reply->deleteLater();return;
                }
                const bool matched=reply->error()==QNetworkReply::NoError &&
                    QString::fromUtf8(reply->readAll()).trimmed()==block;
                reply->deleteLater();
                if(matched) {
                    activeChannel_=block;
                    channel_->setCurrentText(block);
                    ready();
                } else if(retry<(scanningRequest?2:5)) {
                    // DAB demodulator can take a little longer to acknowledge
                    // the selected frequency. Poll only this exact request;
                    // stale confirmations must not open a different service.
                    QTimer::singleShot(scanningRequest?700:450,this,
                        [this,block,ready,scanningRequest,ticket,retry](){
                            confirmTunedBlock(block,ready,
                                scanningRequest,ticket,retry+1);
                        });
                } else {
                    state_->setText(tr("DAB %1 retune was not confirmed by "
                        "the live receiver; no cached channel stream opened.")
                        .arg(block));
                    if(scanningRequest)
                        QTimer::singleShot(300,this,[this](){scanStep();});
                }
            });
    }
	void tune(const QString &block, const std::function<void()> &ready) {
        if(!active()) return;
        const bool scanningRequest=scanning_;
        const quint64 ticket=scanningRequest?scanRequestId_:stationRequestId_;
        if(!apiReady_) {
            if(apiWaitCount_>=18) {
                state_->setText(tr("Cannot tune DAB %1: %2. SNR has NOT "
                    "been measured. Press Start receiver to retry.")
                    .arg(block,apiFailureDetails()));
                scanSNR_->setValue(0);
                scanSNR_->setFormat(tr("DAB SNR NOT MEASURED · no API connection"));
                scanning_=false;
                scan_->setEnabled(true);
                return;
            }
            QTimer::singleShot(450,this,
                [this,block,ready,scanningRequest,ticket](){
                    if(currentTuneRequest(scanningRequest,ticket))
                        tune(block,ready);
                });
            return;
        }
        if(!QRegularExpression(QLatin1String("^(?:[5-9]|1[0-3])[A-F]$"))
            .match(block).hasMatch()) return;
        QNetworkRequest request(QUrl(base()+QLatin1String("/channel")));
        request.setHeader(QNetworkRequest::ContentTypeHeader,
                          QLatin1String("text/plain"));
        QNetworkReply *reply=network_.post(request,block.toUtf8());
        connect(reply,&QNetworkReply::finished,this,
            [this,reply,block,ready,scanningRequest,ticket](){
                const bool valid=currentTuneRequest(scanningRequest,ticket);
                const bool ok=reply->error()==QNetworkReply::NoError;
                reply->deleteLater();
                if(!valid) return;
                if(!ok) {
                    state_->setText(tr("DAB retune failed; receiver API error."));
                    if(scanningRequest)
                        QTimer::singleShot(400,this,[this](){scanStep();});
                    return;
                }
                // Only the scan needs a longer FIC discovery/ensemble dwell.
                // A station switch can start verifying the channel quickly;
                // verifyStation separately waits for a real service URL.
                QTimer::singleShot(scanningRequest?3200:650,this,
                    [this,block,ready,scanningRequest,ticket](){
                        confirmTunedBlock(block,ready,scanningRequest,ticket);
                    });
            });
    }
	void beginScan() {
		if (webPlaying_) stopInternetRadio();
		if (!active()) {
			startReceiver();
			if (!active()) return;
		}
        if(scanning_) return;
        if(!playingKey_.isEmpty()) {
			if (QMessageBox::question(this,tr("Full DAB scan"),
				tr("Stop current radio playback, offline captions and "
				"recording while scanning Band III frequencies?"),
				QMessageBox::Yes|QMessageBox::No,QMessageBox::No)!=QMessageBox::Yes)
				return;
            {
                const QSignalBlocker block(quickAi_);
                quickAi_->setChecked(false);
                quickAi_->setText(tr("AI captions · OFF"));
            }
			stopCaptioning();
			stopLyrics();
			stopRecording();
			player_->stop();
			playingKey_.clear();
			lastDetectedLanguage_.clear();
		}
        // Disable AI only AFTER the user accepts the scan interruption;
        // cancelling the scan must preserve the currently running captions.
        {
            const QSignalBlocker block(quickAi_);
            quickAi_->setChecked(false);
            quickAi_->setText(tr("AI captions · OFF"));
        }
        stopCaptioning();
		scanning_=true;
		++stationRequestId_;
		scanRequestId_=0;
		scanIndex_=0;
		scanSnrByBlock_.clear();
		scanObserved_.clear();
		scanProgress_->setRange(0,channel_->count());
		scanProgress_->setValue(0);
		scanProgress_->setFormat(tr("Scanning Band III: %v/%m blocks"));
		scanSNR_->setValue(0);
		scanSNR_->setFormat(tr("Waiting for current DAB block lock…"));
		scan_->setEnabled(false);
		state_->setText(tr("Scanning real DAB Band III frequencies…"));
		// welle-cli first opens the SDR and then starts its HTTP server.
		// Do not send the initial frequency POST before the HTTP port exists.
		QTimer::singleShot(1400,this,[this](){scanStep();});
	}
	void scanStep() {
		if (!scanning_ || !active()) {
			scanning_=false;
			scan_->setEnabled(true);
			saveStations();
			return;
		}
		if (scanIndex_ >= channel_->count()) {
			scanProgress_->setValue(channel_->count());
			scanProgress_->setFormat(tr("DAB scan complete · %v/%m blocks"));
			if(!scanSnrByBlock_.isEmpty()) {
				auto strongest=std::max_element(scanSnrByBlock_.constBegin(),
					scanSnrByBlock_.constEnd(),
					[](double a,double b){return a<b;});
				scanSNR_->setToolTip(tr("Strongest measured block: %1 · %2 dB SNR. "
					"Values are samples obtained during this scan only.")
					.arg(strongest.key()).arg(strongest.value(),0,'f',1));
			}
			scanning_=false;
			scan_->setEnabled(true);
			saveStations();
			state_->setText(tr("DAB scan complete · %1 services seen on measured "
				"RF blocks this scan · %2 total saved from all scans.")
				.arg(scanObserved_.size()).arg(stations_->topLevelItemCount()));
			return;
		}
		const QString block = channel_->itemText(scanIndex_++);
		scanProgress_->setValue(scanIndex_-1);
		scanSNR_->setValue(0);
		scanSNR_->setFormat(tr("%1 · retuning, awaiting new RF measurement").arg(block));
		state_->setText(tr("Scanning DAB %1 (%2/%3)…")
			.arg(block).arg(scanIndex_).arg(channel_->count()));
		const quint64 requestId=++scanRequestId_;
		tune(block,[this,block,requestId]() {
			if(!scanning_ || requestId!=scanRequestId_ || activeChannel_!=block) return;
			auto completed=std::make_shared<bool>(false);
			auto next=[this,requestId,completed](){
				if(*completed) return;
				*completed=true;
				if(scanning_ && requestId==scanRequestId_)
					QTimer::singleShot(120,this,[this,requestId](){
						if(scanning_ && requestId==scanRequestId_) scanStep();
					});
			};
			callJson(QLatin1String("/mux.json"),
				[this,block,requestId,next](const QJsonObject &data){
					// Never attribute a late /mux.json answer to a later block:
					// a scan can otherwise invent duplicate/stale station entries.
					if(scanning_ && requestId==scanRequestId_ && activeChannel_==block) {
						consumeMux(data,block);
						saveStations();
					}
					next();
				});
			// No HTTP callback (error, timeout): continue without inventing SNR.
			QTimer::singleShot(1500,this,next);
		});
	}
	void verifyStation(const QString &key,const QString &name,
	                   const QString &sid,quint64 requestId,int attempt=0) {
		if(requestId!=stationRequestId_ || scanning_ || !active()) return;
		if(attempt>=5) {
			playStatus_->setText(tr("Unavailable now · %1 is only a SAVED station. "
				"The tuner did not report its service on %2. "
				"Rescan this DAB block or check RF SNR/lock.")
				.arg(name,stationChannels_.value(key)));
			stationOpenProgress_->setFormat(tr("OFFLINE / not found · no audio URL opened"));
			stationOpenProgress_->setValue(0);
			return;
		}
		stationOpenProgress_->setValue(qMin(3,attempt+1));
		stationOpenProgress_->setFormat(tr("Checking live DAB service %1 · attempt %2/5")
			.arg(name).arg(attempt+1));
		auto resolved=std::make_shared<bool>(false);
		const QString block=stationChannels_.value(key);
		callJson(QLatin1String("/mux.json"),
			[this,key,name,sid,block,requestId,attempt,resolved](const QJsonObject &mux) {
				if(*resolved || requestId!=stationRequestId_) return;
				*resolved=true;
				if(!active() || activeChannel_!=block) return;
				const QJsonObject demod=mux.value(QLatin1String("demodulator")).toObject();
				const QJsonArray services=mux.value(QLatin1String("services")).toArray();
				QString stream;
				for(const QJsonValue &v:services) {
					const QJsonObject candidate=v.toObject();
					if(candidate.value(QLatin1String("sid")).toString()!=sid) continue;
					const QString candidateStream=candidate.value(
						QLatin1String("url_mp3")).toString();
					if(QRegularExpression(QLatin1String("^/mp3/[A-Fa-f0-9x]+$"))
						.match(candidateStream).hasMatch()) {
						stream=candidateStream;
						break;
					}
				}
				if(stream.isEmpty()) {
					playStatus_->setText(tr("%1 · DAB %2 · service not in LIVE mux "
						"(saved entry may be stale); SNR %3.")
						.arg(name,block).arg(demod.value(QLatin1String("snr"))
						.isDouble()?QString::number(demod.value(QLatin1String("snr"))
						.toDouble(),'f',1):tr("unavailable")));
					QTimer::singleShot(1100,this,[this,key,name,sid,requestId,attempt](){
						verifyStation(key,name,sid,requestId,attempt+1);
					});
					return;
				}
				// URL comes from the verified current welle mux, never fabricated
				// from a possibly months-old cached service ID.
				const bool restartAi=quickAi_->isChecked();
                stopCaptioning();
                stopLyrics();
                stopRecording();
                // Stopping a lyrics-owned worker may clear its AI toggle,
                // but an independently enabled live caption session must
                // survive a station switch until the owner turns it OFF.
                if(restartAi) {
                    const QSignalBlocker block(quickAi_);
                    quickAi_->setChecked(true);
                    quickAi_->setText(tr("AI captions · ON"));
                }
				lastDetectedLanguage_.clear();
				lagSamples_.clear();
				lastRadioChunk_=-1; lastRadioRevision_=-1;
				displayedRadioChunk_=-1;
                lastCaptionVisibleMs_=0;
                lastCanvasLyricMs_=0;
                captionReadingHoldUntilMs_=0;
                captionDisplayedStartedMs_=0;
                if(radioCanvasCaption_) radioCanvasCaption_->setVisible(false);
                radioCaptionBanner_->setText(tr("Opening DAB station · waiting for audio…"));
				pendingRadioCue_.clear();
                playingKey_=key;
                lastErrorStation_.clear();
                lastRfFrameErrors_=-1;
                lastRfRsErrors_=-1;
                lastRfAacErrors_=-1;
                radioAudioHealth_->setText(tr(
                    "New service · collecting real DAB frame/RS/AAC error "
                    "counter samples. Audio output is not measured."));
                showSelectedSource(name,tr("DAB+ · live mux verified"),
                    tr("Block %1 · %2 · service %3 · stream opening")
                        .arg(block,dabCenterFrequencyMHz(block),sid));
				lastDls_.clear();
                clearLiveRadioLyricsCatalog(); // another station, no old song
                pendingSongKey_.clear();
                pendingSongDls_.clear();
                pendingSongSinceMs_=0;
                lastSongDls_.clear();
                lastAcceptedSongHint_=TihuluDlsSong();
                lastObservedSongHint_=TihuluDlsSong();
                pendingSongHint_=TihuluDlsSong();
                pendingSongObservations_=0;
                lastObservedSongMs_=0;
        lastSongMetadataKey_.clear();
                lyricRawLines_.clear();
                lastLyricsProvider_.clear();
                clearKaraokeLine();
				lyricLoaded_=false;
				lyricCues_=QJsonArray();
				slideHistory_.clear();
				lastSlideHash_.clear();
				slideIndex_=0;
				activePlaybackCacheMs_=requestedPlaybackBufferMs();
                QSettings playback(QLatin1String("TIHULU"),
                                   QLatin1String("KaffeineRadio"));
                playback.setValue(QLatin1String("playbackBufferMs"),
                                  activePlaybackCacheMs_);
                playback.setValue(QLatin1String("radioBufferDesiredMs"),
                                  selectedBufferMs());
                player_->play(QUrl(base()+stream));
				audioStartedMs_=QDateTime::currentMSecsSinceEpoch();
				radioCanvasStation_->setText(tr("♪ %1\nDAB+ %2 · verifying audio playback…")
					.arg(name,block));
				playStatus_->setText(tr("LIVE mux lists %1. Opening audio; "
					"receiver lock does not guarantee decoded sound.").arg(name));
				stationOpenProgress_->setValue(4);
				stationOpenProgress_->setFormat(tr("Live service verified · audio opening"));
                // Buffer setup is a requested media-open delay, so do not
                // falsely label a 9.5s cache as failed after just 3.5s.
                // Match the bounded startup timeout shown by the buffer bar.
                const int verificationMs=qMax(12000,activePlaybackCacheMs_+8000);
				QTimer::singleShot(verificationMs,this,[this,requestId,name](){
					if(requestId!=stationRequestId_) return;
					if(player_->getPlaybackStatus()==MediaWidget::Playing) {
						playStatus_->setText(tr("libVLC reports PLAYING · %1 · audible sound NOT confirmed. "
                            "If captions work but audio is silent, check mute, volume, "
                            "Audio outputs... or Retry DAB sound.")
							.arg(name));
						stationOpenProgress_->setFormat(tr("Player reports PLAYING · %1").arg(name));
                        radioCanvasStation_->setText(tr(
                            "♪ %1\nDAB+ %2 · player reports Playing\n"
                            "Audible output is not independently measured.")
                            .arg(name,activeChannel_));
					} else {
						playStatus_->setText(tr("NO AUDIO PLAYBACK reported for %1. "
							"Check welle receiver, AAC decoding and stream endpoint.")
							.arg(name));
						stationOpenProgress_->setFormat(tr("Audio failed / stopped"));
                        radioCanvasStation_->setText(tr(
                            "♪ %1\nDAB+ %2 · decoder/player did not report Playing\n"
                            "Inspect DAB RF errors and local stream.")
                            .arg(name,activeChannel_));
						stationOpenProgress_->setValue(0);
					}
				});
				if(restartAi)
					QTimer::singleShot(900,this,[this,requestId](){
						if(requestId==stationRequestId_) startCaptioning();
					});
			});
		QTimer::singleShot(1700,this,[this,key,name,sid,requestId,attempt,resolved](){
			if(*resolved || requestId!=stationRequestId_) return;
			*resolved=true;
			playStatus_->setText(tr("DAB live mux API timed out; retrying without "
				"opening a nonexistent /mp3 stream."));
			verifyStation(key,name,sid,requestId,attempt+1);
		});
	}
    static QString dabCenterFrequencyMHz(const QString &block) {
        // ETSI DAB Band III nominal ensemble centre frequency in kHz.
        // This is NOT FM station frequency, RSSI or measured SDR offset.
        static const QMap<QString,int> centers = {
            {"5A",174928},{"5B",176640},{"5C",178352},{"5D",180064},
            {"6A",181936},{"6B",183648},{"6C",185360},{"6D",187072},
            {"7A",188928},{"7B",190640},{"7C",192352},{"7D",194064},
            {"8A",195936},{"8B",197648},{"8C",199360},{"8D",201072},
            {"9A",202928},{"9B",204640},{"9C",206352},{"9D",208064},
            {"10A",209936},{"10B",211648},{"10C",213360},{"10D",215072},
            {"11A",216928},{"11B",218640},{"11C",220352},{"11D",222064},
            {"12A",223936},{"12B",225648},{"12C",227360},{"12D",229072},
            {"13A",230784},{"13B",232496},{"13C",234208},{"13D",235776},
            {"13E",237488},{"13F",239200}
        };
        const auto it=centers.constFind(block.toUpper());
        if(it==centers.cend()) return QString();
        return QString::number(it.value()/1000.,'f',3)+
               QStringLiteral(" MHz");
    }
	void showSelectedSource(const QString &name,const QString &mode,
                           const QString &detail) {
        const QString display=tr("%1 · %2 · %3")
            .arg(mode,name.left(120),detail.left(130));
        if(selectedSource_)selectedSource_->setText(display);
        if(selectedStationVintage_)
            selectedStationVintage_->setText(display+tr(
                " · analogue dial remains independent of DAB/Internet"));
        if(vintageDabReadout_) {
            const QRegularExpression blockPattern(
                QLatin1String("\\bBlock\\s+((?:[5-9]|1[0-3])[A-F])\\b"));
            const auto match=blockPattern.match(detail);
            const QString block=match.hasMatch()?match.captured(1):QString();
            const QString mhz=dabCenterFrequencyMHz(block);
            const bool dab=mode.startsWith(QLatin1String("DAB+")) && !mhz.isEmpty();
            vintageDabReadout_->setVisible(dab);
            if(dab) vintageDabReadout_->setText(tr(
                "DAB+ DIGITAL · %1 · Block %2 · %3 (centre frequency)")
                .arg(name,block,mhz));
        }
    }
	void selectStation(QTreeWidgetItem *item) {
		if(!item) return;
        showSelectedSource(item->text(1),tr("DAB+ · tuning"),
            tr("Block %1 · %2 · SID %3")
                .arg(item->text(2),dabCenterFrequencyMHz(item->text(2)),
                     item->text(3)));
		const QString key=item->data(0,Qt::UserRole).toString();
		const QString block=stationChannels_.value(key);
		const QString name=item->text(1),sid=item->text(3);
		if(scanning_) {
			playStatus_->setText(tr("Wait until scan ends before switching station."));
			return;
		}
		if(!QRegularExpression(QLatin1String("^(?:[5-9]|1[0-3])[A-F]$"))
		   .match(block).hasMatch() ||
		   !QRegularExpression(QLatin1String("^(?:0x)?[A-Fa-f0-9]{1,8}$"))
		   .match(sid).hasMatch()) {
			playStatus_->setText(tr("Invalid saved DAB block/service ID; rescan."));
			return;
		}
		if(!active()) {
			startReceiver();
			if(!active()) return;
		}
        // The old station stops temporarily during a new selection.
        // Do not treat this internal retune as a user Stop.
        dabPlaybackObserved_=false;
        dabIdleSinceMs_=0;
		const quint64 requestId=++stationRequestId_;
		player_->stop();
		playingKey_.clear();
		playStatus_->setText(tr("Tuning DAB %1 for %2; checking LIVE service before play.")
			.arg(block,name));
		stationOpenProgress_->setValue(0);
		auto ready=[this,key,name,sid,requestId]() {
			if(requestId==stationRequestId_)
				verifyStation(key,name,sid,requestId);
		};
		if(activeChannel_!=block || !apiReady_) tune(block,ready);
		else ready();
	}

	void toggleRecording() {
		if (recorder_.state()!=QProcess::NotRunning) {
			stopRecording();
			return;
		}
		if (!active() || playingKey_.isEmpty()) {
			state_->setText(tr("Select an actual DAB station before recording."));
			return;
		}
		const QString filename=QFileDialog::getSaveFileName(
			this,tr("Record live DAB station"),QDir::homePath()+QLatin1String("/Radio.mp3"),
			tr("MP3 audio (*.mp3)"));
		if (filename.isEmpty()) return;
		if (QFile::exists(filename)) {
			QMessageBox::information(this,tr("Recording"),
				tr("Recording never overwrites an existing file. Choose another name."));
			return;
		}
		const QString sid=playingKey_.section(QLatin1Char(':'),1);
		if (!QRegularExpression(QLatin1String("^(?:0x)?[A-Fa-f0-9]{1,8}$"))
			.match(sid).hasMatch()) {
			state_->setText(tr("Invalid station ID: recording refused.")); return;
		}
		const QString address=base()+QLatin1String("/mp3/")+sid;
		recorder_.start(QLatin1String("ffmpeg"),
			{QLatin1String("-nostdin"),QLatin1String("-hide_banner"),
			 QLatin1String("-loglevel"),QLatin1String("error"),
			 QLatin1String("-n"),QLatin1String("-i"),address,
			 QLatin1String("-vn"),QLatin1String("-c:a"),QLatin1String("copy"),
			 filename});
		if (recorder_.waitForStarted(1000)) {
			recordedPath_=filename;
			recordWithSubtitles_=subtitledRecord_->isChecked();
			record_->setText(tr("Stop recording"));
			state_->setText(tr("Recording real DAB audio locally to %1").arg(filename));
		} else
			state_->setText(tr("FFmpeg recording could not start."));
	}
	void stopRecording() {
		const bool wasRunning=recorder_.state()!=QProcess::NotRunning;
		if (wasRunning) {
			recorder_.terminate();
			if (!recorder_.waitForFinished(2200))
				recorder_.kill();
		}
		if (record_) record_->setText(tr("Record station"));
		if(!wasRunning || !recordWithSubtitles_ || recordedPath_.isEmpty() ||
		   !QFileInfo(recordedPath_).isFile() || QFileInfo(recordedPath_).size()==0)
			return;
		recordWithSubtitles_=false;
		if(recordAi_.state()!=QProcess::NotRunning) {
			state_->setText(tr("A previous offline recording transcription is still running."));
			return;
		}
        const QStringList targets=selectedRadioTargets();
		QStringList args{QLatin1String("media-captions"),
			QLatin1String("--input"),recordedPath_,
			QLatin1String("--source"),QLatin1String("auto"),
			QLatin1String("--targets"),targets.join(QLatin1Char(','))};
		if(music_->isChecked()) args<<QLatin1String("--music");
		recordAi_.start(QLatin1String("tihulu-tv-center"),args);
		if(!recordAi_.waitForStarted(850))
			state_->setText(tr("Recording saved; could not launch offline caption worker."));
		else state_->setText(tr("Recording saved. Creating accurate offline SRT before MKV mux…"));
	}
	void requestSlide(const QString &sid) {
		if (!active() || sid.isEmpty() || slidePending_) return;
		if (!QRegularExpression(QLatin1String("^[A-Fa-f0-9x]+$"))
			.match(sid).hasMatch()) return;
		slidePending_=true;
		QNetworkReply *reply=network_.get(
			QNetworkRequest(QUrl(base()+QLatin1String("/slide/")+sid)));
		connect(reply,&QNetworkReply::finished,this,[this,reply]() {
			slidePending_=false;
			const QByteArray bytes=reply->readAll();
			const bool ok=reply->error()==QNetworkReply::NoError && bytes.size()<700000;
			reply->deleteLater();
			if (!ok) return;
			QImage image;
			if (image.loadFromData(bytes) && image.width()<2500 && image.height()<2500) {
				const QPixmap candidate=QPixmap::fromImage(image);
				const QByteArray signature=QCryptographicHash::hash(
					bytes,QCryptographicHash::Sha256);
				if (signature!=lastSlideHash_) {
					lastSlideHash_=signature;
					if(slideHistory_.size()>=30) slideHistory_.removeFirst();
					slideHistory_.append(candidate);
					slideIndex_=slideHistory_.size()-1;
				}
				slideMove(0);
			}
		});
	}
	void slideMove(int offset) {
		if (slideHistory_.isEmpty()) return;
		slideIndex_=qBound(0,slideIndex_+offset,slideHistory_.size()-1);
		slide_->setPixmap(slideHistory_.at(slideIndex_).scaled(
			slide_->size(),Qt::KeepAspectRatio,Qt::SmoothTransformation));
		slide_->setToolTip(tr("DAB MOT/SLS slide %1/%2")
			.arg(slideIndex_+1).arg(slideHistory_.size()));
	}
	void fetchPlot(const QString &overrideType=QString(), QLabel *output=nullptr) {
		QLabel *target=output?output:plot_;
		if (!active()) { state_->setText(tr("Start a DAB receiver first.")); return; }
		if(plotPending_) return;
		const QString type=overrideType.isEmpty()?plotKind_->currentData().toString():overrideType;
		if (type!=QLatin1String("spectrum") &&
		    type!=QLatin1String("nullspectrum") &&
		    type!=QLatin1String("impulseresponse") &&
		    type!=QLatin1String("constellation") &&
		    type!=QLatin1String("waterfall")) return;
		plotPending_=true;
		const QString api=type==QLatin1String("waterfall")?
			QLatin1String("spectrum"):type;
		QNetworkReply *reply=network_.get(QNetworkRequest(QUrl(base()+QLatin1Char('/')+api)));
		// Do not leave Live RF permanently locked if the backend stops
		// answering mid-capture.
		QTimer::singleShot(1800,reply,[reply](){
			if(reply->isRunning()) reply->abort();
		});
		connect(reply,&QNetworkReply::finished,this,[this,reply,type,target]() {
			plotPending_=false;
			const QByteArray raw=reply->readAll();
			const bool okay=reply->error()==QNetworkReply::NoError &&
				raw.size()>=32 && raw.size()<=262144 && raw.size()%4==0;
			reply->deleteLater();
			if (!okay) {
				target->setToolTip(tr("No fresh RF data; retaining last valid plot. "
				"Check SDR signal, lock and backend load."));
				return;
			}
			const int count=raw.size()/4;
			const int steps=qMin(count,500);
			QVector<double> points;
			points.reserve(steps);
			for (int i=0;i<steps;++i) {
				const int offset=((qint64)i*count/steps)*4;
				float value=0;
				memcpy(&value,raw.constData()+offset,sizeof(float));
				points.append(std::isfinite(value)?value:0.0);
			}
			if (points.isEmpty()) return;
			const auto mm=std::minmax_element(points.cbegin(),points.cend());
			const double lo=*mm.first,hi=*mm.second;
			if (type==QLatin1String("waterfall")) {
				const QSize size=target->size();
				if(waterfall_.size()!=size) {
					waterfall_=QImage(size,QImage::Format_RGB32);
					waterfall_.fill(QColor("#0e2536"));
				}
				QImage previous=waterfall_.copy();
				QPainter painter(&waterfall_);
				painter.drawImage(QPoint(0,1),previous,
					QRect(0,0,size.width(),size.height()-1));
				for(int x=0;x<size.width();++x) {
					const double level=points[qBound(0,
						int(double(x)*points.size()/qMax(1,size.width())),
						points.size()-1)];
					const double magnitude=qBound(0.,(level-lo)/qMax(.0001,hi-lo),1.);
					const QColor color=QColor::fromHsv(
						qBound(0,230-int(230*magnitude),230),230,
						qBound(25,25+int(230*magnitude),255));
					painter.setPen(color);
					painter.drawPoint(x,0);
				}
				painter.end();
				target->setPixmap(QPixmap::fromImage(waterfall_));
				return;
			}
			QImage picture(target->width(),target->height(),QImage::Format_ARGB32);
			picture.fill(QColor("#101d2a"));
			QPainter p(&picture);
			p.setRenderHint(QPainter::Antialiasing);
			p.setPen(QPen(QColor("#64cfed"),1.5));
			QPolygonF poly;
			for (int i=0;i<points.size();++i) {
				const double x=8+(picture.width()-16.)*i/qMax(1,points.size()-1);
				const double y=picture.height()-9-
					(picture.height()-18.)*(points[i]-lo)/qMax(.0000001,hi-lo);
				poly<<QPointF(x,y);
			}
			p.drawPolyline(poly);
			target->setPixmap(QPixmap::fromImage(picture));
			target->setToolTip(tr("%1 receiver RF samples (native float32; signal dependent)")
				.arg(type));
		});
	}
	void sendRfOption(const QString &endpoint, const QByteArray &body) {
		if (!active()) {
			state_->setText(tr("Start the local DAB receiver first."));
			return;
		}
		QNetworkRequest req(QUrl(base()+endpoint));
		req.setHeader(QNetworkRequest::ContentTypeHeader,QLatin1String("text/plain"));
		QNetworkReply *reply=network_.post(req,body);
		connect(reply,&QNetworkReply::finished,this,[this,reply,endpoint]() {
			const bool okay=reply->error()==QNetworkReply::NoError;
			reply->deleteLater();
			if (!okay)
				state_->setText(tr("Receiver rejected RF option %1").arg(endpoint));
		});
	}
	void applyRfOptions() {
		const QString fft=fftPlacement_->currentData().toString();
		const QStringList allowed={
			"EarliestPeakWithBinning","StrongestPeak","ThresholdBeforePeak"};
		if (!allowed.contains(fft)) return;
		sendRfOption(QLatin1String("/fftwindowplacement"),fft.toUtf8());
		sendRfOption(QLatin1String("/enablecoarsecorrector"),
			coarseCorrector_->isChecked()?"1":"0");
		state_->setText(tr("Requested local welle.io FFT/coarse correction options."));
	}
    void retryDabAudioPlayback() {
        if(!active() || playingKey_.isEmpty() || scanning_) {
            radioAudioOutputStatus_->setText(
                tr("Select an active DAB station before retrying sound."));
            return;
        }
        const QString sid=playingKey_.section(QLatin1Char(':'),1);
        if(!QRegularExpression(QLatin1String("^(?:0x)?[A-Fa-f0-9]{1,8}$"))
            .match(sid).hasMatch()) {
            radioAudioOutputStatus_->setText(tr("Invalid DAB service ID; retry cancelled."));
            return;
        }
        const QUrl audio(base()+QLatin1String("/mp3/")+sid);
        if(!audio.isValid() || audio.host()!=QLatin1String("127.0.0.1")) {
            radioAudioOutputStatus_->setText(tr("Invalid local MP3 endpoint; retry cancelled."));
            return;
        }
        // Explicit opt-in; do not touch welle-cli, SDR, Whisper or recording.
        if(player_->getVolume()==0) player_->setVolume(70);
        player_->stop();
        dabPlaybackObserved_=false;
        dabIdleSinceMs_=0;
        player_->play(audio);
        audioStartedMs_=QDateTime::currentMSecsSinceEpoch();
        lastAudioRetuneMs_=audioStartedMs_;
        playStatus_->setText(tr(
            "Manual DAB audio reopen · receiver / ASR unchanged. "
            "Check the main mute control and system output sink."));
        radioAudioOutputStatus_->setText(tr(
            "Retrying libVLC sound only. PLAYING does not prove audible speaker output."));
    }
    void showRadioAudioDiagnostics() {
        auto *dlg=new QDialog(this);
        dlg->setAttribute(Qt::WA_DeleteOnClose);
        dlg->setWindowTitle(tr("DAB audio · output routing diagnostics"));
        dlg->resize(760,470);
        auto *layout=new QVBoxLayout(dlg);
        auto *report=new QPlainTextEdit(dlg);
        report->setReadOnly(true);
        report->setPlainText(tr(
            "ASR subtitles use a separate audio input; output can be silent.\n"
            "libVLC: %1 | Volume: %2%\n"
            "SDR: %3 | DAC audio and mute state: not measured.\n\n"
            "Check Playback > Audio > Audio Device (native Kaffeine menu),\n"
            "the main mute button and your system Sound output settings.\n")
            .arg(player_->getPlaybackStatus()==MediaWidget::Playing?
                tr("PLAYING (not audible proof)"):tr("not PLAYING"))
            .arg(player_->getVolume())
            .arg(active()?tr("welle-cli active"):tr("not running")));
        layout->addWidget(report,1);
        auto *close=new QPushButton(tr("Close"),dlg);
        layout->addWidget(close);
        connect(close,&QPushButton::clicked,dlg,&QDialog::close);
        const QString wpctl=QStandardPaths::findExecutable(QLatin1String("wpctl"));
        const QString pactl=QStandardPaths::findExecutable(QLatin1String("pactl"));
        const QString command=wpctl.isEmpty()?pactl:wpctl;
        if(command.isEmpty()) {
            report->appendPlainText(tr("No wpctl/pactl binary; inspect system Sound settings."));
        } else {
            const QStringList arguments=wpctl.isEmpty()?
                QStringList{QLatin1String("info")}:
                QStringList{QLatin1String("status")};
            report->appendPlainText(tr("Read-only: %1 %2\n")
                .arg(command,arguments.join(QLatin1Char(' '))));
            auto *probe=new QProcess(dlg);
            connect(probe,&QProcess::readyReadStandardOutput,dlg,[probe,report](){
                report->insertPlainText(
                    QString::fromLocal8Bit(probe->readAllStandardOutput()).left(18000));
            });
            connect(probe,&QProcess::readyReadStandardError,dlg,[probe,report](){
                report->insertPlainText(
                    QString::fromLocal8Bit(probe->readAllStandardError()).left(4000));
            });
            connect(probe,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
                    dlg,[report](int code,QProcess::ExitStatus){
                report->appendPlainText(
                    QObject::tr("\nAudio routing query ended (%1).").arg(code));
            });
            connect(dlg,&QDialog::finished,probe,[probe](int){
                if(probe->state()!=QProcess::NotRunning) {
                    probe->kill();
                    probe->waitForFinished(150);
                }
            });
            probe->start(command,arguments);
        }
        dlg->show();
    }
	void showReceiverDetails() {
		if (lastMux_.isEmpty()) {
			QMessageBox::information(this,tr("Receiver diagnostics"),
                tr("No fresh RF metrics. Native DAB: %1\n"
                   "Binary: %2\nVerified local installation: %3\n"
                   "The antenna alone does not start welle-cli. The SDR must "
                   "be unclaimed and the local API must answer.\n"
                   "Useful checks: lsusb; pgrep -af 'readsb|rtl_tcp|welle-cli'; "
                   "ss -lntp | grep 127.0.0.1")
                   .arg(hardwareDabStatus(),binaryPath(),
                        prepared()?tr("yes"):tr("no")));
			return;
		}
		QDialog dlg(this);
		dlg.setWindowTitle(tr("Native welle.io · receiver / station / TII diagnostics"));
		dlg.resize(850,560);
		auto *layout=new QVBoxLayout(&dlg);
		auto *note=new QLabel(tr("Raw local receiver diagnostics. The FFT, null "
			"spectrum, constellation and CIR graphs are shown in the Radio tab."),&dlg);
		note->setWordWrap(true);
		layout->addWidget(note);
		auto *textView=new QPlainTextEdit(&dlg);
		textView->setReadOnly(true);
		textView->setPlainText(QString::fromUtf8(
			QJsonDocument(lastMux_).toJson(QJsonDocument::Indented)));
		layout->addWidget(textView);
		dlg.exec();
	}
    void refreshRadioBufferProgress() {
        if(!quickBufferProgress_ || !audioCacheProgress_ || !quickBuffer_) return;
        const bool enabled=quickBuffer_->isChecked();
        quickBufferProgress_->setVisible(enabled);
        audioCacheProgress_->setVisible(enabled);
        if(!enabled) return;
        const int requested=activePlaybackCacheMs_;
        const int staged=requestedPlaybackBufferMs();
        const qint64 elapsed=audioStartedMs_>0?
            qMax(qint64(0),QDateTime::currentMSecsSinceEpoch()-audioStartedMs_):0;
        const bool receiving=active();
        const bool stationSelected=!playingKey_.isEmpty() && audioStartedMs_>0;
        const bool playing=stationSelected && receiving &&
            player_->getPlaybackStatus()==MediaWidget::Playing;
        // This timeout is NOT a measured buffer duration. Once the
        // requested time + an 8s decoder grace period has elapsed, stop
        // pretending the still-silent player is continuously filling.
        // A 12s minimum allows short/zero-cache startup some tolerance.
        const qint64 startupTimeoutMs=qMax(qint64(12000),
                                            qint64(requested)+8000);
        int percent=0;
        QString message;
        if(!receiving && stationSelected) {
            message=tr("DAB receiver stopped / crashed · no audio buffer "
                       "measurement. Check welle-cli status and restart "
                       "receiver manually.");
        } else if(!stationSelected) {
            message=tr("Extra buffer ON · %1 ms requested for next DAB "
                       "playback; no stream currently opening").arg(staged);
        } else if(playing) {
            // 100% means only that libVLC has STARTED playback, never that
            // the requested cache size was measured or fully populated.
            percent=100;
            message=tr("Audio player STARTED · requested cache %1 ms · "
                       "actual fill and audible output NOT measured").arg(requested);
        } else if(elapsed>=startupTimeoutMs) {
            // Distinct terminal state: never remain at 90/95% for minutes.
            // Keep SDR, ASR and recordings untouched until explicit Retry.
            percent=0;
            message=tr("DAB AUDIO STARTUP FAILED / TIMEOUT · player did not "
                       "report PLAYING within %1 ms (requested %2 ms cache). "
                       "NOT buffering. Check welle / MP3 endpoint / audio "
                       "output; choose Retry DAB sound. No auto restart.")
                       .arg(startupTimeoutMs).arg(requested);
        } else if(requested>0) {
            // Bounded display: even when the player is stuck, never show
            // elapsed > requested as if a real libVLC queue kept growing.
            const qint64 bounded=qMin(elapsed,qint64(requested));
            percent=qMin(90,int(bounded*90/requested));
            if(elapsed<=requested)
                message=tr("Waiting for DAB player · %1 / %2 ms estimated "
                           "startup window (%3%); buffer fill unmeasured")
                           .arg(bounded).arg(requested).arg(percent);
            else
                message=tr("Requested %1 ms cache startup window elapsed · "
                           "decoder still not PLAYING (grace until %2 ms). "
                           "No actual buffer measurement.")
                           .arg(requested).arg(startupTimeoutMs);
        } else {
            message=tr("Opening DAB player · no extra cache requested. "
                       "Audio startup still unverified.");
        }
        if(staged!=requested && stationSelected)
            message+=tr(" · next station request: %1 ms").arg(staged);
        for(QProgressBar *bar:{quickBufferProgress_,audioCacheProgress_}) {
            bar->setRange(0,100);
            bar->setValue(percent);
            bar->setFormat(message);
        }
    }
	int selectedBufferMs() const {
        return qBound(0,bufferMs_->value()*(bufferUnitsSeconds_?1000:1),60000);
    }
    int requestedPlaybackBufferMs() const {
        return quickBuffer_->isChecked()?selectedBufferMs():0;
    }
    void setBufferDisplayMs(int milliseconds) {
        const int bounded=qBound(0,milliseconds,60000);
        const QSignalBlocker block(bufferMs_);
        bufferMs_->setValue(bufferUnitsSeconds_?
            qBound(0,(bounded+500)/1000,60):bounded);
    }
    void applyRadioBuffer() {
		QSettings radioSettings(QLatin1String("TIHULU"),QLatin1String("KaffeineRadio"));
		const int desired=requestedPlaybackBufferMs();
        radioSettings.setValue(QLatin1String("radioBufferDesiredMs"),selectedBufferMs());
        radioSettings.setValue(QLatin1String("radioBufferEnabled"),
                               quickBuffer_->isChecked());
        radioSettings.setValue(QLatin1String("playbackBufferMs"),desired);
        radioSettings.sync();
        if(desired==activePlaybackCacheMs_) {
            syncStatus_->setText(tr("Radio extra buffer unchanged: %1 ms. "
                "No audio restart.").arg(desired));
            return;
        }
		if (!playingKey_.isEmpty() && active()) {
			const QString sid=playingKey_.section(QLatin1Char(':'),1);
			if (!QRegularExpression(QLatin1String("^(?:0x)?[A-Fa-f0-9]{1,8}$"))
				.match(sid).hasMatch()) return;
			// libVLC network cache applies to media OPEN, not existing
			// stream. Explicitly reopen when the owner chooses a new
			// buffer; this can briefly interrupt sound.
			player_->play(QUrl(base()+QLatin1String("/mp3/")+sid));
            activePlaybackCacheMs_=desired;
            lastAudioRetuneMs_=QDateTime::currentMSecsSinceEpoch();
            audioStartedMs_=lastAudioRetuneMs_;
            const bool wasAiRunning=captionProcess_.state()!=QProcess::NotRunning;
            if(wasAiRunning) stopCaptioning();
			lastRadioChunk_=-1; lastRadioRevision_=-1;
			displayedRadioChunk_=-1;
			cueQueue_.clear();
			plainLyricQueue_.clear();
			pendingRadioCue_.clear();
			lastAdjustmentMs_=QDateTime::currentMSecsSinceEpoch();
            if(wasAiRunning)
                QTimer::singleShot(400,this,[this](){
                    if(active() && !playingKey_.isEmpty())startCaptioning();
                });
			syncStatus_->setText(tr("Requested %1ms cache at media reopen; "
                "captions restarted to discard old audio timeline. DAC delay unverified.")
				.arg(activePlaybackCacheMs_));
		} else {
			syncStatus_->setText(tr("Extra cache %1ms saved for the next station. "
                "No receiver restart.").arg(desired));
		}
	}
    void scheduleCaptionRecovery() {
        if(!quickAi_ || !quickAi_->isChecked() || shuttingDown_ ||
           tvHandoffInProgress_ || scanning_) return;
        const qint64 now=QDateTime::currentMSecsSinceEpoch();
        // Backoff 2, 4, 8, 16, up to 60 seconds, never a busy loop.
        const int shift=qMin(captionRecoveryFailures_,5);
        const qint64 delay=qMin(qint64(60000),qint64(2000)*(1LL<<shift));
        captionRecoveryFailures_=qMin(captionRecoveryFailures_+1,6);
        captionRecoveryNextMs_=qMax(captionRecoveryNextMs_,now+delay);
    }
    void checkCaptionRecovery() {
        if(!quickAi_ || !quickAi_->isChecked() || shuttingDown_ ||
           scanning_ || tvHandoffInProgress_ || !active() ||
           playingKey_.isEmpty() || !captionSource_ ||
           captionSource_->currentData().toString()==QLatin1String("dls"))
            return;
        const qint64 now=QDateTime::currentMSecsSinceEpoch();
        if(captionProcess_.state()!=QProcess::NotRunning) {
            // Reset retry backoff only after a real ASR chunk, not after
            // QProcess::start() or an unverified player "Playing" status.
            if(lastCaptionUpdateMs_>captionRecoveryLastSuccessMs_ &&
               lastCaptionUpdateMs_>captionRecoveryLastAttemptMs_) {
                captionRecoveryFailures_=0;
                captionRecoveryNextMs_=0;
                captionRecoveryLastSuccessMs_=lastCaptionUpdateMs_;
            }
            return;
        }
        if(captionRecoveryNextMs_<=0)
            scheduleCaptionRecovery();
        if(now<captionRecoveryNextMs_) return;
        captionRecoveryNextMs_=0;
        captionRecoveryLastAttemptMs_=now;
        if(radioCaptionBanner_) {
            radioCaptionBanner_->setText(tr(
                "AI captions ON · reconnecting Whisper to existing DAB audio "
                "(radio playback and SDR unchanged)"));
            radioCaptionBanner_->setVisible(true);
        }
        startCaptioning();
        // FailedToStart and immediate EOF must also have a bounded retry.
        if(captionRecoveryNextMs_<=0) scheduleCaptionRecovery();
    }
	void startCaptioning() {
		if (!active() || playingKey_.isEmpty()) {
			state_->setText(tr("Play a real DAB+ station before starting offline AI.")); return;
		}
		if (captionSource_->currentData().toString()==QLatin1String("dls")) {
			stopCaptioning();
			metadataCaptions_=true;
			lastRadioChunk_=-1; lastRadioRevision_=-1;
			displayedRadioChunk_=-1;
			radioCaption_->setText(tr("Broadcaster DLS selected. "
				"This is NOT a subtitle or spoken transcript; "
				"text is delayed only by the requested buffer and offset."));
			if(!lastDls_.isEmpty())
				cueQueue_.append({++dlsCaptionIndex_,
					QDateTime::currentMSecsSinceEpoch()+activePlaybackCacheMs_+
					radioOffsetMs_->value(),
					QDateTime::currentMSecsSinceEpoch(),
					tr("[DLS broadcaster metadata] %1").arg(lastDls_).left(700)});
			return;
		}
		metadataCaptions_=false;
		if (captionProcess_.state()!=QProcess::NotRunning) return;
        captionRecoveryLastAttemptMs_=QDateTime::currentMSecsSinceEpoch();
        captionBoundStationKey_=playingKey_;
		const QString sid=playingKey_.section(QLatin1Char(':'),1);
		const QString sourceCode=speechLanguage_->currentData().isValid()?
			speechLanguage_->currentData().toString():
			speechLanguage_->currentText().trimmed();
		QStringList options{QLatin1String("radio-captions"),
			QLatin1String("--port"),QString::number(port_),
			QLatin1String("--sid"),sid,
			QLatin1String("--source"),sourceCode};
        const QStringList targets=selectedRadioTargets();
		options<<QLatin1String("--targets")<<targets.join(QLatin1Char(','));
		const int sentenceHops=activePlaybackCacheMs_<8000?2:
			activePlaybackCacheMs_<14000?3:activePlaybackCacheMs_<18500?4:5;
        options<<QLatin1String("--sentence-hops")<<QString::number(sentenceHops);
        options<<QLatin1String("--lyric-match-threshold")
               <<QString::number(lyricMatchThreshold_?
                                  lyricMatchThreshold_->value()/100.:0.74,'f',2);
        options<<QLatin1String("--lyric-match-mode")
               <<(lyricMatchMode_?lyricMatchMode_->currentData().toString():
                                   QLatin1String("lexical"));
        options<<QLatin1String("--karaoke-aligner")
               <<(karaokeAligner_?karaokeAligner_->currentData().toString():
                                   QLatin1String("auto"));
        // Transfer the CURRENT desktop radio timing settings to the
        // separately paired phone. This is a requested native audio cache,
        // not a measured DAC clock. The mobile browser must NOT blindly
        // add this host delay again when decoding its own HLS stream.
        options<<QLatin1String("--host-audio-cache-ms")
               <<QString::number(activePlaybackCacheMs_);
        options<<QLatin1String("--host-caption-offset-ms")
               <<QString::number(radioOffsetMs_->value());
		if (music_->isChecked() || lyricsAudioFallbackActive_)
            options<<QLatin1String("--music");
        if(quickTranslate_ && quickTranslate_->isChecked())
            options<<QLatin1String("--radio-translations");
        if(soundLabels_ && soundLabels_->isChecked())
            options<<QLatin1String("--sound-labels");
		if (preferLyrics_->isChecked())
			options<<QLatin1String("--prefer-verified-lyrics");
		if (speakerLabels_->isChecked() && !music_->isChecked() &&
            !lyricsAudioFallbackActive_)
			options<<QLatin1String("--speaker-labels");
		const QString runtime=QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
		if (runtime.isEmpty()) return;
		captionPath_=runtime + QLatin1String("/tihulu-radio-captions-")+
			QString::number(QCoreApplication::applicationPid())+QLatin1String(".json");
        captionControlsPath_=runtime+QLatin1String("/tihulu-radio-controls-")+
            QString::number(QCoreApplication::applicationPid())+
            QLatin1String(".json");
        if(!writeRadioLanguageControls()) {
            captionControlsPath_.clear();
            radioCaption_->setText(tr("Cannot save private AI controls; "
                "Whisper was not started."));
            return;
        }
		options<<QLatin1String("--output")<<captionPath_
               <<QLatin1String("--controls")<<captionControlsPath_;
		QFile::remove(captionPath_);
		captionProcess_.start(QLatin1String("tihulu-tv-center"),options);
        if (!captionProcess_.waitForStarted(1200)) {
            radioCaption_->setText(tr("Offline radio AI sidecar could not start."));
            captionProgress_->setVisible(false);
        } else {
            captionProgress_->setVisible(true);
            captionProgress_->setRange(0,0);
            captionProgress_->setFormat(tr(
                "Whisper starting · collecting ~5 s of real DAB audio…"));
            // Only a REAL decoded Whisper chunk may count as success
            // for the ASR reconnection backoff.
            radioCaption_->setText(tr("Offline radio ASR/translation started. "
                "Radio audio plays independently; heavy AI may fall behind."));
        }
	}
    void clearKaraokeLine() {
        lastKaraokeUntilMs_=0;
        if(karaokePanel_) karaokePanel_->setVisible(false);
        if(karaokeCurrent_) karaokeCurrent_->clear();
        if(karaokeTranslation_) karaokeTranslation_->clear();
        karaokeLine_.clear();
        karaokeWordAnchors_=QJsonArray();
        lastHighlightedKaraokeWord_=-2;
        previewLastHighlightedWord_=-2;
    }
    QString liveRadioLyricsCatalogPath() const {
        // radio_ai.py derives this stable per-session path by replacing
        // "tihulu-radio-captions-" with "tihulu-radio-lyrics-".
        // Search jobs keep generation-suffixed temporary output;
        // only an accepted current-song result is published here.
        const QString runtime=QStandardPaths::writableLocation(
            QStandardPaths::RuntimeLocation);
        if(runtime.isEmpty()) return QString();
        return runtime+QLatin1String("/tihulu-radio-lyrics-")+
            QString::number(QCoreApplication::applicationPid())+
            QLatin1String(".json");
    }
    void clearLiveRadioLyricsCatalog() {
        const QString path=liveRadioLyricsCatalogPath();
        if(!path.isEmpty()) QFile::remove(path);
    }
    bool publishLiveRadioLyricsCatalog(const QJsonObject &lyrics) {
        if(lyrics.value(QLatin1String("status")).toString()!=
           QLatin1String("completed")) return false;
        if(lyrics.value(QLatin1String("plain_lines")).toArray().isEmpty() &&
           lyrics.value(QLatin1String("cues")).toArray().isEmpty()) return false;
        const QString path=liveRadioLyricsCatalogPath();
        if(path.isEmpty()) return false;
        const QByteArray data=QJsonDocument(lyrics).toJson(
            QJsonDocument::Compact);
        if(data.isEmpty() || data.size()>120000) return false;
        QSaveFile output(path);
        if(!output.open(QIODevice::WriteOnly)) return false;
        if(output.write(data)!=data.size()) return false;
        return output.commit();
    }
    void renderFullLyricsWindow(QLabel *info,QPlainTextEdit *view) {
        if(!info || !view) return;
        const TihuluDlsSong song=lastAcceptedSongHint_;
        const QString songName=song.valid()?
            song.artist+QLatin1String(" — ")+song.title:
            tr("Current radio station · song unknown");
        // A source may contain only LRC cues, even if its alignment_mode
        // flags a plain-text workflow. Prefer any actual loaded text over
        // an empty array; never show "found" based on metadata alone.
        const bool timed=!lyricCues_.isEmpty() &&
            (!plainLyricMode_ || lyricRawLines_.isEmpty());
        const int count=timed?lyricCues_.size():lyricRawLines_.size();
        const qint64 now=QDateTime::currentMSecsSinceEpoch();
        const bool audioVerified=lastVerifiedLyricMs_>0 &&
            now-lastVerifiedLyricMs_<12000;
        const QString proof=audioVerified?
            tr("recent audio-matched Whisper lyrics"):
            tr("retrieved text · NOT audio-verified");
        info->setText(tr("%1\nSOURCE: %2 · %3\n%4 · %5 lyric lines · "
                         "Karaoke/Reading remain independent")
            .arg(songName.left(200),
                 lastLyricsProvider_.isEmpty()?tr("unknown / local file"):
                    lastLyricsProvider_.left(80),
                 proof,timed?tr("Timed LRC"):tr("Plain TXT"))
            .arg(count));
        int currentLine=-1;
        if(audioVerified && !lastVerifiedLyricText_.isEmpty()) {
            for(int i=0;i<count && i<350;++i) {
                const QString line=timed?lyricCues_.at(i).toObject()
                    .value(QLatin1String("text")).toString():
                    lyricRawLines_.at(i);
                if(line.trimmed().compare(
                    lastVerifiedLyricText_.trimmed(),Qt::CaseInsensitive)==0) {
                    currentLine=i;
                    break;
                }
            }
        } else if(karaokePolicy_ &&
                 (karaokePolicy_->currentData().toString()==QLatin1String("found") ||
                  karaokePolicy_->currentData().toString()==QLatin1String("found-sync")))
            currentLine=previewLastIndex_; // ESTIMATED, never proof of singing
        QString all;
        if(count<=0) {
            all=tr("No usable lyric TEXT is loaded. A broadcaster DLS song "
                   "title or a LYRICS FOUND status is not itself song words.\n"
                   "Use Lyrics Refresh for the stable artist/title or import "
                   "an authorized TXT/LRC file.\n"
                   "Full Lyrics never starts network or SDR operations.");
        } else {
            for(int i=0;i<count && i<350 && all.size()<70000;++i) {
                const QJsonObject cue=timed?
                    lyricCues_.at(i).toObject():QJsonObject();
                const QString words=timed?
                    cue.value(QLatin1String("text")).toString().left(500):
                    lyricRawLines_.at(i).left(500);
                if(words.trimmed().isEmpty()) continue;
                QString timestamp;
                if(timed) {
                    const double seconds=cue.value(
                        QLatin1String("start")).toDouble(-1.);
                    if(seconds>=0. && seconds<86400.) {
                        const int whole=int(seconds);
                        timestamp=QString::number(whole/60)
                            .rightJustified(2,QLatin1Char('0'))+
                            QLatin1Char(':')+
                            QString::number(whole%60)
                            .rightJustified(2,QLatin1Char('0'))+
                            QLatin1String("  ");
                    }
                }
                all+=(i==currentLine?QLatin1String("▶ "):
                      QLatin1String("  "))+timestamp+words.trimmed()+
                      QLatin1Char('\n');
                const QJsonObject translations=cue.value(
                    QLatin1String("translations")).toObject();
                for(const QString &lang:selectedRadioTargets()) {
                    const QString translated=translations.value(lang)
                        .toString().trimmed();
                    if(!translated.isEmpty())
                        all+=QLatin1String("   [")+lang.toUpper()+
                            QLatin1String("] ")+translated.left(500)+
                            QLatin1Char('\n');
                }
                all+=QLatin1Char('\n');
            }
            if(count>350) all+=tr("… Remaining lyric lines omitted");
        }
        if(view->toPlainText()!=all) {
            const int scroll=view->verticalScrollBar()->value();
            view->setPlainText(all);
            view->verticalScrollBar()->setValue(scroll);
        }
    }
    void showFullLyricsWindow() {
        if(fullLyricsDialog_) {
            fullLyricsDialog_->showNormal();
            fullLyricsDialog_->raise();
            fullLyricsDialog_->activateWindow();
            return;
        }
        auto *dialog=new QDialog(this,Qt::Window);
        dialog->setAttribute(Qt::WA_DeleteOnClose);
        dialog->setWindowTitle(tr("TIHULU · Full Lyrics"));
        dialog->resize(760,660);
        auto *layout=new QVBoxLayout(dialog);
        auto *header=new QLabel(dialog);
        header->setWordWrap(true);
        header->setTextFormat(Qt::PlainText);
        layout->addWidget(header);
        auto *view=new QPlainTextEdit(dialog);
        view->setReadOnly(true);
        view->setLineWrapMode(QPlainTextEdit::WidgetWidth);
        layout->addWidget(view,1);
        auto *close=new QPushButton(tr("Close Full Lyrics"),dialog);
        layout->addWidget(close);
        connect(close,&QPushButton::clicked,dialog,&QDialog::close);
        fullLyricsDialog_=dialog;
        connect(dialog,&QObject::destroyed,this,
                [this](){fullLyricsDialog_=nullptr;});
        renderFullLyricsWindow(header,view);
        auto *timer=new QTimer(dialog);
        timer->setInterval(950);
        connect(timer,&QTimer::timeout,dialog,[this,header,view](){
            renderFullLyricsWindow(header,view);
        });
        timer->start();
        dialog->show();
        dialog->raise();
        dialog->activateWindow();
        if(lyricsSyncState_)
            lyricsSyncState_->setText(tr(
                "Full Lyrics window opened · %1 actual lines loaded · source %2")
                .arg(lyricRawLines_.isEmpty()?lyricCues_.size():
                     lyricRawLines_.size())
                .arg(lastLyricsProvider_.isEmpty()?tr("unknown"):
                     lastLyricsProvider_));
    }
    void pruneRecentKaraokeEvidence(qint64 now) {
        const qint64 windowMs=qint64(karaokeSyncHistorySeconds_?
            karaokeSyncHistorySeconds_->value():10)*1000;
        while(!recentKaraokeEvidence_.isEmpty() &&
              (recentKaraokeEvidence_.first().receivedMs<now-windowMs ||
               recentKaraokeEvidence_.first().stationKey!=playingKey_ ||
               recentKaraokeEvidence_.first().songKey!=lastSongMetadataKey_))
            recentKaraokeEvidence_.removeFirst();
        while(recentKaraokeEvidence_.size()>48)
            recentKaraokeEvidence_.removeFirst();
    }
    void rememberKaraokeEvidence(const TimedPlainLyric &cue,qint64 now) {
        if(cue.lineIndex<0 || cue.original.isEmpty()) return;
        recentKaraokeEvidence_.append(RecentKaraokeEvidence(
            now,playingKey_,lastSongMetadataKey_,cue));
        pruneRecentKaraokeEvidence(now);
    }
    void refreshRadioCaptionLipSync() {
        const qint64 now=QDateTime::currentMSecsSinceEpoch();
        // Whisper speech subtitle timing ONLY; no karaoke queue changes.
        // No audio, capture worker, speaker or SDR restart.
        lagSamples_.clear();
        lastAdjustmentMs_=now;
        int adjusted=0;
        for(auto &cue:cueQueue_) {
            if(cue.unoffsetDueMs<=0 ||
               cue.chunkIndex<=displayedRadioChunk_)
                continue;
            const int cacheDelta=cue.requestedCacheAtQueueMs>=0?
                activePlaybackCacheMs_-cue.requestedCacheAtQueueMs:0;
            cue.dueMs=qMax(now,cue.unoffsetDueMs+
                radioOffsetMs_->value()+cacheDelta);
            ++adjusted;
        }
        displayDueRadioCues(now);
        if(syncStatus_) syncStatus_->setText(tr(
            "AI Lip-sync Refresh · %1 queued Whisper subtitle(s) retimed · "
            "caption offset %2 ms · requested cache %3 ms. "
            "Old speech NOT replayed; Karaoke model/words untouched; "
            "DAC latency not measured.")
            .arg(adjusted).arg(radioOffsetMs_?radioOffsetMs_->value():0)
            .arg(activePlaybackCacheMs_));
    }
    void refreshRadioLipSync() {
        const qint64 now=QDateTime::currentMSecsSinceEpoch();
        // Karaoke-only sync. Normal speech queue/lag estimator is separate.
        lyricOffsetConsistency_=0;
        lastLyricDirection_=0;
        lastLyricSyncUpdateMs_=0;
        // Request re-acquisition from the ALREADY RUNNING offline Whisper
        // worker: compare recent real ASR text against the full song catalog.
        // No second SDR, playback buffer reset, or ASR restart.
        const bool canRematch=captionProcess_.state()!=QProcess::NotRunning &&
            !captionControlsPath_.isEmpty() && lyricsEnabled_ && lyricLoaded_ &&
            (!lyricRawLines_.isEmpty() || !lyricCues_.isEmpty());
        bool requestedRematch=false;
        if(canRematch) {
            if(karaokeSyncRefreshToken_>=2147483647)
                karaokeSyncRefreshToken_=0;
            ++karaokeSyncRefreshToken_;
            requestedRematch=writeRadioLanguageControls();
        }

        // Karaoke has its own offset: the AI caption offset cannot move
        // the lyric line/word clock or affect Karaoke Lip-sync Refresh.
        int reanchored=0;
        const auto updatePending=[this,now,&reanchored](
                QList<TimedPlainLyric> &queue) {
            for(auto &entry:queue) {
                if(entry.wordAnchors.isEmpty()) continue;
                const qint64 captured=qRound64(entry.wordAnchors.first()
                    .toObject().value(QLatin1String("epoch_ms")).toDouble(0.));
                if(captured<=now-120000 || captured>=now+20000)
                    continue;
                entry.dueMs=qMax(now,captured+activePlaybackCacheMs_+
                    lyricsOffset_->value());
                ++reanchored;
            }
        };
        updatePending(verifiedLyricQueue_);
        updatePending(plainLyricQueue_);
        // A user refresh must not restart a song or re-download lyrics.
        // For a verified line redraw unchanged Whisper word anchors.
        // Unverified Lyrics Found stays STATIC, without estimated time
        // or interpolation. Reuse captured evidence; no
        // new 10s waiting period, audio-buffer flush or ASR re-inference.
        pruneRecentKaraokeEvidence(now);
        int reused=0;
        if(player_ && player_->getPlaybackStatus()==MediaWidget::Playing &&
           karaokeEnabled_ && karaokeEnabled_->isChecked()) {
            for(int i=recentKaraokeEvidence_.size()-1;i>=0;--i) {
                const RecentKaraokeEvidence &e=recentKaraokeEvidence_.at(i);
                if(e.stationKey!=playingKey_ ||
                   e.songKey!=lastSongMetadataKey_ ||
                   e.cue.wordAnchors.isEmpty()) continue;
                // Re-show the last truly heard line and recompute its
                // EXISTING word timestamps at the current user offsets.
                // Never synthesize unheard lyrics from DLS/LRC times.
                showKaraokeLine(e.cue);
                reused=e.cue.wordAnchors.size();
                break;
            }
        }
        lastHighlightedKaraokeWord_=-2;
        refreshKaraokeWordHighlight(now);
        // Preview has no independent moving playhead anymore.
        const QString policy=karaokePolicy_?
            karaokePolicy_->currentData().toString():QString();
        const bool preview=policy==QLatin1String("found") ||
                           policy==QLatin1String("found-sync");
        if(lyricsSyncState_) lyricsSyncState_->setText(tr(
            "Karaoke Sync Refresh · %1 · recent history %2s "
            "(%3 verified word anchors, %4 queued cues updated). "
            "%5 · manual offset %6 ms retained · DAC not measured.")
            .arg(requestedRematch?
                 tr("Whisper re-match requested; next audio hop will confirm"):
                 tr("no active Whisper + lyric catalog; no new match"))
            .arg(karaokeSyncHistorySeconds_?
                karaokeSyncHistorySeconds_->value():10)
            .arg(reused).arg(reanchored)
            .arg(preview?tr("Lyrics Found preview stays unverified"):
                         tr("audio-verified words only"))
            .arg(lyricsOffset_?lyricsOffset_->value():0));
        syncStatus_->setText(tr(
            "Karaoke Refresh: %5. Requested playback cache %1ms unchanged; "
            "SDR/Whisper not restarted. Reading=%2 (independent); "
            "caption offset %3 ms, Karaoke offset %4 ms unchanged. "
            "Normal Whisper subtitle timing remains independent.")
            .arg(activePlaybackCacheMs_)
            .arg(radioReadingPreset_?
                 radioReadingPreset_->currentText():tr("default"))
            .arg(radioOffsetMs_?radioOffsetMs_->value():0)
            .arg(lyricsOffset_?lyricsOffset_->value():0)
            .arg(requestedRematch?
                 tr("checking current song with installed karaoke aligner"):
                 tr("Whisper or lyric catalog unavailable")));
    }
    void refreshKaraokeWordHighlight(qint64 now) {
        if(!karaokeCurrent_ || karaokeLine_.isEmpty() ||
           karaokeWordAnchors_.isEmpty()) return;
        const int count=qMin(karaokeWordAnchors_.size(),90);
        int active=-1;
        for(int i=0;i<count;++i) {
            const QJsonObject word=karaokeWordAnchors_.at(i).toObject();
            const qint64 captured=qRound64(word.value(
                QLatin1String("epoch_ms")).toDouble(0.));
            if(captured<=0 || captured<now-180000 ||
               captured>now+300000) continue;
            // PCM capture clock + requested libVLC cache + user offset:
            // no assertion about actual ALSA/DAC speaker presentation PTS.
            const qint64 expected=captured+activePlaybackCacheMs_+
                lyricsOffset_->value();
            if(now>=expected) active=i;
        }
        if(active==lastHighlightedKaraokeWord_) return;
        lastHighlightedKaraokeWord_=active;
        QString html=QLatin1String("<span style=\"color:#e8edf2\">");
        int cursor=0;
        for(int i=0;i<count;++i) {
            const QJsonObject item=karaokeWordAnchors_.at(i).toObject();
            const int begin=item.value(QLatin1String("start")).toInt(-1);
            const int end=item.value(QLatin1String("end")).toInt(-1);
            if(begin<cursor || end<=begin || end>karaokeLine_.size())
                continue;
            html+=karaokeLine_.mid(cursor,begin-cursor).toHtmlEscaped();
            const QString color=i<active?QLatin1String("#96aab8"):
                i==active?QLatin1String("#ffe17c"):
                QLatin1String("#e8edf2");
            html+=QLatin1String("<span style=\"color:")+color+
                QLatin1String(";font-weight:")+
                (i==active?QLatin1String("800"):QLatin1String("600"))+
                QLatin1String("\">")+
                karaokeLine_.mid(begin,end-begin).toHtmlEscaped()+
                QLatin1String("</span>");
            cursor=end;
        }
        html+=karaokeLine_.mid(cursor).toHtmlEscaped()+
              QLatin1String("</span>");
        karaokeCurrent_->setTextFormat(Qt::RichText);
        karaokeCurrent_->setText(html);
    }
    void showFoundKaraokePreview(qint64 now) {
        // Retrieved text is not heard singing. No DLS/LRC wall-clock walk,
        // six-seconds-per-line advancement, or interpolated word sweep is
        // allowed in either opt-in "Lyrics Found" view.
        const QString policy=karaokePolicy_?
            karaokePolicy_->currentData().toString():QString();
        const bool previewLipSync=policy==QLatin1String("found-sync");
        // Estimated LRC cannot run without *real* timestamps. Show the
        // existing verified-provider text as STATIC preview instead of a
        // completely blank blue Karaoke screen. No invented word sweep.
        const bool estimatedNoLrc=policy==QLatin1String("estimated") &&
                                   lyricCues_.isEmpty();
        if(!lyricsEnabled_ || !lyricLoaded_ ||
           (policy!=QLatin1String("found") && !previewLipSync &&
            !estimatedNoLrc) ||
           !karaokeEnabled_ || !karaokeEnabled_->isChecked() ||
           !karaokePanel_ || !karaokeCurrent_ || !karaokeSource_ ||
           !karaokePrevious_ || !karaokeNext_ || !karaokeTranslation_)
            return;
        // Only real acoustic matches may replace the manually held preview.
        // In found-sync mode the verified renderer owns the lyric position,
        // so this preview must never overwrite even a temporarily quiet song.
        if(lastVerifiedLyricIndex_>=0 && previewIndexShift_==0 &&
           karaokePanel_->isVisible() &&
           karaokeSource_->text().contains(QLatin1String("AUDIO MATCH")))
            return;
        // Online LRC normally provides both timed cues and original lines;
        // some local/imported catalogs contain only one of those arrays.
        // A genuine loaded cue is still displayable in unverified preview.
        const bool timed=!lyricCues_.isEmpty() &&
            (!plainLyricMode_ || lyricRawLines_.isEmpty());
        const int count=timed?lyricCues_.size():lyricRawLines_.size();
        if(count<=0) {
            if(karaokeSource_)
                karaokeSource_->setText(tr(
                    "LYRICS UNAVAILABLE · lookup status has no displayable lines"));
            return;
        }
        const int anchored=lastVerifiedLyricIndex_>=0?
            lastVerifiedLyricIndex_:0;
        const int index=qBound(0,anchored+previewIndexShift_,count-1);
        const auto lineAt=[this,timed](int i)->QString {
            if(i<0) return QString();
            if(timed) {
                if(i>=lyricCues_.size()) return QString();
                return lyricCues_.at(i).toObject().value(
                    QLatin1String("text")).toString().trimmed().left(300);
            }
            if(i>=lyricRawLines_.size()) return QString();
            return lyricRawLines_.at(i).trimmed().left(300);
        };
        const QString line=lineAt(index);
        if(line.isEmpty()) return;
        const bool unchanged=previewLastIndex_==index &&
            karaokePanel_->isVisible() && karaokeLine_==line &&
            karaokeSource_->text().contains(QLatin1String("UNVERIFIED"));
        lastKaraokeUntilMs_=now+1500; // only retain on screen; no movement
        if(unchanged) return;
        previewLastIndex_=index;
        karaokeLine_=line;
        karaokeWordAnchors_=QJsonArray(); // never synthesize ASR word times
        lastHighlightedKaraokeWord_=-2;
        previewLastHighlightedWord_=-2;
        karaokeCurrent_->setTextFormat(Qt::PlainText);
        karaokeCurrent_->setText(line);
        karaokePrevious_->setText(lineAt(index-1));
        karaokePrevious_->setVisible(index>0);
        karaokeNext_->setText(lineAt(index+1));
        karaokeNext_->setVisible(index+1<count);
        QJsonObject translations;
        if(timed)
            translations=lyricCues_.at(index).toObject().value(
                QLatin1String("translations")).toObject();
        QStringList available;
        for(const QString &lang:selectedRadioTargets()) {
            const QString value=translations.value(lang).toString().trimmed();
            if(!value.isEmpty())
                available<<QLatin1String("[")+lang.toUpper()+
                    QLatin1String("] ")+value.left(360);
        }
        karaokeTranslation_->setText(available.join(QLatin1Char('\n')));
        karaokeTranslation_->setVisible(karaokeTranslationsEnabled_ &&
            karaokeTranslationsEnabled_->isChecked() &&
            !available.isEmpty());
        const TihuluDlsSong song=lastAcceptedSongHint_;
        const QString title=song.valid()?
            song.artist+QLatin1String(" · ")+song.title:tr("current song");
        const QString provider=lastLyricsProvider_.isEmpty()?
            tr("local file"):lastLyricsProvider_;
        karaokeSource_->setText(tr(
            "♪ %1 · SOURCE: %2 · LYRICS FOUND · UNVERIFIED\n"
            "LINE %3/%4 · STATIC until Whisper hears matching words or "
            "you choose Lyric ◀/▶.\n"
            "%5 · No guessed word sweep, no fake instrumental position.")
            .arg(title.left(100),provider.left(60))
            .arg(index+1).arg(count)
            .arg(estimatedNoLrc?
                tr("No timestamped LRC: preview only; choose Audio matched "
                   "for Whisper word sync, or import LRC for timed flow"):
                previewLipSync?
                tr("Lip-sync waiting for AUDIO MATCH; 10s evidence history adjustable"):
                tr("Manual lyrics viewer; no automatic progression")));
        karaokePanel_->setVisible(true);
    }
    void showKaraokeLine(const TimedPlainLyric &cue) {
        if(!karaokePanel_ || !karaokeCurrent_ ||
           !karaokeSource_ || !karaokePrevious_ || !karaokeNext_ ||
           !karaokeTranslation_) return;
        if(lastUnmatchedVoiceUntilMs_>QDateTime::currentMSecsSinceEpoch())
            return; // New presenter/advert speech overrides old lyrics
        const QString line=cue.original.trimmed().isEmpty()?
            cue.text.section(QLatin1Char('\n'),0,0).trimmed():
            cue.original.trimmed();
        if(line.isEmpty()) return;
        const int index=cue.lineIndex;
        const QString previous=index>0 && index<=lyricRawLines_.size()?
            lyricRawLines_.at(index-1):QString();
        const QString next=index>=0 && index+1<lyricRawLines_.size()?
            lyricRawLines_.at(index+1):QString();
        karaokePrevious_->setText(previous.left(230));
        karaokePrevious_->setVisible(!previous.isEmpty());
        karaokeLine_=line.left(300);
        karaokeWordAnchors_=cue.wordAnchors;
        lastHighlightedKaraokeWord_=-2;
        karaokeCurrent_->setTextFormat(Qt::PlainText);
        karaokeCurrent_->setText(karaokeLine_);
        refreshKaraokeWordHighlight(QDateTime::currentMSecsSinceEpoch());
        karaokeNext_->setText(next.left(230));
        karaokeNext_->setVisible(!next.isEmpty());
        QStringList translations;
        // Follow OUT language selection and never invent a missing
        // translation. Normal captions continue in their own band.
        for(const QString &lang:selectedRadioTargets()) {
            const QString value=cue.translations.value(lang).toString().trimmed();
            if(!value.isEmpty())
                translations<<QLatin1String("[")+lang.toUpper()+
                    QLatin1String("] ")+value.left(360);
        }
        karaokeTranslation_->setText(translations.join(QLatin1Char('\n')));
        karaokeTranslation_->setVisible(karaokeTranslationsEnabled_ &&
            karaokeTranslationsEnabled_->isChecked() &&
            !translations.isEmpty());
        const QString provider=lastLyricsProvider_.isEmpty()?
            tr("user-provided / source unavailable"):lastLyricsProvider_;
        const QString song=lastAcceptedSongHint_.valid()?
            lastAcceptedSongHint_.artist+QLatin1String(" · ")+
                lastAcceptedSongHint_.title:tr("live radio");
        karaokeSource_->setText(tr(
            "♪ %1 · SOURCE: %2 · AUDIO MATCH: %3% · LINE %4\n"
            "%5")
            .arg(song.left(100),provider.left(55))
            .arg(qRound(cue.confidence*100))
            .arg(index>=0?QString::number(index+1):QStringLiteral("?"))
            .arg(cue.wordAnchors.isEmpty()?
                tr("Line sync only · no verified word timestamps"):
                tr("GPU Whisper words · estimated PCM/cache; DAC unverified")));
        const qint64 now=QDateTime::currentMSecsSinceEpoch();
        // Blue-screen Karaoke hold is independent from the lower subtitle
        // Reading preset; song / Whisper word clock is authoritative here.
        lastKaraokeUntilMs_=now+5500;
        if(!cue.wordAnchors.isEmpty()) {
            const qint64 lastWord=qRound64(cue.wordAnchors.last()
                .toObject().value(QLatin1String("epoch_ms")).toDouble(0.));
            if(lastWord>now-120000 && lastWord<now+20000)
                lastKaraokeUntilMs_=qMax(lastKaraokeUntilMs_,
                    lastWord+activePlaybackCacheMs_+
                    lyricsOffset_->value()+2000);
        }
        karaokePanel_->setVisible(karaokeEnabled_ &&
            karaokeEnabled_->isChecked());
    }
    void showEstimatedLrcFlow(qint64 now) {
        // Explicit, separately labeled fallback for owners with an actual
        // timestamped LRC but insufficient acoustic verification. It is
        // NEVER an audio-model or verified Karaoke match; NO word animation.
        if(!karaokePolicy_ || karaokePolicy_->currentData().toString()!=
             QLatin1String("estimated") ||
           !karaokeEnabled_ || !karaokeEnabled_->isChecked() ||
           !lyricsEnabled_ || !lyricLoaded_ || lyricCues_.isEmpty() ||
           !karaokePanel_ || !karaokeCurrent_ || !karaokeSource_ ||
           !karaokePrevious_ || !karaokeNext_ || !karaokeTranslation_)
            return;
        if(lastUnmatchedVoiceUntilMs_>now) {
            // A presenter/advert has the normal Whisper caption strip.
            // Do not keep advertising old lyrics as currently sung.
            if(karaokeSource_->text().contains(QLatin1String("ESTIMATED LRC")))
                clearKaraokeLine();
            return;
        }
        if(lastVerifiedLyricMs_>0 && now-lastVerifiedLyricMs_<8000 &&
           karaokeSource_->text().contains(QLatin1String("AUDIO MATCH")))
            return;
        const qint64 start=lastLyricsAutoLookup_?songStartMs_:manualSongStartMs_;
        if(start<=0) return;
        const qint64 position=qMax(qint64(0),now-start-
            qint64(lyricsOffset_?lyricsOffset_->value():0));
        int index=-1;
        for(int i=0;i<lyricCues_.size() && i<150;++i) {
            const QJsonObject cue=lyricCues_.at(i).toObject();
            const double from=cue.value(QLatin1String("start")).toDouble(-1.);
            const double until=cue.value(QLatin1String("end")).toDouble(-1.);
            if(from<0. || until<=from) continue;
            const qint64 fromMs=qRound64(from*1000.);
            const qint64 endMs=qRound64(until*1000.);
            if(fromMs>position) break;
            if(position>=fromMs && position<endMs)
                index=i;
        }
        if(index<0) {
            if(karaokeSource_->text().contains(QLatin1String("ESTIMATED LRC")))
                clearKaraokeLine();
            return; // intro / instrumental / end gaps, never fill with fake text
        }
        const QJsonObject cue=lyricCues_.at(index).toObject();
        const QString line=cue.value(QLatin1String("text")).toString().trimmed();
        if(line.isEmpty()) return;
        if(karaokeLine_==line && karaokePanel_->isVisible() &&
           karaokeSource_->text().contains(QLatin1String("ESTIMATED LRC")))
            return;
        const auto neighboring=[this](int at)->QString {
            return at>=0 && at<lyricCues_.size()?
                lyricCues_.at(at).toObject().value(
                    QLatin1String("text")).toString().trimmed():QString();
        };
        karaokeLine_=line;
        karaokeWordAnchors_=QJsonArray(); // no fabricated word positions
        lastHighlightedKaraokeWord_=-2;
        karaokeCurrent_->setTextFormat(Qt::PlainText);
        karaokeCurrent_->setText(line);
        karaokePrevious_->setText(neighboring(index-1));
        karaokePrevious_->setVisible(index>0);
        karaokeNext_->setText(neighboring(index+1));
        karaokeNext_->setVisible(index+1<lyricCues_.size());
        QStringList translations;
        const QJsonObject translated=cue.value(
            QLatin1String("translations")).toObject();
        for(const QString &language:selectedRadioTargets()) {
            const QString text=translated.value(language).toString().trimmed();
            if(!text.isEmpty())
                translations<<QLatin1String("[")+language.toUpper()+
                    QLatin1String("] ")+text.left(360);
        }
        karaokeTranslation_->setText(translations.join(QLatin1Char('\n')));
        karaokeTranslation_->setVisible(karaokeTranslationsEnabled_ &&
            karaokeTranslationsEnabled_->isChecked() &&
            !translations.isEmpty());
        karaokeSource_->setText(tr(
            "ESTIMATED LRC · NOT AUDIO VERIFIED · %1 · line %2/%3 · "
            "DLS clock and user offset, no actual DAC timing. "
            "Whisper speech runs independently.")
            .arg(lastLyricsProvider_.left(80))
            .arg(index+1).arg(lyricCues_.size()));
        lastKaraokeUntilMs_=now+1500; // redraw only, NOT a line timer
        karaokePanel_->setVisible(true);
    }
    void updateRadioCaptionTypography() {
        if(!radioCanvasCaption_) return;
        const int font=radioCaptionFontSize_?
            radioCaptionFontSize_->value():18;
        radioCanvasCaption_->setStyleSheet(QString::fromLatin1(
            "QLabel{background:rgba(0,0,0,215);color:#ffffff;"
            "border-radius:6px;padding:11px;font-size:%1pt;"
            "font-weight:600;}").arg(font));
    }
    int radioCaptionReadingHoldMs(const QString &text) const {
        const int preset=radioReadingPreset_?
            radioReadingPreset_->currentData().toInt():1;
        if(preset<=0) {
            // Fast must still prevent a rapidly revised ASR chunk from
            // flashing two phrases in one 150-ms polling tick. This is only
            // a short visual anti-flicker hold, NOT an audio delay.
            return cueQueue_.size()>=2?250:900;
        }
        // Readability budget for all visible source/translation lines.
        // It does NOT delay audio or claim true sample-clock sync.
        const int chars=qMin(1400,text.trimmed().size());
        const int normal=preset==3?
            // TV-style readability: a sentence-level ~16 cps budget
            // for all visible source/translation lines, but bound the
            // delay so radio speech does not accumulate endlessly.
            qBound(2800,chars*63,9000):
            preset==2?qBound(5500,chars*65,12000):
            qBound(3300,chars*45,8500);
        // TV-style Adaptive also reacts to actual observed Whisper model
        // inference p80, rather than assuming every GPU/CPU model is fast.
        // This only adjusts caption HOLD; it cannot change speaker PTS.
        int adjusted=normal;
        if(preset==3 && lagSamples_.size()>=3) {
            QList<int> sorted=lagSamples_;
            std::sort(sorted.begin(),sorted.end());
            const int p80=sorted[sorted.size()*4/5];
            adjusted=qMax(1800,normal-qBound(0,(p80-2500)/3,1700));
        }
        // Backlog contracts the hold to ~2–4s without dropping phrases.
        if(cueQueue_.size()>=4) return qMin(adjusted,2500);
        if(cueQueue_.size()>=2) return qMin(adjusted,4000);
        return adjusted;
    }
    void setRadioLyricMatchStatus(const QString &message) {
        if(!radioLyricMatchStatus_) return;
        const QString label=message.trimmed().left(210);
        if(label!=radioLyricMatchStatus_->text())
            radioLyricMatchStatus_->setText(label);
        radioLyricMatchStatus_->setVisible(!label.isEmpty());
        // A status update is NOT a karaoke lyric. In Lyrics Found modes,
        // render the actual fetched text, even if the most recent Whisper
        // chunk was spoken advertising rather than singing. The source/
        // verification banner is displayed separately from the words.
        // This is especially important because unmatched speech triggers
        // this status method every few seconds.
        const QString policy=karaokePolicy_?
            karaokePolicy_->currentData().toString():QString();
        const bool previewMode=policy==QLatin1String("found") ||
            policy==QLatin1String("found-sync");
        if(previewMode && karaokeEnabled_ && karaokeEnabled_->isChecked() &&
           lyricsEnabled_ && lyricLoaded_ &&
           (!lyricRawLines_.isEmpty() || !lyricCues_.isEmpty())) {
            showFoundKaraokePreview(QDateTime::currentMSecsSinceEpoch());
            return;
        }
        // While lyrics are actually absent, a placeholder is appropriate.
        // It must never replace fetched lyrics with "listening" text.
        if(karaokePanel_ && karaokeEnabled_ && karaokeEnabled_->isChecked()
           && quickAi_ && quickAi_->isChecked() &&
           lastKaraokeUntilMs_<=QDateTime::currentMSecsSinceEpoch()) {
            karaokePanel_->setVisible(true);
            if(karaokeSource_)
                karaokeSource_->setText(label.isEmpty()?
                    tr("KARAOKE · awaiting song metadata / lyrics"):
                    label);
            if(karaokeCurrent_) {
                karaokeCurrent_->setTextFormat(Qt::PlainText);
                karaokeCurrent_->setText(
                    label.contains(QLatin1String("NOT FOUND"))?
                    tr("No licensed/verified lyrics · Whisper captions below"):
                    label.contains(QLatin1String("FOUND"))?
                    tr("Lyrics retrieved · listening for actual sung words"):
                    tr("Searching / waiting for verified song lyrics…"));
            }
            if(karaokePrevious_) karaokePrevious_->clear();
            if(karaokeNext_) karaokeNext_->clear();
            if(karaokeTranslation_) karaokeTranslation_->clear();
        }
    }
    void showRadioCanvasCaption(const QString &value,bool lyric=false) {
        if(!radioCanvasCaption_) return;
        const QString text=value.trimmed().left(1300);
        if(text.isEmpty() || text==QLatin1String("[music]")) {
            if(!lyric && !lyricsEnabled_) radioCanvasCaption_->setVisible(false);
            return;
        }
        // The LOWER caption strip always belongs to the actual Whisper
        // original + translations. Lyrics (even audio matched) belong in
        // the separate blue Karaoke panel. Never suppress live speech
        // merely because the lyric match holds for several seconds.
        if(lyric) return; // Legacy callers must not overwrite ASR captions.
        const qint64 currentMs=QDateTime::currentMSecsSinceEpoch();
        if(radioCanvasCaption_->text()!=text) {
            radioCanvasCaption_->setText(text);
            // Keep full multi-language phrases readable; never change
            // actual libVLC playback or restart the SDR receiver.
            captionDisplayedStartedMs_=currentMs;
            captionReadingHoldUntilMs_=currentMs+
                radioCaptionReadingHoldMs(text);
        }
        radioCanvasCaption_->setVisible(true);
        if(lyric) {
            lastCanvasLyricMs_=currentMs;
            // Keep a verified lyric line readable between 5s ASR hops;
            // a new unmatched presenter/advert immediately cancels this.
            lastMatchedLyricUntilMs_=qMax(lastMatchedLyricUntilMs_,
                                          currentMs+7500);
        }
    }
	void displayDueRadioCues(qint64 now) {
		// Queue rather than overwrite: a new AI chunk must not erase the
		// previous chunk before its estimated playback presentation time.
        if(captionProgress_) {
            // These are independent 5-second live ASR chunks, not new
            // audio-buffer fills. The one-time user-selected playback cache
            // and caption offset are already baked into each capture-clock
            // dueMs. A repeatedly resetting EST countdown suggested that
            // every phrase rebuffered audio, and caused noisy UI repainting.
            const bool workerRunning=captionProcess_.state()!=QProcess::NotRunning;
            const bool waitingForAudio=cueQueue_.isEmpty();
            const QString status=!workerRunning?
                (quickAi_ && quickAi_->isChecked()?
                    tr("AI captions ON · Whisper recovering (radio unchanged)"):
                    tr("AI captions OFF")):
                waitingForAudio?
                    tr("AI captions ON · listening for next spoken phrase"):
                    tr("AI captions ON · Whisper ready · fixed audio cache %1 ms")
                      .arg(activePlaybackCacheMs_);
            captionProgress_->setRange(0,100);
            const int value=workerRunning?100:0;
            if(captionProgress_->value()!=value)
                captionProgress_->setValue(value);
            if(captionProgress_->format()!=status)
                captionProgress_->setFormat(status);
        }
        while(!cueQueue_.isEmpty() && cueQueue_.first().dueMs<=now) {
            if(captionReadingHoldUntilMs_>now &&
               radioCanvasCaption_ && radioCanvasCaption_->isVisible() &&
               // Readability is a SOFT display preference, not a second
               // subtitle buffer. Audio cache and manual caption offset
               // were already applied to the capture timestamp. Allow only
               // a short visual anti-flicker hold for ONE queued phrase.
               cueQueue_.size()==1 && now-lastCaptionVisibleMs_<350 &&
               now-cueQueue_.first().dueMs<350) {
                // Keep queued phrases rather than flashing a new one
                // before viewers can read the previous phrase.
                if(captionProgress_) captionProgress_->setFormat(
                    tr("Reading hold %1 ms · %2 phrase(s) queued · "
                       "radio audio uninterrupted")
                    .arg(captionReadingHoldUntilMs_-now)
                    .arg(cueQueue_.size()));
                break;
            }
			const TimedRadioCue cue=cueQueue_.takeFirst();
			if(cue.chunkIndex<=displayedRadioChunk_) continue;
			displayedRadioChunk_=cue.chunkIndex;
            const QString shown=cue.text.trimmed();
            if(shown==QLatin1String("[music]")) {
                radioCaption_->setText(tr("Music detected · waiting for "
                    "verified or audio-matched lyrics; no words invented."));
                radioCaptionBanner_->setText(tr("♪ Music · Find lyrics, "
                    "import LRC or enable vocal transcription."));
            } else {
                radioCaption_->setText(cue.text);
                radioCaptionBanner_->setText(tr(
                    "Live radio subtitles · displayed inside station view"));
                showRadioCanvasCaption(cue.text);
            }
            lastCaptionVisibleMs_=now;
            if(lyricsAudioFallbackActive_) {
                const QString heard=tr("Whisper heard (unverified lyrics) · %1")
                    .arg(cue.text.left(650));
                lyricText_->setText(heard);
            }
            // NEVER replace the main DAB station picture/video panel with
            // a caption string: it destroys its status/artwork and places
            // huge subtitles in the center of an unrelated canvas.
		}
        if(lastCaptionVisibleMs_>0 && now-lastCaptionVisibleMs_>=12000 &&
           cueQueue_.isEmpty() && !metadataCaptions_ &&
           captionProcess_.state()!=QProcess::NotRunning) {
            if(!lyricsEnabled_)
                radioCaptionBanner_->setText(tr(
                    "Listening for radio speech · no confirmed words yet."));
            if(!lyricsEnabled_ && radioCanvasCaption_)
                radioCanvasCaption_->setVisible(false);
            lastCaptionVisibleMs_=0;
        }
	}
	void pollCaption() {
		const qint64 now=QDateTime::currentMSecsSinceEpoch();
		if(captionPath_.isEmpty() ||
           (!captionBoundStationKey_.isEmpty() &&
            captionBoundStationKey_!=playingKey_)) {
			displayDueRadioCues(now);
			return;
		}
		QFile stream(captionPath_);
		if(!stream.open(QIODevice::ReadOnly) || stream.size()>15000) {
			displayDueRadioCues(now);
			return;
		}
		const QJsonObject obj=QJsonDocument::fromJson(stream.readAll()).object();
		const QString detected=obj.value(QLatin1String("source_language")).toString();
		if(detected.size()>=2 && detected.size()<=3 &&
		   detected!=QLatin1String("und"))
			lastDetectedLanguage_=detected;
        const int chunk=obj.value(QLatin1String("chunk_index")).toInt(-1);
        const QString aiStatus=obj.value(QLatin1String("status")).toString();
        if(chunk<0 && aiStatus==QLatin1String("waiting_audio")) {
            const QString waiting=tr(
                "AI ON · waiting for decodable DAB audio from local MP3 "
                "endpoint. Lyrics metadata is not a speech transcript.");
            translationStatus_->setText(waiting);
            if(radioCaptionBanner_) {
                radioCaptionBanner_->setText(waiting);
                radioCaptionBanner_->setVisible(true);
            }
        } else if(chunk<0 && aiStatus==QLatin1String("audio_unavailable")) {
            const QString reason=obj.value(QLatin1String("reason"))
                .toString().left(220);
            const QString error=tr(
                "Whisper has NO DAB PCM audio · %1 · no subtitles can be "
                "generated until the stream works. Check welle-cli / MP3 "
                "endpoint / ffmpeg; do not assume audio silence.")
                .arg(reason.isEmpty()?tr("decoder ended without PCM"):reason);
            translationStatus_->setText(error);
            if(radioCaptionBanner_) {
                radioCaptionBanner_->setText(error);
                radioCaptionBanner_->setVisible(true);
            }
            if(captionProgress_) {
                captionProgress_->setRange(0,100);
                captionProgress_->setValue(0);
                captionProgress_->setFormat(tr(
                    "Whisper input failed · no decoded audio; inspect DAB stream"));
            }
        }
        const int revision=obj.value(QLatin1String("caption_revision")).toInt(1);
        const bool newChunk=(chunk!=lastRadioChunk_);
        const bool updatedRevision=(revision>lastRadioRevision_);
		if(chunk>=0 && (newChunk || updatedRevision)) {
            lastCaptionUpdateMs_=now;
            const int lost=obj.value(
                QLatin1String("ai_audio_windows_dropped")).toInt();
            if(lost>0)
                syncStatus_->setText(tr(
                    "AI overload: %1 old audio window(s) dropped to protect "
                    "the live DAB server. Radio audio was NOT retuned. "
                    "Try one output language or a faster Whisper model.")
                    .arg(lost));
            lastRadioChunk_=chunk;
            lastRadioRevision_=revision;
            // Report candidate and applied karaoke engine, independently
            // from the continuous Whisper speaker/transcript stream.
            const QString karaokeCandidate=obj.value(
                QLatin1String("karaoke_alignment_candidate")).toString();
            const QString karaokeApplied=obj.value(
                QLatin1String("karaoke_alignment_engine")).toString();
            const QString karaokeReason=obj.value(
                QLatin1String("karaoke_alignment_reason")).toString();
            const QString karaokeRequested=obj.value(
                QLatin1String("karaoke_alignment_requested")).toString();
            if(karaokeEngineStatus_) {
                if(karaokeApplied==QLatin1String("qwen"))
                    karaokeEngineStatus_->setText(tr(
                        "Karaoke: Qwen3 aligned · Whisper captions separate"));
                else if(karaokeCandidate==QLatin1String("qwen"))
                    karaokeEngineStatus_->setText(tr(
                        "Karaoke: Qwen3 selected/eligible · Whisper timing fallback"));
                else if(karaokeReason==
                        QLatin1String("unsupported_or_undetected_language"))
                    karaokeEngineStatus_->setText(tr(
                        "Karaoke: Whisper · unsupported/unknown Qwen language"));
                else if(karaokeRequested==QLatin1String("whisper"))
                    karaokeEngineStatus_->setText(tr(
                        "Karaoke: Whisper timing explicitly selected"));
                else
                    karaokeEngineStatus_->setText(tr(
                        "Karaoke: Whisper fallback · Qwen unavailable/manual"));
            }
			const double captured=obj.value(QLatin1String("captured_monotonic")).toDouble();
			const double decoded=obj.value(QLatin1String("decoded_monotonic")).toDouble();
			const int inference=(decoded>=captured && decoded-captured<=90.)
				?int((decoded-captured)*1000):0;
			const int carriedChunks=qBound(0,
				obj.value(QLatin1String("sentence_carry_chunks")).toInt(),5);
			const int sentenceHoldMs=qMax(0,carriedChunks-1)*5000;
			if(obj.value(QLatin1String("sentence_pending")).toBool()) {
				syncStatus_->setText(tr("Listening · carrying unfinished sentence "
                    "into next audio segment (up to %1 hops).")
                    .arg(obj.value(QLatin1String("sentence_hops_limit")).toInt(5)));
			}
			if(inference>0) {
				lagSamples_.append(inference);
				while(lagSamples_.size()>8) lagSamples_.removeFirst();
			}
			if(autoSync_->isChecked() && lagSamples_.size()>=4 &&
			   now-lastAdjustmentMs_>30000) {
				QList<int> values=lagSamples_;
				std::sort(values.begin(),values.end());
				const int p80=values[values.size()*4/5];
                // 6s captured PCM + p80 GPU inference + sentence hold,
                // plus a 3s safety margin; all quantities are estimates,
                // not samples of the physical audio output clock.
				const int rawRecommended=
					((6000+p80+sentenceHoldMs+3000+499)/500)*500;
				const int recommended=qBound(0,rawRecommended,60000);
				lastAdjustmentMs_=now;
				bufferRecommendation_->setText(
					tr("Whisper p80 %1 ms · sentence hold %2 ms · estimated "
                    "needed buffer %3 ms (safety ceiling 60000 ms)%4. "
                    "Live output clock NOT verified.")
					.arg(p80).arg(sentenceHoldMs).arg(recommended)
					.arg(rawRecommended>60000?
						tr(" · Above maximum: try fewer target languages or faster model"):
						QString()));
                // Advisory only: no slider/prefs mutation and no automatic
                // libVLC/Whisper restart every time ASR latency changes.
                // Offset and actual playback cache remain fixed until
                // explicit user Apply, as with the stable TV captions.
                if(qAbs(recommended-selectedBufferMs())>=1500)
                    syncStatus_->setText(tr(
                        "Suggested audio cache %1 ms · currently %2 ms. "
                        "Advice only, radio and AI captions uninterrupted.")
                        .arg(recommended).arg(activePlaybackCacheMs_));
			}
            // Use the first real GPU word for earlier caption presentation
            // when available. CPU and multi-hop sentences fall back to the
            // observed phrase END. These are capture-clock estimates, not DAC PTS.
            const qint64 phraseEndEpoch=qRound64(obj.value(
                QLatin1String("subtitle_audio_end_epoch_ms")).toDouble(0.));
            const qint64 firstWordEpoch=qRound64(obj.value(
                QLatin1String("subtitle_audio_start_epoch_ms")).toDouble(0.));
            const qint64 wordEpoch=firstWordEpoch>now-120000 &&
                firstWordEpoch<now+20000 ? firstWordEpoch:phraseEndEpoch;
            const bool hasCaptureTime=wordEpoch>now-120000 &&
                                      wordEpoch<now+20000;
            const int remaining=activePlaybackCacheMs_-6000-inference-
                sentenceHoldMs+550;
            const qint64 requestedDue=hasCaptureTime?
                wordEpoch+activePlaybackCacheMs_+radioOffsetMs_->value():
                now+qMax(0,remaining)+radioOffsetMs_->value();
            const qint64 lateBy=qMax(qint64(0),now-requestedDue);
            const qint64 due=qMax(now,requestedDue);
            const bool fastReading=radioReadingPreset_ &&
                radioReadingPreset_->currentData().toInt()==0;
            if(fastReading && lateBy>800)
                syncStatus_->setText(tr(
                    "Live-fast: ASR result %1 ms behind its estimated audio "
                    "presentation; showing without extra reading delay. "
                    "Lip-sync Refresh cannot undo model latency. Use faster "
                    "Whisper/fewer translations, or opt in to extra audio buffer.")
                    .arg(lateBy));
            else if(lateBy>3000)
                syncStatus_->setText(tr(
                    "Radio AI %1 ms behind captured audio; captions are "
                    "late. Reduce output languages or use faster models.")
                    .arg(lateBy));
			QString caption=obj.value(QLatin1String("original")).toString();
			const QJsonArray speakers=obj.value(QLatin1String("speaker_turns")).toArray();
			if(!caption.isEmpty() && !speakers.isEmpty() && !music_->isChecked()) {
				const QString id=speakers.first().toObject().value(QLatin1String("id")).toString();
				if(QRegularExpression(QLatin1String("^SPEAKER_[0-9]{2}$")).match(id).hasMatch())
					caption=QLatin1String("[")+id+QLatin1String("] ")+caption;
			}
            const auto translations=obj.value(
                QLatin1String("translations")).toObject();
            const QString language=detected.isEmpty()||
                detected==QLatin1String("und")?tr("AUTO ?"):detected.toUpper();
            if(!caption.trimmed().isEmpty())
                caption=tr("[ORIGINAL %1] %2").arg(language,caption);
            // Only actual translated strings are shown. Render exactly
            // the checked target languages in user-selected UI order.
            // Missing outputs are displayed as status, not fake subtitles.
            const QStringList selectedOutputs=selectedRadioTargets();
            for(const QString &code:selectedOutputs) {
                const QString translated=translations.value(code).toString().trimmed();
                if(code!=detected && !translated.isEmpty())
                    caption+=QLatin1String("\n[")+code.toUpper()+
                             QLatin1String("] ")+translated;
            }
			if(!caption.isEmpty() &&
               obj.value(QLatin1String("speech_preserved_when_lyrics_unmatched"))
                   .toBool()) {
                lastUnmatchedVoiceUntilMs_=qMax(lastUnmatchedVoiceUntilMs_,
                                                due+7000);
            }
            if(!caption.isEmpty()) {
                if(newChunk) {
                    cueQueue_.append({chunk,due,now,caption.left(1300),
                        requestedDue-radioOffsetMs_->value(),
                        activePlaybackCacheMs_});
                    while(cueQueue_.size()>12) cueQueue_.removeFirst();
                } else {
                    // Revision 1 adds translations to the SAME original
                    // caption instead of re-speaking it as another cue.
                    bool queued=false;
                    for(auto &cue:cueQueue_) {
                        if(cue.chunkIndex==chunk) {
                            cue.text=caption.left(1300);
                            queued=true;
                            break;
                        }
                    }
                    if(!queued && displayedRadioChunk_==chunk &&
                       radioCanvasCaption_ && !caption.trimmed().isEmpty()) {
                        // Late translations update this SAME already visible
                        // Whisper cue. Never restart the reading hold and
                        // never block on the separate Karaoke/Lyrics panel.
                        const QString updated=caption.left(1300);
                        if(radioCanvasCaption_->text()!=updated)
                            radioCanvasCaption_->setText(updated);
                        radioCanvasCaption_->setVisible(true);
                        radioCaption_->setText(updated);
                        lastCaptionVisibleMs_=now;
                    }
                }
            }
            const QJsonObject matched=obj.value(QLatin1String("lyric_match")).toObject();
            // The optional Qwen model is speech-trained. Its asynchronous
            // word timing can refine only an ALREADY Whisper-verified song
            // line. It cannot invent a lyric match, and its completion must
            // never remove a presenter subtitle or restart audio.
            const QJsonObject acoustic=obj.value(
                QLatin1String("karaoke_qwen_refinement")).toObject();
            const QString acousticLine=acoustic.value(
                QLatin1String("text")).toString().trimmed();
            const QJsonArray acousticWords=acoustic.value(
                QLatin1String("word_anchors")).toArray();
            const qint64 acousticEpoch=qRound64(acoustic.value(
                QLatin1String("capture_epoch_ms")).toDouble(0.));
            if(acousticEpoch>lastHandledQwenCaptureEpochMs_ &&
               acousticEpoch>now-30000 && acousticEpoch<now+1500 &&
               acousticWords.size()>=2 &&
               acousticLine==lastVerifiedLyricText_ &&
               lastVerifiedLyricMs_>0 && now-lastVerifiedLyricMs_<15000) {
                for(auto &cue:plainLyricQueue_)
                    if(cue.original==acousticLine)
                        cue.wordAnchors=acousticWords;
                for(auto &cue:verifiedLyricQueue_)
                    if(cue.original==acousticLine)
                        cue.wordAnchors=acousticWords;
                for(auto &observed:recentKaraokeEvidence_)
                    if(observed.cue.original==acousticLine &&
                       observed.stationKey==playingKey_ &&
                       observed.songKey==lastSongMetadataKey_)
                        observed.cue.wordAnchors=acousticWords;
                if(karaokeLine_==acousticLine) {
                    karaokeWordAnchors_=acousticWords;
                    lastHighlightedKaraokeWord_=-2;
                    refreshKaraokeWordHighlight(now);
                }
                lastHandledQwenCaptureEpochMs_=acousticEpoch;
                if(lyricsSyncState_) lyricsSyncState_->setText(tr(
                    "Qwen acoustic word alignment applied to Whisper-matched "
                    "lyrics · timing estimated from PCM, not measured DAC."));
            }
            const int syncApplied=obj.value(
                QLatin1String("karaoke_sync_refresh_applied")).toInt(0);
            const bool freshRefreshMatch=syncApplied>0 &&
                syncApplied==karaokeSyncRefreshToken_ &&
                syncApplied>lastHandledKaraokeSyncToken_;
            const QString refreshResult=obj.value(
                QLatin1String("karaoke_sync_refresh_status")).toString();
            if(refreshResult==QLatin1String("listening_for_Whisper_match"))
                lyricsSyncState_->setText(tr(
                    "Sync Refresh · searching recent Whisper vocals and next "
                    "audio hops; no reliable lyric match yet."));
            else if(refreshResult==QLatin1String("no_confident_match"))
                lyricsSyncState_->setText(tr(
                    "Sync Refresh · no confident Whisper/lyrics match. "
                    "Karaoke held; spoken subtitles continue."));
            else if(refreshResult==QLatin1String("no_loaded_lyrics"))
                lyricsSyncState_->setText(tr(
                    "Sync Refresh requires loaded song lyrics; Whisper captions continue."));
            const QJsonObject lyricTranslations=obj.value(
                QLatin1String("lyric_translations")).toObject();
            const QJsonArray lyricWordAnchors=obj.value(
                QLatin1String("lyric_word_anchors")).toArray();
			if(matched.value(QLatin1String("kind")).toString()==
				QLatin1String("observed_ASR_chunk_match") &&
				matched.value(QLatin1String("confidence")).toDouble()>=
                (lyricMatchThreshold_?lyricMatchThreshold_->value()/100.:0.74)) {
				const QString line=matched.value(QLatin1String("text")).toString();
				const double confidence=matched.value(QLatin1String("confidence")).toDouble();
				if(!line.isEmpty() && line.size()<=240 &&
                   (freshRefreshMatch ||
                    !(line==lastVerifiedLyricText_ &&
                      lastVerifiedLyricMs_>0 && now-lastVerifiedLyricMs_<7000))) {
                    QString rendered=line;
                    for(auto it=lyricTranslations.begin();it!=lyricTranslations.end();++it)
                        if(it.value().isString() && !it.value().toString().isEmpty())
                            rendered+=QLatin1String("\n[")+it.key().toUpper()+
                                QLatin1String("] ")+it.value().toString();
                    // Accept each manually triggered refresh exactly once.
                    // Revision 1 must not replay the same matched syllables.
                    if(freshRefreshMatch)
                        lastHandledKaraokeSyncToken_=syncApplied;
                    // A genuine audio match is evidence even without a translation.
                    lastVerifiedLyricText_=line;
                    lastVerifiedLyricTranslations_=lyricTranslations;
                    lastVerifiedLyricIndex_=matched.value(
                        QLatin1String("index")).toInt(-1);
                    lastVerifiedLyricMs_=now;
                    lastUnmatchedVoiceUntilMs_=qMin(
                        lastUnmatchedVoiceUntilMs_,now);
                    // Found lyrics get to the real radio caption bar at
                    // their audio-derived due time. The plain and timed
                    // forms share the same evidence requirement, but no
                    // unreliable DLS timestamp is used as proof of match.
                    setRadioLyricMatchStatus(tr(
                        "LYRICS TEXT MATCH %1% · heard audio · line %2 · queued")
                        .arg(qRound(confidence*100))
                        .arg(matched.value(QLatin1String("index")).toInt()+1));
					// Start at the first actually heard GPU word (never metadata).
                    // The old phrase-end cue remains the CPU fallback.
                    // 'due' includes the AI-caption offset; cancel that
                    // offset when scheduling the separate Karaoke stream.
                    qint64 karaokeDue=qMax(now,due-
                        radioOffsetMs_->value()+lyricsOffset_->value());
                    if(!lyricWordAnchors.isEmpty()) {
                        const qint64 firstWord=qRound64(
                            lyricWordAnchors.first().toObject().value(
                                QLatin1String("epoch_ms")).toDouble(0.));
                        if(firstWord>now-120000 && firstWord<now+20000)
                            karaokeDue=qMax(now,firstWord+
                                activePlaybackCacheMs_+
                                lyricsOffset_->value());
                    }
                    const TimedPlainLyric matchedCue(
                        karaokeDue,rendered,confidence,
                        matched.value(QLatin1String("index")).toInt(-1),
                        line,lyricTranslations,lyricWordAnchors);
                    // Bounded evidence memory, independent of libVLC audio
                    // cache. An ordinary Lip-sync Refresh reuses this.
                    rememberKaraokeEvidence(matchedCue,now);
                    if(plainLyricMode_) {
                        plainLyricQueue_.append(matchedCue);
                        while(plainLyricQueue_.size()>10)
                            plainLyricQueue_.removeFirst();
                        lyricsSyncState_->setText(tr(
                            "Verified text match %1% · audio-derived line ordering; "
                            "word timing only when Whisper has actual anchors")
                            .arg(qRound(confidence*100)));
                    } else {
                        verifiedLyricQueue_.append(matchedCue);
                        while(verifiedLyricQueue_.size()>10)
                            verifiedLyricQueue_.removeFirst();
                    }
                    if(!plainLyricMode_ && autoLyricSync_->isChecked() &&
                       confidence>=0.92 && !lyricCues_.isEmpty()) {
						const int idx=matched.value(QLatin1String("index")).toInt(-1);
						if(idx>=0 && idx<lyricCues_.size() && songStartMs_>0) {
							const double lrcSeconds=lyricCues_.at(idx).toObject()
								.value(QLatin1String("start")).toDouble(-1.);
							if(lrcSeconds>=0.) {
								const qint64 inferredStart=due-radioOffsetMs_->value()-
									qRound64(lrcSeconds*1000.);
								const qint64 delta=inferredStart-songStartMs_;
								// Require a close observed vocal line, then correct gently.
								// Broad or false ASR lyric matches must not jump by minutes.
								if(qAbs(delta)<=15000) {
                                    if(qAbs(delta)<900) {
                                        lyricOffsetConsistency_=0;
                                    } else {
                                        const int direction=delta>0?1:-1;
                                        lyricOffsetConsistency_=
                                            direction==lastLyricDirection_?
                                            qMin(3,lyricOffsetConsistency_+1):1;
                                        lastLyricDirection_=direction;
                                        // Require two matching vocal lines and a
                                        // 30s cooldown; cap every correction at
                                        // 250 ms to avoid lyric timing oscillation.
                                        if(lyricOffsetConsistency_>=2 &&
                                           now-lastLyricSyncUpdateMs_>=30000) {
                                            const int step=qBound(-250,int(delta/8),250);
                                            songStartMs_+=step;
                                            lastLyricSyncUpdateMs_=now;
                                            lyricOffsetConsistency_=0;
                                            lyricsSyncState_->setText(tr(
                                                "Audio lyric sync %1% · mismatch %2 ms · "
                                                "corrected %3 ms · manual offset %4 ms")
                                                .arg(qRound(confidence*100)).arg(delta).arg(step)
                                                .arg(lyricsOffset_->value()));
                                        }
                                    }
								} else {
									lyricsSyncState_->setText(tr("Lyric match rejected: "
										"observed offset %1 ms outside ±15000 ms guard. "
										"No auto time jump.").arg(delta));
								}
							}
						}
					}
				}
			}
            // A lyrics lookup proves metadata only. If real speech is
            // heard but fails the line matcher, prioritize Whisper and
            // explain the fallback (especially for adverts/presenters).
            if(lyricsEnabled_ && lyricLoaded_ &&
               (!lyricRawLines_.isEmpty() || !lyricCues_.isEmpty()) &&
               revision>=1 &&
               !obj.value(QLatin1String("original")).toString().trimmed().isEmpty() &&
               (matched.value(QLatin1String("kind")).toString()!=
                QLatin1String("observed_ASR_chunk_match") ||
                matched.value(QLatin1String("confidence")).toDouble()<
                (lyricMatchThreshold_?lyricMatchThreshold_->value()/100.:0.74))) {
                lastMatchedLyricUntilMs_=0;
                verifiedLyricQueue_.clear();
                plainLyricQueue_.clear();
                // Unmatched speech invalidates any moving verified karaoke,
                // but MUST NOT hide the static Lyrics Found preview.
                // Clear stale audio anchors first, then redraw fetched words
                // explicitly in the preview modes.
                clearKaraokeLine();
                lastUnmatchedVoiceUntilMs_=qMax(lastUnmatchedVoiceUntilMs_,
                                                due+5000);
                setRadioLyricMatchStatus(tr(
                    "LYRICS FOUND · NOT MATCHED to this audio · "
                    "Whisper speech/advert fallback"));
                showFoundKaraokePreview(now);
            }
            if(soundLabels_ && soundLabels_->isChecked() &&
               radioCaptionBanner_) {
                const QString note=obj.value(
                    QLatin1String("sound_event_note")).toString();
                const QJsonArray events=obj.value(
                    QLatin1String("sound_events")).toArray();
                QString label;
                if(!note.isEmpty())
                    label=tr("Sound labels unavailable: %1 · Whisper speech kept")
                        .arg(note.left(140));
                else if(!events.isEmpty())
                    label=tr("Sound labels: detector-backed acoustic tags "
                             "added beside recognized speech");
                if(!label.isEmpty() && label!=radioCaptionBanner_->text())
                    radioCaptionBanner_->setText(label);
            }
            const QJsonObject translationWarnings=obj.value(
                QLatin1String("translation_warnings")).toObject();
            const QJsonObject outputLanguages=obj.value(
                QLatin1String("translations")).toObject();
            const QJsonObject realEngines=obj.value(
                QLatin1String("translation_engines")).toObject();
            const QString translationState=obj.value(
                QLatin1String("translation_state")).toString();
            const QString translationNote=obj.value(
                QLatin1String("translation_note")).toString();
            // This status is on the main Radio page, not hidden inside
            // the AI settings tab. A checked language can be pending,
            // ready, or missing; never report "ready" just because
            // model weights exist on disk.
            QStringList outputStates;
            const QJsonArray requested=obj.value(
                QLatin1String("requested_targets")).toArray();
            for(const QJsonValue &entry:requested) {
                const QString code=entry.toString();
                if(code.isEmpty()) continue;
                if(code==detected)
                    outputStates<<code.toUpper()+tr(" original");
                else if(!outputLanguages.value(code).toString().trimmed().isEmpty()) {
                    const QString actual=realEngines.value(code).toString();
                    outputStates<<code.toUpper()+tr(" ready")+
                        (actual.isEmpty()?QString():
                         QLatin1String(" · ")+actual.left(45));
                }
                else
                    outputStates<<code.toUpper()+tr(" missing/pending");
            }
            const QStringList selected=selectedRadioTargets();
            const QString intended=outputStates.isEmpty()?
                (selected.isEmpty()?tr("none"):selected.join(
                    QLatin1String(", ")).toUpper()):
                outputStates.join(QLatin1String(" · "));
            const QString spoken=detected.isEmpty()||
                detected==QLatin1String("und")?tr("auto detecting"):
                detected.toUpper();
            QString mainNote=tr("Spoken: %1 · output: %2").arg(spoken,intended);
            const QString requestedEngine=obj.value(
                QLatin1String("translation_service")).toString();
            if(!requestedEngine.isEmpty())
                mainNote+=tr(" · translator selected: %1")
                    .arg(requestedEngine.left(30));
            // A listed installed model is not evidence of an actual run.
            // Every language's delivered subtitle states its REAL engine.
            if(translationState==QLatin1String("language_pending"))
                mainNote+=tr(" · choose spoken language manually to translate sooner");
            else if(translationState==QLatin1String("translator_disabled"))
                mainNote+=tr(" · enable translation in AI Model Market");
            else if(translationState==QLatin1String("failed") ||
                    translationState==QLatin1String("unavailable") ||
                    translationState==QLatin1String("partial"))
                mainNote+=tr(" · inspect AI translations tab for missing model");
            radioTranslationBanner_->setText(mainNote.left(420));
            radioTranslationBanner_->setVisible(true);
            translationStatus_->setText(translationNote.isEmpty()?
                mainNote:translationNote);
			if(obj.value(QLatin1String("language_pending")).toBool())
				syncStatus_->setText(tr("Language change uncertain; translation held "
					"until two reliable detections. Original audio kept."));
			if(obj.contains(QLatin1String("error")))
				state_->setText(tr("Radio ASR: %1")
					.arg(obj.value(QLatin1String("error")).toString().left(170)));
		}
        if(captionProcess_.state()!=QProcess::NotRunning &&
            lastCaptionUpdateMs_>0 && now-lastCaptionUpdateMs_>20000) {
            radioTranslationBanner_->setText(tr(
                "AI has produced no new radio audio window for 20 s. "
                "Check local welle MP3 stream, ffmpeg and Whisper; this "
                "does not establish that the broadcaster is silent."));
            radioTranslationBanner_->setVisible(true);
        }
		displayDueRadioCues(now);
	}
	void stopCaptioning() {
        captionsStopping_=true;
        captionRecoveryNextMs_=0;
        captionReadingHoldUntilMs_=0;
        captionDisplayedStartedMs_=0;
		cueQueue_.clear();
		metadataCaptions_=false;
		if (captionProcess_.state()!=QProcess::NotRunning) {
			captionProcess_.terminate();
			if (!captionProcess_.waitForFinished(700))
				captionProcess_.kill();
		}
        if(captionProgress_) captionProgress_->setVisible(false);
		if (!captionPath_.isEmpty()) QFile::remove(captionPath_);
		captionPath_.clear();
        captionBoundStationKey_.clear();
        if(!captionControlsPath_.isEmpty()) QFile::remove(captionControlsPath_);
        captionControlsPath_.clear();
        if(!lyricsEnabled_ && radioCanvasCaption_)
            radioCanvasCaption_->setVisible(false);
        if(radioTranslationBanner_) radioTranslationBanner_->setVisible(false);
        captionsStopping_=false;
	}
    void beginLyricListening() {
        if (!active() || playingKey_.isEmpty()) {
            lyricText_->setText(tr("Play a DAB station to transcribe vocals."));
            return;
        }
        // DLS cannot masquerade as spoken captions. Reuse the welle.io
        // audio already playing in the receiver, never the metadata text.
        const int asr=captionSource_->findData(QLatin1String("asr"));
        if(asr>=0) captionSource_->setCurrentIndex(asr);
        const bool alreadyRunning=captionProcess_.state()!=QProcess::NotRunning;
        if(!lyricsAudioFallbackActive_)
            lyricsFallbackStartedAi_=(!alreadyRunning || plainLyricsStartedAi_);
        plainLyricsStartedAi_=false;
        lyricsAudioFallbackActive_=true;
        if(!alreadyRunning) {
            // Explicit Listen action opts into ASR, but NEVER interrupt
            // an already-running presenter transcript just to switch
            // music settings. The original speech stream stays continuous.
            {
                const QSignalBlocker block(quickAi_);
                quickAi_->setChecked(true);
                quickAi_->setText(tr("AI captions · ON"));
            }
            startCaptioning();
        }
        if(captionProcess_.state()==QProcess::NotRunning) {
            lyricsAudioFallbackActive_=false;
            lyricText_->setText(tr("Offline music transcription unavailable. "
                "Install/enable Whisper in AI Model Market and play a valid DAB stream."));
            return;
        }
        lyricCues_=QJsonArray();
        plainLyricMode_=false;
        plainLyricQueue_.clear();
        if(!lyricPath_.isEmpty()) QFile::remove(lyricPath_);
        lyricsEnabled_=true;
        // Whisper vocal listening is NOT a loaded lyric catalog. Marking
        // this true made the native UI falsely say LYRICS FOUND while
        // Full Lyrics had no text and no actual source provenance.
        lyricLoaded_=false;
        lyricRawLines_.clear();
        lyrics_->setEnabled(true);
        stopLyrics_->setEnabled(true);
        lyricProvider_->setText(tr("Local Whisper on actual DAB audio; no "
            "lyrics service used. Heard vocal recognition can be wrong."));
        lyricText_->setText(tr("Listening to DAB vocals offline… Approximate "
            "words appear in live captions, NOT verified song lyrics."));
    }
    void commitPendingDlsSong(const QString &candidate,
                              const QString &station, quint64 ticket) {
        if(candidate.isEmpty() || candidate!=pendingSongKey_ ||
           station!=playingKey_ || ticket!=stationRequestId_ ||
           !active() || scanning_) return;
        const qint64 now=QDateTime::currentMSecsSinceEpoch();
        if(now-pendingSongSinceMs_<5000) {
            // QTimer may fire slightly early: never lose the only callback
            // that can commit a valid artist/title hint.
            const int remaining=int(5000-(now-pendingSongSinceMs_)+50);
            QTimer::singleShot(remaining,this,
                [this,candidate,station,ticket](){
                    commitPendingDlsSong(candidate,station,ticket);
                });
            return;
        }
        // The proposed metadata must STILL be on air after the debounce.
        // Station promos/slogans interrupt candidacy rather than certifying
        // a different song on the basis of a single transient DLS message.
        if(!lastObservedSongHint_.valid() ||
           lastObservedSongHint_.normalizedKey()!=candidate ||
           now-lastObservedSongMs_>12000) {
            pendingSongKey_.clear();
            pendingSongDls_.clear();
            pendingSongObservations_=0;
            return;
        }
        // Some DLS services rotate artist/title and station slides
        // faster than two consecutive mux snapshots. A credible structured
        // track tag can be accepted after 5s; a single generic "A - B"
        // item is given extra time for a second observation, but must not
        // strand Lyrics forever when broadcasts rotate very fast.
        const bool typedSource=pendingSongHint_.format!=
            QLatin1String("DLS artist-first");
        if(pendingSongObservations_<2 && !typedSource &&
           now-pendingSongSinceMs_<8000) {
            QTimer::singleShot(3000,this,
                [this,candidate,station,ticket](){
                    commitPendingDlsSong(candidate,station,ticket);
                });
            return;
        }
        // Recent matching Whisper lyrics are evidence that the old song
        // is still audible. A DLS title alone cannot override that.
        if(lastVerifiedLyricMs_>0 && now-lastVerifiedLyricMs_<7000) {
            QTimer::singleShot(3500,this,[this,candidate,station,ticket](){
                commitPendingDlsSong(candidate,station,ticket);
            });
            return;
        }
        if(candidate==lastSongMetadataKey_) {
            pendingSongKey_.clear();
            return;
        }
        const QString acceptedDls=pendingSongDls_;
        const TihuluDlsSong acceptedSong=pendingSongHint_;
        pendingSongKey_.clear();
        pendingSongDls_.clear();
        pendingSongObservations_=0;
        cancelLyricsRefresh();
        clearLiveRadioLyricsCatalog(); // old accepted song is no longer live
        recentKaraokeEvidence_.clear();
        lastSongMetadataKey_=candidate;
        lastSongDls_=acceptedDls;
        lastAcceptedSongHint_=acceptedSong;
        // DLS is metadata; this time is not measured audio/DAC PTS.
        songStartMs_=now+activePlaybackCacheMs_;
        lyricCues_=QJsonArray();
        lastLyricSyncUpdateMs_=0;
        lastLyricDirection_=0;
        lyricOffsetConsistency_=0;
        lastVerifiedLyricMs_=0;
        lastVerifiedLyricIndex_=-1;
        lastVerifiedLyricText_.clear();
        lastVerifiedLyricTranslations_=QJsonObject();
        plainLyricMode_=false;
        plainLyricQueue_.clear();
        verifiedLyricQueue_.clear();
        lastMatchedLyricUntilMs_=0;
        lyricRawLines_.clear();
        lastLyricsProvider_.clear();
        clearKaraokeLine();
        previewStartedMs_=0;
        previewPauseStartedMs_=0;
        previewSpeedCompensationMs_=0;
        previewPreviousSpeedPercent_=karaokePreviewSpeed_?
            karaokePreviewSpeed_->value():100;
        previewIndexShift_=0;
        previewLastIndex_=-1;
        setRadioLyricMatchStatus(QString());
        const bool listening=lyricsAudioFallbackActive_;
        // A newly announced DLS song has metadata only. An ASR listener
        // can remain enabled but must not masquerade as fetched lyrics.
        lyricLoaded_=false;
        lyricsEnabled_=listening;
        if(lyricsProcess_.state()!=QProcess::NotRunning) {
            lyricsProcess_.kill();
            lyricsProcess_.waitForFinished(900);
        }
        stopLyrics_->setEnabled(listening);
        lyrics_->setEnabled(true);
        if(!lyricPath_.isEmpty()) QFile::remove(lyricPath_);
        lyricPath_.clear();
        lyricText_->setText(listening?
            tr("New stable DLS song · offline vocal listening continues.") :
            tr("Stable new DLS song · changing Karaoke after debounce."));
        if(autoLyrics_ && autoLyrics_->isChecked())
            fetchLyrics(true);
        else
            setRadioLyricMatchStatus(tr(
                "DLS SONG DETECTED · online lyrics search OFF · "
                "enable Auto search or use Lyrics Refresh"));
    }
	void stopLyrics() {
        cancelLyricsRefresh();
        recentKaraokeEvidence_.clear();
        const bool hadListening=lyricsAudioFallbackActive_;
        const bool startedByLyrics=lyricsFallbackStartedAi_;
        lyricsAudioFallbackActive_=false;
        lyricsFallbackStartedAi_=false;
        // Lyrics never owns the main AI ON/OFF switch. Stop Lyrics can
        // clear lyrics and song-specific matching, not live speech captions.
        // Only explicit AI OFF, Stop Captions, radio Stop or TV handoff
        // are allowed to disarm live ASR.
        if((hadListening && startedByLyrics || plainLyricsStartedAi_) &&
           (!quickAi_ || !quickAi_->isChecked()) &&
           captionProcess_.state()!=QProcess::NotRunning)
            stopCaptioning();
        plainLyricsStartedAi_=false;
		lyricsEnabled_=false;
		lyrics_->setEnabled(true);
		if (lyricsProcess_.state()!=QProcess::NotRunning) {
			lyricsProcess_.terminate();
			if (!lyricsProcess_.waitForFinished(600)) lyricsProcess_.kill();
		}
		if (!lyricPath_.isEmpty()) QFile::remove(lyricPath_);
		lyricPath_.clear();
        clearLiveRadioLyricsCatalog(); // manual Stop Lyrics ends matching
		lyricCues_=QJsonArray();
		plainLyricMode_=false;
		plainLyricQueue_.clear();
        verifiedLyricQueue_.clear();
        lastMatchedLyricUntilMs_=0;
        lyricRawLines_.clear();
        lastLyricsProvider_.clear();
        clearKaraokeLine();
        setRadioLyricMatchStatus(QString());
        lastVerifiedLyricMs_=0;
        lastVerifiedLyricIndex_=-1;
        lastVerifiedLyricText_.clear();
        lastVerifiedLyricTranslations_=QJsonObject();
        lyricOffsetConsistency_=0;
		lyricLoaded_=false;
        lastLyricsAutoLookup_=false;
        lyricsRequestKey_.clear();
        lastUnmatchedVoiceUntilMs_=0;
		stopLyrics_->setEnabled(false);
        lyricProvider_->setText(tr("Lyrics stopped. Local DAB audio continues."));
		lyricText_->setText(tr("Lyrics / lyric-triggered listening stopped."));
	}
    void cancelLyricsRefresh() {
        if(lyricsRefreshProcess_.state()!=QProcess::NotRunning) {
            lyricsRefreshProcess_.kill();
            lyricsRefreshProcess_.waitForFinished(500);
        }
        if(!lyricsRefreshPath_.isEmpty()) QFile::remove(lyricsRefreshPath_);
        lyricsRefreshPath_.clear();
        lyricsRefreshRequestKey_.clear();
        lyricsRefreshStationKey_.clear();
        lyricsRefreshSongKey_.clear();
        lyricsRefreshPending_=false;
        if(lyricsRefresh_) lyricsRefresh_->setEnabled(true);
    }
    void refreshCurrentLyrics() {
        // Explicit opt-in online refresh; independent from ASR and lip-sync.
        if(!active() || playingKey_.isEmpty() || scanning_) {
            const QString note=tr(
                "Lyrics Refresh blocked: station not playing or DAB scanning.");
            lyricText_->setText(note);
            if(lyricsSyncState_) lyricsSyncState_->setText(note);
            return;
        }
        // A transient DLS update is not grounds to disable an explicit
        // manual lookup of the already-loaded song. Result application
        // below still checks station identity and pending song stability.
        if(lyricsRefreshPending_ ||
           lyricsRefreshProcess_.state()!=QProcess::NotRunning) {
            const QString note=tr(
                "Lyrics Refresh already running · existing Karaoke preserved.");
            lyricText_->setText(note);
            if(lyricsSyncState_) lyricsSyncState_->setText(note);
            return;
        }
        const bool manual=!lyricsArtist_->text().trimmed().isEmpty() &&
                          !lyricsTitle_->text().trimmed().isEmpty();
        const TihuluDlsSong song=lastAcceptedSongHint_;
        if(!manual && (!song.valid() || lastSongMetadataKey_.isEmpty())) {
            const QString note=tr(
                "Lyrics Refresh needs artist/title; DLS may contain an advert "
                "or delayed song name. Enter them manually in Lyrics settings.");
            lyricText_->setText(note);
            if(lyricsSyncState_) lyricsSyncState_->setText(note);
            return;
        }
        const QString artist=manual?lyricsArtist_->text().trimmed():song.artist;
        const QString title=manual?lyricsTitle_->text().trimmed():song.title;
        if(artist.isEmpty() || title.isEmpty() ||
           artist.size()>130 || title.size()>130) return;
        // Preserve explicit confirmation before contacting external lyric
        // providers. The dialog is parented to the radio window.
        if(QMessageBox::question(this,tr("Lyrics Refresh · online search"),
           tr("Search LRCLIB, lyrics.ovh and optional licensed Musixmatch "
              "again for %1 — %2?\nSong metadata: %3 (station excluded)\n\n"
              "Only artist/title and selected languages are sent; NO radio audio is uploaded. "
              "Current Karaoke remains while searching and on failure.")
              .arg(artist,title,manual?tr("manual correction"):song.format),
           QMessageBox::Yes|QMessageBox::No,QMessageBox::No)!=QMessageBox::Yes)
            return;
        const QString runtime=QStandardPaths::writableLocation(
            QStandardPaths::RuntimeLocation);
        if(runtime.isEmpty()) {
            lyricText_->setText(tr("Private runtime directory unavailable."));
            return;
        }
        // Explicit Lyrics Refresh supersedes an older automatic lookup.
        // Otherwise a slow provider keeps the original worker alive and
        // the Refresh button appears broken. Do this only AFTER the owner
        // accepts the online search; do not clear already displayed lyrics
        // or restart Whisper, radio playback, Karaoke or any SDR.
        if(lyricsProcess_.state()!=QProcess::NotRunning) {
            lyricsProcess_.kill();
            lyricsProcess_.waitForFinished(900);
            if(!lyricPath_.isEmpty()) QFile::remove(lyricPath_);
            lyricPath_.clear();
            if(lyrics_) lyrics_->setEnabled(true);
        }
        const QString sourceCode=lyricsSourceLanguage_->currentData().toString();
        const QStringList targets=selectedRadioTargets();
        const QString identity=manual?
            artist.simplified().toCaseFolded()+QLatin1Char('|')+
            title.simplified().toCaseFolded():song.normalizedKey();
        lyricsRefreshRequestKey_=identity+QLatin1Char('|')+sourceCode+
            QLatin1Char('|')+targets.join(QLatin1Char(','));
        lyricsRefreshStationKey_=playingKey_;
        lyricsRefreshSongKey_=lastSongMetadataKey_;
        lyricsRefreshStationTicket_=stationRequestId_;
        lyricsRefreshStartedMs_=QDateTime::currentMSecsSinceEpoch();
        lyricsRefreshPath_=runtime+QLatin1String("/tihulu-radio-lyrics-refresh-")+
            QString::number(QCoreApplication::applicationPid())+
            QLatin1Char('-')+QString::number(++lyricsLookupGeneration_)+
            QLatin1String(".json");
        QFile::remove(lyricsRefreshPath_);
        lyricsRefreshPending_=true;
        lyricsRefresh_->setEnabled(false);
        // Independent worker/file: do not unset lyricLoaded_, reset the
        // preview song clock, clear word anchors, or restart SDR/Whisper.
        lyricsRefreshProcess_.start(QLatin1String("tihulu-tv-center"),
            {QLatin1String("lyrics-lookup"),QLatin1String("--artist"),artist,
             QLatin1String("--track"),title,QLatin1String("--output"),
             lyricsRefreshPath_,QLatin1String("--source"),sourceCode,
             QLatin1String("--targets"),targets.join(QLatin1Char(',')),
             QLatin1String("--online")});
        if(!lyricsRefreshProcess_.waitForStarted(900)) {
            cancelLyricsRefresh();
            lyricText_->setText(tr("Lyrics Refresh worker failed; old words kept."));
            return;
        }
        const QString note=tr(
            "Lyrics Refresh searching %1 — %2 · old Karaoke preserved")
            .arg(artist.left(80),title.left(80));
        lyricText_->setText(note);
        if(lyricsSyncState_) lyricsSyncState_->setText(note);
    }
    void pollLyricsRefreshResult() {
        if(!lyricsRefreshPending_) return;
        // Never strand the Lyrics Refresh button disabled if an upstream
        // provider stalls indefinitely (or the process dies without JSON).
        // Preserve the existing lyric catalog and all radio/ASR processes.
        const qint64 elapsed=QDateTime::currentMSecsSinceEpoch()-
            lyricsRefreshStartedMs_;
        if(elapsed>30000) {
            cancelLyricsRefresh();
            const QString note=tr(
                "Lyrics Refresh timed out (30s) · original lyrics retained. "
                "Try again or import a local TXT/LRC.");
            lyricText_->setText(note);
            if(lyricsSyncState_) lyricsSyncState_->setText(note);
            return;
        }
        if(lyricsRefreshStationTicket_!=stationRequestId_ ||
           lyricsRefreshStationKey_!=playingKey_ ||
           lyricsRefreshSongKey_!=lastSongMetadataKey_) {
            // Pending DLS is only a hint. Cancel only once a DIFFERENT
            // song is accepted or the actual station/ticket changed.
            // Otherwise presenter promos could prevent every manual refresh.
            cancelLyricsRefresh(); // stale result from old track
            return;
        }
        QFile file(lyricsRefreshPath_);
        if(!file.open(QIODevice::ReadOnly) || file.size()>250000) {
            if(lyricsRefreshProcess_.state()==QProcess::NotRunning &&
               QDateTime::currentMSecsSinceEpoch()-lyricsRefreshStartedMs_>2500) {
                cancelLyricsRefresh();
                const QString note=tr(
                    "Lyrics Refresh worker returned no result · existing "
                    "Karaoke kept. Check network/lyrics provider.");
                lyricText_->setText(note);
                if(lyricsSyncState_) lyricsSyncState_->setText(note);
            }
            return;
        }
        const QJsonObject value=QJsonDocument::fromJson(file.readAll()).object();
        const QString state=value.value(QLatin1String("status")).toString();
        if(state!=QLatin1String("completed") && state!=QLatin1String("error"))
            return;
        const QJsonArray newCues=value.value(QLatin1String("cues")).toArray();
        const QJsonArray newPlain=value.value(QLatin1String("plain_lines")).toArray();
        if(state!=QLatin1String("completed") ||
           (newCues.isEmpty() && newPlain.isEmpty())) {
            const QString note=tr(
                "Lyrics Refresh returned no actual song text; previous Karaoke kept.");
            cancelLyricsRefresh();
            lyricText_->setText(note);
            if(lyricsSyncState_) lyricsSyncState_->setText(note);
            return;
        }
        QStringList newLines;
        for(const QJsonValue &entry:newPlain)
            if(entry.isString()) newLines<<entry.toString().left(350);
        const bool newPlainMode=value.value(QLatin1String("alignment_mode"))
            .toString()==QLatin1String("asr_lexical");
        const bool changed=newCues!=lyricCues_ ||
                           newLines!=lyricRawLines_ ||
                           newPlainMode!=plainLyricMode_;
        const qint64 now=QDateTime::currentMSecsSinceEpoch();
        lyricCues_=newCues;
        lyricRawLines_=newLines;
        plainLyricMode_=newPlainMode;
        const QString provider=value.value(QLatin1String("provenance"))
            .toObject().value(QLatin1String("provider")).toString();
        lastLyricsProvider_=provider.isEmpty()?tr("online source"):provider;
        lyricLoaded_=true;
        lyricsEnabled_=true;
        lastLyricsAutoLookup_=true;
        lyricsRequestKey_=lyricsRefreshRequestKey_;
        const bool liveCatalogPublished=publishLiveRadioLyricsCatalog(value);
        lyricsLookupCooldownUntilMs_=now+90000;
        if(lyricsCache_.size()>=12 &&
           !lyricsCache_.contains(lyricsRequestKey_)) {
            QString oldest;
            qint64 lowest=std::numeric_limits<qint64>::max();
            for(auto it=lyricsCacheTime_.cbegin();
                it!=lyricsCacheTime_.cend();++it)
                if(it.value()<lowest) {lowest=it.value();oldest=it.key();}
            if(!oldest.isEmpty()) {
                lyricsCache_.remove(oldest);
                lyricsCacheTime_.remove(oldest);
            }
        }
        lyricsCache_.insert(lyricsRequestKey_,value);
        lyricsCacheTime_.insert(lyricsRequestKey_,now);
        if(changed) {
            // Only retire old Karaoke AFTER a usable replacement arrived.
            // Do not make a second DLS/song start by resetting songStartMs_.
            verifiedLyricQueue_.clear();
            plainLyricQueue_.clear();
            recentKaraokeEvidence_.clear();
            clearKaraokeLine();
            lastVerifiedLyricMs_=0;
            lastVerifiedLyricText_.clear();
            lastVerifiedLyricTranslations_=QJsonObject();
            previewLastIndex_=-1;
            previewLastHighlightedWord_=-2;
            if(previewStartedMs_<=0) previewStartedMs_=now;
            if(manualSongStartMs_<=0) manualSongStartMs_=now;
        }
        lyricProvider_->setText(tr(
            "Lyrics source: %1 · refreshed · audio verification is independent")
            .arg(lastLyricsProvider_));
        const QString note=tr(
            "Lyrics Refresh completed · %1 · %2 lines · live matcher %3 · "
            "DAB radio/Whisper uninterrupted")
            .arg(changed?tr("new text applied"):tr("same text retained"))
            .arg(lyricRawLines_.isEmpty()?lyricCues_.size():
                 lyricRawLines_.size())
            .arg(liveCatalogPublished?tr("catalog synchronized"):
                 tr("catalog publish failed — check runtime permissions"));
        lyricText_->setText(note);
        if(lyricsSyncState_) lyricsSyncState_->setText(note);
        if(changed) setRadioLyricMatchStatus(tr(
            "LYRICS REFRESHED · new words await Whisper audio match"));
        showFoundKaraokePreview(now);
        cancelLyricsRefresh();
    }
	void fetchLyrics(bool automatic=false) {
		if (!active() || playingKey_.isEmpty()) {
			lyricText_->setText(tr("Play a station first.")); return;
		}
        const TihuluDlsSong song=lastAcceptedSongHint_;
		const bool overridden=!automatic && !lyricsArtist_->text().trimmed().isEmpty()
			&& !lyricsTitle_->text().trimmed().isEmpty();
		if(!song.valid() && !overridden) {
			lyricText_->setText(tr("No reliable Artist - Title DLS metadata. "
                "You can type artist/title, import LRC, or listen to vocals offline."));
            if(!automatic && listenFallbackOnMiss_->isChecked()) beginLyricListening();
			return;
		}
		const QString artist=overridden?lyricsArtist_->text().trimmed():song.artist;
		const QString title=overridden?lyricsTitle_->text().trimmed():song.title;
		if (artist.isEmpty() || title.isEmpty() || artist.size()>130 || title.size()>130)
			return;
		if (automatic && (!autoLyrics_->isChecked() ||
            lastSongMetadataKey_.isEmpty() || !pendingSongKey_.isEmpty()))
            return;
		if(!automatic && QMessageBox::question(this,tr("Optional online lyrics lookup"),
			tr("Search LRCLIB, lyrics.ovh and optional licensed Musixmatch?\nArtist: %1\nTitle: %2\nSong metadata: %3 (station excluded)\n\n"
			   "Only these metadata are sent; no radio audio is uploaded. "
			   "Start time estimated from DLS, so adjust the timing slider manually.")
			   .arg(artist,title,overridden?tr("manual correction"):song.format))!=QMessageBox::Yes) return;
        // Key cached lyrics by song identity plus requested translation
        // languages, never by fragile changing broadcaster DLS text.
        const QString sourceCode=lyricsSourceLanguage_->currentData().toString();
        const QStringList dests=selectedRadioTargets();
        const QString requestKey=(overridden?
            artist.simplified().toCaseFolded()+QLatin1Char('|')+
            title.simplified().toCaseFolded():song.normalizedKey())+
            QLatin1Char('|')+sourceCode+QLatin1Char('|')+
            dests.join(QLatin1Char(','));
        const qint64 lookupNow=QDateTime::currentMSecsSinceEpoch();
        if(automatic && requestKey==lyricsRequestKey_ &&
           (lyricsEnabled_ || lyricLoaded_ ||
            lookupNow<lyricsLookupCooldownUntilMs_)) return;
        // Never allow an old worker to overwrite a newer song result.
        if(lyricsProcess_.state()!=QProcess::NotRunning) {
            lyricsProcess_.kill();
            lyricsProcess_.waitForFinished(900);
        }
        if(!lyricPath_.isEmpty()) QFile::remove(lyricPath_);
        lyricsRequestKey_=requestKey;
        lyricsLookupCooldownUntilMs_=lookupNow+90000;
		const QString runtime=QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
        if(runtime.isEmpty()) {
            lyricsRequestKey_.clear();
            lyricText_->setText(tr("Private runtime directory unavailable; lyrics search cancelled."));
            return;
        }
		lyricPath_=runtime+QLatin1String("/tihulu-radio-lyrics-")+
            QString::number(QCoreApplication::applicationPid())+
            QLatin1Char('-')+QString::number(++lyricsLookupGeneration_)+
            QLatin1String(".json");
		lyricsEnabled_=true;
        lastLyricsAutoLookup_=automatic;
        lyricLoaded_=false;
        plainLyricMode_=false;
        lyricCues_=QJsonArray();
        plainLyricQueue_.clear();
        verifiedLyricQueue_.clear();
        recentKaraokeEvidence_.clear();
        lyricRawLines_.clear();
        lastLyricsProvider_.clear();
        clearLiveRadioLyricsCatalog(); // prevent stale matching mid-lookup
        clearKaraokeLine();
        previewStartedMs_=0;
        previewPauseStartedMs_=0;
        previewSpeedCompensationMs_=0;
        previewPreviousSpeedPercent_=karaokePreviewSpeed_?
            karaokePreviewSpeed_->value():100;
        previewIndexShift_=0;
        previewLastIndex_=-1;
        lastVerifiedLyricMs_=0;
        lastMatchedLyricUntilMs_=0;
        lastVerifiedLyricText_.clear();
        lastVerifiedLyricTranslations_=QJsonObject();
        setRadioLyricMatchStatus(tr(
            "LYRICS SEARCHING · metadata lookup in progress"));
        if(lyricsAudioFallbackActive_) {
            // The current fallback is only for this song's absent lyrics;
            // do not leave a previous track's plain/timed cues visible.
            lyricCues_=QJsonArray();
        }
		lyrics_->setEnabled(false);
        lyricProvider_->setText(tr("Searching LRCLIB, optional licensed "
            "Musixmatch and lyrics.ovh (metadata only).\n"
            "Song: %1 — %2 · source: %3 · station name excluded.")
            .arg(artist.left(130),title.left(130),
                 overridden?tr("manual correction"):song.format));
        // Song-specific manual choice never changes automatic spoken ASR.
        // Do not reuse previous spoken presenter language for the NEXT song:
		// an English or Turkish singer may follow a German-language host.
		// Without independently verified song language, keep it auto and
		// suppress ungrounded German/English/Turkish lyric translation.
        // Session-only bounded cache of previously retrieved licensed/local
        // metadata lyrics. Parsing follows the normal result path; cached
        // data never becomes a verified Whisper audio match.
        if(automatic && lyricsCache_.contains(requestKey) &&
           lookupNow-lyricsCacheTime_.value(requestKey,0)<7200000) {
            const QByteArray json=QJsonDocument(
                lyricsCache_.value(requestKey)).toJson(QJsonDocument::Compact);
            QSaveFile cacheOutput(lyricPath_);
            if(json.size()<=250000 && cacheOutput.open(QIODevice::WriteOnly) &&
               cacheOutput.write(json)==json.size() && cacheOutput.commit()) {
                lyricText_->setText(tr("Lyrics cache hit · no network search"));
                updateLyrics();
                return;
            }
        }
		lyricsProcess_.start(QLatin1String("tihulu-tv-center"),
			{QLatin1String("lyrics-lookup"),QLatin1String("--artist"),artist,
			 QLatin1String("--track"),title,QLatin1String("--output"),lyricPath_,
			 QLatin1String("--source"),sourceCode,
			 QLatin1String("--targets"),dests.join(QLatin1Char(',')),
			 QLatin1String("--online")});
		if (!lyricsProcess_.waitForStarted(900)) {
			lyricsEnabled_=false;
			lyrics_->setEnabled(true);
            stopLyrics_->setEnabled(false);
			lyricText_->setText(tr("Lyrics lookup worker failed to start."));
            setRadioLyricMatchStatus(tr(
                "LYRICS LOOKUP FAILED · Whisper fallback"));
            if(listenFallbackOnMiss_->isChecked()) beginLyricListening();
			return;
		}
		stopLyrics_->setEnabled(true);
		lyricText_->setText(tr("Searching timed OR plain lyrics… Stop available."));
	}
    void updateLyrics() {
        if(!lyricsEnabled_) return;
        const qint64 now=QDateTime::currentMSecsSinceEpoch();
        if(lastKaraokeUntilMs_>0 && now>=lastKaraokeUntilMs_) {
            // Instrumental/quiet intervals cannot advance a confirmed
            // Karaoke lyric without fresh ASR evidence. Hold the LAST
            // heard word while Whisper is listening for the next match.
            // This is not a claim of instrument/vocal classification.
            const bool keepLastMatchedWord=karaokePanel_ &&
                karaokePanel_->isVisible() &&
                lastVerifiedLyricIndex_>=0 &&
                captionProcess_.state()!=QProcess::NotRunning &&
                lastUnmatchedVoiceUntilMs_<=now;
            if(keepLastMatchedWord)
                lastKaraokeUntilMs_=now+1500;
            else
                clearKaraokeLine();
        } else refreshKaraokeWordHighlight(now);
        // Preview and opt-in LRC estimated flow are both independent from
        // Whisper speech; only acoustic matches can supply word anchors.
        showFoundKaraokePreview(now);
        showEstimatedLrcFlow(now);
        // Only ASR-confirmed matches enter this extra timed-LRC queue.
        while(!verifiedLyricQueue_.isEmpty() &&
              verifiedLyricQueue_.first().dueMs<=now) {
            const auto cue=verifiedLyricQueue_.takeFirst();
            // Do NOT replace the independent lower Whisper subtitle strip
            // with catalog lyrics. The blue panel handles Karaoke.
            showKaraokeLine(cue);
            setRadioLyricMatchStatus(tr(
                "LYRICS MATCHED %1% · showing heard song words")
                .arg(qRound(cue.confidence*100)));
            lyricText_->setText(tr("Audio-matched lyric · %1")
                                .arg(cue.text.left(400)));
        }
		if(plainLyricMode_) {
			while(!plainLyricQueue_.isEmpty() && plainLyricQueue_.first().dueMs<=now) {
				const auto cue=plainLyricQueue_.takeFirst();
				lyricText_->setText(tr("Audio-matched lyric (~%1% confidence) · %2")
					.arg(qRound(cue.confidence*100)).arg(cue.text));
                // Keep the ordinary Whisper caption strip intact.
                showKaraokeLine(cue);
                setRadioLyricMatchStatus(tr(
                    "LYRICS MATCHED %1% · showing heard song words")
                    .arg(qRound(cue.confidence*100)));
            }
            // Lyrics/Karaoke are independent and MUST NEVER hide
            // the active Whisper speech/translation caption area.
            return;
		}
		if (lyricPath_.isEmpty() || lyricLoaded_) {
            const qint64 currentEpoch=QDateTime::currentMSecsSinceEpoch();
            // A DLS song title is metadata, not an exact start time:
            // automatic timed LRC requires real ASR-verified matches
            // (processed above) rather than guessed positions.
            // Manually imported/selected LRC may still estimate timing.
            if(lastLyricsAutoLookup_) return;
            if(now<lastMatchedLyricUntilMs_) return;
            if(lastUnmatchedVoiceUntilMs_>currentEpoch) return;
			if (!lyricCues_.isEmpty() && songStartMs_>0) {
				const qint64 start=autoLyricSync_->isChecked()
					?songStartMs_:manualSongStartMs_;
				const double elapsed=(QDateTime::currentMSecsSinceEpoch()-start+
					lyricsOffset_->value())/1000.;
				QString current;
				for (const QJsonValue &item:lyricCues_) {
					const QJsonObject cue=item.toObject();
					if (cue.value(QLatin1String("start")).toDouble()<=elapsed &&
					    cue.value(QLatin1String("end")).toDouble()>elapsed) {
						current=cue.value(QLatin1String("text")).toString();
						QJsonObject translated=cue.value(
							QLatin1String("translations")).toObject();
                        if(translated.isEmpty() &&
                           lastVerifiedLyricText_==current &&
                           QDateTime::currentMSecsSinceEpoch()-lastVerifiedLyricMs_<12000)
                            translated=lastVerifiedLyricTranslations_;
						for(auto it=translated.begin();it!=translated.end();++it)
							if(it.value().isString() && !it.value().toString().isEmpty())
								current+=QLatin1String("\n[")+it.key().toUpper()+
									QLatin1String("] ")+it.value().toString();
						break;
					}
				}
				if (!current.isEmpty()) {
                    const QString text=tr("Estimated lyric timing · %1").arg(current);
                    if(lyricText_->text()!=text)lyricText_->setText(text);
                    // Estimation only belongs to Lyrics / blue Karaoke,
                    // NEVER the lower Whisper conversation subtitle strip.
                }
			}
			return;
		}
		QFile file(lyricPath_);
		if (!file.open(QIODevice::ReadOnly) || file.size()>250000) return;
		const auto value=QJsonDocument::fromJson(file.readAll()).object();
		if (value.value(QLatin1String("status")).toString()==QLatin1String("completed")) {
            // Bounded in-memory lyric cache (max 12 songs, 2h per entry).
            if(!lyricsRequestKey_.isEmpty()) {
                if(lyricsCache_.size()>=12 && !lyricsCache_.contains(lyricsRequestKey_)) {
                    QString oldest;
                    qint64 oldestTime=std::numeric_limits<qint64>::max();
                    for(auto it=lyricsCacheTime_.cbegin();
                        it!=lyricsCacheTime_.cend();++it)
                        if(it.value()<oldestTime) {
                            oldestTime=it.value(); oldest=it.key();
                        }
                    if(!oldest.isEmpty()) {
                        lyricsCache_.remove(oldest);
                        lyricsCacheTime_.remove(oldest);
                    }
                }
                lyricsCache_.insert(lyricsRequestKey_,value);
                lyricsCacheTime_.insert(lyricsRequestKey_,now);
            }
			lyricLoaded_=true;
            const QString provider=value.value(QLatin1String("provenance"))
                .toObject().value(QLatin1String("provider")).toString();
            lyricProvider_->setText(tr("Lyrics source: %1 · metadata matched, "
                "not yet verified against heard audio.")
                .arg(provider.isEmpty()?tr("user local file"):provider));
			plainLyricMode_=value.value(QLatin1String("alignment_mode")).toString()
				==QLatin1String("asr_lexical");
			lyricCues_=value.value(QLatin1String("cues")).toArray();
            lastLyricsProvider_=provider.isEmpty()?tr("local file"):provider;
            lyricRawLines_.clear();
            previewStartedMs_=now;
            previewPauseStartedMs_=0;
            previewSpeedCompensationMs_=0;
            lastVerifiedLyricIndex_=-1;
            previewIndexShift_=0;
            previewLastIndex_=-1;
            const QJsonArray originalLines=value.value(
                QLatin1String("plain_lines")).toArray();
            for(const QJsonValue &item:originalLines)
                if(item.isString() && !item.toString().trimmed().isEmpty())
                    lyricRawLines_<<item.toString().trimmed().left(350);
            if(lyricRawLines_.isEmpty() && lyricCues_.isEmpty()) {
                lyricLoaded_=false;
                lyricsEnabled_=lyricsAudioFallbackActive_;
                const QString note=tr(
                    "LYRICS TEXT UNAVAILABLE · provider returned no actual words. "
                    "Whisper vocal listening continues independently.");
                lyricText_->setText(note);
                setRadioLyricMatchStatus(note);
                return;
            }
            const bool realLyrics=!lyricRawLines_.isEmpty() ||
                !lyricCues_.isEmpty();
            // The live Whisper/Qwen matcher watches a fixed PID filename,
            // not this lookup's generation-suffixed source file.
            const bool liveCatalogPublished=publishLiveRadioLyricsCatalog(value);
            if(!liveCatalogPublished && lyricsSyncState_)
                lyricsSyncState_->setText(tr(
                    "Lyrics loaded but not shared with karaoke aligner · "
                    "check private runtime directory"));
            setRadioLyricMatchStatus(realLyrics?
                tr("LYRICS FOUND · %1 actual lines · %2 · matching live audio…")
                    .arg(lyricRawLines_.isEmpty()?lyricCues_.size():
                         lyricRawLines_.size())
                    .arg(provider.isEmpty()?tr("local file"):provider):
                tr("LYRICS NOT FOUND · provider returned no usable text"));
            // Show the first real lyric line immediately on successful
            // lookup in static-preview modes, without waiting for the next
            // ASR chunk, song-start estimate or a second station tune.
            showFoundKaraokePreview(now);
			if(plainLyricMode_) {
				lyricText_->setText(tr("Plain lyrics found. Awaiting REAL Whisper vocal matches; "
					"no fabricated timestamps."));
				lyrics_->setEnabled(true);
				if(captionProcess_.state()==QProcess::NotRunning) {
                    plainLyricsStartedAi_=true;
                    const int asr=captionSource_->findData(QLatin1String("asr"));
                    if(asr>=0) captionSource_->setCurrentIndex(asr);
					startCaptioning();
                }
				return;
			}
			// Manual timing is anchored to the lookup result, not fake audio matching.
			manualSongStartMs_=QDateTime::currentMSecsSinceEpoch();
			lyricText_->setText(tr("%1 synchronized lyric lines · estimated "
				"from DLS time; adjust offset as necessary.")
				.arg(lyricCues_.size()));
		} else if (value.value(QLatin1String("status")).toString()==QLatin1String("error")) {
            // A failed provider request is NOT a successfully loaded lyric
            // catalog. Mark it absent so a later explicit owner retry can
            // fetch actual words without needing a station retune.
            lyricLoaded_=false;
            lyricsEnabled_=false;
            lyrics_->setEnabled(true);
            stopLyrics_->setEnabled(false);
            const QString reason=value.value(QLatin1String("reason")).toString().left(190);
			lyricText_->setText(tr("Lyrics unavailable: %1").arg(reason));
            setRadioLyricMatchStatus(tr(
                "LYRICS NOT FOUND · Whisper fallback · %1")
                .arg(reason.isEmpty()?tr("provider returned no text"):reason));
            lyricProvider_->setText(tr("No trusted online lyrics; no radio audio uploaded."));
            if(listenFallbackOnMiss_->isChecked()) beginLyricListening();
		}
	}
	MediaWidget *player_;
	QLabel *radioCanvas_=nullptr,*radioCanvasStation_=nullptr;
	QWidget *playerHost_=nullptr;
	QVBoxLayout *playerHostLayout_=nullptr;
	QTabWidget *modes_=nullptr;
    QSplitter *stationSplit_=nullptr;
    QLabel *selectedSource_=nullptr,*selectedStationVintage_=nullptr,
           *vintageDabReadout_=nullptr;
	QComboBox *lyricsSourceLanguage_=nullptr;
    QLabel *translationStatus_=nullptr,*spokenModelStatus_=nullptr;
    QLabel *radioTranslationBanner_=nullptr;
    QLabel *radioCanvasCaption_=nullptr,*radioLyricMatchStatus_=nullptr;
    QLabel *radioAudioHealth_=nullptr;
    QLabel *radioAudioOutputStatus_=nullptr;
    QSlider *radioOutputVolume_=nullptr;
    QPushButton *radioMuteButton_=nullptr,*radioReconnectAudio_=nullptr,
                *radioAudioDiagnostics_=nullptr;
    QLabel *receiverOwnership_=nullptr;
    QCheckBox *advancedLanguages_=nullptr;
	QComboBox *channel_=nullptr, *driver_=nullptr, *speechLanguage_=nullptr,
		*captionSource_=nullptr,
		*plotKind_=nullptr, *fftPlacement_=nullptr;
	QPushButton *quickLanguageButton_=nullptr;
    QPushButton *start_=nullptr,*stop_=nullptr,*forceRelease_=nullptr,
        *scan_=nullptr,*record_=nullptr,
		*caption_=nullptr,*applyCaptions_=nullptr,
		*stopCaption_=nullptr,*lyrics_=nullptr,*lyricsImport_=nullptr,*stopLyrics_=nullptr,
        *listenLyrics_=nullptr,
		*slidePrev_=nullptr,*slideNext_=nullptr;
	QTreeWidget *stations_=nullptr;
    QComboBox *stationListPicker_=nullptr;
    QPushButton *newStationList_=nullptr,*deleteStationList_=nullptr,
        *addStationList_=nullptr,*removeStationList_=nullptr;
    QCheckBox *stationListOnly_=nullptr;
    QMap<QString,QSet<QString>> stationLists_;
	QComboBox *libraryBlock_=nullptr;
	QLineEdit *stationSearch_=nullptr;
	QLineEdit *webSearch_=nullptr,*webSource_=nullptr;
	QComboBox *webCountry_=nullptr;
	QPushButton *webSearchButton_=nullptr,*webPlay_=nullptr,*webStop_=nullptr,
		*webProbeButton_=nullptr,*webAlternate_=nullptr;
	QProcess internetProbe_{this};
	QString testedWebUrl_;
	QTreeWidget *webStations_=nullptr;
	QCheckBox *webFavoritesOnly_=nullptr;
	QLabel *webStatus_=nullptr;
	QProgressBar *rfQuality_=nullptr;
	QProgressBar *scanProgress_=nullptr,*scanSNR_=nullptr,
		*stationOpenProgress_=nullptr;
	QMap<QString,double> scanSnrByBlock_;
	QSet<QString> scanObserved_;
	QCheckBox *multiRf_=nullptr;
	QWidget *multiPanel_=nullptr;
	QList<QLabel*> multiPlots_;
	int multiRfIndex_=0;
	QLabel *analogStatus_=nullptr;
	QComboBox *analogBand_=nullptr;
	QDoubleSpinBox *analogFrequency_=nullptr;
	QDial *analogDial_=nullptr;
	QSlider *analogVolume_=nullptr,*mainBufferSlider_=nullptr,
        *mainCaptionOffsetSlider_=nullptr,*mainLyricOffsetSlider_=nullptr;
    QLabel *mainBufferReadout_=nullptr,*mainLyricOffsetReadout_=nullptr;
	QPushButton *analogMute_=nullptr;
	QLabel *analogDigital_=nullptr;
	QProgressBar *analogAudioVu_=nullptr;
	qint64 lastAnalogVuUpdateMs_=0;
	TihuluAnalogScale *analogScale_=nullptr;
	QTimer analogRetune_{this};
	QTcpServer analogServer_{this};
	QSet<QTcpSocket*> analogSockets_,analogStreaming_;
	QHash<QTcpSocket*,QByteArray> analogRequests_;
	bool analogSocketsWired_=false;
	QPushButton *analogStart_=nullptr,*analogStop_=nullptr;
	QCheckBox *directSampling_=nullptr;
	bool analogStopping_=false;
	QSet<QString> internetFavorites_;
	bool webPlaying_=false,webCatalogRequested_=false,languagePacksLoaded_=false;
	QCheckBox *favoritesOnly_=nullptr;
	QLabel *libraryStatus_=nullptr;
	QSet<QString> favorites_;
	QLabel *state_=nullptr,*playStatus_=nullptr,*dls_=nullptr,*signal_=nullptr,*slide_=nullptr,
		*radioCaption_=nullptr,*radioCaptionBanner_=nullptr,
        *lyricText_=nullptr,*plot_=nullptr;
	QCheckBox *english_=nullptr,*german_=nullptr,*turkish_=nullptr,*music_=nullptr,
		*speakerLabels_=nullptr,
		*livePlot_=nullptr,*showWidgets_=nullptr,
		*coarseCorrector_=nullptr;
	QSlider *lyricsOffset_=nullptr;
	QLabel *lyricsOffsetValue_=nullptr,*lyricsSyncState_=nullptr,
        *lyricProvider_=nullptr,*karaokeEngineStatus_=nullptr;
	QProgressBar *captionProgress_=nullptr,*audioCacheProgress_=nullptr,
                 *quickBufferProgress_=nullptr;
	QLabel *bufferRecommendation_=nullptr;
	qint64 audioStartedMs_=0,lastLyricSyncUpdateMs_=0,
        lastCaptionVisibleMs_=0,lastCanvasLyricMs_=0,lastCaptionUpdateMs_=0,
        lastUnmatchedVoiceUntilMs_=0,lastMatchedLyricUntilMs_=0,
        captionReadingHoldUntilMs_=0,captionDisplayedStartedMs_=0;
    bool tvHandoffInProgress_=false;
    bool lastLyricsAutoLookup_=false;
    QString pendingSongKey_,pendingSongDls_,lyricsRequestKey_;
    TihuluDlsSong pendingSongHint_,lastObservedSongHint_,lastAcceptedSongHint_;
    int pendingSongObservations_=0;
    qint64 pendingSongSinceMs_=0,lastObservedSongMs_=0,
           lyricsLookupCooldownUntilMs_=0;
    quint64 lyricsLookupGeneration_=0;
    QMap<QString,QJsonObject> lyricsCache_;
    QMap<QString,qint64> lyricsCacheTime_;
    QString lyricsRefreshPath_,lyricsRefreshRequestKey_,
            lyricsRefreshStationKey_,lyricsRefreshSongKey_;
    qint64 lyricsRefreshStartedMs_=0;
    quint64 lyricsRefreshStationTicket_=0;
    bool lyricsRefreshPending_=false;
	bool metadataCaptions_=false;
	int dlsCaptionIndex_=0;
	int lastLyricOffsetMs_=0;
	bool plainLyricMode_=false;
	QList<TimedPlainLyric> plainLyricQueue_,verifiedLyricQueue_;
    QCheckBox *karaokeEnabled_=nullptr,
        *karaokeTranslationsEnabled_=nullptr,
        *soundLabels_=nullptr;
    QComboBox *karaokePolicy_=nullptr,*karaokeAligner_=nullptr,
              *lyricMatchMode_=nullptr;
    QPushButton *previewPrevious_=nullptr,*previewNext_=nullptr,
                *fullLyricsButton_=nullptr;
    QPointer<QDialog> fullLyricsDialog_;
    qint64 previewStartedMs_=0,previewSpeedCompensationMs_=0,
           previewPauseStartedMs_=0;
    int lastVerifiedLyricIndex_=-1;
    int previewPreviousSpeedPercent_=100;
    int previewIndexShift_=0,previewLastIndex_=-1,
        previewLastHighlightedWord_=-2;
	QCheckBox *autoLyrics_=nullptr,*autoLyricSync_=nullptr,
		*preferLyrics_=nullptr,*listenFallbackOnMiss_=nullptr;
    bool lyricsAudioFallbackActive_=false,lyricsFallbackStartedAi_=false,
        plainLyricsStartedAi_=false,captionsStopping_=false;
    int captionRecoveryFailures_=0;
    qint64 captionRecoveryNextMs_=0,captionRecoveryLastAttemptMs_=0,
           captionRecoveryLastSuccessMs_=0;
	QSpinBox *bufferMs_=nullptr,*radioOffsetMs_=nullptr,
        *lyricMatchThreshold_=nullptr,*karaokePreviewSpeed_=nullptr;
    QComboBox *bufferUnit_=nullptr;
    bool bufferUnitsSeconds_=false;
    QHBoxLayout *radioQuickRow_=nullptr,*radioPlaybackRow_=nullptr;
    QCheckBox *quickAi_=nullptr,*quickTranslate_=nullptr,
        *quickBuffer_=nullptr,*releaseOnStop_=nullptr;
    QSpinBox *karaokeSyncHistorySeconds_=nullptr;
    QList<RecentKaraokeEvidence> recentKaraokeEvidence_;
    int karaokeSyncRefreshToken_=0,lastHandledKaraokeSyncToken_=0;
    qint64 lastHandledQwenCaptureEpochMs_=0;
    QPushButton *captionEarlier_=nullptr,*captionLater_=nullptr,
        *captionRefresh_=nullptr,*aiSyncRefresh_=nullptr,
        *radioSyncRefresh_=nullptr,*lyricsRefresh_=nullptr;
    QLabel *captionOffsetReadout_=nullptr;
    QComboBox *radioReadingPreset_=nullptr;
    QSpinBox *radioCaptionFontSize_=nullptr;
	QCheckBox *autoSync_=nullptr,*autoRestartAudio_=nullptr;
	int lastCaptionOffsetMs_=0;
    int activePlaybackCacheMs_=0;
    bool dabPlaybackObserved_=false,analogPlaybackObserved_=false;
    qint64 dabIdleSinceMs_=0,analogIdleSinceMs_=0;
    qint64 lastAudioRetuneMs_=0;
	QList<TimedRadioCue> cueQueue_;
	QLineEdit *extraTargets_=nullptr,*lyricsArtist_=nullptr,*lyricsTitle_=nullptr;
	QLabel *syncStatus_=nullptr;
	QProcess backend_,captionProcess_,recorder_,lyricsProcess_,
        lyricsRefreshProcess_,recordAi_,recordMux_,languagePackWorker_;
	QListWidget *installedTargets_=nullptr;
	QPushButton *refreshTargets_=nullptr;
	QString recordedPath_;
	bool recordWithSubtitles_=false;
	QCheckBox *subtitledRecord_=nullptr;
	QProcess analogDemod_{this};
	QNetworkAccessManager network_;
	QTimer tick_,captionTick_,rfTick_;
	quint16 port_=0;
	bool apiReady_=false;
	int apiWaitCount_=0;
    quint64 receiverGeneration_=0;
	bool scanning_=false,shuttingDown_=false,slidePending_=false,lyricLoaded_=false,
		lyricsEnabled_=false,
		plotPending_=false;
	int scanIndex_=0;
	quint64 scanRequestId_=0,stationRequestId_=0;
	qint64 songStartMs_=0,manualSongStartMs_=0;
	QString lastWelleError_,lastAnalogError_;
    QString lastVerifiedLyricText_;
    QString lastErrorStation_;
    qint64 lastRfFrameErrors_=-1,lastRfRsErrors_=-1,lastRfAacErrors_=-1;
    QJsonObject lastVerifiedLyricTranslations_;
    QStringList lyricRawLines_;
    QString lastLyricsProvider_;
    qint64 lastKaraokeUntilMs_=0;
    QString karaokeLine_;
    QJsonArray karaokeWordAnchors_;
    int lastHighlightedKaraokeWord_=-2;
    QLabel *karaokeSource_=nullptr,*karaokePrevious_=nullptr,
        *karaokeCurrent_=nullptr,*karaokeNext_=nullptr,
        *karaokeTranslation_=nullptr;
    QWidget *karaokePanel_=nullptr;
    qint64 lastVerifiedLyricMs_=0;
    int lastLyricDirection_=0,lyricOffsetConsistency_=0;
	QString activeChannel_,playingKey_,captionBoundStationKey_,lastDls_,lastSongDls_,lastSongMetadataKey_,captionPath_,captionControlsPath_,lyricPath_,
		wellePortFile_,
		lastDetectedLanguage_;
	QMap<QString,QJsonObject> stationData_;
	QMap<QString,QString> stationChannels_;
	QJsonArray lyricCues_;
	QJsonObject lastMux_;
	QList<int> lagSamples_;
	int lastRadioChunk_=-1,displayedRadioChunk_=-1,
        lastRadioRevision_=-1;
	qint64 lastAdjustmentMs_=0,radioCueDueMs_=0;
	QString pendingRadioCue_;
	QList<QPixmap> slideHistory_;
	QByteArray lastSlideHash_;
	QImage waterfall_;
	int slideIndex_=0;
};

#endif // TIHULU_NATIVE_RADIO_TAB_H
