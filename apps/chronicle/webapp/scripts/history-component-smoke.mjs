#!/usr/bin/env node
// Real browser + production React routes with explicit synthetic HTTP fixtures.
// This verifies interaction only, never historical content or publication truth.
import assert from "node:assert/strict";
import { chromium, expect } from "@playwright/test";

const args = process.argv.slice(2);
const base = args[args.indexOf("--base-url") + 1];
if (!base || !args.includes("--base-url")) throw new Error("--base-url is required");
const version = "a".repeat(64);
const catalog = "c".repeat(64);
const TOTAL_PARAGRAPHS = 320;
const GROUP_SIZE = 40;
const GROUP_COUNT = Math.ceil(TOTAL_PARAGRAPHS / GROUP_SIZE);
const id = (n) => `hp_${n.toString(16).padStart(24, "0")}`;
const groups = Array.from({ length: GROUP_COUNT }, (_, i) => ({ id: `g${i}`, year: i === 3 ? null : 200 + i,
  period: i === 1 ? "测试历法的长时段（窄屏换行）" : null,
  label: `测试阶段 ${i}`, first_paragraph_id: id(i * GROUP_SIZE), count: Math.min(GROUP_SIZE, TOTAL_PARAGRAPHS - i * GROUP_SIZE) }));
const entries = [
  { label: "汉末局势", kind: "period", ordinal: 0, event_id: null },
  { label: "赤壁之战", kind: "event", ordinal: 20, event_id: "event-1" },
  { label: "荆州局势", kind: "event", ordinal: 45, event_id: "event-2" },
].map((entry) => ({ ...entry, paragraph_id: id(entry.ordinal), year: 200 + Math.floor(entry.ordinal / 10), period: null, excerpt: "合成浏览器测试入口，不是历史验收材料。" }));
const paragraphs = Array.from({ length: TOTAL_PARAGRAPHS }, (_, i) => ({ id: id(i), ordinal: i, phase_id: `phase${i}`, group_id: `g${Math.floor(i / GROUP_SIZE)}`,
  segments: [{ text: i === 0 ? "很短的开篇，定位后仍应停在本段。" : `浏览器测试第 ${i + 1} 段。${i === 20 || i === 5 ? "赤壁之战。" : ""}${"这是一段用于验证滚动和阅读位置的合成正文，测试页面应当保持连续。".repeat(i === 19 || i === 63 || i === TOTAL_PARAGRAPHS - 1 ? 1 : 10)}`,
    conclusion_ids: ["fact-1"], certainty: i === 21 ? "uncertain" : "clear", event_id: i === 20 || i === 5 ? "event-1" : null,
    event_relation: i === 20 ? "current" : i === 5 ? "retrospective" : null, event_text: i === 20 || i === 5 ? "赤壁之战" : null }],
  entities: [{ id: "person-1", name: "曹操", kind: "person", importance: "primary", states: [{ id: "state-1", label: "官职", value: i < 20 ? "测试前期官职" : "测试后期官职", certainty: "clear", reason: "仅用于交互测试" }] },
    { id: "polity-1", name: "测试政权", kind: "polity", importance: "other", states: [] }],
}));
const publication = { version, catalog_sha: catalog, title: "合成阅读测试", paragraph_count: paragraphs.length,
  first_paragraph_id: id(0), groups, entry_points: entries,
  navigation: groups.map((group, n) => ({ id: group.first_paragraph_id, label: group.year === null ? null : `${group.year} 年`, period: null,
    start: n * GROUP_SIZE, end: Math.min(TOTAL_PARAGRAPHS - 1, n * GROUP_SIZE + GROUP_SIZE - 1),
    items: entries.filter((entry) => entry.ordinal >= n * GROUP_SIZE && entry.ordinal < (n + 1) * GROUP_SIZE).map((entry) => ({ ...entry, importance: "major" })),
  })),
};
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
let delayTarget = null;
let failStart = null;
await page.route("**/api/v1/public/**", async (route) => {
  const url = new URL(route.request().url());
  let body = {};
  if (url.pathname === "/api/v1/public/history") body = { publication };
  else if (url.pathname.endsWith("/history/paragraphs")) {
    assert.equal(url.searchParams.get("version"), version);
    const at = url.searchParams.get("at");
    if (at === delayTarget) await new Promise((resolve) => setTimeout(resolve, 900));
    const limit = Number(url.searchParams.get("limit") || 20);
    const start = at ? Math.floor(paragraphs.findIndex((p) => p.id === at) / limit) * limit : Number(url.searchParams.get("start") || 0);
    body = { publication_version: version, paragraphs: paragraphs.slice(start, start + limit), start, total: paragraphs.length,
      previous_start: start ? Math.max(0, start - limit) : null, next_start: start + limit < paragraphs.length ? start + limit : null };
    if (start === failStart) {
      failStart = null;
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ code: "temporary_failure" }) });
      return;
    }
  } else if (url.pathname.includes("/history/conclusions/")) body = { publication_version: version, conclusion: { id: "fact-1", question: "合成依据", text: "仅验证按需查看", certainty: "clear", reason: "测试", evidence: [] }, source_relations: [] };
  else if (url.pathname.includes("/entities/")) body = { canonical_entity_id: "person-1", display: { name: "曹操", type: "person" }, events: [], claims: [], representations: [] };
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
});
const paragraph = (n) => page.locator(`[data-unit-id="${id(n)}"]`);
const near = () => page.getByRole("navigation", { name: "附近的重要事件" });
try {
  await page.goto(base);
  await expect(page.locator('[data-test="home-time-anchor"]')).toHaveCount(1);
  await expect(page.locator('[data-test="home-event-anchor"]')).toHaveCount(2);
  await page.getByRole("link", { name: /汉末局势/ }).click();
  await expect(paragraph(0)).toBeVisible();
  await expect(page.locator('[data-test="reading-context-entity"]')).toContainText("测试前期官职");
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  await expect(page.locator('[data-test="reading-context-panel"]')).toHaveAttribute("data-unit", id(0));
  await expect(page.locator('[data-test="history-phase-status"]')).toHaveAttribute("data-phase-id", "phase0");
  await page.setViewportSize({ width: 1440, height: 860 });
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.locator('[data-test="reading-context-panel"]')).toHaveAttribute("data-unit", id(0));
  await page.setViewportSize({ width: 1440, height: 900 });
  assert.equal(new URL(page.url()).search, "", "public positions use system ID path segments");
  await expect(page.locator('[data-test="history-phase-status"]')).toHaveText("");
  await expect(page.getByRole("heading", { name: "政权与机构" })).toHaveCount(0);
  await page.locator('[data-test="reading-context-more"]').click();
  await expect(page.getByRole("heading", { name: "政权与机构" })).toBeVisible();
  const axis = page.getByRole("navigation", { name: "历史时间轴" });
  await expect(axis.locator(".history-axis-node")).toHaveCount(3);
  await expect(axis.locator("[aria-expanded]")).toHaveCount(0);
  await expect(axis.locator(".history-axis-time")).toHaveCount(7);
  await expect(axis).not.toContainText("年代未详");
  await expect(axis).not.toContainText("从这段读起");
  await expect(axis).not.toContainText("测试阶段");
  await expect(page.locator(".history-desktop-time")).toHaveCount(0);
  const firstGroup = axis.locator(".history-axis-time").first();
  const groupUrl = page.url();
  const groupScroll = await page.evaluate(() => window.scrollY);
  await firstGroup.click();
  assert.equal(page.url(), groupUrl, "time ticks do not navigate or collapse the rail");
  assert.equal(await page.evaluate(() => window.scrollY), groupScroll, "time ticks do not move prose");
  await page.getByRole("button", { name: "回到当前", exact: true }).click();

  await paragraph(18).scrollIntoViewIfNeeded();
  await expect(paragraph(20)).toBeAttached();
  await near().getByRole("button", { name: /赤壁之战/ }).click();
  await expect.poll(() => page.url()).toContain(`/history/${version}/${id(20)}`);
  await expect(paragraph(20)).toBeFocused();
  await expect(page.locator('[data-test="reading-context-entity"]')).toContainText("测试后期官职");
  // Escape must dismiss a mouse-hover preview even when its trigger is not focused.
  await paragraph(20).getByRole("button", { name: "赤壁之战", exact: true }).hover();
  await expect(page.getByRole("group", { name: "赤壁之战阅读位置" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("group", { name: "赤壁之战阅读位置" })).toHaveCount(0);
  await paragraph(20).getByRole("button", { name: "赤壁之战", exact: true }).click();
  await expect(page.getByRole("group", { name: "赤壁之战阅读位置" })).toBeVisible();
  await page.getByRole("group", { name: "赤壁之战阅读位置" }).getByRole("button", { name: "读到这里" }).focus();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("group", { name: "赤壁之战阅读位置" })).toHaveCount(0);
  await expect(paragraph(20).getByRole("button", { name: "赤壁之战", exact: true })).toBeFocused();

  await page.getByRole("button", { name: "阅读资料", exact: true }).click();
  await page.getByRole("button", { name: "查看依据 1" }).click();
  await expect(page.getByText("仅验证按需查看", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "关闭面板" }).click();
  await expect(page.getByRole("button", { name: "阅读资料", exact: true })).toBeFocused();

  // Leaving in the middle of the same long paragraph must save its live offset.
  await page.evaluate(() => window.scrollBy(0, 160));
  await page.waitForTimeout(100);
  const beforeDetail = await paragraph(20).evaluate((node) => node.getBoundingClientRect().top);
  await page.locator('[data-test="reading-context-view-entity"]').first().click();
  await expect(page.getByRole("link", { name: "返回历史正文" })).toBeVisible();
  await expect(page.getByRole("link", { name: "进入相关正文" })).toHaveCount(0);
  await page.getByRole("link", { name: "返回历史正文" }).click();
  await expect(paragraph(20)).toBeAttached();
  await expect.poll(async () => Math.abs(await paragraph(20).evaluate((node) => node.getBoundingClientRect().top) - beforeDetail)).toBeLessThan(3);

  delayTarget = id(45);
  await near().getByRole("button", { name: /荆州局势/ }).click();
  await page.mouse.wheel(0, 80);
  await page.waitForTimeout(1100);
  assert(!page.url().includes(`/${id(45)}`), "late navigation must not change the URL after user scroll");
  await expect(paragraph(20)).toBeAttached();
  await expect(paragraph(45)).toHaveCount(0);
  delayTarget = null;

  await near().getByRole("button", { name: /荆州局势/ }).click();
  await expect.poll(() => page.url()).toContain(`/history/${version}/${id(45)}`);
  await page.goBack();
  await expect(paragraph(20)).toBeAttached();
  assert(!page.url().includes(`/${id(45)}`));
  await page.reload();
  await expect(paragraph(20)).toBeAttached();
  assert(page.url().includes(`/history/${version}/`));

  // A single global edition crosses the synthetic three-fragment boundary;
  // the page request remains versioned and the controller keeps one stream.
  await page.goto(`${base}/history/${version}/${id(170)}`);
  await expect(paragraph(170)).toBeAttached();
  await expect(page.locator('[data-test="reading-context-panel"]')).toHaveAttribute("data-unit", id(170));
  await expect(page.locator('[data-test="reading-context-entity"]')).toContainText("测试后期官职");
  failStart = 200;
  await expect(paragraph(199)).toBeAttached();
  await paragraph(199).scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, 100));
  await page.waitForTimeout(300);
  await expect(page.locator('[data-test="reading-load-error"]')).toBeVisible();
  await expect(paragraph(170)).toBeAttached();
  await page.locator('[data-test="reading-retry"]').click();
  await expect(paragraph(200)).toBeAttached();
  await expect(page.locator('[data-test="reading-load-error"]')).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: /此时此地/ })).toBeVisible();
  await page.getByRole("button", { name: /此时此地/ }).click();
  await near().getByRole("button", { name: /荆州局势/ }).click();
  await expect(paragraph(45)).toBeFocused();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), "mobile page must not overflow horizontally");

  // Short paragraphs at a page boundary must remain the located reading point.
  // Without trailing scroll room, the browser clamps the scroll before them,
  // and the next frame silently replaces the requested URL/context with an earlier paragraph.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${base}/history?version=${version}&at=${id(19)}`);
  await expect(paragraph(20)).toBeAttached();
  await page.waitForTimeout(400);
  await expect(page.locator('[data-test="reading-context-panel"]')).toHaveAttribute("data-unit", id(19));
  assert(page.url().endsWith(`/${id(19)}`));
  await page.goto(`${base}/history?version=${version}&at=${id(63)}`);
  await expect(page.locator('[data-test="reading-context-panel"]')).toHaveAttribute("data-unit", id(63));
  await page.waitForTimeout(400);
  await expect(page.locator('[data-test="reading-context-panel"]')).toHaveAttribute("data-unit", id(63));
  assert(page.url().endsWith(`/${id(63)}`));

  // A longer date wraps the compact bar after the target becomes active.
  // Wait beyond URL settling: a transient target followed by the preceding
  // paragraph is a failure even though the initial jump appeared to work.
  await page.setViewportSize({ width: 320, height: 844 });
  const stableMobileTarget = async (n) => {
    await expect(paragraph(n)).toBeAttached();
    await page.waitForTimeout(600);
    await page.getByRole("button", { name: /此时此地/ }).click();
    await expect(page.locator('[data-test="reading-context-panel"]')).toHaveAttribute("data-unit", id(n));
    await expect(page.locator('[data-test="history-phase-status"]')).toHaveAttribute("data-phase-id", `phase${n}`);
    assert(page.url().endsWith(`/${id(n)}`), `mobile locator must remain at paragraph ${n}`);
    await page.locator('[data-test="reading-context-close"]').click();
  };
  await page.goto(`${base}/history?version=${version}&at=${id(16)}`);
  await stableMobileTarget(16);
  await page.reload();
  await stableMobileTarget(16);
  await page.locator(".history-axis-open").click();
  await page.getByRole("navigation", { name: "历史时间轴" }).getByRole("button", { name: /汉末局势/ }).click();
  await stableMobileTarget(0);
  await page.locator(".history-axis-open").click();
  await page.getByRole("navigation", { name: "历史时间轴" }).getByRole("button", { name: /赤壁之战/ }).click();
  await stableMobileTarget(20);
  await page.goto(`${base}/history/${version}/${id(10)}`);
  await stableMobileTarget(10);
  await page.setViewportSize({ width: 390, height: 844 });
  await stableMobileTarget(10);
  await page.mouse.move(190, 620);
  await page.mouse.wheel(0, -180);
  await stableMobileTarget(9);
  await page.mouse.wheel(0, 240);
  await stableMobileTarget(10);

  // Native prose scrolling follows an undated interval with no event anchors
  // in the axis's own scrollport, including short-height desktop viewports.
  await page.setViewportSize({ width: 1440, height: 540 });
  await page.goto(`${base}/history/${version}/${id(134)}`);
  await expect(paragraph(134)).toBeAttached();
  await paragraph(134).evaluate((node) => node.scrollIntoView({ block: "start" }));
  const proseTop = await paragraph(134).evaluate((node) => node.getBoundingClientRect().top);
  await expect(page.locator('[data-test="reading-context-panel"]')).toHaveAttribute("data-unit", id(134));
  await expect(page.locator('.history-axis-section[data-current="true"]')).toHaveAttribute("data-axis-section", id(120));
  await expect(page.locator('.history-axis-position[aria-current="location"]')).toHaveCount(1);
  await expect(page.locator('.history-axis-time[aria-current="location"]')).toHaveCount(0);
  await expect.poll(() => page.locator(".history-axis-scroll").evaluate((box) => {
    const item = box.querySelector('[data-axis-current="true"]');
    const target = item.getBoundingClientRect(), viewport = box.getBoundingClientRect();
    return target.top >= viewport.top && target.bottom <= viewport.bottom;
  })).toBe(true);
  assert(Math.abs(await paragraph(134).evaluate((node) => node.getBoundingClientRect().top) - proseTop) < 3, "axis follow must preserve prose position");
  const beforeAxisBrowse = await page.evaluate(() => window.scrollY);
  await page.locator(".history-axis-scroll").hover();
  await page.mouse.wheel(0, -1500);
  await expect(page.getByRole("button", { name: "回到当前", exact: true })).toBeVisible();
  await page.waitForTimeout(200);
  assert.equal(await page.evaluate(() => window.scrollY), beforeAxisBrowse, "axis wheel must not leak into prose scrolling");
  await page.getByRole("button", { name: "回到当前", exact: true }).click();
  await expect(page.locator(".history-axis")).toHaveAttribute("data-following", "true");

  // The native dialog is initially display:none. Opening it must reveal the
  // current marker after layout, including late positions on short phones.
  await page.setViewportSize({ width: 320, height: 540 });
  await page.goto(`${base}/history/${version}/${id(TOTAL_PARAGRAPHS - 1)}`);
  await stableMobileTarget(TOTAL_PARAGRAPHS - 1);
  for (let opened = 0; opened < 2; opened++) {
    await page.locator(".history-axis-open").click();
    await expect.poll(() => page.locator("dialog .history-axis-scroll").evaluate((box) => {
      const marker = box.querySelector('[data-axis-current="true"]');
      if (!marker) return false;
      const item = marker.getBoundingClientRect(), frame = box.getBoundingClientRect();
      const dialog = box.closest("dialog").getBoundingClientRect();
      return item.top >= frame.top && item.bottom <= Math.min(frame.bottom, dialog.bottom);
    })).toBe(true);
    await page.keyboard.press("Escape");
    assert(page.url().endsWith(`/${id(TOTAL_PARAGRAPHS - 1)}`), "opening the axis must preserve the prose locator");
  }
  assert.deepEqual(errors, []);
  console.log("history-component-smoke: PASS (curated entries, paging, state, focus, previews, evidence, cancellation, back/refresh, mobile, short boundary/end paragraphs, wrapped dates on deep link/reload/jump/resize/scroll)");
} finally { await browser.close(); }
