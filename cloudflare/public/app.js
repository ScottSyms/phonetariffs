const app = document.getElementById("app");

/** @param {string} tag @param {Record<string, unknown>} [attrs] @param {...(Node|string|null)} children */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = String(value);
    else if (key === "text") node.textContent = String(value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else node.setAttribute(key, String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function panel(title, hint, ...children) {
  return el("section", { class: "panel" }, el("h2", { text: title }), hint ? el("p", { class: "hint", text: hint }) : null, ...children);
}

async function api(path, params = {}) {
  const url = new URL(path, location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== "" && value !== null && value !== undefined) url.searchParams.set(key, value);
  }
  const response = await fetch(url);
  const payload = await response.json().catch(() => ({ error: response.statusText }));
  if (!response.ok) throw new Error(payload.error || `request failed (${response.status})`);
  return payload;
}

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [name, query] = raw.split("?");
  return { name: name || "offices", params: new URLSearchParams(query || "") };
}

function navigate(name, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== "" && value !== null && value !== undefined) query.set(key, value);
  }
  const suffix = query.toString();
  const target = `#/${name}${suffix ? `?${suffix}` : ""}`;
  if (location.hash === target) render();
  else location.hash = target;
}

function scoreBadge(score) {
  return el("span", { class: "score", text: `match ${Number(score).toFixed(3)}` });
}

function officeResults(results) {
  if (results.length === 0) {
    return el("p", { class: "notice warn", text: "No candidate matches. Try a shorter query or lower the minimum score." });
  }
  return el(
    "ul",
    { class: "results" },
    ...results.map((row) => {
      const title = row.property_name_en || row.property_name_fr || `Property ${row.property_number}`;
      const place = [row.municipality_en, row.province_en].filter(Boolean).join(", ");
      return el(
        "li",
        { class: "result" },
        el("h3", {}, el("a", { href: `#/property?number=${encodeURIComponent(row.property_number)}`, text: title })),
        row.address_en ? el("p", { text: row.address_en }) : null,
        el(
          "div",
          { class: "meta" },
          el("span", { text: `#${row.property_number}` }),
          place ? el("span", { text: place }) : null,
          row.primary_use_en ? el("span", { text: row.primary_use_en }) : null,
          scoreBadge(row.match_score),
        ),
      );
    }),
  );
}

function exchangeResults(results) {
  if (results.length === 0) {
    return el("p", { class: "notice warn", text: "No in-service exchange matched. Try a shorter query or lower the minimum score." });
  }
  return el(
    "div",
    { class: "table-scroll" },
    el(
      "table",
      {},
      el("thead", {}, el("tr", {}, ...["NPA-NXX", "Exchange", "Province", "Company", "Status", "Match"].map((label) => el("th", { text: label })))),
      el(
        "tbody",
        {},
        ...results.map((row) =>
          el(
            "tr",
            {},
            el("td", { class: "mono", text: `${row.npa}-${row.nxx}` }),
            el("td", { text: row.exchange_area || "—" }),
            el("td", { text: row.province || "—" }),
            el("td", { text: row.company || "—" }),
            el("td", { text: row.status || "—" }),
            el("td", {}, scoreBadge(row.match_score)),
          ),
        ),
      ),
    ),
  );
}

function renderOffices(params) {
  const query = params.get("q") || "";
  const minimum = params.get("minimum_score") || "0.35";
  const input = el("input", { type: "search", name: "q", value: query, placeholder: "Atomic Energy, Port Hope…", required: "required" });
  const minInput = el("input", { type: "number", name: "minimum_score", value: minimum, min: "0", max: "1", step: "0.05" });
  const output = el("div");
  const form = el(
    "form",
    { class: "search" },
    el("div", { class: "fields" }, el("label", {}, "Search federal properties", input), el("label", {}, "Minimum score", minInput)),
    el("button", { type: "submit", text: "Search" }),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    navigate("offices", { q: input.value.trim(), minimum_score: minInput.value });
  });
  app.replaceChildren(
    panel(
      "Federal offices and locations",
      "Fuzzy match over property names, addresses, municipalities, and places. Scores are candidates, not authoritative address assignments.",
      form,
      output,
    ),
  );
  if (query) {
    output.append(el("p", { class: "status", text: "Searching…" }));
    api("/api/office", { q: query, minimum_score: minimum, limit: 25 })
      .then((payload) => {
        output.replaceChildren(
          el("p", { class: "status", text: `${payload.count} result${payload.count === 1 ? "" : "s"} for “${payload.query}”.` }),
          officeResults(payload.results),
        );
      })
      .catch((error) => output.replaceChildren(el("p", { class: "notice warn", text: error.message })));
  }
}

