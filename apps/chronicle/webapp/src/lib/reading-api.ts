// Chronicle 第二轮连续阅读 HTTP client 与 query keys（C2-R2-T09）。
//
// 浏览器只经过 Rust `/api/v1/public/reading-*`（C0 read model 仍是唯一读取
// authority）。所有路径显式携带 catalog/stream/unit/cursor：snapshot 是身份
// 的一部分，换 catalog 不复用旧正文/预览。client 支持 AbortSignal，区分网络
// 错误、非 JSON 响应、typed 错误与迟到响应；绝不按 canonical ID 单独缓存。
//
// 本模块不接 App/router，不访问数据库；T15 统一挂接 SPA `/read`。

import {
  ReadingPreviewCache,
  eventPreviewCacheKey,
  eventTargetsCacheKey,
  readingPreviewCache,
} from "./reading-preview-cache";
import type {
  EventPreview,
  EventTargetPage,
  ReadingLocator,
  ReadingUnit,
  StreamPage,
  TimeGroup,
} from "./reading-types";
import { isReadingLocator } from "./reading-types";

/** Python sidecar cursor direction (distinct from the UI previous/next action). */
export type ReadingPageDirection = "forward" | "backward";

export const READING_API_PREFIX = "/api/v1/public";

export class ReadingApiError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ReadingApiError";
    this.status = status;
    this.code = code;
  }
}

/** 调用方主动 abort 时抛出；不与真实网络失败混为一谈。 */
export class ReadingAbortError extends Error {
  constructor(message = "reading request aborted") {
    super(message);
    this.name = "ReadingAbortError";
  }
}

// ---------------------------------------------------------------------------
// 响应封套（与 reader_streams._envelope 对应；preview/targets 直接返回对象）
// ---------------------------------------------------------------------------

export interface ReadingSnapshot {
  readonly catalog_sha: string;
  readonly publication_sequence: number;
}

export interface ReadingEnvelope<TPage> {
  readonly schema: string;
  readonly version: string;
  readonly snapshot: ReadingSnapshot;
  readonly query: Record<string, unknown>;
  readonly page: TPage;
}

export interface ReadingStreamDirectoryItem {
  readonly stream_id: string;
  readonly revision_id: string;
  readonly document_id: string;
  readonly origin_catalog_sha: string;
  readonly manifest_sha: string;
  readonly unit_count: number;
  readonly group_count: number;
  readonly revision_no: number;
  readonly created_at: string | null;
}

export interface ReadingStreamDirectoryPage {
  readonly streams: readonly ReadingStreamDirectoryItem[];
  readonly limit: number;
  readonly has_more: boolean;
  readonly next_cursor: string | null;
}

export interface ReadingChapterDirectoryEntry {
  readonly chapter_id: string | null;
  readonly chapter_index: number | null;
  readonly publication_id: string | null;
  readonly artifact_sha256: string | null;
  readonly unit_count: number | null;
  readonly title: string | null;
}

export interface ReadingStreamDetailPage {
  readonly stream_id: string;
  readonly document_id: string;
  readonly revision_id: string;
  readonly revision_no: number;
  readonly catalog_sha: string;
  readonly origin_catalog_sha: string;
  readonly manifest_sha: string;
  readonly unit_count: number;
  readonly group_count: number;
  readonly title: string | null;
  readonly full_text_sha256: string | null;
  readonly chapters: readonly ReadingChapterDirectoryEntry[];
  readonly start_locator: ReadingLocator | null;
}

export interface ReadingLocatePage extends StreamPage {
  readonly locator: ReadingLocator;
  readonly target_ordinal: number;
  readonly group_id: string;
  readonly group_ordinal: number;
  readonly group_cursor: string;
}

export interface ReadingGroupPage {
  readonly stream_id: string;
  readonly catalog_sha: string;
  readonly limit: number;
  readonly groups: readonly TimeGroup[];
  readonly prev_cursor: string | null;
  readonly next_cursor: string | null;
  readonly has_previous: boolean;
  readonly has_next: boolean;
}

export type ReadingDirectoryEnvelope = ReadingEnvelope<ReadingStreamDirectoryPage>;
export type ReadingDetailEnvelope = ReadingEnvelope<ReadingStreamDetailPage>;
export type ReadingUnitsEnvelope = ReadingEnvelope<StreamPage>;
export type ReadingGroupsEnvelope = ReadingEnvelope<ReadingGroupPage>;
export type ReadingLocateEnvelope = ReadingEnvelope<ReadingLocatePage>;

