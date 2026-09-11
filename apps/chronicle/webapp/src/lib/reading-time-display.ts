// C2-R2-T11 侧边阅读时间轴的纯展示模型。
//
// 数据含义以 continuous-reading.md §3 为权威：时间分组由发布前的纯编译器计算，
// 浏览器只复用服务端 TimeGroups，不按年份重新归组、不生成补齐年月、不把传统历
// 八月显示成公历八月。本模块只做「显示哪些年/月标题、是否倒叙、用什么固定标签」
// 的纯函数推导，不持有 World 时间 authority，也不产生任何 canonical 身份。
//
// 轴体反映叙事顺序：函数只标记回溯，绝不按年份数字重排输入顺序。

import type {
  ReadingLocator,
  TimeGroup,
  TimeObservation,
  TimePrecision,
} from "./reading-types";

/** 服务端已固定的 unknown key；不得被附近已知日期覆盖。 */
export const AXIS_UNKNOWN_PERIOD_KEY = "unknown";
export const AXIS_UNKNOWN_YEAR_KEY = "unknown";

export type AxisTimeBasis = "source" | "gregorian" | "mixed" | "unknown";

export interface AxisEntry {
  readonly group: TimeGroup;
  readonly index: number;
  /** 是否在轴体上重印年标题；同年连续区段只印一次。 */
  readonly showYearHeader: boolean;
  /** 是否新建月/精度标记；同月跨页延续只印一次。 */
  readonly showPeriodHeader: boolean;
  /** 与上一区段同年同标记，仅作为延续并入既有轴体。 */
  readonly isContinuation: boolean;
  readonly isActive: boolean;
  readonly isRetrospective: boolean;
  readonly isUnknown: boolean;
  readonly basis: AxisTimeBasis;
  readonly precisionLabel: string;
  readonly ariaLabel: string;
}

export interface AxisModel {
  readonly entries: readonly AxisEntry[];
  /** active group 在输入中的下标；无 active 或未找到为 -1。 */
  readonly activeIndex: number;
  readonly activeGroupId: string | null;
  readonly unknownCount: number;
  readonly knownYearCount: number;
}

const PRECISION_LABELS: Readonly<Record<TimePrecision, string>> = {
  day: "日",
  month: "月",
  year: "年",
  range: "年段",
  mixed: "多源",
  unknown: "时间未明确",
  approximate: "近似",
};

const BASIS_LABELS: Readonly<Record<AxisTimeBasis, string | null>> = {
  source: "来源历法",
  gregorian: "公历",
  mixed: "多历法",
  unknown: null,
};

/** unknown 区段（整段未知）不得继承上一次已知日期。 */
export function isUnknownTime(group: TimeGroup): boolean {
  return (
    group.precision === "unknown" ||
    group.period_key === AXIS_UNKNOWN_PERIOD_KEY ||
    group.year_key === AXIS_UNKNOWN_YEAR_KEY
  );
}

/** 时间基准：区分来源历法、公历、多历法与未明确，标签不得混淆。 */
export function axisTimeBasis(group: TimeGroup): AxisTimeBasis {
  if (isUnknownTime(group)) return "unknown";
  const systems = new Set<"source" | "gregorian">();
  for (const observation of group.observations) {
    const system = observation.source_calendar?.system;
    if (system === "chinese_lunisolar_regnal") systems.add("source");
    else if (system === "proleptic_gregorian") systems.add("gregorian");
  }
  if (systems.size === 0) {
    for (const observation of group.observations) {
      if (observation.normalized?.calendar === "proleptic_gregorian") systems.add("gregorian");
    }
  }
  if (systems.has("source") && systems.has("gregorian")) return "mixed";
  if (systems.has("source")) return "source";
  if (systems.has("gregorian")) return "gregorian";
  return "unknown";
}

export function axisBasisLabel(basis: AxisTimeBasis): string | null {
  return BASIS_LABELS[basis];
}

/** 固定精度标签；mixed/approximate/range 不与精确年月混为一谈。 */
export function axisPrecisionLabel(group: TimeGroup): string {
  return PRECISION_LABELS[group.precision] ?? PRECISION_LABELS.unknown;
}

/** 只复用服务端编译的 year_label；unknown 区段没有年标题。 */
export function axisYearLabel(group: TimeGroup): string | null {
  if (isUnknownTime(group)) return null;
  return group.year_label ?? null;
}

