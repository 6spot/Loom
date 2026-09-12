import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import React from "react";
import {
  AUTO_PREFETCH_EDGE_UNITS,
  applyMeasuredHeight,
  estimateReadingUnitHeight,
  mergeReadingUnitPages,
  planAutoPrefetch,
  planReadingWindow,
  readingChapterHeadings,
  readingStreamEdges,
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

  it("only marks a verifiable stream-start or contiguous chapter boundary", () => {
    // 从 ordinal 3 起（章中间）的页：首个可见 unit 不是真实章首，不得显示标题；
    // 只有连续到章节切换的 ordinal 5 才显示章 B 标题。
    const partial = mergeReadingUnitPages([INITIAL_PAGE]);
    const partialHeadings = readingChapterHeadings(partial, CHAPTER_TITLES);
    const partialOrdinals = Object.keys(partialHeadings).map((id) => {
      return partial.find((unit) => unit.unit_id === id)?.ordinal;
    });
    expect(partialOrdinals).toEqual([5]);
    expect(partialHeadings[activeFromOrdinal(partial, 5)].chapter_title).toBe("卷二 · 魏书");
    expect(partialHeadings[activeFromOrdinal(partial, 3)]).toBeUndefined();

    // 从 stream 起点 ordinal 0 开始：章 A 与章 B 的真实边界都显示。
    const complete = mergeReadingUnitPages([PREVIOUS_PAGE, INITIAL_PAGE, NEXT_PAGE]);
    const completeHeadings = readingChapterHeadings(complete, CHAPTER_TITLES);
    const completeOrdinals = Object.keys(completeHeadings).map((id) => {
      return complete.find((unit) => unit.unit_id === id)?.ordinal;
    });
    expect(completeOrdinals).toEqual([0, 5]);
    expect(completeHeadings[activeFromOrdinal(complete, 0)].chapter_title).toBe("卷一 · 吴书");
    expect(completeHeadings[activeFromOrdinal(complete, 5)].chapter_id).toBe(CHAPTER_B);
  });

  it("does not invent a boundary across a gap in the loaded units", () => {
    const first = makeUnit(3, "章 A 中的一段。", { chapterId: CHAPTER_A });
    const gapped = makeUnit(10, "章 B 中的一段。", { chapterId: CHAPTER_B });
    const contiguous = makeUnit(11, "章 B 的下一段。", { chapterId: CHAPTER_B });
    const headings = readingChapterHeadings([first, gapped, contiguous]);
    // 3 -> 10 有缺口：边界不可验证，不显示；10 -> 11 同章，不显示。
    expect(Object.keys(headings)).toEqual([]);
  });

  function initialCount(): number {
    return mergeReadingUnitPages([INITIAL_PAGE]).length;
  }
});

