import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { useStudioAuth } from "../../lib/studio-auth";
import { stageLabel, studioStatusLabel } from "../../lib/studio-i18n";
import { getJob, jobIsLive, mutateJob, newRunJob, rerunJob, type JobAttempt, type JobDetail, type JobOutputSummary, type ModelSelection } from "../../lib/studio-api";
import { actionEnabled, currentStage, currentWorkspaceStep, failureAdvice, formatStudioTime, hasAuthoritativeActions, jobAction, jobKind, jobNextAction, jobReason, jobSourceCount, jobSteps, jobTitle, PRODUCTION_STEPS, reviewKind, stepLabel, stepState } from "../../lib/studio-workspace";
import ModelSelector from "../../components/studio/ModelSelector";
import JobResultViewer from "../../components/studio/JobResultViewer";

function Status({ value }: { value: string }) {
  return <span className="studio-status" data-status={value}>{studioStatusLabel(value)}</span>;
}

type ComparisonResult = JobOutputSummary & {
  result_sha256?: string;
  output_complete?: boolean | null;
  validation_status?: string | null;
  comparison_status?: string | null;
};

function stepMatches(resultStep: string | null | undefined, selectedStep?: string | null) {
  if (!selectedStep) return true;
  if (!resultStep) return false;
  if (resultStep === selectedStep) return true;
  return (selectedStep === "extract" && ["extraction", "extract"].includes(resultStep))
    || (selectedStep === "present" && ["present", "prose", "facts_compare"].includes(resultStep));
}

function resultStepLabel(step: string | null | undefined): string {
  const labels: Record<string, string> = {
    extraction: "信息提取",
    facts_compare: "事实对比",
    prose: "正文候选",
  };
  return labels[step ?? ""] || stepLabel(step);
}

function acceptedDecisionLabel(value: string | null | undefined): string {
  if (value === "accept" || value === "approve") return "已接受";
  if (value === "reject") return "已驳回";
  if (value === "revise") return "已提交修订";
  return value || "已记录";
}

function acceptanceTypeLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    policy_model_review: "策略模型复核",
    human_review: "人工审核",
    chapter_review: "章节审核",
  };
  return labels[value ?? ""] || value || "审核采用记录";
}

function acceptedEvidenceCount(value: NonNullable<JobDetail["accepted_results"]>[number]): number {
  return value.model_output_sha256s?.length
    ?? value.model_opinion_sha256s?.length
    ?? (typeof value.step_output_sha256 === "string" ? 1 : 0);
}

