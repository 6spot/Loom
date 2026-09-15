import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router-dom";
import ChapterSourceReference from "../../components/ChapterSourceReference";
import ReaderPresentation from "../../components/ReaderPresentation";
import HistoryReturnLink from "../../components/HistoryReturnLink";
import PersonStateDetails from "../../components/reading/PersonStateDetails";
import PersonHistoryReader from "../../components/reading/PersonHistoryReader";
import type { ReadingStateFact } from "../../components/reading/ReadingContextPanel";
import { useEntity, personStatePhaseKey } from "../../lib/queries";
import {
  HistoryPhaseError,
  historyTimeLabel,
  isHistoryLocator,
  loadHistoryConclusion,
  loadHistoryPhase,
  type HistoryConclusion,
  type HistoryPhaseData,
} from "../../lib/history-api";
import { formatTime, readPath } from "../../lib/routes";
import { withHistoricalTime, worldPathFromSearch } from "../../lib/historical-time";
import { ClaimsBlock, ErrorState, LoadingState, RawDetails, ResolutionBlock } from "../../components/shared";
import type { ReaderPresentation as ReaderPresentationData, Representation, TrajectoryEvent } from "../../lib/types";
import { buildReadingUrl, readReturnToken } from "../../lib/reading-location";
import { ReadingHistoryStore, ReadingStorage } from "../../lib/reading-history";
import { useSourcePersonStateContext } from "../../hooks/usePersonStateContext";
import type { ReadingLocator } from "../../lib/reading-types";
import "../../styles/entity.css";

const ENTITY_KIND_LABELS: Readonly<Record<string, string>> = {
  person: "人物",
  place: "地点",
  polity: "政权",
  organization: "组织",
};

function entityKindLabel(kind: string | undefined): string {
  return kind ? ENTITY_KIND_LABELS[kind] ?? "对象" : "对象";
}

function presentationOverview(presentation: ReaderPresentationData | null): string | null {
  const overview = presentation?.blocks?.find((block) => block.block_kind === "overview" && block.text.trim());
  return overview?.text.trim() || null;
}

function EntityRepresentation({ rep }: { rep: Representation }) {
  const entity = rep.entity ?? {};
  const aliases = Array.isArray(entity.aliases) && entity.aliases.length ? (entity.aliases as string[]) : [];
  return (
    <article className="source-card" data-source={rep.bundle}>
      <header>
        <div><div className="source-title">{rep.source?.title ?? rep.bundle}</div><div className="muted">来源记录</div></div>
        <code>{rep.bundle}:{rep.ref}</code>
      </header>
      {aliases.length ? <div className="chip-row">{aliases.map((alias) => <span key={alias} className="chip">{alias}</span>)}</div> : null}
      <ClaimsBlock claims={rep.claims ?? []} />
      <RawDetails label="查看源 Entity 记录" payload={entity} />
      <RawDetails label="查看 Source 元数据" payload={rep.source?.record ?? {}} />
    </article>
  );
}

function involvementChips(involvements: TrajectoryEvent["source_involvements"] = []): string[] {
  const roles = new Set<string>();
  let asPlace = false;
  for (const item of involvements ?? []) {
    for (const role of item.participant_roles ?? []) roles.add(role);
    if (item.as_place) asPlace = true;
  }
  const chips = [...roles].sort();
  if (asPlace) chips.push("作为地点");
  return chips;
}

function useReadingReturn(search: string): ReadingLocator | null {
  return useMemo(() => {
    const token = readReturnToken(search);
    if (!token || typeof window === "undefined") return null;
    try {
      const store = new ReadingHistoryStore(new ReadingStorage(window.sessionStorage));
      return store.resolveReturn(token);
    } catch {
      return null;
    }
  }, [search]);
}

function ReadingReturnBar({ returnLocator }: { returnLocator: ReadingLocator | null }) {
  return (
    <div className="reading-entry" data-test="entity-reading-entry">
      {returnLocator ? (
        <Link className="primary-link" data-test="reading-return" to={buildReadingUrl(returnLocator)}>
          返回阅读
        </Link>
      ) : (
        <Link className="primary-link" data-test="reading-enter" to={readPath()}>
          进入相关正文
        </Link>
      )}
    </div>
  );
}

