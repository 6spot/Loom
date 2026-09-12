// C2-R3-T12 章阶段依据审核显示与草稿 helper。
//
// Contract owner: apps/chronicle/docs/person-state-reading.md §5/§5.1.
// This module is intentionally UI-framework free. It only renders the frozen
// T01 review DTO (ReviewPackage / ReviewCandidate) and holds the typed draft
// that the panel hands to an external save callback. It never fetches, never
// writes sessionStorage, never keys by display name, and never derives a
// certainty/assessment from model confidence: an assessment is either the
// package default the reviewer chose or an explicit per-candidate_key override.
//
// Key rules encoded here:
// - Draft identity is (plan_fingerprint). A draft from another plan/item is
//   ignored instead of being applied to the current candidates.
// - Exceptions are keyed by the exact candidate_key, so an override can never
//   bleed into another candidate or another chapter package.
// - "batch confirm supported" only records an assessment for these concrete
//   candidates; it is not a person merge and does not prove permanent tenure.
// - The submission overlay keeps only candidates that differ from the chosen
//   default or carry a rationale; the default_assessment stays package-level.

import type {
  Assessment,
  AssessmentOverlay,
  AssessmentOverride,
  Attribution,
  PlaceDimension,
  PredictedEffect,
  PhaseSummary,
  PersonPhaseMode,
  Qualification,
  ReasonCode,
  ReviewCandidate,
  ReviewPackage,
  StateDimension,
  StateOperation,
} from "./person-state-types";

// ---------------------------------------------------------------------------
// Typed draft
// ---------------------------------------------------------------------------

export interface AssessmentOverrideDraft {
  readonly assessment: Assessment;
  readonly rationale: string;
}

/**
 * Reviewer draft for one frozen chapter package. `defaultAssessment` is the
 * package-level choice ("批量确认"), `overrides` are the per-candidate_key
 * exceptions. `reviewed` records the candidates the reviewer explicitly
 * assessed (via the bulk action or a per-item choice), so an untouched
 * candidate stays "未审" and is never counted or submitted as supported.
 * Switching plan/item produces a fresh draft; a mismatched draft is never
 * merged.
 */
export interface PersonStateReviewDraft {
  readonly planFingerprint: string;
  /** Package-level value applied to batch-reviewed candidates. */
  readonly defaultAssessment: Assessment;
  /** True once the reviewer confirmed the currently loaded candidates. */
  readonly batchApplied: boolean;
  readonly overrides: Readonly<Record<string, AssessmentOverrideDraft>>;
  /** Explicitly reviewed candidate_keys; absent => 未审. */
  readonly reviewed: Readonly<Record<string, true>>;
  readonly rationale: string;
}

export function createDraft(review: ReviewPackage): PersonStateReviewDraft {
  return {
    planFingerprint: review.plan_fingerprint,
    defaultAssessment: review.default_assessment,
    batchApplied: false,
    overrides: {},
    reviewed: {},
    rationale: "",
  };
}

/** A draft belongs to a review only while the plan fingerprint matches. */
export function isDraftForReview(
  review: ReviewPackage,
  draft: PersonStateReviewDraft | null | undefined,
): boolean {
  return Boolean(draft && draft.planFingerprint === review.plan_fingerprint);
}

/**
 * Never carry a draft across plan/item: a mismatched or missing draft falls
 * back to the fresh defaults for the current review.
 */
export function resolveDraft(
  review: ReviewPackage,
  draft: PersonStateReviewDraft | null | undefined,
): PersonStateReviewDraft {
  return isDraftForReview(review, draft) ? (draft as PersonStateReviewDraft) : createDraft(review);
}

export function isOverrideDraft(value: unknown): value is AssessmentOverrideDraft {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return typeof record.rationale === "string" && typeof record.assessment === "string";
}

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

export const ASSESSMENT_LABELS: Readonly<Record<Assessment, string>> = {
  supported: "支持（有依据）",
  uncertain: "存疑（明确提交不明确）",
  disputed: "有分歧",
  rejected: "拒绝",
};

export function assessmentLabel(value: Assessment | null | undefined): string {
  if (!value) return "未评估";
  return ASSESSMENT_LABELS[value] ?? "其他评估";
}

