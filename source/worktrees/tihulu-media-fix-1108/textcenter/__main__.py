"""CLI: foreground local server, explicit feed registration, decoder JSON import."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import os

from .core import Store
from .media import MediaStore
from .dvb_hardware import diagnose_dvb
from .receivers import receiver_inventory
from .capabilities import capability_catalog
from .http_app import run_server


def default_db() -> Path:
    return Path(os.environ.get("TIHULU_TEXT_DB", str(Path.home() / ".local/share/tihulu-text-center/text-center.db")))


def main():
    parser = argparse.ArgumentParser(prog="python -m textcenter")
    sub = parser.add_subparsers(dest="command")
    server = sub.add_parser("serve", help="Start loopback-only web application")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8787)
    server.add_argument("--db", type=Path, default=default_db())
    importer = sub.add_parser("import-text", help="Import attributed decoder-produced JSON")
    importer.add_argument("--db", type=Path, default=default_db())
    importer.add_argument("--file", type=Path, required=True)
    image_import = sub.add_parser("import-media", help="Import real decoder-exported PNG/JPEG DAB MOT or RDS2 images")
    image_import.add_argument("--db",type=Path,default=default_db())
    image_import.add_argument("--file",type=Path,required=True)
    feed = sub.add_parser("add-feed", help="Register a trusted HTTPS RSS/Atom feed")
    feed.add_argument("--db", type=Path, default=default_db())
    feed.add_argument("--title", required=True)
    feed.add_argument("--url", required=True)
    template = sub.add_parser("make-template", help="Create an EMPTY decoder import JSON file (no simulated RF data)")
    template.add_argument("--file", type=Path, default=Path("decoded-pages.json"))
    doctor = sub.add_parser("doctor", help="Show current local installation and archive status")
    doctor.add_argument("--db", type=Path, default=default_db())
    sub.add_parser("receivers", help="Passively inspect local RTL USB, DVB and decoder tools; no RF tuning")
    sub.add_parser("dvb-diagnose",help="Passively inspect Hauppauge USB, DVB frontends, and firmware")
    args = parser.parse_args()
    if args.command is None:
        args.command = "serve"
        args.host, args.port, args.db = "127.0.0.1", 8787, default_db()
    if args.command == "serve":
        if args.host != "127.0.0.1":
            parser.error("Only --host 127.0.0.1 is permitted; use an authenticated TLS reverse proxy for LAN access")
        if not 1 <= args.port <= 65535:
            parser.error("Port must be 1–65535")
        run_server(Store(args.db), host=args.host, port=args.port)
    elif args.command == "import-media":
        try:
            raw=args.file.read_bytes()
            if len(raw)>14_000_000:
                parser.error("Decoder-media import file exceeds 14 MB")
            results=MediaStore(Store(args.db)).import_images(json.loads(raw))
        except (OSError,ValueError,TypeError) as exc:
            parser.error(f"Cannot import broadcast decoder images: {exc}")
        print(json.dumps(results,indent=2))
    elif args.command == "import-text":
        try:
            content = args.file.read_bytes()
        except FileNotFoundError:
            parser.error(
                f"Import file not found: {args.file}. This is not an included live-data file. "
                "Use an actual decoder export, or run 'python3 -m textcenter make-template' "
                "for an EMPTY JSON template (no radio data)."
            )
        except OSError as exc:
            parser.error(f"Cannot read import file: {exc}")
        if len(content) > 4_000_000:
            parser.error("Import file exceeds four-megabyte limit")
        try:
            data = json.loads(content)
            imported = Store(args.db).import_data(data)
        except (ValueError, TypeError, KeyError) as exc:
            parser.error(f"Invalid decoder import: {exc}")
        print(json.dumps(imported, indent=2))
    elif args.command == "make-template":
        if args.file.exists():
            parser.error(f"Refusing to overwrite existing file: {args.file}")
        args.file.write_text(
            json.dumps({"schema_version": 1, "pages": [], "events": []}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Created EMPTY import template: {args.file} (0 RF records).")
        print("Fill it ONLY with genuine attributed output from an external decoder.")
    elif args.command == "receivers":
        print(json.dumps(receiver_inventory(), indent=2))
    elif args.command == "dvb-diagnose":
        print(json.dumps(diagnose_dvb(),indent=2))
    elif args.command == "doctor":
        store = Store(args.db)
        print(json.dumps({
            "application": "TIHULU TEXT CENTER",
            "database": str(store.filename.resolve()),
            "local_web_url": "http://127.0.0.1:8787/",
            "counts": store.counts(),
            "network_polling": "off_by_default",
            "rf_decoder": "manual_fm_rds_available_if_rtl_fm_and_redsea_installed",
            "fm_spectrum_survey": "manual_if_rtl_power_installed_and_device_free",
            "hardware_inventory": receiver_inventory(),
            "capabilities_tracked": len(capability_catalog()),
            "data_provenance_warning": "USB detected is not RF reception; spectrum peaks are not named stations",
            "how_to_start": "python3 -m textcenter serve",
        }, indent=2))
    elif args.command == "add-feed":
        print("Registered feed:", Store(args.db).add_feed(args.title, args.url))


if __name__ == "__main__":
    main()
