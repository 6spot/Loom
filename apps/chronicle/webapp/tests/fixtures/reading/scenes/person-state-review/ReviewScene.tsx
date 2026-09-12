// C2-R3-T12 章阶段依据审核组件交互场景（仅测试使用，不进生产构建）。
//
// 用合成 ReviewPackage 驱动正式 PersonStateReviewPanel，模拟外部 save / skip /
// load-more / return 回调与 400/409/503/未知结果、迟到响应和窄屏/键盘操作。它不接
// Studio 路由、不写 sessionStorage、不请求真实 API，也不冒充已发布内容。

import { useRef, useState } from "react";
import PersonStateReviewPanel from "../../../../../src/components/studio/PersonStateReviewPanel";
import { createDraft, coverageSummary, reviewCoverage } from "../../../../../src/lib/person-state-review-display";
import type { PersonStateReviewDraft } from "../../../../../src/lib/person-state-review-display";
import type { ReviewCandidate, ReviewPackage } from "../../../../../src/lib/person-state-types";
import { PACKAGE_A, PACKAGE_A_PAGE2, PACKAGE_C, PACKAGES } from "./data";
import "../../../../../src/styles/person-state-review.css";
import "./harness.css";

type ErrorMode = "none" | "400" | "409" | "503" | "unknown";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

/** Synthetic stand-in for T13's read-only ReviewEvidencePanel window/chapter view. */
function SourceViewer({ candidate }: { candidate: ReviewCandidate }) {
  const [view, setView] = useState<"none" | "window" | "chapter">("none");
  return (
    <div className="psr-harness-source">
      <div className="psr-harness-source-tabs">
        <button
          type="button"
          data-test="psr-source-window"
          onClick={() => setView((current) => (current === "window" ? "none" : "window"))}
        >
          原文片段·前后文
        </button>
        <button
          type="button"
          data-test="psr-source-chapter"
          onClick={() => setView((current) => (current === "chapter" ? "none" : "chapter"))}
        >
          整章原文
        </button>
      </div>
      {view === "window" ? (
        <p data-test="psr-source-window-text">窗口原文：{candidate.quote}</p>
      ) : null}
      {view === "chapter" ? (
        <p data-test="psr-source-chapter-text">
          整章原文（{candidate.source_label}）：合成整章上下文…{candidate.quote}…
        </p>
      ) : null}
    </div>
  );
}

export default function ReviewScene() {
  const [packageIndex, setPackageIndex] = useState(0);
  const [blocked, setBlocked] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, PersonStateReviewDraft>>({});
  const [errorMode, setErrorMode] = useState<ErrorMode>("none");
  const [late, setLate] = useState(false);
  const [sourceFailure, setSourceFailure] = useState(false);
  const [lastAction, setLastAction] = useState("");
  const [savedCount, setSavedCount] = useState(0);

  const pkg = blocked ? PACKAGE_C : PACKAGES[packageIndex];
  const identity = `${pkg.review_id}|${pkg.plan_fingerprint}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;

  const draft = drafts[identity] ?? createDraft(pkg);
  const coverage = coverageSummary(reviewCoverage(pkg.candidates, draft));

  const onDraftChange = (next: PersonStateReviewDraft) => {
    setDrafts((current) => ({ ...current, [identity]: next }));
  };

  const advance = () => {
    setBlocked(false);
    setPackageIndex((index) => (index + 1) % PACKAGES.length);
  };

  const onSubmit = async (submitted: PersonStateReviewDraft) => {
    const target = identityRef.current;
    const targetReviewId = pkg.review_id;
    if (late) await delay(700);
    if (identityRef.current !== target) {
      // A late result for a package the reviewer already left must not touch
      // the current form.
      setLastAction(`late-dropped:${targetReviewId}`);
      return;
    }
    if (errorMode !== "none") {
      if (errorMode === "unknown") throw new Error("network down");
      throw { status: Number(errorMode), message: `simulated ${errorMode}` };
    }
    setSavedCount((count) => count + 1);
    setLastAction(`saved:${targetReviewId}`);
    setDrafts((current) => {
      const next = { ...current };
      delete next[target];
      return next;
    });
    advance();
  };

  const onSkip = async () => {
    setLastAction(`skip:${pkg.review_id}`);
    await delay(60);
    setDrafts((current) => {
      const next = { ...current };
      delete next[identity];
      return next;
    });
    advance();
  };

  const onReturn = () => {
    setLastAction(`return:${pkg.review_id}`);
  };

  // Only package A exposes a second page; package C advertises one but never
  // provides the loader, so the panel must fail closed.
  const onLoadMore =
    pkg === PACKAGE_A
      ? async (_cursor: string): Promise<ReviewPackage> => {
          await delay(80);
          setLastAction(`load-more:${pkg.review_id}`);
          return PACKAGE_A_PAGE2;
        }
      : undefined;

  return (
    <main className="psr-harness" data-test="psr-scene" data-synthetic="true">
      <header className="psr-harness-bar">
        <strong>Chronicle Studio · 阶段依据审核组件 harness</strong>
        <span className="psr-harness-flag" data-test="psr-synthetic-flag">
          合成测试场景 · 非真实审核
        </span>
      </header>

      <div className="psr-harness-controls" data-test="psr-controls">
        <label>
          模拟保存失败
          <select
            data-test="psr-simulate-error"
            value={errorMode}
            onChange={(event) => setErrorMode(event.target.value as ErrorMode)}
          >
            <option value="none">不失败</option>
            <option value="400">400 参数错误</option>
            <option value="409">409 版本冲突</option>
            <option value="503">503 服务不可用</option>
            <option value="unknown">未知结果</option>
          </select>
        </label>
        <label className="psr-harness-check">
          <input
            type="checkbox"
            data-test="psr-simulate-late"
            checked={late}
            onChange={(event) => setLate(event.target.checked)}
          />
          模拟迟到响应
        </label>
        <button
          type="button"
          data-test="psr-force-next"
          onClick={() => {
            setLastAction(`force-next:${pkg.review_id}`);
            advance();
          }}
        >
          直接切到下一项（不提交）
        </button>
        <button
          type="button"
          data-test="psr-source-failure"
          onClick={() => setSourceFailure((value) => !value)}
        >
          切换来源分页失败
        </button>
        <button
          type="button"
          data-test="psr-set-package-a"
          onClick={() => {
            setBlocked(false);
            setPackageIndex(0);
          }}
        >
          回到 A 包
        </button>
        <button
          type="button"
          data-test="psr-set-blocked"
          onClick={() => {
            setLastAction("blocked-package");
            setBlocked(true);
          }}
        >
          切到分页不可达的 C 包
        </button>
        <span data-test="psr-current-review">{pkg.review_id}</span>
        <span data-test="psr-last-action">{lastAction}</span>
        <span data-test="psr-saved-count">{savedCount}</span>
        <span data-test="psr-coverage-preview">{coverage}</span>
      </div>

      {sourceFailure ? (
        <p className="psr-harness-source-error" role="status" data-test="psr-source-error">
          来源分页加载失败：已读原文保留、可重试；本表单输入不受影响。
        </p>
      ) : null}

      <PersonStateReviewPanel
        key={identity}
        review={pkg}
        draft={draft}
        onDraftChange={onDraftChange}
        onSubmit={onSubmit}
        onSkip={onSkip}
        onReturn={onReturn}
        onLoadMore={onLoadMore}
        renderSource={(candidate) => <SourceViewer candidate={candidate} />}
      />
    </main>
  );
}