export const PREDICTED_EFFECT_LABELS: Readonly<Record<PredictedEffect, string>> = {
  current: "当前身份",
  prior: "此前记载",
  ended: "结束",
  none: "无状态影响",
};

export function predictedEffectLabel(value: PredictedEffect | null | undefined): string {
  if (!value) return "无状态影响";
  return PREDICTED_EFFECT_LABELS[value] ?? "无状态影响";
}

export function predictedEffectNote(value: PredictedEffect | null | undefined): string {
  switch (value) {
    case "current":
      return "确认后作为当前阶段状态显示；单条授任仍需晚期在任的适用依据。";
    case "prior":
      return "确认后只作为此前记载，不代表延续到当前阶段。";
    case "ended":
      return "确认后表示该项在此阶段结束，不再作为当前身份。";
    default:
      return "不改变当前身份、此前记载或结束状态。";
  }
}

const DIMENSION_LABELS: Readonly<Record<string, string>> = {
  office: "官职",
  title: "爵号",
  affiliation: "效力/归附",
  administration: "行政归属",
  control: "实际控制",
};

export function dimensionLabel(value: StateDimension | PlaceDimension | null | undefined): string {
  if (!value) return "状态";
  return DIMENSION_LABELS[value] ?? "状态";
}

/** Person vs place scope; the two must never be conflated in the panel. */
export function dimensionScope(value: string | null | undefined): "person" | "place" | null {
  if (value === "office" || value === "title" || value === "affiliation") return "person";
  if (value === "administration" || value === "control") return "place";
  return null;
}

const QUALIFICATION_LABELS: Readonly<Record<Qualification, string>> = {
  ordinary: "一般记载",
  recommendation: "推荐",
  self_designation: "自称",
  posthumous: "追赠",
  reported: "奏报自述",
};

export function qualificationLabel(value: Qualification | null | undefined): string {
  if (!value) return "";
  if (value === "ordinary") return "";
  return QUALIFICATION_LABELS[value] ?? "限定记载";
}

/** The qualifier belongs to the conclusion itself, so it is always可见. */
export function qualificationNote(value: Qualification | null | undefined): string {
  switch (value) {
    case "recommendation":
      return "推荐不建立生前当前任职，只作为本段记载。";
    case "posthumous":
      return "追赠不建立生前当前任职，只作为本段记载。";
    case "self_designation":
      return "自称只证明“自称某号”，限定语不得省略。";
    case "reported":
      return "奏报自述只表示该来源如此陈述，不证明其他来源承认。";
    default:
      return "";
  }
}

const ATTRIBUTION_LABELS: Readonly<Record<Attribution, string>> = {
  narrator: "正文叙述",
  quotation: "引述",
  annotation: "注文",
  hearsay: "传闻",
};

export function attributionLabel(value: Attribution | null | undefined): string {
  if (!value) return "来源归属未标";
  return ATTRIBUTION_LABELS[value] ?? "来源归属未标";
}

const OPERATION_LABELS: Readonly<Record<StateOperation, string>> = {
  start: "开始/取得",
  end: "结束",
  attest: "仅证明本段记载",
};

export function operationLabel(value: StateOperation | null | undefined): string {
  if (!value) return "记载";
  return OPERATION_LABELS[value] ?? "记载";
}

export function operationNote(value: StateOperation | null | undefined): string {
  switch (value) {
    case "start":
      return "来源支持的取得或归附；不自动建立无限明确的在任区间。";
    case "end":
      return "该项在此结束，只影响对应状态键，不结束其他关系。";
    case "attest":
      return "只证明在所指阶段有此记载，不建立长期任职。";
    default:
      return "只按本条记载处理。";
  }
}

const REASON_CODE_LABELS: Readonly<Record<ReasonCode, string>> = {
  tenure_unproven: "任期未明",
  order_unknown: "先后未明",
  source_disagreement: "来源分歧",
  attribution_uncertain: "归属不确定",
  evidence_uncertain: "证据不足",
  phase_not_reached: "阶段尚未到达",
  phase_not_begun: "阶段尚未开始",
};

