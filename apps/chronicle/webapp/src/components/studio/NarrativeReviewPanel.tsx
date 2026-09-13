import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "../ui/button";
import NarrativeNavigationEditor from "./NarrativeNavigationEditor";
import { getReview, mutateJob, submitNarrativeDecision, type ReviewDetail } from "../../lib/studio-api";
import { useStudioAuth } from "../../lib/studio-auth";
import type { NarrativeContent, NarrativeContext, NarrativeEvidenceRef, NarrativeFact, NarrativeFacts, NarrativePhase, NarrativeProse, NarrativeReviewData } from "../../lib/narrative-types";
import "../../styles/narrative-review.css";

const RELATIONS: Record<NarrativeEvidenceRef["relation"], string> = { support: "支持", supplement: "补充", contradict: "不同说法", background: "背景", incomparable: "暂不可比较" };
const SOURCE_RELATIONS: Record<string, string> = { same_work: "同一著作", quotes: "转引", dependent: "传承依赖", independent: "独立来源", unknown: "关系未明" };
const DIMENSIONS: Record<NarrativeFact["dimension"], string> = { event_detail: "事件情况", office: "官职", title: "爵号", allegiance: "效力", administration: "行政归属", control: "实际控制" };
const message = (e: unknown) => e instanceof Error ? e.message : String(e);
function copy<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T; }
const localId = (prefix: string) => `${prefix}_${crypto.randomUUID().replace(/-/g, "").slice(0, 20)}`;

function Evidence({ reference, context }: { reference: NarrativeEvidenceRef; context: NarrativeContext }) {
  const [expanded, setExpanded] = useState(false);
  const fullSource = useRef<HTMLDivElement>(null);
  const quote = useRef<HTMLElement>(null);
  useEffect(() => {
    const box = fullSource.current;
    if (expanded && box && quote.current) {
      box.scrollTop += quote.current.getBoundingClientRect().top - box.getBoundingClientRect().top - box.clientHeight / 3;
    }
  }, [expanded, reference.id]);
  const source = context.sources.find((s) => s.evidence.some((e) => e.id === reference.id));
  const anchor = source?.evidence.find((e) => e.id === reference.id);
  if (!source || !anchor) return <p role="alert">这条依据不在固定来源中。</p>;
  const chars = expanded ? Array.from(source.chapter_text) : [];
  return <div className="nr-evidence">
    <p className="studio-muted">{source.document_title} · {source.title} · {RELATIONS[reference.relation]}</p>
    <blockquote>{anchor.quote}</blockquote>
    <p>{reference.attribution}：{reference.note}</p>
    <Button type="button" variant="outline" size="sm" onClick={() => setExpanded((v) => !v)}>{expanded ? "收起完整章节" : "查看完整章节与引用位置"}</Button>
    {expanded ? <div ref={fullSource} className="nr-full-source" tabIndex={0}>{chars.slice(0, anchor.start).join("")}<mark ref={quote}>{chars.slice(anchor.start, anchor.end).join("")}</mark>{chars.slice(anchor.end).join("")}</div> : null}
  </div>;
}

function EvidencePicker({ context, selected, label, add }: { context: NarrativeContext; selected: string[]; label: string; add: (id: string) => void }) {
  return <label>{label}<select value="" onChange={(e) => { if (e.target.value) add(e.target.value); }}><option value="">从固定的完整章中选择…</option>{context.sources.map((source) => <optgroup label={`${source.document_title} · ${source.title}`} key={source.source_id}>{source.evidence.filter((e) => !selected.includes(e.id)).map((e) => <option key={e.id} value={e.id}>{e.quote.slice(0, 100)}</option>)}</optgroup>)}</select></label>;
}

