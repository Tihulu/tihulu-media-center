# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline output-language catalog for the native Kaffeine subtitle picker.

Discover locally installed Argos language pairs and local NLLB/MADLAD weights.
DeepL is a separately labelled ONLINE API, never a local language pack.
The optional --fast pass avoids slow Argos imports and yields an immediate
list. Existence on disk is not evidence of successful model inference.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from .language_codes import language_code

NAMES = {
    "de":"German", "en":"English", "tr":"Turkish", "fr":"French",
    "es":"Spanish", "it":"Italian", "nl":"Dutch", "pl":"Polish",
    "pt":"Portuguese", "ru":"Russian", "uk":"Ukrainian", "ar":"Arabic",
    "ja":"Japanese", "ko":"Korean", "zh":"Chinese", "hi":"Hindi",
    "sv":"Swedish", "da":"Danish", "fi":"Finnish", "el":"Greek",
    "cs":"Czech", "ro":"Romanian", "hu":"Hungarian", "bg":"Bulgarian",
}

def catalog(*, installed_pairs=None, nllb_installed=None,
            madlad_installed=None, deepl_configured=None,
            scan_argos=True):
    errors = []
    if installed_pairs is None and not scan_argos:
        installed_pairs = []
    if installed_pairs is None:
        try:
            from .argos_market_bridge import run
            # PyTorch/Argos cold imports can block for up to a minute in
            # the normal Model Market. A caption language menu must not.
            # This is a read-only, local probe with a strict short deadline.
            installed_pairs = run("installed", installed_timeout=8.0)
        except (OSError, RuntimeError, ValueError, KeyError,
                subprocess.TimeoutExpired) as exc:
            installed_pairs = []
            errors.append("Argos package discovery unavailable: "+str(exc)[:150])
    if nllb_installed is None:
        try:
            from .translation_market import TranslationModelMarket
            nllb_installed = bool(TranslationModelMarket().status()["installed"])
        except (OSError, RuntimeError, ValueError) as exc:
            nllb_installed = False
            errors.append("NLLB status unavailable: "+str(exc)[:120])
    if madlad_installed is None:
        try:
            from .translation_madlad import MadladMarket
            madlad_installed = bool(MadladMarket().status()["installed"])
        except (OSError, RuntimeError, ValueError) as exc:
            madlad_installed = False
            errors.append("MADLAD status unavailable: "+str(exc)[:120])
    if deepl_configured is None:
        try:
            from .deepl_api import read_key
            deepl_configured=bool(read_key())
        except (OSError,ValueError,RuntimeError) as exc:
            deepl_configured=False
            errors.append("DeepL API key unavailable: "+str(exc)[:100])
    destinations = {}
    for pair in installed_pairs:
        if not isinstance(pair, dict):
            continue
        try:
            source = language_code(pair.get("source", ""))
            target = language_code(pair.get("target", ""))
        except ValueError:
            continue
        if source != target:
            destinations.setdefault(target, set()).add("Argos")
    if nllb_installed:
        from .translation_market import LANG
        for code in LANG:
            destinations.setdefault(code, set()).add("NLLB (weights present)")
    if madlad_installed:
        # MADLAD has broad language coverage, but the actual installed
        # tokenizer must verify its <2xx> token at inference time. Offer
        # commonly used codes; arbitrary supported ISO codes remain
        # enterable in the advanced target-language field.
        for code in NAMES:
            destinations.setdefault(code, set()).add("MADLAD (weights present)")
    if deepl_configured:
        # Only the familiar baseline targets are advertised as candidates
        # without calling the authenticated DeepL Languages API. This
        # NEVER claims that DeepL is installed or usable offline.
        for code in ("de","en","tr","fr"):
            destinations.setdefault(code, set()).add(
                "DeepL API (online; configured key, target unverified)")
    return {
        "languages":[{"code":code,"label":NAMES.get(code,code.upper()),
                      "engines":sorted(engines),
                      "verified_by_runtime":False}
                     for code,engines in sorted(
                         destinations.items(),
                         key=lambda pair:(pair[0] not in ("en","tr","de","fr"),
                                          pair[0]))],
        "installed_argos_pairs":len([
            x for x in installed_pairs if isinstance(x,dict)]),
        "nllb_present":bool(nllb_installed),
        "madlad_present":bool(madlad_installed),
        "deepl_online_key_configured":bool(deepl_configured),
        "scan_argos":bool(scan_argos),
        "errors":errors,
        "note":"A model package on disk does not prove translation for the current spoken language. No downloads.",
    }


def main(argv=None):
    parser=argparse.ArgumentParser(
        description="Read installed/offline and explicitly remote translator destinations")
    parser.add_argument("--fast",action="store_true",
        help="Skip potentially slow Argos Python import; inspect local NLLB/MADLAD and DeepL key only")
    args=parser.parse_args(argv)
    print(json.dumps(catalog(scan_argos=not args.fast),ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
