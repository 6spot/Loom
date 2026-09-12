// C2-R3-D02 阅读页交互场景（仅测试使用）。
//
// 沿用正式 HistoryPage 的左轴／中正文／右栏骨架与 `.rpage`、`.chr-context-*`
// 样式；紧凑行、人物详情、依据与回焦行为是本任务要固定的 D02 设计。
// 全部数据显式合成，不是真实后端或已发布内容。

import { useState } from "react";
import PublicDialog from "../../../../../src/components/PublicDialog";
import { READING_STAGE } from "./data";
import type { StateItem, StateSubject } from "./types";
import {
  AttributionTag,
  certaintyLabel,
  EmptyState,
  PhaseBadge,
  StateItemLine,
  StateLegend,
} from "./StateBits";
import "../../../../../src/styles/public-reading.css";
import "../../../../../src/styles/reading-layout.css";
import "../../../../../src/styles/reading-context.css";
import "./person-state-harness.css";

type ContextState = "ready" | "loading" | "error" | "empty";

function SubjectBlock({
  subject,
  onOpenDetail,
  onOpenEvidence,
}: {
  subject: StateSubject;
  onOpenDetail: (subject: StateSubject) => void;
  onOpenEvidence: (subject: StateSubject, item: StateItem) => void;
}) {
  const canOpenDetail = Boolean(subject.intro || (subject.experience && subject.experience.length) || subject.kind === "person");
  return (
    <li
      className="chr-context-item"
      data-test="person-state-subject"
      data-kind={subject.kind}
      data-importance={subject.importance}
      data-phase-mode={subject.phaseMode}
      data-subject-id={subject.id}
      data-has-empty-state={subject.emptyState ?? ""}
    >
      <div className="pstate-subject-row">
        {canOpenDetail ? (
          <button
            type="button"
            className="pstate-name-button"
            data-test="person-state-view-detail"
            aria-label={`查看${subject.name}的人物詳情`}
            onClick={() => onOpenDetail(subject)}
          >
            <span className="chr-context-name" data-test="person-state-name">
              {subject.name}
            </span>
          </button>
        ) : (
          <span className="chr-context-name" data-test="person-state-name">
            {subject.name}
          </span>
        )}
        {subject.emptyState ? (
          <EmptyState kind={subject.emptyState} note={subject.phaseNote} />
        ) : (
          <span className="chr-context-states">
            {subject.items.map((item) => (
              <StateItemLine key={item.id} item={item} onOpenEvidence={(chosen) => onOpenEvidence(subject, chosen)} />
            ))}
          </span>
        )}
      </div>
      <PhaseBadge mode={subject.phaseMode} note={subject.phaseNote} />
    </li>
  );
}

