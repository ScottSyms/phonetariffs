import {
  databaseMeta,
  evaluateCall,
  findExchanges,
  findOffices,
  listCarriers,
  propertyTelephone,
} from "./db";

const DEFAULT_MINIMUM_SCORE = 0.35;
const DEFAULT_LIMIT = 25;
const MAX_LIMIT = 100;
const DEFAULT_SERVICE_TYPE = "standard_landline";
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

const CORS: Record<string, string> = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, HEAD, OPTIONS",
  "access-control-allow-headers": "content-type",
};

function json(data: unknown, status = 200, cache = "no-store"): Response {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": cache,
      ...CORS,
    },
  });
}

function fail(message: string, status = 400): Response {
  return json({ error: message }, status);
}

function parseNumber(
  value: string | null,
  fallback: number,
  name: string,
  minimum: number,
  maximum: number,
): number | Response {
  if (value === null || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < minimum || parsed > maximum) {
    return fail(`${name} must be a number between ${minimum} and ${maximum}`);
  }
  return parsed;
}

function requireText(params: URLSearchParams, name: string): string | Response {
  const value = params.get(name)?.trim();
  if (!value) return fail(`${name} is required`);
  return value;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

async function handleSearch(
  env: Env,
  params: URLSearchParams,
  kind: "office" | "exchange",
): Promise<Response> {
  const query = requireText(params, "q");
  if (query instanceof Response) return query;

  const minimum = parseNumber(
    params.get("minimum_score"),
    DEFAULT_MINIMUM_SCORE,
    "minimum_score",
    0,
    1,
  );
  if (minimum instanceof Response) return minimum;

  const limit = parseNumber(params.get("limit"), DEFAULT_LIMIT, "limit", 1, MAX_LIMIT);
  if (limit instanceof Response) return limit;
  const rounded = Math.trunc(limit);

  const results =
    kind === "office"
      ? await findOffices(env, query, minimum, rounded)
      : await findExchanges(env, query, minimum, rounded);

  return json(
    {
      query,
      table: kind === "office" ? "dfrp.property_search" : "telephone.exchange_search",
      minimum_score: minimum,
      count: results.length,
      results,
      note:
        kind === "office"
          ? "Fuzzy matches are candidate matches and require validation before being treated as authoritative addresses."
          : "Results identify assigned NPA/NXX prefixes; they do not by themselves determine local, toll, or long-distance status.",
    },
    200,
    "public, max-age=300",
  );
}

async function handleProperty(env: Env, propertyNumber: string): Promise<Response> {
  const results = await propertyTelephone(env, propertyNumber);
  const matched = results.filter((row) => row.npa !== null).length;
  return json(
    {
      property_number: propertyNumber,
      count: results.length,
      matched_exchanges: matched,
      results,
      note:
        matched === 0
          ? "No exchange area matched this property's municipality or place name. That is a data gap, not proof that no telephone service exists."
          : "Exchange areas are matched by name and are candidates, not authoritative assignments.",
    },
    200,
    "public, max-age=86400",
  );
}

async function handleCall(env: Env, params: URLSearchParams): Promise<Response> {
  const carrier = requireText(params, "carrier_id");
  if (carrier instanceof Response) return carrier;
  const origin = requireText(params, "origin");
  if (origin instanceof Response) return origin;
  const destination = requireText(params, "destination");
  if (destination instanceof Response) return destination;

  const serviceType = params.get("service_type")?.trim() || DEFAULT_SERVICE_TYPE;
  const onDate = params.get("date")?.trim() || today();
  if (!DATE_PATTERN.test(onDate)) return fail("date must be YYYY-MM-DD");

  const results = await evaluateCall(env, {
    carrierId: carrier,
    origin,
    destination,
    serviceType,
    onDate,
  });

  return json(
    {
      carrier_id: carrier,
      origin_rate_centre: origin,
      destination_rate_centre: destination,
      service_type: serviceType,
      date: onDate,
      count: results.length,
      results,
      // Never let an empty rule set read as "free".
      status: results.length > 0 ? "matched" : "unknown",
      note:
        results.length > 0
          ? "Derived or candidate rules should be checked against the subscriber's exact local calling area, carrier, and plan."
          : "An empty result means the charge is unknown, not that the call is free or chargeable.",
    },
    200,
    "public, max-age=300",
  );
}

async function route(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const params = url.searchParams;

  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS });
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    return fail("method not allowed", 405);
  }

  if (path === "/api" || path === "/api/") {
    return json({
      endpoints: [
        "GET /api/meta",
        "GET /api/carriers",
        "GET /api/office?q=&minimum_score=&limit=",
        "GET /api/exchange?q=&minimum_score=&limit=",
        "GET /api/property/:property_number",
        "GET /api/call?carrier_id=&origin=&destination=&service_type=&date=",
      ],
    });
  }
  if (path === "/api/meta") return json(await databaseMeta(env), 200, "public, max-age=300");
  if (path === "/api/carriers") {
    return json({ results: await listCarriers(env) }, 200, "public, max-age=86400");
  }
  if (path === "/api/office") return handleSearch(env, params, "office");
  if (path === "/api/exchange") return handleSearch(env, params, "exchange");
  if (path === "/api/call") return handleCall(env, params);

  if (path.startsWith("/api/property/")) {
    const propertyNumber = decodeURIComponent(path.slice("/api/property/".length));
    if (!propertyNumber) return fail("property number is required");
    return handleProperty(env, propertyNumber);
  }
  if (path === "/api/property") {
    const propertyNumber = requireText(params, "number");
    if (propertyNumber instanceof Response) return propertyNumber;
    return handleProperty(env, propertyNumber);
  }

  if (path.startsWith("/api/")) return fail("not found", 404);

  // Anything that is not an API route falls through to static assets (SPA).
  return env.ASSETS.fetch(request);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      return await route(request, env);
    } catch (error) {
      console.error("request failed", error);
      return json({ error: "internal error" }, 500);
    }
  },
} satisfies ExportedHandler<Env>;
