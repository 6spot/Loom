import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import PublicDialog from "../../components/PublicDialog";
import ChapterSourceReference from "../../components/ChapterSourceReference";
import ReadingContextPanel from "../../components/reading/ReadingContextPanel";
import { useReadingPosition } from "../../hooks/useReadingPosition";
import { useHistoryPersonStateContext } from "../../hooks/usePersonStateContext";
import { historyPath, historyPositionKey, historyTime, historyTimeLabel, HISTORY_POSITION_STRATEGY,
  loadHistory, loadHistoryPage, loadHistoryConclusion,
  type HistoryPublication, type HistoryEntity, type HistoryParagraph, type HistoryPage as HistoryPageData,
  type HistoryEntry } from "../../lib/history-api";
import type { ContextEntityView } from "../../lib/reading-types";
import "../../styles/reading-layout.css";
import "../../styles/history.css";

const RELATIONS: Record<string, string> = { support: "支持", supplement: "补充", contradict: "不同说法", background: "背景", incomparable: "暂不可比较" };
const SOURCE_RELATIONS: Record<string, string> = { same_work: "同一著作", quotes: "转引", dependent: "存在传承依赖", independent: "独立来源", unknown: "传承关系未定" };

/**
 * Phase locator + loading state for the active composite paragraph. It is the
 * only place the main reading claims a phase: switching paragraphs shows the
 * new phase and its loading state immediately, never the previous one.
 */
function PhaseStage({ status, phaseId, count }: { status: "loading" | "ready" | "empty"; phaseId: string | null; count: number }) {
  if (status === "loading") {
    return <p className="pstate-loading" data-test="history-phase-status" data-status="loading" role="status">正在载入本段人物与地点资料…</p>;
  }
  return <p className="pstate-phase" data-test="history-phase-status" data-status={status} data-phase-id={phaseId ?? ""} data-entity-count={count}>
    {phaseId ? `阶段 ${phaseId}` : "阶段未标明"}
    {status === "empty" ? " · 本段暂无收录人物或地点" : ""}
  </p>;
}

function Conclusion({ version, id }: { version: string; id: string }) {
  const result = useQuery({ queryKey: ["history", version, "conclusion", id], queryFn: () => loadHistoryConclusion(version, id), staleTime: Infinity });
  const [source, setSource] = useState<{ publicationId: string; anchorId: string } | null>(null);
  if (result.isPending) return <p role="status">正在载入依据…</p>;
  if (result.isError) return <div role="alert"><p>依据暂时无法载入。</p><button onClick={() => void result.refetch()}>重试</button></div>;
  const fact = result.data.conclusion;
  return <div className="history-evidence" data-test="history-evidence">
    <p className="history-evidence-question">{fact.question}</p>
    <p>{fact.text}</p><p className="history-evidence-reason">{fact.certainty === "clear" ? "● 明确记载" : "○ 存疑"} · {fact.reason}</p>
    {fact.evidence.map((item) => <section key={item.id}>
      <p className="history-evidence-label">{item.source_title} · {RELATIONS[item.relation]} · {item.attribution}</p>
      <blockquote>{item.quote}</blockquote><p>{item.note}</p>
      <button type="button" className="public-text-button" onClick={() => setSource({ publicationId: item.publication_id, anchorId: item.anchor_id })}>查看原文前后文</button>
    </section>)}
    {result.data.source_relations.map((relation, index) => <p className="history-evidence-reason" key={index}>{SOURCE_RELATIONS[relation.relation] ?? relation.relation}：{relation.reason}</p>)}
    {source ? <ChapterSourceReference key={`${source.publicationId}:${source.anchorId}`} publicationId={source.publicationId} anchorId={source.anchorId} anchorLabel="原文前后文" onClose={() => setSource(null)} /> : null}
  </div>;
}

