#!/usr/bin/env node
// Real React UI, isolated synthetic HTTP. No upload or model run reaches a service.
import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { chromium, expect } from "@playwright/test";

const args = process.argv.slice(2);
const base = args[args.indexOf("--base-url") + 1];
if (!args.includes("--base-url") || !base) throw new Error("--base-url is required");
const output = args.includes("--output") ? args[args.indexOf("--output") + 1] : "/tmp/chronicle-studio-workspace";
await mkdir(output, { recursive: true });
const uuid = (n) => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const sha = (n) => n.toString(16).padStart(64, "0");
const iso = "2026-09-14T01:30:00Z";
const steps = ["translation", "extraction", "comparison", "linking", "review", "repair"];
const choices = { available: true, config_sha256: sha(99), models: [{ id: "a", name: "luna" }, { id: "b", name: "review-model" }],
  steps: Object.fromEntries(steps.map((step) => [step, ["a"]])) };
const document = { document_id: uuid(20), title: "三国志 · 周瑜传（交互测试）", revision_no: 1, filename: "zhouyu.txt" };
const revision = { ...document, revision_id: uuid(21), status: "active", content_chars: 1200, source_sha256: sha(21),
  source_bytes: 3600, storage_status: "present", source_label: "合成浏览器测试资料", created_at: iso };
const source = "瑜字公瑾。建安三年，策授瑜建威中郎将。";
const rawCandidate = JSON.parse(await readFile(new URL("../../ingestion/fixtures/c2r3-contract/candidate-valid.json", import.meta.url), "utf8"));
const outputs = [1, 2, 3].map((n) => ({ output_id: uuid(100 + n), artifact_type: "chapter-production-step", artifact_sha256: sha(n),
  step: n === 3 ? "extraction" : "translation", model: n === 2 ? "review-model" : "luna", status: "completed", round: 0, attempt: 1,
  chunk_id: uuid(30), readable: true, created_at: iso }));
const resultBodies = new Map([
  [sha(1), { parsed: { blocks: [{ text: "译文甲：周瑜字公瑾，少年时便与孙策交好。" }, { text: "孙策准备渡江，周瑜率兵相助。" }] } }],
  [sha(2), { parsed: { blocks: [{ text: "译文乙：周瑜字公瑾，早年与孙策相交。" }, { text: "孙策渡江时，周瑜前来接应，两人一道进兵。" }] } }],
  [sha(3), { parsed: { bundle: rawCandidate.bundle, person_states: rawCandidate.person_states } }],
]);
const failed = { job_id: uuid(1), revision_id: revision.revision_id, status: "failed", attempt: 1, max_attempts: 8,
  created_at: iso, updated_at: iso, error: "model request timed out", open_reviews: 0, document, job_kind: "chapter", source_count: 1,
  current_stage: "extract", completed_stages: 3, chunk_count: 1,
  stages: ["prepare", "structure", "segment", "extract", "assemble", "resolve", "publish", "present"].map((stage, i) => ({ stage,
    status: i < 3 ? "completed" : i === 3 ? "failed" : "pending", attempt: 1, started_at: iso, finished_at: i < 3 ? iso : null })),
  chunks: [{ chunk_id: uuid(30), section_id: uuid(31), title: "周瑜传", chunk_index: 0, status: "failed", attempt: 1, max_attempts: 2,
    source_start: 0, source_end: 1200, source_sha256: sha(20), content_sha256: sha(20), runs: [],
    production: { step: "extraction", status: "started", steps: [
      { step: "translation", slot: "a", status: "completed", model: "luna", round: 0 },
      { step: "translation", slot: "b", status: "completed", model: "review-model", round: 0 },
      { step: "extraction", slot: "a", status: "started", model: "luna", round: 0 },
    ] } }], reviews: [], outputs };
const jobs = new Map([[failed.job_id, failed]]);
const documents = [{ ...document, revision_count: 1, active_revision_no: 1 }];
let createCalls = 0, uploadCalls = 0, queueCalls = 0, retryCalls = 0;
let rerunPayload;
const errors = [];
const resultReads = [];
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
context.setDefaultTimeout(10_000);
const page = await context.newPage();
page.on("pageerror", (error) => errors.push(error.message));
const reply = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const newJob = (id, selection, parent = null) => ({ ...structuredClone(failed), job_id: id, status: "queued", error: null, attempt: 0,
  production_request: { parent_job_id: parent, model_selection: selection }, chunks: [], outputs: [],
  stages: failed.stages.map((item) => ({ ...item, status: "pending" })) });
