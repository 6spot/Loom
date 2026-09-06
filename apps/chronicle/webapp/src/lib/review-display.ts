import type { ReviewDecision, ReviewLinkKind, ReviewRecordContext } from "./studio-api";

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
