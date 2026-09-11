import { describe, expect, it } from "vitest";
import { explicitTimelineYear, narrativeTimeLabel } from "../src/pages/public/ReadingPage";
import type { TimeObservation } from "../src/lib/reading-types";

function observation(overrides: Partial<TimeObservation>): TimeObservation {
  return {
    event_ref: "e1",
    original_text: "建安十三年",
    source_calendar: null,
    normalized: null,
    precision: "year",
    ...overrides,
  } as TimeObservation;
}

describe("reading page narrative time display", () => {
  it("shows server-compiled labels and keeps unknown literal", () => {
    expect(
      narrativeTimeLabel({ precision: "month", period_key: "p", year_label: "公元 208 年", period_label: "八月" }),
    ).toBe("公元 208 年 · 八月");
    expect(narrativeTimeLabel({ precision: "unknown", period_key: "unknown", period_label: "时间未明确" })).toBe(
      "时间未明确",
    );
    expect(narrativeTimeLabel(null)).toBe("时间未明确");
  });

  it("only offers a timeline year for one exact gregorian observation", () => {
    expect(
      explicitTimelineYear([
        observation({ normalized: { calendar: "proleptic_gregorian", year: 208, conversion_status: "exact" } }),
      ]),
    ).toBe(208);
    expect(
      explicitTimelineYear([
        observation({ normalized: { calendar: "proleptic_gregorian", year: 208, conversion_status: "exact" } }),
        observation({ normalized: { calendar: "proleptic_gregorian", year: 209, conversion_status: "exact" } }),
      ]),
    ).toBeNull();
    // 未换算传统历不得到达公历时间线。
    expect(explicitTimelineYear([observation({ source_calendar: { system: "chinese_lunisolar_regnal" } })])).toBeNull();
    // 近似/部分换算不是精确落点。
    expect(
      explicitTimelineYear([
        observation({ normalized: { calendar: "proleptic_gregorian", year: 208, approximate: true } }),
      ]),
    ).toBeNull();
    expect(explicitTimelineYear(undefined)).toBeNull();
  });
});
