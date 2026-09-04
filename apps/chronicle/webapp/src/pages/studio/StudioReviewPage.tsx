import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useStudioAuth } from "../../lib/studio-auth";
import { formatShortHash, listReviews, ReviewStatus, StudioApiError } from "../../lib/studio-api";

function errorText(error: unknown): string {
  if (error instanceof StudioApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

function confidence(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

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
          <p className="studio-eyebrow">C1 · human resolution gate</p>
          <h1>Review Queue</h1>
          <p className="studio-muted">
            模型只提出候选与保守建议；Entity/Event 是否合并必须由管理员显式决定。uncertain 始终是一等决策，不会被置信度自动升级为历史身份事实。
          </p>
        </div>
        <div className="studio-row-actions">
          <Badge>{openCount} open</Badge>
          <Button variant="outline" onClick={() => void reviews.refetch()} disabled={reviews.isFetching}>
            {reviews.isFetching ? "刷新中…" : "刷新队列"}
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Resolution reviews</CardTitle>
          <CardDescription>仅显示 C1-T8 resolution-scoped ReviewItems；chunk failure / quality flag 不在此工作台处理。</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="studio-filter-row" role="group" aria-label="Review 状态过滤">
            {(["open", "resolved", "dismissed", "all"] as const).map((value) => (
              <Button
                key={value}
                size="sm"
                variant={status === value ? "default" : "outline"}
                onClick={() => setStatus(value)}
              >
                {value}
              </Button>
            ))}
          </div>

          {reviews.isLoading ? <p className="studio-muted">正在读取 durable ReviewItems…</p> : null}
          {reviews.error ? <p className="studio-error">{errorText(reviews.error)}</p> : null}
          {reviews.data?.length === 0 ? (
            <p className="studio-muted">当前过滤条件下没有 resolution review。</p>
          ) : null}

          <div className="studio-table" aria-label="Resolution review queue">
            {reviews.data?.map((review) => (
              <div className="studio-table-row" key={review.review_id}>
                <div className="studio-stack studio-stack-tight">
                  <div className="studio-row-title">
                    <Badge>{review.status}</Badge>
                    <Badge>{review.link_kind}</Badge>
                    <strong>{review.document.title}</strong>
                    <span className="studio-muted">r{review.document.revision_no}</span>
                  </div>
                  <div>
                    <span className="studio-mono">{review.left.bundle}/{review.left.ref}</span>
                    <span className="studio-muted"> ↔ </span>
                    <span className="studio-mono">{review.right.bundle}/{review.right.ref}</span>
                  </div>
                  <div className="studio-muted">
                    suggestion: {review.suggestion.decision ?? "—"} · confidence {confidence(review.suggestion.confidence)}
                    {review.decision ? ` · chosen: ${review.decision.decision}` : ""}
                  </div>
                  <div className="studio-muted">
                    signals: {review.suggestion.signals.length ? review.suggestion.signals.map(String).join(" · ") : "—"}
                  </div>
                  <div className="studio-muted">
                    candidate {review.candidate_id} · resolution {formatShortHash(review.resolution_sha256)}
                  </div>
                </div>
                <div className="studio-row-actions">
                  <Badge>{review.job_status}</Badge>
                  <Link className="studio-link-button" to={`/studio/imports/${encodeURIComponent(review.job_id)}`}>
                    Import
                  </Link>
                  <Link className="studio-link-button" to={`/studio/review/${encodeURIComponent(review.review_id)}`}>
                    查看 / 决策
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
