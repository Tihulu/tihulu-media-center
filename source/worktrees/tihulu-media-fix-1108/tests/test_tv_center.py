import tempfile
from pathlib import Path
import unittest
from tv_center.core import read_channels, zap_argv, player_argv, Channel, parse_signal_log, isolated_channel_file
from tv_center.captions import ass_text, decode_segment
from tv_center.bridge import TVBridge
from tv_center.lan import MobileLAN
from tv_center.streaming import hls_command
from tv_center.ts import ServiceFilter, mpeg2_crc32

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
            self.assertIn("--gpu-context=x11", player_argv(channels[0], 42))
            self.assertIn("--vo=x11", player_argv(channels[0], 42, renderer="x11-compat"))
            with self.assertRaises(ValueError):
                player_argv(channels[0], 0)

    def test_exact_service_config_with_duplicate_channel_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf=Path(tmp)/"channels.conf"
            conf.write_text(
                "[Same Name]\nFREQUENCY = 538000000\nSERVICE_ID = 100\n"
                "DELIVERY_SYSTEM = DVBT2\nSTREAM_ID = 1\n\n"
                "[Same Name]\nFREQUENCY = 586000000\nSERVICE_ID = 201\n"
                "DELIVERY_SYSTEM = DVBT2\nSTREAM_ID = 3\n\n")
            second=read_channels([conf])[1]
            isolated=isolated_channel_file(second,Path(tmp)/"single.conf")
            self.assertEqual(isolated.name,"Same Name")
            self.assertEqual(isolated.service_id,201)
            text=isolated.path.read_text()
            self.assertIn("FREQUENCY = 586000000",text)
            self.assertIn("STREAM_ID = 3",text)
            self.assertNotIn("538000000",text)
            self.assertEqual(text.count("[Same Name]"),1)
            self.assertIn("--demuxer-lavf-format=mpegts",player_argv(second,42))
            wrong=Channel(second.name,conf,626000000,second.service_id)
            with self.assertRaisesRegex(RuntimeError,"exactly one"):
                isolated_channel_file(wrong,Path(tmp)/"none.conf")

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

    def test_selected_program_transport_filter(self):
        # Complete PAT: service 100 -> PMT PID 0x100; service 101 -> 0x101
        pat = bytes.fromhex("00 b0 11 00 01 c1 00 00 00 64 e1 00 00 65 e1 01 00 00 00 00")
        # Program 100 PMT: PCR/video PID 0x200, audio 0x201, Teletext 0x202
        pmt = bytes.fromhex("02 b0 1c 00 64 c1 00 00 e2 00 f0 00"
                            " 24 e2 00 f0 00 0f e2 01 f0 00 06 e2 02 f0 00 00 00 00 00")
        def packet(pid, payload, start=False):
            if len(payload) > 184:
                raise ValueError("test payload too big")
            head = bytes([0x47, ((pid >> 8) & 0x1f) | (0x40 if start else 0),
                          pid & 0xff, 0x10])
            return head + payload + bytes([0xff]) * (184-len(payload))
        chunks = [packet(0, bytes([0])+pat, True),
                  packet(0x100, bytes([0])+pmt, True),
                  packet(0x200, b"video"),
                  packet(0x201, b"audio"),
                  packet(0x202, b"teletext"),
                  packet(0x300, b"other program")]
        filt = ServiceFilter(100)
        output = filt.feed(b"".join(chunks))
        result = [((output[n+1]&0x1f)<<8)|output[n+2]
                  for n in range(0, len(output), 188)]
        self.assertEqual(result, [0, 0x100, 0x200, 0x201, 0x202])
        self.assertTrue(filt.ready)
        self.assertEqual(filt.filtered_packets, 1)
        # The output must not advertise other services whose PMTs and PIDs
        # were removed. A stale full-multiplex PAT can break MPV probing.
        rewritten_pat = output[:188]
        self.assertEqual(rewritten_pat[:4], bytes([0x47, 0x40, 0x00, 0x10]))
        self.assertEqual(rewritten_pat[4], 0)  # PSI pointer field
        table = rewritten_pat[5:21]  # PAT section: 3+13 bytes
        self.assertEqual(table[2], 13)
        self.assertEqual(table[8:10], bytes([0, 100]))
        self.assertEqual(table[10:12], bytes([0xE1, 0]))
        self.assertEqual(mpeg2_crc32(table), 0)
        self.assertNotIn(bytes([0, 101, 0xE1, 1]), table)
        self.assertEqual(len(output) % 188, 0)

    def test_crc32_mpeg2_reference(self):
        # Standard check value CRC-32/MPEG-2 on ASCII 123456789.
        self.assertEqual(mpeg2_crc32(b"123456789"), 0x0376E6E7)

    def test_filtered_service_has_no_second_program_in_pat(self):
        # Two neighboring services share a multiplex; select second.
        pat = bytes.fromhex("00 b0 11 00 01 c1 00 00 00 64 e1 00 00 65 e1 01 00 00 00 00")
        def pkt(pid, payload, pusi=True):
            return bytes([0x47, ((pid >> 8)&31) | (0x40 if pusi else 0),
                          pid&255, 0x10]) + payload + bytes([255])*(184-len(payload))
        filt = ServiceFilter(101)
        result = filt.feed(pkt(0, bytes([0])+pat))
        self.assertEqual(len(result), 188)
        section = result[5:21]
        self.assertEqual(section[8:10], bytes([0, 101]))
        self.assertEqual(section[10:12], bytes([0xE1, 1]))
        self.assertEqual(mpeg2_crc32(section), 0)

    def test_hls_is_bound_to_selected_dvb_service(self):
        with tempfile.TemporaryDirectory() as root:
            cmd = hls_command(771, Path(root))
            self.assertIn("0:p:771:v:0", cmd)
            self.assertIn("0:p:771:a:0", cmd)
            self.assertIn("libx264", cmd)
            with self.assertRaises(ValueError):
                hls_command(0, Path(root))

    def test_mobile_pairing_is_rate_limited(self):
        lan = MobileLAN(lambda: {}, lambda p: None, lambda: None)
        self.assertEqual(len(lan.pin), 6)
        ticket, err = lan.accept_pin("192.168.1.1", lan.pin)
        self.assertIsNone(err)
        self.assertTrue(lan.authorized("tihulu_tv="+ticket))
        self.assertFalse(lan.authorized(""))
        other = MobileLAN(lambda: {}, lambda p: None, lambda: None)
        for _ in range(5):
            self.assertIsNotNone(other.accept_pin("192.168.1.2", "bad")[1])
        self.assertIn("Too many", other.accept_pin("192.168.1.2", other.pin)[1])

    def test_bridge_refuses_lan_listener(self):
        with self.assertRaises(ValueError):
            TVBridge(lambda: {}, lambda p: None, host="0.0.0.0")

if __name__ == "__main__":
    unittest.main()
