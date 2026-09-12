// C2-R3-T11 阅读页「当时人物／地点」紧凑状态组件。
//
// 只消费 T01 已编译摘要（PersonSummary / PlaceStateItem）与调用方回调：
//  - 默认每人／每地点独占一行，显示当时官职／爵号／效力与行政归属／控制；
//  - 兼任＝多项并列，不压成“最高官职”；
//  - 每条按服务端 certainty 渲染实心／空心与正常／灰墨色，限定语始终可见，
//    原因与原文／事件入口按需展开；
//  - 不明确项仍可操作，保持 44px 触控与键盘可达；
//  - 暂无记载与阶段未明确是不同空态；加载／失败不沿用上一段身份。
//
// 组件不接 App、API client 或全局 CSS；由 T13 传入同一阅读 locator 的摘要。

import { useId, useState, type ReactNode } from "react";
import type {
  Certainty,
  PersonSummary,
  PhaseSummary,
  PlaceStateItem,
  SourceFactRef,
  StateItem,
} from "../../lib/person-state-types";
import {
  EMPTY_SECTION_TEXT,
  EMPTY_STATE_LABELS,
  LEGEND_CLEAR_TEXT,
  LEGEND_UNCERTAIN_TEXT,
  PHASE_MODE_LABELS,
  certaintyMark,
  emptyStateForPerson,
  groupPlaceItems,
  groupUnitState,
  moreItemsText,
  phaseLabel,
  stateItemView,
  type EmptyStateKind,
  type PlaceGroupView,
  type PlaceItemView,
  type StateItemView,
} from "../../lib/person-state-display";
import "../../styles/person-state.css";

export type PersonStateStatus = "ready" | "loading" | "error" | "empty";

export interface PersonStateSourceRequest {
  readonly subjectId: string;
  readonly subjectName: string;
  readonly itemId: string;
  readonly certainty: Certainty;
  readonly sourceFact: SourceFactRef;
}

export interface PersonStateEventRequest {
  readonly subjectId: string;
  readonly itemId: string;
  readonly eventRef: string;
  readonly label: string;
}

export interface PersonStateEventRef {
  readonly eventRef: string;
  readonly label: string;
}

export interface PersonStateItemsProps {
  readonly people?: readonly PersonSummary[] | null;
  readonly places?: readonly PlaceStateItem[] | null;
  /** 服务端有序阶段；用于 process／ambiguous 阶段标注。 */
  readonly phases?: readonly PhaseSummary[] | null;
  readonly status?: PersonStateStatus;
  readonly onOpenDetails?: (person: PersonSummary) => void;
  readonly onOpenSource?: (request: PersonStateSourceRequest) => void;
  readonly onOpenEvent?: (request: PersonStateEventRequest) => void;
  /** 已审核精选 entry_points，按 item_id 提供；缺省时不渲染事件入口。 */
  readonly eventsByItem?: Readonly<Record<string, readonly PersonStateEventRef[]>>;
  readonly onRetry?: () => void;
  readonly onLoadMoreIdentities?: (person: PersonSummary) => void;
  readonly onLoadMorePeople?: () => void;
  readonly hasMorePeople?: boolean;
  readonly showLegend?: boolean;
}

export function StateMark({ certainty }: { certainty: Certainty }) {
  return (
    <span
      className="chr-state-mark"
      data-test="person-state-mark"
      data-certainty={certainty}
      aria-hidden="true"
    >
      {certaintyMark(certainty)}
    </span>
  );
}

export function PersonStateLegend() {
  return (
    <p className="pstate-legend" data-test="person-state-legend">
      <span className="chr-context-state" data-certainty="clear">
        <StateMark certainty="clear" />
        <span aria-hidden="true">{LEGEND_CLEAR_TEXT}</span>
      </span>
      <span className="chr-context-state" data-certainty="uncertain">
        <StateMark certainty="uncertain" />
        <span aria-hidden="true">{LEGEND_UNCERTAIN_TEXT}</span>
      </span>
    </p>
  );
}

