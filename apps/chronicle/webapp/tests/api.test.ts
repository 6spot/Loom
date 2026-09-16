import { describe, expect, it } from "vitest";
import { entityPath, searchPath } from "../src/lib/api";

describe("public API boundary paths", () => {
  it("search requires the query term on the public namespace", () => {
    expect(searchPath({ q: "曹操" })).toContain("/api/v1/public/search?");
    expect(searchPath({ q: "曹操" })).toContain("q=%E6%9B%B9");
  });

  it("entity detail uses canonical ids on the public namespace", () => {
    expect(entityPath("abc")).toBe("/api/v1/public/entities/abc");
  });

  it("never points at legacy-only or non-HTTP authorities", () => {
    for (const path of [searchPath({ q: "x" }), entityPath("x")]) {
      expect(path.startsWith("/api/v1/public/")).toBe(true);
    }
  });
});