export function reasonCodeLabel(value: string | null | undefined): string {
  if (!value) return "";
  return (REASON_CODE_LABELS as Record<string, string>)[value] ?? "其他不明确原因";
}

export function reasonCodesLabel(values: ReadonlyArray<string> | null | undefined): string {
  if (!values || values.length === 0) return "";
  return values.map((code) => reasonCodeLabel(code)).join("、");
}

const RELATION_LABELS: Readonly<Record<string, string>> = {
  serves: "效力",
  attached_to: "归附",
};

export function relationLabel(value: string | null | undefined): string {
  if (!value) return "";
  return RELATION_LABELS[value] ?? value;
}

// ---------------------------------------------------------------------------
// Candidate presentation
// ---------------------------------------------------------------------------

/** Affiliation renders its directional object; office/title renders its value. */
export function candidateValueText(candidate: ReviewCandidate): string {
  if (candidate.dimension === "affiliation") {
    const relation = relationLabel(candidate.relation);
    const target = candidate.target ?? "";
    if (relation && target) return `${relation} ${target}`;
    if (target) return target;
  }
  return candidate.value ?? candidate.target ?? "—";
}

/** before → after flow, matching the D02 review interaction. */
export function candidateFlow(candidate: ReviewCandidate): { before: string; after: string } {
  const value = candidateValueText(candidate);
  if (candidate.operation === "end") return { before: value, after: "结束" };
  return { before: "—", after: value };
}

/** Human-readable basis line for one candidate, no internal refs involved. */
export interface ReadableBasisEntry {
  readonly candidateKey: string;
  readonly personName: string;
  readonly label: string;
  readonly detail: string;
  readonly quote: string;
  readonly sourceLabel: string;
  readonly attribution: string;
}

export function readableBasisEntry(candidate: ReviewCandidate): ReadableBasisEntry {
  const flow = candidateFlow(candidate);
  const personName = candidate.person_name ?? "未指定人物";
  return {
    candidateKey: candidate.candidate_key,
    personName,
    label: `${personName} · ${dimensionLabel(candidate.dimension)} · ${operationLabel(candidate.operation)}`,
    detail:
      `${flow.before} → ${flow.after}｜${predictedEffectLabel(candidate.predicted_effect)}` +
      `｜来源：${candidate.source_label}（${attributionLabel(candidate.attribution)}）`,
    quote: candidate.quote,
    sourceLabel: candidate.source_label,
    attribution: attributionLabel(candidate.attribution),
  };
}

export interface SharedPhaseBasis {
  /** Stable 1-based display ordinal; raw refs stay in the audit detail. */
  readonly ordinal: number;
  readonly phaseRefs: readonly string[];
  readonly candidateKeys: readonly string[];
  /** Contract-readable phase label (PhaseSummary.label), when supplied. */
  readonly phaseLabel: string | null;
  readonly phaseMode: PersonPhaseMode | null;
  readonly phaseOrdinal: number | null;
  /** Contract-provided readable basis (person/change/effect/source/quote). */
  readonly entries: readonly ReadableBasisEntry[];
}

function resolvePhaseSummary(
  refs: ReadonlyArray<string>,
  phases: ReadonlyArray<PhaseSummary> | null | undefined,
): PhaseSummary | null {
  if (!phases || phases.length === 0) return null;
  const byRef = new Map(phases.map((phase) => [phase.phase_id, phase]));
  for (const ref of refs) {
    const found = byRef.get(ref);
    if (found) return found;
  }
  return null;
}

/**
 * 每章包共用阶段依据单列: candidates that share the exact same phase_refs set
 * share one time basis. Order follows first appearance so the panel is stable.
 * `phases` are the contract's readable `PhaseSummary` entries for this unit (the
 * same fields used by the reading summaries); matching is by exact local phase
 * ref. The main UI renders `phaseLabel` + the readable `entries`; raw `phaseRefs`
 * are audit only.
 */
