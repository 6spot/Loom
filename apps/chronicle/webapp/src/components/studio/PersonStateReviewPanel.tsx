// C2-R3-T12 按章阶段依据审核表单与连续操作组件。
//
// Contract owner: apps/chronicle/docs/person-state-reading.md §5/§5.1.
// The panel renders one frozen chapter_state_evidence package and reports every
// reviewer choice through the external callbacks. It owns no route, no query,
// no sessionStorage and no HTTP client: T10/T13 wire the page, the loader and
// the decision endpoint, and re-key the draft by (review_id, plan_fingerprint).
//
// Props: review / draft / onDraftChange / onSubmit / onSkip / onReturn, plus an
// optional onLoadMore for candidate pages.
// - 未审 is explicit: only a per-item choice or a batch confirmation marks a
//   candidate reviewed, and un-reviewed candidates are neither counted as
//   covered nor submitted. Skip keeps them 未审.
// - The draft is controlled by the caller; the panel never carries a stale
//   draft across a plan/item change (a mismatched fingerprint is ignored).
// - Exceptions are keyed by the exact candidate_key, so they can not bleed
//   across candidates, chapters, plans or candidate pages.
// - If a package has more candidate pages than the panel can reach (has_more
//   without onLoadMore), submission fails closed instead of silently missing
//   candidates.
// - A failed submit (400/409/503/unknown) keeps the draft on screen and tells
//   the operator to re-check the server record; a late result for a package the
//   reviewer already left never clears or overwrites the current form.
// - Source evidence is read-only: a source-pagination failure never disables
//   the assessment inputs.

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Button } from "../ui/button";
import type { Assessment, PhaseSummary, ReviewCandidate, ReviewPackage } from "../../lib/person-state-types";
import {
  BATCH_SCOPE_NOTE,
  SOURCE_LOAD_FAILURE_NOTE,
  assessmentLabel,
  attributionLabel,
  batchConfirmDraft,
  buildAssessmentOverlay,
  candidateFlow,
  candidateValueText,
  coverageSummary,
  dimensionLabel,
  effectiveAssessment,
  groupCandidatesByPerson,
  hasUnreviewedRationale,
  isCandidateException,
  isCandidateReviewed,
  isDraftForReview,
  operationLabel,
  operationNote,
  phaseBasisOrdinals,
  predictedEffectLabel,
  predictedEffectNote,
  qualificationLabel,
  qualificationNote,
  reasonCodesLabel,
  resolveDraft,
  reviewCandidate,
  reviewCoverage,
  setCandidateRationale,
  sharedPhaseBasis,
  submitFailureMessage,
  unreviewCandidate,
} from "../../lib/person-state-review-display";
import type { PersonStateReviewDraft } from "../../lib/person-state-review-display";
import "../../styles/person-state-review.css";

export interface PersonStateReviewPanelProps {
  review: ReviewPackage;
  draft: PersonStateReviewDraft;
  onDraftChange: (draft: PersonStateReviewDraft) => void;
  /** External save; reject to keep the draft (400/409/503/unknown). */
  onSubmit: (draft: PersonStateReviewDraft) => Promise<void>;
  onSkip: () => void | Promise<void>;
  onReturn: () => void;
  /**
   * Load the next candidate page for the same frozen package. Required for a
   * package whose first page has `has_more=true`; without it the panel fails
   * closed rather than reviewing an incomplete candidate set.
   */
  onLoadMore?: (cursor: string) => Promise<ReviewPackage>;
  /**
   * Contract-readable phase summaries for this unit (PhaseSummary.label /
   * ordinal / mode). When supplied, the shared-basis section shows the real
   * 阶段标签 instead of only internal refs; refs stay in the audit detail.
   */
  phases?: readonly PhaseSummary[];
  /**
   * Optional read-only source slot (T13 mounts the existing ReviewEvidencePanel
   * here). The form never owns the source loader: opening 窗口/整章原文 is a
   * separate read-only surface and can not change the draft.
   */
  renderSource?: (candidate: ReviewCandidate) => ReactNode;
}

function reviewIdentity(review: ReviewPackage): string {
  return `${review.review_id}|${review.plan_fingerprint}`;
}

function effectTone(effect: ReviewCandidate["predicted_effect"]): string {
  return effect;
}

