#!/usr/bin/env node
// C2-R2-T02 阅读组件独立浏览器基座（仅测试使用，不接生产 App/dist）。
//
// 职责：
//  - 用受控 glob 发现 Vite fixture 页面注册的 scenes/*/scene.tsx；
//  - 内置 `harness` suite：真实 Chromium 打开 fixture 页面、操作、验证受控响应
//    与小尺寸布局，并证明缺失组件 suite 不会被静默跳过；
//  - 组件 suite（content/axis/position/events/context）由
//    tests/reading-browser/<suite>.mjs 提供 run(ctx)；缺失时显式失败，绝不假 PASS。
//
// 统一入口是 scripts/reading-component-smoke.mjs。

import { existsSync, mkdirSync } from "node:fs";
import { writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";
import os from "node:os";

export const SUITE_NAMES = ["harness", "content", "axis", "position", "events", "context"];
export const COMPONENT_SUITES = ["content", "axis", "position", "events", "context"];
export const BASE_SUITE = "harness";
export const FIXTURE_PATH = "/tests/fixtures/reading/index.html";
export const HARNESS_SCENE = "harness/base-reading-window";

// --- C2-R3-T01 third-round suites ----------------------------------------
// `r3-harness` is the D02 interaction harness reused as the third-round
// base; `person-states` / `person-state-review` are the T11/T12 component
// suites. `r3-all` requires every component suite to exist and pass, so a
// missing spec fails instead of silently passing.
export const R3_BASE_SUITE = "r3-harness";
export const R3_COMPONENT_SUITES = ["person-states", "person-state-review"];
export const R3_ALL_SUITE = "r3-all";
export const R3_SUITE_NAMES = [R3_BASE_SUITE, ...R3_COMPONENT_SUITES, R3_ALL_SUITE];

const HERE = dirname(fileURLToPath(import.meta.url));

export function fixtureUrl(baseUrl, params = {}) {
  const url = new URL(FIXTURE_PATH, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  return url.toString();
}

export async function readRegistry(page) {
  return await page.evaluate(() => {
    const registry = window.__READING_HARNESS__;
    return registry ?? null;
  });
}

class SuiteRunner {
  constructor(suite, outputDir) {
    this.suite = suite;
    this.outputDir = outputDir;
    this.checks = [];
    this.evidence = {};
    this.pages = [];
  }

  check(name, condition, detail = "") {
    const ok = Boolean(condition);
    this.checks.push({ name, ok, detail: ok ? "" : String(detail) });
    if (!ok) throw new Error(`reading ${this.suite} suite: FAIL: ${name}${detail ? ` (${detail})` : ""}`);
    return true;
  }

  info(name, value) {
    this.evidence[name] = value;
  }

  async newPage(options) {
    const page = await this.browser.newPage(options);
    this.pages.push(page);
    return page;
  }

  async screenshot(page, name) {
    if (!this.outputDir) return;
    mkdirSync(this.outputDir, { recursive: true });
    await page.screenshot({ path: join(this.outputDir, `${this.suite}-${name}.png`) });
  }

  async closePages() {
    for (const page of this.pages) {
      try {
        await page.close();
      } catch {
        /* already closed */
      }
    }
    this.pages = [];
  }
}

function summarizeRegistry(registry) {
  const summary = {};
  for (const suite of SUITE_NAMES) {
    const scenes = registry?.suites?.[suite]?.scenes ?? [];
    summary[suite] = scenes.map((scene) => `${scene.name}${scene.synthetic ? " (synthetic)" : ""}`);
  }
  return summary;
}

/**
 * 逐 unit 把渲染出的 segments 文本拼接起来，与该 unit 的 `data-text`（published DTO
 * 的 text 字段）逐字比较；返回不匹配项。这是 continuous-reading「拼接文本必须逐字
 * 等于原译文」的浏览器断言，禁止只检查非空。
 */
async function segmentTextMismatches(page) {
  return await page.$$eval('[data-test="reading-unit"]', (units) =>
    units
      .map((unit) => {
        const nodes = unit.querySelectorAll(
          '[data-test="reading-segment"], [data-test="reading-event-span"], [data-test="reading-event-span-uncertain"]',
        );
        const joined = Array.from(nodes)
          .map((node) => node.textContent || "")
          .join("");
        return {
          ordinal: unit.getAttribute("data-ordinal"),
          expected: unit.getAttribute("data-text") || "",
          joined,
        };
      })
      .filter((row) => row.joined !== row.expected),
  );
}

async function runBaseHarnessSuite(ctx) {
  const runner = new SuiteRunner(BASE_SUITE, ctx.outputDir);
  runner.browser = ctx.browser;
  const pageErrors = [];
  try {
    const page = await runner.newPage({ viewport: { width: 1280, height: 900 } });
    page.on("pageerror", (error) => pageErrors.push(String(error)));

    // 1. 注册表：fixture 页面是可发现来源，列出全部 suite（缺失的显式为 0 场景）。
    await page.goto(fixtureUrl(ctx.baseUrl), { waitUntil: "networkidle" });
    await page.waitForSelector('[data-test="reading-registry"]', { timeout: 15000 });
    const registry = await readRegistry(page);
    runner.check("registry-loaded", registry && registry.fixture === "reading");
    runner.check("registry-built-for-task", registry.builtFor === "C2-R2-T02");
    runner.check(
      "registry-lists-all-suites",
      SUITE_NAMES.every((suite) => Array.isArray(registry.suites?.[suite]?.scenes)),
    );
    runner.check("registry-has-base-scene", (registry.suites?.[BASE_SUITE]?.scenes?.length ?? 0) > 0);
    runner.check(
      "registry-base-scenes-synthetic",
      (registry.suites?.[BASE_SUITE]?.scenes ?? []).every((scene) => scene.synthetic === true),
      "harness scene must be explicitly synthetic",
    );
    runner.info("registry_suites", summarizeRegistry(registry));
    await runner.screenshot(page, "registry");

    // 2. 未知场景必须显式失败，不静默回退。
    await page.goto(fixtureUrl(ctx.baseUrl, { case: "harness/does-not-exist" }), {
      waitUntil: "domcontentloaded",
    });
    await page.waitForSelector('[data-test="reading-scene-missing"]', { timeout: 15000 });
    runner.check("unknown-scene-explicit-failure", true);

    // 3. 基座场景真实挂载，渲染 published DTO 形状（全部 synthetic）。
    await page.goto(fixtureUrl(ctx.baseUrl, { case: HARNESS_SCENE }), { waitUntil: "networkidle" });
    await page.waitForSelector('[data-test="reading-harness"]', { timeout: 15000 });
    runner.check("base-scene-mounts", true);
    runner.check("base-scene-labeled-synthetic", (await page.getAttribute('[data-test="reading-harness"]', "data-synthetic")) === "true");
    const unitCount = await page.locator('[data-test="reading-unit"]').count();
    runner.check("units-rendered", unitCount === 3, `expected 3 got ${unitCount}`);
    const groupCount = await page.locator('[data-test="reading-group"]').count();
    runner.check("time-groups-rendered", groupCount === 4, `expected 4 got ${groupCount}`);
    const contextCount = await page.locator('[data-test="reading-context-entity"]').count();
    runner.check("context-entities-rendered", contextCount > 0, "no context entities");
    const initialMismatches = await segmentTextMismatches(page);
    runner.check(
      "segments-reassemble-unit-text",
      initialMismatches.length === 0,
      `segment text must equal unit text: ${JSON.stringify(initialMismatches)}`,
    );
    runner.info("initial_units_checked", unitCount);
    runner.check(
      "event-span-statuses-present",
      (await page.locator('[data-test="reading-event-span"]').count()) >= 1 &&
        (await page.locator('[data-test="reading-event-span-uncertain"]').count()) >= 1,
      "expected both resolved and uncertain event spans",
    );

    // 4. 交互：点击段落更新 active unit。
    await page.locator('[data-test="reading-unit-activate"]').nth(1).click();
    runner.check(
      "active-unit-updates",
      (await page.getAttribute('[data-test="reading-active-unit"]', "data-ordinal")) === "1",
    );

    // 5. 受控失败：显式错误，已加载正文保留。
    const beforeLoad = await page.locator('[data-test="reading-unit"]').count();
    await page.locator('[data-test="reading-load-next-fail"]').click();
    await page.waitForSelector('[data-test="reading-load-error"]', { timeout: 10000 });
    runner.check("controlled-failure-explicit", true);
    runner.check("failure-keeps-loaded-units", (await page.locator('[data-test="reading-unit"]').count()) === beforeLoad);
    await runner.screenshot(page, "controlled-failure");

    // 6. 受控空白：显式空态，不伪造内容。
    await page.locator('[data-test="reading-load-next-blank"]').click();
    await page.waitForSelector('[data-test="reading-load-empty"]', { timeout: 10000 });
    runner.check("controlled-blank-explicit", true);
    runner.check("blank-adds-no-units", (await page.locator('[data-test="reading-unit"]').count()) === beforeLoad);

    // 7. 受控迟到：先 loading，后追加；重复成功页去重。
    await page.locator('[data-test="reading-load-next-late"]').click();
    await page.waitForSelector('[data-test="reading-loading"]', { timeout: 10000 });
    runner.check("controlled-late-loading-shown", true);
    await page.waitForFunction(
      (count) => document.querySelectorAll('[data-test="reading-unit"]').length > count,
      beforeLoad,
      { timeout: 10000 },
    );
    runner.check("controlled-late-resolves", true);
    runner.check("late-appended-units", (await page.locator('[data-test="reading-unit"]').count()) === beforeLoad + 2);
    await page.locator('[data-test="reading-load-next-ok"]').click();
    await page.waitForTimeout(150);
    runner.check("duplicate-page-deduped", (await page.locator('[data-test="reading-unit"]').count()) === beforeLoad + 2);
    const loadedMismatches = await segmentTextMismatches(page);
    runner.check(
      "segments-reassemble-unit-text-after-load",
      loadedMismatches.length === 0,
      `segment text must equal unit text: ${JSON.stringify(loadedMismatches)}`,
    );
    runner.info("loaded_units_checked", await page.locator('[data-test="reading-unit"]').count());

    // 8. 小尺寸布局：320x568 无横向溢出。
    await page.setViewportSize({ width: 320, height: 568 });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    runner.check("narrow-320-no-horizontal-overflow", overflow <= 1, `overflow=${overflow}`);
    await runner.screenshot(page, "narrow-320");

    // 9. 渲染安全：fixture 数据不产生 script/img。
    const injected = await page.evaluate(() => ({
      scripts: document.querySelectorAll("#root script").length,
      imgs: document.querySelectorAll("#root img").length,
    }));
    runner.check("no-injected-script-or-img", injected.scripts === 0 && injected.imgs === 0, JSON.stringify(injected));

    // 10. 真实 Chromium 无未捕获异常。
    runner.check("no-page-error", pageErrors.length === 0, pageErrors.join("; "));
  } finally {
    await runner.closePages();
  }
  return runner;
}

/**
 * 运行请求的 suite。返回 { ok, results }，其中每个 result 形如
 * { suite, ok, checks, evidence, error? }。缺失的组件 suite 记为失败
 * `suite_not_implemented` / `suite_no_scenes`，绝不假 PASS。
 */
export async function runReadingSuites({ baseUrl, suite = BASE_SUITE, outputDir = null }) {
  if (!baseUrl) throw new Error("reading harness: baseUrl is required");
  const validSuites = [...SUITE_NAMES, ...R3_SUITE_NAMES];
  if (suite !== "all" && !validSuites.includes(suite)) {
    throw new Error(
      `reading harness: unknown suite ${suite}; expected ${[...validSuites, "all"].join("|")}`,
    );
  }
  let requested;
  if (suite === "all") {
    requested = SUITE_NAMES.slice();
    for (const required of COMPONENT_SUITES) {
      if (!requested.includes(required)) requested.push(required);
    }
  } else if (suite === R3_ALL_SUITE) {
    // r3-all must fail if any third-round component spec is missing.
    requested = [R3_BASE_SUITE, ...R3_COMPONENT_SUITES];
  } else {
    requested = [suite];
  }

  const browser = await chromium.launch();
  const ctx = { baseUrl, outputDir, browser };
  const results = [];
  try {
    for (const name of requested) {
      let runner;
      try {
        if (name === BASE_SUITE) {
          runner = await runBaseHarnessSuite(ctx);
        } else if (name === R3_BASE_SUITE || R3_COMPONENT_SUITES.includes(name)) {
          runner = await runR3Suite(name, ctx);
        } else {
          runner = await runComponentSuite(name, ctx);
        }
        results.push({ suite: name, ok: true, checks: runner.checks, evidence: runner.evidence });
      } catch (error) {
        results.push({
          suite: name,
          ok: false,
          checks: runner ? runner.checks : [],
          evidence: runner ? runner.evidence : {},
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }
  } finally {
    await browser.close();
  }

  const ok = results.every((result) => result.ok);
  const isThirdRound = requested.some(
    (name) => name === R3_BASE_SUITE || R3_COMPONENT_SUITES.includes(name),
  );
  const payload = {
    schema: "chronicle.reading-component-harness",
    version: "0.1",
    task: isThirdRound ? "C2-R3-T01" : "C2-R2-T02",
    base_url: baseUrl,
    requested_suite: suite,
    ok,
    results,
  };
  if (outputDir) {
    mkdirSync(outputDir, { recursive: true });
    writeFileSync(join(outputDir, "result.json"), `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  }
  return payload;
}

/**
 * Run a third-round suite. `r3-harness` reuses the D02 interaction harness
 * (`tests/reading-browser/person-state-harness.mjs`); the component suites
 * are owned by T11/T12 and must provide their own `reading-browser/<name>.mjs`
 * exporting `run(ctx)`. A missing file fails explicitly.
 */
async function runR3Suite(name, ctx) {
  const runner = new SuiteRunner(name, ctx.outputDir);
  runner.browser = ctx.browser;
  const specPath = join(HERE, "person-state-harness.mjs");
  if (!existsSync(specPath)) {
    throw new Error(
      `reading ${name} suite: FAIL: suite_not_implemented: ${specPath} 不存在（第三轮基座由 T01/D02 交付）`,
    );
  }
  const spec = await import(pathToFileURL(specPath).href);
  if (typeof spec.run !== "function") {
    throw new Error(`reading ${name} suite: FAIL: ${specPath} 未导出 run(ctx)`);
  }
  const r3ctx = {
    baseUrl: ctx.baseUrl,
    outputDir: ctx.outputDir,
    browser: ctx.browser,
    runner,
    check: (label, condition, detail = "") => runner.check(label, condition, detail),
    info: (label, value) => runner.info(label, value),
    screenshot: (page, label) => runner.screenshot(page, label),
    openScene: async (target, options) => {
      const page = await runner.newPage(options ?? { viewport: { width: 1440, height: 900 } });
      if (name === R3_BASE_SUITE) {
        await page.goto(spec.fixtureUrl(ctx.baseUrl, { case: target }), { waitUntil: "networkidle" });
        return page;
      }
      const url = /^https?:/.test(target)
        ? target
        : new URL(
            target,
            ctx.baseUrl.endsWith("/") ? ctx.baseUrl : `${ctx.baseUrl}/`,
          ).toString();
      await page.goto(url, { waitUntil: "networkidle" });
      return page;
    },
  };
  if (name === R3_BASE_SUITE) {
    r3ctx.scene = "all";
    try {
      await spec.run(r3ctx);
    } finally {
      await runner.closePages();
    }
    return runner;
  }
  const componentPath = join(HERE, `${name}.mjs`);
  if (!existsSync(componentPath)) {
    throw new Error(
      `reading ${name} suite: FAIL: suite_not_implemented: ${componentPath} 不存在` +
        "（T11/T12 需新增自己的 reading-browser/" + name + ".mjs 与 scene/spec）",
    );
  }
  const component = await import(pathToFileURL(componentPath).href);
  if (typeof component.run !== "function") {
    throw new Error(`reading ${name} suite: FAIL: ${componentPath} 未导出 run(ctx)`);
  }
  try {
    await component.run(r3ctx);
  } finally {
    await runner.closePages();
  }
  return runner;
}

async function runComponentSuite(name, ctx) {
  const runner = new SuiteRunner(name, ctx.outputDir);
  runner.browser = ctx.browser;
  const specPath = join(HERE, `${name}.mjs`);
  if (!existsSync(specPath)) {
    throw new Error(
      `reading ${name} suite: FAIL: suite_not_implemented: ${specPath} 不存在（组件任务需新增自己的 reading-browser/${name}.mjs 与 cases/${name}/scene.tsx）`,
    );
  }

  // 先确认 fixture 页面已注册该 suite 的 scene；无 scene 无论如何都失败。
  const probe = await runner.newPage({ viewport: { width: 1280, height: 900 } });
  await probe.goto(fixtureUrl(ctx.baseUrl), { waitUntil: "networkidle" });
  await probe.waitForSelector('[data-test="reading-registry"]', { timeout: 15000 });
  const registry = await readRegistry(probe);
  await probe.close();
  const scenes = registry?.suites?.[name]?.scenes ?? [];
  runner.info("registered_scenes", scenes);
  if (scenes.length === 0) {
    throw new Error(
      `reading ${name} suite: FAIL: suite_no_scenes: cases/${name}/scene.tsx 未注册任何场景`,
    );
  }

  const specUrl = pathToFileURL(specPath).href;
  const spec = await import(specUrl);
  if (typeof spec.run !== "function") {
    throw new Error(`reading ${name} suite: FAIL: ${specPath} 未导出 run(ctx)`);
  }

  const componentCtx = {
    ...ctx,
    runner,
    check: (label, condition, detail = "") => runner.check(label, condition, detail),
    info: (label, value) => runner.info(label, value),
    sceneNames: () => scenes.map((scene) => scene.name),
    openScene: async (sceneName, options) => {
      const page = await runner.newPage(options ?? { viewport: { width: 1280, height: 900 } });
      await page.goto(fixtureUrl(ctx.baseUrl, { case: `${name}/${sceneName}` }), { waitUntil: "networkidle" });
      return page;
    },
    screenshot: (page, label) => runner.screenshot(page, label),
  };
  try {
    await spec.run(componentCtx);
  } finally {
    await runner.closePages();
  }
  return runner;
}

export function defaultOutputDir() {
  return join(os.tmpdir(), "chronicle-reading-component-harness");
}
