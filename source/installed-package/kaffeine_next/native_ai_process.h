// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef TIHULU_AI_PROCESS_H
#define TIHULU_AI_PROCESS_H
#include <QProcess>
#include <csignal>
#include <unistd.h>

// One process group per explicitly started AI job. Helpers (Whisper, translator,
// FFmpeg) inherit it; stopping a job never matches or signals unrelated processes.
class TihuluAiProcess : public QProcess {
public:
    explicit TihuluAiProcess(QObject *parent=nullptr):QProcess(parent) {
        connect(this,&QProcess::started,this,[this](){group_=processId();});
        connect(this,QOverload<int,QProcess::ExitStatus>::of(&QProcess::finished),
            this,[this](int,QProcess::ExitStatus){clearGroup();});
    }
    ~TihuluAiProcess() override { stopJob(); }
    void stopJob() {
        terminate();
        if(state()!=NotRunning && !waitForFinished(1000)) {
            kill();waitForFinished(700);
        }
        clearGroup();
    }
    void terminate() {
        // Graceful parent exit flushes SRT first. Descendants are reaped by the
        // finished handler even when their parent exits before they do.
        QProcess::terminate();
    }
    void kill() { clearGroup();QProcess::kill(); }
protected:
    void setupChildProcess() override {
        if(::setsid()<0) ::_exit(126);
    }
private:
    void clearGroup() {
        const qint64 group=group_;group_=0;
        if(group>1) ::kill(-static_cast<pid_t>(group),SIGKILL);
    }
    qint64 group_=0;
};
#endif
