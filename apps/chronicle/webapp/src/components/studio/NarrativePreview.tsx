import { useRef, useState } from "react";
import type { NarrativeProse, NarrativeReviewData } from "../../lib/narrative-types";

const DIMENSIONS: Record<string, string> = { office: "官职", title: "爵号", allegiance: "所属势力", administration: "行政归属", control: "实际控制" };

/** Review-only preview of the current draft. No public publication is made. */
export default function NarrativePreview({ content, data }: { content: NarrativeProse; data: NarrativeReviewData }) {
  const [activeId, setActiveId] = useState(content.paragraphs[0]?.id);
  const textBox = useRef<HTMLDivElement>(null);
  const active = content.paragraphs.find((paragraph) => paragraph.id === activeId) ?? content.paragraphs[0];
  const facts = data.facts;
  const phase = facts?.phases.find((item) => item.id === active?.phase_id);
  const go = (id: string) => {
    setActiveId(id);
    const box = textBox.current;
    const target = Array.from(box?.querySelectorAll<HTMLElement>("[data-preview-paragraph]") ?? []).find((node) => node.dataset.previewParagraph === id);
    if (box && target) { box.scrollTop += target.getBoundingClientRect().top - box.getBoundingClientRect().top - 18; target.focus({ preventScroll: true }); }
  };
  const follow = () => {
    const box = textBox.current;
    if (!box) return;
    const line = box.getBoundingClientRect().top + 80;
    const nodes = Array.from(box.querySelectorAll<HTMLElement>("[data-preview-paragraph]"));
    const current = nodes.find((node) => node.getBoundingClientRect().bottom >= line);
    if (current?.dataset.previewParagraph) setActiveId(current.dataset.previewParagraph);
  };
  return <section className="studio-reading-preview" aria-label="待审核历史阅读预览">
    <nav aria-label="预览精选入口"><p className="studio-eyebrow">精选入口</p><div className="studio-preview-axis">{content.entry_points.map((entry, index) => <button type="button" key={index} onClick={() => go(entry.paragraph_id)} aria-current={active?.id === entry.paragraph_id ? "location" : undefined}>{entry.label}</button>)}</div>{content.entry_points.length === 0 ? <small className="studio-muted">本稿没有精选入口</small> : null}</nav>
    <div ref={textBox} className="studio-preview-prose" onScroll={follow} tabIndex={0} aria-label="连续历史正文预览">{content.paragraphs.map((paragraph) => <p key={paragraph.id} data-preview-paragraph={paragraph.id} tabIndex={0} onFocus={() => setActiveId(paragraph.id)} onClick={() => setActiveId(paragraph.id)}>{paragraph.segments.map((segment, index) => <span key={index} data-certainty={segment.conclusion_ids.some((id) => facts?.conclusions.find((fact) => fact.id === id)?.certainty === "uncertain") ? "uncertain" : "clear"}>{segment.text}</span>)}</p>)}</div>
    <aside aria-label="预览当前人物与地点"><p className="studio-eyebrow">当前内容</p><p className="studio-preview-time">{phase?.year != null ? `${phase.year < 0 ? `公元前 ${Math.abs(phase.year)}` : phase.year} 年` : phase?.period || "按正文顺序"}</p>
      {active?.entities.filter((entity) => entity.importance === "primary").map((entity) => {
        const subject = data.context.entities[entity.entity_id];
        const states = facts?.conclusions.filter((fact) => fact.subject_id === entity.entity_id && fact.phase_ids.includes(active.phase_id) && fact.dimension !== "event_detail") ?? [];
        return <div className="studio-preview-person" key={entity.entity_id}><strong>{subject?.name || "未命名对象"}</strong>{states.length ? states.map((state) => <p key={state.id} data-certainty={state.certainty}><span>{state.certainty === "uncertain" ? "○ " : "● "}{DIMENSIONS[state.dimension]}</span>{state.value}</p>) : <small>本阶段暂无明确状态记载</small>}</div>;
      })}
    </aside>
  </section>;
}
