// C2-R2-T02 阅读组件 fixture 的场景注册契约（仅测试使用，不进生产构建）。
//
// 各组件任务只新增自己的 `cases/<suite>/scene.tsx`（默认导出 ReadingScene
// 或其数组）；main.tsx 通过 import.meta.glob 发现并注册。这里只固定发现接口，
// 不定义生产组件，也不替代 T01 的 reading-types / 生产契约。

import type { ReactElement } from "react";

export const SUITE_NAMES = ["harness", "content", "axis", "position", "events", "context"] as const;

export type SuiteName = (typeof SUITE_NAMES)[number];

/** 尚未由组件任务实现的五类组件 suite；`--suite all` 要求它们全部存在。 */
export const COMPONENT_SUITES: readonly SuiteName[] = ["content", "axis", "position", "events", "context"];

export interface ReadingScene {
  /** suite 内唯一名称，URL 用 `?case=<suite>/<name>` 定位。 */
  readonly name: string;
  readonly suite: SuiteName;
  readonly label: string;
  /** 人造场景显式标记，禁止冒充真实史料或真实模型输出。 */
  readonly synthetic: boolean;
  readonly render: (params: URLSearchParams) => ReactElement;
}

// —— 以下仅为 published DTO 形状示例（continuous-reading.md），不是真实后端数据。 ——

export interface NarrativeTime {
  mode: "events" | "inherit" | "mixed" | "unknown";
  event_refs: string[];
  from_block_id: string | null;
  source_selections: Array<{ quote: string; occurrence: number }>;
}

export interface UnitSegment {
  kind: "text" | "event";
  text: string;
  span_id?: string;
  status?: "resolved" | "ambiguous" | "unresolved";
  relation?: "current" | "retrospective" | "foreshadow" | "background" | "uncertain";
}

export interface ContextEntity {
  entity_ref: string;
  entity_type: "person" | "place" | "polity" | "other";
  display_name: string;
  importance: "primary" | "other";
  source_selections: Array<{ quote: string; occurrence: number }>;
}

export interface ReadingUnit {
  unit_id: string;
  ordinal: number;
  block_id: string;
  group_id: string;
  continues_previous: boolean;
  text: string;
  segments: UnitSegment[];
  context_entities: ContextEntity[];
  source_anchor_ids: string[];
  narrative_time: NarrativeTime;
  synthetic: boolean;
  sample_note: string;
}

export interface ReadingTimeGroup {
  group_id: string;
  first_unit_ordinal: number;
  last_unit_ordinal: number;
  year_key: string | null;
  period_key: string;
  year_label: string;
  period_label: string;
  precision: "exact" | "year" | "regnal" | "opaque" | "unknown" | "mixed" | "range";
  continues_previous: boolean;
}

export const READING_FIXTURE_SAMPLE_NOTE =
  "fixture published-shape sample; synthetic, not a real model output or live backend";
