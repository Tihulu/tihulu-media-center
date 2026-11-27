"""Hardware detection must never be confused with a working speech engine."""
import unittest
from unittest import mock
from tv_center.ai_diagnostics import inspect


class ReadOnlyAICheckTests(unittest.TestCase):
    def test_detects_rtx_but_does_not_claim_it_can_transcribe_without_cuda_runtime(self):
        ai=mock.Mock()
        ai.values={"asr_enabled":True,"translation_enabled":True,
                   "backend":"gpu","model_path":"/absent/ggml-medium.bin",
                   "translation_model":"argos"}
        hardware={
            "cpu":"x86_64", "raspberry_pi_5":False,
            "gpu":{"name":"NVIDIA GeForce RTX 5080","detected":True,
                   "vram_mib":16300,"cuda_version":None,
                   "cuda_compile_possible":False,"reason":"CUDA toolkit missing"},
            "npu":{"detected":False,"ready":False,"detail":"No NPU detected"},
        }
        profile={"speech":{"ready_npu":False,"gpu_engine":None}}
        with mock.patch("tv_center.ai_settings.AISettings",return_value=ai), \
             mock.patch("tv_center.hardware_market.detect_hardware",return_value=hardware), \
             mock.patch("textcenter.compute.detect_devices",return_value=profile) as devices, \
             mock.patch("textcenter.compute.choose_backend",
                        return_value={"selected":"gpu","ready":False,
                                      "reason":"CUDA speech runtime missing"}), \
             mock.patch("tv_center.whisper_engine.WhisperRuntime") as whisper, \
             mock.patch("tv_center.runtime.AIRuntime") as argos, \
             mock.patch("tv_center.translation_market.TranslationModelMarket") as nllb:
            whisper.return_value.ready.return_value=True
            whisper.return_value.ready_gpu.return_value=False
            argos.return_value.status.return_value={"installed":True}
            nllb.return_value.status.return_value={"installed":False}
            result=inspect()
        ai.configure_environment.assert_called_once()
        devices.assert_called_once_with(model_path="/absent/ggml-medium.bin")
        self.assertEqual(result["hardware"]["nvidia_gpu"],"NVIDIA GeForce RTX 5080")
        self.assertTrue(result["hardware"]["gpu_detected"])
        self.assertFalse(result["whisper"]["backend_ready"])
        self.assertFalse(result["whisper"]["runtime_cuda"])
        self.assertIn("no nvcc needed",result["next_step"])
        self.assertIn("CUDA Toolkit nvcc is optional",result["next_step"])
        self.assertIn("NPU",result["npu_explanation"])
        self.assertIn("no RF access",result["policy"])
