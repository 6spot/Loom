import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Button } from "../ui/button";
import { ReviewEvidencePanel } from "./ReviewEvidencePanel";
import { useStudioAuth } from "../../lib/studio-auth";
import { getChapterReviewHistory, getReview, mutateJob, submitChapterContentDecision, type ReviewDetail } from "../../lib/studio-api";
import { buildContentDecision, contentDraftKey, contentPatches, pointerValue, type ChapterContentReviewData, type ContentDraft, type IssueDisposition } from "../../lib/chapter-content-review";
import { decisionLabel } from "../../lib/review-display";
import "../../styles/chapter-content-review.css";

const STEP_LABELS: Record<string, string> = {
  translation: "整章译文", extraction: "信息提取", comparison: "候选比较", linking: "来源与时间关联",
  review: "内容复核", repair: "局部修正", human_repair: "人工修订", human_revision: "人工修订",
};
const STATUS_LABELS: Record<string, string> = {
  started: "调用开始记录", completed: "已完成", failed: "执行失败", invalid: "校验未通过", draft: "候选草稿",
};
const message = (error: unknown) => error instanceof Error ? error.message : String(error);
const pretty = (value: unknown) => typeof value === "string" ? value : JSON.stringify(value, null, 2);

function initialDraft(key: string, data: ChapterContentReviewData): ContentDraft {
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) ?? "null") as ContentDraft | null;
    if (saved && typeof saved.rationale === "string" && saved.dispositions && typeof saved.dispositions === "object" && saved.edits && typeof saved.edits === "object") return {
      rationale: saved.rationale,
      dispositions: Object.fromEntries(Object.entries(saved.dispositions).filter(([id, value]) =>
        data.issues.some((issue) => issue.id === id) && value && typeof value.rationale === "string" && ["", "resolved", "rejected", "source_uncertainty"].includes(value.disposition))),
      edits: Object.fromEntries(Object.entries(saved.edits).filter(([path, value]) => typeof value === "string" && data.patch_targets.some((target) => target.path === path))),
    };
  } catch { /* A storage failure never discards the live form. */ }
  return {
    rationale: data.decision?.rationale ?? "",
    dispositions: Object.fromEntries((data.decision?.issue_dispositions ?? []).map((entry) => [entry.issue_id, { disposition: entry.disposition, rationale: entry.rationale }])),
    edits: {},
  };
}

function HistoryRecord({ auth, reviewId, fingerprint, record }: {
  auth: string | null; reviewId: string; fingerprint: string; record: ChapterContentReviewData["history"][number];
}) {
  const [text, setText] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const current = useRef(true);
  useEffect(() => { current.current = true; return () => { current.current = false; }; }, []);
  const load = async () => {
    if (busy || (loaded && !cursor)) return;
    setBusy(true); setError("");
    try {
      const page = await getChapterReviewHistory(auth, reviewId, record.index, cursor);
      if (page.review_id !== reviewId || page.plan_fingerprint !== fingerprint || page.entry !== record.index || page.entry_sha256 !== record.entry_sha256) throw new Error("历史记录的版本不一致，请刷新当前审核项。");
      if (!current.current) return;
      setText((value) => value + page.text); setCursor(page.next_cursor); setLoaded(true);
    } catch (failure) { if (current.current) setError(message(failure)); }
    finally { if (current.current) setBusy(false); }
  };
  return <details className="ccr-history-record" onToggle={(event) => { if (event.currentTarget.open && !loaded) void load(); }}>
    <summary>{record.index + 1}. {STEP_LABELS[record.step ?? ""] ?? record.step ?? "处理记录"} · {record.model ?? "程序记录"}{record.status ? ` · ${STATUS_LABELS[record.status] ?? record.status}` : ""}</summary>
    <p className="studio-muted">完整保存的原始结果、解析结果与相关意见。长记录可继续加载。</p>
    <pre className="studio-code ccr-history-text">{text}</pre>
    {error ? <p role="alert" className="studio-error">{error}</p> : null}
    {!loaded || cursor || error ? <Button variant="outline" disabled={busy} onClick={() => void load()}>{busy ? "正在读取…" : loaded ? "继续读取此记录" : "读取此记录"}</Button> : <p className="studio-muted">此记录已完整显示。</p>}
  </details>;
}

