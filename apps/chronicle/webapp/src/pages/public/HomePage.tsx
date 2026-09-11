import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ChronicleIcon from "../../components/ChronicleIcon";
import PublicDialog from "../../components/PublicDialog";
import EventReadingEntry from "../../components/EventReadingEntry";
import { historicalEntryYears } from "../../lib/historical-entry";
import { useTimeline } from "../../lib/queries";
import { formatTime } from "../../lib/routes";
import type { TimelineItem } from "../../lib/types";

export default function HomePage() {
  const navigate = useNavigate();
  const timeline = useTimeline("?limit=12");
  const [entry, setEntry] = useState<TimelineItem | null>(null);
  const items = timeline.data?.items ?? [];
  const years = historicalEntryYears(items);
  return (
    <section className="history-home" data-view="home">
      <header className="home-heading"><h1>从哪里开始读</h1><p>选一个时刻，或一件你想了解的事。</p></header>
      <form className="history-search" role="search" action="/search" onSubmit={(event) => {
        event.preventDefault();
        const query = String(new FormData(event.currentTarget).get("q") ?? "").trim();
        if (query) navigate(`/search?q=${encodeURIComponent(query)}`);
      }}>
        <label className="public-sr-only" htmlFor="home-query">搜索历史</label>
        <input id="home-query" name="q" placeholder="时期、事件、人物或地点" autoComplete="off" />
        <button className="public-icon-button" type="submit" aria-label="搜索历史"><ChronicleIcon name="search" /></button>
      </form>
      {timeline.isPending ? <p className="home-status" role="status">正在载入历史…</p> : null}
      {timeline.isError ? <div className="home-status" role="alert"><p>历史暂时没有载入，请稍后重试。</p><button className="public-text-button" onClick={() => void timeline.refetch()}>重试</button></div> : null}
      {years.length > 0 ? <section className="home-section" aria-labelledby="home-years"><h2 id="home-years">从一个时刻开始</h2><div className="home-years">{years.map(([year, item]) => <button className="home-year" key={year} onClick={() => setEntry(item)} data-test="home-time-anchor"><span>{year < 0 ? `公元前 ${Math.abs(year)}` : year}<small>年</small></span><ChronicleIcon name="arrow" /></button>)}</div></section> : null}
      {items.length > 0 ? <section className="home-section" aria-labelledby="home-events"><h2 id="home-events">从一件事开始</h2><div className="home-entries">{items.map((item) => <button className="history-entry" key={item.canonical_event_id} data-test="home-event-anchor" data-event-id={item.canonical_event_id} onClick={() => setEntry(item)}><span className="history-entry-time">{formatTime(item.time ?? {})}</span><strong>{item.display?.title ?? "未命名事件"}</strong><ChronicleIcon name="arrow" /></button>)}</div><Link className="public-text-button" to="/timeline">寻找其他时刻 <ChronicleIcon name="arrow" /></Link></section> : null}
      {!timeline.isPending && !timeline.isError && items.length === 0 ? <p className="home-status">还没有已发布的历史内容。</p> : null}
      {entry ? <PublicDialog title={entry.display?.title ?? "选择阅读位置"} onClose={() => setEntry(null)}><EventReadingEntry key={entry.canonical_event_id} eventId={entry.canonical_event_id} catalog={null} returnLocator={null} anchor /></PublicDialog> : null}
    </section>
  );
}
