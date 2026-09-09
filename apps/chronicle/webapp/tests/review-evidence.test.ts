import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { evidenceRequestKey } from "../src/lib/studio-api";
import type { SourceContextDescriptor } from "../src/lib/studio-api";
import {
  evidenceChapterTitle,
  evidenceKindLabel,
  evidenceKindsLabel,
  evidenceRevisionLine,
  hasDirectClaimEvidence,
  isRenderableSegments,
  sourceFailureLabel,
  stagedSideLabel,
  unavailableReasonLabel,
} from "../src/lib/review-display";
import type { HumanReviewContext } from "../src/lib/review-display";
import { EvidenceSegments } from "../src/components/studio/ReviewEvidencePanel";

const HERE = dirname(fileURLToPath(import.meta.url));

function descriptor(overrides: Partial<SourceContextDescriptor> = {}): SourceContextDescriptor {
  return {
    context_id: "ctx_abc",
    bundle: "incoming",
    bundle_sha256: "b".repeat(64),
    record_ref: "ent_001",
    link_kind: "entity",
    job_id: "job-1",
    revision_id: "rev-1",
    chapter_id: "ch_01",
    chapter_index: 0,
    chapter_title: "先主传",
    artifact_sha256: "a".repeat(64),
    source_title: "三国志",
    source_sha256: "s".repeat(64),
    evidence_kinds: ["direct_claim", "mention"],
    available: true,
    unavailable_reason: null,
    anchor_count: 1,
    anchors: [{ anchor_id: "anc_1", chapter_id: "ch_01", start: 0, end: 3, quote_sha256: "q" }],
    ...overrides,
  };
}

describe("T12 review evidence display", () => {
  it("labels every evidence kind layer in Chinese", () => {
    expect(evidenceKindLabel("direct_claim")).toContain("事实声明");
    expect(evidenceKindLabel("mention")).toContain("出现");
    expect(evidenceKindLabel("record_source")).toContain("记录来源");
    expect(evidenceKindLabel("event_context")).toContain("事件");
    expect(evidenceKindLabel("translation")).toContain("译文");
    expect(evidenceKindsLabel(["direct_claim", "translation"])).toContain("译文");
  });

  it("keeps same text at different revisions distinct", () => {
    const left = evidenceRevisionLine(descriptor({ revision_id: "rev-1", source_sha256: "s".repeat(64) }));
    const right = evidenceRevisionLine(descriptor({ revision_id: "rev-2", source_sha256: "t".repeat(64) }));
    expect(left).not.toBe(right);
    expect(left).toContain("rev-1".slice(0, 12));
  });

  it("prefers chapter titles and never promotes an internal id to a title", () => {
    expect(evidenceChapterTitle(descriptor())).toBe("先主传");
    expect(evidenceChapterTitle(descriptor({ chapter_title: null, source_title: "三国志" }))).toBe("三国志");
    expect(evidenceChapterTitle(descriptor({ chapter_title: "", source_title: "" }))).toBe("未知章节");
  });

  it("explains unavailable sources while keeping the form path", () => {
    expect(unavailableReasonLabel("legacy_fixture_without_location")).toContain("原有直接引用证据不受影响");
    expect(unavailableReasonLabel("bundle_without_provenance")).toContain("原有直接引用证据不受影响");
    expect(sourceFailureLabel("source_mismatch")).toContain("source_mismatch");
    expect(sourceFailureLabel("source_mismatch")).toContain("保留");
    expect(sourceFailureLabel("source_unavailable")).toContain("保留");
  });

  it("marks both chapter_pair ends as staged, never published", () => {
    expect(stagedSideLabel("chapter_pair", "left")).toContain("staged");
    expect(stagedSideLabel("chapter_pair", "right")).toContain("staged");
    expect(stagedSideLabel("chapter_pair", "left")).not.toContain("已发布");
    expect(stagedSideLabel(null, "left")).toContain("已发布侧");
  });

  it("fixes the request key to review/plan/context/artifact", () => {
    const first = evidenceRequestKey("r1", "fp1", "ctx_a", "anc_a");
    expect(first).toBe("r1|fp1|ctx_a|anc_a");
    expect(evidenceRequestKey("r1", "fp2", "ctx_a", "anc_a")).not.toBe(first);
    expect(evidenceRequestKey("r1", "fp1", "ctx_b", "anc_a")).not.toBe(first);
    expect(evidenceRequestKey("r1", "fp1", "ctx_a", "anc_b")).not.toBe(first);
  });

  it("rejects malformed highlight segments before render", () => {
    expect(isRenderableSegments([{ text: "军次襄阳。", highlight: true }])).toBe(true);
    expect(isRenderableSegments([{ text: "军次襄阳。" }])).toBe(false);
    expect(isRenderableSegments("军次襄阳。")).toBe(false);
    expect(isRenderableSegments(null)).toBe(false);
  });

  it("renders server segments as plain text without executing embedded HTML", () => {
    const evil = '<img src=x onerror="alert(1)">军次襄阳<script>alert(2)</script>';
    const markup = renderToStaticMarkup(
      createElement(EvidenceSegments, {
        segments: [
          { text: evil, highlight: false },
          { text: " highlight ", highlight: true },
        ],
      }),
    );
    expect(markup).not.toContain("<img");
    expect(markup).not.toContain("<script");
    expect(markup).toContain("&lt;img");
    expect(markup).toContain("<mark");
  });

  it("detects records without direct claims for the record_source path", () => {
    const empty: HumanReviewContext = {
      bundle: "incoming", ref: "ent_9", source_title: "三国志",
      record: { kind: "entity", name: "无名氏" },
      display: { kind: "entity", name: "无名氏", evidence: [] },
    };
    expect(hasDirectClaimEvidence(empty)).toBe(false);
    const claimed: HumanReviewContext = {
      ...empty,
      display: {
        kind: "entity", name: "刘备",
        evidence: [{ claim_ref: "clm_1", text: "先主姓刘，讳备。", locator: {} }],
      },
    };
    expect(hasDirectClaimEvidence(claimed)).toBe(true);
  });

  it("wires the evidence section into the detail page without a second form", () => {
    const page = readFileSync(
      resolve(HERE, "../src/pages/studio/StudioReviewDetailPage.tsx"),
      "utf8",
    );
    expect(page).toContain("审核证据与来源");
    expect(page).toContain("ReviewEvidenceSection");
    expect(page).toContain("候选组");
    expect(page).toContain("逐组来源");
    expect(page).toContain("stagedSideLabel");
  });

  it("keeps the evidence styles scoped and leaves global styling untouched", () => {
    const css = readFileSync(resolve(HERE, "../src/styles/review-evidence.css"), "utf8");
    expect(css).toContain(".evidence-");
    expect(css).not.toContain(".studio-shell");
    const app = readFileSync(resolve(HERE, "../src/App.tsx"), "utf8");
    expect(app).toContain("review-evidence.css");
  });
});