function ResultComparison({ jobId, outputs, attempts = [], acceptedResults = [], selectedStep }: {
  jobId: string;
  outputs: JobOutputSummary[];
  attempts?: JobAttempt[];
  acceptedResults?: JobDetail["accepted_results"];
  selectedStep?: string | null;
}) {
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const completeAttempts = attempts.filter((item) => item.result_sha256 && item.status !== "started" && item.output_complete !== false);
  const scopedAttempts = completeAttempts.filter((item) => stepMatches(item.step, selectedStep));
  const modernResults: ComparisonResult[] = (scopedAttempts.length ? scopedAttempts : completeAttempts)
    .map((item) => ({
      output_id: item.attempt_id ?? item.result_sha256!,
      artifact_type: item.artifact_type ?? "model-result",
      artifact_sha256: item.result_sha256!,
      result_sha256: item.result_sha256!,
      created_at: item.ended_at ?? item.started_at ?? null,
      step: item.step,
      model: item.model,
      status: item.status,
      attempt: item.attempt,
      round: item.round,
      slot: item.slot,
      readable: item.output_complete !== false,
      output_complete: item.output_complete,
      validation_status: item.validation_status,
      comparison_status: item.comparison_status,
    }));
  const modernHashes = new Set(modernResults.map((item) => item.artifact_sha256));
  const readableOutputs = outputs.filter((item) => item.readable && item.status !== "started");
  const scopedOutputs = readableOutputs.filter((item) => stepMatches(item.step, selectedStep));
  const legacyResults: ComparisonResult[] = (scopedOutputs.length ? scopedOutputs : readableOutputs)
    .filter((item) => !modernHashes.has(item.artifact_sha256))
    .map((item) => item);
  const results = [...modernResults, ...legacyResults].reverse();
  const chosen = results.find((item) => item.artifact_sha256 === left) ?? results[0];
  const compared = results.find((item) => item.artifact_sha256 === right && item.artifact_sha256 !== chosen?.artifact_sha256);
  const label = (item: ComparisonResult) => `${item.model || "程序记录"} · ${resultStepLabel(item.step)} · 第 ${(item.round ?? 0) + 1} 版${item.attempt ? ` / 尝试 ${item.attempt}` : ""} · ${studioStatusLabel(item.status)}`;
  if (!results.length) return <div className="studio-empty"><strong>这一步还没有保存完整结果</strong><p>执行结束后，模型返回、校验结果和历史尝试会显示在这里。</p></div>;
  return <section className="studio-results-section">
    <div className="studio-section-heading"><h2>模型结果与采用稿</h2><span className="studio-muted">{results.length} 份完整记录 · 可并排核对</span></div>
    <p className="studio-readable-note">同一步骤的结论、段落和校验状态并排展示；长结果会自动分段读取，原始 JSON 只在每份结果内部按需展开。</p>
    <div className="studio-result-selectors">
      <label>查看结果<select aria-label="查看结果" className="studio-select" value={chosen?.artifact_sha256 ?? ""} onChange={(event) => { setLeft(event.target.value); if (right === event.target.value) setRight(""); }}>{results.map((item) => <option key={item.output_id} value={item.artifact_sha256}>{label(item)}</option>)}</select></label>
      <label>对照结果<select aria-label="对照结果" className="studio-select" value={compared?.artifact_sha256 ?? ""} onChange={(event) => setRight(event.target.value)}><option value="">选择另一份结果进行对照</option>{results.filter((item) => item.artifact_sha256 !== chosen?.artifact_sha256).map((item) => <option key={item.output_id} value={item.artifact_sha256}>{label(item)}</option>)}</select></label>
    </div>
    <div className={`studio-result-columns ${compared ? "is-comparing" : ""}`}>
      {chosen ? <article><h3>{label(chosen)}{chosen.comparison_status === "agreed" ? <span className="studio-result-badge">模型结论一致</span> : null}</h3><JobResultViewer key={chosen.artifact_sha256} jobId={jobId} sha={chosen.artifact_sha256} /></article> : null}
      {compared ? <article><h3>{label(compared)}{compared.comparison_status === "agreed" ? <span className="studio-result-badge">模型结论一致</span> : null}</h3><JobResultViewer key={compared.artifact_sha256} jobId={jobId} sha={compared.artifact_sha256} /></article> : null}
    </div>
    {acceptedResults?.length ? <div className="studio-adopted-result"><strong>已采用的草稿与理由</strong>{acceptedResults.map((accepted, index) => <div className="studio-result-record" key={accepted.acceptance_id ?? index}><p><span className="studio-status" data-status="accepted">{acceptedDecisionLabel(accepted.decision)}</span> {acceptanceTypeLabel(accepted.acceptance_type)}</p><p className="studio-muted">保留 {acceptedEvidenceCount(accepted)} 份模型结果作为依据，采用稿与候选版本均已固定。{accepted.review_id ? "审核说明已记录在对应审核项中。" : "当前投影未附理由正文，原始审核记录仍保留。"}</p></div>)}</div> : null}
  </section>;
}

function sourceRelationshipLabel(value: string | null | undefined): string {
  if (value === "immutable_revision") return "固定资料版本";
  if (value === "frozen_catalog") return "固定历史来源选择";
  if (value === "parent_job") return "沿用原任务来源";
  return value || "固定来源范围";
}

function attemptDescription(attempt: JobAttempt): string {
  const usage = attempt.usage?.total_tokens != null
    ? `用量 ${attempt.usage.total_tokens.toLocaleString()}`
    : attempt.usage_status === "unreported" ? "用量未报告" : "用量待记录";
  const elapsed = attempt.elapsed_seconds == null ? "" : ` · ${attempt.elapsed_seconds.toFixed(1)} 秒`;
  const step = attempt.step_label && attempt.step_label !== "模型步骤" ? attempt.step_label : resultStepLabel(attempt.step);
  return `${attempt.model || "未命名模型"} · ${step}${attempt.slot ? ` · ${attempt.slot}` : ""} · 第 ${attempt.attempt ?? 1} 次${elapsed} · ${usage}`;
}

