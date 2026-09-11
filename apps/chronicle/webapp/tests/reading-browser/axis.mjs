// C2-R2-T11 侧边阅读时间轴浏览器 suite 规格（仅测试使用）。
//
// 由 tests/fixtures/reading/cases/axis/scene.tsx 提供合成 published-DTO 场景，
// 主 harness 通过 scripts/reading-component-smoke.mjs --suite axis 调用本文件的 run(ctx)。
// 真实浏览器只证明组件行为，不证明真实后端/译文/事件对应正确。

const HIERARCHY_GROUP = '[data-test="reading-axis-group"]';
const YEAR_HEADER = '[data-test="reading-axis-year"]';
const PERIOD = '[data-test="reading-axis-period"]';
const LAST_NAV = '[data-test="reading-axis-last-nav"]';
const STREAM = "0192f0a0-0000-7000-8000-00000000aa01";
const CATALOG = "4c29947197b9be1907082482c45d724a4dd4216a9db18f9f6ba55b9085597401";

function unitId(ordinal) {
  return `ru_${(ordinal * 10 + 1).toString(16).padStart(24, "0")}`;
}

async function textContents(locator) {
  return await locator.allTextContents();
}

async function runHierarchy(ctx) {
  const page = await ctx.openScene("axis-hierarchy", { viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.waitForSelector('[data-test="reading-time-axis"]');

  const years = await textContents(page.locator(YEAR_HEADER));
  ctx.check(
    "同年共享年标题、换年才新增",
    JSON.stringify(years) === JSON.stringify(["建安十三年", "建安14年"]),
    `实际=${JSON.stringify(years)}`,
  );

  const periods = await textContents(page.locator(PERIOD));
  ctx.check(
    "月标记逐区段出现且未知不继承",
    JSON.stringify(periods) === JSON.stringify(["史料八月", "史料九月", "（月份未明确）", "时间未明确"]),
    `实际=${JSON.stringify(periods)}`,
  );

  const unknown = page.locator(`${HIERARCHY_GROUP}[data-unknown="true"]`);
  ctx.check("未知区段只有一个独立条目", (await unknown.count()) === 1);
  ctx.check("未知区段精度为 unknown", (await unknown.getAttribute("data-precision")) === "unknown");
  ctx.check(
    "未知区段不重印年标题",
    (await unknown.locator("xpath=ancestor::li").locator(YEAR_HEADER).count()) === 0,
  );

  ctx.check(
    "active 区段被标记",
    (await page.locator(`${HIERARCHY_GROUP}[data-active="true"]`).getAttribute("data-group-id")) === "tg_axis_h1",
  );

  const count = await page.locator(`${HIERARCHY_GROUP}[data-group-id="tg_axis_h0"] [data-test="reading-axis-count"]`).textContent();
  ctx.check("一组多段共用轴体并显示段数", (count || "").includes("2"), `实际=${count}`);

  await page.locator(`${HIERARCHY_GROUP}[data-group-id="tg_axis_h0"]`).click();
  const nav = page.locator(LAST_NAV);
  ctx.check("点击发出精确 unit locator", (await nav.getAttribute("data-unit")) === unitId(0));
  ctx.check(
    "locator 含 stream 与 catalog",
    (await nav.getAttribute("data-stream")) === STREAM && (await nav.getAttribute("data-catalog")) === CATALOG,
  );
  ctx.check("locator 不是年份", !(await nav.getAttribute("data-unit")).includes("13"));

  ctx.check("无未捕获页面异常", pageErrors.length === 0, pageErrors.join("; "));
  ctx.info("hierarchy_year_headers", years);
  ctx.info("hierarchy_periods", periods);
  await ctx.screenshot(page, "hierarchy");
}

async function runCalendars(ctx) {
  const page = await ctx.openScene("axis-calendars", { viewport: { width: 1440, height: 900 } });
  await page.waitForSelector('[data-test="reading-time-axis"]');

  const sourcePeriod = await page
    .locator(`${HIERARCHY_GROUP}[data-basis="source"] ${PERIOD}`)
    .first()
    .textContent();
  const gregorianPeriod = await page
    .locator(`${HIERARCHY_GROUP}[data-basis="gregorian"] ${PERIOD}`)
    .first()
    .textContent();
  ctx.check("史料历月使用来源标签", sourcePeriod === "史料八月", `实际=${sourcePeriod}`);
  ctx.check("公历月使用公历标签", gregorianPeriod === "公元208年8月", `实际=${gregorianPeriod}`);

  const axisText = await page.locator('[data-test="reading-time-axis"]').innerText();
  ctx.check("传统八月不显示为公历八月", !axisText.includes("公历八月"), axisText);

  const precisionOf = async (id) =>
    await page.locator(`${HIERARCHY_GROUP}[data-group-id="${id}"] [data-test="reading-axis-precision"]`).textContent();
  ctx.check("近似精度固定标签", (await precisionOf("tg_axis_c2")) === "近似");
  ctx.check("年段精度固定标签", (await precisionOf("tg_axis_c3")) === "年段");
  ctx.check("多源分歧固定标签", (await precisionOf("tg_axis_c4")) === "多源");

  const leap = page.locator(`${HIERARCHY_GROUP}[data-group-id="tg_axis_c5"]`);
  ctx.check("闰月为独立区段", (await leap.count()) === 1);
  const leapPeriod = await leap.locator(PERIOD).textContent();
  ctx.check("闰月保留原始历法标签", (leapPeriod || "").includes("閏八月"), `实际=${leapPeriod}`);
  ctx.check("闰月不与普通八月合并", (await page.locator(PERIOD).count()) === 6);

  ctx.info("source_period", sourcePeriod);
  ctx.info("gregorian_period", gregorianPeriod);
  await ctx.screenshot(page, "calendars");
}

async function runRetrograde(ctx) {
  const page = await ctx.openScene("axis-retrograde", { viewport: { width: 1440, height: 900 } });
  await page.waitForSelector('[data-test="reading-time-axis"]');

  const ids = await page
    .locator(HIERARCHY_GROUP)
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-group-id")));
  ctx.check(
    "叙事顺序未被按年份重排",
    JSON.stringify(ids) === JSON.stringify(["tg_axis_r0", "tg_axis_r1", "tg_axis_r2", "tg_axis_r3"]),
    `实际=${JSON.stringify(ids)}`,
  );

  const retro = await page
    .locator(`${HIERARCHY_GROUP}[data-retrospective="true"]`)
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-group-id")));
  ctx.check(
    "回退年份被标记为倒叙",
    JSON.stringify(retro) === JSON.stringify(["tg_axis_r1", "tg_axis_r3"]),
    `实际=${JSON.stringify(retro)}`,
  );
  ctx.check("未知区段不误标倒叙", (await page.locator(`${HIERARCHY_GROUP}[data-group-id="tg_axis_r2"]`).getAttribute("data-retrospective")) === "false");
  await ctx.screenshot(page, "retrograde");
}

async function runPagination(ctx) {
  const page = await ctx.openScene("axis-pagination", { viewport: { width: 1440, height: 900 } });
  await page.waitForSelector('[data-test="reading-time-axis"]');
  ctx.check("分页前只有第一页区段", (await page.locator(HIERARCHY_GROUP).count()) === 2);
  ctx.check("分页前年标题 1 个", (await page.locator(YEAR_HEADER).count()) === 1);
  ctx.check("存在有界分页入口", (await page.locator('[data-test="reading-axis-load-more"]').count()) === 1);

  await page.locator('[data-test="reading-axis-load-more"]').click();
  await page.waitForFunction(
    () => document.querySelectorAll('[data-test="reading-axis-group"]').length === 4,
  );

  ctx.check("分页后追加区段", (await page.locator(HIERARCHY_GROUP).count()) === 4);
  ctx.check("跨页同月只一个语义区段（年标题 2 个）", (await page.locator(YEAR_HEADER).count()) === 2);
  ctx.check("跨页同月显示为延续", (await page.locator('[data-test="reading-axis-continued"]').count()) === 1);
  ctx.check("onLoadGroups 调用一次", (await page.locator('[data-test="reading-axis-load-count"]').textContent()) === "1");
  ctx.check("加载完后分页入口消失", (await page.locator('[data-test="reading-axis-load-more"]').count()) === 0);
  await ctx.screenshot(page, "pagination");
}

async function runManyAndNarrow(ctx) {
  const page = await ctx.openScene("axis-many", { viewport: { width: 1440, height: 900 } });
  await page.waitForSelector('[data-test="reading-time-axis"]');
  ctx.check("1,000 个区段全部渲染", (await page.locator(HIERARCHY_GROUP).count()) === 1000);

  await page.setViewportSize({ width: 320, height: 568 });
  const overflowMany = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  ctx.check("长轴窄屏无横向溢出", overflowMany <= 1, `overflow=${overflowMany}`);
  ctx.info("many_group_overflow_320", overflowMany);
  await ctx.screenshot(page, "many-narrow");
}

async function runKeyboard(ctx) {
  const page = await ctx.openScene("axis-hierarchy", { viewport: { width: 390, height: 844 } });
  await page.waitForSelector('[data-test="reading-axis-toggle"]');
  ctx.check("窄屏出现轴入口", await page.locator('[data-test="reading-axis-toggle"]').isVisible());
  ctx.check("窄屏默认折叠", (await page.locator('[data-test="reading-axis-panel"]').getAttribute("data-open")) === "false");
  ctx.check("折叠时区段不可见", !(await page.locator(HIERARCHY_GROUP).first().isVisible()));

  await page.locator('[data-test="reading-axis-toggle"]').click();
  ctx.check("展开后面板可见", (await page.locator('[data-test="reading-axis-panel"]').getAttribute("data-open")) === "true");
  ctx.check("展开后区段可见", await page.locator(HIERARCHY_GROUP).first().isVisible());

  await page.keyboard.press("Escape");
  ctx.check("Escape 关闭面板", (await page.locator('[data-test="reading-axis-panel"]').getAttribute("data-open")) === "false");
  ctx.check(
    "Escape 返回焦点到入口",
    await page.evaluate(() => document.activeElement?.getAttribute("data-test") === "reading-axis-toggle"),
  );

  await page.locator('[data-test="reading-axis-toggle"]').click();
  await page.locator(HIERARCHY_GROUP).first().focus();
  await page.keyboard.press("ArrowDown");
  ctx.check(
    "方向键移动焦点",
    await page.evaluate(() => document.activeElement?.getAttribute("data-group-id") === "tg_axis_h1"),
  );
  await page.keyboard.press("Enter");
  await page.waitForTimeout(50);
  ctx.check("键盘选择发出精确 locator", (await page.locator(LAST_NAV).getAttribute("data-unit")) === unitId(1));
  await ctx.screenshot(page, "keyboard");
}

export async function run(ctx) {
  await runHierarchy(ctx);
  await runCalendars(ctx);
  await runRetrograde(ctx);
  await runPagination(ctx);
  await runManyAndNarrow(ctx);
  await runKeyboard(ctx);
}