function renderExchanges(params) {
  const query = params.get("q") || "";
  const minimum = params.get("minimum_score") || "0.35";
  const input = el("input", { type: "search", name: "q", value: query, placeholder: "Ottawa, Port Hope, 613-5…", required: "required" });
  const minInput = el("input", { type: "number", name: "minimum_score", value: minimum, min: "0", max: "1", step: "0.05" });
  const output = el("div");
  const form = el(
    "form",
    { class: "search" },
    el("div", { class: "fields" }, el("label", {}, "Search exchange areas", input), el("label", {}, "Minimum score", minInput)),
    el("button", { type: "submit", text: "Search" }),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    navigate("exchanges", { q: input.value.trim(), minimum_score: minInput.value });
  });
  app.replaceChildren(
    panel(
      "CNA exchange assignments",
      "In-service NPA/NXX prefixes from the Canadian Numbering Administrator. An exchange prefix does not determine whether a call is local or toll.",
      form,
      output,
    ),
  );
  if (query) {
    output.append(el("p", { class: "status", text: "Searching…" }));
    api("/api/exchange", { q: query, minimum_score: minimum, limit: 25 })
      .then((payload) => {
        output.replaceChildren(
          el("p", { class: "status", text: `${payload.count} result${payload.count === 1 ? "" : "s"} for “${payload.query}”.` }),
          exchangeResults(payload.results),
        );
      })
      .catch((error) => output.replaceChildren(el("p", { class: "notice warn", text: error.message })));
  }
}

function renderProperty(params) {
  const number = params.get("number") || "";
  const input = el("input", { type: "search", name: "number", value: number, placeholder: "31559", required: "required" });
  const output = el("div");
  const form = el(
    "form",
    { class: "search" },
    el("div", { class: "fields" }, el("label", {}, "DFRP property number", input)),
    el("button", { type: "submit", text: "Look up" }),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    navigate("property", { number: input.value.trim() });
  });
  app.replaceChildren(
    panel(
      "Property telephone context",
      "Links a federal property to exchange areas sharing its municipality or place name.",
      form,
      output,
    ),
  );
  if (number) {
    output.append(el("p", { class: "status", text: "Looking up…" }));
    api(`/api/property/${encodeURIComponent(number)}`)
      .then((payload) => {
        if (payload.count === 0) {
          output.replaceChildren(el("p", { class: "notice warn", text: `No property found with number ${number}.` }));
          return;
        }
        const rows = payload.results.map((row) =>
          el(
            "tr",
            {},
            el("td", { class: "mono", text: row.npa ? `${row.npa}-${row.nxx}` : "—" }),
            el("td", { text: row.exchange_area || "—" }),
            el("td", { text: row.province || "—" }),
            el("td", { text: row.company || "—" }),
            el("td", { text: row.status || "—" }),
          ),
        );
        output.replaceChildren(
          el(
            "p",
            { class: "status" },
            `${rows.length} exchange candidate${rows.length === 1 ? "" : "s"}; ${payload.matched_exchanges} matched to an exchange area.`,
          ),
          el(
            "div",
            { class: "table-scroll" },
            el(
              "table",
              {},
              el("thead", {}, el("tr", {}, ...["NPA-NXX", "Exchange", "Province", "Company", "Status"].map((label) => el("th", { text: label })))),
              el("tbody", {}, ...rows),
            ),
          ),
          el("p", { class: "notice", text: payload.note }),
        );
      })
      .catch((error) => output.replaceChildren(el("p", { class: "notice warn", text: error.message })));
  }
}

let carriersPromise;
function carriers() {
  carriersPromise ??= api("/api/carriers").then((payload) => payload.results);
  return carriersPromise;
}

