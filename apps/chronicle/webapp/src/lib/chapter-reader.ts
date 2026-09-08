// Chapter reader专属 client/query keys 与 DTO 类型（C2-R1-T15）。
//
// 只绑定公开阅读版本：所有请求都以 publication_id 为版本锚，原文请求再以
// 服务端下发的 anchor_id + view + cursor 为键。绝不回退到 Document 最新版本，
// 也不在前端拼凑 canonical 引用：entity/event refs 只有在服务端给出明确
// canonical 目标时才成为链接，否则只作原文范围内的普通文本展示。
//
// 本模块不接 App/router，不导入全局 CSS；T17 统一挂接路由。

export type ChapterSourceView = "window" | "chapter";

export interface ChapterDirectoryQuery {
  limit?: number;
  cursor?: string | null;
}

export interface ChapterDirectoryItem {
  publication_id: string;
  document_id?: string | null;
  revision_id?: string | null;
  revision_no?: number | null;
  chapter_id?: string | null;
  chapter_index?: number | null;
  chapter_title?: string | null;
  source_title?: string | null;
}

export interface ChapterDirectoryResponse {
  items: ChapterDirectoryItem[];
  next_cursor: string | null;
  has_more?: boolean;
}

export interface ChapterRef {
  kind: "entity" | "event";
  ref: string;
}

export interface ChapterEntityReference {
  ref: string;
  name?: string | null;
  canonical_id?: string | null;
}

export interface ChapterEventReference {
  ref: string;
  title?: string | null;
  canonical_id?: string | null;
}

export interface ChapterTranslationBlock {
  block_id: string;
  text: string;
  source_block_ids?: string[];
  /** 服务端下发的原文锚点（artifact anchors）， viewing 本段原文的唯一依据。缺失时不猜。 */
  source_anchor_ids?: string[];
  entity_refs?: ChapterRef[];
  event_refs?: ChapterRef[];
}

export interface ChapterDetailResponse {
  publication_id: string;
  chapter_id?: string | null;
  revision_id?: string | null;
  source_title?: string | null;
  chapter_title?: string | null;
  translation_blocks: ChapterTranslationBlock[];
  source_overview?: {
    source_title?: string | null;
    chapter_title?: string | null;
    revision_id?: string | null;
    block_count?: number | null;
    anchor_count?: number | null;
  } | null;
  references?: {
    entities?: ChapterEntityReference[] | null;
    events?: ChapterEventReference[] | null;
  } | null;
  note?: string | null;
}

export interface ChapterSourceSegment {
  text: string;
  highlight?: boolean;
}

export interface ChapterSourceResponse {
  anchor_id: string;
  view: ChapterSourceView;
  source_sha256?: string | null;
  chapter_range?: [number, number] | null;
  page_range?: [number, number] | null;
  segments: ChapterSourceSegment[];
  next_cursor: string | null;
  has_more: boolean;
}

export class ChapterReaderApiError extends Error {
  readonly code: string;
  readonly status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ChapterReaderApiError";
    this.status = status;
    this.code = code;
  }
}

function requirePublicationId(publicationId: string | undefined | null): string {
  const value = (publicationId ?? "").trim();
  if (!value) {
    throw new ChapterReaderApiError(400, "missing_publication", "必须指定 publication_id，不能回退到 Document 最新版本");
  }
  return value;
}

export function chapterDirectoryPath(query: ChapterDirectoryQuery = {}): string {
  const params = new URLSearchParams();
  const limit = query.limit ?? 50;
  params.set("limit", String(limit));
  if (query.cursor) params.set("cursor", query.cursor);
  return `/api/v1/public/chapters?${params.toString()}`;
}

export function chapterDetailPath(publicationId: string): string {
  return `/api/v1/public/chapters/${encodeURIComponent(requirePublicationId(publicationId))}`;
}

export interface ChapterSourceQuery {
  view?: ChapterSourceView;
  cursor?: string | null;
}

export function chapterSourcePath(
  publicationId: string,
  anchorId: string,
  query: ChapterSourceQuery = {},
): string {
  const anchor = (anchorId ?? "").trim();
  if (!anchor) {
    throw new ChapterReaderApiError(400, "missing_anchor", "必须使用服务端下发的 anchor_id，不能由前端拼凑引用");
  }
  const params = new URLSearchParams();
  params.set("view", query.view ?? "window");
  if (query.cursor) params.set("cursor", query.cursor);
  return `/api/v1/public/chapters/${encodeURIComponent(requirePublicationId(publicationId))}/sources/${encodeURIComponent(anchor)}?${params.toString()}`;
}

/** 专属 query keys：目录 / 完整章 / 原文分别绑定 publication_id / anchor / view / cursor。 */
export const chapterReaderKeys = {
  directory: (query: ChapterDirectoryQuery = {}) =>
    ["chapter-reader", "directory", query.limit ?? 50, query.cursor ?? null] as const,
  chapter: (publicationId: string) =>
    ["chapter-reader", "chapter", requirePublicationId(publicationId)] as const,
  source: (publicationId: string, anchorId: string, query: ChapterSourceQuery = {}) =>
    [
      "chapter-reader",
      "source",
      requirePublicationId(publicationId),
      (anchorId ?? "").trim(),
      query.view ?? "window",
      query.cursor ?? null,
    ] as const,
};

