// Chronicle 第二轮连续阅读共享 DTO 与组件回调类型（C2-R2-T01）。
//
// 与 `apps/chronicle/ingestion/schemas/chronicle-reading-v0.1.schema.json`
// 及 `apps/chronicle/persistence/reading_contract.py` 的公开 DTO 一一对应。
// 这些类型只描述服务端已编译的结果：canonical ID、hash、坐标、cursor 与
// 分组 key 都由程序计算，浏览器不重新切词或按 UTF-16 偏移猜测事件位置。
//
// 本模块不接 App/router；T10-T15 直接消费这些类型。

export const READING_DTO_SCHEMA_ID =
  "https://loom.local/chronicle/schemas/chronicle-reading-v0.1.schema.json";

/** Engineering envelope mirrored from reading_contract.ReadingLimits. */
export const READING_LIMITS = {
  maxBlockCodePoints: 8192,
  maxEventSpans: 64,
  maxContextEntities: 128,
  minSourceSelections: 1,
  maxSourceSelections: 16,
  pageMinLimit: 1,
  pageMaxLimit: 50,
  groupMaxLimit: 100,
  pageMaxBytes: 2 * 1024 * 1024,
  unitMaxBytes: 256 * 1024,
  previewMaxBytes: 64 * 1024,
  previewMaxSources: 8,
  previewExcerptCodePoints: 160,
  jsonMaxBytes: 8 * 1024 * 1024,
} as const;

export type NarrativeMode = "events" | "inherit" | "mixed" | "unknown";
export type NarrativeStatus = "resolved" | "mixed" | "unknown";
export type SpanStatus = "resolved" | "ambiguous" | "unresolved";
export type SpanRelation =
  | "current"
  | "retrospective"
  | "foreshadow"
  | "background"
  | "uncertain";
export type ContextImportance = "primary" | "other";
export type TimePrecision =
  | "day"
  | "month"
  | "year"
  | "range"
  | "mixed"
  | "unknown"
  | "approximate";

/** Stable reading locator: {stream_id, catalog_sha, unit_id}. */
export interface ReadingLocator {
  readonly stream_id: string;
  readonly catalog_sha: string;
  readonly unit_id: string;
}

export interface TimeObservation {
  readonly event_ref: string | null;
  readonly original_text: string;
  readonly source_calendar: {
    readonly system?: "chinese_lunisolar_regnal" | "proleptic_gregorian" | "unknown";
    readonly era?: string | null;
    readonly era_year?: number | null;
    readonly season?: string | null;
    readonly month?: number | null;
    readonly day?: number | string | null;
  } | null;
  readonly normalized: {
    readonly calendar?: "proleptic_gregorian";
    readonly year?: number | null;
    readonly month?: number | null;
    readonly day?: number | null;
    readonly precision?: "day" | "month" | "year" | "range" | "unknown";
    readonly conversion_status?: "exact" | "year_only" | "partial" | "unresolved";
    readonly approximate?: boolean;
  } | null;
  readonly precision: TimePrecision;
}

export interface NarrativeTime {
  readonly mode: NarrativeMode;
  readonly status: NarrativeStatus;
  readonly event_refs: readonly string[];
  readonly from_block_id: string | null;
  readonly observations: readonly TimeObservation[];
  readonly year_key: string;
  readonly period_key: string;
  readonly year_label: string | null;
  readonly period_label: string;
  readonly precision: TimePrecision;
  readonly continues_previous: boolean;
}

export interface EventSpanView {
  readonly span_id: string;
  readonly text: string;
  readonly start: number;
  readonly end: number;
  readonly status: SpanStatus;
  readonly relation: SpanRelation;
  readonly target_ref: string | null;
  readonly target_event_id: string | null;
  readonly candidate_refs: readonly string[];
}

export interface ContextEntityRole {
  readonly event_ref: string;
  readonly role: string;
  readonly participant_index: number;
}

export interface ContextEntityView {
  readonly entity_ref: string;
  readonly name: string | null;
  readonly canonical_id: string | null;
  readonly kind:
    | "person"
    | "place"
    | "polity"
    | "organization"
    | "army"
    | "office"
    | "group"
    | "other";
  readonly importance: ContextImportance;
  readonly source_anchor_ids: readonly string[];
  readonly event_roles: readonly ContextEntityRole[];
}

export interface ReadingTextSegment {
  readonly kind: "text";
  readonly text: string;
}

export interface ReadingEventSegment {
  readonly kind: "event";
  readonly text: string;
  readonly span: EventSpanView;
}

export type ReadingSegment = ReadingTextSegment | ReadingEventSegment;

export interface ReadingUnit {
  readonly unit_id: string;
  readonly ordinal: number;
  readonly stream_id: string;
  readonly catalog_sha: string;
  readonly publication_id: string;
  readonly chapter_id: string;
  readonly block_id: string;
  readonly artifact_sha256: string;
  readonly text_hash: string;
  readonly source_anchor_ids: readonly string[];
  readonly segments: readonly ReadingSegment[];
  readonly narrative_time: NarrativeTime;
  readonly context_entities: readonly ContextEntityView[];
  readonly group_id: string;
  readonly continues_previous: boolean;
}

