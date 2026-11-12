import tempfile
from pathlib import Path
import unittest
from textcenter.core import Store
from textcenter.transcripts import TranscriptStore,TranslatorUnavailable,translate_offline


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=TranscriptStore(Store(Path(self.tmp.name)/"text.sqlite"))
        self.session="a"*32
        self.cid=self.db.add(session=self.session,medium="fm",source_id="rtl_fm:98600000",
            language="de",text="Guten Morgen",backend="cpu",start=0,end=8.0)

    def tearDown(self):self.tmp.cleanup()

    def test_transcript_and_translation_persist_offline(self):
        rows=self.db.list(self.session)
        self.assertEqual(rows[0]["original_text"],"Guten Morgen")
        result=self.db.translate_later(self.cid,"tr",
            translator=lambda text,s,t:"Günaydın")
        self.assertEqual(result["translated_text"],"Günaydın")
        self.assertEqual(self.db.list(self.session)[0]["original_text"],"Guten Morgen")
        srt=self.db.export(self.session)
        self.assertIn("00:00:00,000 --> 00:00:08,000",srt)
        self.assertIn("Guten Morgen",srt)
        self.assertNotIn("[UNTRANSLATED",self.db.export(self.session,translated=True))
        vtt=self.db.export(self.session,fmt="vtt",translated=True)
        self.assertIn("WEBVTT",vtt)
        self.assertIn("Günaydın",vtt)
        self.assertEqual(TranscriptStore(self.db.store).list(self.session)[0]["translated_text"],"Günaydın")

    def test_explicit_gpu_npu_translation_rejects_unsupported_runtimes(self):
        with self.assertRaises(ValueError):
            translate_offline("Hello","en","de",backend="invalid")
        with self.assertRaises(TranslatorUnavailable):
            translate_offline("Hello","en","tr",backend="npu")

    def test_unavailable_language_never_fabricated(self):
        with self.assertRaises(ValueError):
            self.db.translate_later(self.cid,"fr")
        with self.assertRaises(KeyError):
            self.db.translate_later("unknown","en")
        with self.assertRaises(ValueError):
            self.db.export(self.session,fmt="html")
        self.assertEqual(translate_offline("Hello","en","en"),"Hello")


if __name__=="__main__":
    unittest.main()
