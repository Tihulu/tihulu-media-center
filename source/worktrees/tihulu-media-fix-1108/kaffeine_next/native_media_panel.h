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
		tools->addWidget(de_,1,0);
        tools->addWidget(en_,1,1);
        tools->addWidget(tr_,1,2);
        tools->addWidget(music_,2,0,1,2);
        tools->addWidget(lyrics_,2,2);
        tools->setColumnStretch(1,1);
		detailsLayout->addLayout(tools);
		auto *actions = new QGridLayout();
		actions->addWidget(lyricsOnline_,0,0,1,3);
		run_=new QPushButton(tr("Generate + load captions"),this);
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
		wait_=new QCheckBox(tr("Preprocess before playback"),this);
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
		connect(run_,&QPushButton::clicked,this,[this](){generate();});
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
				process_.kill();
				message_->setText(tr("Subtitle generation stopped. Original playback untouched."));
			}
		});
		connect(&process_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
			this,[this](int exitCode,QProcess::ExitStatus exitStatus) {
				run_->setEnabled(true);
				cancel_->setEnabled(false);
				if(exitCode==0 && exitStatus==QProcess::NormalExit &&
				   !path_.isEmpty() && QFile::exists(srtPath_)) {
					if (pausedForAi_) {
						pausedForAi_=false;
						player_->play(QUrl::fromLocalFile(path_));
					}
					player_->setSubtitle(QUrl::fromLocalFile(srtPath_));
					export_->setEnabled(true);
					message_->setText(tr("Attached generated subtitles to current "
						"file playback · %1").arg(srtPath_));
				} else {
					if (pausedForAi_ && !path_.isEmpty()) {
						pausedForAi_=false;
						player_->play(QUrl::fromLocalFile(path_));
					}
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
		path_=candidate;
		srtPath_=QFileInfo(candidate).absolutePath()+QLatin1Char('/')+
			QFileInfo(candidate).completeBaseName()+QLatin1String(".srt");
		export_->setEnabled(QFileInfo(srtPath_).isFile());
		file_->setText(QFileInfo(candidate).fileName());
		file_->setToolTip(candidate);
	}
private:
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
	void generate() {
		if(path_.isEmpty() || !QFileInfo(path_).isFile()) {
			message_->setText(tr("Open a local media file in TIHULU first."));
			return;
		}
		if(process_.state()!=QProcess::NotRunning) return;
		QStringList targets;
		if(de_->isChecked()) targets<<QLatin1String("de");
		if(en_->isChecked()) targets<<QLatin1String("en");
		if(tr_->isChecked()) targets<<QLatin1String("tr");
		srtPath_=QFileInfo(path_).absolutePath()+QLatin1Char('/')+
			QFileInfo(path_).completeBaseName()+QLatin1String(".srt");
		QStringList args{QLatin1String("media-captions"),
			QLatin1String("--input"),path_,
			QLatin1String("--source"),language_->currentData().toString(),
			QLatin1String("--targets"),targets.join(QLatin1Char(','))};
		if(music_->isChecked()) args<<QLatin1String("--music");
		if(lyrics_->isChecked()) args<<QLatin1String("--lyrics");
		if(lyrics_->isChecked() && lyricsOnline_->isChecked())
			args<<QLatin1String("--fetch-lyrics");
		// The CLI refuses overwriting an existing user's .srt; the
		// player can still attach that file with the native subtitle menu.
		QSettings mediaSettings(QLatin1String("TIHULU"),QLatin1String("MediaPlayer"));
		mediaSettings.setValue(QLatin1String("fileCacheMs"),caching_->value());
		mediaSettings.sync();
		pausedForAi_=wait_->isChecked();
		if (pausedForAi_) player_->stop();
		process_.start(QLatin1String("tihulu-tv-center"),args);
		if(!process_.waitForStarted(800)){
			if (pausedForAi_) {
				pausedForAi_=false;
				player_->play(QUrl::fromLocalFile(path_));
			}
			message_->setText(tr("Could not launch TIHULU AI worker."));
			return;
		}
		run_->setEnabled(false);
		cancel_->setEnabled(true);
		message_->setText(tr("Processing current file offline · same local "
			"GPU Whisper and translation models. Playback stays available."));
	}
	MediaWidget *player_;
	QProcess process_,exportProcess_;
	QLabel *file_=nullptr,*message_=nullptr;
	QComboBox *language_=nullptr;
	QCheckBox *de_=nullptr,*en_=nullptr,*tr_=nullptr,*music_=nullptr,*lyrics_=nullptr,
		*lyricsOnline_=nullptr;
	QPushButton *run_=nullptr,*cancel_=nullptr,*export_=nullptr;
	QSpinBox *caching_=nullptr;
	QCheckBox *wait_=nullptr;
	bool pausedForAi_=false;
	QString path_,srtPath_,exportPath_;
};
#endif
