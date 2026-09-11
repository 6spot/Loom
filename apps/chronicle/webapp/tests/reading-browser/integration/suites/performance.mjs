// C2-R2-T16 performance suite: fixed Chromium, real stack, measured budgets.

import { budgets, readingUrl } from "../manifest.mjs";
import { p95 } from "../runner.mjs";

const UNIT = '[data-test="reading-unit"]';

async function installProbes(page) {
  await page.evaluate(() => {
    window.__r2LongTasks = [];
    window.__r2PreviewRequests = 0;
    if (typeof PerformanceObserver !== "undefined") {
      try {
        const observer = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) window.__r2LongTasks.push(entry.duration);
        });
        observer.observe({ entryTypes: ["longtask"] });
      } catch {
        /* longtask unsupported: recorded as unavailable */
      }
    }
  });
  page.on("request", (request) => {
    if (/\/api\/v1\/public\/reading-events\/[^/]+\/preview/.test(request.url())) {
      page.evaluate(() => {
        window.__r2PreviewRequests += 1;
      }).catch(() => {});
    }
  });
}

async function activeUpdateSamples(page) {
  return await page.evaluate(async () => {
    const samples = [];
    const units = Array.from(document.querySelectorAll('[data-test="reading-unit"]'));
    for (const unit of units.slice(0, 12)) {
      const ordinal = unit.getAttribute("data-ordinal");
      const start = performance.now();
      unit.scrollIntoView({ block: "center" });
      await new Promise((resolve) => {
        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          observer.disconnect();
          resolve();
        };
        const observer = new MutationObserver(() => {
          const active = document.querySelector('[data-test="reading-unit"][data-active="true"]');
          if (active && active.getAttribute("data-ordinal") === ordinal) finish();
        });
        observer.observe(document.body, {
          attributes: true,
          subtree: true,
          attributeFilter: ["data-active"],
        });
        setTimeout(finish, 2000);
      });
      samples.push(performance.now() - start);
    }
    return samples;
  });
}

async function windowRule(page) {
  const mounted = await page.locator(UNIT).count();
  const placeholders = await page.locator('[data-test="reading-unit-placeholder"]').count();
  return { mounted, placeholders };
}

export async function run(ctx) {
  const { runner, baseUrl, manifest } = ctx;
  const stream = manifest.streams[0];
  const limits = budgets(manifest);
  const page = await runner.newPage({ viewport: { width: 1440, height: 900 } });
  try {
    await page.goto(readingUrl(baseUrl, stream), { waitUntil: "domcontentloaded" });
    await page.waitForSelector(UNIT, { timeout: 30000 });
    await installProbes(page);

    const samples = await activeUpdateSamples(page);
    const activeP95 = p95(samples);
    runner.info("active_update_samples_ms", samples.map((value) => Number(value.toFixed(1))));
    runner.info("active_update_p95_ms", activeP95 === null ? null : Number(activeP95.toFixed(1)));
    runner.check("active-to-sidebar-measured", activeP95 !== null, "no active-update sample collected");
    runner.check(
      "active-to-sidebar-p95-budget",
      activeP95 <= limits.active_to_sidebar_p95_ms,
      `p95=${activeP95?.toFixed(1)}ms > ${limits.active_to_sidebar_p95_ms}ms`,
    );

    const rule = await windowRule(page);
    runner.info("mounted_units", rule.mounted);
    runner.check("mounted-units-bounded", rule.mounted <= 140, `mounted=${rule.mounted} > 140`);

    const longTasks = await page.evaluate(() => window.__r2LongTasks || []);
    const worst = longTasks.length === 0 ? 0 : Math.max(...longTasks);
    runner.info("long_tasks_ms", longTasks.map((value) => Number(value.toFixed(1))));
    runner.check(
      "no-reading-long-task",
      worst < limits.max_long_task_ms,
      `long task ${worst.toFixed(1)}ms >= ${limits.max_long_task_ms}ms`,
    );

    const previews = await page.evaluate(() => window.__r2PreviewRequests || 0);
    runner.check(
      "no-preview-n-plus-one",
      previews <= 2,
      `preview requests before interaction=${previews}`,
    );

    // Restore latency: deep link to a later published unit after data is warm.
    const target = await page.locator(UNIT).last().getAttribute("data-unit-id");
    const started = Date.now();
    await page.goto(readingUrl(baseUrl, stream, target), { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      (unitId) =>
        Array.from(document.querySelectorAll('[data-test="reading-unit"]')).some(
          (unit) => unit.getAttribute("data-unit-id") === unitId,
        ),
      target,
      { timeout: 30000 },
    );
    const restoreMs = Date.now() - started;
    runner.info("restore_ms", restoreMs);
    runner.check(
      "restore-latency-budget",
      restoreMs <= limits.restore_p95_ms,
      `restore=${restoreMs}ms > ${limits.restore_p95_ms}ms`,
    );

    // Scale budget: the synthetic 5,000-unit/1,000-group set must be present.
    const scale = manifest.performance && manifest.performance.stream;
    if (!scale) {
      runner.check(
        "performance-scale-stream-present",
        false,
        "fixture manifest carries no synthetic 5,000-unit/1,000-group stream; scale budget not measured",
      );
    } else {
      const scalePage = await runner.newPage({ viewport: { width: 1440, height: 900 } });
      try {
        await scalePage.goto(readingUrl(baseUrl, scale), { waitUntil: "domcontentloaded" });
        await scalePage.waitForSelector(UNIT, { timeout: 30000 });
        const mounted = await scalePage.locator(UNIT).count();
        runner.info("scale_mounted_units", mounted);
        runner.check("scale-window-bounded", mounted <= 140, `mounted=${mounted} > 140`);
        const lastId = scale.last_unit_id;
        if (lastId) {
          const start = Date.now();
          await scalePage.goto(readingUrl(baseUrl, scale, lastId), {
            waitUntil: "domcontentloaded",
          });
          await scalePage.waitForFunction(
            (unitId) =>
              Array.from(document.querySelectorAll('[data-test="reading-unit"]')).some(
                (unit) => unit.getAttribute("data-unit-id") === unitId,
              ),
            lastId,
            { timeout: 30000 },
          );
          const directMs = Date.now() - start;
          runner.info("scale_locate_ms", directMs);
          runner.check(
            "scale-locate-direct",
            directMs <= limits.restore_p95_ms,
            `direct locate=${directMs}ms > ${limits.restore_p95_ms}ms`,
          );
        }
      } finally {
        await scalePage.close();
      }
      runner.check(
        "scale-unit-count",
        scale.unit_count >= (manifest.performance.target_units || 5000),
        `unit_count=${scale.unit_count} below target`,
      );
      runner.check(
        "scale-group-count",
        scale.group_count >= (manifest.performance.target_groups || 1000),
        `group_count=${scale.group_count} below target`,
      );
    }
    await runner.screenshot(page, "performance");
  } finally {
    await runner.closePages();
  }
  return runner;
}
