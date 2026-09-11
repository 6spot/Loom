// C2-R2-T13 events suite 场景注册（仅测试使用，不进生产构建）。
//
// 主 harness 通过 `cases/*/scene.tsx` 发现本文件；本任务只新增 events suite，
// 不改 main.tsx / cases/types.ts / 基座 suite。

import { EventsScene } from "./EventsScene";
import {
  EVENT_LATE_A,
  EVENT_LATE_B,
  EVENT_RED_CLIFFS,
  EVENT_REPEAT_SECOND,
  FAILURE_PREVIEW,
  FAILURE_TARGETS,
  LATE_PREVIEW_A,
  LATE_PREVIEW_B,
  LATE_SEGMENTS,
  LATE_TARGETS_A,
  LATE_TARGETS_B,
  LATE_UNIT_TEXT,
  MENTION_ONLY_PREVIEW,
  MENTION_ONLY_TARGETS,
  MULTI_PREVIEW,
  MULTI_TARGETS,
  REPEAT_SEGMENTS,
  REPEAT_UNIT_TEXT,
  RESOLVED_SENTENCE,
  RESOLVED_UNIT_TEXT,
  SECOND_PREVIEW,
  SECOND_TARGETS,
  SINGLE_PREVIEW,
  SINGLE_TARGETS,
  UNCERTAIN_SEGMENTS,
  UNCERTAIN_UNIT_TEXT,
} from "./fixtures";
import type { ReadingScene } from "../types";

const resolvedResponses = {
  [EVENT_RED_CLIFFS]: { preview: SINGLE_PREVIEW, targets: SINGLE_TARGETS },
};

const scenes: ReadingScene[] = [
  {
    name: "events-resolved",
    suite: "events",
    label: "单个 resolved 事件词：按需预览、查看事件、定位发生位置",
    synthetic: true,
    render: () => (
      <EventsScene
        heading="事件词：单个 resolved"
        unitText={RESOLVED_UNIT_TEXT}
        segments={RESOLVED_SENTENCE}
        responses={resolvedResponses}
      />
    ),
  },
  {
    name: "events-repeat",
    suite: "events",
    label: "重复译文词：同一词两次 occurrence 各自绑定，普通文本不触发",
    synthetic: true,
    render: () => (
      <EventsScene
        heading="事件词：重复词与普通文本"
        unitText={REPEAT_UNIT_TEXT}
        segments={REPEAT_SEGMENTS}
        responses={{
          [EVENT_RED_CLIFFS]: { preview: SINGLE_PREVIEW, targets: SINGLE_TARGETS },
          [EVENT_REPEAT_SECOND]: { preview: SECOND_PREVIEW, targets: SECOND_TARGETS },
        }}
      />
    ),
  },
  {
    name: "events-multi-target",
    suite: "events",
    label: "多 current 目标：必须选择来源/章/位置，mention 单独标注",
    synthetic: true,
    render: () => (
      <EventsScene
        heading="事件词：多目标选择"
        unitText={RESOLVED_UNIT_TEXT}
        segments={RESOLVED_SENTENCE}
        responses={{
          [EVENT_RED_CLIFFS]: { preview: MULTI_PREVIEW, targets: MULTI_TARGETS },
        }}
      />
    ),
  },
  {
    name: "events-mention-only",
    suite: "events",
    label: "只有回溯提及：不自动跳转，如实提示暂无发生段落",
    synthetic: true,
    render: () => (
      <EventsScene
        heading="事件词：仅提及"
        unitText={RESOLVED_UNIT_TEXT}
        segments={RESOLVED_SENTENCE}
        responses={{
          [EVENT_RED_CLIFFS]: { preview: MENTION_ONLY_PREVIEW, targets: MENTION_ONLY_TARGETS },
        }}
      />
    ),
  },
  {
    name: "events-uncertain",
    suite: "events",
    label: "未确认事件词：ambiguous / unresolved 不冒充唯一链接",
    synthetic: true,
    render: () => (
      <EventsScene
        heading="事件词：未确认"
        unitText={UNCERTAIN_UNIT_TEXT}
        segments={UNCERTAIN_SEGMENTS}
        responses={{}}
      />
    ),
  },
  {
    name: "events-late",
    suite: "events",
    label: "快速切换与迟到响应：旧响应不覆盖新预览",
    synthetic: true,
    render: () => (
      <EventsScene
        heading="事件词：迟到响应"
        unitText={LATE_UNIT_TEXT}
        segments={LATE_SEGMENTS}
        responses={{
          [EVENT_LATE_A]: { preview: LATE_PREVIEW_A, targets: LATE_TARGETS_A, previewDelayMs: 500, targetDelayMs: 500 },
          [EVENT_LATE_B]: { preview: LATE_PREVIEW_B, targets: LATE_TARGETS_B },
        }}
      />
    ),
  },
  {
    name: "events-failure",
    suite: "events",
    label: "载入失败保留正文并可重试",
    synthetic: true,
    render: () => (
      <EventsScene
        heading="事件词：载入失败与重试"
        unitText={RESOLVED_UNIT_TEXT}
        segments={RESOLVED_SENTENCE}
        responses={{
          [EVENT_RED_CLIFFS]: { preview: FAILURE_PREVIEW, targets: FAILURE_TARGETS, previewFailures: 1 },
        }}
      />
    ),
  },
  {
    name: "events-reduced-motion",
    suite: "events",
    label: "reduced-motion：开合不做位移动画",
    synthetic: true,
    render: () => (
      <EventsScene
        heading="事件词：reduced-motion"
        unitText={RESOLVED_UNIT_TEXT}
        segments={RESOLVED_SENTENCE}
        responses={resolvedResponses}
        reducedMotion
      />
    ),
  },
];

export default scenes;
