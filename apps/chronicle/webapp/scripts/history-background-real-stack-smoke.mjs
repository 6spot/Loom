#!/usr/bin/env node
// T16 acceptance against a real T15 backend (Rust chronicle-server + Python
// read sidecar + PostgreSQL + the persisted background volume).
//
// It drives the real Studio page and the real public reader page and proves:
//   1. an uploaded candidate is invisible to readers until "保存并显示";
//   2. after the save, the reader page shows the saved image inside the exact
//      saved range and the plain paper page outside it;
//   3. overlap, wrong-version and service failures keep the Studio candidate,
//      range, display draft and current position and never claim "已启用".
//
// Prerequisites: a running stack with one published history edition that has
// at least four paragraphs, and the Studio administrator credentials in
// CHRONICLE_ADMIN_USER / CHRONICLE_ADMIN_PASSWORD. Seed the edition inside the
// stack with the real contract fixture, for example:
//
//   docker compose -f compose.chronicle.yaml exec -T chronicle-read python3 - <<'PY'
//   import os, sys, psycopg
//   sys.path[:0] = ["apps/chronicle/persistence", "apps/chronicle/read_api"]
//   from history_edition_contract import contract_fixture
//   import history_edition_store as store
//   fixture = contract_fixture(paragraphs_per_fragment=5, fragment_count=1)
//   with psycopg.connect(os.environ["CHRONICLE_DATABASE_URL"]) as conn:
//       draft = store.create_draft(conn, fragments=fixture["fragments"],
//                                  boundary_reviews=fixture["boundary_reviews"],
//                                  navigation=fixture["navigation"])
//       store.publish_draft(conn, draft["draft_id"])
//   PY
//
// Usage:
//   node scripts/history-background-real-stack-smoke.mjs --base-url http://127.0.0.1:8080
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium, expect } from "@playwright/test";

const args = process.argv.slice(2);
const baseIndex = args.indexOf("--base-url");
const base = baseIndex >= 0 ? args[baseIndex + 1] : null;
if (!base) throw new Error("--base-url is required");
const outputIndex = args.indexOf("--output");
const output = outputIndex >= 0 ? args[outputIndex + 1] : "/tmp/chronicle-background-real-stack";
await mkdir(output, { recursive: true });
const adminUser = process.env.CHRONICLE_ADMIN_USER;
const adminPassword = process.env.CHRONICLE_ADMIN_PASSWORD;
if (!adminUser || !adminPassword) throw new Error("CHRONICLE_ADMIN_USER and CHRONICLE_ADMIN_PASSWORD are required");
const basicAuth = `Basic ${Buffer.from(`${adminUser}:${adminPassword}`).toString("base64")}`;
const unknownEdition = "f".repeat(64);

const gradientPng = (dataUrl) => Buffer.from(dataUrl.split(",")[1], "base64");
const errors = [];
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", serviceWorkers: "block" });
context.setDefaultTimeout(15_000);
const page = await context.newPage();
page.on("pageerror", (error) => errors.push(error.message));

const apiRequest = (path, init) => page.evaluate(async ({ path, init }) => {
  const result = await fetch(path, init);
  const text = await result.text();
  return { status: result.status, body: text ? JSON.parse(text) : null };
}, { path, init });
const readerBackground = () => page.locator('[data-test="history-background"]');
const backgroundImage = () => page.locator('[data-test="history-background-image"]');
const studioRange = async () => ({
  start: await page.getByLabel("背景范围起点").inputValue(),
  end: await page.getByLabel("背景范围终点").inputValue(),
  opacity: await page.locator("#background-opacity").inputValue(),
  positionX: await page.locator("#background-position-x").inputValue(),
  positionY: await page.locator("#background-position-y").inputValue(),
  scale: await page.locator("#background-scale").inputValue(),
  mask: await page.getByLabel("正文遮罩").inputValue(),
  summary: (await page.locator(".studio-background-range-summary").innerText()).trim(),
});
const publicBackground = (version, paragraphId) =>
  apiRequest(`/api/v1/public/backgrounds?version=${version}&paragraph_id=${paragraphId}`);
