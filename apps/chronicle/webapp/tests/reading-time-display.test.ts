// C2-R2-T11 阅读时间轴纯展示模型单元测试。
//
// 覆盖 continuous-reading.md §3 的显示纪律：同年共享年标题、同月跨页只一个
// 语义区段、未知不继承上次日期、来源/公历/近似/分歧标签不混淆、倒叙只标记
// 不重排、点击 locator 精确。全部为 synthetic fixture，不冒充真实史料。

import { describe, expect, it } from "vitest";
import type { ReadingLocator, TimeGroup, TimeObservation, TimePrecision } from "../src/lib/reading-types";
import {
  axisBasisLabel,
  axisNavigationLocator,
  axisPeriodLabel,
  axisPrecisionLabel,
  axisTimeBasis,
  axisYearLabel,
  buildAxisModel,
  groupObservedYear,
  isUnknownTime,
  observationYear,
  sameAxisSection,
} from "../src/lib/reading-time-display";

const STREAM = "0192f0a0-0000-7000-8000-00000000aa01";
const CATALOG = "4c29947197b9be1907082482c45d724a4dd4216a9db18f9f6ba55b9085597401";

function locator(n: number): ReadingLocator {
  return { stream_id: STREAM, catalog_sha: CATALOG, unit_id: `ru_${n.toString(16).padStart(24, "0")}` };
}

interface ObservationSpec {
  original: string;
  system?: "chinese_lunisolar_regnal" | "proleptic_gregorian" | "unknown";
  era?: string | null;
  era_year?: number | null;
  month?: number | null;
  normalized?: { year?: number | null; month?: number | null; approximate?: boolean; conversion_status?: string; calendar?: "proleptic_gregorian" } | null;
  precision?: TimePrecision;
}

function observation(spec: ObservationSpec): TimeObservation {
  const system = spec.system ?? "chinese_lunisolar_regnal";
  return {
    event_ref: null,
    original_text: spec.original,
    source_calendar:
      system === "unknown"
        ? null
        : { system, era: spec.era ?? null, era_year: spec.era_year ?? null, month: spec.month ?? null, day: null },
    normalized: spec.normalized
      ? {
          calendar: spec.normalized.calendar ?? "proleptic_gregorian",
          year: spec.normalized.year ?? null,
          month: spec.normalized.month ?? null,
          day: null,
          precision: (spec.precision ?? "year") === "unknown" ? "unknown" : "year",
          conversion_status:
            (spec.normalized.conversion_status as "exact" | "year_only" | "partial" | "unresolved" | undefined) ??
            "exact",
          approximate: spec.normalized.approximate ?? false,
        }
      : null,
    precision: spec.precision ?? "month",
  };
}

interface GroupSpec {
  id: string;
  yearKey: string;
  periodKey: string;
  yearLabel: string | null;
  periodLabel: string;
  precision: TimePrecision;
  observations: TimeObservation[];
  continuesPrevious?: boolean;
  unitCount?: number;
  ordinal?: number;
}

function group(spec: GroupSpec): TimeGroup {
  const ordinal = spec.ordinal ?? 0;
  const unitCount = spec.unitCount ?? 1;
  return {
    group_id: spec.id,
    ordinal,
    year_key: spec.yearKey,
    period_key: spec.periodKey,
    year_label: spec.yearLabel,
    period_label: spec.periodLabel,
    precision: spec.precision,
    observations: spec.observations,
    continues_previous: spec.continuesPrevious ?? false,
    first_locator: locator(ordinal * 10 + 1),
    last_locator: locator(ordinal * 10 + unitCount),
    unit_count: unitCount,
  };
}

const regnal = (eraYear: number, month: number | null, text: string) =>
  observation({ original: text, system: "chinese_lunisolar_regnal", era: "建安", era_year: eraYear, month });
const gregorian = (year: number, month: number | null, text: string) =>
  observation({
    original: text,
    system: "proleptic_gregorian",
    normalized: { year, month },
    precision: month === null ? "year" : "month",
  });

