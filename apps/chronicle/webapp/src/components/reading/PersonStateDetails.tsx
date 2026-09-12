// C2-R3-T11 人物详情（受控内容组件）。
//
// 作为 T13 独立人物页的受控内容：提供简短介绍、当时身份与「按时间展开的有据
// 经历与身份变化」。它不拥有布局、路由、返回或当前年份；由调用方（T13）决定
// 放在人物页哪一栏、从主历史进入时保留哪一段并负责返回。
//
// 只消费 T01 已编译 DTO（PersonSummary / StateChange / EvidenceDescriptor），
// 不重新判定 certainty，也不把最后头衔或全生平简介补成一条身份。

import type {
  Attribution,
  PersonSummary,
  PhaseSummary,
  SourceFactRef,
  StateChange,
} from "../../lib/person-state-types";
import {
  certaintyLabel,
  certaintyMark,
  buildChangeTimeline,
  emptyStateForPerson,
  phaseLabel,
  stateItemView,
} from "../../lib/person-state-display";
import { PersonStateEmpty, type PersonStateSourceRequest } from "./PersonStateItems";
import "../../styles/person-state.css";

export interface PersonStateRelatedRef {
  readonly id: string;
  readonly name: string;
  readonly relation: string;
}

export interface PersonStateDetailsProps {
  readonly person: PersonSummary;
  readonly phases?: readonly PhaseSummary[] | null;
  readonly intro?: string | null;
  /** 完整变化（可超过摘要预览上限）；缺省时退回摘要内 changes。 */
  readonly changes?: readonly StateChange[] | null;
  readonly related?: readonly PersonStateRelatedRef[] | null;
  /** 由调用方从 EvidenceDescriptor 提供的来源归属标签，按 item_id 索引。 */
  readonly attributionByItem?: Readonly<Record<string, Attribution>> | null;
  readonly onOpenSource?: (request: PersonStateSourceRequest) => void;
}

const ATTRIBUTION_LABELS: Readonly<Record<Attribution, string>> = {
  narrator: "正文·叙述者",
  quotation: "引述",
  annotation: "裴注·注文",
  hearsay: "传闻",
};

function AttributionTag({ attribution }: { attribution: Attribution }) {
  return (
    <span
      className="pstate-attribution"
      data-test="person-state-attribution"
      data-attribution={attribution}
    >
      {ATTRIBUTION_LABELS[attribution] ?? attribution}
    </span>
  );
}

