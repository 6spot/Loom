// T15 Playwright harness 的 fixture  mock client（仅测试使用，不进生产构建）。
//
// 用固定 DTO 模拟公开阅读 API，支持经 URL 参数注入的延迟与一次性失败，
// 以便验证异步状态、重试与快速切换隔离。所有引用 ID 均来自服务端 fixture。
import {
  ChapterReaderApiError,
  type ChapterDetailResponse,
  type ChapterDirectoryResponse,
  type ChapterSourceResponse,
} from "../../../../src/lib/chapter-reader";
import chapterDetailA from "../chapter-detail.json";
import chapterDetailB from "../chapter-detail-b.json";
import directoryPage1 from "../directory-page1.json";
import directoryPage2 from "../directory-page2.json";
import sourceChapterPage1 from "../source-chapter-page1.json";
import sourceChapterPage2 from "../source-chapter-page2.json";
import sourceMalicious from "../source-malicious.json";
import sourceWindow from "../source-window.json";

function flags(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => { window.setTimeout(resolve, ms); });
}

const counters = { source: 0, detail: 0, directoryPage2: 0 };

export function resetMockCounters(): void {
  counters.source = 0;
  counters.detail = 0;
  counters.directoryPage2 = 0;
}

export async function mockFetchDirectory(cursor: string | null | undefined): Promise<ChapterDirectoryResponse> {
  const slow = Number(flags().get("slowMs") ?? 0);
  if (slow > 0) await delay(slow);
  if (cursor) {
    counters.directoryPage2 += 1;
    if (flags().get("failDirPage2Once") === "1" && counters.directoryPage2 === 1) {
      throw new ChapterReaderApiError(503, "upstream_limited", "harness 注入的一次性目录分页失败");
    }
    return JSON.parse(JSON.stringify(directoryPage2)) as ChapterDirectoryResponse;
  }
  return JSON.parse(JSON.stringify(directoryPage1)) as ChapterDirectoryResponse;
}

export async function mockFetchDetail(publicationId: string): Promise<ChapterDetailResponse> {
  counters.detail += 1;
  const slow = Number(flags().get("slowDetailMs") ?? flags().get("slowMs") ?? 0);
  if (slow > 0) await delay(slow);
  if (flags().get("failChapterOnce") === "1" && counters.detail === 1) {
    throw new ChapterReaderApiError(503, "upstream_limited", "harness 注入的一次性章节失败");
  }
  if (publicationId === (chapterDetailB as unknown as ChapterDetailResponse).publication_id) {
    return JSON.parse(JSON.stringify(chapterDetailB)) as ChapterDetailResponse;
  }
  return JSON.parse(JSON.stringify(chapterDetailA)) as ChapterDetailResponse;
}

export async function mockFetchSource(
  publicationId: string,
  anchorId: string,
  query: { view?: string; cursor?: string | null },
): Promise<ChapterSourceResponse> {
  counters.source += 1;
  const slow = Number(flags().get("slowSourceMs") ?? flags().get("slowMs") ?? 0);
  if (slow > 0) await delay(slow);
  if (flags().get("failSourceFirst") === "1" && counters.source === 1) {
    throw new ChapterReaderApiError(503, "upstream_limited", "harness 注入的一次性原文失败");
  }
  if (anchorId === "anc_malicious") {
    return JSON.parse(JSON.stringify(sourceMalicious)) as ChapterSourceResponse;
  }
  if (query.view === "chapter") {
    if (query.cursor) {
      return JSON.parse(JSON.stringify(sourceChapterPage2)) as ChapterSourceResponse;
    }
    return JSON.parse(JSON.stringify(sourceChapterPage1)) as ChapterSourceResponse;
  }
  void publicationId;
  return JSON.parse(JSON.stringify(sourceWindow)) as ChapterSourceResponse;
}
