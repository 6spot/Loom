// C2-R3-T12 章阶段依据审核显示/草稿 helper 单元测试（全部合成数据）。
//
// 覆盖 person-state-reading.md §5/§5.1 的审核纪律：未审与明确决定分开；评估按
// 精确 candidate_key 覆盖；默认/例外草稿有明确类型；切换计划或审核项不沿用旧值；
// 批量确认不建立人物等价；提交 payload 只含已审的逐项例外；400/409/503/未知结果
// 都保留草稿；分页未取全时 fail closed。

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Assessment, PhaseSummary, ReviewCandidate, ReviewPackage } from "../src/lib/person-state-types";
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
  hasUnreviewedRationale,
  isCandidateException,
  isCandidateReviewed,
  isDraftForReview,
  operationLabel,
  phaseBasisOrdinals,
  predictedEffectLabel,
  predictedEffectNote,
  qualificationLabel,
  qualificationNote,
  readableBasisEntry,
  reasonCodesLabel,
  resolveDraft,
  reviewCandidate,
  reviewCoverage,
  setCandidateRationale,
  sharedPhaseBasis,
  submitFailureMessage,
  unreviewCandidate,
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
    expect(ASSESSMENT_LABELS.supported).toContain("支持");
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

describe("draft identity and reviewed state", () => {
  it("creates a typed draft that starts completely 未审", () => {
    const draft = createDraft(review());
    expect(draft.planFingerprint).toBe(PLAN);
    expect(draft.defaultAssessment).toBe("uncertain");
    expect(draft.batchApplied).toBe(false);
    expect(draft.overrides).toEqual({});
    expect(draft.reviewed).toEqual({});
    expect(draft.rationale).toBe("");
  });

  it("ignores a draft from another plan instead of carrying old values", () => {
    const stale = { ...createDraft(review()), planFingerprint: "c".repeat(64), batchApplied: true };
    expect(isDraftForReview(review(), stale)).toBe(false);
    const resolved = resolveDraft(review(), stale);
    expect(resolved.planFingerprint).toBe(PLAN);
    expect(resolved.batchApplied).toBe(false);
    expect(effectiveAssessment(candidate(1), resolved)).toBeNull();
  });

  it("reports an untouched candidate as 未审, never as supported", () => {
    const a = candidate(1, { assessment_default: "supported" });
    const draft = createDraft(review({ candidates: [a] }));
    expect(isCandidateReviewed(a, draft)).toBe(false);
    expect(effectiveAssessment(a, draft)).toBeNull();
    expect(isCandidateException(a, draft)).toBe(false);
  });

  it("applies an explicit choice only to the exact candidate_key", () => {
    const a = candidate(1);
    const b = candidate(2);
    const draft = reviewCandidate(createDraft(review()), a, "disputed", "来源分歧");
    expect(isCandidateReviewed(a, draft)).toBe(true);
    expect(effectiveAssessment(a, draft)).toBe("disputed");
    expect(isCandidateException(a, draft)).toBe(true);
    expect(isCandidateReviewed(b, draft)).toBe(false);
    expect(effectiveAssessment(b, draft)).toBeNull();
  });

  it("distinguishes 未审 from 明确提交 uncertain", () => {
    const a = candidate(1, { assessment_default: "uncertain" });
    const untouched = createDraft(review({ candidates: [a] }));
    const decided = reviewCandidate(untouched, a, "uncertain");
    expect(effectiveAssessment(a, untouched)).toBeNull();
    expect(effectiveAssessment(a, decided)).toBe("uncertain");
    expect(isCandidateException(a, decided)).toBe(true);
    expect(coverageSummary(reviewCoverage([a], untouched))).toContain("未审 1 项");
    expect(coverageSummary(reviewCoverage([a], decided))).toContain("未审 0 项");
  });

  it("returns a candidate to 未审 and drops its override", () => {
    const a = candidate(1);
    const decided = reviewCandidate(createDraft(review()), a, "supported", "手动确认");
    const back = unreviewCandidate(decided, a);
    expect(isCandidateReviewed(a, back)).toBe(false);
    expect(effectiveAssessment(a, back)).toBeNull();
    expect(back.overrides[a.candidate_key]).toBeUndefined();
  });

  it("never marks a candidate reviewed from a rationale alone", () => {
    const a = candidate(1, { assessment_default: "supported" });
    const onlyRationale = setCandidateRationale(createDraft(review({ candidates: [a] })), a, "只是备注");
    expect(isCandidateReviewed(a, onlyRationale)).toBe(false);
    expect(effectiveAssessment(a, onlyRationale)).toBeNull();
    expect(hasUnreviewedRationale(a, onlyRationale)).toBe(true);
    expect(isCandidateException(a, onlyRationale)).toBe(false);
    const overlay = buildAssessmentOverlay(review({ candidates: [a] }), onlyRationale, [a]);
    expect(overlay.overrides).toEqual([]);
    // Choosing an assessment afterwards keeps the typed reason and marks已审.
    const decided = reviewCandidate(onlyRationale, a, "supported", onlyRationale.overrides[a.candidate_key].rationale);
    expect(isCandidateReviewed(a, decided)).toBe(true);
    expect(effectiveAssessment(a, decided)).toBe("supported");
    expect(hasUnreviewedRationale(a, decided)).toBe(false);
  });

  it("keeps the batch assessment when a reason is added to a batch-covered row", () => {
    const a = candidate(1, { assessment_default: "uncertain" });
    const batch = batchConfirmDraft(createDraft(review({ candidates: [a] })), [a]);
    const withReason = setCandidateRationale(batch, a, "补充说明");
    expect(effectiveAssessment(a, withReason)).toBe("supported");
    const overlay = buildAssessmentOverlay(review({ candidates: [a] }), withReason, [a]);
    expect(overlay.overrides).toEqual([
      { candidate_key: key(1), assessment: "supported", rationale: "补充说明" },
    ]);
  });

  it("falls back to the candidate default when the chosen value is not allowed", () => {
    const constrained = candidate(1, { allowed_assessments: ["uncertain", "rejected"], assessment_default: "rejected" });
    const draft = reviewCandidate(createDraft(review()), constrained, "supported");
    expect(effectiveAssessment(constrained, draft)).toBe("rejected");
  });
});

