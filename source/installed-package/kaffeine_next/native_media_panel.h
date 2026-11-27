/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef TIHULU_NATIVE_MEDIA_PANEL_H
#define TIHULU_NATIVE_MEDIA_PANEL_H
#include "mediawidget.h"
#include "tihulu_ai_process.h"
#include "tihulu_caption_options.h"
#include "tihulu_file_captions.h"
#include <QCheckBox>
#include <QCoreApplication>
#include <QDateTime>
#include <QDialog>
#include <QFormLayout>
#include <QSpinBox>
#include <QDialogButtonBox>
#include <QDir>
#include <QDragEnterEvent>
#include <QDropEvent>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QJsonDocument>
#include <QLabel>
#include <QMimeData>
#include <QMimeDatabase>
#include <QProgressBar>
#include <QPushButton>
#include <QSettings>
#include <QStandardPaths>
#include <QTimer>
#include <QVBoxLayout>

class TihuluMediaPanel final : public QWidget {
public:
    explicit TihuluMediaPanel(MediaWidget *player,QWidget *parent=nullptr)
        :QWidget(parent),player_(player),process_(this),live_(this),exportProcess_(this) {
        setObjectName(QStringLiteral("tihuluMediaPanel"));setAcceptDrops(true);
        auto *root=new QVBoxLayout(this);root->setContentsMargins(8,4,8,4);root->setSpacing(3);
        auto *row=new QHBoxLayout();
        file_=new QLabel(tr("Drop a video or audio file here"),this);
        file_->setTextFormat(Qt::PlainText);file_->setMinimumWidth(80);
        row->addWidget(file_,1);
        liveButton_=new QPushButton(tr("AI captions panel"),this);
        run_=new QPushButton(tr("Transcribe file"),this);
        karaoke_=new QPushButton(tr("Karaoke / lyrics"),this);
        karaoke_->setToolTip(tr("Audio only: time-coded lyrics from a matching local .lrc beside the file, "
            "or optionally from LRCLIB by title/artist. No invented timings."));
        karaoke_->setEnabled(false);
        cancel_=new QPushButton(tr("Stop AI"),this);cancel_->setEnabled(false);
        mpvButton_=new QPushButton(tr("Open in mpv"),this);
        mpvButton_->setToolTip(tr("Hands the current media (local file or stream) to the mpv player "
            "with its subtitles. The built-in VLC engine stays default."));
        row->addWidget(liveButton_);row->addWidget(run_);row->addWidget(karaoke_);row->addWidget(cancel_);row->addWidget(mpvButton_);
        root->addLayout(row);
        message_=new QLabel(tr("Local AI · choose languages and an installed model in Options."),this);
        message_->setTextFormat(Qt::PlainText);message_->setWordWrap(true);root->addWidget(message_);
        progress_=new QProgressBar(this);progress_->hide();root->addWidget(progress_);
        captions_=new TihuluFileCaptions(player);
        // The full caption window owns languages, model, appearance and the
        // File tab (whole-file transcribe, karaoke, SRT, export). This panel
        // keeps only the quick delivery/player switches.
        choices_=new TihuluCaptionOptions(this);
        choices_->hide();
        serviceMode_=new QComboBox(this);
        serviceMode_->addItem(tr("Auto · video uses TV service, audio uses Radio service"),QStringLiteral("auto"));
        serviceMode_->addItem(tr("TV caption service (all settings)"),QStringLiteral("tv"));
        serviceMode_->addItem(tr("Radio caption service (all settings)"),QStringLiteral("radio"));
        serviceMode_->setToolTip(tr("File type decides the default. TV and Radio use their own saved languages, models and tools."));
        liveWindow_=new QSpinBox(this);liveWindow_->setRange(2,20);liveWindow_->setSuffix(tr(" s"));
        liveWindow_->setValue(8);liveWindow_->setToolTip(tr("Live audio window used by the local speech model. Larger = more context, slower first caption."));
        externalPlayer_=new QCheckBox(tr("Play local files with mpv"),this);
        QSettings playerPrefs(QStringLiteral("TIHULU"),QStringLiteral("MediaPlayer"));
        externalPlayer_->setChecked(playerPrefs.value(QStringLiteral("externalPlayerMpv"),false).toBool() &&
                                   !QStandardPaths::findExecutable(QStringLiteral("mpv")).isEmpty());
        externalPlayer_->setToolTip(tr("Optional: local video/audio opens in mpv together with its subtitles. "
            "TV, radio and streams keep the built-in VLC engine."));
        embedVideo_=new QCheckBox(tr("Video: embed the SRT (.mkv copy)"),this);
        embedVideo_->setChecked(true);embedVideo_->setToolTip(tr("Default for video files. The generated .mkv keeps your original "
            "file untouched and carries the SRT as a selectable track."));
        preprocess_=new QCheckBox(tr("Transcribe before opening a file"),this);
        QSettings config("TIHULU","MediaPlayer");preprocess_->setChecked(config.value("transcribeBeforeOpen",false).toBool());
        wait_=new QCheckBox(tr("Wait for subtitles before playback"),this);wait_->setChecked(true);
        auto *fileOptions=new QHBoxLayout();
        fileOptions->addWidget(new QLabel(tr("Service:"),this));
        fileOptions->addWidget(serviceMode_);
        fileOptions->addWidget(new QLabel(tr("Buffer:"),this));
        fileOptions->addWidget(liveWindow_);
        fileOptions->addWidget(externalPlayer_);
        fileOptions->addWidget(embedVideo_);
        fileOptions->addWidget(preprocess_);
        fileOptions->addWidget(wait_);
        overlayMode_=new QComboBox(this);
        overlayMode_->addItem(tr("Caption overlay: compact (default)"),QStringLiteral("compact"));
        overlayMode_->addItem(tr("Caption overlay: off"),QStringLiteral("off"));
        overlayMode_->addItem(tr("Caption overlay: full"),QStringLiteral("full"));
        QSettings overlayPrefs(QStringLiteral("TIHULU"),QStringLiteral("CaptionOverlay"));
        const QString overlayKey=overlayPrefs.value(QStringLiteral("mode"),QStringLiteral("compact")).toString();
        overlayMode_->setCurrentIndex(overlayMode_->findData(overlayKey));
        overlayMode_->setToolTip(tr("Video overlay size. Off keeps captions in the caption window only; "
            "compact shows a strip of at most a quarter of the video."));
        fileOptions->addWidget(new QLabel(tr("Overlay:"),this));
        fileOptions->addWidget(overlayMode_);
        connect(overlayMode_,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int){
            QSettings saved(QStringLiteral("TIHULU"),QStringLiteral("CaptionOverlay"));
            saved.setValue(QStringLiteral("mode"),overlayMode_->currentData().toString());
            saved.sync();
        });
        // Hold for AI analysis: while the AI is still analysing a real audio
        // interval, hold the video so the captions stay accurate, then resume.
        holdForAnalysis_=new QCheckBox(this);
        holdForAnalysis_->setText(tr("Hold for AI analysis"));
        {
            QSettings holdPrefs(QStringLiteral("TIHULU"),QStringLiteral("CaptionHold"));
            holdForAnalysis_->setChecked(
                holdPrefs.value(QStringLiteral("enabled"),true).toBool());
        }
        holdForAnalysis_->setToolTip(tr(
            "While Whisper still has audio windows to analyse, playback is held "
            "so the captions stay accurate, then it resumes. A long analysis "
            "never freezes the video."));
        connect(holdForAnalysis_,&QCheckBox::toggled,this,[](bool value){
            QSettings saved(QStringLiteral("TIHULU"),QStringLiteral("CaptionHold"));
            saved.setValue(QStringLiteral("enabled"),value);
            saved.sync();
        });
        fileOptions->addWidget(holdForAnalysis_);
        fileOptions->addStretch(1);
        root->addLayout(fileOptions);
        connect(preprocess_,&QCheckBox::toggled,this,[](bool value){QSettings("TIHULU","MediaPlayer").setValue("transcribeBeforeOpen",value);});
        connect(externalPlayer_,&QCheckBox::toggled,this,[](bool value){QSettings("TIHULU","MediaPlayer").setValue("externalPlayerMpv",value);});
        connect(serviceMode_,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int){applyServiceMode();});
        connect(karaoke_,&QPushButton::clicked,this,[this](){generateKaraoke();});
        connect(run_,&QPushButton::clicked,this,[this](){generate(false);});
        connect(mpvButton_,&QPushButton::clicked,this,[this](){openInMpv();});
        connect(liveButton_,&QPushButton::clicked,this,[this](){startLive();});
        connect(cancel_,&QPushButton::clicked,this,[this](){stopAi();player_->cancelFileCaptionHold();});
        connect(player_,&MediaWidget::stopRequested,this,[this](){if(!internalStop_)stopAi();});
        connect(player_,&MediaWidget::sourceOpened,this,[this](const QUrl &url){setLocalFile(url);});
        connect(player_,&MediaWidget::fileOpenRequested,this,[this](const QUrl &url,bool *handled){
            setLocalFile(url);if(!resuming_)*handled=prepareLocalFileOpen(url);
        });
        connect(player_,&MediaWidget::subtitleOpened,this,[this](const QUrl &url,bool *handled){
            if(!path_.isEmpty() && url.isLocalFile() && url.toLocalFile().endsWith(".srt",Qt::CaseInsensitive)) {
                *handled=true;srt_=url.toLocalFile();captions_->loadSrt(srt_);
            }
        });
        connect(&process_,&QProcess::readyReadStandardOutput,this,[this](){
            while(process_.canReadLine()) {
                const QByteArray line=process_.readLine();
                if(!line.startsWith("TIHULU_PROGRESS ")) {result_+=line;continue;}
                const auto fields=line.trimmed().split(' ');if(fields.size()!=3)continue;
                bool ok=false;const int pct=fields[2].toInt(&ok);if(!ok || pct< -1 || pct>100)continue;
                progress_->setRange(0,pct<0?0:100);progress_->setValue(qMax(0,pct));
                progress_->setFormat((fields[1]=="translate"?tr("Translating"):fields[1]=="save"?tr("Saving"):tr("Transcribing"))+(pct<0?QString():tr(" · %p%")));
            }
        });
        connect(&process_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),this,[this](int code,QProcess::ExitStatus exit){
            progress_->hide();cancel_->setEnabled(false);run_->setEnabled(!path_.isEmpty());liveButton_->setEnabled(!path_.isEmpty());
            if(cancelled_)return;
            result_+=process_.readAllStandardOutput();
            if(code || exit!=QProcess::NormalExit || !QFileInfo(srt_).isFile()) {
                message_->setText(tr("Offline captions unavailable: %1").arg(QString::fromUtf8(process_.readAllStandardError()).right(300)));
                return;
            }
            captions_->setKaraoke(isAudioRequest_);
            captions_->loadSrt(srt_);
            if(resumeAfter_) {resuming_=true;player_->play(QUrl::fromLocalFile(path_));resuming_=false;}
            if(embedVideo_ && embedVideo_->isChecked() && isVideo_)embedSubtitledVideo();
            const auto result=QJsonDocument::fromJson(result_).object();
            const int warnings=result.value("translation_warning_count").toInt();
            const auto details=result.value("translation_warnings").toArray();
            message_->setText(warnings?tr("SRT saved; %1 translation warnings. %2").arg(warnings).arg(details.isEmpty()?QString():details.first().toObject().value("warning").toString()):tr("Captions ready · %1").arg(srt_));
        });
        connect(&live_,&QProcess::readyReadStandardOutput,this,[this](){
            while(live_.canReadLine()) {
                const auto reply=QJsonDocument::fromJson(live_.readLine()).object();
                if(reply.isEmpty())continue;
                pending_=false;
                if(reply.value("revision").toInt()!=revision_)continue;
                if(reply.contains("error")) {stopLive(false);message_->setText(tr("Live captions: %1").arg(reply.value("error").toString()));}
                else {
                    captions_->append(reply.value("cues").toArray());nextMs_=reply.value("end").toDouble();
                    const QString warning=reply.value("warning").toString();
                    message_->setText(!warning.isEmpty()?warning:nextMs_<player_->getPosition()?tr("AI is behind playback; skipping stale captions."):tr("Live captions · local audio · synchronized to playback position"));
                    if(reply.value("eof").toBool())stopLive(false);
                }
            }
        });
        connect(&live_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),this,[this](int code,QProcess::ExitStatus){
            liveClock_.stop();pending_=false;cancel_->setEnabled(false);
            if(!cancelled_)player_->cancelFileCaptionHold();
            if(code && !cancelled_)message_->setText(tr("Live captions stopped: %1").arg(QString::fromUtf8(live_.readAllStandardError()).right(240)));
        });
        connect(&liveClock_,&QTimer::timeout,this,[this](){tickLive();});
        connect(&exportProcess_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),this,[this](int code,QProcess::ExitStatus status){
            if(code==0 && status==QProcess::NormalExit) {
                message_->setText(tr("Subtitled file ready: %1").arg(exportPath_));
                internalStop_=true;player_->stop();internalStop_=false;
                resuming_=true;player_->play(QUrl::fromLocalFile(exportPath_));resuming_=false;
            } else {
                const QString reason=QString::fromUtf8(exportProcess_.readAllStandardError()).right(300);
                message_->setText(tr("Export failed; source and SRT preserved.%1")
                    .arg(reason.isEmpty()?QString():QStringLiteral("\n")+reason));
            }
        });
        run_->setEnabled(false);liveButton_->setEnabled(false);
    }
    ~TihuluMediaPanel() override {cancelled_=true;process_.stopJob();live_.stopJob();exportProcess_.stopJob();}
    void setLocalFile(const QUrl &url) {
        const QString candidate=url.isLocalFile() && QFileInfo(url.toLocalFile()).isFile()?url.toLocalFile():QString();
        if(candidate==path_)return;
        stopAi();captions_->setSticky(false);captions_->clearCues();path_=candidate;srt_.clear();
        run_->setEnabled(!path_.isEmpty());liveButton_->setEnabled(!path_.isEmpty());
        if(path_.isEmpty()) {file_->setText(tr("Drop a video or audio file here"));return;}
        const QFileInfo info(path_);file_->setText(info.fileName());file_->setToolTip(path_);
        isVideo_=!QMimeDatabase().mimeTypeForFile(path_).name().startsWith("audio/");
        applyServiceMode();
        srt_=info.absolutePath()+QLatin1Char('/')+info.completeBaseName()+QStringLiteral(".srt");
        if(QFileInfo(srt_).isFile())captions_->loadSrt(srt_);
        message_->setText(tr("Ready · Live captions follows playback; Transcribe file creates a reusable SRT."));
    }
    // Any current source can be handed to the external mpv player on demand.
    void openInMpv() {
        if(QStandardPaths::findExecutable(QStringLiteral("mpv")).isEmpty()) {
            message_->setText(tr("mpv is not installed; the built-in VLC engine stays in use."));
            return;
        }
        QStringList args{QStringLiteral("--keep-open=no")};
        if(!path_.isEmpty() && QFileInfo(path_).isFile()) {
            const QString media=path_;
            const QString srt=QFileInfo(media).absolutePath()+QLatin1Char('/')+
                QFileInfo(media).completeBaseName()+QStringLiteral(".srt");
            if(QFileInfo(srt).isFile())args<<QStringLiteral("--sub-file=")+srt;
            args<<media;
        } else {
            const QUrl stream=player_->property("tihulu_recordable_url").toUrl();
            if(!stream.isValid()) {message_->setText(tr("Nothing playing to hand to mpv."));return;}
            args<<stream.toString();
        }
        externalPlayerProcess_.start(QStringLiteral("mpv"),args);
        if(!externalPlayerProcess_.waitForStarted(600))
            message_->setText(tr("mpv could not start."));
        else
            message_->setText(tr("Opened in mpv · VLC playback stays untouched."));
    }
    // Radio-style karaoke for audio files: real time-coded lyrics only.
    void generateKaraoke() {
        if(path_.isEmpty() || process_.state()!=QProcess::NotRunning || tvMode_)return;
        stopLive();cancelled_=false;result_.clear();
        const QString cache=QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
        if(cache.isEmpty() || !QDir().mkpath(cache)) {message_->setText(tr("Cannot create a private lyric cache."));return;}
        srt_=cache+QStringLiteral("/tihulu-lyrics-")+
            QString::number(QCoreApplication::applicationPid())+QLatin1Char('-')+
            QString::number(QDateTime::currentMSecsSinceEpoch())+QStringLiteral(".srt");
        QStringList args{QStringLiteral("media-captions"),QStringLiteral("--input"),path_,
                         QStringLiteral("--lyrics"),QStringLiteral("--music"),
                         QStringLiteral("--output"),srt_};
        if(onlineLyrics_ && onlineLyrics_->isChecked())args<<QStringLiteral("--fetch-lyrics");
        process_.start(QStringLiteral("tihulu-tv-center"),args);
        if(!process_.waitForStarted(800)) {message_->setText(tr("Lyric worker could not start."));return;}
        run_->setEnabled(false);karaoke_->setEnabled(false);liveButton_->setEnabled(false);cancel_->setEnabled(true);
        progress_->setRange(0,0);progress_->show();
        message_->setText(tr("Reading time-coded lyrics for this audio file…"));
    }
    // TV service for video files, Radio service for audio files; a manual choice wins.
    void applyServiceMode() {
        const QString mode=serviceMode_?serviceMode_->currentData().toString():QStringLiteral("auto");
        tvMode_=mode==QStringLiteral("tv") || (mode==QStringLiteral("auto") && isVideo_);
        const bool audio=!tvMode_;
        QSettings prefs("TIHULU",audio?"KaffeineRadio":"KaffeineTVFileCaptionDefaults");
        QStringList targets=prefs.value(audio?"radioOutputs":"outputLanguages",QStringList()).toStringList();
        if(!prefs.value(audio?"radioTranslationOptIn":"showTranslation",!audio).toBool())targets.clear();
        choices_->setLanguages(prefs.value(audio?"radioSpeechLanguage":"spokenSource","auto").toString(),targets);
        if(music_)music_->setChecked(prefs.value(audio?"radioMusicTranscription":"musicTranscription",false).toBool());
        if(original_)original_->setChecked(audio || prefs.value("showOriginal",true).toBool());
        if(lyrics_)lyrics_->setEnabled(audio);
        if(onlineLyrics_)onlineLyrics_->setEnabled(audio && (lyrics_ && lyrics_->isChecked()));
        if(karaoke_)karaoke_->setEnabled(audio);
        if(!audio && lyrics_)lyrics_->setChecked(false);
        message_->setText(tvMode_?
            tr("TV caption service · video settings (languages, model, appearance, SRT export)"):
            tr("Radio caption service · audio settings (languages, karaoke/lyrics, offset, SRT export)"));
    }
    bool prepareLocalFileOpen(const QUrl &url) {
        // Optional mpv playback: the external player opens the file with its
        // sidecar/generated subtitles; nothing else changes for TV/radio.
        if(url.isLocalFile() && externalPlayer_ && externalPlayer_->isChecked() &&
           QFileInfo(url.toLocalFile()).isFile() &&
           !QStandardPaths::findExecutable(QStringLiteral("mpv")).isEmpty()) {
            const QString media=url.toLocalFile();
            const QString srt=QFileInfo(media).absolutePath()+QLatin1Char('/')+
                QFileInfo(media).completeBaseName()+QStringLiteral(".srt");
            QStringList args{QStringLiteral("--keep-open=no")};
            if(QFileInfo(srt).isFile())args<<QStringLiteral("--sub-file=")+srt;
            args<<media;
            externalPlayerProcess_.start(QStringLiteral("mpv"),args);
            if(externalPlayerProcess_.waitForStarted(600)) {
                message_->setText(tr("Opened in mpv: %1").arg(QFileInfo(media).fileName()));
                return true;
            }
        }
        if(!url.isLocalFile() || path_.isEmpty() || !preprocess_->isChecked())return false;
        generate(true);return true;
    }
