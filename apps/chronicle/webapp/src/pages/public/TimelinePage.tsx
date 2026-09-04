import { Link, useSearchParams } from "react-router-dom";
import { useTimeline } from "../../lib/queries";
import { formatTime } from "../../lib/routes";
import { ErrorState, LoadingState } from "../../components/shared";

function paginationHref(
  query: { from_year?: number | null; to_year?: number | null; limit?: number },
  offset: number,
): string {
  const params = new URLSearchParams();
  if (query.from_year !== null && query.from_year !== undefined) params.set("from_year", String(query.from_year));
  if (query.to_year !== null && query.to_year !== undefined) params.set("to_year", String(query.to_year));
  params.set("limit", String(query.limit ?? 50));
  params.set("offset", String(Math.max(0, offset)));
  return `/timeline?${params.toString()}`;
}

export default function TimelinePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const search = `?${searchParams.toString()}`;
  const timeline = useTimeline(search);

  if (timeline.isPending) return <LoadingState label="时间线" />;
  if (timeline.isError) {
    return <ErrorState code={timeline.error.code} message={timeline.error.message} />;
  }

  const data = timeline.data;
  const items = data.items ?? [];
  const query = data.query ?? {};
  const page = data.page ?? { total: items.length, returned: items.length, has_more: false };
  const offset = Number(query.offset ?? 0);
  const limit = Number(query.limit ?? 50);

  return (
    <section data-view="timeline">
      <header className="page-header">
        <p className="eyebrow">Timeline</p>
        <h1>历史时间线</h1>
        <p className="lede">
          每张卡片代表一个 canonical Event。多个史料描述同一 occurrence 时只出现一次，来源与证据在详情页继续展开。
        </p>
      </header>

      <form
        className="filter-panel"
        action="/timeline"
        method="get"
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const next = new URLSearchParams(searchParams);
          const fromYear = String(form.get("from_year") ?? "").trim();
          const toYear = String(form.get("to_year") ?? "").trim();
          if (fromYear) next.set("from_year", fromYear);
          else next.delete("from_year");
          if (toYear) next.set("to_year", toYear);
          else next.delete("to_year");
          next.set("offset", "0");
          setSearchParams(next);
        }}
      >
        <div className="field">
          <label htmlFor="from_year">起始年份</label>
          <input id="from_year" name="from_year" inputMode="numeric" defaultValue={query.from_year ?? ""} placeholder="例如 208" />
        </div>
        <div className="field">
          <label htmlFor="to_year">结束年份</label>
          <input id="to_year" name="to_year" inputMode="numeric" defaultValue={query.to_year ?? ""} placeholder="例如 220" />
        </div>
        <button className="primary-button" type="submit">
          查看时间段
        </button>
      </form>

      <div className="page-stats">
        <span>共 {page.total ?? items.length} 个 canonical Events</span>
        <span>本页 {page.returned ?? items.length} 个</span>
      </div>
      {items.length ? (
        <div className="timeline-list">
          {items.map((item) => (
            <article key={item.canonical_event_id} className="timeline-card" data-event-id={item.canonical_event_id}>
              <div className="timeline-year">{formatTime(item.time ?? {})}</div>
              <h2>
                <Link to={`/events/${encodeURIComponent(item.canonical_event_id)}`}>
                  {item.display?.title ?? "未命名事件"}
                </Link>
              </h2>
              <div className="hero-meta">
                {item.display?.type ? <span className="chip type">{item.display.type}</span> : null}
                <span className="chip">{item.source_count ?? 0} 个来源</span>
                <span className="chip">{item.representation_count ?? 0} 条记录</span>
              </div>
              <div className="source-list">
                {(item.source_titles ?? []).map((title) => (
                  <span key={title} className="source-chip">
                    {title}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <section className="state-card empty-card">
          <h2>这个时间段还没有已收录事件</h2>
          <p className="muted">缺少数据不等于历史上什么都没有发生。</p>
        </section>
      )}
      {offset > 0 || page.has_more ? (
        <nav className="pagination" aria-label="时间线分页">
          {offset > 0 ? (
            <Link rel="prev" to={paginationHref(query, offset - limit)}>
              ← 上一页
            </Link>
          ) : null}
          {page.has_more ? (
            <Link rel="next" to={paginationHref(query, offset + limit)}>
              下一页 →
            </Link>
          ) : null}
        </nav>
      ) : null}
    </section>
  );
}
