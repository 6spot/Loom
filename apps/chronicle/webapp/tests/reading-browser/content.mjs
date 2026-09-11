// C2-R2-T10 content suite 的浏览器验证（仅测试使用，不接生产 App/dist）。
//
// 在独立 content fixture 场景中用真实 Chromium 验证：正常边界前后相邻页自动预取、
// 双向加载去重、跨章顺序与逐字拼接、只在可验证章边界显示标题（含部分页起始）、
// 有界窗口与显式加载、固定单位不消失、按需长原文展开与关闭回到触发点、字号改变
// 保持 active、320px 与 200% 无横向溢出。

const SCENE = "content-window";
const UNIT = '[data-test="reading-unit"]';

async function readUnits(page) {
  return await page.$$eval(UNIT, (nodes) =>
    nodes.map((node) => {
      const segments = node.querySelectorAll(
        '[data-test="reading-segment"], [data-test="reading-event-span"], [data-test="reading-event-span-uncertain"]',
      );
      const joined = Array.from(segments)
        .map((segment) => segment.textContent || "")
        .join("");
      return {
        ordinal: Number(node.getAttribute("data-ordinal")),
        unitId: node.getAttribute("data-unit-id"),
        chapterId: node.getAttribute("data-chapter-id"),
        text: node.getAttribute("data-text") || "",
        joined,
        active: node.getAttribute("data-active") === "true",
        pinned: node.getAttribute("data-pinned") === "true",
      };
    }),
  );
}

async function readHeadings(page) {
  return await page.$$eval('[data-test="reading-chapter-heading"]', (nodes) =>
    nodes.map((node) => {
      const unit = node.closest('[data-test="reading-unit"]');
      return {
        chapterId: node.getAttribute("data-chapter-id"),
        unitId: unit?.getAttribute("data-unit-id") ?? null,
        ordinal: Number(unit?.getAttribute("data-ordinal") ?? -1),
      };
    }),
  );
}

async function windowRequests(page) {
  const text = await page.locator('[data-test="content-window-requests"]').textContent();
  return (text || "").split(",").map((value) => value.trim()).filter(Boolean);
}

async function waitForUnitCount(page, expected) {
  await page.waitForFunction(
    ({ selector, count }) => document.querySelectorAll(selector).length === count,
    { selector: UNIT, count: expected },
    { timeout: 10000 },
  );
}

