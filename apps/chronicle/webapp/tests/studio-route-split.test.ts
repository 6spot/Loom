import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("C1-T10 Studio imports remain route-split", () => {
  it("lazy-loads list and detail pages instead of pulling them into public navigation", () => {
    const root = new URL("..", import.meta.url).pathname;
    const app = readFileSync(`${root}src/App.tsx`, "utf-8");
    expect(app).toContain('lazy(() => import("./pages/studio/StudioImportsPage"))');
    expect(app).toContain('lazy(() => import("./pages/studio/StudioImportDetailPage"))');
    expect(app).toContain('path="imports/:jobId"');
  });
});