function EventWord({ text, entry, jump }: { text: string; entry: HistoryEntry; jump: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const timeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => () => { if (timeout.current) clearTimeout(timeout.current); }, []);
  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      // Hover need not move keyboard focus. Return focus only when it is in
      // this preview, then close after onFocus so the preview cannot reopen.
      if (trigger.current?.parentElement?.contains(document.activeElement)) trigger.current.focus({ preventScroll: true });
      setOpen(false);
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [open]);
  const show = () => { if (timeout.current) clearTimeout(timeout.current); setOpen(true); };
  const hide = () => { timeout.current = setTimeout(() => setOpen(false), 150); };
  return <span className="history-event" onMouseEnter={show} onMouseLeave={hide}
    onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
    <button type="button" ref={trigger} className="history-event-word" onFocus={show} onClick={show} aria-expanded={open}>{text}</button>
    {open ? <span className="history-event-preview" role="group" aria-label={`${entry.label}阅读位置`}>
      <strong>{entry.label}</strong><small>{historyTimeLabel(entry)}</small>
      <span>{entry.excerpt}</span><button type="button" className="public-text-button" onClick={() => { setOpen(false); jump(entry.paragraph_id); }}>读到这里</button>
    </span> : null}
  </span>;
}

export default function HistoryPage() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const version = params.get("version");
  const valid = !location.search || HISTORY_POSITION_STRATEGY.parse(`/history${location.search}`).ok;
  const query = useQuery({ queryKey: ["history", "directory", version ?? "latest"], queryFn: () => loadHistory(version), enabled: valid, staleTime: Infinity, retry: 1 });
  if (!valid) return <div role="alert"><p>这个历史阅读地址无效，请重新选择入口。</p><Link to="/">返回首页</Link></div>;
  if (query.isPending) return <p className="home-status" role="status">正在载入历史正文…</p>;
  if (query.isError) return <div className="home-status" role="alert"><p>这份历史正文暂时无法读取，或该版本尚未发布。</p><button className="public-text-button" onClick={() => void query.refetch()}>重试</button><Link to="/">返回首页</Link></div>;
  if (!query.data) return <p className="home-status">历史正文正在整理，发布后可以从这里连续阅读。</p>;
  if (!version) return <Navigate replace to={historyPath({ version: query.data.version, paragraph_id: query.data.first_paragraph_id })} />;
  return <PinnedHistory key={query.data.version} publication={query.data} />;
}

