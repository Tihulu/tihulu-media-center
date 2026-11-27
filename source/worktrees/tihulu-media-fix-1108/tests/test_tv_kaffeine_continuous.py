"""No-silent-drop caption queue, boundary overlap and multilingual display tests."""
import time
import unittest
from unittest.mock import patch
from kaffeine_next.continuous_captions import (
    CapturedClip, BufferedCaptionQueue, prepended_overlap, remove_repeated_prefix)
from kaffeine_next.caption_timing import CaptionConfig
from tv_center.captions import decode_segment, choose_audio_stream


class ContinuousCaptionsTests(unittest.TestCase):
    def test_queued_chunks_keep_order_while_whisper_is_busy(self):
        q=BufferedCaptionQueue(maximum_bytes=8000,max_clips=3)
        for n in range(3):
            self.assertTrue(q.offer(CapturedClip(
                b"\x47"+b"\x00"*187,{"revision":1},n*6,(n+1)*6)))
        self.assertEqual(q.snapshot()["queued_clips"],3)
        self.assertEqual([q.get(0).started for _ in range(3)],[0,6,12])
        self.assertEqual(q.snapshot()["missed_seconds"],0)

    def test_queue_overflow_is_measured_never_silent(self):
        q=BufferedCaptionQueue(maximum_bytes=188,max_clips=1)
        clip=CapturedClip(b"\x47"+b"\x00"*187,{},0,6)
        self.assertTrue(q.offer(clip))
        self.assertFalse(q.offer(CapturedClip(clip.data,{},6,12)))
        self.assertEqual(q.snapshot()["overflows"],1)
        self.assertEqual(q.snapshot()["missed_seconds"],6)
        q.close()
        self.assertIsNone(q.get(0))
        self.assertFalse(q.offer(clip))

    def test_boundary_overlap_is_transport_packet_aligned(self):
        first=(b"\x47"+b"\x01"*187)*200
        second=(b"\x47"+b"\x02"*187)*160
        merged=prepended_overlap(second,first,preceding_duration=4,overlap_seconds=1)
        self.assertEqual(merged,first[-50*188:]+second)
        self.assertEqual(len(merged)%188,0)

    def test_word_overlap_removed_before_translation(self):
        self.assertEqual(remove_repeated_prefix("Guten Tag, wie geht es Ihnen",
            "wie geht es Ihnen heute?"),"heute?")
        self.assertEqual(remove_repeated_prefix("Es ist kalt","Es ist kalt"),
                         "")
        self.assertEqual(remove_repeated_prefix("Ich bin hier",
            "Ich möchte gehen"),"Ich möchte gehen")

    def test_decoder_deduplicates_before_calling_translator(self):
        packet=(b"\x47"+b"\x00"*187)
        with patch("tv_center.captions.asr_from_clip",
                   return_value="Guten Tag und herzlich willkommen") as asr:
            with patch("tv_center.captions.translate",
                       return_value=("Hoş geldiniz",None)) as tr:
                out=decode_segment(packet,mode="asr",source="de",target="tr",
                    model="/models",previous_text="Hallo guten Tag und herzlich")
        self.assertEqual(out["original"],"willkommen")
        tr.assert_called_once_with("willkommen","de","tr")

    def test_audio_prefers_matching_regular_track(self):
        streams=[
            {"codec_type":"video","index":0},
            {"codec_type":"audio","index":1,"tags":{"language":"eng"}},
            {"codec_type":"audio","index":2,"tags":{"language":"deu","title":"Audio description"}},
            {"codec_type":"audio","index":3,"tags":{"language":"deu","title":"Stereo"}},
        ]
        self.assertEqual(choose_audio_stream(streams,"de"),3)
        self.assertEqual(choose_audio_stream(streams,"en"),1)

    def test_original_only_two_or_three_languages_and_text_transparency(self):
        config=CaptionConfig(show_original=True,show_translation=False,
                             target_languages=(),target="de",
                             text_opacity=30,opacity=0).validate()
        self.assertEqual(config.render({"original":"Hallo",
                                        "translations":{"tr":"Merhaba"}}),"Hallo")
        triple=CaptionConfig(target_languages=("tr","en"),target="tr")
        self.assertEqual(triple.render({
            "original":"Guten Tag",
            "translations":{"tr":"İyi günler","en":"Good day"}
        }),"[DE] Guten Tag\n[TR] İyi günler\n[EN] Good day")
        only_translation=CaptionConfig(target_languages=("tr",),
            show_original=False,target="tr")
        self.assertEqual(only_translation.render({
            "original":"Guten Tag","translations":{"tr":"İyi günler"}}),"[TR] İyi günler")
        self.assertEqual(CaptionConfig(playback_delay_ms=20000).validate().playback_delay_ms,20000)
        with self.assertRaises(ValueError):
            CaptionConfig(playback_delay_ms=21000).validate()
        with self.assertRaises(ValueError):
            CaptionConfig(text_opacity=101).validate()
