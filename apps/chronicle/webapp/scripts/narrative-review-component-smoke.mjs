#!/usr/bin/env node
// Production React routes + an isolated browser + explicit synthetic HTTP fixtures.
// Exercises editing and recovery, not historical truth, model quality, or persistence.
// Every /api/v1 request is intercepted; no candidate or job reaches a real service.
import assert from "node:assert/strict";
import { chromium, expect } from "@playwright/test";

const args = process.argv.slice(2);
const base = args[args.indexOf("--base-url") + 1];
if (!base || !args.includes("--base-url")) throw new Error("--base-url is required");
const uuid = (n) => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const sha = (n) => n.toString(16).padStart(64, "0");
const clone = (value) => structuredClone(value);
const iso = "2026-01-01T00:00:00Z";
const reviewIds = { facts: uuid(1), prose: uuid(2), reject: uuid(3) };
const jobs = { facts: uuid(11), prose: uuid(12), reject: uuid(13) };
const person = uuid(21);
const place = uuid(22);
const mainEvent = uuid(31);
const minorEvent = uuid(32);
const early = "phase_early";
const late = "phase_late";
const officeFact = "fact_office";
const eventFact = "fact_event";
const minorFact = "fact_minor";
const paragraphs = ["paragraph_early", "paragraph_current", "paragraph_minor", "paragraph_retrospective"];

// The highlighted quote comes well after astral characters and many full lines.
// UTF-16 slicing or scrolling only the outer page would both fail this fixture.
const prefix = Array.from({ length: 40 }, (_, i) => `合成前文第 ${i + 1} 行：𠮷是扩展汉字，这些文字只用于验证整章引用定位。\n`).join("");
const officeQuote = "某年冬，𠮷甲受命为测试前职。";
const suffix = Array.from({ length: 15 }, (_, i) => `\n合成后文第 ${i + 1} 行，保留完整上下文供审核者核对。`).join("");
const eventQuote = "次年春，众人于渡河行动中在北岸会合。";
const minorQuote = "此后甲巡视营地，这是正文细节。";
const anchor = (id, quote, before = "") => ({
  id, anchor_id: `anchor_${id}`, start: Array.from(before).length,
  end: Array.from(before + quote).length, quote,
});
const frozenContext = {
  catalog_sha: sha(90),
  sources: [
    { source_id: "source_001", publication_id: uuid(41), document_id: uuid(51), revision_id: uuid(61),
      document_title: "合成测试文献", title: "合成甲章", source_sha: sha(101), chapter_text: prefix + officeQuote + suffix,
      evidence: [anchor("evidence_office", officeQuote, prefix)] },
    { source_id: "source_002", publication_id: uuid(42), document_id: uuid(51), revision_id: uuid(61),
      document_title: "合成测试文献", title: "合成乙章", source_sha: sha(101), chapter_text: eventQuote + "\n" + minorQuote,
      evidence: [anchor("evidence_event", eventQuote), anchor("evidence_minor", minorQuote, eventQuote + "\n")] },
  ],
  entities: { [person]: { name: "合成人物甲", kind: "person" }, [place]: { name: "合成北岸", kind: "place" } },
  events: { [mainEvent]: { name: "渡河行动" }, [minorEvent]: { name: "巡视营地" } },
};
const ref = (id, note = "仅验证编辑，不作为历史验收材料。") => ({ id, relation: "support", attribution: "合成原作者", note });
const initialFacts = {
  schema: "chronicle.source-corroboration", version: "0.1", title: "合成核对范围",
  phases: [
    { id: early, label: "合成前阶段", year: 208, period: "冬", basis: ["evidence_office"], relation_to_previous: "uncertain" },
    { id: late, label: "合成后阶段", year: 209, period: "春", basis: ["evidence_event"], relation_to_previous: "after" },
  ],
  conclusions: [
    { id: officeFact, question: "甲在前阶段担任何职（合成）？", subject_id: person, event_id: null, dimension: "office",
      phase_ids: [early], text: "合成人物甲在前阶段担任测试前职。", value: "测试前职", certainty: "clear",
      reason: "合成原文明确限定前阶段。", evidence: [ref("evidence_office")] },
    { id: eventFact, question: "后阶段发生了什么（合成）？", subject_id: null, event_id: mainEvent, dimension: "event_detail",
      phase_ids: [late], text: "合成记载称众人在渡河行动中会合。", value: null, certainty: "clear",
      reason: "同一著作的补充记载不构成独立见证。", evidence: [ref("evidence_event")] },
  ],
  source_relations: [{ left: "source_001", right: "source_002", relation: "same_work", reason: "同一合成著作的两个章节。" }],
};
const approvedFacts = clone(initialFacts);
approvedFacts.conclusions.push({ id: minorFact, question: "巡视营地细节（合成）", subject_id: person, event_id: minorEvent,
  dimension: "event_detail", phase_ids: [late], text: minorQuote, value: null, certainty: "clear",
  reason: "合成叙述中的次要细节。", evidence: [ref("evidence_minor")] });
