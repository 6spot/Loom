import { Button } from "../ui/button";
import type { NarrativeProse } from "../../lib/narrative-types";

type Section = NonNullable<NarrativeProse["navigation"]>[number];

export default function NarrativeNavigationEditor({ content, update }: {
  content: NarrativeProse; update: (content: NarrativeProse) => void;
}) {
  const sections = content.navigation ?? [];
  const positions = new Map(content.paragraphs.map((p, n) => [p.id, n]));
  const label = (id: string) => content.paragraphs.find((p) => p.id === id)?.segments.map((s) => s.text).join("").slice(0, 60) ?? "正文位置已失效";
  const save = (navigation: Section[]) => update({ ...content, navigation });
  const patch = (index: number, change: Partial<Section>) => save(sections.map((section, n) => n === index ? { ...section, ...change } : section));
  const selected = new Set(sections.flatMap((section) => section.items.map((item) => item.paragraph_id)));
  const missing = content.entry_points.filter((entry) => !selected.has(entry.paragraph_id));
  const entryIds = new Set(content.entry_points.map((entry) => entry.paragraph_id));
  const sortItems = (items: Section["items"]) => [...items].sort((a, b) => positions.get(a.paragraph_id)! - positions.get(b.paragraph_id)!);
  const node = (id: string) => ({ paragraph_id: id, label: label(id), reason: "" });
  const missingIn = (section: Section) => [...new Map(missing.filter((entry) => positions.get(entry.paragraph_id)! >= positions.get(section.first_paragraph_id)!
    && positions.get(entry.paragraph_id)! <= positions.get(section.last_paragraph_id)!).map((entry) => [entry.paragraph_id, entry])).values()];
  const missingOverflow = sections.some((section) => section.items.length + missingIn(section).length > 8);
  const create = () => {
    const items = sortItems([...new Map(content.entry_points.map((entry) => [entry.paragraph_id,
      { paragraph_id: entry.paragraph_id, label: entry.label, reason: entry.reason }])).values()]);
    if (!items.length) items.push(node(content.paragraphs[0].id));
    const navigation: Section[] = [];
    for (let index = 0; index < items.length; index += 8) {
      navigation.push({ label: "", first_paragraph_id: index === 0 ? content.paragraphs[0].id : items[index].paragraph_id,
        last_paragraph_id: items[index + 8] ? content.paragraphs[positions.get(items[index + 8].paragraph_id)! - 1].id
          : content.paragraphs[content.paragraphs.length - 1].id, items: items.slice(index, index + 8) });
    }
    save(navigation);
  };

  return <section className="studio-stack nr-entries" data-test="narrative-navigation-editor">
    <h2>左侧时间轴</h2>
    <p className="studio-muted">按年份、有据范围或时期归组，每组保留少量关键进展。所有正文仍保留，分组不会改变人物状态；月份沿用段落的已审核时间。</p>
    {!sections.length ? <Button type="button" variant="outline" onClick={create}>编排分组时间轴</Button> : null}
    {sections.map((section, index) => {
      const start = positions.get(section.first_paragraph_id)!;
      const end = positions.get(section.last_paragraph_id)!;
      const range = content.paragraphs.slice(start, end + 1);
      return <div className="nr-entry studio-stack" key={section.first_paragraph_id}>
        <label>时间区间名称<input maxLength={80} value={section.label} placeholder="有依据的年份、时期；不能确定时写年代未详" onChange={(event) => patch(index, { label: event.target.value })} /></label>
        <p className="studio-muted">第 {start + 1}–{end + 1} 段 · {section.items.length} 个定位节点</p>
        {section.items.map((item, n) => <div className="nr-entry" key={item.paragraph_id}>
          <label>节点名称<input maxLength={120} value={item.label} onChange={(event) => patch(index, { items: section.items.map((value, i) => i === n ? { ...value, label: event.target.value } : value) })} /></label>
          <label>选择理由<input maxLength={500} value={item.reason} onChange={(event) => patch(index, { items: section.items.map((value, i) => i === n ? { ...value, reason: event.target.value } : value) })} /></label>
          <p className="studio-muted">{entryIds.has(item.paragraph_id) ? "重要入口 · " : ""}{label(item.paragraph_id)}</p>
          <Button type="button" variant="outline" size="sm" disabled={section.items.length <= 1 || entryIds.has(item.paragraph_id)}
            onClick={() => patch(index, { items: section.items.filter((_, i) => i !== n) })}>移除定位节点</Button>
        </div>)}
        {section.items.length < 8 ? <label>补充关键进展<select value="" onChange={(event) => {
          if (event.target.value) patch(index, { items: sortItems([...section.items, node(event.target.value)]) });
        }}><option value="">选择这一时间区间中的正文位置…</option>{range.filter((p) => !section.items.some((item) => item.paragraph_id === p.id)).map((p) => <option key={p.id} value={p.id}>{label(p.id)}</option>)}</select></label> : null}
        {range.length > 1 && sections.length < 64 ? <label>在此段之前拆分时间区间<select value="" onChange={(event) => {
          const at = positions.get(event.target.value);
          if (at === undefined) return;
          const left = section.items.filter((item) => positions.get(item.paragraph_id)! < at);
          const right = section.items.filter((item) => positions.get(item.paragraph_id)! >= at);
          save(sections.flatMap((value, n) => n !== index ? [value] : [
            { ...value, last_paragraph_id: content.paragraphs[at - 1].id, items: left.length ? left : [node(value.first_paragraph_id)] },
            { label: "", first_paragraph_id: content.paragraphs[at].id, last_paragraph_id: value.last_paragraph_id,
              items: right.length ? right : [node(content.paragraphs[at].id)] },
          ]));
        }}><option value="">选择下一时段的起点…</option>{range.slice(1).map((p) => <option key={p.id} value={p.id}>{label(p.id)}</option>)}</select></label> : null}
        {index + 1 < sections.length ? <Button type="button" variant="outline" size="sm"
          disabled={section.items.length + sections[index + 1].items.length > 8} onClick={() => save(sections.flatMap((value, n) =>
            n === index ? [{ ...value, last_paragraph_id: sections[index + 1].last_paragraph_id, items: [...value.items, ...sections[index + 1].items] }]
              : n === index + 1 ? [] : [value]))}>与下一时间区间合并</Button> : null}
      </div>;
    })}
    {missingOverflow ? <p className="studio-muted">补入后有区间超过 8 个节点，请先拆分时间区间或移除次要节点。</p> : null}
    {sections.length > 0 && missing.length > 0 ? <Button type="button" variant="outline" disabled={missingOverflow} onClick={() => save(sections.map((section) => ({ ...section,
      items: sortItems([...section.items, ...missingIn(section).map((entry) => ({ paragraph_id: entry.paragraph_id, label: entry.label, reason: entry.reason }))]),
    })))}>补入 {missing.length} 个缺少的重要入口</Button> : null}
  </section>;
}
