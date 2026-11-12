#!/usr/bin/env python3
"""Produce a reviewable CI-only source candidate provenance index.

No full GPL legal clearance, no source delivery to recipients, and no binary
reproducibility is claimed. Only read existing reconstructed disposable trees.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

FROZEN = "7821769eb7aed576dd426ec18ffce3696d93a00d"
UPSTREAM = "e7ea15b86dafed3b20b151cbcb080578ab8e2d5c"
SOURCE_HEAD_19 = "03a566a57f76428c7fab86fc56e41ac03f011cc2"
NOTICE_BLOBS = {
    "LICENSE": "c03664da635ac564fa53300fc7bd91848839ef68",
    "NOTICE": "45798db6c4414a3848125fdd0a2cbdcb95b2825b",
    "LICENSES/GPL-2.0-only.txt": "d159169d1050894d3ea3b98e1c965c4058208fe1",
}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inventory(root: Path) -> list[dict]:
    root = root.resolve(strict=True)
    records = []
    for p in sorted(root.rglob("*")):
        r = p.relative_to(root).as_posix()
        st = p.lstat()
        if stat.S_ISLNK(st.st_mode):
            target = os.readlink(p)
            resolved = (p.parent / target).resolve(strict=False)
            if os.path.isabs(target) or not resolved.is_relative_to(root):
                raise ValueError("Unsafe external source candidate link: " + r)
            records.append({"path": r, "type": "internal-symlink", "target": target})
        elif stat.S_ISREG(st.st_mode):
            records.append({"path": r, "type": "file", "sha256": sha(p),
                            "size": st.st_size, "mode": oct(stat.S_IMODE(st.st_mode))})
        elif not stat.S_ISDIR(st.st_mode):
            raise ValueError("Unexpected special file in candidate: " + r)
    return records


def report(repo: Path, candidate: Path, output: Path):
    repo = repo.resolve(strict=True)
    candidate = candidate.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((candidate / "candidate-manifest.json").read_text())
    if manifest.get("pinned_upstream_commit") != UPSTREAM or manifest.get("selected_source_files") != 133:
        raise ValueError("Unexpected KDE source candidate revision/size")
    patch = candidate / "patches/kaffeine-from-pinned-upstream.patch"
    if sha(patch) != manifest.get("patch_sha256"):
        raise ValueError("Source candidate patch changed after reconstruction")
    marker = candidate / "selected/source/installed-package/kaffeine_next/patch_upstream.py"
    if not marker.is_file() or not (candidate / "modified_kaffeine/CMakeLists.txt").is_file():
        raise ValueError("Missing source candidate inputs")
    tested = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    parent = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor",
                             SOURCE_HEAD_19, tested], capture_output=True)
    if parent.returncode:
        raise ValueError("Candidate not on independently evidenced PR19 ancestry")
    paths = inventory(candidate)
    required = {"modified_kaffeine/CMakeLists.txt", "modified_kaffeine/COPYING",
                "selected/source/installed-package/kaffeine_next/patch_upstream.py",
                "build_scripts/media-stable-first.sh", "build_scripts/preview_safety.py",
                "patches/kaffeine-from-pinned-upstream.patch"}
    found = {p["path"] for p in paths if p["type"] == "file"}
    if not required <= found:
        raise ValueError("Candidate missing build inputs: " + str(required - found))
    if any(p["path"].startswith("modified_kaffeine/.git/") for p in paths):
        raise ValueError("Original Git internals unintentionally included")
    summary = {
        "artifact_kind": "DISPOSABLE CORRESPONDING-SOURCE REVIEW CANDIDATE - NOT RELEASE",
        "exact_integrated_repo_head": tested,
        "source_evidence_input": SOURCE_HEAD_19,
        "frozen_source_commit": FROZEN,
        "kde_upstream_commit": UPSTREAM,
        "selected_frozen_source_files": 133,
        "upstream_patch_sha256": sha(patch),
        "files_in_candidate": sum(1 for x in paths if x["type"] == "file"),
        "source_inventory": paths,
        "legal_notices_pinned_git_blob": NOTICE_BLOBS,
        "source_delivery_to_binary_recipients": "NOT PERFORMED",
        "complete_gpl_corresponding_source_legal_acceptance": "HOLD",
        "reproducibility_of_native_elf": "NOT DEMONSTRATED",
        "public_release": "HOLD",
    }
    (output / "source-candidate-inventory.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    (output / "candidate-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (output / "candidate-build-instructions.md").write_text(
        "# Review-only Kaffeine corresponding-source candidate\n\n"
        "This is an unapproved SOURCE CANDIDATE and not a binary shipment or GPL legal sign-off.\n\n"
        f"Freeze KDE upstream {UPSTREAM}, selected Git snapshot {FROZEN} "
        f"and integration HEAD {tested}.\n\n"
        "The disposable PR19 tool reconstructs modified_kaffeine/, "
        "selected/source/installed-package/, patches/kaffeine-from-pinned-upstream.patch, "
        "build_scripts/ and legal/ inside the candidate directory. The exact "
        "native patch SHA256 is " + sha(patch) + ".\n\n"
        "For a non-production comparison on a disposable Ubuntu host with matching "
        "Qt/KF5 dependencies, run: cmake -S modified_kaffeine -B build "
        "-DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF "
        "-DCMAKE_INSTALL_PREFIX=/tmp/REVIEW-NOT-SHIP, then "
        "cmake --build build --parallel 2. The installer also stages "
        "133 selected source files, patches and private preview wrappers. "
        "See full file identities in the JSON inventory.\n\n"
        "UNRESOLVED: toolchain flags and binary/source attestation, codec and "
        "package notices, copyright grants, NC model rights, Python wheels, "
        "source offer/delivery, independent legal review. Different ELF hashes "
        "were previously seen despite unchanged source; no binary "
        "reproducibility claim.\n")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = report(Path(args.repo), Path(args.candidate), Path(args.output))
    print("CI-ONLY GPL SOURCE REVIEW CANDIDATE:", result["files_in_candidate"],
          "files; release and legal signoff HOLD")

if __name__ == "__main__":
    main()
