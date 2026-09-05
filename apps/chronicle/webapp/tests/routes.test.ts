import { describe, expect, it } from "vitest";
import { formatTime, formatYear, isStudioPath, safeRouteFor } from "../src/lib/routes";

describe("public routes", () => {
  it("maps World/Timeline/Event/Entity/Search URLs", () => {
    expect(safeRouteFor("/")).toEqual({ view: "world", id: null });
    expect(safeRouteFor("/world/")).toEqual({ view: "world", id: null });
    expect(safeRouteFor("/timeline/")).toEqual({ view: "timeline", id: null });
    expect(safeRouteFor("/events/abc")).toEqual({ view: "event", id: "abc" });
    expect(safeRouteFor("/entities/abc")).toEqual({ view: "entity", id: "abc" });
    expect(safeRouteFor("/search")).toEqual({ view: "search", id: null });
    expect(safeRouteFor("/unknown")).toEqual({ view: "not_found", id: null });
  });

  it("treats malformed encodings as not found", () => {
    expect(safeRouteFor("/events/%E0%A4%A")).toEqual({ view: "not_found", id: null });
  });

  it("keeps studio paths out of the public route space", () => {
    expect(isStudioPath("/studio")).toBe(true);
    expect(isStudioPath("/studio/imports")).toBe(true);
    expect(isStudioPath("/world")).toBe(false);
    expect(safeRouteFor("/studio")).toEqual({ view: "not_found", id: null });
  });
});

describe("year formatting", () => {
  it("renders BCE/CE years and unknown time", () => {
    expect(formatYear(208)).toBe("公元 208 年");
    expect(formatYear(-221)).toBe("公元前 221 年");
    expect(formatYear(null)).toBe("年代未定");
    expect(formatTime({})).toBe("年代未定");
    expect(formatTime({ start_year: 208, end_year: 208 })).toBe("公元 208 年");
  });
});