function PhaseEditor({ phase, context, update }: { phase: NarrativePhase; context: NarrativeContext; update: (phase: NarrativePhase) => void }) {
  const patch = (value: Partial<NarrativePhase>) => update({ ...phase, ...value });
  return <div className="nr-field-grid">
    <label>阶段名称<input value={phase.label} onChange={(e) => patch({ label: e.target.value })} /></label>
    <label>确切公元年（不明留空）<input type="number" value={phase.year ?? ""} onChange={(e) => patch({ year: e.target.value ? Number(e.target.value) : null })} /></label>
    <label>月份或时段原述<input value={phase.period ?? ""} onChange={(e) => patch({ period: e.target.value || null })} /></label>
    <label>与上一阶段关系<select value={phase.relation_to_previous} onChange={(e) => patch({ relation_to_previous: e.target.value as NarrativePhase["relation_to_previous"] })}><option value="after">在其后</option><option value="contemporary">同时期</option><option value="uncertain">先后未明</option></select></label>
    <details><summary>编辑阶段的原文依据（{phase.basis.length} 条）</summary>{phase.basis.map((id) => <section key={id}><Evidence context={context} reference={{ id, relation: "support", attribution: "阶段依据", note: "请核对时间是否得到原文支持。" }} /><Button type="button" variant="outline" size="sm" onClick={() => patch({ basis: phase.basis.filter((v) => v !== id) })}>移除阶段依据</Button></section>)}
      <EvidencePicker context={context} selected={phase.basis} label="添加阶段依据" add={(id) => patch({ basis: [...phase.basis, id] })} />
    </details>
  </div>;
}