export default function ChapterContentReviewPanel({ item, queueScope, onNext, onSkip, onReturn, navigationNote }: {
  item: ReviewDetail; queueScope: string; onNext: () => Promise<void>; onSkip: () => Promise<void>;
  onReturn: () => void; navigationNote: string;
}) {
  const data = item.chapter_content!;
  const auth = useStudioAuth().authHeader();
  const client = useQueryClient();
  const key = contentDraftKey(queueScope, item.review_id, data);
  const [draft, setDraft] = useState<ContentDraft>(() => initialDraft(key, data));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [storageFailed, setStorageFailed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [metadataPath, setMetadataPath] = useState("");
  const current = useRef(true);
  const committed = useRef(false);
  const submitting = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { current.current = true; return () => { current.current = false; }; }, []);
  useEffect(() => { heading.current?.scrollIntoView?.({ block: "start" }); }, [item.review_id]);
  useEffect(() => {
    if (item.status !== "open" || committed.current) return;
    try { sessionStorage.setItem(key, JSON.stringify(draft)); }
    catch { setStorageFailed(true); }
  }, [key, draft, item.status]);

  const prose = data.patch_targets.filter((entry) => /^\/translation\/blocks\/\d+\/text$/.test(entry.path));
  const metadata = data.patch_targets.filter((entry) => !/^\/translation\/blocks\/\d+\/text$/.test(entry.path));
  let changed = 0;
  let patchError = "";
  try { changed = contentPatches(data, draft.edits).length; }
  catch (failure) { patchError = message(failure); }
  const covered = data.issues.every((issue) => draft.dispositions[issue.id]?.disposition && draft.dispositions[issue.id]?.rationale.trim());
  const ready = covered && Boolean(draft.rationale.trim()) && !pending && item.status === "open" && ["running", "needs_review"].includes(item.job_status);
  const setEdit = (path: string, value: string) => setDraft((valueNow) => ({ ...valueNow, edits: { ...valueNow.edits, [path]: value } }));
  const setIssue = (id: string, value: Partial<ContentDraft["dispositions"][string]>) => setDraft((valueNow) => ({
    ...valueNow, dispositions: { ...valueNow.dispositions, [id]: { ...(valueNow.dispositions[id] ?? { disposition: "", rationale: "" }), ...value } },
  }));

  const resume = async () => {
    try {
      await mutateJob(auth, item.job_id, "resume");
      await client.invalidateQueries({ queryKey: ["studio", "jobs"] });
      if (current.current) setNotice("审核已保存，后台将从已完成的步骤继续处理。");
      return true;
    } catch (failure) {
      if (current.current) setNotice(`审核已保存，继续生产失败：${message(failure)}。可在下方重试。`);
      return false;
    }
  };

  const submit = async (decision: "accept" | "revise" | "reject") => {
    if (pending || submitting.current) return;
    submitting.current = true;
    setPending(true); setError("");
    try {
      const submitted = buildContentDecision(data, draft, decision);
      const updated = await submitChapterContentDecision(auth, item.review_id, submitted);
      const result = updated.chapter_content;
      if (updated.review_id !== item.review_id || result?.plan_fingerprint !== data.plan_fingerprint || result.candidate_sha256 !== data.candidate_sha256 || result.history_sha256 !== data.history_sha256 || result.decision?.decision !== decision || updated.status !== "resolved") throw new Error("服务器返回的审核版本不一致，草稿保留，请核对服务器记录。");
      committed.current = true;
      try { sessionStorage.removeItem(key); } catch { /* The server is authoritative. */ }
      client.setQueryData(["studio", "review", item.review_id], updated);
      await client.invalidateQueries({ queryKey: ["studio", "reviews"] });
      if (!current.current) return;
      setNotice(decision === "revise" ? "修订已保存，后台将生成新版本并重新复核。" : decision === "reject" ? "已驳回，本次生产任务已取消。" : "当前版本已接受。");
      if (decision !== "reject" && updated.job_status === "needs_review" && updated.job_open_resolution_reviews === 0 && !(await resume())) return;
      if (current.current) await onNext();
    } catch (failure) {
      if (current.current) setError(committed.current ? `审核决定已保存，进入下一项失败：${message(failure)}。可以重试下一项。` : `${message(failure)}。草稿保留；提交结果不确定时先核对服务器记录。`);
    } finally { submitting.current = false; if (current.current) setPending(false); }
  };

  const verify = async () => {
    if (pending) return;
    setPending(true);
    try {
      const updated = await getReview(auth, item.review_id);
      if (updated.review_id !== item.review_id || updated.chapter_content?.plan_fingerprint !== data.plan_fingerprint) throw new Error("服务器记录的版本已改变，保留草稿供核对。");
      client.setQueryData(["studio", "review", item.review_id], updated);
      if (updated.status === "resolved") {
        committed.current = true;
        try { sessionStorage.removeItem(key); } catch { /* nonfatal */ }
      }
      if (current.current) setNotice(updated.status === "open" ? "服务端仍待审核，草稿已保留。" : "服务端已有固定决定，可查看记录并继续下一项。");
    } catch (failure) { if (current.current) setError(message(failure)); }
    finally { if (current.current) setPending(false); }
  };

  return <div className="studio-stack chapter-content-review" data-view="chapter-content-review">
    <div className="studio-page-heading">
      <div><p className="studio-eyebrow">章节内容审核</p><h1 ref={heading}>{item.document.title}</h1><p className="studio-muted">第 {item.document.revision_no} 版 · {data.issues.length} 条待核对意见 · {data.history_count} 份处理记录</p></div>
      <Link to={`/studio/imports/${item.job_id}`}>查看生产进度</Link>
    </div>
    {notice ? <p role="status">{notice}</p> : null}
    {navigationNote ? <p role="status">{navigationNote}</p> : null}
    {storageFailed ? <p role="status">浏览器无法保存草稿，请保持本页打开；当前编辑仍保留。</p> : null}
    {error ? <div className="studio-error-box" role="alert"><p>{error}</p><Button variant="outline" disabled={pending} onClick={() => void verify()}>核对服务器记录</Button></div> : null}
    {item.status !== "open" ? <section className="ccr-section"><strong>{item.status === "dismissed" ? "本次任务已取消，审核材料保留供查阅。" : `已记录：${decisionLabel(data.decision?.decision)}`}</strong><p>{data.decision?.rationale}</p>{data.decision ? <details><summary>查看固定审核决定</summary><pre className="studio-code">{pretty(data.decision)}</pre></details> : null}</section> : null}
    {!data.can_accept ? <section className="studio-error-box"><strong>当前候选尚不能接受</strong><ul>{data.validation_errors.map((entry, index) => <li key={index}>{entry}</li>)}</ul>{!data.candidate ? <p>尚未形成完整章节候选。可以核对已保存的全部结果，并驳回本次处理。</p> : <p>请修订具体问题后重新复核，或驳回本次处理。</p>}</section> : null}

    <section className="ccr-section" aria-label="原文与当前译文">
      <div className="ccr-section-heading"><h2>原文与当前译文</h2>{item.status === "open" && data.candidate ? <Button variant="outline" disabled={pending} onClick={() => setEditing((value) => !value)}>{editing ? "收起修订编辑" : "修订具体内容"}</Button> : null}</div>
      <p className="studio-muted">原文包含完整上下文与原注。修改后会生成新版本重新复核。</p>
      <div className="ccr-reading-grid">
        <ReviewEvidencePanel auth={auth} reviewId={item.review_id} planFingerprint={data.plan_fingerprint} descriptor={data.source} defaultExpanded />
        <div className="ccr-prose">{prose.map((target, index) => <div key={target.path}>
          {editing && item.status === "open" ? <label><span className="studio-muted">第 {index + 1} 段</span><textarea className="studio-textarea" aria-label={`修订第 ${index + 1} 段译文`} value={draft.edits[target.path] ?? String(pointerValue(data.candidate, target.path) ?? "")} disabled={pending} onChange={(event) => setEdit(target.path, event.target.value)} /></label> : <p>{String(pointerValue(data.candidate, target.path) ?? "")}</p>}
        </div>)}{!prose.length ? <p>当前没有完整白话正文，请查看下面保存的候选记录。</p> : null}</div>
      </div>
      <details><summary>当前提取信息与正文范围</summary><pre className="studio-code">{pretty({ candidate: data.candidate, source_scope: data.source_scope })}</pre></details>
      {editing && item.status === "open" && metadata.length ? <details className="ccr-metadata"><summary>修订提取信息</summary>
        <p className="studio-muted">选择具体记录后修改其内容；保留记录格式和引用。来源范围由程序固定。</p>
        <label>具体记录<select className="studio-select" value={metadataPath} onChange={(event) => setMetadataPath(event.target.value)}><option value="">选择需要修订的记录</option>{metadata.map((target) => <option key={target.path} value={target.path}>{target.label}</option>)}</select></label>
        {metadataPath ? <textarea className="studio-textarea ccr-record-editor" aria-label="修订提取记录" disabled={pending} value={draft.edits[metadataPath] ?? JSON.stringify(pointerValue(data.candidate, metadataPath), null, 2)} onChange={(event) => setEdit(metadataPath, event.target.value)} /> : null}
      </details> : null}
      {patchError ? <p className="studio-error" role="alert">修订记录格式错误：{patchError}</p> : changed ? <p role="status">已修改 {changed} 项。请使用“提交修订并下一项”，新版本仍需复核。</p> : null}
    </section>

    <section className="ccr-section" aria-label="逐项核对模型意见">
      <h2>逐项核对意见</h2>
      <p className="studio-muted">处理错误与史料自身的不确定分别记录。每条意见都需要明确处置和依据。</p>
      {data.issues.length === 0 ? <p>没有单列意见，请核对当前版本和完整处理记录。</p> : null}
      {data.issues.map((issue, index) => <fieldset className="ccr-issue" key={issue.id} disabled={pending || item.status !== "open"}>
        <legend>{index + 1}. {issue.type === "processing_error" ? "处理问题" : "史料不确定"}</legend>
        <p>{issue.message}</p><details><summary>涉及内容与史料依据</summary><pre className="studio-code">{pretty({ target: issue.target, evidence: issue.evidence })}</pre></details>
        <label>处置<select className="studio-select" aria-label={`第 ${index + 1} 条意见处置`} value={draft.dispositions[issue.id]?.disposition ?? ""} onChange={(event) => setIssue(issue.id, { disposition: event.target.value as IssueDisposition["disposition"] | "" })}>
          <option value="">请选择</option><option value="resolved">已核对并处理</option><option value="rejected">此项疑义不成立</option>{issue.type === "source_uncertainty" ? <option value="source_uncertainty">保留史料本身的不确定</option> : null}
        </select></label>
        <label>处置依据<textarea className="studio-textarea" aria-label={`第 ${index + 1} 条意见依据`} value={draft.dispositions[issue.id]?.rationale ?? ""} onChange={(event) => setIssue(issue.id, { rationale: event.target.value })} /></label>
      </fieldset>)}
    </section>

    <section className="ccr-section" aria-label="完整模型候选与意见历史"><h2>全部候选与复核历史</h2><p className="studio-muted">保留每个模型的原始结果、采用版本、修正过程及历次意见，按保存顺序展示。</p>
      {data.history.map((record) => <HistoryRecord key={`${data.plan_fingerprint}:${record.index}:${record.entry_sha256}`} auth={auth} reviewId={item.review_id} fingerprint={data.plan_fingerprint} record={record} />)}
    </section>
    {item.status === "open" ? <label className="ccr-section">本次处理依据<textarea className="studio-textarea" aria-label="本次处理依据" value={draft.rationale} disabled={pending} onChange={(event) => setDraft((value) => ({ ...value, rationale: event.target.value }))} /></label> : null}
    <footer className="studio-review-actionbar ccr-actions">
      <span>{pending ? "正在保存…" : item.status === "open" ? `已处理 ${data.issues.filter((issue) => draft.dispositions[issue.id]?.disposition && draft.dispositions[issue.id]?.rationale.trim()).length} / ${data.issues.length} 条意见` : "决定已固定保存"}</span>
      <div className="studio-review-actionbar-buttons">
        <Button variant="outline" disabled={pending} onClick={onReturn}>返回队列</Button>
        <Button variant="outline" disabled={pending} onClick={() => void onSkip()}>暂时跳过</Button>
        {item.status === "open" ? <>
          <Button variant="outline" disabled={!ready} onClick={() => void submit("reject")}>驳回</Button>
          {data.candidate ? <Button variant="outline" disabled={!ready || Boolean(patchError) || changed === 0} onClick={() => void submit("revise")}>提交修订并下一项</Button> : null}
          <Button disabled={!ready || !data.can_accept || Boolean(patchError) || changed > 0} onClick={() => void submit("accept")}>接受原样并下一项</Button>
        </> : <><Button disabled={pending} onClick={() => void onNext()}>下一项</Button>{data.decision?.decision !== "reject" && item.job_status === "needs_review" && item.job_open_resolution_reviews === 0 ? <Button disabled={pending} onClick={() => void resume()}>继续生产</Button> : null}</>}
      </div>
    </footer>
  </div>;
}
