// C2-R2-T10 连续正文窗口的纯逻辑。
//
// 只做页合并/去重、章边界、有界窗口规划与占位高度记录；不接触 DOM、不拥有
// 路由/历史、不挑选 active unit（那是 T12 controller 的职责）。组件
// `components/reading/ReadingWindow.tsx` 消费这里的纯函数，使窗口回收、
// 固定单位与占位高度可以用 node 环境的单元测试逐条断言。
//
// 依据 reading-experience.md §3：正常最多 120 个已渲染 unit；正在聚焦、文本
// 选择或展开引用的 unit 固定保留，最多额外 20 个；若不能安全回收则停止预取
// 并显示显式加载入口，不移除用户正在操作的 DOM。

import {
  readingUnitText,
  type ReadingUnit,
  type StreamPage,
} from "./reading-types";

export interface ReadingWindowLimits {
  readonly maxMountedUnits: number;
  readonly maxPinnedUnits: number;
}

export const DEFAULT_READING_WINDOW_LIMITS: ReadingWindowLimits = {
  maxMountedUnits: 120,
  maxPinnedUnits: 20,
};

/** 未测得高度时的保守占位估计，避免外层滚动位置塌陷。 */
export const ESTIMATED_READING_UNIT_HEIGHT = 140;

/** active / focused / selected / 引用展开 / 外部显式固定。 */
export type ReadingPinReason =
  | "active"
  | "focused"
  | "selected"
  | "source"
  | "external";

export function resolveReadingWindowLimits(
  input?: Partial<ReadingWindowLimits>,
): ReadingWindowLimits {
  const maxMountedUnits = Math.max(
    1,
    Math.floor(input?.maxMountedUnits ?? DEFAULT_READING_WINDOW_LIMITS.maxMountedUnits),
  );
  const maxPinnedUnits = Math.max(
    0,
    Math.min(
      Math.floor(input?.maxPinnedUnits ?? DEFAULT_READING_WINDOW_LIMITS.maxPinnedUnits),
      maxMountedUnits,
    ),
  );
  return { maxMountedUnits, maxPinnedUnits };
}

function isUsableUnit(unit: ReadingUnit | null | undefined): unit is ReadingUnit {
  return Boolean(unit && typeof unit.unit_id === "string" && unit.unit_id.length > 0);
}

/**
 * 合并双向加载过的 pages：按 unit_id 去重（首见胜出），再按 ordinal 稳定升序，
 * 保证跨章正文顺序连续、重复页不重复内容。
 */
export function mergeReadingUnitPages(
  pages: readonly StreamPage[] | null | undefined,
): ReadingUnit[] {
  const byId = new Map<string, ReadingUnit>();
  for (const page of pages ?? []) {
    for (const unit of page?.units ?? []) {
      if (!isUsableUnit(unit)) continue;
      if (!byId.has(unit.unit_id)) byId.set(unit.unit_id, unit);
    }
  }
  return [...byId.values()].sort((a, b) => a.ordinal - b.ordinal);
}

export interface ReadingChapterHeading {
  readonly unit_id: string;
  readonly ordinal: number;
  readonly chapter_id: string;
  readonly chapter_title: string | null;
}

/**
 * 只在章边界（首段或 chapter_id 变化）产出标题；章内段落不重复标题。
 * 标题来自调用方提供的 publication-owned 映射，组件不猜标题。
 */
export function readingChapterHeadings(
  units: readonly ReadingUnit[],
  chapterTitles?: Readonly<Record<string, string | null>>,
): Readonly<Record<string, ReadingChapterHeading>> {
  const headings: Record<string, ReadingChapterHeading> = {};
  let previousChapter: string | null = null;
  for (const unit of units) {
    if (unit.chapter_id === previousChapter) continue;
    headings[unit.unit_id] = {
      unit_id: unit.unit_id,
      ordinal: unit.ordinal,
      chapter_id: unit.chapter_id,
      chapter_title: chapterTitles?.[unit.chapter_id] ?? null,
    };
    previousChapter = unit.chapter_id;
  }
  return headings;
}

export function estimateReadingUnitHeight(unit: ReadingUnit): number {
  const length = readingUnitText(unit).length;
  const lines = Math.max(1, Math.ceil(length / 28));
  return Math.max(ESTIMATED_READING_UNIT_HEIGHT, lines * 34 + 96);
}

export interface ReadingWindowPlaceholder {
  readonly unit_id: string;
  readonly ordinal: number;
  readonly height: number;
  /** true = 尚未测得，用估计值；false = 使用真实测量高度。 */
  readonly estimated: boolean;
}

export interface ReadingWindowPlan {
  readonly mountedUnitIds: readonly string[];
  readonly mountedUnits: readonly ReadingUnit[];
  readonly pinnedUnitIds: readonly string[];
  readonly overflowPinnedUnitIds: readonly string[];
  readonly evictedUnitIds: readonly string[];
  readonly placeholders: readonly ReadingWindowPlaceholder[];
  /** false 时窗口组件不再自动请求相邻页，只提供显式加载入口。 */
  readonly autoPrefetch: boolean;
  readonly requiresExplicitLoad: boolean;
}