function FactEditor({ fact, context, facts, update }: { fact: NarrativeFact; context: NarrativeContext; facts: NarrativeFacts; update: (fact: NarrativeFact) => void }) {
  const patch = (value: Partial<NarrativeFact>) => update({ ...fact, ...value });
  return <div className="studio-stack">
    <label>核对问题<input value={fact.question} onChange={(e) => patch({ question: e.target.value })} /></label>
    <div className="nr-field-grid">
      <label>主体<select value={fact.subject_id ?? ""} onChange={(e) => patch({ subject_id: e.target.value || null })}><option value="">未指定主体</option>{Object.entries(context.entities).map(([id, entity]) => <option value={id} key={id}>{entity.name}（{entity.kind} · {id.slice(-6)}）</option>)}</select></label>
      <label>结论类型<select value={fact.dimension} onChange={(e) => patch({ dimension: e.target.value as NarrativeFact["dimension"], value: e.target.value === "event_detail" ? null : fact.value ?? "" })}>{Object.entries(DIMENSIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>相关事件<select value={fact.event_id ?? ""} onChange={(e) => patch({ event_id: e.target.value || null })}><option value="">没有指定事件</option>{Object.entries(context.events).map(([id, event]) => <option value={id} key={id}>{event.name}</option>)}</select></label>
      <label>明确性<select value={fact.certainty} onChange={(e) => patch({ certainty: e.target.value as NarrativeFact["certainty"] })}><option value="clear">● 明确记载</option><option value="uncertain">○ 存疑</option></select></label>
    </div>
    {fact.dimension !== "event_detail" ? <label>此阶段显示的状态<input value={fact.value ?? ""} onChange={(e) => patch({ value: e.target.value })} placeholder="如：偏将军；兼任职务分别记录" /></label> : null}
    <fieldset><legend>仅适用于以下阶段</legend><div className="nr-checks">{facts.phases.map((phase) => <label key={phase.id}><input type="checkbox" checked={fact.phase_ids.includes(phase.id)} onChange={(e) => patch({ phase_ids: e.target.checked ? [...fact.phase_ids, phase.id] : fact.phase_ids.filter((id) => id !== phase.id) })} />{phase.label}</label>)}</div></fieldset>
    <label>核对后的表述<textarea rows={3} value={fact.text} onChange={(e) => patch({ text: e.target.value })} /></label>
    <label>明确或存疑的理由<textarea rows={2} value={fact.reason} onChange={(e) => patch({ reason: e.target.value })} /></label>
    <div className="studio-stack"><strong>各份依据与归属</strong>{fact.evidence.map((reference, index) => <section className="nr-evidence-editor" key={reference.id}>
      <Evidence reference={reference} context={context} />
      <div className="nr-field-grid"><label>这条材料与结论的关系<select value={reference.relation} onChange={(e) => patch({ evidence: fact.evidence.map((r, n) => n === index ? { ...r, relation: e.target.value as NarrativeEvidenceRef["relation"] } : r) })}>{Object.entries(RELATIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>原作者、注者或说话人<input value={reference.attribution} onChange={(e) => patch({ evidence: fact.evidence.map((r, n) => n === index ? { ...r, attribution: e.target.value } : r) })} /></label></div>
      <label>支持范围或分歧说明<textarea rows={2} value={reference.note} onChange={(e) => patch({ evidence: fact.evidence.map((r, n) => n === index ? { ...r, note: e.target.value } : r) })} /></label>
      <Button type="button" size="sm" variant="outline" onClick={() => patch({ evidence: fact.evidence.filter((_, n) => n !== index) })}>移除此条依据</Button>
    </section>)}</div>
    <EvidencePicker context={context} selected={fact.evidence.map((r) => r.id)} label="补充引用" add={(id) => patch({ evidence: [...fact.evidence, { id, relation: "support", attribution: "", note: "" }] })} />
  </div>;
}

function ProseEditor({ content, data, update }: { content: NarrativeProse; data: NarrativeReviewData; update: (content: NarrativeProse) => void }) {
  const facts = data.facts!;
  const paragraphLabel = (id: string) => { const p = content.paragraphs.find((p) => p.id === id); return p?.segments.map((s) => s.text).join("").slice(0, 70) ?? id; };
  const patchParagraph = (index: number, value: Partial<NarrativeProse["paragraphs"][number]>) => update({ ...content, paragraphs: content.paragraphs.map((p, i) => i === index ? { ...p, ...value } : p) });
  return <div className="studio-stack">
    <p className="studio-muted">逐段通读综合正文，检查叙述是否超出已核对结论。修改文字后仍会重新校验引用与阶段。</p>
    {content.paragraphs.map((paragraph, index) => <section className="nr-prose" key={paragraph.id}>
      <p className="studio-muted">{facts.phases.find((p) => p.id === paragraph.phase_id)?.label} · 第 {index + 1} 段</p>
      <details><summary>本段阶段与侧栏人物、地点</summary>
        <label>主叙述阶段<select value={paragraph.phase_id} onChange={(e) => patchParagraph(index, { phase_id: e.target.value })}>{facts.phases.map((phase) => <option key={phase.id} value={phase.id}>{phase.label}</option>)}</select></label>
        {paragraph.entities.map((entity) => <div className="nr-checks" key={entity.entity_id}><label>{data.context.entities[entity.entity_id]?.name}<select value={entity.importance} onChange={(e) => patchParagraph(index, { entities: paragraph.entities.map((v) => v.entity_id === entity.entity_id ? { ...v, importance: e.target.value as "primary" | "other" } : v) })}><option value="primary">主要，显示在侧栏</option><option value="other">其他，可按需查看</option></select></label><Button type="button" variant="outline" size="sm" onClick={() => patchParagraph(index, { entities: paragraph.entities.filter((v) => v.entity_id !== entity.entity_id) })}>移除本段关联</Button></div>)}
        {paragraph.entities.length < 32 ? <label>补充本段人物或地点<select value="" onChange={(e) => { if (e.target.value) patchParagraph(index, { entities: [...paragraph.entities, { entity_id: e.target.value, importance: "primary" }] }); }}><option value="">选择已确认主体…</option>{Object.entries(data.context.entities).filter(([id]) => !paragraph.entities.some((v) => v.entity_id === id)).map(([id, entity]) => <option key={id} value={id}>{entity.name}</option>)}</select></label> : null}
      </details>
      {paragraph.segments.map((segment, n) => <div key={n}>
        <textarea aria-label={`第 ${index + 1} 段文字 ${n + 1}`} rows={Math.max(2, Math.ceil(segment.text.length / 45))} value={segment.text} onChange={(e) => update({ ...content, paragraphs: content.paragraphs.map((p, i) => i !== index ? p : { ...p, segments: p.segments.map((s, j) => j === n ? { ...s, text: e.target.value } : s) }) })} />
        {segment.event_id ? <label>供读者触发预览的事件称呼（须在上文出现一次，可留空）<input value={segment.event_text ?? ""} onChange={(e) => update({ ...content, paragraphs: content.paragraphs.map((p, i) => i !== index ? p : { ...p, segments: p.segments.map((s, j) => j === n ? { ...s, event_text: e.target.value || null } : s) }) })} /></label> : null}
        <details><summary>核对这段文字的结论与原文</summary>{segment.conclusion_ids.map((id) => { const fact = facts.conclusions.find((f) => f.id === id); return fact ? <section key={id}><p><strong>{fact.question}</strong></p><p>{fact.text}</p><p>{fact.certainty === "clear" ? "● 明确" : "○ 存疑"} · {fact.reason}</p>{fact.evidence.map((ref) => <Evidence key={ref.id} reference={ref} context={data.context} />)}<Button type="button" variant="outline" size="sm" onClick={() => patchParagraph(index, { segments: paragraph.segments.map((s, j) => j === n ? { ...s, conclusion_ids: s.conclusion_ids.filter((v) => v !== id) } : s) })}>移除此结论引用</Button></section> : <p key={id}>未核对的结论，不可发布。</p>; })}
          <label>引用已审核结论<select value="" onChange={(e) => { if (e.target.value) patchParagraph(index, { segments: paragraph.segments.map((s, j) => j === n ? { ...s, conclusion_ids: [...s.conclusion_ids, e.target.value] } : s) }); }}><option value="">选择支持这段文字的结论…</option>{facts.conclusions.filter((f) => !segment.conclusion_ids.includes(f.id)).map((f) => <option key={f.id} value={f.id}>{f.question}</option>)}</select></label>
        </details>
      </div>)}
    </section>)}
    <section className="studio-stack nr-entries" data-test="narrative-entry-editor"><h2>首页与侧栏的阅读入口</h2><p className="studio-muted">挑选少量重要时期或大事件。官职、称号、领有某地等细节留在正文中，不能因抽取为事件就各占一个入口。</p>
      {content.entry_points.map((entry, index) => <div className="nr-entry" key={index}>
        <p className="studio-muted">{entry.kind === "period" ? "时期入口" : "事件入口"}</p>
        <label>入口名称<input value={entry.label} onChange={(e) => update({ ...content, entry_points: content.entry_points.map((v, i) => i === index ? { ...v, label: e.target.value } : v) })} /></label>
        <label>为何值得独立导航<textarea rows={2} value={entry.reason} onChange={(e) => update({ ...content, entry_points: content.entry_points.map((v, i) => i === index ? { ...v, reason: e.target.value } : v) })} /></label>
        <label>正文位置<select value={entry.paragraph_id} onChange={(e) => update({ ...content, entry_points: content.entry_points.map((v, i) => i === index ? { ...v, paragraph_id: e.target.value } : v) })}>{content.paragraphs.filter((p) => entry.kind === "period" || p.segments.some((s) => s.event_id === entry.event_id && s.event_relation === "current")).map((p) => <option value={p.id} key={p.id}>{paragraphLabel(p.id)}</option>)}</select></label>
        <Button type="button" variant="outline" size="sm" disabled={content.entry_points.length <= 1} onClick={() => update({ ...content, entry_points: content.entry_points.filter((_, i) => i !== index) })}>移除入口</Button>
      </div>)}
      {content.entry_points.length < 12 ? <label>添加经过选择的重要事件<select value="" onChange={(e) => {
        const [paragraphId, eventId] = e.target.value.split("|");
        if (paragraphId && eventId) update({ ...content, entry_points: [...content.entry_points, { kind: "event", paragraph_id: paragraphId, event_id: eventId, label: data.context.events[eventId].name, reason: "" }] });
      }}><option value="">选择正文中明确发生的重要事件…</option>{content.paragraphs.flatMap((p) => p.segments.filter((s, n, all) => s.event_id && s.event_relation === "current" && all.findIndex((v) => v.event_id === s.event_id && v.event_relation === "current") === n && !content.entry_points.some((e) => e.event_id === s.event_id)).map((s) => <option key={`${p.id}:${s.event_id}`} value={`${p.id}|${s.event_id}`}>{data.context.events[s.event_id!]?.name} · {paragraphLabel(p.id)}</option>))}</select></label> : null}
      {content.entry_points.length < 12 ? <label>添加重要时期入口<select value="" onChange={(e) => {
        if (e.target.value) update({ ...content, entry_points: [...content.entry_points, { kind: "period", paragraph_id: e.target.value, event_id: null, label: "", reason: "" }] });
      }}><option value="">选择这一时期的正文起点…</option>{content.paragraphs.filter((p) => !content.entry_points.some((entry) => entry.kind === "period" && entry.paragraph_id === p.id)).map((p) => <option key={p.id} value={p.id}>{paragraphLabel(p.id)}</option>)}</select></label> : null}
    </section>
    <NarrativeNavigationEditor content={content} update={update} />
  </div>;
}

export default function NarrativeReviewPanel({ item, onNext, onSkip, queueHref, navigationNote }: {
  item: ReviewDetail; onNext: () => Promise<void>; onSkip: () => Promise<void>; queueHref: string; navigationNote: string;
}) {
  const data = item.narrative!;
  const auth = useStudioAuth().authHeader();
  const client = useQueryClient();
  const key = `chronicle.narrative-draft.${item.review_id}.${data.candidate_sha}`;
  const saved = useRef<{ content: NarrativeContent; rationale: string; checked: string[]; scopeChecked: boolean } | null>(null);
  if (!saved.current) {
    try { const raw = sessionStorage.getItem(key); const parsed = raw ? JSON.parse(raw) : null;
      if (parsed?.content?.schema === data.candidate.schema && Array.isArray(parsed.checked)) saved.current = parsed;
    } catch { /* quota/storage failures leave the in-memory draft usable */ }
    saved.current ??= { content: copy(data.decision?.content ?? data.candidate), rationale: data.decision?.rationale ?? "", checked: data.decision?.reviewed_conclusion_ids ?? [], scopeChecked: false };
  }
  const [content, setContent] = useState<NarrativeContent>(saved.current.content);
  const [rationale, setRationale] = useState(saved.current.rationale);
  const [checked, setChecked] = useState<string[]>(saved.current.checked);
  const [scopeChecked, setScopeChecked] = useState(saved.current.scopeChecked);
  const [selected, setSelected] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [storageFailed, setStorageFailed] = useState(false);
  const current = useRef(true);
  useEffect(() => { current.current = true; return () => { current.current = false; }; }, []);
  useEffect(() => {
    if (item.status !== "open") return;
    try { sessionStorage.setItem(key, JSON.stringify({ content, rationale, checked, scopeChecked })); }
    catch { setStorageFailed(true); }
  }, [key, content, rationale, checked, scopeChecked, item.status]);
  const facts = content.schema === "chronicle.source-corroboration" ? content : null;
  const canApprove = scopeChecked && !!rationale.trim() && (!facts || facts.conclusions.every((f) => checked.includes(f.id)));
  const patchFacts = (value: NarrativeFacts, changed?: string) => { setContent(value); setChecked(changed ? checked.filter((id) => id !== changed) : []); if (!changed) setScopeChecked(false); };

  const resume = async () => {
    try {
      await mutateJob(auth, item.job_id, "resume");
      if (current.current) setNotice("已继续生产，新的待审内容会出现在同一队列。");
      await client.invalidateQueries({ queryKey: ["studio", "jobs"] });
      await client.invalidateQueries({ queryKey: ["studio", "review", item.review_id] });
      return true;
    } catch (e) {
      if (current.current) setNotice(`审核已保存，继续生产未成功：${message(e)}。可在本页重试。`);
      return false;
    }
  };
  const submit = async (decision: "approve" | "reject") => {
    if (pending) return;
    setPending(true); setError("");
    try {
      const updated = await submitNarrativeDecision(auth, item.review_id, { candidate_sha: data.candidate_sha,
        decision, rationale, content, reviewed_conclusion_ids: checked });
      if (updated.review_id !== item.review_id || updated.candidate_sha !== data.candidate_sha) throw new Error("服务器返回了其他审核项，草稿保留。");
      try { sessionStorage.removeItem(key); } catch { /* nonfatal */ }
      client.setQueryData(["studio", "review", item.review_id], updated);
      await client.invalidateQueries({ queryKey: ["studio", "reviews"] });
      if (!current.current) return;
      setNotice(decision === "approve" ? "审核已保存。" : "已驳回，本次候选不会发布。调整来源或范围后可重新生成。");
      if (decision === "approve") {
        // The worker may still be parking the newly-created review gate.
        // Stay here until its state settles so an accepted draft isn't stranded.
        let latest = updated;
        for (let attempt = 0; latest.job_status === "running" && attempt < 5 && current.current; attempt++) {
          await new Promise((resolve) => setTimeout(resolve, 500));
          latest = await getReview(auth, item.review_id);
          client.setQueryData(["studio", "review", item.review_id], latest);
        }
        if (!current.current) return;
        if (latest.job_status === "running") { setNotice("审核已保存，生产任务正在处理。状态更新后可继续生产或前往下一项。"); return; }
        if (latest.job_status === "needs_review" && !(await resume())) return;
      }
      await onNext();
    } catch (e) { if (current.current) setError(`${message(e)}。草稿保留；提交结果不确定时，先核对服务器记录。`); }
    finally { if (current.current) setPending(false); }
  };
  const verify = async () => {
    setPending(true);
    try { const fresh = await getReview(auth, item.review_id); client.setQueryData(["studio", "review", item.review_id], fresh); setNotice(fresh.status === "open" ? "服务端仍待审核，可检查草稿后提交。" : "服务端已有审核决定，请查看已保存记录。"); }
    catch (e) { setError(message(e)); } finally { setPending(false); }
  };
  const final = data.decision?.content;
  return <div className="studio-stack narrative-review" data-view="narrative-review">
    <div className="studio-page-heading"><div><p className="studio-eyebrow">内容审核</p><h1>{facts ? "多史料事实核对" : "综合历史正文审核"}</h1><p className="studio-muted">{data.context.sources.length} 个完整章节 · {facts ? `${facts.conclusions.length} 个核对问题` : "正文与阅读入口一起审核"}</p></div><Link to={`/studio/imports/${item.job_id}`}>查看生产进度</Link></div>
    {storageFailed ? <p role="status">浏览器暂时不能保存草稿，请保持本页打开；当前编辑仍保留。</p> : null}
    {notice ? <p role="status">{notice}</p> : null}{navigationNote ? <p role="status">{navigationNote}</p> : null}
    {error ? <div role="alert" className="studio-error-box"><p>{error}</p><Button variant="outline" onClick={() => void verify()} disabled={pending}>核对服务器记录</Button></div> : null}
    {item.status !== "open" ? <section><p>{item.status === "dismissed" ? "生产任务已取消，本项不再等待审核。" : `本次${data.decision?.decision === "approve" ? "审核通过" : "已驳回"}，记录已固定。`}</p><p>{data.decision?.rationale}</p><details><summary>查看已保存内容</summary><pre className="studio-code">{JSON.stringify(final ?? data.candidate, null, 2)}</pre></details></section> : <fieldset className="nr-form" disabled={pending}>
      {facts ? <>
        <details className="nr-scope"><summary>来源关系与时间阶段（须一并核对）</summary>
          <p>同书不同传、转引或抄录不能作为多份独立见证；未提到也不是反证。</p>
          <label>本次内容范围<input value={facts.title} onChange={(e) => patchFacts({ ...facts, title: e.target.value })} /></label>
          {facts.source_relations.map((relation, index) => <div className="nr-field-grid" key={index}>
            <label>{data.context.sources.find((s) => s.source_id === relation.left)?.title} ↔ {data.context.sources.find((s) => s.source_id === relation.right)?.title}<select value={relation.relation} onChange={(e) => patchFacts({ ...facts, source_relations: facts.source_relations.map((r, i) => i === index ? { ...r, relation: e.target.value } : r) })}>{Object.entries(SOURCE_RELATIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label>判断理由<input value={relation.reason} onChange={(e) => patchFacts({ ...facts, source_relations: facts.source_relations.map((r, i) => i === index ? { ...r, reason: e.target.value } : r) })} /></label>
          </div>)}
          <p>阶段控制当时状态，不会自动变成导航入口。任职、控制权变化前后应分开；先调整结论的适用阶段，再移除已不用的阶段。</p>
          {facts.phases.map((phase, index) => <section className="nr-prose" key={phase.id}>
            <PhaseEditor phase={phase} context={data.context} update={(value) => patchFacts({ ...facts, phases: facts.phases.map((p, i) => i === index ? value : p) })} />
            <div className="nr-checks">
              <Button type="button" variant="outline" size="sm" disabled={index === 0} onClick={() => {
                const phases = [...facts.phases]; [phases[index - 1], phases[index]] = [phases[index], phases[index - 1]]; patchFacts({ ...facts, phases });
              }}>阶段前移</Button>
              <Button type="button" variant="outline" size="sm" disabled={index === facts.phases.length - 1} onClick={() => {
                const phases = [...facts.phases]; [phases[index], phases[index + 1]] = [phases[index + 1], phases[index]]; patchFacts({ ...facts, phases });
              }}>阶段后移</Button>
              <Button type="button" variant="outline" size="sm" disabled={facts.phases.length >= 64} onClick={() => {
                const phases = [...facts.phases]; phases.splice(index + 1, 0, { id: localId("phase"), label: "", year: null, period: null, basis: [], relation_to_previous: "uncertain" }); patchFacts({ ...facts, phases });
              }}>在此后新增阶段</Button>
              <Button type="button" variant="outline" size="sm" disabled={facts.phases.length <= 1 || facts.conclusions.some((f) => f.phase_ids.includes(phase.id))} onClick={() => patchFacts({ ...facts, phases: facts.phases.filter((p) => p.id !== phase.id) })}>移除未引用的阶段</Button>
            </div>
          </section>)}
        </details>
        <div className="nr-question-nav"><label>当前问题<select value={selected} onChange={(e) => setSelected(Number(e.target.value))}>{facts.conclusions.map((fact, index) => <option key={fact.id} value={index}>{checked.includes(fact.id) ? "✓ " : ""}{index + 1}. {fact.question}</option>)}</select></label><span>已核对 {checked.length} / {facts.conclusions.length}</span></div>
        <div className="nr-checks">
          <Button type="button" variant="outline" size="sm" disabled={facts.conclusions.length >= 256} onClick={() => {
            const fact: NarrativeFact = { id: localId("fact"), question: "", subject_id: null, event_id: null, dimension: "event_detail", phase_ids: [], text: "", value: null, certainty: "uncertain", reason: "", evidence: [] };
            patchFacts({ ...facts, conclusions: [...facts.conclusions, fact] }, fact.id); setSelected(facts.conclusions.length);
          }}>新增核对问题</Button>
          <Button type="button" variant="outline" size="sm" disabled={facts.conclusions.length >= 256} onClick={() => {
            const fact = { ...copy(facts.conclusions[selected]), id: localId("fact") };
            const conclusions = [...facts.conclusions]; conclusions.splice(selected + 1, 0, fact); patchFacts({ ...facts, conclusions }, fact.id); setSelected(selected + 1);
          }}>复制为另一条结论</Button>
          <Button type="button" variant="outline" size="sm" disabled={facts.conclusions.length <= 1} onClick={() => {
            patchFacts({ ...facts, conclusions: facts.conclusions.filter((_, i) => i !== selected) }, facts.conclusions[selected].id); setSelected(Math.max(0, selected - 1));
          }}>移除此问题</Button>
        </div>
        {facts.conclusions[selected] ? <FactEditor key={facts.conclusions[selected].id} context={data.context} facts={facts} fact={facts.conclusions[selected]} update={(fact) => patchFacts({ ...facts, conclusions: facts.conclusions.map((f, i) => i === selected ? fact : f) }, fact.id)} /> : null}
        <div className="nr-checks"><label><input type="checkbox" checked={checked.includes(facts.conclusions[selected]?.id)} onChange={(e) => { const id = facts.conclusions[selected].id; setChecked(e.target.checked ? [...new Set([...checked, id])] : checked.filter((v) => v !== id)); }} />已核对本问题的结论、阶段、明确性与各份原文</label><Button variant="outline" type="button" disabled={selected === 0} onClick={() => setSelected((n) => n - 1)}>上一个问题</Button><Button variant="outline" type="button" disabled={selected >= facts.conclusions.length - 1} onClick={() => setSelected((n) => n + 1)}>下一个问题</Button></div>
      </> : <ProseEditor content={content as NarrativeProse} data={data} update={(value) => { setContent(value); setScopeChecked(false); }} />}
      <label className="nr-confirm"><input type="checkbox" checked={scopeChecked} onChange={(e) => setScopeChecked(e.target.checked)} />{facts ? "已核对来源传承与时间阶段，不把来源数量当作真实性。" : "已通读正文并检查入口；发布后首页使用这一版本，旧版引用仍保留。"}</label>
      <label>本次审核说明<textarea value={rationale} rows={3} maxLength={4000} onChange={(e) => setRationale(e.target.value)} placeholder="记录核对依据、修订原因或驳回原因" /></label>
    </fieldset>}
    <div className="nr-actions" data-test="narrative-review-actions">
      <Link className="studio-link-button" to={queueHref}>返回队列</Link>
      {item.status === "open" ? <>
        <Button variant="outline" disabled={pending} onClick={() => void onSkip()}>暂时跳过</Button>
        <Button variant="outline" disabled={pending || !rationale.trim()} onClick={() => void submit("reject")}>驳回</Button>
        <Button disabled={pending || !canApprove} onClick={() => void submit("approve")}>{pending ? "保存中…" : "通过并继续"}</Button>
      </> : <><Button variant="outline" disabled={pending} onClick={() => void onNext()}>下一项</Button>{data.decision?.decision === "approve" && item.job_status === "needs_review" ? <Button onClick={() => void resume()}>继续生产</Button> : null}</>}
    </div>
  </div>;
}
