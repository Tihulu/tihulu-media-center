"""Fast fail-closed tests for the optional persistent Argos translation path."""
import os
import unittest
from unittest.mock import patch

from tv_center.captions import translate


class PersistentTranslatorTests(unittest.TestCase):
    def test_argos_model_worker_reused_when_system_python_lacks_argos(self):
        with patch.dict(os.environ, {"TIHULU_TRANSLATOR_MODEL":"argos"}):
            with patch("textcenter.transcripts.translate_offline",
                       side_effect=ImportError("system Argos absent")), \
                 patch("tv_center.translation_service.translate_argos",
                       return_value="Merhaba") as backend:
                result,error=translate("Hallo","de","tr")
        self.assertEqual(result,"Merhaba")
        self.assertIsNone(error)
        backend.assert_called_once_with("Hallo","de","tr")

    def test_missing_argos_pack_does_not_fabricate_translation(self):
        with patch.dict(os.environ, {"TIHULU_TRANSLATOR_MODEL":"argos"}):
            with patch("textcenter.transcripts.translate_offline",
                       side_effect=ImportError("not in system Python")), \
                 patch("tv_center.translation_service.translate_argos",
                       side_effect=RuntimeError("de->ja pack not installed")):
                translated,error=translate("Hallo","de","ja")
        self.assertIsNone(translated)
        self.assertIn("DE → JA",error)

    def test_equal_language_needs_no_translator(self):
        with patch("tv_center.translation_service.translate_argos") as backend:
            self.assertEqual(translate("Bonjour","fr","fr"),(None,None))
            backend.assert_not_called()

if __name__=="__main__":
    unittest.main()
