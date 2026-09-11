// C2-R2-T14 当前正文人物、地点及有来源的事件角色面板。
//
// 只渲染 active unit 已发布的 context_entities（T01 DTO），不请求 World 或人物
// 状态，不推导长期官职/阵营。桌面右栏与窄屏按需面板共用同一内容；实体/来源
// 查看由查看回调交给 T12/T15 处理返回，本组件不拥有路由或阅读位置。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ContextEntityView } from "../../lib/reading-types";
import {
  buildReadingContextDisplay,
  contextGroupForKind,
  eventRoleLabel,
  EVENT_ROLE_SCOPE_NOTE,
  PLACE_POSITION_NOTE,
  type ContextDisplayGroup,
  type ContextDisplayItem,
  type ContextGroupKey,
} from "../../lib/reading-context-display";
import "../../styles/reading-context.css";

export interface ReadingContextPanelProps {
  /** active unit 的 published context_entities；null/[] 表示本段无明确关联。 */
  readonly entities: readonly ContextEntityView[] | null | undefined;
  /** 桌面右栏（column）或窄屏按需面板（panel）。两者内容一致。 */
  readonly variant?: "column" | "panel";
  /** 用于在切换 active unit 时重置展开状态；不传则仅依赖 entities 变化。 */
  readonly unitId?: string;
  readonly onViewEntity?: (item: ContextDisplayItem) => void;
  readonly onViewSource?: (item: ContextDisplayItem, anchorId: string) => void;
  readonly onClose?: () => void;
  readonly resolveEventLabel?: (eventRef: string) => string | null;
  readonly limits?: Partial<Record<ContextGroupKey, number>>;
  readonly defaultExpanded?: Partial<Record<ContextGroupKey, boolean>>;
}

