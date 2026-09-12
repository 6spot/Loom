// C2-R2-T15 连续阅读页（`/read/{stream_id}?catalog=&at=`）。
//
// 组合 T09 typed client、T10 正文窗口、T11 侧边轴、T12 单一控制器、T13 事件
// 预览与 T14 当前片段面板，成为真实公开阅读流程。布局与交互合同见
// reading-experience.md：正文优先，桌面三列 / 平板两列 / 窄屏单栏；compact bar
// 只显示 active unit 的叙事时间，绝不用全局 HistoricalTimeBar 覆盖阅读返回。
//
// 本页不重写分组/定位/关联算法，也不修改 World 时间或 Runtime Timeline；URL 只
// 由校验过的 stream/catalog/unit 字段构建。

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import ChapterSourceReference from "../../components/ChapterSourceReference";
import PublicDialog from "../../components/PublicDialog";
import ReadingNearbyEvents from "../../components/reading/ReadingNearbyEvents";
import ReadingContextPanel from "../../components/reading/ReadingContextPanel";
import ReadingEventTrigger from "../../components/reading/ReadingEventTrigger";
import ReadingTimeAxis from "../../components/reading/ReadingTimeAxis";
import ReadingWindow, { type ReadingWindowError } from "../../components/reading/ReadingWindow";
import type { ReadingEventSlot } from "../../components/reading/ReadingContent";
import { useReadingPosition, type ReadingUnitSnapshot } from "../../hooks/useReadingPosition";
import {
  fetchReadingStreams,
  fetchReadingStreamDetail,
  fetchReadingStreamGroups,
  fetchReadingStreamLocate,
  fetchReadingStreamUnits,
  ReadingApiError,
  unitLocator,
  loadReadingEventPreview,
  loadReadingEventTargets,
  type ReadingDirectoryEnvelope,
  type ReadingStreamDetailPage,
} from "../../lib/reading-api";
import { READING_RETURN_PARAM } from "../../lib/reading-location";
import {
  type ReadingDirection,
  type ReadingLocator,
  type ReadingNavigationAction,
  type ReadingUnit,
  type StreamPage,
  type TimeGroup,
  type TimeObservation,
} from "../../lib/reading-types";
import { mergeReadingUnitPages, readingAdjacentPages } from "../../lib/reading-window";
import { isSupportedHistoricalYear } from "../../lib/historical-time";
import { readPath, readingPath } from "../../lib/routes";
import "../../styles/reading-layout.css";

export interface ReadingPageClient {
  fetchDirectory: typeof fetchReadingStreams;
  fetchStreamDetail: typeof fetchReadingStreamDetail;
  fetchStreamUnits: typeof fetchReadingStreamUnits;
  fetchStreamGroups: typeof fetchReadingStreamGroups;
  fetchStreamLocate: typeof fetchReadingStreamLocate;
  loadEventPreview: typeof loadReadingEventPreview;
  loadEventTargets: typeof loadReadingEventTargets;
}

const DEFAULT_CLIENT: ReadingPageClient = {
  fetchDirectory: fetchReadingStreams,
  fetchStreamDetail: fetchReadingStreamDetail,
  fetchStreamUnits: fetchReadingStreamUnits,
  fetchStreamGroups: fetchReadingStreamGroups,
  fetchStreamLocate: fetchReadingStreamLocate,
  loadEventPreview: loadReadingEventPreview,
  loadEventTargets: loadReadingEventTargets,
};

export interface ReadingPageProps {
  streamId?: string;
  search?: string;
  client?: ReadingPageClient;
}

function errorMessage(error: unknown): string {
  if (error instanceof ReadingApiError || error instanceof Error) return error.message;
  return String(error);
}

function useNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(max-width: 1199px)");
    const update = () => setNarrow(media.matches);
    update();
    media.addEventListener?.("change", update);
    return () => media.removeEventListener?.("change", update);
  }, []);
  return narrow;
}

