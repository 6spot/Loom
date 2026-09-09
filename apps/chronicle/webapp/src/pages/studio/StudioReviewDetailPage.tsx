import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { useStudioAuth } from "../../lib/studio-auth";
import {
  getReview,
  listReviewPage,
  mutateJob,
  StudioApiError,
  submitReviewDecision,
} from "../../lib/studio-api";
import type {
  ReviewDecision,
  ReviewDetail,
  ReviewGroupDetail,
  ReviewGroupDecisionInput,
  ReviewRecordContext,
} from "../../lib/studio-api";
import { ReviewEvidenceSection } from "../../components/studio/ReviewEvidencePanel";
import {
  comparisonRows,
  decisionHelp,
  decisionLabel,
  formatLocator,
  formatReviewTime,
  roleLabel,
  signalLabel,
  stagedSideLabel,
  statusLabel,
  typeLabel,
} from "../../lib/review-display";
import type { HumanReviewContext } from "../../lib/review-display";
import {
  buildReviewSearch,
  countStillOpenSkipped,
  evaluateTailRescan,
  findNextAfterAnchor,
  parseReviewSearch,
  ReviewSessionStore,
  sanitizeDecision,
  sanitizeGroupOverrides,
  scopeKey,
} from "../../lib/review-session";
import type { ReviewScope, ReviewSortAnchor } from "../../lib/review-session";

