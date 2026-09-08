// T15 组件交互 harness：真实挂载 + 点击 + 键盘 + 重试 + 异步状态。
// 覆盖验收关键路径：目录分页与导航、单栏全文、按需原文（多引用/整章/续页）、
// 错误重试、快速切换隔离、Escape 关闭恢复焦点、恶意 HTML 不执行。
import { expect, test } from "@playwright/test";

const PAGE = "/tests/fixtures/chapter-reader/harness/index.html";
const PUB_A = "00000000-0000-7000-8000-000000000000";
const PUB_B = "11111111-1111-7000-8000-111111111111";
const ANCHOR = "anc_f00ff77e8922b3e5";

test("directory paginates with cursor and navigates into the full chapter", async ({ page }) => {
  await page.goto(PAGE);
  await expect(page.getByTestId("chapter-index")).toBeVisible();
  // 第一页只有第一章 + 读下一页按钮
  await expect(page.getByTestId("chapter-index-row")).toHaveCount(1);
  await expect(page.getByTestId("chapter-index-more-button")).toBeVisible();
  await page.getByTestId("chapter-index-more-button").click();
  // 第二页追加后共两条，分页结束
  await expect(page.getByTestId("chapter-index-row")).toHaveCount(2);
  await expect(page.getByTestId("chapter-index-end")).toBeVisible();
  // 目录 → 单栏完整白话：点击第一章进入
  await page.getByTestId("chapter-index-open").first().click();
  const reader = page.getByTestId("chapter-reader");
  await expect(reader).toBeVisible();
  await expect(reader).toHaveAttribute("data-publication", PUB_A);
  await expect(reader).toHaveAttribute("data-blocks", "2");
  await expect(page.getByTestId("chapter-paragraph")).toHaveCount(2);
  // 无引用段同样展示
  await expect(reader).toContainText("其人聽聞後君王下令退兵。");
  // 默认无逐句双栏
  await expect(page.locator(".chr-dual, .two-column")).toHaveCount(0);
});

test("on-demand source: open, expand to chapter, paginate, escape-close restores focus", async ({ page }) => {
  await page.goto(`${PAGE}?dir=all`);
  await page.getByTestId("chapter-index-open").first().click();
  const openButton = page.getByTestId("chapter-source-open").first();
  await expect(openButton).toBeVisible();
  await openButton.click();
  const panel = page.getByTestId("chapter-source-panel");
  await expect(panel).toBeVisible();
  await expect(panel).toHaveAttribute("data-anchor", ANCHOR);
  await expect(panel).toHaveAttribute("data-view", "window");
  await expect(page.getByTestId("chapter-source-segments")).toContainText("曹操屯江陵");
  // 打开面板时关闭按钮获得焦点（键盘可达）
  await expect(page.getByTestId("chapter-source-close")).toBeFocused();
  // 展开整章 + 续页
  await page.getByTestId("chapter-source-view-chapter").click();
  await expect(panel).toHaveAttribute("data-view", "chapter");
  await page.getByTestId("chapter-source-more").click();
  await expect(panel).toContainText("王命退兵");
  await expect(page.getByTestId("chapter-source-end")).toBeVisible();
  // Escape 关闭：面板消失，焦点回到触发按钮
  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(page.getByTestId("chapter-source-open").first()).toBeFocused();
});

test("source failure keeps chapter text and retry recovers", async ({ page }) => {
  await page.goto(`${PAGE}?failSourceFirst=1`);
  await page.getByTestId("chapter-index-open").first().click();
  await page.getByTestId("chapter-source-open").first().click();
  await expect(page.getByTestId("chapter-source-error")).toBeVisible();
  // 正文不受影响
  await expect(page.getByTestId("chapter-reader")).toContainText("周瑜在赤壁擊敗曹操");
  await page.getByTestId("chapter-source-retry").click();
  await expect(page.getByTestId("chapter-source-segments")).toContainText("曹操屯江陵");
});

test("chapter failure shows retry and recovers without losing the directory", async ({ page }) => {
  await page.goto(`${PAGE}?failChapterOnce=1`);
  await page.getByTestId("chapter-index-open").first().click();
  await expect(page.getByTestId("chapter-error")).toBeVisible();
  await page.getByTestId("chapter-retry").click();
  await expect(page.getByTestId("chapter-reader")).toBeVisible();
  await expect(page.getByTestId("chapter-reader")).toHaveAttribute("data-publication", PUB_A);
});

test("fast switch between publications never shows stale content", async ({ page }) => {
  await page.goto(`${PAGE}?slowDetailMs=400&slowSourceMs=400`);
  await page.getByTestId("chapter-index-more-button").click();
  await expect(page.getByTestId("chapter-index-row")).toHaveCount(2);
  // 先点第一章（慢响应在途），立刻回目录再进第二章：旧响应不得覆盖新视图
  await page.getByTestId("chapter-index-open").nth(0).click();
  await page.getByTestId("chapter-back").click();
  await page.getByTestId("chapter-index-more-button").click();
  await expect(page.getByTestId("chapter-index-row")).toHaveCount(2);
  await page.getByTestId("chapter-index-open").nth(1).click();
  const reader = page.getByTestId("chapter-reader");
  await expect(reader).toBeVisible({ timeout: 15000 });
  await expect(reader).toHaveAttribute("data-publication", PUB_B);
  await expect(reader).toContainText("第二章白话正文第一段");
  await expect(reader).not.toContainText("周瑜在赤壁擊敗曹操");
  // 同章内快速切换两个引用：面板最终只呈现第二个 anchor
  await page.getByTestId("chapter-back").click();
  await page.getByTestId("chapter-index-open").first().click();
  await expect(page.getByTestId("chapter-reader")).toBeVisible({ timeout: 15000 });
  const anchorButtons = page.getByTestId("chapter-source-open");
  await anchorButtons.nth(0).click();
  await anchorButtons.nth(1).click();
  const panel = page.getByTestId("chapter-source-panel");
  await expect(panel).toBeVisible({ timeout: 15000 });
  await expect(panel).toHaveAttribute("data-anchor", "anc_58d6842876db1d38");
  await expect(page.getByTestId("chapter-source-segments")).toBeVisible({ timeout: 15000 });
});

test("malicious source html renders as inert text and never executes", async ({ page }) => {
  await page.goto(`${PAGE}?panel=security`);
  const panel = page.getByTestId("chapter-source-panel");
  await expect(panel).toBeVisible();
  await expect(page.getByTestId("chapter-source-segments")).toContainText("曹操屯江陵");
  const result = await page.evaluate(() => ({
    scripts: document.querySelectorAll("#root script").length,
    imgs: document.querySelectorAll("#root img").length,
    pwned: (window as unknown as Record<string, unknown>).__pwned,
    escaped: document.querySelector("[data-test='chapter-source-segments']")?.textContent?.includes("<img") ?? false,
  }));
  expect(result.scripts).toBe(0);
  expect(result.imgs).toBe(0);
  expect(result.pwned).toBeUndefined();
  expect(result.escaped).toBe(true);
});