function GroupSection({
  group,
  resolveEventLabel,
  onViewEntity,
  onViewSource,
  onToggleExpand,
}: {
  group: ContextDisplayGroup;
  resolveEventLabel?: (eventRef: string) => string | null;
  onViewEntity?: (item: ContextDisplayItem) => void;
  onViewSource?: (item: ContextDisplayItem, anchorId: string) => void;
  onToggleExpand: (group: ContextGroupKey) => void;
}) {
  const hasEventRoles = group.items.some((item) => item.roles.length > 0);
  const collapsible = group.limit !== null && group.total > group.limit;
  return (
    <section className="chr-context-group" data-test="reading-context-group" data-group={group.key}>
      <h3 className="chr-context-group-title">
        {group.label}
        <span className="chr-context-count" data-test="reading-context-group-count">
          {group.total}
        </span>
      </h3>
      {group.key === "places" ? (
        <p className="chr-context-note" data-test="reading-context-place-note">
          {PLACE_POSITION_NOTE}
        </p>
      ) : null}
      {group.key === "people" && hasEventRoles ? (
        <p className="chr-context-note" data-test="reading-context-role-note">
          {EVENT_ROLE_SCOPE_NOTE}
        </p>
      ) : null}
      <ul className="chr-context-list">
        {group.items.map((item) => (
          <li
            className="chr-context-item"
            data-test="reading-context-entity"
            data-kind={item.kind}
            data-group={contextGroupForKind(item.kind)}
            data-importance={item.importance}
            data-canonical={item.canonicalId ?? ""}
            data-entity-refs={item.entityRefs.join(",")}
            data-deduped={item.deduped ? "true" : "false"}
            key={item.key}
          >
            <div className="chr-context-item-head">
              <span className="chr-context-name" data-test="reading-context-name">
                {item.name}
              </span>
              {item.importance === "primary" ? (
                <span className="chr-context-badge" data-test="reading-context-primary">
                  主要
                </span>
              ) : null}
              {item.deduped ? (
                <span
                  className="chr-context-merged"
                  data-test="reading-context-merged"
                  data-merged-count={item.entityRefs.length}
                >
                  同一对象 {item.entityRefs.length} 处记载
                </span>
              ) : null}
            </div>

            {item.roles.length > 0 ? (
              <ul className="chr-context-roles" data-test="reading-context-roles">
                {item.roles.map((role) => (
                  <li
                    className="chr-context-role"
                    data-test="reading-context-role"
                    data-event={role.eventRef}
                    data-role={role.role}
                    data-participant-index={role.participantIndex}
                    key={`${role.entityRef}:${role.eventRef}:${role.role}:${role.participantIndex}`}
                  >
                    {eventRoleLabel(role, resolveEventLabel)}
                  </li>
                ))}
              </ul>
            ) : null}

            <div className="chr-context-actions" data-test="reading-context-actions">
              {onViewEntity && item.canonicalId ? (
                <button
                  type="button"
                  className="chr-context-action"
                  data-test="reading-context-view-entity"
                  onClick={() => onViewEntity(item)}
                >
                  查看实体
                </button>
              ) : null}
              {onViewSource && item.sourceAnchorIds.length > 0
                ? item.sourceAnchorIds.map((anchorId) => (
                    <button
                      type="button"
                      className="chr-context-action"
                      data-test="reading-context-view-source"
                      data-anchor={anchorId}
                      key={anchorId}
                      onClick={() => onViewSource(item, anchorId)}
                    >
                      查看来源
                    </button>
                  ))
                : null}
              {item.sourceAnchorIds.length === 0 ? (
                <span className="chr-context-missing-source" data-test="reading-context-no-source">
                  本段未附原文依据
                </span>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
      {group.hiddenCount > 0 ? (
        <button
          type="button"
          className="chr-context-expand"
          data-test="reading-context-expand"
          data-group={group.key}
          onClick={() => onToggleExpand(group.key)}
        >
          展开全部（还有 {group.hiddenCount} 项）
        </button>
      ) : null}
      {group.expanded && collapsible ? (
        <button
          type="button"
          className="chr-context-expand"
          data-test="reading-context-collapse"
          data-group={group.key}
          onClick={() => onToggleExpand(group.key)}
        >
          收起到默认数量
        </button>
      ) : null}
    </section>
  );
}

export default function ReadingContextPanel({
  entities,
  variant = "column",
  unitId,
  onViewEntity,
  onViewSource,
  onClose,
  resolveEventLabel,
  limits,
  defaultExpanded,
}: ReadingContextPanelProps) {
  const [expanded, setExpanded] = useState<Partial<Record<ContextGroupKey, boolean>>>(
    () => ({ ...(defaultExpanded ?? {}) }),
  );
  const [open, setOpen] = useState(variant === "column");
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousUnitRef = useRef(unitId);

  useEffect(() => {
    if (previousUnitRef.current === unitId) return;
    previousUnitRef.current = unitId;
    setExpanded({ ...(defaultExpanded ?? {}) });
  }, [unitId, defaultExpanded]);

  useEffect(() => {
    if (variant !== "panel" || !open) return;
    closeButtonRef.current?.focus();
  }, [open, variant]);

  const display = useMemo(
    () => buildReadingContextDisplay(entities, { expanded, limits }),
    [entities, expanded, limits],
  );

  const toggleExpand = useCallback((group: ContextGroupKey) => {
    setExpanded((current) => ({ ...current, [group]: !current[group] }));
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    onClose?.();
    openButtonRef.current?.focus();
  }, [onClose]);

  const body = display.hasAny ? (
    <>
      {display.groups.map((group) => (
        <GroupSection
          group={group}
          key={group.key}
          onToggleExpand={toggleExpand}
          resolveEventLabel={resolveEventLabel}
          onViewEntity={onViewEntity}
          onViewSource={onViewSource}
        />
      ))}
    </>
  ) : (
    <p className="chr-context-empty" data-test="reading-context-empty">
      本段无明确关联
    </p>
  );

  if (variant === "panel") {
    return (
      <div className="chr-context-compact" data-test="reading-context-compact">
        <button
          ref={openButtonRef}
          type="button"
          className="chr-context-open"
          data-test="reading-context-open"
          aria-expanded={open}
          aria-controls="reading-context-panel"
          onClick={() => setOpen(true)}
        >
          人物地点
          {display.hasAny ? <span className="chr-context-count">{display.totalItems}</span> : null}
        </button>
        {open ? (
          <section
            id="reading-context-panel"
            className="chr-context-panel chr-context-panel-overlay"
            data-test="reading-context-panel"
            data-variant="panel"
            aria-label="本段人物地点"
          >
            <header className="chr-context-heading">
              <h2>本段人物地点</h2>
              <button
                ref={closeButtonRef}
                type="button"
                className="chr-context-action"
                data-test="reading-context-close"
                onClick={close}
              >
                关闭
              </button>
            </header>
            {body}
          </section>
        ) : null}
      </div>
    );
  }

  return (
    <aside
      className="chr-context-panel"
      data-test="reading-context-panel"
      data-variant="column"
      data-unit={unitId ?? ""}
      aria-label="本段人物地点"
    >
      <header className="chr-context-heading">
        <h2>本段人物地点</h2>
      </header>
      {body}
    </aside>
  );
}
