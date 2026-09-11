#!/usr/bin/env node
// C2-R3-D02 人物階段資料交互 harness 的真實瀏覽器驗收（僅測試使用）。
//
// 直接提供一個自包含的 Vite fixture 頁面（`scenes/person-state-harness/index.html`），
// 因此 D02 不修改共享 `main.tsx` / `cases/types.ts` / `harness.mjs`。T01 之後可在
// 共享 runner 註冊本文件導出的 `run(ctx)`；此處同時可獨立執行：
//
//   node apps/chronicle/webapp/tests/reading-browser/person-state-harness.mjs \
//     --base-url http://127.0.0.1:5173 --scene all \
//     --output /tmp/chronicle-r3-d02
//
// `ctx` 需提供 check / info / screenshot / openScene（與共享 runner 一致）。

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";
import os from "node:os";

export const FIXTURE_PATH = "/tests/fixtures/reading/scenes/person-state-harness/index.html";
export const SCENE_NAMES = ["reading", "review", "entity"];
export const D02_TASK = "C2-R3-D02";

const HERE = dirname(fileURLToPath(import.meta.url));

export function fixtureUrl(baseUrl, params = {}) {
  const url = new URL(FIXTURE_PATH, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  return url.toString();
}

const VIEWPORTS = [
  { name: "desktop-1440", width: 1440, height: 900 },
  { name: "mid-1024", width: 1024, height: 768 },
  { name: "phone-390", width: 390, height: 844 },
  { name: "phone-320", width: 320, height: 568 },
];

async function waitIdle(page, selector) {
  await page.waitForSelector(selector, { timeout: 15000 });
}

async function overflowX(page) {
  return await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

/** 量測可互動元素的觸控高度；回傳最小值與違規清單。 */
async function minTouchHeight(page, selector) {
  return await page.$$eval(selector, (nodes) =>
    nodes.map((node) => ({
      selector: node.getAttribute("data-test") || node.className,
      height: node.getBoundingClientRect().height,
    })),
  );
}

async function contrastReport(page) {
  return await page.evaluate(() => {
    function parse(color) {
      const match = color.match(/rgba?\(([^)]+)\)/);
      if (!match) return null;
      const parts = match[1].split(",").map((value) => Number(value.trim()));
      return { r: parts[0], g: parts[1], b: parts[2], a: parts[3] ?? 1 };
    }
    function luminance({ r, g, b }) {
      const channel = (value) => {
        const v = value / 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
      };
      return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
    }
    function ratio(fg, bg) {
      const l1 = luminance(fg);
      const l2 = luminance(bg);
      return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    }
    function backgroundOf(node) {
      let current = node;
      while (current) {
        const color = parse(getComputedStyle(current).backgroundColor);
        if (color && color.a > 0) return color;
        current = current.parentElement;
      }
      return { r: 255, g: 255, b: 255, a: 1 };
    }
    function measure(selector) {
      const node = document.querySelector(selector);
      if (!node) return null;
      const color = parse(getComputedStyle(node).color);
      return ratio(color, backgroundOf(node));
    }
    return {
      clear: measure('[data-test="person-state-item"][data-certainty="clear"] .pstate-item-value'),
      uncertain: measure('[data-test="person-state-item"][data-certainty="uncertain"] .pstate-item-value'),
      qualification: measure('[data-test="person-state-qualification"]'),
    };
  });
}

async function coverMatrix(page, ctx) {
  const count = async (selector) => await page.locator(selector).count();
  ctx.check("matrix-clear", (await count('[data-test="person-state-item"][data-certainty="clear"]')) > 0, "no clear item");
  ctx.check("matrix-uncertain", (await count('[data-test="person-state-item"][data-certainty="uncertain"]')) > 0, "no uncertain item");
  ctx.check("matrix-concurrent", (await count('[data-item-id="zy-office-nanjun"]')) === 1, "concurrent office missing");
  ctx.check("matrix-process", (await count('[data-phase-mode="process"]')) >= 1, "process phase missing");
  ctx.check("matrix-ambiguous", (await count('[data-phase-mode="ambiguous"]')) >= 1, "ambiguous phase missing");
  ctx.check("matrix-disagreement", (await count('[data-reason="source_disagreement"]')) >= 2, "disagreement items missing");
  ctx.check("matrix-no-record", (await count('[data-empty-kind="no_record"]')) === 1, "no_record empty state missing");
  ctx.check("matrix-stage-unknown", (await count('[data-empty-kind="stage_unknown"]')) === 1, "stage_unknown empty state missing");
  const partialClarity = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-test="person-state-subject"]')).some((subject) => {
      const items = Array.from(subject.querySelectorAll('[data-test="person-state-item"]'));
      return (
        items.some((item) => item.getAttribute("data-certainty") === "clear") &&
        items.some((item) => item.getAttribute("data-certainty") === "uncertain")
      );
    }),
  );
  ctx.check("matrix-partial-clarity", partialClarity, "no subject carries both clear and uncertain items");
}

