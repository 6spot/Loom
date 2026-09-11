import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import React from "react";
import {
  applyMeasuredHeight,
  estimateReadingUnitHeight,
  mergeReadingUnitPages,
  planReadingWindow,
  readingChapterHeadings,
  resolveReadingWindowLimits,
} from "../src/lib/reading-window";
import { readingUnitText, type ReadingSegment, type ReadingUnit } from "../src/lib/reading-types";
import ReadingContent from "../src/components/reading/ReadingContent";
import ReadingWindow from "../src/components/reading/ReadingWindow";
import {
  BULK_PAGE,
  CHAPTER_A,
  CHAPTER_B,
  CHAPTER_TITLES,
  FAR_PAGE,
  INITIAL_PAGE,
  NEXT_PAGE,
  PREVIOUS_PAGE,
  makeUnit,
} from "./fixtures/reading/cases/content/fixtures";

const webappRoot = new URL("..", import.meta.url).pathname;

function activeFromOrdinal(units: readonly ReadingUnit[], ordinal: number): string {
  return units.find((unit) => unit.ordinal === ordinal)?.unit_id ?? units[0]?.unit_id ?? "";
}

describe("reading-window: page merge and chapter boundaries", () => {
  it("dedupes repeated pages and keeps narrative order across chapters", () => {
    const merged = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, PREVIOUS_PAGE, NEXT_PAGE]);
    expect(merged.map((unit) => unit.ordinal)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8]);
    const ids = merged.map((unit) => unit.unit_id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(mergeReadingUnitPages([INITIAL_PAGE, INITIAL_PAGE]).length).toBe(initialCount());
    expect(mergeReadingUnitPages([null, undefined] as never)).toEqual([]);
  });

  it("emits a chapter heading only at the actual boundary", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE]);
    const headings = readingChapterHeadings(units, CHAPTER_TITLES);
    const headingIds = Object.keys(headings).map((id) => {
      return units.find((unit) => unit.unit_id === id)?.ordinal;
    });
    expect(headingIds).toEqual([3, 5]);
    expect(headings[activeFromOrdinal(units, 5)].chapter_id).toBe(CHAPTER_B);
    expect(headings[activeFromOrdinal(units, 5)].chapter_title).toBe("卷二 · 魏书");
    expect(headings[activeFromOrdinal(units, 3)].chapter_title).toBe("卷一 · 吴书");
  });

  function initialCount(): number {
    return mergeReadingUnitPages([INITIAL_PAGE]).length;
  }
});

