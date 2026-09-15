#!/usr/bin/env node
// Real React UI over a synthetic HTTP boundary. The fixture mirrors the T15
// contracts and proves that a candidate stays private until an explicit save,
// that the ordinary reader page then shows the saved background only inside
// its exact range, and that every failure path keeps the Studio draft intact.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium, expect } from "@playwright/test";

const args = process.argv.slice(2);
const baseIndex = args.indexOf("--base-url");
const base = baseIndex >= 0 ? args[baseIndex + 1] : null;
if (!base) throw new Error("--base-url is required");
const outputIndex = args.indexOf("--output");
const output = outputIndex >= 0 ? args[outputIndex + 1] : "/tmp/chronicle-studio-backgrounds";
await mkdir(output, { recursive: true });

const auth = `Basic ${Buffer.from("studio-test:invalid-test-password").toString("base64")}`;
const edition = "e".repeat(64);
const paragraphIds = ["hp_000000000000000000000001", "hp_000000000000000000000002", "hp_000000000000000000000003"];
const assetId = "00000000-0000-4000-8000-000000000101";
const assetVersionId = "00000000-0000-4000-8000-000000000102";
const bindingId = "00000000-0000-4000-8000-000000000103";
const hash = "a".repeat(64);
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
const now = "2026-09-15T12:00:00Z";
const display = { opacity: 0.55, position: { x: 0.63, y: 0.42 }, scale: 1.2, mask: { shape: "gradient", top: 0.12, right: 0.08, bottom: 0.12, left: 0.08 } };
const asset = {
  asset_id: assetId, asset_version_id: assetVersionId, version: 1, source: "LM-77 浏览器测试",
  era: "东汉末年", prompt: "静水与远山", metadata: {}, content_sha256: hash,
  media_type: "image/png", format: "png", filename: "red-cliffs.png", byte_size: png.length,
  width: 1, height: 1, storage_status: "present", preview_href: `/api/v1/studio/background-assets/${assetId}/preview`,
  created_at: now, version_created_at: now, candidate: true,
};
const binding = {
  binding_id: bindingId, edition_version: edition, start_paragraph_id: paragraphIds[0], end_paragraph_id: paragraphIds[1],
  start_ordinal: 0, end_ordinal: 1, asset_id: assetId, asset_version_id: assetVersionId, asset_version: 1,
  display, status: "active", active: true, revision: 1, etag: '"binding-1"', saved_by: "studio-test",
  created_at: now, updated_at: now, disabled_at: null,
  audit_href: `/api/v1/studio/background-bindings/${bindingId}/audit`, asset,
  image_href: `/api/v1/public/background-assets/${assetId}?version=${edition}&paragraph_id=${paragraphIds[0]}`,
};
const paragraphs = paragraphIds.map((id, ordinal) => ({
  id, ordinal, phase_id: "hphase_000000000000000000000001", group_id: "group-lm77",
  segments: [{ text: `建安十三年合成正文第 ${ordinal + 1} 段：江上风静，远山入水。`, conclusion_ids: [], certainty: "clear", event_id: null, event_relation: null, event_text: null }],
  entities: [],
}));
const publication = {
  version: edition, catalog_sha: edition, title: "LM-77 背景浏览器测试 edition", paragraph_count: 3,
  first_paragraph_id: paragraphIds[0], groups: [{ id: "group-lm77", year: 208, period: "建安十三年", label: "建安十三年", first_paragraph_id: paragraphIds[0], count: 3 }],
  entry_points: [{ label: "赤壁起笔", kind: "period", paragraph_id: paragraphIds[0], event_id: null, ordinal: 0, year: 208, period: "建安十三年", excerpt: "江上风静" }],
  navigation: [{ id: paragraphIds[0], label: "建安十三年", period: "建安十三年", start: 0, end: 2, items: [{ paragraph_id: paragraphIds[0], ordinal: 0, label: "赤壁起笔", period: "建安十三年", importance: "major" }] }],
};
const historyPage = { publication_version: edition, paragraphs, start: 0, total: 3, previous_start: null, next_start: null };
const publicBindingFor = (paragraphId) => [paragraphIds[0], paragraphIds[1]].includes(paragraphId) ? binding : null;

