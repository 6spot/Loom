import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { useStudioAuth } from "../../lib/studio-auth";
import { stageLabel, studioStatusLabel } from "../../lib/studio-i18n";
import { getJob, jobIsLive, mutateJob, rerunJob, type JobDetail, type JobOutputSummary, type ModelSelection } from "../../lib/studio-api";
import { currentStage, failureAdvice, formatStudioTime, jobNextAction, jobTitle, PRODUCTION_STEPS, reviewKind, stepLabel, stepState } from "../../lib/studio-workspace";
import ModelSelector from "../../components/studio/ModelSelector";
import JobResultViewer from "../../components/studio/JobResultViewer";

function Status({ value }: { value: string }) {
  return <span className="studio-status" data-status={value}>{studioStatusLabel(value)}</span>;
}

function ResultComparison({ jobId, outputs }: { jobId: string; outputs: JobOutputSummary[] }) {
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const results = outputs.filter((item) => item.readable && item.status !== "started").slice().reverse();
  const chosen = results.find((item) => item.artifact_sha256 === left) ?? results[0];
  const compared = results.find((item) => item.artifact_sha256 === right && item.artifact_sha256 !== chosen?.artifact_sha256);
  const label = (item: JobOutputSummary) => `${item.model || "程序记录"} · 第 ${(item.round ?? 0) + 1} 版${item.attempt ? ` / 尝试 ${item.attempt}` : ""} · ${studioStatusLabel(item.status)}`;
  if (!results.length) return <div className="studio-empty"><strong>这一步还没有保存完整结果</strong><p>执行结束后，模型返回、校验结果和历史尝试会显示在这里。</p></div>;
  return <section className="studio-results-section">
    <div className="studio-section-heading"><h2>步骤结果</h2><span className="studio-muted">{results.length} 份记录 · 可并排核对</span></div>
    <div className="studio-result-selectors">
      <label>查看结果<select aria-label="查看结果" className="studio-select" value={chosen?.artifact_sha256 ?? ""} onChange={(event) => { setLeft(event.target.value); if (right === event.target.value) setRight(""); }}>{results.map((item) => <option key={item.output_id} value={item.artifact_sha256}>{label(item)}</option>)}</select></label>
      <label>对照结果<select aria-label="对照结果" className="studio-select" value={compared?.artifact_sha256 ?? ""} onChange={(event) => setRight(event.target.value)}><option value="">选择另一份结果进行对照</option>{results.filter((item) => item.artifact_sha256 !== chosen?.artifact_sha256).map((item) => <option key={item.output_id} value={item.artifact_sha256}>{label(item)}</option>)}</select></label>
    </div>
    <div className={`studio-result-columns ${compared ? "is-comparing" : ""}`}>
      {chosen ? <article><h3>{label(chosen)}</h3><JobResultViewer key={chosen.artifact_sha256} jobId={jobId} sha={chosen.artifact_sha256} /></article> : null}
      {compared ? <article><h3>{label(compared)}</h3><JobResultViewer key={compared.artifact_sha256} jobId={jobId} sha={compared.artifact_sha256} /></article> : null}
    </div>
  </section>;
}

