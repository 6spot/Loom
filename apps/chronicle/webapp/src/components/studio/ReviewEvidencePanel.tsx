// C2-R1-T12 review evidence panel.
//
// Contract owner: apps/chronicle/docs/review-workflow.md §§4–5.
// The panel receives a frozen SourceContext descriptor plus a loader and
// expands 原文片段 → 前后文 → 整章 without touching the T11 decision draft
// (review-session.ts) or the queue. All source text renders as plain React
// text nodes from server-cut highlight segments: never
// dangerouslySetInnerHTML, never browser-side UTF-16 slicing.

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "../ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/card";
import {
  createEvidenceRequestGuard,
  evidenceRequestKey,
  getReviewSourceChapterPage,
  getReviewSourceWindow,
  listReviewContexts,
  StudioApiError,
} from "../../lib/studio-api";
import type { EvidenceRequestGuard } from "../../lib/studio-api";
import type {
  ReviewSourceResponse,
  ReviewSourceSegment,
  SourceContextDescriptor,
} from "../../lib/studio-api";
import {
  evidenceChapterTitle,
  evidenceKindLabel,
  evidenceKindsLabel,
  evidenceRevisionLine,
  hasDirectClaimEvidence,
  isRenderableSegments,
  sourceFailureLabel,
  unavailableReasonLabel,
} from "../../lib/review-display";
import type { HumanReviewContext } from "../../lib/review-display";

