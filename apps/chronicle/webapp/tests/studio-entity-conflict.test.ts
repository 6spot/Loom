import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StudioApiError } from "../src/lib/studio-api";
import type { CanonicalIdentityConflictDetails } from "../src/lib/studio-api";
import type { HumanReviewContext } from "../src/lib/review-display";
import { CanonicalIdentityConflictNotice } from "../src/pages/studio/StudioReviewDetailPage";

function context(bundle: string, ref: string, source: string): HumanReviewContext {
  return {
    bundle, ref, source_title: source, record: { kind: "entity", name: "襄阳" },
    display: {
      kind: "entity", name: "襄阳", evidence: [{
        claim_ref: "clm_evidence", text: "軍次襄陽。", locator: { work: "三国志", chapter: source },
      }],
    },
  };
}

function conflictDetails(): CanonicalIdentityConflictDetails {
  const incoming = context("c1rev-r19", "ent_000044", "本次文献");
  return {
    review_id: "review-b", canonical_ids: ["canonical-a", "canonical-b"],
    canonical_entities: [
      { canonical_id: "canonical-a", names: ["襄阳"], contexts: [context("wudi", "ent_013", "武帝纪")] },
      { canonical_id: "canonical-b", names: ["襄阳"], contexts: [context("wuzhu", "ent_030", "吴主传")] },
    ],
    review_group_ids: ["group-conflicting"],
    candidate_keys: ["artifact-a:candidate-a", "artifact-b:candidate-b"],
    proposed_candidate_keys: ["artifact-b:candidate-b"],
    incoming_refs: [{ bundle: incoming.bundle, ref: incoming.ref }],
    incoming_contexts: [incoming],
    published_refs: [
      { bundle: "wudi", ref: "ent_013", canonical_id: "canonical-a" },
      { bundle: "wuzhu", ref: "ent_030", canonical_id: "canonical-b" },
    ],
    review_groups: [{
      review_group_id: "group-conflicting", candidate_keys: ["artifact-b:candidate-b"],
      incoming_refs: [{ bundle: incoming.bundle, ref: incoming.ref }], right_contexts: [incoming],
    }],
  };
}

describe("R19 Studio conflict guidance", () => {
  it("renders Chinese corrective choices, both targets and only the conflicting group with exact evidence", () => {
    const details = conflictDetails();
    const markup = renderToStaticMarkup(createElement(CanonicalIdentityConflictNotice, {
      error: new StudioApiError(409, "canonical_identity_conflict", "不能提交", details),
      reviewGroups: [
        { review_group_id: "group-safe", member_count: 1, signals: [], right_contexts: [] },
        { review_group_id: "group-conflicting", member_count: 1, signals: [], right_contexts: [] },
      ],
    }));
    const visible = markup.replace(/<details\b[\s\S]*?<\/details>/g, "");
    expect(markup).toContain('role="alert"');
    expect(visible).toContain("该判断无法提交");
    expect(visible).toContain("本次判断未保存");
    expect(visible).toContain("襄阳（来源：武帝纪）");
    expect(visible).toContain("襄阳（来源：吴主传）");
    expect(visible).toContain("需调整的来源候选组 2：襄阳");
    expect(visible).not.toContain("来源候选组 1：");
    expect(visible).toContain("軍次襄陽。");
    expect(visible).toContain("不是同一实体");
    expect(visible).toContain("证据不足，暂不确定");
    for (const technical of ["canonical-a", "canonical-b", "group-conflicting", "ent_000044", "candidate-b"]) {
      expect(visible).not.toContain(technical);
      expect(markup).toContain(technical);
    }
    expect(markup).not.toContain("<button");
  });

  it("retains actionable guidance when an older error response has no display context", () => {
    const markup = renderToStaticMarkup(createElement(CanonicalIdentityConflictNotice, {
      error: new StudioApiError(409, "canonical_identity_conflict", "不能提交"),
    }));
    expect(markup).toContain("审核项仍待处理");
    expect(markup).toContain("请选择其中一个已发布实体");
    expect(markup).toContain("冲突技术详情 / 审计字段");
  });

  it("shows legacy candidate evidence without inventing a group ID or a name", () => {
    const details = conflictDetails();
    details.review_groups = [];
    details.review_group_ids = [];
    details.canonical_entities[0].names = [];
    const markup = renderToStaticMarkup(createElement(CanonicalIdentityConflictNotice, {
      error: new StudioApiError(409, "canonical_identity_conflict", "不能提交", details),
    }));
    const visible = markup.replace(/<details\b[\s\S]*?<\/details>/g, "");
    expect(visible).toContain("未命名实体");
    expect(visible).toContain("需调整的来源候选组：襄阳");
    expect(visible).toContain("軍次襄陽。");
    expect(visible).not.toContain("group-conflicting");
  });
});
