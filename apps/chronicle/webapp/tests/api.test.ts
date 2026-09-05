import { describe, expect, it } from "vitest";
import { entityPath, eventPath, searchPath, timelinePath, timelinePathFromSearch } from "../src/lib/api";

describe("public API boundary paths", () => {
  it("timeline keeps the Rust public namespace with sane defaults", () => {
    expect(timelinePath({})).toBe("/api/v1/public/timeline?limit=50&offset=0");
    expect(timelinePath({ from_year: 208, to_year: 208 })).toBe("/api/v1/public/timeline?from_year=208&to_year=208&limit=50&offset=0");
    expect(timelinePathFromSearch("?year=208")).toBe("/api/v1/public/timeline?from_year=208&to_year=208&limit=50&offset=0");
  });

  it("search requires the query term on the public namespace", () => {
    expect(searchPath({ q: "曹操" })).toContain("/api/v1/public/search?");
    expect(searchPath({ q: "曹操" })).toContain("q=%E6%9B%B9");
  });

  it("event and entity detail use canonical ids on the public namespace", () => {
    expect(eventPath("abc")).toBe("/api/v1/public/events/abc");
    expect(entityPath("abc")).toBe("/api/v1/public/entities/abc");
    expect(eventPath("a/b")).toBe("/api/v1/public/events/a%2Fb");
  });

  it("never points at legacy-only or non-HTTP authorities", () => {
    for (const path of [timelinePath({}), searchPath({ q: "x" }), eventPath("x"), entityPath("x")]) {
      expect(path.startsWith("/api/v1/public/")).toBe(true);
    }
  });
});
