// C2-R3-D02 共享展示片段（仅测试使用）。
//
// 只演示契约 §2/§8 的两档标记、限定语、原因与归属标签；T11/T12 会按
// `person-state.css` / review 组件实现等价物，本文件不进入生产构建。

import type { Assessment, Certainty, PhaseMode, ReasonCode, StateItem } from "./types";

export const REASON_LABELS: Record<ReasonCode, string> = {
  tenure_unproven: "任期未明",
  order_unknown: "先後未明",
  source_disagreement: "來源分歧",
  attribution_uncertain: "歸屬未定",
  evidence_uncertain: "證據未能確定",
};

export const PHASE_LABELS: Record<PhaseMode, string> = {
  single: "本段單一階段",
  process: "本段多階段過程",
  ambiguous: "多種解釋並存",
  unknown: "階段未明確",
};

export function certaintyLabel(certainty: Certainty): string {
  return certainty === "clear" ? "明確" : "存疑";
}

export function StateMark({ certainty }: { certainty: Certainty }) {
  return (
    <span className="chr-state-mark" data-test="person-state-mark" data-certainty={certainty} aria-hidden="true">
      {certainty === "clear" ? "●" : "○"}
    </span>
  );
}

/** 一条紧凑状态项：标记＋可访问文字＋值＋始终可见的限定语＋按需依据入口。 */
export function StateItemLine({
  item,
  onOpenEvidence,
}: {
  item: StateItem;
  onOpenEvidence?: (item: StateItem) => void;
}) {
  const reason = item.reasonCode ? REASON_LABELS[item.reasonCode] : null;
  const accessible = `${certaintyLabel(item.certainty)}：${item.label}，${item.value}${item.qualification ? `；${item.qualification}` : ""}${reason ? `；原因：${reason}` : ""}`;
  return (
    <span
      className="chr-context-state"
      data-test="person-state-item"
      data-certainty={item.certainty}
      data-dimension={item.dimension}
      data-reason={item.reasonCode ?? ""}
      data-item-id={item.id}
    >
      <StateMark certainty={item.certainty} />
      <span className="public-sr-only">{accessible}。</span>
      <span className="pstate-item-label" aria-hidden="true">
        {item.label}
      </span>
      <span className="pstate-item-value" aria-hidden="true">
        {item.value}
      </span>
      {item.qualification ? (
        <span className="pstate-qualification" data-test="person-state-qualification" aria-hidden="true">
          （{item.qualification}）
        </span>
      ) : null}
      {reason ? (
        <span className="pstate-reason" data-test="person-state-reason" aria-hidden="true">
          {reason}
        </span>
      ) : null}
      {onOpenEvidence ? (
        <button
          type="button"
          className="public-text-button pstate-evidence-button"
          data-test="person-state-evidence"
          aria-label={`查看${item.label}「${item.value}」的原因與原文依據`}
          onClick={() => onOpenEvidence(item)}
        >
          依據
        </button>
      ) : null}
    </span>
  );
}

export function StateLegend() {
  return (
    <p className="pstate-legend" data-test="person-state-legend">
      <span className="chr-context-state" data-certainty="clear">
        <StateMark certainty="clear" />
        <span aria-hidden="true">明確：有已核對來源支持本階段結論</span>
      </span>
      <span className="chr-context-state" data-certainty="uncertain">
        <StateMark certainty="uncertain" />
        <span aria-hidden="true">存疑：有材料但結論／任期／先後／來源尚未確定，仍可查看</span>
      </span>
    </p>
  );
}

export function PhaseBadge({ mode, note }: { mode: PhaseMode; note?: string }) {
  if (mode === "single") return null;
  return (
    <p className="pstate-phase" data-test="person-state-phase" data-phase-mode={mode}>
      {PHASE_LABELS[mode]}
      {note ? <small>{note}</small> : null}
    </p>
  );
}

export function EmptyState({ kind, note }: { kind: "no_record" | "stage_unknown"; note?: string }) {
  return (
    <p className="chr-context-unknown" data-test="person-state-empty" data-empty-kind={kind}>
      {kind === "no_record" ? "暫無記載" : "階段未明確"}
      {note ? <small>{note}</small> : null}
    </p>
  );
}

const ATTRIBUTION_LABELS: Record<string, string> = {
  narrator: "正文·敘述者",
  quotation: "引述",
  annotation: "裴注·注文",
  hearsay: "傳聞",
};

export function AttributionTag({ attribution }: { attribution: string }) {
  return (
    <span className="pstate-attribution" data-test="person-state-attribution" data-attribution={attribution}>
      {ATTRIBUTION_LABELS[attribution] ?? attribution}
    </span>
  );
}

export const EFFECT_LABELS: Record<string, string> = {
  current: "預測：當前身分",
  prior: "預測：此前記載",
  ended: "預測：已結束",
  none: "不作為長期身分",
};

export function EffectBadge({ effect }: { effect: string }) {
  return (
    <span className="pstate-effect" data-test="review-effect" data-effect={effect}>
      {EFFECT_LABELS[effect] ?? effect}
    </span>
  );
}

export const ASSESSMENT_LABELS: Record<Assessment, string> = {
  supported: "支持",
  uncertain: "不確定",
  disputed: "有分歧",
  rejected: "拒絕",
};