const paragraph = (index, phase, text, conclusion, event = null, relation = null, eventText = null) => ({
  id: paragraphs[index], phase_id: phase,
  segments: [{ text, conclusion_ids: [conclusion], event_id: event, event_relation: relation, event_text: eventText }],
  entities: [{ entity_id: person, importance: "primary" }],
});
const initialProse = {
  schema: "chronicle.historical-narrative", version: "0.1",
  paragraphs: [
    paragraph(0, early, "合成前段：甲在前阶段担任测试前职。", officeFact),
    paragraph(1, late, "合成主段：众人在渡河行动中会合。", eventFact, mainEvent, "current", "渡河行动"),
    paragraph(2, late, "合成细节：此后甲巡视营地。", minorFact, minorEvent, "current", "巡视营地"),
    paragraph(3, late, "合成回顾：这里回顾渡河行动。", eventFact, mainEvent, "retrospective", "渡河行动"),
  ],
  entry_points: [
    { label: "合成前期", kind: "period", paragraph_id: paragraphs[0], event_id: null, reason: "所选叙述范围的起点。" },
    { label: "渡河行动", kind: "event", paragraph_id: paragraphs[1], event_id: mainEvent, reason: "本合成正文的主要事件。" },
  ],
};
function review(kind, name, n) {
  return {
    review_id: reviewIds[name], job_id: jobs[name], chunk_id: null, kind: "stage_gate", status: "open",
    created_at: `2026-01-01T00:00:0${n}Z`, resolved_at: null, job_status: "needs_review", revision_id: uuid(61),
    document: { document_id: uuid(51), title: `合成审核 ${name}`, revision_no: 1, filename: "synthetic.txt",
      source_sha256: sha(101), language: "zh", source_label: "明确的合成浏览器 fixture" },
    scope: "narrative", narrative_kind: kind, candidate_sha: sha(n), link_kind: "",
    review_subject_id: null, review_subject_version: null, member_count: 1, group_count: 1, groups: [], members: [],
    candidate_id: null, resolution_sha256: null, blocking: true, allowed_decisions: ["approve", "reject"],
    left: null, right: null, left_label: kind === "facts" ? "多史料事实核对" : "综合正文审核", right_label: null,
    suggestion: { decision: null, confidence: null, rationale: null, signals: [] }, decision: null,
    narrative: { kind, candidate_sha: sha(n), model: "explicit-synthetic-browser-fixture", review_id: reviewIds[name],
      context: clone(frozenContext), candidate: clone(kind === "facts" ? initialFacts : initialProse), decision: null,
      ...(kind === "prose" ? { facts: clone(approvedFacts) } : {}) },
  };
}
const records = new Map([
  [reviewIds.facts, review("facts", "facts", 1)],
  [reviewIds.prose, review("prose", "prose", 2)],
  [reviewIds.reject, review("facts", "reject", 3)],
]);
const decisionRequests = [];
const resumeRequests = [];
const detailReads = new Map();
const fixtureErrors = [];
const pageErrors = [];
let failDecision = true;
let failResume = true;
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce", serviceWorkers: "block" });
context.setDefaultTimeout(10_000);
const page = await context.newPage();
page.on("pageerror", (error) => pageErrors.push(error.message));
const reply = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const envelope = (item) => ({ schema: "chronicle.review", version: "0.1", review: item });
await context.route("**/api/v1/**", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  const method = request.method();
  const path = url.pathname;
  try {
    assert.equal(request.headers().authorization, `Basic ${Buffer.from("synthetic-studio:synthetic-password-not-valid").toString("base64")}`);
    if (method === "GET" && path === "/api/v1/studio/status") {
      return reply(route, { schema: "chronicle.studio-status", version: "0.1", admin_user: "synthetic-studio", upstream: { reachable: true } });
    }
    if (method === "GET" && path === "/api/v1/studio/jobs/reviews") {
      const status = url.searchParams.get("status") ?? "open";
      const job = url.searchParams.get("job_id");
      const scoped = [...records.values()].filter((item) => !job || item.job_id === job);
      return reply(route, { schema: "chronicle.studio-review-page", version: "0.2",
        query: { status, job_id: job, link_kind: null, limit: Number(url.searchParams.get("limit") ?? 50) },
        items: scoped.filter((item) => status === "all" || item.status === status), next_cursor: null,
        open_count: scoped.filter((item) => item.status === "open").length, observed_at: iso, plan_fingerprint: sha(80) });
    }
    const detail = path.match(/^\/api\/v1\/studio\/jobs\/reviews\/([^/]+)$/);
    if (method === "GET" && detail && records.has(detail[1])) {
      detailReads.set(detail[1], (detailReads.get(detail[1]) ?? 0) + 1);
      return reply(route, envelope(records.get(detail[1])));
    }
    const decision = path.match(/^\/api\/v1\/studio\/jobs\/reviews\/([^/]+)\/decision$/);
    if (method === "POST" && decision && records.has(decision[1])) {
      const item = records.get(decision[1]);
      const payload = request.postDataJSON();
      decisionRequests.push({ review_id: item.review_id, payload });
      assert.equal(payload.candidate_sha, item.candidate_sha, "decision must pin the reviewed candidate");
      if (item.review_id === reviewIds.facts && failDecision) {
        failDecision = false;
        return reply(route, { error: { code: "synthetic_unavailable", message: "合成提交故障" } }, 503);
      }
      assert.equal(item.status, "open", "a resolved candidate must not be resubmitted");
      item.status = "resolved";
      item.resolved_at = iso;
      if (payload.decision === "reject") item.job_status = "cancelled";
      item.decision = { decision: payload.decision, rationale: payload.rationale, content_sha: sha(200 + decisionRequests.length) };
      item.narrative.decision = { ...item.decision, content: clone(payload.content), reviewed_conclusion_ids: [...payload.reviewed_conclusion_ids] };
      return reply(route, envelope(item));
    }
    const resume = path.match(/^\/api\/v1\/studio\/jobs\/([^/]+)\/resume$/);
    if (method === "POST" && resume && Object.values(jobs).includes(resume[1])) {
      resumeRequests.push(resume[1]);
      if (resume[1] === jobs.facts && failResume) {
        failResume = false;
        return reply(route, { error: { code: "synthetic_resume_unavailable", message: "合成继续生产故障" } }, 503);
      }
      const item = [...records.values()].find((value) => value.job_id === resume[1]);
      assert.equal(item.narrative.decision?.decision, "approve");
      item.job_status = "queued";
      return reply(route, { schema: "chronicle.job", version: "0.1", job: { job_id: item.job_id, status: "queued" } });
    }
    throw new Error(`Unexpected synthetic API request: ${method} ${path}`);
  } catch (error) {
    fixtureErrors.push(error.message);
    return reply(route, { error: { code: "fixture_mismatch", message: error.message } }, 500);
  }
});

