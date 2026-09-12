// C2-R3-T12 章阶段依据审核显示/草稿 helper 单元测试（全部合成数据）。
//
// 覆盖 person-state-reading.md §5/§5.1 的审核纪律：评估按精确 candidate_key
// 覆盖；默认/例外草稿有明确类型；切换计划或审核项不沿用旧值；批量确认不建立
// 人物等价；提交 payload 只含合法的逐项例外；400/409/503/未知结果都保留草稿。

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Assessment, ReviewCandidate, ReviewPackage } from "../src/lib/person-state-types";
import {
  ASSESSMENT_LABELS,
  BATCH_SCOPE_NOTE,
  attributionLabel,
  batchConfirmDraft,
  buildAssessmentOverlay,
  candidateFlow,
  candidateValueText,
  coverageSummary,
  createDraft,
  dimensionLabel,
  dimensionScope,
  effectiveAssessment,
  groupCandidatesByPerson,
  isCandidateException,
  isDraftForReview,
  operationLabel,
  phaseBasisOrdinals,
  predictedEffectLabel,
  predictedEffectNote,
  qualificationLabel,
  qualificationNote,
  reasonCodesLabel,
  resolveDraft,
  reviewCoverage,
  sharedPhaseBasis,
  submitFailureMessage,
} from "../src/lib/person-state-review-display";
import PersonStateReviewPanel from "../src/components/studio/PersonStateReviewPanel";

const CATALOG = "a".repeat(64);
const PLAN = "b".repeat(64);

function key(seed: number): string {
  return `psc_${seed.toString(16).padStart(24, "0")}`;
}

function candidate(seed: number, overrides: Partial<ReviewCandidate> = {}): ReviewCandidate {
  return {
    candidate_key: key(seed),
    kind: "fact",
    chapter_id: "ch_0123456789abcdef01234567",
    item_ref: `pf_${seed}`,
    person_id: "0192f0a0-0000-7000-8000-00000000cc07",
    person_name: "周瑜",
    dimension: "office",
    value: "建威中郎將",
    relation: null,
    target: null,
    operation: "start",
    qualification: "ordinary",
    phase_refs: ["ph_001"],
    predicted_effect: "current",
    assessment_default: "uncertain",
    allowed_assessments: ["supported", "uncertain", "disputed", "rejected"],
    source_label: "周瑜傳",
    quote: "策授瑜建威中郎將",
    attribution: "narrator",
    reason_codes: [],
    ...overrides,
  };
}

function review(overrides: Partial<ReviewPackage> = {}): ReviewPackage {
  const candidates = overrides.candidates ?? [candidate(1)];
  return {
    schema: "chronicle.person-state-review",
    version: "0.1",
    review_id: "review_demo_1",
    plan_fingerprint: PLAN,
    scope: "person_state",
    review_mode: "chapter_state_evidence",
    chapter_id: "ch_0123456789abcdef01234567",
    catalog_sha: CATALOG,
    candidates,
    candidate_count: candidates.length,
    limit: 20,
    cursor: null,
    next_cursor: null,
    has_more: false,
    default_assessment: "uncertain",
    ...overrides,
  };
}