describe("coverage and batch confirm", () => {
  const candidates = [
    candidate(1, { person_name: "周瑜", assessment_default: "supported" }),
    candidate(2, { person_name: "周瑜", assessment_default: "uncertain" }),
    candidate(3, { person_name: "劉備", assessment_default: "disputed" }),
  ];

  it("starts with everything 未审 and nothing covered", () => {
    const coverage = reviewCoverage(candidates, resolveDraft(review({ candidates }), null));
    expect(coverage.total).toBe(3);
    expect(coverage.reviewed).toBe(0);
    expect(coverage.unreviewed).toBe(3);
    expect(coverage.batchCovered).toBe(0);
    expect(coverage.perItemSupported).toBe(0);
    expect(coverage.exceptionCount).toBe(0);
    expect(coverageSummary(coverage)).toBe(
      "已审 0 项（批量覆盖 0 项，逐项 supported 0 项，逐项例外 0 项）；未审 3 项（共 3 项）",
    );
  });

  it("counts only explicitly reviewed candidates and separates batch from per-item", () => {
    const current = review({ candidates });
    let draft = createDraft(current);
    draft = reviewCandidate(draft, candidates[0], "supported");
    draft = reviewCandidate(draft, candidates[1], "uncertain", "任期未明");
    const coverage = reviewCoverage(candidates, draft);
    expect(coverage.reviewed).toBe(2);
    expect(coverage.unreviewed).toBe(1);
    expect(coverage.batchCovered).toBe(0);
    expect(coverage.perItemSupported).toBe(1);
    expect(coverage.exceptionCount).toBe(1);
    expect(coverageSummary(coverage)).toBe(
      "已审 2 项（批量覆盖 0 项，逐项 supported 1 项，逐项例外 1 项）；未审 1 项（共 3 项）",
    );
  });

  it("keeps batch coverage separate from a per-item supported choice", () => {
    const current = review({ candidates });
    const batch = batchConfirmDraft(createDraft(current), candidates);
    expect(reviewCoverage(candidates, batch).batchCovered).toBe(3);
    const withPerItem = reviewCandidate(batch, candidates[0], "supported");
    const coverage = reviewCoverage(candidates, withPerItem);
    expect(coverage.batchCovered).toBe(2);
    expect(coverage.perItemSupported).toBe(1);
    expect(coverage.exceptionCount).toBe(0);
    expect(coverageSummary(coverage)).toBe(
      "已审 3 项（批量覆盖 2 项，逐项 supported 1 项，逐项例外 0 项）；未审 0 项（共 3 项）",
    );
  });

  it("batch confirm covers every loaded candidate without becoming a person merge", () => {
    const current = review({ candidates });
    const next = batchConfirmDraft(createDraft(current), candidates);
    expect(next.defaultAssessment).toBe("supported");
    expect(next.batchApplied).toBe(true);
    expect(next.overrides).toEqual({});
    expect(next.reviewed).toEqual({ [key(1)]: true, [key(2)]: true, [key(3)]: true });
    const coverage = reviewCoverage(candidates, next);
    expect(coverage.reviewed).toBe(3);
    expect(coverage.unreviewed).toBe(0);
    expect(coverage.batchCovered).toBe(3);
    expect(coverage.exceptionCount).toBe(0);
    expect(BATCH_SCOPE_NOTE).toContain("不建立人物等价");
    expect(BATCH_SCOPE_NOTE).toContain("永久在任");
  });

  it("keeps overrides keyed precisely after a batch switch", () => {
    const current = review({ candidates });
    const afterBatch = batchConfirmDraft(createDraft(current), candidates);
    const withException = reviewCandidate(afterBatch, candidates[1], "rejected", "错主体");
    expect(effectiveAssessment(candidates[0], withException)).toBe("supported");
    expect(effectiveAssessment(candidates[1], withException)).toBe("rejected");
    expect(effectiveAssessment(candidates[2], withException)).toBe("supported");
  });
});

