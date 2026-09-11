// C2-R2-T02 harness fixture：仅演示 published DTO 形状与受控响应。
//
// 全部内容为 synthetic，不是真实 0.2 模型输出，也不是真实后端响应；
// 文案借用第一轮冻结正文的短定位片段只为说明阅读行为，不得当作译文或史料断言。

import {
  READING_FIXTURE_SAMPLE_NOTE,
  type ContextEntity,
  type ReadingTimeGroup,
  type ReadingUnit,
} from "../types";

const NOTE = READING_FIXTURE_SAMPLE_NOTE;

function sel(quote: string, occurrence = 1) {
  return [{ quote, occurrence }];
}

export const FIXTURE_CONTEXT: ContextEntity[] = [
  {
    entity_ref: "fixture-ent-zhouyu",
    entity_type: "person",
    display_name: "周瑜",
    importance: "primary",
    source_selections: sel("瑜為前部大督"),
  },
  {
    entity_ref: "fixture-ent-caocao",
    entity_type: "person",
    display_name: "曹操",
    importance: "other",
    source_selections: sel("曹公入荊州"),
  },
  {
    entity_ref: "fixture-ent-nanjun",
    entity_type: "place",
    display_name: "南郡",
    importance: "other",
    source_selections: sel("追操至南郡"),
  },
];

export const FIXTURE_PAGE1: ReadingUnit[] = [
  {
    unit_id: "ru_fixture_0001",
    ordinal: 0,
    block_id: "blk_fixture_0001",
    group_id: "rg_fixture_0001",
    continues_previous: false,
    text: "十三年春，權討江夏，瑜為前部大督。",
    segments: [{ kind: "text", text: "十三年春，權討江夏，瑜為前部大督。" }],
    context_entities: FIXTURE_CONTEXT,
    source_anchor_ids: ["anc_fixture_0001"],
    narrative_time: { mode: "events", event_refs: ["evt_fixture_u01"], from_block_id: null, source_selections: sel("十三年春") },
    synthetic: true,
    sample_note: NOTE,
  },
  {
    unit_id: "ru_fixture_0002",
    ordinal: 1,
    block_id: "blk_fixture_0002",
    group_id: "rg_fixture_0002",
    continues_previous: true,
    text: "其年九月，曹公入荊州，劉琮舉眾降。",
    segments: [
      { kind: "text", text: "其年九月，曹公入荊州，" },
      { kind: "event", text: "劉琮舉眾降", span_id: "span_fixture_0000", status: "ambiguous", relation: "current" },
      { kind: "text", text: "。" },
    ],
    context_entities: [FIXTURE_CONTEXT[0], FIXTURE_CONTEXT[1]],
    source_anchor_ids: ["anc_fixture_0002"],
    narrative_time: { mode: "inherit", event_refs: [], from_block_id: "blk_fixture_0001", source_selections: sel("其年九月") },
    synthetic: true,
    sample_note: NOTE,
  },
  {
    unit_id: "ru_fixture_0003",
    ordinal: 2,
    block_id: "blk_fixture_0003",
    group_id: "rg_fixture_0002",
    continues_previous: true,
    text: "遇於赤壁。時曹公軍眾已有疾病。",
    segments: [
      { kind: "text", text: "遇於" },
      {
        kind: "event",
        text: "赤壁",
        span_id: "span_fixture_0001",
        status: "resolved",
        relation: "current",
      },
      { kind: "text", text: "。時曹公軍眾已有疾病。" },
    ],
    context_entities: FIXTURE_CONTEXT,
    source_anchor_ids: ["anc_fixture_0003"],
    narrative_time: { mode: "events", event_refs: ["evt_fixture_red_cliffs"], from_block_id: null, source_selections: sel("遇於赤壁") },
    synthetic: true,
    sample_note: NOTE,
  },
];

export const FIXTURE_PAGE2: ReadingUnit[] = [
  {
    unit_id: "ru_fixture_0004",
    ordinal: 3,
    block_id: "blk_fixture_0004",
    group_id: "rg_fixture_0003",
    continues_previous: true,
    text: "劉備、周瑜水陸並進，追操至南郡。",
    segments: [
      { kind: "text", text: "劉備、周瑜水陸並進，追操至" },
      { kind: "event", text: "南郡", span_id: "span_fixture_0002", status: "ambiguous", relation: "current" },
      { kind: "text", text: "。" },
    ],
    context_entities: [FIXTURE_CONTEXT[0], FIXTURE_CONTEXT[2]],
    source_anchor_ids: ["anc_fixture_0004"],
    narrative_time: { mode: "events", event_refs: ["evt_fixture_nanjun"], from_block_id: null, source_selections: sel("追操至南郡") },
    synthetic: true,
    sample_note: NOTE,
  },
  {
    unit_id: "ru_fixture_0005",
    ordinal: 4,
    block_id: "blk_fixture_0005",
    group_id: "rg_fixture_0004",
    continues_previous: false,
    text: "習鑿齒論曰：曹操暫自驕伐而天下三分。",
    segments: [
      { kind: "text", text: "習鑿齒論曰：曹操暫自驕伐而天下三分。" },
      { kind: "event", text: "曹操", span_id: "span_fixture_0003", status: "unresolved", relation: "background" },
    ],
    context_entities: [],
    source_anchor_ids: ["anc_fixture_0005"],
    narrative_time: { mode: "unknown", event_refs: [], from_block_id: null, source_selections: [] },
    synthetic: true,
    sample_note: NOTE,
  },
];

export const FIXTURE_GROUPS: ReadingTimeGroup[] = [
  {
    group_id: "rg_fixture_0001",
    first_unit_ordinal: 0,
    last_unit_ordinal: 0,
    year_key: "regnal:jianan:13",
    period_key: "regnal:jianan:13:spring",
    year_label: "建安十三年",
    period_label: "春",
    precision: "regnal",
    continues_previous: false,
  },
  {
    group_id: "rg_fixture_0002",
    first_unit_ordinal: 1,
    last_unit_ordinal: 2,
    year_key: "regnal:jianan:13",
    period_key: "regnal:jianan:13:9",
    year_label: "建安十三年",
    period_label: "史料九月",
    precision: "regnal",
    continues_previous: true,
  },
  {
    group_id: "rg_fixture_0003",
    first_unit_ordinal: 3,
    last_unit_ordinal: 3,
    year_key: null,
    period_key: "unknown",
    year_label: "时间未明确",
    period_label: "时间未明确",
    precision: "unknown",
    continues_previous: false,
  },
  {
    group_id: "rg_fixture_0004",
    first_unit_ordinal: 4,
    last_unit_ordinal: 4,
    year_key: null,
    period_key: "unknown",
    year_label: "时间未明确",
    period_label: "时间未明确",
    precision: "unknown",
    continues_previous: false,
  },
];
