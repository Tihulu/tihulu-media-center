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
        liveButton_=new QPushButton(tr("Live captions"),this);
        run_=new QPushButton(tr("Transcribe file"),this);
        auto *optionsButton=new QPushButton(tr("IN / OUT · Options"),this);
        cancel_=new QPushButton(tr("Stop AI"),this);cancel_->setEnabled(false);
        row->addWidget(liveButton_);row->addWidget(run_);row->addWidget(optionsButton);row->addWidget(cancel_);
        root->addLayout(row);
        message_=new QLabel(tr("Local AI · choose languages and an installed model in Options."),this);
        message_->setTextFormat(Qt::PlainText);message_->setWordWrap(true);root->addWidget(message_);
        progress_=new QProgressBar(this);progress_->hide();root->addWidget(progress_);
        captions_=new TihuluFileCaptions(player);
        options_=new QDialog(this);options_->setWindowTitle(tr("Local captions · IN / OUT"));
        auto *form=new QFormLayout(options_);
        choices_=new TihuluCaptionOptions(options_);form->addWidget(choices_);
        serviceMode_=new QComboBox(options_);
        serviceMode_->addItem(tr("Auto · video uses TV service, audio uses Radio service"),QStringLiteral("auto"));
        serviceMode_->addItem(tr("TV caption service (all settings)"),QStringLiteral("tv"));
        serviceMode_->addItem(tr("Radio caption service (all settings)"),QStringLiteral("radio"));
        serviceMode_->setToolTip(tr("File type decides the default. TV and Radio use their own saved languages, models and tools."));
        form->addRow(tr("Caption service"),serviceMode_);
        liveWindow_=new QSpinBox(options_);liveWindow_->setRange(2,20);liveWindow_->setSuffix(tr(" s"));
        liveWindow_->setValue(8);liveWindow_->setToolTip(tr("Live audio window used by the local speech model. Larger = more context, slower first caption."));
        form->addRow(tr("Live buffer"),liveWindow_);
        turnOff_=new QPushButton(tr("Turn off subtitles & exit"),options_);
        turnOff_->setToolTip(tr("Releases the local AI work now. Closing this window NEVER stops running captions."));
        form->addWidget(turnOff_);
        original_=new QCheckBox(tr("Show original text"),options_);original_->setChecked(true);
        music_=new QCheckBox(tr("Include singing / music vocals"),options_);
        lyrics_=new QCheckBox(tr("Use a matching local .lrc for whole-file captions"),options_);
        onlineLyrics_=new QCheckBox(tr("Find lyrics online by title / artist (optional)"),options_);
        onlineLyrics_->setToolTip(tr("Only when Transcribe file is pressed with local LRC mode enabled. Sends title/artist metadata to LRCLIB."));
        preprocess_=new QCheckBox(tr("Transcribe before opening a file"),options_);
        QSettings config("TIHULU","MediaPlayer");preprocess_->setChecked(config.value("transcribeBeforeOpen",false).toBool());
        wait_=new QCheckBox(tr("Wait for whole-file subtitles before playback"),options_);wait_->setChecked(true);
        form->addWidget(original_);form->addWidget(music_);form->addWidget(lyrics_);form->addWidget(onlineLyrics_);
        form->addWidget(preprocess_);form->addWidget(wait_);
        auto *save=new QPushButton(tr("Save SRT…"),options_);
        auto *exportMedia=new QPushButton(tr("Export media + subtitles (.mkv)…"),options_);
        form->addWidget(save);form->addWidget(exportMedia);
        auto *close=new QDialogButtonBox(QDialogButtonBox::Close,options_);form->addWidget(close);
        connect(close,&QDialogButtonBox::rejected,options_,&QDialog::hide);
        connect(optionsButton,&QPushButton::clicked,options_,&QDialog::show);
        connect(preprocess_,&QCheckBox::toggled,this,[](bool value){QSettings("TIHULU","MediaPlayer").setValue("transcribeBeforeOpen",value);});
        connect(serviceMode_,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](int){applyServiceMode();});
        connect(turnOff_,&QPushButton::clicked,this,[this](){
            options_->hide();stopAi();message_->setText(tr("Subtitles turned off · local AI released."));
        });
        connect(save,&QPushButton::clicked,this,[this](){saveSrt();});
        connect(exportMedia,&QPushButton::clicked,this,[this](){exportWithCaptions();});
        connect(run_,&QPushButton::clicked,this,[this](){generate(false);});
        connect(liveButton_,&QPushButton::clicked,this,[this](){startLive();});
        connect(cancel_,&QPushButton::clicked,this,[this](){stopAi();});
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
            captions_->loadSrt(srt_);
            if(resumeAfter_) {resuming_=true;player_->play(QUrl::fromLocalFile(path_));resuming_=false;}
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
            if(code && !cancelled_)message_->setText(tr("Live captions stopped: %1").arg(QString::fromUtf8(live_.readAllStandardError()).right(240)));
        });
        connect(&liveClock_,&QTimer::timeout,this,[this](){tickLive();});
        connect(&exportProcess_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),this,[this](int code,QProcess::ExitStatus status){
            message_->setText(code==0 && status==QProcess::NormalExit?tr("Subtitled MKV saved: %1").arg(exportPath_):tr("Export failed; source and SRT preserved."));
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
    // TV service for video files, Radio service for audio files; a manual choice wins.
    void applyServiceMode() {
        const QString mode=serviceMode_?serviceMode_->currentData().toString():QStringLiteral("auto");
        tvMode_=mode==QStringLiteral("tv") || (mode==QStringLiteral("auto") && isVideo_);
        const bool audio=!tvMode_;
        QSettings prefs("TIHULU",audio?"KaffeineRadio":"KaffeineTVFileCaptionDefaults");
        QStringList targets=prefs.value(audio?"radioOutputs":"outputLanguages",QStringList()).toStringList();
        if(!prefs.value(audio?"radioTranslationOptIn":"showTranslation",!audio).toBool())targets.clear();
        choices_->setLanguages(prefs.value(audio?"radioSpeechLanguage":"spokenSource","auto").toString(),targets);
        music_->setChecked(prefs.value(audio?"radioMusicTranscription":"musicTranscription",false).toBool());
        original_->setChecked(audio || prefs.value("showOriginal",true).toBool());
        lyrics_->setEnabled(audio);onlineLyrics_->setEnabled(audio && lyrics_->isChecked());
        if(!audio)lyrics_->setChecked(false);
        message_->setText(tvMode_?
            tr("TV caption service · video settings (languages, model, appearance, SRT export)"):
            tr("Radio caption service · audio settings (languages, karaoke/lyrics, offset, SRT export)"));
    }
    bool prepareLocalFileOpen(const QUrl &url) {
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
        if(!choices_->appendArguments(args)) {options_->show();return {};}
        if(music_->isChecked())args<<QStringLiteral("--music");
        if(!original_->isChecked())args<<QStringLiteral("--translations-only");
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
        srt_=cache+QStringLiteral("/tihulu-file-")+QString::number(QCoreApplication::applicationPid())+QLatin1Char('-')+QString::number(QDateTime::currentMSecsSinceEpoch())+QStringLiteral(".srt");
        args<<QStringLiteral("--output")<<srt_;
        if(lyrics_->isChecked() && !beforeOpen) {args<<QStringLiteral("--lyrics");if(onlineLyrics_->isChecked())args<<QStringLiteral("--fetch-lyrics");}
        resumeAfter_=beforeOpen || wait_->isChecked();cancelled_=false;result_.clear();
        if(resumeAfter_) {internalStop_=true;player_->stop();internalStop_=false;}
        process_.start(QStringLiteral("tihulu-tv-center"),args);
        if(!process_.waitForStarted(800)) {message_->setText(tr("Offline AI companion could not start."));return;}
        run_->setEnabled(false);liveButton_->setEnabled(false);cancel_->setEnabled(true);
        progress_->setRange(0,0);progress_->show();message_->setText(tr("Preparing local subtitles…"));
    }
    void startLive() {
        if(path_.isEmpty() || process_.state()!=QProcess::NotRunning)return;
        auto args=jobArguments(true);if(args.isEmpty())return;
        stopLive();cancelled_=false;++revision_;nextMs_=player_->getPosition();lastMs_=nextMs_;
        captions_->setSticky(true);
        live_.start(QStringLiteral("tihulu-tv-center"),args);
        if(!live_.waitForStarted(800)) {message_->setText(tr("Live caption worker could not start."));return;}
        cancel_->setEnabled(true);liveClock_.start(200);message_->setText(tr("Live captions · preparing installed local model…"));
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
    void exportWithCaptions() {
        if(path_.isEmpty() || !QFileInfo(srt_).isFile() || exportProcess_.state()!=QProcess::NotRunning)return;
        QString dest=QFileDialog::getSaveFileName(this,tr("Export media and subtitles"),QFileInfo(path_).completeBaseName()+"-subtitled.mkv",tr("Matroska (*.mkv)"));
        if(dest.isEmpty())return;
        if(!dest.endsWith(".mkv",Qt::CaseInsensitive))dest+=".mkv";
        if(QFileInfo::exists(dest)) {message_->setText(tr("Choose a new filename; destination exists."));return;}
        exportPath_=dest;exportProcess_.start("ffmpeg",{"-nostdin","-hide_banner","-loglevel","error","-n","-i",path_,"-i",srt_,"-map","0:v?","-map","0:a?","-map","1:0","-c","copy","-c:s","srt",dest});
    }
    MediaWidget *player_;TihuluAiProcess process_,live_,exportProcess_;
    TihuluFileCaptions *captions_;TihuluCaptionOptions *choices_;QDialog *options_;
    QLabel *file_,*message_;QPushButton *run_,*liveButton_,*cancel_;QProgressBar *progress_;
    QComboBox *serviceMode_=nullptr;QSpinBox *liveWindow_=nullptr;QPushButton *turnOff_=nullptr;
    QCheckBox *original_,*music_,*lyrics_,*onlineLyrics_,*preprocess_,*wait_;
    bool isVideo_=true,tvMode_=true;
    QTimer liveClock_;QString path_,srt_,exportPath_;QByteArray result_;
    bool cancelled_=false,internalStop_=false,resuming_=false,resumeAfter_=false,pending_=false;
    int revision_=0;qint64 nextMs_=0,lastMs_=0;
};
#endif
