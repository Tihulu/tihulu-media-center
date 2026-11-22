// SPDX-License-Identifier: GPL-2.0-or-later
#include "tihulu_media_panel.h"
#include "livecapture.h"
#include <QApplication>
#include <QtTest>
#include <QTemporaryDir>
#include <QTextStream>
#include <csignal>

class OwnerRegression : public QObject {
    Q_OBJECT
private slots:
    void stopKillsOnlyOwnedDescendants() {
        QProcess unrelated;unrelated.start("/usr/bin/python3",{"-c","import time;time.sleep(60)"});
        QVERIFY(unrelated.waitForStarted());
        TihuluAiProcess job;
        job.start("/usr/bin/python3",{"-u","-c","import subprocess,time,signal;signal.signal(signal.SIGTERM,signal.SIG_IGN);p=subprocess.Popen(['/usr/bin/python3','-c','import time;time.sleep(60)']);print(p.pid,flush=True);time.sleep(60)"});
        QVERIFY(job.waitForStarted());QVERIFY(job.waitForReadyRead(3000));
        const int child=job.readAllStandardOutput().trimmed().toInt();QVERIFY(child>1);
        job.stopJob();QCOMPARE(job.state(),QProcess::NotRunning);
        QTRY_VERIFY_WITH_TIMEOUT(!running(child),1500);
        QCOMPARE(unrelated.state(),QProcess::Running);
        unrelated.kill();QVERIFY(unrelated.waitForFinished());
    }
    void normalExitAlsoReleasesDescendants() {
        TihuluAiProcess job;
        job.start("/usr/bin/python3",{"-u","-c","import subprocess;print(subprocess.Popen(['/usr/bin/python3','-c','import time;time.sleep(60)']).pid,flush=True)"});
        QVERIFY(job.waitForStarted());QVERIFY(job.waitForFinished(3000));
        const int child=job.readAllStandardOutput().trimmed().toInt();QVERIFY(child>1);
        QTRY_VERIFY_WITH_TIMEOUT(!running(child),1500);
    }
    void audioSrtUsesPlaybackClockAndPlainText() {
        QTemporaryDir dir;QFile srt(dir.filePath("audio.srt"));QVERIFY(srt.open(QIODevice::WriteOnly));
        srt.write("1\r\n00:00:01,000 --> 00:00:02,500\r\n<original>\r\n[TR] test\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nSecond\r\n");srt.close();
        MediaWidget player;TihuluFileCaptions captions(&player);
        QVERIFY(captions.loadSrt(srt.fileName()));player.state=MediaWidget::Playing;player.position=1200;
        QTRY_COMPARE(captions.text(),QString("<original>\n[TR] test"));
        QCOMPARE(captions.textFormat(),Qt::PlainText);
        player.state=MediaWidget::Paused;QTest::qWait(150);QCOMPARE(captions.text(),QString("<original>\n[TR] test"));
        player.position=3100;QTRY_COMPARE(captions.text(),QString("Second"));
        player.position=1500;QTRY_COMPARE(captions.text(),QString("<original>\n[TR] test"));
        player.state=MediaWidget::Idle;QTRY_VERIFY(captions.isHidden());
    }
    void captureSilenceCollisionAndReplayBytes() {
        QTemporaryDir dir;LiveCapture capture;QString reason;
        const QString path=dir.filePath("tv.ts");
        QVERIFY(capture.begin(path));QVERIFY(capture.finish(reason).isEmpty());QVERIFY(!QFile::exists(path));
        QFile input(qEnvironmentVariable("TIHULU_SYNTHETIC_TS"));QVERIFY(input.open(QIODevice::ReadOnly));
        const QByteArray ts=input.readAll();QVERIFY(ts.size()>1000);QCOMPARE(ts.size()%188,0);
        QVERIFY(capture.begin(path));capture.tables(ts.left(376),ts.mid(376,188));
        for(int i=564;i<ts.size();i+=188)capture.packet(ts.constData()+i);
        QCOMPARE(capture.finish(reason),path);QVERIFY(reason.isEmpty());
        QFile saved(path);QVERIFY(saved.open(QIODevice::ReadOnly));QCOMPARE(saved.readAll(),ts);
        QVERIFY(!capture.begin(path));
        QProcess probe;probe.start("/usr/bin/ffprobe",{"-v","error","-show_entries","stream=codec_type","-of","csv=p=0",path});
        QVERIFY(probe.waitForFinished(5000));QCOMPARE(probe.exitCode(),0);QVERIFY(probe.readAllStandardOutput().contains("audio"));
    }
    void unavailableOutputIsExplicitAndCanBeUnchecked() {
        TihuluCaptionOptions options;
        options.setLanguages("en",{"tr","xx"});
        auto *list=options.findChild<QListWidget *>("captionOutputLanguages");
        QTRY_COMPARE_WITH_TIMEOUT(list->count(),2,3000);
        QStringList args;QVERIFY(!options.appendArguments(args));
        for(int i=0;i<list->count();++i)if(list->item(i)->data(Qt::UserRole).toString()=="xx")list->item(i)->setCheckState(Qt::Unchecked);
        args.clear();QVERIFY(options.appendArguments(args));
        QCOMPARE(args[args.indexOf("--targets")+1],QString("tr"));
    }
    void droppedFileReachesAiAndStopPreventsReopen() {
        QTemporaryDir dir;const QString media=dir.filePath("drop.wav");QFile file(media);QVERIFY(file.open(QIODevice::WriteOnly));file.write("fixture");file.close();
        MediaWidget player;TihuluMediaPanel panel(&player);player.show();panel.show();
        auto *source=panel.findChild<QComboBox *>("captionInputLanguage");QVERIFY(source);
        QTRY_VERIFY_WITH_TIMEOUT(source->count()>1,3000);
        QMimeData mime;mime.setUrls({QUrl::fromLocalFile(media)});
        QDragEnterEvent enter(QPoint(5,5),Qt::CopyAction,&mime,Qt::LeftButton,Qt::NoModifier);QApplication::sendEvent(&panel,&enter);
        QDropEvent drop(QPointF(5,5),Qt::CopyAction,&mime,Qt::LeftButton,Qt::NoModifier);QApplication::sendEvent(&panel,&drop);
        QCOMPARE(player.current,QUrl::fromLocalFile(media));
        QPushButton *run=nullptr;
        for(auto *button:panel.findChildren<QPushButton *>())if(button->text()=="Transcribe file")run=button;
        QVERIFY(run);QVERIFY(run->isEnabled());run->click();
        QTRY_VERIFY_WITH_TIMEOUT(!run->isEnabled(),1000);player.stop();
        QTest::qWait(400);QCOMPARE(player.state,MediaWidget::Idle);QVERIFY(run->isEnabled());
        QVERIFY(!QFile::exists(dir.filePath("drop.srt")));
    }
    void audioCaptionStripStaysOpenWhileServiceIsOn() {
        QTemporaryDir dir;QFile file(dir.filePath("stay.wav"));QVERIFY(file.open(QIODevice::WriteOnly));file.write("fixture");file.close();
        MediaWidget player;TihuluMediaPanel panel(&player);player.show();panel.show();
        auto *source=panel.findChild<QComboBox *>("captionInputLanguage");QTRY_VERIFY_WITH_TIMEOUT(source->count()>1,3000);
        player.play(QUrl::fromLocalFile(file.fileName()));player.state=MediaWidget::Playing;
        QLabel *strip=player.findChild<QLabel *>("tihuluFileCaptionStrip");QVERIFY(strip);
        QPushButton *live=nullptr;for(auto *button:panel.findChildren<QPushButton *>())if(button->text()=="Live captions")live=button;
        QVERIFY(live);live->click();
        // Wait for the caption job to actually start, not only the click.
        QPushButton *cancel=nullptr;for(auto *button:panel.findChildren<QPushButton *>())if(button->text()=="Stop AI")cancel=button;
        QVERIFY(cancel);QTRY_VERIFY_WITH_TIMEOUT(cancel->isEnabled(),3000);
        QTRY_COMPARE_WITH_TIMEOUT(strip->text(),QString("Live captions \u00b7 listening on the current playback position"),3000);
        QVERIFY(!strip->isHidden());
        // Between phrases and while paused, the strip must NOT close and reopen.
        player.state=MediaWidget::Paused;QTest::qWait(250);
        QVERIFY(!strip->isHidden());
        QCOMPARE(strip->text(),QString("Live captions \u00b7 listening on the current playback position"));
        player.state=MediaWidget::Playing;QTest::qWait(250);QVERIFY(!strip->isHidden());
        // Only an explicit stop releases the service and closes the strip.
        player.stop();QTest::qWait(300);QVERIFY(strip->isHidden());
    }
    void liveSeekDiscardsOldReplyAndNeverMovesPlayer() {
        QTemporaryDir dir;QFile file(dir.filePath("seek.wav"));QVERIFY(file.open(QIODevice::WriteOnly));file.write("fixture");file.close();
        MediaWidget player;TihuluMediaPanel panel(&player);player.show();
        auto *source=panel.findChild<QComboBox *>("captionInputLanguage");
        QTRY_VERIFY_WITH_TIMEOUT(source->count()>1,3000);player.play(QUrl::fromLocalFile(file.fileName()));
        QPushButton *live=nullptr;for(auto *button:panel.findChildren<QPushButton *>())if(button->text()=="Live captions")live=button;
        QVERIFY(live);live->click();QTest::qWait(250);player.position=20000;
        QTest::qWait(1600);QCOMPARE(player.position,20000);
        auto *strip=player.findChild<QLabel *>("tihuluFileCaptionStrip");QVERIFY(strip);
        QTRY_COMPARE_WITH_TIMEOUT(strip->text(),QString("position 20"),3000);
        player.stop();QTest::qWait(250);QCOMPARE(player.state,MediaWidget::Idle);
    }
private:
    static bool running(int pid) {
        QFile status(QString("/proc/%1/stat").arg(pid));if(!status.open(QIODevice::ReadOnly))return false;
        const auto data=status.readAll();const int end=data.lastIndexOf(')');return end<0 || data.mid(end+2,1)!="Z";
    }
};
QTEST_MAIN(OwnerRegression)
#include "native.moc"
