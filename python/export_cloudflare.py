#!/usr/bin/env python3
"""Export the DuckDB database to chunked SQL files for Cloudflare D1.

The DuckDB file remains the local source of truth. This command produces a
disposable, deterministic SQL copy that `wrangler d1 execute --file` can load:

    python python/export_cloudflare.py --db phones.duckdb --out dist/d1

The remote schema lives in cloudflare/migrations/0001_schema.sql. Column lists
here must match it; `--verify-schema` checks that before writing any data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import duckdb

from phone_db import normalize

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "cloudflare" / "migrations" / "0001_schema.sql"

# D1 caps a single SQL statement at roughly 100 KB, so batches stay well under
# that. Files rotate to keep each `wrangler d1 execute --file` upload modest.
MAX_STATEMENT_BYTES = 60_000
MAX_ROWS_PER_STATEMENT = 250
MAX_FILE_BYTES = 4_000_000


@dataclass(frozen=True)
class TableSpec:
    name: str
    source: str
    columns: tuple[str, ...]
    row_id: bool = False
    normalize_text: str | None = None

    @property
    def target_columns(self) -> tuple[str, ...]:
        columns = (("row_id",) if self.row_id else ()) + self.columns
        if self.normalize_text is not None:
            columns += ("norm_text",)
        return columns

    @property
    def select(self) -> str:
        inner = ", ".join(self.columns)
        if not self.row_id:
            return f"SELECT {inner} FROM {self.source}"
        # A deterministic integer key is needed as the FTS5 content_rowid.
        order = ", ".join(self.columns)
        return (
            f"SELECT row_number() OVER (ORDER BY {order}) AS row_id, {inner} "
            f"FROM {self.source} ORDER BY {order}"
        )


PROPERTY_SEARCH_COLUMNS = (
    "property_number",
    "property_name_en",
    "property_name_fr",
    "address_en",
    "address_fr",
    "primary_use_en",
    "interest_type_en",
    "created_date",
    "last_modified_date",
    "parcel_number",
    "province_en",
    "municipality_en",
    "place_name_en",
    "metro_area_en",
    "latitude",
    "longitude",
    "search_text",
)

EXCHANGE_SEARCH_COLUMNS = (
    "npa",
    "nxx",
    "status",
    "pooled",
    "exchange_area",
    "province",
    "company",
    "ocn",
    "date_assigned",
    "remarks",
    "source_url",
    "source_snapshot_date",
    "imported_at",
    "search_text",
)

TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "dfrp_properties",
        "dfrp.properties",
        (
            "property_number",
            "property_name_en",
            "property_name_fr",
            "address_en",
            "address_fr",
            "primary_use_en",
            "primary_use_code",
            "interest_type_en",
            "interest_type_code",
            "restriction_en",
            "created_date",
            "last_modified_date",
            "source_file",
            "imported_at",
        ),
    ),
    TableSpec(
        "dfrp_locations",
        "dfrp.locations",
        (
            "property_number",
            "parcel_number",
            "sgc",
            "fed",
            "location_type",
            "rural_area",
            "province_en",
            "municipality_en",
            "place_name_en",
            "metro_area_en",
            "latitude",
            "longitude",
            "positional_accuracy_m",
            "country_code",
            "source_file",
            "imported_at",
        ),
    ),
    TableSpec(
        "dfrp_structures",
        "dfrp.structures",
        (
            "property_number",
            "parcel_number",
            "structure_number",
            "structure_name_en",
            "address_en",
            "latitude",
            "longitude",
            "construction_year",
            "condition_en",
            "floor_area_sqm",
            "source_file",
            "imported_at",
        ),
    ),
    TableSpec(
        "telephone_co_codes",
        "telephone.co_codes",
        (
            "npa",
            "nxx",
            "status",
            "pooled",
            "exchange_area",
            "province",
            "company",
            "ocn",
            "date_assigned",
            "remarks",
            "source_url",
            "source_snapshot_date",
            "imported_at",
        ),
    ),
    TableSpec(
        "telephone_carriers",
        "telephone.carriers",
        (
            "carrier_id",
            "legal_name",
            "ocn",
            "carrier_type",
            "fixed_line",
            "province_scope",
            "source_url",
            "first_seen",
            "last_seen",
            "notes",
        ),
    ),
    TableSpec(
        "telephone_exchange_assignments",
        "telephone.exchange_assignments",
        (
            "npa",
            "nxx",
            "carrier_id",
            "ocn",
            "exchange_area",
            "province",
            "status",
            "pooled",
            "date_assigned",
            "source_url",
            "source_snapshot_date",
            "imported_at",
        ),
    ),
    TableSpec(
        "telephone_calling_rules",
        "telephone.calling_rules",
        (
            "rule_id",
            "carrier_id",
            "origin_rate_centre",
            "destination_rate_centre",
            "origin_exchange",
            "destination_exchange",
            "province",
            "service_type",
            "classification",
            "charge_applies",
            "rate_basis",
            "effective_from",
            "effective_to",
            "source_document",
            "source_url",
            "confidence",
            "notes",
        ),
    ),
    TableSpec(
        "telephone_tariff_sources",
        "telephone.tariff_sources",
        (
            "source_id",
            "carrier_id",
            "source_type",
            "title",
            "jurisdiction",
            "url",
            "effective_from",
            "effective_to",
            "status",
            "notes",
        ),
    ),
    TableSpec(
        "property_search",
        "dfrp.property_search",
        PROPERTY_SEARCH_COLUMNS,
        row_id=True,
        normalize_text="search_text",
    ),
    TableSpec(
        "exchange_search",
        "telephone.exchange_search",
        EXCHANGE_SEARCH_COLUMNS,
        row_id=True,
        normalize_text="search_text",
    ),
)


def sql_literal(value: Any) -> str:
    """Render one DuckDB value as a SQLite literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "NULL"
        return repr(value)
    if isinstance(value, (datetime, date)):
        return "'" + value.isoformat() + "'"
    return "'" + str(value).replace("'", "''") + "'"


