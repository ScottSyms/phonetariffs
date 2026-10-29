-- Cloudflare D1 schema for the phone/property database.
--
-- D1/SQLite has no user-defined schemas, so the DuckDB dfrp.* and telephone.*
-- namespaces are flattened to <schema>_<table>. Types follow SQLite affinity:
-- BOOLEAN -> INTEGER (0/1), DATE/TIMESTAMP -> ISO TEXT, DOUBLE -> REAL.
--
-- This file is applied with `wrangler d1 migrations apply` and is the single
-- source of truth for the remote schema. python/export_cloudflare.py emits data
-- that matches these column lists.

CREATE TABLE IF NOT EXISTS dfrp_properties (
    property_number VARCHAR PRIMARY KEY,
    property_name_en VARCHAR,
    property_name_fr VARCHAR,
    address_en VARCHAR,
    address_fr VARCHAR,
    primary_use_en VARCHAR,
    primary_use_code VARCHAR,
    interest_type_en VARCHAR,
    interest_type_code VARCHAR,
    restriction_en VARCHAR,
    created_date TEXT,
    last_modified_date TEXT,
    source_file VARCHAR,
    imported_at TEXT
);

CREATE TABLE IF NOT EXISTS dfrp_locations (
    property_number VARCHAR,
    parcel_number VARCHAR,
    sgc VARCHAR,
    fed VARCHAR,
    location_type VARCHAR,
    rural_area INTEGER,
    province_en VARCHAR,
    municipality_en VARCHAR,
    place_name_en VARCHAR,
    metro_area_en VARCHAR,
    latitude REAL,
    longitude REAL,
    positional_accuracy_m REAL,
    country_code VARCHAR,
    source_file VARCHAR,
    imported_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_dfrp_locations_property
    ON dfrp_locations (property_number);

CREATE TABLE IF NOT EXISTS dfrp_structures (
    property_number VARCHAR,
    parcel_number VARCHAR,
    structure_number VARCHAR,
    structure_name_en VARCHAR,
    address_en VARCHAR,
    latitude REAL,
    longitude REAL,
    construction_year INTEGER,
    condition_en VARCHAR,
    floor_area_sqm REAL,
    source_file VARCHAR,
    imported_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_dfrp_structures_property
    ON dfrp_structures (property_number);

CREATE TABLE IF NOT EXISTS telephone_co_codes (
    npa VARCHAR,
    nxx VARCHAR,
    status VARCHAR,
    pooled VARCHAR,
    exchange_area VARCHAR,
    province VARCHAR,
    company VARCHAR,
    ocn VARCHAR,
    date_assigned TEXT,
    remarks VARCHAR,
    source_url VARCHAR,
    source_snapshot_date TEXT,
    imported_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_co_codes_npa_nxx
    ON telephone_co_codes (npa, nxx);

CREATE INDEX IF NOT EXISTS idx_co_codes_exchange_area
    ON telephone_co_codes (exchange_area);

CREATE TABLE IF NOT EXISTS telephone_carriers (
    carrier_id VARCHAR PRIMARY KEY,
    legal_name VARCHAR,
    ocn VARCHAR,
    carrier_type VARCHAR,
    fixed_line INTEGER,
    province_scope VARCHAR,
    source_url VARCHAR,
    first_seen TEXT,
    last_seen TEXT,
    notes VARCHAR
);

CREATE TABLE IF NOT EXISTS telephone_exchange_assignments (
    npa VARCHAR,
    nxx VARCHAR,
    carrier_id VARCHAR,
    ocn VARCHAR,
    exchange_area VARCHAR,
    province VARCHAR,
    status VARCHAR,
    pooled VARCHAR,
    date_assigned TEXT,
    source_url VARCHAR,
    source_snapshot_date TEXT,
    imported_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_assignments_carrier
    ON telephone_exchange_assignments (carrier_id);

CREATE INDEX IF NOT EXISTS idx_assignments_exchange_area
    ON telephone_exchange_assignments (exchange_area);

CREATE TABLE IF NOT EXISTS telephone_calling_rules (
    -- Not a primary key: the seed data contains duplicate derived rule_ids
    -- (exchange areas that slug to the same value under one carrier). DuckDB
    -- allows them, so D1 must too, or the import rejects the dataset.
    rule_id VARCHAR,
    carrier_id VARCHAR,
    origin_rate_centre VARCHAR,
    destination_rate_centre VARCHAR,
    origin_exchange VARCHAR,
    destination_exchange VARCHAR,
    province VARCHAR,
    service_type VARCHAR,
    classification VARCHAR,
    charge_applies INTEGER,
    rate_basis VARCHAR,
    effective_from TEXT,
    effective_to TEXT,
    source_document VARCHAR,
    source_url VARCHAR,
    confidence VARCHAR,
    notes VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_calling_rules_lookup
    ON telephone_calling_rules (carrier_id, service_type);

CREATE INDEX IF NOT EXISTS idx_calling_rules_id
    ON telephone_calling_rules (rule_id);

CREATE TABLE IF NOT EXISTS telephone_tariff_sources (
    source_id VARCHAR PRIMARY KEY,
    carrier_id VARCHAR,
    source_type VARCHAR,
    title VARCHAR,
    jurisdiction VARCHAR,
    url VARCHAR,
    effective_from TEXT,
    effective_to TEXT,
    status VARCHAR,
    notes VARCHAR
);

-- Materialized copies of the DuckDB search views. D1 cannot build an FTS5 index
-- over a view, so these are stored as tables and kept in sync by the exporter.
CREATE TABLE IF NOT EXISTS property_search (
    row_id INTEGER PRIMARY KEY,
    property_number VARCHAR,
    property_name_en VARCHAR,
    property_name_fr VARCHAR,
    address_en VARCHAR,
    address_fr VARCHAR,
    primary_use_en VARCHAR,
    interest_type_en VARCHAR,
    created_date TEXT,
    last_modified_date TEXT,
    parcel_number VARCHAR,
    province_en VARCHAR,
    municipality_en VARCHAR,
    place_name_en VARCHAR,
    metro_area_en VARCHAR,
    latitude REAL,
    longitude REAL,
    search_text VARCHAR,
    -- Accent-stripped, lowercased search_text produced by phone_db.normalize().
    -- Matching and scoring use this column so D1 results agree with the CLI.
    norm_text VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_property_search_number
    ON property_search (property_number);

CREATE TABLE IF NOT EXISTS exchange_search (
    row_id INTEGER PRIMARY KEY,
    npa VARCHAR,
    nxx VARCHAR,
    status VARCHAR,
    pooled VARCHAR,
    exchange_area VARCHAR,
    province VARCHAR,
    company VARCHAR,
    ocn VARCHAR,
    date_assigned TEXT,
    remarks VARCHAR,
    source_url VARCHAR,
    source_snapshot_date TEXT,
    imported_at TEXT,
    search_text VARCHAR,
    norm_text VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_exchange_search_npa_nxx
    ON exchange_search (npa, nxx);

-- External-content FTS5 indexes. The trigram tokenizer gives substring matching
-- (so "Port Hop" and partial names work) for terms of three or more characters.
CREATE VIRTUAL TABLE IF NOT EXISTS property_search_fts USING fts5(
    norm_text,
    content = 'property_search',
    content_rowid = 'row_id',
    tokenize = 'trigram'
);

CREATE VIRTUAL TABLE IF NOT EXISTS exchange_search_fts USING fts5(
    norm_text,
    content = 'exchange_search',
    content_rowid = 'row_id',
    tokenize = 'trigram'
);
