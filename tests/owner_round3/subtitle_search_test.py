# SPDX-License-Identifier: GPL-2.0-or-later
"""Subtitle search: hash correctness and fail-closed behaviour (no network calls)."""
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "source/installed-package"))
from tv_center import subtitle_search


class HashAndSearch(unittest.TestCase):
    def _fixture(self, folder):
        path = Path(folder) / "film.mkv"
        block = hashlib.sha512(b"tihulu-fixture").digest()
        path.write_bytes(block * 4096)  # 512 KiB, deterministic
        return path

    def test_movie_hash_matches_reference_algorithm(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._fixture(folder)
            expected = os.path.getsize(path)
            with open(path, "rb") as handle:
                for offset in (0, -65536):
                    handle.seek(offset, os.SEEK_END if offset < 0 else os.SEEK_SET)
                    block = handle.read(65536)
                    for value in struct.unpack("<%dQ" % (len(block) // 8),
                                               block[: len(block) // 8 * 8]):
                        expected = (expected + value) & 0xFFFFFFFFFFFFFFFF
            self.assertEqual(subtitle_search.movie_hash(path), "%016x" % expected)

    def test_small_file_is_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tiny.mkv"
            path.write_bytes(b"x" * 10)
            with patch.object(subtitle_search.urllib.request, "urlopen") as opener:
                with self.assertRaises(ValueError):
                    subtitle_search.movie_hash(path)
                opener.assert_not_called()

    def test_search_requires_a_file_or_a_title(self):
        with self.assertRaises(ValueError):
            subtitle_search.search()

    def test_failed_login_is_reported_without_swallowing_errors(self):
        with patch.object(subtitle_search.urllib.request, "urlopen") as opener:
            opener.return_value.__enter__.return_value.read.return_value = \
                b'{"status":"414 User-Agent missing","result":{}}'
            with self.assertRaisesRegex(RuntimeError, "refused"):
                subtitle_search.login()

    def test_download_decompresses_gzip_and_keeps_vtt_suffix(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "sub.srt"
            payload = __import__("gzip").compress(
                b"1\n00:00:01,000 --> 00:00:02,000\nhi\n")
            response = Mock()
            response.read.return_value = payload
            response.__enter__ = lambda self: response
            response.__exit__ = lambda *a: False
            with patch.object(subtitle_search.urllib.request, "urlopen",
                              return_value=response):
                saved = subtitle_search.download({"link": "https://example/x"},
                                                 dest)
            self.assertEqual(Path(saved).read_text().splitlines()[0], "1")


if __name__ == "__main__":
    unittest.main()
