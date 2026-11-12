"""Explicit opt-in, HTTPS-only remote CUDA speech backend.

No network on import, UI open, model discovery, or localhost playback.
Only direct HTTPS to a user-configured authenticated GPU host. No proxy,
redirect, HTTP downgrade or arbitrary URL paths. Audio is transmitted ONLY
when remote mode is selected. Tokens remain in a mode-0600 private file.
"""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request

TOKEN_PATH = Path.home()/".config/tihulu-tv-center/remote-gpu-token"
MAX_AUDIO = 4_000_000
MAX_RESPONSE = 60_000


def validate_endpoint(value):
    if not isinstance(value,str) or len(value)>512:
        raise ValueError("Remote GPU endpoint must be a short HTTPS URL")
    parts=urllib.parse.urlsplit(value.strip())
    if (parts.scheme != "https" or not parts.hostname or parts.username or
            parts.password or parts.query or parts.fragment or
            parts.path not in ("","/","/v1/transcribe")):
        raise ValueError("Remote GPU requires https://host[:port] (no credentials/query/path)")
    if any(ord(x)<33 or ord(x)>126 for x in value):
        raise ValueError("Remote GPU URL must be printable ASCII")
    try:
        port=parts.port
    except ValueError as exc:
        raise ValueError("Invalid remote GPU port") from exc
    if port is not None and not 1<=port<=65535:
        raise ValueError("Invalid remote GPU port")
    return f"https://{parts.netloc}/v1/transcribe"


def _private_token_file(path):
    file=Path(path)
    if file.is_symlink() or not file.is_file():
        raise ValueError("Private remote GPU token file missing or symlinked")
    st=file.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_size > 1024:
        raise ValueError("Remote GPU token must be private to current user (chmod 600)")
    return file


def save_token(token, *, path=TOKEN_PATH):
    if not isinstance(token,str) or not 16<=len(token)<=256 or not token.isascii():
        raise ValueError("Remote GPU token must be 16–256 ASCII characters")
    if any(ord(x)<33 or ord(x)>126 for x in token):
        raise ValueError("Remote GPU token contains invalid characters")
    path=Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Unsafe remote GPU token storage")
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.NamedTemporaryFile("w",dir=path.parent,encoding="ascii",
                                     prefix=".remote-token-",delete=False) as fp:
        tmp=Path(fp.name)
        fp.write(token+"\n")
    os.chmod(tmp,0o600)
    os.replace(tmp,path)
    return path


def read_token(*, path=TOKEN_PATH):
    return _private_token_file(path).read_text("ascii").strip()


def delete_token(*, path=TOKEN_PATH):
    path=Path(path)
    if path.is_symlink():
        raise ValueError("Refusing to remove symlinked token")
    if path.is_file():
        _private_token_file(path)
        path.unlink()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Remote GPU refused HTTP redirect")


def _request(endpoint, token, payload=None):
    address=validate_endpoint(endpoint)
    method="POST" if payload is not None else "GET"
    if method=="GET":
        address=address.removesuffix("/v1/transcribe")+"/health"
    body=(json.dumps(payload,separators=(",",":")).encode("ascii")
          if payload is not None else None)
    req=urllib.request.Request(
        address,data=body,method=method,
        headers={"Authorization":"Bearer "+token,
                 "Content-Type":"application/json","Accept":"application/json",
                 "User-Agent":"TIHULU-Remote-GPU/1"})
    # Disable env-configured proxies; TLS verification and hostname checks
    # remain mandatory, including localhost/SSH forwarding.
    opener=urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(req,timeout=25) as response:
        if response.status!=200:
            raise RuntimeError(f"Remote GPU HTTP {response.status}")
        chunk=response.read(MAX_RESPONSE+1)
        if len(chunk)>MAX_RESPONSE:
            raise RuntimeError("Remote GPU oversized response")
    decoded=json.loads(chunk)
    if not isinstance(decoded,dict):
        raise RuntimeError("Remote GPU response is not an object")
    return decoded


def test_connection(endpoint):
    """Owner-clicked health check, NEVER uploads TV audio."""
    response=_request(endpoint,read_token())
    return {"reachable":True,"cuda_installed":bool(response.get("cuda_installed")),
            "note":"Health checks cannot prove successful live inference"}


def transcribe(pcm,language,endpoint):
    if not isinstance(pcm,bytes) or not 0<len(pcm)<=MAX_AUDIO or len(pcm)%2:
        raise ValueError("Remote audio must be bounded mono s16le PCM")
    if not isinstance(language,str) or len(language)>40:
        raise ValueError("Invalid source language")
    response=_request(endpoint,read_token(),{
        "audio":base64.b64encode(pcm).decode("ascii"),
        "language":language,
    })
    if response.get("error"):
        raise RuntimeError("Remote GPU failed: "+str(response["error"])[:160])
    text=response.get("text")
    words=response.get("words",[])
    if not isinstance(text,str) or len(text)>3000 or not isinstance(words,list):
        raise RuntimeError("Remote CUDA returned invalid transcript")
    return {
        "text":text,
        "language":str(response.get("language") or language)[:40],
        "language_probability":float(response.get("language_probability") or 0),
        "words":[w for w in words[:240] if isinstance(w,dict)
                 and isinstance(w.get("text"),str)
                 and type(w.get("start")) in (int,float)
                 and type(w.get("end")) in (int,float)
                 and 0<=w["start"]<=w["end"]<=60],
        "recognition_rejected":response.get("recognition_rejected"),
    }
