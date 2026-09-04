import type { ReaderPresentation as ReaderPresentationData, ReaderPresentationBlock, ReaderSupport } from "../lib/types";

const BLOCK_LABEL: Record<ReaderPresentationBlock["block_kind"], string> = {
  overview: "概览",
  sequence: "经过",
  outcome: "结果",
  source_notes: "史料说明",
  uncertainty: "仍有不确定",
};

function SupportEvidence({ support }: { support: ReaderSupport }) {
  const evidence = support.claim?.evidence;
  return (
    <details className="reader-support">
      <summary>
        {support.source?.title ?? support.bundle ?? "来源"}
        {support.claim?.predicate ? ` · ${support.claim.predicate}` : ""}
      </summary>
      <div className="reader-support-body">
        <code>{support.bundle}:{support.ref}</code>
        {evidence?.text ? <blockquote>{evidence.text}</blockquote> : <p className="muted">没有可显示的 evidence 文本。</p>}
        {evidence?.locator ? <pre>{JSON.stringify(evidence.locator, null, 2)}</pre> : null}
      </div>
    </details>
  );
}

export default function ReaderPresentation({ presentation }: { presentation: ReaderPresentationData | null | undefined }) {
  const blocks = presentation?.blocks ?? [];
  if (!presentation || !blocks.length) return null;

  return (
    <section className="reader-presentation" data-test="reader-presentation" data-presentation-id={presentation.presentation_id}>
      <div className="reader-presentation-heading">
        <div>
          <p className="eyebrow">现代中文阅读</p>
          <h2>先读懂，再核对史料</h2>
        </div>
        <span className="reader-version">zh-CN · v{presentation.presentation_version}</span>
      </div>
      <p className="reader-provenance-note">
        下面是派生的阅读文本，不是新的历史权威。每一段都可以展开查看它绑定的 Claim、原始 evidence 与来源。
      </p>
      <div className="reader-blocks">
        {blocks.map((block) => (
          <article
            key={block.block_id}
            className={`reader-block${block.block_kind === "uncertainty" ? " reader-block-uncertainty" : ""}`}
            data-block-kind={block.block_kind}
          >
            <div className="reader-block-label">{BLOCK_LABEL[block.block_kind]}</div>
            <p>{block.text}</p>
            <details className="reader-evidence-group">
              <summary>依据 · {block.supports?.length ?? 0} 条 Claim</summary>
              <div className="reader-support-list">
                {(block.supports ?? []).map((support, index) => (
                  <SupportEvidence key={`${support.bundle}:${support.ref}:${index}`} support={support} />
                ))}
              </div>
            </details>
          </article>
        ))}
      </div>
      <details className="reader-generation-meta">
        <summary>查看 Reader Presentation 生成信息</summary>
        <dl>
          <div><dt>contract</dt><dd>{presentation.contract_version}</dd></div>
          <div><dt>generator</dt><dd>{presentation.generator?.generator_version ?? "—"}</dd></div>
          <div><dt>model</dt><dd>{presentation.generator?.model_version ?? "—"}</dd></div>
          <div><dt>prompt</dt><dd>{presentation.generator?.prompt_version ?? "—"}</dd></div>
        </dl>
      </details>
    </section>
  );
}