/** 服务端编译的叙事时间标签；unknown 原样表达，不改写成默认年份。 */
export function narrativeTimeLabel(time: {
  readonly precision?: string;
  readonly period_key?: string;
  readonly year_label?: string | null;
  readonly period_label?: string;
} | null | undefined): string {
  if (!time) return "时间未明确";
  if (time.precision === "unknown" || time.period_key === "unknown") return "时间未明确";
  const parts = [time.year_label, time.period_label].filter(
    (part): part is string => Boolean(part && part.trim()),
  );
  return parts.length > 0 ? parts.join(" · ") : "时间未明确";
}

/** 仅当本段有唯一、已换算的公历观察年时才提供显式时间线入口。 */
export function explicitTimelineYear(
  observations: readonly TimeObservation[] | null | undefined,
): number | null {
  const years = new Set<number>();
  for (const observation of observations ?? []) {
    const normalized = observation.normalized;
    if (!normalized) continue;
    if (normalized.calendar && normalized.calendar !== "proleptic_gregorian") continue;
    if (normalized.approximate === true) continue;
    if (normalized.conversion_status === "partial" || normalized.conversion_status === "unresolved") {
      continue;
    }
    if (typeof normalized.year === "number" && Number.isInteger(normalized.year)) {
      years.add(normalized.year);
    }
  }
  return years.size === 1 ? [...years][0] : null;
}

function safeLocator(streamId: string, catalog: string, unitId: string): ReadingLocator | null {
  try {
    return unitLocator(streamId, catalog, unitId);
  } catch {
    return null;
  }
}

function ReadingPageError({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="rpage-error" data-test="reading-page-error" role="alert">
      <p className="rpage-eyebrow">连续阅读</p>
      <h1>{title}</h1>
      <p>{detail}</p>
      <a className="rpage-error-link" href={readPath()} data-test="reading-page-back-to-directory">
        返回连续阅读目录
      </a>
    </section>
  );
}

/**
 * `/read/{stream_id}` 生产入口：解析/固定 snapshot 后交给 ReadingSurface。
 * catalog 缺失时只解析一次最新 publication_sequence 并把 URL 固定下来。
 */
export default function ReadingPage({ streamId: streamIdProp, search: searchProp, client }: ReadingPageProps) {
  const params = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const streamId = streamIdProp ?? params.streamId ?? "";
  const search = searchProp ?? location.search;
  const activeClient = client ?? DEFAULT_CLIENT;

  const incoming = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const catalogParam = incoming.get("catalog");
  const atParam = incoming.get("at");

  const [resolvedCatalog, setResolvedCatalog] = useState<string | null>(null);
  const [resolutionError, setResolutionError] = useState<string | null>(null);

  useEffect(() => {
    if (catalogParam || resolvedCatalog || !streamId) return;
    let cancelled = false;
    setResolutionError(null);
    activeClient
      .fetchDirectory({ limit: 20 })
      .then((envelope: ReadingDirectoryEnvelope) => {
        if (cancelled) return;
        const sha = envelope.snapshot.catalog_sha;
        setResolvedCatalog(sha);
        if (typeof window !== "undefined") {
          window.history.replaceState(window.history.state, "", readingPath(streamId, sha, atParam));
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) setResolutionError(errorMessage(error));
      });
    return () => {
      cancelled = true;
    };
  }, [catalogParam, resolvedCatalog, streamId, atParam, activeClient]);

  if (!streamId) return <ReadingPageError title="缺少正文标识" detail="URL 没有 stream_id。" />;
  if (resolutionError) {
    return <ReadingPageError title="无法解析探索快照" detail={resolutionError} />;
  }
  const catalog = catalogParam ?? resolvedCatalog;
  if (!catalog) {
    return (
      <section className="rpage-resolving" data-test="reading-page-resolving" role="status">
        <p className="rpage-eyebrow">连续阅读</p>
        <p>正在解析探索快照…</p>
      </section>
    );
  }

  const openEvent = (eventId: string, token: string | null) => {
    const query = new URLSearchParams();
    query.set("catalog", catalog);
    if (token) query.set(READING_RETURN_PARAM, token);
    navigate(`/events/${encodeURIComponent(eventId)}?${query.toString()}`);
  };
  const openEntity = (entityId: string, token: string | null) => {
    const query = new URLSearchParams();
    query.set("catalog", catalog);
    if (token) query.set(READING_RETURN_PARAM, token);
    navigate(`/entities/${encodeURIComponent(entityId)}?${query.toString()}`);
  };

  return (
    <ReadingSurface
      key={`${streamId}:${catalog}`}
      streamId={streamId}
      catalog={catalog}
      client={activeClient}
      onOpenEvent={openEvent}
      onOpenEntity={openEntity}
    />
  );
}