// ---------------------------------------------------------------------------
// 输入校验：非法 catalog/stream/unit 在构造 URL 前就失败
// ---------------------------------------------------------------------------

const SHA256 = /^[0-9a-f]{64}$/;
const STREAM_UUID_V7 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const UNIT_ID = /^ru_[0-9a-f]{24}$/;

function requireCatalog(catalog: string | undefined | null): string {
  const value = (catalog ?? "").trim();
  if (!SHA256.test(value)) {
    throw new ReadingApiError(400, "invalid_catalog", "catalog 必须是 sha256 摘要");
  }
  return value;
}

function requireStreamId(streamId: string | undefined | null): string {
  const value = (streamId ?? "").trim();
  if (!STREAM_UUID_V7.test(value)) {
    throw new ReadingApiError(400, "invalid_stream", "stream_id 必须是 UUIDv7");
  }
  return value;
}

function requireUnitId(unitId: string | undefined | null): string {
  const value = (unitId ?? "").trim();
  if (!UNIT_ID.test(value)) {
    throw new ReadingApiError(400, "invalid_unit", "unit_id 必须是阅读 unit id");
  }
  return value;
}

// ---------------------------------------------------------------------------
// 路径构造
// ---------------------------------------------------------------------------

export interface ReadingDirectoryQuery {
  readonly catalog?: string | null;
  readonly limit?: number;
  readonly cursor?: string | null;
}

export interface ReadingCatalogQuery {
  readonly catalog: string;
}

export interface ReadingUnitsQuery extends ReadingCatalogQuery {
  readonly limit?: number;
  readonly cursor?: string | null;
  readonly direction?: ReadingPageDirection;
}

export interface ReadingGroupsQuery extends ReadingCatalogQuery {
  readonly limit?: number;
  readonly cursor?: string | null;
  readonly direction?: ReadingPageDirection;
}

export interface ReadingLocateQuery extends ReadingCatalogQuery {
  readonly unitId: string;
  readonly limit?: number;
}

export interface ReadingEventQuery extends ReadingCatalogQuery {
  readonly limit?: number;
  readonly cursor?: string | null;
}

function setLimit(params: URLSearchParams, limit: number | undefined, fallback: number): void {
  params.set("limit", String(limit ?? fallback));
}

export function readingStreamsPath(query: ReadingDirectoryQuery = {}): string {
  const params = new URLSearchParams();
  if (query.catalog) params.set("catalog", requireCatalog(query.catalog));
  setLimit(params, query.limit, 20);
  if (query.cursor) params.set("cursor", query.cursor);
  return `${READING_API_PREFIX}/reading-streams?${params.toString()}`;
}

export function readingStreamDetailPath(streamId: string, query: ReadingCatalogQuery): string {
  const params = new URLSearchParams();
  params.set("catalog", requireCatalog(query.catalog));
  return `${READING_API_PREFIX}/reading-streams/${encodeURIComponent(
    requireStreamId(streamId),
  )}?${params.toString()}`;
}

export function readingStreamUnitsPath(streamId: string, query: ReadingUnitsQuery): string {
  const params = new URLSearchParams();
  params.set("catalog", requireCatalog(query.catalog));
  setLimit(params, query.limit, 20);
  if (query.cursor) params.set("cursor", query.cursor);
  if (query.direction) params.set("direction", query.direction);
  return `${READING_API_PREFIX}/reading-streams/${encodeURIComponent(
    requireStreamId(streamId),
  )}/units?${params.toString()}`;
}

export function readingStreamGroupsPath(streamId: string, query: ReadingGroupsQuery): string {
  const params = new URLSearchParams();
  params.set("catalog", requireCatalog(query.catalog));
  setLimit(params, query.limit, 50);
  if (query.cursor) params.set("cursor", query.cursor);
  if (query.direction) params.set("direction", query.direction);
  return `${READING_API_PREFIX}/reading-streams/${encodeURIComponent(
    requireStreamId(streamId),
  )}/groups?${params.toString()}`;
}

export function readingStreamLocatePath(streamId: string, query: ReadingLocateQuery): string {
  const params = new URLSearchParams();
  params.set("catalog", requireCatalog(query.catalog));
  params.set("unit_id", requireUnitId(query.unitId));
  setLimit(params, query.limit, 20);
  return `${READING_API_PREFIX}/reading-streams/${encodeURIComponent(
    requireStreamId(streamId),
  )}/locate?${params.toString()}`;
}

