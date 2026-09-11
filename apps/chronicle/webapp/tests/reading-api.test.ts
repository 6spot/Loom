// C2-R2-T09 typed reading client 单元测试。
//
// 覆盖 continuous-reading.md §6 / reading-experience.md §5-6 的 client 纪律：
// 路径显式携带 catalog/stream/unit/cursor；query key 以 snapshot 为身份，换
// catalog 不复用；错误/非 JSON/abort/迟到响应都走显式分支。全部为合成数据。

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createReadingStaleGuard,
  fetchReadingEventPreview,
  fetchReadingJSON,
  fetchReadingStreamUnits,
  loadReadingEventPreview,
  ReadingAbortError,
  ReadingApiError,
  readingEventPreviewPath,
  readingEventTargetsPath,
  readingKeys,
  readingStreamDetailPath,
  readingStreamLocatePath,
  readingStreamsPath,
  readingStreamUnitsPath,
  unitLocator,
} from "../src/lib/reading-api";
import { ReadingPreviewCache, eventPreviewCacheKey } from "../src/lib/reading-preview-cache";

const CATALOG_A = "a".repeat(64);
const CATALOG_B = "b".repeat(64);
const STREAM_A = "00000000-0000-7000-8000-000000000000";
const STREAM_B = "11111111-1111-7000-8000-111111111111";
const UNIT_A = "ru_0123456789abcdef01234567";
const EVENT_A = "01a05cd7-439d-7071-bf00-86c664886b06";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(handler: (path: string) => Response | Promise<Response>) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      calls.push(path);
      return handler(path);
    }),
  );
  return calls;
}

describe("reading client paths bind snapshot/stream/unit explicitly", () => {
  it("builds the directory path with catalog/limit/cursor", () => {
    expect(readingStreamsPath({})).toBe("/api/v1/public/reading-streams?limit=20");
    const path = readingStreamsPath({ catalog: CATALOG_A, limit: 5, cursor: "c1" });
    expect(path).toContain("/api/v1/public/reading-streams?");
    expect(path).toContain(`catalog=${CATALOG_A}`);
    expect(path).toContain("limit=5");
    expect(path).toContain("cursor=c1");
  });

  it("builds stream/units/locate paths with the exact catalog and cursor", () => {
    expect(readingStreamDetailPath(STREAM_A, { catalog: CATALOG_A })).toBe(
      `/api/v1/public/reading-streams/${STREAM_A}?catalog=${CATALOG_A}`,
    );
    const units = readingStreamUnitsPath(STREAM_A, {
      catalog: CATALOG_A,
      cursor: "unit-cursor",
      direction: "forward",
    });
    expect(units).toBe(
      `/api/v1/public/reading-streams/${STREAM_A}/units?catalog=${CATALOG_A}&limit=20&cursor=unit-cursor&direction=forward`,
    );
    const locate = readingStreamLocatePath(STREAM_A, { catalog: CATALOG_A, unitId: UNIT_A });
    expect(locate).toBe(
      `/api/v1/public/reading-streams/${STREAM_A}/locate?catalog=${CATALOG_A}&unit_id=${UNIT_A}&limit=20`,
    );
  });

  it("builds event preview/targets paths with catalog", () => {
    expect(readingEventPreviewPath(EVENT_A, { catalog: CATALOG_A })).toBe(
      `/api/v1/public/reading-events/${EVENT_A}/preview?catalog=${CATALOG_A}`,
    );
    const targets = readingEventTargetsPath(EVENT_A, { catalog: CATALOG_A, limit: 10 });
    expect(targets).toBe(
      `/api/v1/public/reading-events/${EVENT_A}/targets?catalog=${CATALOG_A}&limit=10`,
    );
  });

  it("rejects malformed catalog/stream/unit before any URL exists", () => {
    expect(() => readingStreamDetailPath(STREAM_A, { catalog: "not-a-sha" })).toThrow(
      ReadingApiError,
    );
    expect(() => readingStreamDetailPath("not-a-uuid", { catalog: CATALOG_A })).toThrow(
      ReadingApiError,
    );
    expect(() => readingStreamLocatePath(STREAM_A, { catalog: CATALOG_A, unitId: "nope" })).toThrow(
      ReadingApiError,
    );
  });
});