let uploaded = false;
let saved = false;
let disabled = false;
let createCalls = 0;
let disableCalls = 0;
// The error-path fixture: `bindingFailure` is consumed by the next binding
// write so the UI must keep its candidate, range and display draft.
let bindingFailure = null;
const errors = [];
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
context.setDefaultTimeout(10_000);
const page = await context.newPage();
page.on("pageerror", (error) => errors.push(error.message));
const json = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
const errorJson = (route, code, message, status) => json(route, { schema: "chronicle.error", version: "0.1", error: { code, message } }, status);

await context.route("**/api/**", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  const path = url.pathname;
  const method = request.method();
  const paragraphId = url.searchParams.get("paragraph_id");
  try {
    if (path.startsWith("/api/v1/studio/") && request.headers().authorization !== auth) throw new Error("Studio request lost Basic auth");
    if (path === "/api/v1/studio/status") return json(route, { admin_user: "studio-test", upstream: { reachable: true } });
    if (path === "/api/v1/studio/jobs") return json(route, { jobs: [] });
    if (path === "/api/v1/studio/jobs/reviews") return json(route, { items: [], open_count: 0, next_cursor: null, plan_fingerprint: hash, observed_at: now });
    if (path === "/api/v1/studio/documents") return json(route, { documents: [] });
    if (path === "/api/v1/public/history") return json(route, { schema: "chronicle.history-directory", version: "0.1", edition: publication, publication });
    if (path === "/api/v1/public/history/paragraphs") return json(route, historyPage);

    if (path === "/api/v1/studio/background-assets" && method === "GET") {
      return json(route, { schema: "chronicle.background-asset-list", version: "0.1", assets: uploaded ? [asset] : [], offset: 0, has_more: false });
    }
    if (path === "/api/v1/studio/background-assets" && method === "POST") {
      assert.equal(request.headers()["content-type"], "image/png");
      assert((request.postDataBuffer()?.length ?? 0) > 0, "upload body should contain image bytes");
      uploaded = true;
      return json(route, { schema: "chronicle.background-asset", version: "0.1", asset }, 201);
    }
    if (path === `/api/v1/studio/background-assets/${assetId}` && method === "GET") {
      return json(route, { schema: "chronicle.background-asset", version: "0.1", asset });
    }
    if (path === `/api/v1/studio/background-assets/${assetId}/preview` && method === "GET") {
      return route.fulfill({ status: 200, contentType: "image/png", body: png });
    }
    if (path === "/api/v1/studio/background-bindings" && method === "GET") {
      return json(route, { schema: "chronicle.background-binding-list", version: "0.1", bindings: saved ? [{ ...binding, active: !disabled, status: disabled ? "disabled" : "active", revision: disabled ? 2 : 1, etag: disabled ? '"binding-2"' : binding.etag, disabled_at: disabled ? now : null }] : [], offset: 0, has_more: false });
    }
    if (path === "/api/v1/studio/background-bindings" && method === "POST") {
      const payload = request.postDataJSON();
      if (createCalls === 0) {
        assert.deepEqual(payload, { edition_version: edition, start_paragraph_id: paragraphIds[0], end_paragraph_id: paragraphIds[1], asset_id: assetId, asset_version_id: assetVersionId, display, actor: "studio-test" });
      }
      if (bindingFailure) {
        const failure = bindingFailure;
        bindingFailure = null;
        return errorJson(route, failure.code, failure.message, failure.status);
      }
      createCalls += 1;
      saved = true;
      return json(route, { schema: "chronicle.background-binding", version: "0.1", binding }, 201);
    }
    if (path === `/api/v1/studio/background-bindings/${bindingId}/disable` && method === "POST") {
      const payload = request.postDataJSON();
      assert.deepEqual(payload, { actor: "studio-test", expected_revision: 1, expected_etag: '"binding-1"' });
      disableCalls += 1;
      disabled = true;
      return json(route, { schema: "chronicle.background-binding", version: "0.1", binding: { ...binding, active: false, status: "disabled", revision: 2, etag: '"binding-2"', disabled_at: now } });
    }
    if (path === `/api/v1/public/backgrounds` && method === "GET") {
      const background = saved && !disabled ? publicBindingFor(paragraphId) : null;
      return json(route, { schema: "chronicle.background-read", version: "0.1", edition_version: edition, paragraph_id: paragraphId, background });
    }
    if (path === `/api/v1/public/background-assets/${assetId}` && method === "GET") {
      if (!saved || disabled || !publicBindingFor(paragraphId)) return errorJson(route, "not_found", "background is not active at this position", 404);
      return route.fulfill({ status: 200, contentType: "image/png", body: png });
    }
    throw new Error(`Unexpected fixture request ${method} ${path}`);
  } catch (error) {
    errors.push(error.message);
    return errorJson(route, "fixture_error", error.message, 500);
  }
});

