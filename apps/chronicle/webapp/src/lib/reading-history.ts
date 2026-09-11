// Chronicle 第二轮阅读历史与返回栈纯 helper（C2-R2-T12）。
//
// 归属：按 history entry + stream/catalog/unit 存 unit 内相对位置与焦点；有界
// 返回栈（最多 20 项）与 storage 失败降级；本站不可预测 return token 指向 typed
// locator。持久化细节只保存在 sessionStorage，URL 仍可独立定位。状态语义见
// reading-experience.md §6。
//
// 安全边界：token 只映射到经 `isReadingLocator` 校验的 typed locator；缺失/
// 失效/被篡改的 token 一律解析为 null，调用方退回“进入相关正文”，绝不外部跳转。

import type { ReadingLocator } from "./reading-types";
import { isReadingLocator } from "./reading-types";

/** 返回栈硬上限（reading-experience.md §6）。 */
export const RETURN_STACK_LIMIT = 20;
/** 单个存储命名空间的字节上限，避免无限增长。 */
export const RETURN_STACK_MAX_BYTES = 16 * 1024;
/** 详情页 return token 在刷新后的有效窗口。 */
export const RETURN_TOKEN_TTL_MS = 24 * 60 * 60 * 1000;
/** sessionStorage key 前缀（仅当前 tab）。 */
export const READING_STORAGE_PREFIX = "chronicle.reading.v1.";

export const RETURN_TOKEN_PATTERN = /^rt_[0-9a-f]{32}$/;

/** 与浏览器 sessionStorage 对齐的最小接口，便于注入受控实现。 */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
  /** 可选枚举能力；不提供时 `findEntry` 只能依赖已知 history key。 */
  readonly length?: number;
  key?(index: number): string | null;
}

export interface StorageOutcome {
  readonly ok: boolean;
  readonly error?: string;
}

function storageOutcome(error?: unknown): StorageOutcome {
  if (error === undefined) return { ok: true };
  return { ok: false, error: error instanceof Error ? error.message : String(error) };
}

/** 安全包装：任何 storage 访问失败都不抛出，上层据此降级到 URL 定位。 */
export class ReadingStorage {
  constructor(
    private readonly store: StorageLike | null,
    private readonly prefix: string = READING_STORAGE_PREFIX,
  ) {}

  available(): boolean {
    if (!this.store) return false;
    const probe = `${this.prefix}__probe__`;
    try {
      this.store.setItem(probe, "1");
      this.store.removeItem(probe);
      return true;
    } catch {
      return false;
    }
  }

  get(key: string): string | null {
    if (!this.store) return null;
    try {
      return this.store.getItem(this.prefix + key);
    } catch {
      return null;
    }
  }

  set(key: string, value: string): StorageOutcome {
    if (!this.store) return storageOutcome(new Error("storage unavailable"));
    try {
      this.store.setItem(this.prefix + key, value);
      return storageOutcome();
    } catch (error) {
      return storageOutcome(error);
    }
  }

  remove(key: string): StorageOutcome {
    if (!this.store) return storageOutcome(new Error("storage unavailable"));
    try {
      this.store.removeItem(this.prefix + key);
      return storageOutcome();
    } catch (error) {
      return storageOutcome(error);
    }
  }

  /** 枚举命名空间下的 key（去掉前缀）；无枚举能力时返回空数组。 */
  keys(): string[] {
    if (!this.store || typeof this.store.key !== "function" || typeof this.store.length !== "number") {
      return [];
    }
    const found: string[] = [];
    try {
      for (let index = 0; index < this.store.length; index += 1) {
        const key = this.store.key(index);
        if (key && key.startsWith(this.prefix)) found.push(key.slice(this.prefix.length));
      }
    } catch {
      return [];
    }
    return found;
  }
}

// ---------------------------------------------------------------------------
// History entry：unit 内相对位置 + 触发焦点 + 来源展开状态
// ---------------------------------------------------------------------------

export interface ReadingHistoryEntry {
  /** 浏览器 history entry 的稳定 key（本控制器自己维护，不调用 history.back() 猜测）。 */
  readonly history_key: string;
  readonly locator: ReadingLocator;
  /** unit 内相对位置 0..1；禁止用旧 scrollY 跨版本恢复。 */
  readonly relative_offset: number;
  /** 触发导航的焦点标识（引用/事件词），用于恢复焦点。 */
  readonly focus_id: string | null;
  /** 来源展开状态（引用/来源面板是否展开）。 */
  readonly source_expanded: boolean;
}

