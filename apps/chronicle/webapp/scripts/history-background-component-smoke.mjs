#!/usr/bin/env node
// Browser contract for C3-T17. The fixture is deliberately synthetic: it
// proves position/range/loading behavior without claiming anything about
// historical image quality or publication data.
import assert from "node:assert/strict";
import { chromium, expect } from "@playwright/test";

const args = process.argv.slice(2);
const baseIndex = args.indexOf("--base-url");
const base = baseIndex >= 0 ? args[baseIndex + 1] : null;
if (!base) throw new Error("--base-url is required");

const version = "d".repeat(64);
const paragraphId = (ordinal) => `hp_${ordinal.toString(16).padStart(24, "0")}`;
const paragraphs = Array.from({ length: 4 }, (_, ordinal) => ({
  id: paragraphId(ordinal),
  ordinal,
  phase_id: `phase-${ordinal}`,
  group_id: "group-1",
  segments: [{
    text: `背景切换测试正文第 ${ordinal + 1} 段。${"这一段只用于验证阅读位置、文字选择与背景层。".repeat(4)}`,
    conclusion_ids: [], certainty: "clear", event_id: null, event_relation: null, event_text: null,
  }],
  entities: [],
}));
const publication = {
  version,
  catalog_sha: version,
  title: "背景切换浏览器测试",
  paragraph_count: paragraphs.length,
  first_paragraph_id: paragraphs[0].id,
  groups: [{ id: "group-1", year: 208, period: "建安十三年", label: "建安十三年", first_paragraph_id: paragraphs[0].id, count: paragraphs.length }],
  entry_points: [
    { label: "古代图", kind: "period", paragraph_id: paragraphs[0].id, event_id: null, ordinal: 0, year: 208, period: "建安十三年", excerpt: "古代背景" },
    { label: "无图段", kind: "period", paragraph_id: paragraphs[2].id, event_id: null, ordinal: 2, year: 1948, period: "无背景", excerpt: "没有保存背景" },
    { label: "近现代图", kind: "period", paragraph_id: paragraphs[3].id, event_id: null, ordinal: 3, year: 1949, period: "近现代", excerpt: "近现代背景" },
  ],
  navigation: [{
    id: paragraphs[0].id, label: "建安十三年", period: "建安十三年", start: 0, end: 3,
    items: [
      { paragraph_id: paragraphs[0].id, ordinal: 0, label: "古代图", period: "建安十三年", importance: "major" },
      { paragraph_id: paragraphs[2].id, ordinal: 2, label: "无图段", period: "无背景", importance: "major" },
      { paragraph_id: paragraphs[3].id, ordinal: 3, label: "近现代图", period: "近现代", importance: "major" },
    ],
  }],
};
const historyPage = {
  publication_version: version,
  paragraphs,
  start: 0,
  total: paragraphs.length,
  previous_start: null,
  next_start: null,
};
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");
const bindings = {
  ancient: {
    binding_id: "00000000-0000-4000-8000-000000000201",
    asset_id: "00000000-0000-4000-8000-000000000211",
    asset_version_id: "00000000-0000-4000-8000-000000000221",
    start: 0,
    end: 1,
  },
  modern: {
    binding_id: "00000000-0000-4000-8000-000000000202",
    asset_id: "00000000-0000-4000-8000-000000000212",
    asset_version_id: "00000000-0000-4000-8000-000000000222",
    start: 3,
    end: 3,
  },
};
const bindingFor = (ordinal) => ordinal <= 1 ? bindings.ancient : ordinal === 3 ? bindings.modern : null;
const responseFor = (binding, paragraph) => binding ? ({
  binding_id: binding.binding_id,
  edition_version: version,
  start_paragraph_id: paragraphId(binding.start),
  end_paragraph_id: paragraphId(binding.end),
  start_ordinal: binding.start,
  end_ordinal: binding.end,
  asset_id: binding.asset_id,
  asset_version_id: binding.asset_version_id,
  asset_version: 1,
  display: { opacity: 0.42, position: { x: 0.5, y: 0.5 }, scale: 1, mask: null },
  status: "active",
  active: true,
  revision: 1,
  etag: `"${binding.binding_id}"`,
  image_href: `/api/v1/public/background-assets/${binding.asset_id}?version=${version}&paragraph_id=${paragraph.id}`,
  asset: { asset_id: binding.asset_id, asset_version_id: binding.asset_version_id, version: 1, filename: `${binding.binding_id}.png`, media_type: "image/png", width: 1, height: 1 },
}) : null;

