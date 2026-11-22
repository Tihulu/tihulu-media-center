/*
 * TIHULU shared player recorder. LGPL-compatible FFmpeg external process,
 * native Kaffeine TV instant recording, optional offline Whisper sidecars.
 * Neither decoded VLC overlays nor DRM/DVD content are falsely claimed as
 * being captured. Original media remains untouched.
 */
#ifndef TIHULU_UNIFIED_RECORDER_H
#define TIHULU_UNIFIED_RECORDER_H

#include "mediawidget.h"
#include "tihulu_ai_process.h"
#include "tihulu_caption_options.h"
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
#include <QProgressBar>
#include <QDialogButtonBox>
#include <QUuid>
#include <QRegularExpression>
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
          capture_(this),mux_(this),probe_(this),ai_(this) {
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
        whisper_=new QToolButton(this);
        whisper_->setText(tr("Whisper"));
        whisper_->setToolTip(tr("Open the Live Teletext / Whisper subtitles window for the current "
            "TV channel (same as TIHULU AI \u2192 Live Teletext / Whisper subtitles)."));
        whisper_->setMaximumWidth(86);
        library_->setText(tr("Recordings"));
        library_->setToolTip(tr("Open previously recorded media, import native DVB "
            "recordings and generate optional captions."));
        record_->setMinimumWidth(78);
        library_->setMaximumWidth(100);
        line->addWidget(record_);
        line->addWidget(library_);
        line->addWidget(whisper_);
        progress_=new QProgressBar(this);
        progress_->setMaximumWidth(240);
        progress_->setAccessibleName(tr("Recording / subtitle job"));
        progress_->hide();
        line->addWidget(progress_);
        bar->addWidget(this);
        connect(player_,&MediaWidget::stopRequested,this,[this](){
            aiCancelled_=true;ai_.stopJob();stopRecording();
        });
        if(dvb_)connect(dvb_,&DvbTab::quickRecordRequested,this,[this](){
            if(recording_)stopRecording();else startRecording();
        });
        if(dvb_ && dvb_->getManager()) {
            connect(dvb_->getManager()->getLiveView(),&DvbLiveView::captureFinished,
                this,[this](const QString &path,const QString &error){
                    if(!recording_ || captureKind_!=QLatin1String("dvb"))return;
                    endRecordingUi();
                    if(!error.isEmpty()) { report(error); return; }
                    inspectRecording(path);
                });
        }
        connect(&probe_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
            this,[this](int code,QProcess::ExitStatus status){
                progress_->hide();
                const auto packets=probe_.readAllStandardOutput();
                if(status!=QProcess::NormalExit || code!=0 || (!packets.contains("audio") && !packets.contains("video"))) {
                    report(tr("No playable recording confirmed. Any partial file was left in place: %1").arg(recordedPath_)); return;
                }
                addToLibrary(recordedPath_);
                report(tr("Recording saved: %1").arg(recordedPath_));
                if(subtitlesAfter_)chooseCaptions(recordedPath_);
            });
        connect(&ai_,&QProcess::readyReadStandardOutput,this,[this](){
            while(ai_.canReadLine()) {
                const auto line=ai_.readLine();
                if(!line.startsWith("TIHULU_PROGRESS ")) {aiResult_+=line;continue;}
                const auto fields=line.trimmed().split(' ');
                if(fields.size()!=3 || fields[0]!="TIHULU_PROGRESS")continue;
                bool ok=false; const int pct=fields[2].toInt(&ok);
                if(!ok || pct < -1 || pct>100)continue;
                const QString phase=fields[1]=="translate"?tr("Translating"):
                    fields[1]=="save"?tr("Writing SRT"):tr("Transcribing");
                jobProgress(phase,pct);
            }
        });
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
            if(captureKind_==QLatin1String("dvb") && !dvb_->getManager()->getLiveView()->captureError().isEmpty()) {
                stopRecording(); return;
            }
            const qint64 seconds=qMax(qint64(0),
                (QDateTime::currentMSecsSinceEpoch()-startedMs_)/1000);
            const qint64 bytes=QFileInfo(recordedPath_).size();
            record_->setToolTip(captureKind_==QLatin1String("dvb")?
                tr("TV recording %1:%2 · %3 bytes written")
                  .arg(seconds/60).arg(seconds%60,2,10,QLatin1Char('0')).arg(qMax(qint64(0),bytes)):
                tr("REC elapsed %1:%2 · saved %3 MiB. "
                "Live recording has no known completion percentage.")
                  .arg(seconds/60).arg(seconds%60,2,10,QLatin1Char('0'))
                  .arg(QString::number(qMax(qint64(0),bytes)/1048576.,'f',1)));
        });
        connect(record_,&QToolButton::clicked,this,[this](){
            if(recording_)stopRecording(); else startRecording();
        });
        connect(library_,&QToolButton::clicked,this,[this](){openLibrary();});
        connect(whisper_,&QToolButton::clicked,this,[this](){openWhisperService();});
        connect(&capture_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
            this,[this](int exitCode,QProcess::ExitStatus status){
                if(captureKind_!=QLatin1String("ffmpeg"))return;
                endRecordingUi();
                if(status!=QProcess::NormalExit || exitCode!=0) {
                    report(tr("Recording was interrupted. Any partial file was kept: %1").arg(recordedPath_)); return;
                }
                inspectRecording(recordedPath_);
            });
        connect(&ai_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
            this,[this](int code,QProcess::ExitStatus){
                progress_->hide();
                if(aiCancelled_) {report(tr("AI stopped; recording preserved."));return;}
                aiResult_+=ai_.readAllStandardOutput();
                const auto result=QJsonDocument::fromJson(aiResult_).object();
                subtitleWarning_=QString();
                const auto warnings=result.value("translation_warnings").toArray();
                if(!warnings.isEmpty())subtitleWarning_=tr("Translation warning: %1").arg(warnings.first().toObject().value("warning").toString());
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
                jobProgress(tr("Embedding subtitles"));
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
                if(!mux_.waitForStarted(750)) { progress_->hide(); report(tr("SRT saved but MKV mux could not start.")); }
            });
        connect(&mux_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
            this,[this](int code,QProcess::ExitStatus){
                progress_->hide();
                if(code==0 && QFileInfo(muxPath_).size()>0) {
                    addToLibrary(muxPath_);
                    report(tr("Subtitled MKV ready: %1 · %2").arg(QFileInfo(muxPath_).fileName(),subtitleWarning_));
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
        aiCancelled_=true;ai_.stopJob();
        if(probe_.state()!=QProcess::NotRunning) {probe_.kill();probe_.waitForFinished(600);}
        if(mux_.state()!=QProcess::NotRunning) {mux_.kill();mux_.waitForFinished(600);}
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
        if(recording_ || probe_.state()!=QProcess::NotRunning || capture_.state()!=QProcess::NotRunning ||
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
        auto *form=new QFormLayout(&options);
        auto *intro=new QLabel(liveTv?
            tr("Save the current TV service to the chosen folder using the stream already playing. "
               "Stopping or changing channel finalizes this clip. Scheduled TV recordings stay independent."):
            tr("Record the current media source from now into a new MKV. "
               "Player overlays are not burned into video; optional SRT is generated "
               "afterward and embedded as a selectable subtitle track."),&options);
        intro->setWordWrap(true);
        form->addWidget(intro);
        auto *format=new QComboBox(&options);
        format->addItem(tr("Video · MKV (default)"),QStringLiteral("mkv"));
        format->addItem(tr("Broadcast · MPEG-TS .m2t"),QStringLiteral("m2t"));
        format->addItem(tr("Audio only (.mka)"),QStringLiteral("audio"));
        format->addItem(tr("Video on black canvas (radio)"),QStringLiteral("black"));
        form->addRow(tr("Output format"),format);
        auto *aiChoice=new QCheckBox(tr("Offer subtitle language and local model options after saving"),&options);
        aiChoice->setChecked(true); // showing a dialog does not start a model
        form->addWidget(aiChoice);
        auto *folder=new QLineEdit(recordingsFolder(),&options);
        auto *folderRow=new QHBoxLayout();
        folderRow->addWidget(folder);
        auto *browse=new QPushButton(tr("Choose folder"),&options);
        folderRow->addWidget(browse);
        form->addRow(tr("Recording folder"),folderRow);
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
        form->addRow(QString(),actions);
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
        outputFormat_=format->currentData().toString();
        if(liveTv) {
            recordedPath_=QDir(savedFolder).absoluteFilePath(QLatin1String("TIHULU-TV-")+
                QDateTime::currentDateTime().toString(QLatin1String("yyyyMMdd-HHmmss-"))+
                QUuid::createUuid().toString(QUuid::WithoutBraces)+QLatin1String(".m2t"));
            if(!dvb_->getManager()->getLiveView()->beginCapture(recordedPath_)) {
                report(tr("TV source no longer available or recording destination is in use.")); return;
            }
            captureKind_=QLatin1String("dvb");
            recording_=true;
            startedMs_=QDateTime::currentMSecsSinceEpoch();
            elapsed_.start(); refreshButton();
            report(tr("TV recording armed · waiting for stream data: %1").arg(recordedPath_));
            return;
        }
        if(QStandardPaths::findExecutable(QLatin1String("ffmpeg")).isEmpty()){
            report(tr("FFmpeg is required to record this stream."));return;
        }
        const QString timestamp=QDateTime::currentDateTimeUtc().toString(
            QLatin1String("yyyyMMdd-HHmmsszzz"));
        const QString extension=outputFormat_==QLatin1String("m2t")?QStringLiteral("m2t"):
            outputFormat_==QLatin1String("audio")?QStringLiteral("mka"):
            outputFormat_==QLatin1String("black")?QStringLiteral("mkv"):
            QLatin1String("mkv");
        recordedPath_=savedFolder+QLatin1String("/TIHULU-")+
            timestamp+QLatin1Char('.')+extension;
        if(QFileInfo::exists(recordedPath_)){
            report(tr("Destination already exists. Recording was not started."));return;
        }
        QStringList args{QLatin1String("-hide_banner"),QLatin1String("-loglevel"),
            QLatin1String("error"),QLatin1String("-n")};
        // Radio on a black canvas: a real video surface with the station audio,
        // so the same playback, SRT and subtitle tooling as TV works.
        if(outputFormat_==QLatin1String("black"))
            args<<QLatin1String("-f")<<QLatin1String("lavfi")
                <<QLatin1String("-i")<<QLatin1String("color=c=black:s=320x240:r=5");
        if(url.isLocalFile()) {
            if(player_->getPosition()>0)
                args<<QLatin1String("-ss")<<QString::number(
                    player_->getPosition()/1000.,'f',3);
            // A file must be read at playback rate or FFmpeg would
            // finish recording its entire remaining content instantly.
            args<<QLatin1String("-re");
        }
        args<<QLatin1String("-i")<<(url.isLocalFile()?url.toLocalFile():url.toString());
        if(outputFormat_==QLatin1String("audio")) {
            args<<QLatin1String("-map")<<QLatin1String("0:a:0?")
                <<QLatin1String("-c:a")<<QLatin1String("aac")<<QLatin1String("-b:a")<<QLatin1String("160k")
                <<QLatin1String("-f")<<QLatin1String("matroska");
        } else if(outputFormat_==QLatin1String("m2t")) {
            args<<QLatin1String("-map")<<QLatin1String("0:v:0?")
                <<QLatin1String("-map")<<QLatin1String("0:a:0?")
                <<QLatin1String("-c:v")<<QLatin1String("copy")
                <<QLatin1String("-c:a")<<QLatin1String("aac")
                <<QLatin1String("-f")<<QLatin1String("mpegts");
        } else if(outputFormat_==QLatin1String("black")) {
            args<<QLatin1String("-map")<<QLatin1String("0:v")
                <<QLatin1String("-map")<<QLatin1String("1:a:0?")
                <<QLatin1String("-shortest")
                <<QLatin1String("-c:v")<<QLatin1String("libx264")<<QLatin1String("-preset")<<QLatin1String("ultrafast")
                <<QLatin1String("-pix_fmt")<<QLatin1String("yuv420p")
                <<QLatin1String("-c:a")<<QLatin1String("aac")<<QLatin1String("-b:a")<<QLatin1String("160k")
                <<QLatin1String("-f")<<QLatin1String("matroska");
        } else {
            args<<QLatin1String("-map")<<QLatin1String("0:v:0?")
                <<QLatin1String("-map")<<QLatin1String("0:a:0?")
                <<QLatin1String("-c:v")<<QLatin1String("copy")
                <<QLatin1String("-c:a")<<QLatin1String("aac")
                <<QLatin1String("-b:a")<<QLatin1String("160k")
                <<QLatin1String("-f")<<QLatin1String("matroska");
        }
        args<<recordedPath_;
        ++captureGeneration_;
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
    // Shortcut for the live caption service: focus an existing window, otherwise
    // start one for the currently tuned DVB service (no second tuner, no model
    // load until the user asks for subtitles).
    void openWhisperService() {
        const QString runtime=QStandardPaths::writableLocation(QStandardPaths::RuntimeLocation);
        if(runtime.isEmpty()) {
            report(tr("XDG_RUNTIME_DIR is missing; cannot start the caption service."));
            return;
        }
        const QString name=runtime+QLatin1String("/tihulu-dvb-")+
            QString::number(QCoreApplication::applicationPid())+QLatin1String(".sock");
        if(QFileInfo::exists(runtime+QLatin1String("/tihulu-captions-control-")+
                             QString::number(QCoreApplication::applicationPid())+QLatin1String(".sock"))) {
            if(QProcess::startDetached(QLatin1String("tihulu-tv-center"),
                    {QLatin1String("kaffeine-captions"),QLatin1String("--socket"),name,QLatin1String("--show-only")}))
                return;
        }
        whisperJob_.start(QLatin1String("tihulu-tv-center"),
            {QLatin1String("kaffeine-captions"),QLatin1String("--socket"),name});
        if(!whisperJob_.waitForStarted(900))
            report(tr("Could not open the Whisper caption service."));
        else
            report(tr("Opening live captions for the current TV service\u2026"));
    }
    void stopRecording() {
        if(!recording_)return;
        if(captureKind_==QLatin1String("dvb")) {
            dvb_->getManager()->getLiveView()->endCapture();
            return;
        }
        if(finalizing_)return;
        finalizing_=true;
        record_->setEnabled(false);
        const quint64 generation=captureGeneration_;
        capture_.write("q\n"); // ffmpeg finalizes Matroska header/trailer.
        QTimer::singleShot(4000,this,[this,generation](){
            if(generation==captureGeneration_ && capture_.state()!=QProcess::NotRunning){
                capture_.terminate();
                QTimer::singleShot(850,this,[this,generation](){
                    if(generation==captureGeneration_ && capture_.state()!=QProcess::NotRunning)capture_.kill();
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
    void endRecordingUi() {
        recording_=false; finalizing_=false; elapsed_.stop();
        record_->setEnabled(true); refreshButton();
    }
    void jobProgress(const QString &phase,int percent=-1) {
        progress_->setRange(0,percent<0?0:100);
        progress_->setValue(qMax(0,percent));
        progress_->setFormat(phase+(percent<0?QString():tr(" · %p%")));
        progress_->setToolTip(phase); progress_->show();
    }
    void inspectRecording(const QString &path) {
        if(!QFileInfo(path).isFile() || QFileInfo(path).size()==0) {
            report(tr("Nothing was saved: the recording contains no data.")); return;
        }
        recordedPath_=path;
        jobProgress(tr("Checking saved recording"));
        // Require a real audio/video packet; container headers alone are not a recording.
        probe_.start(QLatin1String("ffprobe"),{QLatin1String("-v"),QLatin1String("error"),
            QLatin1String("-read_intervals"),QLatin1String("%+#120"),QLatin1String("-show_entries"),
            QLatin1String("packet=codec_type"),QLatin1String("-of"),QLatin1String("csv=p=0"),path});
        if(!probe_.waitForStarted(800)) { progress_->hide(); report(tr("Recording kept; FFprobe unavailable for verification.")); }
        const auto generation=++probeGeneration_;
        QTimer::singleShot(15000,this,[this,generation](){
            if(generation==probeGeneration_ && probe_.state()!=QProcess::NotRunning)probe_.kill();
        });
    }
    void chooseCaptions(const QString &path) {
        // Media has already been finalized. Cancel or a missing model must never undo the save.
        if(!QFileInfo(path).isFile() || ai_.state()!=QProcess::NotRunning || mux_.state()!=QProcess::NotRunning)return;
        QDialog dialog(this); dialog.setWindowTitle(tr("Subtitles for saved media"));
        QFormLayout form(&dialog);
        form.addRow(tr("Saved file"),new QLabel(QFileInfo(path).fileName(),&dialog));
        TihuluCaptionOptions choices(&dialog);
        QCheckBox music(tr("Include singing / music vocals"));
        form.addRow(&choices);form.addRow(&music);
        QDialogButtonBox buttons(QDialogButtonBox::Ok|QDialogButtonBox::Cancel);
        buttons.button(QDialogButtonBox::Ok)->setText(tr("Generate subtitles"));
        buttons.button(QDialogButtonBox::Cancel)->setText(tr("Keep media only"));
        QStringList args;
        connect(&buttons,&QDialogButtonBox::accepted,&dialog,[&](){
            args=QStringList{"media-captions","--input",path};
            if(!choices.appendArguments(args))return;
            if(music.isChecked())args<<QLatin1String("--music");
            dialog.accept();
        });
        connect(&buttons,&QDialogButtonBox::rejected,&dialog,&QDialog::reject);form.addRow(&buttons);
        if(dialog.exec()!=QDialog::Accepted)return;
        aiCancelled_=false;aiResult_.clear();
        aiPath_=path;
        jobProgress(tr("Preparing local subtitles"));
        ai_.start(QLatin1String("tihulu-tv-center"),args);
        if(!ai_.waitForStarted(850)) { progress_->hide(); report(tr("Recording kept; offline subtitle worker unavailable.")); }
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
                tr("Media (*.mkv *.mp4 *.ts *.m2t *.m2ts *.mka *.mp3 *.flac *.wav *.m4a *.aac *.webm *.ogg)"));
            if(path.isEmpty())return;
            addToLibrary(path);populate();
        });
        connect(caption,&QPushButton::clicked,&dialog,[&,this](){
            const QString path=selected();
            if(path.isEmpty() || ai_.state()!=QProcess::NotRunning ||
               mux_.state()!=QProcess::NotRunning)return;
            dialog.accept();
            chooseCaptions(path);
        });
        connect(folder,&QPushButton::clicked,&dialog,[](){
            QDesktopServices::openUrl(QUrl::fromLocalFile(recordingsFolder()));
        });
        dialog.exec();
    }

    MediaWidget *player_=nullptr;
    DvbTab *dvb_=nullptr;
    std::function<void()> openPlayback_;
    QToolButton *record_=nullptr,*library_=nullptr,*whisper_=nullptr;
    QProcess capture_,mux_,probe_;
    TihuluAiProcess whisperJob_;
    TihuluAiProcess ai_;
    QProgressBar *progress_=nullptr;
    quint64 captureGeneration_=0,probeGeneration_=0;
    bool aiCancelled_=false;
    QByteArray aiResult_;
    QString subtitleWarning_;
    QTimer elapsed_;
    QUrl recordingUrl_;
    qint64 startedMs_=0;
    bool recording_=false,finalizing_=false,
         subtitlesAfter_=false;
    QString outputFormat_=QStringLiteral("mkv");
    QString captureKind_,recordedPath_,aiPath_,muxPath_,statusMessage_;
};
#endif // TIHULU_UNIFIED_RECORDER_H