function renderCall(params) {
  const select = el("select", { name: "carrier_id" }, el("option", { value: "", text: "Loading carriers…" }));
  const origin = el("input", { type: "search", name: "origin", value: params.get("origin") || "", placeholder: "Toronto", required: "required" });
  const destination = el("input", { type: "search", name: "destination", value: params.get("destination") || "", placeholder: "Ottawa", required: "required" });
  const service = el("input", { type: "text", name: "service_type", value: params.get("service_type") || "standard_landline" });
  const date = el("input", {
    type: "date",
    name: "date",
    value: params.get("date") || new Date().toISOString().slice(0, 10),
  });
  const output = el("div");
  const form = el(
    "form",
    { class: "search" },
    el(
      "div",
      { class: "fields" },
      el("label", {}, "Carrier", select),
      el("label", {}, "Origin rate centre", origin),
      el("label", {}, "Destination rate centre", destination),
      el("label", {}, "Service type", service),
      el("label", {}, "Effective date", date),
    ),
    el("button", { type: "submit", text: "Evaluate" }),
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    navigate("call", {
      carrier_id: select.value,
      origin: origin.value.trim(),
      destination: destination.value.trim(),
      service_type: service.value.trim(),
      date: date.value,
    });
  });

  carriers()
    .then((rows) => {
      select.replaceChildren(...rows.map((row) => el("option", { value: row.carrier_id, text: row.legal_name || row.carrier_id })));
      const wanted = params.get("carrier_id");
      if (wanted) select.value = wanted;
    })
    .catch(() => select.replaceChildren(el("option", { value: "", text: "Carriers unavailable" })));

  app.replaceChildren(
    panel(
      "Evaluate a call",
      "Looks up reviewed tariff rules for a carrier, origin, and destination rate centre. No matching rule means the charge is unknown — not free.",
      form,
      output,
    ),
  );

  const carrierId = params.get("carrier_id");
  if (!carrierId || !params.get("origin") || !params.get("destination")) return;
  output.append(el("p", { class: "status", text: "Evaluating…" }));
  api("/api/call", {
    carrier_id: carrierId,
    origin: params.get("origin"),
    destination: params.get("destination"),
    service_type: params.get("service_type") || "standard_landline",
    date: params.get("date") || "",
  })
    .then((payload) => {
      const nodes = [
        el("p", { class: "status", text: `${payload.count} matching rule${payload.count === 1 ? "" : "s"} for ${payload.origin_rate_centre} → ${payload.destination_rate_centre} on ${payload.date}.` }),
      ];
      if (payload.results.length === 0) {
        nodes.push(el("p", { class: "notice warn", text: payload.note }));
      } else {
        nodes.push(
          el(
            "ul",
            { class: "results" },
            ...payload.results.map((rule) =>
              el(
                "li",
                { class: "result" },
                el("h3", { text: rule.classification === "long_distance" ? "Long distance" : rule.classification || "Rule" }),
                el(
                  "div",
                  { class: "meta" },
                  el("span", { class: "badge", text: rule.result }),
                  el("span", { class: "badge" + (rule.confidence === "derived" ? " derived" : ""), text: rule.confidence || "unknown confidence" }),
                  el("span", { text: rule.effective_from ? `effective ${rule.effective_from}` : "no effective date" }),
                ),
                rule.rate_basis ? el("p", { text: rule.rate_basis }) : null,
                rule.notes ? el("p", { text: rule.notes }) : null,
                el(
                  "p",
                  {},
                  rule.source_url
                    ? el("a", { href: rule.source_url, rel: "noopener noreferrer", target: "_blank", text: rule.source_document || "Source document" })
                    : rule.source_document || "No source document",
                ),
              ),
            ),
          ),
          el("p", { class: "notice", text: payload.note }),
        );
      }
      output.replaceChildren(...nodes);
    })
    .catch((error) => output.replaceChildren(el("p", { class: "notice warn", text: error.message })));
}

const views = {
  offices: renderOffices,
  exchanges: renderExchanges,
  property: renderProperty,
  call: renderCall,
};

function render() {
  const { name, params } = parseHash();
  const view = views[name] || views.offices;
  for (const tab of document.querySelectorAll(".tabs a")) {
    const active = tab.dataset.tab === (views[name] ? name : "offices");
    if (active) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  view(params);
}

window.addEventListener("hashchange", render);
render();