interface ReadingSurfaceProps {
  streamId: string;
  catalog: string;
  client: ReadingPageClient;
  onOpenEvent: (eventId: string, token: string | null) => void;
  onOpenEntity: (entityId: string, token: string | null) => void;
}

function ReadingSurface({ streamId, catalog, client, onOpenEvent, onOpenEntity }: ReadingSurfaceProps) {
  const narrow = useNarrowViewport();
  const [currentStream, setCurrentStream] = useState(streamId);
  const [pages, setPages] = useState<StreamPage[]>([]);
  const [pendingUnitId, setPendingUnitId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReadingStreamDetailPage | null>(null);
  const [groups, setGroups] = useState<readonly TimeGroup[]>([]);
  const [groupCursor, setGroupCursor] = useState<string | null>(null);
  const [hasMoreGroups, setHasMoreGroups] = useState(false);
  const [loadingGroups, setLoadingGroups] = useState(false);
  const [loadingDirection, setLoadingDirection] = useState<ReadingDirection | null>(null);
  const [windowError, setWindowError] = useState<ReadingWindowError | null>(null);
  const [sourcePanel, setSourcePanel] = useState<{ publicationId: string; anchorId: string; label: string } | null>(null);
  const [toolsUnit, setToolsUnit] = useState<ReadingUnit | null>(null);

  const chromeRef = useRef<HTMLDivElement | null>(null);
  const [chromeHeight, setChromeHeight] = useState(0);

  const unitByIdRef = useRef<Map<string, ReadingUnit>>(new Map());
  const currentStreamRef = useRef(streamId);
  const loadingDirectionsRef = useRef<Record<ReadingDirection, boolean>>({ previous: false, next: false });

  const units = useMemo(() => mergeReadingUnitPages(pages), [pages]);
  useEffect(() => {
    unitByIdRef.current = new Map(units.map((unit) => [unit.unit_id, unit]));
  }, [units]);

  const addPage = useCallback((page: StreamPage) => {
    if (!page || !Array.isArray(page.units) || page.units.length === 0) return;
    setPages((previous) => {
      const existing = new Set(previous.flatMap((item) => item.units.map((unit) => unit.unit_id)));
      if (page.units.every((unit) => existing.has(unit.unit_id))) return previous;
      return [...previous, page];
    });
  }, []);

  // 章目录 / start locator：按当前 stream 缓存；跨来源切换时失效。
  const detailRef = useRef<{ stream: string; page: ReadingStreamDetailPage } | null>(null);
  const loadDetail = useCallback(
    async (stream: string): Promise<ReadingStreamDetailPage> => {
      if (detailRef.current?.stream === stream) return detailRef.current.page;
      const envelope = await client.fetchStreamDetail(stream, { catalog });
      detailRef.current = { stream, page: envelope.page };
      setDetail(envelope.page);
      return envelope.page;
    },
    [client, catalog],
  );

  useEffect(() => {
    void loadDetail(currentStream).catch(() => {
      /* 章标题缺失不影响正文；定位错误由 controller 显式报告 */
    });
  }, [loadDetail, currentStream]);

  /**
   * 精确 locate。cross-source：locator 指向另一个 stream 时切换当前来源，清空旧
   * stream 的正文/轴/详情，不能把两个 source 的 ordinal 混排成一段连续正文。
   */
  const locate = useCallback(
    async (locator: ReadingLocator, signal?: AbortSignal) => {
      if (signal?.aborted) return null;
      // Mount the destination before waitForDom; active still belongs to the
      // old location until the controller completes or cancels navigation.
      setPendingUnitId(locator.unit_id);
      const stream = locator.stream_id;
      if (stream !== currentStreamRef.current) {
        currentStreamRef.current = stream;
        setCurrentStream(stream);
        setPages([]);
        setGroups([]);
        setGroupCursor(null);
        setHasMoreGroups(false);
        detailRef.current = null;
      }
      const envelope = await client.fetchStreamLocate(stream, {
        catalog: locator.catalog_sha,
        unitId: locator.unit_id,
        limit: 20,
      }, { signal });
      if (signal?.aborted) return null;
      addPage(envelope.page);
      return { locator, unitIds: envelope.page.units.map((unit) => unit.unit_id) };
    },
    [client, addPage],
  );

  const resolveStart = useCallback(async () => {
    const page = await loadDetail(currentStreamRef.current);
    return page.start_locator;
  }, [loadDetail]);

  const getUnit = useCallback((unitId: string): ReadingUnitSnapshot | null => {
    const unit = unitByIdRef.current.get(unitId);
    if (!unit) return null;
    return {
      unitId: unit.unit_id,
      ordinal: unit.ordinal,
      narrativeTime: unit.narrative_time,
      contextEntities: unit.context_entities,
    };
  }, []);

  const controller = useReadingPosition({
    getUnit,
    locate,
    resolveStart,
    unitSelector: '[data-test="reading-unit"]',
    headerHeight: chromeHeight,
    preserveLayoutPosition: true,
    getWindowEdges: (unitId) => {
      const edges = readingAdjacentPages(pages, unitId);
      return { hasPrevious: Boolean(edges.previous?.has_previous), hasNext: Boolean(edges.next?.has_next) };
    },
  });

  useLayoutEffect(() => {
    controller.notifyLayoutChange();
  }, [pages, loadingDirection, windowError, chromeHeight, controller.notifyLayoutChange]);

  useEffect(() => {
    if (pendingUnitId && (controller.navigationState === "interrupted" ||
      (controller.navigationState === "idle" && (controller.activeUnitId === pendingUnitId || controller.issue)))) {
      setPendingUnitId(null);
    }
  }, [pendingUnitId, controller.navigationState, controller.activeUnitId, controller.issue]);

  // 时间轴区段：按阅读顺序分页加载，不在浏览器重新归组。切换来源时重新取。
  useEffect(() => {
    let cancelled = false;
    setLoadingGroups(true);
    client
      .fetchStreamGroups(currentStream, { catalog, limit: 50 })
      .then((envelope) => {
        if (cancelled) return;
        setGroups(envelope.page.groups);
        setGroupCursor(envelope.page.next_cursor);
        setHasMoreGroups(envelope.page.has_next);
      })
      .catch(() => {
        /* 轴载入失败保留正文；用户可重试显式加载入口 */
      })
      .finally(() => {
        if (!cancelled) setLoadingGroups(false);
      });
    return () => {
      cancelled = true;
    };
  }, [client, currentStream, catalog]);

  const loadGroups = useCallback(() => {
    if (!groupCursor || loadingGroups) return;
    setLoadingGroups(true);
    client
      .fetchStreamGroups(currentStream, { catalog, cursor: groupCursor, limit: 50 })
      .then((envelope) => {
        setGroups((previous) => {
          const seen = new Set(previous.map((group) => group.group_id));
          const merged = [...previous];
          for (const group of envelope.page.groups ?? []) {
            if (!group || seen.has(group.group_id)) continue;
            seen.add(group.group_id);
            merged.push(group);
          }
          return merged;
        });
        setGroupCursor(envelope.page.next_cursor);
        setHasMoreGroups(envelope.page.has_next);
      })
      .catch(() => {
        /* 保留已取得区段，用户可再点 */
      })
      .finally(() => setLoadingGroups(false));
  }, [client, currentStream, catalog, groupCursor, loadingGroups]);

  const requestPage = useCallback(
    (direction: ReadingDirection) => {
      if (loadingDirectionsRef.current[direction]) return;
      const edge = readingAdjacentPages(pages, controller.activeUnitId)[direction];
      const cursor = direction === "next" ? edge?.next_cursor : edge?.prev_cursor;
      if (!cursor) return;
      loadingDirectionsRef.current[direction] = true;
      setLoadingDirection(direction);
      setWindowError(null);
      client
        .fetchStreamUnits(currentStream, {
          catalog,
          cursor,
          direction: direction === "next" ? "forward" : "backward",
          limit: 20,
        })
        .then((envelope) => addPage(envelope.page))
        .catch((error: unknown) => setWindowError({ message: errorMessage(error), direction }))
        .finally(() => {
          loadingDirectionsRef.current[direction] = false;
          if (!loadingDirectionsRef.current.previous && !loadingDirectionsRef.current.next) {
            setLoadingDirection(null);
          }
        });
    },
    [client, currentStream, catalog, addPage, pages, controller.activeUnitId],
  );

  const handleNavigation = useCallback(
    (action: ReadingNavigationAction) => {
      if (action.kind === "event" && action.event_id) {
        const target = controller.rememberReturnTarget();
        onOpenEvent(action.event_id, target?.token ?? null);
        return;
      }
      controller.navigate(action);
    },
    [controller, onOpenEvent],
  );

  const renderEvent = useCallback(
    (slot: ReadingEventSlot) => (
      <ReadingEventTrigger
        segment={slot.segment}
        catalogSha={catalog}
        locator={safeLocator(currentStream, catalog, slot.unit.unit_id)}
        loadPreview={(eventId) => client.loadEventPreview(eventId, catalog)}
        loadTargets={(eventId, cursor) => client.loadEventTargets(eventId, { catalog, cursor })}
        onNavigate={handleNavigation}
      />
    ),
    [client, currentStream, catalog, handleNavigation],
  );

  const chapterTitles = useMemo(() => {
    const map: Record<string, string | null> = {};
    for (const chapter of detail?.chapters ?? []) {
      if (chapter.chapter_id) map[chapter.chapter_id] = chapter.title ?? null;
    }
    return map;
  }, [detail]);

  // compact bar 固定在全站 header 下方，其底部偏移进入参考线计算。
  useEffect(() => {
    const bar = chromeRef.current;
    if (!bar) return;
    const header = document.querySelector<HTMLElement>(".site-header");
    const measure = () => {
      const headerHeight = header?.getBoundingClientRect().height ?? 0;
      document.documentElement.style.setProperty("--rpage-chrome-top", `${headerHeight}px`);
      setChromeHeight(headerHeight + bar.getBoundingClientRect().height);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    if (header) observer.observe(header);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  const activeGroupId = controller.activeUnitId
    ? unitByIdRef.current.get(controller.activeUnitId)?.group_id ?? null
    : null;

  const narrativeTime = controller.narrativeTime;
  const timelineYear = explicitTimelineYear(narrativeTime?.observations);
  const timelineHref =
    timelineYear !== null && isSupportedHistoricalYear(timelineYear)
      ? `/timeline?year=${timelineYear}`
      : null;

  const activeUnit = controller.activeUnitId ? unitByIdRef.current.get(controller.activeUnitId) : undefined;
  const issue = controller.issue;

  const axis = (
    <ReadingTimeAxis
      groups={groups}
      activeGroup={activeGroupId}
      onNavigate={(locator) => controller.navigate({ kind: "axis", locator })}
      onLoadGroups={loadGroups}
      hasMoreGroups={hasMoreGroups}
      loadingGroups={loadingGroups}
    />
  );

  const contextPanel = (
    <ReadingContextPanel
      entities={controller.contextEntities}
      variant={narrow ? "panel" : "column"}
      unitId={controller.activeUnitId ?? undefined}
      onViewEntity={(item) => {
        if (!item.canonicalId) return;
        const target = controller.rememberReturnTarget();
        onOpenEntity(item.canonicalId, target?.token ?? null);
      }}
      onViewSource={(_item, anchorId) => {
        if (!activeUnit) return;
        setSourcePanel({
          publicationId: activeUnit.publication_id,
          anchorId,
          label: `${activeUnit.chapter_id} · 原文`,
        });
      }}
    >
      {(close) => <ReadingNearbyEvents units={units} activeOrdinal={controller.activeOrdinal ?? 0}
        onNavigate={(locator) => { close(); controller.navigate({ kind: "locate", locator }); }} />}
    </ReadingContextPanel>
  );

  const hasContent = units.length > 0;
  return (
    <section className="rpage" data-test="reading-page" data-catalog={catalog} data-stream={currentStream}
      data-navigation-state={controller.navigationState}>
      <div className="rpage-compact" data-test="reading-compact-bar" ref={chromeRef}>
        <span className="rpage-compact-time" data-test="reading-compact-time">
          {narrativeTimeLabel(narrativeTime)}
        </span>
        <div className="rpage-tools">
          {narrow ? contextPanel : null}
          <button type="button" className="public-text-button" data-test="reading-tools-open"
            aria-haspopup="dialog" disabled={!activeUnit} onClick={() => setToolsUnit(activeUnit ?? null)}>阅读资料</button>
        </div>
      </div>

      {issue ? (
        <div className="rpage-issue" data-test="reading-issue" role="alert">
          <p className="rpage-eyebrow">{issue.code}</p>
          <p>{issue.detail}</p>
          <a className="rpage-error-link" href={readingPath(currentStream, catalog)} data-test="reading-reset">
            从正文开头重新进入
          </a>
        </div>
      ) : !hasContent && controller.navigationState !== "idle" ? (
        <p className="rpage-loading" data-test="reading-page-loading" role="status">
          正在定位正文…
        </p>
      ) : null}

      <div className="rpage-grid" data-narrow={narrow ? "true" : "false"}>
        <div className="rpage-axis-column" data-test="reading-axis-column">
          {axis}
        </div>
        <div className="rpage-main" data-test="reading-main" aria-label="历史正文">
          <ReadingWindow
            pages={pages}
            activeUnitId={controller.activeUnitId}
            pinnedUnitIds={pendingUnitId ? [pendingUnitId] : []}
            chapterTitles={chapterTitles}
            showChapterHeadings={false}
            showSources={false}
            loadingDirection={loadingDirection}
            error={windowError}
            callbacks={{ requestPage, onRetry: () => requestPage(windowError?.direction ?? "next") }}
            renderEvent={renderEvent}
            onUnitReady={controller.notifyLayoutChange}
            onUnitMeasured={controller.notifyLayoutChange}
          />
        </div>
        {!narrow ? (
          <div className="rpage-context-column" data-test="reading-context-column">
            {contextPanel}
          </div>
        ) : null}
      </div>

      {sourcePanel || toolsUnit ? <PublicDialog title={sourcePanel ? "原文依据" : "阅读资料"}
        onClose={() => { setSourcePanel(null); setToolsUnit(null); }}>
        {sourcePanel ? <div data-test="reading-page-source">
          <ChapterSourceReference
            key={`${sourcePanel.publicationId}:${sourcePanel.anchorId}`}
            publicationId={sourcePanel.publicationId}
            anchorId={sourcePanel.anchorId}
            anchorLabel={sourcePanel.label}
            onClose={() => { setSourcePanel(null); setToolsUnit(null); }}
          />
        </div> : toolsUnit ? <div className="reading-tool-sources">
          <p>{chapterTitles[toolsUnit.chapter_id] ?? "本段史料"}</p>
          {toolsUnit.source_anchor_ids.map((anchorId, index) => <button type="button"
            className="public-text-button" data-test="reading-tool-source" key={anchorId}
            onClick={() => setSourcePanel({ publicationId: toolsUnit.publication_id, anchorId, label: "本段原文" })}>
            查看原文依据{toolsUnit.source_anchor_ids.length > 1 ? ` ${index + 1}` : ""}
          </button>)}
          {toolsUnit.source_anchor_ids.length === 0 ? <p>这一段尚未附上原文依据。</p> : null}
          {timelineHref ? <a className="public-text-button" data-test="reading-compact-timeline" href={timelineHref}>查看这个时刻的其他事件</a> : null}
        </div> : null}
      </PublicDialog> : null}
    </section>
  );
}
