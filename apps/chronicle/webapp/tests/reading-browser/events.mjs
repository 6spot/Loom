// C2-R2-T13 事件词预览/目标选择浏览器 suite 规格（仅测试使用）。
//
// 由 tests/fixtures/reading/cases/events/scene.tsx 提供合成 published-DTO 场景，
// 主 harness 通过 scripts/reading-component-smoke.mjs --suite events 调用 run(ctx)。
// 真实 Chromium 只证明组件交互与可访问性行为，不证明真实后端/译文/事件对应正确。

const TRIGGER = '[data-test="reading-event-trigger"]';
const UNCERTAIN = '[data-test="reading-event-trigger-uncertain"]';
const PREVIEW = '[data-test="reading-event-preview"]';
const PREVIEW_NAME = '[data-test="reading-event-preview-name"]';
const SENTENCE = '[data-test="events-sentence"]';
const LAST_ACTION = '[data-test="events-last-action"]';
const CALL_COUNTS = '[data-test="events-call-counts"]';
const TARGET_OPTION = '[data-test="reading-target-option"]';

const EVENT_RED_CLIFFS = "evt_000000000000000000000001";
const EVENT_REPEAT_SECOND = "evt_000000000000000000000003";
const EVENT_LATE_A = "evt_0000000000000000000000a1";
const EVENT_LATE_B = "evt_0000000000000000000000b2";
const CATALOG = "4c29947197b9be1907082482c45d724a4dd4216a9db18f9f6ba55b9085597401";
const STREAM = "0192f0a0-0000-7000-8000-00000000aa01";
const CURRENT_UNIT = "ru_000000000000000000000001";

function unitId(ordinal) {
  return `ru_${ordinal.toString(16).padStart(24, "0")}`;
}

async function action(page) {
  return await page.$eval(LAST_ACTION, (node) => ({
    kind: node.getAttribute("data-kind") || "",
    eventId: node.getAttribute("data-event-id") || "",
    unit: node.getAttribute("data-unit") || "",
    stream: node.getAttribute("data-stream") || "",
    catalog: node.getAttribute("data-catalog") || "",
  }));
}

async function counts(page) {
  return await page.$eval(CALL_COUNTS, (node) => ({
    preview: Number(node.getAttribute("data-preview") || "0"),
    target: Number(node.getAttribute("data-target") || "0"),
    detail: node.getAttribute("data-detail") || "{}",
  }));
}

async function assertReassembly(ctx, page, label) {
  const reassembly = await page.$eval(SENTENCE, (node) => ({
    expected: node.getAttribute("data-text") || "",
    joined: Array.from(
      node.querySelectorAll(
        '[data-test="events-text-segment"], [data-test="reading-event-trigger"], [data-test="reading-event-trigger-uncertain"]',
      ),
    )
      .map((child) => child.textContent || "")
      .join(""),
  }));
  ctx.check(
    label,
    reassembly.joined === reassembly.expected,
    `segments must reassemble verbatim: ${JSON.stringify(reassembly)}`,
  );
}

