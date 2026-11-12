"""AI starter bundle regression tests; no network, drivers or model downloads."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tv_center.ai_settings import AISettings
from tv_center.ai_provision import StarterAI, translate_ready, PAIRS
from tv_center.model_market import ModelLibrary

class AIBundleTests(unittest.TestCase):
    def test_de_tr_requires_bidirectional_translation_graph(self):
        directions = [{"source": source, "target": target} for source, target in PAIRS]
        self.assertTrue(translate_ready(directions))
        self.assertFalse(translate_ready(directions[:-1]))
        self.assertFalse(translate_ready([]))

    def test_no_network_or_runtime_install_in_status(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = AISettings(Path(root) / "ai.json")
            store = ModelLibrary(Path(root) / "models")
            class StubRuntime:
                def status(self):
                    return {"installed": False, "python": "/missing", "path": "/missing"}
            class StubWhisper:
                def ready(self):
                    return False
            starter = StarterAI(cfg, store, StubRuntime(), StubWhisper())
            with patch("tv_center.ai_provision.argos_installed_pairs", return_value=[]):
                state = starter.status()
            self.assertFalse(state["tiny_model_ready"])
            self.assertFalse(state["whisper_engine_ready"])
            self.assertFalse(state["translation_three_languages_ready"])
            self.assertFalse(state["enabled_asr"])
            self.assertFalse(state["enabled_translation"])

    def test_starter_sets_models_only_after_engines_ready(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            ai = AISettings(root / "ai.json")
            store = ModelLibrary(root / "models")
            model = store._path("tiny")
            model.write_bytes(b"test" * 1024)
            class Whisper:
                def ready(self): return True
                def install(self): raise AssertionError("engine should already exist")
            class Runtime:
                def status(self): return {"installed": True, "python": "/usr/bin/python3"}
                def install_argos(self): raise AssertionError("venv already exists")
            starter = StarterAI(ai, store, Runtime(), Whisper())
            with patch.object(starter, "_setup_argos_packs", return_value=[
                    {"source": s, "target": t} for s, t in PAIRS]):
                with patch("tv_center.ai_provision.argos_installed_pairs", return_value=[
                        {"source": s, "target": t} for s, t in PAIRS]):
                    result = starter.install()
            self.assertTrue(ai.values["asr_enabled"])
            self.assertTrue(ai.values["translation_enabled"])
            self.assertEqual(ai.values["model_path"], str(model))
            self.assertTrue(result["translation_three_languages_ready"])
            self.assertEqual(AISettings(ai.path).values["backend"], "auto")