async function readingSuite(ctx) {
  const page = await ctx.openScene("reading", { viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await waitIdle(page, '[data-test="person-state-reading-scene"]');

  ctx.check("reading-synthetic-flag", (await page.locator('[data-test="person-state-synthetic-flag"]').innerText()).includes("合成"));
  await coverMatrix(page, ctx);

  // 桌面三欄：正文優先，右欄為當時人物地點。
  const grid = await page.evaluate(() => {
    const grid = document.querySelector(".rpage-grid");
    const context = document.querySelector('[data-test="person-state-context-column"]');
    return {
      columns: getComputedStyle(grid).gridTemplateColumns.split(" ").length,
      contextVisible: context ? context.getBoundingClientRect().width > 0 && getComputedStyle(context).display !== "none" : false,
      bodyWidth: document.querySelector('[data-test="person-state-body"]').getBoundingClientRect().width,
    };
  });
  ctx.check("desktop-three-columns", grid.columns === 3, `columns=${grid.columns}`);
  ctx.check("desktop-context-column-visible", grid.contextVisible);
  ctx.check("body-is-primary-column", grid.bodyWidth > 300, `bodyWidth=${grid.bodyWidth}`);
  ctx.info("desktop_grid_columns", grid.columns);

  // 顏色以外可辨識：實心/空心標記同時存在，且非 disabled。
  ctx.check("marker-solid-and-hollow", (await page.locator('.chr-state-mark:has-text("●")').count()) > 0 && (await page.locator('.chr-state-mark:has-text("○")').count()) > 0);
  ctx.check("uncertain-not-disabled", (await page.locator('[data-test="person-state-item"][data-certainty="uncertain"] button[disabled]').count()) === 0);
  const contrast = await contrastReport(page);
  ctx.info("contrast_ratios", contrast);
  ctx.check("contrast-clear-aa", contrast.clear >= 4.5, `clear=${contrast.clear}`);
  ctx.check("contrast-uncertain-aa", contrast.uncertain >= 4.5, `uncertain=${contrast.uncertain}`);
  ctx.check("contrast-qualification-aa", contrast.qualification >= 4.5, `qualification=${contrast.qualification}`);

  // 觸控面積：緊湊行、依據、來源操作至少 44px。
  const touch = [
    ...(await minTouchHeight(page, '[data-test="person-state-view-detail"]')),
    ...(await minTouchHeight(page, '[data-test="person-state-evidence"]')),
  ];
  const tooSmall = touch.filter((row) => row.height < 43.5);
  ctx.info("touch_min_height", Math.min(...touch.map((row) => row.height)));
  ctx.check("touch-targets-44px", tooSmall.length === 0, JSON.stringify(tooSmall));

  // 人物詳情：鍵盤開啟、時間軸、Escape 回焦。
  const detailButton = page.locator('[data-subject-id="ent-zhouyu"] [data-test="person-state-view-detail"]');
  await detailButton.focus();
  await page.keyboard.press("Enter");
  await waitIdle(page, '[data-test="person-detail-dialog"]');
  ctx.check("detail-opens-by-keyboard", true);
  ctx.check("detail-has-intro", (await page.locator(".pstate-intro").first().innerText()).length > 0);
  ctx.check("detail-experience-timeline", (await page.locator('[data-test="person-detail-experience"]').count()) >= 2);
  ctx.check("detail-attribution-tags", (await page.locator('[data-test="person-detail-dialog"] [data-test="person-state-attribution"]').count()) >= 1);
  await page.keyboard.press("Escape");
  await page.waitForSelector('[data-test="person-detail-dialog"]', { state: "detached", timeout: 10000 });
  const focusRestored = await page.evaluate(() =>
    document.activeElement?.getAttribute("data-test") === "person-state-view-detail",
  );
  ctx.check("detail-close-restores-focus", focusRestored);
  await ctx.screenshot(page, "reading-1440-detail");

  // 依據：原因、限定語、原文窗口、整章、相關事件；不改當前閱讀階段。
  const paragraphBefore = await page.getAttribute('[data-test="person-state-stage"]', "data-active-paragraph");
  const evidenceButton = page.locator('[data-item-id="zy-office-jianwei"] [data-test="person-state-evidence"]');
  await evidenceButton.scrollIntoViewIfNeeded();
  await evidenceButton.click();
  await waitIdle(page, '[data-test="person-state-evidence-dialog"]');
  ctx.check("evidence-reason-shown", (await page.locator('[data-test="evidence-reason"]').innerText()).length > 0);
  ctx.check("evidence-qualification-visible", (await page.locator('[data-test="evidence-qualification"]').count()) === 1);
  ctx.check("evidence-quote-shown", (await page.locator('[data-test="evidence-quote"]').innerText()).length > 0);
  ctx.check("evidence-attribution-shown", (await page.locator('[data-test="person-state-evidence-dialog"] [data-test="person-state-attribution"]').count()) >= 1);
  await page.locator('[data-test="evidence-whole-chapter"]').click();
  ctx.check("evidence-whole-chapter", await page.locator('[data-test="evidence-whole-chapter-text"]').isVisible());
  await page.locator('[data-test="evidence-related-event"]').click();
  ctx.check("evidence-event-note", await page.locator('[data-test="evidence-event-note"]').isVisible());
  await page.keyboard.press("Escape");
  await page.waitForSelector('[data-test="person-state-evidence-dialog"]', { state: "detached", timeout: 10000 });
  const paragraphAfter = await page.getAttribute('[data-test="person-state-stage"]', "data-active-paragraph");
  const phaseAfter = await page.getAttribute('[data-test="person-state-stage"]', "data-active-phase");
  ctx.check("evidence-does-not-change-stage", paragraphBefore === paragraphAfter, `${paragraphBefore} -> ${paragraphAfter}`);
  ctx.check("evidence-keeps-phase", Boolean(phaseAfter));
  await ctx.screenshot(page, "reading-1440-evidence");

  // 附近事件懸停不改階段。
  const beforeHover = await page.getAttribute('[data-test="person-state-stage"]', "data-active-paragraph");
  await page.locator('[data-test="person-state-nearby-event"]').first().hover();
  await page.waitForSelector('[data-test="person-state-event-preview"]', { timeout: 5000 });
  const afterHover = await page.getAttribute('[data-test="person-state-stage"]', "data-active-paragraph");
  ctx.check("hover-preview-keeps-stage", beforeHover === afterHover);

  // 受控載入／失敗／空態：明確呈現且正文保留。
  const bodyCount = await page.locator('[data-test="person-state-paragraph"]').count();
  await page.locator('[data-test="person-state-set-loading"]').click();
  ctx.check("loading-explicit", await page.locator('[data-test="person-state-loading"]').isVisible());
  ctx.check("loading-keeps-body", (await page.locator('[data-test="person-state-paragraph"]').count()) === bodyCount);
  await page.locator('[data-test="person-state-set-error"]').click();
  ctx.check("load-error-explicit", await page.locator('[data-test="person-state-error"]').isVisible());
  ctx.check("load-error-keeps-body", (await page.locator('[data-test="person-state-paragraph"]').count()) === bodyCount);
  await page.locator('[data-test="person-state-retry"]').click();
  ctx.check("load-error-retry-recovers", await page.locator('[data-test="person-state-context"]').isVisible());
  await page.locator('[data-test="person-state-set-empty"]').click();
  ctx.check("empty-section-explicit", await page.locator('[data-test="person-state-empty-section"]').isVisible());
  await page.locator('[data-test="person-state-set-ready"]').click();
  ctx.check("no-page-error-reading", errors.length === 0, errors.join("; "));
  await ctx.screenshot(page, "reading-1440");

  // 中屏 1024：右欄收起，改用可展開入口。
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.waitForTimeout(150);
  const midContextHidden = await page.evaluate(() => {
    const context = document.querySelector('[data-test="person-state-context-column"]');
    return getComputedStyle(context).display === "none" || context.getBoundingClientRect().width === 0;
  });
  const midEntryVisible = await page.locator('[data-test="person-state-mobile-entry"]').isVisible();
  ctx.check("mid-context-collapsed", midContextHidden);
  ctx.check("mid-entry-visible", midEntryVisible);
  await page.locator('[data-test="person-state-mobile-entry"]').click();
  await waitIdle(page, '[data-test="person-state-mobile-panel"]');
  ctx.check("mid-panel-opens", await page.locator('[data-test="person-state-mobile-panel"]').isVisible());
  ctx.check("mid-panel-has-subjects", (await page.locator('[data-test="person-state-mobile-panel"] [data-test="person-state-subject"]').count()) > 0);
  await page.locator('[data-test="person-state-mobile-close"]').click();
  await page.waitForSelector('[data-test="person-state-mobile-panel"]', { state: "detached", timeout: 10000 });
  ctx.check("mid-panel-closes", true);
  await ctx.screenshot(page, "reading-1024");

  // 窄屏 390 / 320：單欄正文，人物地點入口可操作，無橫向溢出。
  for (const viewport of VIEWPORTS.filter((entry) => entry.name.startsWith("phone"))) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.waitForTimeout(150);
    const overflow = await overflowX(page);
    ctx.check(`${viewport.name}-no-horizontal-overflow`, overflow <= 1, `overflow=${overflow}`);
    ctx.check(`${viewport.name}-body-visible`, await page.locator('[data-test="person-state-body"]').isVisible());
    await page.locator('[data-test="person-state-mobile-entry"]').click();
    await waitIdle(page, '[data-test="person-state-mobile-panel"]');
    ctx.check(`${viewport.name}-panel-opens`, await page.locator('[data-test="person-state-mobile-panel"]').isVisible());
    await page.keyboard.press("Escape");
    await page.waitForSelector('[data-test="person-state-mobile-panel"]', { state: "detached", timeout: 10000 });
    ctx.check(`${viewport.name}-panel-closes`, true);
    await ctx.screenshot(page, `reading-${viewport.name}`);
  }

  // 200% 字級：正文不橫向溢出，可操作元素仍 >=44px。
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "200%";
  });
  await page.waitForTimeout(200);
  const zoomOverflow = await overflowX(page);
  const zoomTouch = await minTouchHeight(page, '[data-test="person-state-view-detail"]');
  ctx.info("zoom_200_overflow", zoomOverflow);
  ctx.info("zoom_200_touch_min", Math.min(...zoomTouch.map((row) => row.height)));
  ctx.check("zoom-200-no-horizontal-overflow", zoomOverflow <= 1, `overflow=${zoomOverflow}`);
  ctx.check("zoom-200-touch-44px", zoomTouch.every((row) => row.height >= 43.5), JSON.stringify(zoomTouch));
  await ctx.screenshot(page, "reading-200pct");
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "";
  });
}

