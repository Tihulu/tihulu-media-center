"""Unified recording source and output contracts.

The native Kaffeine build checks real C++ compilation. This suite tests that
the centralized recorder is wired to all sources without grabbing a second RF
device, and never advertises DRM capture as functional.
"""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]/"kaffeine_next"


class SharedRecordingSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recorder=(ROOT/"native_unified_recorder.h").read_text()
        cls.patch=(ROOT/"patch_upstream.py").read_text()
        cls.radio=(ROOT/"native_radio_tab.h").read_text()

    def test_record_is_one_bottom_toolbar_widget(self):
        self.assertIn('bar->addWidget(this);',self.recorder)
        self.assertIn('● REC',self.recorder)
        self.assertIn('■ STOP REC',self.recorder)
        self.assertIn('new TihuluUnifiedRecorder(mediaWidget,dvbTab,controlBar,',
                      self.patch)

    def test_uses_native_dvb_recorder_no_second_receiver(self):
        self.assertIn('dvb_->toggleInstantRecord();',self.recorder)
        self.assertIn('hasActiveRecordings()',self.recorder)
        self.assertNotIn('requestExclusiveDevice(',self.recorder)
        self.assertNotIn('rtl_fm',self.recorder)
        self.assertNotIn('welle-cli',self.recorder)

    def test_stream_and_file_capture_are_bounded_and_no_overwrite(self):
        self.assertIn('tihulu_recordable_url',self.patch)
        self.assertIn('source_->getType()==MediaSource::Url',self.patch)
        self.assertIn('QLatin1String("-re")',self.recorder)
        self.assertIn('QLatin1String("-n")',self.recorder)
        self.assertIn('QFileInfo::exists(recordedPath_)',self.recorder)
        self.assertIn('capture_.write("q\\n");',self.recorder)
        self.assertIn('QStandardPaths::MoviesLocation',self.recorder)

    def test_recordings_are_reopenable_with_existing_subtitle_track(self):
        self.assertIn('UnifiedRecordings',self.recorder)
        self.assertIn('QStringList items=',self.recorder)
        self.assertIn('player_->play(QUrl::fromLocalFile(path)',self.recorder)
        self.assertIn('Import saved media / TV recording',self.recorder)

    def test_ai_only_after_real_recording_output(self):
        self.assertIn('const QFileInfo saved(recordedPath_)',self.recorder)
        self.assertIn('saved.size()<8192',self.recorder)
        self.assertIn('generateCaptions(saved.absoluteFilePath()',self.recorder)
        self.assertIn('QLatin1String("media-captions")',self.recorder)
        self.assertIn('QLatin1String("-c:s"),QLatin1String("srt")',self.recorder)
        self.assertIn('Protected DVD/optical-disc capture is not supported.',self.recorder)

    def test_analog_receivers_support_bounded_parallel_playback_and_capture(self):
        self.assertIn('analogSockets_.size()>=3',self.radio)
        self.assertIn('for(QTcpSocket *socket : analogStreaming_)',self.radio)
        self.assertIn('socket->bytesToWrite()<262144',self.radio)
        self.assertNotIn('if(analogClient_) analogClient_->disconnectFromHost()',self.radio)


if __name__=="__main__":
    unittest.main()
