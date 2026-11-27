// SPDX-License-Identifier: GPL-2.0-or-later
// Hardware-free player seam: exercises actual native panel and caption widgets.
#ifndef TEST_MEDIA_WIDGET_H
#define TEST_MEDIA_WIDGET_H
#include <QWidget>
#include <QVBoxLayout>
#include <QUrl>
class MediaWidget : public QWidget {
    Q_OBJECT
public:
    enum PlaybackStatus {Idle,Playing,Paused};
    MediaWidget() {new QVBoxLayout(this);}
    PlaybackStatus state=Idle;int position=0;QUrl current;
    PlaybackStatus getPlaybackStatus() const {return state;}
    int getPosition() const {return position;}
    void beginFileCaptionHold() {}
    void cancelFileCaptionHold() {}
    void stop() {emit stopRequested();state=Idle;}
    void play(const QUrl &url) {
        bool handled=false;emit fileOpenRequested(url,&handled);if(handled)return;
        current=url;emit sourceOpened(url);state=Playing;position=0;
    }
    void setSubtitle(const QUrl &url) {bool handled=false;emit subtitleOpened(url,&handled);}
signals:
    void stopRequested();
    void sourceOpened(const QUrl &url);
    void fileOpenRequested(const QUrl &url,bool *handled);
    void subtitleOpened(const QUrl &url,bool *handled);
};
#endif
