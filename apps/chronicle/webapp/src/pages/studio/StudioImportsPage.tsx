import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { useStudioAuth } from "../../lib/studio-auth";
import {
  createDocument,
  formatShortHash,
  listDocuments,
  listJobs,
  listRevisions,
  mediaTypeForUpload,
  queueJob,
  StudioApiError,
  uploadRevision,
  type DocumentSummary,
  type JobStatus,
  type Revision,
} from "../../lib/studio-api";

const JOB_STATUSES: Array<JobStatus | "all"> = [
  "all",
  "queued",
  "running",
  "needs_review",
  "failed",
  "cancelled",
  "completed",
];

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

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "排队中",
    running: "处理中",
    needs_review: "待评审",
    failed: "失败",
    cancelled: "已取消",
    completed: "完成",
    active: "当前版本",
    superseded: "已替换",
  };
  return labels[status] ?? status;
}

function DocumentRow({
  document,
  selected,
  onSelect,
}: {
  document: DocumentSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`studio-list-row ${selected ? "is-selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <span>
        <strong>{document.title}</strong>
        <small>{document.revision_count} 个 revision · {formatTime(document.created_at)}</small>
      </span>
      <span className="studio-mono">{formatShortHash(document.active_source_sha256)}</span>
    </button>
  );
}

function RevisionRow({
  revision,
  onStart,
  starting,
}: {
  revision: Revision;
  onStart: () => void;
  starting: boolean;
}) {
  return (
    <div className="studio-table-row studio-revision-row">
      <div>
        <div className="studio-row-title">
          <strong>r{revision.revision_no}</strong>
          <Badge>{statusLabel(revision.status)}</Badge>
          {revision.duplicate ? <Badge>duplicate</Badge> : null}
        </div>
        <div className="studio-muted">
          {revision.filename} · {revision.source_bytes.toLocaleString()} bytes · {revision.language ?? "language 未标记"}
        </div>
        <div className="studio-muted studio-mono">sha256 {formatShortHash(revision.source_sha256)}</div>
      </div>
      <div className="studio-row-actions">
        <span className="studio-muted">{formatTime(revision.created_at)}</span>
        <Button size="sm" onClick={onStart} disabled={starting || revision.storage_status !== "present"}>
          {starting ? "正在创建…" : "开始 Ingestion"}
        </Button>
      </div>
    </div>
  );
}

export default function StudioImportsPage() {
  const auth = useStudioAuth();
  const authHeader = auth.authHeader();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("zh-Hant");
  const [sourceLabel, setSourceLabel] = useState("");
  const [jobFilter, setJobFilter] = useState<JobStatus | "all">("all");

  const documents = useQuery({
    queryKey: ["studio", "documents"],
    queryFn: () => listDocuments(authHeader),
  });

  const resolvedDocumentId = selectedDocumentId ?? documents.data?.[0]?.document_id ?? null;
  const revisions = useQuery({
    queryKey: ["studio", "revisions", resolvedDocumentId],
    queryFn: () => listRevisions(authHeader, resolvedDocumentId as string),
    enabled: Boolean(resolvedDocumentId),
  });

  const jobs = useQuery({
    queryKey: ["studio", "jobs", jobFilter],
    queryFn: () => listJobs(authHeader, jobFilter === "all" ? undefined : jobFilter),
    refetchInterval: 4000,
  });

  const createDocumentMutation = useMutation({
    mutationFn: (title: string) => createDocument(authHeader, title),
    onSuccess: async (document) => {
      setNewTitle("");
      setSelectedDocumentId(document.document_id);
      await queryClient.invalidateQueries({ queryKey: ["studio", "documents"] });
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!resolvedDocumentId || !file) throw new Error("请选择 Document 和文件");
      return uploadRevision(authHeader, resolvedDocumentId, file, { language, sourceLabel });
    },
    onSuccess: async () => {
      setFile(null);
      setSourceLabel("");
      const fileInput = document.getElementById("studio-revision-file") as HTMLInputElement | null;
      if (fileInput) fileInput.value = "";
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["studio", "documents"] }),
        queryClient.invalidateQueries({ queryKey: ["studio", "revisions", resolvedDocumentId] }),
      ]);
    },
  });

  const queueMutation = useMutation({
    mutationFn: (revisionId: string) => queueJob(authHeader, revisionId),
    onSuccess: async (job) => {
      await queryClient.invalidateQueries({ queryKey: ["studio", "jobs"] });
      navigate(`/studio/imports/${job.job_id}`);
    },
  });

  const selectedDocument = useMemo(
    () => documents.data?.find((item) => item.document_id === resolvedDocumentId) ?? null,
    [documents.data, resolvedDocumentId],
  );

  return (
    <div className="studio-stack" data-view="studio-imports">
      <div className="studio-page-heading">
        <div>
          <p className="studio-eyebrow">C1 · corpus production</p>
          <h1>Documents & Imports</h1>
          <p className="studio-muted">上传不可变文献版本，启动 ingestion，并从 durable PostgreSQL 状态查看进度。</p>
        </div>
        <Button variant="outline" onClick={() => void jobs.refetch()} disabled={jobs.isFetching}>
          {jobs.isFetching ? "刷新中…" : "刷新 Jobs"}
        </Button>
      </div>

      <div className="studio-grid studio-grid-wide">
        <Card>
          <CardHeader>
            <CardTitle>Documents</CardTitle>
            <CardDescription>逻辑文献容器；替换原文时新增 Revision，不覆盖旧版本。</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="studio-inline-form"
              onSubmit={(event) => {
                event.preventDefault();
                const title = newTitle.trim();
                if (title) createDocumentMutation.mutate(title);
              }}
            >
              <Input
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
                placeholder="例如：三国志·蜀书·先主传"
                aria-label="Document 标题"
              />
              <Button type="submit" disabled={!newTitle.trim() || createDocumentMutation.isPending}>
                新建
              </Button>
            </form>
            {createDocumentMutation.error ? <p className="studio-error">{errorText(createDocumentMutation.error)}</p> : null}
            <div className="studio-list" aria-label="Documents">
              {documents.isLoading ? <p className="studio-muted">正在读取 Documents…</p> : null}
              {documents.error ? <p className="studio-error">{errorText(documents.error)}</p> : null}
              {documents.data?.length === 0 ? <p className="studio-muted">还没有 Document。</p> : null}
              {documents.data?.map((document) => (
                <DocumentRow
                  key={document.document_id}
                  document={document}
                  selected={document.document_id === resolvedDocumentId}
                  onSelect={() => setSelectedDocumentId(document.document_id)}
                />
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Upload Revision</CardTitle>
            <CardDescription>
              {selectedDocument ? `当前 Document：${selectedDocument.title}` : "先创建或选择一个 Document"}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="studio-form"
              onSubmit={(event) => {
                event.preventDefault();
                uploadMutation.mutate();
              }}
            >
              <div>
                <label className="studio-label" htmlFor="studio-revision-file">UTF-8 文献文件</label>
                <Input
                  id="studio-revision-file"
                  type="file"
                  accept=".txt,.md,text/plain,text/markdown"
                  disabled={!resolvedDocumentId}
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
                {file && !mediaTypeForUpload(file.name) ? <p className="studio-error">只支持 .txt 或 .md。</p> : null}
              </div>
              <div className="studio-grid studio-grid-compact">
                <div>
                  <label className="studio-label" htmlFor="studio-language">Language</label>
                  <Input id="studio-language" value={language} onChange={(event) => setLanguage(event.target.value)} placeholder="zh-Hant" />
                </div>
                <div>
                  <label className="studio-label" htmlFor="studio-source-label">Source label</label>
                  <Input id="studio-source-label" value={sourceLabel} onChange={(event) => setSourceLabel(event.target.value)} placeholder="edition / 来源备注（可选）" />
                </div>
              </div>
              <Button
                type="submit"
                disabled={!resolvedDocumentId || !file || !mediaTypeForUpload(file.name) || uploadMutation.isPending}
              >
                {uploadMutation.isPending ? "上传中…" : "上传为新 Revision"}
              </Button>
            </form>
            {uploadMutation.error ? <p className="studio-error">{errorText(uploadMutation.error)}</p> : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Revision history</CardTitle>
          <CardDescription>
            {selectedDocument ? `${selectedDocument.title} · active 与 superseded 均保留` : "选择 Document 后显示版本历史"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {revisions.isLoading && resolvedDocumentId ? <p className="studio-muted">读取 Revision…</p> : null}
          {revisions.error ? <p className="studio-error">{errorText(revisions.error)}</p> : null}
          {!resolvedDocumentId ? <p className="studio-muted">暂无 Document。</p> : null}
          {revisions.data?.length === 0 ? <p className="studio-muted">还没有上传 Revision。</p> : null}
          <div className="studio-table">
            {revisions.data?.slice().reverse().map((revision) => (
              <RevisionRow
                key={revision.revision_id}
                revision={revision}
                onStart={() => queueMutation.mutate(revision.revision_id)}
                starting={queueMutation.isPending && queueMutation.variables === revision.revision_id}
              />
            ))}
          </div>
          {queueMutation.error ? <p className="studio-error">{errorText(queueMutation.error)}</p> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="studio-card-title-row">
            <div>
              <CardTitle>Ingestion Jobs</CardTitle>
              <CardDescription>每 4 秒轮询 durable job 状态；刷新页面不会丢失进度。</CardDescription>
            </div>
            <select
              className="studio-select"
              value={jobFilter}
              onChange={(event) => setJobFilter(event.target.value as JobStatus | "all")}
              aria-label="Job 状态筛选"
            >
              {JOB_STATUSES.map((status) => <option key={status} value={status}>{status === "all" ? "全部状态" : statusLabel(status)}</option>)}
            </select>
          </div>
        </CardHeader>
        <CardContent>
          {jobs.isLoading ? <p className="studio-muted">读取 Jobs…</p> : null}
          {jobs.error ? <p className="studio-error">{errorText(jobs.error)}</p> : null}
          {jobs.data?.length === 0 ? <p className="studio-muted">当前筛选没有 Job。</p> : null}
          <div className="studio-table">
            {jobs.data?.map((job) => (
              <Link className="studio-table-row studio-job-row" key={job.job_id} to={`/studio/imports/${job.job_id}`}>
                <div>
                  <div className="studio-row-title">
                    <Badge>{statusLabel(job.status)}</Badge>
                    <strong className="studio-mono">{job.job_id.slice(0, 8)}</strong>
                  </div>
                  <div className="studio-muted studio-mono">revision {job.revision_id.slice(0, 8)} · attempt {job.attempt}/{job.max_attempts}</div>
                  {job.error ? <div className="studio-error studio-ellipsis">{job.error}</div> : null}
                </div>
                <div className="studio-job-progress">
                  <strong>{job.completed_stages}/8 stages</strong>
                  <span>{job.chunk_count} chunks</span>
                  <span>{formatTime(job.updated_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
