/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Native Hardware page: read-only Linux USB/DVB inventory and explicit
 * ownership of only TIHULU's own welle-cli and rtl_fm worker processes.
 * Physical USB attach/detach cannot be commanded by ordinary software.
 */
#ifndef TIHULU_HARDWARE_TAB_H
#define TIHULU_HARDWARE_TAB_H

#include "tabbase.h"
#include "tihulu_radio_tab.h"
#include "dvb/dvbtab.h"
#include "dvb/dvbmanager.h"
#include "dvb/dvbliveview.h"
#include "dvb/dvbrecording.h"

#include <QCheckBox>
#include <QColor>
#include <QDateTime>
#include <QGridLayout>
#include <QGroupBox>
#include <QHeaderView>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QProcess>
#include <QPushButton>
#include <QScrollArea>
#include <QSet>
#include <QTimer>
#include <QTime>
#include <QFrame>
#include <QTreeWidget>
#include <QVBoxLayout>

#include <functional>

class TihuluHardwareTab final : public TabBase
{
public:
    explicit TihuluHardwareTab(TihuluRadioTab *radio, DvbTab *dvb,
        MediaWidget *media, std::function<void()> openRadio,
        std::function<void()> openTv, QWidget *parent=nullptr)
        : TabBase(), radio_(radio), dvb_(dvb), media_(media),
          openRadio_(openRadio), openTv_(openTv), inventory_(this), timer_(this)
    {
        setParent(parent);
        auto *outer=new QVBoxLayout(this);
        outer->setContentsMargins(2,2,2,2);
        auto *scroll=new QScrollArea(this);
        scroll->setWidgetResizable(true);
        scroll->setFrameShape(QFrame::NoFrame);
        auto *page=new QWidget(scroll);
        auto *root=new QVBoxLayout(page);
        root->setContentsMargins(12,10,12,12);
        root->setSpacing(9);
        scroll->setWidget(page);
        outer->addWidget(scroll);

        auto *title=new QLabel(tr("Hardware · DVB-T2 / RTL-SDR / USB receivers"),page);
        title->setStyleSheet(QLatin1String("font-size:19px;font-weight:650;"));
        root->addWidget(title);
        auto *note=new QLabel(tr(
            "USB connected ≠ receiver acquired ≠ RF lock. "
            "Detection does not open a tuner. Use/release only affects TIHULU's "
            "own workers; never unbinds drivers, ejects USB or kills other apps."),page);
        note->setWordWrap(true);
        root->addWidget(note);
        auto *noTunerNote=new QLabel(tr(
            "No antenna or USB tuner? TIHULU still plays local files, "
            "Internet TV (Television → Web TV / Internet channels) and "
            "Internet radio (Radio → Internet radio). These use the normal "
            "libVLC player and do not start DVB, welle-cli or rtl_fm. "
            "Only terrestrial TV, DAB+ and FM/MW/LW reception need hardware."),page);
        noTunerNote->setWordWrap(true);
        noTunerNote->setStyleSheet(QLatin1String(
            "background:#17334a;border:1px solid #426480;"
            "border-radius:7px;padding:9px;color:#d0f0fa;"));
        root->addWidget(noTunerNote);

        auto *tools=new QGridLayout();
        refreshButton_=new QPushButton(tr("Refresh devices now"),page);
        monitor_=new QCheckBox(tr("Watch USB plug / unplug · every 2.5 s"),page);
        monitor_->setChecked(false); // explicitly opt in to recurring polling
        filter_=new QCheckBox(tr("Receiver devices only"),page);
        filter_->setChecked(true);
        ownerButton_=new QPushButton(tr("Check DVB owners (read-only)"),page);
        tools->addWidget(refreshButton_,0,0);
        tools->addWidget(monitor_,0,1);
        tools->addWidget(filter_,1,0);
        tools->addWidget(ownerButton_,1,1);
        tools->setColumnStretch(1,1);
        root->addLayout(tools);

        summary_=new QLabel(tr("Inventory: not checked yet."),page);
        summary_->setWordWrap(true);
        root->addWidget(summary_);
        list_=new QTreeWidget(page);
        list_->setColumnCount(5);
        list_->setHeaderLabels({
            tr("Type"),tr("Detected hardware"),tr("USB VID:PID / device path"),
            tr("User permission"),tr("Kernel / physical status")});
        list_->setRootIsDecorated(false);
        list_->setAlternatingRowColors(true);
        list_->setMinimumHeight(220);
        list_->header()->setSectionResizeMode(0,QHeaderView::ResizeToContents);
        list_->header()->setSectionResizeMode(1,QHeaderView::Stretch);
        list_->header()->setSectionResizeMode(2,QHeaderView::ResizeToContents);
        list_->header()->setSectionResizeMode(3,QHeaderView::ResizeToContents);
        list_->header()->setSectionResizeMode(4,QHeaderView::Stretch);
        root->addWidget(list_,3);

        auto *cards=new QGridLayout();
        cards->setColumnStretch(0,1);
        cards->setColumnStretch(1,1);

        auto *dvbCard=new QGroupBox(tr("DVB-T2 · native Kaffeine frontend"),page);
        auto *dvbLayout=new QVBoxLayout(dvbCard);
        tvStatus_=new QLabel(dvbCard);
        tvStatus_->setWordWrap(true);
        dvbLayout->addWidget(tvStatus_);
        auto *tvActions=new QVBoxLayout();
        useTv_=new QPushButton(tr("Open TV / tune last channel"),dvbCard);
        releaseTv_=new QPushButton(tr("Stop TV / release playback"),dvbCard);
        tvActions->addWidget(useTv_);
        tvActions->addWidget(releaseTv_);
        dvbLayout->addLayout(tvActions);
        auto *recordingNote=new QLabel(tr(
            "A DVB recording or scan can retain the frontend. "
            "This control never cancels a recording or scan."),dvbCard);
        recordingNote->setWordWrap(true);
        dvbLayout->addWidget(recordingNote);
        cards->addWidget(dvbCard,0,0,1,2);

        auto *dabCard=new QGroupBox(tr("DAB+ · own welle-cli receiver"),page);
        auto *dabLayout=new QVBoxLayout(dabCard);
        dabStatus_=new QLabel(dabCard);
        dabStatus_->setWordWrap(true);
        dabLayout->addWidget(dabStatus_);
        auto *dabActions=new QVBoxLayout();
        useDab_=new QPushButton(tr("Attach / start DAB receiver"),dabCard);
        releaseDab_=new QPushButton(tr("Release TIHULU DAB receiver"),dabCard);
        dabActions->addWidget(useDab_);
        dabActions->addWidget(releaseDab_);
        dabLayout->addLayout(dabActions);
        cards->addWidget(dabCard,1,0,1,2);

        auto *analogCard=new QGroupBox(tr("Analogue radio · own rtl_fm receiver"),page);
        auto *analogLayout=new QVBoxLayout(analogCard);
        analogStatus_=new QLabel(analogCard);
        analogStatus_->setWordWrap(true);
        analogLayout->addWidget(analogStatus_);
        auto *analogActions=new QVBoxLayout();
        useAnalog_=new QPushButton(tr("Attach / play selected FM"),analogCard);
        releaseAnalog_=new QPushButton(tr("Release TIHULU analogue SDR"),analogCard);
        analogActions->addWidget(useAnalog_);
        analogActions->addWidget(releaseAnalog_);
        analogLayout->addLayout(analogActions);
        cards->addWidget(analogCard,2,0,1,2);
        root->addLayout(cards);

        auto *help=new QLabel(tr(
            "No RF data? Check antenna, tuner ownership and frequency separately. "
            "DAB /channel HTTP API failure does not mean USB is disconnected. "
            "Analogue rtl_fm exit code 1 often needs driver/USB/other-process "
            "diagnostics; this page reports errors instead of assuming a fix."),page);
        help->setWordWrap(true);
        root->addWidget(help);

        ownerReport_=new QPlainTextEdit(page);
        ownerReport_->setReadOnly(true);
        ownerReport_->setPlaceholderText(tr(
            "Choose 'Check DVB owners' to inspect /dev/dvb frontends via fuser. "
            "No processes are stopped. This may not reveal processes owned by other users."));
        ownerReport_->setMaximumHeight(105);
        root->addWidget(ownerReport_);
        auto *logTitle=new QLabel(tr("Live hardware events · only while monitoring is enabled"),page);
        root->addWidget(logTitle);
        log_=new QPlainTextEdit(page);
        log_->setReadOnly(true);
        log_->setMaximumBlockCount(120);
        log_->setMaximumHeight(110);
        root->addWidget(log_);

        timer_.setInterval(2500);
        connect(&timer_,&QTimer::timeout,this,[this](){ refresh(false); });
        connect(refreshButton_,&QPushButton::clicked,this,[this](){refresh(true);});
        connect(monitor_,&QCheckBox::toggled,this,[this](bool enabled){
            if(enabled) {
                log_->appendPlainText(tr("Monitoring enabled · no device is opened."));
                timer_.start();
                refresh(true);
            } else {
                timer_.stop();
                log_->appendPlainText(tr("Monitoring stopped. Hardware devices untouched."));
            }
        });
        connect(filter_,&QCheckBox::toggled,this,[this](){renderInventory();});
        connect(ownerButton_,&QPushButton::clicked,this,[this](){checkOwners();});
        connect(&inventory_,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
            this,[this](int code,QProcess::ExitStatus exitStatus){
                refreshButton_->setEnabled(true);
                ownerButton_->setEnabled(true);
                if(code!=0 || exitStatus!=QProcess::NormalExit) {
                    summary_->setText(tr("Hardware inspection failed (exit %1). %2")
                        .arg(code).arg(QString::fromLocal8Bit(
                          inventory_.readAllStandardError()).right(200)));
                    return;
                }
                const auto json=QJsonDocument::fromJson(
                    inventory_.readAllStandardOutput());
                if(!json.isObject() ||
                   !json.object().value(QLatin1String("usb")).isArray() ||
                   !json.object().value(QLatin1String("dvb")).isArray()) {
                    summary_->setText(tr("Hardware inspector returned invalid JSON."));
                    return;
                }
                snapshot_=json.object();
                renderInventory();
                if(checkingOwners_)
                    ownerReport_->setPlainText(snapshot_.value(
                        QLatin1String("owner_report")).toString(
                        tr("DVB owner report unavailable.")));
                checkingOwners_=false;
            });
        connect(useDab_,&QPushButton::clicked,this,[this](){
            if(!radio_ || radio_->hardwareDabOwned()) return;
            if(radio_->hardwareAnalogOwned() &&
               QMessageBox::question(this,tr("Change SDR mode"),
                  tr("Starting DAB releases your own analog RTL-SDR session. Proceed?"))!=
                  QMessageBox::Yes) return;
            radio_->hardwareStartDab();
            refreshSessions();
        });
        connect(releaseDab_,&QPushButton::clicked,this,[this](){
            if(radio_)radio_->hardwareStopDab();
            refreshSessions();
        });
        connect(useAnalog_,&QPushButton::clicked,this,[this](){
            if(!radio_ || radio_->hardwareAnalogOwned()) return;
            if(radio_->hardwareDabOwned() &&
               QMessageBox::question(this,tr("Change SDR mode"),
                 tr("Starting analog radio releases your own DAB receiver. Proceed?"))!=
                 QMessageBox::Yes) return;
            radio_->hardwareStartAnalog();
            refreshSessions();
        });
        connect(releaseAnalog_,&QPushButton::clicked,this,[this](){
            if(radio_)radio_->hardwareStopAnalog();
            refreshSessions();
        });
        connect(useTv_,&QPushButton::clicked,this,[this](){
            if(!dvb_)return;
            if(QMessageBox::question(this,tr("Use native DVB tuner"),
              tr("Open Television and tune the most recently selected channel? "
                 "This may claim the DVB-T2 frontend. No channel scan is started."))!=
                QMessageBox::Yes) return;
            // The Hardware page can open TV without first visiting Radio.
            // Require the same owned-SDR release contract as the side tabs.
            if(radio_ && !radio_->releaseForTelevision()) {
                tvStatus_->setText(tr(
                    "TV switch cancelled: app-owned SDR is still busy. "
                    "Radio/TV playback unchanged."));
                return;
            }
            openTv_();
            dvb_->playLastChannel();
        });
        connect(releaseTv_,&QPushButton::clicked,this,[this](){
            if(!dvb_ || !dvb_->getManager())return;
            auto *manager=dvb_->getManager();
            if(manager->getRecordingModel() &&
               manager->getRecordingModel()->hasActiveRecordings()) {
                QMessageBox::information(this,tr("Recording in progress"),
                    tr("Cannot release DVB while Kaffeine is recording. "
                       "Stop the recording normally in Television first."));
                return;
            }
            if(!manager->getLiveView()->getDevice())return;
            media_->stop(); // native playback handles its own DVB release
            tvStatus_->setText(tr("Requested native TV stop; tuner release "
                                  "is asynchronous. Refresh to verify."));
        });
        refreshSessions();
    }