describe("labels", () => {
  it("labels every assessment and predicted effect in Chinese", () => {
    expect(assessmentLabelOf("supported")).toContain("支持");
    expect(ASSESSMENT_LABELS.uncertain).toContain("存疑");
    expect(ASSESSMENT_LABELS.rejected).toContain("拒绝");
    expect(predictedEffectLabel("current")).toBe("当前身份");
    expect(predictedEffectLabel("prior")).toContain("此前");
    expect(predictedEffectLabel("ended")).toContain("结束");
    expect(predictedEffectNote("current")).toContain("晚期在任");
    expect(predictedEffectNote("prior")).toContain("不代表延续");
  });

  it("keeps person and place dimensions separate", () => {
    expect(dimensionLabel("office")).toBe("官职");
    expect(dimensionLabel("control")).toBe("实际控制");
    expect(dimensionScope("office")).toBe("person");
    expect(dimensionScope("affiliation")).toBe("person");
    expect(dimensionScope("administration")).toBe("place");
    expect(dimensionScope("control")).toBe("place");
  });

  it("keeps qualifications and attribution as visible限定语", () => {
    expect(qualificationLabel("ordinary")).toBe("");
    expect(qualificationLabel("self_designation")).toBe("自称");
    expect(qualificationNote("self_designation")).toContain("不得省略");
    expect(qualificationNote("recommendation")).toContain("不建立生前当前任职");
    expect(qualificationNote("posthumous")).toContain("不建立生前当前任职");
    expect(attributionLabel("annotation")).toBe("注文");
    expect(operationLabel("attest")).toContain("仅证明");
    expect(reasonCodesLabel(["tenure_unproven", "source_disagreement"])).toBe("任期未明、来源分歧");
  });
});

function assessmentLabelOf(value: Assessment): string {
  return ASSESSMENT_LABELS[value];
}

describe("draft identity and per-candidate overrides", () => {
  it("creates a typed draft from the package defaults", () => {
    const draft = createDraft(review());
    expect(draft.planFingerprint).toBe(PLAN);
    expect(draft.defaultAssessment).toBe("uncertain");
    expect(draft.batchApplied).toBe(false);
    expect(draft.overrides).toEqual({});
    expect(draft.rationale).toBe("");
  });

  it("ignores a draft from another plan instead of carrying old values", () => {
    const stale = { ...createDraft(review()), planFingerprint: "c".repeat(64), defaultAssessment: "rejected" as Assessment };
    expect(isDraftForReview(review(), stale)).toBe(false);
    const resolved = resolveDraft(review(), stale);
    expect(resolved.planFingerprint).toBe(PLAN);
    expect(resolved.defaultAssessment).toBe("uncertain");
    expect(effectiveAssessment(candidate(1), resolved)).toBe("uncertain");
  });

  it("applies an override only to the exact candidate_key", () => {
    const a = candidate(1);
    const b = candidate(2, { assessment_default: "supported" });
    const draft = {
      ...createDraft(review()),
      overrides: { [a.candidate_key]: { assessment: "disputed" as Assessment, rationale: "来源分歧" } },
    };
    expect(effectiveAssessment(a, draft)).toBe("disputed");
    expect(effectiveAssessment(b, draft)).toBe("supported");
    expect(isCandidateException(a, draft)).toBe(true);
    expect(isCandidateException(b, draft)).toBe(false);
  });

  it("treats a rationale-only override as an exception", () => {
    const a = candidate(1);
    const draft = {
      ...createDraft(review()),
      defaultAssessment: "supported" as Assessment,
      overrides: { [a.candidate_key]: { assessment: "supported" as Assessment, rationale: "仅此来源" } },
    };
    expect(effectiveAssessment(a, draft)).toBe("supported");
    expect(isCandidateException(a, draft)).toBe(true);
  });

  it("falls back to the candidate default when the chosen value is not allowed", () => {
    const constrained = candidate(1, { allowed_assessments: ["uncertain", "rejected"], assessment_default: "rejected" });
    const draft = { ...createDraft(review()), defaultAssessment: "supported" as Assessment };
    expect(effectiveAssessment(constrained, draft)).toBe("rejected");
  });
});