function OriginalSource({ job }: { job: JobDetail }) {
  const auth = useStudioAuth().authHeader();
  const [expanded, setExpanded] = useState(false);
  const [limit, setLimit] = useState(16_000);
  const documentId = job.source?.document_id || job.document?.document_id;
  const revisionId = job.source?.revision_id || job.revision_id;
  const source = useQuery({
    queryKey: ["studio", "job-source-text", job.job_id, revisionId],
    enabled: expanded && Boolean(documentId && revisionId),
    staleTime: Infinity,
    queryFn: async () => {
      const response = await fetch(`/api/v1/studio/documents/${encodeURIComponent(documentId!)}/revisions/${encodeURIComponent(revisionId!)}/content`, { headers: auth ? { Authorization: auth } : {} });
      if (!response.ok) throw new Error("原文暂时无法读取，请重试。");
      return response.text();
    },
  });
  if (!documentId || !revisionId) return <p className="studio-muted">完整原文请从审核项的证据入口查看。</p>;
  return <details className="studio-source-preview" onToggle={(event) => setExpanded(event.currentTarget.open)}><summary>查看冻结版本的完整原文</summary>
    {source.isFetching ? <p className="studio-muted">正在读取原文…</p> : null}
    {source.error ? <p className="studio-error" role="alert">{source.error.message}<Button variant="outline" size="sm" onClick={() => void source.refetch()}>重试读取</Button></p> : null}
    {source.data != null ? <><div className="studio-source-text">{source.data.slice(0, limit)}</div>{source.data.length > limit ? <Button variant="outline" size="sm" onClick={() => setLimit((value) => value + 16_000)}>继续显示原文</Button> : <small className="studio-muted">已完整显示此版本原文。</small>}</> : null}
  </details>;
}

function ModelOpinionPanel({ job }: { job: JobDetail }) {
  const attempts = job.attempts ?? [];
  const outputs = job.outputs ?? [];
  return <section className="studio-context-section" aria-labelledby="studio-model-opinions-title">
    <div className="studio-section-heading"><h2 id="studio-model-opinions-title">模型意见</h2><span className="studio-muted">{attempts.length || outputs.length} 份</span></div>
    {attempts.length ? <div className="studio-opinion-list">{attempts.map((attempt, index) => {
      const complete = attempt.output_complete !== false && attempt.status === "completed";
      const sha = attempt.result_sha256 || attempt.output_sha256;
      return <details className="studio-opinion" key={attempt.attempt_id ?? `${sha ?? "attempt"}-${index}`}>
        <summary><span><strong>{attempt.model || "未命名模型"}</strong><small>{attempt.step_label && attempt.step_label !== "模型步骤" ? attempt.step_label : resultStepLabel(attempt.step)} · {studioStatusLabel(attempt.status)}</small></span><Status value={attempt.comparison_status === "agreed" ? "accepted" : attempt.status || "pending"} /></summary>
        <div className="studio-opinion-body"><p className="studio-muted">{attemptDescription(attempt)}</p><p>{attempt.validation_status === "passed" ? "结果已通过校验。" : attempt.validation_status === "failed" ? "结果未通过校验，不能作为已采用结论。" : "校验状态尚未记录。"}{attempt.comparison_status === "agreed" ? " 模型结论与对照结果一致。" : attempt.comparison_status === "unavailable" ? " 对照结论不可用。" : ""}</p>{sha && complete ? <details className="studio-details"><summary>查看完整模型结果</summary><JobResultViewer key={sha} jobId={job.job_id} sha={sha} /></details> : <p className="studio-muted">本次没有可读取的完整模型结果；错误和校验信息仍保留在技术记录中。</p>}</div>
      </details>;
    })}</div> : outputs.length ? <div className="studio-opinion-list">{outputs.filter((output) => output.readable).map((output) => <details className="studio-opinion" key={output.output_id}><summary><span><strong>{output.model || "程序记录"}</strong><small>{resultStepLabel(output.step)} · {studioStatusLabel(output.status)}</small></span><Status value={output.status || "pending"} /></summary><div className="studio-opinion-body"><p className="studio-muted">第 {(output.round ?? 0) + 1} 版{output.attempt ? ` · 尝试 ${output.attempt}` : ""} · {formatStudioTime(output.created_at)}</p><p>完整结果已在中间区域按步骤展示，可从那里选择并排对照。</p></div></details>)}</div> : <p className="studio-muted">暂无模型意见。任务完成后，完整结果会按步骤保存。</p>}
  </section>;
}

