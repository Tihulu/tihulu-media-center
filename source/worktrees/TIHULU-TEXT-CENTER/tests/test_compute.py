import unittest
from pathlib import Path
import tempfile
from textcenter.compute import detect_devices, choose_backend, validate_language


class DeviceTests(unittest.TestCase):
    def test_no_runtime_does_not_fake_npu_or_gpu(self):
        with tempfile.TemporaryDirectory() as td:
            profile=detect_devices(executable_lookup=lambda _: None,
                device_root=Path(td),model_path="",system="Linux",
                command_runner=lambda _: "")
            self.assertEqual([x["id"] for x in profile["devices"]],["cpu","gpu","npu"])
            self.assertTrue(profile["devices"][0]["detected"])
            self.assertFalse(profile["devices"][1]["detected"])
            self.assertFalse(profile["devices"][2]["detected"])
            self.assertFalse(choose_backend(profile,"auto")["ready"])
            self.assertEqual(choose_backend(profile,"auto")["selected"],"cpu")
            self.assertFalse(choose_backend(profile,"gpu")["ready"])
            with self.assertRaises(ValueError):
                choose_backend(profile,"supercomputer")

    def test_detect_device_not_equivalent_usable_model(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"hailo0").touch()
            profile=detect_devices(executable_lookup=lambda n: "/usr/bin/"+n,
                device_root=root,model_path="",system="Linux",
                command_runner=lambda _: "NVIDIA RTX 5080\n")
            self.assertIn("RTX 5080",profile["devices"][1]["name"])
            self.assertTrue(profile["devices"][2]["detected"])
            self.assertFalse(profile["devices"][2]["runtime_ready"])
            # Hailo device presence alone does not provide an OpenVINO runtime.
            self.assertFalse(choose_backend(profile,"npu")["ready"])

    def test_tri_language(self):
        self.assertEqual([validate_language(v) for v in ("en","de","tr")],["en","de","tr"])
        with self.assertRaises(ValueError):validate_language("fr")


if __name__=="__main__":
    unittest.main()
