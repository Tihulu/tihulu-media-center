"""Hardware-aware online AI Market regression tests, no network or CUDA needed."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tv_center.hardware_market import detect_hardware, model_fit
from tv_center.online_models import parse_remote_catalog, BASE
from tv_center.model_market import ModelLibrary
from tv_center.ai_settings import AISettings
from tv_center.translation_market import TranslationModelMarket
from tv_center.whisper_engine import WhisperRuntime


class HardwareAwareMarketTests(unittest.TestCase):
    def test_only_verified_official_whisper_ggml_files_are_searchable(self):
        good={"path":"ggml-large-v3-turbo-q5_0.bin","size":574000000,
              "lfs":{"oid":"a"*64,"size":574000000}}
        evil={"path":"ggml-untrusted-injected.bin","size":1000000,
              "lfs":{"oid":"a"*64}}
        unsigned={"path":"ggml-medium.bin","size":1500000000}
        result=parse_remote_catalog([good,evil,unsigned],"turbo")
        self.assertEqual(list(result),["large-v3-turbo-q5_0"])
        item=result["large-v3-turbo-q5_0"]
        self.assertEqual(item["sha256"],"a"*64)
        self.assertEqual(item["url"],BASE+"ggml-large-v3-turbo-q5_0.bin")
        self.assertEqual(item["filename"],"ggml-large-v3-turbo-q5_0.bin")
        self.assertNotIn("untrusted-injected",result)
        with self.assertRaises(ValueError):
            parse_remote_catalog("not a directory")

    def test_online_catalog_persists_without_network_on_restart(self):
        desc=parse_remote_catalog([
            {"path":"ggml-large-v3-q5_0.bin","size":1100000000,
             "lfs":{"oid":"9"*64}}])
        with tempfile.TemporaryDirectory() as root:
            lib=ModelLibrary(root)
            with patch("tv_center.online_models.search_official_models",
                       return_value=desc) as query:
                self.assertEqual(lib.refresh_online("large"),["large-v3-q5_0"])
            self.assertEqual(query.call_count,1)
            again=ModelLibrary(root)
            self.assertIn("large-v3-q5_0",again.catalog)
            self.assertEqual(again._path("large-v3-q5_0"),
                             Path(root)/"ggml-large-v3-q5_0.bin")
            self.assertFalse(again._path("large-v3-q5_0").is_file())
            self.assertEqual(again.installed()[-1]["installed"],False)

    def test_hardware_recognizes_rtx_5080_without_claiming_ready_backend(self):
        def commands(command,timeout=3):
            if "nvidia-smi" in command[0]:
                return "NVIDIA GeForce RTX 5080, 16303, 12.0"
            if "nvcc" in command[0]:
                return "Cuda compilation tools, release 12.8, V12.8.93"
            return ""
        def exe(name,alternatives=()):
            if name=="nvidia-smi":return "/usr/bin/nvidia-smi"
            if name=="nvcc":return "/usr/local/cuda/bin/nvcc"
            return None
        with patch("tv_center.hardware_market._command",side_effect=commands):
            with patch("tv_center.hardware_market._find_executable",side_effect=exe):
                result=detect_hardware()
        self.assertTrue(result["gpu"]["detected"])
        self.assertIn("RTX 5080",result["gpu"]["name"])
        self.assertEqual(result["gpu"]["vram_mib"],16303)
        self.assertTrue(result["gpu"]["cuda_compile_possible"])
        self.assertIn("Recommended",model_fit("large-v3-turbo-q5_0",574,result))

    def test_blackwell_without_128_does_not_claim_cuda_build_ready(self):
        with patch("tv_center.hardware_market._command",
                   side_effect=lambda argv,timeout=3:
                       "NVIDIA GeForce RTX 5080, 16000, 12.0" if
                       "nvidia-smi" in argv[0] else "Cuda compilation tools, release 12.7"):
            with patch("tv_center.hardware_market._find_executable",
                       side_effect=lambda name,alternatives=():"/usr/bin/"+name):
                result=detect_hardware()
        self.assertFalse(result["gpu"]["cuda_compile_possible"])
        self.assertIn("12.8",result["gpu"]["reason"])

    def test_versioned_cuda_13x_nvcc_found_without_path(self):
        # Pop!_OS desktop shells may not add NVIDIA's toolkit directory to
        # PATH. The CUDA compiler may exist at cuda-13.1/bin/nvcc.
        original_glob = Path.glob
        seen = []
        def fake_glob(path, pattern):
            if str(path) == "/usr/local" and pattern == "cuda-*/bin/nvcc":
                return iter([Path("/usr/local/cuda-13.1/bin/nvcc")])
            return iter([])
        def fake_executable(name, alternatives=()):
            if name == "nvidia-smi":
                return "/usr/bin/nvidia-smi"
            if name == "nvcc":
                seen.extend(alternatives)
                return "/usr/local/cuda-13.1/bin/nvcc"
            return None
        def command(argv,timeout=3):
            if "nvidia-smi" in argv[0]:
                return "NVIDIA GeForce RTX 5080, 16303, 12.0"
            return "Cuda compilation tools, release 13.1, V13.1.0"
        with patch.object(Path,"glob",fake_glob), \
             patch("tv_center.hardware_market._find_executable",side_effect=fake_executable), \
             patch("tv_center.hardware_market._command",side_effect=command):
            hardware=detect_hardware()
        self.assertIn("/usr/local/cuda-13.1/bin/nvcc",seen)
        self.assertEqual(hardware["gpu"]["cuda_compiler"],
                         "/usr/local/cuda-13.1/bin/nvcc")
        self.assertEqual(hardware["gpu"]["cuda_version"],"13.1")
        self.assertTrue(hardware["gpu"]["cuda_compile_possible"])

    def test_optional_translator_has_separate_selected_backend(self):
        with tempfile.TemporaryDirectory() as root:
            ai=AISettings(Path(root)/"ai.json")
            self.assertEqual(ai.values["translation_model"],"argos")
            ai.update({"translation_model":"nllb"})
            self.assertEqual(AISettings(Path(root)/"ai.json").values["translation_model"],
                             "nllb")
            with self.assertRaises(ValueError):
                ai.update({"translation_model":"untrusted"})

    def test_nllb_not_installed_until_user_action(self):
        with tempfile.TemporaryDirectory() as root:
            market=TranslationModelMarket(Path(root))
            self.assertFalse(market.status()["installed"])
            self.assertIn("CC-BY-NC",market.status()["license"])
            self.assertFalse(market.model.exists())

    def test_cuda_cli_dispatch_is_present_and_cpu_engine_preserved(self):
        import inspect
        from textcenter.speech import transcribe_pcm
        src=inspect.getsource(transcribe_pcm)
        self.assertIn('profile["speech"].get("gpu_engine") != "whisper_cpp_cuda"',src)
        self.assertIn('profile["speech"].get("gpu_executable")',src)
        self.assertIn("GGML_CUDA=ON",inspect.getsource(WhisperRuntime.install_gpu))

    def test_persistent_nllb_serves_multiple_sentences_without_reloading(self):
        from tv_center.translation_market import run_nllb
        import inspect
        code=inspect.getsource(run_nllb)
        self.assertIn("_load_nllb()",code)
        self.assertIn("@lru_cache(maxsize=1)",
                      Path(__file__).resolve().parent.parent.joinpath(
                          "tv_center","translation_market.py").read_text())

