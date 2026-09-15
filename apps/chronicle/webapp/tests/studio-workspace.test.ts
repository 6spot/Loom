import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import StructuredResult from "../src/components/studio/StructuredResult";
import { actionEnabled, currentWorkspaceStep, failureAdvice, hasAuthoritativeActions, jobAction, jobNextAction, jobSourceCount, jobSteps, stepState } from "../src/lib/studio-workspace";
import type { JobChunk, JobDetail } from "../src/lib/studio-api";
import candidate from "../../ingestion/fixtures/c2r3-contract/candidate-valid.json";

describe("saved production results", () => {
  it("resolves actual temp references and retains source qualifications", () => {
    const value = structuredClone(candidate);
    value.person_states.facts[0].qualification = "recommendation";
    const html = renderToStaticMarkup(createElement(StructuredResult, { value: { parsed: value } }));
    const primary = html.split("<details")[0];
    expect(primary).toContain("周瑜");
    expect(primary).toContain("建威中郎將");
    expect(primary).toContain("推荐");
    expect(primary).toContain("授瑜建威中郎將");
    expect(primary).not.toContain("ent_002");
    expect(primary).not.toContain("ph_001");
  });

  it("does not mark interrupted or invalid model opinions as complete", () => {
    const chunk = { production: { steps: [
      { step: "review", slot: "a", round: 0, status: "completed" },
      { step: "review", slot: "b", round: 0, status: "started" },
    ] } } as JobChunk;
    expect(stepState(chunk, "review", "running")).toBe("started");
    expect(stepState(chunk, "review", "failed")).toBe("interrupted");
    chunk.production!.steps[1].status = "invalid";
    expect(stepState(chunk, "review", "needs_review")).toBe("invalid");
    chunk.production!.steps.push({ step: "review", slot: "a", round: 1, status: "completed" });
    expect(stepState(chunk, "review", "needs_review")).toBe("completed");
    expect(stepState(chunk, "comparison", "running")).toBe("conditional");
  });

  it("explains timeout and configuration drift without offering a local timeout", () => {
    expect(failureAdvice("request timed out")).toContain("全局超时");
    expect(failureAdvice("model_configuration_changed")).toContain("新任务");
    expect(failureAdvice("StepBudgetExhausted")).toContain("用尽");
  });

  it("uses the T07 task graph and control-plane actions for readable progress", () => {
    const job = {
      job_id: "job",
      revision_id: "revision",
      status: "needs_review",
      attempt: 1,
      max_attempts: 8,
      open_reviews: 1,
      error: null,
      current_step: { key: "resolve", machine_key: "resolve", label: "来源核对", status: "needs_review", failure_reason: null },
      task: { type: "chapter", machine_key: "chapter", label: "章节生产任务", title: "武帝紀", source_count: 1 },
      source: { revision_id: "revision", revision_no: 3, source_count: 1, relationship: "immutable_revision" },
      step_graph: { current_step: "resolve", dependencies: { resolve: ["assemble"] }, steps: [
        { key: "assemble", machine_key: "assemble", label: "组装草稿", status: "completed", dependencies: ["extract"] },
        { key: "resolve", machine_key: "resolve", label: "来源核对", status: "needs_review", dependencies: ["assemble"] },
      ] },
      actions: [
        { key: "resume", label: "继续生产", available: false, enabled: false, reason: "仍有 1 项审核未完成" },
        { key: "cancel", label: "取消任务", available: true, enabled: true, reason: null },
      ],
    } as JobDetail;
    expect(jobSteps(job).map((step) => step.key)).toEqual(["assemble", "resolve"]);
    expect(currentWorkspaceStep(job)?.label).toBe("来源核对");
    expect(jobNextAction(job)).toBe("等待核对 1 项内容");
    expect(jobSourceCount(job)).toBe(1);
    expect(hasAuthoritativeActions(job)).toBe(true);
    expect(actionEnabled(job, "resume")).toBe(false);
    expect(actionEnabled(job, "cancel")).toBe(true);
    expect(jobAction(job, "resume")?.reason).toBe("仍有 1 项审核未完成");
  });
});
