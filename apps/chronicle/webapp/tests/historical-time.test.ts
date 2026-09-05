import { describe, expect, it } from "vitest";
import {
  historicalTimeLabel,
  parseHistoricalTime,
  withHistoricalTime,
  worldPathFromSearch,
  worldPathForSelection,
} from "../src/lib/historical-time";

describe("global historical time context", () => {
  it("parses one year and a bounded period without inventing finer precision", () => {
    expect(parseHistoricalTime("?year=208")).toEqual({ kind: "year", year: 208 });
    expect(parseHistoricalTime("?from_year=208&to_year=210")).toEqual({ kind: "period", fromYear: 208, toYear: 210 });
    expect(parseHistoricalTime("?from_year=208&to_year=208")).toEqual({ kind: "year", year: 208 });
    expect(parseHistoricalTime("?from_year=210&to_year=208")).toBeNull();
    expect(parseHistoricalTime("?year=208.5")).toBeNull();
  });

  it("keeps the selected historical time on public drill-down links", () => {
    expect(withHistoricalTime("/events/a%2Fb#evidence", "?year=208")).toBe("/events/a%2Fb?year=208#evidence");
    expect(withHistoricalTime("/search?q=%E6%9B%B9%E6%93%8D", "?from_year=208&to_year=210")).toContain("from_year=208");
    expect(withHistoricalTime("/search?q=x", "?q=ignored")).toBe("/search?q=x");
  });

  it("formats bookmarkable World paths deterministically", () => {
    expect(worldPathForSelection({ kind: "year", year: 208 })).toBe("/world?year=208");
    expect(worldPathForSelection({ kind: "period", fromYear: 208, toYear: 210 })).toBe("/world?from_year=208&to_year=210");
    expect(worldPathFromSearch("?q=x")).toBe("/world?year=208");
    expect(historicalTimeLabel({ kind: "year", year: -221 })).toBe("公元前 221 年");
  });
});