def iter_rows(con: duckdb.DuckDBPyConnection, spec: TableSpec) -> Iterable[tuple[Any, ...]]:
    cursor = con.execute(spec.select)
    normalise_index = spec.columns.index(spec.normalize_text) if spec.normalize_text else None
    while True:
        chunk = cursor.fetchmany(2000)
        if not chunk:
            return
        for row in chunk:
            if normalise_index is not None:
                # Offset by one when a synthetic row_id leads the row.
                index = normalise_index + (1 if spec.row_id else 0)
                row = row + (normalize(row[index]),)
            yield row


class SqlWriter:
    """Writes chunked, re-runnable SQL files."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.sequence = 0
        self.path: Path | None = None
        self.size = 0
        self.files: list[Path] = []

    def _open(self, name: str) -> None:
        self.sequence += 1
        self.path = self.out_dir / f"data-{self.sequence:03d}-{name}.sql"
        self.size = 0
        self.files.append(self.path)
        header = f"-- Generated by python/export_cloudflare.py — table {name}\n"
        self.path.write_text(header, encoding="utf-8")
        self.size = len(header)

    def start(self, name: str) -> None:
        """Always begin a new file so each table's DML starts on a clean boundary."""
        self._open(name)

    def write(self, name: str, statement: str) -> None:
        if self.path is None or self.size > MAX_FILE_BYTES:
            self._open(name)
        assert self.path is not None
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(statement + "\n")
        self.size += len(statement) + 1

    def write_final(self, name: str, statement: str) -> Path:
        self.sequence += 1
        path = self.out_dir / f"data-{self.sequence:03d}-{name}.sql"
        path.write_text(
            f"-- Generated by python/export_cloudflare.py — {name}\n{statement}\n",
            encoding="utf-8",
        )
        self.files.append(path)
        return path