export function PersonStateEmpty({ kind, note }: { kind: EmptyStateKind; note?: string | null }) {
  return (
    <p className="chr-context-unknown pstate-empty" data-test="person-state-empty" data-empty-kind={kind}>
      {EMPTY_STATE_LABELS[kind]}
      {note ? <small>{note}</small> : null}
    </p>
  );
}

function PhaseNote({ mode, note }: { mode: PersonSummary["phase_mode"]; note?: string | null }) {
  if (mode === "single") return null;
  return (
    <p className="pstate-phase" data-test="person-state-phase" data-phase-mode={mode}>
      {PHASE_MODE_LABELS[mode]}
      {note ? <small>{note}</small> : null}
    </p>
  );
}

function EvidenceActions({
  view,
  subjectId,
  subjectName,
  events,
  onOpenSource,
  onOpenEvent,
}: {
  view: StateItemView | PlaceItemView;
  subjectId: string;
  subjectName: string;
  events: readonly PersonStateEventRef[];
  onOpenSource?: (request: PersonStateSourceRequest) => void;
  onOpenEvent?: (request: PersonStateEventRequest) => void;
}) {
  const item = view.item;
  const sourceFacts: readonly SourceFactRef[] = item.source_facts;
  const hasSourceActions = sourceFacts.length > 0 && Boolean(onOpenSource);
  const hasEventActions = events.length > 0 && Boolean(onOpenEvent);
  // 限定语始终可见；原因与来源按需在「依据」中展开。
  const hasDisclosure = Boolean(view.reasonText) || hasSourceActions || hasEventActions;
  if (!hasDisclosure) return null;
  return (
    <details className="pstate-evidence">
      <summary
        className="public-text-button pstate-evidence-button"
        data-test="person-state-evidence"
        aria-label={`查看${view.labelText}「${view.valueText}」的原因与原文依据`}
      >
        依据
      </summary>
      <span className="pstate-evidence-body">
        {view.reasonText ? (
          <span className="pstate-reason" data-test="person-state-reason">
            原因：{view.reasonText}
          </span>
        ) : null}
        {hasSourceActions || hasEventActions ? (
          <span className="pstate-evidence-actions">
            {sourceFacts.map((sourceFact) => (
              <button
                type="button"
                className="public-text-button pstate-source-button"
                data-test="person-state-source"
                data-source-ref={sourceFact.fact_ref}
                key={`${sourceFact.chapter_id}:${sourceFact.fact_ref}`}
                onClick={() =>
                  onOpenSource?.({
                    subjectId,
                    subjectName,
                    itemId: item.item_id,
                    certainty: item.certainty,
                    sourceFact,
                  })
                }
              >
                原文
              </button>
            ))}
            {events.map((event) => (
              <button
                type="button"
                className="public-text-button pstate-event-button"
                data-test="person-state-event"
                data-event-ref={event.eventRef}
                key={event.eventRef}
                onClick={() =>
                  onOpenEvent?.({ subjectId, itemId: item.item_id, eventRef: event.eventRef, label: event.label })
                }
              >
                事件：{event.label}
              </button>
            ))}
          </span>
        ) : null}
      </span>
    </details>
  );
}

function ItemLine({
  view,
  subjectId,
  subjectName,
  events,
  onOpenSource,
  onOpenEvent,
}: {
  view: StateItemView | PlaceItemView;
  subjectId: string;
  subjectName: string;
  events: readonly PersonStateEventRef[];
  onOpenSource?: (request: PersonStateSourceRequest) => void;
  onOpenEvent?: (request: PersonStateEventRequest) => void;
}) {
  const item = view.item;
  const reasonCode = item.reason_codes[0] ?? "";
  return (
    <span
      className="chr-context-state pstate-item"
      data-test="person-state-item"
      data-certainty={item.certainty}
      data-dimension={item.dimension}
      data-reason={reasonCode}
      data-item-id={item.item_id}
    >
      <StateMark certainty={item.certainty} />
      <span className="public-sr-only">{view.accessibleText}。</span>
      <span className="pstate-item-label" aria-hidden="true">
        {view.labelText}
      </span>
      <span className="pstate-item-value" aria-hidden="true">
        {view.valueText}
      </span>
      {view.qualificationText ? (
        <span className="pstate-qualification" data-test="person-state-qualification" aria-hidden="true">
          （{view.qualificationText}）
        </span>
      ) : null}
      <EvidenceActions
        view={view}
        subjectId={subjectId}
        subjectName={subjectName}
        events={events}
        onOpenSource={onOpenSource}
        onOpenEvent={onOpenEvent}
      />
    </span>
  );
}

