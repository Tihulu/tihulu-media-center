"""Per-feature scan & discovery readiness without fabricated reception.

A passive check exists for every feature in the requested catalogue. A
user-initiated rtl_power *energy* survey exists only for known RF bands.
It never decodes DAB/DRM/RTTY/APRS/NAVTEX by itself and cannot search online
protocols via the antenna. DVB requires separate frontend/service management.
"""
from __future__ import annotations

from .capabilities import capability_catalog
from .fm_survey import SURVEY_BANDS

SPECTRUM_FEATURES = {
    "fm_rds": "fm", "fm_rtplus": "fm", "fm_tmc": "fm",
    "dab_dls": "dab", "dab_journaline": "dab",
    "dab_mot": "dab", "dab_epg": "dab", "dab_tpeg": "dab",
    "drm": "drm", "rtty": "rtty", "navtex": "navtex",
    "weatherfax": "weatherfax", "aprs": "aprs",
}
DVB_FEATURES = frozenset({"dvb_teletext", "hbbtv"})
NETWORK_FEATURES = frozenset({
    "rss_atom", "json_feed", "news_politics", "gemini", "gopher",
    "external_bbs", "tihulu_portal",
})
OFFLINE_FEATURES = frozenset({"offline_wiki", "offline_feeds", "local_board"})
TX_FEATURES = frozenset({"meshtastic", "aprs_tx"})


def scan_capabilities(inventory: dict, survey) -> list[dict]:
    """One row for each feature: passive inventory + honest action constraints."""
    results=[]
    readiness_cache: dict[str, dict] = {}
    for feature in capability_catalog(inventory):
        fid=feature["id"]
        row = {
            "id":fid, "title":feature["title"], "group":feature["group"],
            "implementation":feature["state"],"requirements":feature["requirements"],
            "medium":"unknown", "scan_type":"passive_dependency",
            "can_survey_now":False, "can_decode_now":False,
            "band":None, "band_label":None, "reason":"",
        }
        if fid in SPECTRUM_FEATURES:
            band=SPECTRUM_FEATURES[fid]
            p=SURVEY_BANDS[band]
            if band not in readiness_cache:
                readiness_cache[band] = survey.availability(band)
            availability=readiness_cache[band]
            row.update({
                "medium":"rf_receiver", "scan_type":"rf_spectrum",
                "band":band,"band_label":p["label"],
                "can_survey_now":bool(availability.get("ready")),
                "can_decode_now":False,
                "reason":availability["reason"] + (
                    ". Spectrum is energy-only; dedicated protocol decoder not connected."
                    if fid not in ("fm_rds","fm_rtplus") else
                    ". Confirm any candidate separately with explicit rtl_fm/redsea decoding."
                ),
            })
        elif fid in DVB_FEATURES:
            available=bool(inventory.get("dvb_frontends"))
            tools=bool(inventory.get("decoders",{}).get("dvbv5-scan"))
            row.update({
                "medium":"dvb_receiver","scan_type":"dvb_service_adapter_pending",
                "reason":("DVB frontend present; " if available else "No DVB frontend; ") +
                         ("dvbv5-scan installed; " if tools else "dvbv5-scan missing; ") +
                         "safe tuner-lease aware service/PID scanner and actual Teletext decoder not connected",
            })
        elif fid in NETWORK_FEATURES:
            ready=fid in ("rss_atom","json_feed")
            row.update({
                "medium":"internet_only", "scan_type":"cache_check",
                "can_decode_now":ready,
                "reason":"Internet URL is NOT an RF channel. "+
                         ("Feeds may be fetched on explicit request and read from cache offline."
                          if ready else "Native client/gateway integration pending; external site requires internet."),
            })
        elif fid in OFFLINE_FEATURES:
            row.update({
                "medium":"local_archive","scan_type":"local_check",
                "reason":"Uses local stored data only; no RF antenna or internet needed when cached.",
            })
        elif fid in TX_FEATURES:
            row.update({
                "medium":"separate_radio_hardware","scan_type":"hardware_dependency",
                "reason":"An RTL-SDR cannot transmit; a distinct authorized transceiver and integration are required.",
            })
        else:
            row.update({
                "medium":"shared_service","scan_type":"integration_dependency",
                "reason":"Requires existing Survival Kit service integration; no independent antenna scan.",
            })
        results.append(row)
    return results