    void activate() override {
        refresh(true);
    }

private:
    void checkOwners() {
        if(inventory_.state()!=QProcess::NotRunning)return;
        checkingOwners_=true;
        ownerReport_->setPlainText(tr("Checking DVB owner PIDs without claiming hardware…"));
        launchInspector(true);
    }

    void refresh(bool manual) {
        refreshSessions();
        if(inventory_.state()!=QProcess::NotRunning)return;
        if(manual)summary_->setText(tr("Reading Linux USB and DVB devices (no USB open)…"));
        launchInspector(false);
    }

    void launchInspector(bool owners) {
        if(inventory_.state()!=QProcess::NotRunning)return;
        checkingOwners_=owners;
        refreshButton_->setEnabled(false);
        ownerButton_->setEnabled(false);
        QStringList args{QLatin1String("hardware-status")};
        if(owners)args<<QLatin1String("--owners");
        inventory_.start(QLatin1String("tihulu-tv-center"),args);
        if(!inventory_.waitForStarted(250)) {
            refreshButton_->setEnabled(true);
            ownerButton_->setEnabled(true);
            summary_->setText(tr("Hardware inspector not installed. "
                "Reinstall latest TIHULU TV Center package."));
            checkingOwners_=false;
            return;
        }
        QTimer::singleShot(5000,this,[this](){
            if(inventory_.state()!=QProcess::NotRunning)
                inventory_.kill(); // ONLY this helper process, never tuner/backend
        });
    }