function errorText(error: unknown): string {
  if (error instanceof StudioApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

function isNetworkFailure(error: unknown): boolean {
  if (error instanceof StudioApiError) return false;
  return error instanceof TypeError;
}

type GroupOverrideDraft = {
  enabled: boolean;
  decision: ReviewDecision | "";
  rationale: string;
  confidence: string;
};

function pretty(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function EvidenceList({ context }: { context: HumanReviewContext }) {
  const evidence = context.display?.evidence ?? [];
  return (
    <div className="studio-stack">
      <div>
        <strong>来源逐字证据</strong>
        <p className="studio-muted">仅展示当前暂存数据包中直接引用该记录的事实声明逐字证据；这些文字是人工判断的主要依据。</p>
      </div>
      {evidence.length ? (
        evidence.map((item) => (
          <div className="studio-run" key={`${item.claim_ref}:${item.text}`}>
            <p style={{ margin: 0, fontSize: "0.95rem", lineHeight: 1.7 }}>「{item.text}」</p>
            <p className="studio-muted" style={{ marginBottom: 0 }}>
              {formatLocator(item.locator)}
            </p>
          </div>
        ))
      ) : (
        <p className="studio-error-box">
          当前记录没有直接关联的事实声明逐字证据。不要仅凭名称、标题或内部 ID 合并；证据不足时应选择“证据不足，暂不确定”。
        </p>
      )}
    </div>
  );
}

function RecordCard({ label, context }: { label: string; context: ReviewRecordContext }) {
  const human = context as HumanReviewContext;
  const record = context.record ?? {};
  const display = human.display ?? {};
  const title = display.name ?? record.name ?? record.title ?? context.ref;
  const participants = display.participants ?? [];
  const places = display.places ?? [];
  const aliases = (display.aliases ?? []).map(String).filter(Boolean);
  const mentions = display.mentions ?? [];

  return (
    <Card>
      <CardHeader>
        <p className="studio-eyebrow">{label}</p>
        <CardTitle>{title}</CardTitle>
        <CardDescription>
          来源：{context.source_title ?? "未知来源"}
        </CardDescription>
      </CardHeader>
      <CardContent className="studio-stack">
        <dl className="studio-definition-list">
          <div><dt>记录类型</dt><dd>{typeLabel(display.type ?? record.type)}</dd></div>
          {display.time ? <div><dt>时间</dt><dd>{formatReviewTime(display.time)}</dd></div> : null}
          {aliases.length ? <div><dt>别名</dt><dd>{aliases.join("、")}</dd></div> : null}
          {mentions.length ? <div><dt>原文称呼</dt><dd>{mentions.join("、")}</dd></div> : null}
          {participants.length ? (
            <div>
              <dt>参与者</dt>
              <dd>{participants.map((item) => `${item.name}（${roleLabel(item.role)}）`).join("、")}</dd>
            </div>
          ) : null}
          {places.length ? <div><dt>地点</dt><dd>{places.map((item) => item.name).join("、")}</dd></div> : null}
          {display.summary ? (
            <div>
              <dt>记录摘要</dt>
              <dd>{display.summary}<span className="studio-muted">（摘要不是逐字证据）</span></dd>
            </div>
          ) : null}
        </dl>

        <EvidenceList context={human} />

        <details className="studio-details">
          <summary>技术详情 / 审计字段</summary>
          <p className="studio-muted">内部枚举、临时 ID 和原始 JSON 仅用于审计，不应作为人工合并依据。</p>
          <pre className="studio-code">{pretty({
            bundle: context.bundle,
            ref: context.ref,
            source_ref: context.source_ref,
            record,
          })}</pre>
        </details>
      </CardContent>
    </Card>
  );
}

export function CanonicalIdentityConflictNotice({
  error, reviewGroups = [],
}: { error: StudioApiError; reviewGroups?: ReviewGroupDetail[] }) {
  const details = error.details;
  const groups = details?.review_groups ?? [];
  const incoming = groups.length
    ? groups.map((group) => ({
      id: group.review_group_id,
      number: reviewGroups.findIndex((item) => item.review_group_id === group.review_group_id) + 1,
      contexts: group.right_contexts,
    }))
    : [{ id: "incoming", number: 0, contexts: details?.incoming_contexts ?? [] }];

  return (
    <section className="studio-error-box studio-stack" role="alert" aria-label="实体身份冲突">
      <strong>该判断无法提交</strong>
      <p>
        它会把当前来源实体同时连接到两个已经发布的实体。Chronicle 不允许在普通导入审核中合并两个既有实体。
        本次判断未保存，审核项仍待处理，之前的审核记录保持不变。
      </p>
      {details?.canonical_entities?.length ? (
        <div>
          <strong>涉及的已发布实体</strong>
          <ul className="studio-links">
            {details.canonical_entities.map((entity) => {
              const sources = [...new Set(entity.contexts.map((context) => context.source_title).filter(Boolean))];
              return (
                <li key={entity.canonical_id}>
                  {entity.names.join("、") || "未命名实体"}
                  {sources.length ? `（来源：${sources.join("、")}）` : ""}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {incoming.filter((group) => group.contexts.length).map((group) => {
        const names = [...new Set(group.contexts.map((context) => (
          (context as HumanReviewContext).display?.name ?? context.record?.name
        )).filter(Boolean))];
        return (
          <div className="studio-stack" key={group.id}>
            <strong>需调整的来源候选组{group.number > 0 ? ` ${group.number}` : ""}：{names.join("、") || "未命名记录"}</strong>
            {group.contexts.map((context) => (
              <div key={`${context.bundle}:${context.ref}`}>
                <p className="studio-muted">来源：{context.source_title ?? "未知来源"}</p>
                <EvidenceList context={context as HumanReviewContext} />
              </div>
            ))}
          </div>
        );
      })}
      <p>
        请选择其中一个已发布实体作为“同一实体”，其他候选请选择“不是同一实体”或“证据不足，暂不确定”。
        如果批次中只有部分候选组冲突，可点击“存在例外，展开逐组判断”，修改这些组后重新提交。
      </p>
      <details className="studio-details">
        <summary>冲突技术详情 / 审计字段</summary>
        <pre className="studio-code">{pretty(details ?? { code: error.code, message: error.message })}</pre>
      </details>
    </section>
  );
}

const ADVANCE_PAGE_LIMIT = 100;
const ADVANCE_MAX_PAGES = 25;

interface EndState {
  kind: "only-skipped" | "empty" | "refresh";
  stillOpenSkipped: number;
  openCount: number;
  observedAt: string;
}

function sessionStore(): ReviewSessionStore | null {
  try {
    if (typeof sessionStorage === "undefined") return null;
    return new ReviewSessionStore(sessionStorage);
  } catch {
    return null;
  }
}

export default function StudioReviewDetailPage() {
  const { reviewId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const scope = useMemo<ReviewScope>(() => parseReviewSearch(searchParams.toString()), [searchParams]);
  const traverseScope = useMemo<ReviewScope>(
    () => ({ status: "open", jobId: scope.jobId, linkKind: scope.linkKind }),
    [scope.jobId, scope.linkKind],
  );
  const auth = useStudioAuth();
  const authHeader = auth.authHeader();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const store = useMemo(() => sessionStore(), []);
  const review = useQuery({
    queryKey: ["studio", "review", reviewId],
    queryFn: () => getReview(authHeader, reviewId),
    enabled: Boolean(reviewId),
  });
  const item = review.data;
  const allowed = useMemo(() => item?.allowed_decisions ?? [], [item?.allowed_decisions]);
  const fingerprint = item?.plan_fingerprint ?? null;
  const [decision, setDecision] = useState<ReviewDecision | "">("");
  const [rationale, setRationale] = useState("");
  const [confidence, setConfidence] = useState("0.5");
  const [showExceptions, setShowExceptions] = useState(false);
  const [groupOverrides, setGroupOverrides] = useState<Record<string, GroupOverrideDraft>>({});
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [skippedVersion, setSkippedVersion] = useState(0);
  const [advancing, setAdvancing] = useState(false);
  const [advanceNote, setAdvanceNote] = useState("");
  const [contended, setContended] = useState<Array<{ id: string; status: string }>>([]);
  const [endState, setEndState] = useState<EndState | null>(null);
  const [lateNotice, setLateNotice] = useState<string | null>(null);
  const [unknownOutcome, setUnknownOutcome] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<string | null>(null);
  const advanceAfterRef = useRef(false);
  const submittingRef = useRef<{
    id: string;
    fingerprint: string | null;
    advance: boolean;
    anchor: ReviewSortAnchor;
  } | null>(null);
  const currentIdRef = useRef(reviewId);
  currentIdRef.current = reviewId;

  const formKey = `${reviewId}|${fingerprint ?? "-"}`;

  // Hydrate this review's isolated draft. Switching reviewId resets the whole
  // form (decision/rationale/confidence included), never just the group
  // overrides; an Entity→Event move sanitizes illegal carried values.
  useEffect(() => {
    if (!item) return;
    const stored = store?.loadDraft(reviewId, fingerprint);
    const allowedStrings = allowed as string[];
    if (stored) {
      const cleanOverrides = sanitizeGroupOverrides(stored.groupOverrides, allowedStrings);
      const clean: Record<string, GroupOverrideDraft> = {};
      for (const [groupId, draft] of Object.entries(cleanOverrides)) {
        clean[groupId] = {
          enabled: draft.enabled,
          decision: (draft.decision && allowedStrings.includes(draft.decision)
            ? draft.decision
            : sanitizeDecision(stored.decision, allowedStrings)) as ReviewDecision | "",
          rationale: draft.rationale,
          confidence: draft.confidence,
        };
      }
      setDecision(sanitizeDecision(stored.decision, allowedStrings) as ReviewDecision | "");
      setRationale(stored.rationale);
      setConfidence(stored.confidence);
      setShowExceptions(stored.showExceptions);
      setGroupOverrides(clean);
    } else {
      setDecision((allowedStrings[0] ?? "") as ReviewDecision | "");
      setRationale("");
      setConfidence("0.5");
      setShowExceptions(false);
      setGroupOverrides({});
    }
    setLoadedKey(formKey);
    setEndState(null);
    setLateNotice(null);
    setUnknownOutcome(false);
    setVerifyResult(null);
    setContended([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviewId, fingerprint, (allowed as string[]).join("|")]);

  // Persist the draft on every change; only success clears it.
  useEffect(() => {
    if (!item || loadedKey !== formKey) return;
    store?.saveDraft(reviewId, fingerprint, {
      decision,
      rationale,
      confidence,
      showExceptions,
      groupOverrides: Object.fromEntries(
        Object.entries(groupOverrides).map(([groupId, draft]) => [
          groupId,
          { enabled: draft.enabled, decision: draft.decision, rationale: draft.rationale, confidence: draft.confidence },
        ]),
      ),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [decision, rationale, confidence, showExceptions, groupOverrides, loadedKey]);

  const skipped = useMemo(
    () => new Set(store?.loadSkipped(traverseScope) ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scopeKey(traverseScope), skippedVersion],
  );

  const setGroupOverride = (groupId: string, patch: Partial<GroupOverrideDraft>) => {
    setGroupOverrides((current) => {
      const existing = current[groupId] ?? {
        enabled: false,
        decision: (decision || allowed[0] || "") as ReviewDecision | "",
        rationale: "",
        confidence: confidence || "0.5",
      };
      return { ...current, [groupId]: { ...existing, ...patch } };
    });
  };

  const canSubmit = useMemo(() => {
    const parsed = Number(confidence);
    const overridesValid = Object.values(groupOverrides).every((draft) => {
      if (!draft.enabled) return true;
      const groupConfidence = Number(draft.confidence);
      return Boolean(
        draft.decision &&
        allowed.includes(draft.decision as ReviewDecision) &&
        draft.rationale.trim() &&
        Number.isFinite(groupConfidence) &&
        groupConfidence >= 0 &&
        groupConfidence <= 1,
      );
    });
    return Boolean(
      item?.status === "open" &&
      decision &&
      allowed.includes(decision as ReviewDecision) &&
      rationale.trim() &&
      Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 &&
      overridesValid,
    );
  }, [allowed, confidence, decision, groupOverrides, item?.status, rationale]);

  const goToReview = (nextId: string) => {
    navigate(`/studio/review/${encodeURIComponent(nextId)}${buildReviewSearch(scope, nextId)}`);
  };

  const backToQueue = () => {
    navigate(`/studio/review${buildReviewSearch(scope, reviewId)}`);
  };

  const findNextThroughServer = async (
    fromAnchor: ReviewSortAnchor | null,
    extraSkipped?: ReadonlySet<string>,
  ): Promise<ReviewDetail | null> => {
    const handledElsewhere = new Set<string>();
    const collected: Array<{ reviewId: string; createdAt: string | null }> = [];
    let cursor: string | null = null;
    let openCount = 0;
    let observedAt = "";
    const excludedBase = extraSkipped ? new Set([...skipped, ...extraSkipped]) : skipped;
    for (let pageIndex = 0; pageIndex < ADVANCE_MAX_PAGES; pageIndex += 1) {
      setAdvanceNote(`正在寻找下一项…第 ${pageIndex + 1} 页`);
      const pageResult = await listReviewPage(authHeader, {
        status: "open",
        jobId: traverseScope.jobId,
        linkKind: traverseScope.linkKind,
        limit: ADVANCE_PAGE_LIMIT,
        cursor,
      });
      openCount = pageResult.open_count;
      observedAt = pageResult.observed_at;
      collected.push(
        ...pageResult.items.map((entry) => ({
          reviewId: entry.review_id,
          createdAt: entry.created_at,
        })),
      );
      const excluded = new Set([...excludedBase, ...handledElsewhere]);
      // Anchor comparison, not id lookup: the submitted review has left the
      // open queue, so a deep-page current id is absent from `collected` and
      // an index search would restart at the head.
      const candidate = findNextAfterAnchor(collected, fromAnchor, excluded);
      if (candidate) {
        // Another tab may have handled the candidate first: re-check its
        // server status and continue instead of submitting over it.
        const detail = await getReview(authHeader, candidate);
        if (detail.status === "open") {
          store?.saveOpenCursor(traverseScope, pageResult.next_cursor);
          return detail;
        }
        handledElsewhere.add(candidate);
        setContended((current) => [...current, { id: candidate, status: detail.status }]);
        continue;
      }
      if (!pageResult.next_cursor) {
        store?.saveOpenCursor(traverseScope, null);
        // Tail re-scan over the head-to-tail collection: late rows inserted
        // before the old cursor are found here. Handled-elsewhere ids are
        // excluded and reported instead of being submitted over.
        for (;;) {
          const outcome = evaluateTailRescan(
            collected.map((entry) => entry.reviewId),
            new Set([...excludedBase, ...handledElsewhere]),
          );
          if (outcome.kind === "next" && outcome.nextId) {
            const detail = await getReview(authHeader, outcome.nextId);
            if (detail.status === "open") return detail;
            handledElsewhere.add(outcome.nextId);
            setContended((current) => [...current, { id: outcome.nextId as string, status: detail.status }]);
            continue;
          }
          if (outcome.kind === "only-skipped") {
            setEndState({
              kind: "only-skipped",
              stillOpenSkipped: outcome.stillOpenSkipped,
              openCount,
              observedAt,
            });
          } else {
            setEndState({ kind: "empty", stillOpenSkipped: 0, openCount, observedAt });
          }
          return null;
        }
      }
      cursor = pageResult.next_cursor;
    }
    setEndState({
      kind: "refresh",
      stillOpenSkipped: countStillOpenSkipped(
        [...excludedBase],
        new Set(collected.map((entry) => entry.reviewId)),
      ),
      openCount,
      observedAt,
    });
    return null;
  };

  const advance = async (fromAnchor: ReviewSortAnchor | null, extraSkipped?: ReadonlySet<string>) => {
    if (advancing) return;
    setAdvancing(true);
    setAdvanceNote("正在寻找下一项…");
    try {
      const next = await findNextThroughServer(fromAnchor, extraSkipped);
      if (next) goToReview(next.review_id);
    } catch (error) {
      setAdvanceNote(`寻找下一项失败：${errorText(error)}。草稿已保留，可重试。`);
    } finally {
      setAdvancing(false);
    }
  };

  const decide = useMutation({
    mutationFn: async () => {
      const submitted = submittingRef.current;
      if (!item || !decision || !submitted) throw new Error("缺少审核判断");
      if (!window.confirm(`确认提交“${decisionLabel(decision)}”？提交后该审核项将作为审计历史保留，不能静默改写。`)) {
        throw new Error("已取消提交");
      }
      const reviewGroups = item.review_groups ?? [];
      const groupDecisions: ReviewGroupDecisionInput[] = reviewGroups.flatMap((group) => {
        const draft = groupOverrides[group.review_group_id];
        if (!draft?.enabled || !draft.decision) return [];
        return [{
          review_group_id: group.review_group_id,
          decision: draft.decision as ReviewDecision,
          rationale: draft.rationale.trim(),
          confidence: Number(draft.confidence),
        }];
      });
      return submitReviewDecision(
        authHeader,
        submitted.id,
        decision,
        rationale.trim(),
        Number(confidence),
        groupDecisions,
      );
    },
    onSuccess: async (updated) => {
      const submitted = submittingRef.current;
      submittingRef.current = null;
      setUnknownOutcome(false);
      if (submitted) store?.clearDraft(submitted.id, submitted.fingerprint);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["studio", "reviews"] }),
        queryClient.invalidateQueries({ queryKey: ["studio", "review", submitted?.id ?? reviewId] }),
        queryClient.invalidateQueries({ queryKey: ["studio", "job", updated.job_id] }),
      ]);
      // Late responses apply to their original review id, never the current form.
      if (!submitted || submitted.id !== currentIdRef.current) {
        setLateNotice(
          submitted
            ? `迟到响应已按原审核项 ${submitted.id} 处理，当前表单未受影响。`
            : "迟到响应已处理，当前表单未受影响。",
        );
        return;
      }
      if (submitted.advance) {
        await advance(submitted.anchor);
      }
    },
    onError: (error) => {
      submittingRef.current = null;
      // Every failure retains the draft (it is already persisted above).
      if (isNetworkFailure(error)) setUnknownOutcome(true);
    },
  });

  const submit = (advanceAfter: boolean) => {
    if (!canSubmit || decide.isPending || advancing || !item) return;
    advanceAfterRef.current = advanceAfter;
    // Capture the sort anchor BEFORE the POST: success removes this review
    // from the open queue, so the advance must continue after the anchor.
    submittingRef.current = {
      id: reviewId,
      fingerprint,
      advance: advanceAfter,
      anchor: { createdAt: item.created_at, reviewId: item.review_id },
    };
    decide.mutate();
  };

  const skipCurrent = async () => {
    if (!item || advancing || decide.isPending) return;
    // addSkipped returns the updated list synchronously: the advance below
    // must use it directly instead of the pre-click render's skipped set.
    const nextSkipped = new Set(store?.addSkipped(traverseScope, reviewId) ?? [reviewId]);
    setSkippedVersion((value) => value + 1);
    await advance({ createdAt: item.created_at, reviewId: item.review_id }, nextSkipped);
  };

  const verifyServerState = async () => {
    if (!reviewId || verifying) return;
    setVerifying(true);
    setVerifyResult(null);
    try {
      // Unknown transport outcome: ask the server instead of resubmitting.
      const detail = await getReview(authHeader, reviewId);
      await queryClient.invalidateQueries({ queryKey: ["studio", "review", reviewId] });
      if (detail.status !== "open") {
        store?.clearDraft(reviewId, fingerprint);
        const decided = detail.decision ? `（${decisionLabel(detail.decision.decision)}）` : "";
        setVerifyResult(`服务端显示该项已${statusLabel(detail.status)}${decided}；本地草稿已清理，可前往下一项。`);
      } else {
        setVerifyResult("服务端显示该项仍待处理；上次提交未生效，草稿已保留，可检查后重新提交。");
      }
    } catch (error) {
      setVerifyResult(`核对失败：${errorText(error)}。草稿已保留。`);
    } finally {
      setVerifying(false);
    }
  };

  const resume = useMutation({
    mutationFn: async () => {
      if (!item) throw new Error("缺少导入作业");
      if (!window.confirm("所有消歧审核已完成。确认通过控制平面恢复该导入作业？")) {
        throw new Error("已取消恢复");
      }
      return mutateJob(authHeader, item.job_id, "resume");
    },
    onSuccess: async (job) => {
      await queryClient.invalidateQueries({ queryKey: ["studio", "jobs"] });
      navigate(`/studio/imports/${encodeURIComponent(job.job_id)}`);
    },
  });

  const reviewMode = (item?.review_mode ?? null) as string | null;
  // Frozen record lookup for the evidence layers: every staged record the
  // detail projects is addressable by (bundle, ref). The evidence panels
  // reuse these objects and never build a second draft or queue. This hook
  // must stay above the early returns so the hook order never changes.
  const evidenceRecords = useMemo(() => {
    const map = new Map<string, HumanReviewContext>();
    const push = (context: unknown) => {
      const candidate = context as HumanReviewContext;
      if (candidate && typeof candidate.bundle === "string" && typeof candidate.ref === "string") {
        map.set(`${candidate.bundle}:${candidate.ref}`, candidate);
      }
    };
    if (item) {
      for (const context of [...(item.left_contexts ?? []), ...(item.right_contexts ?? []), item.left_context, item.right_context]) {
        push(context);
      }
      for (const group of item.review_groups ?? []) {
        for (const context of group.right_contexts ?? []) push(context);
      }
    }
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.review_id, item?.plan_fingerprint]);

  if (review.isLoading) return <p className="studio-muted">正在读取审核项…</p>;
  if (review.error) return <p className="studio-error">{errorText(review.error)}</p>;
  if (!item) return <p className="studio-muted">审核项不存在。</p>;

  const leftContexts = (item.left_contexts?.length ? item.left_contexts : [item.left_context]) as HumanReviewContext[];
  const rightContexts = (item.right_contexts?.length ? item.right_contexts : [item.right_context]) as HumanReviewContext[];
  const left = leftContexts[0];
  const right = rightContexts[0];
  const comparisons = comparisonRows(item.link_kind, left, right);
  const memberCount = item.member_count ?? 1;
  const reviewGroups = item.review_groups ?? [];
  const groupCount = item.group_count ?? (reviewGroups.length || 1);

  return (
    <div className="studio-stack" data-view="studio-review-detail">
      <div className="studio-page-heading">
        <div>
          <p className="studio-eyebrow">人工消歧</p>
          <h1>{item.link_kind === "entity" ? "实体是否同一身份" : "事件是否同一发生"}</h1>
          <p className="studio-muted">
            审核批次 {item.review_subject_id ?? item.candidate_id} · {groupCount} 个来源候选组 / {memberCount} 个底层候选
          </p>
        </div>
        <div className="studio-row-actions">
          <Badge>{statusLabel(item.status)}</Badge>
          <Badge>{statusLabel(item.job_status)}</Badge>
          <Link className="studio-link-button" to={`/studio/review${buildReviewSearch(scope, reviewId)}`}>返回审核队列</Link>
        </div>
      </div>

      {item.status !== "open" ? (
        <div className="studio-error-box studio-stack" role="status">
          <strong>该审核项已{statusLabel(item.status)}，不能再提交判断。</strong>
          {contended.length ? (
            <p>另一会话已先处理了本轮中的 {contended.length} 项（{contended.map((entry) => `${entry.id.slice(0, 8)}…:${entry.status}`).join("、")}），已自动跳过它们。</p>
          ) : null}
          {item.decision ? <p>服务端决定：{decisionLabel(item.decision.decision)}。已有记录不会被覆盖。</p> : null}
        </div>
      ) : null}
      {lateNotice ? <p className="studio-muted" role="status">{lateNotice}</p> : null}

      <Card>
        <CardHeader>
          <CardTitle>审核来源</CardTitle>
          <CardDescription>该审核项绑定到一个不可变文献修订和一个持久化导入作业。</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="studio-definition-list">
            <div><dt>文档</dt><dd>{item.document.title} · 第 {item.document.revision_no} 版</dd></div>
            <div><dt>文件</dt><dd>{item.document.filename}</dd></div>
            <div><dt>源文件哈希</dt><dd className="studio-mono">{item.document.source_sha256}</dd></div>
            <div><dt>导入作业</dt><dd><Link to={`/studio/imports/${encodeURIComponent(item.job_id)}`}>{item.job_id}</Link></dd></div>
            <div><dt>该作业待处理消歧</dt><dd>{item.job_open_resolution_reviews}</dd></div>
          </dl>
          <div className="studio-row-actions">
            <Link className="studio-link-button" to={`/studio/imports/${encodeURIComponent(item.job_id)}`}>查看导入作业</Link>
            <Link className="studio-link-button" to="/studio/sources">查看来源</Link>
          </div>
        </CardContent>
      </Card>

      {memberCount > 1 || groupCount > 1 ? (
        <Card>
          <CardHeader>
            <CardTitle>重复问题已整理为审核批次</CardTitle>
            <CardDescription>
              该批次包含 {groupCount} 个来源候选组 / {memberCount} 个底层候选。批次只是把指向同一个已发布身份或事件的问题集中展示，绝不表示这些来源候选组彼此已经被认定为同一实体或同一次事件。
            </CardDescription>
          </CardHeader>
          <CardContent className="studio-stack">
            <p className="studio-safe-note">
              默认情况下你可以对整个批次给出一个判断；如果其中某组证据不同，使用“存在例外，展开逐组判断”，只覆盖那个例外组。所有候选 ID、来源引用和证据都会继续保留在审计记录中。
            </p>
            {item.status === "open" && groupCount > 1 ? (
              <Button type="button" variant="outline" onClick={() => setShowExceptions((value) => !value)}>
                {showExceptions ? "收起逐组判断" : "存在例外，展开逐组判断"}
              </Button>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>关键对比</CardTitle>
          <CardDescription>这里只做字段对照和重合提示，不自动产生身份或事件合并结论。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="studio-table">
            {comparisons.map((row) => (
              <div className="studio-table-row" key={row.label}>
                <strong>{row.label}</strong>
                <span>{row.left}</span>
                <span>{row.right}</span>
                <Badge>{row.result}</Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <ReviewEvidenceSection
        auth={authHeader}
        reviewId={reviewId}
        planFingerprint={fingerprint}
        title="审核证据与来源"
        description={`该审核项共 ${item.source_contexts?.total ?? memberCount} 个候选来源。无直接事实声明、chapter_pair 两端与已发布批次的全部候选来源都在此逐一检查；译文仅供辅助参考。`}
        records={evidenceRecords}
      />

      <div className="studio-grid studio-grid-wide">
        <div className="studio-stack">
          {leftContexts.map((context, index) => (
            <RecordCard key={`${context.bundle}:${context.ref}`} label={leftContexts.length > 1 ? `${stagedSideLabel(reviewMode, "left")} ${index + 1}` : stagedSideLabel(reviewMode, "left")} context={context} />
          ))}
        </div>
        <div className="studio-stack">
          {rightContexts.map((context, index) => (
            <RecordCard key={`${context.bundle}:${context.ref}`} label={rightContexts.length > 1 ? `${stagedSideLabel(reviewMode, "right")} ${index + 1}` : stagedSideLabel(reviewMode, "right")} context={context} />
          ))}
        </div>
      </div>

      <div className="studio-grid studio-grid-wide">
        <Card>
          <CardHeader>
            <CardTitle>系统初始建议</CardTitle>
            <CardDescription>只作为辅助线索，不是历史身份权威；同名、同年或参与者重合都不能单独证明应当合并。</CardDescription>
          </CardHeader>
          <CardContent className="studio-stack">
            <dl className="studio-definition-list">
              <div><dt>建议</dt><dd><Badge>{decisionLabel(item.suggestion.decision)}</Badge></dd></div>
              <div><dt>建议置信度</dt><dd>{item.suggestion.confidence == null ? "—" : item.suggestion.confidence}</dd></div>
            </dl>
            {item.suggestion.signals.length ? (
              <div>
                <strong>系统发现的匹配信号</strong>
                <ul className="studio-links">
                  {item.suggestion.signals.map((signal, index) => <li key={index}>{signalLabel(signal)}</li>)}
                </ul>
              </div>
            ) : <p className="studio-muted">没有额外匹配信号。</p>}
            <details className="studio-details">
              <summary>查看原始系统建议 / 技术字段</summary>
              <pre className="studio-code">{pretty(item.suggestion)}</pre>
            </details>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>你的人工判断</CardTitle>
            <CardDescription>只根据上方来源证据作决定；“证据不足，暂不确定”不会触发合并。默认判断应用到未设置例外的候选组，逐组例外只覆盖对应组。</CardDescription>
          </CardHeader>
          <CardContent>
            {item.decision ? (
              <dl className="studio-definition-list">
                <div><dt>判断</dt><dd><Badge>{decisionLabel(item.decision.decision)}</Badge></dd></div>
                <div><dt>置信度</dt><dd>{item.decision.confidence}</dd></div>
                <div><dt>判断依据</dt><dd>{item.decision.rationale}</dd></div>
                {item.decision.group_decisions?.length ? (
                  <div>
                    <dt>逐组例外</dt>
                    <dd>{item.decision.group_decisions.map((group) => `${group.review_group_id}：${decisionLabel(group.decision)}（${group.rationale}）`).join("；")}</dd>
                  </div>
                ) : null}
                <div><dt>处理时间</dt><dd>{item.resolved_at ?? "—"}</dd></div>
              </dl>
            ) : (
              <form
                className="studio-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  submit(false);
                }}
              >
                <div>
                  <label className="studio-label" htmlFor="review-decision">你的判断</label>
                  <select
                    id="review-decision"
                    className="studio-select"
                    value={decision}
                    onChange={(event) => setDecision(event.target.value as ReviewDecision)}
                  >
                    {allowed.map((value) => <option key={value} value={value}>{decisionLabel(value)}</option>)}
                  </select>
                  {decision ? <p className="studio-muted">{decisionHelp(decision as ReviewDecision)}</p> : null}
                </div>
                <div>
                  <label className="studio-label" htmlFor="review-rationale">判断依据</label>
                  <textarea
                    id="review-rationale"
                    className="studio-textarea"
                    value={rationale}
                    onChange={(event) => setRationale(event.target.value)}
                    rows={5}
                    placeholder="写明你依据了哪些原文证据，以及为什么应合并、保持不同、判为相关但不同，或继续保持不确定。"
                  />
                </div>
                <div>
                  <label className="studio-label" htmlFor="review-confidence">判断置信度（0–1）</label>
                  <Input
                    id="review-confidence"
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    value={confidence}
                    onChange={(event) => setConfidence(event.target.value)}
                  />
                </div>

                {showExceptions && reviewGroups.length > 1 ? (
                  <div className="studio-stack">
                    <div>
                      <strong>逐组例外判断</strong>
                      <p className="studio-muted">只有你明确启用的候选组才覆盖上面的默认判断。未启用的组继续使用默认判断；这里的分组不是身份结论。</p>
                    </div>
                    {reviewGroups.map((group, index) => {
                      const draft = groupOverrides[group.review_group_id] ?? {
                        enabled: false,
                        decision: (decision || allowed[0] || "") as ReviewDecision | "",
                        rationale: "",
                        confidence: confidence || "0.5",
                      };
                      const names = group.right_contexts
                        .map((context) => {
                          const human = context as HumanReviewContext;
                          return human.display?.name ?? context.record?.name ?? context.record?.title ?? context.ref;
                        })
                        .filter(Boolean);
                      return (
                        <Card key={group.review_group_id}>
                          <CardHeader>
                            <CardTitle>候选组 {index + 1}：{names.join("、") || "未命名记录"}</CardTitle>
                            <CardDescription>{group.member_count} 个底层候选 · 组 ID {group.review_group_id}</CardDescription>
                          </CardHeader>
                          <CardContent className="studio-stack">
                            {group.right_contexts.map((context) => (
                              <EvidenceList key={`${group.review_group_id}:${context.bundle}:${context.ref}`} context={context as HumanReviewContext} />
                            ))}
                            <ReviewEvidenceSection
                              auth={authHeader}
                              reviewId={reviewId}
                              planFingerprint={fingerprint}
                              groupId={group.review_group_id}
                              title={`候选组 ${index + 1} 的逐组来源`}
                              description="该组全部成员的原文与分层证据；只看代表记录不能当作整组证明。"
                              records={evidenceRecords}
                            />
                            <Button
                              type="button"
                              variant={draft.enabled ? "default" : "outline"}
                              onClick={() => setGroupOverride(group.review_group_id, { enabled: !draft.enabled })}
                            >
                              {draft.enabled ? "取消此组例外，恢复默认判断" : "此组使用不同判断"}
                            </Button>
                            {draft.enabled ? (
                              <div className="studio-form">
                                <div>
                                  <label className="studio-label" htmlFor={`group-decision-${group.review_group_id}`}>此组判断</label>
                                  <select
                                    id={`group-decision-${group.review_group_id}`}
                                    className="studio-select"
                                    value={draft.decision}
                                    onChange={(event) => setGroupOverride(group.review_group_id, { decision: event.target.value as ReviewDecision })}
                                  >
                                    {allowed.map((value) => <option key={value} value={value}>{decisionLabel(value)}</option>)}
                                  </select>
                                </div>
                                <div>
                                  <label className="studio-label" htmlFor={`group-rationale-${group.review_group_id}`}>此组判断依据</label>
                                  <textarea
                                    id={`group-rationale-${group.review_group_id}`}
                                    className="studio-textarea"
                                    rows={3}
                                    value={draft.rationale}
                                    onChange={(event) => setGroupOverride(group.review_group_id, { rationale: event.target.value })}
                                    placeholder="说明为什么这一候选组与批次默认判断不同，并引用上方逐字证据。"
                                  />
                                </div>
                                <div>
                                  <label className="studio-label" htmlFor={`group-confidence-${group.review_group_id}`}>此组置信度（0–1）</label>
                                  <Input
                                    id={`group-confidence-${group.review_group_id}`}
                                    type="number"
                                    min="0"
                                    max="1"
                                    step="0.05"
                                    value={draft.confidence}
                                    onChange={(event) => setGroupOverride(group.review_group_id, { confidence: event.target.value })}
                                  />
                                </div>
                              </div>
                            ) : null}
                          </CardContent>
                        </Card>
                      );
                    })}
                  </div>
                ) : null}

                <Button type="submit" disabled={!canSubmit || decide.isPending || advancing}>
                  {decide.isPending && !advanceAfterRef.current ? "提交中…" : "确认并提交判断"}
                </Button>
              </form>
            )}
            {decide.error instanceof StudioApiError && decide.error.code === "canonical_identity_conflict" ? (
              <CanonicalIdentityConflictNotice error={decide.error} reviewGroups={reviewGroups} />
            ) : decide.error && errorText(decide.error) !== "已取消提交" ? (
              <p className="studio-error">{errorText(decide.error)}草稿已保留，可修改后重新提交。</p>
            ) : null}
            {unknownOutcome ? (
              <div className="studio-error-box studio-stack" role="alert">
                <strong>提交结果未知（网络中断或响应丢失）。</strong>
                <p>草稿已保留，没有自动重发。请先向服务端核对该项状态，再决定是否重新提交，以免覆盖已有记录。</p>
                <Button type="button" variant="outline" onClick={() => void verifyServerState()} disabled={verifying}>
                  {verifying ? "核对中…" : "向服务端核对当前项状态"}
                </Button>
              </div>
            ) : null}
            {verifyResult ? <p className="studio-muted" role="status">{verifyResult}</p> : null}
          </CardContent>
        </Card>
      </div>

      {endState ? (
        <Card>
          <CardHeader>
            <CardTitle>
              {endState.kind === "only-skipped"
                ? `本轮已查看，仍有 ${endState.stillOpenSkipped} 项暂时跳过`
                : endState.kind === "empty"
                  ? "当前范围暂无待审项"
                  : "本轮仍在变化，请刷新后继续"}
            </CardTitle>
            <CardDescription>
              {endState.kind === "only-skipped"
                ? "跳过项仍为待审并继续阻塞作业恢复；从队首重新开始可恢复它们。已处理记录不会被覆盖。"
                : endState.kind === "empty"
                  ? `服务端待审计数为 ${endState.openCount}。不得据此宣称整个导入完成。`
                  : `已翻页到上限仍未定位下一项（观察时间 ${endState.observedAt}）。并发范围持续变动时请刷新。`}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="studio-row-actions">
              <Button variant="outline" onClick={() => { setEndState(null); void advance(null); }}>重新从队首扫描</Button>
              <Button variant="outline" onClick={backToQueue}>返回队列</Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {item.status !== "open" && item.job_status === "needs_review" && item.job_open_resolution_reviews === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>消歧审核已全部完成</CardTitle>
            <CardDescription>所有消歧审核都已关闭；恢复仍由服务器控制平面校验，浏览器不能直接改写作业状态。</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => resume.mutate()} disabled={resume.isPending}>
              {resume.isPending ? "恢复中…" : "恢复导入作业"}
            </Button>
            {resume.error && errorText(resume.error) !== "已取消恢复" ? <p className="studio-error">{errorText(resume.error)}</p> : null}
          </CardContent>
        </Card>
      ) : null}

      <div className="studio-review-actionbar" role="toolbar" aria-label="连续审核操作">
        <div className="studio-review-actionbar-status">
          {decide.isPending ? "提交中…" : advancing ? advanceNote || "正在寻找下一项…" : "草稿自动保存在本标签页"}
          {skipped.size > 0 ? ` · 已跳过 ${skipped.size} 项` : ""}
        </div>
        <div className="studio-review-actionbar-buttons">
          <Button
            type="button"
            disabled={!canSubmit || decide.isPending || advancing || item.status !== "open"}
            onClick={() => submit(true)}
          >
            {decide.isPending && advanceAfterRef.current ? "提交中…" : "保存并下一项"}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={advancing || decide.isPending || item.status !== "open"}
            onClick={() => void skipCurrent()}
          >
            暂时跳过
          </Button>
          <Button type="button" variant="outline" onClick={backToQueue}>
            返回队列
          </Button>
        </div>
      </div>
    </div>
  );
}
