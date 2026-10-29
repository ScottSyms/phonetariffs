import { describe, expect, it } from "vitest";
import { fuzzyScore, normalize, similarity, tokens } from "../src/fuzzy";

describe("normalize", () => {
  it("strips accents, case, and punctuation", () => {
    expect(normalize("Montréal, QC")).toBe("montreal qc");
    expect(normalize("  Port   HOPE  ")).toBe("port hope");
    expect(normalize(null)).toBe("");
  });
});

describe("similarity", () => {
  it("is 1 for identical strings and 0 for empty input", () => {
    expect(similarity("ottawa", "ottawa")).toBe(1);
    expect(similarity("", "ottawa")).toBe(0);
  });

  it("rewards shared bigrams", () => {
    expect(similarity("ottawa", "ottawa hull")).toBeGreaterThan(0.5);
    expect(similarity("ottawa", "vancouver")).toBeLessThan(0.2);
  });
});

describe("fuzzyScore", () => {
  it("scores an exact match at 1", () => {
    expect(fuzzyScore("Port Hope", "Port Hope")).toBe(1);
  });

  it("applies the 0.65 coverage / 0.35 similarity split", () => {
    // Both tokens present, but the text is much longer than the query.
    const score = fuzzyScore("port hope", "port hope federal building ontario");
    expect(score).toBeGreaterThan(0.65);
    expect(score).toBeLessThan(1);
  });

  it("penalises partial coverage", () => {
    const full = fuzzyScore("port hope", "port hope");
    const partial = fuzzyScore("port hope", "port stanley");
    expect(partial).toBeLessThan(full);
    expect(partial).toBeLessThan(0.65);
  });

  it("returns 0 for empty input", () => {
    expect(fuzzyScore("", "ottawa")).toBe(0);
    expect(fuzzyScore("ottawa", "")).toBe(0);
  });
});

describe("tokens", () => {
  it("drops one-character tokens like the Python scorer", () => {
    expect(tokens("a Port Hope")).toEqual(["port", "hope"]);
  });
});
