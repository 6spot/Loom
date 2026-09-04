import { afterEach, describe, expect, it, vi } from "vitest";
import {
  jobIsLive,
  mediaTypeForUpload,
  mutateJob,
  queueJob,
  StudioApiError,
} from "../src/lib/studio-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Studio imports API client", () => {
  it("accepts only the controlled text upload formats", () => {
    expect(mediaTypeForUpload("先主传.txt")).toBe("text/plain");
    expect(mediaTypeForUpload("notes.MD")).toBe("text/markdown");
    expect(mediaTypeForUpload("scan.pdf")).toBeNull();
  });

  it("polls only lifecycle states that can still change", () => {
    expect(jobIsLive("queued")).toBe(true);
    expect(jobIsLive("running")).toBe(true);
    expect(jobIsLive("needs_review")).toBe(true);
    expect(jobIsLive("failed")).toBe(false);
    expect(jobIsLive("cancelled")).toBe(false);
    expect(jobIsLive("completed")).toBe(false);
  });

  it("queues and mutates jobs only through authenticated Studio HTTP routes", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      expect(new Headers(init?.headers).get("Authorization")).toBe("Basic abc");
      expect(init?.credentials).toBe("same-origin");
      if (path.endsWith("/retry")) {
        return new Response(JSON.stringify({ schema: "chronicle.job", version: "0.2", job: { job_id: "j", status: "running" } }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      expect(path).toBe("/api/v1/studio/jobs");
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body))).toEqual({ revision_id: "rev", max_attempts: 3 });
      return new Response(JSON.stringify({ schema: "chronicle.job", version: "0.2", job: { job_id: "j", status: "queued" } }), { status: 201, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    const queued = await queueJob("Basic abc", "rev");
    expect(queued.job_id).toBe("j");
    const retried = await mutateJob("Basic abc", "j", "retry");
    expect(retried.status).toBe("running");
  });

  it("preserves typed server errors for operator feedback", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ error: { code: "conflict", message: "open reviews remain" } }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(mutateJob("Basic abc", "j", "resume")).rejects.toMatchObject<Partial<StudioApiError>>({
      code: "conflict",
      status: 409,
      message: "open reviews remain",
    });
  });
});
