// C2-R3-D02 章階段依據包審核場景（僅測試使用）。
//
// 固定「每自然章一份階段依據包、包內按人物看變化、共用階段依據單列、批量確認＋
// 逐項例外、頁底保存並下一項、錯誤保留草稿」的交互；不掛接 Studio 路由或真實 API。

import { useMemo, useState } from "react";
import { REVIEW_PACKAGE } from "./data";
import type { Assessment, ReviewPackage } from "./types";
import { ASSESSMENT_LABELS, AttributionTag, EffectBadge } from "./StateBits";
import "../../../../../src/styles/public-reading.css";
import "./person-state-harness.css";

const PACKAGES: readonly ReviewPackage[] = [
  REVIEW_PACKAGE,
  {
    ...REVIEW_PACKAGE,
    reviewId: "synth-review-0002",
    chapterLabel: "合成示例章 · 江夏前後",
  },
];

interface Draft {
  readonly assessment: Assessment;
  readonly rationale: string;
}

const ASSESSMENTS: readonly Assessment[] = ["supported", "uncertain", "disputed", "rejected"];

export default function ReviewHarness() {
  const [packageIndex, setPackageIndex] = useState(0);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [skipped, setSkipped] = useState<readonly string[]>([]);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "error" | "saved">("idle");
  const [simulateError, setSimulateError] = useState(false);
  const [lastAction, setLastAction] = useState("");

  const pkg = PACKAGES[packageIndex];
  const draftFor = (candidateId: string, fallback: Assessment): Draft =>
    drafts[candidateId] ?? { assessment: fallback, rationale: "" };

  const exceptionCount = useMemo(
    () => Object.keys(drafts).filter((id) => drafts[id].assessment !== "supported" || drafts[id].rationale.trim().length > 0).length,
    [drafts],
  );
  const batchCovered = pkg.changes.length - exceptionCount;
  const byPerson = useMemo(() => {
    const groups = new Map<string, typeof pkg.changes>();
    for (const change of pkg.changes) {
      groups.set(change.person, [...(groups.get(change.person) ?? []), change]);
    }
    return [...groups.entries()];
  }, [pkg]);

  const setDraft = (candidateId: string, fallback: Assessment, patch: Partial<Draft>) =>
    setDrafts((current) => ({ ...current, [candidateId]: { ...draftFor(candidateId, fallback), ...patch } }));

  const batchConfirmSupported = () => {
    setDrafts({});
    setLastAction(`batch:${pkg.reviewId}`);
    setSaveState("idle");
  };

  const saveAndNext = () => {
    if (saveState === "saving") return;
    setSaveState("saving");
    if (simulateError) {
      window.setTimeout(() => {
        setSaveState("error");
        setLastAction(`save-error:${pkg.reviewId}`);
      }, 120);
      return;
    }
    window.setTimeout(() => {
      setSaveState("saved");
      setLastAction(`saved:${pkg.reviewId}`);
      setDrafts({});
      setSkipped([]);
      setPackageIndex((index) => (index + 1) % PACKAGES.length);
    }, 120);
  };

  return (
    <main className="public-site" data-test="review-harness-scene" data-synthetic="true">
      <header className="site-header">
        <span className="brand">
          <span className="brand-mark">審</span>
          <strong>Chronicle Studio · 階段依據審核</strong>
        </span>
        <span className="pstate-synthetic-flag" data-test="review-synthetic-flag">
          合成測試場景 · 非真實審核
        </span>
      </header>

      <section className="pstate-review" data-test="review-panel" data-review-id={pkg.reviewId}>
        <p className="rpage-eyebrow">每章一份階段依據包</p>
        <h1 data-test="review-title">
          {pkg.title} · {pkg.chapterLabel}
        </h1>
        <p className="pstate-review-intro">
          按人物讀變化；共用階段依據單列；批量確認只記錄對具體候選的評估，不建立人物等價，也不代表永久在任。
        </p>

        <section className="pstate-review-shared" data-test="review-shared-evidence" aria-label="共用階段依據">
          <h2>共用階段依據</h2>
          <ol>
            {pkg.sharedEvidence.map((evidence) => (
              <li key={evidence.id} data-test="review-shared-item">
                <span className="pstate-source">{evidence.sourceLabel}</span>
                <blockquote>{evidence.quote}</blockquote>
                <AttributionTag attribution={evidence.attribution} />
              </li>
            ))}
          </ol>
        </section>

        <div className="pstate-review-batch" data-test="review-batch">
          <button type="button" className="public-text-button" data-test="review-batch-confirm" onClick={batchConfirmSupported}>
            批量確認為「支持」
          </button>
          <span data-test="review-batch-count">
            批量覆蓋 {batchCovered} 項，逐項例外 {exceptionCount} 項（共 {pkg.changes.length} 項）
          </span>
        </div>

        {byPerson.map(([person, changes]) => (
          <section className="pstate-review-person" data-test="review-person" data-person={person} key={person}>
            <h2>{person}</h2>
            <ul>
              {changes.map((change) => {
                const draft = draftFor(change.candidateId, change.defaultAssessment);
                const isException = draft.assessment !== "supported" || draft.rationale.trim().length > 0;
                return (
                  <li
                    className="pstate-review-change"
                    data-test="review-change"
                    data-candidate-id={change.candidateId}
                    data-assessment={draft.assessment}
                    data-exception={isException ? "true" : "false"}
                    key={change.candidateId}
                  >
                    <div className="pstate-review-change-head">
                      <span className="pstate-review-dimension">{change.dimension}</span>
                      <span className="pstate-review-flow">
                        {change.before} → {change.after}
                      </span>
                      <EffectBadge effect={change.predictedEffect} />
                    </div>
                    <p className="pstate-review-stages">適用階段：{change.stages}</p>
                    <blockquote>{change.quote}</blockquote>
                    <p className="pstate-evidence-meta">
                      <span className="pstate-source">{change.sourceLabel}</span>
                      <AttributionTag attribution={change.attribution} />
                    </p>
                    <div className="pstate-review-decision">
                      <label>
                        例外評估
                        <select
                          data-test="review-assessment"
                          value={draft.assessment}
                          onChange={(event) =>
                            setDraft(change.candidateId, change.defaultAssessment, {
                              assessment: event.target.value as Assessment,
                            })
                          }
                        >
                          {ASSESSMENTS.map((assessment) => (
                            <option value={assessment} key={assessment}>
                              {ASSESSMENT_LABELS[assessment]}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        理由
                        <input
                          type="text"
                          data-test="review-rationale"
                          value={draft.rationale}
                          placeholder="例外或暫時跳過的理由"
                          onChange={(event) =>
                            setDraft(change.candidateId, change.defaultAssessment, { rationale: event.target.value })
                          }
                        />
                      </label>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}

        {saveState === "error" ? (
          <div className="pstate-save-error" role="alert" data-test="review-save-error">
            <p>保存失敗（模擬 409）：草稿已保留，請核對伺服端狀態後重試。</p>
            <button type="button" className="public-text-button" data-test="review-save-retry" onClick={saveAndNext}>
              重試保存
            </button>
          </div>
        ) : null}
        {saveState === "saved" ? (
          <p className="pstate-saved" role="status" data-test="review-saved">
            已保存並切換下一項；切項不沿用上一項草稿值。
          </p>
        ) : null}
        {skipped.length ? (
          <p className="pstate-skipped" role="status" data-test="review-skipped">
            本輪仍有 {skipped.length} 項暫時跳過，仍待審。
          </p>
        ) : null}

        <div className="pstate-review-controls" data-test="review-controls">
          <label className="pstate-simulate">
            <input
              type="checkbox"
              data-test="review-simulate-error"
              checked={simulateError}
              onChange={(event) => setSimulateError(event.target.checked)}
            />
            模擬保存失敗（409／503）
          </label>
          <span data-test="review-last-action">{lastAction}</span>
        </div>

        <div className="nr-actions" data-test="review-action-bar">
          <button type="button" className="public-text-button" data-test="review-return" onClick={() => setLastAction("return")}>
            返回隊列
          </button>
          <button
            type="button"
            className="public-text-button"
            data-test="review-skip"
            onClick={() => {
              setSkipped((current) => [...current, pkg.reviewId]);
              setLastAction(`skip:${pkg.reviewId}`);
              setPackageIndex((index) => (index + 1) % PACKAGES.length);
            }}
          >
            暫時跳過
          </button>
          <button type="button" className="pstate-primary" data-test="review-save-next" onClick={saveAndNext}>
            {saveState === "saving" ? "保存中…" : "保存並下一項"}
          </button>
        </div>
      </section>
    </main>
  );
}
