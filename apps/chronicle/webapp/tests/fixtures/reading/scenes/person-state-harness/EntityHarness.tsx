// C2-R3-D02 獨立人物頁三欄場景（僅測試使用）。
//
// 固定職責：左欄概況與時間定位、中欄按時間的有據經歷、右欄當前階段狀態及相關
// 人物／地點。從正文進入保留階段並可回原位；直接進入不捏造當前年份。

import { useState } from "react";
import { PERSON_PAGE, READING_STAGE } from "./data";
import { AttributionTag, StateItemLine } from "./StateBits";
import "../../../../../src/styles/public-reading.css";
import "../../../../../src/styles/reading-layout.css";
import "./person-state-harness.css";

export default function EntityHarness() {
  const [entry, setEntry] = useState<"reading" | "direct">("reading");
  const [returned, setReturned] = useState(false);

  return (
    <main className="public-site" data-test="entity-harness-scene" data-synthetic="true">
      <header className="site-header">
        <span className="brand">
          <span className="brand-mark">人</span>
          <strong>Chronicle · 人物頁</strong>
        </span>
        <span className="pstate-synthetic-flag" data-test="entity-synthetic-flag">
          合成測試場景 · 非真實內容
        </span>
      </header>

      <section
        className="rpage pstate-entity"
        data-view="entity"
        data-entry={entry}
        data-canonical-id={PERSON_PAGE.personId}
      >
        <div className="pstate-entity-grid">
          <aside className="pstate-entity-left" data-test="entity-left" aria-label="概況與時間定位">
            <h1 data-test="entity-name">{PERSON_PAGE.name}</h1>
            <p className="pstate-intro">{PERSON_PAGE.overview}</p>
            {entry === "reading" ? (
              <p className="pstate-time-anchor" data-test="entity-time-anchor">
                時間定位：{PERSON_PAGE.timeAnchor}（從正文進入 · 保留階段）
              </p>
            ) : (
              <p className="pstate-time-anchor" data-test="entity-time-anchor" data-direct="true">
                直接進入：展示人物整體情況，不擅自選定當前年份。
              </p>
            )}
            <div className="pstate-entity-entry">
              <button
                type="button"
                className="public-text-button"
                data-test="entity-toggle-entry"
                onClick={() => {
                  setEntry((value) => (value === "reading" ? "direct" : "reading"));
                  setReturned(false);
                }}
              >
                切換進入方式
              </button>
              {entry === "reading" ? (
                <button
                  type="button"
                  className="pstate-primary"
                  data-test="entity-return-reading"
                  onClick={() => setReturned(true)}
                >
                  返回閱讀
                </button>
              ) : (
                <button type="button" className="public-text-button" data-test="entity-enter-reading" onClick={() => setEntry("reading")}>
                  進入相關正文
                </button>
              )}
            </div>
            {returned ? (
              <p className="pstate-return-status" role="status" data-test="entity-return-restored">
                已恢復原段 {READING_STAGE.paragraphId} · 偏移 420px（同一 locator，不重排階段）
              </p>
            ) : null}
          </aside>

          <div className="pstate-entity-main" data-test="entity-main" aria-label="按時間的個人經歷">
            <h2>有據經歷</h2>
            <ol className="pstate-timeline" data-test="entity-timeline">
              {PERSON_PAGE.experience.map((entryItem) => (
                <li className="pstate-timeline-entry" data-test="entity-experience" key={entryItem.id}>
                  <span className="pstate-timeline-stage">{entryItem.stage}</span>
                  <span className="pstate-timeline-text">{entryItem.text}</span>
                  <span className="pstate-timeline-meta">
                    <span className="pstate-source">{entryItem.sourceLabel}</span>
                    <AttributionTag attribution={entryItem.attribution} />
                  </span>
                  {entryItem.change ? <span className="pstate-change">變化：{entryItem.change}</span> : null}
                </li>
              ))}
            </ol>
          </div>

          <aside className="pstate-entity-right" data-test="entity-right" aria-label="當前階段狀態">
            <h2>當前階段狀態</h2>
            <ul className="pstate-detail-items">
              {PERSON_PAGE.currentStage.map((item) => (
                <li key={item.id}>
                  <StateItemLine item={item} />
                </li>
              ))}
            </ul>
            <h2>相關人物</h2>
            <ul className="pstate-related" data-test="entity-related-people">
              {PERSON_PAGE.relatedPeople.map((ref) => (
                <li key={ref.id}>
                  {ref.name}
                  <small>{ref.relation}</small>
                </li>
              ))}
            </ul>
            <h2>相關地點</h2>
            <ul className="pstate-related" data-test="entity-related-places">
              {PERSON_PAGE.relatedPlaces.map((ref) => (
                <li key={ref.id}>
                  {ref.name}
                  <small>{ref.relation}</small>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      </section>
    </main>
  );
}
