import { useId, useLayoutEffect, useRef, useState } from "react";
import type { HistoryNavigationSection } from "../../lib/history-api";

export default function HistoryAxis({ sections, activeOrdinal, onNavigate }: {
  sections: readonly HistoryNavigationSection[];
  activeOrdinal: number;
  onNavigate: (paragraphId: string) => void;
}) {
  const listId = useId();
  const scroll = useRef<HTMLDivElement>(null);
  const inside = useRef(false);
  const pausedAt = useRef(activeOrdinal);
  const [paused, setPaused] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const activeIndex = sections.findIndex((section) => section.start <= activeOrdinal && activeOrdinal <= section.end);
  const isExpanded = (index: number) => expanded[sections[index].id] ?? (sections.length <= 6 || Math.abs(index - activeIndex) <= 1);
  const pause = () => { pausedAt.current = activeOrdinal; setPaused(true); };
  const follow = () => {
    if (activeIndex >= 0) setExpanded((value) => ({ ...value, [sections[activeIndex].id]: true }));
    setPaused(false);
  };

  useLayoutEffect(() => {
    const box = scroll.current;
    if (!box || !box.clientHeight) return;
    // Resume when reading advances outside the manually browsed axis. While
    // the pointer/focus stays here, never take control away from the reader.
    if (paused) {
      if (activeOrdinal !== pausedAt.current && !inside.current && !box.contains(document.activeElement)) setPaused(false);
      return;
    }
    const target = box.querySelector<HTMLElement>('[data-axis-current="true"]');
    if (!target) return;
    const viewport = box.getBoundingClientRect();
    const item = target.getBoundingClientRect();
    const inset = 12;
    const delta = item.top < viewport.top + inset ? item.top - viewport.top - inset
      : item.bottom > viewport.bottom - inset ? item.bottom - viewport.bottom + inset : 0;
    // scrollIntoView can move ancestor scrollports, including the prose. Only
    // change this private scrollport, and only when the target is out of view.
    if (delta) box.scrollTop += delta;
  }, [activeOrdinal, activeIndex, expanded, paused, sections]);

  return <nav className="history-axis" aria-label="历史时间轴" data-following={paused ? "false" : "true"}>
    <div className="history-axis-toolbar"><span>时间脉络</span>
      {paused ? <button type="button" className="history-axis-resume" onClick={follow}>回到当前</button> : null}
    </div>
    <div className="history-axis-scroll" ref={scroll} tabIndex={0} aria-label="浏览时间轴"
      onPointerEnter={() => { inside.current = true; }} onPointerLeave={() => { inside.current = false; }}
      onWheel={pause} onTouchStart={pause} onPointerDown={pause}
      onKeyDown={(event) => {
        const box = scroll.current;
        if (!box || !["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"].includes(event.key)) return;
        event.preventDefault(); pause();
        const distance = event.key === "ArrowUp" ? -44 : event.key === "ArrowDown" ? 44
          : event.key === "PageUp" ? -box.clientHeight * .8 : box.clientHeight * .8;
        if (event.key === "Home") box.scrollTop = 0;
        else if (event.key === "End") box.scrollTop = box.scrollHeight;
        else box.scrollTop += distance;
      }}>
      <ol>{sections.map((section, index) => {
        const open = isExpanded(index);
        const current = index === activeIndex;
        const currentItem = current ? section.items.reduce((last, item, n) => item.ordinal <= activeOrdinal ? n : last, -1) : -1;
        const controls = `${listId}-${index}`;
        return <li className="history-axis-section" key={section.id} data-axis-section={section.id} data-current={current}>
          <button type="button" className="history-axis-section-toggle" aria-expanded={open} aria-controls={controls}
            aria-current={current && (!open || currentItem < 0) ? "location" : undefined}
            data-axis-current={current && (!open || currentItem < 0) ? "true" : undefined}
            onClick={() => { pause(); setExpanded((value) => ({ ...value, [section.id]: !open })); }}>
            <span className="history-axis-chevron" aria-hidden="true">{open ? "⌄" : "›"}</span>
            <span>{section.label}{section.period && !section.label.includes(section.period) ? <small>{section.period}</small> : null}</span>
          </button>
          <ol className="history-axis-items" id={controls} hidden={!open}>{section.items.map((item, n) =>
            <li key={item.paragraph_id}><button type="button" className="history-axis-node"
              data-importance={item.importance} data-axis-target={item.paragraph_id}
              data-axis-current={open && currentItem === n ? "true" : undefined}
              aria-current={currentItem === n ? "location" : undefined}
              onClick={() => { setPaused(false); onNavigate(item.paragraph_id); }}>
              <span className="history-axis-dot" aria-hidden="true" />
              <span>{item.period ? <small>{item.period}</small> : null}<span>{item.label}</span></span>
            </button></li>)}</ol>
        </li>;
      })}</ol>
    </div>
  </nav>;
}