export function historyEntryKey(historyKey: string, locator: ReadingLocator): string {
  return `entry.${historyKey}.${locator.stream_id}.${locator.catalog_sha}.${locator.unit_id}`;
}

export function clampRelativeOffset(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

type LocatorValidator = (value: unknown) => value is ReadingLocator;

function parseEntry(raw: string | null, validate: LocatorValidator): ReadingHistoryEntry | null {
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const candidate = value as Record<string, unknown>;
  if (typeof candidate.history_key !== "string") return null;
  if (!validate(candidate.locator)) return null;
  if (typeof candidate.relative_offset !== "number") return null;
  if (candidate.focus_id !== null && typeof candidate.focus_id !== "string") return null;
  if (typeof candidate.source_expanded !== "boolean") return null;
  return {
    history_key: candidate.history_key,
    locator: candidate.locator,
    relative_offset: clampRelativeOffset(candidate.relative_offset),
    focus_id: candidate.focus_id ?? null,
    source_expanded: candidate.source_expanded,
  };
}

// ---------------------------------------------------------------------------
// Return token 与有界返回栈
// ---------------------------------------------------------------------------

export interface ReturnTarget {
  readonly token: string;
  readonly locator: ReadingLocator;
  readonly created_at: number;
}

export type RandomBytes = (target: Uint8Array) => Uint8Array;

export function defaultRandomBytes(target: Uint8Array): Uint8Array {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi || typeof cryptoApi.getRandomValues !== "function") {
    throw new Error("secure random source unavailable");
  }
  return cryptoApi.getRandomValues(target);
}

/** 生成本站不可预测 return token；随机源不可用时明确抛错，不退回可预测值。 */
export function createReturnToken(randomBytes: RandomBytes = defaultRandomBytes): string {
  const bytes = randomBytes(new Uint8Array(16));
  let hex = "";
  for (const byte of bytes) hex += byte.toString(16).padStart(2, "0");
  return `rt_${hex}`;
}

function parseReturnTarget(raw: unknown, validate: LocatorValidator): ReturnTarget | null {
  if (typeof raw !== "object" || raw === null) return null;
  const candidate = raw as Record<string, unknown>;
  if (typeof candidate.token !== "string" || !RETURN_TOKEN_PATTERN.test(candidate.token)) {
    return null;
  }
  if (!validate(candidate.locator)) return null;
  if (typeof candidate.created_at !== "number") return null;
  return {
    token: candidate.token,
    locator: candidate.locator,
    created_at: candidate.created_at,
  };
}

const RETURN_STACK_KEY = "return_stack";

export interface RememberResult {
  readonly token: string;
  readonly persisted: boolean;
  readonly outcome: StorageOutcome;
}

export interface ReadingHistoryStoreOptions {
  readonly validateLocator?: LocatorValidator;
  readonly now?: () => number;
  readonly randomBytes?: RandomBytes;
  readonly maxEntries?: number;
  readonly maxBytes?: number;
  readonly ttlMs?: number;
}

/**
 * sessionStorage 支撑的阅读历史：entry 定位 + 有界返回栈。storage 不可用时
 * 所有操作安全降级（读返回 null、写返回 ok:false），不阻塞 URL 定位。
 */
export class ReadingHistoryStore {
  private readonly now: () => number;
  private readonly randomBytes: RandomBytes;
  private readonly maxEntries: number;
  private readonly maxBytes: number;
  private readonly ttlMs: number;
  private readonly validateLocator: LocatorValidator;

  constructor(
    private readonly storage: ReadingStorage,
    options: ReadingHistoryStoreOptions = {},
  ) {
    this.now = options.now ?? (() => Date.now());
    this.randomBytes = options.randomBytes ?? defaultRandomBytes;
    this.maxEntries = options.maxEntries ?? RETURN_STACK_LIMIT;
    this.maxBytes = options.maxBytes ?? RETURN_STACK_MAX_BYTES;
    this.ttlMs = options.ttlMs ?? RETURN_TOKEN_TTL_MS;
    this.validateLocator = options.validateLocator ?? isReadingLocator;
  }

