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
#include <QElapsedTimer>
#include <QSaveFile>
#include <QMap>
#include <QHBoxLayout>
#include <QJsonDocument>
#include <QProcess>
#include <QLocalSocket>
#include <QLabel>
#include <QMimeData>
#include <QMimeDatabase>
#include <QProgressBar>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSettings>
#include <QSignalBlocker>
#include <QStandardPaths>
#include <QTimer>
#include <QVBoxLayout>

class TihuluMediaPanel final : public QWidget {
public:
    explicit TihuluMediaPanel(MediaWidget *player,QWidget *parent=nullptr)
        :QWidget(parent),player_(player),process_(this),exportProcess_(this) {
        setObjectName(QStringLiteral("tihuluMediaPanel"));setAcceptDrops(true);
        auto *root=new QVBoxLayout(this);root->setContentsMargins(8,4,8,4);root->setSpacing(3);
        auto *row=new QHBoxLayout();
        file_=new QLabel(tr("Drop a video or audio file here"),this);
        file_->setTextFormat(Qt::PlainText);file_->setMinimumWidth(80);
        row->addWidget(file_,1);
        liveButton_=new QPushButton(tr("Live captions…"),this);
        liveButton_->setObjectName(QStringLiteral("tihuluStartFileCaptions"));
        liveButton_->setToolTip(tr("Opens the full caption window for this file: appearance, source "
            "sync, reading modes, voice separation, SRT recording and diagnostics."));
        cancel_=new QPushButton(tr("Stop AI"),this);cancel_->setEnabled(false);
        cancel_->setToolTip(tr("Stops caption recognition and every local AI worker."));
        row->addWidget(liveButton_);row->addWidget(cancel_);
        root->addLayout(row);

        auto *fileTools=new QHBoxLayout();
        run_=new QPushButton(tr("Transcribe file"),this);
        karaoke_=new QPushButton(tr("Karaoke / lyrics"),this);
        karaoke_->setToolTip(tr("Audio only: real time-coded lyrics from a matching local .lrc beside "
            "the file, or from a file you choose. Nothing is invented."));
        karaoke_->setEnabled(false);
        importLyrics_=new QPushButton(tr("Open lyrics TXT / LRC…"),this);importLyrics_->setEnabled(false);
        mpvButton_=new QPushButton(tr("Open in mpv"),this);
        mpvButton_->setToolTip(tr("Hands the current media (local file or stream) to the mpv player "
            "with its subtitles. The built-in VLC engine stays default."));
        for(auto *button:{run_,karaoke_,importLyrics_,mpvButton_})fileTools->addWidget(button);
        lyricsOffset_=new QSpinBox(this);lyricsOffset_->setRange(-10000,10000);
        lyricsOffset_->setSingleStep(100);lyricsOffset_->setSuffix(tr(" ms"));
        lyricsOffset_->setToolTip(tr("Positive values show lyrics later. This changes only the "
            "on-screen karaoke display, never the exported SRT timestamps."));
        connect(lyricsOffset_,QOverload<int>::of(&QSpinBox::valueChanged),
                this,[this](int ms){captions_->setLyricOffset(ms);});
        fileTools->addWidget(new QLabel(tr("Lyrics offset:"),this));
        fileTools->addWidget(lyricsOffset_);
        fileTools->addStretch(1);root->addLayout(fileTools);

        serviceMode_=new QComboBox(this);
        serviceMode_->addItem(tr("Auto · file type"),QStringLiteral("auto"));
        serviceMode_->addItem(tr("TV language preset"),QStringLiteral("tv"));
        serviceMode_->addItem(tr("Radio language preset"),QStringLiteral("radio"));
        serviceMode_->setToolTip(tr("Only chooses which saved language preset the caption window starts "
            "from. All caption settings live in the caption window."));
        liveWindow_=new QSpinBox(this);liveWindow_->setObjectName(QStringLiteral("tihuluFileBuffer"));
        liveWindow_->setRange(2,20);liveWindow_->setSuffix(tr(" s"));liveWindow_->setValue(8);
        liveWindow_->setToolTip(tr("Buffer analysis window. Playback pauses for this many seconds while "
            "the speech model analyses that much audio, then resumes from the same position with "
            "subtitles already synchronized. Larger = more context, slower first caption."));
        externalPlayer_=new QCheckBox(tr("Play local files with mpv"),this);
        QSettings playerPrefs(QStringLiteral("TIHULU"),QStringLiteral("MediaPlayer"));
        externalPlayer_->setChecked(playerPrefs.value(QStringLiteral("externalPlayerMpv"),false).toBool() &&
                                   !QStandardPaths::findExecutable(QStringLiteral("mpv")).isEmpty());
        externalPlayer_->setToolTip(tr("Optional: local video/audio opens in mpv together with its "
            "subtitles. TV, radio and streams keep the built-in VLC engine."));
        embedVideo_=new QCheckBox(tr("Video: embed the SRT (.mkv copy)"),this);
        embedVideo_->setChecked(true);embedVideo_->setToolTip(tr("Default for video files. The generated "
            ".mkv keeps your original file untouched and carries the SRT as a selectable track."));
        preprocess_=new QCheckBox(tr("Transcribe before opening a file"),this);
        QSettings config("TIHULU","MediaPlayer");preprocess_->setChecked(config.value("transcribeBeforeOpen",false).toBool());
        wait_=new QCheckBox(tr("Wait for subtitles before playback"),this);wait_->setChecked(true);
        auto *fileOptions=new QHBoxLayout();
        fileOptions->addWidget(new QLabel(tr("Service:"),this));fileOptions->addWidget(serviceMode_);
        fileOptions->addWidget(new QLabel(tr("Buffer:"),this));fileOptions->addWidget(liveWindow_);
        fileOptions->addStretch(1);
        for(auto *option:{externalPlayer_,embedVideo_,preprocess_,wait_})fileOptions->addWidget(option);
        root->addLayout(fileOptions);

        message_=new QLabel(tr("Local AI · choose languages and an installed model in the caption window."),this);
        message_->setTextFormat(Qt::PlainText);message_->setWordWrap(true);root->addWidget(message_);
        progress_=new QProgressBar(this);progress_->hide();root->addWidget(progress_);
        captions_=new TihuluFileCaptions(player);
        choices_=new TihuluCaptionOptions(this);choices_->hide();   // catalog for one-shot jobs

        connect(preprocess_,&QCheckBox::toggled,this,[](bool value){QSettings("TIHULU","MediaPlayer").setValue("transcribeBeforeOpen",value);});
        connect(externalPlayer_,&QCheckBox::toggled,this,[](bool value){QSettings("TIHULU","MediaPlayer").setValue("externalPlayerMpv",value);});
        connect(serviceMode_,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int){applyServiceMode();});
        connect(karaoke_,&QPushButton::clicked,this,[this](){generateKaraoke();});
        connect(importLyrics_,&QPushButton::clicked,this,[this](){importLocalLyrics();});
        connect(run_,&QPushButton::clicked,this,[this](){generate(false);});
        connect(mpvButton_,&QPushButton::clicked,this,[this](){openInMpv();});
        connect(liveButton_,&QPushButton::clicked,this,[this](){startLive();});
        connect(player_,&MediaWidget::tihuluFileCaptionsRequested,this,[this](){startLive();});
        connect(cancel_,&QPushButton::clicked,this,[this](){stopAi();});
        connect(player_,&MediaWidget::stopRequested,this,[this](){if(!internalStop_)stopAi(false);});
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
            progress_->hide();cancel_->setEnabled(false);run_->setEnabled(!path_.isEmpty());
            liveButton_->setEnabled(!path_.isEmpty());
            karaoke_->setEnabled(!path_.isEmpty() && !isVideo_ && !tvMode_);
            importLyrics_->setEnabled(!path_.isEmpty() && !isVideo_ && !tvMode_);
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
    ~TihuluMediaPanel() override {cancelled_=true;process_.stopJob();exportProcess_.stopJob();stopCaptionWindow();}
    void leavePlayback() {stopCaptionWindow();captions_->setSticky(false);captions_->clearCues();}
    void setLocalFile(const QUrl &url) {
        const QString candidate=url.isLocalFile() && QFileInfo(url.toLocalFile()).isFile()?url.toLocalFile():QString();
        if(candidate==path_)return;
        stopAi(false);captions_->setSticky(false);captions_->clearCues();path_=candidate;srt_.clear();
        const bool ready=!path_.isEmpty();
        run_->setEnabled(ready);liveButton_->setEnabled(ready);
        karaoke_->setEnabled(ready && !isVideo_ && !tvMode_);
        importLyrics_->setEnabled(ready && !isVideo_ && !tvMode_);
        if(!ready) {file_->setText(tr("Drop a video or audio file here"));return;}
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
    void importLocalLyrics() {
        const auto chosen=QFileDialog::getOpenFileName(this,tr("Open local lyrics"),QFileInfo(path_).absolutePath(),tr("Lyrics (*.lrc *.txt)"));
        if(chosen.isEmpty())return;
        if(chosen.endsWith(QStringLiteral(".lrc"),Qt::CaseInsensitive)) {generateKaraoke(chosen);return;}
        QFile file(chosen);
        if(!file.open(QIODevice::ReadOnly) || file.size()>2000000) {message_->setText(tr("Cannot read lyric text."));return;}
        QDialog dialog(this);dialog.setWindowTitle(tr("Lyrics preview · no timings"));
        auto *layout=new QVBoxLayout(&dialog);
        auto *text=new QPlainTextEdit(QString::fromUtf8(file.readAll()),&dialog);text->setReadOnly(true);layout->addWidget(text);
        dialog.resize(540,420);dialog.exec();
    }
    void generateKaraoke(const QString &explicitLrc=QString()) {
        if(path_.isEmpty() || process_.state()!=QProcess::NotRunning || tvMode_ || isVideo_)return;
        QStringList args{QStringLiteral("media-captions"),QStringLiteral("--input"),path_,QStringLiteral("--lyrics")};
        if(!choices_->appendArguments(args)) {
            message_->setText(tr("Check the local model and language options first."));return;
        }
        cancelled_=false;resumeAfter_=false;result_.clear();
        isAudioRequest_=true;
        const QString cache=QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
        if(cache.isEmpty() || !QDir().mkpath(cache)) {message_->setText(tr("Cannot create a private lyric cache."));return;}
        srt_=cache+QStringLiteral("/tihulu-lyrics-")+
            QString::number(QCoreApplication::applicationPid())+QLatin1Char('-')+
            QString::number(QDateTime::currentMSecsSinceEpoch())+QStringLiteral(".srt");
        args<<QStringLiteral("--output")<<srt_;
        if(!explicitLrc.isEmpty())args<<QStringLiteral("--lyrics-file")<<explicitLrc;
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
        karaoke_->setEnabled(!path_.isEmpty() && audio && !isVideo_);
        importLyrics_->setEnabled(!path_.isEmpty() && audio && !isVideo_);
        message_->setText(audio?
            tr("Radio language preset · audio settings, karaoke/lyrics and SRT export live in the caption window."):
            tr("TV language preset · video settings live in the caption window."));
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
    // Local playback has ONE caption tool: the full caption window. It owns
    // languages, appearance, reading, voice separation, SRT recording and
    // diagnostics, exactly like live TV. This panel only opens or focuses it,
    // supplies the buffer window, and stops it when playback ends.
    QString fileCaptionSocket() const {
        const QString runtime=QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
        if(runtime.isEmpty())return QString();
        return runtime+QStringLiteral("/tihulu-file-")+
            QString::number(QCoreApplication::applicationPid())+QStringLiteral(".sock");
    }
    bool fileCaptionRunning() const {
        const QString sock=fileCaptionSocket();
        if(sock.isEmpty())return false;
        const QString runtime=QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
        return QFileInfo::exists(runtime+QStringLiteral("/tihulu-captions-control-")+
            QString::number(QCoreApplication::applicationPid())+QStringLiteral("-file.sock"));
    }
    void stopCaptionWindow() {
        const QString runtime=QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
        if(runtime.isEmpty())return;
        const QString ctl=runtime+QLatin1String("/tihulu-captions-control-")+
            QString::number(QCoreApplication::applicationPid())+QLatin1String("-file.sock");
        if(!QFileInfo::exists(ctl))return;
        QLocalSocket stop;stop.connectToServer(ctl);
        if(stop.waitForConnected(300)) {
            stop.write("STOP");stop.flush();stop.waitForBytesWritten(300);
            stop.disconnectFromServer();
        }
    }
    void stopAi(bool releasePlayback=true) {
        cancelled_=true;resumeAfter_=false;process_.stopJob();
        stopCaptionWindow();
        captions_->setSticky(false);captions_->clearCues();
        progress_->hide();cancel_->setEnabled(false);
        run_->setEnabled(!path_.isEmpty());liveButton_->setEnabled(!path_.isEmpty());
        karaoke_->setEnabled(!path_.isEmpty() && !isVideo_ && !tvMode_);
        importLyrics_->setEnabled(!path_.isEmpty() && !isVideo_ && !tvMode_);
        message_->setText(tr("AI stopped · local workers released."));
    }
    QStringList jobArguments() {
        QStringList args{QStringLiteral("media-captions"),QStringLiteral("--input"),path_};
        if(!choices_->appendArguments(args)) {
            message_->setText(tr("Check the local model and language options first."));return {};
        }
        args<<QStringLiteral("--service")<<(tvMode_?QStringLiteral("tv"):QStringLiteral("radio"));
        if(liveWindow_)args<<QStringLiteral("--window")<<QString::number(liveWindow_->value());
        return args;
    }
    void generate(bool beforeOpen) {
        if(path_.isEmpty() || process_.state()!=QProcess::NotRunning)return;
        auto args=jobArguments();if(args.isEmpty())return;
        const QString cache=QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
        if(cache.isEmpty() || !QDir().mkpath(cache)) {message_->setText(tr("Cannot create subtitle cache."));return;}
        isAudioRequest_=!tvMode_;
        srt_=cache+QStringLiteral("/tihulu-file-")+QString::number(QCoreApplication::applicationPid())+QLatin1Char('-')+QString::number(QDateTime::currentMSecsSinceEpoch())+QStringLiteral(".srt");
        args<<QStringLiteral("--output")<<srt_;
        resumeAfter_=beforeOpen || wait_->isChecked();cancelled_=false;result_.clear();
        if(resumeAfter_) {internalStop_=true;player_->stop();internalStop_=false;}
        process_.start(QStringLiteral("tihulu-tv-center"),args);
        if(!process_.waitForStarted(800)) {message_->setText(tr("Offline AI companion could not start."));return;}
        run_->setEnabled(false);liveButton_->setEnabled(false);cancel_->setEnabled(true);
        progress_->setRange(0,0);progress_->show();message_->setText(tr("Preparing local subtitles…"));
    }
    void startLive() {
        if(path_.isEmpty() || process_.state()!=QProcess::NotRunning)return;
        if(player_->getPlaybackStatus()==MediaWidget::Idle || player_->tihuluLocalMediaPath()!=path_) {
            message_->setText(tr("Play this file in the built-in player first."));return;
        }
        const QString socket=fileCaptionSocket();
        if(socket.isEmpty()) {
            message_->setText(tr("XDG_RUNTIME_DIR is missing; cannot start the caption service."));return;
        }
        // Focus the running controller instead of starting a second one.
        if(fileCaptionRunning()) {
            QProcess::startDetached(QLatin1String("tihulu-tv-center"),
                QStringList{QStringLiteral("kaffeine-captions-file"),QStringLiteral("--socket"),socket,
                            QStringLiteral("--show-only")});
            cancel_->setEnabled(true);
            message_->setText(tr("Caption window is already open · playback pauses for its buffer."));
            return;
        }
        const QString window=QString::number(liveWindow_?liveWindow_->value():8);
        const QStringList args{QStringLiteral("kaffeine-captions-file"),
            QStringLiteral("--socket"),socket,QStringLiteral("--file"),path_,
            QStringLiteral("--window"),window};
        cancelled_=false;
        // Detached, exactly like the TV menu and the Whisper button: a child
        // QProcess owned by this widget closed the controller's own GUI.
        if(QProcess::startDetached(QLatin1String("tihulu-tv-center"),args)) {
            cancel_->setEnabled(true);
            message_->setText(tr("Opening the caption window for this file…"));
        } else {
            message_->setText(tr("Could not open the caption window."));
        }
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
    MediaWidget *player_;TihuluAiProcess process_,exportProcess_;
    TihuluFileCaptions *captions_;TihuluCaptionOptions *choices_;
    QLabel *file_,*message_;QPushButton *run_,*liveButton_,*cancel_,
        *karaoke_=nullptr,*importLyrics_=nullptr,*mpvButton_=nullptr;
    QProgressBar *progress_;
    QComboBox *serviceMode_=nullptr;QSpinBox *liveWindow_=nullptr,*lyricsOffset_=nullptr;
    QCheckBox *embedVideo_=nullptr,*externalPlayer_=nullptr,*preprocess_=nullptr,*wait_=nullptr;
    QProcess externalPlayerProcess_;
    QString path_,srt_,exportPath_;QByteArray result_;
    bool isVideo_=true,tvMode_=true,isAudioRequest_=false;
    bool cancelled_=false,internalStop_=false,resuming_=false,resumeAfter_=false;
};
#endif
