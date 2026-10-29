#!/usr/bin/env python3
"""Build or refresh the local phones.duckdb database."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from phone_db import connect, download_cna, evaluate_call, find_exchanges, find_offices, import_calling_rules, import_cna, import_dfrp, property_telephone, seed_reference_calling_rules, seed_tariff_sources


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Federal property and Canadian exchange database")
    parser.add_argument("--db", type=Path, default=root / "phones.duckdb")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--xml", type=Path, default=root / "dfrp-rbif.xml")
    build.add_argument("--cna", type=Path, default=root / "data/raw/cna/COCodeStatus_ALL.csv")
    build.add_argument("--refresh-cna", action="store_true")
    rules = sub.add_parser("import-rules")
    rules.add_argument("csv", type=Path)
    call = sub.add_parser("call")
    call.add_argument("carrier_id")
    call.add_argument("origin_rate_centre")
    call.add_argument("destination_rate_centre")
    call.add_argument("--service-type", default="standard_landline")
    call.add_argument("--date")
    office = sub.add_parser("office")
    office.add_argument("query")
    office.add_argument("--minimum-score", type=float, default=0.35)
    office.add_argument("--limit", type=int, default=25)
    exchange = sub.add_parser("exchange")
    exchange.add_argument("query")
    exchange.add_argument("--minimum-score", type=float, default=0.35)
    exchange.add_argument("--limit", type=int, default=25)
    prop = sub.add_parser("property")
    prop.add_argument("property_number")
    args = parser.parse_args()

    if args.command == "build":
        if args.refresh_cna or not args.cna.exists():
            args.cna = download_cna(args.cna.with_suffix(".zip"))
        with connect(args.db) as con:
            print(json.dumps({"dfrp": import_dfrp(con, args.xml), "cna_records": import_cna(con, args.cna), "tariff_sources": seed_tariff_sources(con), "reference_calling_rules": seed_reference_calling_rules(con)}, indent=2, default=str))
        return 0

    if args.command == "import-rules":
        with connect(args.db) as con:
            print(json.dumps({"calling_rules": import_calling_rules(con, args.csv)}, indent=2))
        return 0

    with connect(args.db) as con:
        if args.command == "office":
            result = find_offices(con, args.query, args.minimum_score, args.limit)
        elif args.command == "exchange":
            result = find_exchanges(con, args.query, args.minimum_score, args.limit)
        elif args.command == "property":
            result = property_telephone(con, args.property_number)
        else:
            result = evaluate_call(con, args.carrier_id, args.origin_rate_centre, args.destination_rate_centre, args.service_type, args.date)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