function requireCanonicalEventId(eventId: string | undefined | null): string {
  const value = (eventId ?? "").trim();
  if (!/^[0-9a-fA-F-]{8,}$/.test(value)) {
    throw new ReadingApiError(400, "invalid_event", "event_id 不是合法 UUID");
  }
  return value;
}

export function readingEventPreviewPath(eventId: string, query: ReadingCatalogQuery): string {
  const params = new URLSearchParams();
  params.set("catalog", requireCatalog(query.catalog));
  return `${READING_API_PREFIX}/reading-events/${encodeURIComponent(
    requireCanonicalEventId(eventId),
  )}/preview?${params.toString()}`;
}

export function readingEventTargetsPath(eventId: string, query: ReadingEventQuery): string {
  const params = new URLSearchParams();
  params.set("catalog", requireCatalog(query.catalog));
  setLimit(params, query.limit, 20);
  if (query.cursor) params.set("cursor", query.cursor);
  return `${READING_API_PREFIX}/reading-events/${encodeURIComponent(
    requireCanonicalEventId(eventId),
  )}/targets?${params.toString()}`;
}

// ---------------------------------------------------------------------------
// query keys：catalog 始终进入 key，不能用 canonical ID 冒充快照身份
// ---------------------------------------------------------------------------

export const readingKeys = {
  directory: (query: ReadingDirectoryQuery = {}) =>
    [
      "chronicle",
      "reading",
      "directory",
      query.catalog ?? null,
      query.limit ?? 20,
      query.cursor ?? null,
    ] as const,
  stream: (streamId: string, catalog: string) =>
    ["chronicle", "reading", "stream", requireStreamId(streamId), requireCatalog(catalog)] as const,
  units: (streamId: string, query: ReadingUnitsQuery) =>
    [
      "chronicle",
      "reading",
      "units",
      requireStreamId(streamId),
      requireCatalog(query.catalog),
      query.direction ?? null,
      query.limit ?? 20,
      query.cursor ?? null,
    ] as const,
  groups: (streamId: string, query: ReadingGroupsQuery) =>
    [
      "chronicle",
      "reading",
      "groups",
      requireStreamId(streamId),
      requireCatalog(query.catalog),
      query.direction ?? null,
      query.limit ?? 50,
      query.cursor ?? null,
    ] as const,
  locate: (streamId: string, query: ReadingLocateQuery) =>
    [
      "chronicle",
      "reading",
      "locate",
      requireStreamId(streamId),
      requireCatalog(query.catalog),
      requireUnitId(query.unitId),
    ] as const,
  preview: (eventId: string, catalog: string) =>
    [
      "chronicle",
      "reading",
      "event-preview",
      requireCatalog(catalog),
      requireCanonicalEventId(eventId),
    ] as const,
  targets: (eventId: string, query: ReadingEventQuery) =>
    [
      "chronicle",
      "reading",
      "event-targets",
      requireCatalog(query.catalog),
      requireCanonicalEventId(eventId),
      query.limit ?? 20,
      query.cursor ?? null,
    ] as const,
};

// ---------------------------------------------------------------------------
// fetch：错误/非 JSON/abort 都走显式分支，不静默回退
// ---------------------------------------------------------------------------

async function readErrorPayload(response: Response): Promise<{ code?: string; message?: string }> {
  try {
    const payload = (await response.json()) as { error?: { code?: string; message?: string } };
    return { code: payload?.error?.code, message: payload?.error?.message };
  } catch {
    return {};
  }
}

export async function fetchReadingJSON<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      ...init,
    });
  } catch (error) {
    if (init?.signal?.aborted) throw new ReadingAbortError();
    throw new ReadingApiError(0, "network_error", `无法连接阅读服务：${path}`);
  }
  if (init?.signal?.aborted) throw new ReadingAbortError();
  if (!response.ok) {
    const payload = await readErrorPayload(response);
    throw new ReadingApiError(
      response.status,
      payload.code ?? (response.status === 404 ? "not_found" : "request_failed"),
      payload.message ?? `阅读服务返回 HTTP ${response.status}`,
    );
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ReadingApiError(response.status, "invalid_response", "阅读服务返回了无法解析的响应");
  }
}

export function fetchReadingStreams(
  query: ReadingDirectoryQuery = {},
  init?: RequestInit,
): Promise<ReadingDirectoryEnvelope> {
  return fetchReadingJSON<ReadingDirectoryEnvelope>(readingStreamsPath(query), init);
}

