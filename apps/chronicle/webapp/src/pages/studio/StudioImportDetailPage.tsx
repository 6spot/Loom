import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { useStudioAuth } from "../../lib/studio-auth";
import { stageLabel, studioStatusLabel } from "../../lib/studio-i18n";
import {
  formatShortHash,
  getJob,
  jobIsLive,
  mutateJob,
  StudioApiError,
  type JobChunk,
  type JobDetail,
  type JobStage,
} from "../../lib/studio-api";

function errorText(error: unknown): string {
  if (error instanceof StudioApiError) return `${error.code}: ${error.message}`;
  if (error instanceof Error) return error.message;
  return String(error);
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}


function Validation({ value }: { value: unknown }) {
  if (value === undefined || value === null) return null;
  return (
    <details className="studio-details">
      <summary>校验详情</summary>
      <pre className="studio-code">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

function StageRow({ stage }: { stage: JobStage }) {
  return (
    <div className="studio-stage-row">
      <div className="studio-stage-marker" data-status={stage.status} aria-hidden="true" />
      <div>
        <div className="studio-row-title">
          <strong>{stageLabel(stage.stage)}</strong>
          <Badge>{studioStatusLabel(stage.status)}</Badge>
          <span className="studio-muted">尝试 {stage.attempt}</span>
        </div>
        <div className="studio-muted">{formatTime(stage.started_at)} → {formatTime(stage.finished_at)}</div>
        {stage.error ? <p className="studio-error">{stage.error}</p> : null}
      </div>
    </div>
  );
}

function ChunkRow({ chunk }: { chunk: JobChunk }) {
  const failed = chunk.status === "failed" || chunk.runs.some((run) => run.status === "failed");
  return (
    <details className="studio-chunk" open={failed}>
      <summary>
        <span className="studio-row-title">
          <strong>分段 {chunk.chunk_index}</strong>
          <Badge>{studioStatusLabel(chunk.status)}</Badge>
          <span>尝试 {chunk.attempt}/{chunk.max_attempts}</span>
        </span>
        <span className="studio-muted">源文本字符 {chunk.source_start}–{chunk.source_end}</span>
      </summary>
      <div className="studio-chunk-body">
        <dl className="studio-facts studio-facts-dense">
          <div><dt>chunk_id</dt><dd className="studio-mono">{chunk.chunk_id}</dd></div>
          <div><dt>section_id</dt><dd className="studio-mono">{chunk.section_id ?? "—"}</dd></div>
          <div><dt>source sha</dt><dd className="studio-mono">{formatShortHash(chunk.source_sha256)}</dd></div>
          <div><dt>content sha</dt><dd className="studio-mono">{formatShortHash(chunk.content_sha256)}</dd></div>
        </dl>
        <h4>运行尝试</h4>
        {chunk.runs.length === 0 ? <p className="studio-muted">尚未执行。</p> : null}
        <div className="studio-run-list">
          {chunk.runs.map((run) => (
            <div className="studio-run" key={run.run_id}>
              <div className="studio-row-title">
                <strong>#{run.attempt}</strong>
                <Badge>{studioStatusLabel(run.status)}</Badge>
                <span className="studio-muted">{run.worker ?? "执行器未记录"}</span>
              </div>
              <div className="studio-muted">{formatTime(run.started_at)} → {formatTime(run.finished_at)}</div>
              {run.error ? <p className="studio-error">{run.error}</p> : null}
              {Object.keys(run.meta ?? {}).length > 0 ? (
                <dl className="studio-facts studio-facts-dense">
                  <div><dt>model</dt><dd>{run.meta.model_version ?? "—"}</dd></div>
                  <div><dt>pipeline</dt><dd>{run.meta.extraction_version ?? "—"}</dd></div>
                  <div><dt>contract</dt><dd>{run.meta.contract_version ?? "—"}</dd></div>
                  <div><dt>prompt version</dt><dd>{run.meta.prompt_version ?? "—"}</dd></div>
                  <div><dt>accepted</dt><dd>{run.meta.accepted === undefined ? "—" : String(run.meta.accepted)}</dd></div>
                </dl>
              ) : null}
              {run.meta.attempts?.map((attempt, index) => (
                <div className="studio-attempt-meta" key={`${run.run_id}-${index}`}>
                  <div className="studio-muted">
                    模型调用 {index + 1} · {attempt.kind ?? "attempt"} · prompt {formatShortHash(attempt.prompt_sha256)} · response {formatShortHash(attempt.raw_response_sha256)}
                  </div>
                  {attempt.parse_error ? <p className="studio-error">{attempt.parse_error}</p> : null}
                  <Validation value={attempt.validation} />
                </div>
              ))}
            </div>
          ))}
        </div>
        <p className="studio-safe-note">管理工作台仅显示版本、哈希、校验与错误；原始提示、模型响应和候选数据留在服务端审计记录中。</p>
      </div>
    </details>
  );
}

function JobActions({ job }: { job: JobDetail }) {
  const auth = useStudioAuth();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (action: "retry" | "resume" | "cancel") => mutateJob(auth.authHeader(), job.job_id, action),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["studio", "job", job.job_id] }),
        queryClient.invalidateQueries({ queryKey: ["studio", "jobs"] }),
      ]);
    },
  });

  const act = (action: "retry" | "resume" | "cancel", prompt: string) => {
    if (window.confirm(prompt)) mutation.mutate(action);
  };
  return (
    <div className="studio-row-actions">
      {job.status === "failed" ? (
        <Button
          onClick={() => act("retry", "重新执行这个失败的 导入作业？已完成 checkpoint 会保留。")}
          disabled={mutation.isPending || job.attempt >= job.max_attempts}
        >
          Retry
        </Button>
      ) : null}
      {job.status === "needs_review" ? (
        <Button
          onClick={() => act("resume", "恢复这个待评审 Job？只有所有 审核项 已解决时后端才会允许。")}
          disabled={mutation.isPending || job.open_reviews > 0}
        >
          Resume
        </Button>
      ) : null}
      {job.status === "queued" || job.status === "running" || job.status === "needs_review" ? (
        <Button
          variant="destructive"
          onClick={() => act("cancel", "取消这个 Job？已完成 checkpoint 会保留，但后续阶段不会继续。")}
          disabled={mutation.isPending}
        >
          Cancel
        </Button>
      ) : null}
      {mutation.error ? <span className="studio-error">{errorText(mutation.error)}</span> : null}
    </div>
  );
}

