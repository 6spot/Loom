import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { useStudioAuth } from "../../lib/studio-auth";
import { formatShortHash, listReviewPage, StudioApiError } from "../../lib/studio-api";
import type { ReviewStatus } from "../../lib/studio-api";
import { decisionLabel, jobStatusLabel, reviewLinkKindLabel, reviewStatusLabel } from "../../lib/studio-i18n";
import { signalLabel } from "../../lib/review-display";
import {
  buildReviewSearch,
  parseReviewSearch,
  ReviewSessionStore,
  scopeAllowsLinkKind,
  scopeKey,
} from "../../lib/review-session";
import type { ReviewScope, ReviewScopeStatus } from "../../lib/review-session";
import type { ReviewScope as ReviewQueueScope } from "../../lib/person-state-types";

function errorText(error: unknown): string {
  if (error instanceof StudioApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

function confidence(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

const STATUS_FILTERS: Array<{ value: ReviewScopeStatus; label: string }> = [
  { value: "open", label: "待处理" },
  { value: "resolved", label: "已处理" },
  { value: "dismissed", label: "已忽略" },
  { value: "all", label: "全部" },
];

const KIND_FILTERS: Array<{ value: ReviewScope["linkKind"]; label: string }> = [
  { value: null, label: "全部种类" },
  { value: "entity", label: "实体身份" },
  { value: "event", label: "事件发生" },
];

// §5.1 queue family. The page default is `all` (resolution + narrative +
// person_state); switching family clears link_kind because it only belongs to
// the resolution queue.
const SCOPE_FILTERS: Array<{ value: ReviewQueueScope; label: string }> = [
  { value: "all", label: "全部范围" },
  { value: "resolution", label: "身份／综合内容" },
  { value: "person_state", label: "阶段依据" },
];

const PAGE_LIMIT = 50;

function sessionStore(): ReviewSessionStore | null {
  try {
    if (typeof sessionStorage === "undefined") return null;
    return new ReviewSessionStore(sessionStorage);
  } catch {
    return null;
  }
}

export default function StudioReviewPage() {
  const auth = useStudioAuth();
  const authHeader = auth.authHeader();
  const [searchParams, setSearchParams] = useSearchParams();
  const scope = useMemo<ReviewScope>(
    () => parseReviewSearch(searchParams.toString()),
    [searchParams],
  );
  const currentId = useMemo(
    () => parseReviewSearch(searchParams.toString()).currentId,
    [searchParams],
  );
  const store = useMemo(() => sessionStore(), []);
  const [jobInput, setJobInput] = useState(scope.jobId ?? "");
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorTrail, setCursorTrail] = useState<Array<string | null>>([]);

  useEffect(() => {
    setJobInput(scope.jobId ?? "");
  }, [scope.jobId]);

  // Refresh / back / forward restores the same scope and list position.
  // The open-traversal cursor is never reused here: only the saved list
  // return position is restored, and only once per scope.
  useEffect(() => {
    setCursor(null);
    setCursorTrail([]);
    const saved = store?.loadListPosition(scope);
    if (saved?.cursor) setCursor(saved.cursor);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKey(scope)]);

  const page = useQuery({
    queryKey: ["studio", "reviews", "page", scopeKey(scope), cursor],
    queryFn: () =>
      listReviewPage(authHeader, {
        status: scope.status as ReviewStatus | "all",
        jobId: scope.jobId,
        linkKind: scope.linkKind,
        reviewScope: scope.reviewScope,
        limit: PAGE_LIMIT,
        cursor,
      }),
    refetchInterval: scope.status === "open" || scope.status === "all" ? 8000 : false,
  });

  useEffect(() => {
    if (page.data) {
      store?.saveListPosition(scope, {
        cursor,
        anchorId: page.data.items[0]?.review_id ?? currentId,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page.data, cursor]);

  const applyScope = (next: ReviewScope) => {
    setCursor(null);
    setCursorTrail([]);
    setSearchParams(new URLSearchParams(buildReviewSearch(next).slice(1)), { replace: false });
  };

  const items = page.data?.items ?? [];
  const skippedCount = store?.loadSkipped(scope).length ?? 0;

  return (
    <div className="studio-stack" data-view="studio-review">
      <div className="studio-page-heading">
        <div>
          <p className="studio-eyebrow">身份与内容审核</p>
          <h1>人工审核队列</h1>
          <p className="studio-muted">
            身份审核判断是否同一人或同一次事件；事实核对比较具体记载；正文审核决定最终叙述与阅读入口。每种决定分别保留。
          </p>
        </div>
        <div className="studio-row-actions">
          <Badge>待处理 {page.data?.open_count ?? "…"} 项</Badge>
          <Button variant="outline" onClick={() => void page.refetch()} disabled={page.isFetching}>
            {page.isFetching ? "刷新中…" : "刷新队列"}
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>待核对内容</CardTitle>
          <CardDescription>选择一个审核项查看完整上下文，可在页底保存并继续下一项。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="studio-filter-row" role="group" aria-label="审核状态过滤">
            {STATUS_FILTERS.map(({ value, label }) => (
              <Button key={value} size="sm" variant={scope.status === value ? "default" : "outline"} onClick={() => applyScope({ ...scope, status: value })}>
                {label}
              </Button>
            ))}
          </div>
          <div className="studio-filter-row" role="group" aria-label="审核范围过滤">
            {SCOPE_FILTERS.map(({ value, label }) => (
              <Button
                key={value}
                size="sm"
                variant={scope.reviewScope === value ? "default" : "outline"}
                onClick={() =>
                  applyScope({
                    ...scope,
                    reviewScope: value,
                    linkKind: scopeAllowsLinkKind(value) ? scope.linkKind : null,
                  })
                }
              >
                {label}
              </Button>
            ))}
          </div>
          {scope.reviewScope === "resolution" ? (
            <div className="studio-filter-row" role="group" aria-label="审核种类过滤">
              {KIND_FILTERS.map(({ value, label }) => (
                <Button
                  key={label}
                  size="sm"
                  variant={scope.linkKind === value ? "default" : "outline"}
                  onClick={() => applyScope({ ...scope, linkKind: value })}
                >
                  {label}
                </Button>
              ))}
            </div>
          ) : null}
          <form
            className="studio-inline-form"
            onSubmit={(event) => {
              event.preventDefault();
              const trimmed = jobInput.trim();
              applyScope({ ...scope, jobId: trimmed ? trimmed : null });
            }}
          >
            <Input
              aria-label="按导入作业过滤"
              placeholder="按 job_id 过滤（留空为全部作业）"
              value={jobInput}
              onChange={(event) => setJobInput(event.target.value)}
            />
            <Button type="submit" size="sm" variant="outline">应用作业范围</Button>
          </form>
          {skippedCount > 0 && scope.status === "open" ? (
            <p className="studio-muted">本轮已暂时跳过 {skippedCount} 项（仍为待审，不阻塞外，只影响本轮导航）。</p>
          ) : null}

          {page.isLoading ? <p className="studio-muted">正在读取持久化审核项…</p> : null}
          {page.error ? <p className="studio-error">{errorText(page.error)}</p> : null}
          {page.data && items.length === 0 ? <p className="studio-muted">当前筛选条件下没有消歧审核。</p> : null}

          <div className="studio-table" aria-label="人工消歧审核队列">
            {items.map((review) => {
              const members = review.member_count ?? 1;
              const groups = review.group_count ?? 1;
              return (
                <div
                  className="studio-table-row"
                  key={review.review_id}
                  data-current={review.review_id === currentId ? "true" : undefined}
                >
                  <div className="studio-stack studio-stack-tight">
                    <div className="studio-row-title">
                      <Badge>{reviewStatusLabel(review.status)}</Badge>
                      <Badge>{review.scope === "narrative" ? (review.narrative_kind === "facts" ? "事实核对" : "综合正文") : review.scope === "person_state" ? "阶段依据" : reviewLinkKindLabel(review.link_kind)}</Badge>
                      <strong>{review.document.title}</strong>
                      <span className="studio-muted">第 {review.document.revision_no} 版</span>
                      {review.review_id === currentId ? <Badge>上次位置</Badge> : null}
                    </div>
                    <div>
                      <strong>{review.left_label ?? "已发布侧记录"}</strong>
                      {review.scope !== "narrative" ? <><span className="studio-muted"> ↔ </span><strong>{review.right_label ?? "本次来源记录"}</strong></> : null}
                    </div>
                    <div className="studio-muted">
                      {review.scope === "narrative" ? "完整章节语境 · 结论、依据与版本固定" : groups > 1 ? `该审核批次包含 ${groups} 个来源候选组 / ${members} 个底层候选` : members > 1 ? `1 个来源候选组 / ${members} 个底层候选` : "1 个来源候选组 / 1 个底层候选"}
                      {review.suggestion.decision ? ` · 系统建议：${decisionLabel(review.suggestion.decision)}` : ""}
                      {review.suggestion.confidence == null ? "" : ` · 建议置信度 ${confidence(review.suggestion.confidence)}`}
                      {review.decision ? ` · 已选择：${decisionLabel(review.decision.decision)}` : ""}
                    </div>
                    {review.suggestion.signals.length ? (
                      <div className="studio-muted">匹配信号：{review.suggestion.signals.map(signalLabel).join(" · ")}</div>
                    ) : null}
                    <details className="studio-details">
                      <summary>技术详情 / 审计字段</summary>
                      <div className="studio-muted studio-mono">
                        主题 {review.review_subject_id ?? "legacy"} · 候选 {review.candidate_id} · 解析批次 {formatShortHash(review.resolution_sha256)}
                      </div>
                    </details>
                  </div>
                  <div className="studio-row-actions">
                    <Badge>{jobStatusLabel(review.job_status)}</Badge>
                    <Link className="studio-link-button" to={`/studio/imports/${encodeURIComponent(review.job_id)}`}>查看导入作业</Link>
                    <Link
                      className="studio-link-button"
                      to={`/studio/review/${encodeURIComponent(review.review_id)}${buildReviewSearch(scope, review.review_id)}`}
                    >
                      查看并判断
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>

          {page.data ? (
            <div className="studio-row-actions studio-pagination">
              <Button
                size="sm"
                variant="outline"
                disabled={cursorTrail.length === 0 || page.isFetching}
                onClick={() => {
                  const trail = [...cursorTrail];
                  const previous = trail.pop() ?? null;
                  setCursorTrail(trail);
                  setCursor(previous);
                }}
              >
                上一页
              </Button>
              <span className="studio-muted">
                本页 {items.length} 项 · 当前范围待审 {page.data.open_count} 项 · 观察时间 {page.data.observed_at}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={!page.data.next_cursor || page.isFetching}
                onClick={() => {
                  if (!page.data?.next_cursor) return;
                  setCursorTrail((trail) => [...trail, cursor]);
                  setCursor(page.data.next_cursor);
                }}
              >
                下一页
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
