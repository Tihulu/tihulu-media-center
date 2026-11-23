#include "tihulu_media_panel.h"
#include <QApplication>
#include <QtTest>
#include <QTemporaryDir>
class Probe:public QObject{Q_OBJECT private slots:
 void construct(){QTemporaryDir d;QFile f(d.filePath("a.mkv"));QVERIFY(f.open(QIODevice::WriteOnly));f.write("x");f.close();
   MediaWidget p;TihuluMediaPanel panel(&p);p.show();panel.show();QTest::qWait(200);qWarning("constructed ok");}
 void setFile(){QTemporaryDir d;QFile f(d.filePath("a.mkv"));QVERIFY(f.open(QIODevice::WriteOnly));f.write("x");f.close();
   MediaWidget p;TihuluMediaPanel panel(&p);p.show();panel.show();QTest::qWait(200);p.play(QUrl::fromLocalFile(f.fileName()));qWarning("setFile ok");QTest::qWait(300);}
};QTEST_MAIN(Probe)
#include "probe.moc"
