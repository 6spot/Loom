import { useMemo, useState } from "react";
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
  listRevisions,
  mediaTypeForUpload,
  StudioApiError,
  uploadRevision,
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

export default function StudioSourcesPage() {
  const auth = useStudioAuth();
  const authHeader = auth.authHeader();
  const queryClient = useQueryClient();
  const [selectedDocumentId, setSelectedDocumentId] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [language, setLanguage] = useState("zh-Hant");
  const [sourceLabel, setSourceLabel] = useState("");

  const documents = useQuery({
    queryKey: ["studio", "documents"],
    queryFn: () => listDocuments(authHeader),
  });
  const resolvedDocumentId = selectedDocumentId ?? documents.data?.[0]?.document_id ?? null;
  const selectedDocument = useMemo(
    () => documents.data?.find((item) => item.document_id === resolvedDocumentId) ?? null,
    [documents.data, resolvedDocumentId],
  );
  const revisions = useQuery({
    queryKey: ["studio", "revisions", resolvedDocumentId],
    queryFn: () => listRevisions(authHeader, resolvedDocumentId as string),
    enabled: Boolean(resolvedDocumentId),
  });

  const createMutation = useMutation({
    mutationFn: (title: string) => createDocument(authHeader, title),
    onSuccess: async (document) => {
      setNewTitle("");
      setSelectedDocumentId(document.document_id);
      await queryClient.invalidateQueries({ queryKey: ["studio", "documents"] });
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!resolvedDocumentId || !file) throw new Error("请选择文献和文件");
      return uploadRevision(authHeader, resolvedDocumentId, file, { language, sourceLabel });
    },
    onSuccess: async () => {
      setFile(null);
      setFileInputKey((value) => value + 1);
      setSourceLabel("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["studio", "documents"] }),
        queryClient.invalidateQueries({ queryKey: ["studio", "revisions", resolvedDocumentId] }),
      ]);
    },
  });

  return (
    <div className="studio-stack" data-view="studio-sources">
      <div className="studio-page-heading">
        <div>
          <p className="studio-eyebrow">C1 · 来源登记</p>
          <h1>来源 / 文献</h1>
          <p className="studio-muted">
            管理逻辑文献 与不可变 版本。替换来源时永远新增 版本，旧版本与 哈希 保留用于审计和 来源追溯。
          </p>
        </div>
        <Button variant="outline" onClick={() => void documents.refetch()} disabled={documents.isFetching}>
          {documents.isFetching ? "刷新中…" : "刷新来源"}
        </Button>
      </div>

      <div className="studio-grid studio-grid-wide">
        <Card>
          <CardHeader>
            <CardTitle>文献</CardTitle>
            <CardDescription>一个 Document 对应一份逻辑史料，可以拥有多个不可变 版本。</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="studio-inline-form"
              onSubmit={(event) => {
                event.preventDefault();
                const title = newTitle.trim();
                if (title) createMutation.mutate(title);
              }}
            >
              <Input
                value={newTitle}
                onChange={(event) => setNewTitle(event.target.value)}
                placeholder="例如：三国志·蜀书·先主传"
                aria-label="文献标题"
              />
              <Button type="submit" disabled={!newTitle.trim() || createMutation.isPending}>
                新建
              </Button>
            </form>
            {createMutation.error ? <p className="studio-error">{errorText(createMutation.error)}</p> : null}
            <div className="studio-list" aria-label="来源文献">
              {documents.isLoading ? <p className="studio-muted">正在读取文献…</p> : null}
              {documents.error ? <p className="studio-error">{errorText(documents.error)}</p> : null}
              {documents.data?.length === 0 ? <p className="studio-muted">还没有文献。</p> : null}
              {documents.data?.map((document) => {
                const selected = document.document_id === resolvedDocumentId;
                return (
                  <button
                    key={document.document_id}
                    type="button"
                    className={`studio-list-row ${selected ? "is-selected" : ""}`}
                    onClick={() => setSelectedDocumentId(document.document_id)}
                    aria-pressed={selected}
                  >
                    <span>
                      <strong>{document.title}</strong>
                      <small>
                        {document.revision_count} 个版本 · 当前第 {document.active_revision_no ?? "—"}
                      </small>
                    </span>
                    <span className="studio-mono">{formatShortHash(document.active_source_sha256)}</span>
                  </button>
                );
              })}
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
                <label className="studio-label" htmlFor="studio-source-file">UTF-8 文献文件</label>
                <Input
                  key={fileInputKey}
                  id="studio-source-file"
                  type="file"
                  accept=".txt,.md,text/plain,text/markdown"
                  disabled={!resolvedDocumentId}
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
                {file && !mediaTypeForUpload(file.name) ? <p className="studio-error">只支持 .txt 或 .md。</p> : null}
              </div>
              <div className="studio-grid studio-grid-compact">
                <div>
                  <label className="studio-label" htmlFor="studio-source-language">语言</label>
                  <Input
                    id="studio-source-language"
                    value={language}
                    onChange={(event) => setLanguage(event.target.value)}
                    placeholder="zh-Hant"
                  />
                </div>
                <div>
                  <label className="studio-label" htmlFor="studio-source-label">来源标签</label>
                  <Input
                    id="studio-source-label"
                    value={sourceLabel}
                    onChange={(event) => setSourceLabel(event.target.value)}
                    placeholder="版本 / 来源备注（可选）"
                  />
                </div>
              </div>
              <Button
                type="submit"
                disabled={!resolvedDocumentId || !file || !mediaTypeForUpload(file.name) || uploadMutation.isPending}
              >
                {uploadMutation.isPending ? "上传中…" : "上传为新 版本"}
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
            {selectedDocument
              ? `${selectedDocument.title} · 当前版本与已替换版本均保留，不覆盖历史来源`
              : "选择文献后显示版本历史"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {revisions.isLoading && resolvedDocumentId ? <p className="studio-muted">读取版本…</p> : null}
          {revisions.error ? <p className="studio-error">{errorText(revisions.error)}</p> : null}
          {!resolvedDocumentId ? <p className="studio-muted">暂无文献。</p> : null}
          {revisions.data?.length === 0 ? <p className="studio-muted">还没有上传版本。</p> : null}
          <div className="studio-table">
            {revisions.data?.slice().reverse().map((revision) => (
              <div className="studio-table-row studio-revision-row" key={revision.revision_id}>
                <div>
                  <div className="studio-row-title">
                    <strong>r{revision.revision_no}</strong>
                    <Badge>{revision.status === "active" ? "当前版本" : "已替换"}</Badge>
                    {revision.duplicate ? <Badge>重复上传</Badge> : null}
                  </div>
                  <div className="studio-muted">
                    {revision.filename} · {revision.source_bytes.toLocaleString()} 字节 · {revision.content_chars.toLocaleString()} 字符
                  </div>
                  <div className="studio-muted">
                    {revision.language ?? "语言未标记"} · {revision.source_label ?? "来源标签未标记"}
                  </div>
                </div>
                <div className="studio-row-actions">
                  <span className="studio-mono">sha256 {formatShortHash(revision.source_sha256)}</span>
                  <span className="studio-muted">{formatTime(revision.created_at)}</span>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
