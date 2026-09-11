import { describe, expect, it } from "vitest";

import {
  buildReadingUrl,
  createFrameScheduler,
  nextNavigationState,
  parseReadingUrl,
  readReturnToken,
  referenceLineFor,
  relativeOffsetWithin,
  selectActiveUnit,
  snapshotMatches,
  withReturnToken,
  type MeasuredUnit,
} from "../src/lib/reading-location";

const STREAM = "01890a5d-ac96-774b-bcce-b302099a8057";
const OTHER_STREAM = "01890a5d-ac96-774b-bcce-b302099a8058";
const CATALOG = "a".repeat(64);
const OTHER_CATALOG = "b".repeat(64);
const UNIT = `ru_${"c".repeat(24)}`;

describe("typed reading locator parse/build", () => {
  it("parses a complete same-site reading URL", () => {
    const result = parseReadingUrl(`/read/${STREAM}?catalog=${CATALOG}&at=${UNIT}`);
    expect(result).toEqual({
      ok: true,
      location: { stream_id: STREAM, catalog_sha: CATALOG, unit_id: UNIT },
    });
  });

  it("allows omitting at so reading can start at the first unit", () => {
    const result = parseReadingUrl(`/read/${STREAM}?catalog=${CATALOG}`);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.location.unit_id).toBeNull();
    }
  });

  it("accepts an absolute same-origin URL but rejects external targets", () => {
    expect(parseReadingUrl(`https://loom.local/read/${STREAM}?catalog=${CATALOG}&at=${UNIT}`).ok).toBe(true);
    expect(parseReadingUrl(`https://evil.example/read/${STREAM}?catalog=${CATALOG}&at=${UNIT}`)).toEqual({
      ok: false,
      issue: { code: "unsupported_target", detail: "external origin https://evil.example" },
    });
    expect(parseReadingUrl("javascript:alert(1)")).toMatchObject({ ok: false, issue: { code: "unsupported_target" } });
  });

  it("treats duplicate, unknown and wrong-typed query fields as explicit errors", () => {
    expect(parseReadingUrl(`/read/${STREAM}?catalog=${CATALOG}&catalog=${CATALOG}`)).toMatchObject({
      ok: false,
      issue: { code: "duplicate_param" },
    });
    expect(parseReadingUrl(`/read/${STREAM}?catalog=${CATALOG}&return_to=https://evil.example`)).toMatchObject({
      ok: false,
      issue: { code: "unknown_param" },
    });
    expect(parseReadingUrl(`/read/${STREAM}?catalog=${CATALOG}&at=not-a-unit`)).toMatchObject({
      ok: false,
      issue: { code: "invalid_unit" },
    });
    expect(parseReadingUrl(`/read/not-a-uuid?catalog=${CATALOG}&at=${UNIT}`)).toMatchObject({
      ok: false,
      issue: { code: "invalid_stream" },
    });
    expect(parseReadingUrl(`/read/${STREAM}?catalog=zzz&at=${UNIT}`)).toMatchObject({
      ok: false,
      issue: { code: "invalid_catalog" },
    });
    expect(parseReadingUrl(`/read/${STREAM}`)).toMatchObject({ ok: false, issue: { code: "missing_catalog" } });
    expect(parseReadingUrl("/read")).toMatchObject({ ok: false, issue: { code: "missing_stream" } });
    expect(parseReadingUrl("/timeline")).toMatchObject({ ok: false, issue: { code: "unsupported_target" } });
  });

  it("builds URLs only from validated typed fields", () => {
    const url = buildReadingUrl({ stream_id: STREAM, catalog_sha: CATALOG, unit_id: UNIT });
    expect(url).toBe(`/read/${STREAM}?catalog=${CATALOG}&at=${UNIT}`);
    expect(parseReadingUrl(url)).toEqual({
      ok: true,
      location: { stream_id: STREAM, catalog_sha: CATALOG, unit_id: UNIT },
    });
    expect(() => buildReadingUrl({ stream_id: "nope", catalog_sha: CATALOG, unit_id: UNIT })).toThrow();
    expect(() => buildReadingUrl({ stream_id: OTHER_STREAM, catalog_sha: "short", unit_id: UNIT })).toThrow();
  });

  it("keeps return tokens on same-site paths and ignores external return_to", () => {
    expect(withReturnToken("/events/abc?catalog=x", "rt_0")).toBe("/events/abc?catalog=x&return=rt_0");
    expect(() => withReturnToken("https://evil.example/events/abc", "rt_0")).toThrow();
    expect(() => withReturnToken("//evil.example/events", "rt_0")).toThrow();
    expect(readReturnToken("?return=rt_0&return_to=https://evil.example")).toBe("rt_0");
    expect(readReturnToken("?return_to=https://evil.example")).toBeNull();
  });

  it("detects a snapshot mismatch instead of silently upgrading", () => {
    const parsed = parseReadingUrl(`/read/${STREAM}?catalog=${CATALOG}&at=${UNIT}`);
    if (!parsed.ok) throw new Error("expected parse");
    expect(snapshotMatches(parsed.location, CATALOG)).toBe(true);
    expect(snapshotMatches(parsed.location, OTHER_CATALOG)).toBe(false);
    expect(snapshotMatches({ ...parsed.location, unit_id: null }, OTHER_CATALOG)).toBe(false);
  });
});

