// C2-R2-T13 events suite fixture 数据（仅测试使用，不进生产构建）。
//
// 全部为 synthetic published-DTO 形状样例，不是真实模型输出、不是真实后端响应，
// 也不是史料断言：文案借用第一轮冻结正文的短定位片段只为说明阅读行为。

import type {
  EventPreview,
  EventPreviewSource,
  EventTarget,
  EventTargetPage,
  ReadingEventSegment,
  ReadingLocator,
  TimeObservation,
} from "../../../../../src/lib/reading-types";

export { READING_FIXTURE_SAMPLE_NOTE } from "../types";

export const EVENTS_STREAM = "0192f0a0-0000-7000-8000-00000000aa01";
export const EVENTS_CATALOG = "4c29947197b9be1907082482c45d724a4dd4216a9db18f9f6ba55b9085597401";

export const EVENT_RED_CLIFFS = "evt_000000000000000000000001";
export const EVENT_REPEAT_SECOND = "evt_000000000000000000000003";
export const EVENT_LATE_A = "evt_0000000000000000000000a1";
export const EVENT_LATE_B = "evt_0000000000000000000000b2";

export function unitId(ordinal: number): string {
  return `ru_${ordinal.toString(16).padStart(24, "0")}`;
}

export function unitLocator(ordinal: number): ReadingLocator {
  return { stream_id: EVENTS_STREAM, catalog_sha: EVENTS_CATALOG, unit_id: unitId(ordinal) };
}

/** 当前阅读 locator；「查看事件」返回这里。 */
export const CURRENT_READING_LOCATOR = unitLocator(1);

export function eventSpan(
  spanId: string,
  text: string,
  eventId: string | null,
  overrides: Partial<ReadingEventSegment["span"]> = {},
): ReadingEventSegment {
  return {
    kind: "event",
    text,
    span: {
      span_id: spanId,
      text,
      start: 0,
      end: text.length,
      status: "resolved",
      relation: "current",
      target_ref: eventId ? "local_ref" : null,
      target_event_id: eventId,
      candidate_refs: [],
      ...overrides,
    },
  };
}

function sourceObservation(original: string, eraYear: number | null, month: number | null): TimeObservation {
  return {
    event_ref: null,
    original_text: original,
    source_calendar: {
      system: "chinese_lunisolar_regnal",
      era: "建安",
      era_year: eraYear,
      season: null,
      month,
      day: null,
    },
    normalized: null,
    precision: month === null ? "year" : "month",
  };
}

function source(
  title: string,
  observations: TimeObservation[],
  excerpt: string | null,
  excerptMore: boolean,
  originalEntry: EventPreviewSource["original_entry"] = null,
): EventPreviewSource {
  return {
    source_title: title,
    publication_id: null,
    observations,
    excerpt,
    excerpt_more: excerptMore,
    original_entry: originalEntry,
  };
}

export function makePreview(
  eventId: string,
  name: string,
  sources: EventPreviewSource[],
  sourceCount = sources.length,
  hasMoreSources = false,
): EventPreview {
  return {
    event_id: eventId,
    catalog_sha: EVENTS_CATALOG,
    name,
    sources,
    source_count: sourceCount,
    has_more_sources: hasMoreSources,
  };
}

export interface TargetSpec {
  readonly eventId: string;
  readonly relation: "current" | "mention";
  readonly ordinal: number;
  readonly spanId: string;
  readonly excerpt: string;
  readonly sourceTitle: string;
  readonly chapterTitle: string;
}

export function makeTarget(spec: TargetSpec): EventTarget {
  return {
    event_id: spec.eventId,
    catalog_sha: EVENTS_CATALOG,
    relation: spec.relation,
    stream_id: EVENTS_STREAM,
    publication_id: "0192f0a0-0000-7000-8000-00000000bb02",
    chapter_id: `ch_fixture_${spec.ordinal}`,
    chapter_title: spec.chapterTitle,
    source_title: spec.sourceTitle,
    unit_id: unitId(spec.ordinal),
    span_id: spec.spanId,
    locator: unitLocator(spec.ordinal),
    excerpt: spec.excerpt,
  };
}

