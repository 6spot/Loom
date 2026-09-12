#!/usr/bin/env node
// C2-R3-T12 章阶段依据审核组件的独立真实浏览器验收（仅测试使用）。
//
// 复用 scripts/reading-component-smoke.mjs 的 r3 suite：本文件导出 run(ctx)，
// 由共享 runner 以 `--suite person-state-review` 调用。页面是自包含 Vite 入口
// `scenes/person-state-review/index.html`，只操作正式 PersonStateReviewPanel，
// 全部数据为合成 fixture，不是真实史料或已发布内容。

export const FIXTURE_PATH = "/tests/fixtures/reading/scenes/person-state-review/index.html";
export const WIDE = { width: 1440, height: 900 };

const KEY = (seed) => `psc_${seed.toString(16).padStart(24, "0")}`;
const k1 = KEY(1);
const k2 = KEY(2);
const k6 = KEY(6);

function currentReview(page) {
  return page.locator('[data-test="psr-current-review"]').innerText();
}

function lastAction(page) {
  return page.locator('[data-test="psr-last-action"]').innerText();
}

function coverage(page) {
  return page.locator('[data-test="psr-coverage"]').innerText();
}

export async function run(ctx) {
  const page = await ctx.openScene(FIXTURE_PATH, { viewport: WIDE });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  const originalPath = new URL(page.url()).pathname + new URL(page.url()).search;
  await page.waitForSelector('[data-test="person-state-review-panel"]', { timeout: 15000 });
  ctx.check("scene-synthetic", (await page.locator('[data-test="psr-synthetic-flag"]').innerText()).includes("合成"));

  // 1. 全部候选可达，且按人物分组、共用阶段依据单列。
  const candidateCount = await page.locator('[data-test="psr-candidate"]').count();
  ctx.check("all-candidates-rendered", candidateCount === 24, `count=${candidateCount}`);
  ctx.info("candidate_count", candidateCount);
  ctx.check("person-groups", (await page.locator('[data-test="psr-person"]').count()) >= 3);
  ctx.check("shared-phase-basis", (await page.locator('[data-test="psr-basis-item"]').count()) >= 2);
  const lastCandidate = page.locator('[data-test="psr-candidate"]').last();
  await lastCandidate.scrollIntoViewIfNeeded();
  ctx.check("last-candidate-reachable", await lastCandidate.isVisible());
  ctx.check("effect-badges", (await page.locator('[data-test="psr-effect"]').count()) === candidateCount);
  ctx.check("qualification-visible", (await page.locator('[data-test="psr-qualification"]').count()) >= 1);
  ctx.check("reasons-visible", (await page.locator('[data-test="psr-reasons"]').count()) >= 1);
  ctx.check("predicted-effects-labelled", (await page.locator('[data-test="psr-effect"]').allInnerTexts()).join("|").includes("预测效果"));

  // 2. 初始覆盖反映服务端编译默认值：默认为 supported 的候选被批量覆盖，
  //    默认为 uncertain/disputed 的进入逐项例外。
  const initialCoverage = await coverage(page);
  ctx.check(
    "initial-coverage-reflects-defaults",
    initialCoverage === "批量覆盖 15 项，逐项例外 9 项（共 24 项）",
    initialCoverage,
  );

  // 2b. 复用只读来源槽：窗口与整章原文可查看，且不改变评估与草稿。
  const sourceHost = page.locator(`[data-candidate-key="${k1}"]`);
  ctx.check("source-slot-present", (await page.locator('[data-test="psr-source-slot"]').count()) === candidateCount);
  await sourceHost.locator('[data-test="psr-source-window"]').click();
  ctx.check("source-window-visible", await sourceHost.locator('[data-test="psr-source-window-text"]').isVisible());
  await sourceHost.locator('[data-test="psr-source-chapter"]').click();
  ctx.check("source-chapter-visible", await sourceHost.locator('[data-test="psr-source-chapter-text"]').isVisible());
  ctx.check("source-view-keeps-assessment", (await sourceHost.getAttribute("data-assessment")) === "supported");

  // 3. 批量确认覆盖全部候选，但仍声明不是人物合并/永久在任。
  await page.locator('[data-test="psr-batch-confirm"]').click();
  ctx.check(
    "batch-covers-all",
    (await coverage(page)) === "批量覆盖 24 项，逐项例外 0 项（共 24 项）",
    await coverage(page),
  );
  const allSupported = await page.$$eval('[data-test="psr-candidate"]', (nodes) =>
    nodes.every(
      (node) => node.getAttribute("data-assessment") === "supported" && node.getAttribute("data-exception") === "false",
    ),
  );
  ctx.check("batch-sets-supported", allSupported);
  ctx.check("batch-scope-note", (await page.locator('[data-test="psr-batch-note"]').innerText()).includes("不建立人物等价"));

  // 4. 例外按精确 candidate_key 提交，不串到其他候选。
  const exception = page.locator(`[data-candidate-key="${k6}"]`);
  await exception.locator('[data-test="psr-assessment"]').selectOption("rejected");
  await exception.locator('[data-test="psr-candidate-rationale"]').fill("错主体，拒绝");
  ctx.check("exception-marked", (await exception.getAttribute("data-exception")) === "true");
  ctx.check(
    "exception-count-updates",
    (await coverage(page)) === "批量覆盖 23 项，逐项例外 1 项（共 24 项）",
    await coverage(page),
  );
  const untouched = page.locator(`[data-candidate-key="${k1}"]`);
  ctx.check(
    "exception-does-not-bleed",
    (await untouched.getAttribute("data-assessment")) === "supported" &&
      (await untouched.getAttribute("data-exception")) === "false",
  );

  // 5. 键盘：批量按钮可聚焦并用 Enter 触发；评估下拉可聚焦。
  await page.locator('[data-test="psr-batch-confirm"]').focus();
  await page.keyboard.press("Enter");
  ctx.check("keyboard-batch-works", (await coverage(page)).includes("逐项例外 0 项"));
  await exception.locator('[data-test="psr-assessment"]').focus();
  ctx.check(
    "keyboard-assessment-focusable",
    (await page.evaluate(() => document.activeElement?.getAttribute("data-test"))) === "psr-assessment",
  );

  // 6. 409 失败保留草稿与已读原文，说明核对服务端状态，不切项。
  await exception.locator('[data-test="psr-candidate-rationale"]').fill("奏章自称，未证明收讫");
  await page.locator('[data-test="psr-simulate-error"]').selectOption("409");
  await page.locator('[data-test="psr-save-next"]').click();
  await page.waitForSelector('[data-test="psr-error"]', { timeout: 10000 });
  const errorText = await page.locator('[data-test="psr-error"]').innerText();
  ctx.check("409-error-explicit", errorText.includes("409") && errorText.includes("核对服务端记录"), errorText);
  ctx.check("409-keeps-draft", (await exception.locator('[data-test="psr-candidate-rationale"]').inputValue()) === "奏章自称，未证明收讫");
  ctx.check("409-keeps-source", await exception.locator('[data-test="psr-quote"]').isVisible());
  ctx.check("409-does-not-advance", (await currentReview(page)) === "synth-review-A");

  // 7. 重试成功后切到下一项，且新项不沿用上一包草稿（复用同一 candidate_key）。
  await page.locator('[data-test="psr-simulate-error"]').selectOption("none");
  await page.locator('[data-test="psr-save-next"]').click();
  await page.waitForFunction(
    () => document.querySelector('[data-test="psr-current-review"]')?.textContent === "synth-review-B",
    null,
    { timeout: 10000 },
  );
  const bKey1 = page.locator(`[data-review-id="synth-review-B"] [data-candidate-key="${k1}"]`);
  ctx.check("save-advances", true);
  ctx.check("next-item-clears-rationale", (await bKey1.locator('[data-test="psr-candidate-rationale"]').inputValue()) === "");
  ctx.check("next-item-no-carry-assessment", (await bKey1.getAttribute("data-assessment")) === "supported");
  ctx.check("next-item-fresh-exception", (await bKey1.getAttribute("data-exception")) === "false");

  // 8. 「暂时跳过」切项、不提交决定。
  await page.locator('[data-test="psr-skip"]').click();
  await page.waitForFunction(
    () => document.querySelector('[data-test="psr-current-review"]')?.textContent === "synth-review-A",
    null,
    { timeout: 10000 },
  );
  ctx.check("skip-advances", true);
  ctx.check("skip-not-submitted", (await lastAction(page)).startsWith("skip:synth-review-B"), await lastAction(page));

  // 9. 迟到响应不得清空/覆盖当前项的草稿。
  await page.locator('[data-test="psr-simulate-late"]').check();
  await page.locator('[data-test="psr-save-next"]').click();
  await page.locator('[data-test="psr-force-next"]').click();
  await page.waitForFunction(
    () => document.querySelector('[data-test="psr-current-review"]')?.textContent === "synth-review-B",
    null,
    { timeout: 10000 },
  );
  const bKey2 = page.locator(`[data-review-id="synth-review-B"] [data-candidate-key="${k2}"]`);
  await bKey2.locator('[data-test="psr-candidate-rationale"]').fill("B 包理由，迟到结果不得清除");
  await page.waitForTimeout(1000);
  ctx.check("late-dropped", (await lastAction(page)).includes("late-dropped:synth-review-A"), await lastAction(page));
  ctx.check("late-keeps-current-item", (await currentReview(page)) === "synth-review-B");
  ctx.check(
    "late-keeps-new-draft",
    (await bKey2.locator('[data-test="psr-candidate-rationale"]').inputValue()) === "B 包理由，迟到结果不得清除",
  );
  ctx.check("late-no-error", (await page.locator('[data-test="psr-error"]').count()) === 0);
  await page.locator('[data-test="psr-simulate-late"]').uncheck();

  // 10. 来源分页失败不阻塞表单输入。
  await page.locator('[data-test="psr-source-failure"]').click();
  ctx.check("source-failure-explicit", await page.locator('[data-test="psr-source-error"]').isVisible());
  ctx.check(
    "source-failure-inputs-enabled",
    (await page.locator('[data-test="psr-save-next"]').isEnabled()) &&
      (await page.locator('[data-test="psr-assessment"]').first().isEnabled()),
  );
  await page.locator('[data-test="psr-source-failure"]').click();

  // 11. 长页底部固定操作区仍可见可操作。
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(150);
  ctx.check("action-bar-visible-at-bottom", await page.locator('[data-test="psr-save-next"]').isVisible());
  const barBox = await page.locator('[data-test="psr-action-bar"]').boundingBox();
  ctx.check(
    "action-bar-in-viewport",
    Boolean(barBox) && barBox.y < (page.viewportSize()?.height ?? 0),
    JSON.stringify(barBox),
  );
  await ctx.screenshot(page, "review-1440");

  // 12. 返回队列只记录动作，不改表单。
  await page.locator('[data-test="psr-return"]').click();
  ctx.check("return-recorded", (await lastAction(page)).startsWith("return:synth-review-B"), await lastAction(page));

  // 13. 窄屏 390/320：无横向溢出，操作区与评估控件可达。
  for (const viewport of [
    { width: 390, height: 844 },
    { width: 320, height: 568 },
  ]) {
    await page.setViewportSize(viewport);
    await page.waitForTimeout(150);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    ctx.check(`narrow-${viewport.width}-no-overflow`, overflow <= 1, `overflow=${overflow}`);
    ctx.check(`narrow-${viewport.width}-action-visible`, await page.locator('[data-test="psr-save-next"]').isVisible());
    ctx.check(`narrow-${viewport.width}-assessment-usable`, await page.locator('[data-test="psr-assessment"]').first().isVisible());
    await ctx.screenshot(page, `review-${viewport.width}`);
  }

  // 14. 不抢写共享 session 或页面入口。
  const shared = await page.evaluate(() => ({
    sessionKeys: sessionStorage.length,
    path: window.location.pathname + window.location.search,
  }));
  ctx.check("no-shared-session-write", shared.sessionKeys === 0, JSON.stringify(shared));
  ctx.check("no-page-navigation", shared.path === originalPath, `${originalPath} -> ${shared.path}`);

  // 15. 真实 Chromium 无未捕获异常。
  ctx.check("no-page-error", errors.length === 0, errors.join("; "));
}
