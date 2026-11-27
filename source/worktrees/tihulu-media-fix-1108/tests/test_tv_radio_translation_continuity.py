"""DAB+ live-radio translation must not silently disappear under music.

End-to-end mock feeds REAL-length PCM windows through the normal radio
translation control flow. It never talks to a network, tuner, GPU or model.
"""
from __future__ import annotations
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tv_center.radio_language import RadioLanguageLock
from tv_center.radio_translation_status import translation_state
from tv_center.lyrics_sync import LyricCue
from tv_center.media_ai import CHUNK_SAMPLES
from tv_center.radio_ai import decode_radio_live


class RadioLanguageContinuityTests(unittest.TestCase):
    def test_strong_initial_english_lock_survives_background_music(self):
        state = RadioLanguageLock()
        first=state.observe("en", 0.96)
        self.assertEqual(first.language, "en")
        self.assertFalse(first.pending)
        weak=state.observe(None, 0.13)
        self.assertEqual(weak.language, "en")
        self.assertFalse(weak.pending)
        self.assertEqual(weak.reason, "retained_confirmed_language_during_music")
        contradiction=state.observe("de", 0.89)
        self.assertEqual(contradiction.language, "en")
        self.assertFalse(contradiction.pending)
        self.assertEqual(state.observe("de", 0.91).language, "de")

    def test_initial_weak_or_unverified_source_does_not_translate(self):
        state=RadioLanguageLock()
        self.assertTrue(state.observe("en", 0.45).pending)
        self.assertTrue(state.observe("en", 0.83).pending)
        self.assertEqual(state.observe("en", 0.84).language, "en")
        self.assertIsNone(RadioLanguageLock().observe(None, 0.0).language)

    def test_invalid_confidence_does_not_invent_language(self):
        s=RadioLanguageLock()
        for candidate,confidence in (("auto",.99),("und",.97),
                                      ("en",float("nan")),("English",.99)):
            self.assertTrue(s.observe(candidate,confidence).pending)
        self.assertIsNone(s.language)

    def test_missing_translation_is_explained_without_fake_output(self):
        base=dict(original="Guten Morgen",source_language="en",
                  requested_targets=("de","tr"),translated={},
                  failures={},translator_enabled=True,language_pending=True)
        self.assertEqual(translation_state(**base)["state"],"language_pending")
        off=translation_state(**{**base,"language_pending":False,
                                  "translator_enabled":False})
        self.assertEqual(off["state"], "translator_disabled")
        error=translation_state(**{**base,"language_pending":False,
                     "failures":{"tr":"missing Argos pair","de":"missing model"}})
        self.assertEqual(error["state"],"failed")
        self.assertIn("missing Argos pair",error["message"])
        result=translation_state(**{**base,"language_pending":False,
                              "translated":{"tr":"Günaydın"}})
        self.assertEqual(result["state"],"partial")
        self.assertEqual(result["missing_targets"],["de"])

    def test_radio_engine_keeps_translating_when_intermediate_music_low_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio=[b"\x01\x00" * (CHUNK_SAMPLES*6),
                   b"\x01\x00" * (CHUNK_SAMPLES*5),
                   b"\x01\x00" * (CHUNK_SAMPLES*5)]
            fp=Mock()
            fp.stdout.read.side_effect=audio
            fp.stdout.close=Mock()
            ai=Mock()
            ai.values={"asr_enabled":True,"translation_enabled":True}
            output=Path(tmp)/"tihulu-radio-captions-314.json"
            sent=[]
            observed=iter([("en",.96), (None,.15), ("en",.93)])
            def chunk(pcm,*,position,lang,profile,backend,music,detection):
                lang_code,confidence=next(observed)
                detection["language"]=lang_code
                detection["confidence"]=confidence
                return [LyricCue(position+1.2,position+4.2,
                                 "You are right about this", "Whisper/CUDA", "en")]
            def translated(text,source,target):
                sent.append((source,target))
                return ("Haklısın",None)
            with (patch.dict(os.environ, {"XDG_RUNTIME_DIR":tmp}),
                  patch("tv_center.radio_ai.AISettings",return_value=ai),
                  patch("tv_center.radio_ai._choose_model",return_value=({}, "gpu")),
                  patch("tv_center.radio_ai.subprocess.Popen",return_value=fp),
                  patch("tv_center.radio_ai.signal.signal"),
                  patch("tv_center.radio_ai._near_silent_pcm",return_value=False),
                  patch("tv_center.radio_ai._chunk_cues",side_effect=chunk),
                  patch("tv_center.captions.translate",side_effect=translated),
                  patch("tv_center.radio_ai.write_runtime_json",
                        side_effect=lambda path,payload: (
                            sent.append(("status",payload["translation_state"],
                                         payload["language_source"])),
                            Path(path).write_text(json.dumps(payload))))):
                result=decode_radio_live(port=8765,sid="0123",source="auto",
                    targets=("tr",),output=str(output),music=True,max_chunks=3)
            self.assertEqual(result["chunks"],3)
            self.assertEqual(len([x for x in sent if x==("en","tr")]),3)
            last=json.loads(output.read_text())
            self.assertEqual(last["source_language"],"en")
            self.assertEqual(last["translation_state"],"translated")
            self.assertEqual(last["translations"]["tr"],"Haklısın")
            self.assertIn(("status","translated","retained_confirmed_language_during_music"),
                          sent)

    def test_native_radio_shows_failure_reason_separately_from_speech(self):
        source=(Path(__file__).resolve().parents[1] /
                "kaffeine_next/native_radio_tab.h").read_text()
        self.assertIn("radioTranslationBanner_=new QLabel(page)",source)
        self.assertIn('QLatin1String("translation_note")',source)
        self.assertIn('QLatin1String("translation_state")',source)
        self.assertIn('radioTranslationBanner_->setText(',source)
        self.assertIn('radioTranslationBanner_->setVisible(false)',source)
        self.assertIn('caption+=QLatin1String("\\n[")',source)


if __name__=="__main__":
    unittest.main()
