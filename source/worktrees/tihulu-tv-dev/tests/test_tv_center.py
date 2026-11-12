import tempfile
from pathlib import Path
import unittest
from tv_center.core import read_channels, zap_argv, player_argv, Channel, parse_signal_log
from tv_center.captions import ass_text, decode_segment
from tv_center.bridge import TVBridge

class NativeTVTests(unittest.TestCase):
    def test_dvbv5_channels_and_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "channels.conf"
            conf.write_text("[arte HD]\nFREQUENCY = 538000000\nSERVICE_ID = 100\n\n"
                            "[KiKA HD]\nFREQUENCY = 538000000\nSERVICE_ID = 101\n")
            channels = read_channels([conf, conf])
            self.assertEqual([c.name for c in channels], ["arte HD", "KiKA HD"])
            self.assertEqual(channels[0].service_id, 100)
            self.assertEqual(zap_argv(channels[0])[-1], "arte HD")
            self.assertNotIn("--program=100", player_argv(channels[0], 42))
            self.assertIn("--input-ipc-server=/tmp/tv.sock",
                          player_argv(channels[0], 42, ipc_path="/tmp/tv.sock"))
            self.assertIn("--hwdec=no", player_argv(channels[0], 42))
            with self.assertRaises(ValueError):
                player_argv(channels[0], 0)

    def test_ass_parser_uses_only_real_dialogue(self):
        raw = "Header\nDialogue: 0,0:00:01,0:00:05,Default,,0,0,0,,{\\i1}Guten Tag\\Nzusammen\n"
        self.assertEqual(ass_text(raw), "Guten Tag zusammen")

    def test_missing_stream_is_not_fabricated(self):
        result = decode_segment(b"", mode="auto", page=150)
        self.assertEqual(result["original"], "")

    def test_real_signal_parser(self):
        text = ("Lock   (0x1f) Signal= -64.00dBm C/N= 18.50dB UCB= 900 postBER= 1e-6\n"
                "Carrier(0x03) Signal= -64.00dBm\n"
                "Lock   (0x1f) Signal= -64.00dBm C/N= 21.50dB UCB= 915 postBER= 0\n")
        result = parse_signal_log(text)
        self.assertEqual(result["ucb_delta"], 15)
        self.assertEqual(result["loss_indications"], 1)
        self.assertEqual(result["cn_max_db"], 21.5)

    def test_bridge_refuses_lan_listener(self):
        with self.assertRaises(ValueError):
            TVBridge(lambda: {}, lambda p: None, host="0.0.0.0")

if __name__ == "__main__":
    unittest.main()
