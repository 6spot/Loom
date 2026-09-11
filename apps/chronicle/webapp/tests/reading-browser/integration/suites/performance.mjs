// C2-R2-T16 performance suite: fixed Chromium/viewport, real stack.
//
// The acceptance requires the active-update and restore budgets to be measured
// in a fixed environment across five runs, with the per-run and aggregate p95
// recorded. A missing scale stream fails the suite; budgets are never widened.

import { budgets, readingUrl } from "../manifest.mjs";
import { p95 } from "../runner.mjs";

const UNIT = '[data-test="reading-unit"]';
const RUNS = 5;
const ACTIVE_SAMPLES_PER_RUN = 15;
const FIXED_VIEWPORT = { width: 1440, height: 900 };

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

async function measureActiveUpdates(page, iterations) {
  const samples = [];
  const timeouts = [];
  for (let index = 0; index < iterations; index += 1) {
    const before = await activeUnitOrdinal(page);
    const start = Date.now();
    await page.mouse.wheel(0, 900);
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
      samples.push(Date.now() - start);
    } catch {
      timeouts.push(index);
    }
    await page.waitForTimeout(60);
  }
  return { samples, timeouts };
}

async function waitForUnit(page, unitId, timeout = 30000) {
  await page.waitForFunction(
    (wanted) =>
      Array.from(document.querySelectorAll('[data-test="reading-unit"]')).some(
        (unit) => unit.getAttribute("data-unit-id") === wanted,
      ),
    unitId,
    { timeout },
  );
}

async function runOnce(runner, baseUrl, scaleStream) {
  const page = await runner.newPage({ viewport: FIXED_VIEWPORT });
  try {
    await page.goto(readingUrl(baseUrl, scaleStream), { waitUntil: "domcontentloaded" });
    await page.waitForSelector(UNIT, { timeout: 30000 });
    const mounted = await page.locator(UNIT).count();
    await installProbes(page);
    const { samples, timeouts } = await measureActiveUpdates(
      page,
      ACTIVE_SAMPLES_PER_RUN,
    );
    // Warm the locate/page data, then measure restore to the last unit.
    await page.goto(readingUrl(baseUrl, scaleStream, scaleStream.last_unit_id), {
      waitUntil: "domcontentloaded",
    });
    await waitForUnit(page, scaleStream.last_unit_id);
    await page.goto(readingUrl(baseUrl, scaleStream), { waitUntil: "domcontentloaded" });
    await page.waitForSelector(UNIT, { timeout: 30000 });
    const start = Date.now();
    await page.goto(readingUrl(baseUrl, scaleStream, scaleStream.last_unit_id), {
      waitUntil: "domcontentloaded",
    });
    await waitForUnit(page, scaleStream.last_unit_id);
    const restoreMs = Date.now() - start;
    const longTasks = await page.evaluate(() => window.__r2LongTasks || []);
    const previews = await page.evaluate(() => window.__r2PreviewRequests || 0);
    return { samples, timeouts, restoreMs, mounted, longTasks, previews };
  } finally {
    await runner.closePages();
  }
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
  const scaleStream = {
    stream_id: scale.stream_id,
    catalog_sha: scale.catalog_sha,
    last_unit_id: scale.last_unit_id,
  };
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

  const runs = [];
  const allActive = [];
  const allRestore = [];
  for (let index = 0; index < RUNS; index += 1) {
    const observed = await runOnce(runner, baseUrl, scaleStream);
    const activeP95 = p95(observed.samples);
    runs.push({
      run: index + 1,
      active_p95_ms: activeP95,
      active_samples_ms: observed.samples,
      active_timeouts: observed.timeouts,
      restore_ms: observed.restoreMs,
      mounted_units: observed.mounted,
    });
    runner.info(`run_${index + 1}`, runs[runs.length - 1]);
    if (observed.timeouts.length > 0) {
      runner.check(
        `run-${index + 1}-active-samples`,
        false,
        `active-update timeouts=${observed.timeouts.length}`,
      );
    }
    runner.check(
      `run-${index + 1}-active-p95-budget`,
      activeP95 !== null && activeP95 <= limits.active_to_sidebar_p95_ms,
      `run ${index + 1} active p95=${activeP95}ms > ${limits.active_to_sidebar_p95_ms}ms`,
    );
    runner.check(
      `run-${index + 1}-restore-budget`,
      observed.restoreMs <= limits.restore_p95_ms,
      `run ${index + 1} restore=${observed.restoreMs}ms > ${limits.restore_p95_ms}ms`,
    );
    allActive.push(...observed.samples);
    allRestore.push(observed.restoreMs);
    if (index === RUNS - 1) {
      const worstLongTask = observed.longTasks.length
        ? Math.max(...observed.longTasks)
        : 0;
      runner.check(
        "no-reading-long-task",
        worstLongTask < limits.max_long_task_ms,
        `long task ${worstLongTask}ms >= ${limits.max_long_task_ms}ms`,
      );
      runner.check(
        "no-preview-n-plus-one",
        observed.previews <= 2,
        `preview requests before interaction=${observed.previews}`,
      );
    }
  }

  const aggregateActiveP95 = p95(allActive);
  const aggregateRestoreP95 = p95(allRestore);
  runner.check("five-fixed-runs", runs.length === RUNS, `runs=${runs.length}`);
  runner.check(
    "aggregate-active-p95-budget",
    aggregateActiveP95 !== null && aggregateActiveP95 <= limits.active_to_sidebar_p95_ms,
    `aggregate active p95=${aggregateActiveP95}ms > ${limits.active_to_sidebar_p95_ms}ms`,
  );
  runner.check(
    "aggregate-restore-p95-budget",
    aggregateRestoreP95 !== null && aggregateRestoreP95 <= limits.restore_p95_ms,
    `aggregate restore p95=${aggregateRestoreP95}ms > ${limits.restore_p95_ms}ms`,
  );
  runner.info("environment", {
    browser: "chromium",
    viewport: `${FIXED_VIEWPORT.width}x${FIXED_VIEWPORT.height}`,
    runs: RUNS,
    active_samples_per_run: ACTIVE_SAMPLES_PER_RUN,
  });
  runner.info("runs", runs);
  runner.info("aggregate_active_p95_ms", aggregateActiveP95);
  runner.info("aggregate_restore_p95_ms", aggregateRestoreP95);
  return runner;
}