def export_table(
    con: duckdb.DuckDBPyConnection, writer: SqlWriter, spec: TableSpec
) -> int:
    columns = ", ".join(spec.target_columns)
    writer.start(spec.name)
    writer.write(spec.name, f"DELETE FROM {spec.name};")
    batch: list[str] = []
    batch_bytes = 8 + len(spec.name) + len(columns)
    count = 0
    for row in iter_rows(con, spec):
        batch.append("(" + ", ".join(sql_literal(value) for value in row) + ")")
        batch_bytes += len(batch[-1]) + 2
        count += 1
        if batch_bytes >= MAX_STATEMENT_BYTES or len(batch) >= MAX_ROWS_PER_STATEMENT:
            writer.write(
                spec.name,
                f"INSERT INTO {spec.name} ({columns}) VALUES\n" + ",\n".join(batch) + ";",
            )
            batch = []
            batch_bytes = 8 + len(spec.name) + len(columns)
    if batch:
        writer.write(
            spec.name,
            f"INSERT INTO {spec.name} ({columns}) VALUES\n" + ",\n".join(batch) + ";",
        )
    return count


def schema_columns() -> dict[str, set[str]]:
    """Parse the D1 migration so exporter columns can be checked against it."""
    text = MIGRATION.read_text(encoding="utf-8")
    result: dict[str, set[str]] = {}
    for match in re.finditer(
        r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", text, re.DOTALL
    ):
        table, body = match.group(1), match.group(2)
        columns = set()
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            columns.add(line.split()[0])
        result[table] = columns
    return result


def verify_schema() -> list[str]:
    declared = schema_columns()
    problems = []
    for spec in TABLES:
        if spec.name not in declared:
            problems.append(f"{spec.name}: missing from {MIGRATION}")
        else:
            unknown = set(spec.target_columns) - declared[spec.name]
            if unknown:
                problems.append(
                    f"{spec.name}: columns not in migration: {', '.join(sorted(unknown))}"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Export DuckDB to Cloudflare D1 SQL")
    parser.add_argument("--db", type=Path, default=ROOT / "phones.duckdb")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "d1")
    parser.add_argument(
        "--verify-schema",
        action="store_true",
        help="check exporter columns against the D1 migration only",
    )
    args = parser.parse_args()

    problems = verify_schema()
    if problems:
        for problem in problems:
            print(f"error: {problem}")
        return 1
    if args.verify_schema:
        print(f"schema ok: {len(TABLES)} tables match {MIGRATION.relative_to(ROOT)}")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    for stale in args.out.glob("data-*.sql"):
        stale.unlink()

    con = duckdb.connect(str(args.db), read_only=True)
    writer = SqlWriter(args.out)
    counts: dict[str, int] = {}
    warnings: list[str] = []
    try:
        for spec in TABLES:
            counts[spec.name] = export_table(con, writer, spec)
        duplicates = con.execute(
            """
            SELECT count(*) FROM (
                SELECT rule_id FROM telephone.calling_rules
                 GROUP BY rule_id HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
        if duplicates:
            warnings.append(
                f"telephone_calling_rules has {duplicates} duplicated rule_id values; "
                "the D1 table keeps them but cannot enforce a primary key on rule_id."
            )
    finally:
        con.close()

    rebuild = "\n".join(
        [
            "INSERT INTO property_search_fts(property_search_fts) VALUES('rebuild');",
            "INSERT INTO exchange_search_fts(exchange_search_fts) VALUES('rebuild');",
            "INSERT INTO property_search_fts(property_search_fts) VALUES('optimize');",
            "INSERT INTO exchange_search_fts(exchange_search_fts) VALUES('optimize');",
        ]
    )
    writer.write_final("fts", rebuild)

    total_bytes = sum(path.stat().st_size for path in writer.files)
    manifest = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "database": str(args.db),
        "counts": counts,
        "rows": sum(counts.values()),
        "files": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in writer.files
        ],
        "total_bytes": total_bytes,
        "warnings": warnings,
    }
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(json.dumps({"counts": counts, "rows": manifest["rows"], "files": len(writer.files), "bytes": total_bytes, "warnings": warnings}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
