// C2-R3-T11 组件场景（仅测试使用，不接生产 App/router/API/dist）。
//
// 用真实 `PersonStateItems` / `PersonStateDetails` 组件 + `ReadingContextPanel`
// 的阶段 slot，验证紧凑当时状态、两档明确性、详情／原文／事件入口、空态与窄屏。
// 全部数据为合成示例，不冒充真实后端或已发布内容。

import { useState } from "react";
import ReadingContextPanel from "../../../../../src/components/reading/ReadingContextPanel";
import PersonStateDetails from "../../../../../src/components/reading/PersonStateDetails";
import PersonStateItems, {
  type PersonStateEventRequest,
  type PersonStateSourceRequest,
  type PersonStateStatus,
} from "../../../../../src/components/reading/PersonStateItems";
import PublicDialog from "../../../../../src/components/PublicDialog";
import type { ContextEntityView } from "../../../../../src/lib/reading-types";
import type { PersonSummary } from "../../../../../src/lib/person-state-types";
import {
  ATTRIBUTION_BY_ITEM,
  EVENTS_BY_ITEM,
  INTRO_TEXT,
  PARAGRAPHS,
  PARAGRAPH_ID,
  PEOPLE,
  PHASES,
  PHASE_ID,
  PLACES,
  SYNTHETIC_VERSION,
  ZHOUYU_MORE_ITEMS,
  ZHOUYU_SUMMARY,
} from "./data";
import "../../../../../src/styles/public-reading.css";
import "../../../../../src/styles/reading-layout.css";
import "../../../../../src/styles/reading-context.css";
import "./scene.css";

const SLOT_ENTITIES: readonly ContextEntityView[] = [
  {
    entity_ref: "ref-zhouyu",
    name: "周瑜",
    canonical_id: "ent-zhouyu",
    kind: "person",
    importance: "primary",
    source_anchor_ids: ["anc-zhouyu"],
    event_roles: [],
  },
];

const STATUS_CONTROLS: readonly PersonStateStatus[] = ["ready", "loading", "error", "empty"];