function ContextBody({
  contextState,
  onOpenDetail,
  onOpenEvidence,
  onRetry,
}: {
  contextState: ContextState;
  onOpenDetail: (subject: StateSubject) => void;
  onOpenEvidence: (subject: StateSubject, item: StateItem) => void;
  onRetry: () => void;
}) {
  if (contextState === "loading") {
    return (
      <p className="pstate-loading" data-test="person-state-loading" role="status">
        正在載入本段人物與地點資料…
      </p>
    );
  }
  if (contextState === "error") {
    return (
      <div className="pstate-error" data-test="person-state-error" role="alert">
        <p>本段人物資料暫時無法讀取；已讀正文保留，不沿用上一段身分。</p>
        <button type="button" className="public-text-button" data-test="person-state-retry" onClick={onRetry}>
          重試
        </button>
      </div>
    );
  }
  if (contextState === "empty") {
    return (
      <p className="chr-context-empty" data-test="person-state-empty-section">
        本段還沒有關聯人物或地點。
      </p>
    );
  }
  const people = READING_STAGE.contextSubjects.filter((subject) => subject.kind === "person");
  const places = READING_STAGE.contextSubjects.filter((subject) => subject.kind === "place");
  const groups: Array<{ key: string; label: string; subjects: StateSubject[] }> = [
    { key: "person", label: "當前人物", subjects: people },
    { key: "place", label: "當時地點", subjects: places },
  ];
  return (
    <>
      <StateLegend />
      {groups.map((group) => (
        <section className="chr-context-group" data-test="person-state-group" data-group={group.key} key={group.key}>
          <h3 className="chr-context-group-title">{group.label}</h3>
          <ul className="chr-context-list">
            {group.subjects.map((subject) => (
              <SubjectBlock
                key={subject.id}
                subject={subject}
                onOpenDetail={onOpenDetail}
                onOpenEvidence={onOpenEvidence}
              />
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}

function PersonDetailDialog({ subject, onClose }: { subject: StateSubject; onClose: () => void }) {
  const [fullSourceId, setFullSourceId] = useState<string | null>(null);
  return (
    <PublicDialog title={`${subject.name} · 人物詳情`} onClose={onClose} closeTestId="person-detail-close">
      <div data-test="person-detail-dialog" data-subject-id={subject.id}>
        {subject.intro ? <p className="pstate-intro">{subject.intro}</p> : null}
        <h3 className="pstate-section-title">當時身分（本段）</h3>
        <ul className="pstate-detail-items">
          {subject.items.map((item) => (
            <li key={item.id}>
              <StateItemLine item={item} />
            </li>
          ))}
        </ul>
        <h3 className="pstate-section-title">有據經歷與變化</h3>
        <ol className="pstate-timeline" data-test="person-detail-timeline">
          {(subject.experience ?? []).map((entry) => (
            <li
              className="pstate-timeline-entry"
              data-test="person-detail-experience"
              data-attribution={entry.attribution}
              key={entry.id}
            >
              <span className="pstate-timeline-stage">{entry.stage}</span>
              <span className="pstate-timeline-text">{entry.text}</span>
              <span className="pstate-timeline-meta">
                <span className="pstate-source">{entry.sourceLabel}</span>
                <AttributionTag attribution={entry.attribution} />
              </span>
              {entry.change ? <span className="pstate-change">變化：{entry.change}</span> : null}
              <button
                type="button"
                className="public-text-button pstate-inline-source"
                data-test="person-detail-source"
                onClick={() => setFullSourceId(entry.id)}
              >
                查看原文
              </button>
            </li>
          ))}
          {(subject.experience ?? []).length === 0 ? (
            <li className="pstate-timeline-empty">暫無可定位的經歷材料。</li>
          ) : null}
        </ol>
        {subject.related && subject.related.length ? (
          <>
            <h3 className="pstate-section-title">相關人物與地點</h3>
            <ul className="pstate-related" data-test="person-detail-related">
              {subject.related.map((ref) => (
                <li key={ref.id}>
                  {ref.name}
                  <small>{ref.relation}</small>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        {fullSourceId ? (
          <p className="pstate-source-window" data-test="person-detail-source-window">
            原文窗口（合成示例）：本段只讀取使用者打開的那一條材料，不預取全章。
          </p>
        ) : null}
      </div>
    </PublicDialog>
  );
}

function EvidenceDialog({ subject, item, onClose }: { subject: StateSubject; item: StateItem; onClose: () => void }) {
  const [wholeChapter, setWholeChapter] = useState(false);
  const [eventOpened, setEventOpened] = useState(false);
  return (
    <PublicDialog title={`依據 · ${item.value}`} onClose={onClose} closeTestId="person-state-evidence-close">
      <div data-test="person-state-evidence-dialog" data-item-id={item.id} data-certainty={item.certainty}>
        <p className="pstate-evidence-subject">
          {subject.name} · {item.label} · {certaintyLabel(item.certainty)}
        </p>
        <h3 className="pstate-section-title">為何這樣判定</h3>
        <p className="pstate-evidence-reason" data-test="evidence-reason">
          {item.reasonText ?? "本階段結論有已核對來源直接支持。"}
        </p>
        {item.qualification ? (
          <p className="pstate-evidence-qualification" data-test="evidence-qualification">
            限定語：{item.qualification}
          </p>
        ) : null}
        <h3 className="pstate-section-title">原文窗口</h3>
        <blockquote className="pstate-quote" data-test="evidence-quote">
          {item.evidenceQuote ?? "（暫無引文）"}
        </blockquote>
        <p className="pstate-evidence-meta">
          <span className="pstate-source">{item.sourceLabel}</span>
          {item.evidenceAttribution ? <AttributionTag attribution={item.evidenceAttribution} /> : null}
        </p>
        <div className="pstate-evidence-actions">
          <button
            type="button"
            className="public-text-button"
            data-test="evidence-whole-chapter"
            aria-expanded={wholeChapter}
            onClick={() => setWholeChapter((value) => !value)}
          >
            查看整章
          </button>
          {item.relatedEvent ? (
            <button
              type="button"
              className="public-text-button"
              data-test="evidence-related-event"
              onClick={() => setEventOpened(true)}
            >
              相關事件：{item.relatedEvent}
            </button>
          ) : null}
        </div>
        {wholeChapter ? (
          <p className="pstate-source-window" data-test="evidence-whole-chapter-text">
            整章窗口（合成示例）：按需載入，不改當前閱讀階段，也不改變本段人物。
          </p>
        ) : null}
        {eventOpened ? (
          <p className="pstate-source-window" data-test="evidence-event-note">
            事件入口沿用本段快照，僅供查看；開啟它不改變當前閱讀階段。
          </p>
        ) : null}
      </div>
    </PublicDialog>
  );
}

export default function ReadingHarness() {
  const [contextState, setContextState] = useState<ContextState>("ready");
  const [detail, setDetail] = useState<StateSubject | null>(null);
  const [evidence, setEvidence] = useState<{ subject: StateSubject; item: StateItem } | null>(null);
  const [activeParagraph] = useState(READING_STAGE.paragraphId);
  const [eventPreview, setEventPreview] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  const openDetail = (subject: StateSubject) => setDetail(subject);
  const openEvidence = (subject: StateSubject, item: StateItem) => setEvidence({ subject, item });

  const contextBody = (
    <ContextBody
      contextState={contextState}
      onOpenDetail={openDetail}
      onOpenEvidence={openEvidence}
      onRetry={() => setContextState("ready")}
    />
  );

  return (
    <main className="public-site" data-test="person-state-reading-scene" data-synthetic="true">
      <header className="site-header">
        <span className="brand">
          <span className="brand-mark">史</span>
          <strong>Chronicle</strong>
        </span>
        <span className="pstate-synthetic-flag" data-test="person-state-synthetic-flag">
          合成測試場景 · 非真實內容
        </span>
      </header>

      <section
        className="rpage person-state-reading"
        data-test="person-state-stage"
        data-view="history-reading"
        data-version={READING_STAGE.version}
        data-active-paragraph={activeParagraph}
        data-active-phase={READING_STAGE.phaseId}
      >
        <div className="rpage-compact" data-test="person-state-compact">
          <span className="rpage-compact-time" data-test="reading-time-label">
            {READING_STAGE.timeLabel}
          </span>
          <span className="public-sr-only" data-test="reading-active-paragraph">
            當前段落：{activeParagraph}
          </span>
          <div className="rpage-tools">
            <button
              type="button"
              className="public-text-button pstate-mobile-entry"
              data-test="person-state-mobile-entry"
              aria-haspopup="dialog"
              onClick={() => setMobileOpen(true)}
            >
              人物地點
            </button>
          </div>
        </div>

        <div className="rpage-grid">
          <nav className="rpage-axis-column history-axis" aria-label="歷史時間軸" data-test="person-state-axis">
            <ol>
              {READING_STAGE.nearby.map((entry, index) => (
                <li key={entry.label}>
                  <button type="button" aria-current={index === 1 ? "location" : undefined}>
                    <span>{entry.time}</span>
                    <small>{entry.label}</small>
                  </button>
                </li>
              ))}
            </ol>
          </nav>

          <div className="rpage-main history-body" data-test="person-state-body" aria-label="歷史正文">
            {READING_STAGE.paragraphs.map((text, index) => (
              <p className="history-paragraph" data-test="person-state-paragraph" key={index}>
                {text}
              </p>
            ))}
            <nav className="reading-nearby" aria-label="附近的重要事件">
              <h2>讀到這裡</h2>
              <ol>
                {READING_STAGE.nearby.map((entry) => (
                  <li key={entry.label}>
                    <button
                      type="button"
                      data-test="person-state-nearby-event"
                      onMouseEnter={() => setEventPreview(entry.label)}
                      onFocus={() => setEventPreview(entry.label)}
                      onMouseLeave={() => setEventPreview(null)}
                    >
                      {entry.label}
                      <small>{entry.time}</small>
                    </button>
                  </li>
                ))}
              </ol>
              {eventPreview ? (
                <p className="pstate-event-preview" data-test="person-state-event-preview">
                  預覽：{eventPreview}（懸停不改變當前閱讀階段）
                </p>
              ) : null}
            </nav>
          </div>

          <aside className="rpage-context-column" data-test="person-state-context-column" aria-label="此時的人物與地點">
            <div className="chr-context-panel" data-test="person-state-context">
              {contextBody}
            </div>
          </aside>
        </div>
      </section>

      <section className="pstate-controls" data-test="person-state-controls" aria-label="合成狀態控制">
        <span>合成狀態：</span>
        {(["ready", "loading", "error", "empty"] as ContextState[]).map((state) => (
          <button
            type="button"
            key={state}
            className="public-text-button"
            data-test={`person-state-set-${state}`}
            aria-pressed={contextState === state}
            onClick={() => setContextState(state)}
          >
            {state}
          </button>
        ))}
      </section>

      {mobileOpen ? (
        <PublicDialog title="此時地點與人物" onClose={() => setMobileOpen(false)} closeTestId="person-state-mobile-close">
          <div id="pstate-mobile-panel" data-test="person-state-mobile-panel">
            {contextBody}
          </div>
        </PublicDialog>
      ) : null}

      {detail ? <PersonDetailDialog subject={detail} onClose={() => setDetail(null)} /> : null}
      {evidence ? (
        <EvidenceDialog subject={evidence.subject} item={evidence.item} onClose={() => setEvidence(null)} />
      ) : null}
    </main>
  );
}
