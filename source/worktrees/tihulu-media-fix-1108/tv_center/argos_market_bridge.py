"""Owner-initiated Argos language market in the *actual installed venv*.

The PyQt process runs under system Python, while Argos is provisioned in an
isolated venv. This bridge makes online catalog/installation use the same
runtime the subtitle worker uses, with explicit user choice and no shell.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys

from .language_codes import language_code, translation_language

ACTIONS=("catalog","installed","install","remove")


def run(action,source="de",target="tr"):
    if action not in ACTIONS:
        raise ValueError("Invalid Argos Market command")
    source, target = language_code(source), language_code(target)
    if action in ("install","remove") and source==target:
        raise ValueError("Choose distinct source/target languages")
    from .runtime import AIRuntime
    rt=AIRuntime().status()
    if not rt["installed"]:
        raise RuntimeError("Argos engine missing; install starter bundle or Argos runtime first")
    root=str(Path(__file__).resolve().parent.parent)
    env=os.environ.copy()
    env["PYTHONPATH"]=root+os.pathsep+env.get("PYTHONPATH","")
    proc=subprocess.run(
        [rt["python"],"-m","tv_center.argos_market_bridge",
         "--worker",action,source,target],
        cwd=root,env=env,stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=1800 if action=="install" else 60,check=False)
    if proc.returncode:
        raise RuntimeError("Argos Market: "+
            proc.stderr.decode("utf-8","replace")[-400:])
    try:
        result=json.loads(proc.stdout.decode("utf-8","replace"))
    except (ValueError,UnicodeError) as exc:
        raise RuntimeError("Invalid Argos runtime response") from exc
    return result


def worker(action,source,target):
    from argostranslate import package
    if action=="catalog":
        package.update_package_index()
        result=[{"source":p.from_code,"target":p.to_code,
                 "name":str(p),"version":str(getattr(p,"package_version",""))}
                for p in package.get_available_packages()
                if p.from_code != p.to_code
                and all(translation_language(code) for code in (p.from_code,p.to_code))
                and getattr(p,"type","translate")=="translate"]
    elif action=="installed":
        result=[{"source":p.from_code,"target":p.to_code,
                 "name":str(p)} for p in package.get_installed_packages()
                 if all(language_code(code) for code in (p.from_code,p.to_code))]
    elif action=="install":
        existing={(p.from_code,p.to_code)
                  for p in package.get_installed_packages()}
        if (source,target) in existing:
            result={"status":"already installed","pair":source+"→"+target}
        else:
            package.update_package_index()
            candidate=next((p for p in package.get_available_packages()
                            if p.from_code==source and p.to_code==target
                            and getattr(p,"type","translate")=="translate"),None)
            if candidate is None:
                raise RuntimeError("No direct Argos package in official index for "+
                                   source+"→"+target+"; try English-pivot packs")
            archive=candidate.download()
            package.install_from_path(archive)
            result={"status":"installed","pair":source+"→"+target}
    elif action=="remove":
        found=[p for p in package.get_installed_packages()
               if p.from_code==source and p.to_code==target]
        if len(found)!=1:
            raise RuntimeError("Expected one installed Argos package")
        loc=Path(found[0].package_path).resolve()
        if not loc.is_relative_to(Path.home().resolve()):
            raise RuntimeError("Refusing removal of external package")
        package.uninstall(found[0])
        result={"status":"removed","pair":source+"→"+target}
    else:
        raise ValueError("Unknown action")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    args=sys.argv[1:]
    if len(args)!=4 or args[0]!="--worker" or args[1] not in ACTIONS:
        raise SystemExit("Invalid Argos worker arguments")
    worker(args[1],args[2],args[3])
