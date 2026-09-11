// C2-R2-T14 当前片段人物地点组件的 Independent fixture scenes（仅测试使用，不进生产）。
//
// 全部场景显式 synthetic：演示 published DTO 形状（T01 ContextEntityView）与
// 受控切换/空段/来源缺失，不是真实史料译文，也不是真实模型输出。

import { useState } from "react";
import ReadingContextPanel from "../../../../../src/components/reading/ReadingContextPanel";
import type { ContextEntityView } from "../../../../../src/lib/reading-types";
import type { ContextDisplayItem } from "../../../../../src/lib/reading-context-display";
import type { ReadingScene } from "../types";

function ent(overrides: Partial<ContextEntityView> & { entity_ref: string }): ContextEntityView {
  return {
    entity_ref: overrides.entity_ref,
    name: overrides.name ?? overrides.entity_ref,
    canonical_id: overrides.canonical_id ?? null,
    kind: overrides.kind ?? "person",
    importance: overrides.importance ?? "other",
    source_anchor_ids: overrides.source_anchor_ids ?? [`anc-${overrides.entity_ref}`],
    event_roles: overrides.event_roles ?? [],
  };
}

const EVENT_LABELS: Record<string, string> = {
  "evt-red-cliffs": "赤壁之戰",
  "evt-nanjun": "南郡之戰",
  "evt-jiangxia": "江夏之戰",
};

const UNIT_A: ContextEntityView[] = [
  ent({
    entity_ref: "ref-zhouyu-a",
    canonical_id: "ent-zhouyu",
    name: "周瑜",
    importance: "primary",
    source_anchor_ids: ["anc-zhouyu-a"],
    event_roles: [{ event_ref: "evt-red-cliffs", role: "督", participant_index: 0 }],
  }),
  ent({
    entity_ref: "ref-zhouyu-b",
    canonical_id: "ent-zhouyu",
    name: "周瑜",
    source_anchor_ids: ["anc-zhouyu-b"],
    event_roles: [{ event_ref: "evt-nanjun", role: "領軍", participant_index: 1 }],
  }),
  ent({ entity_ref: "ref-caocao", canonical_id: "ent-caocao", name: "曹操" }),
  ent({ entity_ref: "ref-zhangfei-1", canonical_id: "ent-zhangfei-1", name: "張飛" }),
  ent({ entity_ref: "ref-zhangfei-2", canonical_id: "ent-zhangfei-2", name: "張飛" }),
  ent({ entity_ref: "ref-liubei", canonical_id: "ent-liubei", name: "劉備", importance: "primary" }),
  ent({ entity_ref: "ref-sunquan", canonical_id: "ent-sunquan", name: "孫權" }),
  ent({ entity_ref: "ref-guanyu", canonical_id: "ent-guanyu", name: "關羽" }),
  ent({ entity_ref: "ref-nanjun", canonical_id: "ent-nanjun", name: "南郡", kind: "place" }),
  ent({ entity_ref: "ref-jiangling", canonical_id: "ent-jiangling", name: "江陵", kind: "place" }),
  ent({ entity_ref: "ref-xiakou", canonical_id: "ent-xiakou", name: "夏口", kind: "place" }),
  ent({ entity_ref: "ref-chibi", canonical_id: "ent-chibi", name: "赤壁", kind: "place",
    event_roles: [{ event_ref: "evt-red-cliffs", role: "戰地", participant_index: 0 }] }),
  ent({ entity_ref: "ref-wulin", canonical_id: "ent-wulin", name: "烏林", kind: "place" }),
  ent({ entity_ref: "ref-wu", canonical_id: "ent-wu", name: "吳", kind: "polity" }),
  ent({ entity_ref: "ref-navy", canonical_id: "ent-navy", name: "水軍", kind: "army" }),
  ent({ entity_ref: "ref-seal", name: "傳國璽", kind: "other", source_anchor_ids: [] }),
];

const UNIT_B: ContextEntityView[] = [];

