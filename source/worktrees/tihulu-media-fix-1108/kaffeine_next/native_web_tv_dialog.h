/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Internet TV channel catalogue. Never opens a DVB frontend, never plays
 * a fake station, and downloads a playlist only on the user's explicit click.
 */
#ifndef TIHULU_NATIVE_WEB_TV_DIALOG_H
#define TIHULU_NATIVE_WEB_TV_DIALOG_H
#include "mediawidget.h"
#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QHBoxLayout>
#include <QGridLayout>
#include <QHeaderView>
#include <QJsonDocument>
#include <QLabel>
#include <QLocale>
#include <QTimer>
#include <QLineEdit>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QPushButton>
#include <QRegularExpression>
#include <QSettings>
#include <QSet>
#include <QTreeWidget>
#include <QUrl>
#include <QVBoxLayout>
#include <functional>

class TihuluWebTvDialog final : public QDialog {
public:
 explicit TihuluWebTvDialog(MediaWidget *player,
                            std::function<void()> showPlayback,
                            QWidget *parent = nullptr)
   : QDialog(parent), player_(player), showPlayback_(showPlayback), network_(this) {
   setAttribute(Qt::WA_DeleteOnClose);
   setWindowTitle(tr("Internet TV · online station directory"));
   resize(900, 620);
   auto *layout = new QVBoxLayout(this);
   auto *intro = new QLabel(tr("Search real public internet TV streams without a DVB tuner. "
      "The free directory is downloaded only on request; streams may be offline or geo-restricted."),this);
   intro->setWordWrap(true);
   layout->addWidget(intro);
   auto *filter = new QGridLayout();
   country_ = new QComboBox(this);
   for (const QString &code : QStringList({"de","tr","gb","fr","it","us","ww"}))
      country_->addItem(code.toUpper(),code);
   country_->setEditable(true);
   const QString systemCountry = QLocale::system().name().section(QLatin1Char('_'),1,1).toLower();
   if (country_->findData(systemCountry) >= 0)
      country_->setCurrentIndex(country_->findData(systemCountry));
   load_ = new QPushButton(tr("Discover TV channels"),this);
   search_ = new QLineEdit(this);
   search_->setPlaceholderText(tr("Filter discovered channels by name..."));
   filter->addWidget(new QLabel(tr("Country:"),this),0,0);
   filter->addWidget(country_,0,1);
   filter->addWidget(load_,0,2);
   filter->addWidget(search_,1,0,1,3);
   filter->setColumnStretch(1,1);
   layout->addLayout(filter);
   channels_ = new QTreeWidget(this);
   channels_->setHeaderLabels({tr("★"),tr("Channel"),tr("Stream URL")});
   channels_->setRootIsDecorated(false);
   channels_->setAlternatingRowColors(true);
   channels_->header()->setSectionResizeMode(0,QHeaderView::ResizeToContents);
   channels_->header()->setSectionResizeMode(1,QHeaderView::Stretch);
   channels_->header()->setSectionResizeMode(2,QHeaderView::Stretch);
   layout->addWidget(channels_,1);
   auto *row = new QGridLayout();
   direct_ = new QLineEdit(this);
   direct_->setPlaceholderText(tr("Or paste an HTTP(S) TV / HLS / MPEG-TS stream URL"));
   auto *play = new QPushButton(tr("Play selected / URL"),this);
   auto *close = new QPushButton(tr("Close"),this);
   row->addWidget(direct_,0,0,1,2);
   row->addWidget(play,1,0);
   row->addWidget(close,1,1);
   row->setColumnStretch(0,1);
   layout->addLayout(row);
   status_ = new QLabel(tr("Select a country, then choose Discover. No RF device needed."),this);
   status_->setWordWrap(true);
   layout->addWidget(status_);
   QSettings settings(QLatin1String("TIHULU"),QLatin1String("WebTV"));
   for (const QString &url: settings.value(QLatin1String("favorites")).toStringList())
      favorites_.insert(url);
   connect(close,&QPushButton::clicked,this,&QDialog::close);
   connect(load_,&QPushButton::clicked,this,[this](){ discover(); });
   connect(search_,&QLineEdit::textChanged,this,[this](){ filterList(); });
   connect(play,&QPushButton::clicked,this,[this](){ playUrl(direct_->text()); });
   connect(direct_,&QLineEdit::returnPressed,this,[this](){ playUrl(direct_->text()); });
   connect(channels_,&QTreeWidget::itemClicked,this,
      [this](QTreeWidgetItem *item,int column) {
         if (!item) return;
         if (column==0) toggleFavorite(item);
         else direct_->setText(item->data(1,Qt::UserRole).toString());
      });
   connect(channels_,&QTreeWidget::itemDoubleClicked,this,
      [this](QTreeWidgetItem *item,int column){
         if (column!=0 && item) playUrl(item->data(1,Qt::UserRole).toString());
      });
   // Automatically search the user's system-locale country on opening;
   // no external tuner, token or paid provider is necessary.
   QTimer::singleShot(0,this,[this](){discover();});
 }
private:
 void filterList(){
   const QString term=search_->text().trimmed();
   for(int i=0;i<channels_->topLevelItemCount();++i){
      auto *item=channels_->topLevelItem(i);
      item->setHidden(!term.isEmpty() && !item->text(1).contains(term,Qt::CaseInsensitive));
   }
 }
 void toggleFavorite(QTreeWidgetItem *item){
   const QString url=item->data(1,Qt::UserRole).toString();
   if (url.isEmpty()) return;
   if(favorites_.contains(url)) favorites_.remove(url);
   else favorites_.insert(url);
   item->setText(0,favorites_.contains(url)?QStringLiteral("★"):QStringLiteral("☆"));
   QSettings settings(QLatin1String("TIHULU"),QLatin1String("WebTV"));
   settings.setValue(QLatin1String("favorites"),QStringList(favorites_.values()));
 }
 void discover(){
   QString region=country_->currentData().toString();
   if (country_->isEditable()) region=country_->currentText().trimmed().toLower();
   if (!QRegularExpression(QLatin1String("^[a-z]{2}$")).match(region).hasMatch()){
      status_->setText(tr("Enter a valid two-letter country code (or WW for worldwide)."));
      return;
   }
   const QString path=(region==QLatin1String("ww"))
      ? QLatin1String("/iptv/index.m3u")
      : QLatin1String("/iptv/countries/")+region+QLatin1String(".m3u");
   QNetworkRequest request(QUrl(QLatin1String("https://iptv-org.github.io")+path));
   request.setRawHeader("User-Agent","TIHULU-Media-Center/0.2");
   request.setTransferTimeout(20000);
   load_->setEnabled(false);
   status_->setText(tr("Fetching a public playlist..."));
   QNetworkReply *reply=network_.get(request);
   connect(reply,&QNetworkReply::finished,this,[this,reply](){
      load_->setEnabled(true);
      const QByteArray data=reply->readAll();
      const bool ok=reply->error()==QNetworkReply::NoError && data.size()<=12*1024*1024;
      const QString error=reply->errorString();
      reply->deleteLater();
      if(!ok){ status_->setText(tr("Catalog failed: %1").arg(error)); return; }
      if(!data.startsWith("#EXTM3U")){
         status_->setText(tr("Unrecognized M3U playlist; nothing imported."));return;
      }
      channels_->clear();
      QString pendingName;
      int count=0;
      const QStringList rows=QString::fromUtf8(data).split(QLatin1Char('\n'));
      for(const QString &raw:rows){
         const QString line=raw.trimmed();
         if(line.startsWith(QLatin1String("#EXTINF:"))){
            pendingName=line.section(QLatin1Char(','),-1).trimmed().left(130);
            continue;
         }
         if(line.startsWith(QLatin1Char('#')) || line.isEmpty()) continue;
         const QUrl url(line);
         if(url.isValid() && !url.host().isEmpty() &&
            (url.scheme()==QLatin1String("http") || url.scheme()==QLatin1String("https"))) {
            auto *item=new QTreeWidgetItem(channels_);
            item->setText(0,favorites_.contains(line)?QStringLiteral("★"):QStringLiteral("☆"));
            item->setText(1,pendingName.isEmpty()?url.host():pendingName);
            item->setText(2,url.host());
            item->setData(1,Qt::UserRole,line);
            ++count;
         }
         pendingName.clear();
         if(count>=4000) break; // avoid unbounded widgets on huge catalogues
      }
      filterList();
      status_->setText(tr("%1 listed streams. These are directory entries, not verified live signals.")
          .arg(count));
   });
 }
 void playUrl(const QString &address){
   const QUrl url=QUrl::fromUserInput(address.trimmed());
   if(!url.isValid() || url.host().isEmpty() ||
      (url.scheme()!=QLatin1String("http") && url.scheme()!=QLatin1String("https"))){
      status_->setText(tr("Choose a channel or paste a valid HTTP(S) URL."));
      return;
   }
   // Start video in the application-owned libVLC player, no external browser.
   showPlayback_();
   player_->play(url);
   close();
 }
 MediaWidget *player_;
 std::function<void()> showPlayback_;
 QNetworkAccessManager network_;
 QComboBox *country_=nullptr;
 QLineEdit *search_=nullptr,*direct_=nullptr;
 QTreeWidget *channels_=nullptr;
 QPushButton *load_=nullptr;
 QLabel *status_=nullptr;
 QSet<QString> favorites_;
};
#endif // TIHULU_NATIVE_WEB_TV_DIALOG_H