export function makeTargetPage(
  eventId: string,
  targets: EventTarget[],
  currentCount: number,
  mentionCount: number,
  nextCursor: string | null = null,
): EventTargetPage {
  return {
    event_id: eventId,
    catalog_sha: EVENTS_CATALOG,
    targets,
    current_count: currentCount,
    mention_count: mentionCount,
    next_cursor: nextCursor,
    has_more: nextCursor !== null,
  };
}

const RED_CLIFFS_SOURCE = source(
  "三國志·吳書·周瑜傳",
  [sourceObservation("建安十三年", 13, null)],
  "瑜、普為左右督，各領萬人，與備俱進。",
  true,
  { publication_id: "0192f0a0-0000-7000-8000-00000000bb02", anchor_id: "anc_fixture_red" },
);

const DIVERGENT_SOURCES: EventPreviewSource[] = [
  source("三國志·吳書", [sourceObservation("建安十三年", 13, null)], "瑜為前部大督。", false),
  source("後漢紀", [sourceObservation("建安十四年", 14, 8)], null, false),
];

export const SINGLE_PREVIEW = makePreview(
  EVENT_RED_CLIFFS,
  "赤壁之戰",
  [RED_CLIFFS_SOURCE],
  1,
  false,
);

export const SINGLE_TARGETS = makeTargetPage(
  EVENT_RED_CLIFFS,
  [
    makeTarget({
      eventId: EVENT_RED_CLIFFS,
      relation: "current",
      ordinal: 21,
      spanId: "es_target_single",
      excerpt: "遇於赤壁",
      sourceTitle: "三國志·吳書·周瑜傳",
      chapterTitle: "周瑜傳",
    }),
  ],
  1,
  0,
);

export const SECOND_PREVIEW = makePreview(
  EVENT_REPEAT_SECOND,
  "再記赤壁",
  DIVERGENT_SOURCES,
  4,
  true,
);

export const SECOND_TARGETS = makeTargetPage(
  EVENT_REPEAT_SECOND,
  [
    makeTarget({
      eventId: EVENT_REPEAT_SECOND,
      relation: "current",
      ordinal: 2,
      spanId: "es_target_second",
      excerpt: "再記赤壁",
      sourceTitle: "資治通鑑·卷六十五",
      chapterTitle: "漢紀五十七",
    }),
  ],
  1,
  0,
);

export const MULTI_PREVIEW = makePreview(
  EVENT_RED_CLIFFS,
  "赤壁之戰",
  [RED_CLIFFS_SOURCE, DIVERGENT_SOURCES[1]],
  2,
  false,
);

export const MULTI_TARGETS = makeTargetPage(
  EVENT_RED_CLIFFS,
  [
    makeTarget({
      eventId: EVENT_RED_CLIFFS,
      relation: "current",
      ordinal: 5,
      spanId: "es_multi_zhouyu",
      excerpt: "遇於赤壁",
      sourceTitle: "三國志·吳書·周瑜傳",
      chapterTitle: "周瑜傳",
    }),
    makeTarget({
      eventId: EVENT_RED_CLIFFS,
      relation: "current",
      ordinal: 6,
      spanId: "es_multi_weidi",
      excerpt: "公至赤壁",
      sourceTitle: "三國志·魏書·武帝紀",
      chapterTitle: "武帝紀",
    }),
    makeTarget({
      eventId: EVENT_RED_CLIFFS,
      relation: "mention",
      ordinal: 7,
      spanId: "es_multi_mention",
      excerpt: "後人稱赤壁之戰",
      sourceTitle: "資治通鑑·卷六十五",
      chapterTitle: "漢紀五十七",
    }),
  ],
  2,
  1,
);

