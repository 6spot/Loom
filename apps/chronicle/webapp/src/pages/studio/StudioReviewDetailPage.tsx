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
  StudioApiError,
  submitReviewDecision,
} from "../../lib/studio-api";
import type { ReviewDecision, ReviewRecordContext } from "../../lib/studio-api";
import {
  comparisonRows,
  decisionHelp,
  decisionLabel,
  formatLocator,
  formatReviewTime,
  roleLabel,
  signalLabel,
  statusLabel,
  typeLabel,
} from "../../lib/review-display";
import type { HumanReviewContext } from "../../lib/review-display";

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
      if (!item || !decision) throw new Error("缺少审核判断");
      if (!window.confirm(`确认提交“${decisionLabel(decision)}”？提交后该审核项将作为审计历史保留，不能静默改写。`)) {
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

  if (review.isLoading) return <p className="studio-muted">正在读取审核项…</p>;
  if (review.error) return <p className="studio-error">{errorText(review.error)}</p>;
  if (!item) return <p className="studio-muted">审核项不存在。</p>;

  const left = item.left_context as HumanReviewContext;
  const right = item.right_context as HumanReviewContext;
  const comparisons = comparisonRows(item.link_kind, left, right);

  return (
    <div className="studio-stack" data-view="studio-review-detail">
      <div className="studio-page-heading">
        <div>
          <p className="studio-eyebrow">人工消歧</p>
          <h1>{item.link_kind === "entity" ? "实体是否同一身份" : "事件是否同一发生"}</h1>
          <p className="studio-muted">
            候选 {item.candidate_id} · 解析批次 {formatShortHash(item.resolution_sha256)}
          </p>
        </div>
        <div className="studio-row-actions">
          <Badge>{statusLabel(item.status)}</Badge>
          <Badge>{statusLabel(item.job_status)}</Badge>
          <Link className="studio-link-button" to="/studio/review">返回审核队列</Link>
        </div>
      </div>

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

      <div className="studio-grid studio-grid-wide">
        <RecordCard label="左侧记录" context={item.left_context} />
        <RecordCard label="右侧记录" context={item.right_context} />
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
            <CardDescription>只根据上方两侧来源证据作决定；“证据不足，暂不确定”不会触发合并。</CardDescription>
          </CardHeader>
          <CardContent>
            {item.decision ? (
              <dl className="studio-definition-list">
                <div><dt>判断</dt><dd><Badge>{decisionLabel(item.decision.decision)}</Badge></dd></div>
                <div><dt>置信度</dt><dd>{item.decision.confidence}</dd></div>
                <div><dt>判断依据</dt><dd>{item.decision.rationale}</dd></div>
                <div><dt>处理时间</dt><dd>{item.resolved_at ?? "—"}</dd></div>
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
                <Button type="submit" disabled={!canSubmit || decide.isPending}>
                  {decide.isPending ? "提交中…" : "确认并提交判断"}
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
    </div>
  );
}