async function runResolved(ctx) {
  const page = await ctx.openScene("events-resolved", { viewport: { width: 1280, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.waitForSelector('[data-test="events-fixture"]');
  await assertReassembly(ctx, page, "结构化 segments 逐字拼回原译文");

  const before = await counts(page);
  ctx.check("未交互前不预取 preview/targets", before.preview === 0 && before.target === 0, JSON.stringify(before));

  // hover 打开（约 180ms 意图延迟）
  await page.locator(TRIGGER).hover();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  ctx.check("hover 打开预览", true);
  ctx.check("打开来源标记为 hover", (await page.getAttribute(PREVIEW, "data-open-reason")) === "hover");

  const name = await page.locator(PREVIEW_NAME).textContent();
  ctx.check("预览显示事件名", name === "赤壁之戰", `实际=${name}`);
  ctx.check("预览有来源归属", (await page.locator('[data-test="reading-event-preview-source"]').count()) === 1);
  ctx.check(
    "预览有译文摘录",
    ((await page.locator('[data-test="reading-event-preview-excerpt"]').textContent()) || "").includes("瑜、普為左右督"),
  );

  // 指针移入卡片不闪退
  await page.locator(PREVIEW).hover();
  await page.waitForTimeout(260);
  ctx.check("指针进入卡片不闪退", (await page.locator(PREVIEW).count()) === 1);
  await ctx.screenshot(page, "resolved-hover");

  // 指针离开卡片后关闭
  await page.mouse.move(4, 4);
  await page.waitForTimeout(260);
  ctx.check("指针离开后关闭", (await page.locator(PREVIEW).count()) === 0);

  // 查看事件：使用当前阅读 locator，带事件 id
  await page.locator(TRIGGER).hover();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  await page.locator('[data-test="reading-event-preview-view"]').click();
  const viewAction = await action(page);
  ctx.check("查看事件发出 event 导航", viewAction.kind === "event", JSON.stringify(viewAction));
  ctx.check("查看事件带 canonical event id", viewAction.eventId === EVENT_RED_CLIFFS, viewAction.eventId);
  ctx.check(
    "查看事件返回当前阅读 locator",
    viewAction.unit === CURRENT_UNIT && viewAction.stream === STREAM && viewAction.catalog === CATALOG,
    JSON.stringify(viewAction),
  );
  ctx.check("查看事件后预览关闭", (await page.locator(PREVIEW).count()) === 0);

  // 定位发生位置：唯一 current 直接跳到 target locator，而不是当前段
  await page.locator(TRIGGER).hover();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  await page.locator('[data-test="reading-event-preview-locate"]').click();
  const locateAction = await action(page);
  ctx.check("唯一 current 直接定位", locateAction.kind === "locate", JSON.stringify(locateAction));
  ctx.check("定位使用 target 正文位置", locateAction.unit === unitId(21), locateAction.unit);
  ctx.check("定位不是按名称/首个字符串", locateAction.unit !== CURRENT_UNIT, locateAction.unit);

  ctx.check("无未捕获页面异常", pageErrors.length === 0, pageErrors.join("; "));
  const after = await counts(page);
  ctx.info("resolved_counts", after);
  ctx.info("resolved_name", name);
}

async function runRepeat(ctx) {
  const page = await ctx.openScene("events-repeat", { viewport: { width: 1280, height: 900 } });
  await page.waitForSelector('[data-test="events-fixture"]');
  await assertReassembly(ctx, page, "重复词场景 segments 拼回原译文");

  ctx.check("只有两次事件 occurrence 可触发", (await page.locator(TRIGGER).count()) === 2);
  const spans = await page
    .locator(TRIGGER)
    .evaluateAll((nodes) => nodes.map((node) => ({ eventId: node.getAttribute("data-event-id"), span: node.getAttribute("data-span") })));
  ctx.check(
    "两次 occurrence 各自绑定不同事件与 span",
    spans[0].eventId === EVENT_RED_CLIFFS &&
      spans[1].eventId === EVENT_REPEAT_SECOND &&
      spans[0].span !== spans[1].span,
    JSON.stringify(spans),
  );
  ctx.check(
    "正文中普通文本「赤壁」不成为事件链接",
    (await page.locator('[data-test="events-text-segment"]').first().textContent())?.includes("赤壁"),
  );

  await page.locator(TRIGGER).first().hover();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  const firstCounts = await counts(page);
  ctx.check("只加载被触发的事件，不预取另一个", !firstCounts.detail.includes(EVENT_REPEAT_SECOND), firstCounts.detail);
  ctx.check("第一次 occurrence 预览事件名", (await page.locator(PREVIEW_NAME).textContent()) === "赤壁之戰");
  await page.mouse.move(4, 4);
  await page.waitForTimeout(260);

  await page.locator(TRIGGER).nth(1).hover();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  ctx.check("第二次 occurrence 预览另一个事件", (await page.locator(PREVIEW_NAME).textContent()) === "再記赤壁");
  ctx.check(
    "多来源时间分歧显式呈现",
    (await page.locator('[data-test="reading-event-preview-time-divergence"]').count()) === 1,
  );
  ctx.check(
    "来源总数多于已取回时如实标注",
    ((await page.locator('[data-test="reading-event-preview-source-count"]').textContent()) || "").includes("4"),
  );
  await ctx.screenshot(page, "repeat-second");
}

async function runMultiTarget(ctx) {
  const page = await ctx.openScene("events-multi-target", { viewport: { width: 1280, height: 900 } });
  await page.waitForSelector('[data-test="events-fixture"]');

  await page.locator(TRIGGER).hover();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  await page.locator('[data-test="reading-event-preview-locate"]').click();
  ctx.check("多 current 时定位先要选择", (await page.locator('[data-test="reading-target-picker"]').count()) === 1);
  ctx.check("选择器处于定位模式", (await page.getAttribute('[data-test="reading-target-picker"]', "data-mode")) === "locate");
  ctx.check("定位选择器只列 current", (await page.locator(TARGET_OPTION).count()) === 2);
  ctx.check("未选择前不跳转", (await action(page)).kind === "");

  await page.locator(TARGET_OPTION).nth(1).click();
  const chosen = await action(page);
  ctx.check("选择第二个 current 跳到该位置", chosen.kind === "locate" && chosen.unit === unitId(6), JSON.stringify(chosen));
  ctx.check("没有默认取第一个 current", chosen.unit !== unitId(5), chosen.unit);

  // 其他记载：列出 current 与 mention，mention 明确标注
  await page.locator(TRIGGER).hover();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  await page.locator('[data-test="reading-event-preview-other"]').click();
  ctx.check("其他记载为 other 模式", (await page.getAttribute('[data-test="reading-target-picker"]', "data-mode")) === "other");
  ctx.check("current 与 mention 分组", (await page.locator('[data-test="reading-target-current-group"]').count()) === 1 && (await page.locator('[data-test="reading-target-mention-group"]').count()) === 1);
  const relations = await page.locator(TARGET_OPTION).evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-relation")));
  ctx.check("mention 与 current 明确分开", relations.includes("mention") && relations.includes("current"), JSON.stringify(relations));

  const mentionOption = page.locator(`${TARGET_OPTION}[data-relation="mention"]`);
  await mentionOption.click();
  const sourceAction = await action(page);
  ctx.check("选择其他来源发出 source 导航", sourceAction.kind === "source" && sourceAction.unit === unitId(7), JSON.stringify(sourceAction));
  await ctx.screenshot(page, "multi-target");
}

async function runMentionOnly(ctx) {
  const page = await ctx.openScene("events-mention-only", { viewport: { width: 1280, height: 900 } });
  await page.waitForSelector('[data-test="events-fixture"]');

  await page.locator(TRIGGER).hover();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  await page.locator('[data-test="reading-event-preview-locate"]').click();
  ctx.check("只有回溯提及时不自动跳转", (await action(page)).kind === "");
  ctx.check("如实提示暂无发生段落", (await page.locator('[data-test="reading-target-empty"]').count()) === 1);
  ctx.check("定位模式无 current 选项", (await page.locator(`${TARGET_OPTION}[data-relation="current"]`).count()) === 0);

  await page.locator('[data-test="reading-event-preview-other"]').click();
  ctx.check("其他记载仍可查看提及", (await page.locator('[data-test="reading-target-mention-group"]').count()) === 1);
  await page.locator(`${TARGET_OPTION}[data-relation="mention"]`).click();
  ctx.check("查看提及发出 source 导航", (await action(page)).kind === "source");
}

async function runUncertain(ctx) {
  const page = await ctx.openScene("events-uncertain", { viewport: { width: 1280, height: 900 } });
  await page.waitForSelector('[data-test="events-fixture"]');
  await assertReassembly(ctx, page, "未确认 span segments 拼回原译文");

  ctx.check("未确认词没有可操作链接", (await page.locator(TRIGGER).count()) === 0);
  ctx.check("未确认词全部显示为不确定", (await page.locator(UNCERTAIN).count()) === 3);

  const reasons = await page.locator(UNCERTAIN).evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-reason")));
  ctx.check(
    "不确定原因来自 status / 无 canonical 目标",
    reasons.includes("ambiguous") && reasons.includes("unresolved") && reasons.includes("no-canonical-target"),
    JSON.stringify(reasons),
  );
  const aria = await page.locator(UNCERTAIN).first().getAttribute("aria-label");
  ctx.check("不确定提示对读屏可见", (aria || "").includes("未确认事件"), aria);

  const before = await counts(page);
  await page.locator(UNCERTAIN).first().click();
  await page.waitForTimeout(200);
  ctx.check("点击未确认词不打开预览、不静默跳转", (await page.locator(PREVIEW).count()) === 0 && (await action(page)).kind === "");
  const after = await counts(page);
  ctx.check("未确认词不触发任何加载", before.preview === 0 && after.preview === 0 && after.target === 0, JSON.stringify(after));
}

async function runLate(ctx) {
  const page = await ctx.openScene("events-late", { viewport: { width: 1280, height: 900 } });
  await page.waitForSelector('[data-test="events-fixture"]');

  await page.locator(TRIGGER).first().click();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  ctx.check("慢请求先显示自己的预览", (await page.getAttribute(PREVIEW, "data-event-id")) === EVENT_LATE_A);

  await page.locator(TRIGGER).nth(1).click();
  await page.waitForFunction(
    (expected) => document.querySelector('[data-test="reading-event-preview"]')?.getAttribute("data-event-id") === expected,
    EVENT_LATE_B,
    { timeout: 10000 },
  );
  ctx.check("切换到第二个事件", (await page.getAttribute(PREVIEW, "data-event-id")) === EVENT_LATE_B);

  await page.waitForTimeout(800);
  ctx.check("迟到的旧响应不覆盖新预览", (await page.getAttribute(PREVIEW, "data-event-id")) === EVENT_LATE_B);
  ctx.check("同一时刻只有一个预览", (await page.locator(PREVIEW).count()) === 1);
  ctx.check("迟到后名称仍为新事件", (await page.locator(PREVIEW_NAME).textContent()) === "南郡之戰");
  await ctx.screenshot(page, "late-switch");

  // 关闭后迟到响应不得重新打开
  await page.keyboard.press("Escape");
  await page.waitForTimeout(700);
  ctx.check("关闭后迟到响应不重开预览", (await page.locator(PREVIEW).count()) === 0);
}

async function runFailure(ctx) {
  const page = await ctx.openScene("events-failure", { viewport: { width: 1280, height: 900 } });
  await page.waitForSelector('[data-test="events-fixture"]');

  await page.locator(TRIGGER).hover();
  await page.waitForSelector('[data-test="reading-event-preview-error"]', { timeout: 10000 });
  ctx.check("载入失败显示错误", true);
  ctx.check(
    "失败时触发词与正文仍可用",
    (await page.locator(TRIGGER).count()) === 1 && (await page.locator(SENTENCE).isVisible()),
  );
  ctx.check("错误信息可见", ((await page.locator('[data-test="reading-event-preview-error"]').textContent()) || "").includes("controlled preview failure"));

  await page.locator('[data-test="reading-event-preview-retry"]').click();
  await page.waitForSelector('[data-test="reading-event-preview-source"]', { timeout: 10000 });
  ctx.check("重试后恢复内容", (await page.locator('[data-test="reading-event-preview-error"]').count()) === 0);
  const detail = await counts(page);
  ctx.check("重试确实重新请求", detail.preview === 2, JSON.stringify(detail));
  await ctx.screenshot(page, "failure-retry");
}

async function runKeyboard(ctx) {
  const page = await ctx.openScene("events-resolved", { viewport: { width: 1280, height: 900 } });
  await page.waitForSelector('[data-test="events-fixture"]');

  await page.locator(TRIGGER).focus();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  ctx.check("键盘 focus 打开预览", (await page.getAttribute(PREVIEW, "data-open-reason")) === "focus");

  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.getAttribute("data-test"));
  ctx.check("Tab 进入卡片按钮", focused === "reading-event-preview-close", `实际=${focused}`);

  await page.keyboard.press("Escape");
  ctx.check("Escape 关闭预览", (await page.locator(PREVIEW).count()) === 0);
  ctx.check(
    "Escape 焦点回到触发词",
    await page.evaluate(() => {
      const active = document.activeElement;
      return active?.getAttribute("data-test") === "reading-event-trigger" && active?.getAttribute("data-span") === "es_resolved";
    }),
  );
  await ctx.screenshot(page, "keyboard");
}

async function runTouch(ctx) {
  const page = await ctx.openScene("events-resolved", { viewport: { width: 390, height: 844 }, hasTouch: true });
  await page.waitForSelector('[data-test="events-fixture"]');

  await page.locator(TRIGGER).tap();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  ctx.check("触屏打开预览面板", (await page.getAttribute(PREVIEW, "data-variant")) === "panel");
  ctx.check("首次 tap 不离开正文", await page.locator(SENTENCE).isVisible());
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  ctx.check("触屏面板无横向溢出", overflow <= 1, `overflow=${overflow}`);

  await page.locator('[data-test="reading-event-preview-close"]').tap();
  ctx.check("触屏可关闭面板", (await page.locator(PREVIEW).count()) === 0);
  await ctx.screenshot(page, "touch-panel");
}

async function runReducedMotion(ctx) {
  const page = await ctx.openScene("events-reduced-motion", { viewport: { width: 1280, height: 900 } });
  await page.waitForSelector('[data-test="events-fixture"]');

  await page.locator(TRIGGER).hover();
  await page.waitForSelector(PREVIEW, { timeout: 10000 });
  ctx.check("reduced-motion 标记来自 prop", (await page.getAttribute(PREVIEW, "data-reduced-motion")) === "true");
  const animation = await page.evaluate(
    () => getComputedStyle(document.querySelector('[data-test="reading-event-preview"]')).animationName,
  );
  ctx.check("reduced-motion 不做位移动画", animation === "none", `animation=${animation}`);
}

async function runTargetsFailure(ctx) {
  const page = await ctx.openScene("events-targets-failure", { viewport: { width: 1280, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.waitForSelector('[data-test="events-fixture"]');

  await page.locator(TRIGGER).hover();
  await page.waitForSelector('[data-test="reading-event-preview-name"]', { timeout: 10000 });
  ctx.check("preview 成功仍显示事件名", (await page.locator(PREVIEW_NAME).textContent()) === "赤壁之戰");
  ctx.check(
    "preview 成功仍显示来源摘录",
    (await page.locator('[data-test="reading-event-preview-excerpt"]').count()) >= 1,
  );

  await page.waitForSelector('[data-test="reading-event-targets-error"]', { timeout: 10000 });
  ctx.check(
    "targets 失败有可访问错误区",
    (await page.getAttribute('[data-test="reading-event-targets-error"]', "role")) === "alert",
  );
  ctx.check("提供显式重试按钮", (await page.locator('[data-test="reading-event-targets-retry"]').count()) === 1);
  ctx.check("preview 内容未被 targets 失败清空", (await page.locator(PREVIEW_NAME).textContent()) === "赤壁之戰");

  // 错误态下点击「定位发生位置」会再取一次而不是静默无动作（本次仍受控失败）。
  await page.locator('[data-test="reading-event-preview-locate"]').click();
  await page.waitForFunction(
    () =>
      document.querySelector('[data-test="events-call-counts"]')?.getAttribute("data-target") === "2" &&
      document.querySelector('[data-test="reading-event-targets-error"]') !== null,
    undefined,
    { timeout: 10000 },
  );
  ctx.check("错误态点击定位会重试", (await page.locator('[data-test="reading-event-targets-error"]').count()) === 1);
  ctx.check("targets 未就绪前不跳转", (await action(page)).kind === "");

  // 点显式重试按钮恢复位置列表（第三次请求成功）。
  await page.locator('[data-test="reading-event-targets-retry"]').click();
  await page.waitForSelector('[data-test="reading-event-targets-error"]', { state: "detached", timeout: 10000 });
  const recovered = await counts(page);
  ctx.check("重试确实重新请求 targets", recovered.target === 3, JSON.stringify(recovered));
  ctx.check("重试后错误消失", (await page.locator('[data-test="reading-event-targets-error"]').count()) === 0);

  // 恢复后可选择并定位到精确正文位置。
  await page.waitForSelector(TARGET_OPTION, { timeout: 10000 });
  ctx.check("恢复后位置可选", (await page.locator(TARGET_OPTION).count()) === 1);
  await page.locator(TARGET_OPTION).click();
  const nav = await action(page);
  ctx.check("恢复后定位到 target 正文位置", nav.kind === "locate" && nav.unit === unitId(21), JSON.stringify(nav));
  ctx.check("无未捕获页面异常", pageErrors.length === 0, pageErrors.join("; "));
  await ctx.screenshot(page, "targets-failure");
}

export async function run(ctx) {
  await runResolved(ctx);
  await runRepeat(ctx);
  await runMultiTarget(ctx);
  await runMentionOnly(ctx);
  await runUncertain(ctx);
  await runLate(ctx);
  await runFailure(ctx);
  await runTargetsFailure(ctx);
  await runKeyboard(ctx);
  await runTouch(ctx);
  await runReducedMotion(ctx);
}
