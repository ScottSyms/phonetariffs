import { env, SELF } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import schema from "../migrations/0001_schema.sql?raw";

/** Run a multi-statement SQL script, one statement at a time. */
async function runSql(sql: string): Promise<void> {
  for (const raw of sql.split(/;\s*\n/)) {
    const statement = raw
      .split("\n")
      .filter((line) => !line.trim().startsWith("--"))
      .join("\n")
      .trim();
    if (statement) await env.DB.prepare(statement).run();
  }
}

const FIXTURES = `
INSERT INTO property_search
  (row_id, property_number, property_name_en, address_en, municipality_en, place_name_en,
   province_en, primary_use_en, search_text, norm_text)
VALUES
  (1, '31559', 'Port Hope Federal Building', '56 Queen St', 'Port Hope', 'Port Hope', 'Ontario',
   'Office', 'Port Hope Federal Building 56 Queen St Port Hope Ontario',
   'port hope federal building 56 queen st port hope ontario'),
  (2, '90001', 'Atomic Energy of Canada Limited', 'Chalk River Laboratories', 'Chalk River',
   'Chalk River', 'Ontario', 'Laboratory',
   'Atomic Energy of Canada Limited Chalk River Laboratories Chalk River Ontario',
   'atomic energy of canada limited chalk river laboratories chalk river ontario');

INSERT INTO exchange_search
  (row_id, npa, nxx, status, exchange_area, province, company, search_text, norm_text)
VALUES
  (1, '905', '885', 'In Service', 'Port Hope', 'Ontario', 'Bell Canada',
   '905 885 Port Hope Ontario Bell Canada', '905 885 port hope ontario bell canada'),
  (2, '905', '999', 'Out of Service', 'Port Hope', 'Ontario', 'Bell Canada',
   '905 999 Port Hope Ontario Bell Canada', '905 999 port hope ontario bell canada');

INSERT INTO telephone_calling_rules
  (rule_id, carrier_id, origin_rate_centre, destination_rate_centre, province, service_type,
   classification, charge_applies, rate_basis, effective_from, confidence, source_document, source_url)
VALUES
  ('bell-on-toronto-ottawa-2026', '8051', 'Toronto', 'Ottawa-Hull', 'ON', 'standard_landline',
   'long_distance', 1, '81+ miles', '2026-01-01', 'derived', 'Bell Long Distance', 'https://www.bell.ca/'),
  ('local-port-hope', '8051', 'Port Hope', 'Port Hope', 'ON', 'standard_landline',
   'local', 0, 'same exchange', '2026-01-01', 'derived', 'CNA CO Code Status', 'https://www.cnac.ca/');

INSERT INTO telephone_carriers (carrier_id, legal_name, ocn, carrier_type, fixed_line)
VALUES
  ('8051', 'Bell Canada', '8051', 'incumbent_or_independent_wireline', 1),
  ('9999', 'Rogers Wireless', '9999', 'wireless', 0);

INSERT INTO telephone_co_codes (npa, nxx, status, exchange_area, province, company)
VALUES
  ('905', '885', 'In Service', 'Port Hope', 'Ontario', 'Bell Canada');

INSERT INTO property_search_fts(property_search_fts) VALUES('rebuild');
INSERT INTO exchange_search_fts(exchange_search_fts) VALUES('rebuild');
`;

beforeAll(async () => {
  await runSql(schema);
  await runSql(FIXTURES);
  await runSql(`
    DELETE FROM dfrp_properties;
    INSERT INTO dfrp_properties (property_number, property_name_en) VALUES ('31559', 'Port Hope Federal Building');
  `);
});

async function get(path: string): Promise<{ status: number; body: any }> {
  const response = await SELF.fetch(`https://example.com${path}`);
  return { status: response.status, body: await response.json() };
}

describe("GET /api/office", () => {
  it("ranks candidates and hides internal columns", async () => {
    const { status, body } = await get("/api/office?q=port%20hope");
    expect(status).toBe(200);
    expect(body.count).toBeGreaterThan(0);
    expect(body.results[0].property_number).toBe("31559");
    expect(body.results[0].match_score).toBeGreaterThan(0.65);
    expect(body.results[0]).not.toHaveProperty("row_id");
    expect(body.results[0]).not.toHaveProperty("norm_text");
  });

  it("applies minimum_score", async () => {
    const { body } = await get("/api/office?q=port%20hope&minimum_score=0.99");
    expect(body.count).toBe(0);
  });

  it("rejects a missing query", async () => {
    const { status, body } = await get("/api/office");
    expect(status).toBe(400);
    expect(body.error).toMatch(/q is required/);
  });

  it("rejects an out-of-range limit", async () => {
    const { status } = await get("/api/office?q=port&limit=1000");
    expect(status).toBe(400);
  });
});

describe("GET /api/exchange", () => {
  it("returns only in-service exchanges", async () => {
    const { body } = await get("/api/exchange?q=port%20hope");
    expect(body.count).toBeGreaterThan(0);
    for (const row of body.results) expect(row.status).toBe("In Service");
    expect(body.results[0].npa).toBe("905");
  });

  it("falls back to LIKE for short queries", async () => {
    const { body } = await get("/api/exchange?q=905");
    expect(body.count).toBeGreaterThan(0);
  });
});

describe("GET /api/property/:number", () => {
  it("returns exchange candidates for a property", async () => {
    const { status, body } = await get("/api/property/31559");
    expect(status).toBe(200);
    expect(body.count).toBe(1);
    expect(body.matched_exchanges).toBe(1);
    expect(body.results[0].npa).toBe("905");
  });

  it("is explicit when no property exists", async () => {
    const { body } = await get("/api/property/does-not-exist");
    expect(body.count).toBe(0);
  });
});

describe("GET /api/call", () => {
  it("returns a matched rule", async () => {
    const { body } = await get(
      "/api/call?carrier_id=8051&origin=Toronto&destination=Ottawa&date=2026-06-01",
    );
    expect(body.status).toBe("matched");
    expect(body.count).toBe(1);
    expect(body.results[0].result).toBe("charge_applies");
    expect(body.results[0].charge_applies).toBe(1);
  });

  it("reports unknown instead of free", async () => {
    const { body } = await get(
      "/api/call?carrier_id=8051&origin=Toronto&destination=Vancouver&date=2026-06-01",
    );
    expect(body.status).toBe("unknown");
    expect(body.count).toBe(0);
    expect(body.note).toMatch(/unknown, not that the call is free/);
  });

  it("respects the effective date", async () => {
    const { body } = await get(
      "/api/call?carrier_id=8051&origin=Toronto&destination=Ottawa&date=2025-01-01",
    );
    expect(body.count).toBe(0);
  });

  it("rejects a malformed date", async () => {
    const { status } = await get(
      "/api/call?carrier_id=8051&origin=Toronto&destination=Ottawa&date=June",
    );
    expect(status).toBe(400);
  });
});

describe("GET /api/meta and /api/carriers", () => {
  it("reports row counts", async () => {
    const { status, body } = await get("/api/meta");
    expect(status).toBe(200);
    expect(body.properties).toBe(1);
    expect(body.calling_rules).toBe(2);
  });

  it("lists fixed-line carriers only", async () => {
    const { body } = await get("/api/carriers");
    expect(body.results.map((row: { carrier_id: string }) => row.carrier_id)).toEqual(["8051"]);
  });
});
