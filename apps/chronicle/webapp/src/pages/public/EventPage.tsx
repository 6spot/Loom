import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router-dom";
import ChapterSourceReference from "../../components/ChapterSourceReference";
import EventReadingEntry from "../../components/EventReadingEntry";
import HistoryReturnLink from "../../components/HistoryReturnLink";
export { mergeEventTargetPages } from "../../components/EventReadingEntry";
import { ErrorState, LoadingState } from "../../components/shared";
import {
  historyPath,
  historyTimeLabel,
  loadHistory,
  type HistoryEntry,
  type HistoryPublication,
} from "../../lib/history-api";
import { fetchReadingStreams, loadReadingEventPreview } from "../../lib/reading-api";
import { readReturnToken } from "../../lib/reading-location";
import { ReadingHistoryStore, ReadingStorage } from "../../lib/reading-history";
import type { EventPreview, EventPreviewSource, ReadingLocator } from "../../lib/reading-types";
import { describeTimeDivergence, sourceTimeText } from "../../components/reading/ReadingEventPreview";

/** From sessionStorage restore the typed source-reading return locator. */
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

function PublishedEventLocations({
  eventId,
  publication,
  pending,
  failed,
}: {
  eventId: string;
  publication: HistoryPublication | null | undefined;
  pending: boolean;
  failed: boolean;
}) {
  if (pending) {
    return (
      <section className="panel" data-test="event-published-locations">
        <div className="panel-heading"><h2>已发布历史正文</h2></div>
        <p className="muted" role="status">正在核对当前发布版本中的正文位置…</p>
      </section>
    );
  }

  const locations = publication?.entry_points.filter((entry) => entry.event_id === eventId) ?? [];
  return (
    <section className="panel" data-test="event-published-locations">
      <div className="panel-heading">
        <h2>已发布历史正文</h2>
        <span className="count">{publication ? publication.title : "当前版本"}</span>
      </div>
      {failed || locations.length === 0 ? (
        <p className="muted" data-test="event-no-published-location">
          暂无对应历史正文；以下仅展示已发布的来源定位，不根据年份或首段猜测正文位置。
        </p>
      ) : (
        <>
          <p className="muted">{locations.length > 1 ? "这一事件在当前版本有多个正文位置，请选择：" : "已核对到当前发布版本的正文位置："}</p>
          <div className="search-event-location-list">
            {locations.map((entry: HistoryEntry) => (
              <Link
                className="public-text-button"
                key={entry.paragraph_id}
                to={historyPath({ version: publication!.version, paragraph_id: entry.paragraph_id })}
                data-test="event-published-location"
              >
                {historyTimeLabel(entry)} · {entry.label}
              </Link>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function SourceEvidence({
  source,
  onOpen,
}: {
  source: EventPreviewSource;
  onOpen: (reference: { publicationId: string; anchorId: string; label: string }) => void;
}) {
  const originalEntry = source.original_entry;
  return (
    <article className="source-card" data-test="event-source-evidence" data-source={source.source_title}>
      <header>
        <div>
          <div className="source-title">{source.source_title}</div>
          <div className="muted">已发布来源记录</div>
        </div>
        {source.publication_id ? <code>{source.publication_id}</code> : null}
      </header>
      <p className="muted">原始时间记载：{sourceTimeText(source)}</p>
      {source.excerpt ? (
        <blockquote className="claim" data-test="event-source-excerpt">
          {source.excerpt}{source.excerpt_more ? "…" : ""}
        </blockquote>
      ) : (
        <p className="muted" data-test="event-source-no-excerpt">暂无已发布译文摘录。</p>
      )}
      {originalEntry ? (
        <button
          type="button"
          className="public-text-button"
          data-test="event-source-original-entry"
          onClick={() => onOpen({
            publicationId: originalEntry.publication_id,
            anchorId: originalEntry.anchor_id,
            label: `${source.source_title} · 原文入口`,
          })}
        >
          查看该来源原文入口
        </button>
      ) : (
        <p className="muted" data-test="event-source-no-original-entry">该来源暂未发布可展开的原文入口。</p>
      )}
    </article>
  );
}

function EventSources({ preview }: { preview: EventPreview }) {
  const [source, setSource] = useState<{ publicationId: string; anchorId: string; label: string } | null>(null);
  const divergence = describeTimeDivergence(preview.sources);
  return (
    <section className="panel" id="evidence" data-test="event-source-panel">
      <div className="panel-heading">
        <h2>已发布来源</h2>
        <span className="count">共 {preview.source_count} 个来源{preview.has_more_sources ? "，仅列部分" : ""}</span>
      </div>
      <p className="muted">这里保留来源归属、原始时间和可展开的原文依据；来源摘录不是历史正文的替代品。</p>
      {divergence ? <p className="muted" data-test="event-source-time-divergence" role="note">{divergence}</p> : null}
      {preview.sources.length ? (
        <div className="source-stack">
          {preview.sources.map((item, index) => <SourceEvidence key={`${item.source_title}:${index}`} source={item} onOpen={setSource} />)}
        </div>
      ) : (
        <p className="muted" data-test="event-no-sources">当前发布版本没有可展示的来源摘录。</p>
      )}
      {source ? (
        <ChapterSourceReference
          key={`${source.publicationId}:${source.anchorId}`}
          publicationId={source.publicationId}
          anchorId={source.anchorId}
          anchorLabel={source.label}
          onClose={() => setSource(null)}
        />
      ) : null}
    </section>
  );
}

export default function EventPage() {
  const { id } = useParams();
  const location = useLocation();
  const params = new URLSearchParams(location.search.startsWith("?") ? location.search.slice(1) : location.search);
  const requestedCatalog = params.get("catalog");
  const requestedVersion = params.get("version");
  const returnLocator = useReadingReturn(location.search);
  const catalog = useQuery({
    queryKey: ["reading", "event-catalog", requestedCatalog ?? "latest"],
    queryFn: async () => requestedCatalog ?? (await fetchReadingStreams({ limit: 1 })).snapshot.catalog_sha,
    enabled: Boolean(id),
    staleTime: Infinity,
    retry: 1,
  });
  const catalogSha = catalog.data ?? requestedCatalog;
  const preview = useQuery<EventPreview, Error>({
    queryKey: ["reading", "event-page-preview", id ?? "", catalogSha ?? null],
    queryFn: () => loadReadingEventPreview(id!, catalogSha!),
    enabled: Boolean(id && catalogSha),
    staleTime: Infinity,
    retry: 1,
  });
  const history = useQuery<HistoryPublication | null, Error>({
    queryKey: ["history", "event-page-locations", requestedVersion ?? "latest"],
    queryFn: () => loadHistory(requestedVersion),
    enabled: Boolean(id),
    staleTime: 30_000,
    retry: 1,
  });

  if (!id) return <LoadingState label="事件" />;
  if (catalog.isError) return <ErrorState code="reading_catalog_unavailable" message={catalog.error.message} />;
  if (preview.isPending || (catalog.isPending && !catalogSha)) return <LoadingState label="事件来源" />;
  if (preview.isError) return <ErrorState code="event_not_found" message={preview.error.message} />;

  const data = preview.data;
  return (
    <section data-view="event" data-canonical-id={data.event_id}>
      <div className="breadcrumbs"><Link to="/history">历史正文</Link><span>›</span><span>事件来源定位</span></div>
      <HistoryReturnLink fallback={<EventReadingEntry
        key={`${data.event_id}:${catalogSha ?? "latest"}`}
        eventId={data.event_id}
        catalog={catalogSha}
        returnLocator={returnLocator}
      />} />
      <header className="page-header">
        <p className="eyebrow">事件来源定位</p>
        <h1>{data.name || "未命名事件"}</h1>
        <p className="lede">此页只连接当前发布版本的历史正文和已发布来源定位；没有经过核对的正文映射时，不会补写百科式事件叙事。</p>
        <a className="primary-link" href="#evidence" data-test="event-evidence-link">查看已发布来源</a>
      </header>
      <PublishedEventLocations
        eventId={data.event_id}
        publication={history.data}
        pending={history.isPending}
        failed={history.isError}
      />
      <EventSources preview={data} />
    </section>
  );
}
