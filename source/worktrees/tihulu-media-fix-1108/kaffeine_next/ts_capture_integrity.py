"""Best-effort MPEG-TS sidecar integrity before offline subtitle decoding.

Kaffeine's stream is already tuned and played independently. This guard
only cleans the *copy* sent to FFmpeg/Whisper; it never changes the live
DVB player, tuner, channel, or broadcaster packets. It rejects damaged
headers/TEI and duplicated payload packets, and marks PES continuity gaps.
"""
from __future__ import annotations


class CaptionPacketGuard:
    def __init__(self):
        self.cc = {}
        self.last_payload = {}

    def reset(self):
        self.cc.clear()
        self.last_payload.clear()

    def filter(self, datagram: bytes, *, audio_pid=None, teletext_pid=None):
        stats = {"invalid":0, "duplicates":0, "gaps":0,
                 "critical_gaps":0, "kept_packets":0}
        if (not isinstance(datagram,bytes) or
                not datagram or len(datagram)%188):
            stats["invalid"]+=1
            return b"", stats
        critical={pid for pid in (audio_pid,teletext_pid)
                  if type(pid) is int and 1 <= pid <= 8190}
        output=bytearray()
        for start in range(0,len(datagram),188):
            packet=datagram[start:start+188]
            if packet[0]!=0x47 or packet[1]&0x80:
                stats["invalid"]+=1
                continue
            pid=((packet[1]&0x1f)<<8)|packet[2]
            afc=(packet[3]>>4)&3
            if afc==0:
                stats["invalid"]+=1
                continue
            if afc in (2,3):
                length=packet[4]
                if length>183 or (afc==3 and length>182):
                    stats["invalid"]+=1
                    continue
                if length>=1 and packet[5]&0x80:
                    self.cc.pop(pid,None)
                    self.last_payload.pop(pid,None)
            if afc in (1,3) and pid!=0x1fff:
                value=packet[3]&15
                prev=self.cc.get(pid)
                if prev is not None:
                    if value==prev and self.last_payload.get(pid)==packet:
                        stats["duplicates"]+=1
                        continue  # exact repeated TS packet, no new audio
                    if value!=(prev+1)&15:
                        stats["gaps"]+=1
                        if pid in critical:
                            stats["critical_gaps"]+=1
                self.cc[pid]=value
                self.last_payload[pid]=packet
            output.extend(packet)
            stats["kept_packets"]+=1
        return bytes(output), stats