    void refreshSessions() {
        if(radio_) {
            dabStatus_->setText(radio_->hardwareDabStatus());
            analogStatus_->setText(radio_->hardwareAnalogStatus());
            const bool dab=radio_->hardwareDabOwned();
            const bool analog=radio_->hardwareAnalogOwned();
            useDab_->setEnabled(!dab);
            releaseDab_->setEnabled(dab);
            useAnalog_->setEnabled(!analog);
            releaseAnalog_->setEnabled(analog);
        }
        if(dvb_ && dvb_->getManager()) {
            auto *manager=dvb_->getManager();
            const bool live=manager->getLiveView() &&
                            manager->getLiveView()->getDevice()!=nullptr;
            const bool recording=manager->getRecordingModel() &&
                                 manager->getRecordingModel()->hasActiveRecordings();
            tvStatus_->setText(live?tr("ACTIVE native DVB playback · frontend in use by "
                "TIHULU%1").arg(recording?tr(" · recording active"):QString()):
                recording?tr("DVB recording active · tuner must remain available"):
                tr("TIHULU live DVB currently RELEASED · physical/other-app "
                   "ownership is checked below"));
            releaseTv_->setEnabled(live && !recording);
        } else {
            tvStatus_->setText(tr("Native DVB frontend not built in this player."));
            releaseTv_->setEnabled(false);
            useTv_->setEnabled(false);
        }
    }