export function sharedPhaseBasis(
  candidates: ReadonlyArray<ReviewCandidate>,
  phases?: ReadonlyArray<PhaseSummary> | null,
): SharedPhaseBasis[] {
  const groups: Array<{ key: string; refs: string[]; candidateKeys: string[]; entries: ReadableBasisEntry[] }> = [];
  const byKey = new Map<string, number>();
  for (const candidate of candidates) {
    const refs = [...candidate.phase_refs].sort();
    const key = refs.join("|");
    const at = byKey.get(key);
    const entry = readableBasisEntry(candidate);
    if (at === undefined) {
      byKey.set(key, groups.length);
      groups.push({ key, refs, candidateKeys: [candidate.candidate_key], entries: [entry] });
    } else {
      groups[at].candidateKeys.push(candidate.candidate_key);
      groups[at].entries.push(entry);
    }
  }
  return groups.map((group, index) => {
    const summary = resolvePhaseSummary(group.refs, phases);
    const labels = group.refs
      .map((ref) => phases?.find((phase) => phase.phase_id === ref)?.label)
      .filter((label): label is string => Boolean(label && label.trim()));
    const phaseLabel = summary?.label?.trim() ? labels.join("、") : null;
    return {
      ordinal: index + 1,
      phaseRefs: group.refs,
      candidateKeys: group.candidateKeys,
      phaseLabel,
      phaseMode: summary?.mode ?? null,
      phaseOrdinal: summary?.ordinal ?? null,
      entries: group.entries,
    };
  });
}

/** Map candidate_key → shared basis ordinal for row badges. */
export function phaseBasisOrdinals(
  candidates: ReadonlyArray<ReviewCandidate>,
): ReadonlyMap<string, number> {
  const result = new Map<string, number>();
  for (const basis of sharedPhaseBasis(candidates)) {
    for (const key of basis.candidateKeys) result.set(key, basis.ordinal);
  }
  return result;
}

export interface PersonCandidateGroup {
  readonly key: string;
  readonly personName: string;
  readonly personId: string | null;
  readonly candidates: readonly ReviewCandidate[];
}

/** 包内按人物列出变化链, preserving first appearance order. */
export function groupCandidatesByPerson(
  candidates: ReadonlyArray<ReviewCandidate>,
): PersonCandidateGroup[] {
  const groups = new Map<string, PersonCandidateGroup & { candidates: ReviewCandidate[] }>();
  for (const candidate of candidates) {
    const key = candidate.person_id ?? candidate.person_name ?? "__unassigned__";
    const existing = groups.get(key);
    if (existing) {
      existing.candidates.push(candidate);
    } else {
      groups.set(key, {
        key,
        personName: candidate.person_name ?? "未指定人物",
        personId: candidate.person_id ?? null,
        candidates: [candidate],
      });
    }
  }
  return [...groups.values()];
}

// ---------------------------------------------------------------------------
// Effective assessment and coverage
// ---------------------------------------------------------------------------

function legalAssessment(candidate: ReviewCandidate, value: Assessment): Assessment {
  return candidate.allowed_assessments.includes(value) ? value : candidate.assessment_default;
}

/** 未审 until the reviewer picks an assessment or covers it with batch confirm. */
export function isCandidateReviewed(
  candidate: ReviewCandidate,
  draft: PersonStateReviewDraft,
): boolean {
  return draft.reviewed[candidate.candidate_key] === true;
}

/**
 * Effective assessment for a reviewed candidate; `null` while 未审. An
 * un-reviewed candidate is never reported as supported.
 */
export function effectiveAssessment(
  candidate: ReviewCandidate,
  draft: PersonStateReviewDraft,
): Assessment | null {
  if (!isCandidateReviewed(candidate, draft)) return null;
  const override = draft.overrides[candidate.candidate_key];
  if (override) return legalAssessment(candidate, override.assessment);
  return legalAssessment(candidate, draft.batchApplied ? draft.defaultAssessment : candidate.assessment_default);
}

export function isCandidateException(
  candidate: ReviewCandidate,
  draft: PersonStateReviewDraft,
): boolean {
  if (!isCandidateReviewed(candidate, draft)) return false;
  const override = draft.overrides[candidate.candidate_key];
  if (override && override.rationale.trim().length > 0) return true;
  return effectiveAssessment(candidate, draft) !== "supported";
}

