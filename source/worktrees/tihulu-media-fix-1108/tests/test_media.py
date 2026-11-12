import base64
import tempfile
from pathlib import Path
import unittest
from textcenter.core import Store
from textcenter.media import MediaStore,check_image,rds2_image_group


# Small hand-constructed valid PNG with full IEND marker, not over size threshold.
PNG=(b"\x89PNG\r\n\x1a\n"+b"\x00\x00\x00\x0dIHDR"+
     b"\x00\x00\x00\x01\x00\x00\x00\x01"+b"\x08\x02\x00\x00\x00"+
     b"\x90\x77\x53\xde"+b"\x00\x00\x00\x00IEND\xae\x42\x60\x82")


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.media=MediaStore(Store(Path(self.tmp.name)/"media.db"))

    def tearDown(self):self.tmp.cleanup()

    def test_image_validation_and_real_provenance(self):
        self.assertEqual(check_image(PNG),"image/png")
        obj=self.media.save(medium="dab_mot",station="TEST ENSEMBLE",
            source_id="external_decoder:local_recording",frequency_hz=222_064_000,
            received_at="2026-11-06T12:00:00Z",
            provenance="Operator imported saved MOT decoder JSON - TEST fixture",
            image_base64=base64.b64encode(PNG).decode())
        self.assertEqual(len(self.media.list()),1)
        kind,payload=self.media.get(obj["id"])
        self.assertEqual(kind,"image/png")
        self.assertEqual(payload,PNG)
        self.assertEqual(len(MediaStore(self.media.store).list()),1)
        self.assertIsNone(self.media.get("../etc/passwd"))

    def test_reject_unsafe_images_and_fake_provenance(self):
        for raw in (b"<svg><script>x</script></svg>",b"a"*400,b"\xff\xd8\xff"+"bad".encode()):
            with self.assertRaises(ValueError):
                check_image(raw)
        with self.assertRaises(ValueError):
            self.media.save(medium="dab_mot",station="S",source_id="decoder",
                            frequency_hz=222_000_000,received_at="yesterday",
                            provenance="x",image_base64=base64.b64encode(PNG).decode())
        with self.assertRaises(ValueError):
            self.media.import_images({"schema_version":1,"images":[{"medium":"random"}]})

    def test_RDS2_field_extraction_requires_actual_file_data(self):
        self.assertIsNone(rds2_image_group({"rft":{"data":{"segment_data":[1,2]}}}))
        self.assertEqual(rds2_image_group({
            "rft":{"data":{"file_contents":base64.b64encode(PNG).decode()}}
        }),base64.b64encode(PNG).decode())


if __name__=="__main__":
    unittest.main()