export interface StreamPage {
  readonly stream_id: string;
  readonly catalog_sha: string;
  readonly limit: number;
  readonly units: readonly ReadingUnit[];
  readonly prev_cursor: string | null;
  readonly next_cursor: string | null;
  readonly has_previous: boolean;
  readonly has_next: boolean;
  readonly group_continuation: {
    readonly group_id: string;
    readonly continues_previous: boolean;
  } | null;
}

export interface TimeGroup {
  readonly group_id: string;
  readonly ordinal: number;
  readonly year_key: string;
  readonly period_key: string;
  readonly year_label: string | null;
  readonly period_label: string;
  readonly precision: TimePrecision;
  readonly observations: readonly TimeObservation[];
  readonly continues_previous: boolean;
  readonly first_locator: ReadingLocator;
  readonly last_locator: ReadingLocator;
  readonly unit_count: number;
}

export interface EventPreviewSource {
  readonly source_title: string;
  readonly publication_id: string | null;
  readonly observations: readonly TimeObservation[];
  readonly excerpt: string | null;
  readonly excerpt_more: boolean;
  readonly original_entry: {
    readonly publication_id: string;
    readonly anchor_id: string;
  } | null;
}

export interface EventPreview {
  readonly event_id: string;
  readonly catalog_sha: string;
  readonly name: string;
  readonly sources: readonly EventPreviewSource[];
  readonly source_count: number;
  readonly has_more_sources: boolean;
}

export interface EventTarget {
  readonly event_id: string;
  readonly catalog_sha: string;
  readonly relation: "current" | "mention";
  readonly stream_id: string;
  readonly publication_id: string;
  readonly chapter_id: string;
  readonly chapter_title: string | null;
  readonly source_title: string | null;
  readonly unit_id: string;
  readonly span_id: string;
  readonly locator: ReadingLocator;
  readonly excerpt: string;
}

export interface EventTargetPage {
  readonly event_id: string;
  readonly catalog_sha: string;
  readonly targets: readonly EventTarget[];
  readonly current_count: number;
  readonly mention_count: number;
  readonly next_cursor: string | null;
  readonly has_more: boolean;
}

// ---------------------------------------------------------------------------
// Fixed error codes and component callback seams (reading-experience.md §3-4)
// ---------------------------------------------------------------------------

export type ReadingErrorCode =
  | "bad_request"
  | "not_found"
  | "source_missing"
  | "source_mismatch";

export const READING_ERROR_STATUS: Readonly<Record<ReadingErrorCode, number>> = {
  bad_request: 400,
  not_found: 404,
  source_missing: 409,
  source_mismatch: 409,
};

export type ReadingDirection = "previous" | "next";

/** Content-window component -> controller typed callbacks (no shared scroll state). */
export interface ReadingWindowCallbacks {
  readonly requestPage: (direction: ReadingDirection) => void;
  readonly onLoadError: (unitId: string, message: string) => void;
  readonly onRetry: (unitId: string) => void;
}

/** Explicit navigation actions; the controller owns active unit and URL writes. */
export type ReadingNavigationAction =
  | { readonly kind: "axis"; readonly locator: ReadingLocator }
  | { readonly kind: "event"; readonly locator: ReadingLocator; readonly event_id: string }
  | { readonly kind: "source"; readonly locator: ReadingLocator }
  | { readonly kind: "locate"; readonly locator: ReadingLocator }
  | { readonly kind: "back"; readonly locator: ReadingLocator }
  | { readonly kind: "forward"; readonly locator: ReadingLocator };

/** Controller callbacks shared by the axis, context and event-preview components. */
export interface ReadingControllerCallbacks {
  readonly onActiveUnitChange: (unit: ReadingUnit) => void;
  readonly onNavigate: (action: ReadingNavigationAction) => void;
  readonly onRestore: (locator: ReadingLocator) => void;
}

const LOCATOR_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const UNIT_ID = /^ru_[0-9a-f]{24}$/;

/** Validate the untrusted locator fields before building any URL. */
export function isReadingLocator(value: unknown): value is ReadingLocator {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.stream_id === "string" &&
    LOCATOR_UUID.test(candidate.stream_id) &&
    typeof candidate.catalog_sha === "string" &&
    SHA256.test(candidate.catalog_sha) &&
    typeof candidate.unit_id === "string" &&
    UNIT_ID.test(candidate.unit_id)
  );
}

export function isEventSegment(segment: ReadingSegment): segment is ReadingEventSegment {
  return segment.kind === "event";
}

/** Concatenating segment text must reproduce the translation block verbatim. */
export function readingUnitText(unit: ReadingUnit): string {
  return unit.segments.map((segment) => segment.text).join("");
}