/** 只复用服务端编译的 period_label，不补齐、不翻译日历。 */
export function axisPeriodLabel(group: TimeGroup): string {
  const label = group.period_label?.trim();
  return label && label.length > 0 ? group.period_label : "时间未明确";
}

/** 可用于叙事顺序比较的公历观察年；近似/未解析/多值不参与。 */
export function observationYear(observation: TimeObservation): number | null {
  const normalized = observation.normalized;
  if (!normalized) return null;
  if (normalized.calendar && normalized.calendar !== "proleptic_gregorian") return null;
  if (normalized.approximate === true) return null;
  if (normalized.conversion_status === "partial" || normalized.conversion_status === "unresolved") {
    return null;
  }
  const year = normalized.year;
  if (typeof year !== "number" || !Number.isInteger(year)) return null;
  return year;
}

/** 单一确定年份时返回该年；多来源分歧或缺失时返回 null，不合成范围。 */
export function groupObservedYear(group: TimeGroup): number | null {
  const years = new Set<number>();
  for (const observation of group.observations) {
    const year = observationYear(observation);
    if (year !== null) years.add(year);
  }
  return years.size === 1 ? [...years][0] : null;
}

/** 两个区段是否属于同一个年/月语义区段（同月跨页共享标记）。 */
export function sameAxisSection(previous: TimeGroup, current: TimeGroup): boolean {
  if (isUnknownTime(previous) || isUnknownTime(current)) return false;
  return previous.year_key === current.year_key && previous.period_key === current.period_key;
}

export function axisAriaLabel(group: TimeGroup, index: number): string {
  const parts = [`区段 ${index + 1}`];
  const year = axisYearLabel(group);
  if (year) parts.push(year);
  parts.push(axisPeriodLabel(group));
  if (group.continues_previous) parts.push("延续上一区段");
  parts.push(`共 ${group.unit_count} 段`);
  return parts.join("，");
}

/** 点击区段必须发出精确 locator（stream + catalog + unit），而不是年份。 */
export function axisNavigationLocator(group: TimeGroup): ReadingLocator {
  return group.first_locator;
}

/**
 * 把服务端 TimeGroups 转成轴体展示模型。输入顺序即叙事顺序，输出顺序不变。
 * 倒叙只做标记：已知公历观察年小于此前最大年时 isRetrospective=true。
 */
export function buildAxisModel(
  groups: readonly TimeGroup[],
  activeGroup: string | null,
): AxisModel {
  const entries: AxisEntry[] = [];
  let lastYearKey: string | null = null;
  let lastPeriodKey: string | null = null;
  let hasPrevious = false;
  let maxObservedYear: number | null = null;
  let activeIndex = -1;
  let unknownCount = 0;
  let knownYearCount = 0;

  groups.forEach((group, index) => {
    const unknown = isUnknownTime(group);
    const yearKey = unknown ? null : group.year_key;
    const previous = hasPrevious ? { yearKey: lastYearKey, periodKey: lastPeriodKey } : null;

    const sameSection =
      previous !== null &&
      yearKey !== null &&
      previous.yearKey === yearKey &&
      previous.periodKey === group.period_key;

    const showYearHeader = yearKey !== null && (previous === null || previous.yearKey !== yearKey);
    const showPeriodHeader = !sameSection;

    const observedYear = groupObservedYear(group);
    let retrospective = false;
    if (observedYear !== null) {
      if (maxObservedYear !== null && observedYear < maxObservedYear) retrospective = true;
      maxObservedYear = maxObservedYear === null ? observedYear : Math.max(maxObservedYear, observedYear);
    }

    const isActive = activeGroup !== null && group.group_id === activeGroup;
    if (isActive) activeIndex = index;

    entries.push({
      group,
      index,
      showYearHeader,
      showPeriodHeader,
      isContinuation: sameSection,
      isActive,
      isRetrospective: retrospective,
      isUnknown: unknown,
      basis: axisTimeBasis(group),
      precisionLabel: axisPrecisionLabel(group),
      ariaLabel: axisAriaLabel(group, index),
    });

    if (unknown) {
      unknownCount += 1;
      // 未知不继承上次日期：随后出现的已知区段必须重新显示年标题。
      lastYearKey = null;
    } else if (yearKey !== null) {
      lastYearKey = yearKey;
      knownYearCount += 1;
    }
    lastPeriodKey = group.period_key;
    hasPrevious = true;
  });

  return {
    entries,
    activeIndex,
    activeGroupId: activeGroup,
    unknownCount,
    knownYearCount,
  };
}
