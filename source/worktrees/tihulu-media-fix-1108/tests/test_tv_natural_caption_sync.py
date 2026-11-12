"""Regression: bounded native delay, readable phrases and transparent video OSD.

Pure tests; no RF hardware, network, Qt desktop, or GPU required.
"""
from __future__ import annotations

import inspect
from pathlib import Path
import unittest

from kaffeine_next.caption_timing import (
    CaptionConfig, CueQueue, cue_window, confirmed_cue_config)
from kaffeine_next.word_cues import word_groups, enqueue_word_cues
from kaffeine_next.continuous_captions import (
    estimate_overlap_seconds, prepended_overlap)
from kaffeine_next.ts_capture_integrity import CaptionPacketGuard
from kaffeine_next.patch_upstream import transform


def packet(pid, cc, content=0xAA):
    return (bytes((0x47, (pid>>8)&0x1F, pid&0xFF, 0x10|(cc&15))) +
            bytes([content])*184)


def sample():
    words=[
        {"start":.2,"end":.52,"text":"Guten"},
        {"start":.6,"end":.95,"text":"Morgen,"},
        {"start":1.0,"end":1.3,"text":"heute"},
        {"start":1.5,"end":1.82,"text":"haben"},
        {"start":1.9,"end":2.15,"text":"wir"},
        {"start":2.3,"end":2.6,"text":"Neuigkeiten"},
        {"start":2.9,"end":3.3,"text":"für"},
        {"start":3.4,"end":3.7,"text":"alle."}
    ]
    return {
        "source":"local_asr","source_language":"de",
        "original":"Guten Morgen heute haben wir Neuigkeiten für alle",
        "words":words,
        "translations":{
            "en":"Good morning today we have news for everyone",
            "tr":"Günaydın bugün herkes için güzel haberlerimiz var"}}


