import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useStudioAuth } from "../../lib/studio-auth";
import { formatShortHash, listReviews, ReviewStatus, StudioApiError } from "../../lib/studio-api";
import { decisionLabel, jobStatusLabel, reviewLinkKindLabel, reviewStatusLabel } from "../../lib/studio-i18n";
import { signalLabel } from "../../lib/review-display";

function errorText(error: unknown): string {
  if (error instanceof StudioApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

function confidence(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

const FILTERS: Array<{ value: ReviewStatus | "all"; label: string }> = [
  { value: "open", label: "待处理" },
  { value: "resolved", label: "已处理" },
  { value: "dismissed", label: "已忽略" },
  { value: "all", label: "全部" },
];

export default function StudioReviewPage() {
  const auth = useStudioAuth();
  const authHeader = auth.authHeader();
  const [status, setStatus] = useState<ReviewStatus | "all">("open");
  const reviews = useQuery({
    queryKey: ["studio", "reviews", status],
    queryFn: () => listReviews(authHeader, status),
    refetchInterval: status === "open" || status === "all" ? 5000 : false,
  });

  const openCount = reviews.data?.filter((item) => item.status === "open").length ?? 0;

  return (
    <div className="studio-stack" data-view="studio-review">
      <div className="studio-page-heading">
        <div>
          <p className="studio-eyebrow">C1 · 人工消歧关口</p>
          <h1>人工审核队列</h1>
          <p className="studio-muted">
            系统把指向同一已发布身份/事件的重复问题组织成审核批次，但批次本身不代表同一身份；“证据不足，暂不确定”始终不会触发合并。
          </p>
        </div>
        <div className="studio-row-actions">
          <Badge>待处理 {openCount} 项</Badge>
          <Button variant="outline" onClick={() => void reviews.refetch()} disabled={reviews.isFetching}>
            {reviews.isFetching ? "刷新中…" : "刷新队列"}
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>消歧审核</CardTitle>
          <CardDescription>每一行代表一个需要人判断的语义审核主题；主题可以包含多个底层候选，但不会跨越未经证明的身份关系。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="studio-filter-row" role="group" aria-label="审核状态过滤">
            {FILTERS.map(({ value, label }) => (
              <Button key={value} size="sm" variant={status === value ? "default" : "outline"} onClick={() => setStatus(value)}>
                {label}
              </Button>
            ))}
          </div>

          {reviews.isLoading ? <p className="studio-muted">正在读取持久化审核项…</p> : null}
          {reviews.error ? <p className="studio-error">{errorText(reviews.error)}</p> : null}
          {reviews.data?.length === 0 ? <p className="studio-muted">当前筛选条件下没有消歧审核。</p> : null}

          <div className="studio-table" aria-label="人工消歧审核队列">
            {reviews.data?.map((review) => {
              const members = review.member_count ?? 1;
              const groups = review.group_count ?? 1;
              return (
                <div className="studio-table-row" key={review.review_id}>
                  <div className="studio-stack studio-stack-tight">
                    <div className="studio-row-title">
                      <Badge>{reviewStatusLabel(review.status)}</Badge>
                      <Badge>{reviewLinkKindLabel(review.link_kind)}</Badge>
                      <strong>{review.document.title}</strong>
                      <span className="studio-muted">第 {review.document.revision_no} 版</span>
                    </div>
                    <div>
                      <strong>{review.left_label ?? "已发布侧记录"}</strong>
                      <span className="studio-muted"> ↔ </span>
                      <strong>{review.right_label ?? "本次来源记录"}</strong>
                    </div>
                    <div className="studio-muted">
                      {groups > 1 ? `该审核批次包含 ${groups} 个来源候选组 / ${members} 个底层候选` : members > 1 ? `1 个来源候选组 / ${members} 个底层候选` : "1 个来源候选组 / 1 个底层候选"}
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
                    <Link className="studio-link-button" to={`/studio/review/${encodeURIComponent(review.review_id)}`}>查看并判断</Link>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