    void renderInventory() {
        if(snapshot_.isEmpty())return;
        const QJsonArray usb=snapshot_.value(QLatin1String("usb")).toArray();
        const QJsonArray dvb=snapshot_.value(QLatin1String("dvb")).toArray();
        QSet<QString> connected;
        for(const auto &j:usb) {
            const auto o=j.toObject();
            connected.insert(QLatin1String("usb:")+o.value(
                QLatin1String("id")).toString());
        }
        for(const auto &j:dvb) {
            const auto o=j.toObject();
            connected.insert(QLatin1String("dvb:")+o.value(
                QLatin1String("id")).toString());
        }
        if(inventorySeen_) {
            for(const auto &id:connected) if(!previous_.contains(id))
                log_->appendPlainText(QTime::currentTime().toString(QLatin1String("HH:mm:ss"))
                    +tr(" · CONNECTED · ")+id);
            for(const auto &id:previous_) if(!connected.contains(id))
                log_->appendPlainText(QTime::currentTime().toString(QLatin1String("HH:mm:ss"))
                    +tr(" · DISCONNECTED · ")+id);
        }
        previous_=connected;
        inventorySeen_=true;
        list_->clear();
        auto append=[this](const QJsonObject &o){
            auto *item=new QTreeWidgetItem(list_);
            item->setText(0,o.value(QLatin1String("kind")).toString());
            item->setText(1,o.value(QLatin1String("name")).toString());
            const QString vidpid=o.value(QLatin1String("vidpid")).toString();
            item->setText(2,vidpid.isEmpty()?
                o.value(QLatin1String("path")).toString():
                vidpid+QLatin1String(" · ")+o.value(QLatin1String("path")).toString());
            item->setText(3,o.value(QLatin1String("permission")).toString());
            item->setText(4,o.value(QLatin1String("physical")).toString());
            const bool denied=item->text(3).contains(QLatin1String("no user access"));
            if(denied)item->setForeground(3,QColor(QLatin1String("#ffbd7a")));
        };
        for(const auto &v:dvb)append(v.toObject());
        for(const auto &v:usb) {
            const auto o=v.toObject();
            if(filter_->isChecked() &&
               !o.value(QLatin1String("receiver_candidate")).toBool())continue;
            append(o);
        }
        const auto counts=snapshot_.value(QLatin1String("summary")).toObject();
        summary_->setText(tr("%1 USB devices · %2 receiver candidates · "
            "%3 DVB frontends · %4 shown. "
            "Kernel presence is not RF signal or exclusive ownership.")
            .arg(counts.value(QLatin1String("usb_count")).toInt())
            .arg(counts.value(QLatin1String("receiver_candidates")).toInt())
            .arg(counts.value(QLatin1String("dvb_frontends")).toInt())
            .arg(list_->topLevelItemCount()));
        if(list_->topLevelItemCount()==0)
            summary_->setText(summary_->text()+tr(
                " · No RF receiver found. Local media, Web TV and Internet radio "
                "remain available without hardware."));
    }

    TihuluRadioTab *radio_=nullptr;
    DvbTab *dvb_=nullptr;
    MediaWidget *media_=nullptr;
    std::function<void()> openRadio_,openTv_;
    QProcess inventory_;
    QTimer timer_;
    QCheckBox *monitor_=nullptr,*filter_=nullptr;
    QPushButton *refreshButton_=nullptr,*ownerButton_=nullptr;
    QPushButton *useTv_=nullptr,*releaseTv_=nullptr;
    QPushButton *useDab_=nullptr,*releaseDab_=nullptr;
    QPushButton *useAnalog_=nullptr,*releaseAnalog_=nullptr;
    QLabel *summary_=nullptr,*tvStatus_=nullptr,
           *dabStatus_=nullptr,*analogStatus_=nullptr;
    QTreeWidget *list_=nullptr;
    QPlainTextEdit *ownerReport_=nullptr,*log_=nullptr;
    QJsonObject snapshot_;
    QSet<QString> previous_;
    bool inventorySeen_=false,checkingOwners_=false;
};

#endif // TIHULU_HARDWARE_TAB_H