class NaturalSubtitleTests(unittest.TestCase):
    def test_real_word_phrases_not_rapid_fragments_or_repeat_translation(self):
        groups=word_groups(sample())
        self.assertGreaterEqual(len(groups),2)
        source=" ".join(x[2]["original"] for x in groups)
        self.assertEqual(source,"Guten Morgen, heute haben wir Neuigkeiten für alle.")
        for language in ("en","tr"):
            fragments=[g[2]["translations"].get(language,"") for g in groups]
            produced=" ".join(x for x in fragments if x)
            self.assertEqual(
                produced, sample()["translations"][language],
                "A translation word must be emitted in exactly one group")
            self.assertTrue(all(len(piece.split())<=11 for piece in fragments))

    def test_when_asr_is_late_use_whole_phrase_not_word_burst(self):
        queue=CueQueue(maximum=30)
        config=CaptionConfig(playback_delay_ms=10000)
        result=enqueue_word_cues(queue,sample(),config,100,106,118)
        self.assertIsNone(result)
        self.assertEqual(len(queue.items),0)

    def test_all_due_words_are_displayed_in_order_with_minimum_reading_time(self):
        cfg=CaptionConfig(playback_delay_ms=9000)
        queue=CueQueue(maximum=30,minimum_hold=1.7)
        original=["Hallo Welt","Das ist gut","Und weiter"]
        for index,text in enumerate(original):
            queue.add({"original":text,"source":"local_asr"},
                      cfg,100+index*.1,101+index*.1,109.5)
        first=queue.poll(110,0)
        self.assertEqual(first["result"]["original"],"Hallo Welt")
        self.assertIsNone(queue.poll(110.1,0))
        second=queue.poll(111.8,0)
        self.assertEqual(second["result"]["original"],"Das ist gut")
        third=queue.poll(113.6,0)
        self.assertEqual(third["result"]["original"],"Und weiter")
        self.assertIsNone(queue.poll(114,0))

    def test_exact_duplicate_from_overlap_not_broadcast_twice(self):
        cfg=CaptionConfig(playback_delay_ms=15000)
        q=CueQueue()
        first=q.add({"original":"Guten Morgen heute","source":"local_asr"},
                    cfg,100,106,107)
        duplicate=q.add({"original":"Guten Morgen heute","source":"local_asr"},
                        cfg,105,111,112)
        self.assertFalse(first.get("skipped_duplicate",False))
        self.assertTrue(duplicate["skipped_duplicate"])
        self.assertEqual(len(q.items),1)
        # A genuinely repeated sentence much later is not suppressed.
        later=q.add({"original":"Guten Morgen heute","source":"local_asr"},
                    cfg,125,131,132)
        self.assertFalse(later.get("skipped_duplicate",False))

    def test_native_buffer_must_confirm_new_requested_value(self):
        cfg=CaptionConfig(playback_delay_ms=15000)
        self.assertIsNone(confirmed_cue_config(cfg,None))
        self.assertIsNone(confirmed_cue_config(cfg,{
            "requested_ms":9000,"effective_ms":9000}))
        expected=confirmed_cue_config(cfg,{
            "requested_ms":15000,"effective_ms":8000})
        self.assertEqual(expected.playback_delay_ms,8000)
        self.assertAlmostEqual(
            cue_window(100,102,105,expected)["due"],108.55)
        self.assertIsNotNone(confirmed_cue_config(
            CaptionConfig(playback_delay_ms=0),None))
        self.assertIsNone(confirmed_cue_config(cfg,{
            "requested_ms":15000,"effective_ms":8000,
            "primed":False,"queue_age_ms":2500}))
        self.assertEqual(confirmed_cue_config(cfg,{
            "requested_ms":15000,"effective_ms":8000,
            "primed":True,"queue_age_ms":7950}).playback_delay_ms,8000)

    def test_native_queue_priming_status_is_distinct_from_target_delay(self):
        import tempfile
        from kaffeine_next.caption_timing import KaffeineOSD
        with tempfile.TemporaryDirectory() as root:
            ipc=KaffeineOSD(5454,root)
            cfg=CaptionConfig(playback_delay_ms=15000)
            ipc.effective.write_text("15000 15000 3500000 0 2500")
            state=ipc.read_effective_delay()
            self.assertFalse(state["primed"])
            self.assertEqual(state["queue_age_ms"],2500)
            self.assertIsNone(confirmed_cue_config(cfg,state))
            ipc.effective.write_text("15000 15000 3500000 1 14900")
            state=ipc.read_effective_delay()
            self.assertTrue(state["primed"])
            self.assertEqual(confirmed_cue_config(cfg,state).playback_delay_ms,15000)
            ipc.effective.write_text("15000 15000 3500000")
            self.assertFalse(ipc.read_effective_delay()["primed"])
            ipc.close()

    def test_source_overlap_uses_actual_packet_count_not_fixed_one_second(self):
        previous=bytes(6*1024*1024)
        current=b"B"*1880
        seconds=estimate_overlap_seconds(previous,2.0,1.0)
        self.assertAlmostEqual(seconds, 1/3,delta=0.005)
        recovered=prepended_overlap(current,previous,2.0,1.0)
        self.assertEqual(len(recovered)%188,len(current)%188)
        self.assertLess(len(recovered),len(current)+1024*1024+188)

    def test_integrity_guard_deduplicates_and_flags_audio_damage(self):
        guard=CaptionPacketGuard()
        a=packet(0x110,0,0x32)
        b=packet(0x110,2,0x33)
        filtered,quality=guard.filter(a+a+b,audio_pid=0x110)
        self.assertEqual(filtered,a+b)
        self.assertEqual(quality["duplicates"],1)
        self.assertEqual(quality["critical_gaps"],1)
        # Faulty TEI packets cannot be passed to FFmpeg as real speech.
        damaged=bytearray(packet(0x110,3))
        damaged[1]|=0x80
        clean,damage=guard.filter(bytes(damaged),audio_pid=0x110)
        self.assertEqual(clean,b"")
        self.assertEqual(damage["invalid"],1)
        guard.reset()
        _,clean_state=guard.filter(packet(0x110,4),audio_pid=0x110)
        self.assertEqual(clean_state["critical_gaps"],0)

    def test_native_caption_background_zero_is_not_an_opaque_widget(self):
        patch=inspect.getsource(transform)
        self.assertIn("WA_TranslucentBackground",patch)
        self.assertIn("WA_NoSystemBackground",patch)
        self.assertIn("setAutoFillBackground(false)",patch)
        self.assertIn("if (tihuluCaptionOpacity > 0)",patch)
        self.assertIn("painter.fillRect(QWidget::rect(), Qt::transparent)",patch)
        overlay=(Path(__file__).resolve().parent.parent /
                 "kaffeine_next"/"captions_overlay.py").read_text()
        self.assertIn("KaffeineCaptionAppearance",overlay)
        self.assertIn('appearance_store.setValue("background_opacity"',overlay)
        self.assertIn("No background · white text visible",overlay)
        self.assertIn("last_sync_audit_at",overlay)
        self.assertIn("confirmed_cue_config(applied, native_state)",overlay)


if __name__=="__main__":
    unittest.main()
