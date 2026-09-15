import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { useStudioAuth } from "../../lib/studio-auth";
import NarrativeProductionPanel from "../../components/studio/NarrativeProductionPanel";
import { studioStatusLabel } from "../../lib/studio-i18n";
import { listJobs, type JobStatus } from "../../lib/studio-api";
import { currentWorkspaceStep, formatStudioTime, jobKind, jobNextAction, jobReason, jobSourceCount, jobTitle } from "../../lib/studio-workspace";

const FILTERS: Array<{ id: JobStatus | "all"; label: string }> = [
  { id: "all", label: "全部任务" }, { id: "running", label: "处理中" }, { id: "needs_review", label: "等待核对" },
  { id: "failed", label: "需要处理" }, { id: "completed", label: "已完成" }, { id: "queued", label: "排队中" }, { id: "cancelled", label: "已停止" },
];

export default function StudioImportsPage() {
  const auth = useStudioAuth().authHeader();
  const [params, setParams] = useSearchParams();
  const rawStatus = params.get("status");
  const status = FILTERS.find((item) => item.id === rawStatus)?.id ?? "all";
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const creating = params.get("create") === "history";
  const [search, setSearch] = useState("");
  const jobs = useQuery({ queryKey: ["studio", "jobs", status, offset], queryFn: () => listJobs(auth, status === "all" ? undefined : status, offset), refetchInterval: 4000 });
  const visible = useMemo(() => (jobs.data ?? []).filter((job) => !search.trim() || jobTitle(job).toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())), [jobs.data, search]);
  const groups = useMemo(() => ([
    { key: "chapter" as const, label: "单份资料任务", items: visible.filter((job) => jobKind(job) === "chapter") },
    { key: "narrative" as const, label: "综合历史任务", items: visible.filter((job) => jobKind(job) === "narrative") },
  ].filter((group) => group.items.length)), [visible]);
  const update = (key: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); if (key === "status") next.delete("offset"); setParams(next); };
  return <div className="studio-stack" data-view="studio-imports">
    <div className="studio-page-heading"><div><p className="studio-eyebrow">内容生产</p><h1>生产任务</h1><p className="studio-muted">从完整史料到连续历史，跟踪每一步的进展与结果。</p></div><div className="studio-row-actions"><Link className="studio-link-button" to="/studio/sources?upload=1">上传资料</Link><Button onClick={() => update("create", creating ? "" : "history")}>{creating ? "收起创建" : "生成历史正文"}</Button></div></div>
    {creating ? <NarrativeProductionPanel /> : null}
    <section className="studio-panel studio-tasks-panel">
      <div className="studio-filter-row studio-segmented" aria-label="任务状态">{FILTERS.map((filter) => <button type="button" key={filter.id} aria-pressed={filter.id === status} onClick={() => update("status", filter.id)}>{filter.label}</button>)}</div>
      <div className="studio-section-heading"><Input aria-label="搜索当前页任务" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="按资料名称搜索当前页" /><Button variant="ghost" size="sm" disabled={jobs.isFetching} onClick={() => void jobs.refetch()}>{jobs.isFetching ? "更新中…" : "刷新"}</Button></div>
      {jobs.isPending ? <p className="studio-muted">正在读取生产任务…</p> : null}
      {jobs.error ? <p role="alert" className="studio-error">任务读取失败：{jobs.error.message}</p> : null}
      {jobs.data && visible.length === 0 ? <div className="studio-empty"><strong>{search ? "本页没有匹配的任务" : "当前没有这类任务"}</strong><p>上传一份完整资料，即可开始翻译与信息提取。</p></div> : null}
      <div className="studio-task-groups" aria-label="生产任务列表">
        {groups.map((group) => <section className="studio-task-group" key={group.key}>
          <div className="studio-section-heading"><h2>{group.label}</h2><span className="studio-muted">{group.items.length} 项</span></div>
          <div className="studio-task-list">
            {group.items.map((job) => {
              const current = currentWorkspaceStep(job);
              const reason = jobReason(job);
              const kind = jobKind(job);
              return <Link className="studio-task-row" data-task-kind={kind} data-current-step={current?.key ?? undefined} key={job.job_id} to={`/studio/imports/${job.job_id}`}>
                <span className="studio-task-glyph" aria-hidden="true">{kind === "narrative" ? "史" : "文"}</span>
                <div className="studio-task-name"><strong>{jobTitle(job)}</strong><small>{job.document ? `第 ${job.document.revision_no} 版 · ` : ""}{kind === "narrative" ? `${jobSourceCount(job)} 份来源章节` : job.chunk_count ? `${job.chunk_count} 个完整章节` : "准备资料"}{current ? ` · 当前：${current.label}` : ""}</small></div>
                <div className="studio-task-state"><span className="studio-status" data-status={job.status}>{studioStatusLabel(job.status)}</span><small>{jobNextAction(job)}</small>{reason && ["failed", "needs_review"].includes(job.status) ? <small className="studio-task-reason">原因：{reason}</small> : null}</div>
                <time>{formatStudioTime(job.updated_at)}</time><span className="studio-task-arrow" aria-hidden="true">→</span>
              </Link>;
            })}
          </div>
        </section>)}
      </div>
      <div className="studio-pagination studio-row-actions"><span className="studio-muted">第 {Math.floor(offset / 100) + 1} 页 · 本页 {jobs.data?.length ?? 0} 项</span><div className="studio-row-actions"><Button size="sm" variant="outline" disabled={offset === 0 || jobs.isFetching} onClick={() => update("offset", String(Math.max(0, offset - 100)))}>上一页</Button><Button size="sm" variant="outline" disabled={(jobs.data?.length ?? 0) < 100 || jobs.isFetching} onClick={() => update("offset", String(offset + 100))}>下一页</Button></div></div>
    </section>
  </div>;
}
