/**
 * Fuzzy matching, ported from python/phone_db.py.
 *
 * The Python CLI scores candidates with `0.65 * token coverage + 0.35 *
 * difflib.SequenceMatcher ratio`. difflib is not available in a Worker, so the
 * ratio term uses a bigram Dice coefficient instead. Rankings agree with the CLI
 * in practice; scores are not bit-for-bit identical.
 */

/** Accent-stripped, lowercased, alphanumeric-only form of a string. */
export function normalize(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function bigrams(value: string): Map<string, number> {
  const counts = new Map<string, number>();
  if (value.length < 2) {
    counts.set(value, 1);
    return counts;
  }
  for (let i = 0; i < value.length - 1; i += 1) {
    const gram = value.slice(i, i + 2);
    counts.set(gram, (counts.get(gram) ?? 0) + 1);
  }
  return counts;
}

/** Sørensen–Dice coefficient over character bigrams, in [0, 1]. */
export function similarity(a: string, b: string): number {
  if (!a.length || !b.length) return 0;
  if (a === b) return 1;
  const left = bigrams(a);
  const right = bigrams(b);
  let overlap = 0;
  for (const [gram, count] of left) {
    const other = right.get(gram);
    if (other) overlap += Math.min(count, other);
  }
  const total = Math.max(0, a.length - 1) + Math.max(0, b.length - 1);
  return total > 0 ? (2 * overlap) / total : 0;
}

/** Query tokens that participate in coverage, matching the Python filter. */
export function tokens(query: string): string[] {
  return normalize(query)
    .split(" ")
    .filter((token) => token.length > 1);
}

/**
 * Score a query against text. Both inputs are normalised here, so callers may
 * pass the raw `norm_text` column directly.
 */
export function fuzzyScore(query: string, text: string): number {
  const q = normalize(query);
  const t = normalize(text);
  if (!q || !t) return 0;
  const parts = q.split(" ").filter((token) => token.length > 1);
  let coverage = 0;
  if (parts.length > 0) {
    let hits = 0;
    for (const token of parts) {
      if (t.includes(token)) hits += 1;
    }
    coverage = hits / parts.length;
  }
  return Math.round((0.65 * coverage + 0.35 * similarity(q, t)) * 10000) / 10000;
}