function SubjectName({
  name,
  onOpenDetails,
}: {
  name: string;
  onOpenDetails?: () => void;
}) {
  if (!onOpenDetails) {
    return (
      <span className="chr-context-name" data-test="person-state-name">
        {name}
      </span>
    );
  }
  return (
    <button
      type="button"
      className="pstate-name-button"
      data-test="person-state-view-detail"
      aria-label={`查看${name}的人物详情`}
      onClick={onOpenDetails}
    >
      <span className="chr-context-name" data-test="person-state-name">
        {name}
      </span>
    </button>
  );
}

function PersonBlock({
  person,
  phases,
  eventsByItem,
  onOpenDetails,
  onOpenSource,
  onOpenEvent,
  onLoadMoreIdentities,
}: {
  person: PersonSummary;
  phases: readonly PhaseSummary[] | null | undefined;
  eventsByItem: Readonly<Record<string, readonly PersonStateEventRef[]>>;
  onOpenDetails?: (person: PersonSummary) => void;
  onOpenSource?: (request: PersonStateSourceRequest) => void;
  onOpenEvent?: (request: PersonStateEventRequest) => void;
  onLoadMoreIdentities?: (person: PersonSummary) => void;
}) {
  const emptyKind = emptyStateForPerson(person);
  const phaseNote = phaseLabel(person.identities[0]?.phase_ids[0], phases) || null;
  const hidden = person.identity_count - person.identities.length;
  return (
    <li
      className="chr-context-item pstate-subject"
      data-test="person-state-subject"
      data-kind="person"
      data-importance={person.importance}
      data-phase-mode={person.phase_mode}
      data-subject-id={person.person_id}
      data-has-empty-state={emptyKind ?? ""}
    >
      <div className="pstate-subject-row">
        <SubjectName
          name={person.name}
          onOpenDetails={onOpenDetails ? () => onOpenDetails(person) : undefined}
        />
        {emptyKind ? (
          <PersonStateEmpty kind={emptyKind} note={phaseNote} />
        ) : (
          <span className="chr-context-states">
            {person.identities.map((item: StateItem) => (
              <ItemLine
                key={item.item_id}
                view={stateItemView(item)}
                subjectId={person.person_id}
                subjectName={person.name}
                events={eventsByItem[item.item_id] ?? []}
                onOpenSource={onOpenSource}
                onOpenEvent={onOpenEvent}
              />
            ))}
          </span>
        )}
      </div>
      <PhaseNote mode={person.phase_mode} note={phaseNote} />
      {person.has_more_identities && hidden > 0 ? (
        <button
          type="button"
          className="pstate-more"
          data-test="person-state-more"
          onClick={() => onLoadMoreIdentities?.(person)}
        >
          {moreItemsText(hidden)}
        </button>
      ) : null}
    </li>
  );
}

function PlaceBlock({
  group,
  eventsByItem,
  onOpenSource,
  onOpenEvent,
}: {
  group: PlaceGroupView;
  eventsByItem: Readonly<Record<string, readonly PersonStateEventRef[]>>;
  onOpenSource?: (request: PersonStateSourceRequest) => void;
  onOpenEvent?: (request: PersonStateEventRequest) => void;
}) {
  return (
    <li
      className="chr-context-item pstate-subject"
      data-test="person-state-subject"
      data-kind="place"
      data-importance="primary"
      data-subject-id={group.placeId}
    >
      <div className="pstate-subject-row">
        <SubjectName name={group.name} />
        <span className="chr-context-states">
          {group.items.map((view) => (
            <ItemLine
              key={view.item.item_id}
              view={view}
              subjectId={group.placeId}
              subjectName={group.name}
              events={eventsByItem[view.item.item_id] ?? []}
              onOpenSource={onOpenSource}
              onOpenEvent={onOpenEvent}
            />
          ))}
        </span>
      </div>
    </li>
  );
}

