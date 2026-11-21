// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef TIHULU_CAPTION_OPTIONS_H
#define TIHULU_CAPTION_OPTIONS_H
#include <QWidget>
#include <QComboBox>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QJsonDocument>
#include <QJsonArray>
#include <QJsonObject>
#include <QLabel>
#include <QListWidget>
#include <QProcess>
#include <QPushButton>
#include <QSignalBlocker>
#include <QTimer>

// The same local inventory used by TV and Radio. No arbitrary language promises,
// no network catalog and no model load when opening a file or this selector.
class TihuluCaptionOptions final : public QWidget {
public:
    explicit TihuluCaptionOptions(QWidget *parent=nullptr):QWidget(parent),catalog_(this) {
        auto *form=new QFormLayout(this);
        form->setContentsMargins(0,0,0,0);
        source_=new QComboBox(this);
        source_->setObjectName(QStringLiteral("captionInputLanguage"));
        source_->addItem(tr("Auto detect"),QStringLiteral("auto"));
        targets_=new QListWidget(this);
        targets_->setObjectName(QStringLiteral("captionOutputLanguages"));
        targets_->setMaximumHeight(135);
        model_=new QComboBox(this);
        model_->addItem(tr("Configured local speech model"),QStringLiteral("configured"));
        model_->addItem(tr("Whisper.cpp · selected local GGML file"),QStringLiteral("cpu-file"));
        model_->addItem(tr("Installed Faster-Whisper CUDA"),QStringLiteral("managed-cuda"));
        auto *browse=new QPushButton(tr("Use existing model file…"),this);
        connect(browse,&QPushButton::clicked,this,[this](){
            const QString path=QFileDialog::getOpenFileName(this,tr("Use existing Whisper model"),
                localModel_,tr("Whisper GGML (*.bin)"));
            if(path.isEmpty())return;
            localModel_=path; model_->setCurrentIndex(model_->findData(QStringLiteral("cpu-file")));
            status_->setText(tr("Using existing file (no copy): %1").arg(path));
        });
        status_=new QLabel(tr("Reading installed models and languages…"),this);
        status_->setWordWrap(true);
        auto *refresh=new QPushButton(tr("Refresh installed models / languages"),this);
        connect(refresh,&QPushButton::clicked,this,[this](){reload();});
        form->addRow(tr("IN · spoken language"),source_);
        form->addRow(tr("OUT · installed translators (up to 6)"),targets_);
        form->addRow(tr("Offline speech model"),model_);
        form->addRow(browse);form->addRow(refresh);form->addRow(status_);
        connect(source_,QOverload<int>::of(&QComboBox::currentIndexChanged),this,[this](){
            wantedSource_=source_->currentData().toString();
        });
        connect(targets_,&QListWidget::itemChanged,this,[this](QListWidgetItem *changed){
            if(targets().size()>6) {
                const QSignalBlocker blocker(targets_);changed->setCheckState(Qt::Unchecked);
                status_->setText(tr("Choose at most six OUT languages."));
            }
            wantedTargets_=targets();
        });
        connect(&catalog_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),this,
            [this](int code,QProcess::ExitStatus exit){
                const QByteArray data=catalog_.readAllStandardOutput();
                QJsonParseError error; const auto doc=QJsonDocument::fromJson(data,&error);
                if(code || exit!=QProcess::NormalExit || error.error!=QJsonParseError::NoError || !doc.isObject()) {
                    ready_=false;status_->setText(tr("Local catalog unavailable; check the companion runtime and refresh."));return;
                }
                info_=doc.object();ready_=true;populate();
            });
        QTimer::singleShot(0,this,[this](){reload();});
    }
    ~TihuluCaptionOptions() override {
        if(catalog_.state()!=QProcess::NotRunning) {catalog_.kill();catalog_.waitForFinished(600);}
    }
    void setLanguages(const QString &source,const QStringList &targets) {
        wantedSource_=source;wantedTargets_=targets;
        if(ready_)populate();
    }
    QStringList targets() const {
        QStringList out;
        for(int i=0;i<targets_->count();++i) {
            const auto *item=targets_->item(i);
            if(item->checkState()==Qt::Checked && (item->flags() & Qt::ItemIsEnabled))
                out<<item->data(Qt::UserRole).toString();
        }
        return out;
    }
    bool appendArguments(QStringList &args) {
        const QString model=model_->currentData().toString();
        if(!ready_) {status_->setText(tr("Wait for the local catalog or press Refresh."));return false;}
        if(model==QStringLiteral("cpu-file")) {
            if(!QFileInfo(localModel_).isFile()) {status_->setText(tr("Choose an existing GGML model file."));return false;}
            args<<QStringLiteral("--whisper-file")<<localModel_;
        } else if(!info_.value(model==QStringLiteral("managed-cuda")?
                   QStringLiteral("cuda_model_present"):QStringLiteral("speech_model_present")).toBool()) {
            status_->setText(tr("No local speech model found. Use an existing model file or select the installed asset folder."));return false;
        }
        args<<QStringLiteral("--source")<<source_->currentData().toString()
            <<QStringLiteral("--targets")<<targets().join(QLatin1Char(','))
            <<QStringLiteral("--record-model")<<model<<QStringLiteral("--progress");
        return true;
    }