const actions = page.locator('[data-test="narrative-review-actions"]');
const approve = () => actions.getByRole("button", { name: "通过并继续", exact: true });
const question = () => page.getByLabel(/^当前问题/);
const factChecked = () => page.getByRole("checkbox", { name: "已核对本问题的结论、阶段、明确性与各份原文", exact: true });
const scopeChecked = () => page.getByRole("checkbox", { name: "已核对来源传承与时间阶段，不把来源数量当作真实性。", exact: true });
const proseChecked = () => page.getByRole("checkbox", { name: "已通读正文并检查入口；发布后首页使用这一版本，旧版引用仍保留。", exact: true });
const phases = page.locator(".nr-scope > section.nr-prose");
const entries = page.locator(".nr-entries .nr-entry");
const options = (select) => select.locator("option").evaluateAll((nodes) => nodes.map((node) => node.value).filter(Boolean));
const openScope = async () => {
  if (!(await page.locator(".nr-scope").evaluate((node) => node.open))) await page.locator(".nr-scope > summary").click();
};
async function footerInViewport() {
  for (const control of await actions.locator("a, button").all()) await expect(control).toBeInViewport({ ratio: 1 });
}
async function mobileFits() {
  const bounds = await page.evaluate(() => ({ width: window.innerWidth, content: document.documentElement.scrollWidth }));
  assert(bounds.content <= bounds.width + 1, `mobile form overflow: ${JSON.stringify(bounds)}`);
  await footerInViewport();
}
let stage = "login";
try {
  await page.goto(new URL("/studio/login", base).href);
  await page.getByLabel(/^用户名/).fill("synthetic-studio");
  await page.getByLabel(/^密码/).fill("synthetic-password-not-valid");
  await page.getByRole("button", { name: "登录管理工作台", exact: true }).click();
  await expect(page.locator('[data-view="studio-home"]')).toBeVisible();
  await page.goto(new URL(`/studio/review/${reviewIds.facts}?status=open`, base).href);
  await expect(page.getByRole("heading", { name: "多史料事实核对", exact: true })).toBeVisible();
  await expect(question().locator("option")).toHaveCount(2);
  await expect(approve()).toBeDisabled();
  await expect(actions.getByRole("button", { name: "驳回", exact: true })).toBeDisabled();
  await footerInViewport();

  stage = "complete source and Unicode quote";
  const evidence = page.locator(".nr-evidence-editor").first();
  const expand = evidence.getByRole("button", { name: "查看完整章节与引用位置", exact: true });
  await expand.scrollIntoViewIfNeeded();
  const outerTop = await page.evaluate(() => window.scrollY);
  await expand.click();
  await expect(evidence.locator(".nr-full-source mark")).toHaveText(officeQuote);
  assert.equal(await evidence.locator(".nr-full-source").textContent(), prefix + officeQuote + suffix);
  await expect.poll(() => evidence.locator(".nr-full-source").evaluate((box) => {
    const mark = box.querySelector("mark").getBoundingClientRect();
    const rect = box.getBoundingClientRect();
    return box.scrollTop > 0 && mark.top >= rect.top && mark.bottom <= rect.bottom;
  })).toBe(true);
  assert(Math.abs(await page.evaluate(() => window.scrollY) - outerTop) < 4, "opening a citation must scroll its source, not jump the outer form");
  await evidence.getByRole("button", { name: "收起完整章节", exact: true }).click();

  stage = "conclusion editing, copying, addition and deletion";
  const revisedOffice = "合成人物甲在前阶段担任测试前职；此句已经人工修订。";
  await factChecked().check();
  await page.getByLabel(/^核对后的表述/).fill(revisedOffice);
  await expect(factChecked()).not.toBeChecked();
  await factChecked().check();
  await page.getByRole("button", { name: "下一个问题", exact: true }).click();
  await factChecked().check();
  await expect(page.locator(".nr-question-nav")).toContainText("已核对 2 / 2");
  await page.getByRole("button", { name: "上一个问题", exact: true }).click();
  await page.getByRole("button", { name: "复制为另一条结论", exact: true }).click();
  await expect(question()).toHaveValue("1");
  await expect(question().locator("option")).toHaveCount(3);
  await expect(factChecked()).not.toBeChecked();
  await expect(page.getByLabel(/^核对后的表述/)).toHaveValue(revisedOffice);
  await page.getByLabel(/^核对问题/).fill("同阶段称号（合成副本）");
  await page.getByLabel(/^结论类型/).selectOption("title");
  await page.getByLabel(/^此阶段显示的状态/).fill("合成测试称号");
  await page.getByLabel(/^核对后的表述/).fill("合成副本单独记录测试称号。");
  await page.getByLabel(/^支持范围或分歧说明/).fill("仅修改副本的嵌套依据。");
  await question().selectOption("0");
  await expect(factChecked()).toBeChecked();
  await expect(page.getByLabel(/^核对后的表述/)).toHaveValue(revisedOffice);
  await expect(page.getByLabel(/^支持范围或分歧说明/)).toHaveValue(initialFacts.conclusions[0].evidence[0].note);
  await page.getByRole("button", { name: "新增核对问题", exact: true }).click();
  await expect(question()).toHaveValue("3");
  await expect(page.getByLabel(/^核对问题/)).toHaveValue("");
  await expect(page.getByLabel(/^核对后的表述/)).toHaveValue("");
  await expect(page.locator(".nr-evidence-editor")).toHaveCount(0);
  await expect(page.getByRole("group", { name: "仅适用于以下阶段" }).locator("input:checked")).toHaveCount(0);
  await page.getByRole("button", { name: "移除此问题", exact: true }).click();
  await expect(question().locator("option")).toHaveCount(3);
  await page.getByRole("button", { name: "新增核对问题", exact: true }).click();
  await page.getByLabel(/^核对问题/).fill("新增的巡视细节（合成）");
  await page.getByLabel(/^主体/).selectOption(person);
  await page.getByLabel(/^相关事件/).selectOption(minorEvent);
  await page.getByLabel(/^明确性/).selectOption("clear");
  await page.getByRole("checkbox", { name: "合成后阶段", exact: true }).check();
  await page.getByLabel(/^核对后的表述/).fill(minorQuote);
  await page.getByLabel(/^明确或存疑的理由/).fill("这条新结论来自合成乙章的后文。");
  await page.getByLabel(/^补充引用/).selectOption("evidence_minor");
  await page.getByLabel(/^原作者、注者或说话人/).fill("合成原作者");
  await page.getByLabel(/^支持范围或分歧说明/).fill("巡视细节仅用于正文。");
  await expect(question().locator("option")).toHaveCount(4);

  stage = "phase evidence, ordering and reference protection";
  await factChecked().check();
  await scopeChecked().check();
  await openScope();
  await expect(page.getByLabel(/^合成甲章 ↔ 合成乙章/)).toHaveValue("same_work");
  await page.getByLabel(/^本次内容范围/).fill("合成审核范围（修订）");
  await expect(scopeChecked()).not.toBeChecked();
  await expect(page.locator(".nr-question-nav")).toContainText("已核对 0 / 4");
  await page.getByLabel(/^判断理由/).fill("同一合成著作两章，已核对传承关系。");
  await expect(phases).toHaveCount(2);
  for (const phase of await phases.all()) await expect(phase.getByRole("button", { name: "移除未引用的阶段" })).toBeDisabled();
  await factChecked().check();
  await scopeChecked().check();
  await phases.first().getByRole("button", { name: "在此后新增阶段" }).click();
  await expect(phases).toHaveCount(3);
  await expect(factChecked()).not.toBeChecked();
  await expect(scopeChecked()).not.toBeChecked();
  await expect(page.locator(".nr-question-nav")).toContainText("已核对 0 / 4");
  await phases.nth(1).getByLabel(/^阶段名称/).fill("临时合成阶段");
  await expect(phases.nth(1).getByRole("button", { name: "移除未引用的阶段" })).toBeEnabled();
  await page.getByRole("checkbox", { name: "临时合成阶段", exact: true }).check();
  await expect(phases.nth(1).getByRole("button", { name: "移除未引用的阶段" })).toBeDisabled();
  await page.getByRole("checkbox", { name: "临时合成阶段", exact: true }).uncheck();
  await phases.nth(1).getByRole("button", { name: "移除未引用的阶段" }).click();
  await expect(phases).toHaveCount(2);
  await phases.first().getByRole("button", { name: "在此后新增阶段" }).click();
  await phases.nth(1).getByLabel(/^阶段名称/).fill("合成补充分期");
  await phases.nth(1).getByLabel(/^确切公元年（不明留空）/).fill("208");
  await phases.nth(1).getByLabel(/^月份或时段原述/).fill("冬末");
  await phases.nth(1).getByLabel(/^与上一阶段关系/).selectOption("after");
  await phases.nth(1).locator("summary").click();
  await phases.nth(1).getByLabel(/^添加阶段依据/).selectOption("evidence_event");
  await expect(phases.nth(1).locator("summary")).toContainText("1 条");
  assert(!(await options(phases.nth(1).getByLabel(/^添加阶段依据/))).includes("evidence_event"));
  await phases.nth(1).getByRole("button", { name: "移除阶段依据", exact: true }).click();
  await phases.nth(1).getByLabel(/^添加阶段依据/).selectOption("evidence_office");
  await phases.nth(1).getByRole("button", { name: "阶段前移", exact: true }).click();
  await expect(phases.first().getByLabel(/^阶段名称/)).toHaveValue("合成补充分期");
  await expect(phases.first().getByRole("button", { name: "阶段前移", exact: true })).toBeDisabled();
  await phases.first().getByRole("button", { name: "阶段后移", exact: true }).click();
  await expect(phases.nth(1).getByLabel(/^阶段名称/)).toHaveValue("合成补充分期");
  await expect(phases.last().getByRole("button", { name: "阶段后移", exact: true })).toBeDisabled();
  await question().selectOption("1");
  await page.getByRole("checkbox", { name: "合成补充分期", exact: true }).check();
  await expect(phases.nth(1).getByRole("button", { name: "移除未引用的阶段" })).toBeDisabled();
  const rationale = "合成审核说明：已逐项修订结论、引用及阶段；不作为历史验收。";
  await page.getByLabel(/^本次审核说明/).fill(rationale);
  await page.getByRole("heading", { name: "多史料事实核对", exact: true }).scrollIntoViewIfNeeded();
  await footerInViewport();
  await page.setViewportSize({ width: 390, height: 844 });
  await mobileFits();

  stage = "skip, isolated drafts, queue return and refresh";
  await actions.getByRole("button", { name: "暂时跳过", exact: true }).click();
  await expect(page.getByRole("heading", { name: "综合历史正文审核", exact: true })).toBeVisible();
  await expect(page.getByLabel(/^本次审核说明/)).toHaveValue("");
  await expect(entries).toHaveCount(2);
  assert.equal(records.get(reviewIds.facts).status, "open", "skipping must not resolve the candidate");
  assert.equal(decisionRequests.length, 0);
  await actions.getByRole("link", { name: "返回队列", exact: true }).click();
  await expect(page.getByRole("heading", { name: "人工审核队列", exact: true })).toBeVisible();
  await page.locator(`a[href^="/studio/review/${reviewIds.facts}?"]`).click();
  await expect(question().locator("option")).toHaveCount(4);
  await page.reload();
  await expect(page.getByLabel(/^本次审核说明/)).toHaveValue(rationale);
  await expect(page.getByLabel(/^核对后的表述/)).toHaveValue(revisedOffice);
  await openScope();
  await expect(page.getByLabel(/^本次内容范围/)).toHaveValue("合成审核范围（修订）");
  await expect(phases).toHaveCount(3);
  await expect(phases.nth(1).getByLabel(/^阶段名称/)).toHaveValue("合成补充分期");
  await expect(phases.nth(1).locator("summary")).toContainText("1 条");
  await question().selectOption("1");
  await expect(page.getByLabel(/^核对问题/)).toHaveValue("同阶段称号（合成副本）");
  await expect(page.getByRole("checkbox", { name: "合成补充分期", exact: true })).toBeChecked();
  for (let i = 0; i < 4; i++) {
    await question().selectOption(String(i));
    await factChecked().check();
    if (i < 3) await expect(approve()).toBeDisabled();
  }
  await expect(approve()).toBeDisabled();
  await scopeChecked().check();
  await expect(approve()).toBeEnabled();
  await mobileFits();

  stage = "failed decision, record verification, refresh and resume retry";
  await approve().click();
  await expect(page.getByRole("alert")).toContainText("合成提交故障");
  await expect(page.getByLabel(/^本次审核说明/)).toHaveValue(rationale);
  await expect(page.locator(".nr-question-nav")).toContainText("已核对 4 / 4");
  assert.equal(resumeRequests.length, 0, "a failed decision cannot resume production");
  const previousReads = detailReads.get(reviewIds.facts);
  await page.getByRole("button", { name: "核对服务器记录", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("服务端仍待审核");
  assert(detailReads.get(reviewIds.facts) > previousReads);
  await expect(page.getByLabel(/^本次审核说明/)).toHaveValue(rationale);
  await page.reload();
  await expect(page.getByLabel(/^核对后的表述/)).toHaveValue(revisedOffice);
  await expect(scopeChecked()).toBeChecked();
  await expect(factChecked()).toBeChecked();
  await expect(page.locator(".nr-question-nav")).toContainText("已核对 4 / 4");
  await approve().click();
  await expect(page.getByRole("status")).toContainText("合成继续生产故障");
  await expect(page.getByText("本次审核通过，记录已固定。", { exact: true })).toBeVisible();
  await expect(page.locator(".nr-form")).toHaveCount(0);
  assert.equal(decisionRequests.length, 2);
  assert.deepEqual(decisionRequests[1].payload, decisionRequests[0].payload, "retry must preserve the reviewed draft and explicit coverage");
  const acceptedFacts = decisionRequests[1].payload.content;
  const conclusionIds = acceptedFacts.conclusions.map((fact) => fact.id);
  assert.equal(new Set(conclusionIds).size, 4, "copied and added conclusions need independent IDs");
  assert.deepEqual(new Set(decisionRequests[1].payload.reviewed_conclusion_ids), new Set(conclusionIds));
  assert.equal(acceptedFacts.conclusions[0].id, officeFact);
  assert.equal(acceptedFacts.conclusions[0].text, revisedOffice);
  assert.equal(acceptedFacts.conclusions[1].dimension, "title");
  assert.equal(acceptedFacts.conclusions[1].evidence[0].note, "仅修改副本的嵌套依据。");
  assert.equal(acceptedFacts.conclusions[2].id, eventFact);
  assert.equal(acceptedFacts.conclusions[3].event_id, minorEvent);
  assert.deepEqual(acceptedFacts.conclusions[3].evidence.map((item) => item.id), ["evidence_minor"]);
  assert.deepEqual(acceptedFacts.phases.map((phase) => phase.label), ["合成前阶段", "合成补充分期", "合成后阶段"]);
  assert.deepEqual(acceptedFacts.phases[1].basis, ["evidence_office"]);
  assert.equal(acceptedFacts.phases[1].year, 208);
  assert.equal(acceptedFacts.phases[1].period, "冬末");
  assert(acceptedFacts.conclusions[1].phase_ids.includes(acceptedFacts.phases[1].id));
  await page.reload();
  await expect(page.getByText("本次审核通过，记录已固定。", { exact: true })).toBeVisible();
  await actions.getByRole("button", { name: "继续生产", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("已继续生产");
  await expect(actions.getByRole("button", { name: "继续生产", exact: true })).toHaveCount(0);
  assert.deepEqual(resumeRequests, [jobs.facts, jobs.facts]);
  await actions.getByRole("button", { name: "下一项", exact: true }).click();
  await expect(page.getByRole("heading", { name: "综合历史正文审核", exact: true })).toBeVisible();

  stage = "prose, context, conclusion references and curated entry editing";
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(entries).toHaveCount(2);
  await expect(page.getByLabel(/^本次审核说明/)).toHaveValue("");
  await proseChecked().check();
  const firstParagraph = page.locator("section.nr-prose").nth(0);
  const currentParagraph = page.locator("section.nr-prose").nth(1);
  const revisedProse = "合成前段修订：甲在前阶段担任测试前职。";
  await page.getByLabel(/^第 1 段文字 1/).fill(revisedProse);
  await expect(proseChecked()).not.toBeChecked();
  await firstParagraph.getByText("本段阶段与侧栏人物、地点", { exact: true }).click();
  await firstParagraph.getByLabel(/^主叙述阶段/).selectOption(late);
  await firstParagraph.getByLabel(/^主叙述阶段/).selectOption(early);
  await firstParagraph.getByRole("button", { name: "移除本段关联", exact: true }).click();
  await firstParagraph.getByLabel(/^补充本段人物或地点/).selectOption(person);
  await firstParagraph.getByLabel(/^合成人物甲/).selectOption("other");
  await firstParagraph.getByLabel(/^补充本段人物或地点/).selectOption(place);
  await currentParagraph.getByLabel(/^第 2 段文字 1/).fill("合成主段修订：众人在渡河行动中会合。");
  await currentParagraph.getByLabel(/^供读者触发预览的事件称呼（须在上文出现一次，可留空）/).fill("渡河");
  await currentParagraph.getByText("核对这段文字的结论与原文", { exact: true }).click();
  await currentParagraph.getByRole("button", { name: "移除此结论引用", exact: true }).click();
  await expect(currentParagraph.getByRole("button", { name: "移除此结论引用", exact: true })).toHaveCount(0);
  await currentParagraph.getByLabel(/^引用已审核结论/).selectOption(eventFact);
  assert(!(await options(currentParagraph.getByLabel(/^引用已审核结论/))).includes(eventFact));
  assert.deepEqual(await options(entries.nth(1).getByLabel(/^正文位置/)), [paragraphs[1]], "event entries may target occurrence paragraphs, not retrospectives");
  const eventPicker = page.getByLabel(/^添加经过选择的重要事件/);
  assert.deepEqual(await options(eventPicker), [`${paragraphs[2]}|${minorEvent}`]);
  await proseChecked().check();
  await eventPicker.selectOption(`${paragraphs[2]}|${minorEvent}`);
  await expect(entries).toHaveCount(3);
  await expect(proseChecked()).not.toBeChecked();
  await entries.last().getByLabel(/^入口名称/).fill("临时合成细节入口");
  await entries.last().getByLabel(/^为何值得独立导航/).fill("仅验证新增后可以撤销选择。");
  await entries.last().getByRole("button", { name: "移除入口", exact: true }).click();
  await expect(entries).toHaveCount(2);
  assert.deepEqual(await options(eventPicker), [`${paragraphs[2]}|${minorEvent}`]);
  await page.getByLabel(/^添加重要时期入口/).selectOption(paragraphs[2]);
  await entries.last().getByLabel(/^入口名称/).fill("合成后期入口");
  await entries.last().getByLabel(/^为何值得独立导航/).fill("合成叙述后期的独立阅读起点。");
  await entries.last().getByLabel(/^正文位置/).selectOption(paragraphs[3]);
  await entries.last().getByLabel(/^正文位置/).selectOption(paragraphs[2]);
  await entries.nth(1).getByLabel(/^入口名称/).fill("渡河会合");
  await entries.nth(1).getByLabel(/^为何值得独立导航/).fill("人工选择的主要事件，回顾段不是入口。");
  await expect(entries).toHaveCount(3);
  assert(!(await options(page.getByLabel(/^添加重要时期入口/))).includes(paragraphs[2]));
  const proseRationale = "合成正文审核：入口经过人工选择，细节留在正文。";
  await page.getByLabel(/^本次审核说明/).fill(proseRationale);
  await expect(approve()).toBeDisabled();
  await proseChecked().check();
  await page.reload();
  await expect(page.getByLabel(/^第 1 段文字 1/)).toHaveValue(revisedProse);
  await expect(page.getByLabel(/^本次审核说明/)).toHaveValue(proseRationale);
  await expect(proseChecked()).toBeChecked();
  await expect(entries).toHaveCount(3);
  await expect(entries.last().getByLabel(/^入口名称/)).toHaveValue("合成后期入口");
  await expect(entries.last().getByLabel(/^正文位置/)).toHaveValue(paragraphs[2]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("heading", { name: "综合历史正文审核", exact: true }).scrollIntoViewIfNeeded();
  await mobileFits();
  await entries.last().scrollIntoViewIfNeeded();
  await mobileFits();
  await approve().click();
  await expect(page.getByRole("heading", { name: "多史料事实核对", exact: true })).toBeVisible();
  assert.equal(decisionRequests[2].review_id, reviewIds.prose);
  const acceptedProse = decisionRequests[2].payload.content;
  assert.equal(acceptedProse.paragraphs[0].segments[0].text, revisedProse);
  assert.deepEqual(acceptedProse.paragraphs[0].entities, [{ entity_id: person, importance: "other" }, { entity_id: place, importance: "primary" }]);
  assert.equal(acceptedProse.paragraphs[1].segments[0].event_text, "渡河");
  assert.deepEqual(acceptedProse.paragraphs[1].segments[0].conclusion_ids, [eventFact]);
  assert.deepEqual(acceptedProse.entry_points.map((entry) => [entry.kind, entry.paragraph_id]), [
    ["period", paragraphs[0]], ["event", paragraphs[1]], ["period", paragraphs[2]],
  ]);
  assert(!acceptedProse.entry_points.some((entry) => entry.event_id === minorEvent), "extracting an event must not automatically create a navigation entry");

  stage = "last conclusion guard, rejection and queue return";
  await expect(question().locator("option")).toHaveCount(2);
  await expect(page.getByLabel(/^本次审核说明/)).toHaveValue("");
  await page.getByRole("button", { name: "移除此问题", exact: true }).click();
  await expect(question().locator("option")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "移除此问题", exact: true })).toBeDisabled();
  await page.getByLabel(/^本次审核说明/).fill("合成驳回说明：用于验证页底驳回和固定审计记录。");
  await expect(approve()).toBeDisabled();
  await mobileFits();
  await actions.getByRole("button", { name: "驳回", exact: true }).click();
  await expect(page.getByText("本次已驳回，记录已固定。", { exact: true })).toBeVisible();
  await expect(page.locator(".nr-form")).toHaveCount(0);
  await expect(actions.getByRole("button", { name: "继续生产", exact: true })).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "当前范围暂无待审项" })).toBeVisible();
  await actions.getByRole("link", { name: "返回队列", exact: true }).click();
  await expect(page.getByRole("heading", { name: "人工审核队列", exact: true })).toBeVisible();
  await expect(page.locator('[data-view="studio-review"] .studio-table-row')).toHaveCount(0);
  assert.equal(decisionRequests.length, 4);
  assert.equal(decisionRequests[3].review_id, reviewIds.reject);
  assert.equal(decisionRequests[3].payload.decision, "reject");
  assert.deepEqual(resumeRequests, [jobs.facts, jobs.facts, jobs.prose]);
  assert.deepEqual(fixtureErrors, []);
  assert.deepEqual(pageErrors, []);
  console.log("narrative-review-component-smoke: PASS (conclusions, phases/basis, full-source Unicode, draft/refresh, failures/retry, curated entries, footer actions, mobile)");
} catch (error) {
  console.error(`narrative-review-component-smoke: FAIL at ${stage}`);
  if (fixtureErrors.length) console.error("Fixture errors:", fixtureErrors);
  if (pageErrors.length) console.error("Page errors:", pageErrors);
  throw error;
} finally {
  await browser.close();
}
