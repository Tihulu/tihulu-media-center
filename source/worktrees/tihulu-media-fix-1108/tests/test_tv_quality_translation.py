"""No-network regressions for optional translation model selection."""
from __future__ import annotations
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tv_center.ai_settings import AISettings
from tv_center.deepl_api import save_key,read_key,remove_key,translate_deepl,ALLOWED_ENDPOINTS
from tv_center.translation_madlad import MadladMarket


class _Response:
    status=200
    def __init__(self, payload):
        self.payload=payload
    def __enter__(self):
        return self
    def __exit__(self,*_):
        return False
    def read(self,maximum):
        return json.dumps(self.payload).encode("utf-8")[:maximum]


class OptInTranslationTests(unittest.TestCase):
    def test_deepl_request_only_explicitly_selected(self):
        with mock.patch("urllib.request.urlopen",return_value=_Response(
                {"translations":[{"text":"Guten Tag"}]})) as call:
            self.assertEqual(
                translate_deepl("Good day","en","de",key="test-123456:fx"),
                "Guten Tag")
            request=call.call_args.args[0]
            self.assertEqual(request.full_url,
                             "https://api-free.deepl.com/v2/translate")
            self.assertEqual(json.loads(request.data)["text"],["Good day"])
        self.assertEqual(len(ALLOWED_ENDPOINTS),2)

    def test_deepl_does_not_accept_untrusted_destination(self):
        with mock.patch("urllib.request.urlopen") as network:
            with self.assertRaisesRegex(RuntimeError,"official HTTPS"):
                translate_deepl("Hello","en","de",key="test-123456:fx",
                                endpoint="http://localhost/v2/translate")
            network.assert_not_called()

    def test_local_secret_stays_private(self):
        with tempfile.TemporaryDirectory() as d:
            key_path=Path(d)/"deepl.key"
            save_key("example-valid-api-key:fx",key_path)
            self.assertEqual(key_path.stat().st_mode&0o077,0)
            with mock.patch.dict("os.environ",{"TIHULU_DEEPL_API_KEY":""}):
                self.assertEqual(read_key(key_path),"example-valid-api-key:fx")
            remove_key(key_path)
            self.assertFalse(key_path.exists())

    def test_model_selection_requires_explicit_choice(self):
        with tempfile.TemporaryDirectory() as d:
            settings=AISettings(Path(d)/"ai-settings.json")
            self.assertEqual(settings.values["translation_model"],"argos")
            settings.update({"translation_model":"deepl"})
            self.assertEqual(settings.values["translation_model"],"deepl")
            settings.update({"translation_model":"madlad"})
            self.assertEqual(settings.values["translation_model"],"madlad")

    def test_madlad_has_no_implicit_download(self):
        with tempfile.TemporaryDirectory() as d:
            manager=MadladMarket(root=Path(d))
            self.assertFalse(manager.status()["installed"])
            self.assertFalse(manager.model.exists())
            self.assertEqual(manager.status()["license"],"Apache-2.0")


if __name__=="__main__":
    unittest.main()
