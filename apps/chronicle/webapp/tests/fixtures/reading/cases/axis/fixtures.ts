// C2-R2-T11 axis suite fixture 数据（仅测试使用，不进生产构建）。
//
// 全部为 synthetic published-DTO 形状样例，不是真实模型输出、不是真实后端响应，
// 也不是史料断言。时间分组字段（year_key/period_key/label/precision/observations）
// 假定已由发布前编译器算好，本 fixture 不重新归组。

import type { TimeGroup } from "../../../../../src/lib/reading-types";
import { READING_FIXTURE_SAMPLE_NOTE } from "../types";

export { READING_FIXTURE_SAMPLE_NOTE };

const STREAM = "0192f0a0-0000-7000-8000-00000000aa01";
const CATALOG = "4c29947197b9be1907082482c45d724a4dd4216a9db18f9f6ba55b9085597401";

function locator(ordinal: number): TimeGroup["first_locator"] {
  return {
    stream_id: STREAM,
    catalog_sha: CATALOG,
    unit_id: `ru_${ordinal.toString(16).padStart(24, "0")}`,
  };
}

function sourceObservation(
  ordinal: number,
  eraYear: number,
  month: number | null,
  original: string,
): TimeGroup["observations"][number] {
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

function gregorianObservation(
  year: number,
  month: number | null,
  original: string,
  options: { approximate?: boolean; precision?: TimeGroup["precision"] } = {},
): TimeGroup["observations"][number] {
  return {
    event_ref: null,
    original_text: original,
    source_calendar: {
      system: "proleptic_gregorian",
      era: null,
      era_year: null,
      season: null,
      month,
      day: null,
    },
    normalized: {
      calendar: "proleptic_gregorian",
      year,
      month,
      day: null,
      precision: month === null ? "year" : "month",
      conversion_status: options.approximate ? "partial" : "exact",
      approximate: options.approximate ?? false,
    },
    precision: options.precision ?? (month === null ? "year" : "month"),
  };
}

interface GroupSpec {
  readonly id: string;
  readonly yearKey: string;
  readonly periodKey: string;
  readonly yearLabel: string | null;
  readonly periodLabel: string;
  readonly precision: TimeGroup["precision"];
  readonly observations: TimeGroup["observations"];
  readonly continuesPrevious?: boolean;
  readonly unitCount?: number;
}

function group(spec: GroupSpec, ordinal: number): TimeGroup {
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

/** 同月共享标记 + 换月/换年 + 未知：年标题只出现 2 次。 */
export const HIERARCHY_GROUPS: TimeGroup[] = [
  group(
    {
      id: "tg_axis_h0",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:8",
      yearLabel: "建安十三年",
      periodLabel: "史料八月",
      precision: "month",
      observations: [sourceObservation(0, 13, 8, "十三年八月")],
      unitCount: 2,
    },
    0,
  ),
  group(
    {
      id: "tg_axis_h1",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:9",
      yearLabel: "建安十三年",
      periodLabel: "史料九月",
      precision: "month",
      observations: [sourceObservation(1, 13, 9, "其年九月")],
      continuesPrevious: true,
    },
    1,
  ),
  group(
    {
      id: "tg_axis_h2",
      yearKey: "regnal:建安:14",
      periodKey: "regnal:建安:14:year",
      yearLabel: "建安14年",
      periodLabel: "（月份未明确）",
      precision: "year",
      observations: [sourceObservation(2, 14, null, "十四年")],
    },
    2,
  ),
  group(
    {
      id: "tg_axis_h3",
      yearKey: "unknown",
      periodKey: "unknown",
      yearLabel: null,
      periodLabel: "时间未明确",
      precision: "unknown",
      observations: [],
    },
    3,
  ),
];

/** 来源历法 / 公历 / 近似 / 年段 / 多源 / 闰月 opaque，标签互不混淆。 */
export const CALENDAR_GROUPS: TimeGroup[] = [
  group(
    {
      id: "tg_axis_c0",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:8",
      yearLabel: "建安十三年",
      periodLabel: "史料八月",
      precision: "month",
      observations: [sourceObservation(0, 13, 8, "八月")],
    },
    0,
  ),
  group(
    {
      id: "tg_axis_c1",
      yearKey: "gregorian:208",
      periodKey: "gregorian:208:8",
      yearLabel: "公元208年",
      periodLabel: "公元208年8月",
      precision: "month",
      observations: [gregorianObservation(208, 8, "公元208年8月")],
    },
    1,
  ),
  group(
    {
      id: "tg_axis_c2",
      yearKey: "gregorian:208",
      periodKey: "gregorian:208:approximate",
      yearLabel: "约公元208年",
      periodLabel: "约208年",
      precision: "approximate",
      observations: [gregorianObservation(208, null, "约208年", { approximate: true, precision: "approximate" })],
    },
    2,
  ),
  group(
    {
      id: "tg_axis_c3",
      yearKey: "range:208-209",
      periodKey: "range:208-209",
      yearLabel: "公元208—209年",
      periodLabel: "公元208—209年",
      precision: "range",
      observations: [
        gregorianObservation(208, null, "208年", { precision: "range" }),
        gregorianObservation(209, null, "209年", { precision: "range" }),
      ],
    },
    3,
  ),
  group(
    {
      id: "tg_axis_c4",
      yearKey: "mixed:208|209",
      periodKey: "mixed:208|209",
      yearLabel: null,
      periodLabel: "208 或 209 年（来源分歧）",
      precision: "mixed",
      observations: [
        gregorianObservation(208, null, "208年", { precision: "mixed" }),
        gregorianObservation(209, null, "209年", { precision: "mixed" }),
      ],
    },
    4,
  ),
  group(
    {
      id: "tg_axis_c5",
      yearKey: "regnal:建安:13",
      periodKey: "opaque:閏八月",
      yearLabel: "建安十三年",
      periodLabel: "閏八月（原始历法，不换算）",
      precision: "month",
      observations: [sourceObservation(5, 13, null, "閏八月")],
    },
    5,
  ),
];

/** 倒叙：已知公历年份回退，只标记不重排；未知不影响最大年。 */
export const RETRO_GROUPS: TimeGroup[] = [
  group(
    {
      id: "tg_axis_r0",
      yearKey: "gregorian:208",
      periodKey: "gregorian:208:year",
      yearLabel: "公元208年",
      periodLabel: "公元208年",
      precision: "year",
      observations: [gregorianObservation(208, null, "建安十三年")],
    },
    0,
  ),
  group(
    {
      id: "tg_axis_r1",
      yearKey: "gregorian:205",
      periodKey: "gregorian:205:year",
      yearLabel: "公元205年",
      periodLabel: "公元205年",
      precision: "year",
      observations: [gregorianObservation(205, null, "建安十年")],
    },
    1,
  ),
  group(
    {
      id: "tg_axis_r2",
      yearKey: "unknown",
      periodKey: "unknown",
      yearLabel: null,
      periodLabel: "时间未明确",
      precision: "unknown",
      observations: [],
    },
    2,
  ),
  group(
    {
      id: "tg_axis_r3",
      yearKey: "gregorian:206",
      periodKey: "gregorian:206:year",
      yearLabel: "公元206年",
      periodLabel: "公元206年",
      precision: "year",
      observations: [gregorianObservation(206, null, "建安十一年")],
    },
    3,
  ),
];

/** 分页：page2 首段与 page1 末段同月，跨页只一个语义区段。 */
export const PAGINATION_PAGE1: TimeGroup[] = [
  group(
    {
      id: "tg_axis_p0",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:8",
      yearLabel: "建安十三年",
      periodLabel: "史料八月",
      precision: "month",
      observations: [sourceObservation(0, 13, 8, "八月")],
    },
    0,
  ),
  group(
    {
      id: "tg_axis_p1",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:9",
      yearLabel: "建安十三年",
      periodLabel: "史料九月",
      precision: "month",
      observations: [sourceObservation(1, 13, 9, "九月")],
    },
    1,
  ),
];

export const PAGINATION_PAGE2: TimeGroup[] = [
  group(
    {
      id: "tg_axis_p2",
      yearKey: "regnal:建安:13",
      periodKey: "regnal:建安:13:9",
      yearLabel: "建安十三年",
      periodLabel: "史料九月",
      precision: "month",
      observations: [sourceObservation(2, 13, 9, "九月")],
      continuesPrevious: true,
    },
    2,
  ),
  group(
    {
      id: "tg_axis_p3",
      yearKey: "regnal:建安:14",
      periodKey: "regnal:建安:14:year",
      yearLabel: "建安14年",
      periodLabel: "（月份未明确）",
      precision: "year",
      observations: [sourceObservation(3, 14, null, "十四年")],
    },
    3,
  ),
];

/** 1,000 个区段：验证长轴渲染与窄屏不横向溢出。 */
export function buildManyGroups(count = 1000): TimeGroup[] {
  const groups: TimeGroup[] = [];
  for (let index = 0; index < count; index += 1) {
    const year = index + 1;
    groups.push(
      group(
        {
          id: `tg_axis_many_${index}`,
          yearKey: `gregorian:${year}`,
          periodKey: `gregorian:${year}:year`,
          yearLabel: `公元${year}年`,
          periodLabel: `公元${year}年`,
          precision: "year",
          observations: [gregorianObservation(year, null, `${year}年`)],
        },
        index,
      ),
    );
  }
  return groups;
}

export const NOTE = READING_FIXTURE_SAMPLE_NOTE;