await context.route("**/api/**", async (route) => {
  const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
  try {
    assert.equal(request.headers().authorization, `Basic ${Buffer.from("studio-test:invalid-test-password").toString("base64")}`);
    if (path === "/api/v1/studio/status") return reply(route, { admin_user: "studio-test", upstream: { reachable: true } });
    if (path === "/api/v1/studio/jobs/model-options") return reply(route, choices);
    if (path === "/api/v1/studio/jobs/reviews") return reply(route, { items: [], open_count: 0, next_cursor: null, plan_fingerprint: sha(80), observed_at: iso });
    if (path === "/api/v1/studio/documents") {
      if (method === "GET") return reply(route, { documents });
      createCalls += 1;
      const created = { ...document, document_id: uuid(40), title: request.postDataJSON().title, revision_count: 0 };
      documents.push(created);
      return reply(route, { document: created }, 201);
    }
    if (/\/documents\/[^/]+\/revisions\/[^/]+\/content$/.test(path)) return route.fulfill({ contentType: "text/plain", body: source });
    if (/\/documents\/[^/]+\/revisions$/.test(path)) {
      if (method === "GET") return reply(route, { revisions: [revision] });
      uploadCalls += 1;
      assert.equal(request.postData(), source);
      return reply(route, { revision: { ...revision, document_id: uuid(40), revision_id: uuid(41), filename: "test.txt" } }, 201);
    }
    if (path === "/api/v1/studio/jobs") {
      if (method === "GET") return reply(route, { jobs: [...jobs.values()].filter((job) => !url.searchParams.get("status") || job.status === url.searchParams.get("status")) });
      queueCalls += 1;
      const payload = request.postDataJSON();
      assert.equal(payload.revision_id, uuid(41));
      assert.equal(payload.model_selection.config_sha256, choices.config_sha256);
      if (queueCalls === 1) return reply(route, { error: { code: "unavailable", message: "合成排队故障" } }, 503);
      const queued = newJob(uuid(4), payload.model_selection);
      jobs.set(queued.job_id, queued);
      return reply(route, { job: queued }, 201);
    }
    const match = path.match(/^\/api\/v1\/studio\/jobs\/([^/]+)(?:\/(.*))?$/);
    if (match && jobs.has(match[1])) {
      const job = jobs.get(match[1]);
      if (!match[2] && method === "GET") return reply(route, { job });
      if (match[2] === "rerun" && method === "POST") {
        rerunPayload = request.postDataJSON();
        const rerun = newJob(uuid(2), rerunPayload.model_selection, job.job_id);
        jobs.set(rerun.job_id, rerun);
        return reply(route, { job: rerun }, 201);
      }
      if (match[2] === "retry" && method === "POST") {
        retryCalls += 1; job.status = "running"; job.error = null;
        job.stages.find((item) => item.stage === "extract").status = "running";
        return reply(route, { job });
      }
      if (match[2]?.startsWith("outputs/")) {
        const digest = match[2].split("/")[1], offset = Number(url.searchParams.get("offset") || 0);
        assert.equal(job.job_id, failed.job_id);
        const text = JSON.stringify(resultBodies.get(digest)), end = Math.min(text.length, offset + 16000);
        resultReads.push(digest);
        return reply(route, { job_id: job.job_id, output_sha256: digest, offset, text: text.slice(offset, end), total_chars: text.length, next_offset: end < text.length ? end : null });
      }
    }
    throw new Error(`Unexpected fixture request ${method} ${path}`);
  } catch (error) { errors.push(error.message); return reply(route, { error: { message: error.message } }, 500); }
});
let stage = "login";
try {
  await page.goto(new URL("/studio/login", base).href);
  await page.getByLabel(/^用户名/).fill("studio-test");
  await page.getByLabel(/^密码/).fill("invalid-test-password");
  await page.getByRole("button", { name: "登录管理工作台", exact: true }).click();
  await expect(page.getByRole("heading", { name: "内容工作台", exact: true })).toBeVisible();
  await expect(page.getByText(document.title, { exact: true })).toBeVisible();
  await page.screenshot({ path: `${output}/overview.png`, fullPage: true });

  stage = "task progress and result comparison";
  await page.goto(new URL(`/studio/imports/${failed.job_id}`, base).href);
  await expect(page.getByRole("heading", { name: document.title, exact: true })).toBeVisible();
  await expect(page.locator(".studio-step-tile").filter({ hasText: "信息提取" })).toContainText("已中断");
  assert(!(await page.locator("main").innerText()).includes(failed.job_id), "internal IDs stay collapsed");
  await page.locator(".studio-step-tile").filter({ hasText: "整章翻译" }).click();
  await expect(page.getByText("译文乙：周瑜字公瑾，早年与孙策相交。", { exact: true })).toBeVisible();
  await page.getByLabel("对照结果", { exact: true }).selectOption(sha(1));
  await expect(page.getByText("译文甲：周瑜字公瑾，少年时便与孙策交好。", { exact: true })).toBeVisible();
  await expect(page.locator(".studio-result-columns.is-comparing > article")).toHaveCount(2);
  await page.screenshot({ path: `${output}/task-comparison.png`, fullPage: true });
  await page.locator(".studio-step-tile").filter({ hasText: "信息提取" }).click();
  await expect(page.getByText("周瑜 · 官职", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("开始/取得：建威中郎將", { exact: true })).toBeVisible();

  stage = "new-model rerun and original-model retry";
  await page.getByRole("button", { name: "换模型重新处理", exact: true }).click();
  await page.getByText("调整各步骤模型", { exact: true }).click();
  const translation = page.getByRole("group", { name: "整章翻译", exact: true });
  await translation.getByRole("checkbox", { name: "review-model", exact: true }).check();
  await translation.getByRole("checkbox", { name: "luna", exact: true }).uncheck();
  await page.getByRole("button", { name: "新建任务并重新处理", exact: true }).click();
  await expect(page.getByRole("link", { name: "查看新任务 →", exact: true })).toBeVisible();
  assert.deepEqual(rerunPayload.model_selection.steps.translation, ["b"]);
  assert.equal(failed.status, "failed");
  assert.equal(failed.outputs.length, 3);
  await page.getByRole("link", { name: "查看新任务 →", exact: true }).click();
  await expect(page.getByRole("link", { name: "原任务与结果", exact: true })).toHaveAttribute("href", `/studio/imports/${failed.job_id}`);
  await page.getByRole("link", { name: "原任务与结果", exact: true }).click();
  await page.getByRole("button", { name: "重试未完成步骤", exact: true }).click();
  await expect(page.locator(".studio-job-banner")).toContainText("正在翻译与提取");
  assert.equal(retryCalls, 1);
  assert.equal(failed.outputs.length, 3);

  stage = "source upload and queue failure recovery";
  await page.goto(new URL("/studio/sources?upload=1", base).href);
  await expect(page.getByRole("heading", { name: "上传完整史料", exact: true })).toBeVisible();
  await page.getByLabel("选择史料文件", { exact: true }).setInputFiles({ name: "test.txt", mimeType: "text/plain", buffer: Buffer.from(source) });
  await page.getByLabel("资料名称", { exact: true }).fill("合成测试新资料");
  await expect(page.locator(".studio-model-settings")).toContainText("luna");
  await page.screenshot({ path: `${output}/source-upload.png`, fullPage: true });
  await page.getByRole("button", { name: "上传并开始处理", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("资料已保存，启动处理失败");
  assert.equal(createCalls, 1); assert.equal(uploadCalls, 1); assert.equal(queueCalls, 1);
  await page.getByRole("button", { name: "上传并开始处理", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/studio/imports/${uuid(4)}$`));
  assert.equal(createCalls, 1); assert.equal(uploadCalls, 1); assert.equal(queueCalls, 2);
  await page.goto(new URL("/studio/sources", base).href);
  await page.getByText("查看保存的原文", { exact: true }).click();
  await expect(page.locator(".studio-source-text")).toHaveText(source);
  assert.deepEqual(errors, []);
  assert(resultReads.includes(sha(1)) && resultReads.includes(sha(2)) && resultReads.includes(sha(3)));
  console.log(`studio-workspace-component-smoke: PASS; screenshots: ${output}`);
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png`, fullPage: true });
  console.error(`studio-workspace-component-smoke: FAIL at ${stage}`, errors);
  throw error;
} finally { await context.close(); await browser.close(); }
