// C2-R3-T11 person-states 真实浏览器 suite（仅测试使用）。
//
// 独立 suite：打开本任务自包含的 Vite fixture 场景，操作真实 `PersonStateItems` /
// `PersonStateDetails` 组件与 `ReadingContextPanel` 阶段 slot，验证：
//  - 紧凑当时状态、兼任并列、两档明确性（颜色外有标识、非 disabled、AA）；
//  - 更多项、原因、原文／事件入口可操作，不改当前阅读阶段；
//  - 人物详情按服务端阶段展开有据经历，键盘开启、Escape 回焦；
//  - 暂无记载 / 阶段未明确 / 加载 / 失败 / 空段是不同状态；
//  - 中屏／窄屏不挤压正文、入口可操作、无横向溢出、200% 字号与 44px 触控。
//
// 由共享 runner 以 `reading-browser/<name>.mjs` 发现并调用 `run(ctx)`；ctx 提供
// check / info / screenshot / openScene。全部数据合成，不冒充真实后端。

export const FIXTURE_PATH = "/tests/fixtures/reading/scenes/person-states/index.html";
export const SCENE_CASES = ["reading", "slot"];
export const TASK = "C2-R3-T11";

const ZHOUYU_ID = "0192f0a0-0000-7000-8000-00000000cc07";
const VIEWPORTS = [
  { name: "desktop-1440", width: 1440, height: 900 },
  { name: "mid-1024", width: 1024, height: 768 },
  { name: "phone-390", width: 390, height: 844 },
  { name: "phone-320", width: 320, height: 568 },
];

