import { describe, expect, it } from "vitest";
import { narrativeTimeLabel } from "../src/pages/public/ReadingPage";

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

});
