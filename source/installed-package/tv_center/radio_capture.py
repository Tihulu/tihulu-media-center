"""Bounded DAB speech-capture reader, independent of slow Whisper inference.

A dedicated reader continuously drains the PRIVATE ffmpeg HTTP client so an
expensive ASR/translation step does not exert backpressure on the welle.io
receiver's other playback client. At overload, drop the OLDEST *AI* audio
windows and explicitly report their count; radio playback is never retuned.
No network/tuner/model access occurs when importing this module.
"""
from __future__ import annotations

import queue
import threading
import time


class BoundedRadioCapture:
    def __init__(self, stream, *, samples_per_second=32000,
                 max_windows=0, queue_size=4):
        if not 2 <= queue_size <= 16 or samples_per_second <= 0:
            raise ValueError("Invalid radio capture budget")
        self.stream=stream
        self.samples_per_second=samples_per_second
        self.max_windows=max_windows
        self.items=queue.Queue(maxsize=queue_size)
        self.stopping=threading.Event()
        self.finished=threading.Event()
        self.dropped_windows=0
        self.captured_windows=0
        self.thread=threading.Thread(target=self._read,
            name="tihulu-radio-audio-drain",daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _read(self):
        overlap=b""
        try:
            index=0
            while not self.stopping.is_set():
                seconds=6 if index==0 else 5
                fresh=self.stream.read(seconds*self.samples_per_second*2)
                if self.stopping.is_set() or len(fresh)<self.samples_per_second*2:
                    break
                pcm=overlap+fresh
                overlap=pcm[-self.samples_per_second*2:]
                item=(index,pcm,time.monotonic())
                index+=1
                self.captured_windows=index
                try:
                    self.items.put_nowait(item)
                except queue.Full:
                    try:
                        self.items.get_nowait()
                        self.dropped_windows+=1
                    except queue.Empty:
                        pass
                    try:
                        self.items.put_nowait(item)
                    except queue.Full:
                        self.dropped_windows+=1
                if self.max_windows>0 and index>=self.max_windows:
                    break
        finally:
            self.finished.set()

    def next(self, timeout=0.5):
        """Return (absolute hop, PCM, timestamp), None once EOF is drained.

        An empty but still live queue is NOT interpreted as silence or EOF.
        """
        while not self.stopping.is_set():
            try:
                return self.items.get(timeout=timeout)
            except queue.Empty:
                if self.finished.is_set() and self.items.empty():
                    return None
        return None

    def stop(self):
        self.stopping.set()
        # The calling code terminates the owned ffmpeg subprocess first.
        # Never wait indefinitely for a stuck OS pipe.
        if self.thread.is_alive():
            self.thread.join(timeout=0.5)
