// C2-R2-T12 position suite 浏览器 spec（真实 Chromium + 受控 synthetic 数据）。
//
// 覆盖：深链接/刷新定位远处目标、自然滚动 replace 不压历史、显式导航 push、
// back/forward、回溯预览不改 active/time、未知段清空人物年份、A→B→Event→返回
// 多层 token、旧 locate 响应被忽略、用户滚动打断恢复、storage 失效降级、
// 无效 token 不外部跳转。本 spec 只证明组件行为，不冒充真实后端或史料。

import { fixtureUrl } from "./harness.mjs";

const STREAM = "01890a5d-ac96-774b-bcce-b302099a8057";
const CATALOG = "c".repeat(64);
const VIEWPORT = { width: 1280, height: 900 };

function ru(ordinal) {
  return `ru_${ordinal.toString(16).padStart(24, "0")}`;
}

async function activeUnitId(page) {
  return (await page.getAttribute('[data-test="position-active-unit"]', "data-unit-id")) ?? "";
}

async function activeOrdinal(page) {
  return Number((await page.getAttribute('[data-test="position-active-unit"]', "data-ordinal")) ?? "-1");
}

async function text(page, selector) {
  return (await page.textContent(selector)) ?? "";
}

async function waitForActive(page, ordinal) {
  await page.waitForFunction(
    (expected) => {
      const el = document.querySelector('[data-test="position-active-unit"]');
      return el?.getAttribute("data-unit-id") === expected;
    },
    ru(ordinal),
    { timeout: 10000 },
  );
}

async function scrollToUnit(page, ordinal) {
  await page.evaluate((expected) => {
    const el = document.querySelector(`[data-reading-unit][data-unit-id="${expected}"]`);
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 100 });
  }, ru(ordinal));
}

function deepLink(ctx, scene, params = {}) {
  return fixtureUrl(ctx.baseUrl, {
    case: `position/${scene}`,
    stream: STREAM,
    catalog: CATALOG,
    ...params,
  });
}

