import { describe, expect, it } from "vitest";
import { basicAuthHeader } from "../src/lib/basic-auth";

describe("studio basic auth encoding (Review D-1)", () => {
  it("matches the RFC 7617 ASCII vector used by the server tests", () => {
    // Same credentials as the Rust server integration tests.
    expect(basicAuthHeader("admin", "long-password")).toBe("Basic YWRtaW46bG9uZy1wYXNzd29yZA==");
  });

  it("UTF-8 encodes Unicode credentials instead of throwing in btoa", () => {
    expect(basicAuthHeader("admin", "密码")).toBe("Basic YWRtaW465a+G56CB");
    expect(basicAuthHeader("管理员", "chronicle-密码-2026")).toBe(
      `Basic ${Buffer.from("管理员:chronicle-密码-2026", "utf-8").toString("base64")}`,
    );
  });

  it("keeps colons and symbols byte-exact", () => {
    expect(basicAuthHeader("admin", "p:a s+s/w==")).toBe(
      `Basic ${Buffer.from("admin:p:a s+s/w==", "utf-8").toString("base64")}`,
    );
  });
});
