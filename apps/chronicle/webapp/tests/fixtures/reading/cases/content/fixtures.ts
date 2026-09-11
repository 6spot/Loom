// C2-R2-T10 content suite 的合成 fixture（仅测试使用，不进生产构建）。
//
// 只构造 published DTO 形状（T01 reading-types）与受控的相邻/跨章/大页/远页，
// 不是真实模型输出，也不是真实后端响应。文案为合成占位，不冒充史料译文。

import type {
  NarrativeTime,
  ReadingSegment,
  ReadingUnit,
  StreamPage,
} from "../../../../../src/lib/reading-types";

export const STREAM_ID = "00000000-0000-7000-8000-0000000000aa";
export const CATALOG_SHA = "a".repeat(64);
export const PUBLICATION_A = "00000000-0000-7000-8000-00000000000a";
export const PUBLICATION_B = "11111111-1111-7000-8000-111111111111";
export const CHAPTER_A = "chap-a";
export const CHAPTER_B = "chap-b";
export const CHAPTER_TITLES: Readonly<Record<string, string | null>> = {
  [CHAPTER_A]: "卷一 · 吴书",
  [CHAPTER_B]: "卷二 · 魏书",
};

const ARTIFACT_SHA = "c".repeat(64);

function hexId(value: number): string {
  return `ru_${value.toString(16).padStart(24, "0").slice(-24)}`;
}

function unknownTime(): NarrativeTime {
  return {
    mode: "unknown",
    status: "unknown",
    event_refs: [],
    from_block_id: null,
    observations: [],
    year_key: "unknown",
    period_key: "unknown",
    year_label: "时间未明确",
    period_label: "时间未明确",
    precision: "unknown",
    continues_previous: false,
  };
}

export interface UnitOptions {
  readonly chapterId?: string;
  readonly publicationId?: string;
  readonly segments?: readonly ReadingSegment[];
  readonly anchors?: readonly string[];
}

export function makeUnit(ordinal: number, text: string, options: UnitOptions = {}): ReadingUnit {
  const chapterId = options.chapterId ?? (ordinal < 5 ? CHAPTER_A : CHAPTER_B);
  const publicationId = options.publicationId ?? PUBLICATION_A;
  return {
    unit_id: hexId(ordinal),
    ordinal,
    stream_id: STREAM_ID,
    catalog_sha: CATALOG_SHA,
    publication_id: publicationId,
    chapter_id: chapterId,
    block_id: `blk_${String(ordinal).padStart(4, "0")}`,
    artifact_sha256: ARTIFACT_SHA,
    text_hash: ARTIFACT_SHA,
    source_anchor_ids: options.anchors ?? [`anc_${String(ordinal).padStart(4, "0")}`],
    segments: options.segments ?? [{ kind: "text", text }],
    narrative_time: unknownTime(),
    context_entities: [],
    group_id: `rg_${chapterId}`,
    continues_previous: ordinal > 0,
  };
}

function plainUnit(ordinal: number): ReadingUnit {
  return makeUnit(ordinal, `第 ${ordinal + 1} 段合成正文，用于验证连续顺序与窗口回收。`);
}

/** 初始可见页：跨越 chap-a → chap-b，并含 resolved/uncertain 两种事件词。 */
export function initialUnits(): ReadingUnit[] {
  const eventResolved = makeUnit(4, "遇于赤壁，大破曹公军。", {
    segments: [
      { kind: "text", text: "遇于" },
      {
        kind: "event",
        text: "赤壁",
        span: {
          span_id: "span_0004",
          text: "赤壁",
          start: 2,
          end: 4,
          status: "resolved",
          relation: "current",
          target_ref: "evt_red_cliffs",
          target_event_id: "evt_red_cliffs",
          candidate_refs: [],
        },
      },
      { kind: "text", text: "，大破曹公军。" },
    ],
  });
  const eventUncertain = makeUnit(6, "習鑿齒論曰曹操暫自驕伐而天下三分。", {
    segments: [
      { kind: "text", text: "習鑿齒論曰" },
      {
        kind: "event",
        text: "曹操",
        span: {
          span_id: "span_0006",
          text: "曹操",
          start: 6,
          end: 8,
          status: "ambiguous",
          relation: "background",
          target_ref: null,
          target_event_id: null,
          candidate_refs: ["ent_cao_1", "ent_cao_2"],
        },
      },
      { kind: "text", text: "暫自驕伐而天下三分。" },
    ],
  });
  return [plainUnit(3), eventResolved, plainUnit(5), eventUncertain];
}

export function previousUnits(): ReadingUnit[] {
  return [plainUnit(0), plainUnit(1), plainUnit(2)];
}

export function nextUnits(): ReadingUnit[] {
  return [plainUnit(7), plainUnit(8)];
}

/** 大页：ordinal 9..208（200 段），用于验证 mounted ≤120 与显式加载。 */
export function bulkUnits(): ReadingUnit[] {
  return Array.from({ length: 200 }, (_, index) => plainUnit(9 + index));
}

/** 远页：ordinal 5000..5049，模拟 locate 直达而不下载前面所有页。 */
export function farUnits(): ReadingUnit[] {
  return Array.from({ length: 50 }, (_, index) => plainUnit(5000 + index));
}

export interface PageOptions {
  readonly hasPrevious?: boolean;
  readonly hasNext?: boolean;
  readonly prevCursor?: string | null;
  readonly nextCursor?: string | null;
}

export function pageOf(units: readonly ReadingUnit[], options: PageOptions = {}): StreamPage {
  return {
    stream_id: STREAM_ID,
    catalog_sha: CATALOG_SHA,
    limit: units.length,
    units,
    prev_cursor: options.prevCursor ?? (options.hasPrevious ? "cursor-prev" : null),
    next_cursor: options.nextCursor ?? (options.hasNext ? "cursor-next" : null),
    has_previous: options.hasPrevious ?? false,
    has_next: options.hasNext ?? false,
    group_continuation: null,
  };
}

export const INITIAL_PAGE = pageOf(initialUnits(), {
  hasPrevious: true,
  hasNext: true,
  prevCursor: "cursor-prev",
  nextCursor: "cursor-next",
});

export const PREVIOUS_PAGE = pageOf(previousUnits(), { hasNext: true, nextCursor: "cursor-initial" });
export const NEXT_PAGE = pageOf(nextUnits(), { hasPrevious: true, hasNext: true });
export const BULK_PAGE = pageOf(bulkUnits(), { hasPrevious: true });
export const FAR_PAGE = pageOf(farUnits(), { hasPrevious: true, hasNext: true });
