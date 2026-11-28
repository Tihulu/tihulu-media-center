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
    void stop() {emit stopRequested();state=Idle;}
    void play(const QUrl &url) {
        bool handled=false;emit fileOpenRequested(url,&handled);if(handled)return;
        current=url;emit sourceOpened(url);state=Playing;position=0;
    }
    MediaWidget::PlaybackStatus reportedPlaybackStatus() const {return state;}
    // The player performs the buffer-analysis freeze. This stub mirrors the
    // contract the panel relies on: enabling the hold freezes Playing
    // playback at its current position, and disabling it resumes from there.
    // MediaSource::replay() is a no-op for local files, so the position is
    // restored with an explicit seek in the real player.
    bool holdEnabled=true;
    void tihuluSetFileCaptionHold(bool enabled) {
        if(enabled) {
            if(state==Playing) {state=Paused;heldByCaptionHold=true;}
        } else if(heldByCaptionHold && state==Paused) {
            state=Playing;heldByCaptionHold=false;
        }
        holdEnabled=enabled;
    }
    bool heldByCaptionHold=false;
    QString tihuluLocalMediaPath() const {return current.toLocalFile();}
    void setSubtitle(const QUrl &url) {bool handled=false;emit subtitleOpened(url,&handled);}
    // Real Kaffeine mediawidget.h: play() replays the current media, pause is
    // the play/pause action, and setPosition() seeks in milliseconds.
    void play() {state=Playing;emit playResumed();}
    void togglePause() {if(state==Playing)state=Paused;else if(state==Paused)state=Playing;emit pauseToggled();}
    void setPosition(int ms) {position=ms;emit positionSeeked(ms);}
signals:
    void stopRequested();
    void tihuluFileCaptionsRequested();
    void sourceOpened(const QUrl &url);
    void fileOpenRequested(const QUrl &url,bool *handled);
    void subtitleOpened(const QUrl &url,bool *handled);
    void playResumed();
    void pauseToggled();
    void positionSeeked(int ms);
};
#endif
