import { typeLabel } from "../../lib/review-display";
import { attributionLabel, dimensionLabel, operationLabel, qualificationLabel } from "../../lib/person-state-review-display";
import type { Attribution, Qualification, StateDimension, StateOperation } from "../../lib/person-state-types";

type Row = Record<string, unknown>;
const object = (value: unknown): Row => value && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.map(object) : [];
const text = (value: unknown): string => typeof value === "string" ? value : "";

/** A readable projection of saved results; never infer missing history. */
export default function StructuredResult({ value, raw = false }: { value: unknown; raw?: boolean }) {
  const record = object(value);
  const candidate = object(record.candidate ?? record.parsed ?? value);
  const translation = object(candidate.translation);
  const blocks = rows(translation.blocks ?? candidate.blocks);
  const bundle = object(candidate.bundle);
  const entities = rows(bundle.entities);
  const events = rows(bundle.events);
  const states = object(candidate.person_states);
  const facts = rows(states.facts);
  const issues = rows(candidate.issues ?? record.issues);
  const differences = rows(candidate.differences);
  const links = rows(candidate.translation_links);
  const units = rows(object(candidate.reading).units);
  const patches = rows(candidate.patches);
  const names = new Map(entities.map((entity) => [text(entity.temp_id ?? entity.id), text(entity.name ?? entity.canonical_name)]));
  const phases = new Map(rows(states.phases).map((phase) => [text(phase.phase_id), text(phase.label)]));
  const nameFor = (ref: unknown) => names.get(text(object(ref).ref ?? ref));
  const verdicts: Record<string, string> = { pass: "复核通过", revise: "需要修订", needs_review: "需要人工核对", reject: "未通过", selected: "建议采用", compatible: "内容相容", rejected: "不建议采用", disputed: "存在分歧" };
  const label = text(candidate.verdict ?? candidate.decision);
  const hasReadable = blocks.length || entities.length || events.length || facts.length || issues.length || differences.length || links.length || patches.length || label;
  return <div className="studio-result-content">
    {label ? <p className="studio-result-verdict">{verdicts[label] ?? "已返回复核意见"}</p> : null}
    {text(candidate.rationale) ? <p>{text(candidate.rationale)}</p> : null}
    {blocks.length ? <div className="studio-result-prose">{blocks.map((block, index) => <p key={index}>{text(block.text)}</p>)}</div> : null}
    {entities.length ? <section><h3>人物、地点与相关对象 <span>{entities.length}</span></h3><div className="studio-object-list">{entities.map((entity, index) => <div key={index}><strong>{text(entity.name ?? entity.canonical_name) || "未命名对象"}</strong><span>{typeLabel(text(entity.type))}</span>{text(entity.description) ? <p>{text(entity.description)}</p> : null}</div>)}</div></section> : null}
    {events.length ? <section><h3>事件记录 <span>{events.length}</span></h3>{events.map((event, index) => <div className="studio-result-record" key={index}><strong>{text(event.title ?? event.name) || `事件 ${index + 1}`}</strong>{text(event.summary ?? event.description) ? <p>{text(event.summary ?? event.description)}</p> : null}</div>)}</section> : null}
    {facts.length ? <section><h3>人物状态与阶段依据 <span>{facts.length}</span></h3>{facts.map((fact, index) => <div className="studio-result-record" key={index}>
      <strong>{nameFor(fact.person_ref) || `状态依据 ${index + 1}`} · {dimensionLabel(text(fact.dimension) as StateDimension)}</strong>
      <p>{qualificationLabel(text(fact.qualification) as Qualification)}{operationLabel(text(fact.operation) as StateOperation)}：{nameFor(fact.value_ref ?? fact.target_ref) || "对象名称未记录"}</p>
      <small className="studio-muted">{phases.get(text(fact.phase_ref)) || "阶段名称未记录"} · {attributionLabel(text(fact.attribution) as Attribution)}</small>
      {rows(fact.source_selections).map((source, sourceIndex) => <blockquote key={sourceIndex}>{text(source.quote)}</blockquote>)}
    </div>)}</section> : null}
    {links.length ? <section><h3>原文与时间关联</h3><p>{links.length} 段译文已关联原文，{units.length} 个正文位置保存了事件与侧栏信息。</p><p className="studio-muted">关联记录用于阅读时定位依据；不会把每个事件都变成精选入口。</p></section> : null}
    {patches.length ? <section><h3>局部修订 <span>{patches.length}</span></h3>{patches.map((patch, index) => <div className="studio-result-record" key={index}><strong>修订 {index + 1}</strong>{text(patch.value) ? <p>{text(patch.value)}</p> : <p className="studio-muted">调整了提取或关联信息，具体字段保留在完整记录中。</p>}</div>)}</section> : null}
    {issues.length ? <section><h3>核对意见 <span>{issues.length}</span></h3>{issues.map((issue, index) => <div className="studio-result-record" key={index}><span className="studio-status" data-status="needs_review">{issue.type === "source_uncertainty" ? "史料不确定" : "处理问题"}</span><p>{text(issue.message ?? issue.rationale)}</p></div>)}</section> : null}
    {differences.length ? <section><h3>模型比较意见</h3>{differences.map((difference, index) => <div className="studio-result-record" key={index}><strong>候选 {index + 1} · {verdicts[text(difference.assessment)] ?? "待核对"}</strong><p>{text(difference.rationale)}</p></div>)}</section> : null}
    {!hasReadable ? <p className="studio-result-prose">{text(record.raw_text) || (typeof value === "string" ? value : "本次结果以结构化记录保存，请展开查看。")}</p> : null}
    <details className="studio-details"><summary>{raw ? "完整原始结果与字段" : "完整记录与来源字段"}</summary><pre className="studio-code">{JSON.stringify(value, null, 2)}</pre></details>
  </div>;
}
