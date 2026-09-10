import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { describe, expect, it } from "vitest";

// CLI contract for the review-flow smoke: argument validation must fail fast
// with exit 1 and a clear message before any browser is launched, and the
// real-backend mode must refuse to run without credentials.
const SCRIPT = new URL("../scripts/review-flow-smoke.mjs", import.meta.url).pathname;
const NODE = process.execPath;

function run(argv: string[], env: Record<string, string> = {}) {
  return spawnSync(NODE, [SCRIPT, ...argv], {
    encoding: "utf8",
    env: { PATH: "/usr/local/bin:/usr/bin:/bin", HOME: homedir(), ...env },
  });
}

describe("review-flow-smoke CLI contract", () => {
  it("requires --base-url", () => {
    const result = run([]);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("--base-url is required");
  });

  it("rejects an unsupported mode", () => {
    const result = run(["--base-url", "http://127.0.0.1:1", "--mode", "bogus"]);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("unsupported --mode bogus");
  });

  it("rejects an unsupported mocked-api suite", () => {
    const result = run(["--base-url", "http://127.0.0.1:1", "--mode", "mocked-api", "--suite", "bogus"]);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("unsupported --suite bogus");
  });

  it("requires credentials in real-backend mode", () => {
    const result = run(["--base-url", "http://127.0.0.1:1", "--mode", "real-backend"]);
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("real-backend needs credentials");
  });

  it("accepts real-backend credentials from flags", () => {
    // The next failure must be the connection, not credential validation.
    const result = run([
      "--base-url",
      "http://127.0.0.1:1",
      "--mode",
      "real-backend",
      "--username",
      "smoke-user",
      "--password",
      "smoke-pass",
    ]);
    expect(result.stderr).not.toContain("real-backend needs credentials");
  });
});
