import { fuzzyScore, normalize } from "./fuzzy";
import type { CallParams, Row, SearchRow } from "./types";

/**
 * Candidate retrieval + in-Worker reranking.
 *
 * The Python CLI loads every row and scores it. A Worker cannot afford that, so
 * an FTS5 trigram index narrows the field first and the top candidates are
 * reranked with the same scoring formula. ORDER BY rank keeps the prefilter
 * recall-focused; the final ordering always comes from `fuzzyScore`.
 */
const CANDIDATE_LIMIT = 300;
const SEARCH_COLUMNS = new Set(["row_id", "norm_text"]);

type SearchTable = "property_search" | "exchange_search";

function withoutInternalColumns(row: SearchRow): Row {
  const result: Row = {};
  for (const [key, value] of Object.entries(row)) {
    if (!SEARCH_COLUMNS.has(key)) result[key] = value;
  }
  return result;
}

function rank(
  rows: SearchRow[],
  query: string,
  minimumScore: number,
  limit: number,
): Row[] {
  return rows
    .map((row) => ({
      ...withoutInternalColumns(row),
      match_score: fuzzyScore(query, row.norm_text),
    }))
    .filter((row) => (row.match_score as number) >= minimumScore)
    .sort((left, right) => (right.match_score as number) - (left.match_score as number))
    .slice(0, limit);
}

async function ftsCandidates(
  env: Env,
  table: SearchTable,
  match: string,
  orderBy: string,
): Promise<SearchRow[]> {
  const status = table === "exchange_search" ? "AND s.status = 'In Service'" : "";
  const { results } = await env.DB.prepare(
    `SELECT s.* FROM ${table}_fts
       JOIN ${table} s ON s.row_id = ${table}_fts.rowid
      WHERE ${table}_fts MATCH ?
        ${status}
      ORDER BY ${orderBy}
      LIMIT ?`,
  )
    .bind(match, CANDIDATE_LIMIT)
    .all<SearchRow>();
  return results;
}

/**
 * Candidate retrieval for reranking.
 *
 * A single `ORDER BY rank` list is not enough: for a one-word query like
 * "Ottawa", bm25 surfaces long property descriptions and the short, exact
 * matches the Python scorer prefers fall outside the limit. Each FTS query is
 * therefore read twice — once by bm25, once by text length, which is a good
 * proxy for the similarity half of the score — and all-token matches are read
 * separately from any-token matches. Results are deduplicated by row_id.
 */
async function candidates(
  env: Env,
  table: SearchTable,
  query: string,
): Promise<SearchRow[]> {
  const terms = normalize(query)
    .split(" ")
    .filter((token) => token.length > 1);
  const longTerms = terms.filter((token) => token.length >= 3);
  const seen = new Map<number, SearchRow>();

  if (longTerms.length > 0) {
    const all = longTerms.map((token) => `"${token}"`).join(" AND ");
    const any = longTerms.map((token) => `"${token}"`).join(" OR ");
    const plans = [
      { match: all, orderBy: "length(s.norm_text)" },
      { match: all, orderBy: "rank" },
      { match: any, orderBy: "length(s.norm_text)" },
      { match: any, orderBy: "rank" },
    ];
    for (const plan of plans) {
      for (const row of await ftsCandidates(env, table, plan.match, plan.orderBy)) {
        seen.set(row.row_id, row);
      }
    }
  }
  if (seen.size > 0) return [...seen.values()];

  // Short queries and zero-hit FTS fall back to a bounded substring scan.
  const fallback = terms.length > 0 ? terms : normalize(query) ? [normalize(query)] : [];
  if (fallback.length === 0) return [];

  const status = table === "exchange_search" ? "AND s.status = 'In Service'" : "";
  const conditions = fallback.map(() => "instr(s.norm_text, ?) > 0").join(" AND ");
  const { results } = await env.DB.prepare(
    `SELECT s.* FROM ${table} s
      WHERE ${conditions}
        ${status}
      ORDER BY length(s.norm_text)
      LIMIT ?`,
  )
    .bind(...fallback, CANDIDATE_LIMIT * 2)
    .all<SearchRow>();
  return results;
}

