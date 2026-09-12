// C2-R3-T11 人物阶段资料的纯展示投影。
//
// 只消费 T01 已编译的公开 DTO（person-state-types.ts 的 PersonSummary /
// StateItem / StateChange / PlaceStateItem），把“当时状态、两档明确性、限定语、
// 原因与变化”整理成组件可直接渲染的行。这里不做任何历史判定：
//
//  - certainty 只来自服务端结果，不按 confidence／年份重新推断颜色或虚实；
//  - 兼任＝多个并存项各自成行，不压成“最高官职”；
//  - 暂无记载（no_record）与阶段未明确（stage_unknown）是不同空态；
//  - 行政归属（administration）与实际控制（control）分开，不互相推导。
//
// 组件层只负责排版与回调，不在这里创建第二套状态／来源语义。

import type {
  Certainty,
  PersonPhaseMode,
  PersonSummary,
  PhaseSummary,
  PlaceDimension,
  PlaceStateItem,
  Qualification,
  ReasonCode,
  StateChange,
  StateDimension,
  StateItem,
  StateOperation,
} from "./person-state-types";

// ---------------------------------------------------------------------------
// Fixed labels / marks (mirror person-state-reading.md §2)
// ---------------------------------------------------------------------------

export const CERTAINTY_LABELS: Readonly<Record<Certainty, string>> = {
  clear: "明确",
  uncertain: "存疑",
};

/** 实心／空心组合；颜色不是唯一信号。 */
export const CERTAINTY_MARKS: Readonly<Record<Certainty, string>> = {
  clear: "●",
  uncertain: "○",
};

export const REASON_LABELS: Readonly<Record<ReasonCode, string>> = {
  tenure_unproven: "任期未明",
  order_unknown: "先后未明",
  source_disagreement: "来源分歧",
  attribution_uncertain: "归属未定",
  evidence_uncertain: "证据未能确定",
  phase_not_reached: "属于当前阶段之后",
  phase_not_begun: "尚未开始",
};

export const PHASE_MODE_LABELS: Readonly<Record<PersonPhaseMode, string>> = {
  single: "本段单一阶段",
  process: "本段多阶段过程",
  ambiguous: "多种解释并存",
  unknown: "阶段未明确",
};

export const PERSON_DIMENSION_LABELS: Readonly<Record<StateDimension, string>> = {
  office: "官职",
  title: "爵号",
  affiliation: "效力",
};

export const PLACE_DIMENSION_LABELS: Readonly<Record<PlaceDimension, string>> = {
  administration: "行政归属",
  control: "实际控制",
};

export const RELATION_LABELS: Readonly<Record<"serves" | "attached_to", string>> = {
  serves: "效力",
  attached_to: "归附",
};

/** ordinary 不显示限定语；荐举／追赠不能建立生前当前任职，自称必须保留。 */
export const QUALIFICATION_LABELS: Readonly<Record<Qualification, string>> = {
  ordinary: "",
  recommendation: "荐举（不建立当前任职）",
  self_designation: "自称",
  posthumous: "追赠（不建立当前任职）",
  reported: "引述记载",
};

export const OPERATION_LABELS: Readonly<Record<StateOperation, string>> = {
  start: "取得／归附",
  end: "结束",
  attest: "本段有载",
};

export const EMPTY_STATE_LABELS: Readonly<Record<EmptyStateKind, string>> = {
  no_record: "暂无记载",
  stage_unknown: "阶段未明确",
};

export const LEGEND_CLEAR_TEXT = "明确：有已核对来源支持本阶段结论";
export const LEGEND_UNCERTAIN_TEXT = "存疑：有材料但结论／任期／先后／来源尚未确定，仍可查看";

export type EmptyStateKind = "no_record" | "stage_unknown";

export function certaintyLabel(certainty: Certainty): string {
  return CERTAINTY_LABELS[certainty];
}

export function certaintyMark(certainty: Certainty): string {
  return CERTAINTY_MARKS[certainty];
}

export function reasonLabel(code: ReasonCode): string {
  return REASON_LABELS[code] ?? code;
}

