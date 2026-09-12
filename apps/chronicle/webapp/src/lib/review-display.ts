import type {
  ReviewDecision,
  ReviewLinkKind,
  ReviewRecordContext,
  ReviewSourceSegment,
  SourceContextDescriptor,
  SourceEvidenceKind,
} from "./studio-api";

export interface ReviewDisplayTime {
  original_text?: string | null;
  era?: string | null;
  era_year?: number | null;
  season?: string | null;
  month?: number | null;
  day?: number | string | null;
  normalized_year?: number | null;
  precision?: string | null;
  approximate?: boolean;
}

export interface ReviewDisplayEntityRef {
  ref: string;
  name: string;
  type?: string | null;
  role?: string | null;
}

export interface ReviewDisplayEvidence {
  claim_ref: string;
  relation?: string | null;
  predicate?: string | null;
  text: string;
  source_ref?: string | null;
  locator?: Record<string, unknown>;
}

export interface ReviewRecordDisplay {
  kind?: ReviewLinkKind;
  type?: string | null;
  name?: string | null;
  summary?: string | null;
  aliases?: unknown[];
  mentions?: string[];
  time?: ReviewDisplayTime | null;
  participants?: ReviewDisplayEntityRef[];
  places?: ReviewDisplayEntityRef[];
  evidence?: ReviewDisplayEvidence[];
}

export type HumanReviewContext = ReviewRecordContext & { display?: ReviewRecordDisplay };

const DECISION_LABELS: Record<string, string> = {
  approve: "审核通过",
  accept: "接受当前版本",
  revise: "修订后重新复核",
  reject: "驳回",
  same_entity: "同一实体",
  not_same: "明确不同",
  same_occurrence: "同一次事件",
  related_occurrence: "有关联，但不是同一次事件",
  uncertain: "证据不足，暂不确定",
};

const STATUS_LABELS: Record<string, string> = {
  open: "待处理",
  resolved: "已处理",
  dismissed: "已忽略",
  needs_review: "等待人工审核",
  queued: "排队中",
  running: "处理中",
  failed: "失败",
  cancelled: "已取消",
  completed: "已完成",
};

const TYPE_LABELS: Record<string, string> = {
  person: "人物",
  place: "地点",
  polity: "政权",
  organization: "组织",
  army: "军队",
  office: "官职",
  group: "群体",
  political: "政治事件",
  administrative: "行政事件",
  military: "军事事件",
  battle: "战役",
  movement: "移动",
  retreat: "撤退",
  death: "死亡",
  birth: "出生",
  succession: "继承",
  appointment: "任命",
  surrender: "投降",
  diplomatic: "外交事件",
  epidemic: "疫病",
  territorial_change: "领土变化",
  economic: "经济事件",
  cultural: "文化事件",
  other: "其他",
};

const ROLE_LABELS: Record<string, string> = {
  commander: "统帅",
  ally: "盟友",
  defeated_army: "战败方",
  combatant: "参战方",
  participant: "参与者",
  subject: "主体",
  target: "目标",
  attacker: "进攻方",
  defender: "防守方",
  recipient: "接受方",
  surrendering: "投降方",
  retreating: "撤退方",
  sender: "派遣方",
  stationed_force: "驻军",
};

export interface ReviewComparisonRow {
  label: string;
  left: string;
  right: string;
  result: string;
}

export function decisionLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return DECISION_LABELS[value] ?? "其他判断（见技术详情）";
}

export function statusLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return STATUS_LABELS[value] ?? value;
}

export function typeLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return TYPE_LABELS[value] ?? "其他类型";
}

export function roleLabel(value: string | null | undefined): string {
  if (!value) return "参与";
  if (ROLE_LABELS[value]) return ROLE_LABELS[value];
  return /[\u3400-\u9fff]/.test(value) ? value : "其他参与角色";
}

function chineseNumber(value: number | null | undefined): string {
  if (value == null) return "";
  const map: Record<number, string> = {
    1: "元",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
    11: "十一",
    12: "十二",
    13: "十三",
    14: "十四",
    15: "十五",
    16: "十六",
    17: "十七",
    18: "十八",
    19: "十九",
    20: "二十",
  };
  return map[value] ?? String(value);
}

export function formatReviewTime(value: ReviewDisplayTime | null | undefined): string {
  if (!value) return "未提供明确时间";
  const parts: string[] = [];
  if (value.original_text) parts.push(`原文：${value.original_text}`);
  if (value.era && value.era_year) {
    let historical = `${value.era}${chineseNumber(value.era_year)}年`;
    if (value.month) historical += `${chineseNumber(value.month)}月`;
    parts.push(historical);
  }
  if (value.normalized_year != null) {
    parts.push(`${value.approximate ? "约" : ""}公元${value.normalized_year}年`);
  }
  return parts.length ? parts.join(" · ") : "未提供明确时间";
}

