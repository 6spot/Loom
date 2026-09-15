import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router-dom";
import ChapterSourceReference from "../ChapterSourceReference";
import HistoryReturnLink from "../HistoryReturnLink";
import { usePersonHistory, type PersonHistoryMainLocator } from "../../hooks/usePersonHistory";
import { usePersonHistoryPosition } from "../../hooks/usePersonHistoryPosition";
import {
  loadPersonHistoryConclusion,
  type PersonHistoryConclusion,
  type PersonHistoryEvidence,
  type PersonHistoryParagraph,
  type PersonHistoryPhase,
  type PersonHistoryRelatedObject,
  type PersonHistoryConclusionResponse,
} from "../../lib/person-history-api";
import { buildReadingUrl } from "../../lib/reading-location";
import type { ReadingLocator } from "../../lib/reading-types";
import { readPath } from "../../lib/routes";
import { withHistoricalTime } from "../../lib/historical-time";
import type { TrajectoryEvent } from "../../lib/types";

interface PersonHistoryReaderProps {
  readonly entityId: string;
  readonly name: string;
  readonly search: string;
  readonly returnLocator: ReadingLocator | null;
  readonly requestedPersonVersion: string | null;
  readonly mainLocator: PersonHistoryMainLocator;
  readonly hasEvidence: boolean;
  readonly events: readonly TrajectoryEvent[];
}

function yearLabel(year: number | null | undefined): string | null {
  if (typeof year !== "number" || !Number.isFinite(year)) return null;
  return year < 0 ? `公元前 ${-year} 年` : `${year} 年`;
}

function phaseTimeLabel(phase: PersonHistoryPhase | null | undefined): string {
  if (!phase) return "年代未详";
  return [yearLabel(phase.year), phase.period?.trim() || null].filter(Boolean).join(" · ") || "年代未详";
}

function dateLabel(date: { readonly text?: string | null; readonly certainty?: string | null } | null | undefined): string | null {
  const text = date?.text?.trim();
  if (!text) return null;
  return date?.certainty === "uncertain" ? `${text}（存疑）` : text;
}

function qualificationLabel(qualification: PersonHistoryConclusion["qualification"]): string | null {
  switch (qualification) {
    case "recommendation": return "荐举";
    case "self_designation": return "自称";
    case "posthumous": return "追赠";
    case "reported": return "引述记载";
    default: return null;
  }
}

function stateDimensionLabel(dimension: PersonHistoryConclusion["dimension"]): string {
  switch (dimension) {
    case "office": return "官职";
    case "title": return "爵号";
    case "allegiance": return "效力／归属";
    default: return "状态";
  }
}

function objectLabel(object: PersonHistoryRelatedObject): string {
  return object.name?.trim() || object.title?.trim() || "未命名对象";
}

function objectPath(object: PersonHistoryRelatedObject, search: string): string | null {
  const id = object.canonical_id?.trim() || object.id.trim();
  if (!id) return null;
  if (object.kind === "event") return withHistoricalTime(`/events/${encodeURIComponent(id)}`, search);
  if (["person", "place", "polity", "organization"].includes(object.kind ?? "")) {
    return withHistoricalTime(`/entities/${encodeURIComponent(id)}`, search);
  }
  return null;
}

function SourceReturnLink({ returnLocator }: { readonly returnLocator: ReadingLocator | null }) {
  return returnLocator ? (
    <Link className="primary-link" data-test="reading-return" to={buildReadingUrl(returnLocator)}>返回阅读</Link>
  ) : (
    <Link className="primary-link" data-test="reading-enter" to={readPath()}>进入相关正文</Link>
  );
}

function phaseMappingText(
  history: ReturnType<typeof usePersonHistory>,
  selectedPhaseId: string | null,
): { readonly text: string; readonly tone: "mapped" | "ambiguous" | "unmapped" | "direct" | "invalid" } {
  if (history.invalidMainLocator) return { text: "这条人物页地址缺少有效的历史段落位置，请从历史正文重新进入。", tone: "invalid" };
  if (!history.hasMainLocator) return { text: "直接进入：展示人物整体情况，不擅自选定当前年份。", tone: "direct" };
  if (history.isEmpty) return { text: "主历史这段暂时没有已发布的人物生平对应关系；可以从已有资料入口开始。", tone: "unmapped" };
  if (history.mappingStatus === "mapped" && selectedPhaseId) return { text: "已保留主历史段落对应的人物阶段；返回阅读时恢复原位置。", tone: "mapped" };
  if (history.mappingStatus === "ambiguous") return { text: "主历史这一段对应多个已发布的人物阶段；请选择要阅读的阶段。", tone: "ambiguous" };
  if (history.mappingStatus === "unmapped" || history.mappingUnavailable || history.mapping.isError) {
    return { text: "主历史这段没有可靠的人物生平对应阶段；可以从生平开头阅读。", tone: "unmapped" };
  }
  return { text: "正在核对主历史段落与人物生平的对应关系。", tone: "unmapped" };
}