describe("reading-window: bounded plan and pinning", () => {
  it("mounts every unit while under the limit and keeps auto prefetch on", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE]);
    const plan = planReadingWindow({ units, activeUnitId: activeFromOrdinal(units, 4) });
    expect(plan.mountedUnitIds).toHaveLength(units.length);
    expect(plan.evictedUnitIds).toEqual([]);
    expect(plan.autoPrefetch).toBe(true);
    expect(plan.requiresExplicitLoad).toBe(false);
  });

  it("caps mounted units at 120 and stops auto prefetch once content is recycled", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    expect(units.length).toBeGreaterThan(120);
    const plan = planReadingWindow({ units, activeUnitId: activeFromOrdinal(units, 4) });
    expect(plan.mountedUnitIds.length).toBeLessThanOrEqual(120);
    expect(plan.mountedUnitIds).toContain(activeFromOrdinal(units, 4));
    expect(plan.evictedUnitIds.length).toBe(units.length - plan.mountedUnitIds.length);
    expect(plan.requiresExplicitLoad).toBe(true);
    expect(plan.autoPrefetch).toBe(false);
    expect(plan.placeholders.length).toBe(plan.evictedUnitIds.length);
    // active unit is always mounted, even when the loaded set is far larger.
    expect(plan.mountedUnitIds).toContain(activeFromOrdinal(units, 4));
  });

  it("keeps externally pinned units mounted and uses measured placeholder heights", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    const active = activeFromOrdinal(units, 9);
    const farPin = activeFromOrdinal(units, 4);
    const evicted = activeFromOrdinal(units, 203);
    const plan = planReadingWindow({
      units,
      activeUnitId: active,
      pinnedUnitIds: [farPin],
      placeholderHeights: { [evicted]: 777 },
      limits: { maxMountedUnits: 60 },
    });
    expect(plan.pinnedUnitIds).toContain(farPin);
    expect(plan.mountedUnitIds).toContain(farPin);
    expect(plan.mountedUnitIds).toContain(active);
    // A pinned unit is never evicted, so it never appears as a placeholder.
    expect(plan.evictedUnitIds).not.toContain(farPin);
    // An evicted unit reuses its measured height instead of the estimate.
    const placeholder = plan.placeholders.find((entry) => entry.unit_id === evicted);
    expect(placeholder?.height).toBe(777);
    expect(placeholder?.estimated).toBe(false);
  });

  it("caps pinned units at 20 and requires explicit load on overflow", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    const pins = units.slice(0, 30).map((unit) => unit.unit_id);
    const plan = planReadingWindow({
      units,
      activeUnitId: activeFromOrdinal(units, 4),
      pinnedUnitIds: pins,
    });
    expect(plan.pinnedUnitIds).toHaveLength(20);
    expect(plan.overflowPinnedUnitIds).toHaveLength(10);
    expect(plan.autoPrefetch).toBe(false);
    expect(plan.requiresExplicitLoad).toBe(true);
  });

  it("resolves limits and estimates unmounted heights", () => {
    expect(resolveReadingWindowLimits()).toEqual({ maxMountedUnits: 120, maxPinnedUnits: 20 });
    expect(resolveReadingWindowLimits({ maxMountedUnits: 40, maxPinnedUnits: 99 })).toEqual({
      maxMountedUnits: 40,
      maxPinnedUnits: 40,
    });
    const unit = makeUnit(1, "短句。");
    expect(estimateReadingUnitHeight(unit)).toBeGreaterThanOrEqual(140);
  });

  it("records measured heights without churning identical values", () => {
    const base = { a: 10 };
    expect(applyMeasuredHeight(base, "b", 20)).toEqual({ a: 10, b: 20 });
    expect(applyMeasuredHeight(base, "b", 0)).toBe(base);
    const once = applyMeasuredHeight(base, "b", 20);
    expect(applyMeasuredHeight(once, "b", 20)).toBe(once);
  });
});

describe("reading-window: safe content rendering", () => {
  it("reassembles segments verbatim and marks resolved/uncertain events", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE]);
    const resolved = units.find((unit) => unit.ordinal === 4)!;
    const html = renderToString(React.createElement(ReadingContent, { unit: resolved }));
    expect(readingUnitText(resolved)).toContain("赤壁");
    expect(html).toContain('data-test="reading-event-span"');
    expect(html).toContain("大破曹公军");
    const uncertainUnit = units.find((unit) => unit.ordinal === 6)!;
    const uncertain = renderToString(React.createElement(ReadingContent, { unit: uncertainUnit }));
    expect(uncertain).toContain('data-test="reading-event-span-uncertain"');
  });

  it("renders hostile segment text as inert text and never injects nodes", () => {
    const malicious: ReadingSegment[] = [
      { kind: "text", text: "<script>alert(1)</script><img src=x onerror=alert(2)>" },
    ];
    const unit = makeUnit(99, "", { segments: malicious, anchors: [] });
    const html = renderToString(React.createElement(ReadingContent, { unit }));
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;script&gt;");
  });

  it("offers one on-demand source toggle per server-issued anchor", () => {
    const unit = makeUnit(1, "正文。", { anchors: ["anc_a", "anc_b"] });
    const html = renderToString(
      React.createElement(ReadingContent, {
        unit,
        expandedAnchorId: null,
        onToggleSource: () => {},
      }),
    );
    expect(html.match(/data-test="reading-source-toggle"/g)).toHaveLength(2);
    expect(html).toContain('data-anchor="anc_a"');
    expect(html).toContain('data-anchor="anc_b"');
  });
});

