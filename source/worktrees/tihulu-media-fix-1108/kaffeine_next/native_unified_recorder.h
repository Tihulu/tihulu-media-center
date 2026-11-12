/*
 * TIHULU shared player recorder. LGPL-compatible FFmpeg external process,
 * native Kaffeine TV instant recording, optional offline Whisper sidecars.
 * Neither decoded VLC overlays nor DRM/DVD content are falsely claimed as
 * being captured. Original media remains untouched.
 */
#ifndef TIHULU_UNIFIED_RECORDER_H
#define TIHULU_UNIFIED_RECORDER_H

#include "mediawidget.h"
#include "dvb/dvbtab.h"
#include "dvb/dvbmanager.h"
#include "dvb/dvbliveview.h"
#include "dvb/dvbrecording.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDateTime>
#include <QDesktopServices>
#include <QDialog>
#include <QDir>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QMainWindow>
#include <QStatusBar>
#include <QListWidgetItem>
#include <QProcess>
#include <QPushButton>
#include <QSettings>
#include <QStandardPaths>
#include <QTimer>
#include <QToolBar>
#include <QToolButton>
#include <QUrl>
#include <QVBoxLayout>
#include <QListWidget>
#include <QMenu>
#include <QFile>
#include <functional>

class TihuluUnifiedRecorder final : public QWidget {
public:
    explicit TihuluUnifiedRecorder(MediaWidget *player,DvbTab *dvb,
                                   QToolBar *bar,std::function<void()> openPlayback,
                                   QWidget *parent=nullptr)
        : QWidget(parent),player_(player),dvb_(dvb),
          openPlayback_(openPlayback),
          capture_(this),ai_(this),mux_(this) {
        auto *line=new QHBoxLayout(this);
        line->setContentsMargins(1,0,1,0);
        line->setSpacing(4);
        record_=new QToolButton(this);
        record_->setText(tr("● REC"));
        record_->setToolTip(tr("Record current playable source; Stop finishes recording. "
            "Choose whether to generate optional offline subtitles afterward."));
        record_->setStyleSheet(QLatin1String(
            "QToolButton{background:#68262a;color:#fff;border:1px solid #d65c5c;"
            "border-radius:4px;padding:4px 7px;font-weight:bold;}"
            "QToolButton:hover{background:#a13636;}"));
        library_=new QToolButton(this);
        library_->setText(tr("Recordings"));
        library_->setToolTip(tr("Open previously recorded media, import native DVB "
            "recordings and generate optional captions."));
        record_->setMinimumWidth(78);
        library_->setMaximumWidth(100);
        line->addWidget(record_);
        line->addWidget(library_);
        bar->addWidget(this);
        elapsed_.setInterval(1000);
        connect(&elapsed_,&QTimer::timeout,this,[this](){
            if(!recording_)return;
            if(!finalizing_ && captureKind_==QLatin1String("ffmpeg") &&
               recordingUrl_.isValid() &&
               player_->property("tihulu_recordable_url").toUrl()!=recordingUrl_) {
                report(tr("Player changed source; finalizing the previous recording."));
                stopRecording();
                return;
            }
            const qint64 seconds=qMax(qint64(0),
                (QDateTime::currentMSecsSinceEpoch()-startedMs_)/1000);
            const qint64 bytes=QFileInfo(recordedPath_).size();
            record_->setToolTip(captureKind_==QLatin1String("dvb")?
                tr("Native DVB recording elapsed %1:%2 · Kaffeine owns saved file.")
                  .arg(seconds/60).arg(seconds%60,2,10,QLatin1Char('0')):
                tr("REC elapsed %1:%2 · saved %3 MiB. "
                "Live recording has no known completion percentage.")
                  .arg(seconds/60).arg(seconds%60,2,10,QLatin1Char('0'))
                  .arg(QString::number(qMax(qint64(0),bytes)/1048576.,'f',1)));
        });
        connect(record_,&QToolButton::clicked,this,[this](){
            if(recording_)stopRecording(); else startRecording();
        });
        connect(library_,&QToolButton::clicked,this,[this](){openLibrary();});
        connect(&capture_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
            this,[this](int exitCode,QProcess::ExitStatus){
                const bool wanted=recording_;
                recording_=false;
                finalizing_=false;
                elapsed_.stop();
                record_->setEnabled(true);
                refreshButton();
                if(captureKind_!=QLatin1String("ffmpeg"))return;
                if(exitCode!=0 && !intentionalStop_) {
                    report(tr("FFmpeg exited (%1): %2").arg(exitCode)
                         .arg(QString::fromUtf8(capture_.readAllStandardError()).right(200)));
                }
                const QFileInfo saved(recordedPath_);
                if(!saved.isFile() || saved.size()<8192) {
                    report(tr("No usable recording file was produced. "
                        "Check the stream and FFmpeg logs."));
                    return;
                }
                addToLibrary(saved.absoluteFilePath());
                report(tr("Recorded %1 · %2 bytes. Open from Recordings.")
                    .arg(saved.fileName()).arg(saved.size()));
                if(subtitlesAfter_ && wanted) {
                    // Unexpected stream failure must not manufacture a complete AI export.
                    if(exitCode==0 || intentionalStop_)generateCaptions(saved.absoluteFilePath(),
                                                     targets_,singing_);
                }
            });
        connect(&ai_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
            this,[this](int code,QProcess::ExitStatus){
                const QFileInfo input(aiPath_);
                const QString srt=input.absolutePath()+QLatin1Char('/')+
                    input.completeBaseName()+QLatin1String(".srt");
                if(code!=0 || !QFileInfo(srt).isFile()){
                    report(tr("Recording preserved. AI subtitles unavailable: %1")
                        .arg(QString::fromUtf8(ai_.readAllStandardError()).right(220)));
                    return;
                }
                report(tr("Subtitle SRT saved; embedding selectable track in MKV…"));
                const QString subtitled=input.absolutePath()+QLatin1Char('/')+
                    input.completeBaseName()+QLatin1String("-subtitled.mkv");
                if(QFileInfo::exists(subtitled)){
                    report(tr("SRT exists but MKV destination already exists; "
                        "not overwriting your recording."));
                    return;
                }
                muxPath_=subtitled;
                mux_.start(QLatin1String("ffmpeg"),{
                    QLatin1String("-nostdin"),QLatin1String("-hide_banner"),
                    QLatin1String("-loglevel"),QLatin1String("error"),
                    QLatin1String("-n"),QLatin1String("-i"),aiPath_,
                    QLatin1String("-i"),srt,
                    QLatin1String("-map"),QLatin1String("0:v?"),
                    QLatin1String("-map"),QLatin1String("0:a?"),
                    QLatin1String("-map"),QLatin1String("1:0"),
                    QLatin1String("-c"),QLatin1String("copy"),
                    QLatin1String("-c:s"),QLatin1String("srt"),muxPath_});
                if(!mux_.waitForStarted(750))
                    report(tr("SRT saved but MKV mux could not start (FFmpeg missing)."));
            });
        connect(&mux_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
            this,[this](int code,QProcess::ExitStatus){
                if(code==0 && QFileInfo::exists(muxPath_)) {
                    addToLibrary(muxPath_);
                    report(tr("Subtitled MKV ready: %1").arg(QFileInfo(muxPath_).fileName()));
                } else {
                    report(tr("Original and SRT preserved; MKV export failed: %1")
                        .arg(QString::fromUtf8(mux_.readAllStandardError()).right(210)));
                }
            });
    }
    ~TihuluUnifiedRecorder() override {
        // Never abandon an ffmpeg writer with a still-open media container.
        if(capture_.state()!=QProcess::NotRunning) {
            capture_.write("q\n");
            if(!capture_.waitForFinished(2200)) {
                capture_.terminate();
                if(!capture_.waitForFinished(600))capture_.kill();
            }
        }
        if(ai_.state()!=QProcess::NotRunning)ai_.kill();
        if(mux_.state()!=QProcess::NotRunning)mux_.kill();
    }

private:
    static QString recordingsFolder() {
        QSettings config(QLatin1String("TIHULU"),QLatin1String("UnifiedRecordings"));
        QString name=config.value(QLatin1String("folder")).toString();
        if(name.isEmpty()) {
            QString movies=QStandardPaths::writableLocation(QStandardPaths::MoviesLocation);
            if(movies.isEmpty())movies=QDir::homePath();
            name=movies+QLatin1String("/TIHULU Recordings");
        }
        return name;
    }
    static bool supportedInput(const QUrl &url) {
        if(!url.isValid())return false;
        if(url.isLocalFile())
            return QFileInfo(url.toLocalFile()).isFile();
        return (url.scheme()==QLatin1String("https") ||
                url.scheme()==QLatin1String("http")) && !url.host().isEmpty();
    }
    void report(const QString &message) {
        statusMessage_=message;
        record_->setToolTip(message);
        if(parentWidget() && parentWidget()->window()) {
            auto *bar=qobject_cast<QMainWindow *>(parentWidget()->window());
            if(bar && bar->statusBar())bar->statusBar()->showMessage(message,12000);
        }
    }
    void refreshButton() {
        record_->setText(recording_?tr("■ STOP REC"):tr("● REC"));
        record_->setToolTip(recording_?
            tr("Recording in progress. Stop to finalize the file."):
            tr("Record current source · optional offline subtitles."));
        record_->setStyleSheet(recording_?
            QLatin1String("QToolButton{background:#c93e42;color:white;"
                         "border-radius:4px;padding:4px 7px;font-weight:bold;}"):
            QLatin1String("QToolButton{background:#68262a;color:white;"
                         "border-radius:4px;padding:4px 7px;font-weight:bold;}"));
    }
    void startRecording() {
        if(capture_.state()!=QProcess::NotRunning ||
           ai_.state()!=QProcess::NotRunning ||
           mux_.state()!=QProcess::NotRunning) {
            report(tr("Finish active recording/AI export before starting another."));
            return;
        }
        const bool liveTv=dvb_ && dvb_->getManager() &&
            dvb_->getManager()->getLiveView() &&
            dvb_->getManager()->getLiveView()->getDevice();
        const QUrl url=player_->property("tihulu_recordable_url").toUrl();
        if(!liveTv && (!supportedInput(url) ||
                player_->getPlaybackStatus()==MediaWidget::Idle)) {
            QMessageBox::information(this,tr("Nothing recordable"),
                tr("Open a local video/audio, Internet TV, Internet radio or DAB/analog "
                   "stream first. For live DVB-T2, tune a TV channel. "
                   "Protected DVD/optical-disc capture is not supported."));
            return;
        }
        QDialog options(this);
        options.setWindowTitle(tr("Record current playback"));
        auto *form=new QVBoxLayout(&options);
        auto *intro=new QLabel(liveTv?
            tr("DVB-T2: use native Kaffeine recording to avoid opening a second tuner. "
               "After stopping, import its output file from the Kaffeine recording folder."):
            tr("Record the current media source from now into a new MKV. "
               "Player overlays are not burned into video; optional SRT is generated "
               "afterward and embedded as a selectable subtitle track."),&options);
        intro->setWordWrap(true);
        form->addWidget(intro);
        auto *aiChoice=new QCheckBox(tr("After recording, use local AI to generate subtitles + MKV"),&options);
        aiChoice->setChecked(true); // explicit opt-in by confirming Record dialog
        auto *musicChoice=new QCheckBox(tr("Transcribe singing/music vocals too"),&options);
        auto *targets=new QLineEdit(QLatin1String("en,de,tr"),&options);
        targets->setPlaceholderText(tr("Translation targets, comma separated (max 3)"));
        form->addWidget(aiChoice);
        form->addWidget(musicChoice);
        form->addWidget(new QLabel(tr("Translation languages (en,de,tr or empty):"),&options));
        form->addWidget(targets);
        auto *folder=new QLineEdit(recordingsFolder(),&options);
        auto *folderRow=new QHBoxLayout();
        folderRow->addWidget(folder);
        auto *browse=new QPushButton(tr("Choose folder"),&options);
        folderRow->addWidget(browse);
        form->addLayout(folderRow);
        connect(browse,&QPushButton::clicked,&options,[&](){
            const QString f=QFileDialog::getExistingDirectory(&options,
                tr("Choose recording directory"),folder->text());
            if(!f.isEmpty())folder->setText(f);
        });
        auto *actions=new QHBoxLayout();
        auto *cancel=new QPushButton(tr("Cancel"),&options);
        auto *begin=new QPushButton(tr("● Start recording"),&options);
        actions->addWidget(cancel);
        actions->addWidget(begin);
        form->addLayout(actions);
        connect(cancel,&QPushButton::clicked,&options,&QDialog::reject);
        connect(begin,&QPushButton::clicked,&options,&QDialog::accept);
        if(options.exec()!=QDialog::Accepted)return;
        const QString savedFolder=folder->text().trimmed();
        if(savedFolder.isEmpty() || !QDir().mkpath(savedFolder)) {
            report(tr("Cannot create recording directory."));return;
        }
        QSettings config(QLatin1String("TIHULU"),QLatin1String("UnifiedRecordings"));
        config.setValue(QLatin1String("folder"),savedFolder);
        subtitlesAfter_=aiChoice->isChecked();
        singing_=musicChoice->isChecked();
        targets_=targets->text().trimmed();
        if(liveTv) {
            if(dvb_->getManager()->getRecordingModel() &&
                dvb_->getManager()->getRecordingModel()->hasActiveRecordings()){
                report(tr("Native DVB already has an active recording. "
                    "Use Kaffeine Television recordings to avoid toggling an "
                    "unrelated recording or interrupting it."));
                return;
            }
            captureKind_=QLatin1String("dvb");
            dvb_->toggleInstantRecord();
            recording_=true;
            startedMs_=QDateTime::currentMSecsSinceEpoch();
            recordedPath_.clear();
            recordingUrl_=QUrl();
            elapsed_.start();
            refreshButton();
            report(tr("Native DVB instant-record requested; confirm Kaffeine "
                "recording indicator. Stop here to finalize."));
            return;
        }
        if(QStandardPaths::findExecutable(QLatin1String("ffmpeg")).isEmpty()){
            report(tr("FFmpeg is required to record this stream."));return;
        }
        const QString timestamp=QDateTime::currentDateTimeUtc().toString(
            QLatin1String("yyyyMMdd-HHmmsszzz"));
        recordedPath_=savedFolder+QLatin1String("/TIHULU-")+
            timestamp+QLatin1String(".mkv");
        if(QFileInfo::exists(recordedPath_)){
            report(tr("Destination already exists. Recording was not started."));return;
        }
        QStringList args{QLatin1String("-hide_banner"),QLatin1String("-loglevel"),
            QLatin1String("error"),QLatin1String("-n")};
        if(url.isLocalFile()) {
            if(player_->getPosition()>0)
                args<<QLatin1String("-ss")<<QString::number(
                    player_->getPosition()/1000.,'f',3);
            // A file must be read at playback rate or FFmpeg would
            // finish recording its entire remaining content instantly.
            args<<QLatin1String("-re");
        }
        args<<QLatin1String("-i")<<(url.isLocalFile()?url.toLocalFile():url.toString())
            <<QLatin1String("-map")<<QLatin1String("0:v:0?")
            <<QLatin1String("-map")<<QLatin1String("0:a:0?")
            <<QLatin1String("-c:v")<<QLatin1String("copy")
            <<QLatin1String("-c:a")<<QLatin1String("aac")
            <<QLatin1String("-b:a")<<QLatin1String("160k")
            <<QLatin1String("-f")<<QLatin1String("matroska")
            <<recordedPath_;
        intentionalStop_=false;
        finalizing_=false;
        captureKind_=QLatin1String("ffmpeg");
        capture_.start(QLatin1String("ffmpeg"),args);
        if(!capture_.waitForStarted(950)) {
            report(tr("FFmpeg recorder could not start."));return;
        }
        recording_=true;
        recordingUrl_=url;
        startedMs_=QDateTime::currentMSecsSinceEpoch();
        elapsed_.start();
        refreshButton();
        report(tr("REC · saving source stream to %1").arg(recordedPath_));
    }
    void stopRecording() {
        if(!recording_)return;
        if(captureKind_==QLatin1String("dvb")) {
            dvb_->toggleInstantRecord();
            recording_=false;
            elapsed_.stop();
            refreshButton();
            report(tr("Native DVB record stop requested. Select the resulting "
                "Kaffeine TV recording from Recordings → Import; it is not "
                "automatically identified or modified."));
            return;
        }
        if(finalizing_)return;
        finalizing_=true;
        record_->setEnabled(false);
        intentionalStop_=true;
        capture_.write("q\n"); // ffmpeg finalizes Matroska header/trailer.
        QTimer::singleShot(4000,this,[this](){
            if(capture_.state()!=QProcess::NotRunning){
                capture_.terminate();
                QTimer::singleShot(850,this,[this](){
                    if(capture_.state()!=QProcess::NotRunning)capture_.kill();
                });
            }
        });
        report(tr("Finalizing recording; it will appear in Recordings when saved."));
    }
    void addToLibrary(const QString &path) {
        const QFileInfo file(path);
        if(!file.isFile() || file.size()==0)return;
        QSettings cfg(QLatin1String("TIHULU"),QLatin1String("UnifiedRecordings"));
        QStringList items=cfg.value(QLatin1String("paths")).toStringList();
        if(!items.contains(file.absoluteFilePath()))items.prepend(file.absoluteFilePath());
        while(items.size()>500)items.removeLast();
        cfg.setValue(QLatin1String("paths"),items);
        cfg.sync();
    }
    void generateCaptions(const QString &path,const QString &languages,bool music) {
        if(ai_.state()!=QProcess::NotRunning || !QFileInfo::exists(path))return;
        aiPath_=path;
        QStringList args{QLatin1String("media-captions"),QLatin1String("--input"),path,
                         QLatin1String("--source"),QLatin1String("auto"),
                         QLatin1String("--targets"),languages};
        if(music)args<<QLatin1String("--music");
        ai_.start(QLatin1String("tihulu-tv-center"),args);
        if(!ai_.waitForStarted(850))
            report(tr("Recording saved; cannot start installed AI companion."));
        else
            report(tr("Recording saved. Offline AI is creating real-timestamp SRT…"));
    }
    void openLibrary() {
        QDialog dialog(this);
        dialog.setWindowTitle(tr("TIHULU Recordings · open / import / subtitle"));
        dialog.resize(760,420);
        auto *root=new QVBoxLayout(&dialog);
        auto *info=new QLabel(tr("Recordings are user-owned local files. "
            "Open any item in the TIHULU player. Import native TV recordings "
            "or your existing audio/video files. AI processing is optional."),&dialog);
        info->setWordWrap(true);
        root->addWidget(info);
        auto *list=new QListWidget(&dialog);
        root->addWidget(list,1);
        auto populate=[&](){
            list->clear();
            QSettings cfg(QLatin1String("TIHULU"),QLatin1String("UnifiedRecordings"));
            for(const QString &path:cfg.value(QLatin1String("paths")).toStringList()){
                const QFileInfo f(path);
                if(!f.isFile() || f.size()==0)continue;
                auto *item=new QListWidgetItem(f.fileName()+
                    QLatin1String("  ·  ")+QString::number(f.size()/1024)+
                    tr(" KiB"),list);
                item->setData(Qt::UserRole,f.absoluteFilePath());
                item->setToolTip(f.absoluteFilePath());
            }
        };
        populate();
        auto *row=new QHBoxLayout();
        auto *open=new QPushButton(tr("▶ Open in player"),&dialog);
        auto *import=new QPushButton(tr("Import saved media / TV recording"),&dialog);
        auto *caption=new QPushButton(tr("Generate AI subtitles"),&dialog);
        auto *folder=new QPushButton(tr("Open recording folder"),&dialog);
        row->addWidget(open);row->addWidget(import);
        row->addWidget(caption);row->addWidget(folder);
        root->addLayout(row);
        auto selected=[&]()->QString{
            return list->currentItem()?list->currentItem()->data(Qt::UserRole).toString():QString();
        };
        connect(open,&QPushButton::clicked,&dialog,[&,this](){
            const QString path=selected();
            if(path.isEmpty() || !QFileInfo(path).isFile())return;
            const QFileInfo info(path);
            const QString subtitle=info.absolutePath()+QLatin1Char('/')+
                info.completeBaseName()+QLatin1String(".srt");
            if(openPlayback_)openPlayback_();
            player_->play(QUrl::fromLocalFile(path),
                QFileInfo::exists(subtitle)?QUrl::fromLocalFile(subtitle):QUrl());
            dialog.accept();
        });
        connect(list,&QListWidget::itemDoubleClicked,&dialog,
                [open](QListWidgetItem*){open->click();});
        connect(import,&QPushButton::clicked,&dialog,[&,this](){
            const QString path=QFileDialog::getOpenFileName(&dialog,
                tr("Import a finished recording"),QDir::homePath(),
                tr("Media (*.mkv *.mp4 *.ts *.m2ts *.mp3 *.flac *.wav *.m4a *.aac *.webm *.ogg)"));
            if(path.isEmpty())return;
            addToLibrary(path);populate();
        });
        connect(caption,&QPushButton::clicked,&dialog,[&,this](){
            const QString path=selected();
            if(path.isEmpty() || ai_.state()!=QProcess::NotRunning ||
               mux_.state()!=QProcess::NotRunning)return;
            generateCaptions(path,QLatin1String("en,de,tr"),false);
            dialog.accept();
        });
        connect(folder,&QPushButton::clicked,&dialog,[](){
            QDesktopServices::openUrl(QUrl::fromLocalFile(recordingsFolder()));
        });
        dialog.exec();
    }

    MediaWidget *player_=nullptr;
    DvbTab *dvb_=nullptr;
    std::function<void()> openPlayback_;
    QToolButton *record_=nullptr,*library_=nullptr;
    QProcess capture_,ai_,mux_;
    QTimer elapsed_;
    QUrl recordingUrl_;
    qint64 startedMs_=0;
    bool recording_=false,finalizing_=false,intentionalStop_=false,
         subtitlesAfter_=false,singing_=false;
    QString captureKind_,recordedPath_,aiPath_,muxPath_,targets_,statusMessage_;
};
#endif // TIHULU_UNIFIED_RECORDER_H
