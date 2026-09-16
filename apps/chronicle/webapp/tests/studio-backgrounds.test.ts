import { afterEach, describe, expect, it, vi } from "vitest";
import {
  backgroundAssetPreviewPath,
  backgroundMediaTypeForUpload,
  createBackgroundBinding,
  disableBackgroundBinding,
  listBackgroundAssets,
  listBackgroundBindings,
  replaceBackgroundBinding,
  studioBinaryRequest,
  StudioApiError,
  uploadBackgroundAsset,
} from "../src/lib/studio-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

const imageFile = { name: "赤壁.webp", size: 128 } as File;

describe("Studio background API client", () => {
  it("accepts only the formats validated by the T15 backend", () => {
    expect(backgroundMediaTypeForUpload("scene.PNG")).toBe("image/png");
    expect(backgroundMediaTypeForUpload("scene.jpeg")).toBe("image/jpeg");
    expect(backgroundMediaTypeForUpload("scene.webp")).toBe("image/webp");
    expect(backgroundMediaTypeForUpload("scene.svg")).toBeNull();
    expect(backgroundAssetPreviewPath("asset/with-slash", "version")).toBe(
      "/api/v1/studio/background-assets/asset%2Fwith-slash/preview?asset_version_id=version",
    );
  });

  it("uploads and reads candidates through authenticated Studio routes", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init });
      expect(new Headers(init?.headers).get("Authorization")).toBe("Basic abc");
      expect(init?.credentials).toBe("same-origin");
      if (path.includes("background-assets?")) {
        if (init?.method === "POST") {
          expect(path).toContain("filename=%E8%B5%A4%E5%A3%81.webp");
          expect(path).toContain("source=operator");
          expect(path).toContain("era=late+Han");
          expect(path).toContain("prompt=quiet+river");
          expect(init.headers && new Headers(init.headers).get("Content-Type")).toBe("image/webp");
          return new Response(JSON.stringify({ asset: { asset_id: "a", asset_version_id: "av", version: 1, candidate: true } }), { status: 201 });
        }
        return new Response(JSON.stringify({ assets: [], offset: 0, has_more: false }), { status: 200 });
      }
      throw new Error(`unexpected path ${path}`);
    }));

    const uploaded = await uploadBackgroundAsset("Basic abc", imageFile, {
      source: "operator",
      era: "late Han",
      prompt: "quiet river",
    });
    const page = await listBackgroundAssets("Basic abc", { source: "operator", era: "late Han" });
    expect(uploaded.asset_id).toBe("a");
    expect(page.assets).toEqual([]);
    expect(calls).toHaveLength(2);
  });

  it("keeps exact binding version, range and concurrency preconditions in the request", async () => {
    const calls: Array<{ path: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init });
      if (path === "/api/v1/studio/background-bindings?limit=100&offset=0&status=all") {
        return new Response(JSON.stringify({ bindings: [], offset: 0, has_more: false }), { status: 200 });
      }
      if (path.endsWith("/replace")) {
        expect(JSON.parse(String(init?.body))).toMatchObject({
          asset_id: "asset",
          asset_version_id: "version",
          start_paragraph_id: "hp_000000000000000000000001",
          end_paragraph_id: "hp_000000000000000000000002",
          expected_revision: 3,
          expected_etag: '"binding-3"',
        });
        return new Response(JSON.stringify({ binding: { binding_id: "binding", active: true } }), { status: 200 });
      }
      if (path.endsWith("/disable")) {
        expect(JSON.parse(String(init?.body))).toEqual({ actor: "operator", expected_revision: 4, expected_etag: '"binding-4"' });
        return new Response(JSON.stringify({ binding: { binding_id: "binding", active: false } }), { status: 200 });
      }
      if (path === "/api/v1/studio/background-bindings") {
        expect(JSON.parse(String(init?.body))).toMatchObject({
          edition_version: "e".repeat(64),
          asset_id: "asset",
          asset_version_id: "version",
        });
        return new Response(JSON.stringify({ binding: { binding_id: "binding", active: true } }), { status: 201 });
      }
      throw new Error(`unexpected path ${path}`);
    }));

    const page = await listBackgroundBindings("Basic abc", { status: "all" });
    expect(page.bindings).toEqual([]);
    await createBackgroundBinding("Basic abc", {
      edition_version: "e".repeat(64),
      start_paragraph_id: "hp_000000000000000000000001",
      end_paragraph_id: "hp_000000000000000000000002",
      asset_id: "asset",
      asset_version_id: "version",
      display: { opacity: 0.4 },
    });
    await replaceBackgroundBinding("Basic abc", "binding", {
      asset_id: "asset",
      asset_version_id: "version",
      start_paragraph_id: "hp_000000000000000000000001",
      end_paragraph_id: "hp_000000000000000000000002",
      expected_revision: 3,
      expected_etag: '"binding-3"',
    });
    await disableBackgroundBinding("Basic abc", "binding", { actor: "operator", expected_revision: 4, expected_etag: '"binding-4"' });
    expect(calls).toHaveLength(4);
  });

  it("downloads private previews as blobs and preserves typed errors", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("Authorization")).toBe("Basic abc");
      expect(new Headers(init?.headers).get("Accept")).toContain("image/");
      return new Response(new Uint8Array([1, 2, 3]), { status: 200, headers: { "Content-Type": "image/png" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const blob = await studioBinaryRequest("Basic abc", "/preview");
    expect(blob.type).toBe("image/png");
    expect(blob.size).toBe(3);

    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "conflict", message: "范围重叠" } }), { status: 409 })));
    await expect(studioBinaryRequest("Basic abc", "/preview")).rejects.toMatchObject<Partial<StudioApiError>>({ status: 409, code: "conflict" });
  });
});
