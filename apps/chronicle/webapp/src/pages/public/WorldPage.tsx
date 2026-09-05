import { Link, useLocation } from "react-router-dom";
import { ErrorState, LoadingState } from "../../components/shared";
import { useHistoricalMoment } from "../../lib/queries";
import { historicalTimeLabel, parseHistoricalTime, withHistoricalTime } from "../../lib/historical-time";
import type { HistoricalMomentClaim, HistoricalMomentEntity, HistoricalMomentEvent } from "../../lib/historical-moment";
import type { ReaderPresentation } from "../../lib/types";

const DENSITY_LABEL: Record<string, string> = {
  represented: "当前语料有代表性记录",
  sparse: "当前语料较稀疏",
  unrepresented: "当前语料未覆盖",
};

function readerSummary(presentation: ReaderPresentation | null | undefined): string | null {
  const blocks = presentation?.blocks ?? [];
  return blocks.find((block) => block.block_kind === "overview")?.text ?? blocks[0]?.text ?? null;
}

function eventTimeLabel(event: HistoricalMomentEvent): string {
  const start = event.time.start_year;
  const end = event.time.end_year;
  if (start === null || end === null) return "年代未定";
  const format = (year: number) => (year < 0 ? `公元前 ${Math.abs(year)} 年` : `公元 ${year} 年`);
  return start === end ? format(start) : `${format(start)} — ${format(end)}`;
}

function ClaimPreview({ claim }: { claim: HistoricalMomentClaim }) {
  const evidence = claim.claim?.evidence;
  return (
    <div className="world-claim-preview">
      <span>{claim.source?.title ?? claim.bundle ?? "来源"}</span>
      {claim.claim?.predicate ? <strong>{claim.claim.predicate}</strong> : null}
      {evidence?.text ? <q>{evidence.text}</q> : <em>此 Claim 没有可显示的 evidence 文本。</em>}
    </div>
  );
}

function MomentEventCard({ event, timeSearch }: { event: HistoricalMomentEvent; timeSearch: string }) {
  const summary = readerSummary(event.reader_presentation);
  const title = event.display?.title ?? "未命名事件";
  return (
    <article className="world-event-card" data-event-id={event.canonical_event_id}>
      <div className="world-card-topline">
        <span className="world-year">{eventTimeLabel(event)}</span>
        {event.time.status === "source_disagreement" ? <span className="decision uncertain">来源时间有分歧</span> : null}
      </div>
      <h2>
        <Link data-test="world-event-link" to={withHistoricalTime(`/events/${encodeURIComponent(event.canonical_event_id)}`, timeSearch)}>{title}</Link>
      </h2>
      <div className="hero-meta">
        {event.display?.type ? <span className="chip type">{event.display.type}</span> : null}
        <span className="chip">{event.source_count} 个来源</span>
        <span className="chip">{event.representation_count} 条记录</span>
      </div>
      <p className="world-summary">{summary ?? "当前 canonical Event 没有已发布的现代中文 Reader Presentation；Chronicle 不会临时补写叙事。"}</p>
      {(event.claims ?? []).length ? (
        <div className="world-claim-stack">{event.claims.slice(0, 2).map((claim, index) => <ClaimPreview key={`${claim.bundle}:${claim.ref}:${index}`} claim={claim} />)}</div>
      ) : null}
      <div className="world-card-actions">
        <Link to={withHistoricalTime(`/events/${encodeURIComponent(event.canonical_event_id)}`, timeSearch)}>打开事件</Link>
        <Link data-test="world-evidence-link" to={withHistoricalTime(`/events/${encodeURIComponent(event.canonical_event_id)}#evidence`, timeSearch)}>查看史料与证据</Link>
      </div>
    </article>
  );
}

function EntityGroup({ title, items, timeSearch, empty }: { title: string; items: HistoricalMomentEntity[]; timeSearch: string; empty: string }) {
  return (
    <section className="panel world-entity-panel">
      <div className="panel-heading"><h2>{title}</h2><span className="count">{items.length}</span></div>
      {items.length ? (
        <div className="world-entity-grid">
          {items.map((entity) => {
            const summary = readerSummary(entity.reader_presentation);
            return (
              <Link
                key={entity.canonical_entity_id}
                className="world-entity-card"
                data-test="world-entity-link"
                to={withHistoricalTime(`/entities/${encodeURIComponent(entity.canonical_entity_id)}`, timeSearch)}
              >
                <strong>{entity.display?.name ?? "未命名实体"}</strong>
                <span>{entity.display?.type ?? "entity"} · {entity.source_count} 个来源</span>
                {summary ? <p>{summary}</p> : null}
              </Link>
            );
          })}
        </div>
      ) : <p className="muted">{empty}</p>}
    </section>
  );
}