export function formatLocator(locator: Record<string, unknown> | null | undefined): string {
  if (!locator) return "未提供定位信息";
  const labels: Array<[string, string]> = [
    ["work", "文献"],
    ["chapter", "篇章"],
    ["volume", "卷"],
    ["section", "节"],
    ["paragraph", "段"],
  ];
  const parts = labels
    .map(([key, label]) => {
      const value = locator[key];
      return value == null || value === "" ? null : `${label}：${String(value)}`;
    })
    .filter(Boolean);
  return parts.length ? parts.join(" · ") : "未提供定位信息";
}

export function signalLabel(value: unknown): string {
  const text = String(value ?? "");
  const known: Record<string, string> = {
    exact_name: "名称完全一致",
    same_type: "类型一致",
    participant_overlap: "参与者存在重合",
    place_overlap: "地点存在重合",
  };
  if (known[text]) return known[text];
  const rules: Array<[RegExp, string]> = [
    [/^compatible event types:\s*(.+)$/i, "事件类型兼容：$1"],
    [/^shared participants:\s*(.+)$/i, "共同参与者：$1"],
    [/^shared places:\s*(.+)$/i, "共同地点：$1"],
    [/^shared (?:surface|name):\s*(.+)$/i, "共同名称：$1"],
  ];
  for (const [pattern, replacement] of rules) {
    if (pattern.test(text)) return text.replace(pattern, replacement);
  }
  return "存在其他系统匹配信号（详见技术详情）";
}

function displayName(context: HumanReviewContext): string {
  return context.display?.name ?? context.record.name ?? context.record.title ?? context.ref;
}

function participantNames(context: HumanReviewContext): string[] {
  return (context.display?.participants ?? []).map((item) => item.name).filter(Boolean);
}

function placeNames(context: HumanReviewContext): string[] {
  return (context.display?.places ?? []).map((item) => item.name).filter(Boolean);
}

function overlap(left: string[], right: string[]): string[] {
  const rightSet = new Set(right);
  return [...new Set(left.filter((value) => rightSet.has(value)))];
}

function compareSimple(left: string, right: string): string {
  if (!left || left === "—" || !right || right === "—") return "信息不足";
  return left === right ? "一致" : "不同";
}

export function comparisonRows(
  linkKind: ReviewLinkKind,
  left: HumanReviewContext,
  right: HumanReviewContext,
): ReviewComparisonRow[] {
  const rows: ReviewComparisonRow[] = [];
  const leftName = displayName(left);
  const rightName = displayName(right);
  rows.push({ label: linkKind === "event" ? "事件名称" : "实体名称", left: leftName, right: rightName, result: compareSimple(leftName, rightName) });

  const leftType = typeLabel(left.display?.type ?? left.record.type);
  const rightType = typeLabel(right.display?.type ?? right.record.type);
  rows.push({ label: "类型", left: leftType, right: rightType, result: compareSimple(leftType, rightType) });

  if (linkKind === "event") {
    const leftTime = formatReviewTime(left.display?.time);
    const rightTime = formatReviewTime(right.display?.time);
    const leftYear = left.display?.time?.normalized_year;
    const rightYear = right.display?.time?.normalized_year;
    rows.push({
      label: "时间",
      left: leftTime,
      right: rightTime,
      result: leftYear != null && rightYear != null ? (leftYear === rightYear ? "公元年一致" : "公元年不同") : "需结合原文判断",
    });

    const leftParticipants = participantNames(left);
    const rightParticipants = participantNames(right);
    const participantOverlap = overlap(leftParticipants, rightParticipants);
    rows.push({
      label: "参与者",
      left: leftParticipants.join("、") || "—",
      right: rightParticipants.join("、") || "—",
      result: participantOverlap.length ? `共同：${participantOverlap.join("、")}` : "未发现名称重合",
    });

    const leftPlaces = placeNames(left);
    const rightPlaces = placeNames(right);
    const placeOverlap = overlap(leftPlaces, rightPlaces);
    rows.push({
      label: "地点",
      left: leftPlaces.join("、") || "—",
      right: rightPlaces.join("、") || "—",
      result: placeOverlap.length ? `共同：${placeOverlap.join("、")}` : "未发现名称重合",
    });
  }

  return rows;
}

