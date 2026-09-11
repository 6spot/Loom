import type { JobStatus, ReviewDecision, ReviewLinkKind, ReviewStatus, StageStatus } from "./studio-api";

const STATUS_LABELS: Record<string, string> = {
  all: "全部",
  open: "待处理",
  resolved: "已处理",
  dismissed: "已忽略",
  queued: "排队中",
  running: "处理中",
  needs_review: "等待人工审核",
  failed: "失败",
  cancelled: "已取消",
  completed: "已完成",
  pending: "待开始",
  skipped: "已跳过",
  active: "当前版本",
  superseded: "已替换",
  present: "可用",
};

const DECISION_LABELS: Record<ReviewDecision, string> = {
  approve: "审核通过",
  reject: "驳回",
  same_entity: "同一实体",
  not_same: "明确不同",
  uncertain: "证据不足，暂不确定",
  same_occurrence: "同一次事件",
  related_occurrence: "有关联，但不是同一次事件",
};

const LINK_KIND_LABELS: Record<ReviewLinkKind, string> = {
  entity: "实体身份",
  event: "事件发生",
};

const STAGE_LABELS: Record<string, string> = {
  prepare: "准备",
  structure: "结构识别",
  segment: "文本分段",
  extract: "事实抽取",
  assemble: "来源内装配",
  resolve: "跨来源消歧",
  publish: "规范化发布",
  present: "读者呈现",
};

export function studioStatusLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return STATUS_LABELS[value] ?? value;
}

export function jobStatusLabel(value: JobStatus | string | null | undefined): string {
  return studioStatusLabel(value);
}

export function reviewStatusLabel(value: ReviewStatus | "all" | string | null | undefined): string {
  return studioStatusLabel(value);
}

export function stageStatusLabel(value: StageStatus | string | null | undefined): string {
  return studioStatusLabel(value);
}

export function stageLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return STAGE_LABELS[value] ?? value;
}

export function decisionLabel(value: ReviewDecision | string | null | undefined): string {
  if (!value) return "—";
  return DECISION_LABELS[value as ReviewDecision] ?? "其他判断（见技术详情）";
}

export function reviewLinkKindLabel(value: ReviewLinkKind | string | null | undefined): string {
  if (!value) return "—";
  return LINK_KIND_LABELS[value as ReviewLinkKind] ?? value;
}

export function booleanLabel(value: boolean | null | undefined): string {
  if (value === undefined || value === null) return "—";
  return value ? "是" : "否";
}

export function densityLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    represented: "已有表示",
    sparse: "表示稀疏",
    unrepresented: "当前未表示",
  };
  if (!value) return "—";
  return labels[value] ?? value;
}