function PinnedHistory({ publication: pub }: { publication: HistoryPublication }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [pages, setPages] = useState<HistoryPageData[]>([]);
  const pagesRef = useRef(pages); pagesRef.current = pages;
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<{ direction: "previous" | "next"; message: string } | null>(null);
  const [toolsParagraph, setToolsParagraph] = useState<HistoryParagraph | null>(null);
  const [conclusionId, setConclusionId] = useState<string | null>(null);
  const [axisOpen, setAxisOpen] = useState(false);
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 1199px)").matches);
  const [headerHeight, setHeaderHeight] = useState(72);
  const [chromeHeight, setChromeHeight] = useState(72);
  const epoch = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const flight = useRef(false);
  const mounted = useRef(true);
  const chromeRef = useRef<HTMLDivElement>(null);
  const windowRef = useRef<HTMLDivElement>(null);
  const cache = useRef(new Map<number, HistoryPageData>());

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1199px)");
    const resize = () => setNarrow(media.matches); media.addEventListener("change", resize);
    const header = document.querySelector(".site-header");
    const bar = chromeRef.current;
    const measure = () => {
      const height = header?.getBoundingClientRect().height ?? 72;
      setHeaderHeight(height);
      setChromeHeight(height + (bar?.getBoundingClientRect().height ?? 0));
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (header) observer.observe(header);
    if (bar) observer.observe(bar);
    window.addEventListener("resize", measure);
    mounted.current = true;
    return () => { mounted.current = false; abort.current?.abort(); observer.disconnect(); media.removeEventListener("change", resize); window.removeEventListener("resize", measure); };
  }, []);
  const paragraphs = useMemo(() => pages.flatMap((page) => page.paragraphs).filter((p, n, all) => all.findIndex((v) => v.id === p.id) === n).sort((a, b) => a.ordinal - b.ordinal), [pages]);
  const paragraphRef = useRef(paragraphs); paragraphRef.current = paragraphs;
  const groups = useMemo(() => new Map(pub.groups.map((g) => [g.id, g])), [pub]);
  const contextFor = (entities: readonly HistoryEntity[]): ContextEntityView[] => entities.map((e) => ({ entity_ref: e.id, canonical_id: e.id,
    name: e.name, kind: e.kind, importance: e.importance, event_roles: [], source_anchor_ids: [] }));

  const controller = useReadingPosition({
    urlStrategy: HISTORY_POSITION_STRATEGY, unitSelector: "[data-history-paragraph]", headerHeight: chromeHeight,
    preserveLayoutPosition: true,
    getUnit: (id) => {
      const p = paragraphRef.current.find((v) => v.id === id);
      return p ? { unitId: p.id, ordinal: p.ordinal, narrativeTime: historyTime(groups.get(p.group_id)), contextEntities: contextFor(p.entities) } : null;
    },
    resolveStart: async () => historyPositionKey({ version: pub.version, paragraph_id: pub.first_paragraph_id }),
    locate: async (key, signal) => {
      if (key.catalog_sha !== pub.version) return null;
      const seq = ++epoch.current;
      abort.current?.abort(); abort.current = new AbortController(); flight.current = false;
      setLoading(false); setFailure(null);
      let page = [...cache.current.values()].find((candidate) => candidate.paragraphs.some((p) => p.id === key.unit_id));
      if (!page) page = await loadHistoryPage(pub.version, { at: key.unit_id }, signal);
      if (!mounted.current || signal?.aborted || seq !== epoch.current) return null;
      cache.current.set(page.start, page);
      if (!paragraphRef.current.some((p) => p.id === key.unit_id)) setPages([page]);
      return { locator: key, unitIds: page.paragraphs.map((p) => p.id) };
    },
  });
  // React Router same-page navigation and the native history controller share one restore path.
  const previousSearch = useRef(location.search);
  useEffect(() => {
    if (previousSearch.current !== location.search) { previousSearch.current = location.search; controller.restoreFromUrl(); }
  }, [location.search, controller.restoreFromUrl]);
  const active = paragraphs.find((p) => p.id === controller.activeUnitId) ?? paragraphs[0];
  const activeParagraph = active ?? null;
  // Single subscription point for the active composite paragraph's person/place
  // state. Switching paragraphs replaces the context synchronously (empty
  // paragraph clears it); hover previews never change it.
  const phaseContext = useHistoryPersonStateContext(pub.version, activeParagraph);
  const group = active ? groups.get(active.group_id) : null;

  const requestAdjacent = useCallback(async (direction: "previous" | "next") => {
    if (flight.current) return;
    const currentPages = [...pagesRef.current].sort((a, b) => a.start - b.start);
    const start = direction === "previous" ? currentPages[0]?.previous_start : currentPages[currentPages.length - 1]?.next_start;
    if (start == null) return;
    const seq = epoch.current;
    flight.current = true; setLoading(true); setFailure(null);
    const requestAbort = new AbortController(); abort.current = requestAbort;
    try {
      const page = cache.current.get(start) ?? await loadHistoryPage(pub.version, { start }, requestAbort.signal);
      if (!mounted.current || seq !== epoch.current) return;
      cache.current.set(page.start, page);
      setPages((old) => old.some((p) => p.start === page.start) ? old : [...old, page].sort((a, b) => a.start - b.start));
    } catch (error) {
      if (mounted.current && seq === epoch.current && !requestAbort.signal.aborted) setFailure({ direction, message: error instanceof Error ? error.message : "正文暂时无法载入" });
    } finally {
      if (seq === epoch.current) { flight.current = false; if (mounted.current) setLoading(false); }
    }
  }, [pub.version]);
  useLayoutEffect(() => {
    // The active date can wrap only after navigation commits. Preserve that
    // layout change through the same controller that owns paging and scroll.
    controller.notifyLayoutChange();
  }, [pages, loading, failure, chromeHeight, active?.id, narrow, controller.notifyLayoutChange]);
  useEffect(() => {
    const body = windowRef.current;
    if (!body) return;
    const observer = new ResizeObserver(() => controller.notifyLayoutChange());
    observer.observe(body);
    return () => observer.disconnect();
  }, [controller.notifyLayoutChange]);
  useEffect(() => {
    if (!active || loading || failure || controller.navigationState !== "idle") return;
    if (active.ordinal - paragraphs[0].ordinal < 6 && pages[0]?.previous_start != null) void requestAdjacent("previous");
    else if (paragraphs[paragraphs.length - 1].ordinal - active.ordinal < 6) void requestAdjacent("next");
  }, [active, paragraphs, pages, loading, failure, requestAdjacent, controller.navigationState]);

  const jump = (id: string) => controller.navigate({ kind: "locate", locator: historyPositionKey({ version: pub.version, paragraph_id: id }) });
  const nearbyIndex = pub.entry_points.reduce((n, entry, index) => entry.ordinal <= (active?.ordinal ?? 0) ? index : n, 0);
  const nearby = pub.entry_points.slice(Math.max(0, nearbyIndex - 1), nearbyIndex + 3);
  const entriesByEvent = new Map(pub.entry_points.filter((e) => e.event_id).map((e) => [e.event_id, e]));
  const side = <ReadingContextPanel entities={contextFor(phaseContext.entities)} unitId={active?.id} variant={narrow ? "panel" : "column"}
    stateFacts={phaseContext.stateFacts}
    stage={<PhaseStage status={phaseContext.status} phaseId={phaseContext.phaseId} count={phaseContext.entities.length} />}
    onViewEntity={(entity) => {
      if (!entity.canonicalId) return;
      const target = controller.rememberReturnTarget();
      const locator = phaseContext.locator;
      const paragraphId = locator?.paragraph_id ?? active?.id ?? "";
      const phase = locator?.phase_id ? `&phase=${encodeURIComponent(locator.phase_id)}` : "";
      navigate(`/entities/${encodeURIComponent(entity.canonicalId)}?catalog=${pub.catalog_sha}&version=${pub.version}&para=${encodeURIComponent(paragraphId)}${phase}${target ? `&return=${target.token}` : ""}`);
    }}>
    {(close) => <nav className="reading-nearby" aria-label="附近的重要事件"><h2>读到这里</h2><ol>{nearby.map((entry) => <li key={`${entry.kind}:${entry.paragraph_id}`}><button type="button" aria-current={entry === pub.entry_points[nearbyIndex] ? "location" : undefined} onClick={() => { close(); jump(entry.paragraph_id); }}>{entry.label}<small>{historyTimeLabel(entry)}</small></button></li>)}</ol></nav>}
  </ReadingContextPanel>;
  const axis = <nav className="history-axis" aria-label="历史时间轴"><ol>{pub.groups.map((item, index) => <li key={item.id}><button type="button" aria-label={`${historyTimeLabel(item)}，${item.label}`} aria-current={item.id === group?.id ? "location" : undefined} onClick={() => { setAxisOpen(false); jump(item.first_paragraph_id); }}>
    {index === 0 || pub.groups[index - 1].year !== item.year ? <span>{item.year == null ? "年代未详" : `${item.year < 0 ? `公元前 ${-item.year}` : item.year} 年`}</span> : null}
    <small>{item.period ?? (item.year == null ? item.label : "月份未详")}</small>
  </button></li>)}</ol></nav>;
  const factIds = toolsParagraph ? [...new Set([...toolsParagraph.segments.flatMap((s) => s.conclusion_ids), ...toolsParagraph.entities.flatMap((e) => e.states.map((s) => s.id))])] : [];
  return <section className="rpage history-reading" data-view="history-reading" data-version={pub.version} style={{ "--rpage-chrome-top": `${headerHeight}px` } as React.CSSProperties}>
    <div className="rpage-compact" ref={chromeRef}><button type="button" className="public-text-button history-axis-open" onClick={() => setAxisOpen(true)}>{historyTimeLabel(group) || "时间轴"}</button><span className="rpage-compact-time history-desktop-time">{historyTimeLabel(group)}</span>
      <div className="rpage-tools">{narrow ? side : null}<button className="public-text-button" disabled={!active} onClick={() => { setConclusionId(null); setToolsParagraph(active ?? null); }}>阅读资料</button></div></div>
    {controller.issue ? <div className="history-load-error" role="alert"><p>无法定位这段正文。{controller.issue.detail}</p><button className="public-text-button" onClick={() => controller.restoreFromUrl()}>重试定位</button><Link to="/">返回首页</Link></div> : null}
    <div className="rpage-grid"><div className="rpage-axis-column history-desktop-axis">{axis}</div><div className="rpage-main history-body" ref={windowRef} aria-label="历史正文">
      {pages[0]?.previous_start != null ? <button type="button" className="public-text-button history-load-previous" disabled={loading} onClick={() => void requestAdjacent("previous")}>读取更早的历史</button> : null}
      {paragraphs.map((paragraph) => <p key={paragraph.id} className="history-paragraph" data-history-paragraph data-unit-id={paragraph.id} data-ordinal={paragraph.ordinal} tabIndex={-1}>
        {paragraph.segments.map((segment, index) => { const entry = segment.event_id ? entriesByEvent.get(segment.event_id) : null;
          const mentionAt = segment.event_text ? segment.text.indexOf(segment.event_text) : -1;
          return <span key={index} data-certainty={segment.certainty} className={segment.certainty === "uncertain" ? "history-uncertain" : undefined}>
            {segment.certainty === "uncertain" ? <span className="public-sr-only">存疑表述：</span> : null}
            {entry && mentionAt >= 0 && segment.event_text ? <>{segment.text.slice(0, mentionAt)}<EventWord text={segment.event_text} entry={entry} jump={jump} />{segment.text.slice(mentionAt + segment.event_text.length)}</> : segment.text}
          </span>;
        })}
      </p>)}
      {loading || (paragraphs.length === 0 && !controller.issue) ? <p className="history-reading-status" role="status">正在载入正文…</p> : null}
      {failure ? <div className="history-load-error" role="alert"><p>{failure.message}，已读正文保留。</p><button className="public-text-button" onClick={() => void requestAdjacent(failure.direction)}>重试</button></div> : null}
      {paragraphs.length > 0 && paragraphs[paragraphs.length - 1].ordinal === pub.paragraph_count - 1 ? <p className="history-reading-end">已读到当前收录的末尾</p> : null}
    </div>{!narrow ? <div className="rpage-context-column">{side}</div> : null}</div>
    {axisOpen ? <PublicDialog title="时间轴" onClose={() => setAxisOpen(false)} compact>{axis}</PublicDialog> : null}
    {toolsParagraph ? <PublicDialog title="阅读资料" onClose={() => { setToolsParagraph(null); setConclusionId(null); }}>
      {conclusionId ? <><button type="button" className="public-text-button" onClick={() => setConclusionId(null)}>返回本段资料</button><Conclusion key={conclusionId} version={pub.version} id={conclusionId} /></> : <>
        <p className="history-tools-excerpt">{toolsParagraph.segments.map((s) => s.text).join("")}</p>
        <div className="history-fact-links">{factIds.map((id, index) => <button type="button" className="public-text-button" key={id} onClick={() => setConclusionId(id)}>查看依据 {index + 1}</button>)}</div>
      </>}
    </PublicDialog> : null}
  </section>;
}