const readerUrl = (paragraphId) => new URL(`/history/${edition}/${paragraphId}`, base).href;
const readerBackground = () => page.locator('[data-test="history-background"]');
const publicBackground = (paragraphId) => page.evaluate(async ({ version, id }) => {
  const response = await fetch(`/api/v1/public/backgrounds?version=${version}&paragraph_id=${id}`);
  return { status: response.status, body: response.status === 200 ? await response.json() : null };
}, { version: edition, id: paragraphId });
const studioRange = async () => ({
  start: await page.getByLabel("背景范围起点").inputValue(),
  end: await page.getByLabel("背景范围终点").inputValue(),
  opacity: await page.locator("#background-opacity").inputValue(),
  positionX: await page.locator("#background-position-x").inputValue(),
  positionY: await page.locator("#background-position-y").inputValue(),
  scale: await page.locator("#background-scale").inputValue(),
  mask: await page.getByLabel("正文遮罩").inputValue(),
});
const assertDraftKept = async (before, expectedError) => {
  await expect(page.locator(".studio-error", { hasText: "保存未完成" }).last()).toContainText(expectedError);
  await expect(page.getByText("已保存并显示", { exact: false })).toHaveCount(0);
  await expect(page.locator(".studio-background-asset-card.is-selected")).toHaveCount(1);
  assert.deepEqual(await studioRange(), before, "failed save must keep the range and display draft");
};