const metadataRequests = [];
const imageRequests = [];
let delayModernImage = false;
let modernImageRequested;
let resolveModernImage;
const modernImagePromise = new Promise((resolve) => { resolveModernImage = resolve; });
modernImageRequested = modernImagePromise;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
context.setDefaultTimeout(10_000);
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.route("**/api/v1/public/**", async (route) => {
  const url = new URL(route.request().url());
  if (url.pathname === "/api/v1/public/history") {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ publication }) });
    return;
  }
  if (url.pathname === "/api/v1/public/history/paragraphs") {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(historyPage) });
    return;
  }
  if (url.pathname === "/api/v1/public/backgrounds") {
    const id = url.searchParams.get("paragraph_id");
    const ordinal = paragraphs.findIndex((paragraph) => paragraph.id === id);
    metadataRequests.push(id);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ background: responseFor(bindingFor(ordinal), paragraphs[ordinal]) }) });
    return;
  }
  if (url.pathname.startsWith("/api/v1/public/background-assets/")) {
    const binding = Object.values(bindings).find((candidate) => url.pathname.includes(candidate.asset_id));
    imageRequests.push(binding?.binding_id ?? "unknown");
    if (binding === bindings.modern) {
      resolveModernImage();
      if (delayModernImage) await new Promise((resolve) => setTimeout(resolve, 700));
    }
    await route.fulfill({ status: 200, contentType: "image/png", body: png });
    return;
  }
  await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
});

const background = () => page.locator('[data-test="history-background"]');
const paragraph = (ordinal) => page.locator(`[data-history-paragraph][data-unit-id="${paragraphId(ordinal)}"]`);
const near = () => page.getByRole("navigation", { name: "附近的重要事件" });

let stage = "initial saved range";
try {
  await page.goto(new URL(`/history/${version}/${paragraphs[0].id}`, base).href);
  await expect(paragraph(0)).toBeVisible();
  await expect(background()).toHaveAttribute("data-status", "visible");
  await expect(background()).toHaveAttribute("data-binding-id", bindings.ancient.binding_id);
  await expect.poll(() => metadataRequests.filter((id) => id === paragraphs[1].id).length).toBeGreaterThan(0);
  assert(!metadataRequests.includes(paragraphs[3].id), "initial reader may fetch only the active and adjacent paragraphs");
  await expect(background()).toHaveCSS("pointer-events", "none");
  assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector("[data-test=history-background-image]")).transitionDuration), "0s");
  const bodyHeight = await page.evaluate(() => document.body.scrollHeight);
  await page.getByRole("button", { name: "关闭历史背景" }).focus();
  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "开启历史背景" })).toHaveAttribute("aria-pressed", "false");
  await expect(background()).toHaveCount(0);
  assert.equal(await page.evaluate(() => document.body.scrollHeight), bodyHeight, "background layer must not change document height");
  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "关闭历史背景" })).toHaveAttribute("aria-pressed", "true");

  stage = "unbound paragraph and late image";
  delayModernImage = true;
  await near().getByRole("button", { name: "无图段" }).click();
  await expect(paragraph(2)).toBeVisible();
  await expect(background()).toHaveCount(0);
  await near().getByRole("button", { name: "近现代图" }).click();
  await modernImageRequested;
  await expect(background()).toHaveAttribute("data-status", "loading");
  await near().getByRole("button", { name: "无图段" }).click();
  await expect(paragraph(2)).toBeVisible();
  await expect(background()).toHaveCount(0);
  await page.waitForTimeout(850);
  assert.equal(await page.locator(`[data-test="history-background"][data-binding-id="${bindings.modern.binding_id}"]`).count(), 0, "late modern bytes must not paint over the current paragraph");

  stage = "unbound paragraph and disabled prefetch";
  delayModernImage = false;
  await near().getByRole("button", { name: "近现代图" }).click();
  await expect(background()).toHaveAttribute("data-binding-id", bindings.modern.binding_id);
  await page.getByRole("button", { name: "关闭历史背景" }).click();
  const requestCount = metadataRequests.length + imageRequests.length;
  await page.getByRole("navigation", { name: "历史时间轴" }).getByRole("button", { name: "古代图" }).click();
  await expect(background()).toHaveCount(0);
  await page.waitForTimeout(300);
  assert.equal(metadataRequests.length + imageRequests.length, requestCount, "disabled reader must not prefetch the next background");

  assert.deepEqual(errors, []);
  console.log(`history-background-component-smoke: PASS (range, adjacent preload, reduced motion, toggle, late image discard)`);
} catch (error) {
  console.error(`history-background-component-smoke: FAIL at ${stage}`, errors);
  throw error;
} finally {
  await context.close();
  await browser.close();
}