describe("reading-time-display: 年/月层级", () => {
  const groups: TimeGroup[] = [
    group({
      id: "tg_1",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:8",
      yearLabel: "建安十三年",
      periodLabel: "史料八月",
      precision: "month",
      observations: [regnal(13, 8, "八月")],
      unitCount: 2,
      ordinal: 0,
    }),
    group({
      id: "tg_2",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:9",
      yearLabel: "建安十三年",
      periodLabel: "史料九月",
      precision: "month",
      observations: [regnal(13, 9, "九月")],
      continuesPrevious: true,
      ordinal: 1,
    }),
    group({
      id: "tg_3",
      yearKey: "regnal:建安:14",
      periodKey: "regnal:建安:14:year",
      yearLabel: "建安14年",
      periodLabel: "（月份未明确）",
      precision: "year",
      observations: [regnal(14, null, "十四年")],
      ordinal: 2,
    }),
  ];

  it("同年区段只在第一次显示年标题，换月只新增月标记", () => {
    const model = buildAxisModel(groups, null);
    expect(model.entries.map((entry) => entry.showYearHeader)).toEqual([true, false, true]);
    expect(model.entries.map((entry) => entry.showPeriodHeader)).toEqual([true, true, true]);
    expect(model.knownYearCount).toBe(3);
  });

  it("同月跨页（同年同标记）只算一个语义区段，不重印年/月标题", () => {
    const continued = group({
      id: "tg_page2",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:9",
      yearLabel: "建安十三年",
      periodLabel: "史料九月",
      precision: "month",
      observations: [regnal(13, 9, "九月")],
      continuesPrevious: true,
      ordinal: 3,
    });
    expect(sameAxisSection(groups[1], continued)).toBe(true);
    const model = buildAxisModel([groups[0], groups[1], continued], null);
    const entry = model.entries[2];
    expect(entry.isContinuation).toBe(true);
    expect(entry.showYearHeader).toBe(false);
    expect(entry.showPeriodHeader).toBe(false);
  });

  it("未知区段不继承上次日期，后续已知区段重新显示年标题", () => {
    const unknown = group({
      id: "tg_unknown",
      yearKey: "unknown",
      periodKey: "unknown",
      yearLabel: "时间未明确",
      periodLabel: "时间未明确",
      precision: "unknown",
      observations: [],
      ordinal: 3,
    });
    const laterKnown = group({
      id: "tg_later",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:10",
      yearLabel: "建安十三年",
      periodLabel: "史料十月",
      precision: "month",
      observations: [regnal(13, 10, "十月")],
      ordinal: 4,
    });
    const model = buildAxisModel([groups[0], unknown, laterKnown], null);
    expect(model.entries[1].isUnknown).toBe(true);
    expect(model.entries[1].showYearHeader).toBe(false);
    expect(model.entries[1].showPeriodHeader).toBe(true);
    expect(axisYearLabel(unknown)).toBeNull();
    expect(axisPeriodLabel(unknown)).toBe("时间未明确");
    expect(model.entries[2].showYearHeader).toBe(true);
    expect(model.unknownCount).toBe(1);
  });
});

