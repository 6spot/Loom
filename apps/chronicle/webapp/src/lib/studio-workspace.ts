import type { JobChunk, JobDetail, JobPresentation, JobSummary, ProductionStepName } from "./studio-api";
import { stageLabel } from "./studio-i18n";

export const PRODUCTION_STEPS: Array<{ id: ProductionStepName; label: string; description: string; conditional?: boolean }> = [
  { id: "translation", label: "整章翻译", description: "保留完整语境，生成简体白话正文" },
  { id: "extraction", label: "信息提取", description: "识别人物、地点、事件及随时间变化的状态" },
  { id: "comparison", label: "候选对比", description: "多模型运行时比较各稿，保留差异与采用理由", conditional: true },
  { id: "linking", label: "关联原文与时间", description: "将译文、史料依据和人物阶段关联" },
  { id: "review", label: "内容复核", description: "检查错译、引用、身份与时间，汇总各模型意见" },
  { id: "repair", label: "局部修正", description: "存在可修正问题时处理，再次复核新版本", conditional: true },
];

export function stepLabel(step: string | null | undefined): string {
  return PRODUCTION_STEPS.find((item) => item.id === step)?.label
    ?? (step === "human_revision" || step === "human_repair" ? "人工修订" : "处理记录");
}

export function jobTitle(job: JobPresentation): string {
  const title = job.document?.title;
  return job.job_kind === "narrative" ? `综合历史${title ? ` · ${title}` : ""}` : title || "资料处理任务";
}

export function formatStudioTime(value?: string | null): string {
  if (!value) return "尚未开始";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未记录" : date.toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

export function currentStage(job: JobDetail): string | null {
  return job.stages.find((stage) => ["running", "needs_review", "failed"].includes(stage.status))?.stage
    ?? job.stages.find((stage) => stage.status === "pending")?.stage ?? null;
}

export function jobNextAction(job: JobSummary | JobDetail): string {
  if (job.status === "needs_review") return `等待核对 ${job.open_reviews ?? 0} 项内容`;
  if (job.status === "failed") return "处理未完成，可查看原因并重试";
  if (job.status === "cancelled") return "任务已停止，已保存结果仍可查看";
  if (job.status === "completed") return job.job_kind === "narrative" ? "历史正文已发布" : "来源成果已保存，可用于综合历史";
  if (job.status === "queued") return "等待后台开始处理";
  const stage = "stages" in job ? currentStage(job) : job.current_stage;
  return stage ? `正在${stageLabel(stage)}` : "后台正在处理";
}

export function stepState(chunk: JobChunk, step: ProductionStepName, jobStatus: string): string {
  const entries = chunk.production?.steps.filter((item) => item.step === step) ?? [];
  if (entries.length === 0) return PRODUCTION_STEPS.find((item) => item.id === step)?.conditional ? "conditional" : "pending";
  const round = Math.max(...entries.map((item) => item.round ?? 0));
  const latest = entries.filter((item) => (item.round ?? 0) === round);
  if (latest.some((item) => item.status === "started")) return ["failed", "cancelled"].includes(jobStatus) ? "interrupted" : "started";
  if (latest.some((item) => item.status === "failed")) return "failed";
  if (latest.some((item) => item.status === "invalid")) return "invalid";
  return latest.every((item) => item.status === "completed") ? "completed" : "pending";
}

export function failureAdvice(error: string | null | undefined): string {
  if (!error) return "展开处理记录查看详情。";
  if (/timeout|timed out|超时/i.test(error)) return "模型在全局超时时间内未完成。可重试未完成步骤，或换模型重新处理。";
  if (/budget|attempts exhausted|max_attempts/i.test(error)) return "本次任务的尝试次数或输入容量已用尽。请检查结果后重新创建任务。";
  if (/drift|configuration_changed/i.test(error)) return "任务开始后的模型或处理配置发生了变化。请按当前配置建立新任务。";
  if (/connection|network|HTTP [45]|urlopen|unavailable/i.test(error)) return "模型服务暂时无法完成请求。已保存的步骤仍然保留，可恢复后重试。";
  if (/invalid|validation|schema|校验/i.test(error)) return "返回内容没有通过校验。请查看对应结果与问题说明后处理。";
  return "这一步未能完成。已保存结果保留，可查看详细原因后重试。";
}

export function reviewKind(scope?: string | null, kind?: string | null): string {
  if (scope === "chapter_content") return "译文与提取内容";
  if (scope === "person_state") return "人物阶段与状态";
  if (scope === "narrative") return kind === "facts" ? "多来源事实核对" : "综合历史正文";
  return "身份与事件核对";
}
