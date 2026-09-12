#!/usr/bin/env node
// C2-R2-T02 统一只读浏览器 driver（仅测试使用，不接生产路径、不改 dist）。
// C2-R3-T01 追加第三轮 suite：r3-harness|person-states|person-state-review|r3-all。
//
// 用法：
//   node apps/chronicle/webapp/scripts/reading-component-smoke.mjs \
//     --base-url http://127.0.0.1:5173 \
//     --suite harness|content|axis|position|events|context|all|r3-harness|person-states|person-state-review|r3-all \
//     --output /tmp/chronicle-r2-harness
//
// 需要已有 Vite 开发服务提供 fixture 页面（本 driver 不自起服务）。
// `--suite all` 只有五类组件 suite 均存在且通过才成功；缺失组件 suite 显式失败。
// `--suite r3-all` 只有第三轮基座与全部组件 suite 均存在且通过才成功；缺失显式失败。

import {
  defaultOutputDir,
  FIXTURE_PATH,
  R3_SUITE_NAMES,
  runReadingSuites,
  SUITE_NAMES,
} from "../tests/reading-browser/harness.mjs";

const args = process.argv.slice(2);
function flag(name) {
  const at = args.indexOf(name);
  return at >= 0 ? args[at + 1] : null;
}

const baseUrl = (flag("--base-url") || "").replace(/\/+$/, "");
const suite = flag("--suite") || "harness";
const output = flag("--output") || defaultOutputDir();

const validSuites = [...SUITE_NAMES, ...R3_SUITE_NAMES, "all"];
if (!baseUrl) {
  console.error("reading-component-smoke: FAIL: --base-url is required (running Vite fixture server)");
  process.exit(2);
}
if (!validSuites.includes(suite)) {
  console.error(`reading-component-smoke: FAIL: --suite must be ${validSuites.join("|")}`);
  process.exit(2);
}

async function assertFixtureServer() {
  const url = new URL(FIXTURE_PATH, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`).toString();
  let res;
  try {
    res = await fetch(url, { headers: { Accept: "text/html" } });
  } catch (error) {
    throw new Error(`fixture server unreachable at ${url}: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!res.ok) throw new Error(`fixture server ${url} returned ${res.status}`);
  const body = await res.text();
  if (!body.includes("tests/fixtures/reading/main.tsx") && !body.includes("main.tsx")) {
    throw new Error(`fixture server ${url} is not the reading fixture page`);
  }
}

async function main() {
  await assertFixtureServer();
  console.log(`reading-component-smoke: suite=${suite} base-url=${baseUrl} output=${output}`);
  const payload = await runReadingSuites({ baseUrl, suite, outputDir: output });

  for (const result of payload.results) {
    const status = result.ok ? "PASS" : "FAIL";
    console.log(`  [${status}] ${result.suite}`);
    for (const check of result.checks) {
      if (!check.ok) console.log(`      x ${check.name}: ${check.detail}`);
    }
    for (const [name, value] of Object.entries(result.evidence)) {
      console.log(`      . ${name}=${JSON.stringify(value)}`);
    }
    if (result.error) console.log(`      ! ${result.error}`);
  }

  if (!payload.ok) {
    const missing = payload.results.filter((result) => !result.ok && !result.error).map((r) => r.suite);
    if (missing.length > 0) console.log(`reading-component-smoke: failed suites: ${missing.join(", ")}`);
    console.error(`reading-component-smoke: FAIL (suite=${suite}); see ${output}/result.json`);
    process.exit(1);
  }
  console.log(`reading-component-smoke: PASS (suite=${suite}); evidence at ${output}/result.json`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
