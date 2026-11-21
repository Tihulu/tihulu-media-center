# SPDX-License-Identifier: GPL-2.0-or-later
"""Local-asset discovery regressions; synthetic metadata only, no inference/RF."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'source/installed-package'
sys.path.insert(0, str(SOURCE))
from tv_center.local_assets import existing_asset, model_preferences, require_asset_write
from tv_center.ai_settings import AISettings
from tv_center.model_market import ModelLibrary


class ExistingAssets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.owner = self.base / 'owner'
        self.preview = self.base / 'preview'
        self.owner.mkdir(); self.preview.mkdir()
        self.env = patch.dict(os.environ, {'HOME': str(self.preview), 'TIHULU_ASSET_HOME': str(self.owner)})
        self.env.start(); self.addCleanup(self.env.stop)

    def owner_config(self, **extra):
        p = self.owner / '.config/tihulu-tv-center/ai-settings.json'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({'version': 1, **extra}))
        return p

    def test_reuses_file_in_place_without_creating_preview_copy(self):
        relative = '.local/share/tihulu-tv-center/models/ggml-tiny.bin'
        model = self.owner / relative
        model.parent.mkdir(parents=True); model.write_bytes(b'synthetic-not-a-model')
        self.assertEqual(existing_asset(self.preview / relative), model)
        self.assertFalse((self.preview / relative).exists())

    def test_preview_choice_takes_precedence(self):
        for home in (self.preview, self.owner):
            (home / 'chosen.bin').write_bytes(b'fixture')
        self.assertEqual(existing_asset(self.preview / 'chosen.bin'), self.preview / 'chosen.bin')

    def test_no_fallback_without_explicit_asset_home(self):
        with patch.dict(os.environ, {'TIHULU_ASSET_HOME': ''}):
            p = self.preview / 'missing'
            self.assertEqual(existing_asset(p), p)
            self.assertEqual(model_preferences(), {})

    def test_imports_only_local_model_fields_not_credentials_or_enable_switches(self):
        model = self.owner / 'selected.bin'; model.write_bytes(b'fixture')
        self.owner_config(model_path=str(model), model_dir=str(self.owner),
                          asr_enabled=True, remote_gpu_enabled=True,
                          remote_gpu_url='https://private.invalid', translation_model='deepl')
        self.assertEqual(model_preferences(), {'model_path': str(model), 'model_dir': str(self.owner)})
        settings = AISettings()
        self.assertEqual(settings.values['model_path'], str(model))
        self.assertFalse(settings.values['asr_enabled'])
        self.assertFalse(settings.values['remote_gpu_enabled'])
        self.assertEqual(settings.values['remote_gpu_url'], '')
        self.assertFalse(settings.path.exists())

    def test_malformed_and_oversize_settings_are_ignored(self):
        config = self.owner_config()
        for text in ('[]', '{bad', 'x' * 16385):
            config.write_text(text)
            self.assertEqual(model_preferences(), {})

    def test_model_inventory_is_read_only_even_for_missing_directory(self):
        root = self.base / 'missing-models'
        self.assertFalse(any(row['installed'] for row in ModelLibrary(root).installed()))
        self.assertFalse(root.exists())

    def test_shared_mutation_is_blocked_before_files_or_network(self):
        with self.assertRaises(RuntimeError): require_asset_write()
        root = self.base / 'missing-models'
        library = ModelLibrary(root)
        for operation in (lambda: library.download('tiny'), lambda: library.remove('tiny'),
                          lambda: library.refresh_online()):
            with self.assertRaises(RuntimeError): operation()
        self.assertFalse(root.exists())

    def test_existing_local_settings_win_over_owner_preferences(self):
        a = self.owner / 'a.bin'; a.write_bytes(b'a')
        b = self.preview / 'b.bin'; b.write_bytes(b'b')
        self.owner_config(model_path=str(a), translation_model='nllb')
        local = self.preview / '.config/tihulu-tv-center/ai-settings.json'
        local.parent.mkdir(parents=True); local.write_text(json.dumps({'version':1, 'model_path':str(b)}))
        self.assertEqual(AISettings().values['model_path'], str(b))
        self.assertEqual(AISettings().values['translation_model'], 'nllb')


if __name__ == '__main__':
    unittest.main()
