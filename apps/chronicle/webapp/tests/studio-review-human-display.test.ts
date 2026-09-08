import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  comparisonRows,
  decisionLabel,
  formatReviewTime,
  signalLabel,
} from "../src/lib/review-display";
import type { HumanReviewContext } from "../src/lib/review-display";

const HERE = dirname(fileURLToPath(import.meta.url));

function eventContext(
  bundle: string,
  title: string,
  participantNames: string[],
  placeNames: string[],
): HumanReviewContext {
  return {
    bundle,
    ref: `${bundle}-evt`,
    source_title: bundle === "left" ? "武帝纪" : "先主传",
    record: { kind: "event", type: "battle", title },
    display: {
      kind: "event",
      type: "battle",
      name: title,
      time: {
        original_text: "是岁",
        era: "建安",
        era_year: 13,
        normalized_year: 208,
        approximate: true,
      },
      participants: participantNames.map((name, index) => ({ ref: `ent_${index}`, name, type: "person" })),
      places: placeNames.map((name, index) => ({ ref: `place_${index}`, name, type: "place" })),
      evidence: [
        {
          claim_ref: "clm_001",
          text: "与曹公战于赤壁，大破之",
          locator: { work: "三国志", chapter: "蜀书·先主传", paragraph: "1" },
        },
      ],
    },
  };
}

describe("R15/R19 human-decidable Studio review display", () => {
  it("keeps stable decision enums but renders the primary choices in Chinese", () => {
    expect(decisionLabel("same_occurrence")).toBe("同一次事件");
    expect(decisionLabel("related_occurrence")).toBe("有关联，但不是同一次事件");
    expect(decisionLabel("uncertain")).toBe("证据不足，暂不确定");
    expect(signalLabel("shared participants: 周瑜, 程普")).toBe("共同参与者：周瑜, 程普");
  });

  it("renders historical time and human-readable overlap instead of temp IDs", () => {
    expect(formatReviewTime({
      original_text: "是岁",
      era: "建安",
      era_year: 13,
      normalized_year: 208,
      approximate: true,
    })).toBe("原文：是岁 · 建安十三年 · 约公元208年");

    const rows = comparisonRows(
      "event",
      eventContext("left", "赤壁之战", ["周瑜", "程普", "刘备"], ["赤壁"]),
      eventContext("right", "赤壁之战", ["周瑜", "程普", "曹操"], ["赤壁"]),
    );
    expect(rows.find((row) => row.label === "参与者")?.result).toBe("共同：周瑜、程普");
    expect(rows.find((row) => row.label === "地点")?.result).toBe("共同：赤壁");
    expect(JSON.stringify(rows)).not.toContain("ent_");
  });

  it("keeps raw audit data behind technical details and removes English primary headings", () => {
    const page = readFileSync(
      resolve(HERE, "../src/pages/studio/StudioReviewDetailPage.tsx"),
      "utf8",
    );
    expect(page).toContain("来源逐字证据");
    expect(page).toContain("技术详情 / 审计字段");
    expect(page).toContain("系统初始建议");
    expect(page).toContain("你的人工判断");
    expect(page).not.toContain("Original suggestion");
    expect(page).not.toContain("Administrator decision");
    expect(page).not.toContain("Decision confidence");
  });

  it("makes review batching non-authoritative and exposes explicit per-group exceptions", () => {
    const page = readFileSync(
      resolve(HERE, "../src/pages/studio/StudioReviewDetailPage.tsx"),
      "utf8",
    );
    expect(page).toContain("重复问题已整理为审核批次");
    expect(page).toContain("批次只是把指向同一个已发布身份或事件的问题集中展示");
    expect(page).toContain("存在例外，展开逐组判断");
    expect(page).toContain("此组使用不同判断");
    expect(page).toContain("逐组例外判断");
  });
});
