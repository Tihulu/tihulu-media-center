/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Small in-player AI controls: original Video/Audio file remains in the
 * existing libVLC MediaWidget. No new Qt top-level player or file window.
 */
#ifndef TIHULU_NATIVE_MEDIA_PANEL_H
#define TIHULU_NATIVE_MEDIA_PANEL_H
#include "mediawidget.h"
#include <QCheckBox>
#include <QComboBox>
#include <QFile>
#include <QDir>
#include <QDateTime>
#include <QMimeDatabase>
#include <QProgressBar>
#include <QRegularExpression>
#include <QFileInfo>
#include <QFileDialog>
#include <QMessageBox>
#include <QHBoxLayout>
#include <QGridLayout>
#include <QToolButton>
#include <QLabel>
#include <QLineEdit>
#include <QProcess>
#include <QSettings>
#include <QSpinBox>
#include <QPushButton>
#include <QStandardPaths>
#include <QTimer>
#include <QCoreApplication>
#include <QUrl>
#include <QVBoxLayout>
#include <QWidget>

class TihuluMediaPanel final:public QWidget {
public:
	explicit TihuluMediaPanel(MediaWidget *player, QWidget *parent=nullptr)
		:QWidget(parent), player_(player), process_(this)
	{
		setObjectName(QLatin1String("tihuluMediaPanel"));
		setStyleSheet(QLatin1String(
			"QWidget#tihuluMediaPanel{background:#12202c;border-top:1px solid #356078}"
			"QLabel{color:#d3e9f3}QPushButton{padding:6px}"));
		auto *v=new QVBoxLayout(this);
		v->setContentsMargins(9,5,9,6);
		v->setSpacing(4);
		auto *h=new QHBoxLayout();
		h->addWidget(new QLabel(tr("Local Video / Audio · offline AI"),this));
		file_=new QLabel(tr("Open a file from Start / File → Open"),this);
		file_->setTextInteractionFlags(Qt::TextSelectableByMouse);
		file_->setMinimumWidth(120);
		h->addWidget(file_,1);
		v->addLayout(h);
        QSettings openSettings(QLatin1String("TIHULU"),QLatin1String("MediaPlayer"));
        preprocessOnOpen_=new QCheckBox(tr(
            "Entire local file · transcribe/translate first, then play"),this);
        preprocessOnOpen_->setChecked(openSettings.value(
            QLatin1String("transcribeBeforeOpen"),false).toBool());
        preprocessOnOpen_->setToolTip(tr(
            "Optional for local video and audio. Prevents initial playback "
            "until complete offline transcription and translations finish. "
            "Live TV/radio and URLs remain untouched."));
        v->addWidget(preprocessOnOpen_);
        connect(preprocessOnOpen_,&QCheckBox::toggled,this,[](bool enabled){
            QSettings prefs(QLatin1String("TIHULU"),QLatin1String("MediaPlayer"));
            prefs.setValue(QLatin1String("transcribeBeforeOpen"),enabled);
        });
        profile_=new QLabel(tr(
            "Local video uses TV AI preferences; audio uses Radio AI preferences."),this);
        profile_->setWordWrap(true);
        v->addWidget(profile_);
        auto *expand=new QToolButton(this);
        expand->setText(tr("Show offline AI / lyric / export options"));
        expand->setCheckable(true);
        expand->setChecked(false);
        expand->setToolButtonStyle(Qt::ToolButtonTextOnly);
        auto *details=new QWidget(this);
        auto *detailsLayout=new QVBoxLayout(details);
        detailsLayout->setContentsMargins(0,0,0,0);
        detailsLayout->setSpacing(4);
        v->addWidget(expand);
        v->addWidget(details);
        connect(expand,&QToolButton::toggled,this,[details,expand,this](bool enabled){
            details->setVisible(enabled);
            expand->setText(enabled?tr("Hide offline AI / lyric / export options"):
                tr("Show offline AI / lyric / export options"));
        });
        details->setVisible(false);
		auto *tools=new QGridLayout();
		language_=new QComboBox(this);
		language_->addItem(tr("Auto detect (GPU)"),QLatin1String("auto"));
		for(const QString &code:QStringList{"de","en","tr","fr","es","pl","ja","ar"})
			language_->addItem(code.toUpper(),code);
		tools->addWidget(new QLabel(tr("Speech language"),this),0,0);
        tools->addWidget(language_,0,1,1,2);
		en_=new QCheckBox(tr("EN"),this); en_->setChecked(true);
		de_=new QCheckBox(tr("DE"),this);
		tr_=new QCheckBox(tr("TR"),this); tr_->setChecked(true);
		music_=new QCheckBox(tr("Song vocals"),this);
		lyrics_=new QCheckBox(tr("Use synced .lrc"),this);
		lyricsOnline_=new QCheckBox(tr("Find lyrics online (optional)"),this);
		lyricsOnline_->setToolTip(tr("Only song title/artist metadata is sent "
			"to LRCLIB after pressing Generate, never file audio. No API key."));
        extraTargets_=new QLineEdit(this);
        extraTargets_->setPlaceholderText(tr("Other targets · fr, es, pl, ja…"));
        extraTargets_->setToolTip(tr(
            "Additional output languages from the same installed translation models."));
        original_=new QCheckBox(tr("Include original transcription"),this);
        original_->setChecked(true);
		tools->addWidget(de_,1,0);
        tools->addWidget(en_,1,1);
        tools->addWidget(tr_,1,2);
        tools->addWidget(music_,2,0,1,2);
        tools->addWidget(lyrics_,2,2);
        tools->addWidget(extraTargets_,3,0,1,2);
        tools->addWidget(original_,3,2);
        tools->setColumnStretch(1,1);
		detailsLayout->addLayout(tools);
		auto *actions = new QGridLayout();
		actions->addWidget(lyricsOnline_,0,0,1,3);
		run_=new QPushButton(tr("Transcribe entire file + load captions"),this);
		cancel_=new QPushButton(tr("Cancel"),this);
		cancel_->setEnabled(false);
		export_=new QPushButton(tr("Save video/audio + subtitles (.mkv)"),this);
		export_->setToolTip(tr("Mux the original media and existing time-coded SRT "
			"as an editable/selectable subtitle track; original files remain unchanged."));
		export_->setEnabled(false);
		caching_=new QSpinBox(this);
		caching_->setRange(0,20000);
		caching_->setSingleStep(500);
		caching_->setSuffix(tr(" ms"));
		QSettings mediaSettings(QLatin1String("TIHULU"),QLatin1String("MediaPlayer"));
		caching_->setValue(qBound(0,
			mediaSettings.value(QLatin1String("fileCacheMs"),1500).toInt(),20000));
		caching_->setToolTip(tr("libVLC file read-ahead; this is not the "
			"same as the Whisper subtitle creation budget."));
		wait_=new QCheckBox(tr("Preprocess before playback · finish first"),this);
		wait_->setChecked(true);
		wait_->setToolTip(tr("Stops the selected media during offline transcription, "
			"then restarts it at the beginning with synchronized SRT. "
			"Processing the entire file can take a while."));
		actions->addWidget(new QLabel(tr("File cache:"),this),1,0);
        actions->addWidget(caching_,1,1);
        actions->addWidget(wait_,1,2);
        actions->addWidget(run_,2,0,1,2);
        actions->addWidget(cancel_,2,2);
        actions->addWidget(export_,3,0,1,3);
        actions->setColumnStretch(1,1);
		detailsLayout->addLayout(actions);
		message_=new QLabel(tr("Caption file will attach to the same playing video/audio."),this);
		message_->setWordWrap(true);
		v->addWidget(message_);
        workProgress_=new QProgressBar(this);
        workProgress_->setRange(0,0); // Indeterminate until worker reports completion
        workProgress_->setVisible(false);
        v->addWidget(workProgress_);
		connect(run_,&QPushButton::clicked,this,[this](){generate(false);});
		connect(export_,&QPushButton::clicked,this,[this](){exportWithCaptions();});
		connect(&exportProcess_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
			this,[this](int exitCode,QProcess::ExitStatus exitStatus){
				export_->setEnabled(true);
				if(exitCode==0 && exitStatus==QProcess::NormalExit)
					message_->setText(tr("Export complete · playable MKV with selectable SRT: %1")
						.arg(exportPath_));
				else
					message_->setText(tr("Media export failed: %1")
						.arg(QString::fromUtf8(exportProcess_.readAllStandardError()).right(350)));
			});
		connect(cancel_,&QPushButton::clicked,this,[this](){
			if(process_.state()!=QProcess::NotRunning) {
                cancelledByUser_=true;
				process_.kill();
				message_->setText(tr("Transcription cancelled; source media untouched."));
			}
		});
		connect(&process_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
			this,[this](int exitCode,QProcess::ExitStatus exitStatus) {
				run_->setEnabled(true);
				cancel_->setEnabled(false);
                workProgress_->setVisible(false);
                if(cancelledForFileChange_) {
                    cancelledForFileChange_=false;
                    cancelledByUser_=false;
                    pausedForAi_=false;
                    beforeOpenMode_=false;
                    return; // Never reopen a previous selected file.
                }
                if(cancelledByUser_) {
                    cancelledByUser_=false;
                    const bool manualPause=pausedForAi_ && !beforeOpenMode_;
                    pausedForAi_=false;
                    beforeOpenMode_=false;
                    if(manualPause && !path_.isEmpty())
                        player_->play(QUrl::fromLocalFile(path_));
                    message_->setText(tr("Whole-file transcription cancelled. "
                        "Automatic file opening cancelled; source untouched."));
                    return;
                }
				if(exitCode==0 && exitStatus==QProcess::NormalExit &&
				   !path_.isEmpty() && QFile::exists(srtPath_)) {
					if (pausedForAi_) {
						pausedForAi_=false;
						player_->play(QUrl::fromLocalFile(path_));
					}
                    beforeOpenMode_=false;
					player_->setSubtitle(QUrl::fromLocalFile(srtPath_));
                    // libVLC can still be opening the just-started file.
                    // Retry attaching once, but never to a newly opened
                    // different media file or a different transcription.
                    const QString opened=path_, subtitle=srtPath_;
                    QTimer::singleShot(650,this,[this,opened,subtitle](){
                        if(path_==opened && srtPath_==subtitle &&
                           QFileInfo(subtitle).isFile())
                            player_->setSubtitle(QUrl::fromLocalFile(subtitle));
                    });
					export_->setEnabled(true);
					message_->setText(tr("Attached generated subtitles to current "
						"file playback · %1").arg(srtPath_));
				} else {
					if (pausedForAi_ && !path_.isEmpty() && !beforeOpenMode_)
						player_->play(QUrl::fromLocalFile(path_));
                    pausedForAi_=false;
                    beforeOpenMode_=false;
					const QString err=QString::fromUtf8(process_.readAllStandardError());
					message_->setText(tr("Offline captions unavailable: %1")
						.arg(err.left(220)));
				}
			});
	}
	void setLocalFile(const QUrl &url) {
        if(!url.isLocalFile()) return;
        const QString candidate=url.toLocalFile();
        if(!QFileInfo(candidate).isFile()) return;
        if(candidate!=path_ && process_.state()!=QProcess::NotRunning) {
            cancelledForFileChange_=true;
            process_.kill();
            process_.waitForFinished(950);
        }
        path_=candidate;
        const QFileInfo info(candidate);
        const QMimeType mime=QMimeDatabase().mimeTypeForFile(
            candidate,QMimeDatabase::MatchExtension);
        const QString ext=info.suffix().toLower();
        isAudio_=mime.name().startsWith(QLatin1String("audio/")) ||
            QStringList{QLatin1String("mp3"),QLatin1String("wav"),
                QLatin1String("flac"),QLatin1String("m4a"),
                QLatin1String("aac"),QLatin1String("ogg"),
                QLatin1String("opus"),QLatin1String("wma"),
                QLatin1String("aiff"),QLatin1String("alac"),
                QLatin1String("mka")}.contains(ext);
        isLocalMedia_=isAudio_ ||
            mime.name().startsWith(QLatin1String("video/")) ||
            QStringList{QLatin1String("mp4"),QLatin1String("mkv"),
                QLatin1String("avi"),QLatin1String("mov"),
                QLatin1String("webm"),QLatin1String("ts"),
                QLatin1String("m2ts"),QLatin1String("mpeg"),
                QLatin1String("mpg"),QLatin1String("m4v")}.contains(ext);
        loadSharedCaptionProfile();
        srtPath_=info.absolutePath()+QLatin1Char('/')+
            info.completeBaseName()+QLatin1String(".srt");
        export_->setEnabled(QFileInfo(srtPath_).isFile());
        file_->setText(info.fileName());
        file_->setToolTip(candidate);
    }
    bool prepareLocalFileOpen(const QUrl &url) {
        // No live TV, DAB, HTTP or Web TV source may enter this gate.
        if(!url.isLocalFile() || !preprocessOnOpen_->isChecked() ||
           !QFileInfo(url.toLocalFile()).isFile()) return false;
        setLocalFile(url);
        if(!isLocalMedia_) return false;
        // Consume the requested Open action even if the AI worker fails
        // to LAUNCH. Falling through to Kaffeine's playlist would play an
        // untranscribed file despite the user's explicit finish-first choice.
        generate(true);
        return true;
    }
private:
    void loadSharedCaptionProfile() {
        // Video follows the APPLIED television caption choices; audio-only
        // files use Radio's existing persisted language/translation settings.
        // Both use the one common AISettings/model installation at runtime.
        QSettings defaults(QLatin1String("TIHULU"),
            isAudio_?QLatin1String("KaffeineRadio"):
                     QLatin1String("KaffeineTVFileCaptionDefaults"));
        const QString source=defaults.value(isAudio_?
            QLatin1String("radioSpeechLanguage"):QLatin1String("spokenSource"),
            QLatin1String("auto")).toString();
        int index=language_->findData(source);
        if(index<0 && !source.isEmpty()) {
            language_->addItem(source.toUpper(),source);
            index=language_->findData(source);
        }
        language_->setCurrentIndex(index>=0?index:0);
        QStringList targets=defaults.value(isAudio_?
            QLatin1String("radioOutputs"):QLatin1String("outputLanguages"),
            QStringList{QLatin1String("en"),QLatin1String("tr")}).toStringList();
        const bool translate=isAudio_?
            defaults.value(QLatin1String("radioTranslationOptIn"),false).toBool():
            defaults.value(QLatin1String("showTranslation"),true).toBool();
        if(!translate) targets.clear();
        en_->setChecked(targets.contains(QLatin1String("en")));
        de_->setChecked(targets.contains(QLatin1String("de")));
        tr_->setChecked(targets.contains(QLatin1String("tr")));
        QStringList extra;
        for(const QString &target:targets)
            if(target!=QLatin1String("en") && target!=QLatin1String("de") &&
               target!=QLatin1String("tr"))
                extra<<target;
        extraTargets_->setText(extra.join(QLatin1Char(',')));
        music_->setChecked(defaults.value(isAudio_?
            QLatin1String("radioMusicTranscription"):
            QLatin1String("musicTranscription"),false).toBool());
        original_->setChecked(isAudio_ || defaults.value(
            QLatin1String("showOriginal"),true).toBool());
        profile_->setText(isAudio_?
            tr("AUDIO · Radio IN/OUT language and translation settings; "
               "shared installed Whisper/translation models."):
            tr("VIDEO · applied TV IN/OUT language and display settings; "
               "shared installed Whisper/translation models. "
               "DVB live buffer/Teletext clock are NOT applied to a file."));
    }
	void exportWithCaptions() {
		if(exportProcess_.state()!=QProcess::NotRunning || path_.isEmpty() ||
		   !QFileInfo(path_).isFile() || !QFileInfo(srtPath_).isFile()) {
			message_->setText(tr("Open a local file with an existing generated SRT first."));
			return;
		}
		QString suggested=QFileInfo(path_).absolutePath()+QLatin1Char('/')+
			QFileInfo(path_).completeBaseName()+QLatin1String("-subtitled.mkv");
		QString destination=QFileDialog::getSaveFileName(this,tr("Save media with selectable subtitles"),
			suggested,tr("Matroska media (*.mkv)"));
		if(destination.isEmpty()) return;
		if(!destination.endsWith(QLatin1String(".mkv"),Qt::CaseInsensitive))
			destination+=QLatin1String(".mkv");
		if(QFileInfo(destination).exists()) {
			message_->setText(tr("Destination exists; choose another filename to protect your files."));
			return;
		}
		exportPath_=destination;
		// -n prevents overwrite even if another process creates this path.
		// Copy the original streams; mux subtitles as a selectable MKV track.
		// No protected-disc bypass, no unverified 'burned in' claim.
		exportProcess_.start(QLatin1String("ffmpeg"),
			{QLatin1String("-nostdin"),QLatin1String("-hide_banner"),
			 QLatin1String("-loglevel"),QLatin1String("error"),
			 QLatin1String("-n"),QLatin1String("-i"),path_,
			 QLatin1String("-i"),srtPath_,
			 QLatin1String("-map"),QLatin1String("0:v?"),
			 QLatin1String("-map"),QLatin1String("0:a?"),
			 QLatin1String("-map"),QLatin1String("1:0"),
			 QLatin1String("-c:v"),QLatin1String("copy"),
			 QLatin1String("-c:a"),QLatin1String("copy"),
			 QLatin1String("-c:s"),QLatin1String("srt"),
			 exportPath_});
		if(!exportProcess_.waitForStarted(800)) {
			message_->setText(tr("FFmpeg is not available for subtitled export."));
			return;
		}
		export_->setEnabled(false);
		message_->setText(tr("Muxing original media and SRT in the background…"));
	}
    bool generate(bool beforeOpen) {
        if(path_.isEmpty() || !QFileInfo(path_).isFile()) {
            message_->setText(tr("Select a local video or audio file first."));
            return false;
        }
        if(process_.state()!=QProcess::NotRunning) return false;
        QStringList targets;
        if(de_->isChecked()) targets<<QLatin1String("de");
        if(en_->isChecked()) targets<<QLatin1String("en");
        if(tr_->isChecked()) targets<<QLatin1String("tr");
        // Preserve script-specific TV outputs such as zho_Hant.
        const QRegularExpression validTarget(
            QLatin1String("^[a-z]{2,3}(?:_[A-Za-z]{4})?$"));
        for(const QString &item:extraTargets_->text().split(
            QLatin1Char(','),Qt::SkipEmptyParts)) {
            const QString code=item.trimmed();
            if(validTarget.match(code).hasMatch() && !targets.contains(code))
                targets<<code;
        }
        if(targets.size()>6) {
            message_->setText(tr("Select up to six output languages."));
            return false;
        }
        const QString cache=QStandardPaths::writableLocation(
            QStandardPaths::AppLocalDataLocation);
        if(cache.isEmpty() || !QDir().mkpath(cache)) {
            message_->setText(tr("Cannot create a private subtitle cache."));
            return false;
        }
        // Never overwrite an existing user-created .srt in the media folder,
        // including when the video is read-only or on a removable disk.
        srtPath_=cache+QLatin1String("/tihulu-file-")+
            QString::number(QCoreApplication::applicationPid())+
            QLatin1Char('-')+QString::number(
                QDateTime::currentMSecsSinceEpoch())+
            QLatin1String(".srt");
        QStringList args{QLatin1String("media-captions"),
            QLatin1String("--input"),path_,
            QLatin1String("--source"),language_->currentData().toString(),
            QLatin1String("--targets"),targets.join(QLatin1Char(',')),
            QLatin1String("--output"),srtPath_};
        if(!original_->isChecked() && !targets.isEmpty())
            args<<QLatin1String("--translations-only");
        if(music_->isChecked()) args<<QLatin1String("--music");
        // Whole-file-before-open always uses actual local Whisper audio;
        // optional lyric-only matching remains available on manual Generate.
        if(lyrics_->isChecked() && !beforeOpen) args<<QLatin1String("--lyrics");
        if(lyrics_->isChecked() && !beforeOpen && lyricsOnline_->isChecked())
            args<<QLatin1String("--fetch-lyrics");
        QSettings mediaSettings(QLatin1String("TIHULU"),QLatin1String("MediaPlayer"));
        mediaSettings.setValue(QLatin1String("fileCacheMs"),caching_->value());
        mediaSettings.sync();
        beforeOpenMode_=beforeOpen;
        cancelledByUser_=false;
        pausedForAi_=beforeOpen || wait_->isChecked();
        if(pausedForAi_) player_->stop();
        process_.start(QLatin1String("tihulu-tv-center"),args);
        if(!process_.waitForStarted(800)) {
            if(pausedForAi_ && !beforeOpen)
                player_->play(QUrl::fromLocalFile(path_));
            pausedForAi_=false;
            beforeOpenMode_=false;
            message_->setText(tr("Could not launch the offline AI worker."));
            return false;
        }
        run_->setEnabled(false);
        cancel_->setEnabled(true);
        workProgress_->setRange(0,0);
        workProgress_->setVisible(true);
        message_->setText(pausedForAi_?
            tr("Entire file: transcribing and translating before playback. "
               "Radio/TV live processing stays independent."):
            tr("Entire file: offline transcription in progress while media plays."));
        return true;
    }
	MediaWidget *player_;
	QProcess process_,exportProcess_;
	QLabel *file_=nullptr,*message_=nullptr;
	QComboBox *language_=nullptr;
	QCheckBox *de_=nullptr,*en_=nullptr,*tr_=nullptr,*music_=nullptr,*lyrics_=nullptr,
		*lyricsOnline_=nullptr,*original_=nullptr,*preprocessOnOpen_=nullptr;
	QPushButton *run_=nullptr,*cancel_=nullptr,*export_=nullptr;
	QSpinBox *caching_=nullptr;
    QLineEdit *extraTargets_=nullptr;
    QProgressBar *workProgress_=nullptr;
    QLabel *profile_=nullptr;
	QCheckBox *wait_=nullptr;
	bool pausedForAi_=false;
    bool cancelledForFileChange_=false;
    bool cancelledByUser_=false;
    bool beforeOpenMode_=false;
    bool isAudio_=false;
    bool isLocalMedia_=false;
	QString path_,srtPath_,exportPath_;
};
#endif
