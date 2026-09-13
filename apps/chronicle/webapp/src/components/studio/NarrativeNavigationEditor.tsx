import { Button } from "../ui/button";
import { synchronizeNarrativeNavigation } from "../../lib/narrative-navigation";
import type { NarrativeProse } from "../../lib/narrative-types";

type Section = NonNullable<NarrativeProse["navigation"]>[number];

export default function NarrativeNavigationEditor({ content, update }: {
  content: NarrativeProse; update: (content: NarrativeProse) => void;
}) {
  const sections = content.navigation ?? [];
  const positions = new Map(content.paragraphs.map((p, n) => [p.id, n]));
  const label = (id: string) => content.paragraphs.find((p) => p.id === id)?.segments.map((s) => s.text).join("").slice(0, 60) ?? "正文位置已失效";
  const save = (navigation: Section[]) => update(synchronizeNarrativeNavigation({ ...content, navigation }));
  const patch = (index: number, change: Partial<Section>) => save(sections.map((section, n) => n === index ? { ...section, ...change } : section));
  const synchronized = synchronizeNarrativeNavigation(content);
  const needsSync = JSON.stringify(content.navigation) !== JSON.stringify(synchronized.navigation);

  return <section className="studio-stack nr-entries" data-test="narrative-navigation-editor">
    <h2>左侧时间轴</h2>
    <p className="studio-muted">年份或时期是连续轴上的时间刻度，可点击节点统一取自上方精选入口。这里仅编排时间区间；没有重点的区间可留空，所有正文和人物状态仍保留。</p>
    {!sections.length ? <Button type="button" variant="outline" onClick={() => save([{
      label: null, first_paragraph_id: content.paragraphs[0].id,
      last_paragraph_id: content.paragraphs[content.paragraphs.length - 1].id, items: [],
    }])}>编排连续时间轴</Button> : null}
    {needsSync ? <div className="studio-stack"><p className="studio-muted">这份草稿的时间轴与精选入口不一致。同步会移除额外节点，并复用精选入口的名称、位置和理由。</p>
      <Button type="button" variant="outline" onClick={() => update(synchronized)}>按精选入口同步时间轴</Button></div> : null}
    {sections.map((section, index) => {
      const start = positions.get(section.first_paragraph_id)!;
      const end = positions.get(section.last_paragraph_id)!;
      const range = content.paragraphs.slice(start, end + 1);
      return <div className="nr-entry studio-stack" key={section.first_paragraph_id}>
        <label>时间区间名称<input maxLength={80} value={section.label ?? ""} placeholder="有依据的年份或时期；无法确定时留空" onChange={(event) => patch(index, { label: event.target.value || null })} /></label>
        <p className="studio-muted">第 {start + 1}–{end + 1} 段 · {section.items.length} 个精选入口{section.label === null ? " · 前台不显示时间标题" : ""}</p>
        {section.items.map((item) => <div className="nr-entry" data-test="narrative-axis-entry" key={item.paragraph_id}>
          <strong>{item.label}</strong><p>{item.reason}</p><p className="studio-muted">{label(item.paragraph_id)}</p>
        </div>)}
        {section.items.length === 0 ? <p className="studio-muted">这一时间区间没有精选事件，无需补节点。</p> : null}
        {range.length > 1 && sections.length < 64 ? <label>在此段之前拆分时间区间<select value="" onChange={(event) => {
          const at = positions.get(event.target.value);
          if (at === undefined) return;
          save(sections.flatMap((value, n) => n !== index ? [value] : [
            { ...value, last_paragraph_id: content.paragraphs[at - 1].id },
            { label: null, first_paragraph_id: content.paragraphs[at].id, last_paragraph_id: value.last_paragraph_id, items: [] },
          ]));
        }}><option value="">选择下一时段的起点…</option>{range.slice(1).map((p) => <option key={p.id} value={p.id}>{label(p.id)}</option>)}</select></label> : null}
        {index + 1 < sections.length ? <Button type="button" variant="outline" size="sm"
          onClick={() => save(sections.flatMap((value, n) =>
            n === index ? [{ ...value, last_paragraph_id: sections[index + 1].last_paragraph_id }]
              : n === index + 1 ? [] : [value]))}>与下一时间区间合并</Button> : null}
      </div>;
    })}
  </section>;
}
