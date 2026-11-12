"""Explicit opt-in remote DeepL translation; never an offline/open model.

Local Whisper/TV audio and RF remain local. Only text phrases are submitted
when a user selected DeepL in AI Model Market and installed a secret API key.
The app never creates an account, bundles a key, or claims DeepL is open-source.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import tempfile
import urllib.error
import urllib.request

from .language_codes import language_code

ALLOWED_ENDPOINTS={
    "https://api.deepl.com/v2/translate",
    "https://api-free.deepl.com/v2/translate",
}
KEY_FILE=Path.home()/".config/tihulu-tv-center/deepl-api.key"


def read_key(path=None):
    explicit=os.environ.get("TIHULU_DEEPL_API_KEY","").strip()
    if explicit:
        if not 8<=len(explicit)<=256:
            raise RuntimeError("DeepL environment key length invalid")
        return explicit
    location=Path(path) if path is not None else KEY_FILE
    if location.is_symlink() or not location.is_file():
        return ""
    mode=location.stat().st_mode
    if mode & (stat.S_IRWXG|stat.S_IRWXO):
        raise RuntimeError("DeepL key file permissions unsafe (must be 0600)")
    if location.stat().st_size>300:
        raise RuntimeError("DeepL secret file length unsafe")
    return location.read_text(encoding="utf-8").strip()


def save_key(key, path=None):
    if not isinstance(key,str) or not (8<=len(key.strip())<=256):
        raise ValueError("Paste the API key from your own DeepL developer account")
    location=Path(path) if path is not None else KEY_FILE
    if location.is_symlink() or location.parent.is_symlink():
        raise RuntimeError("Refusing symlink DeepL secret path")
    location.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile("w",dir=location.parent,
              prefix=".deepl-",encoding="utf-8",delete=False) as output:
        temporary=Path(output.name)
        output.write(key.strip()+"\n")
    try:
        os.chmod(temporary,0o600)
        os.replace(temporary,location)
    finally:
        temporary.unlink(missing_ok=True)


def remove_key(path=None):
    location=Path(path) if path is not None else KEY_FILE
    if location.is_symlink():
        raise RuntimeError("Refusing symlink DeepL key")
    location.unlink(missing_ok=True)


def translate_deepl(text,source,target,*,key=None,endpoint=None):
    if not isinstance(text,str) or not text.strip() or len(text)>1400:
        raise ValueError("DeepL text length must be 1–1400 characters")
    src=language_code(source,nllb=True)
    tgt=language_code(target,nllb=True)
    if len(src)!=2 or len(tgt)!=2:
        raise ValueError("DeepL requires supported ISO two-letter language codes")
    if src==tgt:
        return text
    secret=read_key() if key is None else key
    if not isinstance(secret,str) or not secret.strip():
        raise RuntimeError("DeepL API key not configured; use offline Argos")
    url=endpoint or ("https://api-free.deepl.com/v2/translate"
                     if secret.endswith(":fx") else
                     "https://api.deepl.com/v2/translate")
    if url not in ALLOWED_ENDPOINTS:
        raise RuntimeError("DeepL endpoint must be one of two official HTTPS endpoints")
    payload=json.dumps({"text":[text],"source_lang":src.upper(),
                        "target_lang":tgt.upper()}).encode("utf-8")
    request=urllib.request.Request(url,data=payload,method="POST",headers={
        "Content-Type":"application/json",
        "Authorization":"DeepL-Auth-Key "+secret.strip(),
        "User-Agent":"TIHULU-Media-Center/0.3"})
    try:
        with urllib.request.urlopen(request,timeout=7) as response:
            if response.status!=200:
                raise RuntimeError("DeepL returned HTTP "+str(response.status))
            result=json.loads(response.read(64000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError("DeepL HTTP "+str(exc.code)) from None
    except (urllib.error.URLError,TimeoutError,ValueError) as exc:
        raise RuntimeError("DeepL request failed (offline Argos may work)") from None
    outputs=result.get("translations",[]) if isinstance(result,dict) else []
    translated=outputs[0].get("text") if outputs and isinstance(outputs[0],dict) else None
    if not isinstance(translated,str) or not translated.strip():
        raise RuntimeError("DeepL API returned no translated text")
    return translated[:1800]
