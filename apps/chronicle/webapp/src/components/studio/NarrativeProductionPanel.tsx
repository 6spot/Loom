import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useStudioAuth } from "../../lib/studio-auth";
import { listNarrativeSources, queueNarrative } from "../../lib/studio-api";
import { Button } from "../ui/button";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "../ui/card";

export default function NarrativeProductionPanel() {
  const auth = useStudioAuth().authHeader();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const [scope, setScope] = useState<{ catalog: string; ids: string[] } | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const sources = useQuery({ queryKey: ["studio", "narrative-sources", offset], queryFn: () => listNarrativeSources(auth, offset), staleTime: 30_000 });
  const data = sources.data;
  const stale = scope && data && scope.catalog !== data.catalog_sha;
  const ids = scope?.ids ?? [];
  const toggle = (id: string) => {
    if (!data?.catalog_sha) return;
    const before = scope?.catalog === data.catalog_sha ? ids : [];
    setScope({ catalog: data.catalog_sha, ids: before.includes(id) ? before.filter((v) => v !== id) : [...before, id] });
  };
  const start = async () => {
    if (!scope || stale || pending) return;
    setPending(true); setError("");
    try { const job = await queueNarrative(auth, scope.catalog, scope.ids); navigate(`/studio/imports/${job.job_id}`); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setPending(false); }
  };
  return <Card data-test="narrative-production"><CardHeader><CardTitle>生成综合历史正文</CardTitle><CardDescription>选择本次叙述范围的完整章节。系统先提交事实核对稿，再生成正文；两次审核通过后才发布到前台。新版本以本次选择为范围，旧版本保留。</CardDescription></CardHeader>
    <CardContent className="studio-stack">
      {sources.isPending ? <p>正在读取已发布章节…</p> : null}
      {sources.isError ? <p role="alert">章节目录读取失败。<Button variant="outline" onClick={() => void sources.refetch()}>重试</Button></p> : null}
      {data?.items.length === 0 ? <p className="studio-muted">还没有完成发布的来源章节，请先导入资料并完成身份审核。</p> : null}
      {stale ? <p role="alert">资料目录有新版本，请重新选择本次来源。<Button variant="outline" onClick={() => setScope(null)}>重新选择</Button></p> : null}
      <div className="studio-stack">{data?.items.map((source) => <label key={source.publication_id} className="studio-list-row" style={{ display: "flex", alignItems: "center", justifyContent: "flex-start", gap: "1rem" }}>
        <input type="checkbox" checked={!stale && ids.includes(source.publication_id)} disabled={pending || (!ids.includes(source.publication_id) && ids.length >= 16)} onChange={() => toggle(source.publication_id)} />
        <span><strong>{source.document_title}</strong><small>{source.title} · 第 {source.revision_no} 版</small></span>
      </label>)}</div>
      <div className="studio-row-actions"><Button size="sm" variant="outline" disabled={offset === 0 || pending} onClick={() => setOffset((value) => Math.max(0, value - 50))}>上一页</Button><Button size="sm" variant="outline" disabled={!data?.has_more || pending} onClick={() => setOffset((value) => value + 50)}>下一页</Button><Button variant="outline" onClick={() => { setScope(null); setOffset(0); void sources.refetch(); }}>刷新来源</Button></div>
      <p className="studio-muted">已选 {stale ? 0 : ids.length} / 16 个完整章节。不能用截取的几句话代替整章；输入过大时会明确提示调整范围。</p>
      {error ? <p role="alert" className="studio-error">{error}</p> : null}
      <Button disabled={pending || !!stale || ids.length === 0} onClick={() => void start()}>{pending ? "正在创建生产任务…" : "开始核对并生成"}</Button>
    </CardContent></Card>;
}
