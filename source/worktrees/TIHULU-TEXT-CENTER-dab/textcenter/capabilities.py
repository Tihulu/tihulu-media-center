"""Explicit feature contracts and deployment gates for the entire Text Center scope.

All entries are represented, even when the decoder/hardware/rights/integration
is NOT available. This catalogue is not a list of working live receivers.
"""
from __future__ import annotations

# id, family, label, implementation state, required condition, intended output
CAPABILITIES = (
    ("fm_rds", "Broadcast radio", "FM RDS / RadioText",
     "manual_capture", "RTL2832U plus rtl_fm and redsea; exclusive SDR lease",
     "PS, station names and source-attributed RadioText"),
    ("fm_rtplus", "Broadcast radio", "FM RadioText+",
     "manual_capture", "RT+ capable redsea output and broadcaster-provided structured tags",
     "Artist, song, programme type and associated running metadata"),
    ("fm_tmc", "Broadcast radio", "FM TMC / traffic data",
     "planned", "Compatible licensed/authorized TMC decoder and local rules",
     "Traffic information, without falsely promoting it as live authority"),
    ("dab_dls", "Broadcast radio", "DAB+ DLS / DLS+",
     "decoder_import", "DAB-capable receiver and a verified metadata decoder",
     "Dynamic label text, programmes, titles and station metadata"),
    ("dab_journaline", "Broadcast radio", "DAB+ / DRM Journaline",
     "licensed_decoder_needed", "Broadcast service, compliant decoder and Journaline licensing",
     "Hierarchical menus, stored news pages and service information"),
    ("dab_mot", "Broadcast radio", "DAB+ MOT Slideshow",
     "planned", "DAB ensemble carrying MOT image data plus tested image decoder",
     "Image slides with correct broadcast provenance"),
    ("dab_epg", "Broadcast radio", "DAB+ EPG / SPI",
     "planned", "DAB decoder supporting programme/service information",
     "Schedule and programme guide"),
    ("dab_tpeg", "Broadcast radio", "DAB+ TPEG",
     "planned", "Actual TPEG service and compatible rights/decoder",
     "Structured traffic and travel information"),
    ("dvb_teletext", "Television", "DVB-T2 Teletext",
     "decoder_import", "A working DVB frontend, TS capture and Teletext PID decoder",
     "Real numbered/subpages, packet-derived attribution and timestamp"),
    ("hbbtv", "Television", "HbbTV links",
     "planned", "Compatible broadcaster URL extraction, security assessment and browser",
     "Linked broadcast companion services, not native Teletext replacement"),
    ("drm", "HF / receiver text", "DRM digital radio / EWF",
     "decoder_import", "HF SDR antenna, DRM demodulator, EWF decoder and provenance",
     "DRM service text and warnings without unauthenticated alert promotion"),
    ("rtty", "HF / receiver text", "RTTY / Radiotelex",
     "decoder_import", "Q-branch HF antenna and suitable RTTY decoder",
     "DWD/Pinneberg and other scheduled text bulletins"),
    ("navtex", "HF / receiver text", "NAVTEX 518/490 kHz",
     "decoder_import", "Suitable LF antenna, Q-branch and SITOR-B/NAVTEX decoder",
     "Marine safety/weather messages with time and source attribution"),
    ("weatherfax", "HF / receiver text", "HF WeatherFAX / WEFAX",
     "planned", "HF antenna, weatherfax decoder and image storage",
     "Weather map images and source/capture records"),
    ("aprs", "HF / receiver text", "APRS / AX.25 receive-only",
     "decoder_import", "VHF-capable receiver, proper packet decoder and privacy controls",
     "Publicly receivable amateur location and text packets (RX only)"),
    ("rss_atom", "Text internet", "RSS / Atom feeds",
     "implemented", "Operator-added public HTTPS feed, explicit on-demand refresh",
     "Searchable cached feed items with source URL"),
    ("json_feed", "Text internet", "JSON Feed 1 / 1.1",
     "implemented", "Operator-added public HTTPS JSON Feed and on-demand refresh",
     "Searchable text items, no automatic downloads"),
    ("news_politics", "Text internet", "Shared News & Politics Center feeds",
     "integration_required", "Survival Kit-owned DE/TR source catalogue and filtering API",
     "Single source of truth for international/political feeds"),
    ("gemini", "Text internet", "Gemini text network",
     "directory_only", "Bounded authenticated certificate-aware Gemini client",
     "Low-bandwidth pages and offline snapshots"),
    ("gopher", "Text internet", "Gopher text network",
     "directory_only", "Safe bounded read-only Gopher client and protocol parser",
     "Low-bandwidth menus and cached pages"),
    ("external_bbs", "Text internet", "External BBS (SSH/Telnet/HTTP)",
     "directory_only", "Restricted client sandbox, credential and network security policy",
     "Text BBS session viewer; no unsafe generic terminal proxy"),
    ("local_board", "Messaging", "Local bulletin board",
     "single_owner_only", "Loopback access only; auth+per-user ACL for LAN/phones",
     "Offline local notes and announcements"),
    ("meshtastic", "Messaging", "Meshtastic LoRa messages",
     "separate_tx_hardware_required", "Compatible LoRa transceiver, approved region and explicit TX consent",
     "Offline peer messaging; RTL-SDR does not transmit"),
    ("aprs_tx", "Messaging", "APRS / AX.25 transmit",
     "separate_tx_hardware_required", "Authorized ham transmitter and licence where needed",
     "Explicit two-way amateur packet radio; never activated by default"),
    ("official_cap", "Safety & trust", "Official CAP / BBK / AFAD alerts",
     "integration_required", "Trusted verified Emergency Center alert data and freshness",
     "Authority-verified warnings distinct from unverified broadcast messages"),
    ("offline_wiki", "Offline library", "Offline Wikipedia / guides",
     "integration_required", "Survival Kit offline Wiki/Files/Browser API",
     "Read-only linked articles; no duplicated wiki index"),
    ("offline_feeds", "Offline library", "Saved articles / imported RF archive",
     "implemented", "Local SQLite archive and source metadata",
     "Cached content, search and bookmarks"),
    ("translate_ai", "Processing", "Translation then optional local AI",
     "integration_required", "Survival Kit Translator and hardware-aware AI service",
     "User-triggered multilingual translation and source-preserving summaries"),
    ("region_presets", "Platform", "Regional frequency/service catalogue",
     "integration_required", "Versioned Survival Kit region/channel registry",
     "DE/TR regional choices with optional downloaded datasets"),
    ("tihulu_portal", "Platform", "tihulu.lan mobile/desktop portal",
     "integration_required", "Authenticated TLS same-origin route, session ACL and base path",
     "Responsive phone/desktop use without exposing the unauthenticated backend"),
    ("receiver_broker", "Platform", "Shared Radio/Flight Radar SDR lease broker",
     "integration_required", "Survival Kit authoritative lease API and recording priority",
     "Never preempt Flight Radar, SDR recording or TV tuning"),
)