function HistoryFactEvidence({ version, factId }: { version: string; factId: string }) {
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<{ publicationId: string; anchorId: string } | null>(null);
  const query = useQuery<{ conclusion: HistoryConclusion }, Error>({
    queryKey: ["entity-history-evidence", version, factId],
    queryFn: () => loadHistoryConclusion(version, factId),
    enabled: open,
    staleTime: Infinity,
    retry: 1,
  });
  return (
    <details className="entity-state-evidence" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="public-text-button">查看原文依据</summary>
      {query.isPending ? <p role="status">正在载入本条依据…</p> : null}
      {query.isError ? <div role="alert"><p>本条依据暂时无法读取。</p><button type="button" className="public-text-button" onClick={() => void query.refetch()}>重试</button></div> : null}
      {query.data ? <div className="entity-state-evidence-content">
        <p className="muted">{query.data.conclusion.question}</p>
        <p>{query.data.conclusion.text}</p>
        <p className="entity-state-reason">依据：{query.data.conclusion.reason}</p>
        {query.data.conclusion.evidence.map((item) => <section key={item.id} className="entity-source-quote">
          <p className="muted">{item.source_title} · {item.attribution}</p>
          <blockquote>{item.quote}</blockquote>
          {item.note ? <p>{item.note}</p> : null}
          <button type="button" className="public-text-button" onClick={() => setSource({ publicationId: item.publication_id, anchorId: item.anchor_id })}>查看原章前后文</button>
        </section>)}
        {source ? <ChapterSourceReference key={`${source.publicationId}:${source.anchorId}`} publicationId={source.publicationId} anchorId={source.anchorId} anchorLabel="原章前后文" onClose={() => setSource(null)} /> : null}
      </div> : null}
    </details>
  );
}

function HistoryStateFacts({ version, facts }: { version: string; facts: readonly ReadingStateFact[] }) {
  return (
    <ul className="entity-state-facts" data-test="entity-phase-facts">
      {facts.map((fact) => (
        <li key={fact.id} className="entity-state-fact" data-certainty={fact.certainty} data-fact-id={fact.id}>
          <span className="chr-state-mark" aria-hidden="true">{fact.certainty === "clear" ? "●" : "○"}</span>
          <span className="public-sr-only">{fact.certainty === "clear" ? "明确记载：" : "存疑："}</span>
          <span className="entity-state-label">{fact.label}</span>
          <span className="entity-state-value">{fact.value}</span>
          {fact.certainty === "uncertain" ? <small>存疑</small> : null}
          <HistoryFactEvidence version={version} factId={fact.id} />
        </li>
      ))}
    </ul>
  );
}

/**
 * Composite-history state for this entity. The paragraph and period come from
 * the fixed history response itself; the optional URL phase is only a cache
 * discriminator and is never used to choose or label a state.
 */