function MappingChoices({
  history,
  selectedPhaseId,
  onSelect,
}: {
  readonly history: ReturnType<typeof usePersonHistory>;
  readonly selectedPhaseId: string | null;
  readonly onSelect: (phaseId: string) => void;
}) {
  if (history.mappingStatus !== "ambiguous" || !history.mainMapping) return null;
  const phaseById = new Map((history.publication?.phases ?? []).map((phase) => [phase.id, phase]));
  return (
    <div className="pstate-mapping-choices" data-test="person-history-mapping-choices">
      <p>对应候选：</p>
      <div className="pstate-choice-list">
        {history.mainMapping.matches.map((match) => {
          const phase = phaseById.get(match.phase_id);
          return (
            <button
              type="button"
              className="pstate-choice"
              data-selected={selectedPhaseId === match.phase_id}
              data-phase-id={match.phase_id}
              key={match.phase_id}
              onClick={() => onSelect(match.phase_id)}
            >
              <strong>{phase?.label?.trim() || "未命名阶段"}</strong>
              <span>{phaseTimeLabel(phase)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PersonHistoryConclusionEvidence({
  personId,
  version,
  conclusionId,
}: {
  readonly personId: string;
  readonly version: string;
  readonly conclusionId: string;
}) {
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<{ readonly publicationId: string; readonly anchorId: string } | null>(null);
  const query = useQuery<PersonHistoryConclusionResponse, Error>({
    queryKey: ["chronicle", "person-history", "conclusion", personId, version, conclusionId],
    queryFn: ({ signal }) => loadPersonHistoryConclusion(personId, version, conclusionId, signal),
    enabled: open,
    staleTime: Infinity,
    retry: 1,
  });
  const evidence = query.data?.conclusion.evidence ?? query.data?.source_citations ?? [];
  return (
    <details className="entity-state-evidence pstate-evidence" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="public-text-button">查看依据</summary>
      {query.isPending ? <p role="status">正在载入本条依据…</p> : null}
      {query.isError ? (
        <div role="alert">
          <p>本条依据暂时无法读取。</p>
          <button type="button" className="public-text-button" onClick={() => void query.refetch()}>重试</button>
        </div>
      ) : null}
      {query.data ? (
        <div className="entity-state-evidence-content">
          {query.data.conclusion.text ? <p>{query.data.conclusion.text}</p> : null}
          {evidence.map((item: PersonHistoryEvidence) => (
            <section className="entity-source-quote" data-test="entity-source-quote" key={item.id}>
              <p className="muted">{item.source_title?.trim() || "已发布原章"}{item.attribution ? ` · ${item.attribution}` : ""}</p>
              {item.quote ? <blockquote>{item.quote}</blockquote> : <p>原章依据已登记，可打开前后文查看。</p>}
              {item.note ? <p>{item.note}</p> : null}
              <button
                type="button"
                className="public-text-button"
                onClick={() => setSource({ publicationId: item.publication_id, anchorId: item.anchor_id })}
              >
                查看原章前后文
              </button>
            </section>
          ))}
          {source ? (
            <ChapterSourceReference
              key={`${source.publicationId}:${source.anchorId}`}
              publicationId={source.publicationId}
              anchorId={source.anchorId}
              anchorLabel="原章前后文"
              onClose={() => setSource(null)}
            />
          ) : null}
        </div>
      ) : null}
    </details>
  );
}

function StateItem({ item, personId, version }: { readonly item: PersonHistoryConclusion; readonly personId: string; readonly version: string }) {
  const qualification = qualificationLabel(item.qualification);
  return (
    <li className="entity-state-fact pstate-state-item" data-certainty={item.certainty} data-dimension={item.dimension} data-fact-id={item.id}>
      <span className="chr-state-mark" aria-hidden="true">{item.certainty === "clear" ? "●" : "○"}</span>
      <span className="public-sr-only">{item.certainty === "clear" ? "明确记载：" : "存疑："}</span>
      <span className="entity-state-label">{stateDimensionLabel(item.dimension)}</span>
      <span className="entity-state-value">{item.value?.trim() || item.text?.trim() || "阶段内容未明确"}</span>
      {item.certainty === "uncertain" ? <small>存疑</small> : null}
      {qualification ? <small>{qualification}</small> : null}
      {item.evidence_count > 0 ? <PersonHistoryConclusionEvidence personId={personId} version={version} conclusionId={item.id} /> : null}
    </li>
  );
}

function RelatedObjects({ objects, search }: { readonly objects: readonly PersonHistoryRelatedObject[]; readonly search: string }) {
  const unique = [...new Map(objects.map((object) => [object.id, object])).values()];
  if (!unique.length) return <p className="chr-context-unknown">本段没有额外关联对象。</p>;
  return (
    <ul className="pstate-related" data-test="entity-related-objects">
      {unique.map((object) => {
        const path = objectPath(object, search);
        return (
          <li key={object.id}>
            {path ? <Link to={path}>{objectLabel(object)}</Link> : <span>{objectLabel(object)}</span>}
            {object.kind ? <small>{object.kind === "event" ? "相关事件" : "相关对象"}</small> : null}
          </li>
        );
      })}
    </ul>
  );
}

function CurrentPhasePanel({
  paragraph,
  personId,
  version,
  search,
}: {
  readonly paragraph: PersonHistoryParagraph | null;
  readonly personId: string;
  readonly version: string | null;
  readonly search: string;
}) {
  if (!paragraph || !version) {
    return (
      <section className="panel entity-phase-panel pstate-current" data-test="entity-phase-state">
        <div className="panel-heading"><h2>当前阶段状态</h2></div>
        <p className="chr-context-unknown">滚动个人经历后显示当时阶段状态；页面不会把未定位阶段当作当前身份。</p>
      </section>
    );
  }
  const states = [...new Map(
    paragraph.states
      .filter((item) => ["office", "title", "allegiance"].includes(item.dimension))
      .map((item) => [item.id, item]),
  ).values()];
  return (
    <section
      className="panel entity-phase-panel pstate-current"
      data-test="entity-phase-state"
      data-phase-id={paragraph.phase_id}
      data-paragraph-id={paragraph.id}
    >
      <div className="panel-heading">
        <div>
          <h2>当前阶段状态</h2>
          <p className="entity-phase-context"><strong>{paragraph.phase.label?.trim() || "阶段未注明"}</strong><span>{phaseTimeLabel(paragraph.phase)}</span></p>
        </div>
        <span className="count">{states.length ? `${states.length} 项` : "暂无记载"}</span>
      </div>
      {states.length ? (
        <ul className="entity-state-facts" data-test="entity-phase-facts">
          {states.map((item) => <StateItem item={item} personId={personId} version={version} key={item.id} />)}
        </ul>
      ) : <p className="chr-context-unknown">本阶段没有明确的官职、爵号或效力／归属记载。</p>}
      <div className="entity-phase-related" data-test="entity-phase-related">
        <h3>相关对象</h3>
        <RelatedObjects objects={paragraph.related_objects} search={search} />
      </div>
    </section>
  );
}

function ExperienceParagraph({
  paragraph,
  first,
  active,
  register,
  personId,
  version,
}: {
  readonly paragraph: PersonHistoryParagraph;
  readonly first: boolean;
  readonly active: boolean;
  readonly register: (id: string, node: HTMLElement | null) => void;
  readonly personId: string;
  readonly version: string;
}) {
  return (
    <li
      className="pstate-history-paragraph entity-experience-entry"
      data-test="person-history-paragraph"
      data-paragraph-id={paragraph.id}
      data-phase-id={paragraph.phase_id}
      data-active={active}
      id={first ? "person-history-start" : undefined}
      ref={(node) => register(paragraph.id, node)}
    >
      <div className="pstate-time-anchor">
        <span>{paragraph.phase.label?.trim() || "阶段未注明"}</span>
        <small>{phaseTimeLabel(paragraph.phase)}</small>
      </div>
      <div className="pstate-history-copy" data-test="entity-experience-entry">
        {paragraph.segments.map((segment, index) => <p key={`${paragraph.id}:${index}`}>{segment.text}</p>)}
      </div>
      {paragraph.conclusion_ids.length ? (
        <details className="pstate-paragraph-evidence" data-test="person-history-evidence">
          <summary className="public-text-button">查看本段依据（{paragraph.conclusion_ids.length}）</summary>
          <div className="pstate-paragraph-evidence-list">
            {[...new Set(paragraph.conclusion_ids)].map((conclusionId) => (
              <PersonHistoryConclusionEvidence key={conclusionId} personId={personId} version={version} conclusionId={conclusionId} />
            ))}
          </div>
        </details>
      ) : null}
    </li>
  );
}

export default function PersonHistoryReader({
  entityId,
  name,
  search,
  returnLocator,
  requestedPersonVersion,
  mainLocator,
  hasEvidence,
  events,
}: PersonHistoryReaderProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const history = usePersonHistory(entityId, requestedPersonVersion, mainLocator);
  const [selectedPhaseId, setSelectedPhaseId] = useState<string | null>(null);
  const mappedPhaseId = history.mappingStatus === "mapped" ? history.mappedPhaseIds[0] ?? null : null;
  const preferredPhaseId = selectedPhaseId ?? mappedPhaseId;
  const position = usePersonHistoryPosition({ paragraphs: history.paragraphs, preferredPhaseId });
  const activeParagraph = history.paragraphs.find((paragraph) => paragraph.id === position.activeParagraphId) ?? null;
  const mappingText = phaseMappingText(history, selectedPhaseId ?? mappedPhaseId);
  const phaseById = useMemo(() => new Map((history.publication?.phases ?? []).map((phase) => [phase.id, phase])), [history.publication?.phases]);

  useEffect(() => {
    const version = history.publication?.person_history_version;
    if (!version || requestedPersonVersion !== null) return;
    const params = new URLSearchParams(location.search);
    if (params.get("person_version")) return;
    params.set("person_version", version);
    navigate({ pathname: location.pathname, search: `?${params.toString()}`, hash: location.hash }, { replace: true });
  }, [history.publication?.person_history_version, location.hash, location.pathname, location.search, navigate, requestedPersonVersion]);

  const selectPhase = (phaseId: string) => {
    setSelectedPhaseId(phaseId);
    const first = history.paragraphs.find((paragraph) => paragraph.phase_id === phaseId);
    if (first) position.scrollToParagraph(first.id);
  };

  const overview = history.publication?.overview?.trim() || history.publication?.reviewed_overview?.trim() || null;
  const birth = dateLabel(history.publication?.birth);
  const death = dateLabel(history.publication?.death);
  const coverage = history.publication?.coverage?.statement?.trim() || "根据当前收录资料整理的经历";
  const limitedCoverage = history.publication?.coverage?.exhaustive !== true;

  return (
    <section className="pstate-entity" data-test="person-history-page" data-person-version={history.personVersion ?? undefined}>
      <HistoryReturnLink fallback={<SourceReturnLink returnLocator={returnLocator} />} />
      <div className="pstate-entity-grid">
        <aside className="pstate-entity-left" data-test="entity-left" aria-label="概况与时间定位">
          <p className="eyebrow">人物</p>
          <h1 data-test="entity-name">{name || "未命名人物"}</h1>
          {history.metadata.isPending ? <p className="pstate-muted">正在读取人物生平版本…</p> : null}
          {history.metadata.isError ? (
            <div className="pstate-message" role="alert">
              <p>人物生平暂时无法读取；不会用其他版本替代当前请求。</p>
              <button type="button" className="public-text-button" onClick={() => void history.metadata.refetch()}>重试</button>
            </div>
          ) : null}
          {!history.metadata.isPending && !history.metadata.isError && history.isEmpty ? (
            <div className="pstate-message" data-test="person-history-empty">
              <p>目前没有已发布的人物生平。</p>
              {hasEvidence ? <a className="public-text-button" href="#evidence">查看已有可核查资料</a> : null}
            </div>
          ) : null}
          {history.publication ? (
            <>
              <p className="pstate-intro" data-test="person-history-overview">
                {overview || "暂无已发布人物简介；这里不把主历史片段拼成简介。"}
              </p>
              <p className="pstate-coverage" data-test="person-history-coverage">{coverage}{limitedCoverage ? "，不代表完整一生。" : "。"}</p>
              {birth || death ? (
                <dl className="pstate-life-dates">
                  {birth ? <><dt>生年</dt><dd>{birth}</dd></> : null}
                  {death ? <><dt>卒年</dt><dd>{death}</dd></> : null}
                </dl>
              ) : null}
            </>
          ) : null}
          {!history.publication && events.length ? (
            <section className="pstate-existing-material" data-test="person-existing-material">
              <h2>已有可核查资料</h2>
              <p>人物生平尚未发布；先从已有的事件资料进入，不把它们拼成未经发布的传记。</p>
              <ul>
                {events.map((event) => (
                  <li key={event.canonical_event_id}>
                    <Link to={withHistoricalTime(`/events/${encodeURIComponent(event.canonical_event_id)}`, search)}>{event.display?.title ?? "未命名经历"}</Link>
                    <span>{event.time?.start_year == null ? "年代未详" : yearLabel(event.time.start_year)}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <p className={`pstate-time-anchor pstate-time-anchor-${mappingText.tone}`} data-test="entity-time-anchor">
            {mappingText.text}
          </p>
          <MappingChoices history={history} selectedPhaseId={selectedPhaseId} onSelect={selectPhase} />
          {history.publication && (mappingText.tone === "unmapped" || mappingText.tone === "direct") ? (
            <a className="public-text-button" href="#person-history-start">从生平开头阅读</a>
          ) : null}
          {hasEvidence ? <a className="public-text-button" href="#evidence" data-test="entity-evidence-link">查看来源与依据</a> : null}
        </aside>

        <main className="pstate-entity-main" data-test="entity-main" aria-label="按时间的个人经历" ref={position.rootRef}>
          <div className="pstate-main-heading">
            <div>
              <p className="eyebrow">人物生平</p>
              <h2>个人经历</h2>
            </div>
            {history.publication ? <span className="count">{history.publication.paragraph_count} 段</span> : null}
          </div>
          {history.publication ? (
            <p className="pstate-main-scope">{coverage}{limitedCoverage ? "，不代表完整一生。" : "。"}</p>
          ) : (
            <p className="pstate-main-scope">目前没有已发布的人物生平；已有可核查资料会保持在按需打开的入口中。</p>
          )}
          {history.pages.isPending ? <p role="status">正在载入按时间排列的个人经历…</p> : null}
          {history.pages.isError ? (
            <div className="pstate-message" role="alert">
              <p>个人经历暂时无法读取；当前页面未改用其他版本。</p>
              <button type="button" className="public-text-button" onClick={() => void history.pages.refetch()}>重试</button>
            </div>
          ) : null}
          {!history.pages.isPending && !history.pages.isError && history.publication ? (
            history.paragraphs.length ? (
              <ol className="pstate-timeline entity-experience-timeline" data-test="entity-timeline">
                {history.paragraphs.map((paragraph, index) => (
                  <ExperienceParagraph
                    key={paragraph.id}
                    paragraph={paragraph}
                    first={index === 0}
                    active={paragraph.id === activeParagraph?.id}
                    register={position.registerParagraph}
                    personId={entityId}
                    version={history.personVersion!}
                  />
                ))}
              </ol>
            ) : <p className="chr-context-unknown">当前发布版本没有可阅读的个人经历。</p>
          ) : null}
          {history.pages.hasNextPage ? (
            <button type="button" className="public-text-button pstate-load-more" onClick={() => void history.loadMore()} disabled={history.pages.isFetchingNextPage}>
              {history.pages.isFetchingNextPage ? "正在载入…" : "加载更多经历"}
            </button>
          ) : null}
        </main>

        <aside className="pstate-entity-right" data-test="entity-right" aria-label="当时阶段状态">
          {history.mapping.isFetching ? <p className="pstate-mapping-loading" role="status">正在核对主历史段落…</p> : null}
          {history.mapping.isError && !history.mappingUnavailable && history.hasMainLocator ? (
            <div className="pstate-message" role="alert"><p>主历史段落的对应关系暂时无法读取。</p><button type="button" className="public-text-button" onClick={() => void history.mapping.refetch()}>重试</button></div>
          ) : null}
          <CurrentPhasePanel paragraph={activeParagraph} personId={entityId} version={history.personVersion} search={search} />
          {activeParagraph ? <p className="pstate-active-note" aria-live="polite">状态随正在阅读的个人经历段落更新。</p> : null}
          {history.mainMapping?.reason && history.mappingStatus !== "mapped" ? <p className="pstate-mapping-reason">{history.mainMapping.reason}</p> : null}
          {[...phaseById.values()].some((phase) => phase.mapping_status === "unmapped") ? <p className="pstate-mapping-reason">未能可靠对应主历史的位置会保留为未映射，不以年份或名称猜测。</p> : null}
        </aside>
      </div>
    </section>
  );
}