function SourceModelPanel({ job }: { job: JobDetail }) {
  const source = job.source;
  const kind = jobKind(job);
  const reason = jobReason(job);
  const accepted = job.accepted_results ?? [];
  return <aside className="studio-context-panel" aria-label="来源与模型意见">
    <section className="studio-context-section"><div className="studio-section-heading"><h2>来源范围</h2><span className="studio-context-lock" aria-label="固定来源">已固定</span></div>
      <dl className="studio-context-facts"><div><dt>任务</dt><dd>{job.task?.label || (kind === "narrative" ? "多史料综合任务" : "章节生产任务")}</dd></div><div><dt>资料</dt><dd>{job.document?.title || job.task?.title || "固定来源"}</dd></div><div><dt>版本</dt><dd>第 {source?.revision_no ?? job.document?.revision_no ?? "—"} 版</dd></div><div><dt>来源数量</dt><dd>{jobSourceCount(job)} {kind === "narrative" ? "份来源章节" : "个资料来源"}</dd></div><div><dt>绑定关系</dt><dd>{sourceRelationshipLabel(source?.relationship)}</dd></div></dl>
      <p className="studio-muted">此范围在任务创建时冻结；换模型新建运行会保留原任务与这份来源选择。</p><OriginalSource job={job} />
    </section>
    {job.current_step ? <section className="studio-context-section"><h2>当前步骤</h2><p className="studio-current-step"><strong>{job.current_step.label}</strong><Status value={job.current_step.status} /></p>{reason ? <p className="studio-context-reason">{reason}</p> : null}</section> : null}
    {accepted.length ? <section className="studio-context-section"><div className="studio-section-heading"><h2>采用稿</h2><span className="studio-muted">{accepted.length} 项</span></div><div className="studio-adopted-list">{accepted.map((item, index) => <div className="studio-adopted-item" key={item.acceptance_id ?? index}><strong>{item.kind === "facts" ? "事实结论" : item.kind === "prose" ? "历史正文" : item.kind || "已保存结果"}</strong><span>{acceptedDecisionLabel(item.decision)}</span><p>保留 {acceptedEvidenceCount(item)} 份模型意见作为依据，草稿版本已固定。{item.review_id ? "审核说明已归档。" : "理由正文未随任务摘要返回。"}</p></div>)}</div></section> : null}
    <ModelOpinionPanel job={job} />
  </aside>;
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
  const authoritativeActions = hasAuthoritativeActions(job);
  const chunks = job.chunks ?? [];
  const outputs = job.outputs ?? [];
  const reviews = job.reviews ?? [];
  const actions = useMutation({
    mutationFn: async (name: "retry" | "resume" | "cancel") => {
      if (authoritativeActions && !actionEnabled(job, name)) {
        throw new Error(jobAction(job, name)?.reason || "当前任务不允许该操作");
      }
      const updated = await mutateJob(auth, job.job_id, name);
      if (updated.job_id !== job.job_id) throw new Error("服务器返回了不同的任务，当前页面未更新");
      return updated;
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData(["studio", "job", job.job_id], updated);
      setConfirmStop(false);
      await queryClient.invalidateQueries({ queryKey: ["studio", "jobs"] });
    },
  });
  const rerun = useMutation({
    mutationFn: async () => {
      if (authoritativeActions && !actionEnabled(job, "new_run")) {
        throw new Error(jobAction(job, "new_run")?.reason || "当前任务不允许新建运行");
      }
      const created = authoritativeActions
        ? await newRunJob(auth, job.job_id, selection)
        : await rerunJob(auth, job.job_id, selection);
      if (!created.job_id || created.job_id === job.job_id) throw new Error("服务器没有返回新的任务");
      return created;
    },
    onSuccess: async (created) => {
      setNewJob(created);
      await queryClient.invalidateQueries({ queryKey: ["studio", "jobs"] });
    },
  });
  const current = currentWorkspaceStep(job);
  const active = currentStage(job);
  const stage = selectedStage ?? active ?? (jobKind(job) === "narrative" ? "present" : "extract");
  const steps = jobSteps(job);
  const visibleSteps = steps.filter((item) => item.status !== "skipped");
  const stageInfo = steps.find((item) => item.key === stage);
  const chunk = chunks.find((item) => item.chunk_id === selectedChunk)
    ?? chunks.find((item) => ["running", "failed", "needs_review"].includes(item.status)) ?? chunks[0];
  const step = selectedStep ?? (chunk && PRODUCTION_STEPS.find((item) => ["started", "failed", "invalid", "interrupted"].includes(stepState(chunk, item.id, job.status)))?.id)
    ?? chunk?.production?.step ?? current?.key ?? "translation";
  const completed = visibleSteps.filter((item) => item.status === "completed").length;
  const reviewLink = `/studio/review?status=open&review_scope=all&job_id=${encodeURIComponent(job.job_id)}`;
  const canRetry = authoritativeActions ? actionEnabled(job, "retry") : job.status === "failed" && job.attempt < job.max_attempts;
  const canResume = authoritativeActions ? actionEnabled(job, "resume") : job.status === "needs_review" && job.open_reviews === 0;
  const canCancel = authoritativeActions ? actionEnabled(job, "cancel") : jobIsLive(job.status);
  const canNewRun = authoritativeActions ? actionEnabled(job, "new_run") : ["failed", "cancelled"].includes(job.status);
  const statusForStep = (item: typeof PRODUCTION_STEPS[number]) => {
    if (chunk?.production?.steps.length) return stepState(chunk, item.id, job.status);
    const graphStep = steps.find((entry) => entry.key === item.id || (item.id === "extraction" && entry.key === "extract"));
    return graphStep?.status ?? "pending";
  };
  return <div className="studio-stack" data-view="studio-import-detail">
    <Link className="studio-back-link" to="/studio/imports">← 返回任务列表</Link>
    <div className="studio-page-heading"><div><p className="studio-eyebrow">{jobKind(job) === "narrative" ? "综合历史" : "资料生产"}</p><h1>{jobTitle(job)}</h1><p className="studio-muted">{job.document ? `第 ${job.document.revision_no} 版 · ` : ""}{formatStudioTime(job.created_at)} 创建</p></div><Status value={job.status} /></div>
    <div className="studio-job-banner" data-status={job.status}>
      <div><strong>{jobNextAction(job)}</strong><p>{job.status === "failed" ? failureAdvice(job.error) : `${completed} / ${visibleSteps.length} 个主要阶段完成${chunks.length ? ` · ${chunks.filter((item) => item.status === "completed").length} / ${chunks.length} 章完成` : ""}`}</p></div>
      {job.open_reviews > 0 ? <Link className="studio-link-button studio-link-primary" to={reviewLink}>处理 {job.open_reviews} 项审核</Link> : null}
    </div>
    {job.status === "failed" && !canRetry ? <p className="studio-muted">本次任务暂时不能重试；可查看记录后，按服务端提供的操作创建新运行。</p> : null}
    {job.error ? <details className="studio-details"><summary>查看失败的详细原因</summary><p className="studio-readable-error">{job.error}</p></details> : null}
    {actions.error ? <p role="alert" className="studio-error">操作未完成：{actions.error.message}</p> : null}
    {showRerun ? <section className="studio-panel"><h2>重新处理这份范围</h2><p className="studio-muted">将沿用这次任务冻结的资料版本或历史来源选择，使用新模型创建独立运行。原任务、已保存结果和审核意见保留，可随时返回对照。</p>
      <ModelSelector value={selection} onChange={setSelection} onReady={setModelReady} disabled={rerun.isPending || Boolean(newJob)} />
      {newJob ? <p role="status">新任务已创建，模型选择已记录。<Link to={`/studio/imports/${newJob.job_id}`}>查看新任务 →</Link></p> : <Button disabled={rerun.isPending || !modelReady} onClick={() => rerun.mutate()}>{rerun.isPending ? "正在创建…" : "新建任务并重新处理"}</Button>}
      {rerun.error ? <p role="alert" className="studio-error">{rerun.error.message}</p> : null}
    </section> : null}
    {job.production_request?.parent_job_id ? <p className="studio-muted">本次重新处理关联至 <Link to={`/studio/imports/${job.production_request.parent_job_id}`}>原任务与结果</Link>。</p> : null}
    <div className="studio-workspace studio-import-detail-workspace">
      <aside className="studio-process-rail" aria-label="任务流程"><h2>处理流程</h2><ol>{visibleSteps.map((item, index) => <li key={item.key} data-status={item.status}><button type="button" aria-current={stage === item.key ? "step" : undefined} onClick={() => setSelectedStage(item.key)}>
        <span className="studio-process-dot" aria-hidden="true">{item.status === "completed" ? "✓" : index + 1}</span><span><strong>{item.label || stageLabel(item.key)}</strong><small>{studioStatusLabel(item.status)}</small>{item.failure_reason ? <small className="studio-step-reason">{item.failure_reason}</small> : null}</span>
      </button></li>)}</ol><p className="studio-muted">已完成结果逐步保存，刷新后继续跟踪。</p></aside>
      <div className="studio-workspace-body">
        <section className="studio-panel"><div className="studio-section-heading"><h2>{jobKind(job) === "narrative" ? "历史正文生产" : stageInfo?.label || stageLabel(stage)}</h2><span className="studio-muted">{formatStudioTime(job.updated_at)} 更新</span></div>
          {chunk ? <>
            <div className="studio-chapter-switch"><label>当前章节<select className="studio-select" value={chunk.chunk_id} onChange={(event) => { setSelectedChunk(event.target.value); setSelectedStep(null); }}>{chunks.map((item) => <option key={item.chunk_id} value={item.chunk_id}>{item.title || `第 ${item.chunk_index + 1} 章`} · {studioStatusLabel(item.status)}</option>)}</select></label><span className="studio-muted">{(chunk.source_end - chunk.source_start).toLocaleString()} 字原文 · 完整章节语境</span></div>
            <div className="studio-step-grid" aria-label="章节处理进度">{PRODUCTION_STEPS.map((item) => { const status = statusForStep(item); return <button type="button" key={item.id} className="studio-step-tile" data-status={status} aria-pressed={step === item.id} onClick={() => setSelectedStep(item.id)}><strong>{item.label}</strong><Status value={status} /><small>{item.description}</small></button>; })}</div>
            <ResultComparison key={`${chunk.chunk_id}:${step}`} jobId={job.job_id} outputs={outputs.filter((item) => !item.chunk_id || item.chunk_id === chunk.chunk_id)} attempts={job.attempts} acceptedResults={job.accepted_results} selectedStep={step} />
            {outputs.some((item) => item.chunk_id === chunk.chunk_id && item.artifact_type === "chapter-production-draft") ? <details className="studio-details"><summary>汇总稿与历次修订</summary><ResultComparison key={`${chunk.chunk_id}:drafts`} jobId={job.job_id} outputs={outputs.filter((item) => item.chunk_id === chunk.chunk_id && item.artifact_type === "chapter-production-draft")} attempts={[]} selectedStep={null} /></details> : null}
            <details className="studio-details"><summary>本章执行记录</summary><div className="studio-table">{chunk.production?.steps.map((entry, index) => <div className="studio-table-row" key={entry.output_sha256 ?? index}><div><strong>{stepLabel(entry.step)}</strong><p className="studio-muted">{entry.model} · 尝试 {entry.attempt ?? 1}{entry.elapsed_seconds != null ? ` · ${entry.elapsed_seconds.toFixed(1)} 秒` : ""} · 输出用量 {entry.usage?.output_tokens ?? "未报告"}</p></div><Status value={entry.status ?? "pending"} /></div>)}</div></details>
          </> : <>
            <p className="studio-muted">{jobKind(job) === "narrative" ? `基于 ${jobSourceCount(job)} 个完整来源章节，先核对事实，再审核连续正文与精选入口。` : stage === "structure" || stage === "segment" ? "按自然章节准备完整上下文，每章保留原文与原注，再独立翻译和提取。" : "本阶段沿用已保存的上游结果。需要人工判断时，审核入口会显示在下方。"}</p>
            <ResultComparison jobId={job.job_id} outputs={outputs} attempts={job.attempts} acceptedResults={job.accepted_results} selectedStep={stage} />
            {chunks.length ? <div className="studio-table">{chunks.map((item) => <button type="button" className="studio-list-row" key={item.chunk_id} onClick={() => { setSelectedChunk(item.chunk_id); setSelectedStage("extract"); }}><span><strong>{item.title || `第 ${item.chunk_index + 1} 章`}</strong><small>{(item.source_end - item.source_start).toLocaleString()} 字原文</small></span><Status value={item.status} /></button>)}</div> : <p className="studio-muted">{jobKind(job) === "narrative" ? "来源章节已固定，处理意见会在审核项中集中呈现。" : "章节识别完成后，这里显示各章进度。"}</p>}
          </>}
        </section>
        {reviews.length ? <section className="studio-panel"><div className="studio-section-heading"><h2>内容核对</h2><Link to={reviewLink}>查看审核队列 →</Link></div><div className="studio-table">{reviews.map((review) => <Link className="studio-table-row" key={review.review_id} to={`/studio/review/${review.review_id}?review_scope=all&job_id=${job.job_id}`}><div><strong>{reviewKind(review.scope, review.narrative_kind)}</strong><p className="studio-muted">{formatStudioTime(review.created_at)}</p></div><Status value={review.status} /><span aria-hidden="true">→</span></Link>)}</div></section> : null}
        {job.status === "completed" ? <section className="studio-panel"><h2>处理成果</h2><p>{jobKind(job) === "narrative" ? "连续历史正文已通过审核并发布。" : "本次资料已完成处理，可作为综合历史叙事的来源。"}</p><Link className="studio-link-button" to={jobKind(job) === "narrative" ? "/history" : "/studio/imports?create=history"}>{jobKind(job) === "narrative" ? "查看历史阅读页 →" : "选择来源并生成综合历史 →"}</Link></section> : null}
      </div>
      <SourceModelPanel job={job} />
    </div>
    <div className="studio-production-actionbar" role="toolbar" aria-label="任务操作">
      <Link className="studio-link-button" to="/studio/imports">返回任务列表</Link>
      {job.open_reviews > 0 ? <Link className="studio-link-button studio-link-primary" to={reviewLink}>处理审核并继续</Link> : null}
      <span className="studio-production-action-spacer" />
      {canRetry ? <Button disabled={actions.isPending} onClick={() => actions.mutate("retry")}>{actions.isPending ? "正在重试…" : "重试未完成步骤"}</Button> : null}
      {canResume ? <Button disabled={actions.isPending} onClick={() => actions.mutate("resume")}>{actions.isPending ? "正在继续…" : "继续生产"}</Button> : null}
      {canNewRun ? <Button variant="outline" onClick={() => setShowRerun((value) => !value)}>{showRerun ? "收起换模型" : "换模型重新处理"}</Button> : null}
      {canCancel ? confirmStop ? <><span className="studio-muted">停止后保留已保存结果。</span><Button variant="destructive" disabled={actions.isPending} onClick={() => actions.mutate("cancel")}>确认停止任务</Button><Button variant="outline" onClick={() => setConfirmStop(false)}>继续保留任务</Button></> : <Button variant="outline" onClick={() => setConfirmStop(true)}>停止任务</Button> : null}
    </div>
    <details className="studio-panel studio-details"><summary>技术记录与任务操作</summary><dl className="studio-facts"><div><dt>任务编号</dt><dd className="studio-mono">{job.job_id}</dd></div><div><dt>资料版本编号</dt><dd className="studio-mono">{job.revision_id}</dd></div><div><dt>任务尝试</dt><dd>{job.attempt} / {job.max_attempts}</dd></div><div><dt>已保存产物</dt><dd>{outputs.length || job.results?.length || 0} 份</dd></div></dl>
      <details><summary>查看完整运行元数据</summary><pre className="studio-code">{JSON.stringify(job, null, 2)}</pre></details>
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
