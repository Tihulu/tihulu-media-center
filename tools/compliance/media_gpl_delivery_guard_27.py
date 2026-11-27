#!/usr/bin/env python3
"""Read-only future GPL binary/source pair inspector. NEVER legal approval.

No building, downloading, model inference, publishing, or hardware operation.
A self-declared manifest cannot authenticate compiler inputs or rights.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile

BASE = "77f46af46335b3c91286c327780d657ebe7f0bf4"
FROZEN = "7821769eb7aed576dd426ec18ffce3696d93a00d"
TREE = "c572e6eccc5118c5130b1b5827af2f643633c26d"
KDE = "e7ea15b86dafed3b20b151cbcb080578ab8e2d5c"
NOTICE_BLOBS = {
    "LICENSE": "c03664da635ac564fa53300fc7bd91848839ef68",
    "NOTICE": "45798db6c4414a3848125fdd0a2cbdcb95b2825b",
    "LICENSES/GPL-2.0-only.txt": "d159169d1050894d3ea3b98e1c965c4058208fe1",
}
LEGAL_GATES = (
    "complete_corresponding_source_delivery", "third_party_rights",
    "final_dependency_sbom", "commercial_model_rights",
    "build_binary_provenance", "full_security", "owner_release_approval",
    "public_release",
)
REQUIRED_CANDIDATE = {
    "modified_kaffeine/CMakeLists.txt",
    "modified_kaffeine/COPYING",
    "selected/source/installed-package/kaffeine_next/patch_upstream.py",
    "build_scripts/media-stable-first.sh",
    "build_scripts/preview_safety.py",
    "patches/kaffeine-from-pinned-upstream.patch",
    "legal/LICENSE", "legal/NOTICE", "legal/LICENSES/GPL-2.0-only.txt",
    "candidate-manifest.json",
}
PAIR_PATHS = (
    "SOURCE-DELIVERY-MANIFEST.json", "corresponding-source.tar.gz",
    "source-inventory.json", "build-provenance.json", "SBOM-observation.json",
    "binary/native/bin/kaffeine", *NOTICE_BLOBS,
)
MODEL_SUFFIXES = (".safetensors", ".gguf", ".ggml", ".onnx",
                  ".argosmodel", ".pth", ".ckpt", ".pt")

def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def blob_oid(value: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()

def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result

def read_json(path: Path):
    return json.loads(path.read_text(), object_pairs_hook=strict_object)

def model_path(path: str) -> bool:
    low = path.lower()
    name = PurePosixPath(low).name
    return (low.endswith(MODEL_SUFFIXES)
            or (name.endswith(".bin")
                and any(x in low for x in ("model", "weight", "ggml", "checkpoint")))
            or any(p in low for p in ("/downloaded_models/", "/model_weights/",
                                      "/checkpoints/")))

def audit_ledger(ledger, models, spdx):
    if (ledger.get("pinned_pr22") != BASE or
            ledger.get("frozen_source") != FROZEN or
            ledger.get("frozen_selected_tree") != TREE or
            ledger.get("kaffeine_upstream") != KDE or
            ledger.get("source_candidate_file_baseline") != 492):
        raise ValueError("untrusted source or candidate provenance")
    if any(ledger.get("gates", {}).get(k) != "HOLD" for k in LEGAL_GATES):
        raise ValueError("unapproved legal or release PASS claim")
    if (ledger.get("model_policy") !=
            "NO MODEL WEIGHTS OR UNVERIFIED ASSETS IN RELEASE"):
        raise ValueError("unapproved model redistribution policy")
    decisions = ledger.get("owner_decisions", [])
    if len(decisions) < 7 or any(
            x.get("status") != "OWNER_REQUIRED" or
            x.get("answer") != "UNDECIDED" for x in decisions):
        raise ValueError("owner approval invented or omitted")
    model_records = models.get("models", [])
    catalog = {x["id"]: x for x in model_records}
    if len(catalog) != 9 or len(model_records) != 9:
        raise ValueError("optional model ledger incomplete")
    if set(ledger.get("model_exclusions", [])) != set(catalog):
        raise ValueError("optional model exclusion set differs")
    for x in model_records:
        if x.get("bundled") is not False:
            raise ValueError("model unexpectedly bundled")
    for key, license_id in (
        ("nllb-600m", "CC-BY-NC-4.0"),
        ("audeering-voice", "CC-BY-NC-SA-4.0"),
    ):
        m = catalog[key]
        if (m.get("declared_license") != license_id or
                m.get("redistribution") != "HOLD" or
                m.get("noncommercial") is not True):
            raise ValueError("noncommercial model restriction weakened: " + key)
    files = spdx.get("files", [])
    if (len(files) != 133 or
            any(x.get("licenseConcluded") != "NOASSERTION" or
                x.get("copyrightText") != "NOASSERTION" for x in files)):
        raise ValueError("per-file license/ownership clearance was invented")
    return {"static_policy": "SCOPED_PASS",
            "per_file_license_conclusions": "HOLD",
            "models_commercial_rights": "HOLD", "public_release": "HOLD"}

def check_git(repo: Path):
    def git(*cmd):
        return subprocess.check_output(
            ("git", "-C", str(repo), *cmd), text=True).strip()
    if (git("rev-parse", "HEAD:source/installed-package") != TREE or
            git("rev-parse", FROZEN + ":source/installed-package") != TREE):
        raise ValueError("source snapshot changed")
    ancestry = subprocess.run(
        ("git", "-C", str(repo), "merge-base", "--is-ancestor", BASE, "HEAD"),
        capture_output=True)
    if ancestry.returncode:
        raise ValueError("not based on frozen PR22")
    for path, sha in NOTICE_BLOBS.items():
        if git("rev-parse", "HEAD:" + path) != sha:
            raise ValueError("pinned notice changed: " + path)

def safe_file(root: Path, rel: str) -> Path:
    if (not rel or rel.startswith("/") or
            any(x in ("", ".", "..") for x in rel.split("/"))):
        raise ValueError("unsafe source/release path: " + rel)
    p = root
    for part in rel.split("/"):
        p = p / part
        if stat.S_ISLNK(p.lstat().st_mode):
            raise ValueError("symlink release path: " + rel)
    if not p.is_file():
        raise ValueError("not a regular file: " + rel)
    return p

def archive_inventory(archive: Path):
    records = []
    seen = set()
    byte_count = 0
    with tarfile.open(archive, mode="r:gz") as tf:
        for member in tf:
            if member.isdir():
                continue
            name = member.name
            if (not name or name.startswith("/") or
                    any(part in ("", ".", "..") for part in name.split("/"))
                    or name in seen or not member.isfile()):
                raise ValueError("archive traversal, duplicate or nonregular member")
            if member.size > 32 * 1024 * 1024:
                raise ValueError("source candidate member too large")
            seen.add(name)
            byte_count += member.size
            if len(seen) > 10000 or byte_count > 256 * 1024 * 1024:
                raise ValueError("unreasonably large source candidate archive")
            stream = tf.extractfile(member)
            if stream is None:
                raise ValueError("source candidate member missing")
            content = stream.read(member.size + 1)
            if len(content) != member.size:
                raise ValueError("source candidate member truncated")
            records.append({
                "path": name, "type": "file", "sha256": sha256_bytes(content),
                "size": member.size, "mode": oct(member.mode & 0o777),
                "git_blob": blob_oid(content)
                if (name in {"legal/" + k for k in NOTICE_BLOBS}
                    or name == "modified_kaffeine/COPYING") else None,
            })
    return records

def audit_pair(pair: Path, ledger: dict):
    """Future technical paired-artifact check; never establishes shipping rights."""
    pair = Path(pair)
    if pair.is_symlink() or not pair.is_dir():
        raise ValueError("paired review root must be a real directory")
    files = {p: safe_file(pair, p) for p in PAIR_PATHS}
    manifest = read_json(files["SOURCE-DELIVERY-MANIFEST.json"])
    if (manifest.get("schema") != "TIHULU-PAIRED-GPL-DELIVERY-27-DRAFT"
            or manifest.get("build_source_commit") != BASE
            or manifest.get("frozen_commit") != FROZEN
            or manifest.get("kde_commit") != KDE
            or manifest.get("recipient_delivery") != "NOT_PUBLISHED"
            or manifest.get("legal_clearance") != "HOLD"
            or manifest.get("public_release") != "HOLD"):
        raise ValueError("claimed authority/approval or bad source identity")
    targets = {
        "binary": "binary/native/bin/kaffeine",
        "source_archive": "corresponding-source.tar.gz",
        "source_inventory": "source-inventory.json",
        "build_provenance": "build-provenance.json",
        "sbom_observation": "SBOM-observation.json",
    }
    hashes = manifest.get("sha256", {})
    if set(hashes) != set(targets):
        raise ValueError("incomplete paired object digests")
    for key, path in targets.items():
        if not re.fullmatch(r"[a-f0-9]{64}", str(hashes[key])):
            raise ValueError("invalid content digest")
        if sha256_file(files[path]) != hashes[key]:
            raise ValueError("file content no longer matches paired digest: " + key)
    for path, expected in NOTICE_BLOBS.items():
        if blob_oid(files[path].read_bytes()) != expected:
            raise ValueError("binary release notice differs from pinned PR16: " + path)
    inventory = read_json(files["source-inventory.json"])
    declared = inventory.get("source_inventory")
    if not isinstance(declared, list) or len(declared) < ledger["source_candidate_file_baseline"]:
        raise ValueError("source review candidate member count incomplete")
    records = archive_inventory(files["corresponding-source.tar.gz"])
    actual = {x["path"]: x for x in records}
    if len(actual) != len(records) or len(records) != len(declared):
        raise ValueError("source archive and inventory members differ")
    paths = set()
    for item in declared:
        path = item["path"]
        if path in paths or path not in actual:
            raise ValueError("missing/duplicate inventory source entry")
        paths.add(path)
        record = actual[path]
        if any(record[k] != item.get(k) for k in
               ("sha256", "size", "mode", "type")):
            raise ValueError("source member checksum, size or mode mismatch: " + path)
    if not REQUIRED_CANDIDATE <= paths:
        raise ValueError("missing source/build/patch/notice input")
    kde_count = sum(p.startswith("modified_kaffeine/") for p in paths)
    selected_count = sum(p.startswith("selected/source/installed-package/")
                         for p in paths)
    if kde_count < 352 or selected_count != 133:
        raise ValueError("KDE/source coverage does not match known baseline")
    if any(model_path(p) for p in paths):
        raise ValueError("unverified model or weight inside source package")
    if any(model_path(p.relative_to(pair).as_posix()) for p in
           pair.rglob("*") if p.is_file()):
        raise ValueError("model weights inside paired package")
    for name, blob in NOTICE_BLOBS.items():
        if actual["legal/" + name]["git_blob"] != blob:
            raise ValueError("source legal text differs from PR16: " + name)
    if actual["modified_kaffeine/COPYING"]["git_blob"] != NOTICE_BLOBS[
            "LICENSES/GPL-2.0-only.txt"]:
        raise ValueError("Kaffeine COPYING differs from GPL source text")
    provenance = read_json(files["build-provenance.json"])
    if (provenance.get("build_commit") != BASE or
            provenance.get("kde_commit") != KDE or
            provenance.get("binary_sha256") != hashes["binary"] or
            not provenance.get("compiler_identity") or
            not provenance.get("full_build_commands")):
        raise ValueError("missing/inconsistent declared binary build provenance")
    return {
        "technical_candidate_byte_pair": "SCOPED_PASS_ONLY",
        "candidate_regular_files": len(records),
        "selected_source_members": selected_count,
        "binary_sha256": hashes["binary"],
        "source_archive_sha256": hashes["source_archive"],
        "build_provenance_authenticity": "NOT_VERIFIED",
        "complete_gpl_corresponding_source": "HOLD",
        "third_party_licenses_and_final_sbom": "HOLD",
        "real_recipient_delivery": "NOT_PERFORMED",
        "commercial_model_rights": "HOLD",
        "public_release": "HOLD",
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pair", help="optional FUTURE disposable source/binary pair, read only")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    check_git(repo)
    ledger = read_json(repo / "docs/compliance/MEDIA_GPL_SOURCE_DELIVERY_GATES_27.json")
    models = read_json(repo / "docs/compliance/AI_MODEL_LICENSES_19.json")
    spdx = read_json(repo / "docs/compliance/SPDX_SOURCES_19.spdx.json")
    result = audit_ledger(ledger, models, spdx)
    if args.pair:
        result.update(audit_pair(Path(args.pair), ledger))
    else:
        result.update({"actual_binary_source_pair": "NOT_PROVIDED",
                       "real_recipient_delivery": "NOT_PERFORMED"})
    result.update({"legal_clearance": "HOLD", "public_release": "HOLD"})
    print(json.dumps(result, sort_keys=True, indent=2))

if __name__ == "__main__":
    main()