describe("reference-line active unit selection", () => {
  const measured = (unitId: string, ordinal: number, top: number, bottom: number, visible = true): MeasuredUnit => ({
    unitId,
    ordinal,
    top,
    bottom,
    visible,
  });

  it("picks the unit crossing the reference line", () => {
    const units = [measured("a", 0, -200, 100), measured("b", 1, 100, 300), measured("c", 2, 300, 500)];
    expect(selectActiveUnit(units, 200)?.unitId).toBe("b");
  });

  it("when the line is in a gap takes the following visible unit", () => {
    const units = [measured("a", 0, -200, 90), measured("b", 1, 120, 300)];
    expect(selectActiveUnit(units, 100)?.unitId).toBe("b");
  });

  it("at the end returns the last visible unit", () => {
    const units = [measured("a", 0, -200, 90), measured("b", 1, 100, 300)];
    expect(selectActiveUnit(units, 4000)?.unitId).toBe("b");
  });

  it("prefers the following unit when the line sits exactly on a boundary", () => {
    const units = [measured("a", 0, -200, 100), measured("b", 1, 100, 300)];
    expect(selectActiveUnit(units, 100)?.unitId).toBe("b");
    expect(selectActiveUnit(units, -200)?.unitId).toBe("a");
  });

  it("breaks overlaps by ordinal and ignores hidden units", () => {
    const units = [measured("a", 5, 0, 400), measured("b", 2, 100, 500), measured("c", 1, 0, 999, false)];
    expect(selectActiveUnit(units, 200)?.unitId).toBe("b");
    expect(selectActiveUnit([measured("c", 1, 0, 999, false)], 10)).toBeNull();
    expect(selectActiveUnit([], 10)).toBeNull();
  });

  it("returns a bounded relative offset inside the unit", () => {
    expect(relativeOffsetWithin({ top: 100, bottom: 300 }, 200)).toBeCloseTo(0.5);
    expect(relativeOffsetWithin({ top: 100, bottom: 300 }, 50)).toBe(0);
    expect(relativeOffsetWithin({ top: 100, bottom: 300 }, 999)).toBe(1);
    expect(relativeOffsetWithin({ top: 100, bottom: 100 }, 120)).toBe(0);
  });

  it("places the reference line 30% below the sticky header", () => {
    expect(referenceLineFor(1000, 0)).toBeCloseTo(300);
    expect(referenceLineFor(1000, 100)).toBeCloseTo(370);
    expect(referenceLineFor(100, 200)).toBeCloseTo(200);
  });
});

describe("rAF batching", () => {
  function fakeFrames() {
    const pending = new Map<number, FrameRequestCallback>();
    let nextId = 0;
    return {
      requestFrame: (callback: FrameRequestCallback) => {
        nextId += 1;
        pending.set(nextId, callback);
        return nextId;
      },
      cancelFrame: (handle: number) => {
        pending.delete(handle);
      },
      flush: () => {
        const callbacks = [...pending.values()];
        pending.clear();
        callbacks.forEach((callback) => callback(0));
      },
      pendingCount: () => pending.size,
    };
  }

  it("coalesces many calls into one frame", () => {
    const frames = fakeFrames();
    const scheduler = createFrameScheduler(frames.requestFrame, frames.cancelFrame);
    let runs = 0;
    scheduler.schedule(() => {
      runs += 1;
    });
    scheduler.schedule(() => {
      runs += 1;
    });
    scheduler.schedule(() => {
      runs += 1;
    });
    expect(runs).toBe(0);
    expect(scheduler.pending()).toBe(true);
    expect(frames.pendingCount()).toBe(1);
    frames.flush();
    expect(runs).toBe(1);
    expect(scheduler.pending()).toBe(false);
  });

  it("cancels a pending frame", () => {
    const frames = fakeFrames();
    const scheduler = createFrameScheduler(frames.requestFrame, frames.cancelFrame);
    let runs = 0;
    scheduler.schedule(() => {
      runs += 1;
    });
    scheduler.cancel();
    frames.flush();
    expect(runs).toBe(0);
  });
});

describe("navigation state machine", () => {
  it("tracks explicit navigation, restoring and user interruption", () => {
    expect(nextNavigationState("idle", "begin_navigation")).toBe("navigating");
    expect(nextNavigationState("navigating", "settled")).toBe("idle");
    expect(nextNavigationState("idle", "begin_restore")).toBe("restoring");
    expect(nextNavigationState("restoring", "user_scrolled")).toBe("interrupted");
    expect(nextNavigationState("navigating", "user_scrolled")).toBe("interrupted");
    expect(nextNavigationState("idle", "user_scrolled")).toBe("idle");
    expect(nextNavigationState("interrupted", "settled")).toBe("idle");
    expect(nextNavigationState("interrupted", "cancelled")).toBe("idle");
  });
});