function pretty(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function failureText(error: unknown): string {
  if (error instanceof StudioApiError) return sourceFailureLabel(error.code);
  if (error instanceof Error) return `原文加载失败（${error.message}）。已保留表单和已读材料，可重试。`;
  return "原文加载失败。已保留表单和已读材料，可重试。";
}

/** Plain-text rendering of one server-cut segment list. No HTML is parsed. */
export function EvidenceSegments({ segments }: { segments: ReviewSourceSegment[] }) {
  return (
    <p className="evidence-text">
      {segments.map((segment, index) =>
        segment.highlight ? (
          <mark key={index} className="evidence-hit">{segment.text}</mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </p>
  );
}

function AnchorAudit({ descriptor }: { descriptor: SourceContextDescriptor }) {
  return (
    <details className="studio-details">
      <summary>审计详情 / 内部标识</summary>
      <p className="studio-muted">内部 ID 与哈希仅用于审计，不能作为合并依据；相同文字在不同版本中属于不同来源。</p>
      <pre className="studio-code">{pretty({
        context_id: descriptor.context_id,
        bundle: descriptor.bundle,
        bundle_sha256: descriptor.bundle_sha256,
        record_ref: descriptor.record_ref,
        job_id: descriptor.job_id,
        revision_id: descriptor.revision_id,
        chapter_id: descriptor.chapter_id,
        chapter_index: descriptor.chapter_index,
        artifact_sha256: descriptor.artifact_sha256,
        source_sha256: descriptor.source_sha256,
        anchors: descriptor.anchors,
      })}</pre>
    </details>
  );
}

export interface ReviewEvidencePanelProps {
  auth: string | null;
  reviewId: string;
  planFingerprint: string | null;
  descriptor: SourceContextDescriptor;
  /** Linked staged record for the 直接Claim/出现分层；缺席时按 record_source 指引。 */
  record?: HumanReviewContext | null;
  defaultExpanded?: boolean;
}

export function ReviewEvidencePanel({
  auth,
  reviewId,
  planFingerprint,
  descriptor,
  record = null,
  defaultExpanded = false,
}: ReviewEvidencePanelProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [view, setView] = useState<"window" | "chapter">("window");
  const [anchorId, setAnchorId] = useState(descriptor.anchors[0]?.anchor_id ?? "");
  const [chapterPages, setChapterPages] = useState<ReviewSourceResponse[]>([]);
  const [chapterCursor, setChapterCursor] = useState<string | null>(null);
  const [chapterLoading, setChapterLoading] = useState(false);
  const [chapterError, setChapterError] = useState<unknown>(null);
  const [chapterExhausted, setChapterExhausted] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const savedScroll = useRef(0);
  // Stale-response guard: a late chapter page from a closed anchor, context
  // or review may never append under the current header. Every identity
  // transition invalidates outstanding flights; only the current token
  // writes state.
  const guardRef = useRef<EvidenceRequestGuard | null>(null);
  if (guardRef.current === null) guardRef.current = createEvidenceRequestGuard();
  const guard = guardRef.current;

  // The artifact is part of the identity: the backend binds context_id only
  // to (review_id, bundle, ref), so a re-accepted artifact keeps the same
  // context/anchor with different source material.
  const artifactSha256 = descriptor.artifact_sha256 ?? null;
  const currentKey = evidenceRequestKey(reviewId, planFingerprint, descriptor.context_id, anchorId, artifactSha256);

  // Switching review/plan/context/artifact/anchor resets chapter pagination
  // so the previous chapter's pages can never appear under the new header,
  // and invalidates any flight that is still in the air for the old
  // identity.
  useEffect(() => {
    guard.invalidate();
    setChapterPages([]);
    setChapterCursor(null);
    setChapterError(null);
    setChapterExhausted(false);
    // A stale flight's finally-block must not own this flag afterwards: the
    // new identity starts idle so its own loads are never blocked.
    setChapterLoading(false);
    setView("window");
    setAnchorId(descriptor.anchors[0]?.anchor_id ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewId, planFingerprint, descriptor.context_id, artifactSha256, descriptor.anchors]);

  // Anchor switches invalidate outstanding chapter flights as well: the
  // select handler below also invalidates synchronously to close the gap
  // between the state update and this effect.
  useEffect(() => {
    guard.invalidate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchorId]);

  const windowQuery = useQuery({
    queryKey: ["studio", "review-source", currentKey, "window"],
    queryFn: () => getReviewSourceWindow(auth, reviewId, anchorId),
    enabled: expanded && view === "window" && descriptor.available && Boolean(anchorId),
    staleTime: 60_000,
    // A 409 source_mismatch/source_unavailable is a versioned verdict, not a
    // transient blip: surface it at once with its retry affordance instead of
    // spending the global refetch on the same frozen anchor.
    retry: false,
  });

  const toggle = () => {
    if (!expanded) {
      savedScroll.current = typeof window === "undefined" ? 0 : window.scrollY;
      setExpanded(true);
    } else {
      setExpanded(false);
      // Restore the trigger position and keyboard focus; never jump to the
      // page top and never touch the T11 decision draft.
      requestAnimationFrame(() => {
        if (typeof window !== "undefined") window.scrollTo({ top: savedScroll.current });
        triggerRef.current?.focus({ preventScroll: true });
      });
    }
  };

  const loadChapterPage = async (cursor: string | null) => {
    if (chapterLoading || !anchorId) return;
    // The token binds this flight to the current anchor/context/review: any
    // identity transition invalidates the guard first, so a late page for
    // the old anchor can never append under the new one.
    const token = guard.issue();
    const anchorAtIssue = anchorId;
    setChapterLoading(true);
    setChapterError(null);
    try {
      const page = await getReviewSourceChapterPage(auth, reviewId, anchorAtIssue, { cursor });
      // Drop the response when the panel moved on while it was in flight.
      if (!guard.isCurrent(token)) return;
      if (!isRenderableSegments(page.segments)) throw new Error("服务端返回的原文片段形状无效");
      setChapterPages((current) => [...current, page]);
      setChapterCursor(page.next_cursor);
      setChapterExhausted(!page.has_more);
      if (view !== "chapter") setView("chapter");
    } catch (error) {
      if (!guard.isCurrent(token)) return;
      setChapterError(error);
    } finally {
      if (guard.isCurrent(token)) setChapterLoading(false);
    }
  };

  const retryWindow = () => {
    void windowQuery.refetch();
  };

  const directClaim = record && hasDirectClaimEvidence(record);
  const mentions = record?.display?.mentions ?? [];
  const translationNote = descriptor.evidence_kinds.includes("translation");

  return (
    <div className="evidence-panel" data-evidence-context={descriptor.context_id}>
      <div className="evidence-panel-head">
        <div>
          <strong>{evidenceChapterTitle(descriptor)}</strong>
          <p className="studio-muted">
            来源：{descriptor.source_title ?? "未知来源"} · {evidenceKindsLabel(descriptor.evidence_kinds)} · {evidenceRevisionLine(descriptor)}
          </p>
        </div>
        <Button ref={triggerRef} type="button" variant="outline" onClick={toggle} aria-expanded={expanded}>
          {expanded ? "收起原文" : "展开原文"}
        </Button>
      </div>

      {expanded ? (
        <div className="evidence-panel-body">
          {!descriptor.available ? (
            <p className="studio-error-box" role="status">
              {unavailableReasonLabel(descriptor.unavailable_reason)}
              原有表单与已读材料不受影响。
            </p>
          ) : null}

          {descriptor.available && descriptor.anchors.length > 1 ? (
            <div>
              <label className="studio-label" htmlFor={`evidence-anchor-${descriptor.context_id}`}>定位锚点（同组多个出现位置分别可查）</label>
              <select
                id={`evidence-anchor-${descriptor.context_id}`}
                className="studio-select"
                value={anchorId}
                onChange={(event) => {
                  // Invalidate synchronously: a chapter flight for the old
                  // anchor must not survive the switch even before the
                  // anchorId effect above runs. The new anchor starts idle.
                  guard.invalidate();
                  setAnchorId(event.target.value);
                  setChapterPages([]);
                  setChapterCursor(null);
                  setChapterError(null);
                  setChapterExhausted(false);
                  setChapterLoading(false);
                }}
              >
                {descriptor.anchors.map((anchor) => (
                  <option key={anchor.anchor_id} value={anchor.anchor_id}>{anchor.anchor_id}</option>
                ))}
              </select>
            </div>
          ) : null}

          {descriptor.available && anchorId ? (
            <div className="evidence-view-switch" role="group" aria-label="原文展开层级">
              <Button type="button" variant={view === "window" ? "default" : "outline"} onClick={() => setView("window")}>
                原文片段·前后文
              </Button>
              <Button
                type="button"
                variant={view === "chapter" ? "default" : "outline"}
                onClick={() => (chapterPages.length ? setView("chapter") : void loadChapterPage(null))}
              >
                整章阅读
              </Button>
            </div>
          ) : null}

          {descriptor.available && anchorId && view === "window" ? (
            <div>
              {windowQuery.isPending ? <p className="studio-muted">正在加载原文片段…</p> : null}
              {windowQuery.error ? (
                <div className="studio-error-box studio-stack" role="alert">
                  <span>{failureText(windowQuery.error)}</span>
                  <Button type="button" variant="outline" onClick={retryWindow}>重试加载原文</Button>
                </div>
              ) : null}
              {windowQuery.data && isRenderableSegments(windowQuery.data.segments) ? (
                <EvidenceSegments segments={windowQuery.data.segments} />
              ) : null}
            </div>
          ) : null}

          {descriptor.available && anchorId && view === "chapter" ? (
            <div className="studio-stack">
              {chapterPages.map((page, index) => (
                <div key={`${page.bounds.slice_start}:${page.bounds.slice_end}:${index}`}>
                  {isRenderableSegments(page.segments) ? <EvidenceSegments segments={page.segments} /> : null}
                </div>
              ))}
              {chapterError ? (
                <div className="studio-error-box studio-stack" role="alert">
                  <span>{failureText(chapterError)}</span>
                  <Button type="button" variant="outline" onClick={() => void loadChapterPage(chapterCursor)}>
                    重试加载本页
                  </Button>
                </div>
              ) : null}
              {chapterLoading ? <p className="studio-muted">正在加载整章分页…</p> : null}
              {!chapterExhausted && !chapterError ? (
                <Button type="button" variant="outline" onClick={() => void loadChapterPage(chapterCursor)} disabled={chapterLoading}>
                  {chapterPages.length ? "分页续读（还有未完内容）" : "从章首开始整章阅读"}
                </Button>
              ) : null}
              {chapterExhausted && chapterPages.length ? <p className="studio-muted">已读完本章全部内容。</p> : null}
              {!chapterExhausted && chapterPages.length ? <p className="studio-muted">本章还有未完分页，当前不是全文。</p> : null}
            </div>
          ) : null}

          <div className="evidence-layers">
            <div>
              <strong>直接引用的事实声明</strong>
              {directClaim ? (
                <ul className="studio-links">
                  {(record?.display?.evidence ?? []).map((item) => (
                    <li key={item.claim_ref}>「{item.text}」</li>
                  ))}
                </ul>
              ) : (
                <p className="studio-muted">
                  该记录没有直接关联的事实声明。请使用下方记录来源原文或对象出现材料核对；不要仅凭名称合并，证据不足时保持不确定。
                </p>
              )}
            </div>
            <div>
              <strong>对象在原文中的出现</strong>
              {mentions.length ? (
                <p className="studio-muted">{mentions.join("、")}</p>
              ) : (
                <p className="studio-muted">以记录来源（record_source）原文为准；译文不是逐字证据。</p>
              )}
            </div>
            <div>
              <strong>事件背景与辅助译文</strong>
              <p className="studio-muted">
                {descriptor.evidence_kinds.map((kind) => evidenceKindLabel(kind)).join("、")}
                {translationNote ? "。白话译文仅供辅助参考，不是逐字证据。" : "。"}
              </p>
            </div>
          </div>

          <AnchorAudit descriptor={descriptor} />
        </div>
      ) : null}
    </div>
  );
}

export interface ReviewEvidenceSectionProps {
  auth: string | null;
  reviewId: string;
  planFingerprint: string | null;
  groupId?: string | null;
  title: string;
  description: string;
  records?: Map<string, HumanReviewContext | null>;
}

/**
 * One group (or the whole frozen member set when groupId is null) of source
 * contexts. The first page loads immediately; remaining members load only
 * through an explicit affordance that names the outstanding count, so a
 * representative record is never presented as the whole group.
 */
export function ReviewEvidenceSection({
  auth,
  reviewId,
  planFingerprint,
  groupId = null,
  title,
  description,
  records,
}: ReviewEvidenceSectionProps) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [items, setItems] = useState<SourceContextDescriptor[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [exhausted, setExhausted] = useState(false);
  const groupKey = `${reviewId}|${planFingerprint ?? "-"}|${groupId ?? "-"}`;

  const firstPage = useQuery({
    queryKey: ["studio", "review-contexts", groupKey, "first"],
    queryFn: () => listReviewContexts(auth, reviewId, { groupId, limit: 50 }),
    enabled: Boolean(reviewId),
    staleTime: 60_000,
  });

  useEffect(() => {
    setCursor(firstPage.data?.next_cursor ?? null);
    setItems(firstPage.data?.items ?? []);
    setTotal(firstPage.data?.total ?? null);
    setExhausted(firstPage.data ? !firstPage.data.has_more : false);
  }, [firstPage.data]);

  const sectionGuardRef = useRef<EvidenceRequestGuard | null>(null);
  if (sectionGuardRef.current === null) sectionGuardRef.current = createEvidenceRequestGuard();
  const sectionGuard = sectionGuardRef.current;

  const [expanding, setExpanding] = useState(false);
  const [expandError, setExpandError] = useState<unknown>(null);

  useEffect(() => {
    // A group/review transition drops the previous group's state and
    // invalidates its in-flight pagination: old members may never append
    // into the new group's list. The new group starts idle.
    sectionGuard.invalidate();
    setCursor(null);
    setItems([]);
    setTotal(null);
    setExhausted(false);
    setExpanding(false);
    setExpandError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupKey]);

  const expandAll = async () => {
    if (expanding || exhausted) return;
    // Bind this pagination run to the group/review that started it.
    const token = sectionGuard.issue();
    setExpanding(true);
    setExpandError(null);
    try {
      // Reuse the frozen member list: every remaining page is fetched with
      // the group-bound cursor, never by name search or latest revision.
      let next: string | null = cursor;
      const extra: SourceContextDescriptor[] = [];
      while (next) {
        const page = await listReviewContexts(auth, reviewId, { groupId, limit: 50, cursor: next });
        if (!sectionGuard.isCurrent(token)) return;
        extra.push(...page.items);
        next = page.has_more ? page.next_cursor : null;
      }
      if (!sectionGuard.isCurrent(token)) return;
      setItems((current) => [...current, ...extra]);
      setCursor(null);
      setExhausted(true);
    } catch (error) {
      if (!sectionGuard.isCurrent(token)) return;
      setExpandError(error);
    } finally {
      // The busy flag carries no group data, so clearing it is safe even
      // for a stale run; only the member writes above are guarded.
      setExpanding(false);
    }
  };

  const remaining = total != null ? Math.max(total - items.length, 0) : 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="studio-stack">
        {firstPage.isPending ? <p className="studio-muted">正在加载来源描述…</p> : null}
        {firstPage.error ? (
          <div className="studio-error-box studio-stack" role="alert">
            <span>来源描述加载失败。已保留表单和已读材料，可重试。</span>
            <Button type="button" variant="outline" onClick={() => void firstPage.refetch()}>重试加载来源</Button>
          </div>
        ) : null}
        {total != null ? (
          <p className="studio-muted" role="status">
            已加载 {items.length} / 共 {total} 个候选来源{remaining > 0 ? "（当前不是全部，不能把已加载当作整组证明）" : "（已全部加载）"}
          </p>
        ) : null}
        {items.map((descriptor) => (
          <ReviewEvidencePanel
            key={descriptor.context_id}
            auth={auth}
            reviewId={reviewId}
            planFingerprint={planFingerprint}
            descriptor={descriptor}
            record={records?.get(`${descriptor.bundle}:${descriptor.record_ref}`) ?? null}
          />
        ))}
        {!exhausted && total != null && remaining > 0 ? (
          <div className="studio-stack">
            {expandError ? <p className="studio-error">展开全部成员失败，可重试；已加载材料不受影响。</p> : null}
            <Button type="button" variant="outline" onClick={() => void expandAll()} disabled={expanding}>
              {expanding ? "正在展开…" : `展开全部成员（剩余 ${remaining} 个）`}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
