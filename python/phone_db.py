"""Python interface for the Canadian phone/property DuckDB database."""

from __future__ import annotations

import csv
import difflib
import re
import tempfile
import unicodedata
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import duckdb


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "sql" / "schema.sql"
CNA_ZIP_URL = "https://www.cnac.ca/data/COCodeStatus_ALL.zip"
TARIFF_SOURCES = [
    ("cnac-co-codes", None, "numbering", "CNA CO Code Status", "Canada", "https://www.cnac.ca/co_codes/co_code_status.htm", None, None, "active", "NPA/NXX assignment source; not a local-calling tariff."),
    ("crtc-tariffs", None, "regulatory_tariff", "CRTC Tariff Notices and Decisions", "Canada", "https://crtc.gc.ca/eng/archive.htm", None, None, "active", "Authoritative source for approved tariff filings and effective dates."),
    ("bell-general-tariff", "8051", "carrier_tariff", "Bell Canada General Tariff", "Ontario and Quebec", "https://www.bell.ca/styles/common/all_languages/all_regions/pdf/BellBusinessReg.pdf", None, None, "reference", "Verify the applicable item and effective tariff revision."),
    ("bell-long-distance", "8051", "rate_table", "Bell Home Phone Basic Long Distance Rates", "Ontario and Quebec", "https://www.bell.ca/Home_phone/Long_distance_rates", None, None, "reference", "Distance-based long-distance rates; local calls are excluded."),
    ("bell-aliant-general-tariff", None, "carrier_tariff", "Bell Aliant General Tariff", "Atlantic Canada", "https://bellaliant.bell.ca/binaries/content/assets/common_en/pdf/tariffs/bell-aliant-general-tariff.pdf", None, None, "reference", "Bell Aliant is tracked separately from Bell Canada."),
    ("telus-tariffs", None, "carrier_tariff", "TELUS Canadian tariffs and local calling area archive", "British Columbia, Alberta, Quebec", "https://www.telus.com/en/about/policies-and-disclosures/tariffs", None, None, "reference", "TELUS publishes tariff and local-calling-area materials by operating company."),
    ("sasktel-tariffs", None, "carrier_tariff", "SaskTel General Tariff", "Saskatchewan", "https://www.sasktel.com/wps/wcm/connect/9f02157e-0de0-43fc-b97a-e160fc683749/table-of-contents-GTBS-21411.pdf", None, None, "reference", "SaskTel tariff source; local calling area definitions must be extracted from applicable items."),
    ("northwestel-general-tariff", None, "carrier_tariff", "Northwestel General Tariff CRTC 3001", "Yukon, Northwest Territories, Nunavut", "https://www.nwtel.ca/sites/default/files/files/Legal-Tariffs/CRTC%203001/crtc-3001-general-tariff1-july-19-2023.pdf", None, None, "reference", "Includes extended area service provisions and northern rate structures."),
    ("eastlink-tariffs", None, "carrier_tariff", "Eastlink tariffs", "Atlantic Canada and other serving areas", "https://www.eastlink.ca/terms-conditions/eastlink-tariffs/", None, None, "reference", "Location-specific tariff selection is required."),
    ("cogeco-regulatory", None, "carrier_tariff", "Cogeco Regulatory Affairs tariffs", "Ontario and Quebec", "https://www.cogeco.ca/en/regulatory-affairs", None, None, "reference", "Cogeco tariff documents define local calling area provisions."),
    ("rogers-access-tariff", None, "carrier_tariff", "Rogers Communications access services tariff", "Canada", "https://www.rogers.com/cms/images/en/RogersCommunicationsGT_CRTC_21530_RogersAccessServicesTariff_July_1_2014.pdf", None, None, "reference", "Use current CRTC/Rogers revision before importing rules."),
    ("videotron-business-long-distance", None, "rate_table", "Videotron business long-distance rates", "Quebec", "https://www.videotron.com/en/business/support/telephony/business-lines/long-distance-calls", None, None, "reference", "Business service terms; do not apply to residential profiles without verification."),
    ("crtc-clec-registry", None, "carrier_registry", "CRTC Competitive Local Exchange Carriers", "Canada", "https://crtc.gc.ca/eng/comm/telecom/eslcclec.htm", None, None, "active", "Registry for Type I, II, III, and IV CLECs."),
    ("crtc-silec-registry", None, "carrier_registry", "CRTC Small Incumbent Local Exchange Carriers", "Canada", "https://crtc.gc.ca/eng/archive/2020/2020-40.htm", None, None, "active", "Regulatory framework identifying small incumbent local exchange carriers."),
    ("crtc-forborne-exchanges", None, "regulatory_list", "CRTC Local Exchanges Forborne List", "Canada", "https://crtc.gc.ca/eng/publications/forbornelist.htm", None, None, "active", "Forbearance affects which local services remain tariff-regulated."),
    ("bell-mts-general-tariff", None, "carrier_tariff", "Bell MTS General Tariff", "Manitoba", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Search CRTC tariff notices for Bell MTS General Tariff and exchange-service items."),
    ("dmts-general-tariff", None, "carrier_tariff", "DMTS General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "DMTS is a division of Bell Canada; search current CRTC tariff notices."),
    ("kmts-general-tariff", None, "carrier_tariff", "KMTS General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "KMTS is a division of Bell Canada; search current CRTC tariff notices."),
    ("northerntel-general-tariff", None, "carrier_tariff", "NorthernTel General Tariff", "Quebec", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Search current NorthernTel tariff notices and General Tariff items N140, N260, and N490."),
    ("telebec-general-tariff", None, "carrier_tariff", "Télébec General Tariff", "Quebec", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Search current Télébec tariff notices and local exchange service items."),
    ("onterra-general-tariff", None, "carrier_tariff", "Ontera General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Search current Ontera tariff notices and local exchange service items."),
    ("tbaytel-general-tariff", None, "carrier_tariff", "Tbaytel General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "SILEC tariff source; search CRTC filings for current tariff documents."),
    ("bruce-telecom-general-tariff", None, "carrier_tariff", "Bruce Telecom General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "SILEC tariff source; search CRTC filings for current tariff documents."),
    ("cooptel-general-tariff", None, "carrier_tariff", "CoopTel General Tariff", "Quebec", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "SILEC tariff source; current tariff notices are filed with the CRTC."),
    ("nexicom-general-tariff", None, "carrier_tariff", "Nexicom General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "CLEC/SILEC tariff source; search current CRTC tariff notices."),
    ("execulink-general-tariff", None, "carrier_tariff", "Execulink General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "CLEC tariff source; search current CRTC tariff notices."),
    ("hay-communications-general-tariff", None, "carrier_tariff", "Hay Communications General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
    ("quadro-general-tariff", None, "carrier_tariff", "Quadro Communications General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
    ("mornington-general-tariff", None, "carrier_tariff", "Mornington Communications General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
    ("wtc-general-tariff", None, "carrier_tariff", "WTC Communications General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
    ("amtelecom-general-tariff", None, "carrier_tariff", "Amtelecom General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
    ("nrtc-general-tariff", None, "carrier_tariff", "NRTC Communications General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
    ("north-frontenac-general-tariff", None, "carrier_tariff", "North Frontenac Telephone Company General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
    ("westport-rural-general-tariff", None, "carrier_tariff", "Westport Telephone Company General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
    ("lansdowne-rural-general-tariff", None, "carrier_tariff", "Lansdowne Rural Telephone General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
    ("roxborough-general-tariff", None, "carrier_tariff", "Roxborough Telephone General Tariff", "Ontario", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
    ("citywest-general-tariff", None, "carrier_tariff", "CityWest General Tariff", "British Columbia", "https://crtc.gc.ca/eng/archive.htm", None, None, "discovery_required", "Independent telephone company tariff source."),
]

REFERENCE_CALLING_RULES = [
    ("bell-on-toronto-ottawa-2026", "8051", "Toronto", "Ottawa-Hull", None, None, "ON", "standard_landline", "long_distance", True, "Bell basic Ontario/Quebec distance tier: 81+ miles; local calls excluded", "2026-01-01", None, "Bell Home Phone Basic Long Distance Rates", "https://www.bell.ca/Home_phone/Long_distance_rates", "derived", "Toronto and Ottawa-Hull are distinct exchange areas. Verify against the subscriber's exact local calling area and plan."),
    ("bell-on-ottawa-toronto-2026", "8051", "Ottawa-Hull", "Toronto", None, None, "ON", "standard_landline", "long_distance", True, "Bell basic Ontario/Quebec distance tier: 81+ miles; local calls excluded", "2026-01-01", None, "Bell Home Phone Basic Long Distance Rates", "https://www.bell.ca/Home_phone/Long_distance_rates", "derived", "Toronto and Ottawa-Hull are distinct exchange areas. Verify against the subscriber's exact local calling area and plan."),
]


def connect(database: str | Path = ROOT / "phones.duckdb") -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(database))
    con.execute(SCHEMA.read_text(encoding="utf-8"))
    return con


def _text(element: ET.Element | None, path: str) -> str | None:
    if element is None:
        return None
    child = element.find(path)
    if child is None or child.text is None or not child.text.strip():
        return None
    return child.text.strip()


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _insert_batches(con: duckdb.DuckDBPyConnection, table: str, columns: list[str], rows: Iterable[tuple[Any, ...]], batch_size: int = 1000) -> int:
    # Bulk-loading a temporary CSV is considerably faster than row-wise
    # executemany for the 20k-property XML export, while keeping this module
    # independent of pandas or pyarrow.
    rows = list(rows)
    if not rows:
        return 0
    with tempfile.NamedTemporaryFile(mode="w", newline="", encoding="utf-8", suffix=".csv", delete=False) as stream:
        path = stream.name
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)
    try:
        escaped = path.replace("'", "''")
        con.execute(f"INSERT INTO {table} ({', '.join(columns)}) SELECT {', '.join(columns)} FROM read_csv_auto('{escaped}', header=true, delim=',', quote='\"', nullstr='')")
    finally:
        Path(path).unlink(missing_ok=True)
    return len(rows)


def import_dfrp(con: duckdb.DuckDBPyConnection, xml_path: str | Path) -> dict[str, int]:
    """Stream the nested DFRP XML into normalized DuckDB tables."""
    xml_path = Path(xml_path)
    con.execute("DELETE FROM dfrp.structures")
    con.execute("DELETE FROM dfrp.locations")
    con.execute("DELETE FROM dfrp.properties")
    imported_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    properties: list[tuple[Any, ...]] = []
    locations: list[tuple[Any, ...]] = []
    structures: list[tuple[Any, ...]] = []
    counts = {"properties": 0, "locations": 0, "structures": 0}

    for _, prop in ET.iterparse(xml_path, events=("end",)):
        if prop.tag != "Property":
            continue
        number = _text(prop, "Property_Number")
        if not number:
            prop.clear()
            continue
        properties.append((number, _text(prop, "Property_Name_E"), _text(prop, "Property_Name_F"), _text(prop, "Address_E"), _text(prop, "Address_F"), _text(prop, "Primary_Use_E"), prop.find("Primary_Use_E").get("code") if prop.find("Primary_Use_E") is not None else None, _text(prop, "Interest_Type_E"), prop.find("Interest_Type_E").get("code") if prop.find("Interest_Type_E") is not None else None, _text(prop, "Restriction_on_Interest_E"), prop.get("createdDate"), prop.get("lastModifiedDate"), xml_path.name, imported_at))
        counts["properties"] += 1
        for parcel in prop.findall("./Parcels/Parcel"):
            loc = parcel.find("Location")
            if loc is not None:
                locations.append((number, parcel.get("Number"), loc.get("sgc"), loc.get("fed"), loc.get("type"), loc.get("inRuralArea") == "true", _text(loc, "Province_E"), _text(loc, "Municipality_E"), _text(loc, "Place_Name_EN"), _text(loc, "Metro_Area_Name_E"), _float(_text(loc, "Latitude")), _float(_text(loc, "Longitude")), _float(_text(loc, "Positional_Accuracy")), loc.find("Country_Name_E").get("code") if loc.find("Country_Name_E") is not None else None, xml_path.name, imported_at))
                counts["locations"] += 1
            for structure in parcel.findall("./Structures/Structure"):
                sloc = structure.find("Location")
                structures.append((number, parcel.get("Number"), _text(structure, "Structure_Number"), _text(structure, "Structure_Name_E"), _text(structure, "Address_E"), _float(_text(sloc, "Latitude")), _float(_text(sloc, "Longitude")), _int(_text(structure, "Construction_Year")), _text(structure, "Condition_E"), _float(_text(structure, "Floor_Area")), xml_path.name, imported_at))
                counts["structures"] += 1
        prop.clear()

    _insert_batches(con, "dfrp.properties", ["property_number", "property_name_en", "property_name_fr", "address_en", "address_fr", "primary_use_en", "primary_use_code", "interest_type_en", "interest_type_code", "restriction_en", "created_date", "last_modified_date", "source_file", "imported_at"], properties)
    _insert_batches(con, "dfrp.locations", ["property_number", "parcel_number", "sgc", "fed", "location_type", "rural_area", "province_en", "municipality_en", "place_name_en", "metro_area_en", "latitude", "longitude", "positional_accuracy_m", "country_code", "source_file", "imported_at"], locations)
    _insert_batches(con, "dfrp.structures", ["property_number", "parcel_number", "structure_number", "structure_name_en", "address_en", "latitude", "longitude", "construction_year", "condition_en", "floor_area_sqm", "source_file", "imported_at"], structures)
    con.commit()
    return counts


def download_cna(destination: str | Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(CNA_ZIP_URL, destination)
    with zipfile.ZipFile(destination) as archive:
        member = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
        archive.extract(member, destination.parent)
        extracted = destination.parent / member
        target = destination.with_suffix(".csv")
        if extracted != target:
            extracted.replace(target)
    return target


def import_cna(con: duckdb.DuckDBPyConnection, csv_path: str | Path) -> int:
    csv_path = Path(csv_path)
    con.execute("DELETE FROM telephone.exchange_assignments")
    con.execute("DELETE FROM telephone.carriers")
    con.execute("DELETE FROM telephone.co_codes")
    rows = []
    with csv_path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if not re.fullmatch(r"\d{3}", row.get("NPA", "")) or not re.fullmatch(r"\d{3}", row.get("CO Code (NXX)", "")):
                continue
            rows.append((row["NPA"], row["CO Code (NXX)"], row.get("Status"), row.get("Pooled"), row.get("Exchange Area"), row.get("Province"), row.get("Company"), row.get("OCN"), row.get("Date Assigned") or None, row.get("Remarks"), CNA_ZIP_URL, date.today(), datetime.now(timezone.utc).replace(microsecond=0)))
    count = _insert_batches(con, "telephone.co_codes", ["npa", "nxx", "status", "pooled", "exchange_area", "province", "company", "ocn", "date_assigned", "remarks", "source_url", "source_snapshot_date", "imported_at"], rows)
    carriers = {}
    for row in rows:
        company, ocn, province = row[6], row[7], row[5]
        if not company:
            continue
        carrier_id = ocn or normalize(company).replace(" ", "-")
        carrier_type, fixed_line = classify_carrier(company)
        if carrier_id not in carriers:
            carriers[carrier_id] = (carrier_id, company, ocn, carrier_type, fixed_line, province, CNA_ZIP_URL, date.today(), date.today(), "Classification is heuristic until verified against CRTC records.")
    _insert_batches(con, "telephone.carriers", ["carrier_id", "legal_name", "ocn", "carrier_type", "fixed_line", "province_scope", "source_url", "first_seen", "last_seen", "notes"], carriers.values())
    assignments = []
    for row in rows:
        if not row[6]:
            continue
        carrier_id = row[7] or normalize(row[6]).replace(" ", "-")
        assignments.append((row[0], row[1], carrier_id, row[7], row[4], row[5], row[2], row[3], row[8], row[10], row[11], row[12]))
    _insert_batches(con, "telephone.exchange_assignments", ["npa", "nxx", "carrier_id", "ocn", "exchange_area", "province", "status", "pooled", "date_assigned", "source_url", "source_snapshot_date", "imported_at"], assignments)
    con.commit()
    return count


def seed_tariff_sources(con: duckdb.DuckDBPyConnection) -> int:
    con.execute("DELETE FROM telephone.tariff_sources")
    count = _insert_batches(con, "telephone.tariff_sources", ["source_id", "carrier_id", "source_type", "title", "jurisdiction", "url", "effective_from", "effective_to", "status", "notes"], TARIFF_SOURCES)
    con.commit()
    return count


def seed_reference_calling_rules(con: duckdb.DuckDBPyConnection) -> int:
    con.execute("DELETE FROM telephone.calling_rules")
    columns = ["rule_id", "carrier_id", "origin_rate_centre", "destination_rate_centre", "origin_exchange", "destination_exchange", "province", "service_type", "classification", "charge_applies", "rate_basis", "effective_from", "effective_to", "source_document", "source_url", "confidence", "notes"]
    count = _insert_batches(con, "telephone.calling_rules", columns, REFERENCE_CALLING_RULES)
    # Same exchange-area calls are a useful national baseline, but remain
    # explicitly derived because carrier-specific local calling areas can be
    # broader or narrower than the CNA exchange-area label.
    con.execute("""
        INSERT INTO telephone.calling_rules
        SELECT
            'derived-same-exchange-' || carrier_id || '-' || regexp_replace(lower(exchange_area), '[^a-z0-9]+', '-', 'g'),
            carrier_id, exchange_area, exchange_area, NULL, NULL, province,
            'standard_landline', 'local', false, 'same CNA exchange area',
            current_date, NULL, 'CNA CO Code Status', ?, 'derived',
            'Candidate local rule only; verify against the carrier tariff and local calling area.'
        FROM (
            SELECT DISTINCT a.carrier_id, a.exchange_area, a.province
            FROM telephone.fixed_line_exchange_assignments a
            WHERE a.exchange_area IS NOT NULL AND trim(a.exchange_area) <> ''
        )
    """, [CNA_ZIP_URL])
    count = con.execute("SELECT count(*) FROM telephone.calling_rules").fetchone()[0]
    con.commit()
    return count


def import_calling_rules(con: duckdb.DuckDBPyConnection, csv_path: str | Path) -> int:
    """Import reviewed, tariff-backed calling rules from CSV."""
    columns = ["rule_id", "carrier_id", "origin_rate_centre", "destination_rate_centre", "origin_exchange", "destination_exchange", "province", "service_type", "classification", "charge_applies", "rate_basis", "effective_from", "effective_to", "source_document", "source_url", "confidence", "notes"]
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as stream:
        rows = [tuple(row.get(column) or None for column in columns) for row in csv.DictReader(stream) if row.get("rule_id") and not row["rule_id"].startswith("example-")]
    con.execute("DELETE FROM telephone.calling_rules")
    count = _insert_batches(con, "telephone.calling_rules", columns, rows)
    con.commit()
    return count


def evaluate_call(con: duckdb.DuckDBPyConnection, carrier_id: str, origin_rate_centre: str, destination_rate_centre: str, service_type: str = "standard_landline", on_date: str | None = None) -> list[dict[str, Any]]:
    """Return tariff rules; no matching rule means the charge is unknown."""
    on_date = on_date or date.today().isoformat()
    return _dict_rows(con, """SELECT *, CASE WHEN charge_applies THEN 'charge_applies' ELSE 'no_charge' END AS result
        FROM telephone.calling_rules WHERE carrier_id = ?
        AND lower(origin_rate_centre) LIKE lower(?) || '%' AND lower(destination_rate_centre) LIKE lower(?) || '%'
        AND service_type = ? AND effective_from <= CAST(? AS DATE)
        AND (effective_to IS NULL OR effective_to >= CAST(? AS DATE))""", (carrier_id, origin_rate_centre, destination_rate_centre, service_type, on_date, on_date))


def classify_carrier(name: str) -> tuple[str, bool]:
    """Conservative CNA company classification; CRTC verification remains authoritative."""
    value = normalize(name)
    if any(token in value for token in ("mobility", "wireless", "fido", "mobile")):
        return "wireless", False
    if any(token in value for token in ("cable", "cogeco", "shaw", "videotron", "rogers communications")):
        return "cable_or_clec", True
    if any(token in value for token in ("bell canada", "bell aliant", "bell mts", "telus", "sasktel", "northwestel", "telephone company", "telecom")):
        return "incumbent_or_independent_wireline", True
    if any(token in value for token in ("voip", "distributel", "fibernetics", "iristel", "primus", "teksavvy", "comwave", "zayo", "isp telecom")):
        return "clec_or_fixed_voip", True
    return "unknown", True


def normalize(value: str | None) -> str:
    if not value:
        return ""
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def fuzzy_score(query: str, text: str) -> float:
    q, t = normalize(query), normalize(text)
    if not q or not t:
        return 0.0
    tokens = [token for token in q.split() if len(token) > 1]
    coverage = sum(token in t for token in tokens) / len(tokens) if tokens else 0
    similarity = difflib.SequenceMatcher(None, q, t).ratio()
    return round(0.65 * coverage + 0.35 * similarity, 4)


def _dict_rows(con: duckdb.DuckDBPyConnection, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    result = con.execute(sql, parameters)
    names = [column[0] for column in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def find_offices(con: duckdb.DuckDBPyConnection, query: str, minimum_score: float = 0.35, limit: int = 25) -> list[dict[str, Any]]:
    rows = _dict_rows(con, "SELECT * FROM dfrp.property_search")
    matches = []
    for row in rows:
        score = fuzzy_score(query, row.get("search_text", ""))
        if score >= minimum_score:
            row["match_score"] = score
            matches.append(row)
    return sorted(matches, key=lambda row: row["match_score"], reverse=True)[:limit]


def find_exchanges(con: duckdb.DuckDBPyConnection, query: str, minimum_score: float = 0.35, limit: int = 25) -> list[dict[str, Any]]:
    rows = _dict_rows(con, "SELECT * FROM telephone.exchange_search WHERE status = 'In Service'")
    matches = []
    for row in rows:
        score = fuzzy_score(query, row.get("search_text", ""))
        if score >= minimum_score:
            row["match_score"] = score
            matches.append(row)
    return sorted(matches, key=lambda row: row["match_score"], reverse=True)[:limit]


def property_telephone(con: duckdb.DuckDBPyConnection, property_number: str) -> list[dict[str, Any]]:
    return _dict_rows(con, """SELECT p.property_number, p.property_name_en, p.municipality_en, p.place_name_en,
        e.npa, e.nxx, e.exchange_area, e.province, e.company, e.status
        FROM dfrp.property_search p
        LEFT JOIN telephone.co_codes e ON lower(e.exchange_area) = lower(p.municipality_en)
          OR lower(e.exchange_area) = lower(regexp_replace(coalesce(p.place_name_en, ''), ', [A-Z]{2}$', ''))
        WHERE p.property_number = ?""", (property_number,))
