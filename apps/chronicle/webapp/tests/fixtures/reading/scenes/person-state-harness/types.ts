// C2-R3-D02 人物阶段资料交互 harness 的本地 DTO 形状（仅测试使用）。
//
// 这里只描述 D02 需要固定的交互状态；真正的机器契约由 T01 的
// `person-state-types.ts` / `person-state-reading.md` 拥有。D02 场景不得
// 冒充真实史料或真实后端，所有数据显式 `synthetic`。

export type Certainty = "clear" | "uncertain";

export type StateDimension = "office" | "title" | "allegiance" | "administration" | "control";

export type PhaseMode = "single" | "process" | "ambiguous" | "unknown";

/** 契约 §2 的原因码；颜色不是唯一信号，原因必须可查。 */
export type ReasonCode =
  | "tenure_unproven"
  | "order_unknown"
  | "source_disagreement"
  | "attribution_uncertain"
  | "evidence_uncertain";

export interface StateItem {
  readonly id: string;
  readonly dimension: StateDimension;
  readonly label: string;
  readonly value: string;
  readonly certainty: Certainty;
  /** 限定语始终可见，例如“奏章自稱已還”“僅此前記載”。 */
  readonly qualification?: string;
  readonly reasonCode?: ReasonCode;
  readonly reasonText?: string;
  readonly sourceLabel: string;
  readonly evidenceQuote?: string;
  readonly evidenceAttribution?: string;
  readonly relatedEvent?: string;
}

export interface ExperienceEntry {
  readonly id: string;
  readonly stage: string;
  readonly text: string;
  readonly sourceLabel: string;
  readonly attribution: "narrator" | "quotation" | "annotation" | "hearsay";
  readonly change?: string;
}

export interface RelatedRef {
  readonly id: string;
  readonly name: string;
  readonly relation: string;
}

export interface StateSubject {
  readonly id: string;
  readonly kind: "person" | "place";
  readonly name: string;
  readonly importance: "primary" | "other";
  readonly phaseMode: PhaseMode;
  readonly phaseNote?: string;
  /** 契约 §2 区分空态：暫無記載 ≠ 階段未明確。 */
  readonly emptyState?: "no_record" | "stage_unknown";
  readonly items: readonly StateItem[];
  readonly experience?: readonly ExperienceEntry[];
  readonly related?: readonly RelatedRef[];
  readonly intro?: string;
}

export interface ReadingStage {
  readonly version: string;
  readonly paragraphId: string;
  readonly phaseId: string;
  readonly timeLabel: string;
  readonly paragraphs: readonly string[];
  readonly contextSubjects: readonly StateSubject[];
  readonly nearby: readonly { readonly label: string; readonly time: string }[];
}

// —— 審核頁（契約 §5）：每章一份階段依據包 ——

export type Assessment = "supported" | "uncertain" | "disputed" | "rejected";

export interface ReviewChange {
  readonly candidateId: string;
  readonly person: string;
  readonly dimension: string;
  readonly before: string;
  readonly after: string;
  readonly stages: string;
  readonly predictedEffect: "current" | "prior" | "ended" | "none";
  readonly sourceLabel: string;
  readonly quote: string;
  readonly attribution: string;
  readonly defaultAssessment: Assessment;
}

export interface ReviewPackage {
  readonly reviewId: string;
  readonly title: string;
  readonly chapterLabel: string;
  readonly sharedEvidence: readonly {
    readonly id: string;
    readonly label: string;
    readonly sourceLabel: string;
    readonly quote: string;
    readonly attribution: string;
  }[];
  readonly changes: readonly ReviewChange[];
}

// —— 人物頁（契約 §8）：三欄職責 ——

export interface PersonPage {
  readonly personId: string;
  readonly name: string;
  readonly overview: string;
  readonly timeAnchor: string;
  readonly experience: readonly ExperienceEntry[];
  readonly currentStage: readonly StateItem[];
  readonly relatedPeople: readonly RelatedRef[];
  readonly relatedPlaces: readonly RelatedRef[];
}