describe("coverage and batch confirm", () => {
  const candidates = [
    candidate(1, { person_name: "周瑜", assessment_default: "supported" }),
    candidate(2, { person_name: "周瑜", assessment_default: "uncertain" }),
    candidate(3, { person_name: "劉備", assessment_default: "disputed" }),
  ];

  it("counts batch coverage against the real effective assessments", () => {
    const draft = resolveDraft(review({ candidates }), null);
    const coverage = reviewCoverage(candidates, draft);
    expect(coverage.total).toBe(3);
    expect(coverage.batchCovered).toBe(1);
    expect(coverage.exceptionCount).toBe(2);
    expect(coverageSummary(coverage)).toBe("批量覆盖 1 项，逐项例外 2 项（共 3 项）");
  });

  it("batch confirm covers every candidate without becoming a person merge", () => {
    const current = review({ candidates });
    const next = batchConfirmDraft(current, resolveDraft(current, null));
    expect(next.defaultAssessment).toBe("supported");
    expect(next.overrides).toEqual({});
    const coverage = reviewCoverage(candidates, next);
    expect(coverage.batchCovered).toBe(3);
    expect(coverage.exceptionCount).toBe(0);
    expect(BATCH_SCOPE_NOTE).toContain("不建立人物等价");
    expect(BATCH_SCOPE_NOTE).toContain("永久在任");
  });

  it("keeps overrides keyed precisely after a batch switch", () => {
    const current = review({ candidates });
    const afterBatch = batchConfirmDraft(current, resolveDraft(current, null));
    const withException = {
      ...afterBatch,
      overrides: { [key(2)]: { assessment: "rejected" as Assessment, rationale: "错主体" } },
    };
    expect(effectiveAssessment(candidates[0], withException)).toBe("supported");
    expect(effectiveAssessment(candidates[1], withException)).toBe("rejected");
    expect(effectiveAssessment(candidates[2], withException)).toBe("supported");
  });
});

describe("shared phase basis and person grouping", () => {
  it("groups candidates by exact shared phase refs and keeps stable ordinals", () => {
    const candidates = [
      candidate(1, { phase_refs: ["ph_001"] }),
      candidate(2, { phase_refs: ["ph_001"] }),
      candidate(3, { phase_refs: ["ph_002", "ph_003"] }),
    ];
    const groups = sharedPhaseBasis(candidates);
    expect(groups).toHaveLength(2);
    expect(groups[0].ordinal).toBe(1);
    expect(groups[0].phaseRefs).toEqual(["ph_001"]);
    expect(groups[0].candidateKeys).toEqual([key(1), key(2)]);
    expect(groups[1].ordinal).toBe(2);
    expect(groups[1].phaseRefs).toEqual(["ph_002", "ph_003"]);
    const ordinals = phaseBasisOrdinals(candidates);
    expect(ordinals.get(key(1))).toBe(1);
    expect(ordinals.get(key(3))).toBe(2);
  });

  it("groups the change chain per person and never by display name collision", () => {
    const candidates = [
      candidate(1, { person_id: "p1", person_name: "周瑜" }),
      candidate(2, { person_id: "p2", person_name: "周瑜" }),
      candidate(3, { person_id: null, person_name: null }),
    ];
    const groups = groupCandidatesByPerson(candidates);
    expect(groups).toHaveLength(3);
    expect(groups[0].personName).toBe("周瑜");
    expect(groups[1].personId).toBe("p2");
    expect(groups[2].personName).toBe("未指定人物");
  });
});

describe("submission overlay", () => {
  it("emits only exact candidate_key overrides that differ or carry a rationale", () => {
    const candidates = [candidate(1), candidate(2)];
    const current = review({ candidates });
    const draft = {
      ...resolveDraft(current, null),
      defaultAssessment: "supported" as Assessment,
      batchApplied: true,
      overrides: {
        [key(1)]: { assessment: "disputed" as Assessment, rationale: "分歧未决" },
        [key(2)]: { assessment: "supported" as Assessment, rationale: "" },
      },
      rationale: "本包说明",
    };
    const overlay = buildAssessmentOverlay(current, draft);
    expect(overlay.plan_fingerprint).toBe(PLAN);
    expect(overlay.default_assessment).toBe("supported");
    expect(overlay.overrides).toEqual([
      { candidate_key: key(1), assessment: "disputed", rationale: "分歧未决" },
    ]);
    expect(overlay.rationale).toBe("本包说明");
  });

  it("preserves each compiled baseline as an override before any bulk action", () => {
    const candidates = [
      candidate(1, { assessment_default: "supported" }),
      candidate(2, { assessment_default: "uncertain" }),
    ];
    const current = review({ candidates });
    const overlay = buildAssessmentOverlay(current, createDraft(current));
    // The plan default is uncertain; the supported candidate keeps its own
    // baseline as an explicit positive override instead of being washed out.
    expect(overlay.default_assessment).toBe("uncertain");
    expect(overlay.overrides).toEqual([
      { candidate_key: key(1), assessment: "supported", rationale: "" },
    ]);
  });

  it("builds an empty overlay from a mismatched draft", () => {
    const current = review();
    const stale = { ...createDraft(current), planFingerprint: "d".repeat(64), overrides: { [key(1)]: { assessment: "disputed" as Assessment, rationale: "x" } } };
    const overlay = buildAssessmentOverlay(current, stale);
    expect(overlay.plan_fingerprint).toBe(PLAN);
    expect(overlay.overrides).toEqual([]);
  });
});

