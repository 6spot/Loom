// C2-R2-T14 当前片段人物、地点与事件角色的纯展示投影。
//
// 只消费 active unit 的 published `context_entities`（reading-types.ts 的
// ContextEntityView）；不读取 World/人物状态，不推导长期官职、阵营或关系。
// 输出只描述“本段”：主要项优先、同类按出现顺序、按 canonical ID 去重但保留
// 各条来源与事件角色；未知/空段显式为空，不回退整章或世界快照。

import type { ContextEntityView, ContextImportance } from "./reading-types";

export type ContextEntityKind = ContextEntityView["kind"];

export const CONTEXT_GROUP_ORDER = ["people", "places", "polities", "others"] as const;

export type ContextGroupKey = (typeof CONTEXT_GROUP_ORDER)[number];

export const CONTEXT_GROUP_LABELS: Readonly<Record<ContextGroupKey, string>> = {
  people: "人物",
  places: "地点",
  polities: "政权与机构",
  others: "其他对象",
};

/** 默认最多展示 6 位人物、4 个地点；其余分组不设默认上限。 */
export const DEFAULT_CONTEXT_LIMITS: Readonly<Partial<Record<ContextGroupKey, number>>> = {
  people: 6,
  places: 4,
};

/** 事件角色只属于本段所叙述的事件，不是可推导的长期官职或阵营。 */
export const EVENT_ROLE_SCOPE_NOTE =
  "以下角色仅属于本段所叙述的事件，不代表长期官职或阵营。";

/** 地点只说明本段叙述涉及，不能据此断言人物正在该地。 */
export const PLACE_POSITION_NOTE = "地点为本段叙述所涉及，不代表人物所在位置。";

export interface ContextRoleDisplay {
  readonly entityRef: string;
  readonly eventRef: string;
  readonly role: string;
  readonly participantIndex: number;
}

export interface ContextDisplayItem {
  /** 稳定身份键：有 canonical ID 时按其去重，否则按 source-local ref 各自保留。 */
  readonly key: string;
  readonly canonicalId: string | null;
  readonly entityRef: string;
  readonly entityRefs: readonly string[];
  /** 展示名称来自当前 publication；缺失时退回 source-local ref，不向别处查询。 */
  readonly name: string;
  readonly kind: ContextEntityKind;
  readonly importance: ContextImportance;
  readonly sourceAnchorIds: readonly string[];
  readonly roles: readonly ContextRoleDisplay[];
  readonly deduped: boolean;
}

export interface ContextDisplayGroup {
  readonly key: ContextGroupKey;
  readonly label: string;
  readonly items: readonly ContextDisplayItem[];
  readonly total: number;
  readonly hiddenCount: number;
  readonly expanded: boolean;
  readonly limit: number | null;
}

export interface ReadingContextDisplay {
  readonly groups: readonly ContextDisplayGroup[];
  readonly hiddenGroups: readonly ContextDisplayGroup[];
  readonly hasAny: boolean;
  readonly totalItems: number;
}

export interface ReadingContextDisplayOptions {
  readonly primaryOnly?: boolean;
  readonly expanded?: Partial<Record<ContextGroupKey, boolean>>;
  readonly limits?: Partial<Record<ContextGroupKey, number>>;
}

export function contextGroupForKind(kind: ContextEntityKind): ContextGroupKey {
  switch (kind) {
    case "person":
      return "people";
    case "place":
      return "places";
    case "polity":
    case "organization":
    case "army":
    case "office":
      return "polities";
    default:
      return "others";
  }
}

function identityKey(entity: ContextEntityView): string {
  return entity.canonical_id ? `cid:${entity.canonical_id}` : `ref:${entity.entity_ref}`;
}

function uniquePush<T>(list: T[], value: T): void {
  if (!list.includes(value)) list.push(value);
}

interface Accumulator {
  key: string;
  canonicalId: string | null;
  entityRef: string;
  entityRefs: string[];
  name: string;
  kind: ContextEntityKind;
  importance: ContextImportance;
  sourceAnchorIds: string[];
  roles: ContextRoleDisplay[];
  firstSeen: number;
  deduped: boolean;
}