function HistoryPhasePanel({
  version,
  paragraphId,
  phaseId,
  entityId,
}: {
  version: string | null;
  paragraphId: string | null;
  phaseId: string | null;
  entityId: string;
}) {
  const locator = version !== null && paragraphId !== null
    ? { version, paragraph_id: paragraphId }
    : null;
  const validLocator = locator !== null && isHistoryLocator(locator);
  const query = useQuery<HistoryPhaseData, Error>({
    queryKey: personStatePhaseKey({ version: version ?? "", paragraph_id: paragraphId ?? "", phase_id: phaseId ?? null }),
    queryFn: ({ signal }) => loadHistoryPhase(locator!.version, locator!.paragraph_id, signal),
    enabled: validLocator,
    staleTime: Infinity,
    retry: 1,
  });

  if (version === null && paragraphId === null) return null;
  if (!validLocator) {
    return (
      <section className="panel entity-phase-panel" data-test="entity-phase-invalid">
        <div className="panel-heading"><h2>当前阶段状态</h2></div>
        <div role="alert"><p>这条人物页缺少有效的历史段落位置。请从历史正文重新进入，避免带入其他段落的状态。</p></div>
      </section>
    );
  }
  if (query.isPending) {
    return <section className="panel entity-phase-panel"><div className="panel-heading"><h2>当前阶段状态</h2></div><p role="status">正在载入当前历史段落的状态…</p></section>;
  }
  if (query.isError) {
    const notFound = query.error instanceof HistoryPhaseError && query.error.code === "not_found";
    return (
      <section className="panel entity-phase-panel" data-test={notFound ? "entity-phase-not-found" : "entity-phase-error"}>
        <div className="panel-heading"><h2>当前阶段状态</h2></div>
        <div role="alert">
          <p>{notFound ? "没有找到这段固定历史版本，未显示其他段落的状态。" : "当前阶段状态暂时无法读取。"}</p>
          <button type="button" className="public-text-button" data-test="entity-phase-retry" onClick={() => { void query.refetch(); }}>重试</button>
        </div>
      </section>
    );
  }

  const { paragraph, group } = query.data;
  const states = paragraph.entities.find((item) => item.id === entityId)?.states ?? [];
  const related = paragraph.entities.filter((item) => item.id !== entityId);
  const phaseLabel = group?.label?.trim() || "阶段未注明";
  const timeLabel = historyTimeLabel(group) || "时间未注明";
  return (
    <section className="panel entity-phase-panel" data-test="entity-phase-state" data-phase-id={paragraph.phase_id} data-paragraph-id={paragraph.id}>
      <div className="panel-heading">
        <div>
          <h2>当前阶段状态</h2>
          <p className="entity-phase-context"><strong>{phaseLabel}</strong><span>{timeLabel}</span></p>
        </div>
        <span className="count">{states.length ? `${states.length} 项` : "暂无记载"}</span>
      </div>
      {states.length ? <HistoryStateFacts version={locator!.version} facts={states} /> : <p className="chr-context-unknown">本段没有该人物的官职、爵号或效力记载。</p>}
      {related.length ? (
        <div className="entity-phase-related" data-test="entity-phase-related">
          <h3>同段相关对象</h3>
          <div className="chip-row">{related.map((item) => <span key={item.id} className="chip">{item.name}</span>)}</div>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Main-history/direct-entry experience view. The entity endpoint already
 * returns published, source-backed event associations in chronological order;
 * present them once as a readable timeline instead of exposing the old event
 * card/claim dump as the page's primary content. This is an evidence-backed
 * reading aid, not a generated or complete biography.
 */
function EntityExperienceTimeline({ events, search }: { events: readonly TrajectoryEvent[]; search: string }) {
  return (
    <section className="panel entity-experience-panel" data-test="entity-experience">
      <div className="panel-heading">
        <div><h2>有据经历</h2><p className="entity-experience-scope">只列当前已发布资料关联到此人物的经历，不代表完整生平。</p></div>
        <span className="count">{events.length ? `${events.length} 项` : "暂无记载"}</span>
      </div>
      {events.length ? (
        <ol className="entity-experience-timeline">
          {events.map((event) => (
            <li className="entity-experience-entry" data-test="entity-experience-entry" key={event.canonical_event_id}>
              <span className="entity-experience-time">{formatTime(event.time ?? {})}</span>
              <div className="entity-experience-content">
                <Link className="entity-experience-event" data-test="entity-experience-event" to={withHistoricalTime(`/events/${encodeURIComponent(event.canonical_event_id)}`, search)}>
                  {event.display?.title ?? "未命名经历"}
                </Link>
                {involvementChips(event.source_involvements ?? []).length ? <div className="trajectory-meta">{involvementChips(event.source_involvements ?? []).map((chip) => <span key={chip} className="role-chip">{chip}</span>)}</div> : null}
              </div>
            </li>
          ))}
        </ol>
      ) : <p className="chr-context-unknown">当前已发布资料没有可连续展开的有据经历。</p>}
    </section>
  );
}

/**
 * Source-reading person state for this entity. A source locator resolves to
 * the full compiled PersonSummary; without one this panel stays an honest
 * scope empty state rather than turning the main history into a biography.
 */
function SourcePersonPanel({ locator, entityId, events, search }: { locator: ReadingLocator | null; entityId: string; events: readonly TrajectoryEvent[]; search: string }) {
  const source = useSourcePersonStateContext(locator, { enabled: Boolean(locator) });
  if (!locator) {
    return <EntityExperienceTimeline events={events} search={search} />;
  }
  if (source.status === "loading") return <section className="panel entity-experience-panel"><div className="panel-heading"><h2>有据经历</h2></div><p role="status">正在载入来源人物阶段资料…</p></section>;
  if (source.status === "error") return (
    <section className="panel entity-experience-panel" data-test="entity-source-person-error">
      <div className="panel-heading"><h2>有据经历</h2></div>
      <div role="alert"><p>来源人物资料暂时无法读取。</p><button type="button" className="public-text-button" data-test="entity-source-person-retry" onClick={source.retry}>重试</button></div>
    </section>
  );
  const person = source.people.find((item) => item.person_id === entityId);
  if (!person) return (
    <section className="panel entity-experience-panel" data-test="entity-source-person-missing">
      <div className="panel-heading"><h2>有据经历</h2></div>
      <p>当前来源阅读位置没有登记此人物；不按名称或年份猜一份身份。</p>
    </section>
  );
  return (
    <section className="panel entity-experience-panel" data-test="entity-source-person">
      <div className="panel-heading"><h2>有据经历</h2><span className="count">当前史料</span></div>
      <p className="entity-experience-scope">只列当前来源阅读位置已经发布的阶段记载，明确与存疑逐项保留。</p>
      <PersonStateDetails person={person} phases={source.phases} />
    </section>
  );
}

function EntityEvidence({
  entityId,
  readerPresentation,
  reps,
  events,
  claims,
  resolutionLinks,
  showEventRecords,
  search,
}: {
  entityId: string;
  readerPresentation: ReaderPresentationData | null;
  reps: readonly Representation[];
  events: readonly TrajectoryEvent[];
  claims: NonNullable<ReturnType<typeof useEntity>["data"]>["claims"];
  resolutionLinks: NonNullable<ReturnType<typeof useEntity>["data"]>["resolution_links"];
  showEventRecords: boolean;
  search: string;
}) {
  const hasPresentation = Boolean(readerPresentation?.blocks?.length);
  const hasEventRecords = showEventRecords && events.length > 0;
  const hasEvidence = hasPresentation || reps.length > 0 || hasEventRecords || (claims?.length ?? 0) > 0 || (resolutionLinks?.length ?? 0) > 0;
  if (!hasEvidence) return null;
  return (
    <details className="entity-evidence" id="evidence" data-test="entity-evidence">
      <summary>查看来源、不同说法与技术资料</summary>
      <div className="entity-evidence-body">
        {hasPresentation ? <section className="entity-evidence-section"><h3>已发布阅读文本</h3><ReaderPresentation presentation={readerPresentation} /></section> : null}
        {hasEventRecords ? (
          <section className="entity-evidence-section">
            <div className="panel-heading"><h3>关联事件</h3><span className="count">{events.length} 项</span></div>
            <div className="trajectory-list">
              {events.map((event) => (
                <Link key={event.canonical_event_id} className="trajectory-card" to={withHistoricalTime(`/events/${encodeURIComponent(event.canonical_event_id)}`, search)} data-test="trajectory-event">
                  <strong>{event.display?.title ?? "未命名事件"}</strong>
                  <span className="muted">{formatTime(event.time ?? {})}</span>
                  <div className="trajectory-meta">{involvementChips(event.source_involvements ?? []).map((chip) => <span key={chip} className="role-chip">{chip}</span>)}</div>
                </Link>
              ))}
            </div>
          </section>
        ) : null}
        {reps.length ? (
          <section className="entity-evidence-section">
            <div className="panel-heading"><h3>来源记录</h3><span className="count">{reps.length} 项</span></div>
            <div className="source-stack">{reps.map((rep, index) => <EntityRepresentation key={`${rep.bundle ?? "bundle"}:${rep.ref ?? index}`} rep={rep} />)}</div>
          </section>
        ) : null}
        {(resolutionLinks?.length ?? 0) > 0 ? (
          <section className="entity-evidence-section">
            <div className="panel-heading"><h3>身份核对</h3><span className="count">{resolutionLinks?.length ?? 0} 项</span></div>
            <ResolutionBlock links={resolutionLinks ?? []} targetKind="entity" currentId={entityId} />
          </section>
        ) : null}
        {(claims?.length ?? 0) > 0 ? (
          <section className="entity-evidence-section">
            <div className="panel-heading"><h3>直接主张</h3><span className="count">{claims?.length ?? 0} 项</span></div>
            <ClaimsBlock claims={claims ?? []} />
          </section>
        ) : null}
      </div>
    </details>
  );
}

export default function EntityPage() {
  const { id } = useParams();
  const location = useLocation();
  const params = new URLSearchParams(location.search.startsWith("?") ? location.search.slice(1) : location.search);
  const catalog = params.get("catalog");
  const version = params.get("version");
  const paragraphId = params.get("para");
  const phaseId = params.get("phase");
  const requestedPersonVersion = params.get("person_version") ?? params.get("person_history_version") ?? params.get("history_version");
  const hasHistoryLocator = version !== null || paragraphId !== null;
  const hasValidHistoryLocator = version !== null && paragraphId !== null && isHistoryLocator({ version, paragraph_id: paragraphId });
  const returnLocator = useReadingReturn(location.search);
  const entity = useEntity(id, catalog);

  if (entity.isPending) return <LoadingState label="实体" />;
  if (entity.isError) return <ErrorState code={entity.error.code} message={entity.error.message} />;

  const data = entity.data;
  const reps = data.representations ?? [];
  const events = data.events ?? [];
  const claims = data.claims ?? [];
  const resolutionLinks = data.resolution_links ?? [];
  const readerPresentation = data.reader_presentation ?? null;
  const isPerson = data.display?.type === "person";
  const intro = presentationOverview(readerPresentation);
  const hasEvidence = Boolean(readerPresentation?.blocks?.length) || reps.length > 0 || (!isPerson && events.length > 0) || claims.length > 0 || resolutionLinks.length > 0;

  if (isPerson) {
    return (
      <section data-view="entity" data-canonical-id={data.canonical_entity_id}>
        <div className="breadcrumbs"><Link to={worldPathFromSearch(location.search)}>历史世界</Link><span>›</span><Link to={withHistoricalTime("/timeline", location.search)}>时间线</Link><span>›</span><span>人物</span></div>
        <PersonHistoryReader
          key={`${data.canonical_entity_id}:${requestedPersonVersion ?? "latest"}`}
          entityId={data.canonical_entity_id}
          name={data.display?.name ?? "未命名人物"}
          search={location.search}
          returnLocator={returnLocator}
          requestedPersonVersion={requestedPersonVersion}
          mainLocator={{ version, paragraphId, phaseId }}
          hasEvidence={hasEvidence}
          events={events}
        />
        <EntityEvidence entityId={data.canonical_entity_id} readerPresentation={readerPresentation} reps={reps} events={events} claims={claims} resolutionLinks={resolutionLinks} showEventRecords={false} search={location.search} />
      </section>
    );
  }

  return (
    <section data-view="entity" data-canonical-id={data.canonical_entity_id}>
      <div className="breadcrumbs"><Link to={worldPathFromSearch(location.search)}>历史世界</Link><span>›</span><Link to={withHistoricalTime("/timeline", location.search)}>时间线</Link><span>›</span><span>{isPerson ? "人物" : "对象"}</span></div>
      <HistoryReturnLink fallback={<ReadingReturnBar returnLocator={returnLocator} />} />
      <p className="muted" data-test="entity-phase-note">
        {hasValidHistoryLocator
          ? "来自固定历史版本的当前段落；返回时会恢复原来的阅读位置。"
          : hasHistoryLocator
            ? "这条人物页地址缺少有效的历史段落位置，请从历史正文重新进入。"
            : "直接进入人物页；不会替你选择某个年份或历史阶段。"}
      </p>
      <header className="page-header">
        <p className="eyebrow">{isPerson ? "人物" : "对象"}</p>
        <h1>{data.display?.name ?? "未命名对象"}</h1>
        <div className="hero-meta">
          <span className="chip type">{entityKindLabel(data.display?.type)}</span>
          {data.source_count !== undefined ? <span className="chip">{data.source_count} 个来源</span> : null}
        </div>
        <p className="lede" data-test="entity-scope">{isPerson
          ? "姓名是入口；身份、经历和阶段状态只显示已发布资料能够支持的范围。"
          : "这里仅显示已发布资料能够支持的内容。"}</p>
        {hasEvidence ? <a className="primary-link" href="#evidence" data-test="entity-evidence-link">查看来源与依据</a> : null}
      </header>

      <section className="entity-reader-summary" data-test="entity-reader-summary">
        <div className="entity-reader-heading"><div><p className="eyebrow">{isPerson ? "人物概况" : "资料摘要"}</p><h2>{isPerson ? "简介" : "摘要"}</h2></div></div>
        {intro ? <p className="entity-reader-intro" data-test="entity-intro">{intro}</p> : <p className="entity-intro-empty" data-test="entity-intro-empty">{isPerson
          ? "目前没有单独的人物简介。页面只展示已发布资料支持的内容；没有专门的人物生平时，不把历史片段拼成完整传记。"
          : "目前没有单独的资料摘要。页面不会从常识补写内容。"}</p>}
      </section>

      <div className="detail-grid">
        <div className="detail-main">
          {isPerson ? <SourcePersonPanel locator={returnLocator} entityId={data.canonical_entity_id} events={events} search={location.search} /> : null}
          <EntityEvidence entityId={data.canonical_entity_id} readerPresentation={readerPresentation} reps={reps} events={events} claims={claims} resolutionLinks={resolutionLinks} showEventRecords={!isPerson} search={location.search} />
        </div>
        <aside className="detail-side">
          <HistoryPhasePanel version={version} paragraphId={paragraphId} phaseId={phaseId} entityId={data.canonical_entity_id} />
        </aside>
      </div>
    </section>
  );
}