private:
    void reload() {
        if(catalog_.state()!=QProcess::NotRunning)return;
        ready_=false;status_->setText(tr("Reading installed models and languages…"));
        const quint64 generation=++generation_;
        catalog_.start(QStringLiteral("tihulu-tv-center"),{QStringLiteral("ai-file-languages")});
        if(!catalog_.waitForStarted(750)) {
            status_->setText(tr("Local AI companion could not start."));return;
        }
        QTimer::singleShot(12000,this,[this,generation](){
            if(generation==generation_ && catalog_.state()!=QProcess::NotRunning)catalog_.kill();
        });
    }
    void populate() {
        const QSignalBlocker a(source_),b(targets_);
        source_->clear();source_->addItem(tr("Auto detect"),QStringLiteral("auto"));
        for(const auto &value:info_.value(QStringLiteral("speech_languages")).toArray()) {
            const auto row=value.toObject();const QString code=row.value(QStringLiteral("code")).toString();
            source_->addItem(row.value(QStringLiteral("label")).toString()+QStringLiteral(" · ")+code,code);
        }
        source_->setCurrentIndex(qMax(0,source_->findData(wantedSource_)));
        targets_->clear();
        for(const auto &value:info_.value(QStringLiteral("languages")).toArray()) {
            const auto row=value.toObject();const QString code=row.value(QStringLiteral("code")).toString();
            QStringList engines;for(const auto &e:row.value(QStringLiteral("engines")).toArray())engines<<e.toString();
            auto *item=new QListWidgetItem(row.value(QStringLiteral("label")).toString()+QStringLiteral(" · ")+code,targets_);
            item->setData(Qt::UserRole,code);item->setToolTip(engines.join(QStringLiteral(", ")));
            item->setFlags(item->flags()|Qt::ItemIsUserCheckable);
            item->setCheckState(wantedTargets_.contains(code)?Qt::Checked:Qt::Unchecked);
        }
        const auto errors=info_.value(QStringLiteral("errors")).toArray();
        status_->setText(tr("%1 installed OUT candidates · %2. IN languages use one multilingual Whisper model; translation pairs are checked at runtime.%3")
            .arg(targets_->count()).arg(info_.value(QStringLiteral("speech_model_selected")).toString())
            .arg(errors.isEmpty()?QString():tr(" Some local inventories were unavailable; refresh to retry.")));
    }
    QComboBox *source_=nullptr,*model_=nullptr;
    QListWidget *targets_=nullptr;
    QLabel *status_=nullptr;
    QProcess catalog_;
    QJsonObject info_;
    QString wantedSource_=QStringLiteral("auto"),localModel_;
    QStringList wantedTargets_;
    quint64 generation_=0;
    bool ready_=false;
};
#endif