export default function PersonStatesScene({ mode = "reading" }: { mode?: "reading" | "slot" }) {
  const [status, setStatus] = useState<PersonStateStatus>("ready");
  const [people, setPeople] = useState<readonly PersonSummary[]>(PEOPLE);
  const [detail, setDetail] = useState<PersonSummary | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [lastAction, setLastAction] = useState("");

  const handleSource = (request: PersonStateSourceRequest) => {
    setLastAction(`source:${request.subjectId}:${request.itemId}:${request.sourceFact.fact_ref}`);
  };
  const handleEvent = (request: PersonStateEventRequest) => {
    setLastAction(`event:${request.subjectId}:${request.itemId}:${request.eventRef}`);
  };
  const loadMoreIdentities = (person: PersonSummary) => {
    if (person.person_id !== ZHOUYU_SUMMARY.person_id) return;
    setPeople((current) =>
      current.map((entry) =>
        entry.person_id === person.person_id
          ? { ...entry, identities: [...entry.identities, ...ZHOUYU_MORE_ITEMS], has_more_identities: false }
          : entry,
      ),
    );
  };

  const stateBlock = (
    <PersonStateItems
      people={people}
      places={PLACES}
      phases={PHASES}
      status={status}
      onOpenDetails={setDetail}
      onOpenSource={handleSource}
      onOpenEvent={handleEvent}
      eventsByItem={EVENTS_BY_ITEM}
      onRetry={() => setStatus("ready")}
      onLoadMoreIdentities={loadMoreIdentities}
    />
  );

  if (mode === "slot") {
    return (
      <main className="public-site" data-test="person-state-slot-scene" data-synthetic="true">
        <div data-test="person-states-slot-probe">
          <ReadingContextPanel
            entities={SLOT_ENTITIES}
            variant="column"
            unitId="ru_0123456789abcdef01234567"
            stage={stateBlock}
          />
        </div>
      </main>
    );
  }

  return (
    <main className="public-site" data-test="person-state-reading-scene" data-synthetic="true">
      <header className="site-header">
        <span className="brand">
          <span className="brand-mark">史</span>
          <strong>Chronicle</strong>
        </span>
        <span className="pstate-synthetic-flag" data-test="person-state-synthetic-flag">
          合成测试场景 · 非真实内容
        </span>
      </header>

      <section
        className="rpage person-state-reading"
        data-test="person-state-stage"
        data-view="history-reading"
        data-version={SYNTHETIC_VERSION}
        data-active-paragraph={PARAGRAPH_ID}
        data-active-phase={PHASE_ID}
      >
        <div className="rpage-compact" data-test="person-state-compact">
          <span className="rpage-compact-time" data-test="reading-time-label">
            建安十三年 · 赤壁前后
          </span>
          <div className="rpage-tools">
            <button
              type="button"
              className="public-text-button pstate-scene-mobile-entry"
              data-test="person-state-mobile-entry"
              aria-haspopup="dialog"
              aria-expanded={mobileOpen}
              onClick={() => setMobileOpen(true)}
            >
              人物地点
            </button>
          </div>
        </div>

        <div className="rpage-grid">
          <nav className="rpage-axis-column history-axis" aria-label="历史时间轴" data-test="person-state-axis">
            <ol>
              <li>
                <button type="button">
                  <span>建安十一年</span>
                  <small>江夏之战</small>
                </button>
              </li>
              <li>
                <button type="button" aria-current="location">
                  <span>建安十三年</span>
                  <small>赤壁之战</small>
                </button>
              </li>
              <li>
                <button type="button">
                  <span>建安十四年</span>
                  <small>南郡之战</small>
                </button>
              </li>
            </ol>
          </nav>

          <div className="rpage-main history-body" data-test="person-state-body" aria-label="历史正文">
            {PARAGRAPHS.map((text, index) => (
              <p className="pstate-scene-paragraph" data-test="person-state-paragraph" key={index}>
                {text}
              </p>
            ))}
          </div>

          <aside
            className="rpage-context-column"
            data-test="person-state-context-column"
            aria-label="此时的人物与地点"
          >
            {stateBlock}
          </aside>
        </div>
      </section>

      <section className="pstate-scene-controls" data-test="person-state-controls" aria-label="合成状态控制">
        <span>合成状态：</span>
        {STATUS_CONTROLS.map((state) => (
          <button
            type="button"
            key={state}
            className="public-text-button"
            data-test={`person-state-set-${state}`}
            aria-pressed={status === state}
            onClick={() => setStatus(state)}
          >
            {state}
          </button>
        ))}
      </section>

      <output className="public-sr-only" data-test="person-states-last-action">
        {lastAction}
      </output>

      {mobileOpen ? (
        <PublicDialog
          title="此时地点与人物"
          onClose={() => setMobileOpen(false)}
          closeTestId="person-state-mobile-close"
        >
          <div data-test="person-state-mobile-panel">{stateBlock}</div>
        </PublicDialog>
      ) : null}

      {detail ? (
        <PublicDialog title={`${detail.name} · 人物详情`} onClose={() => setDetail(null)} closeTestId="person-detail-close">
          <div data-test="person-detail-dialog" data-subject-id={detail.person_id}>
            <PersonStateDetails
              person={detail}
              phases={PHASES}
              intro={INTRO_TEXT}
              changes={detail.changes}
              related={[
                { id: "ent-sunquan", name: "孙权", relation: "授官者" },
                { id: "ent-nanjun", name: "南郡", relation: "本段领郡" },
              ]}
              attributionByItem={ATTRIBUTION_BY_ITEM}
              onOpenSource={handleSource}
            />
          </div>
        </PublicDialog>
      ) : null}
    </main>
  );
}
