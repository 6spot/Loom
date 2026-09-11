import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import ReaderPresentation from "../../components/ReaderPresentation";
import ReadingTargetPicker from "../../components/reading/ReadingTargetPicker";
import { useEvent } from "../../lib/queries";
import { formatTime, readPath, readingPath } from "../../lib/routes";
import { withHistoricalTime, worldPathFromSearch } from "../../lib/historical-time";
import { ClaimsBlock, DECISION_LABEL, ErrorState, LoadingState, RawDetails, ResolutionBlock } from "../../components/shared";
import type { Participant, Representation } from "../../lib/types";
import { buildReadingUrl, readReturnToken } from "../../lib/reading-location";
import { ReadingHistoryStore, ReadingStorage } from "../../lib/reading-history";
import { fetchReadingStreams, loadReadingEventTargets } from "../../lib/reading-api";
import type { EventTarget, EventTargetPage, ReadingLocator } from "../../lib/reading-types";

function LinkedEntity({ item, sourceLabel }: { item: Participant; sourceLabel: string }) {
  const location = useLocation();
  const name = item.display?.name ?? "未命名实体";
  const type = item.display?.type ?? "entity";
  if (!item.canonical_entity_id) {
    return (
      <div className="entity-link">
        <span><strong>{name}</strong><small> · {type}</small></span>
        <span className="decision uncertain">未解析</span>
      </div>
    );
  }
  return (
    <Link
      className="entity-link"
      to={withHistoricalTime(`/entities/${encodeURIComponent(item.canonical_entity_id)}`, location.search)}
      data-test="entity-link"
    >
      <span><strong>{name}</strong><small> · {type}</small></span>
      <span className="muted">{sourceLabel}</span>
    </Link>
  );
}

function EventRepresentation({ rep }: { rep: Representation }) {
  return (
    <article className="source-card" data-source={rep.bundle}>
      <header>
        <div><div className="source-title">{rep.source?.title ?? rep.bundle}</div><div className="muted">Source representation</div></div>
        <code>{rep.bundle}:{rep.ref}</code>
      </header>
      <ClaimsBlock claims={rep.claims ?? []} />
      <RawDetails label="查看源 Event 记录" payload={rep.event ?? {}} />
      <RawDetails label="查看 Source 元数据" payload={rep.source?.record ?? {}} />
    </article>
  );
}

/** 从 sessionStorage 的 return token 恢复本站 typed locator；缺失/失效返回 null。 */
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

/**
 * 事件详情 → 连续正文入口。优先恢复阅读返回 token；没有 token 时显示目录入口，
 * 并在已知 catalog 时列出该事件的精确正文位置（current/mention 分开）。
 */