export default function PersonStateReviewPanel({
  review,
  draft,
  onDraftChange,
  onSubmit,
  onSkip,
  onReturn,
  onLoadMore,
  phases,
  renderSource,
}: PersonStateReviewPanelProps) {
  const identity = reviewIdentity(review);
  const identityRef = useRef(identity);
  identityRef.current = identity;

  const [extraPages, setExtraPages] = useState<ReviewPackage[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [skipped, setSkipped] = useState(false);

  // A new package starts with a clean form surface: no error/notice from the
  // package the reviewer just left, no in-flight save owns the new form, and no
  // candidate page from the old package remains reachable.
  useEffect(() => {
    setExtraPages([]);
    setLoadingMore(false);
    setLoadError("");
    setSubmitting(false);
    setError("");
    setNotice("");
    setSkipped(false);
  }, [identity]);

  const lastPage = extraPages.length ? extraPages[extraPages.length - 1] : review;
  const allCandidates = useMemo(() => {
    const seen = new Set<string>();
    const merged: ReviewCandidate[] = [];
    for (const page of [review, ...extraPages]) {
      for (const candidate of page.candidates) {
        if (seen.has(candidate.candidate_key)) continue;
        seen.add(candidate.candidate_key);
        merged.push(candidate);
      }
    }
    return merged;
  }, [review, extraPages]);

  const draftBelongs = isDraftForReview(review, draft);
  const activeDraft = resolveDraft(review, draft);
  const coverage = reviewCoverage(allCandidates, activeDraft);
  const basis = sharedPhaseBasis(allCandidates, phases);
  const basisOrdinals = phaseBasisOrdinals(allCandidates);
  const personGroups = groupCandidatesByPerson(allCandidates);
  const overlayPreview = buildAssessmentOverlay(review, activeDraft, allCandidates);
  const remaining = Math.max(review.candidate_count - allCandidates.length, 0);
  const morePending = lastPage.has_more;
  const paginationBlocked = morePending && !onLoadMore;
  const canSubmit =
    draftBelongs && !submitting && coverage.unreviewed === 0 && !morePending && !paginationBlocked;

  const updateDraft = (patch: Partial<PersonStateReviewDraft>) => {
    onDraftChange({ ...activeDraft, ...patch });
  };

  const handleBatchConfirm = () => {
    if (submitting || allCandidates.length === 0) return;
    onDraftChange(batchConfirmDraft(activeDraft, allCandidates));
    setNotice("已批量确认为支持；这是对具体候选的评估，不代表人物合并或永久在任。");
    setError("");
  };

  const loadMore = async () => {
    if (loadingMore || !onLoadMore || !lastPage.has_more || !lastPage.next_cursor) return;
    const key = identityRef.current;
    const cursor = lastPage.next_cursor;
    setLoadingMore(true);
    setLoadError("");
    try {
      const page = await onLoadMore(cursor);
      if (identityRef.current !== key) return;
      if (page.review_id !== review.review_id || page.plan_fingerprint !== review.plan_fingerprint) {
        setLoadError("加载到的候选属于其他审核项或计划，已忽略；请重试。");
        return;
      }
      setExtraPages((current) => [...current, page]);
    } catch (caught) {
      if (identityRef.current !== key) return;
      setLoadError(
        caught instanceof Error && caught.message
          ? `候选分页加载失败（${caught.message}）；已加载候选不受影响，可重试。`
          : "候选分页加载失败；已加载候选不受影响，可重试。",
      );
    } finally {
      if (identityRef.current === key) setLoadingMore(false);
    }
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const key = identityRef.current;
    setSubmitting(true);
    setError("");
    try {
      await onSubmit(resolveDraft(review, activeDraft));
      // A late success for a package the reviewer already left must not write
      // any state into the current form.
      if (identityRef.current !== key) return;
      setNotice("已保存。可继续下一项。");
    } catch (caught) {
      if (identityRef.current !== key) return;
      setError(submitFailureMessage(caught));
    } finally {
      if (identityRef.current === key) setSubmitting(false);
    }
  };

  const handleSkip = async () => {
    if (submitting) return;
    const key = identityRef.current;
    setSkipped(true);
    setError("");
    setNotice("已暂时跳过：只改变浏览会话，仍待审，没有提交任何决定。");
    try {
      await onSkip();
    } catch {
      if (identityRef.current !== key) return;
      setNotice("");
      setSkipped(false);
      setError("切换下一项失败，当前表单与草稿仍保留，可重试。");
    }
  };

  return (
    <section
      className="psr-panel"
      data-test="person-state-review-panel"
      data-review-id={review.review_id}
      data-plan-fingerprint={review.plan_fingerprint}
      data-submitting={submitting ? "true" : "false"}
      aria-label="章阶段依据审核表单"
    >
      <header className="psr-head">
        <p className="psr-eyebrow">每章一份阶段依据包 · {review.review_mode}</p>
        <h1 className="psr-title" data-test="psr-title">
          章阶段依据审核
        </h1>
        <p className="psr-intro">
          按人物读变化；共用阶段依据单列；批量确认只记录对具体候选的评估，不建立人物等价，也不代表永久在任。
        </p>
        <p className="psr-meta" data-test="psr-meta">
          <span>审核项 {review.review_id}</span>
          <span>
            已加载候选 {allCandidates.length} / 共 {review.candidate_count}
          </span>
          <span>默认评估 {assessmentLabel(review.default_assessment)}</span>
        </p>
      </header>

      {!draftBelongs ? (
        <p className="psr-warn" role="status" data-test="psr-stale-draft">
          本表单的草稿属于其他计划或审核项，已按本项默认值重新开始；旧草稿不会被套用到当前候选。
        </p>
      ) : null}

      <section className="psr-basis" data-test="psr-shared-basis" aria-label="共用阶段依据">
        <h2>共用阶段依据</h2>
        <p className="psr-muted">
          同一阶段依据组下的候选共用同一条时间依据；下面是该组可读的依据（人物、变化、预测效果与来源原文）。确认某一条不代表其余阶段自动成立。
        </p>
        {basis.length === 0 ? (
          <p className="psr-muted">本包没有候选。</p>
        ) : (
          <ol className="psr-basis-list">
            {basis.map((group) => (
              <li key={group.ordinal} data-test="psr-basis-item" data-basis-ordinal={group.ordinal}>
                <strong>阶段依据 {group.ordinal}</strong>
                {group.phaseLabel ? (
                  <span className="psr-basis-phase" data-test="psr-basis-phase" data-phase-mode={group.phaseMode ?? ""}>
                    阶段：{group.phaseLabel}
                    {group.phaseOrdinal != null ? `（顺序 ${group.phaseOrdinal}）` : ""}
                  </span>
                ) : (
                  <span className="psr-muted" data-test="psr-basis-phase-missing">
                    未提供可读阶段标签；请由调用方传入契约 phases。
                  </span>
                )}
                <span className="psr-muted">覆盖 {group.candidateKeys.length} 项候选</span>
                <ul className="psr-basis-readable">
                  {group.entries.map((entry) => (
                    <li data-test="psr-basis-entry" data-basis-key={entry.candidateKey} key={entry.candidateKey}>
                      <span className="psr-basis-label">{entry.label}</span>
                      <span className="psr-basis-detail">{entry.detail}</span>
                      <blockquote className="psr-basis-quote">{entry.quote}</blockquote>
                    </li>
                  ))}
                </ul>
                <details className="psr-audit">
                  <summary>审计详情 / 内部阶段引用</summary>
                  <pre className="psr-code">{JSON.stringify(group.phaseRefs, null, 2)}</pre>
                </details>
              </li>
            ))}
          </ol>
        )}
      </section>

      <div className="psr-batch" data-test="psr-batch">
        <Button
          type="button"
          variant="outline"
          data-test="psr-batch-confirm"
          onClick={handleBatchConfirm}
          disabled={submitting || allCandidates.length === 0}
        >
          批量确认为「支持」
        </Button>
        <span data-test="psr-coverage">{coverageSummary(coverage)}</span>
      </div>
      <p className="psr-muted" data-test="psr-batch-note">{BATCH_SCOPE_NOTE}</p>
      {coverage.unreviewed > 0 ? (
        <p className="psr-warn" role="status" data-test="psr-unreviewed">
          还有 {coverage.unreviewed} 项未审；未审不会按支持提交。请逐项选择（包括明确提交「不明确」）或批量确认。
        </p>
      ) : null}
      {coverage.exceptionsMissingRationale > 0 ? (
        <p className="psr-warn" role="status" data-test="psr-missing-rationale">
          有 {coverage.exceptionsMissingRationale} 项例外尚未填写理由；理由用于区分为何明确提交不明确或拒绝。
        </p>
      ) : null}

      {allCandidates.length === 0 ? (
        <p className="psr-empty" data-test="psr-empty">
          本包没有可审核候选；请核对生产结果后再继续。
        </p>
      ) : (
        personGroups.map((group) => (
          <section className="psr-person" data-test="psr-person" data-person={group.key} key={group.key}>
            <h2 className="psr-person-name">
              {group.personName}
              <span className="psr-muted"> · {group.candidates.length} 项</span>
            </h2>
            <ul className="psr-list">
              {group.candidates.map((candidate) => {
                const flow = candidateFlow(candidate);
                const reviewed = isCandidateReviewed(candidate, activeDraft);
                const effective = effectiveAssessment(candidate, activeDraft);
                const exception = isCandidateException(candidate, activeDraft);
                const override = activeDraft.overrides[candidate.candidate_key];
                const qualification = qualificationLabel(candidate.qualification);
                const reasons = reasonCodesLabel(candidate.reason_codes);
                const basisOrdinal = basisOrdinals.get(candidate.candidate_key);
                return (
                  <li
                    className="psr-candidate"
                    data-test="psr-candidate"
                    data-candidate-key={candidate.candidate_key}
                    data-candidate-id={candidate.candidate_key}
                    data-assessment={effective ?? "unreviewed"}
                    data-reviewed={reviewed ? "true" : "false"}
                    data-exception={exception ? "true" : "false"}
                    data-certainty={candidate.assessment_default}
                    key={candidate.candidate_key}
                  >
                    <div className="psr-candidate-head">
                      <span className="psr-dimension">{dimensionLabel(candidate.dimension)}</span>
                      <span className="psr-operation">{operationLabel(candidate.operation)}</span>
                      <span
                        className="psr-effect"
                        data-test="psr-effect"
                        data-effect={effectTone(candidate.predicted_effect)}
                        title={predictedEffectNote(candidate.predicted_effect)}
                      >
                        预测效果：{predictedEffectLabel(candidate.predicted_effect)}
                      </span>
                      {basisOrdinal ? (
                        <span className="psr-basis-badge" data-test="psr-basis-badge">
                          共用依据 {basisOrdinal}
                        </span>
                      ) : null}
                      {!reviewed ? (
                        <span className="psr-review-state" data-test="psr-review-state">未审</span>
                      ) : null}
                    </div>

                    <p className="psr-flow" data-test="psr-flow">
                      <span>{flow.before}</span>
                      <span aria-hidden="true"> → </span>
                      <span>{flow.after}</span>
                      <span className="psr-muted">（{candidateValueText(candidate)}）</span>
                    </p>

                    <blockquote className="psr-quote" data-test="psr-quote">
                      {candidate.quote}
                    </blockquote>
                    <p className="psr-source-meta">
                      <span className="psr-source" data-test="psr-source">{candidate.source_label}</span>
                      <span className="psr-attribution" data-test="psr-attribution">
                        {attributionLabel(candidate.attribution)}
                      </span>
                    </p>

                    {renderSource ? (
                      <div className="psr-source-slot" data-test="psr-source-slot">
                        {renderSource(candidate)}
                      </div>
                    ) : null}

                    <p className="psr-notes">
                      <span className="psr-op-note">{operationNote(candidate.operation)}</span>
                      {qualification ? (
                        <span className="psr-qualification" data-test="psr-qualification">
                          限定：{qualification}。{qualificationNote(candidate.qualification)}
                        </span>
                      ) : null}
                      {reasons ? (
                        <span className="psr-reasons" data-test="psr-reasons">
                          不明确原因：{reasons}
                        </span>
                      ) : null}
                    </p>

                    <div className="psr-decision">
                      <label className="psr-field">
                        <span>逐项评估</span>
                        <select
                          data-test="psr-assessment"
                          value={effective ?? ""}
                          disabled={submitting}
                          onChange={(event) => {
                            const value = event.target.value;
                            if (!value) {
                              onDraftChange(unreviewCandidate(activeDraft, candidate));
                              return;
                            }
                            onDraftChange(
                              reviewCandidate(
                                activeDraft,
                                candidate,
                                value as Assessment,
                                override?.rationale ?? "",
                              ),
                            );
                          }}
                        >
                          <option value="">未审（请选择）</option>
                          {candidate.allowed_assessments.map((option) => (
                            <option value={option} key={option}>
                              {assessmentLabel(option)}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="psr-field psr-field-wide">
                        <span>例外理由</span>
                        <input
                          type="text"
                          data-test="psr-candidate-rationale"
                          value={override?.rationale ?? ""}
                          disabled={submitting}
                          placeholder="填写为何明确提交不明确、分歧或拒绝"
                          onChange={(event) =>
                            onDraftChange(setCandidateRationale(activeDraft, candidate, event.target.value))
                          }
                        />
                      </label>
                      {!reviewed && hasUnreviewedRationale(candidate, activeDraft) ? (
                        <span className="psr-rationale-only" data-test="psr-rationale-only">
                          仅填理由，尚未选择评估：不会标记已审，也不会提交。
                        </span>
                      ) : null}
                      {reviewed ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          data-test="psr-clear-override"
                          disabled={submitting}
                          onClick={() => onDraftChange(unreviewCandidate(activeDraft, candidate))}
                        >
                          标为未审
                        </Button>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      )}

      <div className="psr-pagination" data-test="psr-pagination">
        {morePending ? (
          onLoadMore ? (
            <>
              <span className="psr-muted">还有 {remaining} 项候选未加载，全部候选可审之前不能提交。</span>
              <Button
                type="button"
                variant="outline"
                data-test="psr-load-more"
                disabled={loadingMore}
                onClick={() => void loadMore()}
              >
                {loadingMore ? "正在加载…" : `加载更多候选（剩余 ${remaining}）`}
              </Button>
            </>
          ) : (
            <p className="psr-warn" role="alert" data-test="psr-pagination-blocked">
              本页之外仍有候选，但未提供加载回调；为避免漏审，提交已停用。请传入完整包或提供 onLoadMore。
            </p>
          )
        ) : (
          <span className="psr-muted" data-test="psr-pagination-complete">已加载全部候选</span>
        )}
        {loadError ? (
          <p className="psr-error" role="alert" data-test="psr-load-error">{loadError}</p>
        ) : null}
      </div>

      <p className="psr-muted" data-test="psr-source-note">{SOURCE_LOAD_FAILURE_NOTE}</p>

      <label className="psr-field psr-package-rationale">
        <span>本包审核说明</span>
        <textarea
          data-test="psr-rationale"
          rows={3}
          value={activeDraft.rationale}
          disabled={submitting}
          placeholder="记录批量范围、总体理由或需要后手核对的服务端状态"
          onChange={(event) => updateDraft({ rationale: event.target.value })}
        />
      </label>
      <p className="psr-muted" data-test="psr-overlay-preview">
        将提交：默认 {assessmentLabel(activeDraft.defaultAssessment)} · 逐项例外 {overlayPreview.overrides.length} 项 ·
        未审 {coverage.unreviewed} 项
      </p>

      {error ? (
        <div className="psr-error" role="alert" data-test="psr-error">
          <p>{error}</p>
        </div>
      ) : null}
      {notice ? (
        <p className="psr-notice" role="status" data-test="psr-notice">{notice}</p>
      ) : null}
      {skipped ? (
        <p className="psr-skipped" role="status" data-test="psr-skipped">
          本项已暂时跳过，仍待审；没有提交决定。
        </p>
      ) : null}

      <div className="psr-actions" data-test="psr-action-bar">
        <Button
          type="button"
          variant="outline"
          data-test="psr-return"
          disabled={submitting}
          onClick={onReturn}
        >
          返回队列
        </Button>
        <Button
          type="button"
          variant="outline"
          data-test="psr-skip"
          disabled={submitting}
          onClick={() => void handleSkip()}
        >
          暂时跳过
        </Button>
        <Button
          type="button"
          data-test="psr-save-next"
          data-blocked-reason={
            coverage.unreviewed > 0
              ? "unreviewed"
              : morePending
                ? "more-candidates"
                : undefined
          }
          disabled={!canSubmit}
          onClick={() => void handleSubmit()}
        >
          {submitting ? "保存中…" : "保存并下一项"}
        </Button>
      </div>
    </section>
  );
}
