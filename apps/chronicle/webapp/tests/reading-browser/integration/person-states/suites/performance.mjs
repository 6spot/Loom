// C2-R3-T14 integrated person-region performance suite.
//
// Measures the person/place context region update on the real published
// HistoryPage: after the data is already retrieved, switching the active
// paragraph must repaint the reviewed state within the contract budget, and no
// main-thread long task may reach the ceiling. This complements the R2 scale
// suite (which measures 5,000-unit continuous reading) with the R3
// person-region budget.

import { historyUrl } from "../manifest.mjs";

export const TASK = "C2-R3-T14";
const RUNS = 5;

export async function run(ctx) {
  const { baseUrl, manifest, runner } = ctx;
  const history = manifest.history;
  const budgets = manifest.budgets;
  const page = await runner.newPage({ viewport: { width: 1440, height: 900 } });
  await page.addInitScript(() => {
    window.__r3LongTasks = [];
    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) window.__r3LongTasks.push(entry.duration);
      }).observe({ entryTypes: ["longtask"] });
    } catch {
      /* longtask unsupported: treated as no observed long task */
    }
  });
  await page.goto(historyUrl(baseUrl, history), { waitUntil: "domcontentloaded" });
  await page.waitForSelector(`.history-paragraph[data-unit-id="${history.paragraph_id}"]`, {
    timeout: 30000,
  });
  await page.waitForSelector('[data-test="history-phase-status"][data-status="ready"]', {
    state: "attached",
    timeout: 30000,
  });

  const axes = page.locator(".history-axis [data-axis-target]:visible");
  const axisCount = await axes.count();
  runner.check("history_axis_present", axisCount >= 1, "no axis entries");

  const samples = [];
  for (let run = 0; run < RUNS; run += 1) {
    const target = axes.nth(run % axisCount);
    const started = Date.now();
    await target.click();
    await page.waitForFunction(
      () => {
        const node = document.querySelector('[data-test="history-phase-status"]');
        return Boolean(node) && node.getAttribute("data-status") === "ready";
      },
      undefined,
      { timeout: 10000 },
    );
    samples.push(Date.now() - started);
  }
  const sorted = [...samples].sort((a, b) => a - b);
  const p95 = sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1)];
  runner.info("person_region_samples_ms", samples);
  runner.info("person_region_p95_ms", p95);
  runner.check(
    "person_region_p95_within_budget",
    p95 <= budgets.person_region_p95_ms,
    `p95=${p95}ms > ${budgets.person_region_p95_ms}ms`,
  );

  const longTasks = await page.evaluate(() => window.__r3LongTasks || []);
  const maxLongTask = longTasks.length ? Math.max(...longTasks) : 0;
  runner.info("long_task_count", longTasks.length);
  runner.info("max_long_task_ms", maxLongTask);
  runner.check(
    "no_long_task_over_budget",
    maxLongTask < budgets.max_long_task_ms,
    `max long task ${maxLongTask}ms >= ${budgets.max_long_task_ms}ms`,
  );

  // The context panel must stay bounded: never one element per person.
  const mounted = await page.locator('[data-test="reading-context-entity"]').count();
  runner.info("context_entities_mounted", mounted);
  runner.check("context_entities_bounded", mounted <= budgets.mounted_max_units, `${mounted}`);
}
