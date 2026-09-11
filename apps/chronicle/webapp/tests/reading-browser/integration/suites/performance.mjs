// C2-R2-T16 performance suite: fixed Chromium/viewport, real stack.
//
// Acceptance requires the active-update and restore budgets to be measured in a
// fixed environment across five runs, and each run to include a real
// 30-second continuous scroll/window progression on the active page with Long
// Task and request-count evidence collected before any navigation. A mounted
// window budget is asserted on every run. A missing scale stream fails the
// suite; budgets are never widened.

import { budgets, readingUrl } from "../manifest.mjs";
import { p95 } from "../runner.mjs";

const UNIT = '[data-test="reading-unit"]';
const RUNS = 5;
const ACTIVE_SAMPLES_PER_RUN = 15;
const SCROLL_SECONDS = 30;
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
}

function countRequests(page) {
  const counts = { units: 0, groups: 0, locate: 0, preview: 0, other: 0 };
  page.on("request", (request) => {
    const url = request.url();
    if (!url.includes("/api/v1/public/reading-")) return;
    if (/\/reading-streams\/[^/]+\/units/.test(url)) counts.units += 1;
    else if (/\/reading-streams\/[^/]+\/groups/.test(url)) counts.groups += 1;
    else if (/\/reading-streams\/[^/]+\/locate/.test(url)) counts.locate += 1;
    else if (/\/reading-events\/[^/]+\/preview/.test(url)) counts.preview += 1;
    else counts.other += 1;
  });
  return counts;
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

async function continuousScroll(page, seconds) {
  const started = Date.now();
  const deadline = started + seconds * 1000;
  const mountedSamples = [];
  const ordinals = [];
  let wheels = 0;
  while (Date.now() < deadline) {
    await page.mouse.wheel(0, 1200);
    wheels += 1;
    const state = await page.evaluate(() => {
      const units = document.querySelectorAll('[data-test="reading-unit"]');
      const active = document.querySelector('[data-test="reading-unit"][data-active="true"]');
      return {
        mounted: units.length,
        active: active ? Number(active.getAttribute("data-ordinal")) : null,
      };
    });
    mountedSamples.push(state.mounted);
    if (state.active !== null && Number.isFinite(state.active)) ordinals.push(state.active);
    await page.waitForTimeout(80);
  }
  return {
    duration_seconds: Math.round((Date.now() - started) / 1000),
    wheels,
    mounted_samples: mountedSamples.length,
    mounted_max: mountedSamples.length ? Math.max(...mountedSamples) : 0,
    mounted_min: mountedSamples.length ? Math.min(...mountedSamples) : 0,
    active_ordinal_min: ordinals.length ? Math.min(...ordinals) : null,
    active_ordinal_max: ordinals.length ? Math.max(...ordinals) : null,
  };
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
  const requests = countRequests(page);
  try {
    await page.goto(readingUrl(baseUrl, scaleStream), { waitUntil: "domcontentloaded" });
    await page.waitForSelector(UNIT, { timeout: 30000 });
    await installProbes(page);
    const { samples, timeouts } = await measureActiveUpdates(
      page,
      ACTIVE_SAMPLES_PER_RUN,
    );
    const progression = await continuousScroll(page, SCROLL_SECONDS);
    // Collect active-page evidence before any navigation discards it.
    const longTasks = await page.evaluate(() => window.__r2LongTasks || []);
    const previewRequests = await page.evaluate(() => window.__r2PreviewRequests || 0);
    const mountedUnits = await page.locator(UNIT).count();
    const evidence = {
      active_samples_ms: samples,
      active_timeouts: timeouts,
      long_tasks_ms: longTasks,
      max_long_task_ms: longTasks.length ? Math.max(...longTasks) : 0,
      preview_requests: previewRequests,
      request_counts: { ...requests },
      mounted_units: mountedUnits,
      window_progression: progression,
    };
    // Restore latency (warms locate/page data, then measures restore).
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
    evidence.restore_ms = Date.now() - start;
    return evidence;
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
  const scaleStream = {
    stream_id: scale.stream_id,
    catalog_sha: scale.catalog_sha,
    last_unit_id: scale.last_unit_id,
  };

  const runs = [];
  const allActive = [];
  const allRestore = [];
  for (let index = 0; index < RUNS; index += 1) {
    const observed = await runOnce(runner, baseUrl, scaleStream);
    const activeP95 = p95(observed.active_samples_ms);
    const run = {
      run: index + 1,
      active_p95_ms: activeP95,
      active_samples_ms: observed.active_samples_ms,
      active_timeouts: observed.active_timeouts,
      restore_ms: observed.restore_ms,
      mounted_units: observed.mounted_units,
      window_progression: observed.window_progression,
      long_tasks_ms: observed.long_tasks_ms,
      max_long_task_ms: observed.max_long_task_ms,
      request_counts: observed.request_counts,
      preview_requests: observed.preview_requests,
    };
    runs.push(run);
    runner.info(`run_${index + 1}`, run);

    runner.check(
      `run-${index + 1}-active-samples`,
      observed.active_timeouts.length === 0,
      `active-update timeouts=${observed.active_timeouts.length}`,
    );
    runner.check(
      `run-${index + 1}-active-p95-budget`,
      activeP95 !== null && activeP95 <= limits.active_to_sidebar_p95_ms,
      `run ${index + 1} active p95=${activeP95}ms > ${limits.active_to_sidebar_p95_ms}ms`,
    );
    runner.check(
      `run-${index + 1}-restore-budget`,
      observed.restore_ms <= limits.restore_p95_ms,
      `run ${index + 1} restore=${observed.restore_ms}ms > ${limits.restore_p95_ms}ms`,
    );
    runner.check(
      `run-${index + 1}-mounted-window-budget`,
      observed.window_progression.mounted_max <= limits.mounted_max_units,
      `run ${index + 1} mounted window reached ${observed.window_progression.mounted_max} > ${limits.mounted_max_units}`,
    );
    runner.check(
      `run-${index + 1}-scroll-duration`,
      observed.window_progression.duration_seconds >= SCROLL_SECONDS,
      `run ${index + 1} continuous scroll only ${observed.window_progression.duration_seconds}s`,
    );
    runner.check(
      `run-${index + 1}-window-progressed`,
      observed.window_progression.active_ordinal_max !== null &&
        observed.window_progression.active_ordinal_min !== null &&
        observed.window_progression.active_ordinal_max > observed.window_progression.active_ordinal_min,
      `run ${index + 1} window did not advance: ${JSON.stringify(observed.window_progression)}`,
    );
    runner.check(
      `run-${index + 1}-long-task-budget`,
      observed.max_long_task_ms < limits.max_long_task_ms,
      `run ${index + 1} long task ${observed.max_long_task_ms}ms >= ${limits.max_long_task_ms}ms`,
    );
    runner.check(
      `run-${index + 1}-no-preview-n-plus-one`,
      observed.request_counts.preview === 0,
      `run ${index + 1} issued ${observed.request_counts.preview} preview requests without interaction`,
    );
    runner.check(
      `run-${index + 1}-units-requests-bounded`,
      observed.request_counts.units > 0 && observed.request_counts.units <= 1000,
      `run ${index + 1} units requests=${observed.request_counts.units}`,
    );
    allActive.push(...observed.active_samples_ms);
    allRestore.push(observed.restore_ms);
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
    continuous_scroll_seconds: SCROLL_SECONDS,
  });
  runner.info("runs", runs);
  runner.info("aggregate_active_p95_ms", aggregateActiveP95);
  runner.info("aggregate_restore_p95_ms", aggregateRestoreP95);
  return runner;
}