export default function StudioImportDetailPage() {
  const auth = useStudioAuth();
  const { jobId } = useParams();
  const navigate = useNavigate();
  const job = useQuery({
    queryKey: ["studio", "job", jobId],
    queryFn: () => getJob(auth.authHeader(), jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const current = query.state.data as JobDetail | undefined;
      return current && jobIsLive(current.status) ? 3000 : false;
    },
  });

  if (!jobId) {
    return <p className="studio-error">缺少 job id。</p>;
  }
  if (job.isLoading) {
    return <p className="studio-muted">正在读取 导入作业…</p>;
  }
  if (job.error || !job.data) {
    return (
      <Card>
        <CardHeader><CardTitle>导入作业无法读取</CardTitle></CardHeader>
        <CardContent>
          <p className="studio-error">{errorText(job.error)}</p>
          <Button variant="outline" onClick={() => navigate("/studio/imports")}>返回导入列表</Button>
        </CardContent>
      </Card>
    );
  }

  const data = job.data;
  const failed分段 = data.chunks.filter((chunk) => chunk.status === "failed").length;
  const completed分段 = data.chunks.filter((chunk) => chunk.status === "completed").length;
  const currentStage = data.stages.find((stage) => stage.status === "running" || stage.status === "needs_review" || stage.status === "failed");

  return (
    <div className="studio-stack" data-view="studio-import-detail">
      <div className="studio-page-heading">
        <div>
          <Link className="studio-back-link" to="/studio/imports">← 返回导入列表</Link>
          <p className="studio-eyebrow">导入作业</p>
          <h1 className="studio-mono">{data.job_id}</h1>
          <div className="studio-row-title">
            <Badge>{studioStatusLabel(data.status)}</Badge>
            <span className="studio-muted">版本 <span className="studio-mono">{data.revision_id}</span></span>
          </div>
        </div>
        <JobActions job={data} />
      </div>

      <div className="studio-metric-grid">
        <Card><CardContent><span className="studio-metric-label">当前阶段</span><strong className="studio-metric-value">{currentStage?.stage ?? (data.status === "completed" ? "已完成" : "—")}</strong></CardContent></Card>
        <Card><CardContent><span className="studio-metric-label">分段</span><strong className="studio-metric-value">{completed分段}/{data.chunks.length}</strong></CardContent></Card>
        <Card><CardContent><span className="studio-metric-label">失败分段</span><strong className="studio-metric-value">{failed分段}</strong></CardContent></Card>
        <Card><CardContent><span className="studio-metric-label">待处理审核</span><strong className="studio-metric-value">{data.open_reviews}</strong></CardContent></Card>
      </div>

      {data.error ? <div className="studio-error-box"><strong>作业错误</strong><p>{data.error}</p></div> : null}

      <div className="studio-grid studio-grid-wide">
        <Card>
          <CardHeader><CardTitle>处理流水线</CardTitle><CardDescription>持久化阶段状态</CardDescription></CardHeader>
          <CardContent><div className="studio-stage-list">{data.stages.map((stage) => <StageRow key={stage.stage} stage={stage} />)}</div></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>作业信息</CardTitle><CardDescription>执行器 / 重试 / 输出状态</CardDescription></CardHeader>
          <CardContent>
            <dl className="studio-facts">
              <div><dt>尝试次数</dt><dd>{data.attempt}/{data.max_attempts}</dd></div>
              <div><dt>租约持有者</dt><dd>{data.lease_owner ?? "—"}</dd></div>
              <div><dt>租约到期</dt><dd>{formatTime(data.lease_expires_at)}</dd></div>
              <div><dt>创建时间</dt><dd>{formatTime(data.created_at)}</dd></div>
              <div><dt>更新时间</dt><dd>{formatTime(data.updated_at)}</dd></div>
              <div><dt>输出数量</dt><dd>{data.outputs.length}</dd></div>
            </dl>
            {data.status === "needs_review" && data.open_reviews > 0 ? (
              <p className="studio-muted">还有 {data.open_reviews} 个 审核项。C1-T11 人工审核队列 完成后可在评审页面处理，再回来 Resume。</p>
            ) : null}
            <div className="studio-row-actions">
              <Link
                className="studio-link-button"
                to={`/studio/review?status=open&job_id=${encodeURIComponent(data.job_id)}`}
              >
                进入该作业的审核队列
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>分段 & attempts</CardTitle>
          <CardDescription>源文本坐标、失败信息、运行版本/hash；不返回原始模型 prompt/response。</CardDescription>
        </CardHeader>
        <CardContent>
          {data.chunks.length === 0 ? <p className="studio-muted">尚未产生分段。</p> : null}
          <div className="studio-chunk-list">{data.chunks.map((chunk) => <ChunkRow key={chunk.chunk_id} chunk={chunk} />)}</div>
        </CardContent>
      </Card>

      <div className="studio-grid studio-grid-wide">
        <Card>
          <CardHeader><CardTitle>审核待办</CardTitle><CardDescription>T10 只显示摘要；决策属于 C1-T11。</CardDescription></CardHeader>
          <CardContent>
            {data.reviews.length === 0 ? <p className="studio-muted">没有 审核项。</p> : null}
            <div className="studio-table">
              {data.reviews.map((review) => (
                <div className="studio-table-row" key={review.review_id}>
                  <div><strong>{review.kind}</strong><div className="studio-muted studio-mono">{review.review_id}</div></div>
                  <div className="studio-row-actions"><Badge>{review.status}</Badge><span className="studio-muted">分段 {review.chunk_id?.slice(0, 8) ?? "—"}</span></div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>输出</CardTitle><CardDescription>按内容寻址的导入产物</CardDescription></CardHeader>
          <CardContent>
            {data.outputs.length === 0 ? <p className="studio-muted">尚无输出。</p> : null}
            <div className="studio-table">
              {data.outputs.map((output) => (
                <div className="studio-table-row" key={output.output_id}>
                  <div><strong>{output.artifact_type}</strong><div className="studio-muted studio-mono">{formatShortHash(output.artifact_sha256)}</div></div>
                  <span className="studio-muted">{formatTime(output.created_at)}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
