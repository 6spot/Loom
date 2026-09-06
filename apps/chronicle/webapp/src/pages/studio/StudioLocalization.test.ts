import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  decisionLabel,
  jobStatusLabel,
  reviewLinkKindLabel,
  reviewStatusLabel,
  stageLabel,
} from "../../lib/studio-i18n";

const STUDIO_DIR = new URL(".", import.meta.url);

function source(name: string): string {
  return readFileSync(join(STUDIO_DIR.pathname, name), "utf8");
}

describe("Studio zh-CN operator surface", () => {
  it("centralizes human labels without changing stable backend enums", () => {
    expect(jobStatusLabel("needs_review")).toBe("等待人工审核");
    expect(reviewStatusLabel("open")).toBe("待处理");
    expect(reviewLinkKindLabel("entity")).toBe("实体身份");
    expect(decisionLabel("same_occurrence")).toBe("同一次事件");
    expect(decisionLabel("uncertain")).toBe("证据不足，暂不确定");
    expect(stageLabel("resolve")).toBe("跨来源消歧");
  });

  it("does not regress core navigation/review/import paths to English primary labels", () => {
    const files = [
      "StudioLayout.tsx",
      "StudioHomePage.tsx",
      "StudioImportsPage.tsx",
      "StudioImportDetailPage.tsx",
      "StudioReviewPage.tsx",
      "StudioReviewDetailPage.tsx",
      "StudioSourcesPage.tsx",
      "StudioCoveragePage.tsx",
      "StudioLoginPage.tsx",
      "placeholders.tsx",
    ];
    const combined = files.map(source).join("\n");
    const forbidden = [
      ">Imports<",
      ">Review<",
      ">Sources / Corpus<",
      ">Coverage<",
      ">Retry<",
      ">Resume<",
      ">Cancel<",
      "<h1>Review Queue</h1>",
      "<CardTitle>Resolution reviews</CardTitle>",
      "Current stage",
      "Failed chunks",
      "Open reviews",
      "Review debt",
      "Documents & Imports",
      "Upload Revision",
      "Revision history",
      "Ingestion Jobs",
      "Source contribution",
      "Actionable gaps",
    ];
    for (const text of forbidden) expect(combined).not.toContain(text);
  });

  it("keeps grouped review debt visible as one semantic subject", () => {
    const queue = source("StudioReviewPage.tsx");
    const detail = source("StudioReviewDetailPage.tsx");
    expect(queue).toContain("底层候选");
    expect(detail).toContain("一个判断会确定性应用到该主题中的全部底层候选");
  });
});