describe("reading-time-display: 历法与精度标签", () => {
  it("史料历月与公历月分属不同基准，标签不混淆", () => {
    const sourceGroup = group({
      id: "tg_source",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:8",
      yearLabel: "建安十三年",
      periodLabel: "史料八月",
      precision: "month",
      observations: [regnal(13, 8, "八月")],
    });
    const gregorianGroup = group({
      id: "tg_gregorian",
      yearKey: "gregorian:208",
      periodKey: "gregorian:208:8",
      yearLabel: null,
      periodLabel: "公元208年8月",
      precision: "month",
      observations: [gregorian(208, 8, "公元208年8月")],
    });
    expect(axisTimeBasis(sourceGroup)).toBe("source");
    expect(axisTimeBasis(gregorianGroup)).toBe("gregorian");
    expect(axisBasisLabel(axisTimeBasis(sourceGroup))).toBe("来源历法");
    expect(axisBasisLabel(axisTimeBasis(gregorianGroup))).toBe("公历");
    expect(axisPeriodLabel(sourceGroup)).not.toContain("公历");
  });

  it("近似、年段、多源与未知使用各自的固定精度标签", () => {
    const precisionCases: Array<[TimePrecision, string]> = [
      ["approximate", "近似"],
      ["range", "年段"],
      ["mixed", "多源"],
      ["unknown", "时间未明确"],
    ];
    for (const [precision, label] of precisionCases) {
      const spec = group({
        id: `tg_${precision}`,
        yearKey: precision === "unknown" ? "unknown" : "gregorian:208",
        periodKey: precision === "unknown" ? "unknown" : `gregorian:208:${precision}`,
        yearLabel: precision === "unknown" ? null : "公元208年",
        periodLabel: label,
        precision,
        observations: [gregorian(208, null, "约208年")],
      });
      expect(axisPrecisionLabel(spec)).toBe(label);
    }
    expect(isUnknownTime(group({
      id: "tg_opaque",
      yearKey: "regnal:建安:13",
      periodKey: "opaque:閏八月",
      yearLabel: "建安十三年",
      periodLabel: "閏八月（原始历法）",
      precision: "month",
      observations: [regnal(13, null, "閏八月")],
    }))).toBe(false);
  });

  it("单一确定年份可比较，多来源分歧或近似不伪造范围", () => {
    const exact = group({
      id: "tg_exact",
      yearKey: "gregorian:208",
      periodKey: "gregorian:208:year",
      yearLabel: "公元208年",
      periodLabel: "公元208年",
      precision: "year",
      observations: [gregorian(208, null, "208年")],
    });
    expect(groupObservedYear(exact)).toBe(208);

    const approximate = group({
      id: "tg_approx",
      yearKey: "gregorian:208",
      periodKey: "gregorian:208:approx",
      yearLabel: null,
      periodLabel: "约208年",
      precision: "approximate",
      observations: [
        observation({
          original: "约208年",
          system: "proleptic_gregorian",
          normalized: { year: 208, approximate: true },
          precision: "approximate",
        }),
      ],
    });
    expect(observationYear(approximate.observations[0])).toBeNull();
    expect(groupObservedYear(approximate)).toBeNull();

    const divergent = group({
      id: "tg_divergent",
      yearKey: "mixed:2",
      periodKey: "mixed:2",
      yearLabel: null,
      periodLabel: "208 或 209 年（分歧）",
      precision: "mixed",
      observations: [gregorian(208, null, "208年"), gregorian(209, null, "209年")],
    });
    expect(groupObservedYear(divergent)).toBeNull();
  });
});

describe("reading-time-display: 倒叙与导航", () => {
  it("叙事顺序不变，仅把较早年份标记为倒叙", () => {
    const later = group({
      id: "tg_208",
      yearKey: "gregorian:208",
      periodKey: "gregorian:208:year",
      yearLabel: "公元208年",
      periodLabel: "公元208年",
      precision: "year",
      observations: [gregorian(208, null, "208年")],
      ordinal: 0,
    });
    const earlier = group({
      id: "tg_205",
      yearKey: "gregorian:205",
      periodKey: "gregorian:205:year",
      yearLabel: "公元205年",
      periodLabel: "公元205年",
      precision: "year",
      observations: [gregorian(205, null, "205年")],
      ordinal: 1,
    });
    const model = buildAxisModel([later, earlier], null);
    expect(model.entries.map((entry) => entry.isRetrospective)).toEqual([false, true]);
    expect(model.entries.map((entry) => entry.group.group_id)).toEqual(["tg_208", "tg_205"]);
  });

  it("点击区段发出精确 locator，而不是年份", () => {
    const target = group({
      id: "tg_target",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:8",
      yearLabel: "建安十三年",
      periodLabel: "史料八月",
      precision: "month",
      observations: [regnal(13, 8, "八月")],
      ordinal: 2,
    });
    const nav = axisNavigationLocator(target);
    expect(nav).toEqual(target.first_locator);
    expect(nav.unit_id).toBe("ru_000000000000000000000015");
    expect(nav.catalog_sha).toBe(CATALOG);
  });

  it("activeGroup 命中对应区段，空输入安全", () => {
    const g1 = group({ id: "tg_a", yearKey: "unknown", periodKey: "unknown", yearLabel: null, periodLabel: "时间未明确", precision: "unknown", observations: [], ordinal: 0 });
    const g2 = group({ id: "tg_b", yearKey: "unknown", periodKey: "unknown", yearLabel: null, periodLabel: "时间未明确", precision: "unknown", observations: [], ordinal: 1 });
    const model = buildAxisModel([g1, g2], "tg_b");
    expect(model.activeIndex).toBe(1);
    expect(model.entries[1].isActive).toBe(true);
    expect(model.entries[0].isActive).toBe(false);

    const empty = buildAxisModel([], null);
    expect(empty.entries).toHaveLength(0);
    expect(empty.activeIndex).toBe(-1);
  });
});
