"""Thread-safe dispatch of authenticated web actions onto the Qt GUI thread.

HTTP request threads must never call Qt widgets or retune /dev/dvb directly.
The GUI polls this queue; each remote action has a bounded wait.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import queue
import threading

@dataclass
class WebCall:
    action: str
    params: dict
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    error: str = ""

class WebCommandQueue:
    ACTIONS = frozenset({
        "channels","scan_status","scan_start","scan_cancel","play",
        "stop","channel_update","teletext","models","set_captions"
    })

    def __init__(self):
        self.queue = queue.Queue(maxsize=64)
        self.closed = False

    def submit(self, action: str, params: dict | None = None):
        if self.closed:
            raise RuntimeError("Web control has been shut down")
        if action not in self.ACTIONS:
            raise ValueError("Unsupported remote TV command")
        if not isinstance(params, dict) or len(str(params)) > 12000:
            raise ValueError("Invalid web command arguments")
        call = WebCall(action, params)
        try:
            self.queue.put_nowait(call)
        except queue.Full as exc:
            raise RuntimeError("Too many pending TV commands") from exc
        if not call.done.wait(10):
            raise TimeoutError("Native TV controller is busy; retry after it responds")
        if call.error:
            raise RuntimeError(call.error)
        return call.result

    def drain(self, handler, limit=12):
        for _ in range(limit):
            try:
                call = self.queue.get_nowait()
            except queue.Empty:
                return
            try:
                if self.closed:
                    raise RuntimeError("Web bridge is shutting down")
                call.result = handler(call.action,call.params)
            except Exception as exc:
                call.error = str(exc)[:400]
            finally:
                call.done.set()
                self.queue.task_done()

    def close(self):
        self.closed = True
        while True:
            try: call=self.queue.get_nowait()
            except queue.Empty: break
            call.error="Web controller shut down"
            call.done.set()
            self.queue.task_done()
