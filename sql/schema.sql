CREATE SCHEMA IF NOT EXISTS dfrp;
CREATE SCHEMA IF NOT EXISTS telephone;

CREATE TABLE IF NOT EXISTS dfrp.properties (
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
    created_date TIMESTAMP,
    last_modified_date TIMESTAMP,
    source_file VARCHAR,
    imported_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dfrp.locations (
    property_number VARCHAR,
    parcel_number VARCHAR,
    sgc VARCHAR,
    fed VARCHAR,
    location_type VARCHAR,
    rural_area BOOLEAN,
    province_en VARCHAR,
    municipality_en VARCHAR,
    place_name_en VARCHAR,
    metro_area_en VARCHAR,
    latitude DOUBLE,
    longitude DOUBLE,
    positional_accuracy_m DOUBLE,
    country_code VARCHAR,
    source_file VARCHAR,
    imported_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dfrp.structures (
    property_number VARCHAR,
    parcel_number VARCHAR,
    structure_number VARCHAR,
    structure_name_en VARCHAR,
    address_en VARCHAR,
    latitude DOUBLE,
    longitude DOUBLE,
    construction_year INTEGER,
    condition_en VARCHAR,
    floor_area_sqm DOUBLE,
    source_file VARCHAR,
    imported_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS telephone.co_codes (
    npa VARCHAR,
    nxx VARCHAR,
    status VARCHAR,
    pooled VARCHAR,
    exchange_area VARCHAR,
    province VARCHAR,
    company VARCHAR,
    ocn VARCHAR,
    date_assigned DATE,
    remarks VARCHAR,
    source_url VARCHAR,
    source_snapshot_date DATE,
    imported_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS telephone.carriers (
    carrier_id VARCHAR,
    legal_name VARCHAR,
    ocn VARCHAR,
    carrier_type VARCHAR,
    fixed_line BOOLEAN,
    province_scope VARCHAR,
    source_url VARCHAR,
    first_seen DATE,
    last_seen DATE,
    notes VARCHAR
);

CREATE TABLE IF NOT EXISTS telephone.exchange_assignments (
    npa VARCHAR,
    nxx VARCHAR,
    carrier_id VARCHAR,
    ocn VARCHAR,
    exchange_area VARCHAR,
    province VARCHAR,
    status VARCHAR,
    pooled VARCHAR,
    date_assigned DATE,
    source_url VARCHAR,
    source_snapshot_date DATE,
    imported_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS telephone.calling_rules (
    rule_id VARCHAR,
    carrier_id VARCHAR,
    origin_rate_centre VARCHAR,
    destination_rate_centre VARCHAR,
    origin_exchange VARCHAR,
    destination_exchange VARCHAR,
    province VARCHAR,
    service_type VARCHAR,
    classification VARCHAR,
    charge_applies BOOLEAN,
    rate_basis VARCHAR,
    effective_from DATE,
    effective_to DATE,
    source_document VARCHAR,
    source_url VARCHAR,
    confidence VARCHAR,
    notes VARCHAR
);

CREATE TABLE IF NOT EXISTS telephone.tariff_sources (
    source_id VARCHAR,
    carrier_id VARCHAR,
    source_type VARCHAR,
    title VARCHAR,
    jurisdiction VARCHAR,
    url VARCHAR,
    effective_from DATE,
    effective_to DATE,
    status VARCHAR,
    notes VARCHAR
);

CREATE OR REPLACE VIEW dfrp.property_search AS
SELECT
    p.property_number,
    p.property_name_en,
    p.property_name_fr,
    p.address_en,
    p.address_fr,
    p.primary_use_en,
    p.interest_type_en,
    p.created_date,
    p.last_modified_date,
    l.parcel_number,
    l.province_en,
    l.municipality_en,
    l.place_name_en,
    l.metro_area_en,
    l.latitude,
    l.longitude,
    concat_ws(' ', p.property_name_en, p.property_name_fr, p.address_en,
              p.address_fr, l.province_en, l.municipality_en,
              l.place_name_en, l.metro_area_en) AS search_text
FROM dfrp.properties p
LEFT JOIN dfrp.locations l USING (property_number);

CREATE OR REPLACE VIEW telephone.exchange_search AS
SELECT *, concat_ws(' ', npa, nxx, exchange_area, province, company) AS search_text
FROM telephone.co_codes;

CREATE OR REPLACE VIEW telephone.fixed_line_carriers AS
SELECT * FROM telephone.carriers WHERE fixed_line;

CREATE OR REPLACE VIEW telephone.fixed_line_exchange_assignments AS
SELECT a.*
FROM telephone.exchange_assignments a
JOIN telephone.carriers c USING (carrier_id)
WHERE c.fixed_line;
