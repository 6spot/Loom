#!/usr/bin/env python3
"""Temporary R19 Studio exception-workflow patch."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:140]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Keep the pre-R19 request body byte-compatible when no exceptions are supplied.
replace_once(
    "apps/chronicle/webapp/src/lib/studio-api.ts",
    '''  const path = `${REVIEWS_API}/${encodeURIComponent(reviewId)}/decision`;\n  return (\n    await studioRequest<ReviewResponse>(auth, path, {\n      method: "POST",\n      headers: { "Content-Type": "application/json" },\n      body: JSON.stringify({\n        decision,\n        rationale,\n        confidence,\n        group_decisions: groupDecisions,\n      }),\n    })\n  ).review;\n''',
    '''  const path = `${REVIEWS_API}/${encodeURIComponent(reviewId)}/decision`;\n  const payload: {\n    decision: ReviewDecision;\n    rationale: string;\n    confidence: number;\n    group_decisions?: ReviewGroupDecisionInput[];\n  } = { decision, rationale, confidence };\n  if (groupDecisions.length) payload.group_decisions = groupDecisions;\n  return (\n    await studioRequest<ReviewResponse>(auth, path, {\n      method: "POST",\n      headers: { "Content-Type": "application/json" },\n      body: JSON.stringify(payload),\n    })\n  ).review;\n''',
)

DETAIL = "apps/chronicle/webapp/src/pages/studio/StudioReviewDetailPage.tsx"

replace_once(
    DETAIL,
    '''import type { ReviewDecision, ReviewRecordContext } from "../../lib/studio-api";\n''',
    '''import type {\n  ReviewDecision,\n  ReviewGroupDecisionInput,\n  ReviewRecordContext,\n} from "../../lib/studio-api";\n''',
)

replace_once(
    DETAIL,
    '''function pretty(value: unknown): string {\n''',
    '''type GroupOverrideDraft = {\n  enabled: boolean;\n  decision: ReviewDecision | "";\n  rationale: string;\n  confidence: string;\n};\n\nfunction pretty(value: unknown): string {\n''',
)

replace_once(
    DETAIL,
    '''  const [confidence, setConfidence] = useState("0.5");\n\n  useEffect(() => {\n''',
    '''  const [confidence, setConfidence] = useState("0.5");\n  const [showExceptions, setShowExceptions] = useState(false);\n  const [groupOverrides, setGroupOverrides] = useState<Record<string, GroupOverrideDraft>>({});\n\n  useEffect(() => {\n''',
)

replace_once(
    DETAIL,
    '''  useEffect(() => {\n    if (!decision && allowed.length) setDecision(allowed[0]);\n  }, [allowed, decision]);\n\n  const canSubmit = useMemo(() => {\n    const parsed = Number(confidence);\n    return Boolean(\n      item?.status === "open" &&\n      decision &&\n      allowed.includes(decision as ReviewDecision) &&\n      rationale.trim() &&\n      Number.isFinite(parsed) && parsed >= 0 && parsed <= 1,\n    );\n  }, [allowed, confidence, decision, item?.status, rationale]);\n''',
    '''  useEffect(() => {\n    if (!decision && allowed.length) setDecision(allowed[0]);\n  }, [allowed, decision]);\n\n  useEffect(() => {\n    setShowExceptions(false);\n    setGroupOverrides({});\n  }, [reviewId]);\n\n  const setGroupOverride = (groupId: string, patch: Partial<GroupOverrideDraft>) => {\n    setGroupOverrides((current) => {\n      const existing = current[groupId] ?? {\n        enabled: false,\n        decision: (decision || allowed[0] || "") as ReviewDecision | "",\n        rationale: "",\n        confidence: confidence || "0.5",\n      };\n      return { ...current, [groupId]: { ...existing, ...patch } };\n    });\n  };\n\n  const canSubmit = useMemo(() => {\n    const parsed = Number(confidence);\n    const overridesValid = Object.values(groupOverrides).every((draft) => {\n      if (!draft.enabled) return true;\n      const groupConfidence = Number(draft.confidence);\n      return Boolean(\n        draft.decision &&\n        allowed.includes(draft.decision as ReviewDecision) &&\n        draft.rationale.trim() &&\n        Number.isFinite(groupConfidence) &&\n        groupConfidence >= 0 &&\n        groupConfidence <= 1,\n      );\n    });\n    return Boolean(\n      item?.status === "open" &&\n      decision &&\n      allowed.includes(decision as ReviewDecision) &&\n      rationale.trim() &&\n      Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 &&\n      overridesValid,\n    );\n  }, [allowed, confidence, decision, groupOverrides, item?.status, rationale]);\n''',
)

replace_once(
    DETAIL,
    '''      return submitReviewDecision(\n        authHeader,\n        item.review_id,\n        decision,\n        rationale.trim(),\n        Number(confidence),\n      );\n''',
    '''      const reviewGroups = item.review_groups ?? [];\n      const groupDecisions: ReviewGroupDecisionInput[] = reviewGroups.flatMap((group) => {\n        const draft = groupOverrides[group.review_group_id];\n        if (!draft?.enabled || !draft.decision) return [];\n        return [{\n          review_group_id: group.review_group_id,\n          decision: draft.decision as ReviewDecision,\n          rationale: draft.rationale.trim(),\n          confidence: Number(draft.confidence),\n        }];\n      });\n      return submitReviewDecision(\n        authHeader,\n        item.review_id,\n        decision,\n        rationale.trim(),\n        Number(confidence),\n        groupDecisions,\n      );\n''',
)

replace_once(
    DETAIL,
    '''  const memberCount = item.member_count ?? 1;\n\n  return (\n''',
    '''  const memberCount = item.member_count ?? 1;\n  const reviewGroups = item.review_groups ?? [];\n  const groupCount = item.group_count ?? (reviewGroups.length || 1);\n\n  return (\n''',
)

replace_once(
    DETAIL,
    '''            审核主题 {item.review_subject_id ?? item.candidate_id} · {memberCount} 个底层候选\n''',
    '''            审核批次 {item.review_subject_id ?? item.candidate_id} · {groupCount} 个来源候选组 / {memberCount} 个底层候选\n''',
)

replace_once(
    DETAIL,
    '''      {memberCount > 1 ? (\n        <Card>\n          <CardHeader>\n            <CardTitle>已合并重复审核</CardTitle>\n            <CardDescription>\n              该审核主题包含 {memberCount} 个底层候选。它们只因为已发布规范身份或来源内已证明的同一关系而被归到同一主题；分组本身不是身份结论。\n            </CardDescription>\n          </CardHeader>\n          <CardContent>\n            <p className="studio-safe-note">\n              你只需审核一次；一个判断会确定性应用到该主题中的全部底层候选，同时每个候选 ID、来源引用和证据仍保留在审计记录中。\n            </p>\n          </CardContent>\n        </Card>\n      ) : null}\n''',
    '''      {memberCount > 1 || groupCount > 1 ? (\n        <Card>\n          <CardHeader>\n            <CardTitle>重复问题已整理为审核批次</CardTitle>\n            <CardDescription>\n              该批次包含 {groupCount} 个来源候选组 / {memberCount} 个底层候选。批次只是把指向同一个已发布身份或事件的问题集中展示，绝不表示这些来源候选组彼此已经被认定为同一实体或同一次事件。\n            </CardDescription>\n          </CardHeader>\n          <CardContent className="studio-stack">\n            <p className="studio-safe-note">\n              默认情况下你可以对整个批次给出一个判断；如果其中某组证据不同，使用“存在例外，展开逐组判断”，只覆盖那个例外组。所有候选 ID、来源引用和证据都会继续保留在审计记录中。\n            </p>\n            {item.status === "open" && groupCount > 1 ? (\n              <Button type="button" variant="outline" onClick={() => setShowExceptions((value) => !value)}>\n                {showExceptions ? "收起逐组判断" : "存在例外，展开逐组判断"}\n              </Button>\n            ) : null}\n          </CardContent>\n        </Card>\n      ) : null}\n''',
)

replace_once(
    DETAIL,
    '''            <CardDescription>只根据上方两侧来源证据作决定；“证据不足，暂不确定”不会触发合并。若该主题包含多个底层候选，这一个判断会应用到全部成员。</CardDescription>\n''',
    '''            <CardDescription>只根据上方来源证据作决定；“证据不足，暂不确定”不会触发合并。默认判断应用到未设置例外的候选组，逐组例外只覆盖对应组。</CardDescription>\n''',
)

replace_once(
    DETAIL,
    '''                <div>\n                  <label className="studio-label" htmlFor="review-confidence">判断置信度（0–1）</label>\n                  <Input\n                    id="review-confidence"\n                    type="number"\n                    min="0"\n                    max="1"\n                    step="0.05"\n                    value={confidence}\n                    onChange={(event) => setConfidence(event.target.value)}\n                  />\n                </div>\n                <Button type="submit" disabled={!canSubmit || decide.isPending}>\n''',
    '''                <div>\n                  <label className="studio-label" htmlFor="review-confidence">判断置信度（0–1）</label>\n                  <Input\n                    id="review-confidence"\n                    type="number"\n                    min="0"\n                    max="1"\n                    step="0.05"\n                    value={confidence}\n                    onChange={(event) => setConfidence(event.target.value)}\n                  />\n                </div>\n\n                {showExceptions && reviewGroups.length > 1 ? (\n                  <div className="studio-stack">\n                    <div>\n                      <strong>逐组例外判断</strong>\n                      <p className="studio-muted">只有你明确启用的候选组才覆盖上面的默认判断。未启用的组继续使用默认判断；这里的分组不是身份结论。</p>\n                    </div>\n                    {reviewGroups.map((group, index) => {\n                      const draft = groupOverrides[group.review_group_id] ?? {\n                        enabled: false,\n                        decision: (decision || allowed[0] || "") as ReviewDecision | "",\n                        rationale: "",\n                        confidence: confidence || "0.5",\n                      };\n                      const names = group.right_contexts\n                        .map((context) => {\n                          const human = context as HumanReviewContext;\n                          return human.display?.name ?? context.record?.name ?? context.record?.title ?? context.ref;\n                        })\n                        .filter(Boolean);\n                      return (\n                        <Card key={group.review_group_id}>\n                          <CardHeader>\n                            <CardTitle>候选组 {index + 1}：{names.join("、") || "未命名记录"}</CardTitle>\n                            <CardDescription>{group.member_count} 个底层候选 · 组 ID {group.review_group_id}</CardDescription>\n                          </CardHeader>\n                          <CardContent className="studio-stack">\n                            {group.right_contexts.map((context) => (\n                              <EvidenceList key={`${group.review_group_id}:${context.bundle}:${context.ref}`} context={context as HumanReviewContext} />\n                            ))}\n                            <Button\n                              type="button"\n                              variant={draft.enabled ? "default" : "outline"}\n                              onClick={() => setGroupOverride(group.review_group_id, { enabled: !draft.enabled })}\n                            >\n                              {draft.enabled ? "取消此组例外，恢复默认判断" : "此组使用不同判断"}\n                            </Button>\n                            {draft.enabled ? (\n                              <div className="studio-form">\n                                <div>\n                                  <label className="studio-label" htmlFor={`group-decision-${group.review_group_id}`}>此组判断</label>\n                                  <select\n                                    id={`group-decision-${group.review_group_id}`}\n                                    className="studio-select"\n                                    value={draft.decision}\n                                    onChange={(event) => setGroupOverride(group.review_group_id, { decision: event.target.value as ReviewDecision })}\n                                  >\n                                    {allowed.map((value) => <option key={value} value={value}>{decisionLabel(value)}</option>)}\n                                  </select>\n                                </div>\n                                <div>\n                                  <label className="studio-label" htmlFor={`group-rationale-${group.review_group_id}`}>此组判断依据</label>\n                                  <textarea\n                                    id={`group-rationale-${group.review_group_id}`}\n                                    className="studio-textarea"\n                                    rows={3}\n                                    value={draft.rationale}\n                                    onChange={(event) => setGroupOverride(group.review_group_id, { rationale: event.target.value })}\n                                    placeholder="说明为什么这一候选组与批次默认判断不同，并引用上方逐字证据。"\n                                  />\n                                </div>\n                                <div>\n                                  <label className="studio-label" htmlFor={`group-confidence-${group.review_group_id}`}>此组置信度（0–1）</label>\n                                  <Input\n                                    id={`group-confidence-${group.review_group_id}`}\n                                    type="number"\n                                    min="0"\n                                    max="1"\n                                    step="0.05"\n                                    value={draft.confidence}\n                                    onChange={(event) => setGroupOverride(group.review_group_id, { confidence: event.target.value })}\n                                  />\n                                </div>\n                              </div>\n                            ) : null}\n                          </CardContent>\n                        </Card>\n                      );\n                    })}\n                  </div>\n                ) : null}\n\n                <Button type="submit" disabled={!canSubmit || decide.isPending}>\n''',
)

replace_once(
    DETAIL,
    '''                <div><dt>判断依据</dt><dd>{item.decision.rationale}</dd></div>\n                <div><dt>处理时间</dt><dd>{item.resolved_at ?? "—"}</dd></div>\n''',
    '''                <div><dt>判断依据</dt><dd>{item.decision.rationale}</dd></div>\n                {item.decision.group_decisions?.length ? (\n                  <div>\n                    <dt>逐组例外</dt>\n                    <dd>{item.decision.group_decisions.map((group) => `${group.review_group_id}：${decisionLabel(group.decision)}（${group.rationale}）`).join("；")}</dd>\n                  </div>\n                ) : null}\n                <div><dt>处理时间</dt><dd>{item.resolved_at ?? "—"}</dd></div>\n''',
)

print("R19 Studio exception workflow patch applied")
