// C2-R2-T14 当前片段人物/地点组件的独立浏览器 spec（仅测试使用）。
//
// 由 scripts/reading-component-smoke.mjs → tests/reading-browser/harness.mjs 调用；
// 只验证组件行为（真实 Chromium + mocked fixture），不冒充真实后端或真实模型。
// 组件任务拥有自己的 suite 文件，不改共享 driver。

export async function run(ctx) {
  const scenes = ctx.sceneNames();
  ctx.check("context suite 已注册场景", scenes.length > 0, `scenes=${JSON.stringify(scenes)}`);
  for (const required of ["active-unit", "event-roles", "compact-panel"]) {
    ctx.check(`场景 ${required} 已注册`, scenes.includes(required));
  }
  await activeUnitScene(ctx);
  await eventRoleScene(ctx);
  await compactPanelScene(ctx);
}

async function activeUnitScene(ctx) {
  const page = await ctx.openScene("active-unit");

  await page.waitForSelector('[data-test="reading-context-panel"]', { timeout: 15000 });
  ctx.check(
    "面板不使用整栏 aria-live",
    (await page.locator('[data-test="reading-context-panel"] [aria-live]').count()) === 0,
  );

  const peopleGroup = '[data-test="reading-context-group"][data-group="people"]';
  const placesGroup = '[data-test="reading-context-group"][data-group="places"]';
  const politiesGroup = '[data-test="reading-context-group"][data-group="polities"]';
  const othersGroup = '[data-test="reading-context-group"][data-group="others"]';

  ctx.check(
    "人物默认最多 6 位",
    (await page.locator(`${peopleGroup} [data-test="reading-context-entity"]`).count()) === 6,
  );
  ctx.check(
    "人物分组总数仍为 7",
    (await page.locator(`${peopleGroup} [data-test="reading-context-group-count"]`).innerText()).trim() === "7",
  );
  ctx.check(
    "地点默认最多 4 个",
    (await page.locator(`${placesGroup} [data-test="reading-context-entity"]`).count()) === 4,
  );
  ctx.check(
    "地点分组总数仍为 5",
    (await page.locator(`${placesGroup} [data-test="reading-context-group-count"]`).innerText()).trim() === "5",
  );
  ctx.check(
    "政权与军队不当作人物，单独成组",
    (await page.locator(`${politiesGroup} [data-test="reading-context-entity"]`).count()) === 2 &&
      (await page.locator(`${peopleGroup} [data-test="reading-context-entity"][data-kind="polity"]`).count()) === 0,
  );
  ctx.check(
    "其他对象单独成组",
    (await page.locator(`${othersGroup} [data-test="reading-context-entity"]`).count()) === 1,
  );

  const peopleNames = (
    await page.locator(`${peopleGroup} [data-test="reading-context-name"]`).allInnerTexts()
  ).map((name) => name.trim());
  ctx.check(
    "主要人物优先且保持出现顺序",
    peopleNames[0] === "周瑜" && peopleNames[1] === "劉備",
    `names=${JSON.stringify(peopleNames)}`,
  );

  const deduped = page.locator(
    '[data-test="reading-context-entity"][data-canonical="ent-zhouyu"]',
  );
  ctx.check(
    "同一 canonical ID 合并显示",
    (await deduped.count()) === 1 &&
      (await deduped.getAttribute("data-deduped")) === "true" &&
      (await deduped.getAttribute("data-entity-refs")) === "ref-zhouyu-a,ref-zhouyu-b",
  );
  ctx.check(
    "去重后保留各事件角色与来源",
    (await deduped.locator('[data-test="reading-context-role"]').count()) === 2 &&
      (await deduped.locator('[data-test="reading-context-view-source"]').count()) === 2,
  );

  const zhangfei = page.locator(
    '[data-test="reading-context-group"][data-group="people"] [data-test="reading-context-name"]',
    { hasText: "張飛" },
  );
  ctx.check("同名不同 ID 保持分开", (await zhangfei.count()) === 2, `count=${await zhangfei.count()}`);
  const zhangfeiIds = await page
    .locator('[data-test="reading-context-entity"]')
    .evaluateAll((nodes) =>
      nodes
        .filter((node) => node.querySelector('[data-test="reading-context-name"]')?.textContent?.trim() === "張飛")
        .map((node) => node.getAttribute("data-canonical")),
    );
  ctx.check(
    "同名人物分别保留各自 canonical ID",
    zhangfeiIds.length === 2 && new Set(zhangfeiIds).size === 2,
    JSON.stringify(zhangfeiIds),
  );

  ctx.check(
    "地点分组带不产生人物位置断言的说明",
    (await page.locator('[data-test="reading-context-place-note"]').count()) === 1,
  );

  await deduped.locator('[data-test="reading-context-view-entity"]').click();
  ctx.check(
    "查看实体回调可操作",
    (await page.locator('[data-test="context-last-action"]').innerText()).trim() === "entity:ent-zhouyu",
  );
  await deduped.locator('[data-test="reading-context-view-source"]').first().click();
  ctx.check(
    "查看来源回调可操作",
    (await page.locator('[data-test="context-last-action"]').innerText()).trim() === "source:anc-zhouyu-a",
  );

  await page.locator(`${peopleGroup} [data-test="reading-context-expand"]`).click();
  ctx.check(
    "展开后显示全部人物",
    (await page.locator(`${peopleGroup} [data-test="reading-context-entity"]`).count()) === 7,
  );

  await page.locator('[data-test="context-unit-b"]').click();
  await page.waitForSelector('[data-test="reading-context-empty"]', { timeout: 10000 });
  ctx.check(
    "空段清空而非沿用上一段",
    (await page.locator('[data-test="reading-context-entity"]').count()) === 0,
  );

  await page.locator('[data-test="context-unit-a"]').click();
  await page.waitForSelector(`${peopleGroup} [data-test="reading-context-entity"]`, { timeout: 10000 });
  ctx.check(
    "回读前段恢复本段人物地点",
    (await page.locator(`${peopleGroup} [data-test="reading-context-entity"]`).count()) === 6 &&
      (await page.locator('[data-test="reading-context-entity"][data-canonical="ent-zhouyu"]').count()) === 1,
  );

  await page.locator('[data-test="context-unit-c"]').click();
  await page.waitForSelector('[data-test="reading-context-entity"]', { timeout: 10000 });
  ctx.check(
    "原文支持但无 direct Claim 的对象仍显示",
    (await page
      .locator('[data-test="reading-context-entity"][data-canonical=""]')
      .filter({ hasText: "某將" })
      .count()) === 1,
  );
  ctx.check(
    "缺少来源时显式标注，不伪造依据",
    (await page
      .locator('[data-test="reading-context-entity"]', { hasText: "無據可考者" })
      .locator('[data-test="reading-context-no-source"]')
      .count()) === 1,
  );

  ctx.info("people_names", peopleNames);
  await ctx.screenshot(page, "active-unit");
  await page.close();
}