const interceptBindingPost = (handler) => page.route("**/api/v1/studio/background-bindings", async (route) => {
  if (route.request().method() !== "POST") return route.continue();
  return handler(route);
});
const rewritePayload = (mutate) => async (route) => {
  const payload = route.request().postDataJSON();
  await route.continue({ postData: JSON.stringify(mutate(payload)) });
};
const assertDraftKept = async (before, expectedError) => {
  await expect(page.locator(".studio-error", { hasText: "保存未完成" }).last()).toContainText(expectedError);
  await expect(page.getByText("已保存并显示", { exact: false })).toHaveCount(0);
  await expect(page.locator(".studio-background-asset-card.is-selected")).toHaveCount(1);
  assert.deepEqual(await studioRange(), before, "failed save must keep the asset, range, display draft and current position");
};
const drawCandidate = (page) => page.evaluate(() => {
  const canvas = document.createElement("canvas");
  canvas.width = 960;
  canvas.height = 640;
  const context2d = canvas.getContext("2d");
  const gradient = context2d.createLinearGradient(0, 0, 960, 640);
  gradient.addColorStop(0, "#1f3a5f");
  gradient.addColorStop(0.55, "#7d2f2f");
  gradient.addColorStop(1, "#e6d6a8");
  context2d.fillStyle = gradient;
  context2d.fillRect(0, 0, 960, 640);
  context2d.fillStyle = "#f5ecd7";
  context2d.beginPath();
  context2d.arc(700, 180, 96, 0, Math.PI * 2);
  context2d.fill();
  context2d.fillStyle = "#d8b26a";
  context2d.beginPath();
  context2d.moveTo(0, 520);
  context2d.lineTo(220, 360);
  context2d.lineTo(420, 540);
  context2d.lineTo(640, 380);
  context2d.lineTo(960, 560);
  context2d.lineTo(960, 640);
  context2d.lineTo(0, 640);
  context2d.closePath();
  context2d.fill();
  return canvas.toDataURL("image/png");
});

