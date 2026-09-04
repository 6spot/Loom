import { Link, useParams } from "react-router-dom";
import ReaderPresentation from "../../components/ReaderPresentation";
import { useEvent } from "../../lib/queries";
import { formatTime } from "../../lib/routes";
import { ClaimsBlock, DECISION_LABEL, ErrorState, LoadingState, RawDetails, ResolutionBlock } from "../../components/shared";
import type { Participant, Representation } from "../../lib/types";

function LinkedEntity({ item, sourceLabel }: { item: Participant; sourceLabel: string }) {
  const name = item.display?.name ?? "未命名实体";
  const type = item.display?.type ?? "entity";
  if (!item.canonical_entity_id) {
    return (
      <div className="entity-link">
        <span>
          <strong>{name}</strong>
          <small> · {type}</small>
        </span>
        <span className="decision uncertain">未解析</span>
      </div>
    );
  }
  return (
    <Link className="entity-link" to={`/entities/${encodeURIComponent(item.canonical_entity_id)}`} data-test="entity-link">
      <span>
        <strong>{name}</strong>
        <small> · {type}</small>
      </span>
      <span className="muted">{sourceLabel}</span>
    </Link>
  );
}

function EventRepresentation({ rep }: { rep: Representation }) {
  return (
    <article className="source-card" data-source={rep.bundle}>
      <header>
        <div>
          <div className="source-title">{rep.source?.title ?? rep.bundle}</div>
          <div className="muted">Source representation</div>
        </div>
        <code>
          {rep.bundle}:{rep.ref}
        </code>
      </header>
      <ClaimsBlock claims={rep.claims ?? []} />
      <RawDetails label="查看源 Event 记录" payload={rep.event ?? {}} />
      <RawDetails label="查看 Source 元数据" payload={rep.source?.record ?? {}} />
    </article>
  );
}

export default function EventPage() {
  const { id } = useParams();
  const event = useEvent(id);

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
        <Link to="/timeline">时间线</Link>
        <span>›</span>
        <span>事件</span>
      </div>
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
      </header>

      <ReaderPresentation presentation={readerPresentation} />

      <div className="detail-grid">
        <div className="detail-main">
          <section className="panel">
            <div className="panel-heading">
              <h2>史料与证据</h2>
              <span className="count">{reps.length} representations</span>
            </div>
            <div className="source-stack">
              {reps.map((rep, index) => (
                <EventRepresentation key={`${rep.bundle ?? "bundle"}:${rep.ref ?? index}`} rep={rep} />
              ))}
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>Resolution</h2>
              <span className="count">跨来源判断</span>
            </div>
            <ResolutionBlock links={data.resolution_links ?? []} targetKind="event" currentId={data.canonical_event_id} />
          </section>
        </div>
        <aside className="detail-side">
          <section className="panel">
            <div className="panel-heading">
              <h2>人物 / 实体</h2>
              <span className="count">participants</span>
            </div>
            <div className="entity-links">
              {participants.length ? (
                participants.map((item, index) => (
                  <LinkedEntity
                    key={item.canonical_entity_id ?? index}
                    item={item}
                    sourceLabel={(item.source_roles ?? []).map((role) => role.role).filter(Boolean).join(" · ") || "participant"}
                  />
                ))
              ) : (
                <p className="muted">没有 participant 映射。</p>
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>地点</h2>
              <span className="count">places</span>
            </div>
            <div className="entity-links">
              {places.length ? (
                places.map((item, index) => (
                  <LinkedEntity key={item.canonical_entity_id ?? index} item={item} sourceLabel="place" />
                ))
              ) : (
                <p className="muted">没有地点映射。</p>
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>相关事件</h2>
              <span className="count">related ≠ same</span>
            </div>
            <div className="related-list">
              {related.length ? (
                related.map((item, index) => (
                  <Link
                    key={item.event?.canonical_event_id ?? index}
                    className="related-card"
                    to={`/events/${encodeURIComponent(item.event?.canonical_event_id ?? "")}`}
                    data-test="related-event"
                  >
                    <strong>{item.event?.display?.title ?? "未命名事件"}</strong>
                    <span className="muted">
                      {formatTime(item.event?.time ?? {})} · {DECISION_LABEL[item.type ?? ""] ?? item.type}
                    </span>
                  </Link>
                ))
              ) : (
                <p className="muted">没有 related occurrence。</p>
              )}
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}
