"""On-demand remote-GPU HTTPS endpoint for an *already installed* CUDA model.

Run explicitly on trusted GPU host only:
python3 -m tv_center.remote_gpu_server --host 127.0.0.1 --port 8443 \
 --cert server.crt --key server.key --token-file ~/.config/tihulu-tv-center/remote-gpu-token

For LAN access use a dedicated TLS hostname/certificate and firewall policy.
The server never opens a DVB tuner; model and CUDA self-tests are distinct.
"""
from __future__ import annotations
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import ssl
import threading

from .remote_gpu import read_token, MAX_AUDIO

MAX_REQUEST = 5_500_000


def make_handler(expected_token):
    slots=threading.BoundedSemaphore(2)
    class RemoteASRHandler(BaseHTTPRequestHandler):
        server_version="TIHULU-RemoteCUDA/1"
        def log_message(self,fmt,*args):
            # Do not write authorization tokens or spoken content to logs.
            return
        def _send(self,code,payload):
            data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def _authorized(self):
            header=self.headers.get("Authorization","")
            return hmac.compare_digest(header,"Bearer "+expected_token)
        def do_GET(self):
            if not self._authorized():
                self._send(401,{"error":"Unauthorized"})
                return
            if self.path!="/health":
                self._send(404,{"error":"Unknown endpoint"})
                return
            from .cuda_faster_whisper import FasterWhisperCUDA
            self._send(200,{"cuda_installed":FasterWhisperCUDA().installed(),
                            "note":"Installed marker only; live CUDA unverified"})
        def do_POST(self):
            if not self._authorized():
                self._send(401,{"error":"Unauthorized"})
                return
            if self.path!="/v1/transcribe":
                self._send(404,{"error":"Unknown endpoint"})
                return
            try:
                size=int(self.headers.get("Content-Length","0"))
            except ValueError:
                size=0
            if not 1<=size<=MAX_REQUEST:
                self._send(413,{"error":"Audio request size limit"})
                return
            if not slots.acquire(blocking=False):
                self._send(429,{"error":"GPU worker busy"})
                return
            try:
                item=json.loads(self.rfile.read(size))
                if not isinstance(item,dict) or not isinstance(item.get("audio"),str):
                    raise ValueError("Missing audio")
                pcm=base64.b64decode(item["audio"],validate=True)
                if not 0<len(pcm)<=MAX_AUDIO or len(pcm)%2:
                    raise ValueError("Invalid PCM")
                language=item.get("language","auto")
                if not isinstance(language,str) or len(language)>40:
                    raise ValueError("Invalid language")
                from .cuda_faster_whisper import FasterWhisperCUDA, transcribe_cuda_details
                model=FasterWhisperCUDA()
                if not model.installed():
                    raise RuntimeError("GPU host has no verified managed CUDA model")
                result=transcribe_cuda_details(pcm,language,str(model.model_dir))
                # Do not return system paths, logs, arbitrary model metadata.
                self._send(200,{key:result.get(key) for key in
                                ("text","words","language","language_probability",
                                 "recognition_rejected")})
            except (RuntimeError,ValueError,TypeError,KeyError) as exc:
                self._send(422,{"error":str(exc)[:160]})
            finally:
                slots.release()
    return RemoteASRHandler


def main(args=None):
    parser=argparse.ArgumentParser(description="Owner-started TLS remote CUDA service")
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8443)
    parser.add_argument("--cert",type=Path,required=True)
    parser.add_argument("--key",type=Path,required=True)
    parser.add_argument("--token-file",type=Path,required=True)
    opts=parser.parse_args(args)
    if not 1<=opts.port<=65535:
        parser.error("Port out of range")
    # The server must be explicitly provisioned with a TLS key and token.
    for file in (opts.cert,opts.key):
        if file.is_symlink() or not file.is_file():
            parser.error("TLS certificate and key must be regular files")
    expected=read_token(path=opts.token_file)
    if not expected:
        parser.error("A nonempty private token is required")
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(opts.cert),str(opts.key))
    server=ThreadingHTTPServer((opts.host,opts.port),make_handler(expected))
    server.socket=context.wrap_socket(server.socket,server_side=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
