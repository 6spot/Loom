import { useLayoutEffect, useRef, useState } from "react";
import type { HistoryNavigationSection } from "../../lib/history-api";

export default function HistoryAxis({ sections, activeOrdinal, onNavigate }: {
  sections: readonly HistoryNavigationSection[];
  activeOrdinal: number;
  onNavigate: (paragraphId: string) => void;
}) {
  const scroll = useRef<HTMLDivElement>(null);
  const inside = useRef(false);
  const pausedAt = useRef(activeOrdinal);
  const [paused, setPaused] = useState(false);
  const activeIndex = sections.findIndex((section) => section.start <= activeOrdinal && activeOrdinal <= section.end);
  const pause = () => { pausedAt.current = activeOrdinal; setPaused(true); };

  useLayoutEffect(() => {
    const box = scroll.current;
    if (!box) return;
    // Resume when reading advances outside the manually browsed axis. While
    // the pointer/focus stays here, never take control away from the reader.
    if (paused) {
      if (activeOrdinal !== pausedAt.current && !inside.current && !box.contains(document.activeElement)) setPaused(false);
      return;
    }
    const reveal = () => {
      if (!box.clientHeight) return;
      const target = box.querySelector<HTMLElement>('[data-axis-current="true"]');
      if (!target) return;
      const viewport = box.getBoundingClientRect();
      const item = target.getBoundingClientRect();
      const inset = 12;
      const delta = item.top < viewport.top + inset ? item.top - viewport.top - inset
        : item.bottom > viewport.bottom - inset ? item.bottom - viewport.bottom + inset : 0;
      // scrollIntoView can move ancestor scrollports, including the prose.
      // Change only this private scrollport when the target is out of view.
      if (delta) box.scrollTop += delta;
    };
    reveal();
    // A native dialog is display:none until showModal runs after layout.
    // Observe its first visible size as well as later viewport changes.
    const observer = new ResizeObserver(reveal);
    observer.observe(box);
    return () => observer.disconnect();
  }, [activeOrdinal, activeIndex, paused, sections]);

  return <nav className="history-axis" aria-label="历史时间轴" data-following={paused ? "false" : "true"}>
    <div className="history-axis-toolbar"><span>时间脉络</span>
      {paused ? <button type="button" className="history-axis-resume" onClick={() => setPaused(false)}>回到当前</button> : null}
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
      <ol className="history-axis-track">{sections.map((section, index) => {
        const current = index === activeIndex;
        const currentItem = current ? section.items.reduce((last, item, n) => item.ordinal <= activeOrdinal ? n : last, -1) : -1;
        return <li className="history-axis-section" key={section.id} data-axis-section={section.id}
          data-current={current} data-undated={section.label === null} data-empty={section.items.length === 0}>
          {section.label !== null ? <div className="history-axis-time"
            aria-current={current && currentItem < 0 ? "location" : undefined}
            data-axis-current={current && currentItem < 0 ? "true" : undefined}>
            <span>{section.label}{section.period && !section.label.includes(section.period) ? <small>{section.period}</small> : null}</span>
          </div> : null}
          {current && currentItem < 0 && section.label === null ? <span className="history-axis-position"
            data-axis-current="true" aria-current="location"><span className="public-sr-only">当前阅读位置</span></span> : null}
          <ol className="history-axis-items">{section.items.map((item, n) =>
            <li key={item.paragraph_id}><button type="button" className="history-axis-node"
              data-axis-target={item.paragraph_id}
              data-axis-current={currentItem === n ? "true" : undefined}
              aria-current={currentItem === n ? "location" : undefined}
              onClick={() => { setPaused(false); onNavigate(item.paragraph_id); }}>
              <span className="history-axis-dot" aria-hidden="true" />
              <span><span>{item.label}</span>{item.period ? <small>{item.period}</small> : null}</span>
            </button></li>)}</ol>
        </li>;
      })}</ol>
    </div>
  </nav>;
}
