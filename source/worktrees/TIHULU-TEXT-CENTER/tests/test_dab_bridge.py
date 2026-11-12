import json
from pathlib import Path
import tempfile
import unittest
from textcenter.core import Store
from textcenter.dab_bridge import DABReader,parse_mux,DABError
from textcenter.media import MediaStore

PNG=(b"\x89PNG\r\n\x1a\n"+b"\x00\x00\x00\x0dIHDR"+
     b"\x00\x00\x00\x01\x00\x00\x00\x01"+b"\x08\x02\x00\x00\x00"+
     b"\x90\x77\x53\xde"+b"\x00\x00\x00\x00IEND\xae\x42\x60\x82")


class DABTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/"db.sqlite")
        self.raw=json.dumps({
            "receiver":{"software":{"name":"welle.io","version":"2.x"}},
            "ensemble":{"label":"TEST NRW"},
            "services":[{
                "sid":"0x1234","label":"TEST STATION",
                "dls_label":"REAL DATA ONLY WHEN FROM ACTUAL DECODER",
                "dls_time":1_783_610_000,"mot_time":1_783_610_000,
                "ptystring":"News","url_mp3":"/mp3/0x1234",
            }]
        }).encode()

    def tearDown(self):self.tmp.cleanup()

    def test_readonly_decoder_bridge_preserves_real_provenance(self):
        requested=[]
        def fetch(path,limit):
            requested.append(path)
            return {"/channel":b"11D","/mux.json":self.raw,"/slide/0x1234":PNG}[path]
        reader=DABReader(self.store,fetcher=fetch)
        result=reader.refresh(include_images=True)
        self.assertEqual(result["channel"],"11D")
        self.assertEqual(result["frequency_hz"],222_064_000)
        self.assertEqual(result["imported_dls"],1)
        self.assertEqual(result["saved_mot_images"],1)
        self.assertEqual(len(self.store.events()),1)
        self.assertEqual(len(MediaStore(self.store).list()),1)
        self.assertEqual(requested,["/channel","/mux.json","/slide/0x1234"])
        self.assertTrue(result["radio_not_retuned"])
        self.assertEqual(result["services"][0]["name"],"TEST STATION")

    def test_bad_endpoint_identity_and_unknown_channel_fail_closed(self):
        with self.assertRaises(DABError):
            parse_mux(json.dumps({"receiver":{"software":{"name":"fake"}},"services":[]}).encode(),"11D")
        doc=parse_mux(self.raw,"UNKNOWN")
        self.assertIsNone(doc["frequency_hz"])
        reader=DABReader(self.store,fetcher=lambda path,_:b"??" if path=="/channel" else self.raw)
        result=reader.refresh()
        self.assertEqual(result["imported_dls"],0)
        self.assertEqual(result["saved_mot_images"],0)
        self.assertEqual(self.store.counts()["events"],0)


if __name__=="__main__":
    unittest.main()
