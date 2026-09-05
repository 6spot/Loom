import { describe, expect, it } from "vitest";
import { historicalMomentPath, historicalMomentPathFromSearch } from "../src/lib/historical-moment";

describe("Historical Moment public API boundary", () => {
  it("uses only the grounded C1-T15 public projection", () => {
    expect(historicalMomentPath({ kind: "year", year: 208 })).toBe("/api/v1/public/historical-moment?year=208&limit=100&offset=0");
    expect(historicalMomentPath({ kind: "period", fromYear: 208, toYear: 210 })).toBe(
      "/api/v1/public/historical-moment?from_year=208&to_year=210&limit=100&offset=0",
    );
  });

  it("refuses to manufacture a query when URL time context is invalid", () => {
    expect(historicalMomentPathFromSearch("?q=red-cliffs")).toBeNull();
    expect(historicalMomentPathFromSearch("?year=208")).toContain("year=208");
  });
});
