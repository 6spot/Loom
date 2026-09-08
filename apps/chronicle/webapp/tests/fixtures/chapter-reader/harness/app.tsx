// T15 组件交互 harness 入口（仅供 Playwright 驱动，不进生产构建）。
// 目录 → 章节导航经 onSelectChapter 回调在本地 state 完成，不导入 App/router。
// 刻意不用 StrictMode：harness 用调用计数做一次性失败注入，双挂载会吞掉错误态。
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ChapterIndexPage from "../../../../src/pages/public/ChapterIndexPage";
import ChapterPage from "../../../../src/pages/public/ChapterPage";
import ChapterSourceReference from "../../../../src/components/ChapterSourceReference";
import "../../../../src/styles/chapter-reader.css";
import { mockFetchDetail, mockFetchDirectory, mockFetchSource, resetMockCounters } from "./mock";

const PUB_A = "00000000-0000-7000-8000-000000000000";

function Harness() {
  const [selected, setSelected] = useState<string | null>(null);
  const params = new URLSearchParams(window.location.search);
  const securityMode = params.get("panel") === "security";

  if (securityMode) {
    return (
      <main>
        <ChapterSourceReference
          publicationId={PUB_A}
          anchorId="anc_malicious"
          anchorLabel="harness 恶意片段检查"
          client={{ fetchSource: mockFetchSource }}
        />
      </main>
    );
  }

  if (!selected) {
    return (
      <main>
        <ChapterIndexPage
          client={{ fetchDirectory: (query) => mockFetchDirectory(query.cursor) }}
          onSelectChapter={(publicationId) => {
            resetMockCounters();
            setSelected(publicationId);
          }}
        />
      </main>
    );
  }
  return (
    <main>
      <button type="button" data-test="chapter-back" onClick={() => setSelected(null)}>
        回到目录
      </button>
      <ChapterPage
        publicationId={selected}
        client={{ fetchDetail: mockFetchDetail }}
        sourceClient={{ fetchSource: mockFetchSource }}
      />
    </main>
  );
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: 0 } },
});

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={queryClient}>
    <Harness />
  </QueryClientProvider>,
);