export function fetchReadingStreamDetail(
  streamId: string,
  query: ReadingCatalogQuery,
  init?: RequestInit,
): Promise<ReadingDetailEnvelope> {
  return fetchReadingJSON<ReadingDetailEnvelope>(readingStreamDetailPath(streamId, query), init);
}

export function fetchReadingStreamUnits(
  streamId: string,
  query: ReadingUnitsQuery,
  init?: RequestInit,
): Promise<ReadingUnitsEnvelope> {
  return fetchReadingJSON<ReadingUnitsEnvelope>(readingStreamUnitsPath(streamId, query), init);
}

export function fetchReadingStreamGroups(
  streamId: string,
  query: ReadingGroupsQuery,
  init?: RequestInit,
): Promise<ReadingGroupsEnvelope> {
  return fetchReadingJSON<ReadingGroupsEnvelope>(readingStreamGroupsPath(streamId, query), init);
}

export function fetchReadingStreamLocate(
  streamId: string,
  query: ReadingLocateQuery,
  init?: RequestInit,
): Promise<ReadingLocateEnvelope> {
  return fetchReadingJSON<ReadingLocateEnvelope>(readingStreamLocatePath(streamId, query), init);
}

export function fetchReadingEventPreview(
  eventId: string,
  query: ReadingCatalogQuery,
  init?: RequestInit,
): Promise<EventPreview> {
  return fetchReadingJSON<EventPreview>(readingEventPreviewPath(eventId, query), init);
}

export function fetchReadingEventTargets(
  eventId: string,
  query: ReadingEventQuery,
  init?: RequestInit,
): Promise<EventTargetPage> {
  return fetchReadingJSON<EventTargetPage>(readingEventTargetsPath(eventId, query), init);
}

// ---------------------------------------------------------------------------
// 有界预览缓存 + 迟到响应守卫
// ---------------------------------------------------------------------------

/**
 * 按 catalog + event 缓存的 preview/targets 加载器：同一个 event 在不同
 * snapshot 下各自一条记录，换 snapshot 不会复用旧正文/预览。底层缓存合并
 * 并发同请求并做 LRU 淘汰（reading-preview-cache.ts）。
 */
export function loadReadingEventPreview(
  eventId: string,
  catalog: string,
  init?: RequestInit,
  cache: ReadingPreviewCache = readingPreviewCache,
): Promise<EventPreview> {
  const key = eventPreviewCacheKey(requireCatalog(catalog), requireCanonicalEventId(eventId));
  return cache.load<EventPreview>(key, () => fetchReadingEventPreview(eventId, { catalog }, init));
}

export function loadReadingEventTargets(
  eventId: string,
  query: ReadingEventQuery,
  init?: RequestInit,
  cache: ReadingPreviewCache = readingPreviewCache,
): Promise<EventTargetPage> {
  const key = eventTargetsCacheKey(requireCatalog(query.catalog), requireCanonicalEventId(eventId));
  return cache.load<EventTargetPage>(key, () => fetchReadingEventTargets(eventId, query, init));
}

export interface ReadingStaleGuard {
  next(): number;
  isCurrent(token: number): boolean;
}

/**
 * 迟到响应守卫：快速切换 unit/事件/来源时，只有最新一次请求的响应允许写入
 * 当前视图。旧 Promise 的 resolve/reject 均被丢弃。
 */
export function createReadingStaleGuard(): ReadingStaleGuard {
  let latest = 0;
  return {
    next(): number {
      latest += 1;
      return latest;
    },
    isCurrent(token: number): boolean {
      return token === latest;
    },
  };
}

/** 合并 unit 页：按 unit_id 去重，保持服务端顺序。纯函数。 */
export function mergeReadingUnits(
  existing: readonly ReadingUnit[],
  page: StreamPage,
): ReadingUnit[] {
  const seen = new Set((existing ?? []).map((unit) => unit.unit_id));
  const merged = [...(existing ?? [])];
  for (const unit of page?.units ?? []) {
    if (!unit || seen.has(unit.unit_id)) continue;
    seen.add(unit.unit_id);
    merged.push(unit);
  }
  return merged;
}

/** active unit 已取得的 locator；缺 unit 时返回 null，不猜首段。 */
export function unitLocator(
  streamId: string,
  catalog: string,
  unitId: string,
): ReadingLocator | null {
  const locator = {
    stream_id: requireStreamId(streamId),
    catalog_sha: requireCatalog(catalog),
    unit_id: requireUnitId(unitId),
  };
  return isReadingLocator(locator) ? locator : null;
}
