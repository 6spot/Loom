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

function reviewId(page) {
  return page.locator('[data-test="psr-current-review"]').innerText();
}

function lastAction(page) {
  return page.locator('[data-test="psr-last-action"]').innerText();
}

function coverage(page) {
  return page.locator('[data-test="psr-coverage"]').innerText();
}

async function loadAllCandidates(page) {
  const loadMore = page.locator('[data-test="psr-load-more"]');
  if (await loadMore.count()) {
    await loadMore.click();
    await page.waitForSelector('[data-test="psr-pagination-complete"]', { timeout: 10000 });
  }
}

export async function run(ctx) {
  const page = await ctx.openScene(FIXTURE_PATH, { viewport: WIDE });
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  const originalPath = new URL(page.url()).pathname + new URL(page.url()).search;
  await page.waitForSelector('[data-test="person-state-review-panel"]', { timeout: 15000 });
  ctx.check("scene-synthetic", (await page.locator('[data-test="psr-synthetic-flag"]').innerText()).includes("合成"));

  // 1. 全部候选可达，且按人物分组、共用阶段依据带可读依据。
  const candidateCount = await page.locator('[data-test="psr-candidate"]').count();
  ctx.check("all-candidates-rendered", candidateCount === 24, `count=${candidateCount}`);
  ctx.info("page1_candidate_count", candidateCount);
  ctx.check("person-groups", (await page.locator('[data-test="psr-person"]').count()) >= 3);
  ctx.check("shared-phase-basis", (await page.locator('[data-test="psr-basis-item"]').count()) >= 2);
  const basisEntries = await page.locator('[data-test="psr-basis-entry"]').count();
  ctx.check("basis-has-readable-entries", basisEntries === candidateCount, `entries=${basisEntries}`);
  const firstBasisText = await page.locator('[data-test="psr-basis-entry"]').first().innerText();
  ctx.check(
    "basis-readable-text",
    firstBasisText.includes("来源：") && firstBasisText.includes("周瑜") && !firstBasisText.includes("ph_0"),
    firstBasisText,
  );
  ctx.check("basis-audit-details", (await page.locator(".psr-audit").count()) >= 2);
  const lastCandidate = page.locator('[data-test="psr-candidate"]').last();
  await lastCandidate.scrollIntoViewIfNeeded();
  ctx.check("last-candidate-reachable", await lastCandidate.isVisible());
  ctx.check("effect-badges", (await page.locator('[data-test="psr-effect"]').count()) === candidateCount);
  ctx.check("qualification-visible", (await page.locator('[data-test="psr-qualification"]').count()) >= 1);
  ctx.check("reasons-visible", (await page.locator('[data-test="psr-reasons"]').count()) >= 1);

  // 2. 初始状态全部未审：未审既不计入覆盖也不得提交为 supported。
  ctx.check(
    "initial-all-unreviewed",
    (await page.$$eval('[data-test="psr-candidate"]', (nodes) =>
      nodes.every((node) => node.getAttribute("data-reviewed") === "false" && node.getAttribute("data-assessment") === "unreviewed"),
    )),
  );
  ctx.check("unreviewed-badge-visible", (await page.locator('[data-test="psr-review-state"]').count()) === candidateCount);
  ctx.check(
    "initial-coverage-unreviewed",
    (await coverage(page)) === "已审 0 项（批量覆盖 0 项，逐项例外 0 项）；未审 24 项（共 24 项）",
    await coverage(page),
  );
  ctx.check("unreviewed-warning", await page.locator('[data-test="psr-unreviewed"]').isVisible());
  ctx.check(
    "submit-blocked-while-unreviewed",
    (await page.getAttribute('[data-test="psr-save-next"]', "data-blocked-reason")) === "unreviewed" &&
      !(await page.locator('[data-test="psr-save-next"]').isEnabled()),
  );

  // 3. 复用只读来源槽：窗口与整章原文可查看，且不改变评估与草稿。
  const sourceHost = page.locator(`[data-candidate-key="${k1}"]`);
  ctx.check("source-slot-present", (await page.locator('[data-test="psr-source-slot"]').count()) === candidateCount);
  await sourceHost.locator('[data-test="psr-source-window"]').click();
  ctx.check("source-window-visible", await sourceHost.locator('[data-test="psr-source-window-text"]').isVisible());
  await sourceHost.locator('[data-test="psr-source-chapter"]').click();
  ctx.check("source-chapter-visible", await sourceHost.locator('[data-test="psr-source-chapter-text"]').isVisible());
  ctx.check("source-view-keeps-unreviewed", (await sourceHost.getAttribute("data-assessment")) === "unreviewed");

  // 4. 候选分页：取全后全部候选可达且仍为未审。
  await loadAllCandidates(page);
  await page.waitForFunction(
    () => document.querySelectorAll('[data-test="psr-candidate"]').length === 40,
    null,
    { timeout: 10000 },
  );
  ctx.check("all-pages-reachable", (await page.locator('[data-test="psr-candidate"]').count()) === 40);
  ctx.check("load-more-recorded", (await lastAction(page)).startsWith("load-more:synth-review-A"));
  ctx.check(
    "coverage-after-load-all",
    (await coverage(page)) === "已审 0 项（批量覆盖 0 项，逐项例外 0 项）；未审 40 项（共 40 项）",
    await coverage(page),
  );
  ctx.check("pagination-complete", await page.locator('[data-test="psr-pagination-complete"]').isVisible());

  // 5. 批量确认覆盖全部已加载候选，但仍声明不是人物合并/永久在任。
  await page.locator('[data-test="psr-batch-confirm"]').click();
  ctx.check(
    "batch-covers-all",
    (await coverage(page)) === "已审 40 项（批量覆盖 40 项，逐项例外 0 项）；未审 0 项（共 40 项）",
    await coverage(page),
  );
  const allSupported = await page.$$eval('[data-test="psr-candidate"]', (nodes) =>
    nodes.every(
      (node) => node.getAttribute("data-assessment") === "supported" && node.getAttribute("data-exception") === "false",
    ),
  );
  ctx.check("batch-sets-supported", allSupported);
  ctx.check("batch-scope-note", (await page.locator('[data-test="psr-batch-note"]').innerText()).includes("不建立人物等价"));
  ctx.check("submit-enabled-after-review", await page.locator('[data-test="psr-save-next"]').isEnabled());

  // 6. 例外按精确 candidate_key 提交，不串到其他候选。
  const exception = page.locator(`[data-candidate-key="${k6}"]`);
  await exception.locator('[data-test="psr-assessment"]').selectOption("rejected");
  await exception.locator('[data-test="psr-candidate-rationale"]').fill("错主体，拒绝");
  ctx.check("exception-marked", (await exception.getAttribute("data-exception")) === "true");
  ctx.check(
    "exception-count-updates",
    (await coverage(page)) === "已审 40 项（批量覆盖 39 项，逐项例外 1 项）；未审 0 项（共 40 项）",
    await coverage(page),
  );
  const untouched = page.locator(`[data-candidate-key="${k1}"]`);
  ctx.check(
    "exception-does-not-bleed",
    (await untouched.getAttribute("data-assessment")) === "supported" &&
      (await untouched.getAttribute("data-exception")) === "false",
  );

  // 7. 明确提交「不明确」与未审可区分：显式选择 uncertain 后标记为已审。
  const explicitUncertain = page.locator(`[data-candidate-key="${k2}"]`);
  await explicitUncertain.locator('[data-test="psr-assessment"]').selectOption("uncertain");
  ctx.check("explicit-uncertain-reviewed", (await explicitUncertain.getAttribute("data-reviewed")) === "true");
  ctx.check("explicit-uncertain-assessment", (await explicitUncertain.getAttribute("data-assessment")) === "uncertain");
  await explicitUncertain.locator('[data-test="psr-clear-override"]').click();
  ctx.check("mark-unreviewed-again", (await explicitUncertain.getAttribute("data-assessment")) === "unreviewed");
  await page.locator(`[data-candidate-key="${k2}"] [data-test="psr-assessment"]`).selectOption("supported");

  // 8. 键盘：批量按钮可聚焦并用 Enter 触发；评估下拉可聚焦。
  await page.locator('[data-test="psr-batch-confirm"]').focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(100);
  ctx.check("keyboard-batch-works", (await coverage(page)).includes("逐项例外 0 项"), await coverage(page));
  await exception.locator('[data-test="psr-assessment"]').focus();
  ctx.check(
    "keyboard-assessment-focusable",
    (await page.evaluate(() => document.activeElement?.getAttribute("data-test"))) === "psr-assessment",
  );

  // 9. 409 失败保留草稿与已读原文，说明核对服务端状态，不切项。
  await exception.locator('[data-test="psr-assessment"]').selectOption("rejected");
  await exception.locator('[data-test="psr-candidate-rationale"]').fill("奏章自称，未证明收讫");
  await page.locator('[data-test="psr-simulate-error"]').selectOption("409");
  await page.locator('[data-test="psr-save-next"]').click();
  await page.waitForSelector('[data-test="psr-error"]', { timeout: 10000 });
  const errorText = await page.locator('[data-test="psr-error"]').innerText();
  ctx.check("409-error-explicit", errorText.includes("409") && errorText.includes("核对服务端记录"), errorText);
  ctx.check("409-keeps-draft", (await exception.locator('[data-test="psr-candidate-rationale"]').inputValue()) === "奏章自称，未证明收讫");
  ctx.check("409-keeps-source", await exception.locator('[data-test="psr-quote"]').isVisible());
  ctx.check("409-does-not-advance", (await reviewId(page)) === "synth-review-A");

  // 10. 重试成功后切到下一项，新项全部未审且不沿用上一包草稿。
  await page.locator('[data-test="psr-simulate-error"]').selectOption("none");
  await page.locator('[data-test="psr-save-next"]').click();
  await page.waitForFunction(
    () => document.querySelector('[data-test="psr-current-review"]')?.textContent === "synth-review-B",
    null,
    { timeout: 10000 },
  );
  const bKey1 = page.locator(`[data-review-id="synth-review-B"] [data-candidate-key="${k1}"]`);
  ctx.check("save-advances", true);
  ctx.check(
    "next-item-all-unreviewed",
    (await coverage(page)) === "已审 0 项（批量覆盖 0 项，逐项例外 0 项）；未审 4 项（共 4 项）",
    await coverage(page),
  );
  ctx.check("next-item-clears-rationale", (await bKey1.locator('[data-test="psr-candidate-rationale"]').inputValue()) === "");
  ctx.check("next-item-no-carry-assessment", (await bKey1.getAttribute("data-assessment")) === "unreviewed");

  // 11. 「暂时跳过」切项、不提交决定。
  await page.locator('[data-test="psr-skip"]').click();
  await page.waitForFunction(
    () => document.querySelector('[data-test="psr-current-review"]')?.textContent === "synth-review-A",
    null,
    { timeout: 10000 },
  );
  ctx.check("skip-advances", true);
  ctx.check("skip-not-submitted", (await lastAction(page)).startsWith("skip:synth-review-B"), await lastAction(page));

  // 12. 迟到响应不得清空/覆盖当前项的草稿。
  await loadAllCandidates(page);
  await page.locator('[data-test="psr-batch-confirm"]').click();
  await page.locator('[data-test="psr-simulate-late"]').check();
  await page.locator('[data-test="psr-save-next"]').click();
  await page.locator('[data-test="psr-force-next"]').click();
  await page.waitForFunction(
    () => document.querySelector('[data-test="psr-current-review"]')?.textContent === "synth-review-B",
    null,
    { timeout: 10000 },
  );
  const bKey2 = page.locator(`[data-review-id="synth-review-B"] [data-candidate-key="${k2}"]`);
  await bKey2.locator('[data-test="psr-assessment"]').selectOption("supported");
  await bKey2.locator('[data-test="psr-candidate-rationale"]').fill("B 包理由，迟到结果不得清除");
  await page.waitForTimeout(1000);
  ctx.check("late-dropped", (await lastAction(page)).includes("late-dropped:synth-review-A"), await lastAction(page));
  ctx.check("late-keeps-current-item", (await reviewId(page)) === "synth-review-B");
  ctx.check(
    "late-keeps-new-draft",
    (await bKey2.locator('[data-test="psr-candidate-rationale"]').inputValue()) === "B 包理由，迟到结果不得清除",
  );
  ctx.check("late-no-error", (await page.locator('[data-test="psr-error"]').count()) === 0);
  await page.locator('[data-test="psr-simulate-late"]').uncheck();

  // 13. 分页不可达时 fail closed：广告还有候选但不提供 loader，提交停用。
  await page.locator('[data-test="psr-set-blocked"]').click();
  await page.waitForFunction(
    () => document.querySelector('[data-test="psr-current-review"]')?.textContent === "synth-review-C",
    null,
    { timeout: 10000 },
  );
  ctx.check("pagination-blocked-explicit", await page.locator('[data-test="psr-pagination-blocked"]').isVisible());
  ctx.check(
    "pagination-blocked-disables-submit",
    !(await page.locator('[data-test="psr-save-next"]').isEnabled()),
  );
  await page.locator('[data-test="psr-set-package-a"]').click();
  await page.waitForFunction(
    () => document.querySelector('[data-test="psr-current-review"]')?.textContent === "synth-review-A",
    null,
    { timeout: 10000 },
  );

  // 14. 来源分页失败不阻塞表单输入。
  await page.locator('[data-test="psr-source-failure"]').click();
  ctx.check("source-failure-explicit", await page.locator('[data-test="psr-source-error"]').isVisible());
  ctx.check(
    "source-failure-inputs-enabled",
    (await page.locator('[data-test="psr-assessment"]').first().isEnabled()),
  );
  await page.locator('[data-test="psr-source-failure"]').click();

  // 15. 长页底部固定操作区仍可见可操作。
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

  // 16. 返回队列只记录动作，不改表单。
  await page.locator('[data-test="psr-return"]').click();
  ctx.check("return-recorded", (await lastAction(page)).startsWith("return:synth-review-A"), await lastAction(page));

  // 17. 窄屏 390/320：无横向溢出，操作区与评估控件可达。
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

  // 18. 不抢写共享 session 或页面入口。
  const shared = await page.evaluate(() => ({
    sessionKeys: sessionStorage.length,
    path: window.location.pathname + window.location.search,
  }));
  ctx.check("no-shared-session-write", shared.sessionKeys === 0, JSON.stringify(shared));
  ctx.check("no-page-navigation", shared.path === originalPath, `${originalPath} -> ${shared.path}`);

  // 19. 真实 Chromium 无未捕获异常。
  ctx.check("no-page-error", errors.length === 0, errors.join("; "));
}