/** 服务端已给中文短说明时优先使用；缺省时按稳定 code 回退，不编造文本。 */
export function buildReasonText(
  codes: readonly ReasonCode[],
  serverText?: string | null,
): string | null {
  if (serverText && serverText.trim().length > 0) return serverText.trim();
  const labels = codes.map(reasonLabel).filter((label) => label.length > 0);
  return labels.length > 0 ? labels.join("；") : null;
}

// ---------------------------------------------------------------------------
// Person state items
// ---------------------------------------------------------------------------

export interface StateItemView {
  readonly item: StateItem;
  readonly labelText: string;
  readonly valueText: string;
  readonly qualificationText: string | null;
  readonly reasonText: string | null;
  readonly accessibleText: string;
  readonly hasEvidence: boolean;
}

export function stateItemLabelText(item: StateItem): string {
  if (item.dimension === "affiliation") {
    return item.relation ? RELATION_LABELS[item.relation] : PERSON_DIMENSION_LABELS.affiliation;
  }
  return PERSON_DIMENSION_LABELS[item.dimension];
}

export function stateItemValueText(item: StateItem): string {
  // affiliation 的关系标签已由 labelText 呈现（例如 label「效力」＋value「孙权」）；
  // 值只放对象本身，避免同一关系在同一行出现两次。
  if (item.dimension === "affiliation") {
    return item.target ?? "（对象未明）";
  }
  return item.value ?? "—";
}

export function stateItemQualificationText(item: StateItem): string | null {
  const label = QUALIFICATION_LABELS[item.qualification];
  return label.length > 0 ? label : null;
}

/** 一条紧凑项的完整可访问名称，覆盖标记、限定语与原因。 */
export function stateItemAccessibleText(view: Omit<StateItemView, "accessibleText">): string {
  const parts = [`${certaintyLabel(view.item.certainty)}：${view.labelText}，${view.valueText}`];
  if (view.qualificationText) parts.push(view.qualificationText);
  if (view.reasonText) parts.push(`原因：${view.reasonText}`);
  return parts.join("；");
}

export function stateItemView(item: StateItem): StateItemView {
  const base = {
    item,
    labelText: stateItemLabelText(item),
    valueText: stateItemValueText(item),
    qualificationText: stateItemQualificationText(item),
    reasonText: buildReasonText(item.reason_codes, item.reason_text),
    hasEvidence: item.source_facts.length > 0 || item.evidence_count > 0,
  };
  return { ...base, accessibleText: stateItemAccessibleText(base) };
}

export interface PlaceItemView {
  readonly item: PlaceStateItem;
  readonly labelText: string;
  readonly valueText: string;
  readonly certainty: Certainty;
  /** 地点 DTO 没有限定语维度；保留字段以便与人物条目统一渲染。 */
  readonly qualificationText: null;
  readonly reasonText: string | null;
  readonly accessibleText: string;
  readonly hasEvidence: boolean;
}

export function placeItemValueText(item: PlaceStateItem): string {
  if (item.dimension === "control") return item.value ?? item.controller ?? "—";
  return item.value ?? "—";
}

export function placeItemView(item: PlaceStateItem): PlaceItemView {
  const labelText = PLACE_DIMENSION_LABELS[item.dimension];
  const valueText = placeItemValueText(item);
  const reasonText = buildReasonText(item.reason_codes, item.reason_text);
  const parts = [`${certaintyLabel(item.certainty)}：${labelText}，${valueText}`];
  if (reasonText) parts.push(`原因：${reasonText}`);
  return {
    item,
    labelText,
    valueText,
    certainty: item.certainty,
    qualificationText: null,
    reasonText,
    accessibleText: parts.join("；"),
    hasEvidence: item.source_facts.length > 0 || item.evidence_count > 0,
  };
}

/**
 * 空态只由“是否已有当时条目”与阶段模式决定：
 * 未知阶段且无条目 → 阶段未明确；其余无条目 → 暂无记载。
 * 不把事件角色、最后头衔或全生平简介补成一条虚构身份。
 */
export function emptyStateForPerson(person: PersonSummary): EmptyStateKind | null {
  if (person.identities.length > 0) return null;
  return person.phase_mode === "unknown" ? "stage_unknown" : "no_record";
}

// ---------------------------------------------------------------------------
// Grouping / pagination
// ---------------------------------------------------------------------------

export interface UnitStateGroups {
  readonly primary: readonly PersonSummary[];
  readonly other: readonly PersonSummary[];
  readonly places: readonly PlaceStateItem[];
}

