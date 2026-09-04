import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("C1-T10 Studio operations remain route-split", () => {
  it("lazy-loads imports, import detail, and sources instead of pulling them into public navigation", () => {
    const root = new URL("..", import.meta.url).pathname;
    const app = readFileSync(`${root}src/App.tsx`, "utf-8");
    expect(app).toContain('lazy(() => import("./pages/studio/StudioImportsPage"))');
    expect(app).toContain('lazy(() => import("./pages/studio/StudioImportDetailPage"))');
    expect(app).toContain('lazy(() => import("./pages/studio/StudioSourcesPage"))');
    expect(app).toContain('path="imports/:jobId"');
    expect(app).toContain('path="sources"');
    expect(app).not.toContain("StudioPlaceholders.SourcesPage");
  });
});