function EventReadingEntry({
  eventId,
  catalog,
  returnLocator,
}: {
  eventId: string;
  catalog: string | null;
  returnLocator: ReadingLocator | null;
}) {
  const navigate = useNavigate();
  const [catalogSha, setCatalogSha] = useState<string | null>(catalog);
  const [targets, setTargets] = useState<EventTargetPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (catalogSha || !eventId) return;
    let cancelled = false;
    fetchReadingStreams({ limit: 1 })
      .then((envelope) => {
        if (!cancelled) setCatalogSha(envelope.snapshot.catalog_sha);
      })
      .catch(() => {
        /* 无 snapshot 时仍可退回目录入口 */
      });
    return () => {
      cancelled = true;
    };
  }, [catalogSha, eventId]);

  useEffect(() => {
    if (!catalogSha) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadReadingEventTargets(eventId, { catalog: catalogSha, limit: 20 })
      .then((page) => {
        if (!cancelled) setTargets(page);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "正文位置暂时读不出来");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [catalogSha, eventId]);

  const choose = (target: EventTarget) => {
    if (!catalogSha) return;
    navigate(readingPath(target.stream_id, catalogSha, target.unit_id));
  };

  return (
    <section className="panel reading-entry" data-test="event-reading-entry">
      <div className="panel-heading"><h2>进入相关正文</h2><span className="count">连续阅读</span></div>
      {returnLocator ? (
        <Link className="primary-link" data-test="reading-return" to={buildReadingUrl(returnLocator)}>
          返回阅读
        </Link>
      ) : (
        <Link className="primary-link" data-test="reading-enter-directory" to={readPath()}>
          浏览连续阅读目录
        </Link>
      )}
      {loading ? <p className="muted" data-test="event-reading-loading">正在读取正文位置…</p> : null}
      {error ? (
        <p className="muted" data-test="event-reading-error" role="alert">{error}</p>
      ) : null}
      {targets && targets.targets.length > 0 ? (
        <ReadingTargetPicker
          mode="other"
          targets={targets.targets}
          currentCount={targets.current_count}
          mentionCount={targets.mention_count}
          onChoose={choose}
          hasMore={targets.has_more}
        />
      ) : null}
      {targets && targets.targets.length === 0 && !loading ? (
        <p className="muted" data-test="event-reading-empty">暂无已收录的正文位置。</p>
      ) : null}
    </section>
  );
}

export default function EventPage() {
  const { id } = useParams();
  const location = useLocation();
  const params = new URLSearchParams(location.search.startsWith("?") ? location.search.slice(1) : location.search);
  const catalog = params.get("catalog");
  const returnLocator = useReadingReturn(location.search);
  const event = useEvent(id, catalog);

  if (event.isPending) return <LoadingState label="事件" />;
  if (event.isError) return <ErrorState code={event.error.code} message={event.error.message} />;

  const data = event.data;
  const participants = data.participants ?? [];
  const places = data.places ?? [];
  const related = data.related_events ?? [];
  const reps = data.representations ?? [];
  const readerPresentation = data.reader_presentation ?? null;

  return (
    <section data-view="event" data-canonical-id={data.canonical_event_id}>
      <div className="breadcrumbs">
        <Link to={worldPathFromSearch(location.search)}>历史世界</Link><span>›</span>
        <Link to={withHistoricalTime("/timeline", location.search)}>时间线</Link><span>›</span><span>事件</span>
      </div>
      <EventReadingEntry
        eventId={data.canonical_event_id}
        catalog={catalog}
        returnLocator={returnLocator}
      />
      <header className="page-header">
        <p className="eyebrow">Canonical Event</p>
        <h1>{data.display?.title ?? "未命名事件"}</h1>
        <div className="hero-meta">
          {data.display?.type ? <span className="chip type">{data.display.type}</span> : null}
          <span className="chip">{formatTime(data.time ?? {})}</span>
          <span className="chip">{data.source_count ?? reps.length} 个来源</span>
        </div>
        <p className="lede">
          {readerPresentation
            ? "先显示经过 grounding 校验的现代中文 Reader Presentation；下方仍完整保留 Source representation、Claim、原始 evidence 与 Resolution。"
            : "此事件暂未生成经过 grounding 校验的现代中文 Reader Presentation，因此不会临时补写叙事；以下直接显示 source-grounded 史料与证据。"}
        </p>
        <a className="primary-link" href="#evidence" data-test="event-evidence-link">跳到史料与证据</a>
      </header>

      <ReaderPresentation presentation={readerPresentation} />

      <div className="detail-grid">
        <div className="detail-main">
          <section className="panel" id="evidence">
            <div className="panel-heading"><h2>史料与证据</h2><span className="count">{reps.length} representations</span></div>
            <div className="source-stack">{reps.map((rep, index) => <EventRepresentation key={`${rep.bundle ?? "bundle"}:${rep.ref ?? index}`} rep={rep} />)}</div>
          </section>
          <section className="panel">
            <div className="panel-heading"><h2>Resolution</h2><span className="count">跨来源判断</span></div>
            <ResolutionBlock links={data.resolution_links ?? []} targetKind="event" currentId={data.canonical_event_id} />
          </section>
        </div>
        <aside className="detail-side">
          <section className="panel">
            <div className="panel-heading"><h2>人物 / 实体</h2><span className="count">participants</span></div>
            <div className="entity-links">
              {participants.length ? participants.map((item, index) => (
                <LinkedEntity key={item.canonical_entity_id ?? index} item={item} sourceLabel={(item.source_roles ?? []).map((role) => role.role).filter(Boolean).join(" · ") || "participant"} />
              )) : <p className="muted">没有 participant 映射。</p>}
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading"><h2>地点</h2><span className="count">places</span></div>
            <div className="entity-links">{places.length ? places.map((item, index) => <LinkedEntity key={item.canonical_entity_id ?? index} item={item} sourceLabel="place" />) : <p className="muted">没有地点映射。</p>}</div>
          </section>
          <section className="panel">
            <div className="panel-heading"><h2>相关事件</h2><span className="count">related ≠ same</span></div>
            <div className="related-list">
              {related.length ? related.map((item, index) => (
                <Link
                  key={item.event?.canonical_event_id ?? index}
                  className="related-card"
                  to={withHistoricalTime(`/events/${encodeURIComponent(item.event?.canonical_event_id ?? "")}`, location.search)}
                  data-test="related-event"
                >
                  <strong>{item.event?.display?.title ?? "未命名事件"}</strong>
                  <span className="muted">{formatTime(item.event?.time ?? {})} · {DECISION_LABEL[item.type ?? ""] ?? item.type}</span>
                </Link>
              )) : <p className="muted">没有 related occurrence。</p>}
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}