export interface ReadingWindowPlanInput {
  readonly units: readonly ReadingUnit[];
  readonly activeUnitId?: string | null;
  readonly pinnedUnitIds?: readonly string[];
  readonly placeholderHeights?: Readonly<Record<string, number>>;
  readonly limits?: Partial<ReadingWindowLimits>;
}

function dedupeStrings(values: readonly string[] | null | undefined): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values ?? []) {
    if (typeof value !== "string" || value.length === 0 || seen.has(value)) continue;
    seen.add(value);
    out.push(value);
  }
  return out;
}

/**
 * 规划本帧实际渲染的 unit 与占位区：
 *  - 总量不超过 maxMountedUnits 时全部渲染；
 *  - 超出时保留 active、最多 maxPinnedUnits 个固定单位，再按 ordinal 距离补齐；
 *  - 被移除的已测得单位输出精确占位高度，未测得的用估计值；
 *  - 一旦发生回收或固定单位溢出，停止自动预取并给出显式加载入口。
 */
export function planReadingWindow(input: ReadingWindowPlanInput): ReadingWindowPlan {
  const limits = resolveReadingWindowLimits(input.limits);
  const units = [...(input.units ?? [])].sort((a, b) => a.ordinal - b.ordinal);
  const heights = input.placeholderHeights ?? {};

  if (units.length === 0) {
    return {
      mountedUnitIds: [],
      mountedUnits: [],
      pinnedUnitIds: [],
      overflowPinnedUnitIds: [],
      evictedUnitIds: [],
      placeholders: [],
      autoPrefetch: true,
      requiresExplicitLoad: false,
    };
  }

  const presentIds = new Set(units.map((unit) => unit.unit_id));
  const requestedPinned = dedupeStrings(input.pinnedUnitIds).filter((id) => presentIds.has(id));
  const pinnedUnitIds = requestedPinned.slice(0, limits.maxPinnedUnits);
  const overflowPinnedUnitIds = requestedPinned.slice(limits.maxPinnedUnits);

  const activeUnitId =
    input.activeUnitId && presentIds.has(input.activeUnitId)
      ? input.activeUnitId
      : units[0].unit_id;

  const selected = new Set<string>([activeUnitId, ...pinnedUnitIds]);
  let truncated = false;

  if (units.length <= limits.maxMountedUnits) {
    for (const unit of units) selected.add(unit.unit_id);
  } else {
    truncated = true;
    const activeOrdinal = units.find((unit) => unit.unit_id === activeUnitId)?.ordinal ?? units[0].ordinal;
    const candidates = units
      .filter((unit) => !selected.has(unit.unit_id))
      .sort((a, b) => {
        const distanceA = Math.abs(a.ordinal - activeOrdinal);
        const distanceB = Math.abs(b.ordinal - activeOrdinal);
        if (distanceA !== distanceB) return distanceA - distanceB;
        return a.ordinal - b.ordinal;
      });
    for (const unit of candidates) {
      if (selected.size >= limits.maxMountedUnits) break;
      selected.add(unit.unit_id);
    }
  }

  const mountedUnits = units.filter((unit) => selected.has(unit.unit_id));
  const evictedUnits = units.filter((unit) => !selected.has(unit.unit_id));
  const placeholders: ReadingWindowPlaceholder[] = evictedUnits.map((unit) => {
    const measured = heights[unit.unit_id];
    const hasMeasured = typeof measured === "number" && Number.isFinite(measured) && measured > 0;
    return {
      unit_id: unit.unit_id,
      ordinal: unit.ordinal,
      height: hasMeasured ? Math.round(measured) : estimateReadingUnitHeight(unit),
      estimated: !hasMeasured,
    };
  });

  const requiresExplicitLoad = truncated || overflowPinnedUnitIds.length > 0;
  return {
    mountedUnitIds: mountedUnits.map((unit) => unit.unit_id),
    mountedUnits,
    pinnedUnitIds,
    overflowPinnedUnitIds,
    evictedUnitIds: evictedUnits.map((unit) => unit.unit_id),
    placeholders,
    autoPrefetch: !requiresExplicitLoad,
    requiresExplicitLoad,
  };
}

/**
 * 记录测得高度。相同高度返回原对象，避免 ResizeObserver 触发无意义重渲染。
 */
export function applyMeasuredHeight(
  heights: Readonly<Record<string, number>> | null | undefined,
  unitId: string,
  height: number,
): Readonly<Record<string, number>> {
  const current = heights ?? {};
  if (!unitId || !Number.isFinite(height) || height <= 0) return current;
  const rounded = Math.round(height);
  if (current[unitId] === rounded) return current;
  return { ...current, [unitId]: rounded };
}