def capability_catalog(inventory: dict | None = None) -> list[dict]:
    """Read-only catalogue; installed tools != proven receiver lock or reception."""
    inv = inventory or {}
    decoders = inv.get("decoders") or {}
    values = []
    for identifier, group, title, state, required, output in CAPABILITIES:
        item = {
            "id":identifier, "group":group, "title":title,
            "state":state, "requirements":required, "purpose":output,
            "live_verified":False,
        }
        if identifier == "fm_rds":
            item["dependency_status"] = {
                "rtl_usb_detected": bool(inv.get("rtl_usb_count")),
                "rtl_fm_installed": bool(decoders.get("rtl_fm")),
                "redsea_installed": bool(decoders.get("redsea")),
                "process_conflict_detected": bool(inv.get("receiver_conflicts")),
            }
        if identifier == "dvb_teletext":
            item["dependency_status"] = {
                "dvb_frontend_detected": bool(inv.get("dvb_frontends")),
                "teletext_decoder_connected":False,
            }
        if identifier in ("dab_dls","dab_journaline","dab_mot","dab_epg","dab_tpeg"):
            item["dependency_status"] = {
                "welle_cli_installed":bool(decoders.get("welle-cli")),
                "live_dab_metadata_connected":False,
            }
        values.append(item)
    return values
