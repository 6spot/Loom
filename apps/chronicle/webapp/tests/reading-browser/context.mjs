// Synthetic browser verification. This is not real historical content acceptance.
export async function run(ctx) {
  const page = await ctx.openScene("active-unit");
  const people = '[data-test="reading-context-group"][data-group="people"]';
  await page.waitForSelector('[data-test="reading-context-panel"]');
  ctx.check("默认只显示主要人物", (await page.locator(`${people} [data-test="reading-context-name"]`).allTextContents()).join(",") === "周瑜,劉備");
  const zhouyu = page.locator('[data-canonical="ent-zhouyu"]');
  ctx.check("同一身份只占一行并保留各来源引用", await zhouyu.count() === 1 && await zhouyu.getAttribute("data-entity-refs") === "ref-zhouyu-a,ref-zhouyu-b");
  ctx.check("无状态数据时明确缺失，不把事件角色当身份", (await zhouyu.innerText()).includes("当时身份尚未收录") && await page.locator('[data-test="reading-context-role"]').count() === 0);
  await zhouyu.locator('button').click();
  ctx.check("姓名进入对象详情", await page.locator('[data-test="context-last-action"]').innerText() === "entity:ent-zhouyu");
  await page.locator(`${people} [data-test="reading-context-expand"]`).click();
  ctx.check("次要人物仍可展开查看", await page.locator(`${people} [data-test="reading-context-entity"]`).count() === 7);
  ctx.check("同名不同身份不会合并", await page.locator(`${people} [data-test="reading-context-name"]`).filter({ hasText: "張飛" }).count() === 2);
  await page.locator('[data-test="reading-context-expand"][data-group="places"]').click();
  ctx.check("地点逐行独立且不猜测控制权", await page.locator('[data-group="places"] .chr-context-unknown').count() === 5);
  await page.locator('[data-test="context-unit-b"]').click();
  await page.waitForSelector('[data-test="reading-context-empty"]');
  ctx.check("无关联的新片段清空旧资料", await page.locator('[data-test="reading-context-entity"]').count() === 0);
  await page.locator('[data-test="context-unit-a"]').click();
  ctx.check("回读恢复当前段并重置次要项展开", await page.locator(`${people} [data-test="reading-context-entity"]`).count() === 2);
  await page.locator('[data-test="context-unit-c"]').click();
  await page.locator(`${people} [data-test="reading-context-expand"]`).click();
  const unlinked = page.locator('[data-test="reading-context-entity"]').filter({ hasText: "某將" });
  await unlinked.locator('summary').click();
  await unlinked.locator('[data-test="reading-context-view-source"]').click();
  ctx.check("未确认身份仍可查原文，来源不伪造", await page.locator('[data-test="context-last-action"]').innerText() === "source:anc-supported-only");
  const missing = page.locator('[data-test="reading-context-entity"]').filter({ hasText: "無據可考者" });
  ctx.check("没有依据就没有原文入口", await missing.locator('[data-test="reading-context-view-source"]').count() === 0);
  await ctx.screenshot(page, "active-unit");
  await page.close();

  const states = await ctx.openScene("event-roles");
  await states.waitForSelector('[data-test="reading-context-panel"]');
  ctx.check("参与角色不会推导为官职", !(await states.locator('[data-canonical="ent-zhouyu"]').innerText()).includes("前部大督"));
  await states.locator('[data-test="context-reviewed-state"]').click();
  ctx.check("只有已核对阶段资料可以展示身份", await states.locator('.chr-context-state').count() === 2);
  ctx.check("明确性逐项标记而非整个人物变灰", await states.locator('.chr-context-state[data-certainty="clear"]').count() === 1 && await states.locator('.chr-context-state[data-certainty="uncertain"]').count() === 1);
  ctx.check("存疑有文字提示，不只靠颜色", (await states.locator('.chr-context-state[data-certainty="uncertain"]').innerText()).includes("存疑"));
  await states.locator('[data-test="context-reviewed-state"]').click();
  ctx.check("切换资料时不沿用后来头衔", await states.locator('.chr-context-state').count() === 0);
  await ctx.screenshot(states, "state-facts");
  await states.close();

  for (const width of [390, 900]) {
    const compact = await ctx.openScene("compact-panel", { viewport: { width, height: 844 } });
    await compact.locator('[data-test="reading-context-open"]').click();
    await compact.waitForFunction(() => document.activeElement?.getAttribute("data-test") === "reading-context-close");
    ctx.check(`${width}px 面板有焦点约束`, await compact.locator('dialog:modal').count() === 1);
    ctx.check(`${width}px 无横向溢出`, await compact.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await compact.keyboard.press("Escape");
    await compact.waitForFunction(() => document.activeElement?.getAttribute("data-test") === "reading-context-open");
    ctx.check(`${width}px Escape 关闭并恢复焦点`, await compact.locator('dialog').count() === 0);
    await compact.close();
  }
}