let stage = "login";
try {
  await page.goto(new URL("/studio/login", base).href);
  await page.getByLabel(/^用户名/).fill("studio-test");
  await page.getByLabel(/^密码/).fill("invalid-test-password");
  await page.getByRole("button", { name: "登录管理工作台", exact: true }).click();
  await expect(page).toHaveURL(/\/studio$/);
  await page.getByRole("link", { name: /背景素材/ }).click();
  await expect(page.getByRole("heading", { name: "背景素材库", exact: true })).toBeVisible();
  await expect(page.getByText("当前没有已发布历史 edition", { exact: true })).toHaveCount(0);
  await expect(page.getByText("还没有公开背景关联", { exact: true })).toBeVisible();

  stage = "reader sees paper before the candidate is saved";
  await page.goto(readerUrl(paragraphIds[0]));
  await expect(page.getByText("建安十三年合成正文第 1 段", { exact: false })).toBeVisible();
  await expect(readerBackground()).toHaveCount(0);
  await page.screenshot({ path: `${output}/reader-before-save.png`, fullPage: true });

  stage = "upload candidate and preview draft";
  await page.goto(new URL("/studio/backgrounds", base).href);
  await page.getByLabel("选择背景图片", { exact: true }).setInputFiles({ name: "red-cliffs.png", mimeType: "image/png", buffer: png });
  await page.getByPlaceholder("例如：skill 归档 / 操作员上传").fill("LM-77 浏览器测试");
  await page.getByPlaceholder("例如：东汉末年").fill("东汉末年");
  await page.getByPlaceholder("保留实际制作信息，便于复用和核对").fill("静水与远山");
  await page.getByRole("button", { name: "上传为候选", exact: true }).click();
  await expect(page.getByText("图片已上传为候选素材。它还没有公开展示", { exact: false })).toBeVisible();
  await expect(page.getByText("候选 · 尚未展示", { exact: true })).toBeVisible();
  assert.equal(createCalls, 0, "upload must not create a public binding");
  const before = await publicBackground(paragraphIds[0]);
  assert.equal(before.status, 200, "public metadata should remain a successful empty read");
  assert.equal(before.body.background, null, "candidate must stay invisible to readers");
  await page.getByLabel("背景范围终点").selectOption(paragraphIds[1]);
  await page.locator("#background-opacity").fill("0.55");
  await page.locator("#background-position-x").fill("0.63");
  await page.locator("#background-position-y").fill("0.42");
  await page.locator("#background-scale").fill("1.2");
  await page.getByLabel("正文遮罩").selectOption("gradient");
  await page.getByLabel("显示背景").uncheck();
  await expect(page.locator(".studio-background-preview")).toHaveAttribute("data-background-visible", "false");
  await page.getByLabel("显示背景").check();
  await page.screenshot({ path: `${output}/studio-before-save.png`, fullPage: true });

  stage = "save, then the reader sees the background only inside the saved range";
  await page.getByRole("button", { name: "保存并显示", exact: true }).click();
  await expect(page.getByText("已保存并显示：", { exact: false })).toBeVisible();
  await expect(page.getByText("已展示 · 1 处", { exact: true })).toBeVisible();
  assert.equal(createCalls, 1);
  const after = await publicBackground(paragraphIds[0]);
  assert.equal(after.status, 200, "saved binding must become publicly readable");
  assert.equal(after.body.background.asset_version_id, assetVersionId);
  await page.goto(readerUrl(paragraphIds[0]));
  await expect(readerBackground()).toHaveAttribute("data-status", "visible");
  await expect(page.locator('[data-test="history-background-image"]')).toHaveAttribute("src", binding.image_href);
  await expect(page.locator('[data-test="history-background"]')).toHaveCSS("pointer-events", "none");
  await page.screenshot({ path: `${output}/reader-after-save.png`, fullPage: true });
  await page.goto(readerUrl(paragraphIds[2]));
  await expect(page.getByText("建安十三年合成正文第 3 段", { exact: false })).toBeVisible();
  await expect(readerBackground()).toHaveCount(0);
  await page.screenshot({ path: `${output}/reader-outside-range.png`, fullPage: true });

  stage = "overlap, wrong-version and service failures keep the Studio draft";
  await page.goto(new URL("/studio/backgrounds", base).href);
  await page.getByRole("button", { name: /red-cliffs\.png/ }).first().click();
  await page.getByLabel("背景范围起点").selectOption(paragraphIds[1]);
  await page.getByLabel("背景范围终点").selectOption(paragraphIds[2]);
  const draft = await studioRange();
  bindingFailure = { code: "overlap_conflict", message: "range overlaps an active binding", status: 409 };
  await page.getByRole("button", { name: "保存并显示", exact: true }).click();
  await assertDraftKept(draft, "与已有背景重叠");
  const afterOverlap = await publicBackground(paragraphIds[1]);
  assert.equal(afterOverlap.body.background.binding_id, bindingId, "overlap failure must not change the public binding");

  bindingFailure = { code: "asset_version_mismatch", message: "asset version does not belong to the asset", status: 400 };
  await page.getByRole("button", { name: "保存并显示", exact: true }).click();
  await assertDraftKept(draft, "图片版本与素材不一致");
  assert.equal((await publicBackground(paragraphIds[1])).body.background.binding_id, bindingId);

  bindingFailure = { code: "unknown_edition", message: "edition is not published", status: 409 };
  await page.getByRole("button", { name: "保存并显示", exact: true }).click();
  await assertDraftKept(draft, "当前 edition 已不可保存");

  stage = "transport failure keeps the same draft";
  await page.route("**/api/v1/studio/background-bindings", async (route) => {
    if (route.request().method() === "POST") return route.abort("failed");
    return route.continue();
  });
  await page.getByRole("button", { name: "保存并显示", exact: true }).click();
  await expect(page.locator(".studio-error", { hasText: "保存未完成" }).last()).toBeVisible();
  await expect(page.getByText("已保存并显示", { exact: false })).toHaveCount(0);
  assert.deepEqual(await studioRange(), draft, "transport failure must keep the range and display draft");
  await page.unroute("**/api/v1/studio/background-bindings");
  assert.equal((await publicBackground(paragraphIds[1])).body.background.binding_id, bindingId);
  await page.screenshot({ path: `${output}/studio-error-draft-kept.png`, fullPage: true });

  stage = "single-location disable restores the paper reader";
  await page.goto(new URL("/studio/backgrounds", base).href);
  await page.getByRole("button", { name: "停用", exact: true }).click();
  await expect(page.getByText("已停用", { exact: true }).last()).toBeVisible();
  assert.equal(disableCalls, 1, "row action must disable the clicked binding");
  const disabledRead = await publicBackground(paragraphIds[0]);
  assert.equal(disabledRead.status, 200);
  assert.equal(disabledRead.body.background, null, "disabled binding must leave the public reader without a background");
  await page.goto(readerUrl(paragraphIds[0]));
  await expect(page.getByText("建安十三年合成正文第 1 段", { exact: false })).toBeVisible();
  await expect(readerBackground()).toHaveCount(0);
  assert.deepEqual(errors, []);
  console.log(`studio-background-component-smoke: PASS; screenshots: ${output}`);
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png`, fullPage: true });
  console.error(`studio-background-component-smoke: FAIL at ${stage}`, errors);
  throw error;
} finally {
  await context.close();
  await browser.close();
}