export default function PersonStateDetails({
  person,
  phases,
  intro,
  changes,
  related,
  attributionByItem,
  onOpenSource,
}: PersonStateDetailsProps) {
  const emptyKind = emptyStateForPerson(person);
  const timeline = buildChangeTimeline(changes ?? person.changes, phases);
  const attribution = attributionByItem ?? {};

  return (
    <section className="pstate-details" data-test="person-state-details" data-subject-id={person.person_id}>
      {intro ? <p className="pstate-intro">{intro}</p> : null}

      <h3 className="pstate-section-title">当时身份（本段）</h3>
      {emptyKind ? (
        <PersonStateEmpty
          kind={emptyKind}
          note={phaseLabel(person.identities[0]?.phase_ids[0], phases) || null}
        />
      ) : (
        <ul className="pstate-detail-items" data-test="person-detail-identities">
          {person.identities.map((item) => {
            const view = stateItemView(item);
            const tag = attribution[item.item_id];
            const sourceFacts: readonly SourceFactRef[] = item.source_facts;
            return (
              <li
                className="chr-context-state pstate-item"
                data-test="person-state-item"
                data-certainty={item.certainty}
                data-dimension={item.dimension}
                data-reason={item.reason_codes[0] ?? ""}
                data-item-id={item.item_id}
                key={item.item_id}
              >
                <span
                  className="chr-state-mark"
                  data-test="person-state-mark"
                  data-certainty={item.certainty}
                  aria-hidden="true"
                >
                  {certaintyMark(item.certainty)}
                </span>
                <span className="public-sr-only">{view.accessibleText}。</span>
                <span className="pstate-item-label">{view.labelText}</span>
                <span className="pstate-item-value">{view.valueText}</span>
                {view.qualificationText ? (
                  <span className="pstate-qualification" data-test="person-state-qualification">
                    （{view.qualificationText}）
                  </span>
                ) : null}
                {tag ? <AttributionTag attribution={tag} /> : null}
                {view.reasonText || (sourceFacts.length > 0 && onOpenSource) ? (
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
                      {sourceFacts.length > 0 && onOpenSource ? (
                        <button
                          type="button"
                          className="public-text-button pstate-inline-source"
                          data-test="person-detail-source"
                          onClick={() =>
                            onOpenSource({
                              subjectId: person.person_id,
                              subjectName: person.name,
                              itemId: item.item_id,
                              certainty: item.certainty,
                              sourceFact: sourceFacts[0],
                            })
                          }
                        >
                          查看原文
                        </button>
                      ) : null}
                    </span>
                  </details>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <h3 className="pstate-section-title">有据经历与变化</h3>
      <ol className="pstate-timeline" data-test="person-detail-timeline">
        {timeline.map((entry) => {
          const sourceFacts: readonly SourceFactRef[] = entry.change.source_facts;
          const tag = attribution[entry.change.item_id];
          return (
            <li
              className="pstate-timeline-entry"
              data-test="person-detail-experience"
              data-certainty={entry.certainty}
              data-item-id={entry.change.item_id}
              data-attribution={tag ?? ""}
              key={entry.change.item_id}
            >
              <span className="pstate-timeline-stage">{entry.phaseLabel}</span>
              <span className="pstate-timeline-text">
                <span className="chr-state-mark" aria-hidden="true">{certaintyMark(entry.certainty)}</span>{" "}
                {certaintyLabel(entry.certainty)}
                {entry.fromPhaseLabel ? ` · 自${entry.fromPhaseLabel}` : ""}
                {" · "}
                {entry.dimensionLabel}
                {entry.valueText}
                {"（"}
                {entry.operationLabel}
                {"）"}
              </span>
              {tag ? <AttributionTag attribution={tag} /> : null}
              {entry.reasonText || (sourceFacts.length > 0 && onOpenSource) ? (
                <details className="pstate-evidence">
                  <summary
                    className="public-text-button pstate-evidence-button"
                    data-test="person-state-evidence"
                    aria-label={`查看${entry.phaseLabel}${entry.dimensionLabel}${entry.valueText}的原因与原文依据`}
                  >
                    依据
                  </summary>
                  <span className="pstate-evidence-body">
                    {entry.reasonText ? (
                      <span className="pstate-reason" data-test="person-state-reason">
                        原因：{entry.reasonText}
                      </span>
                    ) : null}
                    {sourceFacts.length > 0 && onOpenSource ? (
                      <button
                        type="button"
                        className="public-text-button pstate-inline-source"
                        data-test="person-detail-source"
                        onClick={() =>
                          onOpenSource({
                            subjectId: person.person_id,
                            subjectName: person.name,
                            itemId: entry.change.item_id,
                            certainty: entry.certainty,
                            sourceFact: sourceFacts[0],
                          })
                        }
                      >
                        查看原文
                      </button>
                    ) : null}
                  </span>
                </details>
              ) : null}
            </li>
          );
        })}
        {timeline.length === 0 ? (
          <li className="pstate-timeline-empty">暂无可定位的经历材料。</li>
        ) : null}
      </ol>

      {related && related.length > 0 ? (
        <>
          <h3 className="pstate-section-title">相关人物与地点</h3>
          <ul className="pstate-related" data-test="person-detail-related">
            {related.map((ref) => (
              <li key={ref.id}>
                <span>{ref.name}</span>
                <small>{ref.relation}</small>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