async function horizontalOverflow(page) {
  return await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

export async function run(ctx) {
  const page = await ctx.openScene(SCENE, { viewport: { width: 1280, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  // 1. 场景挂载；正常边界自动预取前后相邻页（页 3..6 -> 0..8）。
  await page.waitForSelector('[data-test="content-scene"]', { timeout: 15000 });
  await page.waitForSelector('[data-test="reading-window"]', { timeout: 15000 });
  ctx.check("content-scene-mounts", true);
  await waitForUnitCount(page, 9);
  const autoRequests = await windowRequests(page);
  ctx.check(
    "auto-prefetch-both-directions",
    autoRequests.includes("previous") && autoRequests.includes("next"),
    autoRequests.join(","),
  );

  let units = await readUnits(page);
  ctx.check(
    "auto-prefetch-extends-both-ends",
    units.map((unit) => unit.ordinal).join(",") === "0,1,2,3,4,5,6,7,8",
    JSON.stringify(units.map((unit) => unit.ordinal)),
  );
  const mismatches = units.filter((unit) => unit.joined !== unit.text);
  ctx.check(
    "segments-reassemble-unit-text",
    mismatches.length === 0,
    JSON.stringify(mismatches.map((unit) => unit.ordinal)),
  );

  // 2. 章标题只在可验证边界：ordinal 0（stream 起点）与 ordinal 5（连续换章）。
  const headings = await readHeadings(page);
  ctx.check(
    "chapter-headings-only-at-verifiable-boundaries",
    headings.length === 2 &&
      headings[0].chapterId === "chap-a" &&
      headings[0].ordinal === 0 &&
      headings[1].chapterId === "chap-b" &&
      headings[1].ordinal === 5,
    JSON.stringify(headings),
  );
  ctx.check(
    "event-span-statuses-present",
    (await page.locator('[data-test="reading-event-span"]').count()) >= 1 &&
      (await page.locator('[data-test="reading-event-span-uncertain"]').count()) >= 1,
    "expected resolved and uncertain event spans",
  );
  await ctx.screenshot(page, "initial");

  // 3. 重复页去重（手动再加载同一页不新增内容）。
  await page.locator('[data-test="content-load-next-ok"]').click();
  await page.waitForTimeout(200);
  ctx.check("duplicate-next-deduped", (await page.locator(UNIT).count()) === 9);
  await page.locator('[data-test="content-load-prev-ok"]').click();
  await page.waitForTimeout(200);
  ctx.check("duplicate-previous-deduped", (await page.locator(UNIT).count()) === 9);

  // 4. 受控失败保留已读正文，并可重试恢复。
  const beforeFail = await page.locator(UNIT).count();
  await page.locator('[data-test="content-load-next-fail"]').click();
  await page.waitForSelector('[data-test="reading-load-error"]', { timeout: 10000 });
  ctx.check("failure-explicit", true);
  ctx.check("failure-keeps-loaded-units", (await page.locator(UNIT).count()) === beforeFail);
  await page.locator('[data-test="reading-retry"]').click();
  await page.waitForSelector('[data-test="reading-load-error"]', { state: "detached", timeout: 10000 });
  ctx.check("retry-recovers-with-content", (await page.locator(UNIT).count()) === beforeFail);
  await ctx.screenshot(page, "failure-recovered");

  // 5. 按需长原文：展开整章、续页、关闭回到触发点。
  const activeUnit = (await readUnits(page)).find((unit) => unit.active);
  ctx.check("active-unit-present", Boolean(activeUnit), "no active unit");
  const toggle = page.locator(
    `[data-test="reading-unit"][data-unit-id="${activeUnit.unitId}"] [data-test="reading-source-toggle"]`,
  );
  const activeAnchor = await toggle.getAttribute("data-anchor");
  await toggle.click();
  await page.waitForSelector('[data-test="chapter-source-panel"]', { timeout: 10000 });
  ctx.check("source-panel-opens-on-demand", true);
  await page.locator('[data-test="chapter-source-view-chapter"]').click();
  await page.waitForSelector('[data-test="chapter-source-more"]', { timeout: 10000 });
  await page.locator('[data-test="chapter-source-more"]').click();
  await page.waitForSelector('[data-test="chapter-source-end"]', { timeout: 10000 });
  ctx.check("source-expands-and-paginates", true);
  ctx.check(
    "source-expansion-pins-unit",
    (await readUnits(page)).some((unit) => unit.unitId === activeUnit.unitId && unit.pinned),
  );
  await page.keyboard.press("Escape");
  await page.waitForSelector('[data-test="chapter-source-panel"]', { state: "detached", timeout: 10000 });
  const focusAfterClose = await page.evaluate(() => {
    const active = document.activeElement;
    return {
      test: active?.getAttribute("data-test") ?? null,
      anchor: active?.getAttribute("data-anchor") ?? null,
    };
  });
  ctx.check(
    "source-close-returns-focus-to-trigger",
    focusAfterClose.test === "reading-source-toggle" && focusAfterClose.anchor === activeAnchor,
    JSON.stringify({ focusAfterClose, activeAnchor }),
  );
  ctx.check("content-still-present-after-source", (await page.locator(UNIT).count()) >= 9);

  // 6. 引用失败不清正文，错误显式且关闭回到触发点。
  await page.locator('[data-test="content-source-fail"]').check();
  const beforeSourceFail = await page.locator(UNIT).count();
  await toggle.click();
  await page.waitForSelector('[data-test="chapter-source-error"]', { timeout: 10000 });
  ctx.check("source-failure-explicit", true);
  ctx.check(
    "source-failure-keeps-content",
    (await page.locator(UNIT).count()) === beforeSourceFail,
  );
  await page.keyboard.press("Escape");
  await page.waitForSelector('[data-test="chapter-source-error"]', { state: "detached", timeout: 10000 });
  await page.locator('[data-test="content-source-fail"]').uncheck();
  ctx.check(
    "source-failure-close-keeps-content",
    (await page.locator(UNIT).count()) === beforeSourceFail,
  );

  // 7. 大页触发有界窗口与显式加载；饱和后不再自动请求，手动入口可用。
  await page.locator('[data-test="content-load-bulk"]').click();
  await page.waitForSelector('[data-test="reading-paused"]', { timeout: 10000 });
  const mountedAfterBulk = await page.locator(UNIT).count();
  ctx.check("bulk-bounded-mounted", mountedAfterBulk <= 120, `mounted=${mountedAfterBulk}`);
  ctx.check(
    "bulk-placeholders-reserve-space",
    (await page.locator('[data-test="reading-unit-placeholder"]').count()) > 0,
  );
  ctx.check(
    "active-unit-survives-bulk",
    (await readUnits(page)).some((unit) => unit.unitId === activeUnit.unitId && unit.pinned),
  );
  const requestsAtBulk = (await windowRequests(page)).length;
  await page.waitForTimeout(400);
  ctx.check(
    "saturated-window-stops-auto-prefetch",
    (await windowRequests(page)).length === requestsAtBulk,
    "explicit load must be required once saturated",
  );
  await page.locator('[data-test="reading-manual-next"]').click();
  await page.waitForTimeout(200);
  ctx.check("manual-load-keeps-window-bounded", (await page.locator(UNIT).count()) <= 120);
  await ctx.screenshot(page, "bounded-window");

  // 8. 文本选择固定的单位在窗口回收后仍在 DOM。
  await page.locator('[data-test="content-reset"]').click();
  await waitForUnitCount(page, 9);
  const selectedUnit = await page.evaluate(() => {
    const target = document.querySelectorAll('[data-test="reading-unit"]')[1];
    const paragraph = target?.querySelector('[data-test="reading-unit-text"]');
    if (!target || !paragraph || !paragraph.firstChild) return null;
    const range = document.createRange();
    range.selectNodeContents(paragraph.firstChild);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
    return target.getAttribute("data-unit-id");
  });
  ctx.check("selection-made", Boolean(selectedUnit), "could not select unit text");
  await page.waitForFunction(
    (unitId) => {
      const node = document.querySelector(`[data-test="reading-unit"][data-unit-id="${unitId}"]`);
      return node?.getAttribute("data-pinned") === "true";
    },
    selectedUnit,
    { timeout: 5000 },
  );
  ctx.check("selection-pins-unit", true);
  await page.evaluate(() => {
    document.querySelector('[data-test="content-load-bulk"]').click();
  });
  await page.waitForSelector('[data-test="reading-paused"]', { timeout: 10000 });
  await page.waitForTimeout(200);
  ctx.check(
    "selection-survives-window-recycle",
    (await readUnits(page)).some((unit) => unit.unitId === selectedUnit && unit.pinned),
  );

  // 9. 部分页起始（locate 到章中间）：不得伪造章标题；也不预取整本书。
  await page.locator('[data-test="content-jump-far"]').click();
  await page.waitForSelector('[data-ordinal="5000"]', { timeout: 10000 });
  await page.waitForTimeout(300);
  const farUnits = await readUnits(page);
  ctx.check(
    "far-page-starts-mid-chapter",
    farUnits[0]?.ordinal === 5000 && farUnits.some((unit) => unit.active && unit.ordinal === 5020),
    JSON.stringify(farUnits.slice(0, 2)),
  );
  ctx.check(
    "mid-page-start-shows-no-false-heading",
    (await page.locator('[data-test="reading-chapter-heading"]').count()) === 0,
  );
  await ctx.screenshot(page, "mid-page-start");

  // 10. 字号改变保持 active 且无横向溢出，随后 320px 窄屏可读。
  const activeBeforeFont = (await readUnits(page)).find((unit) => unit.active)?.ordinal;
  await page.locator('[data-test="content-font-large"]').click();
  await page.waitForTimeout(200);
  const activeAfterFont = (await readUnits(page)).find((unit) => unit.active)?.ordinal;
  ctx.check(
    "font-change-keeps-active",
    activeBeforeFont === activeAfterFont,
    `${activeBeforeFont} -> ${activeAfterFont}`,
  );
  ctx.check("font-large-no-overflow", (await horizontalOverflow(page)) <= 1);
  await page.locator('[data-test="content-font-normal"]').click();

  await page.setViewportSize({ width: 320, height: 568 });
  await page.waitForTimeout(200);
  ctx.check("narrow-320-no-horizontal-overflow", (await horizontalOverflow(page)) <= 1);
  const narrowFontSize = await page.evaluate(() => {
    const node = document.querySelector('[data-test="reading-unit-text"]');
    return node ? Number.parseFloat(getComputedStyle(node).fontSize) : 0;
  });
  ctx.check("narrow-font-readable", narrowFontSize >= 17, `font-size=${narrowFontSize}`);
  await ctx.screenshot(page, "narrow-320");

  // 11. 真实 Chromium 无未捕获异常。
  ctx.check("no-page-error", pageErrors.length === 0, pageErrors.join("; "));

  ctx.info("mounted_after_bulk", mountedAfterBulk);
  ctx.info("auto_requests", (await windowRequests(page)).join(","));
}
