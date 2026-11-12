"""DVB PAT/PMT Teletext subtitle selection and real PID/page routing."""
import unittest
from unittest.mock import patch

from kaffeine_next.subtitle_tracks import TeletextSubtitleDiscovery, mpeg_crc32
from tv_center.captions import (_sub_stream, ass_text, decode_segment,
                                teletext_from_clip, choose_audio_stream)


def _section(table_id, body):
    length=len(body)+4
    pre=bytes([table_id, 0xB0 | (length >> 8), length & 255])+body
    return pre+mpeg_crc32(pre).to_bytes(4,"big")


def _ts(pid, data, cc=0):
    # One PSI section per 188-byte MPEG-TS packet, with a pointer_field=0.
    assert len(data)<=183
    return (bytes([0x47,0x40 | (pid>>8),pid&255,0x10 | cc,0])+
            data+bytes([0xff])*(183-len(data)))


def _pat(programs):
    # PAT header: tsid, version/current, section number, last section
    body=bytes([0,1,0xC1,0,0])
    for service,pid in programs:
        body+=bytes([service>>8,service&255,0xE0 | (pid>>8),pid&255])
    return _ts(0,_section(0,body))


def _ttx_descriptor(iso,page,hearing=False):
    magazine=page//100
    rawpage=page%100
    return (iso.encode("ascii") +
            bytes([(5 if hearing else 2)<<3 | (magazine & 7),
                   (rawpage//10)<<4 | rawpage%10]))


def _pmt(service, streams):
    body=bytes([service>>8, service&255,0xC1,0,0,
                0xE1,0x01,0xF0,0])
    for pid,language,page,hearing in streams:
        info=_ttx_descriptor(language,page,hearing)
        desc=bytes([0x56,len(info)])+info
        body+=bytes([0x06,0xE0 | (pid>>8),pid&255,
                     0xF0,len(desc)])+desc
    return _ts(0x100,_section(2,body))


def _pmt_audio(service, streams):
    body=bytes([service>>8, service&255, 0xC1, 0, 0, 0xE1, 1, 0xF0, 0])
    for stream_type, pid, language, audio_type in streams:
        desc=(bytes([0x0a, 4])+language.encode("ascii")+
              bytes([audio_type]))
        body+=bytes([stream_type, 0xE0 | (pid>>8), pid&255,
                     0xF0, len(desc)])+desc
    return _ts(0x100,_section(2,body))


class RealDVBSubtitleTrackTests(unittest.TestCase):
    def test_real_broadcaster_german_french_teletext_subtitles(self):
        # Exact DVB descriptor 0x56, teletext types 2 & 5; Kaffeine-style
        # German and French choices are real signalled tracks, not guessed.
        meter=TeletextSubtitleDiscovery()
        self.assertTrue(meter.offer(_pat([(42,0x100)]),preferred_service_id=42))
        self.assertTrue(meter.offer(_pmt(42,[
            (0x120,"deu",250,False),(0x121,"fre",366,True)]),
            preferred_service_id=42))
        tracks=meter.snapshot()
        self.assertEqual(len(tracks),2)
        self.assertEqual([(t["pid"],t["page"],t["source_hint"]) for t in tracks],
                         [(0x120,250,"de"),(0x121,366,"fr")])
        self.assertIn("hearing impaired",tracks[1]["label"])
        self.assertFalse(meter.offer(_pmt(42,[
            (0x120,"deu",250,False),(0x121,"fre",366,True)]),
            preferred_service_id=42))

    def test_real_audio_tracks_discovered_for_whisper(self):
        meter = TeletextSubtitleDiscovery()
        meter.offer(_pat([(42, 0x100)]), preferred_service_id=42)
        self.assertTrue(meter.offer(_pmt_audio(42, [
            (0x11, 0x121, "deu", 0),
            (0x11, 0x122, "deu", 3),
            (0x0f, 0x123, "eng", 0)]), preferred_service_id=42))
        tracks = meter.snapshot_audio()
        self.assertEqual([(t["pid"], t["source_hint"]) for t in tracks],
                         [(0x121, "de"), (0x122, "de"), (0x123, "en")])
        self.assertFalse(tracks[0]["visual_impaired"])
        self.assertTrue(tracks[1]["visual_impaired"])
        self.assertIn("audio description", tracks[1]["label"])
        self.assertEqual(meter.snapshot(), [])
        self.assertFalse(meter.offer(_pmt_audio(42, [
            (0x11, 0x121, "deu", 0),
            (0x11, 0x122, "deu", 3),
            (0x0f, 0x123, "eng", 0)]), preferred_service_id=42))

    def test_whisper_exact_audio_pid_does_not_fallback(self):
        streams = [
            {"codec_type":"audio", "index":3, "id":"0x121",
             "tags":{"language":"deu"}},
            {"codec_type":"audio", "index":5, "id":"0x123",
             "tags":{"language":"eng"}},
        ]
        self.assertEqual(choose_audio_stream(streams, "de", 0x123), 5)
        self.assertIsNone(choose_audio_stream(streams, "de", 0x333))
        self.assertEqual(choose_audio_stream(streams, "de"), 3)
        with self.assertRaises(ValueError):
            choose_audio_stream(streams, "de", -1)
        from kaffeine_next.caption_timing import CaptionConfig
        self.assertEqual(CaptionConfig(audio_pid=0x123).validate().options()["audio_pid"],0x123)
        with self.assertRaises(ValueError):
            CaptionConfig(audio_pid=8191).validate()

    def test_selected_audio_pid_is_forwarded_to_asr(self):
        with patch("tv_center.captions.asr_from_clip",
                   return_value="German speech") as asr:
            result=decode_segment(bytes([0x47])+bytes(187), mode="asr",
                                  source="de", target="de", targets=(),
                                  audio_pid=0x121)
        self.assertEqual(result["original"], "German speech")
        self.assertEqual(asr.call_args.kwargs["audio_pid"], 0x121)

    def test_teletext_and_whisper_fallback_translate_from_their_actual_languages(self):
        sample_ts = bytes([0x47]) + bytes(187)
        with patch("tv_center.captions.teletext_from_clip", return_value="Bonjour!"):
            with patch("tv_center.captions.translate",
                       return_value=("Merhaba", None)) as translate:
                with patch("tv_center.captions.asr_from_clip") as asr:
                    tele = decode_segment(sample_ts, mode="auto",
                        page=366, source="fr", target="tr", targets=("tr",),
                        teletext_pid=0x121, audio_pid=0x122,
                        audio_source="en")
        asr.assert_not_called()
        translate.assert_called_once_with("Bonjour!", "fr", "tr")
        self.assertEqual(tele["source_language"], "fr")

        with patch("tv_center.captions.teletext_from_clip", return_value=""):
            with patch("tv_center.captions.asr_from_clip",
                       return_value="English speech") as asr:
                with patch("tv_center.captions.translate",
                           return_value=("Türkçe", None)) as translate:
                    speech = decode_segment(sample_ts, mode="auto",
                        page=366, source="fr", target="tr", targets=("tr",),
                        teletext_pid=0x121, audio_pid=0x122,
                        audio_source="en")
        self.assertEqual(asr.call_args.args[1], "en")
        self.assertEqual(asr.call_args.kwargs["audio_pid"], 0x122)
        translate.assert_called_once_with("English speech", "en", "tr")
        self.assertEqual(speech["source_language"], "en")

    def test_multiple_pat_entries_do_not_select_another_television_service(self):
        meter=TeletextSubtitleDiscovery()
        pat=_pat([(41,0x111),(42,0x100)])
        self.assertTrue(meter.offer(pat, preferred_service_id=42))
        self.assertEqual(meter.service_id,42)
        self.assertEqual(meter.pmt_pid,0x100)
        meter.offer(_pmt(42,[(0x120,"deu",150,False)]),
                    preferred_service_id=42)
        self.assertEqual(meter.snapshot()[0]["page"],150)
        meter.offer(_pat([(78,0x114)]),preferred_service_id=78)
        self.assertEqual(meter.snapshot(),[])
        self.assertEqual(meter.service_id,78)

    def test_ignore_non_subtitle_teletext_descriptor(self):
        meter=TeletextSubtitleDiscovery()
        meter.offer(_pat([(42,0x100)]),preferred_service_id=42)
        # Type 1 is a general-purpose teletext initial page, not subtitles.
        body=bytes([0,42,0xc1,0,0,0xe1,1,0xf0,0])
        info=b"deu"+bytes([0x08 | 1,0x50])
        desc=bytes([0x56,5])+info
        body+=bytes([0x06,0xE1,0x20,0xf0,len(desc)])+desc
        meter.offer(_ts(0x100,_section(2,body)),preferred_service_id=42)
        self.assertEqual(meter.snapshot(),[])

    def test_only_requested_teletext_pid_is_used_for_ffmpeg(self):
        streams=[
            {"index":3,"codec_name":"dvb_teletext","id":"0x0120"},
            {"index":5,"codec_name":"dvb_teletext","id":"0x0121"},
        ]
        with patch("tv_center.captions._program_streams",return_value=streams):
            self.assertEqual(_sub_stream("test.ts",42,0x121),5)
            self.assertEqual(_sub_stream("test.ts",42,0x120),3)
            self.assertIsNone(_sub_stream("test.ts",42,0x133))
            with patch("tv_center.captions._run") as ff:
                ff.return_value.returncode=0
                ff.return_value.stdout=(b"[Events]\n"
                    b"Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,Bonjour\n")
                result=teletext_from_clip("test.ts",366,42,0x121)
                self.assertEqual(result,"Bonjour")
                argv=ff.call_args.args[0]
                self.assertEqual(argv[argv.index("-txt_page")+1],"366")
                self.assertEqual(argv[argv.index("-map")+1],"0:5")

    def test_selected_french_subtitles_translate_from_french(self):
        sample_ts=b"\x47"+bytes(187)
        with patch("tv_center.captions.teletext_from_clip",
                   return_value="Bonjour!") as teletext:
            with patch("tv_center.captions.translate",return_value=("Merhaba!",None)) as translate:
                with patch("tv_center.captions.asr_from_clip") as asr:
                    result=decode_segment(sample_ts,mode="teletext",page=366,
                                          source="fr",target="tr",targets=("tr",),
                                          teletext_pid=0x121,service_id=42)
        self.assertEqual(teletext.call_args.args,
                         (unittest.mock.ANY,366,42,0x121))
        translate.assert_called_once_with("Bonjour!","fr","tr")
        asr.assert_not_called()
        self.assertEqual(result["original"],"Bonjour!")
        self.assertEqual(result["translations"]["tr"],"Merhaba!")

    def test_ass_nonbreaking_space_escape_does_not_leak_to_translation(self):
        text=("Dialogue: 0,0:00:00.00,0:00:02.00,"
              "Default,,0,0,0,,(Publikum)\\hOh.\\hJa,\\hne?")
        cleaned=ass_text(text)
        self.assertEqual(cleaned,"(Publikum) Oh. Ja, ne?")
        self.assertNotIn("\\h",cleaned)

    def test_panel_has_real_broadcast_track_selector_not_fabricated_languages(self):
        from pathlib import Path
        source=Path(__file__).resolve().parent.parent.joinpath(
            "kaffeine_next","captions_overlay.py").read_text()
        self.assertIn('"teletext_tracks"',source)
        self.assertIn('subtitle_track.addItem(item["label"], item)',source)
        self.assertIn("teletext_pid=chosen_track",source)
        self.assertIn('service_id=options.get("service_id")',source)
        self.assertIn("subtitle_track.setCurrentIndex(0)",source)
