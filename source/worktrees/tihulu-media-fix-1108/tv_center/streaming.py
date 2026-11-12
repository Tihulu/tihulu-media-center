"""Explicitly enabled DVB-T2 to mobile HLS relay.

A bounded ffmpeg stdin writer consumes copies from the existing tuner reader.
Stopping TV stops this job. HLS is H.264/AAC for iOS Safari/Android hls.js.
No transcoder is launched on startup; do not enable this feature on a weak Pi
without monitoring load. Do not serve outside a trusted local network.
"""
from __future__ import annotations
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading

def hls_command(program_id: int, directory: Path) -> list[str]:
    if type(program_id) is not int or not 1 <= program_id <= 65535:
        raise ValueError("Mobile video requires a known DVB service ID")
    dest = Path(directory)
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-fflags", "+genpts+discardcorrupt",
            "-probesize", "5000000", "-analyzeduration", "5000000",
            "-f", "mpegts", "-i", "pipe:0",
            "-map", f"0:p:{program_id}:v:0",
            "-map", f"0:p:{program_id}:a:0",
            "-sn", "-dn",
            "-vf", "fps=25,scale=854:-2",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-g", "50",
            "-b:v", "1400k", "-maxrate", "1600k", "-bufsize", "2200k",
            "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-ar", "48000",
            "-f", "hls", "-hls_time", "2", "-hls_list_size", "5",
            "-hls_flags", "delete_segments+independent_segments+omit_endlist",
            "-hls_segment_filename", str(dest / "segment_%06d.ts"),
            str(dest / "index.m3u8")]

class HLSStreamer:
    def __init__(self, report=lambda event, value: None):
        self.report = report
        self.queue = queue.Queue(maxsize=48)
        self.dir = None
        self.temp = None
        self.proc = None
        self.worker = None
        self.stopping = threading.Event()
        self.dropped = 0

    def start(self, service_id: int):
        if self.proc is not None:
            raise RuntimeError("Mobile HLS stream already active")
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is required for mobile HLS video")
        self.temp = tempfile.TemporaryDirectory(prefix="tihulu-tv-mobile-")
        self.dir = Path(self.temp.name)
        self.stopping.clear()
        self.dropped = 0
        try:
            self.proc = subprocess.Popen(hls_command(service_id, self.dir),
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True)
            self.worker = threading.Thread(target=self._write, daemon=True,
                                           name="tihulu-hls-writer")
            self.worker.start()
            self.report("status", "Mobile HLS encoder started on demand (H.264 480p/25)")
        except BaseException:
            self.stop()
            raise

    def offer(self, data: bytes):
        if self.proc is None or self.proc.poll() is not None or self.stopping.is_set():
            return
        try:
            self.queue.put_nowait(data)
        except queue.Full:
            self.dropped += 1
            if self.dropped % 30 == 1:
                self.report("warning", "Mobile stream is too slow; TS packets dropped")

    def _write(self):
        try:
            while not self.stopping.is_set() and self.proc.poll() is None:
                try:
                    data = self.queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    self.proc.stdin.write(data)
                    self.proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    break
                finally:
                    self.queue.task_done()
        finally:
            if not self.stopping.is_set():
                self.report("warning", "Mobile HLS transcoder ended; check CPU / codecs / signal")

    def get_dir(self):
        if self.proc is None or self.proc.poll() is not None:
            return None
        return self.dir

    def stop(self):
        self.stopping.set()
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=2.5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=1)
            if self.proc.stdin is not None:
                try:
                    self.proc.stdin.close()
                except OSError:
                    pass
        if self.worker is not None and self.worker.is_alive():
            self.worker.join(timeout=1)
        self.proc = None
        self.worker = None
        self.queue = queue.Queue(maxsize=48)
        if self.temp is not None:
            self.temp.cleanup()
        self.temp = None
        self.dir = None
