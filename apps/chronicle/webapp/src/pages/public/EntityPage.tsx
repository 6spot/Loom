import { Link, useParams } from "react-router-dom";
import { useEntity } from "../../lib/queries";
import { formatTime } from "../../lib/routes";
import { ClaimsBlock, ErrorState, LoadingState, RawDetails, ResolutionBlock } from "../../components/shared";
import type { Representation, TrajectoryEvent } from "../../lib/types";

function EntityRepresentation({ rep }: { rep: Representation }) {
  const entity = rep.entity ?? {};
  const aliases = Array.isArray(entity.aliases) && entity.aliases.length
    ? (entity.aliases as string[])
    : [];
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
      {aliases.length ? (
        <div className="chip-row">
          {aliases.map((alias) => (
            <span key={alias} className="chip">
              {alias}
            </span>
          ))}
        </div>
      ) : null}
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

export default function EntityPage() {
  const { id } = useParams();
  const entity = useEntity(id);

  if (entity.isPending) return <LoadingState label="实体" />;
  if (entity.isError) return <ErrorState code={entity.error.code} message={entity.error.message} />;

  const data = entity.data;
  const reps = data.representations ?? [];
  const events = data.events ?? [];
  const claims = data.claims ?? [];

  return (
    <section data-view="entity" data-canonical-id={data.canonical_entity_id}>
      <div className="breadcrumbs">
        <Link to="/timeline">时间线</Link>
        <span>›</span>
        <span>实体</span>
      </div>
      <header className="page-header">
        <p className="eyebrow">Canonical Entity</p>
        <h1>{data.display?.name ?? "未命名实体"}</h1>
        <div className="hero-meta">
          {data.display?.type ? <span className="chip type">{data.display.type}</span> : null}
          <span className="chip">{data.source_count ?? reps.length} 个来源</span>
          <span className="chip">{data.representation_count ?? reps.length} 条记录</span>
        </div>
        <p className="lede">Canonical UUID 只负责跨来源导航。相同名称但身份不确定的地点保持不同页面，并通过 Resolution 明确显示“不确定”。</p>
      </header>

      <div className="detail-grid">
        <div className="detail-main">
          <section className="panel">
            <div className="panel-heading">
              <h2>事件轨迹</h2>
              <span className="count">{events.length} canonical Events</span>
            </div>
            <div className="trajectory-list">
              {events.length ? (
                events.map((event) => (
                  <Link
                    key={event.canonical_event_id}
                    className="trajectory-card"
                    to={`/events/${encodeURIComponent(event.canonical_event_id)}`}
                    data-test="trajectory-event"
                  >
                    <strong>{event.display?.title ?? "未命名事件"}</strong>
                    <span className="muted">{formatTime(event.time ?? {})}</span>
                    <div className="trajectory-meta">
                      {involvementChips(event.source_involvements ?? []).map((chip) => (
                        <span key={chip} className="role-chip">
                          {chip}
                        </span>
                      ))}
                    </div>
                  </Link>
                ))
              ) : (
                <p className="muted">暂时没有关联事件。</p>
              )}
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>来源表示</h2>
              <span className="count">{reps.length} representations</span>
            </div>
            <div className="source-stack">
              {reps.map((rep, index) => (
                <EntityRepresentation key={`${rep.bundle ?? "bundle"}:${rep.ref ?? index}`} rep={rep} />
              ))}
            </div>
          </section>
        </div>
        <aside className="detail-side">
          <section className="panel">
            <div className="panel-heading">
              <h2>Resolution</h2>
              <span className="count">identity</span>
            </div>
            <ResolutionBlock links={data.resolution_links ?? []} targetKind="entity" currentId={data.canonical_entity_id} />
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>直接 Claims</h2>
              <span className="count">{claims.length}</span>
            </div>
            <ClaimsBlock claims={claims} />
          </section>
        </aside>
      </div>
    </section>
  );
}