function sceneUrl(baseUrl, sceneCase, params = {}) {
  const url = new URL(FIXTURE_PATH, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  url.searchParams.set("case", sceneCase);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  return url.toString();
}

async function overflowX(page) {
  return await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

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

async function slotSuite(ctx) {
  const page = await ctx.openScene(sceneUrl(ctx.baseUrl, "slot"), { viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.waitForSelector('[data-test="person-state-slot-scene"]', { timeout: 15000 });
  ctx.check("slot-scene-synthetic", (await page.getAttribute('[data-test="person-state-slot-scene"]', "data-synthetic")) === "true");
  ctx.check(
    "slot-injected-into-context-panel",
    (await page.locator('[data-test="person-states-slot-probe"] [data-test="reading-context-panel"] [data-test="person-state-context"]').count()) === 1,
    "stage slot did not render inside ReadingContextPanel",
  );
  ctx.check(
    "slot-keeps-existing-context-groups",
    (await page.locator('[data-test="reading-context-group"]').count()) >= 1,
    "existing context groups lost when stage slot is present",
  );
  ctx.check("no-page-error-slot", errors.length === 0, errors.join("; "));
  await ctx.screenshot(page, "slot-1280");
}

async function readingSuite(ctx) {
  const page = await ctx.openScene(sceneUrl(ctx.baseUrl, "reading"), { viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.waitForSelector('[data-test="person-state-reading-scene"]', { timeout: 15000 });

  ctx.check("reading-synthetic-flag", (await page.locator('[data-test="person-state-synthetic-flag"]').innerText()).includes("合成"));

  // 默认只列本段重要主体；其他人物按需展开。
  const primaryNames = await page.locator('[data-test="person-state-subject"][data-kind="person"] [data-test="person-state-name"]').allTextContents();
  ctx.check("default-primary-people-only", primaryNames.join(",") === "周瑜,刘备", primaryNames.join(","));
  await page.locator('[data-test="person-state-more-people"]').click();
  ctx.check("other-people-toggle-expands", (await page.locator('[data-test="person-state-more-people"]').innerText()).includes("收起"));
  await coverMatrix(page, ctx);

  // 桌面三栏：正文优先，右栏为当时人物地点。
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

  // 颜色以外可辨识：实心/空心标记同时存在，且不明确项不是 disabled。
  ctx.check("marker-solid-and-hollow", (await page.locator('.chr-state-mark:has-text("●")').count()) > 0 && (await page.locator('.chr-state-mark:has-text("○")').count()) > 0);
  ctx.check("uncertain-not-disabled", (await page.locator('[data-test="person-state-item"][data-certainty="uncertain"] button[disabled], [data-test="person-state-item"][data-certainty="uncertain"] summary[aria-disabled="true"]').count()) === 0);
  const contrast = await contrastReport(page);
  ctx.info("contrast_ratios", contrast);
  ctx.check("contrast-clear-aa", contrast.clear >= 4.5, `clear=${contrast.clear}`);
  ctx.check("contrast-uncertain-aa", contrast.uncertain >= 4.5, `uncertain=${contrast.uncertain}`);
  ctx.check("contrast-qualification-aa", contrast.qualification >= 4.5, `qualification=${contrast.qualification}`);

  // 触控面积：紧凑行、依据、来源操作至少 44px。
  const touch = [
    ...(await minTouchHeight(page, '[data-test="person-state-view-detail"]')),
    ...(await minTouchHeight(page, '[data-test="person-state-evidence"]')),
  ];
  ctx.info("touch_min_height", Math.min(...touch.map((row) => row.height)));
  ctx.check("touch-targets-44px", touch.length > 0 && touch.every((row) => row.height >= 43.5), JSON.stringify(touch));

  // 更多项：默认摘要分页，入口加载更多后按钮消失、条目增加。
  const zyItems = page.locator(`[data-subject-id="${ZHOUYU_ID}"] [data-test="person-state-item"]`);
  const zyItemSelector = `[data-subject-id="${ZHOUYU_ID}"] [data-test="person-state-item"]`;
  const beforeMore = await zyItems.count();
  await page.locator(`[data-subject-id="${ZHOUYU_ID}"] [data-test="person-state-more"]`).click();
  await page.waitForFunction(
    ({ selector, count }) => document.querySelectorAll(selector).length > count,
    { selector: zyItemSelector, count: beforeMore },
    { timeout: 5000 },
  );
  const afterMore = await zyItems.count();
  ctx.check("more-identities-loads", afterMore > beforeMore, `${beforeMore} -> ${afterMore}`);
  ctx.check("more-identities-entry-consumed", (await page.locator(`[data-subject-id="${ZHOUYU_ID}"] [data-test="person-state-more"]`).count()) === 0);

  // 人物详情：键盘开启、按阶段时间轴、Escape 回焦。
  const detailButton = page.locator(`[data-subject-id="${ZHOUYU_ID}"] [data-test="person-state-view-detail"]`);
  await detailButton.scrollIntoViewIfNeeded();
  await detailButton.focus();
  await page.keyboard.press("Enter");
  await page.waitForSelector('[data-test="person-detail-dialog"]', { timeout: 10000 });
  ctx.check("detail-opens-by-keyboard", true);
  ctx.check("detail-has-intro", (await page.locator(".pstate-intro").first().innerText()).length > 0);
  ctx.check("detail-experience-timeline", (await page.locator('[data-test="person-detail-experience"]').count()) >= 2);
  ctx.check("detail-attribution-tags", (await page.locator('[data-test="person-detail-dialog"] [data-test="person-state-attribution"]').count()) >= 1);
  ctx.check("detail-keeps-concurrent-items", (await page.locator('[data-test="person-detail-dialog"] [data-item-id="zy-office-nanjun"]').count()) === 1);
  await page.keyboard.press("Escape");
  await page.waitForSelector('[data-test="person-detail-dialog"]', { state: "detached", timeout: 10000 });
  const focusRestored = await page.evaluate(() =>
    document.activeElement?.getAttribute("data-test") === "person-state-view-detail",
  );
  ctx.check("detail-close-restores-focus", focusRestored);
  await ctx.screenshot(page, "reading-1440-detail");

  // 依据：原因/限定语可见，原文与相关事件入口可操作，且不改当前阅读阶段。
  const paragraphBefore = await page.getAttribute('[data-test="person-state-stage"]', "data-active-paragraph");
  const targetItem = page.locator('[data-item-id="zy-office-jianwei"]');
  await targetItem.scrollIntoViewIfNeeded();
  await targetItem.locator('[data-test="person-state-evidence"]').click();
  ctx.check("evidence-qualification-visible", (await targetItem.locator('[data-test="person-state-qualification"]').count()) >= 1);
  ctx.check("evidence-reason-visible", (await page.locator('[data-test="person-state-reason"]').count()) >= 1);
  await targetItem.locator('[data-test="person-state-source"]').first().click();
  const lastAction = page.locator('[data-test="person-states-last-action"]');
  ctx.check("evidence-source-operable", (await lastAction.textContent()).startsWith("source:"), await lastAction.textContent());
  await targetItem.locator('[data-test="person-state-event"]').first().click();
  ctx.check("evidence-event-operable", (await lastAction.textContent()).startsWith("event:"), await lastAction.textContent());
  const paragraphAfter = await page.getAttribute('[data-test="person-state-stage"]', "data-active-paragraph");
  const phaseAfter = await page.getAttribute('[data-test="person-state-stage"]', "data-active-phase");
  ctx.check("evidence-does-not-change-stage", paragraphBefore === paragraphAfter, `${paragraphBefore} -> ${paragraphAfter}`);
  ctx.check("evidence-keeps-phase", Boolean(phaseAfter));
  await ctx.screenshot(page, "reading-1440-evidence");

  // 受控加载／失败／空态：显式呈现且正文保留。
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

  // 中屏 1024：右栏收起，改用可展开入口。
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.waitForTimeout(150);
  const midContextHidden = await page.evaluate(() => {
    const context = document.querySelector('[data-test="person-state-context-column"]');
    return getComputedStyle(context).display === "none" || context.getBoundingClientRect().width === 0;
  });
  ctx.check("mid-context-collapsed", midContextHidden);
  ctx.check("mid-entry-visible", await page.locator('[data-test="person-state-mobile-entry"]').isVisible());
  await page.locator('[data-test="person-state-mobile-entry"]').click();
  await page.waitForSelector('[data-test="person-state-mobile-panel"]', { timeout: 10000 });
  ctx.check("mid-panel-opens", await page.locator('[data-test="person-state-mobile-panel"]').isVisible());
  ctx.check("mid-panel-has-subjects", (await page.locator('[data-test="person-state-mobile-panel"] [data-test="person-state-subject"]').count()) > 0);
  await page.keyboard.press("Escape");
  await page.waitForSelector('[data-test="person-state-mobile-panel"]', { state: "detached", timeout: 10000 });
  ctx.check("mid-panel-closes", true);
  await ctx.screenshot(page, "reading-1024");

  // 窄屏 390 / 320：单栏正文，人物地点入口可操作，无横向溢出。
  for (const viewport of VIEWPORTS.filter((entry) => entry.name.startsWith("phone"))) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.waitForTimeout(150);
    const overflow = await overflowX(page);
    ctx.check(`${viewport.name}-no-horizontal-overflow`, overflow <= 1, `overflow=${overflow}`);
    ctx.check(`${viewport.name}-body-visible`, await page.locator('[data-test="person-state-body"]').isVisible());
    await page.locator('[data-test="person-state-mobile-entry"]').click();
    await page.waitForSelector('[data-test="person-state-mobile-panel"]', { timeout: 10000 });
    ctx.check(`${viewport.name}-panel-opens`, await page.locator('[data-test="person-state-mobile-panel"]').isVisible());
    const narrowTouch = await minTouchHeight(page, '[data-test="person-state-mobile-panel"] [data-test="person-state-view-detail"]');
    ctx.check(`${viewport.name}-panel-touch-44px`, narrowTouch.length > 0 && narrowTouch.every((row) => row.height >= 43.5), JSON.stringify(narrowTouch));
    await page.keyboard.press("Escape");
    await page.waitForSelector('[data-test="person-state-mobile-panel"]', { state: "detached", timeout: 10000 });
    ctx.check(`${viewport.name}-panel-closes`, true);
    await ctx.screenshot(page, `reading-${viewport.name}`);
  }

  // 200% 字号：正文不横向溢出，可操作元素仍 >=44px。
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
  ctx.check("zoom-200-touch-44px", zoomTouch.length > 0 && zoomTouch.every((row) => row.height >= 43.5), JSON.stringify(zoomTouch));
  await ctx.screenshot(page, "reading-200pct");
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "";
  });
}

export async function run(ctx) {
  await readingSuite(ctx);
  await slotSuite(ctx);
}