async function readErrorPayload(response: Response): Promise<{ code?: string; message?: string }> {
  try {
    const payload = (await response.json()) as { error?: { code?: string; message?: string } };
    return { code: payload?.error?.code, message: payload?.error?.message };
  } catch {
    return {};
  }
}

export async function fetchChapterReaderJSON<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      ...init,
    });
  } catch {
    throw new ChapterReaderApiError(0, "network_error", `无法连接阅读服务：${path}`);
  }
  if (!response.ok) {
    const error = await readErrorPayload(response);
    throw new ChapterReaderApiError(
      response.status,
      error.code ?? (response.status === 404 ? "not_found" : "request_failed"),
      error.message ?? `阅读服务返回 HTTP ${response.status}`,
    );
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ChapterReaderApiError(response.status, "invalid_response", "阅读服务返回了无法解析的响应");
  }
}

export function fetchChapterDirectory(
  query: ChapterDirectoryQuery = {},
  init?: RequestInit,
): Promise<ChapterDirectoryResponse> {
  return fetchChapterReaderJSON<ChapterDirectoryResponse>(chapterDirectoryPath(query), init);
}

export function fetchChapterDetail(
  publicationId: string,
  init?: RequestInit,
): Promise<ChapterDetailResponse> {
  return fetchChapterReaderJSON<ChapterDetailResponse>(chapterDetailPath(publicationId), init);
}

export function fetchChapterSource(
  publicationId: string,
  anchorId: string,
  query: ChapterSourceQuery = {},
  init?: RequestInit,
): Promise<ChapterSourceResponse> {
  return fetchChapterReaderJSON<ChapterSourceResponse>(
    chapterSourcePath(publicationId, anchorId, query),
    init,
  );
}

/**
 * 迟到响应守卫：快速切换两个 publication（或 anchor/view/cursor）时，
 * 只有最新一次请求的响应允许写入当前视图，旧响应直接丢弃。
 */
export interface StaleGuard {
  next(): number;
  isCurrent(token: number): boolean;
}

export function createStaleGuard(): StaleGuard {
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

export type ChapterStatusKind = "empty" | "loading" | "not_found" | "error" | "ready";

export function classifyChapterError(error: unknown): { kind: ChapterStatusKind; code: string; message: string } {
  if (error instanceof ChapterReaderApiError) {
    if (error.status === 404 || error.code === "not_found") {
      return { kind: "not_found", code: error.code, message: error.message };
    }
    return { kind: "error", code: error.code, message: error.message };
  }
  return { kind: "error", code: "unknown_error", message: "阅读服务暂时不可用，请稍后重试" };
}

/** 合并目录分页：按 publication_id 去重追加，保证快速翻页不丢不重。纯函数。 */
export function mergeDirectoryPages(
  existing: ChapterDirectoryItem[],
  page: ChapterDirectoryResponse,
): ChapterDirectoryItem[] {
  const seen = new Set((existing ?? []).map((item) => item.publication_id));
  const merged = [...(existing ?? [])];
  for (const item of page?.items ?? []) {
    if (!item || seen.has(item.publication_id)) continue;
    seen.add(item.publication_id);
    merged.push(item);
  }
  return merged;
}

/** 服务端未给 canonical 目标的引用：只展示名称/引用，不生成详情链接。 */
export function canonicalTargetForRef(
  ref: ChapterRef,
  references?: ChapterDetailResponse["references"],
): string | null {
  const pool = ref.kind === "entity" ? (references?.entities ?? []) : (references?.events ?? []);
  const match = (pool ?? []).find((entry) => entry?.ref === ref.ref);
  const canonicalId = (match?.canonical_id ?? "").trim();
  if (!canonicalId) return null;
  return ref.kind === "entity"
    ? `/entities/${encodeURIComponent(canonicalId)}`
    : `/events/${encodeURIComponent(canonicalId)}`;
}

export function refDisplayName(
  ref: ChapterRef,
  references?: ChapterDetailResponse["references"],
): string {
  const pool = ref.kind === "entity" ? (references?.entities ?? []) : (references?.events ?? []);
  const match = (pool ?? []).find((entry) => entry?.ref === ref.ref);
  if (ref.kind === "entity") {
    const name = (match as ChapterEntityReference | undefined)?.name;
    return (name ?? "").trim() || ref.ref;
  }
  const title = (match as ChapterEventReference | undefined)?.title;
  return (title ?? "").trim() || ref.ref;
}

/** 本段可请求的原文锚点：只取服务端下发的 source_anchor_ids，绝不猜测。 */
export function anchorsForBlock(block: ChapterTranslationBlock): string[] {
  const anchors = Array.isArray(block.source_anchor_ids) ? block.source_anchor_ids : [];
  return anchors.map((anchor) => (anchor ?? "").trim()).filter((anchor) => anchor.length > 0);
}
