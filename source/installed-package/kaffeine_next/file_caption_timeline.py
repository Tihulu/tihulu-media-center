# SPDX-License-Identifier: GPL-2.0-or-later
"""File playhead cue cache, independent of the DVB monotonic release clock."""
class FileCaptionTimeline:
    def __init__(self):
        self.key=None
        self.start=0
        self.end=0
        self.rows=[]
        self.eof=False
        self.error=""
        self.has_window=False
    def sync(self,generation,revision,state):
        key=(generation,revision,state[2] if state else None)
        if key!=self.key:
            self.key=key
            self.start=self.end=round(state[0]) if state else 0
            self.rows=[]
            self.eof=False
            self.error=""
            self.has_window=False
    def accept(self,kind,data):
        key=(data["generation"],data["revision"],data["session"])
        if key!=self.key:
            # First event can precede the first GUI timer after a reset.
            self.key=key
            self.start=self.end=data.get("start",0)
            self.rows=[]
            self.eof=False
            self.error=""
            self.has_window=False
        if kind=="file_window_error":
            self.error=data["error"]
            return
        if self.error:
            return
        if not self.has_window:
            self.start=self.end=data["start"]
            self.has_window=True
        if data["start"]!=self.end or data["end"]<data["start"]:
            self.error="Non-contiguous audio analysis; restart captions."
            return
        self.end=data["end"]
        self.eof=bool(data["eof"])
        self.rows.extend(data["cues"])
        self.rows=self.rows[-300:]
    def snapshot(self,state,window,active,offset=0):
        pos=round(state[0]) if state else 0
        active=bool(active and state and state[1])
        covered=self.has_window and self.start<=pos<=self.end
        ready=covered and (self.end-pos>=window*1000-100 or self.eof)
        # Display on the file clock, not wall time or native TV FIFO ACK.
        text="\n".join(row["text"] for row in self.rows
                       if row["start"]+offset<=pos<row["end"]+offset)
        return (text if active and covered and not self.error else "",
                dict(file_active=active,file_session=state[2] if state else -1,
                     file_ready=bool(active and ready and not self.error),
                     file_ready_start_ms=self.start,file_ready_end_ms=self.end,
                     file_eof=self.eof,file_error=self.error,
                     file_window_ms=window*1000))
