// C2-R2-T13 事件预览有界异步缓存。
//
// 合同见 reading-experience.md §5：缓存按 catalog + event_id，合并并发同请求，
// 最多 100 个事件、总 payload 至多 2 MiB、每条不超过协议响应上限，LRU 淘汰；
// 只在 hover/focus/tap 按需加载，不为全文事件预取。关闭或换词后迟到的响应由
// 触发组件用 stale guard 丢弃；缓存 key 带 catalog，快照之间互不覆盖。
//
// 本模块不接 App/router，不访问网络。

import { READING_LIMITS } from "./reading-types";

export const PREVIEW_CACHE_MAX_ENTRIES = 100;
export const PREVIEW_CACHE_MAX_TOTAL_BYTES = 2 * 1024 * 1024;
export const PREVIEW_CACHE_MAX_ENTRY_BYTES = READING_LIMITS.previewMaxBytes;

export interface ReadingPreviewCacheOptions {
  readonly maxEntries?: number;
  readonly maxTotalBytes?: number;
  readonly maxEntryBytes?: number;
}

export interface ReadingPreviewCacheStats {
  readonly size: number;
  readonly totalBytes: number;
  readonly inFlight: number;
}

interface CacheEntry {
  readonly value: unknown;
  readonly bytes: number;
}

/** UTF-8 字节数；缓存计费与单条上限都按真实传输字节而不是字符数。 */
export function jsonByteLength(value: unknown): number {
  let json: string;
  try {
    json = JSON.stringify(value) ?? String(value);
  } catch {
    json = String(value);
  }
  if (typeof TextEncoder !== "undefined") {
    return new TextEncoder().encode(json).length;
  }
  return unescape(encodeURIComponent(json)).length;
}

/** catalog 是快照身份的一部分：同一 event 在不同 catalog 不得共享缓存。 */
export function eventPreviewCacheKey(catalogSha: string, eventId: string): string {
  return `event-preview:${catalogSha}:${eventId}`;
}

export function eventTargetsCacheKey(catalogSha: string, eventId: string): string {
  return `event-targets:${catalogSha}:${eventId}`;
}

/**
 * 有界 LRU 异步缓存。`load` 在同一 key 上合并并发请求并复用进行中的 Promise；
 * 成功结果在不超过单条协议上限时写入缓存，失败不缓存。`set` 返回是否真正存入
 * （超过单条上限时只把结果交给调用方，不进入缓存）。
 */
export class ReadingPreviewCache {
  private readonly maxEntries: number;
  private readonly maxTotalBytes: number;
  private readonly maxEntryBytes: number;
  private readonly entries = new Map<string, CacheEntry>();
  private readonly pending = new Map<string, Promise<unknown>>();
  private bytes = 0;

  constructor(options: ReadingPreviewCacheOptions = {}) {
    this.maxEntries = options.maxEntries ?? PREVIEW_CACHE_MAX_ENTRIES;
    this.maxTotalBytes = options.maxTotalBytes ?? PREVIEW_CACHE_MAX_TOTAL_BYTES;
    this.maxEntryBytes = options.maxEntryBytes ?? PREVIEW_CACHE_MAX_ENTRY_BYTES;
  }

  get size(): number {
    return this.entries.size;
  }

  get totalBytes(): number {
    return this.bytes;
  }

  stats(): ReadingPreviewCacheStats {
    return { size: this.entries.size, totalBytes: this.bytes, inFlight: this.pending.size };
  }

  has(key: string): boolean {
    return this.entries.has(key);
  }

  /** 读取并刷新 LRU 次序；不触发加载。 */
  peek<T>(key: string): T | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.value as T;
  }

  set<T>(key: string, value: T, bytes: number = jsonByteLength(value)): boolean {
    const size = Number.isFinite(bytes) && bytes >= 0 ? bytes : jsonByteLength(value);
    if (size > this.maxEntryBytes) {
      // 单条超过协议响应上限：交给调用方，但不进入缓存。
      this.drop(key);
      return false;
    }
    this.drop(key);
    this.entries.set(key, { value, bytes: size });
    this.bytes += size;
    this.evict();
    return true;
  }

  delete(key: string): void {
    this.drop(key);
  }

  clear(): void {
    this.entries.clear();
    this.pending.clear();
    this.bytes = 0;
  }

  load<T>(key: string, loader: () => Promise<T>, bytes?: (value: T) => number): Promise<T> {
    const cached = this.entries.get(key);
    if (cached) {
      this.entries.delete(key);
      this.entries.set(key, cached);
      return Promise.resolve(cached.value as T);
    }
    const inFlight = this.pending.get(key);
    if (inFlight) return inFlight as Promise<T>;
    const request = (async () => {
      try {
        const value = await loader();
        this.set(key, value, bytes ? bytes(value) : jsonByteLength(value));
        return value;
      } finally {
        this.pending.delete(key);
      }
    })();
    this.pending.set(key, request);
    return request;
  }

  private drop(key: string): void {
    const existing = this.entries.get(key);
    if (!existing) return;
    this.entries.delete(key);
    this.bytes -= existing.bytes;
    if (this.bytes < 0) this.bytes = 0;
  }

  private evict(): void {
    while (this.entries.size > this.maxEntries || this.bytes > this.maxTotalBytes) {
      const oldest = this.entries.keys().next();
      if (oldest.done) break;
      this.drop(oldest.value);
    }
  }
}

/** 页面共享默认实例；T15 挂接时可注入自己的实例（同一 catalog 语义）。 */
export const readingPreviewCache = new ReadingPreviewCache();