let stage = "discover the published edition";
try {
  await page.goto(new URL("/", base).href);
  const directory = await apiRequest("/api/v1/public/history");
  assert.equal(directory.status, 200, "public history directory must answer");
  const publication = directory.body?.publication ?? directory.body?.edition;
  assert(publication, "seed a published history edition before running this scenario");
  const version = publication.version;
  const firstPage = await apiRequest(`/api/v1/public/history/paragraphs?version=${version}&start=0&limit=20`);
  assert.equal(firstPage.status, 200);
  const paragraphs = firstPage.body.paragraphs;
  assert(paragraphs.length >= 4, `the scenario needs at least 4 paragraphs, got ${paragraphs.length}`);
  const [outside, first, second, third] = paragraphs.map((paragraph) => paragraph.id);

  stage = "login and upload a candidate in Studio";
  await page.goto(new URL("/studio/login", base).href);
  await page.getByLabel(/^用户名/).fill(adminUser);
  await page.getByLabel(/^密码/).fill(adminPassword);
  await page.getByRole("button", { name: "登录管理工作台", exact: true }).click();
  await expect(page).toHaveURL(/\/studio$/);
  await page.goto(new URL("/studio/backgrounds", base).href);
  await expect(page.getByRole("heading", { name: "背景素材库", exact: true })).toBeVisible();
  await expect(page.getByText("当前没有已发布历史 edition", { exact: true })).toHaveCount(0);

  const filename = `real-stack-${Date.now()}.png`;
  const variantFilename = `real-stack-variant-${Date.now()}.png`;
  const png = gradientPng(await drawCandidate(page));
  await page.getByLabel("选择背景图片", { exact: true }).setInputFiles({ name: filename, mimeType: "image/png", buffer: png });
  await page.getByPlaceholder("例如：skill 归档 / 操作员上传").fill("T15 真后端场景");
  await page.getByPlaceholder("例如：东汉末年").fill("东汉末年");
  await page.getByPlaceholder("保留实际制作信息，便于复用和核对").fill("渐变江面与远山，仅用于 LM-77 真后端验收。");
  await page.getByRole("button", { name: "上传为候选", exact: true }).click();
  await expect(page.getByText("图片已上传为候选素材。它还没有公开展示", { exact: false })).toBeVisible();
  await expect(page.locator(".studio-background-asset-card", { hasText: filename }).getByText("候选 · 尚未展示", { exact: true })).toBeVisible();

  stage = "reader page stays on paper while the candidate is unsaved";
  const beforeSave = await publicBackground(version, first);
  assert.equal(beforeSave.status, 200);
  assert.equal(beforeSave.body.background, null, "candidate must stay invisible to readers");
  await page.goto(new URL(`/history/${version}/${first}`, base).href);
  await expect(page.locator(`[data-history-paragraph][data-unit-id="${first}"]`)).toBeVisible();
  await expect(readerBackground()).toHaveCount(0);
  await page.screenshot({ path: `${output}/reader-before-save.png`, fullPage: true });

  stage = "save the explicit range and display with keyboard-only actions";
  await page.goto(new URL("/studio/backgrounds", base).href);
  await page.getByRole("button", { name: new RegExp(filename) }).first().click();
  await page.getByLabel("背景范围起点").selectOption(first);
  await page.getByLabel("背景范围终点").selectOption(second);
  await page.locator("#background-opacity").fill("0.5");
  await page.locator("#background-position-x").fill("0.4");
  await page.locator("#background-position-y").fill("0.35");
  await page.locator("#background-scale").fill("1.1");
  await page.getByLabel("正文遮罩").selectOption("gradient");
  await page.getByLabel("显示背景").focus();
  await page.keyboard.press("Space");
  await expect(page.locator(".studio-background-preview")).toHaveAttribute("data-background-visible", "false");
  await page.keyboard.press("Space");
  await expect(page.locator(".studio-background-preview")).toHaveAttribute("data-background-visible", "true");
  await page.locator("#background-scale").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.locator("#background-scale")).toHaveValue("1.2");
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect(page.getByRole("button", { name: "保存并显示", exact: true })).toBeInViewport();
  await page.getByRole("button", { name: "保存并显示", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("已保存并显示：", { exact: false })).toBeVisible();
  await expect(page.locator(".studio-background-asset-card", { hasText: filename }).getByText("已展示 · 1 处", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: /打开读者历史/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp("/history$"));

  stage = "reader page shows the saved background inside the exact range only";
  const saved = await publicBackground(version, first);
  assert.equal(saved.status, 200);
  assert(saved.body.background, "saved binding must be publicly readable");
  const bindingId = saved.body.background.binding_id;
  assert.equal((await publicBackground(version, second)).body.background.binding_id, bindingId);
  assert.equal((await publicBackground(version, outside)).body.background, null, "outside the saved range readers stay on paper");
  await page.goto(new URL(`/history/${version}/${first}`, base).href);
  await expect(page.locator(`[data-history-paragraph][data-unit-id="${first}"]`)).toBeVisible();
  await expect(readerBackground()).toHaveAttribute("data-status", "visible");
  await expect(backgroundImage()).toHaveAttribute("src", new RegExp("/api/v1/public/background-assets/"));
  await page.waitForFunction(() => {
    const image = document.querySelector('[data-test="history-background-image"]');
    return image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0;
  });
  await expect(readerBackground()).toHaveCSS("pointer-events", "none");
  await page.screenshot({ path: `${output}/reader-after-save.png`, fullPage: true });
  await page.goto(new URL(`/history/${version}/${outside}`, base).href);
  await expect(page.locator(`[data-history-paragraph][data-unit-id="${outside}"]`)).toBeVisible();
  await expect(readerBackground()).toHaveCount(0);
  await page.screenshot({ path: `${output}/reader-outside-range.png`, fullPage: true });

  stage = "prepare a second candidate for the wrong-version failure";
  await page.goto(new URL("/studio/backgrounds", base).href);
  await page.getByLabel("选择背景图片", { exact: true }).setInputFiles({ name: variantFilename, mimeType: "image/png", buffer: png });
  await page.getByPlaceholder("例如：skill 归档 / 操作员上传").fill("T15 真后端场景（对照版本）");
  await page.getByPlaceholder("例如：东汉末年").fill("东汉末年");
  await page.getByPlaceholder("保留实际制作信息，便于复用和核对").fill("用于错版本错误路径的第二张候选。");
  await page.getByRole("button", { name: "上传为候选", exact: true }).click();
  await expect(page.getByText("图片已上传为候选素材。它还没有公开展示", { exact: false })).toBeVisible();
  const assetList = await apiRequest("/api/v1/studio/background-assets?limit=100", { headers: { Authorization: basicAuth } });
  assert.equal(assetList.status, 200);
  const variant = assetList.body.assets.find((asset) => asset.filename === variantFilename);
  assert(variant, "the second candidate must be listed by the real Studio API");

  stage = "overlap conflict keeps the Studio draft";
  await page.getByRole("button", { name: new RegExp(filename) }).first().click();
  await page.getByLabel("背景范围起点").selectOption(second);
  await page.getByLabel("背景范围终点").selectOption(third);
  await expect(page.locator(".studio-background-range-summary")).toContainText("已载入正文预览");
  const draft = await studioRange();
  await page.getByRole("button", { name: "保存并显示", exact: true }).click();
  await assertDraftKept(draft, "与已有背景重叠");
  assert.equal((await publicBackground(version, second)).body.background.binding_id, bindingId, "a failed overlap must not move the public binding");

  stage = "wrong asset version is rejected by the real backend and keeps the draft";
  await interceptBindingPost(rewritePayload((payload) => ({ ...payload, asset_version_id: variant.asset_version_id })));
  await page.getByRole("button", { name: "保存并显示", exact: true }).click();
  await assertDraftKept(draft, "图片版本与素材不一致");
  assert.equal((await publicBackground(version, second)).body.background.binding_id, bindingId);
  await page.unroute("**/api/v1/studio/background-bindings");

  stage = "wrong edition is rejected by the real backend and keeps the draft";
  await interceptBindingPost(rewritePayload((payload) => ({ ...payload, edition_version: unknownEdition })));
  await page.getByRole("button", { name: "保存并显示", exact: true }).click();
  await assertDraftKept(draft, "当前 edition 已不可保存");
  assert.equal((await publicBackground(version, second)).body.background.binding_id, bindingId);
  await page.unroute("**/api/v1/studio/background-bindings");

  stage = "service failure keeps the draft and never claims enabled";
  await interceptBindingPost((route) => route.abort("failed"));
  await page.getByRole("button", { name: "保存并显示", exact: true }).click();
  await expect(page.locator(".studio-error", { hasText: "保存未完成" }).last()).toBeVisible();
  await expect(page.getByText("已保存并显示", { exact: false })).toHaveCount(0);
  assert.deepEqual(await studioRange(), draft, "transport failure must keep the asset, range, display draft and current position");
  await page.unroute("**/api/v1/studio/background-bindings");
  assert.equal((await publicBackground(version, second)).body.background.binding_id, bindingId);
  await page.screenshot({ path: `${output}/studio-error-draft-kept.png`, fullPage: true });

  stage = "single-location disable restores the paper reader and keeps both candidates";
  await page.goto(new URL("/studio/backgrounds", base).href);
  await page.getByRole("button", { name: "停用", exact: true }).first().click();
  await expect(page.getByText("已停用", { exact: true }).last()).toBeVisible();
  assert.equal((await publicBackground(version, first)).body.background, null, "disabled binding must leave the public reader without a background");
  assert.equal((await publicBackground(version, second)).body.background, null, "disabling one binding must clear the whole saved range");
  await expect(page.getByRole("button", { name: new RegExp(filename) }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: new RegExp(variantFilename) }).first()).toBeVisible();
  await page.goto(new URL(`/history/${version}/${first}`, base).href);
  await expect(page.locator(`[data-history-paragraph][data-unit-id="${first}"]`)).toBeVisible();
  await expect(readerBackground()).toHaveCount(0);

  assert.deepEqual(errors, []);
  console.log(`history-background-real-stack-smoke: PASS; edition=${version}; binding=${bindingId}; screenshots: ${output}`);
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png`, fullPage: true });
  console.error(`history-background-real-stack-smoke: FAIL at ${stage}`, errors);
  throw error;
} finally {
  await context.close();
  await browser.close();
}
