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
        :QWidget(parent),player_(player),process_(this),live_(this),exportProcess_(this) {
        setObjectName(QStringLiteral("tihuluMediaPanel"));setAcceptDrops(true);
        auto *root=new QVBoxLayout(this);root->setContentsMargins(8,4,8,4);root->setSpacing(3);
        auto *row=new QHBoxLayout();
        file_=new QLabel(tr("Drop a video or audio file here"),this);
        file_->setTextFormat(Qt::PlainText);file_->setMinimumWidth(80);
        row->addWidget(file_,1);
        liveButton_=new QPushButton(tr("Live transcription / translation"),this);
        liveButton_->setObjectName(QStringLiteral("tihuluStartFileCaptions"));
        auto *optionsButton=new QPushButton(tr("Caption options"),this);
        saveLive_=new QPushButton(tr("Save live SRT…"),this);
        saveLive_->setEnabled(false);
        saveLive_->setObjectName(QStringLiteral("tihuluSaveLiveSrt"));
        run_=new QPushButton(tr("Transcribe file"),this);
        karaoke_=new QPushButton(tr("Karaoke / lyrics"),this);
        karaoke_->setToolTip(tr("Audio only: time-coded lyrics from a matching local .lrc beside the file, "
            "or optionally from LRCLIB by title/artist. No invented timings."));
        karaoke_->setEnabled(false);
        cancel_=new QPushButton(tr("Stop AI"),this);cancel_->setEnabled(false);
        mpvButton_=new QPushButton(tr("Open in mpv"),this);
        mpvButton_->setToolTip(tr("Hands the current media (local file or stream) to the mpv player "
            "with its subtitles. The built-in VLC engine stays default."));
        row->addWidget(liveButton_);row->addWidget(cancel_);
        row->addWidget(optionsButton);row->addWidget(saveLive_);
        root->addLayout(row);
        message_=new QLabel(tr("Local AI · choose languages and an installed model in Options."),this);
        message_->setTextFormat(Qt::PlainText);message_->setWordWrap(true);root->addWidget(message_);
        progress_=new QProgressBar(this);progress_->hide();root->addWidget(progress_);
        captions_=new TihuluFileCaptions(player);
        // Keep model and languages next to the live file controls.
        choices_=new TihuluCaptionOptions(this);
        options_=new QWidget(this);auto *optionLayout=new QVBoxLayout(options_);
        optionLayout->addWidget(choices_);root->addWidget(options_);options_->hide();
        connect(optionsButton,&QPushButton::clicked,this,[this](){options_->setVisible(options_->isHidden());});
        auto *timingOptions=new QHBoxLayout();
        reading_=new QComboBox(options_);reading_->setObjectName(QStringLiteral("tihuluFileReading"));
        reading_->addItem(tr("Live · fast"),QStringLiteral("fast"));
        reading_->addItem(tr("Comfort · readable phrases"),QStringLiteral("comfort"));
        reading_->addItem(tr("Relaxed · longer hold"),QStringLiteral("relaxed"));
        reading_->setToolTip(tr("Gives subtitles time to read in gaps without shifting the speech start. Applies on the next live session."));
        auto *readingLabel=new QLabel(tr("Reading:"),options_);readingLabel->setBuddy(reading_);
        timingOptions->addWidget(readingLabel);timingOptions->addWidget(reading_);
        speakers_=new QComboBox(options_);speakers_->setObjectName(QStringLiteral("tihuluFileSpeakers"));
        speakers_->addItem(tr("Speaker labels off"),QStringLiteral("off"));
        speakers_->addItem(tr("Resemblyzer · local"),QStringLiteral("resemblyzer"));
        speakers_->addItem(tr("pyannote · local"),QStringLiteral("pyannote"));
        speakers_->setToolTip(tr("Uses an already installed model and timed words. Labels are estimates per clip, not identities. Applies on the next live session."));
        timingOptions->addWidget(speakers_);
        timingOptions->addStretch(1);optionLayout->addLayout(timingOptions);
        auto *voiceOptions=new QHBoxLayout();
        original_=new QCheckBox(tr("Show original speech"),options_);
        music_=new QCheckBox(tr("Recognize singing"),options_);
        dialogue_=new QCheckBox(tr("Prefer dialogue over music"),options_);
        for(auto *option:{original_,music_,dialogue_})voiceOptions->addWidget(option);
        voiceOptions->addStretch(1);optionLayout->addLayout(voiceOptions);
        connect(music_,&QCheckBox::toggled,this,[this](bool enabled){if(enabled)dialogue_->setChecked(false);});
        connect(dialogue_,&QCheckBox::toggled,this,[this](bool enabled){if(enabled)music_->setChecked(false);});
        connect(reading_,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int){
            QSettings("TIHULU","FileCaptionReading").setValue(tvMode_?"video":"audio",reading_->currentData());
        });
        connect(speakers_,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int){
            QSettings("TIHULU","FileCaptionSpeakers").setValue(tvMode_?"video":"audio",speakers_->currentData());
        });
        audioOptions_=new QWidget(options_);auto *audioLayout=new QHBoxLayout(audioOptions_);
        auto *importLyrics=new QPushButton(tr("Open TXT / LRC…"),audioOptions_);
        saveLyrics_=new QPushButton(tr("Save lyrics SRT…"),audioOptions_);saveLyrics_->setEnabled(false);
        onlineLyrics_=new QCheckBox(tr("Allow online lyrics search"),audioOptions_);
        onlineLyrics_->setToolTip(tr("Off by default. Karaoke sends artist/title metadata to LRCLIB only if local lyrics are missing and this is checked."));
        auto *offset=new QSpinBox(audioOptions_);offset->setRange(-10000,10000);offset->setSingleStep(100);offset->setSuffix(tr(" ms"));
        offset->setToolTip(tr("Positive values show lyrics later. This changes playback display, not the exported SRT timestamps."));
        connect(offset,QOverload<int>::of(&QSpinBox::valueChanged),captions_,&TihuluFileCaptions::setLyricOffset);
        connect(importLyrics,&QPushButton::clicked,this,[this](){importLocalLyrics();});
        connect(saveLyrics_,&QPushButton::clicked,this,[this](){saveSrt();});
        audioLayout->addWidget(importLyrics);audioLayout->addWidget(saveLyrics_);
        audioLayout->addWidget(onlineLyrics_);audioLayout->addWidget(new QLabel(tr("Lyrics offset:"),audioOptions_));audioLayout->addWidget(offset);
        audioLayout->addStretch(1);optionLayout->addWidget(audioOptions_);audioOptions_->hide();
        connect(saveLive_,&QPushButton::clicked,this,[this](){saveLiveSrt();});
        serviceMode_=new QComboBox(this);
        serviceMode_->addItem(tr("Auto · file type"),QStringLiteral("auto"));
        serviceMode_->addItem(tr("TV language preset"),QStringLiteral("tv"));
        serviceMode_->addItem(tr("Radio language preset"),QStringLiteral("radio"));
        serviceMode_->setToolTip(tr("Local playback uses its own worker. This only selects the saved language preset."));
        liveWindow_=new QSpinBox(this);liveWindow_->setObjectName(QStringLiteral("tihuluFileBuffer"));liveWindow_->setRange(2,20);liveWindow_->setSuffix(tr(" s"));
        liveWindow_->setValue(8);liveWindow_->setToolTip(tr("Buffer analysis window. When AI captions start, "
            "playback pauses for this many seconds while the speech model analyses that "
            "much audio, then resumes from the same position with subtitles already "
            "synchronized. Larger = more context, slower first caption."));
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

        overlayMode_=new QComboBox(this);
        overlayMode_->addItem(tr("Below video · caption strip"),QStringLiteral("compact"));
        overlayMode_->addItem(tr("On video · transparent"),QStringLiteral("video"));
        overlayMode_->addItem(tr("Hide caption text"),QStringLiteral("off"));
        overlayMode_->addItem(tr("Show caption text (large)"),QStringLiteral("full"));
        QSettings overlayPrefs(QStringLiteral("TIHULU"),QStringLiteral("FileCaptionDisplay"));
        const QString overlayKey=overlayPrefs.value(QStringLiteral("mode"),QStringLiteral("compact")).toString();
        overlayMode_->setCurrentIndex(qMax(0,overlayMode_->findData(overlayKey)));
        overlayMode_->setToolTip(tr("Draw text on the video without a background, show it in a separate strip, or hide it. Saving live SRT works in every mode."));
        fileOptions->addWidget(new QLabel(tr("Subtitles:"),this));
        fileOptions->addWidget(overlayMode_);
        connect(overlayMode_,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int){
            QSettings saved(QStringLiteral("TIHULU"),QStringLiteral("FileCaptionDisplay"));
            saved.setValue(QStringLiteral("mode"),overlayMode_->currentData().toString());
            saved.sync();
        });
        fileOptions->addStretch(1);
        root->addLayout(fileOptions);
        auto *fileTools=new QHBoxLayout();
        for(auto *button:{run_,karaoke_,mpvButton_})fileTools->addWidget(button);
        fileTools->addStretch(1);root->addLayout(fileTools);
        auto *exportOptions=new QHBoxLayout();
        for(auto *option:{externalPlayer_,embedVideo_,preprocess_,wait_})exportOptions->addWidget(option);
        exportOptions->addStretch(1);root->addLayout(exportOptions);
        connect(preprocess_,&QCheckBox::toggled,this,[](bool value){QSettings("TIHULU","MediaPlayer").setValue("transcribeBeforeOpen",value);});
        connect(externalPlayer_,&QCheckBox::toggled,this,[](bool value){QSettings("TIHULU","MediaPlayer").setValue("externalPlayerMpv",value);});
        connect(serviceMode_,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int){stopLive(true,true);applyServiceMode();});
        connect(karaoke_,&QPushButton::clicked,this,[this](){generateKaraoke();});
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
            progress_->hide();cancel_->setEnabled(false);run_->setEnabled(!path_.isEmpty());liveButton_->setEnabled(!path_.isEmpty());
            karaoke_->setEnabled(!path_.isEmpty() && !isVideo_ && !tvMode_);
            if(cancelled_)return;
            result_+=process_.readAllStandardOutput();
            if(code || exit!=QProcess::NormalExit || !QFileInfo(srt_).isFile()) {
                message_->setText(tr("Offline captions unavailable: %1").arg(QString::fromUtf8(process_.readAllStandardError()).right(300)));
                return;
            }
            captions_->setKaraoke(isAudioRequest_);
            saveLyrics_->setEnabled(isAudioRequest_);
            captions_->loadSrt(srt_);
            if(resumeAfter_) {resuming_=true;player_->play(QUrl::fromLocalFile(path_));resuming_=false;}
            if(embedVideo_ && embedVideo_->isChecked() && isVideo_)embedSubtitledVideo();
            const auto result=QJsonDocument::fromJson(result_).object();
            const int warnings=result.value("translation_warning_count").toInt();
            const auto details=result.value("translation_warnings").toArray();
            message_->setText(warnings?tr("SRT saved; %1 translation warnings. %2").arg(warnings).arg(details.isEmpty()?QString():details.first().toObject().value("warning").toString()):tr("Captions ready · %1").arg(srt_));
        });
        connect(&live_,&QProcess::readyReadStandardOutput,this,[this](){readLive();});
        connect(&live_,&QProcess::started,this,[this](){tickLive();});
        connect(&live_,&QProcess::errorOccurred,this,[this](QProcess::ProcessError error){
            if(error==QProcess::FailedToStart && !stoppingLive_)
                liveError(tr("The local caption worker could not start."));
        });
        connect(&live_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),this,[this](int,QProcess::ExitStatus){
            if(!stoppingLive_)liveError(tr("The local caption worker exited: %1")
                .arg(QString::fromUtf8(live_.readAllStandardError()).trimmed().right(240)));
        });
        liveClock_.setInterval(75);
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
    ~TihuluMediaPanel() override {stoppingLive_=true;cancelled_=true;process_.stopJob();live_.stopJob();exportProcess_.stopJob();}
    void leavePlayback() {if(liveClock_.isActive())stopLive(true,true);}
    void setLocalFile(const QUrl &url) {
        const QString candidate=url.isLocalFile() && QFileInfo(url.toLocalFile()).isFile()?url.toLocalFile():QString();
        if(candidate==path_)return;
        stopAi(false);captions_->setSticky(false);captions_->clearCues();path_=candidate;srt_.clear();
        liveSrt_.clear();saveLive_->setEnabled(false);saveLyrics_->setEnabled(false);
        run_->setEnabled(!path_.isEmpty());liveButton_->setEnabled(!path_.isEmpty());
        if(path_.isEmpty()) {audioOptions_->hide();karaoke_->setEnabled(false);file_->setText(tr("Drop a video or audio file here"));return;}
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
        if(!choices_->appendLanguageArguments(args)) {options_->show();return;}
        stopLive(true,true);cancelled_=false;resumeAfter_=false;result_.clear();
        isAudioRequest_=true;saveLyrics_->setEnabled(false);
        const QString cache=QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
        if(cache.isEmpty() || !QDir().mkpath(cache)) {message_->setText(tr("Cannot create a private lyric cache."));return;}
        srt_=cache+QStringLiteral("/tihulu-lyrics-")+
            QString::number(QCoreApplication::applicationPid())+QLatin1Char('-')+
            QString::number(QDateTime::currentMSecsSinceEpoch())+QStringLiteral(".srt");
        args<<QStringLiteral("--output")<<srt_;
        if(!explicitLrc.isEmpty())args<<QStringLiteral("--lyrics-file")<<explicitLrc;
        else if(onlineLyrics_->isChecked())args<<QStringLiteral("--fetch-lyrics");
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
        const QSignalBlocker readingSignal(reading_),speakerSignal(speakers_);
        const QString videoDefault=prefs.value("readablePacing",true).toBool()?QStringLiteral("comfort"):QStringLiteral("fast");
        const int radioPreset=prefs.value("radioReadingPreset",1).toInt();
        const QString radioDefault=radioPreset==0?QStringLiteral("fast"):(radioPreset==2?QStringLiteral("relaxed"):QStringLiteral("comfort"));
        reading_->setCurrentIndex(qMax(0,reading_->findData(QSettings("TIHULU","FileCaptionReading")
            .value(tvMode_?"video":"audio",tvMode_?videoDefault:radioDefault))));
        speakers_->setCurrentIndex(qMax(0,speakers_->findData(QSettings("TIHULU","FileCaptionSpeakers")
            .value(tvMode_?"video":"audio",QStringLiteral("off")))));
        audioOptions_->setVisible(audio && !isVideo_ && !path_.isEmpty());
        karaoke_->setEnabled(audio && !isVideo_ && !path_.isEmpty());
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
    void releaseHold(bool resume) {
        const bool owned=holding_;
        holding_=false;pausedForAnalysis_=false;holdClock_.invalidate();
        if(resume && owned && player_->getPlaybackStatus()==MediaWidget::Paused)
            player_->togglePause();
    }
    void stopLive(bool clear=true,bool resume=false) {
        liveClock_.stop();++revision_;pending_=false;
        stoppingLive_=true;live_.stopJob();stoppingLive_=false;
        releaseHold(resume);
        if(nativeFileSubtitle_) {
            player_->tihuluShowFileSubtitle(false,QString());
            nativeFileSubtitle_=false;
        }
        captions_->setSticky(false);captions_->setOutputVisible(true);
        if(clear)captions_->clearCues();
        cancel_->setEnabled(process_.state()!=QProcess::NotRunning);
    }
    void stopAi(bool resume=true) {
        cancelled_=true;resumeAfter_=false;process_.stopJob();stopLive(liveClock_.isActive(),resume);
        progress_->hide();cancel_->setEnabled(false);run_->setEnabled(!path_.isEmpty());liveButton_->setEnabled(!path_.isEmpty());
        message_->setText(tr("AI stopped · local workers released."));
    }
    void liveError(const QString &reason) {
        stopLive(false,true);
        message_->setText(tr("Live subtitles: %1").arg(reason));
    }
    QStringList jobArguments(bool live) {
        QStringList args{QStringLiteral("media-captions"),QStringLiteral("--input"),path_};
        if(!choices_->appendArguments(args)) {
            options_->show();
            message_->setText(tr("Check the local model and language options before starting captions."));
            return {};
        }
        if(music_ && music_->isChecked())args<<QStringLiteral("--music");
        if(original_ && !original_->isChecked())args<<QStringLiteral("--translations-only");
        args<<QStringLiteral("--service")<<(tvMode_?QStringLiteral("tv"):QStringLiteral("radio"));
        if(liveWindow_)args<<QStringLiteral("--window")<<QString::number(liveWindow_->value());
        if(live)args<<QStringLiteral("--live");
        if(live) {
            args<<QStringLiteral("--reading")<<reading_->currentData().toString()
                <<QStringLiteral("--speaker-provider")<<speakers_->currentData().toString();
            if(dialogue_->isChecked())args<<QStringLiteral("--speech-priority");
        }
        return args;
    }
    void generate(bool beforeOpen) {
        if(path_.isEmpty() || process_.state()!=QProcess::NotRunning)return;
        auto args=jobArguments(false);if(args.isEmpty())return;
        stopLive(true,true);captions_->clearCues();
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
        if(liveClock_.isActive()) {show();message_->setFocus();return;}
        if(player_->getPlaybackStatus()==MediaWidget::Idle || player_->tihuluLocalMediaPath()!=path_) {
            message_->setText(tr("Play this file in the built-in player first."));return;
        }
        const auto args=jobArguments(true);
        if(args.isEmpty())return;
        stopLive();captions_->setKaraoke(false);cancelled_=false;atEnd_=false;
        windowMs_=liveWindow_->value()*1000;
        nextMs_=lastMs_=qMax(0,player_->getPosition());
        lastLiveWarning_.clear();
        coveredMs_=-1;clock_.restart();
        if(player_->getPlaybackStatus()==MediaWidget::Playing)beginHold();
        // This worker reads requests on stdin and decodes the file directly.
        // It can produce cues while the player clock is frozen and never uses DVB.
        cancel_->setEnabled(true);
        liveClock_.start();
        live_.start(QStringLiteral("tihulu-tv-center"),args);
    }
    void beginHold() {
        holding_=true;pausedForAnalysis_=false;holdClock_.restart();
        player_->togglePause();
        message_->setText(tr("Playback paused for subtitle analysis (%1 s)…").arg(windowMs_/1000));
    }
    void readLive() {
        while(live_.canReadLine()) {
            const auto reply=QJsonDocument::fromJson(live_.readLine()).object();
            if(stoppingLive_ || reply.isEmpty())continue;
            if(!pending_ || reply.value("revision").toInt(-1)!=requestRevision_)continue;
            pending_=false;
            if(requestRevision_!=revision_)continue;
            if(reply.contains("error")) {liveError(reply.value("error").toString());return;}
            atEnd_=reply.value("eof").toBool();
            coveredMs_=reply.value("end").toDouble(-1);
            if(coveredMs_ < nextMs_ || (coveredMs_==nextMs_ && !atEnd_)) {
                liveError(tr("The caption worker returned an invalid audio interval."));return;
            }
            nextMs_=coveredMs_;
            const auto rows=reply.value("cues").toArray();
            captions_->append(rows);
            for(const auto &row:rows) {
                auto cue=row.toObject();
                const qint64 start=cue.value("start").toDouble(-1);
                if(start>=0 && cue.value("end").toDouble()>start && !cue.value("text").toString().isEmpty())
                    liveSrt_.insert(start,cue);
            }
            saveLive_->setEnabled(!liveSrt_.isEmpty());
            lastLiveWarning_=reply.value("warning").toString();
            if(!holding_)showLiveStatus();
        }
    }
    void showLiveStatus() {
        message_->setText(lastLiveWarning_.isEmpty() ?
            tr("Live file subtitles · synchronized to playback · Save live SRT for a reusable track") : lastLiveWarning_);
    }
    void tickLive() {
        const auto state=player_->getPlaybackStatus();
        if(state==MediaWidget::Idle) {stopLive();return;}
        if(holding_ && !pausedForAnalysis_) {
            if(state!=MediaWidget::Paused) {
                if(holdClock_.elapsed()>2500)liveError(tr("The player could not pause for analysis."));
                return;
            }
            // Start the buffer at the position the backend actually paused at.
            pausedForAnalysis_=true;holdClock_.restart();
            if(coveredMs_<0)nextMs_=lastMs_=qMax(0,player_->getPosition());
        }
        const qint64 now=qMax(0,player_->getPosition());
        const qint64 elapsed=clock_.restart();
        if(now<lastMs_-350 || now>lastMs_+elapsed+700) {
            ++revision_;nextMs_=now;coveredMs_=-1;atEnd_=false;
            captions_->clearCues();
            if(holding_)holdClock_.restart();
        }
        lastMs_=now;
        const bool covered=atEnd_ || coveredMs_>now;
        if(holding_) {
            if(state==MediaWidget::Playing)releaseHold(false); // explicit user Play
            else if(holdClock_.elapsed()>=windowMs_ && covered) {
                releaseHold(true);showLiveStatus();
            } else if(holdClock_.elapsed()>=windowMs_+30000) {
                liveError(tr("Analysis did not finish in time; playback resumed without new subtitles."));return;
            }
        } else if(!covered && state==MediaWidget::Playing && !atEnd_) {
            beginHold();return;
        }
        const QString display=overlayMode_->currentData().toString();
        const bool onVideo=isVideo_ && display==QStringLiteral("video");
        captions_->setOutputVisible(!onVideo && display!=QStringLiteral("off"));
        if(onVideo || nativeFileSubtitle_)
            player_->tihuluShowFileSubtitle(onVideo,onVideo?captions_->activeText(now):QString());
        nativeFileSubtitle_=onVideo;
        if(pending_ || atEnd_ || nextMs_>=now+windowMs_ || live_.state()!=QProcess::Running)return;
        const QByteArray request=QJsonDocument(QJsonObject{{"position",double(nextMs_)/1000.},
            {"revision",revision_}}).toJson(QJsonDocument::Compact)+"\n";
        requestRevision_=revision_;pending_=true;
        if(live_.write(request)!=request.size())liveError(tr("Could not send an audio request to the caption worker."));
    }
    static QString srtTime(qint64 ms) {
        return QStringLiteral("%1:%2:%3,%4").arg(ms/3600000,2,10,QLatin1Char('0'))
            .arg(ms/60000%60,2,10,QLatin1Char('0')).arg(ms/1000%60,2,10,QLatin1Char('0'))
            .arg(ms%1000,3,10,QLatin1Char('0'));
    }
public:
    QByteArray liveSrt() const {
        QByteArray data;int number=0;
        for(auto cue=liveSrt_.cbegin();cue!=liveSrt_.cend();++cue) {
            QString text=cue.value().value("text").toString().trimmed();
            text.replace(QRegularExpression(QStringLiteral("[\\r\\n][\\r\\n]+")),QStringLiteral("\n"));
            data+=QStringLiteral("%1\n%2 --> %3\n%4\n\n").arg(++number).arg(srtTime(cue.key()),
                srtTime(cue.value().value("end").toDouble()),text).toUtf8();
        }
        return data;
    }
private:
    void saveLiveSrt() {
        const auto data=liveSrt();if(data.isEmpty())return;
        const auto dest=QFileDialog::getSaveFileName(this,tr("Save live subtitle track"),
            QFileInfo(path_).completeBaseName()+QStringLiteral(".live.srt"),tr("SubRip (*.srt)"));
        if(dest.isEmpty())return;
        QSaveFile file(dest);
        if(file.open(QIODevice::WriteOnly) && file.write(data)==data.size() && file.commit())
            message_->setText(tr("SRT saved: %1").arg(dest));
        else message_->setText(tr("Could not save live subtitles: %1").arg(file.errorString()));
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
    QSpinBox *liveWindow_=nullptr;
    QCheckBox *embedVideo_=nullptr,*externalPlayer_=nullptr;
    QProcess externalPlayerProcess_;
    QWidget *options_=nullptr,*audioOptions_=nullptr;
    QComboBox *reading_=nullptr,*speakers_=nullptr;
    QPushButton *saveLyrics_=nullptr;
    QCheckBox *original_=nullptr,*music_=nullptr,*dialogue_=nullptr,*onlineLyrics_=nullptr,*preprocess_=nullptr,*wait_=nullptr;
    bool isVideo_=true,tvMode_=true,isAudioRequest_=false;
    QTimer liveClock_;QString path_,srt_,exportPath_;QByteArray result_;
    bool cancelled_=false,internalStop_=false,resuming_=false,resumeAfter_=false,pending_=false;
    QPushButton *saveLive_=nullptr;
    QMap<qint64,QJsonObject> liveSrt_;
    QElapsedTimer holdClock_,clock_;
    QString lastLiveWarning_;
    bool holding_=false,pausedForAnalysis_=false,stoppingLive_=false,atEnd_=false,nativeFileSubtitle_=false;
    int revision_=0,requestRevision_=0,windowMs_=8000;
    qint64 nextMs_=0,lastMs_=0,coveredMs_=-1;
};
#endif