/** 默认只列本段重要主体；其余人物按需（搜索／展开）进入。 */
export function groupUnitState(
  people: readonly PersonSummary[] | null | undefined,
  places: readonly PlaceStateItem[] | null | undefined,
): UnitStateGroups {
  const list = people ?? [];
  return {
    primary: list.filter((person) => person.importance === "primary"),
    other: list.filter((person) => person.importance !== "primary"),
    places: places ?? [],
  };
}

/** 每个地点独占一行：把同 place_id 的行政归属／控制项归到一行。 */
export interface PlaceGroupView {
  readonly placeId: string;
  readonly name: string;
  readonly items: readonly PlaceItemView[];
}

export function groupPlaceItems(
  places: readonly PlaceStateItem[] | null | undefined,
): readonly PlaceGroupView[] {
  const order: string[] = [];
  const buckets = new Map<string, { name: string; items: PlaceItemView[] }>();
  for (const place of places ?? []) {
    const key = place.place_id || place.name;
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { name: place.name, items: [] };
      buckets.set(key, bucket);
      order.push(key);
    }
    bucket.items.push(placeItemView(place));
  }
  return order.map((key) => ({ placeId: key, name: buckets.get(key)!.name, items: buckets.get(key)!.items }));
}

export const EMPTY_SECTION_TEXT = "这段正文还没有关联人物或地点。";

/** 超出预览上限时只显示入口与总数，不把首批冒充全部。 */
export function moreItemsText(count: number): string {
  return `更多 · ${count}`;
}

// ---------------------------------------------------------------------------
// Phase / change timeline (PersonStateDetails)
// ---------------------------------------------------------------------------

export function phaseLabel(phaseId: string | null | undefined, phases: readonly PhaseSummary[] | null | undefined): string {
  if (!phaseId) return "";
  const match = (phases ?? []).find((phase) => phase.phase_id === phaseId);
  return match ? match.label : phaseId;
}

export interface ChangeTimelineEntry {
  readonly change: StateChange;
  readonly dimensionLabel: string;
  readonly valueText: string;
  readonly operationLabel: string;
  readonly phaseLabel: string;
  readonly fromPhaseLabel: string | null;
  readonly certainty: Certainty;
  readonly reasonText: string | null;
  readonly accessibleText: string;
}

function changeValueText(change: StateChange): string {
  // 关系标签放进 dimensionLabel（「效力」／「归附」），值只保留对象，避免重复。
  if (change.dimension === "affiliation") {
    return change.target ?? "（对象未明）";
  }
  return change.value ?? "—";
}

/** 变化行的维度短标签；affiliation 用具体关系（效力／归附）而非笼统「效力」。 */
function changeDimensionLabel(change: StateChange): string {
  if (change.dimension === "affiliation") {
    return change.relation ? RELATION_LABELS[change.relation] : PERSON_DIMENSION_LABELS.affiliation;
  }
  return PERSON_DIMENSION_LABELS[change.dimension];
}

/**
 * 把 StateChange 投影成按阶段展开的有据经历；阶段顺序来自服务端有序
 * phases，不按年份重建或前端排序。
 */
export function buildChangeTimeline(
  changes: readonly StateChange[] | null | undefined,
  phases: readonly PhaseSummary[] | null | undefined,
): readonly ChangeTimelineEntry[] {
  return (changes ?? []).map((change) => {
    const dimensionLabel = changeDimensionLabel(change);
    const valueText = changeValueText(change);
    const operationLabel = OPERATION_LABELS[change.operation];
    const toLabel = phaseLabel(change.to_phase_id, phases) || change.to_phase_id;
    const fromLabel = change.from_phase_id ? phaseLabel(change.from_phase_id, phases) : null;
    const reason = buildReasonText(change.reason_codes);
    const text = `${certaintyLabel(change.certainty)}：${toLabel}，${dimensionLabel}${valueText}（${operationLabel}）`;
    return {
      change,
      dimensionLabel,
      valueText,
      operationLabel,
      phaseLabel: toLabel,
      fromPhaseLabel: fromLabel,
      certainty: change.certainty,
      reasonText: reason,
      accessibleText: reason ? `${text}；原因：${reason}` : text,
    };
  });
}