describe("reading-window: adjacent-page auto prefetch", () => {
  it("derives real bidirectional edges from page metadata", () => {
    expect(readingStreamEdges([INITIAL_PAGE])).toEqual({
      firstOrdinal: 3,
      lastOrdinal: 6,
      hasPrevious: true,
      hasNext: true,
    });
    expect(readingStreamEdges([PREVIOUS_PAGE, NEXT_PAGE])).toEqual({
      firstOrdinal: 0,
      lastOrdinal: 8,
      hasPrevious: false,
      hasNext: true,
    });
    expect(readingStreamEdges([])).toEqual({
      firstOrdinal: null,
      lastOrdinal: null,
      hasPrevious: false,
      hasNext: false,
    });
  });

  it("requests both adjacent pages at a normal boundary", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE]);
    const edges = readingStreamEdges([INITIAL_PAGE]);
    const plan = planAutoPrefetch({
      autoPrefetch: true,
      units,
      edges,
      activeUnitId: units[0].unit_id,
    });
    expect(plan.requests).toEqual(["previous", "next"]);
    expect(plan.markers).toEqual({ previous: 3, next: 6 });
  });

  it("produces no request while protected content prevents safe recycling", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    const edges = readingStreamEdges([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    const plan = planAutoPrefetch({
      autoPrefetch: false,
      units,
      edges,
      activeUnitId: units[0].unit_id,
    });
    expect(plan.requests).toEqual([]);
    expect(plan.markers).toEqual({ previous: null, next: null });
  });

  it("does not prefetch from a mid-page locate and does not repeat the same edge", () => {
    const far = mergeReadingUnitPages([FAR_PAGE]);
    const farPlan = planAutoPrefetch({
      autoPrefetch: true,
      units: far,
      edges: readingStreamEdges([FAR_PAGE]),
      activeUnitId: activeFromOrdinal(far, 5020),
    });
    expect(farPlan.requests).toEqual([]);

    const units = mergeReadingUnitPages([INITIAL_PAGE]);
    const repeated = planAutoPrefetch({
      autoPrefetch: true,
      units,
      edges: readingStreamEdges([INITIAL_PAGE]),
      activeUnitId: units[0].unit_id,
      markers: { previous: 3, next: 6 },
    });
    expect(repeated.requests).toEqual([]);
  });

  it("holds a direction that is already loading but still prefetches the other", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE]);
    const plan = planAutoPrefetch({
      autoPrefetch: true,
      units,
      edges: readingStreamEdges([INITIAL_PAGE]),
      activeUnitId: units[0].unit_id,
      loadingDirection: "previous",
    });
    expect(plan.requests).toEqual(["next"]);
  });

  it("respects the edge buffer threshold", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE]);
    const edges = readingStreamEdges([INITIAL_PAGE]);
    const atEdge = planAutoPrefetch({
      autoPrefetch: true,
      units,
      edges,
      activeUnitId: activeFromOrdinal(units, 3),
      edgeUnits: 0,
    });
    expect(atEdge.requests).toEqual(["previous"]);
    expect(AUTO_PREFETCH_EDGE_UNITS).toBeGreaterThan(0);
    const buffered = planAutoPrefetch({
      autoPrefetch: true,
      units,
      edges,
      activeUnitId: activeFromOrdinal(units, 3),
    });
    expect(buffered.requests).toEqual(["previous", "next"]);
  });
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

  it("recycles to 120 mounted units and keeps adjacent-page prefetch enabled", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    expect(units.length).toBeGreaterThan(120);
    const plan = planReadingWindow({ units, activeUnitId: activeFromOrdinal(units, 4) });
    expect(plan.mountedUnitIds.length).toBeLessThanOrEqual(120);
    expect(plan.mountedUnitIds).toContain(activeFromOrdinal(units, 4));
    expect(plan.evictedUnitIds.length).toBe(units.length - plan.mountedUnitIds.length);
    expect(plan.requiresExplicitLoad).toBe(false);
    expect(plan.autoPrefetch).toBe(true);
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

  it("does not charge pins inside the ordinary window against the extra allowance", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    const pins = units.slice(0, 30).map((unit) => unit.unit_id);
    const plan = planReadingWindow({
      units,
      activeUnitId: activeFromOrdinal(units, 4),
      pinnedUnitIds: pins,
    });
    expect(plan.pinnedUnitIds).toEqual(pins);
    expect(plan.overflowPinnedUnitIds).toEqual([]);
    expect(plan.mountedUnitIds).toHaveLength(120);
    expect(plan.autoPrefetch).toBe(true);
  });

  it("uses up to 20 extra units for distant pins without interrupting reading", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    const pins = units.slice(0, 20).map((unit) => unit.unit_id);
    const plan = planReadingWindow({
      units,
      activeUnitId: activeFromOrdinal(units, 203),
      pinnedUnitIds: pins,
    });
    expect(plan.mountedUnitIds).toHaveLength(140);
    expect(plan.pinnedUnitIds).toEqual(pins);
    expect(pins.every((id) => plan.mountedUnitIds.includes(id))).toBe(true);
    expect(plan.overflowPinnedUnitIds).toEqual([]);
    expect(plan.autoPrefetch).toBe(true);
  });

  it("preserves every operated unit on overflow and resumes after pins are released", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    const pins = units.slice(0, 30).map((unit) => unit.unit_id);
    const activeUnitId = activeFromOrdinal(units, 203);
    const plan = planReadingWindow({ units, activeUnitId, pinnedUnitIds: pins });
    expect(plan.pinnedUnitIds).toEqual(pins);
    expect(plan.overflowPinnedUnitIds).toEqual(pins.slice(20));
    expect(pins.every((id) => plan.mountedUnitIds.includes(id))).toBe(true);
    expect(plan.mountedUnitIds).toHaveLength(140);
    expect(plan.autoPrefetch).toBe(false);
    expect(plan.requiresExplicitLoad).toBe(true);
    const released = planReadingWindow({ units, activeUnitId, pinnedUnitIds: pins.slice(0, 20) });
    expect(released.autoPrefetch).toBe(true);
    expect(released.requiresExplicitLoad).toBe(false);
  });

  it("requests the next and previous pages after multiple normal window recycles", () => {
    const units = Array.from({ length: 320 }, (_, ordinal) => makeUnit(ordinal, "连续正文。"));
    const edges = { firstOrdinal: 0, lastOrdinal: 319, hasPrevious: true, hasNext: true };
    for (const [ordinal, direction] of [[315, "next"], [4, "previous"]] as const) {
      const activeUnitId = units[ordinal].unit_id;
      const window = planReadingWindow({ units, activeUnitId });
      expect(window.mountedUnitIds).toHaveLength(120);
      expect(planAutoPrefetch({ autoPrefetch: window.autoPrefetch, units, edges, activeUnitId }).requests)
        .toEqual([direction]);
    }
  });

  it("defers a new target when every slot protects operated DOM, then admits it on release", () => {
    const units = Array.from({ length: 600 }, (_, ordinal) => makeUnit(ordinal, "连续正文。"));
    const previous = planReadingWindow({
      units, activeUnitId: units[300].unit_id,
      pinnedUnitIds: units.slice(0, 20).map((unit) => unit.unit_id),
    });
    expect(previous.mountedUnitIds).toHaveLength(140);
    const target = units[500].unit_id;
    const blocked = planReadingWindow({
      units, activeUnitId: target,
      pinnedUnitIds: [target, ...previous.mountedUnitIds],
      previousMountedUnitIds: previous.mountedUnitIds,
    });
    expect(blocked.mountedUnitIds).toEqual(previous.mountedUnitIds);
    expect(blocked.mountedUnitIds).not.toContain(target);
    expect(blocked.autoPrefetch).toBe(false);
    expect(blocked.overflowPinnedUnitIds).toContain(target);
    const released = planReadingWindow({
      units, activeUnitId: target, pinnedUnitIds: [target],
      previousMountedUnitIds: blocked.mountedUnitIds,
    });
    expect(released.mountedUnitIds).toContain(target);
    expect(released.mountedUnitIds).toHaveLength(120);
    expect(released.autoPrefetch).toBe(true);
  });

  it("admits a pending distant target before the controller commits a new active unit", () => {
    const units = Array.from({ length: 1000 }, (_, ordinal) => makeUnit(ordinal, "连续正文。"));
    const activeUnitId = units[600].unit_id;
    const before = planReadingWindow({ units, activeUnitId });
    const pending = units[0].unit_id;
    const locating = planReadingWindow({
      units, activeUnitId, pinnedUnitIds: [pending], previousMountedUnitIds: before.mountedUnitIds,
    });
    expect(locating.mountedUnitIds).toContain(activeUnitId);
    expect(locating.mountedUnitIds).toContain(pending);
    expect(locating.mountedUnitIds).toHaveLength(121);
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
  it("renders units in ordinal order and only marks the verifiable chapter boundary", () => {
    const html = renderToString(
      React.createElement(ReadingWindow, {
        pages: [INITIAL_PAGE, NEXT_PAGE],
        activeUnitId: activeFromOrdinal(mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE]), 6),
        chapterTitles: CHAPTER_TITLES,
      }),
    );
    expect(html.match(/data-test="reading-unit"/g)?.length).toBe(6);
    // 页从 ordinal 3（章中间）开始：章 A 起点不可验证，不显示；只显示连续的章 B 边界。
    expect(html.match(/data-test="reading-chapter-heading"/g)).toHaveLength(1);
    expect(html).toContain('data-test="reading-chapter-heading" data-chapter-id="' + CHAPTER_B + '"');
    expect(html).not.toContain('data-test="reading-chapter-heading" data-chapter-id="' + CHAPTER_A + '"');
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

  it("renders placeholders without a pause during ordinary recycling", () => {
    const units = mergeReadingUnitPages([INITIAL_PAGE, NEXT_PAGE, BULK_PAGE]);
    const html = renderToString(
      React.createElement(ReadingWindow, {
        pages: [INITIAL_PAGE, NEXT_PAGE, BULK_PAGE],
        activeUnitId: activeFromOrdinal(units, 4),
      }),
    );
    expect(html).not.toContain('data-test="reading-paused"');
    expect(html).toContain('data-auto-prefetch="true"');
    expect(html).toContain('data-test="reading-unit-placeholder"');
    expect((html.match(/data-test="reading-unit"/g) ?? []).length).toBeLessThanOrEqual(120);
  });

  it("offers explicit loading while retaining pins that exceed the extra allowance", () => {
    const pages = [INITIAL_PAGE, NEXT_PAGE, BULK_PAGE];
    const units = mergeReadingUnitPages(pages);
    const html = renderToString(React.createElement(ReadingWindow, {
      pages,
      activeUnitId: activeFromOrdinal(units, 203),
      pinnedUnitIds: units.slice(0, 30).map((unit) => unit.unit_id),
    }));
    expect(html).toContain('data-test="reading-paused"');
    expect(html).toContain('data-test="reading-manual-next"');
    expect(html).toContain('data-test="reading-load-more"');
    expect((html.match(/data-test="reading-unit"/g) ?? []).length).toBeLessThanOrEqual(140);
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
