import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Input } from "../../components/ui/input";
import { useStudioAuth } from "../../lib/studio-auth";
import { studioStatusLabel } from "../../lib/studio-i18n";
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
        <small>{document.revision_count} 个版本 · {formatTime(document.created_at)}</small>
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
          <Badge>{studioStatusLabel(revision.status)}</Badge>
          {revision.duplicate ? <Badge>重复上传</Badge> : null}
        </div>
        <div className="studio-muted">
          {revision.filename} · {revision.source_bytes.toLocaleString()} 字节 · {revision.language ?? "语言未标记"}
        </div>
        <div className="studio-muted studio-mono">sha256 {formatShortHash(revision.source_sha256)}</div>
      </div>
      <div className="studio-row-actions">
        <span className="studio-muted">{formatTime(revision.created_at)}</span>
        <Button size="sm" onClick={onStart} disabled={starting || revision.storage_status !== "present"}>
          {starting ? "正在创建…" : "开始导入处理"}
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
          <p className="studio-eyebrow">C1 · 语料生产</p>
          <h1>文献与导入</h1>
          <p className="studio-muted">上传不可变文献版本，启动导入处理，并从持久化 PostgreSQL 状态查看进度。</p>
        </div>
        <Button variant="outline" onClick={() => void jobs.refetch()} disabled={jobs.isFetching}>
          {jobs.isFetching ? "刷新中…" : "刷新作业"}
        </Button>
      </div>

      <div className="studio-grid studio-grid-wide">
        <Card>
          <CardHeader>
            <CardTitle>文献</CardTitle>
            <CardDescription>逻辑文献容器；替换原文时新增版本，不覆盖旧版本。</CardDescription>
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
                aria-label="文献标题"
              />
              <Button type="submit" disabled={!newTitle.trim() || createDocumentMutation.isPending}>
                新建
              </Button>
            </form>
            {createDocumentMutation.error ? <p className="studio-error">{errorText(createDocumentMutation.error)}</p> : null}
            <div className="studio-list" aria-label="文献列表">
              {documents.isLoading ? <p className="studio-muted">正在读取文献…</p> : null}
              {documents.error ? <p className="studio-error">{errorText(documents.error)}</p> : null}
              {documents.data?.length === 0 ? <p className="studio-muted">还没有文献。</p> : null}
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
            <CardTitle>上传新版本</CardTitle>
            <CardDescription>
              {selectedDocument ? `当前文献：${selectedDocument.title}` : "先创建或选择一份文献"}
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
                  <label className="studio-label" htmlFor="studio-language">语言</label>
                  <Input id="studio-language" value={language} onChange={(event) => setLanguage(event.target.value)} placeholder="zh-Hant" />
                </div>
                <div>
                  <label className="studio-label" htmlFor="studio-source-label">来源标签</label>
                  <Input id="studio-source-label" value={sourceLabel} onChange={(event) => setSourceLabel(event.target.value)} placeholder="版本 / 来源备注（可选）" />
                </div>
              </div>
              <Button
                type="submit"
                disabled={!resolvedDocumentId || !file || !mediaTypeForUpload(file.name) || uploadMutation.isPending}
              >
                {uploadMutation.isPending ? "上传中…" : "上传为新版本"}
              </Button>
            </form>
            {uploadMutation.error ? <p className="studio-error">{errorText(uploadMutation.error)}</p> : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>版本历史</CardTitle>
          <CardDescription>
            {selectedDocument ? `${selectedDocument.title} · 当前版本与已替换版本均保留` : "选择文献后显示版本历史"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {revisions.isLoading && resolvedDocumentId ? <p className="studio-muted">读取版本…</p> : null}
          {revisions.error ? <p className="studio-error">{errorText(revisions.error)}</p> : null}
          {!resolvedDocumentId ? <p className="studio-muted">暂无文献。</p> : null}
          {revisions.data?.length === 0 ? <p className="studio-muted">还没有上传版本。</p> : null}
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
              <CardTitle>导入作业</CardTitle>
              <CardDescription>每 4 秒轮询 持久化作业状态；刷新页面不会丢失进度。</CardDescription>
            </div>
            <select
              className="studio-select"
              value={jobFilter}
              onChange={(event) => setJobFilter(event.target.value as JobStatus | "all")}
              aria-label="作业状态筛选"
            >
              {JOB_STATUSES.map((status) => <option key={status} value={status}>{status === "all" ? "全部状态" : studioStatusLabel(status)}</option>)}
            </select>
          </div>
        </CardHeader>
        <CardContent>
          {jobs.isLoading ? <p className="studio-muted">读取作业…</p> : null}
          {jobs.error ? <p className="studio-error">{errorText(jobs.error)}</p> : null}
          {jobs.data?.length === 0 ? <p className="studio-muted">当前筛选没有作业。</p> : null}
          <div className="studio-table">
            {jobs.data?.map((job) => (
              <Link className="studio-table-row studio-job-row" key={job.job_id} to={`/studio/imports/${job.job_id}`}>
                <div>
                  <div className="studio-row-title">
                    <Badge>{studioStatusLabel(job.status)}</Badge>
                    <strong className="studio-mono">{job.job_id.slice(0, 8)}</strong>
                  </div>
                  <div className="studio-muted studio-mono">版本 {job.revision_id.slice(0, 8)} · 尝试 {job.attempt}/{job.max_attempts}</div>
                  {job.error ? <div className="studio-error studio-ellipsis">{job.error}</div> : null}
                </div>
                <div className="studio-job-progress">
                  <strong>{job.completed_stages}/8 阶段</strong>
                  <span>{job.chunk_count} 分段</span>
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
