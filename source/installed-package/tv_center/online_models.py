"""Owner-triggered verified Whisper GGML catalog from the official upstream repo.

Search is restricted to files in ggerganov/whisper.cpp on Hugging Face:
no arbitrary code, third-party repositories, unverified executable artifacts,
or remote auto-installation on application startup.
"""
from __future__ import annotations
import json
import re
from urllib.request import Request, urlopen

API = "https://huggingface.co/api/models/ggerganov/whisper.cpp/tree/main"
BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
ALLOWED = (
    "base", "small", "medium", "large-v3", "large-v3-q5_0",
    "large-v3-turbo", "large-v3-turbo-q5_0"
)
LIMIT = 4_100_000_000


def parse_remote_catalog(entries, search=""):
    """Only accept canonical GGML weights with official LFS SHA-256 hashes."""
    if not isinstance(entries, list) or len(entries) > 600:
        raise ValueError("Unexpected model listing")
    query = str(search or "").lower().strip()[:70]
    catalog = {}
    for row in entries:
        if not isinstance(row, dict):
            continue
        path = row.get("path", "")
        if not isinstance(path, str) or not re.fullmatch(
                r"ggml-[a-z0-9_.-]{3,45}\.bin", path):
            continue
        name = path.removeprefix("ggml-").removesuffix(".bin")
        if name not in ALLOWED or (query and query not in name):
            continue
        lfs = row.get("lfs", {})
        sha = lfs.get("oid", "") if isinstance(lfs, dict) else ""
        if sha.startswith("sha256:"):
            sha = sha[7:]
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            continue
        size = row.get("size")
        if type(size) is not int or not 1_000_000 <= size <= LIMIT:
            continue
        catalog[name] = {
            "name": "Whisper " + name.replace("-", " ").title() + " multilingual",
            "size_mb": (size + 999_999) // 1_000_000,
            "backend": "whisper.cpp CPU/CUDA depending on installed engine",
            "url": BASE + path, "sha256": sha,
            "filename": path, "max_bytes": max(size + 1024, size * 101 // 100),
            "quality": ("high" if name.startswith("large") or name=="medium"
                        else "balanced"),
            "source": "Official upstream Hugging Face GGML model",
        }
    return catalog


def search_official_models(query=""):
    request = Request(API, headers={
        "Accept": "application/json", "User-Agent": "TIHULU-TV-Center/0.2"})
    with urlopen(request, timeout=20) as response:
        if not response.url.startswith("https://huggingface.co/"):
            raise ValueError("Model index was redirected to untrusted host")
        if int(response.headers.get("Content-Length", "0")) > 2_000_000:
            raise ValueError("Model index unexpectedly large")
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("Model index too large")
    entries = json.loads(payload.decode("utf-8"))
    return parse_remote_catalog(entries, query)
