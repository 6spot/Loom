import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { useStudioAuth } from "../../lib/studio-auth";
import {
  formatShortHash,
  getReview,
  mutateJob,
  ReviewDecision,
  ReviewRecordContext,
  StudioApiError,
  submitReviewDecision,
} from "../../lib/studio-api";

function errorText(error: unknown): string {
  if (error instanceof StudioApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

function pretty(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function RecordCard({ label, context }: { label: string; context: ReviewRecordContext }) {
  const record = context.record ?? {};
  const display = record.name ?? record.title ?? context.ref;
  return (
    <Card>
      <CardHeader>
        <p className="studio-eyebrow">{label}</p>
        <CardTitle>{display}</CardTitle>
        <CardDescription>
          {context.source_title ?? "未知来源"} · {context.bundle}/{context.ref}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="studio-definition-list">
          <div><dt>kind / type</dt><dd>{record.kind ?? "—"} / {record.type ?? "—"}</dd></div>
          {record.aliases?.length ? <div><dt>aliases</dt><dd>{record.aliases.map(String).join(" · ")}</dd></div> : null}
          {record.mentions?.length ? <div><dt>mentions</dt><dd><pre>{pretty(record.mentions)}</pre></dd></div> : null}
          {record.time != null ? <div><dt>time</dt><dd><pre>{pretty(record.time)}</pre></dd></div> : null}
          {record.participants?.length ? <div><dt>participants</dt><dd><pre>{pretty(record.participants)}</pre></dd></div> : null}
          {record.places?.length ? <div><dt>places</dt><dd><pre>{pretty(record.places)}</pre></dd></div> : null}
        </dl>
      </CardContent>
    </Card>
  );
}

export default function StudioReviewDetailPage() {
  const { reviewId = "" } = useParams();
  const auth = useStudioAuth();
  const authHeader = auth.authHeader();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const review = useQuery({
    queryKey: ["studio", "review", reviewId],
    queryFn: () => getReview(authHeader, reviewId),
    enabled: Boolean(reviewId),
  });
  const item = review.data;
  const allowed = item?.allowed_decisions ?? [];
  const [decision, setDecision] = useState<ReviewDecision | "">("");
  const [rationale, setRationale] = useState("");
  const [confidence, setConfidence] = useState("0.5");

  useEffect(() => {
    if (!decision && allowed.length) setDecision(allowed[0]);
  }, [allowed, decision]);

  const canSubmit = useMemo(() => {
    const parsed = Number(confidence);
    return Boolean(
      item?.status === "open" &&
      decision &&
      allowed.includes(decision as ReviewDecision) &&
      rationale.trim() &&
      Number.isFinite(parsed) && parsed >= 0 && parsed <= 1,
    );
  }, [allowed, confidence, decision, item?.status, rationale]);

  const decide = useMutation({
    mutationFn: async () => {
      if (!item || !decision) throw new Error("缺少 Review decision");
      if (!window.confirm(`确认提交 ${decision}？提交后该 ReviewItem 将保持为审计历史，不能静默改写。`)) {
        throw new Error("已取消提交");
      }
      return submitReviewDecision(
        authHeader,
        item.review_id,
        decision,
        rationale.trim(),
        Number(confidence),
      );
    },
    onSuccess: async (updated) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["studio", "reviews"] }),
        queryClient.invalidateQueries({ queryKey: ["studio", "review", reviewId] }),
        queryClient.invalidateQueries({ queryKey: ["studio", "job", updated.job_id] }),
      ]);
    },
  });

  const resume = useMutation({
    mutationFn: async () => {
      if (!item) throw new Error("缺少 Job");
      if (!window.confirm("所有 resolution review 已解决。确认通过控制平面恢复该 ingestion job？")) {
        throw new Error("已取消恢复");
      }
      return mutateJob(authHeader, item.job_id, "resume");
    },
    onSuccess: async (job) => {
      await queryClient.invalidateQueries({ queryKey: ["studio", "jobs"] });
      navigate(`/studio/imports/${encodeURIComponent(job.job_id)}`);
    },
  });

  if (review.isLoading) return <p className="studio-muted">正在读取 ReviewItem…</p>;
  if (review.error) return <p className="studio-error">{errorText(review.error)}</p>;
  if (!item) return <p className="studio-muted">ReviewItem 不存在。</p>;

  return (
    <div className="studio-stack" data-view="studio-review-detail">
      <div className="studio-page-heading">
        <div>
          <p className="studio-eyebrow">Resolution Review</p>
          <h1>{item.link_kind === "entity" ? "Entity identity" : "Event occurrence"}</h1>
          <p className="studio-muted">
            candidate {item.candidate_id} · resolution {formatShortHash(item.resolution_sha256)}
          </p>
        </div>
        <div className="studio-row-actions">
          <Badge>{item.status}</Badge>
          <Badge>{item.job_status}</Badge>
          <Link className="studio-link-button" to="/studio/review">返回队列</Link>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Origin</CardTitle>
          <CardDescription>该 ReviewItem 绑定到一个 immutable Revision 和一个 durable Ingestion Job。</CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="studio-definition-list">
            <div><dt>Document</dt><dd>{item.document.title} · r{item.document.revision_no}</dd></div>
            <div><dt>file</dt><dd>{item.document.filename}</dd></div>
            <div><dt>source hash</dt><dd className="studio-mono">{item.document.source_sha256}</dd></div>
            <div><dt>Job</dt><dd><Link to={`/studio/imports/${encodeURIComponent(item.job_id)}`}>{item.job_id}</Link></dd></div>
            <div><dt>open review debt</dt><dd>{item.job_open_resolution_reviews}</dd></div>
          </dl>
          <div className="studio-row-actions">
            <Link className="studio-link-button" to={`/studio/imports/${encodeURIComponent(item.job_id)}`}>查看 Import</Link>
            <Link className="studio-link-button" to="/studio/sources">查看 Sources</Link>
          </div>
        </CardContent>
      </Card>

      <div className="studio-grid studio-grid-wide">
        <RecordCard label="Left representation" context={item.left_context} />
        <RecordCard label="Right representation" context={item.right_context} />
      </div>

      <div className="studio-grid studio-grid-wide">
        <Card>
          <CardHeader>
            <CardTitle>Original suggestion</CardTitle>
            <CardDescription>只读。模型/规则建议不是历史身份 authority。</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="studio-definition-list">
              <div><dt>decision</dt><dd><Badge>{item.suggestion.decision ?? "—"}</Badge></dd></div>
              <div><dt>confidence</dt><dd>{item.suggestion.confidence == null ? "—" : item.suggestion.confidence}</dd></div>
              <div><dt>rationale</dt><dd>{item.suggestion.rationale ?? "—"}</dd></div>
              <div><dt>signals</dt><dd>{item.suggestion.signals.length ? item.suggestion.signals.map(String).join(" · ") : "—"}</dd></div>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Administrator decision</CardTitle>
            <CardDescription>选择只来自该 ReviewItem 的 C0 allowed_decisions；uncertain 不会触发 merge。</CardDescription>
          </CardHeader>
          <CardContent>
            {item.decision ? (
              <dl className="studio-definition-list">
                <div><dt>decision</dt><dd><Badge>{item.decision.decision}</Badge></dd></div>
                <div><dt>confidence</dt><dd>{item.decision.confidence}</dd></div>
                <div><dt>rationale</dt><dd>{item.decision.rationale}</dd></div>
                <div><dt>resolved</dt><dd>{item.resolved_at ?? "—"}</dd></div>
              </dl>
            ) : (
              <form
                className="studio-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (canSubmit) decide.mutate();
                }}
              >
                <div>
                  <label className="studio-label" htmlFor="review-decision">Decision</label>
                  <select
                    id="review-decision"
                    className="studio-select"
                    value={decision}
                    onChange={(event) => setDecision(event.target.value as ReviewDecision)}
                  >
                    {allowed.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </div>
                <div>
                  <label className="studio-label" htmlFor="review-rationale">Rationale</label>
                  <textarea
                    id="review-rationale"
                    className="studio-textarea"
                    value={rationale}
                    onChange={(event) => setRationale(event.target.value)}
                    rows={5}
                    placeholder="写明你为何认为两侧记录应该合并、保持不同、相关但不同，或继续 uncertain。"
                  />
                </div>
                <div>
                  <label className="studio-label" htmlFor="review-confidence">Decision confidence (0–1)</label>
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
                <Button type="submit" disabled={!canSubmit || decide.isPending}>
                  {decide.isPending ? "提交中…" : "确认并提交 Decision"}
                </Button>
              </form>
            )}
            {decide.error && errorText(decide.error) !== "已取消提交" ? <p className="studio-error">{errorText(decide.error)}</p> : null}
          </CardContent>
        </Card>
      </div>

      {item.status !== "open" && item.job_status === "needs_review" && item.job_open_resolution_reviews === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Review gate cleared</CardTitle>
            <CardDescription>所有 resolution review 已关闭；恢复仍由服务器 control-plane 校验，不由浏览器直接改状态。</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => resume.mutate()} disabled={resume.isPending}>
              {resume.isPending ? "恢复中…" : "Resume ingestion job"}
            </Button>
            {resume.error && errorText(resume.error) !== "已取消恢复" ? <p className="studio-error">{errorText(resume.error)}</p> : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