describe("reading-window: window states", () => {
  it("renders units in ordinal order with chapter headings only at boundaries", () => {
    const html = renderToString(
      React.createElement(ReadingWindow, {
        pages: [INITIAL_PAGE, NEXT_PAGE],
        activeUnitId: activeFromOrdinal(mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE]), 6),
        chapterTitles: CHAPTER_TITLES,
      }),
    );
    expect(html.match(/data-test="reading-unit"/g)?.length).toBe(6);
    expect(html.match(/data-test="reading-chapter-heading"/g)).toHaveLength(2);
    expect(html).toContain('data-chapter-id="' + CHAPTER_A + '"');
    expect(html).toContain('data-chapter-id="' + CHAPTER_B + '"');
    // data-text must equal the reconstructed segment text.
    expect(html).toContain("遇于");
  });

  it("keeps loaded units and shows an explicit error with retry on failure", () => {
    const html = renderToString(
      React.createElement(ReadingWindow, {
        pages: [INITIAL_PAGE],
        activeUnitId: activeFromOrdinal(mergeReadingUnitPages([INITIAL_PAGE]), 3),
        error: { message: "upstream_limited", direction: "next" },
      }),
    );
    expect(html).toContain('data-test="reading-load-error"');
    expect(html).toContain('data-test="reading-retry"');
    expect(html.match(/data-test="reading-unit"/g)?.length).toBe(4);
  });

  it("shows an honest empty state instead of fabricating content", () => {
    const html = renderToString(React.createElement(ReadingWindow, { pages: [] }));
    expect(html).toContain('data-test="reading-empty"');
    expect(html).not.toContain('data-test="reading-unit"');
  });

  it("renders placeholders and a paused explicit-load entry when the window is saturated", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    const html = renderToString(
      React.createElement(ReadingWindow, {
        pages: [INITIAL_PAGE, NEXT_PAGE, BULK_PAGE],
        activeUnitId: activeFromOrdinal(units, 4),
      }),
    );
    expect(html).toContain('data-test="reading-paused"');
    expect(html).toContain('data-test="reading-manual-next"');
    expect(html).toContain('data-test="reading-load-more"');
    expect(html).toContain('data-test="reading-unit-placeholder"');
    expect((html.match(/data-test="reading-unit"/g) ?? []).length).toBeLessThanOrEqual(120);
  });

  it("exposes the far page through an explicit page prop without downloading the gap", () => {
    const units = mergeReadingUnitPages([FAR_PAGE]);
    const html = renderToString(
      React.createElement(ReadingWindow, {
        pages: [FAR_PAGE],
        activeUnitId: activeFromOrdinal(units, 5020),
      }),
    );
    expect(units[0].ordinal).toBe(5000);
    expect(html).toContain('data-ordinal="5020"');
    expect(html).toContain('data-active="true"');
  });
});

describe("reading-window: ownership boundary", () => {
  it("keeps styling scoped and does not reach into App or global styles", () => {
    const css = readFileSync(`${webappRoot}src/styles/reading-content.css`, "utf-8");
    expect(css).toContain(".rcw-window");
    expect(css).toContain(":focus-visible");
    expect(css).toContain("@media");
    expect(css).not.toMatch(/^(html|body|button|a|input|p|h1|h2)\s*\{/m);

    for (const file of [
      `${webappRoot}src/components/reading/ReadingContent.tsx`,
      `${webappRoot}src/components/reading/ReadingWindow.tsx`,
      `${webappRoot}src/lib/reading-window.ts`,
    ]) {
      const source = readFileSync(file, "utf-8");
      expect(source).not.toContain("from \"../../App\"");
      expect(source).not.toContain("chronicle.css");
    }

    const app = readFileSync(`${webappRoot}src/App.tsx`, "utf-8");
    const globalCss = readFileSync(`${webappRoot}src/styles/chronicle.css`, "utf-8");
    expect(app).not.toContain("reading-content.css");
    expect(globalCss).not.toContain("rcw-");
  });
});
