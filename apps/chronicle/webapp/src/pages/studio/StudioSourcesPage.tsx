import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { useStudioAuth } from "../../lib/studio-auth";
import { createDocument, listDocuments, listRevisions, mediaTypeForUpload, queueJob, uploadRevision, type ModelSelection, type Revision } from "../../lib/studio-api";
import { formatStudioTime } from "../../lib/studio-workspace";
import ModelSelector from "../../components/studio/ModelSelector";

function OriginalSource({ revision }: { revision: Revision }) {
  const auth = useStudioAuth().authHeader();
  const [expanded, setExpanded] = useState(false);
  const [limit, setLimit] = useState(16000);
  const source = useQuery({ queryKey: ["studio", "source-text", revision.revision_id], enabled: expanded, staleTime: Infinity,
    queryFn: async () => {
      const response = await fetch(`/api/v1/studio/documents/${encodeURIComponent(revision.document_id)}/revisions/${encodeURIComponent(revision.revision_id)}/content`, { headers: auth ? { Authorization: auth } : {} });
      if (!response.ok) throw new Error("原文暂时无法读取，请重试。");
      return response.text();
    },
  });
  return <details className="studio-source-preview" onToggle={(event) => setExpanded(event.currentTarget.open)}><summary>查看保存的原文</summary>
    {source.isFetching ? <p className="studio-muted">正在读取原文…</p> : null}
    {source.error ? <p className="studio-error" role="alert">{source.error.message}<Button variant="outline" size="sm" onClick={() => void source.refetch()}>重试读取</Button></p> : null}
    {source.data != null ? <><div className="studio-source-text">{source.data.slice(0, limit)}</div>{source.data.length > limit ? <Button variant="outline" size="sm" onClick={() => setLimit((value) => value + 16000)}>继续显示原文</Button> : <small className="studio-muted">已完整显示此版本原文。</small>}</> : null}
  </details>;
}