export interface ReviewCoverage {
  readonly total: number;
  /** Explicitly assessed candidates (batch-covered + per-item choices). */
  readonly reviewed: number;
  /** Untouched candidates; they are neither covered nor submitted. */
  readonly unreviewed: number;
  /** Reviewed by the bulk action without a per-item override. */
  readonly batchCovered: number;
  /** Explicit per-item "supported" choices without a rationale. */
  readonly perItemSupported: number;
  /** Reviewed candidates that are not a plain supported decision. */
  readonly exceptionCount: number;
  /** Reviewed candidates carrying an explicit per-candidate_key override. */
  readonly explicitOverrideCount: number;
  /** Exceptions that still lack a rationale; the reviewer should add one. */
  readonly exceptionsMissingRationale: number;
}

export function reviewCoverage(
  candidates: ReadonlyArray<ReviewCandidate>,
  draft: PersonStateReviewDraft,
): ReviewCoverage {
  let reviewed = 0;
  let batchCovered = 0;
  let perItemSupported = 0;
  let exceptionCount = 0;
  let explicitOverrideCount = 0;
  let exceptionsMissingRationale = 0;
  for (const candidate of candidates) {
    if (!isCandidateReviewed(candidate, draft)) continue;
    reviewed += 1;
    const override = draft.overrides[candidate.candidate_key];
    if (override) explicitOverrideCount += 1;
    if (isCandidateException(candidate, draft)) {
      exceptionCount += 1;
      if (!override || override.rationale.trim().length === 0) exceptionsMissingRationale += 1;
    } else if (override) {
      perItemSupported += 1;
    } else {
      batchCovered += 1;
    }
  }
  return {
    total: candidates.length,
    reviewed,
    unreviewed: candidates.length - reviewed,
    batchCovered,
    perItemSupported,
    exceptionCount,
    explicitOverrideCount,
    exceptionsMissingRationale,
  };
}

export function coverageSummary(coverage: ReviewCoverage): string {
  return (
    `已审 ${coverage.reviewed} 项（批量覆盖 ${coverage.batchCovered} 项，逐项 supported ${coverage.perItemSupported} 项，` +
    `逐项例外 ${coverage.exceptionCount} 项）；未审 ${coverage.unreviewed} 项（共 ${coverage.total} 项）`
  );
}

/**
 * Batch confirm records "supported" for the currently loaded candidates only.
 * It is not a person merge and does not prove permanent tenure.
 */
export const BATCH_SCOPE_NOTE =
  "批量确认只记录对这些具体候选的评估，不建立人物等价，也不代表永久在任；晚期在任仍须另有适用依据。";

export function batchConfirmDraft(
  draft: PersonStateReviewDraft,
  candidates: ReadonlyArray<ReviewCandidate>,
): PersonStateReviewDraft {
  const reviewed = { ...draft.reviewed };
  for (const candidate of candidates) reviewed[candidate.candidate_key] = true;
  return { ...draft, defaultAssessment: "supported", batchApplied: true, overrides: {}, reviewed };
}

/** Explicitly assess one candidate (including "uncertain" as a real decision). */
export function reviewCandidate(
  draft: PersonStateReviewDraft,
  candidate: ReviewCandidate,
  assessment: Assessment,
  rationale = "",
): PersonStateReviewDraft {
  return {
    ...draft,
    overrides: {
      ...draft.overrides,
      [candidate.candidate_key]: { assessment, rationale },
    },
    reviewed: { ...draft.reviewed, [candidate.candidate_key]: true },
  };
}

/**
 * Record an exception rationale without ever marking the candidate reviewed.
 * Typing only a reason must not produce an assessment: an 未审 candidate keeps
 * no effective value and is never submitted. For an already reviewed candidate
 * the rationale attaches to its existing (or batch) assessment.
 */
export function setCandidateRationale(
  draft: PersonStateReviewDraft,
  candidate: ReviewCandidate,
  rationale: string,
): PersonStateReviewDraft {
  const existing = draft.overrides[candidate.candidate_key];
  const assessment = existing?.assessment ?? effectiveAssessment(candidate, draft) ?? candidate.assessment_default;
  return {
    ...draft,
    overrides: {
      ...draft.overrides,
      [candidate.candidate_key]: { assessment, rationale },
    },
  };
}