function accumulate(
  buckets: Map<string, Accumulator>,
  entity: ContextEntityView,
  index: number,
): void {
  const key = identityKey(entity);
  const existing = buckets.get(key);
  if (!existing) {
    buckets.set(key, {
      key,
      canonicalId: entity.canonical_id ?? null,
      entityRef: entity.entity_ref,
      entityRefs: [entity.entity_ref],
      name: entity.name ?? entity.entity_ref,
      kind: entity.kind,
      importance: entity.importance,
      sourceAnchorIds: [...(entity.source_anchor_ids ?? [])],
      roles: (entity.event_roles ?? []).map((role) => ({
        entityRef: entity.entity_ref,
        eventRef: role.event_ref,
        role: role.role,
        participantIndex: role.participant_index,
      })),
      firstSeen: index,
      deduped: false,
    });
    return;
  }

  // 同一 canonical ID 的不同 source-local 表示：合并来源与事件角色，保留主要性。
  existing.deduped = true;
  uniquePush(existing.entityRefs, entity.entity_ref);
  for (const anchor of entity.source_anchor_ids ?? []) uniquePush(existing.sourceAnchorIds, anchor);
  for (const role of entity.event_roles ?? []) {
    const duplicate = existing.roles.some(
      (candidate) =>
        candidate.entityRef === entity.entity_ref &&
        candidate.eventRef === role.event_ref &&
        candidate.role === role.role &&
        candidate.participantIndex === role.participant_index,
    );
    if (!duplicate) {
      existing.roles.push({
        entityRef: entity.entity_ref,
        eventRef: role.event_ref,
        role: role.role,
        participantIndex: role.participant_index,
      });
    }
  }
  if (entity.importance === "primary") existing.importance = "primary";
}

function toItem(accumulator: Accumulator): ContextDisplayItem {
  return {
    key: accumulator.key,
    canonicalId: accumulator.canonicalId,
    entityRef: accumulator.entityRef,
    entityRefs: accumulator.entityRefs,
    name: accumulator.name,
    kind: accumulator.kind,
    importance: accumulator.importance,
    sourceAnchorIds: accumulator.sourceAnchorIds,
    roles: accumulator.roles,
    deduped: accumulator.deduped,
  };
}

function importanceRank(importance: ContextImportance): number {
  return importance === "primary" ? 0 : 1;
}

/**
 * 把 active unit 的 context_entities 投影成分组展示结果。
 * null/undefined/空数组都表示“本段无明确关联”，不会返回整章或世界数据。
 */
export function buildReadingContextDisplay(
  entities: readonly ContextEntityView[] | null | undefined,
  options: ReadingContextDisplayOptions = {},
): ReadingContextDisplay {
  const list = entities ?? [];
  const bucketsByGroup = new Map<ContextGroupKey, Map<string, Accumulator>>();
  for (const group of CONTEXT_GROUP_ORDER) bucketsByGroup.set(group, new Map());

  list.forEach((entity, index) => {
    const groupKey = contextGroupForKind(entity.kind);
    accumulate(bucketsByGroup.get(groupKey)!, entity, index);
  });

  const groups: ContextDisplayGroup[] = [];
  const hiddenGroups: ContextDisplayGroup[] = [];
  let totalItems = 0;

  for (const groupKey of CONTEXT_GROUP_ORDER) {
    const buckets = [...bucketsByGroup.get(groupKey)!.values()];
    if (buckets.length === 0) continue;
    totalItems += buckets.length;

    // 主要项优先，其余按本段出现顺序；排序稳定，不依赖 locale。
    buckets.sort(
      (left, right) =>
        importanceRank(left.importance) - importanceRank(right.importance) ||
        left.firstSeen - right.firstSeen,
    );

    const limit = options.limits?.[groupKey] ?? DEFAULT_CONTEXT_LIMITS[groupKey] ?? null;
    const expanded = options.expanded?.[groupKey] === true;
    const items = buckets.map(toItem);
    const eligible = options.primaryOnly && !expanded
      ? items.filter((item) => item.importance === "primary")
      : items;
    const visible = limit === null || expanded ? eligible : eligible.slice(0, limit);

    (visible.length ? groups : hiddenGroups).push({
      key: groupKey,
      label: CONTEXT_GROUP_LABELS[groupKey],
      items: visible,
      total: items.length,
      hiddenCount: items.length - visible.length,
      expanded,
      limit,
    });
  }

  return { groups, hiddenGroups, hasAny: groups.length > 0, totalItems };
}

/** 事件角色标签：显式带出所属事件，避免被读成长期头衔。 */
export function eventRoleLabel(
  role: Pick<ContextRoleDisplay, "eventRef" | "role">,
  resolveEventLabel?: (eventRef: string) => string | null,
): string {
  const event = resolveEventLabel?.(role.eventRef) ?? role.eventRef;
  return `${role.role}（事件：${event}）`;
}
