import { describe, expect, it } from "vitest";
import { mergeEventTargetPages } from "../src/pages/public/EventPage";
import type { EventTarget, EventTargetPage } from "../src/lib/reading-types";

const CATALOG = "a".repeat(64);

function target(span: string, unit: string, relation: "current" | "mention" = "current"): EventTarget {
  return {
    event_id: "evt-1",
    catalog_sha: CATALOG,
    relation,
    stream_id: "00000000-0000-7000-8000-000000000000",
    publication_id: "pub-1",
    chapter_id: "ch-1",
    chapter_title: "第一章",
    source_title: "来源",
    unit_id: unit,
    span_id: span,
    locator: {
      stream_id: "00000000-0000-7000-8000-000000000000",
      catalog_sha: CATALOG,
      unit_id: unit,
    },
    excerpt: `${span}:${unit}`,
  };
}

function page(
  targets: EventTarget[],
  options: { current?: number; mention?: number; next?: string | null; hasMore?: boolean } = {},
): EventTargetPage {
  return {
    event_id: "evt-1",
    catalog_sha: CATALOG,
    targets,
    current_count: options.current ?? targets.filter((item) => item.relation === "current").length,
    mention_count: options.mention ?? targets.filter((item) => item.relation === "mention").length,
    next_cursor: options.next ?? null,
    has_more: options.hasMore ?? false,
  };
}

describe("event target pagination merge", () => {
  it("returns the first page unchanged when there is no current page", () => {
    const first = page([target("s1", "ru_000000000000000000000001")], { next: "c1", hasMore: true });
    expect(mergeEventTargetPages(null, first)).toEqual(first);
  });

  it("appends subsequent pages and advances cursor/counts", () => {
    const first = page([target("s1", "ru_000000000000000000000001")], {
      current: 1,
      next: "c1",
      hasMore: true,
    });
    const second = page([target("s2", "ru_000000000000000000000002")], {
      current: 2,
      mention: 1,
      next: null,
      hasMore: false,
    });
    const merged = mergeEventTargetPages(first, second);
    expect(merged.targets.map((item) => item.span_id)).toEqual(["s1", "s2"]);
    expect(merged.next_cursor).toBeNull();
    expect(merged.has_more).toBe(false);
    expect(merged.current_count).toBe(2);
    expect(merged.mention_count).toBe(1);
  });

  it("dedupes repeated (span_id, unit_id) across pages without losing order", () => {
    const first = page(
      [target("s1", "ru_000000000000000000000001"), target("s2", "ru_000000000000000000000002")],
      { next: "c1", hasMore: true },
    );
    const second = page(
      [target("s2", "ru_000000000000000000000002"), target("s3", "ru_000000000000000000000003", "mention")],
      { next: "c2", hasMore: true },
    );
    const merged = mergeEventTargetPages(first, second);
    expect(merged.targets.map((item) => item.span_id)).toEqual(["s1", "s2", "s3"]);
    expect(merged.next_cursor).toBe("c2");
    expect(merged.has_more).toBe(true);
  });
});