export default function WorldPage() {
  const location = useLocation();
  const selection = parseHistoricalTime(location.search);
  const moment = useHistoricalMoment(location.search);

  if (!selection) {
    return (
      <section data-view="world">
        <header className="page-header"><p className="eyebrow">Historical World</p><h1>选择一个历史时刻</h1><p className="lede">Chronicle 只会展示当前语料真正能够支撑的 Historical Moment，不会把缺失数据补成完整世界状态。</p></header>
        <section className="state-card empty-card"><h2>从一个年份开始</h2><p className="muted">可以在上方历史时间栏输入年份或最多 100 年的区间。</p><Link className="primary-link" to="/world?year=208">查看公元 208 年</Link></section>
      </section>
    );
  }
  if (moment.isPending) return <LoadingState label={`历史世界 · ${historicalTimeLabel(selection)}`} />;
  if (moment.isError) return <ErrorState code={moment.error.code} message={moment.error.message} />;

  const data = moment.data;
  const events = data.events ?? [];
  const coverageYears = data.coverage?.time?.years ?? [];
  const represented = coverageYears.filter((item) => item.density !== "unrepresented").length;
  const density = selection.kind === "year" ? coverageYears[0]?.density : null;

  return (
    <section data-view="world" data-time-kind={selection.kind}>
      <header className="world-hero">
        <div>
          <p className="eyebrow">Historical Moment Projection</p>
          <h1>{historicalTimeLabel(selection)}的历史世界</h1>
          <p className="lede">这里的“世界”只表示当前 Chronicle 已发布语料在这个时刻能够共同呈现的事件、人物、地点、政体、来源与不确定性，不是完整历史世界状态。</p>
        </div>
        <aside className="world-coverage-summary" data-test="world-coverage-summary">
          <span className={`coverage-dot ${density ?? "period"}`} aria-hidden="true" />
          <strong>{density ? DENSITY_LABEL[density] ?? density : `${represented}/${coverageYears.length} 个年份有语料表示`}</strong>
          <small>{data.page.total_events} 个 canonical Events · {data.sources.length} 个来源</small>
        </aside>
      </header>

      <section className="world-limit-note" data-test="world-limit-note">
        <strong>边界说明</strong>
        <p>{data.authority.limitation}</p>
        <p>没有记录 ≠ 历史上没有发生；Coverage 只描述当前语料库的可见范围。</p>
      </section>

      <div className="world-layout">
        <div className="world-main">
          <section className="panel">
            <div className="panel-heading"><h2>同时发生 / 被记录的事件</h2><span className="count">{events.length} / {data.page.total_events}</span></div>
            {events.length ? <div className="world-event-list">{events.map((event) => <MomentEventCard key={event.canonical_event_id} event={event} timeSearch={location.search} />)}</div> : (
              <section className="state-card empty-card" data-test="world-empty"><h2>当前语料没有这个时段的已发布事件</h2><p className="muted">这是一条 Coverage 结论，不是历史不存在的结论。可以用上方时间栏切换到相邻年份。</p></section>
            )}
          </section>
          <EntityGroup title="人物与其他实体" items={data.entities ?? []} timeSearch={location.search} empty="当前事件没有解析到可展示的人物或其他实体。" />
          <EntityGroup title="地点" items={data.places ?? []} timeSearch={location.search} empty="当前事件没有解析到可展示的地点；不会从常识猜测地理位置。" />
          <EntityGroup title="政体 / 政治实体" items={data.polities ?? []} timeSearch={location.search} empty="当前事件没有持久化为 polity 的实体；不会从年代自动推断政治归属。" />
        </div>
        <aside className="world-side">
          <section className="panel">
            <div className="panel-heading"><h2>不确定性</h2><span className="count">explicit</span></div>
            <dl className="world-facts">
              <div><dt>时间分歧事件</dt><dd>{data.uncertainty.temporal_disagreement_event_count}</dd></div>
              <div><dt>未解析实体引用</dt><dd>{data.uncertainty.unresolved_entity_reference_count}</dd></div>
              <div><dt>缺失是否等于历史不存在</dt><dd>{data.uncertainty.absence_is_not_historical_absence ? "否" : "—"}</dd></div>
            </dl>
          </section>
          <section className="panel">
            <div className="panel-heading"><h2>Coverage</h2><span className="count">corpus</span></div>
            <div className="coverage-year-list">
              {coverageYears.slice(0, 20).map((year) => <div key={year.year}><span>{year.year < 0 ? `前 ${Math.abs(year.year)}` : year.year}</span><strong>{DENSITY_LABEL[year.density] ?? year.density}</strong><small>{year.event_count} events · {year.source_count} sources</small></div>)}
            </div>
            {coverageYears.length > 20 ? <p className="muted">长区间仅摘要显示前 20 个年份；Historical Moment API 仍按选定区间计算。</p> : null}
          </section>
          <section className="panel">
            <div className="panel-heading"><h2>本时刻来源</h2><span className="count">{data.sources.length}</span></div>
            <ul className="world-source-list">{data.sources.map((source) => <li key={source.bundle}><strong>{source.title ?? source.bundle}</strong><code>{source.bundle}</code></li>)}</ul>
          </section>
        </aside>
      </div>
    </section>
  );
}