function JobWorkspace({ job }: { job: JobDetail }) {
  const auth = useStudioAuth().authHeader();
  const queryClient = useQueryClient();
  const [selectedStage, setSelectedStage] = useState<string | null>(null);
  const [selectedChunk, setSelectedChunk] = useState<string | null>(null);
  const [selectedStep, setSelectedStep] = useState<string | null>(null);
  const [showRerun, setShowRerun] = useState(false);
  const [selection, setSelection] = useState<ModelSelection>();
  const [modelReady, setModelReady] = useState(false);
  const [newJob, setNewJob] = useState<JobDetail | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);
  const action = useMutation({
    mutationFn: (name: "retry" | "resume" | "cancel") => mutateJob(auth, job.job_id, name),
    onSuccess: async (updated) => {
      queryClient.setQueryData(["studio", "job", job.job_id], updated);
      setConfirmStop(false);
      await queryClient.invalidateQueries({ queryKey: ["studio", "jobs"] });
    },
  });
  const rerun = useMutation({ mutationFn: () => rerunJob(auth, job.job_id, selection), onSuccess: async (created) => {
    setNewJob(created); await queryClient.invalidateQueries({ queryKey: ["studio", "jobs"] });
  } });
  const active = currentStage(job);
  const stage = selectedStage ?? active ?? (job.job_kind === "narrative" ? "present" : "extract");
  const chunk = job.chunks.find((item) => item.chunk_id === selectedChunk)
    ?? job.chunks.find((item) => ["running", "failed", "needs_review"].includes(item.status)) ?? job.chunks[0];
  const step = selectedStep ?? (chunk && PRODUCTION_STEPS.find((item) => ["started", "failed", "invalid", "interrupted"].includes(stepState(chunk, item.id, job.status)))?.id)
    ?? chunk?.production?.step ?? "translation";
  const completed = job.stages.filter((item) => item.status === "completed").length;
  const stages = job.stages.filter((item) => item.status !== "skipped");
  const reviewLink = `/studio/review?status=open&review_scope=all&job_id=${encodeURIComponent(job.job_id)}`;
  return <div className="studio-stack" data-view="studio-import-detail">
    <Link className="studio-back-link" to="/studio/imports">← 返回任务列表</Link>
    <div className="studio-page-heading"><div><p className="studio-eyebrow">{job.job_kind === "narrative" ? "综合历史" : "资料生产"}</p><h1>{jobTitle(job)}</h1><p className="studio-muted">{job.document ? `第 ${job.document.revision_no} 版 · ` : ""}{formatStudioTime(job.created_at)} 创建</p></div><Status value={job.status} /></div>
    <div className="studio-job-banner" data-status={job.status}>
      <div><strong>{jobNextAction(job)}</strong><p>{job.status === "failed" ? failureAdvice(job.error) : `${completed} / ${stages.length} 个主要阶段完成${job.chunks.length ? ` · ${job.chunks.filter((item) => item.status === "completed").length} / ${job.chunks.length} 章完成` : ""}`}</p></div>
      <div className="studio-row-actions">
        {job.open_reviews > 0 ? <Link className="studio-link-button studio-link-primary" to={reviewLink}>处理 {job.open_reviews} 项审核</Link> : null}
        {job.status === "failed" ? <Button disabled={action.isPending || job.attempt >= job.max_attempts} onClick={() => action.mutate("retry")}>{action.isPending ? "正在重试…" : "重试未完成步骤"}</Button> : null}
        {job.status === "needs_review" && job.open_reviews === 0 ? <Button disabled={action.isPending} onClick={() => action.mutate("resume")}>继续生产</Button> : null}
        {["failed", "cancelled"].includes(job.status) && job.job_kind !== "narrative" ? <Button variant="outline" onClick={() => setShowRerun((value) => !value)}>换模型重新处理</Button> : null}
      </div>
    </div>
    {job.status === "failed" && job.attempt >= job.max_attempts ? <p className="studio-muted">本次任务已达到重试上限，可查看记录后创建新任务。</p> : null}
    {job.error ? <details className="studio-details"><summary>查看失败的详细原因</summary><pre className="studio-code">{job.error}</pre></details> : null}
    {action.error ? <p role="alert" className="studio-error">操作未完成：{action.error.message}</p> : null}
    {showRerun ? <section className="studio-panel"><h2>重新处理这份资料</h2><p className="studio-muted">将使用同一份资料版本创建新任务，从整章翻译与提取重新开始。原任务、已保存结果和审核意见保留，可随时返回对照。</p>
      <ModelSelector value={selection} onChange={setSelection} onReady={setModelReady} disabled={rerun.isPending || Boolean(newJob)} />
      {newJob ? <p role="status">新任务已创建。<Link to={`/studio/imports/${newJob.job_id}`}>查看新任务 →</Link></p> : <Button disabled={rerun.isPending || !modelReady} onClick={() => rerun.mutate()}>{rerun.isPending ? "正在创建…" : "新建任务并重新处理"}</Button>}
      {rerun.error ? <p role="alert" className="studio-error">{rerun.error.message}</p> : null}
    </section> : null}
    {job.production_request?.parent_job_id ? <p className="studio-muted">本次重新处理关联至 <Link to={`/studio/imports/${job.production_request.parent_job_id}`}>原任务与结果</Link>。</p> : null}
    <div className="studio-workspace">
      <aside className="studio-process-rail" aria-label="任务流程"><h2>处理流程</h2><ol>{stages.map((item, index) => <li key={item.stage} data-status={item.status}><button type="button" aria-current={stage === item.stage ? "step" : undefined} onClick={() => setSelectedStage(item.stage)}>
        <span className="studio-process-dot" aria-hidden="true">{item.status === "completed" ? "✓" : index + 1}</span><span><strong>{job.job_kind === "narrative" && item.stage === "present" ? "核对并综合历史" : stageLabel(item.stage)}</strong><small>{studioStatusLabel(item.status)}</small></span>
      </button></li>)}</ol><p className="studio-muted">已完成结果逐步保存，刷新后继续跟踪。</p></aside>
      <div className="studio-workspace-body">
        <section className="studio-panel"><div className="studio-section-heading"><h2>{job.job_kind === "narrative" ? "历史正文生产" : stageLabel(stage)}</h2><span className="studio-muted">{formatStudioTime(job.updated_at)} 更新</span></div>
          {stage === "extract" && chunk ? <>
            <div className="studio-chapter-switch"><label>当前章节<select className="studio-select" value={chunk.chunk_id} onChange={(event) => { setSelectedChunk(event.target.value); setSelectedStep(null); }}>{job.chunks.map((item) => <option key={item.chunk_id} value={item.chunk_id}>{item.title || `第 ${item.chunk_index + 1} 章`} · {studioStatusLabel(item.status)}</option>)}</select></label><span className="studio-muted">{(chunk.source_end - chunk.source_start).toLocaleString()} 字原文 · 完整章节语境</span></div>
            <div className="studio-step-grid" aria-label="章节处理进度">{PRODUCTION_STEPS.map((item) => { const status = stepState(chunk, item.id, job.status); return <button type="button" key={item.id} className="studio-step-tile" data-status={status} aria-pressed={step === item.id} onClick={() => setSelectedStep(item.id)}><strong>{item.label}</strong><Status value={status} /><small>{item.description}</small></button>; })}</div>
            <ResultComparison key={`${chunk.chunk_id}:${step}`} jobId={job.job_id} outputs={job.outputs.filter((item) => item.chunk_id === chunk.chunk_id && item.step === step)} />
            {job.outputs.some((item) => item.chunk_id === chunk.chunk_id && item.artifact_type === "chapter-production-draft") ? <details className="studio-details"><summary>汇总稿与历次修订</summary><ResultComparison key={`${chunk.chunk_id}:drafts`} jobId={job.job_id} outputs={job.outputs.filter((item) => item.chunk_id === chunk.chunk_id && item.artifact_type === "chapter-production-draft")} /></details> : null}
            <details className="studio-details"><summary>本章执行记录</summary><div className="studio-table">{chunk.production?.steps.map((entry, index) => <div className="studio-table-row" key={entry.output_sha256 ?? index}><div><strong>{stepLabel(entry.step)}</strong><p className="studio-muted">{entry.model} · 尝试 {entry.attempt ?? 1}{entry.elapsed_seconds != null ? ` · ${entry.elapsed_seconds.toFixed(1)} 秒` : ""} · 输出用量 {entry.usage?.output_tokens ?? "未报告"}</p></div><Status value={entry.status ?? "pending"} /></div>)}</div></details>
          </> : <>
            <p className="studio-muted">{job.job_kind === "narrative" ? `基于 ${job.source_count ?? 0} 个完整来源章节，先核对事实，再审核连续正文与精选入口。` : stage === "structure" || stage === "segment" ? "按自然章节准备完整上下文，每章保留原文与原注，再独立翻译和提取。" : "本阶段沿用已保存的上游结果。需要人工判断时，审核入口会显示在下方。"}</p>
            {job.chunks.length ? <div className="studio-table">{job.chunks.map((item) => <button type="button" className="studio-list-row" key={item.chunk_id} onClick={() => { setSelectedChunk(item.chunk_id); setSelectedStage("extract"); }}><span><strong>{item.title || `第 ${item.chunk_index + 1} 章`}</strong><small>{(item.source_end - item.source_start).toLocaleString()} 字原文</small></span><Status value={item.status} /></button>)}</div> : <p className="studio-muted">{job.job_kind === "narrative" ? "来源章节已固定，处理意见会在审核项中集中呈现。" : "章节识别完成后，这里显示各章进度。"}</p>}
          </>}
        </section>
        {job.reviews.length ? <section className="studio-panel"><div className="studio-section-heading"><h2>内容核对</h2><Link to={reviewLink}>查看审核队列 →</Link></div><div className="studio-table">{job.reviews.map((review) => <Link className="studio-table-row" key={review.review_id} to={`/studio/review/${review.review_id}?review_scope=all&job_id=${job.job_id}`}><div><strong>{reviewKind(review.scope, review.narrative_kind)}</strong><p className="studio-muted">{formatStudioTime(review.created_at)}</p></div><Status value={review.status} /><span aria-hidden="true">→</span></Link>)}</div></section> : null}
        {job.status === "completed" ? <section className="studio-panel"><h2>处理成果</h2><p>{job.job_kind === "narrative" ? "连续历史正文已通过审核并发布。" : "本次资料已完成处理，可作为综合历史叙事的来源。"}</p><Link className="studio-link-button" to={job.job_kind === "narrative" ? "/history" : "/studio/imports?create=history"}>{job.job_kind === "narrative" ? "查看历史阅读页 →" : "选择来源并生成综合历史 →"}</Link></section> : null}
      </div>
    </div>
    <details className="studio-panel studio-details"><summary>技术记录与任务操作</summary><dl className="studio-facts"><div><dt>任务编号</dt><dd className="studio-mono">{job.job_id}</dd></div><div><dt>资料版本编号</dt><dd className="studio-mono">{job.revision_id}</dd></div><div><dt>任务尝试</dt><dd>{job.attempt} / {job.max_attempts}</dd></div><div><dt>已保存产物</dt><dd>{job.outputs.length} 份</dd></div></dl>
      <details><summary>查看完整运行元数据</summary><pre className="studio-code">{JSON.stringify(job, null, 2)}</pre></details>
      {jobIsLive(job.status) ? confirmStop ? <div className="studio-row-actions"><p>停止后不再执行后续步骤，已保存结果仍保留。</p><Button variant="destructive" disabled={action.isPending} onClick={() => action.mutate("cancel")}>确认停止任务</Button><Button variant="outline" onClick={() => setConfirmStop(false)}>继续保留任务</Button></div> : <Button variant="outline" onClick={() => setConfirmStop(true)}>停止任务</Button> : null}
    </details>
  </div>;
}

export default function StudioImportDetailPage() {
  const auth = useStudioAuth();
  const { jobId } = useParams();
  const job = useQuery({ queryKey: ["studio", "job", jobId], queryFn: () => getJob(auth.authHeader(), jobId!), enabled: Boolean(jobId),
    refetchInterval: (query) => { const data = query.state.data; return data && jobIsLive(data.status) ? 3000 : false; },
  });
  useEffect(() => { window.scrollTo(0, 0); }, [jobId]);
  if (job.isPending) return <p className="studio-muted">正在读取任务进度…</p>;
  if (job.error || !job.data) return <div className="studio-empty"><h1>任务暂时无法读取</h1><p>{job.error?.message}</p><Button onClick={() => void job.refetch()}>重新读取</Button><Link to="/studio/imports">返回任务列表</Link></div>;
  return <JobWorkspace key={job.data.job_id} job={job.data} />;
}
