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

  // Curated anchors may contain just one entry (or none). Measure changes
  // between actual paragraphs, never repeat a no-op click on the same anchor.
  const response = await page.request.get(new URL(
    `/api/v1/public/history/paragraphs?version=${encodeURIComponent(history.version)}&at=${encodeURIComponent(history.paragraph_id)}`,
    baseUrl,
  ).toString());
  runner.check("history_paragraphs_loaded", response.ok(), `HTTP ${response.status()}`);
  const data = await response.json();
  const mountedIds = await page.locator("[data-history-paragraph]")
    .evaluateAll((nodes) => nodes.map((node) => node.dataset.unitId));
  const byPhase = new Map(data.paragraphs.filter((paragraph) => mountedIds.includes(paragraph.id)
    && paragraph.phase_id && paragraph.entities.length > 0).map((paragraph) => [paragraph.phase_id, paragraph]));
  const targets = [...byPhase.values()].slice(-2);
  runner.check("distinct_paragraph_targets", targets.length === 2
    && targets[0].id !== targets[1].id && targets[0].phase_id !== targets[1].phase_id,
  "performance fixture needs two loaded paragraphs from different phases");

  async function readParagraph(target, measured) {
    return page.evaluate(({ target, measured }) => {
      const panel = () => document.querySelector('[data-test="reading-context-panel"][data-variant="column"]');
      const from = panel()?.dataset.unit;
      if (measured && from === target.id) throw new Error("person-state performance sample must change paragraph");
      const paragraph = [...document.querySelectorAll("[data-history-paragraph]")]
        .find((node) => node.dataset.unitId === target.id);
      if (!paragraph) throw new Error("performance target paragraph is not mounted");
      const chrome = document.querySelector(".site-header").getBoundingClientRect().height
        + document.querySelector(".rpage-compact").getBoundingClientRect().height;
      const readingLine = chrome + (innerHeight - chrome) * 0.3;
      const started = performance.now();
      window.scrollBy({ top: paragraph.getBoundingClientRect().top - readingLine + 4, behavior: "instant" });
      return new Promise((resolve, reject) => {
        const check = () => {
          const phase = document.querySelector('[data-test="history-phase-status"]');
          if (panel()?.dataset.unit === target.id && phase?.dataset.status === "ready"
            && phase.dataset.phaseId === target.phase_id) {
            requestAnimationFrame(() => resolve({ from, paragraph_id: target.id, phase_id: target.phase_id,
              duration_ms: performance.now() - started }));
          } else if (performance.now() - started > 10000) {
            reject(new Error(`paragraph ${target.id} did not update its reviewed phase`));
          } else requestAnimationFrame(check);
        };
        requestAnimationFrame(check);
      });
    }, { target: { id: target.id, phase_id: target.phase_id }, measured });
  }

  // Warm both already-loaded contexts, ending at the second target so every
  // timed sample, including the first, switches paragraph and phase.
  for (const target of targets) await readParagraph(target, false);

  const samples = [];
  const transitions = [];
  for (let run = 0; run < RUNS; run += 1) {
    const transition = await readParagraph(targets[run % targets.length], true);
    transitions.push(transition);
    samples.push(transition.duration_ms);
  }
  runner.info("person_region_transitions", transitions);
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
