import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import StructuredResult from "../src/components/studio/StructuredResult";
import { failureAdvice, stepState } from "../src/lib/studio-workspace";
import type { JobChunk } from "../src/lib/studio-api";
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
});