export default function PersonStateItems({
  people,
  places,
  phases,
  status = "ready",
  onOpenDetails,
  onOpenSource,
  onOpenEvent,
  eventsByItem,
  onRetry,
  onLoadMoreIdentities,
  onLoadMorePeople,
  hasMorePeople = false,
  showLegend = true,
}: PersonStateItemsProps) {
  const [showOther, setShowOther] = useState(false);
  const panelId = useId();
  const groups = groupUnitState(people, places);
  const events = eventsByItem ?? {};

  if (status === "loading") {
    return (
      <div className="chr-context-panel pstate-panel" data-test="person-state-context" data-status="loading">
        <p className="pstate-loading" data-test="person-state-loading" role="status">
          正在加载本段人物与地点资料…
        </p>
      </div>
    );
  }
  if (status === "error") {
    return (
      <div className="chr-context-panel pstate-panel" data-test="person-state-context" data-status="error">
        <div className="pstate-error" data-test="person-state-error" role="alert">
          <p>本段人物资料暂时无法读取；已读正文保留，不沿用上一段身份。</p>
          <button type="button" className="public-text-button" data-test="person-state-retry" onClick={onRetry}>
            重试
          </button>
        </div>
      </div>
    );
  }
  if (status === "empty" || (!groups.primary.length && !groups.other.length && !groups.places.length)) {
    return (
      <div className="chr-context-panel pstate-panel" data-test="person-state-context" data-status="empty">
        <p className="chr-context-empty" data-test="person-state-empty-section">
          {EMPTY_SECTION_TEXT}
        </p>
      </div>
    );
  }

  const placeGroups = groupPlaceItems(groups.places);
  const visiblePlaces: ReactNode = placeGroups.map((group) => (
    <PlaceBlock
      key={group.placeId}
      group={group}
      eventsByItem={events}
      onOpenSource={onOpenSource}
      onOpenEvent={onOpenEvent}
    />
  ));

  return (
    <div className="chr-context-panel pstate-panel" data-test="person-state-context" data-status="ready">
      {showLegend ? <PersonStateLegend /> : null}
      {groups.primary.length > 0 ? (
        <section className="chr-context-group" data-test="person-state-group" data-group="people">
          <h3 className="chr-context-group-title">当前人物</h3>
          <ul className="chr-context-list">
            {groups.primary.map((person) => (
              <PersonBlock
                key={person.person_id}
                person={person}
                phases={phases}
                eventsByItem={events}
                onOpenDetails={onOpenDetails}
                onOpenSource={onOpenSource}
                onOpenEvent={onOpenEvent}
                onLoadMoreIdentities={onLoadMoreIdentities}
              />
            ))}
          </ul>
          {groups.other.length > 0 ? (
            <button
              type="button"
              className="chr-context-expand"
              data-test="person-state-more-people"
              aria-expanded={showOther}
              aria-controls={panelId}
              onClick={() => {
                setShowOther((value) => !value);
                onLoadMorePeople?.();
              }}
            >
              {showOther ? "收起其他人物" : `其他人物 · ${groups.other.length}`}
            </button>
          ) : null}
          {showOther ? (
            <ul className="chr-context-list" id={panelId}>
              {groups.other.map((person) => (
                <PersonBlock
                  key={person.person_id}
                  person={person}
                  phases={phases}
                  eventsByItem={events}
                  onOpenDetails={onOpenDetails}
                  onOpenSource={onOpenSource}
                  onOpenEvent={onOpenEvent}
                  onLoadMoreIdentities={onLoadMoreIdentities}
                />
              ))}
            </ul>
          ) : null}
          {hasMorePeople ? (
            <button
              type="button"
              className="chr-context-expand"
              data-test="person-state-more-page"
              onClick={() => onLoadMorePeople?.()}
            >
              更多人物
            </button>
          ) : null}
        </section>
      ) : null}
      {groups.places.length > 0 ? (
        <section className="chr-context-group" data-test="person-state-group" data-group="places">
          <h3 className="chr-context-group-title">当时地点</h3>
          <ul className="chr-context-list">{visiblePlaces}</ul>
        </section>
      ) : null}
    </div>
  );
}
