// C2-R2-T13 事件预览缓存单元测试。
//
// 覆盖 reading-experience.md §5 的缓存纪律：key 带 catalog + event_id、并发同请求
// 合并、最多 100 条且总 payload 不超过上限、单条不超过协议响应上限、LRU 淘汰、
// 失败不缓存可重试、快照隔离。全部为合成数据，不代表真实后端。

import { describe, expect, it } from "vitest";
import {
  ReadingPreviewCache,
  eventPreviewCacheKey,
  eventTargetsCacheKey,
  jsonByteLength,
  PREVIEW_CACHE_MAX_ENTRIES,
  PREVIEW_CACHE_MAX_TOTAL_BYTES,
  PREVIEW_CACHE_MAX_ENTRY_BYTES,
} from "../src/lib/reading-preview-cache";

const CATALOG_A = "a".repeat(64);
const CATALOG_B = "b".repeat(64);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("event preview cache keys", () => {
  it("includes catalog and event so snapshots never share entries", () => {
    expect(eventPreviewCacheKey(CATALOG_A, "evt_1")).not.toBe(eventPreviewCacheKey(CATALOG_B, "evt_1"));
    expect(eventPreviewCacheKey(CATALOG_A, "evt_1")).not.toBe(eventPreviewCacheKey(CATALOG_A, "evt_2"));
    expect(eventPreviewCacheKey(CATALOG_A, "evt_1")).toContain(CATALOG_A);
  });

  it("keeps preview and targets namespaces apart", () => {
    expect(eventPreviewCacheKey(CATALOG_A, "evt_1")).not.toBe(eventTargetsCacheKey(CATALOG_A, "evt_1"));
  });

  it("exposes the documented limits", () => {
    expect(PREVIEW_CACHE_MAX_ENTRIES).toBe(100);
    expect(PREVIEW_CACHE_MAX_TOTAL_BYTES).toBe(2 * 1024 * 1024);
    expect(PREVIEW_CACHE_MAX_ENTRY_BYTES).toBe(64 * 1024);
  });

  it("counts UTF-8 bytes, not UTF-16 code units", () => {
    expect(jsonByteLength("赤壁")).toBe(new TextEncoder().encode(JSON.stringify("赤壁")).length);
    expect(jsonByteLength("赤壁")).toBeGreaterThan(JSON.stringify("赤壁").length);
  });
});

describe("ReadingPreviewCache.load", () => {
  it("caches a successful load and reuses it without calling the loader again", async () => {
    const cache = new ReadingPreviewCache();
    let calls = 0;
    const loader = async () => {
      calls += 1;
      return { name: "赤壁之戰" };
    };
    const first = await cache.load("k", loader);
    const second = await cache.load("k", loader);
    expect(first).toEqual({ name: "赤壁之戰" });
    expect(second).toEqual(first);
    expect(calls).toBe(1);
    expect(cache.size).toBe(1);
    expect(cache.totalBytes).toBeGreaterThan(0);
  });

  it("coalesces concurrent requests for the same key", async () => {
    const cache = new ReadingPreviewCache();
    let calls = 0;
    const gate = deferred<number>();
    const loader = () => {
      calls += 1;
      return gate.promise;
    };
    const first = cache.load("shared", loader);
    const second = cache.load("shared", loader);
    expect(calls).toBe(1);
    expect(cache.stats().inFlight).toBe(1);
    gate.resolve(7);
    await expect(Promise.all([first, second])).resolves.toEqual([7, 7]);
    expect(calls).toBe(1);
    expect(cache.stats().inFlight).toBe(0);
  });

  it("does not cache a rejected load and allows a retry", async () => {
    const cache = new ReadingPreviewCache();
    let calls = 0;
    const loader = async () => {
      calls += 1;
      if (calls === 1) throw new Error("controlled failure");
      return { name: "重试成功" };
    };
    await expect(cache.load("k", loader)).rejects.toThrow("controlled failure");
    expect(cache.size).toBe(0);
    expect(cache.stats().inFlight).toBe(0);
    await expect(cache.load("k", loader)).resolves.toEqual({ name: "重试成功" });
    expect(calls).toBe(2);
    expect(cache.size).toBe(1);
  });

  it("isolates the same event id across catalogs", async () => {
    const cache = new ReadingPreviewCache();
    const loadA = await cache.load(eventPreviewCacheKey(CATALOG_A, "evt_1"), async () => "A");
    const loadB = await cache.load(eventPreviewCacheKey(CATALOG_B, "evt_1"), async () => "B");
    expect(loadA).toBe("A");
    expect(loadB).toBe("B");
    expect(cache.size).toBe(2);
  });
});

describe("ReadingPreviewCache bounds", () => {
  it("evicts least-recently-used entries past the entry cap", () => {
    const cache = new ReadingPreviewCache({ maxEntries: 2 });
    cache.set("k1", { v: 1 });
    cache.set("k2", { v: 2 });
    cache.set("k3", { v: 3 });
    expect(cache.size).toBe(2);
    expect(cache.peek("k1")).toBeUndefined();
    expect(cache.peek("k3")).toEqual({ v: 3 });

    // k2 被 peek 刷新为最近使用；写入 k4 应淘汰 k3。
    expect(cache.peek("k2")).toEqual({ v: 2 });
    cache.set("k4", { v: 4 });
    expect(cache.peek("k3")).toBeUndefined();
    expect(cache.peek("k2")).toEqual({ v: 2 });
    expect(cache.peek("k4")).toEqual({ v: 4 });
  });

  it("evicts until the total byte budget is respected", () => {
    const cache = new ReadingPreviewCache({ maxTotalBytes: 10 });
    cache.set("k1", { v: 1 }, 6);
    cache.set("k2", { v: 2 }, 6);
    expect(cache.totalBytes).toBeLessThanOrEqual(10);
    expect(cache.peek("k1")).toBeUndefined();
    expect(cache.peek("k2")).toEqual({ v: 2 });
  });

  it("refuses to cache an entry over the per-response protocol limit", async () => {
    const cache = new ReadingPreviewCache({ maxEntryBytes: 5 });
    expect(cache.set("k", { big: true }, 6)).toBe(false);
    expect(cache.size).toBe(0);

    const value = await cache.load("k", async () => ({ big: true }), () => 6);
    expect(value).toEqual({ big: true });
    expect(cache.size).toBe(0);
    expect(cache.stats().inFlight).toBe(0);
  });

  it("clear() drops entries and in-flight bookkeeping", () => {
    const cache = new ReadingPreviewCache();
    cache.set("k", { v: 1 });
    cache.clear();
    expect(cache.size).toBe(0);
    expect(cache.totalBytes).toBe(0);
    expect(cache.stats().inFlight).toBe(0);
  });
});