const UNIT_C: ContextEntityView[] = [
  ent({
    entity_ref: "ref-supported-only",
    canonical_id: null,
    name: "某將",
    source_anchor_ids: ["anc-supported-only"],
  }),
  ent({ entity_ref: "ref-no-source", canonical_id: null, name: "無據可考者", source_anchor_ids: [] }),
];

const EVENT_ROLE_UNIT: ContextEntityView[] = [
  ent({
    entity_ref: "ref-zhouyu",
    canonical_id: "ent-zhouyu",
    name: "周瑜",
    importance: "primary",
    event_roles: [
      { event_ref: "evt-jiangxia", role: "前部大督", participant_index: 0 },
      { event_ref: "evt-red-cliffs", role: "督", participant_index: 0 },
      { event_ref: "evt-nanjun", role: "領軍", participant_index: 1 },
    ],
  }),
  ent({
    entity_ref: "ref-chibi",
    canonical_id: "ent-chibi",
    name: "赤壁",
    kind: "place",
    event_roles: [{ event_ref: "evt-red-cliffs", role: "戰地", participant_index: 0 }],
  }),
  ent({ entity_ref: "ref-unknown-envoy", name: "使者", canonical_id: null, source_anchor_ids: [] }),
];

function SwitchableColumn() {
  const [active, setActive] = useState<"A" | "B" | "C">("A");
  const [lastAction, setLastAction] = useState("");
  const entities = active === "A" ? UNIT_A : active === "B" ? UNIT_B : UNIT_C;
  return (
    <main data-test="context-scene" data-synthetic="true">
      <p data-test="reading-synthetic-note">
        合成 fixture：仅演示 ContextEntityView 形状，非真实史料或模型输出。
      </p>
      <div data-test="context-unit-controls">
        <button type="button" data-test="context-unit-a" onClick={() => setActive("A")}>
          切到有人的段
        </button>
        <button type="button" data-test="context-unit-b" onClick={() => setActive("B")}>
          切到空段
        </button>
        <button type="button" data-test="context-unit-c" onClick={() => setActive("C")}>
          切到来源缺失段
        </button>
        <span data-test="context-active-unit">{active}</span>
        <span data-test="context-last-action">{lastAction}</span>
      </div>
      <ReadingContextPanel
        entities={entities}
        unitId={`unit-${active}`}
        resolveEventLabel={(ref) => EVENT_LABELS[ref] ?? null}
        onViewEntity={(item: ContextDisplayItem) => setLastAction(`entity:${item.canonicalId ?? item.entityRef}`)}
        onViewSource={(item: ContextDisplayItem, anchorId: string) => setLastAction(`source:${anchorId}`)}
      />
    </main>
  );
}

function EventRoleColumn() {
  return (
    <main data-test="context-scene" data-synthetic="true">
      <ReadingContextPanel
        entities={EVENT_ROLE_UNIT}
        unitId="unit-event-roles"
        resolveEventLabel={(ref) => EVENT_LABELS[ref] ?? null}
      />
    </main>
  );
}

function CompactPanel() {
  return (
    <main data-test="context-scene" data-synthetic="true">
      <ReadingContextPanel entities={UNIT_A} unitId="unit-compact" variant="panel" />
    </main>
  );
}

const scenes: ReadingScene[] = [
  {
    name: "active-unit",
    suite: "context",
    label: "随 active unit 切换/清空/恢复的人物地点分栏",
    synthetic: true,
    render: () => <SwitchableColumn />,
  },
  {
    name: "event-roles",
    suite: "context",
    label: "多事件角色与地点事件角色（不冒充长期官职/人物位置）",
    synthetic: true,
    render: () => <EventRoleColumn />,
  },
  {
    name: "compact-panel",
    suite: "context",
    label: "窄屏按需人物地点面板（打开/关闭焦点）",
    synthetic: true,
    render: () => <CompactPanel />,
  },
];

export default scenes;