async function eventRoleScene(ctx) {
  const page = await ctx.openScene("event-roles");
  await page.waitForSelector('[data-test="reading-context-panel"]', { timeout: 15000 });

  const zhouyu = page.locator('[data-test="reading-context-entity"][data-canonical="ent-zhouyu"]');
  const roleKeys = await zhouyu
    .locator('[data-test="reading-context-role"]')
    .evaluateAll((nodes) =>
      nodes.map((node) => `${node.getAttribute("data-event")}:${node.getAttribute("data-role")}`),
    );
  ctx.check(
    "多个事件的不同角色全部保留",
    roleKeys.length === 3 &&
      roleKeys.includes("evt-jiangxia:前部大督") &&
      roleKeys.includes("evt-red-cliffs:督") &&
      roleKeys.includes("evt-nanjun:領軍"),
    JSON.stringify(roleKeys),
  );
  ctx.check(
    "事件角色文案明确限定于事件而非长期官职",
    (await page.locator('[data-test="reading-context-role-note"]').count()) === 1 &&
      (await zhouyu.locator('[data-test="reading-context-role"]').first().innerText()).includes("事件："),
  );

  const chibi = page.locator('[data-test="reading-context-entity"][data-canonical="ent-chibi"]');
  ctx.check(
    "地点的事件角色独立显示",
    (await chibi.locator('[data-test="reading-context-role"]').count()) === 1,
  );
  ctx.check(
    "地点分组不把人物位置当断言",
    (await page.locator('[data-test="reading-context-place-note"]').innerText()).includes("不代表人物所在位置"),
  );
  ctx.check(
    "无 canonical 的使者仍显示为人物且无来源按钮",
    (await page.locator('[data-test="reading-context-entity"]', { hasText: "使者" }).count()) === 1 &&
      (await page.locator('[data-test="reading-context-no-source"]').count()) === 1,
  );

  ctx.info("event_role_keys", roleKeys);
  await ctx.screenshot(page, "event-roles");
  await page.close();
}

async function compactPanelScene(ctx) {
  const page = await ctx.openScene("compact-panel", { viewport: { width: 390, height: 844 } });
  await page.waitForSelector('[data-test="reading-context-open"]', { timeout: 15000 });

  ctx.check(
    "窄屏入口初始不展开面板",
    (await page.locator('[data-test="reading-context-panel"]').count()) === 0,
  );

  await page.locator('[data-test="reading-context-open"]').click();
  await page.waitForSelector('[data-test="reading-context-panel"]', { timeout: 10000 });
  await page.waitForFunction(
    () => document.activeElement?.getAttribute("data-test") === "reading-context-close",
    undefined,
    { timeout: 5000 },
  );
  ctx.check("打开面板后焦点进入关闭按钮", true);
  const overflowOpen =
    await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  ctx.check("窄屏打开面板无横向溢出", overflowOpen <= 1, `overflow=${overflowOpen}`);

  await page.locator('[data-test="reading-context-close"]').click();
  await page.waitForFunction(
    () =>
      document.querySelector('[data-test="reading-context-panel"]') === null &&
      document.activeElement?.getAttribute("data-test") === "reading-context-open",
    undefined,
    { timeout: 5000 },
  );
  ctx.check("关闭面板并返回触发焦点", true);

  await ctx.screenshot(page, "compact-panel");
  await page.close();
}
