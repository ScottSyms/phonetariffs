# Canadian Telephone and Federal Property Database

This project combines Canada's Federal Real Property data with Canadian telephone NPA/NXX exchange assignments in DuckDB. It includes a Python command-line interface and a PowerShell interface.

> **Scope:** CNA data identifies assigned area-code/exchange prefixes and exchange areas. It does not by itself determine whether a call is local, toll, or long distance. Carrier tariffs and local-calling-area data must be added for that analysis.

## Requirements

- [mise](https://mise.jdx.dev/)
- Python 3.12.13, managed by `mise.toml`
- Node.js 22.23.2, managed by `mise.toml` (Cloudflare Worker and tests)
- DuckDB Python package, installed from `python/requirements.txt`
- The supplied `dfrp-rbif.xml` file

## Setup

From the project directory:

```bash
mise install
mise exec -- python -m pip install -r python/requirements.txt
```

The database file is `phones.duckdb`.

## Build the database

Build from the local DFRP XML and CNA CSV files:

```bash
mise exec -- python python/build_database.py build
```

Refresh the CNA data from the Canadian Numbering Administrator before building:

```bash
mise exec -- python python/build_database.py build --refresh-cna
```

The build currently imports:

- 20,009 federal properties
- 20,860 property locations
- 38,520 structures
- 46,400 CNA exchange records
- 117 heuristic fixed-line carriers
- 20,984 fixed-line exchange assignments
- 37 tariff and regulatory source records
- 11,879 calling rules, including derived same-exchange candidates

The CNA source is:

<https://www.cnac.ca/co_codes/co_code_status.htm>

## Python searches

All search commands return JSON.

### Search federal offices or locations

```bash
mise exec -- python python/build_database.py office "Atomic Energy"
mise exec -- python python/build_database.py office "Port Hop"
```

Limit results or require a higher fuzzy-match score:

```bash
mise exec -- python python/build_database.py office "Port Hop" --limit 10 --minimum-score 0.60
```

### Search telephone exchanges

```bash
mise exec -- python python/build_database.py exchange Ottawa
mise exec -- python python/build_database.py exchange "Port Hope"
```

### Find exchanges associated with a federal property

```bash
mise exec -- python python/build_database.py property 31559
```

Evaluate a call against reviewed tariff rules:

```bash
mise exec -- python python/build_database.py call 8051 Toronto Ottawa
```

An empty result means **unknown**, not necessarily free or chargeable.

The current Bell example is:

```bash
mise exec -- python python/build_database.py call 8051 Toronto Ottawa
```

It returns a derived Bell Canada long-distance result based on the published 81+ mile Ontario/Québec basic rate tier. Other cross-exchange routes remain unknown until a verified carrier rule is imported.

Import reviewed rules using the supplied format:

```bash
cp data/tariffs/calling_rules.example.csv data/tariffs/calling_rules.csv
# Edit the copy and remove the example row before importing it.
mise exec -- python python/build_database.py import-rules data/tariffs/calling_rules.csv
```

## Python module usage

```python
from phone_db import connect, find_offices, find_exchanges, property_telephone

with connect("phones.duckdb") as con:
    offices = find_offices(con, "Port Hop")
    exchanges = find_exchanges(con, "Ottawa")
    telephone = property_telephone(con, "31559")
```

For scripts outside the `python` directory, add the module directory to `PYTHONPATH` or install the project package when packaging is added.

## PowerShell interface

Requirements:

- PowerShell 7+
- DuckDB CLI available as `duckdb`, or set `$env:DUCKDB_PATH`

Build or refresh using PowerShell:

```powershell
./src/Build-PhoneDatabase.ps1
./src/Build-PhoneDatabase.ps1 -RefreshCna
```

Search using the PowerShell module:

```powershell
Import-Module ./src/PhoneDatabase.psm1

Find-FederalOffice 'Atomic Energy'
Find-FederalOffice 'Port Hop'
Find-Exchange 'Ottawa'
Get-PropertyTelephone -PropertyNumber 31559
```

Fuzzy results include a `MatchScore`. Scores are useful for finding candidates and should not be treated as authoritative address assignments without review.

## DuckDB SQL

Open the database directly:

```bash
duckdb phones.duckdb
```

Main schemas and views:

```text
dfrp.properties
dfrp.locations
dfrp.structures
dfrp.property_search
telephone.co_codes
telephone.exchange_search
telephone.carriers
telephone.exchange_assignments
telephone.calling_rules
telephone.tariff_sources
telephone.fixed_line_carriers
telephone.fixed_line_exchange_assignments
```

Example query:

```sql
SELECT property_number, property_name_en, municipality_en,
       latitude, longitude
FROM dfrp.property_search
WHERE lower(search_text) LIKE '%port hope%';
```

## Cloudflare hosting

The public site runs on Cloudflare: a Worker serves a JSON API, D1 stores the
data, and the static UI is served from Workers static assets. The DuckDB file
stays the local source of truth; Cloudflare gets a derived, disposable copy.

```text
cloudflare/
├── wrangler.jsonc            Worker, D1 binding, static assets
├── migrations/0001_schema.sql  D1 schema (flattened dfrp_* and telephone_* tables)
├── src/                      Worker: router, D1 queries, fuzzy scoring
├── public/                   Static UI (no bundler)
├── scripts/seed-local.mjs    Loads exported SQL into D1
└── test/                     Vitest + Workers pool
python/export_cloudflare.py   DuckDB -> chunked D1 SQL
```

### JSON API

```text
GET /api/meta
GET /api/carriers
GET /api/office?q=&minimum_score=&limit=
GET /api/exchange?q=&minimum_score=&limit=
GET /api/property/:property_number
GET /api/call?carrier_id=&origin=&destination=&service_type=&date=
```

Responses mirror the Python CLI's JSON. `/api/call` returns
`"status": "unknown"` when no rule matches; that is not the same as free.

### One-time Cloudflare setup

```bash
npx wrangler login

# Create the database, then copy the printed database_id into
# cloudflare/wrangler.jsonc (d1_databases[0].database_id).
cd cloudflare
npx wrangler d1 create phonetariffs
```

Add `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` as GitHub Actions
secrets. The API token needs D1 edit and Workers scripts edit permissions for
the account. Until `CLOUDFLARE_API_TOKEN` is set, the workflow's deploy job is
skipped (the site can still be deployed manually with `npm run deploy`).

### Local development

```bash
mise install
mise exec -- python -m pip install -r python/requirements.txt

# Build the local DuckDB file, then export it for D1.
mise exec -- python python/build_database.py build
mise exec -- python python/export_cloudflare.py

cd cloudflare
npm ci
npm run db:local     # apply migrations + load dist/d1 into local D1
npm run dev          # http://127.0.0.1:8787
npm test             # unit + API tests against a fixture database
```

`npm run typecheck` regenerates nothing; run `npx wrangler types` after changing
`wrangler.jsonc` so `worker-configuration.d.ts` matches the bindings.

### Deployment

Pushing to `main` runs `.github/workflows/deploy.yml`, which:

1. builds `phones.duckdb` from the committed XML and CNA CSV,
2. exports chunked SQL,
3. typechecks and tests the Worker,
4. applies D1 migrations and loads data,
5. deploys the Worker.

Set the repository variable `SITE_URL` (for example
`https://phonetariffs.example.workers.dev`) to enable the post-deploy smoke test.

### Notes and limitations

- Fuzzy search is ported to TypeScript. It keeps the CLI formula
  (`0.65 * token coverage + 0.35 * similarity`) but uses a bigram Dice
  coefficient instead of `difflib.SequenceMatcher`. Scores differ slightly and
  ties may order differently; tests assert the scoring behaviour, and results
  were compared against the CLI on a sample of queries.
- Candidate retrieval uses an FTS5 trigram index (`norm_text`) before reranking
  in the Worker, so requests never scan the full table.
- `telephone.calling_rules` contains 65 duplicated `rule_id` values (exchange
  areas that slug to the same value). D1 keeps the rows but cannot enforce a
  primary key on `rule_id`; the exporter warns about this on every run.
- The 129 MB `dfrp-rbif.xml` is stored in Git LFS (see `.gitattributes`), so CI
  checks out with `lfs: true`. Every workflow run pulls it, which counts against
  GitHub's LFS bandwidth. It is the main reason clone and build times are high.

## Source files

```text
dfrp-rbif.xml                         Federal property source
data/raw/cna/COCodeStatus_ALL.csv     CNA exchange data
data/raw/cna/COCodeStatus_ALL.zip     CNA source archive
sql/schema.sql                         DuckDB schema and views
python/phone_db.py                     Python data and query library
python/build_database.py               Python CLI
python/export_cloudflare.py            DuckDB to Cloudflare D1 exporter
src/PhoneDatabase.psm1                 PowerShell module
src/Build-PhoneDatabase.ps1            PowerShell build script
cloudflare/                            Cloudflare Worker, D1 schema, and UI
.github/workflows/deploy.yml           Build, test, and deploy on push to main
```

## Data limitations

- An NPA/NXX is a number prefix, not an individual telephone number.
- Exchange-area names do not always correspond exactly to municipal boundaries.
- Mobile, VoIP, pooled, and ported numbers can differ from geographic expectations.
- Local/long-distance status depends on the originating carrier, destination carrier, tariff, rate centre, and effective date.
- Fuzzy matches are candidate matches and require validation.

## National landline coverage

The CNA import now creates a carrier registry and exchange-assignment table using OCNs (Operating Company Numbers). Carrier categories are initial heuristics based on CNA company names:

```text
wireless
cable_or_clec
incumbent_or_independent_wireline
clec_or_fixed_voip
unknown
```

The authoritative carrier classification should eventually be verified against CRTC records. The `telephone.calling_rules` table is reserved for tariff-backed local, extended-local, toll, and long-distance rules. It is intentionally not populated merely from NPA/NXX assignments.

The build seeds `telephone.tariff_sources` with 37 source records covering CNA, CRTC, Bell Canada, Bell Aliant, Bell MTS, DMTS, KMTS, NorthernTel, Télébec, Ontera, TELUS, SaskTel, Northwestel, Rogers, Cogeco, Eastlink, Videotron, and named independent/SILEC carriers.

Source status values are:

```text
active              official registry or live source
reference           official tariff page identified for review
discovery_required  official CRTC repository target; current document still needs locating/review
```

The build creates explicitly marked `derived` candidate rules for calls within the same CNA exchange area, plus Bell Canada Toronto ↔ Ottawa-Hull using Bell's 81+ mile basic long-distance tier. These rules are a starting point and should be checked against the subscriber's exact local calling area and plan. Cross-exchange calls remain unknown unless supported by a carrier tariff rule.

### Adding verified tariff rules

Rules belong in `telephone.calling_rules` and must include the carrier, rate centres, service type, classification, effective date, source document, source URL, and confidence. Use the template:

```text
data/tariffs/calling_rules.example.csv
```

After adding reviewed rows:

```bash
mise exec -- python python/build_database.py import-rules data/tariffs/calling_rules.csv
```

The importer replaces the current rule table, so keep the complete reviewed rule set in the CSV. Do not convert `discovery_required` source records into charge rules without reading and citing the applicable tariff.