export async function run(ctx) {
  const pageErrors = [];
  const page = await ctx.runner.newPage({ viewport: VIEWPORT });
  page.on("pageerror", (error) => pageErrors.push(String(error)));

  // 1. 深链接定位远处目标，并真实滚动过去。
  await page.goto(deepLink(ctx, "main", { at: ru(20) }), { waitUntil: "networkidle" });
  await page.waitForSelector('[data-test="position-scene"]', { timeout: 15000 });
  await waitForActive(page, 20);
  ctx.check("deep-link-locates-far-unit", (await activeUnitId(page)) === ru(20), `active=${await activeUnitId(page)}`);
  const deepScrollY = await page.evaluate(() => window.scrollY);
  ctx.check("deep-link-actually-scrolls", deepScrollY > 100, `scrollY=${deepScrollY}`);
  ctx.check(
    "deep-link-time-context-consistent",
    (await text(page, '[data-test="position-time-label"]')).includes("史料八月") &&
      Number(await text(page, '[data-test="position-context-count"]')) > 0,
  );
  ctx.info("deep_link_url", await text(page, '[data-test="position-url"]'));
  await ctx.screenshot(page, "deep-link");

  // 2. 刷新后仍能恢复同一 locator。
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector('[data-test="position-scene"]', { timeout: 15000 });
  await waitForActive(page, 20);
  ctx.check("refresh-restores-same-unit", (await activeUnitId(page)) === ru(20));

  // 3. 自然滚动只 replace URL，不新增 history entry。
  const historyBefore = await page.evaluate(() => window.history.length);
  await scrollToUnit(page, 2);
  await waitForActive(page, 2);
  await page.waitForTimeout(300);
  const historyAfter = await page.evaluate(() => window.history.length);
  ctx.check("natural-scroll-no-history-growth", historyAfter === historyBefore, `${historyBefore}->${historyAfter}`);
  const replacedAt = await page.evaluate(() => new URLSearchParams(window.location.search).get("at"));
  ctx.check("natural-scroll-replaces-url", replacedAt === ru(2), `at=${replacedAt}`);

  // 3b. 自然滚动 settle 时必须持久化实测的 unit 内相对位置，而不是固定 0。
  const storedOffsets = await page.evaluate(() => {
    const out = [];
    for (let index = 0; index < window.sessionStorage.length; index += 1) {
      const key = window.sessionStorage.key(index);
      if (!key || !key.includes("entry.")) continue;
      try {
        out.push(JSON.parse(window.sessionStorage.getItem(key) ?? "{}").relative_offset);
      } catch {
        /* ignore malformed */
      }
    }
    return out;
  });
  ctx.check(
    "natural-scroll-persists-relative-offset",
    storedOffsets.some((value) => typeof value === "number" && value > 0.05),
    JSON.stringify(storedOffsets),
  );

  // 4. 显式导航使用 push。
  const pushBefore = await page.evaluate(() => window.history.length);
  await page.click('[data-test="position-nav-axis"]');
  await waitForActive(page, 10);
  const pushAfter = await page.evaluate(() => window.history.length);
  ctx.check("explicit-nav-pushes-history", pushAfter === pushBefore + 1, `${pushBefore}->${pushAfter}`);

  // 5. 回溯事件预览不改 active unit / 叙事时间。
  const activeBeforePreview = await activeUnitId(page);
  const timeBeforePreview = await text(page, '[data-test="position-time-label"]');
  await page.click('[data-test="position-preview"]');
  await page.waitForTimeout(200);
  ctx.check("preview-keeps-active-unit", (await activeUnitId(page)) === activeBeforePreview);
  ctx.check("preview-keeps-narrative-time", (await text(page, '[data-test="position-time-label"]')) === timeBeforePreview);
  ctx.check("preview-does-not-push-history", (await page.evaluate(() => window.history.length)) === pushAfter);
  ctx.info("preview_count", await text(page, '[data-test="position-preview-count"]'));

  // 6. back/forward 按本站 history entry 恢复。
  await page.evaluate(() => window.history.back());
  await waitForActive(page, 2);
  ctx.check("back-restores-previous-locator", (await activeUnitId(page)) === ru(2), `active=${await activeUnitId(page)}`);
  await page.evaluate(() => window.history.forward());
  await waitForActive(page, 10);
  ctx.check("forward-restores-next-locator", (await activeUnitId(page)) === ru(10));

  // 7. 未知段时间/人物不遗留前段。
  await scrollToUnit(page, 7);
  await waitForActive(page, 7);
  await page.waitForTimeout(150);
  ctx.check("unknown-clears-narrative-time", (await text(page, '[data-test="position-time-label"]')) === "时间未明确");
  ctx.check("unknown-clears-context", (await text(page, '[data-test="position-context-count"]')) === "0");

  // 8. A→B→Event→返回：多层不可预测 token 各自恢复。
  await scrollToUnit(page, 2);
  await waitForActive(page, 2);
  await page.click('[data-test="position-remember-return"]');
  await page.click('[data-test="position-nav-axis"]');
  await waitForActive(page, 10);
  await page.click('[data-test="position-remember-return"]');
  const tokens = await page.$$eval('[data-test="position-return-tokens"] [data-token]', (nodes) =>
    nodes.map((node) => node.getAttribute("data-token")),
  );
  ctx.check(
    "return-tokens-unpredictable-and-distinct",
    tokens.length === 2 && tokens[0] !== tokens[1] && tokens.every((token) => /^rt_[0-9a-f]{32}$/.test(token ?? "")),
    JSON.stringify(tokens),
  );
  await page.click('[data-test="position-return-token-0"]');
  await waitForActive(page, 2);
  ctx.check("multi-level-return-first", (await activeUnitId(page)) === ru(2));
  await page.click('[data-test="position-return-token-1"]');
  await waitForActive(page, 10);
  ctx.check("multi-level-return-second", (await activeUnitId(page)) === ru(10));

  // 9. 迟到的旧 locate 响应不得抢回视口；用户滚动打断恢复。
  await page.click('[data-test="position-delayed-nav"]');
  await page.evaluate(() => window.dispatchEvent(new WheelEvent("wheel", { deltaY: 240 })));
  await scrollToUnit(page, 3);
  await waitForActive(page, 3);
  await page.waitForTimeout(1100);
  ctx.check(
    "stale-locate-response-ignored",
    (await activeUnitId(page)) === ru(3),
    `active=${await activeUnitId(page)}`,
  );
  const navState = await text(page, '[data-test="position-nav-state"]');
  ctx.check("user-interrupt-returns-to-idle", navState === "idle" || navState === "interrupted", `state=${navState}`);

  // 10. 失效 token 退回“进入相关正文”，不外部跳转。
  const origin = await page.evaluate(() => window.location.origin);
  const activeBeforeInvalid = await activeUnitId(page);
  await page.click('[data-test="position-invalid-token"]');
  await page.waitForTimeout(200);
  ctx.check("invalid-token-falls-back", (await text(page, '[data-test="position-return-result"]')).includes("token 失效"));
  ctx.check("invalid-token-no-external-jump", (await page.evaluate(() => window.location.origin)) === origin);
  ctx.check("invalid-token-keeps-active-unit", (await activeUnitId(page)) === activeBeforeInvalid);

  // 10b. 迟到的起点解析（URL 无 at）不得覆盖之后发生的显式导航。
  await page.click('[data-test="position-nav-axis"]');
  await waitForActive(page, 10);
  await page.click('[data-test="position-delayed-start"]');
  await page.click('[data-test="position-nav-event"]');
  await waitForActive(page, 15);
  await page.waitForTimeout(1000);
  ctx.check(
    "delayed-start-does-not-override-later-nav",
    (await activeUnitId(page)) === ru(15),
    `active=${await activeUnitId(page)}`,
  );
  ctx.check("delayed-start-resolves-idle", (await text(page, '[data-test="position-nav-state"]')) === "idle");
  ctx.check("delayed-start-no-issue", (await text(page, '[data-test="position-issue"]')) === "");

  // 10c. locate 抛错必须显式回落 idle，保留已读正文与 URL。
  const activeBeforeLocateFailure = await activeUnitId(page);
  await page.click('[data-test="position-fail-locate"]');
  await page.waitForTimeout(400);
  ctx.check("locate-failure-explicit-issue", (await text(page, '[data-test="position-issue"]')) === "snapshot_mismatch");
  ctx.check("locate-failure-returns-idle", (await text(page, '[data-test="position-nav-state"]')) === "idle");
  ctx.check("locate-failure-preserves-active", (await activeUnitId(page)) === activeBeforeLocateFailure);
  ctx.check(
    "locate-failure-preserves-url",
    (await page.evaluate(() => new URLSearchParams(window.location.search).get("at"))) === activeBeforeLocateFailure,
  );

  // 10d. locate 成功后、loadWindow/DOM 就绪前用户滚动取消：不得提交目标 URL/locator。
  await page.click('[data-test="position-nav-axis"]');
  await waitForActive(page, 10);
  await page.click('[data-test="position-slow-window-nav"]');
  await page.evaluate(() => window.dispatchEvent(new WheelEvent("wheel", { deltaY: 240 })));
  await scrollToUnit(page, 4);
  await waitForActive(page, 4);
  await page.waitForTimeout(1000);
  ctx.check(
    "cancel-during-loadwindow-keeps-active-unit",
    (await activeUnitId(page)) === ru(4),
    `active=${await activeUnitId(page)}`,
  );
  const atAfterCancel = await page.evaluate(() => new URLSearchParams(window.location.search).get("at"));
  ctx.check("cancel-during-loadwindow-does-not-commit-target-url", atAfterCancel !== ru(25), `at=${atAfterCancel}`);
  ctx.check("cancel-during-loadwindow-url-matches-active", atAfterCancel === ru(4), `at=${atAfterCancel}`);
  ctx.check("cancel-during-loadwindow-no-issue", (await text(page, '[data-test="position-issue"]')) === "");
  ctx.check(
    "cancel-during-loadwindow-settles-idle",
    (await text(page, '[data-test="position-nav-state"]')) === "idle",
  );

  // Loading notices and delayed prepends keep the reading point in place;
  // subsequent user scrolling must still update active normally.
  await page.click('[data-test="position-nav-axis"]');
  await waitForActive(page, 10);
  const topBeforePrepend = await page.locator(`[data-reading-unit][data-unit-id="${ru(10)}"]`)
    .evaluate((node) => node.getBoundingClientRect().top);
  await page.click('[data-test="position-prepend"]');
  await page.waitForFunction(() => document.querySelector('[data-test="position-prepended"]')?.dataset.height === "6000");
  await page.waitForTimeout(100);
  const topAfterPrepend = await page.locator(`[data-reading-unit][data-unit-id="${ru(10)}"]`)
    .evaluate((node) => node.getBoundingClientRect().top);
  ctx.check("delayed-prepend-preserves-reading-point",
    Math.abs(topAfterPrepend - topBeforePrepend) <= 3 && await activeOrdinal(page) === 10,
    `top=${topBeforePrepend}->${topAfterPrepend}, active=${await activeOrdinal(page)}`);
  await page.mouse.wheel(0, 500);
  await page.waitForFunction(() => Number(document.querySelector('[data-test="position-active-unit"]')?.dataset.ordinal) > 10);
  ctx.check("layout-preservation-does-not-lock-user-scroll", await activeOrdinal(page) > 10);

  ctx.check("no-page-error", pageErrors.length === 0, pageErrors.join(";"));

  // 11. storage 不可用：URL 定位仍可用，token 安全降级。
  const offErrors = [];
  const offPage = await ctx.runner.newPage({ viewport: VIEWPORT });
  offPage.on("pageerror", (error) => offErrors.push(String(error)));
  await offPage.goto(deepLink(ctx, "storage-off", { at: ru(12), storage: "off" }), { waitUntil: "networkidle" });
  await offPage.waitForSelector('[data-test="position-scene"]', { timeout: 15000 });
  await waitForActive(offPage, 12);
  ctx.check("storage-off-deep-link-still-works", (await activeUnitId(offPage)) === ru(12));
  await offPage.click('[data-test="position-remember-return"]');
  await offPage.waitForTimeout(150);
  ctx.check(
    "storage-off-reports-unavailable",
    (await text(offPage, '[data-test="position-return-result"]')).includes("存储不可用"),
  );
  await offPage.click('[data-test="position-restore-return"]');
  await offPage.waitForTimeout(150);
  ctx.check(
    "storage-off-token-degrades",
    (await text(offPage, '[data-test="position-return-result"]')).includes("token 失效"),
  );
  ctx.check("storage-off-keeps-active-unit", (await activeUnitId(offPage)) === ru(12));
  ctx.check("storage-off-no-page-error", offErrors.length === 0, offErrors.join(";"));

  // A locate page containing only the final paragraph cannot initially reach
  // the requested offset. Delay its prefix beyond URL settle and keep that
  // request until the page can reach it; a real stream edge finishes normally.
  const shortPage = await ctx.runner.newPage({ viewport: VIEWPORT });
  await shortPage.goto(deepLink(ctx, "short-window", { at: ru(20) }), { waitUntil: "networkidle" });
  await waitForActive(shortPage, 20);
  await shortPage.waitForTimeout(300);
  ctx.check("temporary-short-window-keeps-restore-intent",
    await text(shortPage, '[data-test="position-nav-state"]') === "restoring");
  await shortPage.click('[data-test="position-short-prepend"]');
  await shortPage.waitForFunction(() =>
    document.querySelector('[data-test="position-prepended"]')?.dataset.height === "6000" &&
    document.querySelector('[data-test="position-nav-state"]')?.textContent === "idle");
  const alignedTop = await shortPage.locator('[data-reading-unit]').evaluate((node) => node.getBoundingClientRect().top);
  ctx.check("short-window-restores-requested-offset-after-prefix",
    Math.abs(alignedTop - (64 + (VIEWPORT.height - 64) * 0.3 - 2)) <= 3,
    `top=${alignedTop}`);
  const restoredScroll = await shortPage.evaluate(() => scrollY);
  await shortPage.mouse.wheel(0, -200);
  await shortPage.waitForTimeout(100);
  ctx.check("completed-short-window-restore-releases-scroll",
    Math.abs(await shortPage.evaluate(() => scrollY) - (restoredScroll - 200)) <= 3);

  const singlePage = await ctx.runner.newPage({ viewport: VIEWPORT });
  await singlePage.goto(deepLink(ctx, "short-window", { at: ru(0), more: "false" }), { waitUntil: "networkidle" });
  await waitForActive(singlePage, 0);
  await singlePage.waitForTimeout(300);
  ctx.check("single-paragraph-real-boundary-finishes",
    await text(singlePage, '[data-test="position-nav-state"]') === "idle" &&
    await singlePage.evaluate(() => scrollY) === 0);

  for (const input of ["wheel", "touch"]) {
    const cancelledPage = await ctx.runner.newPage({ viewport: VIEWPORT, hasTouch: input === "touch" });
    await cancelledPage.goto(deepLink(ctx, "short-window", { at: ru(20) }), { waitUntil: "networkidle" });
    await waitForActive(cancelledPage, 20);
    await cancelledPage.click('[data-test="position-short-prepend"]');
    if (input === "wheel") await cancelledPage.mouse.wheel(0, 40);
    else await cancelledPage.touchscreen.tap(600, 400);
    await cancelledPage.waitForTimeout(100);
    const userTop = await cancelledPage.locator('[data-reading-unit]').evaluate((node) => node.getBoundingClientRect().top);
    await cancelledPage.waitForFunction(() => document.querySelector('[data-test="position-prepended"]')?.dataset.height === "6000");
    await cancelledPage.waitForTimeout(100);
    const finalTop = await cancelledPage.locator('[data-reading-unit]').evaluate((node) => node.getBoundingClientRect().top);
    ctx.check(`short-window-${input}-cancels-pending-alignment`,
      Math.abs(finalTop - userTop) <= 3 &&
      await text(cancelledPage, '[data-test="position-nav-state"]') !== "restoring",
      `top=${userTop}->${finalTop}`);
  }

  await ctx.screenshot(page, "position-summary");
}
