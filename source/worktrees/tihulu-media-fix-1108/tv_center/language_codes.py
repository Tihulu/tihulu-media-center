"""Validate user-selected languages without advertising nonexistent models.

Speech-source engines may support fewer languages than the offline translator.
ISO 639-1/639-2 codes are accepted for Argos; explicit NLLB language/script
tags are accepted for NLLB only and verified against its tokenizer at runtime.
"""
from __future__ import annotations
import re

# Common TV-language ISO-639-2 aliases map to the ISO-639-1 code used by
# Argos. Other valid 3-letter language codes are kept unchanged.
# ISO 639-1 vocabulary. Invalid placeholders such as 'zz' are rejected
# rather than being mistaken for a language whose model is unavailable.
ISO_639_1 = frozenset("""
aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs
ca ce ch co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff
fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id
ie ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku
kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my
na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu
rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv
sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo
wa wo xh yi yo za zh zu
""".split())

_ALIASES = {
    "deu":"de", "ger":"de", "eng":"en", "tur":"tr",
    "fra":"fr", "fre":"fr", "spa":"es", "ita":"it",
    "nld":"nl", "dut":"nl", "pol":"pl", "por":"pt",
    "rus":"ru", "ukr":"uk", "ara":"ar", "zho":"zh",
    "chi":"zh", "jpn":"ja", "kor":"ko", "hin":"hi",
    "swe":"sv", "nor":"no", "dan":"da", "fin":"fi",
    "ell":"el", "gre":"el", "ces":"cs", "cze":"cs",
    "ron":"ro", "rum":"ro", "hun":"hu", "slk":"sk",
    "slo":"sk", "bul":"bg", "hrv":"hr", "srp":"sr",
    "cat":"ca", "heb":"he", "ind":"id", "vie":"vi",
    "tha":"th",
}


def language_code(code: str, *, nllb: bool = False) -> str:
    if not isinstance(code, str):
        raise ValueError("Choose an ISO language code such as es, pl, ar or ja")
    value = code.strip()
    if nllb and re.fullmatch(r"[a-z]{3}_[A-Z][a-z]{3}", value):
        return value
    value = value.lower().replace("-", "_")
    if not re.fullmatch(r"[a-z]{2,3}", value):
        raise ValueError("Language must be a 2/3-letter ISO code; NLLB also accepts eng_Latn")
    normalized = _ALIASES.get(value, value)
    if len(normalized) == 2 and normalized not in ISO_639_1:
        raise ValueError(f"Unknown ISO language code: {value}")
    return normalized


def translation_language(code: str) -> bool:
    try:
        return bool(language_code(code, nllb=True))
    except ValueError:
        return False
