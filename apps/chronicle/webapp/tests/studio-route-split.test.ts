import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("Chronicle Studio operations remain route-split", () => {
  it("lazy-loads imports, review queue/detail, sources, and coverage outside public navigation", () => {
    const root = new URL("..", import.meta.url).pathname;
    const app = readFileSync(`${root}src/App.tsx`, "utf-8");
    expect(app).toContain('lazy(() => import("./pages/studio/StudioImportsPage"))');
    expect(app).toContain('lazy(() => import("./pages/studio/StudioImportDetailPage"))');
    expect(app).toContain('lazy(() => import("./pages/studio/StudioReviewPage"))');
    expect(app).toContain('lazy(() => import("./pages/studio/StudioReviewDetailPage"))');
    expect(app).toContain('lazy(() => import("./pages/studio/StudioSourcesPage"))');
    expect(app).toContain('lazy(() => import("./pages/studio/StudioCoveragePage"))');
    expect(app).toContain('path="imports/:jobId"');
    expect(app).toContain('path="review/:reviewId"');
    expect(app).toContain('path="sources"');
    expect(app).toContain('path="coverage"');
    expect(app).not.toContain("StudioPlaceholders.ReviewPage");
    expect(app).not.toContain("StudioPlaceholders.SourcesPage");
  });
});