export async function findOffices(
  env: Env,
  query: string,
  minimumScore: number,
  limit: number,
): Promise<Row[]> {
  return rank(await candidates(env, "property_search", query), query, minimumScore, limit);
}

export async function findExchanges(
  env: Env,
  query: string,
  minimumScore: number,
  limit: number,
): Promise<Row[]> {
  return rank(await candidates(env, "exchange_search", query), query, minimumScore, limit);
}

/**
 * SQLite has no regexp_replace, so the trailing ", ON" place-name suffix from
 * the Python query is stripped with GLOB + substr.
 */
export async function propertyTelephone(
  env: Env,
  propertyNumber: string,
): Promise<Row[]> {
  const { results } = await env.DB.prepare(
    `SELECT p.property_number, p.property_name_en, p.municipality_en, p.place_name_en,
            e.npa, e.nxx, e.exchange_area, e.province, e.company, e.status
       FROM property_search p
       LEFT JOIN telephone_co_codes e
              ON lower(e.exchange_area) = lower(p.municipality_en)
              OR lower(e.exchange_area) =
                 lower(CASE WHEN p.place_name_en GLOB '*, [A-Z][A-Z]'
                            THEN substr(p.place_name_en, 1, length(p.place_name_en) - 4)
                            ELSE p.place_name_en END)
      WHERE p.property_number = ?`,
  )
    .bind(propertyNumber)
    .all<Row>();
  return results;
}

/**
 * Returns matching tariff rules. An empty result means the charge is UNKNOWN,
 * not free; callers must present it that way.
 *
 * Rules are carrier-specific: the same route can be local under one carrier's
 * tariff and long distance under another's. When `carrierId` is null the query
 * spans every carrier that has a rule for the route, and the caller groups the
 * results.
 */
export async function evaluateCall(env: Env, params: CallParams): Promise<Row[]> {
  const carrierFilter = params.carrierId ? "AND r.carrier_id = ?" : "";
  const bindings: (string | null)[] = [
    params.origin,
    params.destination,
    params.serviceType,
    params.onDate,
    params.onDate,
  ];
  if (params.carrierId) bindings.push(params.carrierId);

  const { results } = await env.DB.prepare(
    `SELECT r.*, c.legal_name AS carrier_name,
            CASE WHEN r.charge_applies THEN 'charge_applies' ELSE 'no_charge' END AS result
       FROM telephone_calling_rules r
       LEFT JOIN telephone_carriers c ON c.carrier_id = r.carrier_id
      WHERE lower(r.origin_rate_centre) LIKE lower(?) || '%'
        AND lower(r.destination_rate_centre) LIKE lower(?) || '%'
        AND r.service_type = ?
        AND r.effective_from <= ?
        AND (r.effective_to IS NULL OR r.effective_to >= ?)
        ${carrierFilter}
      ORDER BY r.carrier_id, r.rule_id`,
  )
    .bind(...bindings)
    .all<Row>();
  return results;
}

export async function listCarriers(env: Env): Promise<Row[]> {
  const { results } = await env.DB.prepare(
    `SELECT carrier_id, legal_name, carrier_type
       FROM telephone_carriers
      WHERE fixed_line = 1
      ORDER BY legal_name`,
  ).all<Row>();
  return results;
}

export async function databaseMeta(env: Env): Promise<Row> {
  const { results } = await env.DB.prepare(
    `SELECT
       (SELECT count(*) FROM dfrp_properties) AS properties,
       (SELECT count(*) FROM dfrp_locations) AS locations,
       (SELECT count(*) FROM dfrp_structures) AS structures,
       (SELECT count(*) FROM telephone_co_codes) AS co_codes,
       (SELECT count(*) FROM telephone_carriers) AS carriers,
       (SELECT count(*) FROM telephone_exchange_assignments) AS exchange_assignments,
       (SELECT count(*) FROM telephone_calling_rules) AS calling_rules,
       (SELECT count(*) FROM telephone_tariff_sources) AS tariff_sources,
       (SELECT max(imported_at) FROM dfrp_properties) AS property_imported_at,
       (SELECT max(imported_at) FROM telephone_co_codes) AS co_codes_imported_at`,
  ).all<Row>();
  return results[0] ?? {};
}