  saveEntry(entry: ReadingHistoryEntry): StorageOutcome {
    const normalized: ReadingHistoryEntry = {
      ...entry,
      relative_offset: clampRelativeOffset(entry.relative_offset),
    };
    const result = this.storage.set(
      historyEntryKey(entry.history_key, entry.locator),
      JSON.stringify(normalized),
    );
    // An index to the existing entry; Storage.key() enumeration is not a
    // recency guarantee when an earlier history entry is updated on return.
    if (result.ok) this.storage.set(historyEntryKey("latest", entry.locator), JSON.stringify(normalized));
    return result;
  }

  loadEntry(historyKey: string, locator: ReadingLocator): ReadingHistoryEntry | null {
    const entry = parseEntry(this.storage.get(historyEntryKey(historyKey, locator)), this.validateLocator);
    return entry && entry.locator.stream_id === locator.stream_id && entry.locator.catalog_sha === locator.catalog_sha && entry.locator.unit_id === locator.unit_id ? entry : null;
  }

  /**
   * 刷新/深链接没有本站 history key 时，按 stream/catalog/unit 找最近一次记录，
   * 用于恢复 unit 内相对位置与焦点；匹配不到返回 null，不按年份猜位置。
   */
  findEntry(locator: ReadingLocator, historyKeys: readonly string[] = []): ReadingHistoryEntry | null {
    for (const key of historyKeys) {
      const found = this.loadEntry(key, locator);
      if (found) return found;
    }
    const latest = this.loadEntry("latest", locator);
    if (latest) return latest;
    let match: ReadingHistoryEntry | null = null;
    for (const key of this.storage.keys()) {
      if (!key.startsWith("entry.")) continue;
      const entry = parseEntry(this.storage.get(key), this.validateLocator);
      if (!entry) continue;
      if (
        entry.locator.stream_id === locator.stream_id &&
        entry.locator.catalog_sha === locator.catalog_sha &&
        entry.locator.unit_id === locator.unit_id
      ) {
        match = entry;
      }
    }
    return match;
  }

  loadReturnStack(): ReturnTarget[] {
    const raw = this.storage.get(RETURN_STACK_KEY);
    if (!raw) return [];
    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch {
      return [];
    }
    if (!Array.isArray(value)) return [];
    return value
      .map((item) => parseReturnTarget(item, this.validateLocator))
      .filter((item): item is ReturnTarget => item !== null);
  }

  /** 记住回到本 locator 的返回目标；返回 token 与是否成功持久化。 */
  rememberReturn(locator: ReadingLocator): RememberResult {
    if (!this.validateLocator(locator)) {
      return { token: "", persisted: false, outcome: storageOutcome(new Error("invalid locator")) };
    }
    const token = createReturnToken(this.randomBytes);
    const target: ReturnTarget = { token, locator, created_at: this.now() };
    const stack = this.loadReturnStack().filter(
      (item) =>
        !(
          item.locator.stream_id === locator.stream_id &&
          item.locator.unit_id === locator.unit_id
        ),
    );
    stack.push(target);
    const bounded = this.bound(stack);
    const result = this.storage.set(RETURN_STACK_KEY, JSON.stringify(bounded));
    return { token, persisted: result.ok, outcome: result };
  }

  /** 解析 return token；缺失/失效/过期/被篡改都返回 null。 */
  resolveReturn(token: string | null | undefined): ReadingLocator | null {
    if (!token || !RETURN_TOKEN_PATTERN.test(token)) return null;
    const target = this.loadReturnStack().find((item) => item.token === token);
    if (!target) return null;
    if (this.ttlMs > 0 && this.now() - target.created_at > this.ttlMs) return null;
    return target.locator;
  }

  forgetReturn(token: string): void {
    const stack = this.loadReturnStack().filter((item) => item.token !== token);
    this.storage.set(RETURN_STACK_KEY, JSON.stringify(stack));
  }

  private bound(stack: ReturnTarget[]): ReturnTarget[] {
    let bounded = stack.slice(-this.maxEntries);
    while (bounded.length > 1 && JSON.stringify(bounded).length > this.maxBytes) {
      bounded = bounded.slice(1);
    }
    if (JSON.stringify(bounded).length > this.maxBytes) return [];
    return bounded;
  }
}
