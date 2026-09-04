import { formatTime } from "../lib/routes";
import type { ClaimWrapper, ResolutionLink } from "../lib/types";

export const DECISION_LABEL: Record<string, string> = {
  same_entity: "同一实体",
  same_occurrence: "同一事件",
  related_occurrence: "相关但不同事件",
  uncertain: "身份不确定",
  not_same: "明确不同",
};

export function ClaimCard({ wrapper }: { wrapper: ClaimWrapper }) {
  const claim = wrapper.claim ?? {};
  const evidence = claim.evidence ?? {};
  const evidenceText = evidence.text ?? "（此 Claim 没有 evidence.text）";
  const locator = evidence.locator && Object.keys(evidence.locator).length
    ? `定位：${JSON.stringify(evidence.locator)}`
    : null;
  return (
    <article className="claim" data-test="claim">
      <div className="predicate">
        {claim.predicate ?? "claim"} · {wrapper.bundle ?? ""} : {wrapper.ref ?? ""}
      </div>
      <blockquote>{evidenceText}</blockquote>
      {locator ? <div className="locator">{locator}</div> : null}
    </article>
  );
}

export function ClaimsBlock({ claims }: { claims?: ClaimWrapper[] }) {
  if (!claims || claims.length === 0) return <p className="muted">此记录没有直接关联的 Claim。</p>;
  return (
    <div className="claims-list">
      {claims.map((claim, index) => (
        <ClaimCard key={`${claim.bundle ?? "bundle"}:${claim.ref ?? index}`} wrapper={claim} />
      ))}
    </div>
  );
}

export function RawDetails({ label, payload }: { label: string; payload: unknown }) {
  return (
    <details className="details-json">
      <summary>{label}</summary>
      <pre>{JSON.stringify(payload ?? {}, null, 2)}</pre>
    </details>
  );
}

function ResolutionItem({
  link,
  targetKind,
  currentId,
}: {
  link: ResolutionLink;
  targetKind: "entity" | "event";
  currentId: string;
}) {
  const confidence = Number.isFinite(Number(link.confidence))
    ? `${Math.round(Number(link.confidence) * 100)}%`
    : "—";
  const sideKey = targetKind === "entity" ? "canonical_entity_id" : "canonical_event_id";
  const leftId = link.left?.[sideKey];
  const rightId = link.right?.[sideKey];
  const otherId = leftId && leftId !== currentId ? leftId : rightId && rightId !== currentId ? rightId : null;
  return (
    <article className="resolution-item" data-decision={link.decision ?? ""}>
      <header>
        <span className={`decision ${link.decision ?? ""}`}>
          {DECISION_LABEL[link.decision ?? ""] ?? link.decision ?? "unknown"}
        </span>
        <span className="count">confidence {confidence}</span>
      </header>
      <p>{link.rationale ?? "无 rationale"}</p>
      {otherId ? (
        <a href={targetKind === "entity" ? `/entities/${encodeURIComponent(otherId)}` : `/events/${encodeURIComponent(otherId)}`}>
          查看另一 canonical {targetKind === "entity" ? "Entity" : "Event"}
        </a>
      ) : null}
      <RawDetails label="Resolution signals" payload={link.signals ?? {}} />
    </article>
  );
}

export function ResolutionBlock({
  links,
  targetKind,
  currentId,
}: {
  links?: ResolutionLink[];
  targetKind: "entity" | "event";
  currentId: string;
}) {
  if (!links || links.length === 0) return <p className="muted">没有跨来源 Resolution 记录。</p>;
  return (
    <div className="resolution-list">
      {links.map((link, index) => (
        <ResolutionItem key={index} link={link} targetKind={targetKind} currentId={currentId} />
      ))}
    </div>
  );
}

export function LoadingState({ label }: { label: string }) {
  return (
    <section className="state-card">
      <p className="eyebrow">Chronicle</p>
      <h1>正在读取{label}…</h1>
      <p className="muted">数据来自 Chronicle read API。</p>
    </section>
  );
}

export function ErrorState({ code, message }: { code: string; message: string }) {
  return (
    <section className="state-card error-card" data-view="error">
      <p className="eyebrow">{code}</p>
      <h1>无法读取这个历史页面</h1>
      <p>{message}</p>
      <p>
        <a href="/timeline">返回时间线</a>
      </p>
    </section>
  );
}

export function NotFoundState() {
  return (
    <section className="state-card error-card" data-view="not-found">
      <p className="eyebrow">404</p>
      <h1>这个 Chronicle 页面不存在</h1>
      <p>
        <a href="/timeline">返回时间线</a>
      </p>
    </section>
  );
}

export { formatTime };
