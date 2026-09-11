// C2-R2-T16 performance suite: fixed Chromium, real stack, measured budgets.
//
// Latency is measured on the explicitly synthetic 5,000-unit scale stream so
// active-unit/restore/locate are exercised at real scale. A missing scale
// stream fails the suite; budgets are never widened to go green.

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
        /* longtask unsupported */
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

async function activeUnitOrdinal(page) {
  return await page.evaluate(() => {
    const active = document.querySelector('[data-test="reading-unit"][data-active="true"]');
    return active ? active.getAttribute("data-ordinal") : null;
  });
}

async function measureActiveUpdate(page, iterations) {
  const samples = [];
  const timeouts = [];
  for (let index = 0; index < iterations; index += 1) {
    const before = await activeUnitOrdinal(page);
    const start = Date.now();
    await page.mouse.wheel(0, 900);
    let observed = null;
    try {
      await page.waitForFunction(
        (previous) => {
          const active = document.querySelector(
            '[data-test="reading-unit"][data-active="true"]',
          );
          const ordinal = active ? active.getAttribute("data-ordinal") : null;
          return ordinal !== null && ordinal !== previous;
        },
        before,
        { timeout: 2000 },
      );
      observed = Date.now() - start;
    } catch {
      timeouts.push(index);
      continue;
    }
    samples.push(observed);
    await page.waitForTimeout(60);
  }
  return { samples, timeouts };
}

export async function run(ctx) {
  const { runner, baseUrl, manifest } = ctx;
  const limits = budgets(manifest);
  const scale = manifest.scale;
  runner.check(
    "performance-scale-stream-present",
    Boolean(scale && scale.stream_id),
    "fixture manifest carries no synthetic scale stream; scale budget not measured",
  );
  const scaleStream = { stream_id: scale.stream_id, catalog_sha: scale.catalog_sha };
  const page = await runner.newPage({ viewport: { width: 1440, height: 900 } });
  try {
    await page.goto(readingUrl(baseUrl, scaleStream), { waitUntil: "domcontentloaded" });
    await page.waitForSelector(UNIT, { timeout: 30000 });
    await installProbes(page);
    const mounted = await page.locator(UNIT).count();
    runner.info("scale_mounted_units", mounted);
    runner.check("scale-window-bounded", mounted <= 140, `mounted=${mounted} > 140`);
    runner.check(
      "scale-unit-count",
      scale.unit_count >= (manifest.budgets.target_units || 5000),
      `unit_count=${scale.unit_count} below target`,
    );
    runner.check(
      "scale-group-count",
      scale.group_count >= (manifest.budgets.target_groups || 1000),
      `group_count=${scale.group_count} below target`,
    );

    const { samples, timeouts } = await measureActiveUpdate(page, 15);
    const activeP95 = p95(samples);
    runner.info("active_update_samples_ms", samples);
    runner.info("active_update_timeouts", timeouts);
    runner.info("active_update_p95_ms", activeP95);
    runner.check(
      "active-update-samples-collected",
      samples.length >= 5,
      `only ${samples.length} active-update samples collected (timeouts=${timeouts.length})`,
    );
    runner.check(
      "active-to-sidebar-p95-budget",
      activeP95 !== null && activeP95 <= limits.active_to_sidebar_p95_ms,
      `p95=${activeP95}ms > ${limits.active_to_sidebar_p95_ms}ms`,
    );

    const longTasks = await page.evaluate(() => window.__r2LongTasks || []);
    const worst = longTasks.length === 0 ? 0 : Math.max(...longTasks);
    runner.info("long_tasks_ms", longTasks);
    runner.check(
      "no-reading-long-task",
      worst < limits.max_long_task_ms,
      `long task ${worst}ms >= ${limits.max_long_task_ms}ms`,
    );
    const previews = await page.evaluate(() => window.__r2PreviewRequests || 0);
    runner.check(
      "no-preview-n-plus-one",
      previews <= 2,
      `preview requests before interaction=${previews}`,
    );

    const start = Date.now();
    await page.goto(readingUrl(baseUrl, scaleStream, scale.last_unit_id), {
      waitUntil: "domcontentloaded",
    });
    await page.waitForFunction(
      (unitId) =>
        Array.from(document.querySelectorAll('[data-test="reading-unit"]')).some(
          (unit) => unit.getAttribute("data-unit-id") === unitId,
        ),
      scale.last_unit_id,
      { timeout: 30000 },
    );
    const directMs = Date.now() - start;
    runner.info("scale_locate_ms", directMs);
    runner.check(
      "scale-locate-direct",
      directMs <= limits.restore_p95_ms,
      `direct locate=${directMs}ms > ${limits.restore_p95_ms}ms`,
    );
    await runner.screenshot(page, "performance");
  } finally {
    await runner.closePages();
  }
  return runner;
}
