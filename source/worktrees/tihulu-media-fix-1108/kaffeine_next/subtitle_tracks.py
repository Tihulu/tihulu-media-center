# SPDX-License-Identifier: GPL-2.0-or-later
"""Discover *broadcast-signalled* Teletext subtitle pages from PAT/PMT.

Read-only DVB MPEG-TS section parser for Kaffeine's copied stream; it does not
open the tuner or infer subtitles from arbitrary Teletext news pages. Only DVB
teletext_descriptor (0x56) type 0x02 or 0x05 is offered as selectable captions.
"""
from __future__ import annotations
from dataclasses import dataclass

LANGUAGE = {
    "deu": "de", "ger": "de", "de": "de",
    "eng": "en", "en": "en",
    "tur": "tr", "tr": "tr", "fra":"fr", "fre":"fr", "fr":"fr",
    "spa":"es", "es":"es", "ita":"it", "it":"it",
    "nld":"nl", "dut":"nl", "pol":"pl", "por":"pt", "rus":"ru",
    "ukr":"uk", "ara":"ar",
}

@dataclass(frozen=True)
class TeletextTrack:
    pid: int
    page: int
    language: str
    hearing_impaired: bool = False

    @property
    def language_hint(self):
        return LANGUAGE.get(self.language.lower())

    @property
    def display(self):
        return (f"{self.language.upper()} · Teletext {self.page} · PID {self.pid}"
                + (" · hearing impaired" if self.hearing_impaired else ""))

    def as_dict(self):
        return {"pid":self.pid, "page":self.page,
                "language":self.language, "source_hint":self.language_hint,
                "hearing_impaired":self.hearing_impaired,
                "label":self.display}


@dataclass(frozen=True)
class BroadcastAudioTrack:
    pid: int
    language: str
    visual_impaired: bool = False

    def as_dict(self):
        return {
            "pid": self.pid, "language": self.language,
            "source_hint": LANGUAGE.get(self.language.lower()),
            "visual_impaired": self.visual_impaired,
            "label": (f"{self.language.upper()} · Audio PID {self.pid}" +
                      (" · audio description" if self.visual_impaired else "")),
        }


def mpeg_crc32(data: bytes) -> int:
    result = 0xffffffff
    for byte in data:
        result ^= byte << 24
        for _ in range(8):
            result = ((result << 1) ^ (0x04c11db7 if result & 0x80000000 else 0)) & 0xffffffff
    return result


