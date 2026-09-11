import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import ChronicleIcon from "../../components/ChronicleIcon";
import { historyPath, historyTimeLabel, loadHistory } from "../../lib/history-api";

export default function HomePage() {
  const navigate = useNavigate();
  const history = useQuery({ queryKey: ["history", "directory", "latest"], queryFn: () => loadHistory(), staleTime: 30_000 });
  const publication = history.data;
  const periods = publication?.entry_points.filter((entry) => entry.kind === "period") ?? [];
  const events = publication?.entry_points.filter((entry) => entry.kind === "event") ?? [];
  const path = (paragraph: string) => historyPath({ version: publication!.version, paragraph_id: paragraph });
  return <section className="history-home" data-view="home">
    <header className="home-heading"><h1>从哪里开始读</h1><p>走进一个时代，沿着历史往下读。</p></header>
    <form className="history-search" role="search" action="/search" onSubmit={(event) => {
      event.preventDefault(); const query = String(new FormData(event.currentTarget).get("q") ?? "").trim();
      if (query) navigate(`/search?q=${encodeURIComponent(query)}`);
    }}>
      <label className="public-sr-only" htmlFor="home-query">搜索历史</label>
      <input id="home-query" name="q" placeholder="时期、事件、人物或地点" autoComplete="off" />
      <button className="public-icon-button" type="submit" aria-label="搜索历史"><ChronicleIcon name="search" /></button>
    </form>
    {history.isPending ? <p className="home-status" role="status">正在载入历史…</p> : null}
    {history.isError ? <div className="home-status" role="alert"><p>历史暂时没有载入，请稍后重试。</p><button className="public-text-button" onClick={() => void history.refetch()}>重试</button></div> : null}
    {periods.length > 0 ? <section className="home-section" aria-labelledby="home-periods"><h2 id="home-periods">从一个时期开始</h2><div className="home-entries">{periods.map((entry) => <Link className="history-entry" key={entry.paragraph_id} to={path(entry.paragraph_id)} data-test="home-time-anchor"><span className="history-entry-time">{historyTimeLabel(entry)}</span><strong>{entry.label}</strong><ChronicleIcon name="arrow" /><span className="history-entry-excerpt">{entry.excerpt}</span></Link>)}</div></section> : null}
    {events.length > 0 ? <section className="home-section" aria-labelledby="home-events"><h2 id="home-events">从一件大事开始</h2><div className="home-entries">{events.map((entry) => <Link className="history-entry" key={`${entry.event_id}:${entry.paragraph_id}`} to={path(entry.paragraph_id)} data-test="home-event-anchor"><span className="history-entry-time">{historyTimeLabel(entry)}</span><strong>{entry.label}</strong><ChronicleIcon name="arrow" /><span className="history-entry-excerpt">{entry.excerpt}</span></Link>)}</div></section> : null}
    {publication ? <Link className="public-text-button" to={path(publication.first_paragraph_id)}>从当前收录的开头阅读 <ChronicleIcon name="arrow" /></Link> : null}
    {!history.isPending && !history.isError && !publication ? <p className="home-status">历史正文正在整理，发布后会在这里出现。</p> : null}
  </section>;
}