export const MENTION_ONLY_PREVIEW = makePreview(
  EVENT_RED_CLIFFS,
  "赤壁之戰",
  [DIVERGENT_SOURCES[0]],
  1,
  false,
);

export const MENTION_ONLY_TARGETS = makeTargetPage(
  EVENT_RED_CLIFFS,
  [
    makeTarget({
      eventId: EVENT_RED_CLIFFS,
      relation: "mention",
      ordinal: 8,
      spanId: "es_mention_only",
      excerpt: "習鑿齒論及赤壁",
      sourceTitle: "漢晉春秋",
      chapterTitle: "習鑿齒論",
    }),
  ],
  0,
  1,
);

export const LATE_PREVIEW_A = makePreview(
  EVENT_LATE_A,
  "赤壁之戰（迟到响应）",
  [RED_CLIFFS_SOURCE],
  1,
  false,
);
export const LATE_TARGETS_A = makeTargetPage(EVENT_LATE_A, [], 0, 0);

export const LATE_PREVIEW_B = makePreview(
  EVENT_LATE_B,
  "南郡之戰",
  [source("三國志·吳書·周瑜傳", [sourceObservation("建安十四年", 14, null)], "追操至南郡。", false)],
  1,
  false,
);
export const LATE_TARGETS_B = makeTargetPage(
  EVENT_LATE_B,
  [
    makeTarget({
      eventId: EVENT_LATE_B,
      relation: "current",
      ordinal: 9,
      spanId: "es_late_b",
      excerpt: "追操至南郡",
      sourceTitle: "三國志·吳書·周瑜傳",
      chapterTitle: "周瑜傳",
    }),
  ],
  1,
  0,
);

export const FAILURE_PREVIEW = makePreview(
  EVENT_RED_CLIFFS,
  "赤壁之戰",
  [RED_CLIFFS_SOURCE],
  1,
  false,
);
export const FAILURE_TARGETS = SINGLE_TARGETS;

/** 单 trigger 场景：resolved span 位于本段。 */
export const RESOLVED_SEGMENT = eventSpan("es_resolved", "赤壁", EVENT_RED_CLIFFS, { start: 3, end: 5 });

export const RESOLVED_SENTENCE = [
  { kind: "text" as const, text: "遇於" },
  RESOLVED_SEGMENT,
  { kind: "text" as const, text: "。" },
];
export const RESOLVED_UNIT_TEXT = "遇於赤壁。";

/** 重复词：正文里还有一次普通文本「赤壁」，不得被全局 replace 成事件。 */
export const REPEAT_SEGMENTS = [
  eventSpan("es_repeat_first", "赤壁", EVENT_RED_CLIFFS),
  { kind: "text" as const, text: "，後人又稱赤壁之戰，再記" },
  eventSpan("es_repeat_second", "赤壁", EVENT_REPEAT_SECOND),
  { kind: "text" as const, text: "。" },
];
export const REPEAT_UNIT_TEXT = "赤壁，後人又稱赤壁之戰，再記赤壁。";

/** 非 resolved：ambiguous / unresolved / resolved-but-no-canonical 都不可操作。 */
export const UNCERTAIN_SEGMENTS: ReadingEventSegment[] = [
  eventSpan("es_amb", "曹操", null, { status: "ambiguous", relation: "current" }),
  eventSpan("es_unres", "劉琮", null, { status: "unresolved", relation: "retrospective" }),
  eventSpan("es_nocanon", "孫權", null),
];
export const UNCERTAIN_UNIT_TEXT = "曹操劉琮孫權";

export const LATE_SEGMENTS = [
  eventSpan("es_late_a", "赤壁", EVENT_LATE_A),
  { kind: "text" as const, text: "與" },
  eventSpan("es_late_b", "南郡", EVENT_LATE_B),
];
export const LATE_UNIT_TEXT = "赤壁與南郡";