describe("readable shared phase basis", () => {
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

  it("exposes contract-readable basis text, keeping refs out of the main line", () => {
    const entry = readableBasisEntry(candidate(1, { predicted_effect: "current" }));
    expect(entry.label).toContain("周瑜");
    expect(entry.label).toContain("官职");
    expect(entry.detail).toContain("当前身份");
    expect(entry.detail).toContain("来源：周瑜傳");
    expect(entry.quote).toBe("策授瑜建威中郎將");
    expect(entry.label).not.toContain("ph_001");
    const [group] = sharedPhaseBasis([candidate(1)]);
    expect(group.entries).toHaveLength(1);
    expect(group.entries[0].detail).toContain("周瑜傳");
  });

  it("consumes contract PhaseSummary labels for the shared basis", () => {
    const phases: PhaseSummary[] = [
      { phase_id: "ph_001", label: "建安三年 · 授建威中郎將", ordinal: 0, mode: "single" },
      { phase_id: "ph_002", label: "建安十三年 · 拜偏將軍", ordinal: 1, mode: "process" },
    ];
    const candidates = [candidate(1, { phase_refs: ["ph_001"] }), candidate(2, { phase_refs: ["ph_002"] })];
    const groups = sharedPhaseBasis(candidates, phases);
    expect(groups[0].phaseLabel).toBe("建安三年 · 授建威中郎將");
    expect(groups[0].phaseMode).toBe("single");
    expect(groups[0].phaseOrdinal).toBe(0);
    expect(groups[1].phaseLabel).toContain("建安十三年");
    expect(groups[1].phaseMode).toBe("process");
    const [noPhases] = sharedPhaseBasis(candidates);
    expect(noPhases.phaseLabel).toBeNull();
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
  it("never emits an un-reviewed candidate as supported", () => {
    const candidates = [candidate(1, { assessment_default: "supported" }), candidate(2)];
    const current = review({ candidates });
    const overlay = buildAssessmentOverlay(current, createDraft(current), candidates);
    expect(overlay.default_assessment).toBe("uncertain");
    expect(overlay.overrides).toEqual([]);
  });

  it("emits an explicit per-item decision even when it equals the plan default", () => {
    const candidates = [candidate(1), candidate(2)];
    const current = review({ candidates });
    let draft = createDraft(current);
    draft = reviewCandidate(draft, candidates[0], "uncertain", "明确提交不明确");
    draft = reviewCandidate(draft, candidates[1], "supported");
    const overlay = buildAssessmentOverlay(current, draft, candidates);
    expect(overlay.default_assessment).toBe("uncertain");
    expect(overlay.overrides).toEqual([
      { candidate_key: key(1), assessment: "uncertain", rationale: "明确提交不明确" },
      { candidate_key: key(2), assessment: "supported", rationale: "" },
    ]);
  });

  it("keeps batch-covered candidates on the package default and exceptions explicit", () => {
    const candidates = [candidate(1), candidate(2)];
    const current = review({ candidates });
    const batch = batchConfirmDraft(createDraft(current), candidates);
    const draft = reviewCandidate(batch, candidates[0], "disputed", "分歧未决");
    const overlay = buildAssessmentOverlay(current, draft, candidates);
    expect(overlay.default_assessment).toBe("supported");
    expect(overlay.overrides).toEqual([
      { candidate_key: key(1), assessment: "disputed", rationale: "分歧未决" },
    ]);
  });

  it("builds an empty overlay from a mismatched draft", () => {
    const current = review();
    const stale = { ...createDraft(current), planFingerprint: "d".repeat(64), batchApplied: true };
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
  const baseProps = {
    review: current,
    onDraftChange: noop,
    onSubmit: async () => undefined,
    onSkip: noop,
    onReturn: noop,
    phases: [{ phase_id: "ph_001", label: "建安三年 · 授建威中郎將", ordinal: 0, mode: "single" as const }],
  };

  it("keeps qualifiers, reasons and predictions visible, not inside technical details", () => {
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        ...baseProps,
        draft: createDraft(current),
      }),
    );
    expect(markup).toContain('data-test="psr-qualification"');
    expect(markup).toContain('data-test="psr-reasons"');
    expect(markup).toContain("自称");
    expect(markup).toContain("任期未明");
    expect(markup).toContain('data-test="psr-effect"');
    expect(markup).toContain("此前记载");
    // Human-readable shared basis is in the main UI; refs are audit-only.
    expect(markup).toContain('data-test="psr-basis-entry"');
    expect(markup).toContain("周瑜傳");
    // Contract PhaseSummary label is shown as the phase/time basis.
    expect(markup).toContain('data-test="psr-basis-phase"');
    expect(markup).toContain("建安三年 · 授建威中郎將");
    expect(markup).toContain("审计详情");
    expect(markup).not.toContain("<script");
  });

  it("does not review a candidate whose only input is a rationale", () => {
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        ...baseProps,
        draft: setCandidateRationale(createDraft(current), candidates[0], "仅备注"),
      }),
    );
    expect(markup).toContain('data-test="psr-rationale-only"');
    expect(markup).toContain('data-test="psr-unreviewed"');
    expect(markup).toMatch(/data-test="psr-save-next"[^>]*disabled/);
  });

  it("shows 未审 and blocks submit until every candidate is reviewed", () => {
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        ...baseProps,
        draft: createDraft(current),
      }),
    );
    expect(markup).toContain('data-test="psr-unreviewed"');
    expect(markup).toContain("未审（请选择）");
    expect(markup).toMatch(/data-test="psr-save-next"[^>]*data-blocked-reason="unreviewed"/);
    expect(markup).toMatch(/data-test="psr-save-next"[^>]*disabled/);
  });

  it("enables submit once all candidates are reviewed and no page remains", () => {
    const draft = reviewCandidate(createDraft(current), candidates[0], "supported");
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        ...baseProps,
        draft,
      }),
    );
    expect(markup).not.toContain('data-test="psr-unreviewed"');
    expect(markup).toMatch(/data-test="psr-save-next"(?![^>]*disabled)/);
  });

  it("fails closed on has_more without a load callback", () => {
    const paged = review({ has_more: true, next_cursor: "cur-2", candidate_count: 3 });
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        ...baseProps,
        review: paged,
        draft: reviewCandidate(createDraft(paged), paged.candidates[0], "supported"),
      }),
    );
    expect(markup).toContain('data-test="psr-pagination-blocked"');
    expect(markup).toMatch(/data-test="psr-save-next"[^>]*disabled/);
  });

  it("offers load-more when a callback is provided", () => {
    const paged = review({ has_more: true, next_cursor: "cur-2", candidate_count: 3 });
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        ...baseProps,
        review: paged,
        draft: createDraft(paged),
        onLoadMore: async () => paged,
      }),
    );
    expect(markup).toContain('data-test="psr-load-more"');
    expect(markup).not.toContain('data-test="psr-pagination-blocked"');
  });

  it("marks a mismatched draft and disables submit until the caller re-keys it", () => {
    const stale = { ...createDraft(current), planFingerprint: "e".repeat(64) };
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        ...baseProps,
        draft: stale,
      }),
    );
    expect(markup).toContain('data-test="psr-stale-draft"');
    expect(markup).toMatch(/data-test="psr-save-next"[^>]*disabled/);
  });

  it("mounts the optional read-only source slot without owning a loader", () => {
    const markup = renderToStaticMarkup(
      createElement(PersonStateReviewPanel, {
        ...baseProps,
        draft: createDraft(current),
        renderSource: (item) => createElement("span", null, `来源槽 ${item.candidate_key}`),
      }),
    );
    expect(markup).toContain('data-test="psr-source-slot"');
    expect(markup).toContain("来源槽");
  });
});
