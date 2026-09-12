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
const CONSECUTIVE_ADVANCES_PER_RUN = 1000;
const SCROLL_SECONDS = 30;
const FIXED_VIEWPORT = { width: 1440, height: 900 };

async function installProbes(page) {
  await page.evaluate(() => {
    window.__r2LongTasks = [];
    window.__r2PreviewRequests = 0;
    window.__r2ActiveToSidebar = [];
    window.__r2ViewMarker = Math.random().toString(36);
    let activeId = document.querySelector('[data-test="reading-unit"][data-active="true"]')?.dataset.unitId;
    let pending = null;
    const updates = new MutationObserver(() => {
      const id = document.querySelector('[data-test="reading-unit"][data-active="true"]')?.dataset.unitId;
      const now = performance.now();
      if (id && id !== activeId) {
        activeId = id;
        pending = { unit_id: id, start: now };
      }
      if (pending && document.querySelector('[data-test="reading-context-panel"]')?.dataset.unit === pending.unit_id) {
        window.__r2ActiveToSidebar.push({ unit_id: pending.unit_id, ms: now - pending.start });
        pending = null;
      }
    });
    updates.observe(document.body, { subtree: true, childList: true, attributes: true,
      attributeFilter: ["data-active", "data-unit"] });
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
    const cursor = await page.evaluate(() => window.__r2ActiveToSidebar.length);
    await page.mouse.wheel(0, 900);
    try {
      await page.waitForFunction(
        ({ previous, cursor }) => {
          const active = document.querySelector(
            '[data-test="reading-unit"][data-active="true"]',
          );
          const ordinal = active ? active.getAttribute("data-ordinal") : null;
          return ordinal !== null && ordinal !== previous &&
            document.querySelector('[data-test="reading-context-panel"]')?.dataset.unit === active.dataset.unitId &&
            window.__r2ActiveToSidebar.slice(cursor).some((sample) => sample.unit_id === active.dataset.unitId);
        },
        { previous: before, cursor },
        { timeout: 2000 },
      );
      samples.push(await page.evaluate(() => window.__r2ActiveToSidebar.at(-1).ms));
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
  const checkpoints = [];
  let checkpointAt = started;
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
    if (Date.now() >= checkpointAt) {
      checkpoints.push({ elapsed_ms: Date.now() - started, ordinal: state.active });
      checkpointAt = Date.now() + 5000;
    }
    await page.waitForTimeout(80);
  }
  const finalOrdinal = await activeUnitOrdinal(page);
  checkpoints.push({ elapsed_ms: Date.now() - started, ordinal: finalOrdinal === null ? null : Number(finalOrdinal) });
  return {
    duration_seconds: Math.round((Date.now() - started) / 1000),
    wheels,
    mounted_samples: mountedSamples.length,
    mounted_max: mountedSamples.length ? Math.max(...mountedSamples) : 0,
    mounted_min: mountedSamples.length ? Math.min(...mountedSamples) : 0,
    active_ordinal_min: ordinals.length ? Math.min(...ordinals) : null,
    active_ordinal_max: ordinals.length ? Math.max(...ordinals) : null,
    checkpoints,
  };
}

// Each step scrolls to the next real paragraph and waits for the production
// controller to select it. Counting ordinal distance alone would miss a reader
// that jumps ahead or stops loading after its first virtual window.
async function advanceConsecutiveUnits(page, count) {
  return await page.evaluate(async (wanted) => {
    const activeOrdinal = () => {
      const active = document.querySelector('[data-test="reading-unit"][data-active="true"]');
      return active ? Number(active.getAttribute("data-ordinal")) : null;
    };
    const frame = () => new Promise((resolve) => requestAnimationFrame(resolve));
    const started = performance.now();
    const first = activeOrdinal();
    let current = first;
    let completed = 0;
    let mountedMax = 0;
    let stalledAt = null;
    for (let index = 0; index < wanted; index += 1) {
      const nextOrdinal = current + 1;
      const deadline = performance.now() + 5000;
      let scrolled = false;
      while (performance.now() < deadline) {
        mountedMax = Math.max(mountedMax, document.querySelectorAll('[data-test="reading-unit"]').length);
        const next = document.querySelector(`[data-test="reading-unit"][data-ordinal="${nextOrdinal}"]`);
        if (next && !scrolled) {
          const header = document.querySelector(".site-header")?.getBoundingClientRect().height ?? 0;
          const compact = document.querySelector('[data-test="reading-compact-bar"]')?.getBoundingClientRect().height ?? 0;
          const reference = header + compact + (innerHeight - header - compact) * 0.3;
          const rect = next.getBoundingClientRect();
          window.scrollBy(0, rect.top + Math.min(20, rect.height / 2) - reference);
          scrolled = true;
        }
        if (scrolled && activeOrdinal() === nextOrdinal) break;
        await frame();
      }
      if (activeOrdinal() !== nextOrdinal) {
        stalledAt = { expected: nextOrdinal, active: activeOrdinal(), target_mounted: scrolled };
        break;
      }
      completed += 1;
      current = nextOrdinal;
    }
    return {
      requested_steps: wanted,
      completed_adjacent_steps: completed,
      first_ordinal: first,
      last_ordinal: current,
      mounted_max: mountedMax,
      duration_ms: Math.round(performance.now() - started),
      stalled_at: stalledAt,
    };
  }, count);
}

async function waitForUnit(page, unitId, relativeOffset = 0) {
  return await page.evaluate(async ({ wanted, relativeOffset }) => {
    const deadline = performance.now() + 30000;
    let previousTop = null;
    let stable = 0;
    let last = null;
    while (performance.now() < deadline) {
      const node = document.querySelector(`[data-test="reading-unit"][data-unit-id="${wanted}"]`);
      if (node) {
        const rect = node.getBoundingClientRect();
        const header = document.querySelector(".site-header")?.getBoundingClientRect().height ?? 0;
        const compact = document.querySelector('[data-test="reading-compact-bar"]')?.getBoundingClientRect().height ?? 0;
        const reference = header + compact + (innerHeight - header - compact) * 0.3;
        const targetScroll = Math.max(0, Math.min(document.documentElement.scrollHeight - innerHeight,
          scrollY + rect.top - reference + Math.max(rect.height * relativeOffset, Math.min(2, rect.height / 2))));
        last = { active: node.dataset.active === "true",
          context: document.querySelector('[data-test="reading-context-panel"]')?.dataset.unit === wanted,
          idle: document.querySelector('[data-test="reading-page"]')?.dataset.navigationState === "idle",
          position_error: Math.abs(scrollY - targetScroll), top: rect.top,
          visible: rect.bottom > header + compact && rect.top < innerHeight };
        if (last.active && last.context && last.idle && last.visible && last.position_error <= 3 &&
          document.fonts.status === "loaded" && previousTop !== null && Math.abs(rect.top - previousTop) <= 1) {
          stable += 1;
        } else stable = 0;
        previousTop = rect.top;
        if (stable >= 2) {
          const response = performance.getEntriesByType("resource").filter((entry) => {
            const url = new URL(entry.name);
            return url.pathname.endsWith("/locate") && url.searchParams.get("unit_id") === wanted;
          }).at(-1);
          if (!response) throw new Error(`missing real locate response timing for ${wanted}`);
          return { data_ready_ms: response.responseEnd, completed_ms: performance.now(), ...last };
        }
      }
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    throw new Error(`reading restore did not complete for ${wanted}: ${JSON.stringify(last)}`);
  }, { wanted: unitId, relativeOffset });
}

async function runOnce(runner, baseUrl, scaleStream) {
  const page = await runner.newPage({ viewport: FIXED_VIEWPORT });
  const requests = countRequests(page);
  try {
    await page.goto(readingUrl(baseUrl, scaleStream), { waitUntil: "domcontentloaded" });
    await page.waitForSelector(UNIT, { timeout: 30000 });
    await page.waitForSelector(`${UNIT}[data-active="true"]`, { timeout: 30000 });
    await installProbes(page);
    const firstUnitId = await page.locator(`${UNIT}[data-active="true"]`).getAttribute("data-unit-id");
    const consecutive = await advanceConsecutiveUnits(page, CONSECUTIVE_ADVANCES_PER_RUN);
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
      consecutive_advances: consecutive,
    };
    // Same-page navigation after long reading must remount an evicted target;
    // reloading the application would hide a locate -> waitForDom deadlock.
    await page.waitForTimeout(300);
    const returnPosition = await page.evaluate(() => {
      const active = document.querySelector('[data-test="reading-unit"][data-active="true"]');
      const rect = active.getBoundingClientRect();
      const chrome = (document.querySelector(".site-header")?.getBoundingClientRect().height ?? 0) +
        (document.querySelector('[data-test="reading-compact-bar"]')?.getBoundingClientRect().height ?? 0);
      return { unitId: active.dataset.unitId, marker: window.__r2ViewMarker,
        offset: Math.max(0, Math.min(1, (chrome + (innerHeight - chrome) * 0.3 - rect.top) / rect.height)) };
    });
    await page.locator('[data-test="reading-axis-group"]').first().click();
    await waitForUnit(page, firstUnitId);
    await page.goBack();
    await waitForUnit(page, returnPosition.unitId, returnPosition.offset);
    evidence.same_page_return = await page.evaluate((marker) => window.__r2ViewMarker === marker, returnPosition.marker);

    // Deep-link restore: start at the exact locate response's responseEnd
    // (it contains the page), finish only at stable, correctly placed content.
    await page.goto(readingUrl(baseUrl, scaleStream, scaleStream.last_unit_id), {
      waitUntil: "domcontentloaded",
    });
    await waitForUnit(page, scaleStream.last_unit_id);
    await page.goto(readingUrl(baseUrl, scaleStream), { waitUntil: "domcontentloaded" });
    await page.waitForSelector(UNIT, { timeout: 30000 });
    await page.goto(readingUrl(baseUrl, scaleStream, scaleStream.last_unit_id), {
      waitUntil: "domcontentloaded",
    });
    const restore = await waitForUnit(page, scaleStream.last_unit_id);
    evidence.restore_ms = restore.completed_ms - restore.data_ready_ms;
    evidence.restore_observation = restore;
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
      consecutive_advances: observed.consecutive_advances,
      same_page_return: observed.same_page_return,
      restore_observation: observed.restore_observation,
      long_tasks_ms: observed.long_tasks_ms,
      max_long_task_ms: observed.max_long_task_ms,
      request_counts: observed.request_counts,
      preview_requests: observed.preview_requests,
    };
    runs.push(run);
    runner.info(`run_${index + 1}`, run);

    runner.check(`run-${index + 1}-same-page-navigation-return`, observed.same_page_return,
      "long-reading navigation/return reloaded the page instead of restoring within its existing window");

    runner.check(
      `run-${index + 1}-1000-consecutive-advances`,
      observed.consecutive_advances.completed_adjacent_steps === CONSECUTIVE_ADVANCES_PER_RUN &&
        observed.consecutive_advances.stalled_at === null,
      `run ${index + 1} stopped before 1000 adjacent paragraph advances: ${JSON.stringify(observed.consecutive_advances)}`,
    );

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
      Math.max(observed.window_progression.mounted_max, observed.consecutive_advances.mounted_max) <= limits.mounted_max_units,
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
    const checkpoints = observed.window_progression.checkpoints;
    runner.check(
      `run-${index + 1}-sustained-scroll-progress`,
      checkpoints.length >= 7 && checkpoints.every((point, i) =>
        point.ordinal !== null && (i === 0 || point.ordinal > checkpoints[i - 1].ordinal)),
      `run ${index + 1} stopped advancing during the 30-second scroll: ${JSON.stringify(checkpoints)}`,
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
    consecutive_advances_per_run: CONSECUTIVE_ADVANCES_PER_RUN,
    continuous_scroll_seconds: SCROLL_SECONDS,
  });
  runner.info("runs", runs);
  runner.info("aggregate_active_p95_ms", aggregateActiveP95);
  runner.info("aggregate_restore_p95_ms", aggregateRestoreP95);
  return runner;
}