export function decisionHelp(decision: ReviewDecision): string {
  const help: Record<ReviewDecision, string> = {
    approve: "接受本次经过核对的内容，继续下一生产阶段。",
    accept: "接受原样且已通过机械校验的当前版本，所有意见逐项留存。",
    revise: "保存局部修订，生成新版本后重新复核。",
    reject: "拒绝本次候选，保留审核记录。",
    same_entity: "两侧证据足以确认是在说同一个人物、地点、组织或其他实体。",
    not_same: "两侧证据明确表明不是同一个实体或不是同一次事件。",
    same_occurrence: "两侧证据足以确认描述的是同一次历史事件。",
    related_occurrence: "两侧事件属于同一历史脉络，但不是同一次具体发生。",
    uncertain: "当前证据不足以安全合并；保留为不确定，不触发合并。",
  };
  return help[decision];
}

export function displayEvidenceCount(display: ReviewRecordDisplay | undefined): number {
  return display?.evidence?.length ?? 0;
}

// ---- C2-R1-T12 review evidence helpers --------------------------------------
// Contract owner: apps/chronicle/docs/review-workflow.md §§4–5. These are
// pure label/format helpers for ReviewEvidencePanel; fetching stays in
// studio-api.ts and draft/queue ownership stays in review-session.ts.

const EVIDENCE_KIND_LABELS: Record<SourceEvidenceKind, string> = {
  direct_claim: "直接引用的事实声明",
  mention: "对象在原文中的出现",
  record_source: "记录来源原文",
  event_context: "参与事件背景",
  translation: "白话译文（辅助参考）",
};

export function evidenceKindLabel(kind: string | null | undefined): string {
  if (!kind) return "其他来源";
  return (EVIDENCE_KIND_LABELS as Record<string, string>)[kind] ?? "其他来源";
}

export function evidenceKindsLabel(kinds: ReadonlyArray<string> | null | undefined): string {
  if (!kinds || kinds.length === 0) return "暂无来源分类";
  return kinds.map((kind) => evidenceKindLabel(kind)).join("、");
}

const UNAVAILABLE_REASONS: Record<string, string> = {
  bundle_without_provenance: "该来源没有记录生产出处，无法定位原文；原有直接引用证据不受影响。",
  no_chapter_anchor: "该记录暂无章节定位锚点，无法展开原文；原有直接引用证据不受影响。",
  legacy_fixture_without_location: "旧材料没有定位信息，无法展开原文；原有直接引用证据不受影响。",
  revision_without_storage: "该版本没有配置原文存储，无法展开原文；原有直接引用证据不受影响。",
};

export function unavailableReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "来源暂不可用";
  return UNAVAILABLE_REASONS[reason] ?? `来源暂不可用（${reason}）`;
}

export function sourceFailureLabel(code: string | null | undefined): string {
  if (code === "source_mismatch") return "原文已变化，定位不再匹配该版本（source_mismatch）。已保留表单和已读材料，可重试。";
  if (code === "source_unavailable") return "原文暂不可用（source_unavailable）。已保留表单和已读材料，可重试。";
  return "原文加载失败。已保留表单和已读材料，可重试。";
}

/** Chapter title preferred; never fall back to an internal id as a title. */
export function evidenceChapterTitle(context: SourceContextDescriptor): string {
  if (context.chapter_title && context.chapter_title.trim()) return context.chapter_title;
  if (context.source_title && context.source_title.trim()) return context.source_title;
  return "未知章节";
}

/** Revision-scoped identity line: same text at another revision stays distinct. */
export function evidenceRevisionLine(context: SourceContextDescriptor): string {
  const short = (value: string | null) => (value ? `${value.slice(0, 12)}…` : "未知");
  return `版本 ${short(context.revision_id)} · 来源 ${short(context.source_sha256)}`;
}

/**
 * Whether a server highlight segment list is safe to render as plain text.
 * The panel always renders segments as React text nodes (never
 * dangerouslySetInnerHTML), so this only guards shape, not content.
 */
export function isRenderableSegments(
  segments: unknown,
): segments is ReviewSourceSegment[] {
  if (!Array.isArray(segments)) return false;
  return segments.every(
    (item) =>
      typeof item === "object" &&
      item !== null &&
      typeof (item as { text?: unknown }).text === "string" &&
      typeof (item as { highlight?: unknown }).highlight === "boolean",
  );
}

/**
 * Staged identity for chapter_pair ends: both sides are unpublished chapter
 * material, never a published canonical. The backend review_mode decides;
 * without it the panel still shows per-context staged provenance.
 */
export function stagedSideLabel(reviewMode: string | null | undefined, side: "left" | "right"): string {
  if (reviewMode === "chapter_pair") {
    return side === "left" ? "左侧待发布章节（staged）" : "右侧待发布章节（staged）";
  }
  return side === "left" ? "已发布侧记录" : "本次来源记录";
}

/** A record without direct Claim evidence still has checkable material. */
export function hasDirectClaimEvidence(context: HumanReviewContext): boolean {
  return (context.display?.evidence?.length ?? 0) > 0;
}
