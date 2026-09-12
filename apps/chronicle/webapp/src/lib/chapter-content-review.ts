import type { SourceContextDescriptor } from "./studio-api";

export interface ContentIssue {
  id: string;
  type: "processing_error" | "source_uncertainty";
  target: string | Record<string, unknown>;
  message: string;
  evidence: unknown;
}

export interface IssueDisposition {
  issue_id: string;
  disposition: "resolved" | "source_uncertainty" | "rejected";
  rationale: string;
}

export interface ContentPatch {
  path: string;
  before_sha256: string;
  value: unknown;
  op?: "replace" | "add" | "remove";
}

export interface ChapterContentDecisionInput {
  decision: "accept" | "revise" | "reject";
  plan_fingerprint: string;
  candidate_sha256: string | null;
  history_sha256: string;
  rationale: string;
  issue_dispositions: IssueDisposition[];
  patches?: ContentPatch[];
}

export interface ChapterContentReviewData {
  schema: "chronicle.chapter-content-review";
  version: "0.1";
  plan_fingerprint: string;
  candidate_sha256: string | null;
  history_sha256: string;
  request_fingerprint: string;
  pipeline_fingerprint: string;
  step_output_sha256s: string[];
  candidate: Record<string, unknown> | null;
  issues: ContentIssue[];
  history: Array<{ index: number; entry_sha256: string; step: string | null; model: string | null; status: string | null }>;
  history_count: number;
  can_accept: boolean;
  validation_errors: string[];
  source_scope: Record<string, unknown>;
  source: SourceContextDescriptor;
  decision: (ChapterContentDecisionInput & { decision_sha256: string }) | null;
  patch_targets: Array<{ path: string; before_sha256: string; label: string }>;
}

export interface ChapterReviewHistoryPage {
  schema: "chronicle.chapter-review-history";
  version: "0.1";
  review_id: string;
  plan_fingerprint: string;
  entry: number;
  entry_sha256: string;
  text: string;
  has_more: boolean;
  next_cursor: string | null;
}

export interface ContentDraft {
  rationale: string;
  dispositions: Record<string, { disposition: IssueDisposition["disposition"] | ""; rationale: string }>;
  edits: Record<string, string>;
}

export function contentDraftKey(scope: string, reviewId: string, data: ChapterContentReviewData): string {
  return `chronicle.chapter-content-draft.${scope}.${reviewId}.${data.plan_fingerprint}.${data.candidate_sha256 ?? "none"}`;
}

export function pointerValue(candidate: unknown, path: string): unknown {
  let value = candidate;
  for (const encoded of path.slice(1).split("/")) {
    const key = encoded.replace(/~1/g, "/").replace(/~0/g, "~");
    if (Array.isArray(value)) value = value[Number(key)];
    else if (value && typeof value === "object") value = (value as Record<string, unknown>)[key];
    else return undefined;
  }
  return value;
}

export function contentPatches(data: ChapterContentReviewData, edits: Record<string, string>): ContentPatch[] {
  const result: ContentPatch[] = [];
  for (const [path, text] of Object.entries(edits)) {
    const target = data.patch_targets.find((item) => item.path === path);
    if (!target) throw new Error("修改对应的版本已改变，请重新核对当前内容。");
    const isProse = /^\/translation\/blocks\/\d+\/text$/.test(path);
    const value: unknown = isProse ? text : JSON.parse(text);
    if (JSON.stringify(value) === JSON.stringify(pointerValue(data.candidate, path))) continue;
    result.push({ op: "replace", path, before_sha256: target.before_sha256, value });
  }
  return result;
}

export function buildContentDecision(
  data: ChapterContentReviewData, draft: ContentDraft, decision: ChapterContentDecisionInput["decision"],
): ChapterContentDecisionInput {
  if (!draft.rationale.trim()) throw new Error("请填写本次处理依据。");
  const issue_dispositions = data.issues.map((issue): IssueDisposition => {
    const answer = draft.dispositions[issue.id];
    if (!answer?.disposition || !answer.rationale.trim()) throw new Error("请逐项处理所有意见并填写依据。");
    if (answer.disposition === "source_uncertainty" && issue.type !== "source_uncertainty") throw new Error("处理错误不能直接标成史料不确定。");
    return { issue_id: issue.id, disposition: answer.disposition, rationale: answer.rationale.trim() };
  });
  const patches = decision === "reject" ? [] : contentPatches(data, draft.edits);
  if (decision === "accept" && (!data.can_accept || patches.length > 0)) throw new Error("接受只针对校验通过的原版本；有改动请提交修订并重新复核。");
  if (decision === "revise" && (!data.candidate || patches.length === 0)) throw new Error("请先修改需要修订的具体段落或提取记录。");
  return {
    decision, plan_fingerprint: data.plan_fingerprint, candidate_sha256: data.candidate_sha256,
    history_sha256: data.history_sha256, rationale: draft.rationale.trim(), issue_dispositions,
    ...(decision === "revise" ? { patches } : {}),
  };
}