export default function StudioSourcesPage() {
  const auth = useStudioAuth().authHeader();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [target, setTarget] = useState("new");
  const [language, setLanguage] = useState("zh-Hant");
  const [label, setLabel] = useState("");
  const [selection, setSelection] = useState<ModelSelection>();
  const [modelReady, setModelReady] = useState(false);
  const [pendingRevision, setPendingRevision] = useState<Revision | null>(null);
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const fresh = useRef<{ title: string; id: string } | null>(null);
  const uploaded = useRef<Revision | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const documents = useQuery({ queryKey: ["studio", "documents"], queryFn: () => listDocuments(auth) });
  const id = params.get("document") ?? documents.data?.[0]?.document_id;
  const selected = documents.data?.find((document) => document.document_id === id);
  const uploading = params.has("upload");
  const revisions = useQuery({ queryKey: ["studio", "revisions", id], queryFn: () => listRevisions(auth, id!), enabled: Boolean(id) });
  const formChange = () => { uploaded.current = null; setNotice(""); };
  const mutation = useMutation({
    mutationFn: async (process: boolean) => {
      if (!file || !mediaTypeForUpload(file.name)) throw new Error("请选择 UTF-8 编码的 .txt 或 .md 文件。");
      let documentId = target;
      if (target === "new") {
        if (!title.trim()) throw new Error("请填写资料名称。");
        if (fresh.current?.title === title.trim()) documentId = fresh.current.id;
        else { const created = await createDocument(auth, title.trim()); documentId = created.document_id; fresh.current = { title: title.trim(), id: documentId }; }
      }
      const revision = uploaded.current ?? await uploadRevision(auth, documentId, file, { language, sourceLabel: label });
      uploaded.current = revision;
      // If queueing fails, another click retries only queueing the saved
      // revision, not document creation or upload.
      const job = process ? await queueJob(auth, revision.revision_id, 8, selection) : null;
      return { revision, job };
    },
    onSuccess: async ({ revision, job }) => {
      await Promise.all([client.invalidateQueries({ queryKey: ["studio", "documents"] }), client.invalidateQueries({ queryKey: ["studio", "revisions"] }), client.invalidateQueries({ queryKey: ["studio", "jobs"] })]);
      if (job) navigate(`/studio/imports/${job.job_id}`);
      else { setNotice("资料已保存，可查看原文或开始处理。"); setParams({ document: revision.document_id }); setFile(null); setTitle(""); fresh.current = null; uploaded.current = null; if (fileInput.current) fileInput.current.value = ""; }
    },
  });
  const queue = useMutation({ mutationFn: (revisionId: string) => queueJob(auth, revisionId, 8, selection), onSuccess: (job) => navigate(`/studio/imports/${job.job_id}`) });
  const validFile = file && mediaTypeForUpload(file.name);
  const ready = Boolean(validFile && (target !== "new" || title.trim()) && !mutation.isPending);
  return <div className="studio-stack" data-view="studio-sources">
    <div className="studio-page-heading"><div><p className="studio-eyebrow">历史内容的来源</p><h1>史料管理</h1><p className="studio-muted">保存完整资料，按自然章节处理。原始版本保留，读者正文统一使用简体中文。</p></div><Button onClick={() => { const next = new URLSearchParams(params); if (uploading) next.delete("upload"); else next.set("upload", "1"); setParams(next); }}>{uploading ? "收起上传" : "＋ 上传资料"}</Button></div>
    {notice ? <p className="studio-success" role="status">{notice}</p> : null}
    {uploading || documents.data?.length === 0 ? <section className="studio-panel studio-upload-panel"><div className="studio-section-heading"><h2>上传完整史料</h2><span className="studio-muted">支持 .txt / .md · UTF-8</span></div>
      <form onSubmit={(event) => { event.preventDefault(); if (ready && modelReady) mutation.mutate(true); }}>
        <fieldset disabled={mutation.isPending} className="studio-upload-fields">
          <label className={`studio-dropzone ${file ? "has-file" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (mutation.isPending) return; const next = event.dataTransfer.files[0]; if (next) { setFile(next); if (!title) setTitle(next.name.replace(/\.(txt|md)$/i, "")); formChange(); } }}>
            <span aria-hidden="true">↥</span><strong>{file?.name ?? "选择文件，或拖到这里"}</strong><small>{file ? `${(file.size / 1024).toFixed(1)} KB · 点击可重新选择` : "使用完整章节或带章节结构的资料"}</small>
            <input ref={fileInput} type="file" accept=".txt,.md,text/plain,text/markdown" aria-label="选择史料文件" onChange={(event) => { const next = event.target.files?.[0] ?? null; setFile(next); if (next && !title) setTitle(next.name.replace(/\.(txt|md)$/i, "")); formChange(); }} />
          </label>
          {file && !validFile ? <p role="alert" className="studio-error">目前支持 .txt 和 .md，请选择对应文件。</p> : null}
          <div className="studio-form"><label>保存到<select className="studio-select" value={target} onChange={(event) => { setTarget(event.target.value); formChange(); }}><option value="new">新建一份资料</option>{documents.data?.map((document) => <option key={document.document_id} value={document.document_id}>{document.title} · 新增版本</option>)}</select></label>
            {target === "new" ? <label>资料名称<Input value={title} onChange={(event) => { setTitle(event.target.value); formChange(); }} placeholder="例如：三国志·蜀书·先主传" aria-label="资料名称" /></label> : null}
            <div className="studio-grid studio-grid-compact"><label>原文语言<select className="studio-select" value={language} onChange={(event) => { setLanguage(event.target.value); formChange(); }}><option value="zh-Hant">繁体中文 / 古文</option><option value="zh-CN">简体中文</option><option value="en">英文</option></select></label><label>版本或来源备注<Input value={label} onChange={(event) => { setLabel(event.target.value); formChange(); }} placeholder="可选：出版社、整理者、来源" /></label></div>
            <ModelSelector value={selection} onChange={setSelection} onReady={setModelReady} disabled={mutation.isPending} />
            {mutation.error ? <p role="alert" className="studio-error">{uploaded.current ? "资料已保存，启动处理失败。再次提交将使用已保存版本。" : "上传未完成。"}{mutation.error.message}</p> : null}
            <div className="studio-row-actions"><Button type="submit" disabled={!ready || !modelReady}>{mutation.isPending ? "正在保存…" : "上传并开始处理"}</Button><Button variant="outline" disabled={!ready} onClick={() => mutation.mutate(false)}>只保存资料</Button></div>
          </div>
        </fieldset>
      </form>
    </section> : null}
    <div className="studio-source-workspace">
      <aside className="studio-panel studio-source-list"><div className="studio-section-heading"><h2>已收录资料</h2><span className="studio-muted">{documents.data?.length ?? "—"}</span></div><Input aria-label="搜索史料" placeholder="搜索资料名称" value={search} onChange={(event) => setSearch(event.target.value)} />
        {documents.error ? <p className="studio-error">资料列表读取失败。</p> : null}
        {documents.data?.filter((document) => document.title.includes(search.trim())).map((document) => <button type="button" className="studio-source-item" key={document.document_id} aria-pressed={id === document.document_id} onClick={() => setParams({ document: document.document_id })}><span className="studio-task-glyph" aria-hidden="true">文</span><span><strong>{document.title}</strong><small>{document.revision_count} 个保存版本</small></span></button>)}
      </aside>
      <section className="studio-panel"><div className="studio-section-heading"><div><h2>{selected?.title ?? "资料版本"}</h2><p className="studio-muted">每次上传保留为独立版本，原文与处理结果可以追溯。</p></div>{selected ? <Button variant="outline" size="sm" onClick={() => { setTarget(selected.document_id); formChange(); setParams({ document: selected.document_id, upload: "1" }); }}>上传新版本</Button> : null}</div>
        {revisions.isFetching ? <p className="studio-muted">正在读取版本…</p> : null}
        {revisions.error ? <p className="studio-error">版本读取失败：{revisions.error.message}</p> : null}
        {revisions.data?.length === 0 ? <p className="studio-muted">此资料还没有上传原文。</p> : null}
        {revisions.data?.slice().reverse().map((revision) => <article className="studio-revision" key={revision.revision_id}><div className="studio-section-heading"><div><strong>第 {revision.revision_no} 版</strong>{revision.status === "active" ? <span className="studio-status" data-status="completed">当前版本</span> : null}<p className="studio-muted">{revision.filename} · {revision.content_chars.toLocaleString()} 字 · {formatStudioTime(revision.created_at)}</p>{revision.source_label ? <p className="studio-muted">{revision.source_label}</p> : null}</div><Button variant="outline" size="sm" disabled={queue.isPending || revision.storage_status !== "present"} onClick={() => { setPendingRevision(revision); queue.reset(); }}>配置并处理</Button></div>
          <OriginalSource key={revision.revision_id} revision={revision} /><details className="studio-details"><summary>版本技术信息</summary><dl className="studio-facts"><div><dt>版本编号</dt><dd className="studio-mono">{revision.revision_id}</dd></div><div><dt>原文校验值</dt><dd className="studio-mono">{revision.source_sha256}</dd></div></dl></details>
          {pendingRevision?.revision_id === revision.revision_id ? <div className="studio-stack" aria-label="处理此资料版本">
            <ModelSelector value={selection} onChange={setSelection} onReady={setModelReady} disabled={queue.isPending} />
            <div className="studio-row-actions"><Button disabled={!modelReady || queue.isPending} onClick={() => queue.mutate(revision.revision_id)}>{queue.isPending ? "正在创建…" : "创建生产任务"}</Button><Button variant="outline" disabled={queue.isPending} onClick={() => setPendingRevision(null)}>收起</Button></div>
            {queue.error ? <p role="alert" className="studio-error">启动处理失败：{queue.error.message}</p> : null}
          </div> : null}
        </article>)}
        {selected ? <Link className="studio-back-link" to="/studio/imports">前往生产任务查看进度 →</Link> : null}
      </section>
    </div>
  </div>;
}