describe("candidate presentation and failure guidance", () => {
  it("renders affiliation direction and end/attest flows", () => {
    const affiliation = candidate(4, { dimension: "affiliation", relation: "attached_to", target: "陶謙", value: null, operation: "start" });
    expect(candidateValueText(affiliation)).toBe("归附 陶謙");
    expect(candidateFlow(affiliation)).toEqual({ before: "—", after: "归附 陶謙" });
    const ended = candidate(5, { operation: "end" });
    expect(candidateFlow(ended)).toEqual({ before: "建威中郎將", after: "结束" });
  });

  it("explains 400/409/503/unknown outcomes and always retains the draft", () => {
    for (const status of [400, 409, 503]) {
      const message = submitFailureMessage({ status, message: "boom" });
      expect(message).toContain("草稿与已读来源已保留");
    }
    expect(submitFailureMessage({ status: 409 })).toContain("核对服务端记录");
    expect(submitFailureMessage({ status: 503 })).toContain("稍后重试");
    expect(submitFailureMessage(new Error("network down"))).toContain("无法确认提交结果");
  });
});

describe("panel rendering", () => {
  const candidates = [
    candidate(1, {
      qualification: "self_designation",
      reason_codes: ["tenure_unproven"],
      predicted_effect: "prior",
    }),
  ];
  const current = review({ candidates });
  const noop = () => undefined;

  it("keeps qualifiers, reasons and predictions visible, not inside technical details", () => {
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        review: current,
        draft: createDraft(current),
        onDraftChange: noop,
        onSubmit: async () => undefined,
        onSkip: noop,
        onReturn: noop,
      }),
    );
    expect(markup).toContain('data-test="psr-qualification"');
    expect(markup).toContain('data-test="psr-reasons"');
    expect(markup).toContain("自称");
    expect(markup).toContain("任期未明");
    expect(markup).toContain('data-test="psr-effect"');
    expect(markup).toContain("此前记载");
    expect(markup).toContain('data-test="psr-action-bar"');
    // Internal phase refs are audit-only.
    expect(markup).toContain("审计详情");
    expect(markup).not.toContain("<script");
  });

  it("mounts the optional read-only source slot without owning a loader", () => {
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        review: current,
        draft: createDraft(current),
        onDraftChange: noop,
        onSubmit: async () => undefined,
        onSkip: noop,
        onReturn: noop,
        renderSource: (candidate) => createElement("span", null, `来源槽 ${candidate.candidate_key}`),
      }),
    );
    expect(markup).toContain('data-test="psr-source-slot"');
    expect(markup).toContain("来源槽");
  });

  it("marks a mismatched draft and disables submit until the caller re-keys it", () => {
    const stale = { ...createDraft(current), planFingerprint: "e".repeat(64) };
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        review: current,
        draft: stale,
        onDraftChange: noop,
        onSubmit: async () => undefined,
        onSkip: noop,
        onReturn: noop,
      }),
    );
    expect(markup).toContain('data-test="psr-stale-draft"');
    expect(markup).toContain('data-test="psr-save-next"');
    expect(markup).toMatch(/data-test="psr-save-next"[^>]*disabled/);
  });
});