/** True when the reviewer has typed a reason but not chosen an assessment yet. */
export function hasUnreviewedRationale(
  candidate: ReviewCandidate,
  draft: PersonStateReviewDraft,
): boolean {
  return (
    !isCandidateReviewed(candidate, draft) &&
    (draft.overrides[candidate.candidate_key]?.rationale.trim().length ?? 0) > 0
  );
}

/** Return one candidate to 未审: drop its override and reviewed marker. */
export function unreviewCandidate(
  draft: PersonStateReviewDraft,
  candidate: ReviewCandidate,
): PersonStateReviewDraft {
  const overrides = { ...draft.overrides };
  delete overrides[candidate.candidate_key];
  const reviewed = { ...draft.reviewed };
  delete reviewed[candidate.candidate_key];
  return { ...draft, overrides, reviewed };
}

// ---------------------------------------------------------------------------
// Submission overlay
// ---------------------------------------------------------------------------

/**
 * Build the frozen decision payload from the candidates that were explicitly
 * reviewed. Un-reviewed candidates are never emitted and never become
 * supported. The package default is the reviewer's bulk choice when one was
 * made, otherwise the plan default; each reviewed per-item choice is emitted
 * as an explicit candidate_key override (so an explicit "不明确" is visible in
 * the payload even when it equals the plan default).
 */
export function buildAssessmentOverlay(
  review: ReviewPackage,
  draft: PersonStateReviewDraft,
  candidates: ReadonlyArray<ReviewCandidate> = review.candidates,
): AssessmentOverlay {
  const active = resolveDraft(review, draft);
  const packageDefault = active.batchApplied ? active.defaultAssessment : review.default_assessment;
  const overrides: AssessmentOverride[] = [];
  for (const candidate of candidates) {
    if (!isCandidateReviewed(candidate, active)) continue;
    const override = active.overrides[candidate.candidate_key];
    if (!override) continue;
    overrides.push({
      candidate_key: candidate.candidate_key,
      assessment: legalAssessment(candidate, override.assessment),
      rationale: override.rationale,
    });
  }
  return {
    plan_fingerprint: review.plan_fingerprint,
    default_assessment: packageDefault,
    overrides,
    rationale: active.rationale,
  };
}

export function overrideCount(overlay: AssessmentOverlay): number {
  return overlay.overrides.length;
}

// ---------------------------------------------------------------------------
// Submission failure guidance
// ---------------------------------------------------------------------------

function numericStatus(error: unknown): number | null {
  if (typeof error !== "object" || error === null) return null;
  const record = error as Record<string, unknown>;
  for (const key of ["status", "statusCode", "httpStatus"]) {
    const value = record[key];
    if (typeof value === "number") return value;
  }
  const code = record.code;
  if (typeof code === "string" && /^\d{3}$/.test(code)) return Number(code);
  return null;
}

/**
 * 400/409/503/unknown outcomes all retain the draft; the message tells the
 * operator whether to fix the input, re-check the server record, or retry.
 */
export function submitFailureMessage(error: unknown): string {
  const status = numericStatus(error);
  const prefix = "保存失败：草稿与已读来源已保留。";
  if (status === 400) {
    return `${prefix}服务端拒绝了这次提交（400）：请确认评估值都在允许范围内，修正后重试。`;
  }
  if (status === 409) {
    return `${prefix}计划版本或候选已变化（409）：请先核对服务端记录，再决定是否重新提交，不要丢弃草稿。`;
  }
  if (status === 503) {
    return `${prefix}核对服务暂时不可用（503）：可稍后重试，草稿不受影响。`;
  }
  return `${prefix}无法确认提交结果：请先核对服务端记录，再决定是否重试，避免重复提交。`;
}

/** Kept visible so a source-page load failure never blocks the form. */
export const SOURCE_LOAD_FAILURE_NOTE =
  "来源分页加载失败不影响本表单输入：已读原文保留、可重试，候选评估仍可继续提交。";