protected:
    void dragEnterEvent(QDragEnterEvent *event) override {if(event->mimeData()->hasUrls())event->acceptProposedAction();}
    void dropEvent(QDropEvent *event) override {
        const auto urls=event->mimeData()->urls();if(urls.isEmpty())return;
        player_->play(urls.first());event->acceptProposedAction();
    }
private:
    void stopLive(bool clear=true) {
        liveClock_.stop();live_.stopJob();pending_=false;
        if(clear)captions_->setSticky(false),captions_->clearCues();
    }
    void stopAi() {
        cancelled_=true;resumeAfter_=false;++revision_;process_.stopJob();stopLive(live_.state()!=QProcess::NotRunning);
        progress_->hide();cancel_->setEnabled(false);run_->setEnabled(!path_.isEmpty());liveButton_->setEnabled(!path_.isEmpty());
        message_->setText(tr("AI stopped · local workers released."));
    }
    QStringList jobArguments(bool live) {
        QStringList args{QStringLiteral("media-captions"),QStringLiteral("--input"),path_};
        if(!choices_->appendArguments(args)) {
            // Language/model catalog not ready: open the full caption window
            // where the same settings live (it refreshes them on start).
            openFullCaptionWindow();return {};
        }
        if(music_ && music_->isChecked())args<<QStringLiteral("--music");
        if(original_ && !original_->isChecked())args<<QStringLiteral("--translations-only");
        args<<QStringLiteral("--service")<<(tvMode_?QStringLiteral("tv"):QStringLiteral("radio"));
        if(liveWindow_)args<<QStringLiteral("--window")<<QString::number(liveWindow_->value());
        if(live)args<<QStringLiteral("--live");
        return args;
    }
    void generate(bool beforeOpen) {
        if(path_.isEmpty() || process_.state()!=QProcess::NotRunning)return;
        auto args=jobArguments(false);if(args.isEmpty())return;
        stopLive();captions_->clearCues();
        const QString cache=QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
        if(cache.isEmpty() || !QDir().mkpath(cache)) {message_->setText(tr("Cannot create subtitle cache."));return;}
        isAudioRequest_=!tvMode_;
        srt_=cache+QStringLiteral("/tihulu-file-")+QString::number(QCoreApplication::applicationPid())+QLatin1Char('-')+QString::number(QDateTime::currentMSecsSinceEpoch())+QStringLiteral(".srt");
        args<<QStringLiteral("--output")<<srt_;
        if(lyrics_ && lyrics_->isChecked() && !beforeOpen) {args<<QStringLiteral("--lyrics");if(onlineLyrics_ && onlineLyrics_->isChecked())args<<QStringLiteral("--fetch-lyrics");}
        resumeAfter_=beforeOpen || wait_->isChecked();cancelled_=false;result_.clear();
        if(resumeAfter_) {internalStop_=true;player_->stop();internalStop_=false;}
        process_.start(QStringLiteral("tihulu-tv-center"),args);
        if(!process_.waitForStarted(800)) {message_->setText(tr("Offline AI companion could not start."));return;}
        run_->setEnabled(false);liveButton_->setEnabled(false);cancel_->setEnabled(true);
        progress_->setRange(0,0);progress_->show();message_->setText(tr("Preparing local subtitles…"));
    }
    void openFullCaptionWindow() {
        // Guard: the caption window itself refreshes the language catalog, so
        // a failed probe must not re-enter this path from generate()/startLive().
        if(openingCaptionWindow_ || live_.state()!=QProcess::NotRunning)return;
        openingCaptionWindow_=true;
        startLive();
        openingCaptionWindow_=false;
    }
    // Opens the FULL caption service (same window as live TV: appearance,
    // reading modes, model market, SRT recording) driven by this file's audio.
    void startLive() {
        if(path_.isEmpty() || process_.state()!=QProcess::NotRunning)return;
        const QString runtime=QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
        if(runtime.isEmpty()) {message_->setText(tr("XDG_RUNTIME_DIR is missing; cannot start the caption service."));return;}
        QStringList captionArgs;
        if(!choices_->appendArguments(captionArgs)) {
            openFullCaptionWindow();return;
        }
        stopLive();cancelled_=false;++revision_;
        // Local file playback is a SEPARATE caption service from live TV:
        // its own service name and its own private runtime socket, so the
        // file service can never reuse, focus or stop the TV caption service.
        const QString name=runtime+QStringLiteral("/tihulu-file-")+
            QString::number(QCoreApplication::applicationPid())+QStringLiteral(".sock");
        QStringList args{QStringLiteral("kaffeine-captions-file"),QStringLiteral("--socket"),name,
                         QStringLiteral("--file"),path_};
        for(int i=0;i<captionArgs.size();++i) {
            if(captionArgs.value(i)==QStringLiteral("--source") && i+1<captionArgs.size())
                args<<QStringLiteral("--source")<<captionArgs.value(i+1);
            else if(captionArgs.value(i)==QStringLiteral("--targets") && i+1<captionArgs.size())
                args<<QStringLiteral("--targets")<<captionArgs.value(i+1);
        }
        if(liveWindow_)args<<QStringLiteral("--window")<<QString::number(liveWindow_->value());
        captions_->setSticky(true);
        player_->beginFileCaptionHold();
        live_.start(QStringLiteral("tihulu-tv-center"),args);
        if(!live_.waitForStarted(900)) {player_->cancelFileCaptionHold();captions_->setSticky(false);message_->setText(tr("Caption service could not start."));return;}
        cancel_->setEnabled(true);
        message_->setText(tr("Caption panel opened · buffering synchronized file subtitles."));
    }
    void tickLive() {
        if(player_->getPlaybackStatus()!=MediaWidget::Playing)return;
        const qint64 now=player_->getPosition();
        if(now<lastMs_-800 || now>lastMs_+2000) {++revision_;nextMs_=now;captions_->clearCues();}
        lastMs_=now;
        if(pending_ || nextMs_>now+8000 || live_.state()!=QProcess::Running)return;
        nextMs_=qMax(nextMs_,now);pending_=true;
        live_.write(QJsonDocument(QJsonObject{{"position",double(nextMs_)/1000.},{"revision",revision_}}).toJson(QJsonDocument::Compact)+"\n");
    }
    void saveSrt() {
        if(!QFileInfo(srt_).isFile()) {message_->setText(tr("Transcribe a file first to save its SRT."));return;}
        const QString dest=QFileDialog::getSaveFileName(this,tr("Save subtitles"),QFileInfo(path_).completeBaseName()+".srt",tr("SubRip (*.srt)"));
        if(!dest.isEmpty())message_->setText(QFile::copy(srt_,dest)?tr("SRT saved: %1").arg(dest):tr("Cannot save SRT; choose a new writable filename."));
    }
    // Default delivery for video: a new .mkv copy carrying the SRT as a
    // selectable subtitle track. The original file is never modified.
    void embedSubtitledVideo() {
        if(path_.isEmpty() || !QFileInfo(srt_).isFile() || exportProcess_.state()!=QProcess::NotRunning)return;
        const QString dest=QFileInfo(path_).absolutePath()+QLatin1Char('/')+
            QFileInfo(path_).completeBaseName()+QStringLiteral("-subtitled.mkv");
        if(QFileInfo::exists(dest)) {message_->setText(tr("Embedded subtitles already exist: %1").arg(dest));return;}
        exportPath_=dest;
        exportProcess_.start(QStringLiteral("ffmpeg"),{QStringLiteral("-nostdin"),QStringLiteral("-hide_banner"),
            QStringLiteral("-loglevel"),QStringLiteral("error"),QStringLiteral("-n"),QStringLiteral("-i"),path_,QStringLiteral("-i"),srt_,
            QStringLiteral("-map"),QStringLiteral("0:v?"),QStringLiteral("-map"),QStringLiteral("0:a?"),QStringLiteral("-map"),QStringLiteral("1:0"),
            QStringLiteral("-c"),QStringLiteral("copy"),QStringLiteral("-c:s"),QStringLiteral("srt"),dest});
        if(exportProcess_.waitForStarted(800))message_->setText(tr("Embedding subtitles into %1 …").arg(dest));
    }
    void exportWithCaptions() {
        if(path_.isEmpty() || !QFileInfo(srt_).isFile() || exportProcess_.state()!=QProcess::NotRunning)return;
        QString dest=QFileDialog::getSaveFileName(this,tr("Export media and subtitles"),QFileInfo(path_).completeBaseName()+"-subtitled.mkv",tr("Matroska (*.mkv)"));
        if(dest.isEmpty())return;
        if(!dest.endsWith(".mkv",Qt::CaseInsensitive))dest+=".mkv";
        if(QFileInfo::exists(dest)) {message_->setText(tr("Choose a new filename; destination exists."));return;}
        exportPath_=dest;exportProcess_.start("ffmpeg",{"-nostdin","-hide_banner","-loglevel","error","-n","-i",path_,"-i",srt_,"-map","0:v?","-map","0:a?","-map","1:0","-c","copy","-c:s","srt",dest});
    }
    MediaWidget *player_;TihuluAiProcess process_,live_,exportProcess_;
    TihuluFileCaptions *captions_;TihuluCaptionOptions *choices_;
    QLabel *file_,*message_;QPushButton *run_,*liveButton_,*cancel_,*karaoke_=nullptr,*mpvButton_=nullptr;QProgressBar *progress_;
    QComboBox *serviceMode_=nullptr,*overlayMode_=nullptr;
    QCheckBox *holdForAnalysis_=nullptr;QSpinBox *liveWindow_=nullptr;
    QCheckBox *embedVideo_=nullptr,*externalPlayer_=nullptr;
    QProcess externalPlayerProcess_;
    QCheckBox *original_=nullptr,*music_=nullptr,*lyrics_=nullptr,*onlineLyrics_=nullptr,*preprocess_=nullptr,*wait_=nullptr;
    bool isVideo_=true,tvMode_=true,isAudioRequest_=false;
    QTimer liveClock_;QString path_,srt_,exportPath_;QByteArray result_;
    bool cancelled_=false,internalStop_=false,resuming_=false,resumeAfter_=false,pending_=false;
    bool openingCaptionWindow_=false;
    int revision_=0;qint64 nextMs_=0,lastMs_=0;
};
#endif
