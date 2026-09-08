import { defineConfig } from "@playwright/test";

// T15 组件交互 harness 配置：只跑本目录的 harness.spec.ts，
// 用 webapp 的 vite dev 服务器承载测试专用页面，不影响生产构建与 dist。
export default defineConfig({
  testDir: ".",
  testMatch: "harness.spec.ts",
  timeout: 30000,
  expect: { timeout: 8000 },
  use: { baseURL: "http://127.0.0.1:5193", testIdAttribute: "data-test" },
  webServer: {
    command: "npm run dev -- --port 5193 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:5193/tests/fixtures/chapter-reader/harness/index.html",
    reuseExistingServer: false,
    cwd: "../../../..",
    timeout: 120000,
  },
});