class TeletextSubtitleDiscovery:
    """Accumulate bounded PSI sections across packets and socket datagrams.

    Does not interpret unverified pages as subtitles. PAT/PMT CRC, lengths,
    transport errors and section continuation are checked before publishing.
    """
    def __init__(self):
        self.service_id = None
        self.pmt_pid = None
        self.tracks = ()
        self.audio_tracks = ()
        self._buffers = {}
        self._continuity = {}

    def clear(self):
        self.service_id = None
        self.pmt_pid = None
        self.tracks = ()
        self.audio_tracks = ()
        self._buffers.clear()
        self._continuity.clear()

    def snapshot(self):
        return [t.as_dict() for t in self.tracks]

    def snapshot_audio(self):
        return [t.as_dict() for t in self.audio_tracks]

    def offer(self, chunk: bytes, preferred_service_id=None) -> bool:
        # Kaffeine usually sends a selected-service TS. If its PAT still
        # includes more than one service, prefer the real tuned program ID
        # rather than mixing tracks from a neighbouring channel.
        self._preferred = preferred_service_id
        old = (self.service_id, self.pmt_pid, self.tracks, self.audio_tracks)
        if not isinstance(chunk, bytes) or len(chunk) % 188:
            return False
        for i in range(0, len(chunk), 188):
            packet = chunk[i:i + 188]
            if packet[0] != 0x47 or packet[1] & 0x80:
                continue
            pid = ((packet[1] & 0x1f) << 8) | packet[2]
            if pid not in (0, self.pmt_pid):
                continue
            afc = (packet[3] >> 4) & 3
            if afc not in (1, 3):
                continue
            start = 4
            if afc == 3:
                if start >= 188:
                    continue
                start += packet[4] + 1
            if start >= 188:
                continue
            cc = packet[3] & 15
            previous = self._continuity.get(pid)
            self._continuity[pid] = cc
            if previous is not None and cc != ((previous + 1) & 15):
                self._buffers.pop(pid, None)
            payload = packet[start:]
            if packet[1] & 0x40:
                if not payload:
                    continue
                pointer = payload[0]
                if 1 + pointer > len(payload):
                    self._buffers.pop(pid, None)
                    continue
                if pointer and pid in self._buffers:
                    self._feed(pid, payload[1:1 + pointer])
                self._buffers.pop(pid, None)
                self._feed(pid, payload[1 + pointer:])
            elif pid in self._buffers:
                self._feed(pid, payload)
        return old != (self.service_id, self.pmt_pid, self.tracks, self.audio_tracks)

    def _feed(self, pid, content):
        if not content:
            return
        buf = self._buffers.setdefault(pid, bytearray())
        buf.extend(content)
        if len(buf) > 4096:
            buf.clear()
            return
        while len(buf) >= 3:
            if buf[0] == 0xff:
                buf.clear()
                break
            length = ((buf[1] & 0x0f) << 8) | buf[2]
            if length < 9 or length > 1021:
                buf.clear()
                break
            total = 3 + length
            if len(buf) < total:
                break
            section = bytes(buf[:total])
            del buf[:total]
            if mpeg_crc32(section) != 0:
                continue
            if pid == 0 and section[0] == 0x00:
                self._pat(section)
            elif pid == self.pmt_pid and section[0] == 0x02:
                self._pmt(section)

    def _pat(self, section):
        end = len(section) - 4
        if end < 12:
            return
        programs = []
        for i in range(8, end - 3, 4):
            service = (section[i] << 8) | section[i + 1]
            pid = ((section[i + 2] & 0x1f) << 8) | section[i + 3]
            if service:
                programs.append((service, pid))
        if not programs:
            return
        preferred = getattr(self, "_preferred", None)
        if preferred is not None:
            matches = [entry for entry in programs if entry[0] == preferred]
            if not matches:
                self.tracks = ()
                self.audio_tracks = ()
                return
            service, pmt_pid = matches[0]
        elif len(programs) == 1:
            service, pmt_pid = programs[0]
        else:
            # Never guess whose subtitles they are in a multiplex.
            self.tracks = ()
            self.audio_tracks = ()
            return
        if (service, pmt_pid) != (self.service_id, self.pmt_pid):
            self.service_id, self.pmt_pid = service, pmt_pid
            self.tracks = ()
            self.audio_tracks = ()
            self._buffers = {0: self._buffers.get(0, bytearray())}
            self._continuity.pop(pmt_pid, None)

    def _pmt(self, section):
        if len(section) < 16:
            return
        program = (section[3] << 8) | section[4]
        if program != self.service_id:
            return
        program_info_len = ((section[10] & 0x0f) << 8) | section[11]
        start = 12 + program_info_len
        end = len(section) - 4
        if start > end:
            return
        tracks = set()
        audio_tracks = set()
        i = start
        while i + 5 <= end:
            stream_type = section[i]
            audio_languages = []
            private_audio = False
            pid = ((section[i + 1] & 0x1f) << 8) | section[i + 2]
            desc_len = ((section[i + 3] & 0x0f) << 8) | section[i + 4]
            desc_end = i + 5 + desc_len
            if desc_end > end:
                return
            desc_at = i + 5
            while desc_at + 2 <= desc_end:
                tag = section[desc_at]
                size = section[desc_at + 1]
                entry_start = desc_at + 2
                entry_end = entry_start + size
                if entry_end > desc_end:
                    break
                if tag == 0x0a and size % 4 == 0:
                    # ISO 639 audio-language descriptor; type=3 denotes
                    # audio intended for visually impaired listeners.
                    for j in range(entry_start, entry_end, 4):
                        raw = section[j:j + 3]
                        if all(97 <= byte <= 122 for byte in raw):
                            audio_languages.append((raw.decode("ascii"),
                                                    section[j + 3] == 3))
                if tag in (0x6a, 0x7a, 0x7c, 0x7b):
                    # AC-3, enhanced AC-3 and AAC descriptor signalled
                    # inside a private-data elementary stream.
                    private_audio = True
                if tag == 0x56 and size % 5 == 0:
                    for j in range(entry_start, entry_end, 5):
                        raw = section[j:j + 3]
                        if not all(97 <= b <= 122 for b in raw):
                            continue
                        language = raw.decode("ascii")
                        kind = section[j + 3] >> 3
                        mag = section[j + 3] & 7 or 8
                        bcd = section[j + 4]
                        tens, units = bcd >> 4, bcd & 15
                        page = mag * 100 + tens * 10 + units
                        if kind in (2, 5) and tens <= 9 and units <= 9 and 100 <= page <= 899:
                            tracks.add(TeletextTrack(pid, page, language,
                                                     hearing_impaired=kind == 5))
                desc_at = entry_end
            # Only advertise identified audio types. In particular, DVB
            # private-stream type 0x06 also carries Teletext, not just AC3.
            if stream_type in (0x03, 0x04, 0x0f, 0x11, 0x81) or (
                    stream_type == 0x06 and private_audio):
                for language, descriptive in (audio_languages or [("und", False)]):
                    audio_tracks.add(BroadcastAudioTrack(pid, language, descriptive))
            i = desc_end
        self.tracks = tuple(sorted(tracks, key=lambda t: (t.language, t.page, t.pid,
                                                         t.hearing_impaired)))
        self.audio_tracks = tuple(sorted(
            audio_tracks, key=lambda t: (t.language, t.visual_impaired, t.pid)))