describe("reading query keys isolate snapshots", () => {
  it("keeps canonical id distinct from snapshot identity", () => {
    const a = readingKeys.preview(EVENT_A, CATALOG_A);
    const b = readingKeys.preview(EVENT_A, CATALOG_B);
    expect(a).not.toEqual(b);
    expect(a).toContain(CATALOG_A);
    expect(b).toContain(CATALOG_B);
  });

  it("distinguishes streams and cursors", () => {
    expect(readingKeys.stream(STREAM_A, CATALOG_A)).not.toEqual(
      readingKeys.stream(STREAM_B, CATALOG_A),
    );
    expect(
      readingKeys.units(STREAM_A, { catalog: CATALOG_A, cursor: "c1" }),
    ).not.toEqual(readingKeys.units(STREAM_A, { catalog: CATALOG_A, cursor: "c2" }));
  });

  it("derives a typed locator only from validated fields", () => {
    expect(unitLocator(STREAM_A, CATALOG_A, UNIT_A)).toEqual({
      stream_id: STREAM_A,
      catalog_sha: CATALOG_A,
      unit_id: UNIT_A,
    });
    expect(() => unitLocator(STREAM_A, "bad", UNIT_A)).toThrow(ReadingApiError);
  });
});

describe("reading fetch error handling", () => {
  it("surfaces the typed error envelope", async () => {
    stubFetch(() =>
      jsonResponse(
        { schema: "chronicle.error", version: "0.1", error: { code: "not_found", message: "missing" } },
        404,
      ),
    );
    await expect(fetchReadingEventPreview(EVENT_A, { catalog: CATALOG_A })).rejects.toMatchObject({
      status: 404,
      code: "not_found",
    });
  });

  it("rejects a non-JSON success body explicitly", async () => {
    stubFetch(() => new Response("<html>shell</html>", { status: 200 }));
    await expect(fetchReadingEventPreview(EVENT_A, { catalog: CATALOG_A })).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("maps a connection failure to network_error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("connection refused");
      }),
    );
    await expect(fetchReadingEventPreview(EVENT_A, { catalog: CATALOG_A })).rejects.toMatchObject({
      status: 0,
      code: "network_error",
    });
  });

  it("raises ReadingAbortError when the signal is already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    stubFetch(() => jsonResponse({ ok: true }));
    await expect(
      fetchReadingJSON("/api/v1/public/reading-streams", { signal: controller.signal }),
    ).rejects.toBeInstanceOf(ReadingAbortError);
  });

  it("returns the parsed envelope on success", async () => {
    const payload = {
      schema: "chronicle.reading-stream-directory",
      version: "0.1",
      snapshot: { catalog_sha: CATALOG_A, publication_sequence: 3 },
      query: {},
      page: { streams: [], limit: 20, has_more: false, next_cursor: null },
    };
    stubFetch(() => jsonResponse(payload));
    await expect(fetchReadingStreamUnits(STREAM_A, { catalog: CATALOG_A })).resolves.toEqual(payload);
  });
});

describe("reading preview cache is snapshot-scoped", () => {
  it("calls fetch once per catalog and never reuses the other snapshot's preview", async () => {
    const cache = new ReadingPreviewCache();
    const calls = stubFetch((path) => {
      const catalog = path.includes(CATALOG_B) ? CATALOG_B : CATALOG_A;
      return jsonResponse({
        event_id: EVENT_A,
        catalog_sha: catalog,
        name: catalog === CATALOG_A ? "A" : "B",
        sources: [],
        source_count: 0,
        has_more_sources: false,
      });
    });

    const first = await loadReadingEventPreview(EVENT_A, CATALOG_A, undefined, cache);
    const again = await loadReadingEventPreview(EVENT_A, CATALOG_A, undefined, cache);
    const other = await loadReadingEventPreview(EVENT_A, CATALOG_B, undefined, cache);

    expect(first.name).toBe("A");
    expect(again.name).toBe("A");
    expect(other.name).toBe("B");
    expect(calls).toHaveLength(2);
    expect(cache.has(eventPreviewCacheKey(CATALOG_A, EVENT_A))).toBe(true);
    expect(cache.has(eventPreviewCacheKey(CATALOG_B, EVENT_A))).toBe(true);
  });
});

describe("reading stale guard drops late responses", () => {
  it("only accepts the latest token", () => {
    const guard = createReadingStaleGuard();
    const first = guard.next();
    const second = guard.next();
    expect(guard.isCurrent(first)).toBe(false);
    expect(guard.isCurrent(second)).toBe(true);
  });
});
