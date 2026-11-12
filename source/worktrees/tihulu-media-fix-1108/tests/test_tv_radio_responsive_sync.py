"""Radio UI and sync contracts: no feature removal while making tabs responsive.

These assertions supplement pinned Qt native compile; they do not claim
that a physical RTL-SDR audio-output clock is sample-accurate.
"""
import unittest
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]


class RadioModesAndSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.radio=(BASE/"kaffeine_next/native_radio_tab.h").read_text()
        cls.patch=(BASE/"kaffeine_next/patch_upstream.py").read_text()
        cls.ai=(BASE/"tv_center/radio_ai.py").read_text()

    def test_compact_modes_preserve_each_major_radio_function(self):
        for section in ('DAB+ · stations','Internet radio','Vintage FM / AM / LW',
                        'AI subtitles / lyrics','RF Lab · advanced'):
            self.assertIn('modes_->addTab(',self.radio)
            self.assertIn(section,self.radio)
        for legacy in ('scanProgress_', 'scanSNR_', 'webStations_',
                       'analogDial_', 'analogScale_', 'radioCanvas_',
                       'stations_', 'captionSource_', 'music_', 'lyrics_',
                       'rfQuality_', 'multiRf_', 'slideHistory_',
                       'stopCaption_', 'lyricsImport_', 'record_'):
            self.assertIn(legacy,self.radio)
        self.assertIn('setOrientation(width()<930?Qt::Vertical:Qt::Horizontal)',self.radio)
        self.assertIn('radioModeTab',self.radio)

    def test_global_window_and_other_player_panels_are_responsive(self):
        panel=(BASE/"kaffeine_next/native_media_panel.h").read_text()
        hardware=(BASE/"kaffeine_next/native_hardware_tab.h").read_text()
        web=(BASE/"kaffeine_next/native_web_tv_dialog.h").read_text()
        self.assertIn('Show offline AI / lyric / export options',panel)
        self.assertIn('details->setVisible(false)',panel)
        self.assertIn('detailsLayout->addLayout(tools)',panel)
        self.assertIn('detailsLayout->addLayout(actions)',panel)
        self.assertIn('QTabWidget *modes_',self.radio)
        self.assertIn('auto *tools=new QGridLayout()',hardware)
        self.assertIn('cards->addWidget(analogCard,2,0,1,2)',hardware)
        self.assertIn('auto *filter = new QGridLayout()',web)
        self.assertIn('auto *row = new QGridLayout()',web)
        self.assertIn('restoreGeometry(geometry)',self.patch)
        self.assertIn('resize(qMin(width(),screen.width())',self.patch)

    def test_song_source_is_independent_from_presenter_language(self):
        self.assertIn('lyricsSourceLanguage_->addItem(',self.radio)
        self.assertIn('QString sourceCode=lyricsSourceLanguage_->currentData().toString()',self.radio)
        self.assertIn('QString sourceCode=speechLanguage_->currentData().isValid()',self.radio)
        self.assertIn('translationStatus_->setText(',self.radio)
        self.assertIn('lastVerifiedLyricTranslations_',self.radio)

    def test_native_tuner_station_label_avoids_fake_fm_frequency(self):
        self.assertIn('showSelectedSource(item->text(1)',self.radio)
        self.assertIn('showSelectedSource(knownName',self.radio)
        self.assertIn('showSelectedSource(name,tr("DAB+ · live mux verified")',self.radio)
        self.assertIn('analogue dial remains independent of DAB/Internet',self.radio)
        self.assertIn('analogBand_->currentText()',self.radio)

    def test_cache_guard_matches_actual_vlc_media_option(self):
        self.assertIn('bufferMs_->setRange(0,60000)',self.radio)
        self.assertIn('activePlaybackCacheMs_',self.radio)
        self.assertIn('lastAudioRetuneMs_>=180000',self.radio)
        self.assertIn('QCheckBox(tr("Allow automatic radio audio restart")',self.radio)
        self.assertIn('qMax(0,remaining)+radioOffsetMs_->value()',self.radio)
        self.assertIn('radioSettings.value(QLatin1String("playbackBufferMs"),12000).toInt()',self.patch)
        self.assertIn('60000);',self.patch)
        self.assertIn('60 s',self.radio)

    def test_radio_picture_is_preserved_and_captions_use_small_banner(self):
        self.assertIn("radioCaptionBanner_=new QLabel",self.radio)
        self.assertIn("radioCaptionBanner_->setText(cue.text.left(680))",self.radio)
        self.assertNotIn("radioCanvas_->setText(cue.text.left(680))",self.radio)
        self.assertIn("applyCaptions_=new QPushButton",self.radio)
        self.assertIn('tr("Apply caption settings")',self.radio)
        self.assertIn("stopCaptioning();",self.radio)

    def test_radio_cache_uptime_never_means_audio_is_fully_buffered(self):
        self.assertIn("Stream uptime is NOT buffering progress",self.radio)
        self.assertIn("audioCacheProgress_->setRange(0,audioStartedMs_>0?0:100)",self.radio)
        self.assertIn("queue/DAC UNVERIFIED",self.radio)
        self.assertNotIn("Applied at open %1 ms · elapsed %2 ms",self.radio)
        self.assertIn("EST. caption in ~%1 ms",self.radio)

    def test_missing_lyrics_fall_back_to_real_local_whisper_audio(self):
        for field in ("listenLyrics_","listenFallbackOnMiss_",
                      "lyricsAudioFallbackActive_","beginLyricListening()",
                      "lyricsFallbackStartedAi_"):
            self.assertIn(field,self.radio)
        self.assertIn("if(listenFallbackOnMiss_->isChecked()) beginLyricListening();",
                      self.radio)
        self.assertIn("if (music_->isChecked() || lyricsAudioFallbackActive_)",self.radio)
        self.assertIn("lyricsEnabled_=false;",self.radio)
        self.assertIn("lyrics_->setEnabled(true)",self.radio)
        self.assertIn("lyricsAudioFallbackActive_=false;",self.radio)
        self.assertIn("Local Whisper on actual DAB audio",self.radio)
        self.assertIn('captionSource_->findData(QLatin1String("asr"))',self.radio)
        self.assertIn("lyricsProcess_.start",self.radio)
        self.assertIn("No radio audio uploaded",self.radio) if False else None

    def test_lyric_listening_keeps_stop_control_across_dls_metadata(self):
        self.assertIn("const bool listening=lyricsAudioFallbackActive_",self.radio)
        self.assertIn("stopLyrics_->setEnabled(listening)",self.radio)
        self.assertIn("DLS metadata updated. Continuing offline vocal",self.radio)
        self.assertIn("plainLyricsStartedAi_",self.radio)
        self.assertIn("lastCaptionVisibleMs_=now",self.radio)
        self.assertIn("now-lastCaptionVisibleMs_>=12000",self.radio)

    def test_lyric_alignment_requires_reliable_evidence_and_is_rate_limited(self):
        self.assertIn('confidence>=0.92',self.radio)
        self.assertIn('lyricOffsetConsistency_>=2',self.radio)
        self.assertIn('now-lastLyricSyncUpdateMs_>=30000',self.radio)
        self.assertIn('qBound(-250,int(delta/8),250)',self.radio)
        self.assertIn('lastVerifiedLyricTranslations_',self.radio)
        self.assertIn('lyric_translations',self.ai)
        self.assertIn('"timed_lrc" if cues else "asr_lexical"',self.ai)


if __name__=="__main__":
    unittest.main()
