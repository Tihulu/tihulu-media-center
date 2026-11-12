#!/usr/bin/env python3
"""Disposable CI evidence only; no legal clearance, release, model or hardware."""
import argparse, hashlib, importlib.metadata, io, json, re, shutil, subprocess, sys, tarfile
from pathlib import Path

BASE="e5271965dadaf82c4be1a336396d0e9b3a083b8d"
FROZEN="7821769eb7aed576dd426ec18ffce3696d93a00d"
UPSTREAM="e7ea15b86dafed3b20b151cbcb080578ab8e2d5c"
TREE="c572e6eccc5118c5130b1b5827af2f643633c26d"
REQUIRED_NOTICE=("LICENSE","NOTICE","LICENSES/GPL-2.0-only.txt")
MODEL_SUFFIX={".safetensors",".gguf",".ggml",".onnx",".argosmodel",".pt",".pth",".ckpt"}
APT=("qtbase5-dev","libkf5coreaddons-dev","libkf5kio-dev","libkf5solid-dev","libvlc-dev","libdvbv5-dev","vlc","ffmpeg","mpv","python3","python3-pyqt5","dvb-tools")

def run(*cmd, input=None, check=True):
    p=subprocess.run(cmd,input=input,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if check and p.returncode: raise RuntimeError(f"failed {cmd}: {p.stderr[-1000:]}")
    return p.stdout

def git(repo,*args): return run("git","-C",str(repo),*args).strip()
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify_base(repo):
    for commit in (BASE,FROZEN):
        if git(repo,"rev-parse",f"{commit}:source/installed-package")!=TREE:
            raise ValueError("frozen source modified or pinned tree mismatch")
    run("git","-C",str(repo),"merge-base","--is-ancestor",BASE,"HEAD")
    return git(repo,"rev-parse","HEAD")

def models_ok(model_manifest):
    records={m["id"]:m for m in model_manifest["models"]}
    for key,license in (("nllb-600m","CC-BY-NC-4.0"),("audeering-voice","CC-BY-NC-SA-4.0")):
        v=records[key]
        if (v["declared_license"]!=license or v.get("noncommercial")!=True or
            v.get("redistribution")!="HOLD" or v.get("bundled")!=False or
            "commercial" not in v.get("commercial","").lower()):
            raise ValueError("noncommercial model restriction weakened: "+key)
    return True

def needed(text):
    return sorted(set(re.findall(r"\(NEEDED\)\s+Shared library:\s+\[([^\]]+)\]",text)))

def ldd_lines(text):
    out=[]
    for line in text.splitlines():
        s=line.strip()
        if " => " in s:
            name,right=s.split(" => ",1); target=right.split(" (",1)[0].strip()
        elif s.startswith("/"):
            target=s.split(" (",1)[0].strip(); name=Path(target).name
        else: continue
        out.append({"soname":name,"path":target if target.startswith("/") else None,"resolved":target.startswith("/")})
    return sorted(out,key=lambda x:x["soname"])

def notices(release):
    missing=[p for p in REQUIRED_NOTICE if not (Path(release)/p).is_file()]
    return {"present":[p for p in REQUIRED_NOTICE if p not in missing],"missing":missing,
            "delivery":"HOLD" if missing else "REVIEW_REQUIRED"}

def spdx_headers(selected):
    all_files=sorted(p for p in Path(selected).rglob("*") if p.is_file())
    gaps=[p.relative_to(selected).as_posix() for p in all_files
          if "SPDX-License-Identifier:" not in p.read_text(errors="replace")[:2500]]
    return {"total":len(all_files),"explicit_headers":len(all_files)-len(gaps),"missing_headers":gaps}

def weights(release):
    return sorted(p.relative_to(release).as_posix() for p in Path(release).rglob("*")
                  if p.is_file() and p.suffix.lower() in MODEL_SUFFIX)

def pkg(name):
    r=run("dpkg-query","-W",name,check=False).strip()
    if not r: return {"name":name,"installed":False,"license_concluded":"NOASSERTION"}
    s=r.splitlines()[0].split("\t"); copyright=Path("/usr/share/doc")/s[0].split(":")[0]/"copyright"
    return {"name":s[0],"version":s[1] if len(s)>1 else None,"installed":True,
            "copyright_present":copyright.is_file(),
            "copyright_sha256":digest(copyright) if copyright.is_file() else None,
            "license_concluded":"NOASSERTION"}

def owner(path):
    for p in (str(path),str(Path(path).resolve())):
        r=run("dpkg-query","-S",p,check=False)
        if r:
            return r.split(": ",1)[0].split(",",1)[0].splitlines()[0].strip()
    return None

def source_candidate(repo,target):
    repo=Path(repo).resolve(); target=Path(target).resolve()
    verify_base(repo)
    if target.exists(): raise ValueError("reconstruction target already exists")
    target.mkdir(parents=True)
    upstream=target/"work_kaffeine"
    run("git","clone","--quiet","--depth","1","--single-branch","--branch","v2.0.19",
        "https://github.com/KDE/kaffeine.git",str(upstream))
    if git(upstream,"rev-parse","HEAD")!=UPSTREAM: raise ValueError("KDE commit mismatch")
    blob=subprocess.check_output(["git","-C",str(repo),"archive",FROZEN,"--","source/installed-package"])
    selected=target/"selected"; selected.mkdir()
    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
        members=tf.getmembers()
        for m in members:
            if not (m.name=="source" or m.name=="source/installed-package" or
                    m.name.startswith("source/installed-package/")) or m.issym() or m.islnk():
                raise ValueError("unsafe frozen archive member")
        tf.extractall(selected,filter="data")
    if spdx_headers(selected/"source/installed-package")["total"]!=133:
        raise ValueError("selected source expected 133 Git blobs")
    patch=selected/"source/installed-package/kaffeine_next/patch_upstream.py"
    run(sys.executable,str(patch),str(upstream))
    # Execute exactly the in-installer native parity patch, never a handwritten variant.
    shell=(repo/"installer/media-stable-first.sh").read_text()
    found=re.search(r"python3 - \"\$work/upstream/src/mainwindow.cpp\" <<'DVB_DIAGNOSTICS_ROUTE'\n(.*?)\nDVB_DIAGNOSTICS_ROUTE\n",shell,re.S)
    if not found: raise ValueError("installer native parity patch not found")
    run(sys.executable,"-",str(upstream/"src/mainwindow.cpp"),input=found.group(1)+"\n")
    run("git","-C",str(upstream),"diff","--check")
    diff=run("git","-C",str(upstream),"diff","--binary")
    if "mainwindow.cpp" not in diff: raise ValueError("native parity source modification absent")
    (target/"patches").mkdir()
    patchfile=target/"patches/kaffeine-from-pinned-upstream.patch";patchfile.write_text(diff)
    shutil.copytree(upstream,target/"modified_kaffeine",ignore=shutil.ignore_patterns(".git"))
    (target/"build_scripts").mkdir()
    for p in ("installer/media-stable-first.sh","installer/preview_safety.py"):
        shutil.copy2(repo/p,target/"build_scripts"/Path(p).name)
    for p in REQUIRED_NOTICE:
        dest=target/"legal"/p;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(repo/p,dest)
    manifest={"source_candidate_only":True,"complete_corresponding_source_delivered":"HOLD",
              "pinned_upstream_commit":UPSTREAM,"frozen_selected_tree":TREE,
              "selected_source_files":133,"patch_sha256":digest(patchfile),
              "included":["modified_kaffeine","selected","build_scripts","patches","legal"],
              "source_offer_or_distribution":"NOT PERFORMED","public_release":"HOLD"}
    (target/"candidate-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    shutil.rmtree(upstream)
    return manifest

def collect(repo,release,candidate,destination):
    repo=Path(repo).resolve();release=Path(release).resolve()
    candidate=Path(candidate).resolve();destination=Path(destination).resolve()
    head=verify_base(repo)
    native=release/"native/bin/kaffeine"
    if not native.is_file(): raise ValueError("no actual disposable native ELF")
    direct=needed(run("readelf","-d",str(native)))
    if not direct: raise ValueError("missing direct native dependencies")
    resolved=ldd_lines(run("ldd",str(native)))
    for x in resolved:
        if x["path"]:
            x["package"]=owner(x["path"])
            if x["package"]: x["deb_metadata"]=pkg(x["package"])
    candidate_manifest=json.loads((candidate/"candidate-manifest.json").read_text())
    if candidate_manifest["patch_sha256"]!=digest(candidate/"patches/kaffeine-from-pinned-upstream.patch"):
        raise ValueError("candidate source patch integrity mismatch")
    required=("modified_kaffeine/CMakeLists.txt","modified_kaffeine/COPYING",
              "selected/source/installed-package/kaffeine_next/patch_upstream.py",
              "build_scripts/media-stable-first.sh","build_scripts/preview_safety.py",
              "patches/kaffeine-from-pinned-upstream.patch")
    absent=[p for p in required if not (candidate/p).is_file()]
    if absent: raise ValueError("incomplete source candidate: "+repr(absent))
    model_manifest=json.loads((repo/"docs/compliance/AI_MODEL_LICENSES_19.json").read_text())
    models_ok(model_manifest)
    spdx=json.loads((repo/"docs/compliance/SPDX_SOURCES_19.spdx.json").read_text())
    if len(spdx["files"])!=133 or any(x["licenseConcluded"]!="NOASSERTION" for x in spdx["files"]):
        raise ValueError("SPDX invented per-file license conclusions")
    bundled=weights(release/"py")
    if bundled: raise ValueError("model files were unexpectedly bundled")
    py=sorted([{"name":m.metadata.get("Name"),"version":m.version,
                "license_metadata":m.metadata.get("License") or "NOASSERTION",
                "installed_environment_only":True}
               for m in importlib.metadata.distributions() if m.metadata.get("Name")],
              key=lambda x:x["name"].lower())
    evidence={
        "schema":"MEDIA-DISTRIBUTION-COMPLIANCE-23 v1","tested_exact_head":head,
        "integrated_baseline":BASE,"frozen_source_commit":FROZEN,
        "disposable_runner_only":True,
        "native_binary":{"sha256":digest(native),"size_bytes":native.stat().st_size,
                         "elf_direct_needed":direct,"ldd_resolved":resolved,
                         "unresolved_runtime":sorted(x["soname"] for x in resolved if not x["resolved"])},
        "native_apt_package_metadata":[pkg(x) for x in APT],
        "python_runner_distribution_metadata":py,
        "python_wheel_graph_complete":False,
        "source_candidate":candidate_manifest,
        "source_candidate_required_missing":absent,
        "actual_corresponding_source_provided_to_binary_recipient":False,
        "actual_binary_notices":notices(release),
        "selected_source_spdx_header_gaps":spdx_headers(candidate/"selected/source/installed-package"),
        "file_license_conclusions_unverified":133,
        "model_ledger_count":len(model_manifest["models"]),
        "bundled_model_files":bundled,
        "nllb_license":"CC-BY-NC-4.0",
        "audeering_license":"CC-BY-NC-SA-4.0",
        "limits":["NO final GPL source offer","NO actual final distro package","NO optional Python wheel resolution",
                  "NO transitive dlopen codec inventory","NO per-file rightsholder clearance",
                  "NO model downloads or inference","NO owner PC, device or private-binary validation"],
        "gates":{"disposable_native_binary":"PASS","observed_runtime_link_metadata":"PASS_WITH_GAPS",
                 "observed_runner_python_metadata":"PASS_WITH_GAPS",
                 "reconstructed_source_candidate":"PASS_AS_CANDIDATE_ONLY",
                 "complete_corresponding_source_delivery":"HOLD",
                 "real_binary_notice_delivery":"HOLD",
                 "file_level_license_rights":"HOLD",
                 "noncommercial_model_redistribution":"HOLD",
                 "owner_hardware_and_inference":"NOT_RUN",
                 "public_release":"HOLD"}
    }
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
    return evidence

def verify(e):
    g=e["gates"]
    for p in ("complete_corresponding_source_delivery","real_binary_notice_delivery",
              "file_level_license_rights","noncommercial_model_redistribution","public_release"):
        if g[p]!="HOLD": raise ValueError("unsafe gate: "+p)
    if (e["bundled_model_files"] or e["selected_source_spdx_header_gaps"]["total"]!=133 or
        not e["native_binary"]["elf_direct_needed"] or e["source_candidate_required_missing"]):
        raise ValueError("evidence missing, model accidentally bundled or incomplete file tree")
    return True

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="cmd",required=True)
    a=sub.add_parser("reconstruct");a.add_argument("--repo",required=True);a.add_argument("--candidate",required=True)
    a=sub.add_parser("collect")
    for name in ("repo","release","candidate","output"): a.add_argument("--"+name,required=True)
    a=sub.add_parser("verify");a.add_argument("--evidence",required=True)
    args=p.parse_args()
    if args.cmd=="reconstruct":
        m=source_candidate(args.repo,args.candidate)
        print("SOURCE CANDIDATE reconstructed, not supplied to recipients; HOLD",m["patch_sha256"])
    elif args.cmd=="collect":
        e=collect(args.repo,args.release,args.candidate,args.output);verify(e)
        print("DISPOSABLE ELF + SBOM EVIDENCE RECORDED; PUBLIC RELEASE HOLD",e["native_binary"]["sha256"])
    else:
        verify(json.loads(Path(args.evidence).read_text()));print("FAIL-CLOSED SCHEMA PASS; RELEASE HOLD")
if __name__=="__main__": main()
