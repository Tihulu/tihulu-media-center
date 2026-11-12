"""Offline CUDA market regression tests; no GPU, network or inference used."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tv_center.cuda_faster_whisper import (
    FasterWhisperCUDA, MARKER, MODEL_MARKER, PARTIAL_MARKER)
from textcenter.compute import detect_devices, choose_backend
from textcenter.speech import transcribe_pcm


class CUDAModelMarketTests(unittest.TestCase):
    def test_runtime_requires_owner_marker_and_complete_ct2_model(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            root = Path(tmp)/"managed"
            storage = Path(tmp)/"weights"
            runtime = FasterWhisperCUDA(root=root, model_dir=storage)
            self.assertFalse(runtime.installed())
            root.mkdir()
            (root/MARKER).write_text("managed")
            (root/"bin").mkdir()
            (root/"bin/python3").touch()
            runtime.model_dir.mkdir(parents=True)
            (runtime.model_dir/MODEL_MARKER).write_text("sha256 verified")
            for file in ("model.bin", "config.json", "tokenizer.json"):
                (runtime.model_dir/file).touch()
            self.assertTrue(runtime.installed())
            self.assertEqual(runtime.probe()["ready"], False)
            self.assertTrue(runtime.worker_env()["HF_HUB_OFFLINE"] == "1")

    def test_recoverable_incomplete_model_is_owned_but_never_ready(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
            root = Path(tmp)/"managed"
            model_base = Path(tmp)/"weights"
            runtime = FasterWhisperCUDA(root=root, model_dir=model_base)
            runtime.model_dir.mkdir(parents=True)
            (runtime.model_dir/PARTIAL_MARKER).write_text("in progress")
            runtime._guard()
            self.assertFalse(runtime.installed())
            (runtime.model_dir/PARTIAL_MARKER).unlink()
            (runtime.model_dir/"orphan.bin").write_text("unowned")
            with self.assertRaises(RuntimeError):
                runtime._guard()

    @mock.patch("tv_center.cuda_faster_whisper.FasterWhisperCUDA")
    def test_gpu_ready_without_nvcc_if_verified_worker_probe_passes(self, managed):
        managed.return_value.installed.return_value = True
        managed.return_value.probe.return_value = {"ready":True}
        managed.return_value.model_dir = Path("/mock/ct2-large-v3-turbo")
        profile = detect_devices(
            executable_lookup=lambda name: (
                "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None),
            command_runner=lambda command: "NVIDIA GeForce RTX 5080\\n",
            system="Linux", model_path="")
        self.assertTrue(profile["speech"]["ready_gpu"])
        self.assertEqual(profile["speech"]["gpu_engine"], "faster_whisper_managed")
        self.assertEqual(profile["speech"]["gpu_model_path"], "/mock/ct2-large-v3-turbo")
        selected = choose_backend(profile, "auto")
        self.assertEqual(selected["selected"], "gpu")
        self.assertTrue(selected["ready"])

    @mock.patch("tv_center.cuda_faster_whisper.transcribe_cuda",
                return_value="Actual GPU recognized words")
    def test_inference_dispatch_uses_managed_persistent_worker(self, run):
        profile = {"speech":{
            "gpu_engine":"faster_whisper_managed",
            "gpu_model_path":"/external/verified-ct2-model",
            "ready_gpu":True,
        }}
        result = transcribe_pcm(bytes([0,0])*32000, "de", "gpu", profile)
        self.assertEqual(result, "Actual GPU recognized words")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[2], "/external/verified-ct2-model")


if __name__ == "__main__":
    unittest.main()
