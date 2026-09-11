// Active-paragraph context only. Event participation is never an office or allegiance.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import PublicDialog from "../PublicDialog";
import type { ContextEntityView } from "../../lib/reading-types";
import { buildReadingContextDisplay, contextGroupForKind,
  type ContextDisplayItem, type ContextGroupKey } from "../../lib/reading-context-display";
import "../../styles/reading-context.css";

export interface ReadingStateFact {
  readonly id: string;
  readonly label: string;
  readonly value: string;
  readonly certainty: "clear" | "uncertain";
  readonly reason?: string;
}

export function StateFacts({ facts }: { facts: readonly ReadingStateFact[] }) {
  return <span className="chr-context-states">{facts.map((fact) =>
    <span key={fact.id} className="chr-context-state" data-certainty={fact.certainty}
      title={fact.reason || undefined}>
      <span className="chr-state-mark" aria-hidden="true">{fact.certainty === "clear" ? "●" : "○"}</span>
      <span className="public-sr-only">{fact.certainty === "clear" ? "明确记载：" : "存疑："}{fact.label}，</span>
      {fact.value}{fact.certainty === "uncertain" ? <small>存疑</small> : null}
    </span>
  )}</span>;
}

export interface ReadingContextPanelProps {
  readonly entities: readonly ContextEntityView[] | null | undefined;
  readonly variant?: "column" | "panel";
  readonly unitId?: string;
  /** Already reviewed facts for this exact stage; never synthesized from event_roles. */
  readonly stateFacts?: Readonly<Record<string, readonly ReadingStateFact[]>>;
  readonly onViewEntity?: (item: ContextDisplayItem) => void;
  readonly onViewSource?: (item: ContextDisplayItem, anchorId: string) => void;
  readonly onClose?: () => void;
  readonly resolveEventLabel?: (eventRef: string) => string | null;
  readonly limits?: Partial<Record<ContextGroupKey, number>>;
  readonly defaultExpanded?: Partial<Record<ContextGroupKey, boolean>>;
  readonly children?: ReactNode | ((close: () => void) => ReactNode);
}

export default function ReadingContextPanel({ entities, variant = "column", unitId,
  stateFacts, onViewEntity, onViewSource, onClose, limits, defaultExpanded, children,
}: ReadingContextPanelProps) {
  const [expanded, setExpanded] = useState<Partial<Record<ContextGroupKey, boolean>>>(() => ({ ...defaultExpanded }));
  const [open, setOpen] = useState(false);
  const previousUnitRef = useRef(unitId);
  useEffect(() => {
    if (previousUnitRef.current === unitId) return;
    previousUnitRef.current = unitId;
    setExpanded({ ...defaultExpanded });
  }, [unitId, defaultExpanded]);
  const display = useMemo(() => buildReadingContextDisplay(entities, { expanded, limits, primaryOnly: true }), [entities, expanded, limits]);
  const close = () => { setOpen(false); onClose?.(); };
  const body = <>
    {typeof children === "function" ? children(close) : children}
    {display.hasAny ? display.groups.map((group) => <section className="chr-context-group"
      data-test="reading-context-group" data-group={group.key} key={group.key}>
      <h3 className="chr-context-group-title">{group.label}</h3>
      <ul className="chr-context-list">{group.items.map((item) => {
        const facts = stateFacts?.[item.canonicalId ?? item.entityRef] ?? [];
        const content = <><span className="chr-context-name" data-test="reading-context-name">{item.name}</span>
          {facts.length ? <StateFacts facts={facts} /> : <span className="chr-context-unknown">
            {item.kind === "person" ? "当时身份尚未收录" : item.kind === "place" ? "当时归属尚未收录" : "本段涉及"}
          </span>}</>;
        return <li className="chr-context-item" data-test="reading-context-entity"
          data-kind={item.kind} data-group={contextGroupForKind(item.kind)} data-importance={item.importance}
          data-canonical={item.canonicalId ?? ""} data-entity-refs={item.entityRefs.join(",")}
          data-deduped={item.deduped ? "true" : "false"} key={item.key}>
          {onViewEntity && item.canonicalId ? <button type="button" className="chr-context-row"
            data-test="reading-context-view-entity" aria-label={`查看${item.name}的详细资料`}
            onClick={() => onViewEntity(item)}>{content}</button> : <div className="chr-context-row">{content}</div>}
          {!item.canonicalId && onViewSource && item.sourceAnchorIds.length ? <details className="chr-context-source-details">
            <summary>资料</summary>{item.sourceAnchorIds.map((anchorId) => <button type="button" className="public-text-button"
              key={anchorId} data-test="reading-context-view-source" onClick={() => { close(); onViewSource(item, anchorId); }}>查看原文</button>)}
          </details> : null}
        </li>;
      })}</ul>
      {group.hiddenCount > 0 ? <button type="button" className="chr-context-expand" data-test="reading-context-expand"
        data-group={group.key} onClick={() => setExpanded((current) => ({ ...current, [group.key]: true }))}>其他{group.label} · {group.hiddenCount}</button> : null}
      {group.expanded ? <button type="button" className="chr-context-expand" data-test="reading-context-collapse"
        data-group={group.key} onClick={() => setExpanded((current) => ({ ...current, [group.key]: false }))}>收起</button> : null}
    </section>) : <p className="chr-context-empty" data-test="reading-context-empty">这段正文还没有关联人物或地点。</p>}
  </>;
  if (variant === "panel") return <div className="chr-context-compact" data-test="reading-context-compact">
    <button type="button" className="public-text-button" data-test="reading-context-open"
      aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>此时此地</button>
    {open ? <PublicDialog title="此时此地" onClose={close} closeTestId="reading-context-close" compact>
      <div className="chr-context-panel" data-test="reading-context-panel" data-variant="panel" data-unit={unitId ?? ""}>
        {body}
      </div>
    </PublicDialog> : null}
  </div>;
  return <aside className="chr-context-panel" data-test="reading-context-panel" data-variant="column"
    data-unit={unitId ?? ""} aria-label="此时的人物与地点">{body}</aside>;
}