async function reviewSuite(ctx) {
  const page = await ctx.openScene("review", { viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await waitIdle(page, '[data-test="review-panel"]');
  ctx.check("review-synthetic-flag", (await page.locator('[data-test="review-synthetic-flag"]').innerText()).includes("合成"));
  ctx.check("review-shared-evidence", (await page.locator('[data-test="review-shared-item"]').count()) >= 3);
  ctx.check("review-per-person", (await page.locator('[data-test="review-person"]').count()) >= 3);
  ctx.check("review-changes", (await page.locator('[data-test="review-change"]').count()) >= 5);
  ctx.check("review-effect-badges", (await page.locator('[data-test="review-effect"]').count()) >= 5);
  ctx.check("review-attribution", (await page.locator('[data-test="review-change"] [data-test="person-state-attribution"]').count()) >= 5);
  ctx.check("review-batch-count", /批量覆蓋 \d+ 項/.test(await page.locator('[data-test="review-batch-count"]').innerText()));
  ctx.check("review-default-supported", (await page.locator('[data-candidate-id="cand-zy-office"]').getAttribute("data-assessment")) === "supported");

  // 逐項例外：改評估＋理由，批量覆蓋計數變化。
  const exception = page.locator('[data-candidate-id="cand-lb-office"]');
  await exception.locator('[data-test="review-assessment"]').selectOption("disputed");
  await exception.locator('[data-test="review-rationale"]').fill("奏章自稱，未證明收訖");
  ctx.check("review-exception-marked", (await exception.getAttribute("data-exception")) === "true");
  ctx.check("review-exception-count", /逐項例外 1 項/.test(await page.locator('[data-test="review-batch-count"]').innerText()));

  await ctx.screenshot(page, "review-1440");

  // 保存失敗保留草稿，重試成功才切項。
  await page.locator('[data-test="review-simulate-error"]').check();
  await page.locator('[data-test="review-save-next"]').click();
  await waitIdle(page, '[data-test="review-save-error"]');
  ctx.check("review-error-explicit", true);
  ctx.check(
    "review-error-keeps-draft",
    (await exception.locator('[data-test="review-rationale"]').inputValue()) === "奏章自稱，未證明收訖",
  );
  const reviewIdBefore = await page.locator('[data-test="review-panel"]').getAttribute("data-review-id");
  await page.locator('[data-test="review-simulate-error"]').uncheck();
  await page.locator('[data-test="review-save-retry"]').click();
  await waitIdle(page, '[data-test="review-saved"]');
  const reviewIdAfter = await page.locator('[data-test="review-panel"]').getAttribute("data-review-id");
  ctx.check("review-save-advances", reviewIdBefore !== reviewIdAfter, `${reviewIdBefore} -> ${reviewIdAfter}`);
  ctx.check("review-next-item-clears-draft", (await page.locator('[data-test="review-rationale"]').first().inputValue()) === "");

  // 頁底固定操作區：捲到底仍可見且可操作。
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(150);
  ctx.check("review-action-bar-sticky", await page.locator('[data-test="review-save-next"]').isVisible());
  const barBox = await page.locator('[data-test="review-action-bar"]').boundingBox();
  const viewportHeight = page.viewportSize().height;
  ctx.check("review-action-bar-in-viewport", barBox && barBox.y < viewportHeight, JSON.stringify(barBox));

  // 窄屏：操作區與例外控件可達、不遮最後一項。
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(150);
  const reviewOverflow = await overflowX(page);
  ctx.info("review_390_overflow", reviewOverflow);
  ctx.check("review-390-no-overflow", reviewOverflow <= 1, `overflow=${reviewOverflow}`);
  ctx.check("review-390-action-visible", await page.locator('[data-test="review-save-next"]').isVisible());
  ctx.check("review-390-assessment-visible", await page.locator('[data-test="review-assessment"]').first().isVisible());
  await ctx.screenshot(page, "review-390");
  ctx.check("no-page-error-review", errors.length === 0, errors.join("; "));
}

async function entitySuite(ctx) {
  const page = await ctx.openScene("entity", { viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await waitIdle(page, '[data-test="entity-harness-scene"]');
  ctx.check("entity-synthetic-flag", (await page.locator('[data-test="entity-synthetic-flag"]').innerText()).includes("合成"));

  const columns = await page.evaluate(() => ({
    left: document.querySelector('[data-test="entity-left"]').getBoundingClientRect().width,
    main: document.querySelector('[data-test="entity-main"]').getBoundingClientRect().width,
    right: document.querySelector('[data-test="entity-right"]').getBoundingClientRect().width,
  }));
  ctx.check("entity-three-columns", columns.left > 0 && columns.main > 0 && columns.right > 0, JSON.stringify(columns));
  ctx.check("entity-timeline", (await page.locator('[data-test="entity-experience"]').count()) >= 2);
  ctx.check("entity-related-people", (await page.locator('[data-test="entity-related-people"] li').count()) >= 1);
  ctx.check("entity-related-places", (await page.locator('[data-test="entity-related-places"] li').count()) >= 1);

  // 從正文進入：保留階段，返回恢復原段與偏移。
  ctx.check("entity-time-anchor-preserved", (await page.locator('[data-test="entity-time-anchor"]').innerText()).includes("保留階段"));
  await page.locator('[data-test="entity-return-reading"]').click();
  await waitIdle(page, '[data-test="entity-return-restored"]');
  const restored = await page.locator('[data-test="entity-return-restored"]').innerText();
  ctx.check("entity-return-restores-paragraph", restored.includes("para-208-chibi-03"), restored);
  ctx.check("entity-return-restores-offset", restored.includes("420px"), restored);

  // 直接進入：不捏造當前年份。
  await page.locator('[data-test="entity-toggle-entry"]').click();
  await page.waitForTimeout(100);
  const anchor = await page.locator('[data-test="entity-time-anchor"]').innerText();
  ctx.check("entity-direct-no-fabricated-year", (await page.getAttribute('[data-test="entity-time-anchor"]', "data-direct")) === "true" && anchor.includes("不擅自選定當前年份"), anchor);
  await ctx.screenshot(page, "entity-1440");

  // 窄屏：單欄堆疊，無橫向溢出。
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(150);
  ctx.check("entity-390-no-overflow", (await overflowX(page)) <= 1);
  ctx.check("entity-390-left-visible", await page.locator('[data-test="entity-left"]').isVisible());
  ctx.check("entity-390-right-visible", await page.locator('[data-test="entity-right"]').isVisible());
  await ctx.screenshot(page, "entity-390");
  ctx.check("no-page-error-entity", errors.length === 0, errors.join("; "));
}

export async function run(ctx) {
  const requested = ctx.scene ?? "all";
  const suites = requested === "all" ? SCENE_NAMES : [requested];
  for (const name of suites) {
    if (!SCENE_NAMES.includes(name)) throw new Error(`person-state-harness: unknown scene ${name}`);
    if (name === "reading") await readingSuite(ctx);
    else if (name === "review") await reviewSuite(ctx);
    else await entitySuite(ctx);
  }
}

// ---------------------------------------------------------------- 獨立 CLI

class StandaloneRunner {
  constructor(outputDir) {
    this.outputDir = outputDir;
    this.checks = [];
    this.evidence = {};
    this.pages = [];
  }
  check(name, condition, detail = "") {
    const ok = Boolean(condition);
    this.checks.push({ name, ok, detail: ok ? "" : String(detail) });
    if (!ok) throw new Error(`person-state-harness D02: FAIL: ${name}${detail ? ` (${detail})` : ""}`);
  }
  info(name, value) {
    this.evidence[name] = value;
  }
  async screenshot(page, label) {
    if (!this.outputDir) return;
    mkdirSync(this.outputDir, { recursive: true });
    await page.screenshot({ path: join(this.outputDir, `d02-${label}.png`), fullPage: false });
  }
  async closePages() {
    for (const page of this.pages) {
      try {
        await page.close();
      } catch {
        /* already closed */
      }
    }
  }
}

async function standalone() {
  const args = process.argv.slice(2);
  const flag = (name) => {
    const at = args.indexOf(name);
    return at >= 0 ? args[at + 1] : null;
  };
  const baseUrl = (flag("--base-url") || "").replace(/\/+$/, "");
  const outputDir = flag("--output") || join(os.tmpdir(), "chronicle-r3-d02-harness");
  const scene = flag("--scene") || "all";
  if (!baseUrl) {
    console.error("person-state-harness: FAIL: --base-url is required (running Vite fixture server)");
    process.exit(2);
  }
  const browser = await chromium.launch();
  const runner = new StandaloneRunner(outputDir);
  const ctx = {
    baseUrl,
    outputDir,
    browser,
    runner,
    scene,
    check: (name, condition, detail) => runner.check(name, condition, detail),
    info: (name, value) => runner.info(name, value),
    screenshot: (page, label) => runner.screenshot(page, label),
    openScene: async (name, options) => {
      const page = await browser.newPage(options ?? { viewport: { width: 1440, height: 900 } });
      runner.pages.push(page);
      await page.goto(fixtureUrl(baseUrl, { case: name }), { waitUntil: "networkidle" });
      return page;
    },
  };
  let ok = true;
  let error = null;
  try {
    await run(ctx);
  } catch (caught) {
    ok = false;
    error = caught instanceof Error ? caught.message : String(caught);
  } finally {
    await runner.closePages();
    await browser.close();
  }
  const payload = {
    schema: "chronicle.person-state-harness",
    version: "0.1",
    task: D02_TASK,
    base_url: baseUrl,
    requested_scene: scene,
    ok,
    checks: runner.checks,
    evidence: runner.evidence,
    error,
  };
  mkdirSync(outputDir, { recursive: true });
  writeFileSync(join(outputDir, "result.json"), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  for (const check of runner.checks) {
    console.log(`  [${check.ok ? "PASS" : "FAIL"}] ${check.name}${check.ok ? "" : `: ${check.detail}`}`);
  }
  for (const [name, value] of Object.entries(runner.evidence)) {
    console.log(`      . ${name}=${JSON.stringify(value)}`);
  }
  if (!ok) {
    console.error(`person-state-harness: FAIL; see ${outputDir}/result.json`);
    process.exit(1);
  }
  console.log(`person-state-harness: PASS (scene=${scene}); evidence at ${outputDir}/result.json`);
}

const invokedDirectly = process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url;
if (invokedDirectly) {
  standalone().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  });
}
