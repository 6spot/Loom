import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("C1-T14 Studio Coverage", () => {
  it("uses the authenticated Coverage API and keeps no-data semantics explicit", () => {
    const root = new URL("..", import.meta.url).pathname;
    const api = readFileSync(`${root}src/lib/coverage-api.ts`, "utf-8");
    const page = readFileSync(`${root}src/pages/studio/StudioCoveragePage.tsx`, "utf-8");
    expect(api).toContain('"/api/v1/studio/coverage"');
    expect(api).toContain('historical_truth: false');
    expect(api).toContain('mutates_history: false');
    expect(page).toContain("不是历史完整度");
    expect(page).toContain("0 只表示当前 corpus 未表示");
    expect(page).toContain("Source contribution");
    expect(page).toContain("Actionable gaps");
    expect(page).toContain("<progress");
  });
});
