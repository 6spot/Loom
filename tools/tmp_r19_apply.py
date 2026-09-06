#!/usr/bin/env python3
"""Temporary R19 patch applicator for the implementation branch only."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Persistence: allow one batch default plus explicit per-group exceptions.
# ---------------------------------------------------------------------------
replace_once(
    "apps/chronicle/persistence/resolve_publish.py",
    '''def resolve_resolution_review(\n    conn,\n    *,\n    review_id: uuid.UUID,\n    decision: str,\n    rationale: str,\n    confidence: float = CONFIDENCE_INITIAL_UNCERTAIN,\n) -> None:\n''',
    '''def resolve_resolution_review(\n    conn,\n    *,\n    review_id: uuid.UUID,\n    decision: str,\n    rationale: str,\n    confidence: float = CONFIDENCE_INITIAL_UNCERTAIN,\n    group_decisions: list[dict[str, Any]] | None = None,\n) -> None:\n''',
)
replace_once(
    "apps/chronicle/persistence/resolve_publish.py",
    '''    decided["decision"] = {\n        "decision": decision,\n        "confidence": float(confidence),\n        "rationale": rationale.strip(),\n    }\n''',
    '''    decided["decision"] = {\n        "decision": decision,\n        "confidence": float(confidence),\n        "rationale": rationale.strip(),\n    }\n    normalized_group_decisions = review_subjects.normalize_group_decisions(\n        payload, group_decisions\n    )\n    if normalized_group_decisions:\n        decided["decision"]["group_decisions"] = normalized_group_decisions\n''',
)

# ---------------------------------------------------------------------------
# Studio read API: expose group counts/context and accept exception decisions.
# ---------------------------------------------------------------------------
replace_once(
    "apps/chronicle/read_api/studio_reviews.py",
    '''        "member_count": int(payload.get("member_count") or 1),\n        "members": list(payload.get("members") or []),\n''',
    '''        "member_count": int(payload.get("member_count") or 1),\n        "group_count": int(payload.get("group_count") or 1),\n        "groups": list(payload.get("groups") or []),\n        "members": list(payload.get("members") or []),\n''',
)
replace_once(
    "apps/chronicle/read_api/studio_reviews.py",
    '''    item["right_contexts"] = [\n        _side_context(conn, side, link_kind=link_kind) for side in right_refs\n    ]\n    open_count = conn.execute(\n''',
    '''    item["right_contexts"] = [\n        _side_context(conn, side, link_kind=link_kind) for side in right_refs\n    ]\n    review_groups: list[dict[str, Any]] = []\n    for raw_group in item.get("groups") or []:\n        if not isinstance(raw_group, dict):\n            continue\n        group_id = raw_group.get("review_group_id")\n        members = raw_group.get("members") or []\n        if not isinstance(group_id, str) or not isinstance(members, list):\n            continue\n        group_refs: list[dict[str, str]] = []\n        seen: set[tuple[str, str]] = set()\n        for member in members:\n            side = member.get("right") if isinstance(member, dict) else None\n            if not isinstance(side, dict):\n                continue\n            bundle, ref = side.get("bundle"), side.get("ref")\n            if not isinstance(bundle, str) or not isinstance(ref, str):\n                continue\n            key = (bundle, ref)\n            if key in seen:\n                continue\n            seen.add(key)\n            group_refs.append({"bundle": bundle, "ref": ref})\n        review_groups.append(\n            {\n                "review_group_id": group_id,\n                "member_count": int(raw_group.get("member_count") or len(members)),\n                "signals": list(raw_group.get("signals") or []),\n                "right_contexts": [\n                    _side_context(conn, side, link_kind=link_kind)\n                    for side in group_refs\n                ],\n            }\n        )\n    item["review_groups"] = review_groups\n    open_count = conn.execute(\n''',
)
replace_once(
    "apps/chronicle/read_api/studio_reviews.py",
    '''        confidence = payload.get("confidence", resolve_publish.CONFIDENCE_INITIAL_UNCERTAIN)\n        if not isinstance(decision, str):\n''',
    '''        confidence = payload.get("confidence", resolve_publish.CONFIDENCE_INITIAL_UNCERTAIN)\n        group_decisions = payload.get("group_decisions")\n        if group_decisions is not None and not isinstance(group_decisions, list):\n            raise _BadRequest("group_decisions must be an array when given")\n        if not isinstance(decision, str):\n''',
)
replace_once(
    "apps/chronicle/read_api/studio_reviews.py",
    '''            rationale=rationale,\n            confidence=confidence,\n        )\n''',
    '''            rationale=rationale,\n            confidence=confidence,\n            group_decisions=group_decisions,\n        )\n''',
)

# ---------------------------------------------------------------------------
# TypeScript API contract for review batches and per-group overrides.
# ---------------------------------------------------------------------------
replace_once(
    "apps/chronicle/webapp/src/lib/studio-api.ts",
    '''export interface ReviewChosenDecision {\n  decision: ReviewDecision;\n  confidence: number;\n  rationale: string;\n}\n''',
    '''export interface ReviewGroupDecisionInput {\n  review_group_id: string;\n  decision: ReviewDecision;\n  confidence: number;\n  rationale: string;\n}\n\nexport interface ReviewChosenDecision {\n  decision: ReviewDecision;\n  confidence: number;\n  rationale: string;\n  group_decisions?: ReviewGroupDecisionInput[];\n}\n''',
)
replace_once(
    "apps/chronicle/webapp/src/lib/studio-api.ts",
    '''export interface ReviewSummary {\n''',
    '''export interface ReviewGroupDetail {\n  review_group_id: string;\n  member_count: number;\n  signals: string[];\n  right_contexts: ReviewRecordContext[];\n}\n\nexport interface ReviewSummary {\n''',
)
replace_once(
    "apps/chronicle/webapp/src/lib/studio-api.ts",
    '''  member_count?: number;\n  members?: ReviewCandidateMember[];\n''',
    '''  member_count?: number;\n  group_count?: number;\n  groups?: unknown[];\n  members?: ReviewCandidateMember[];\n''',
)
replace_once(
    "apps/chronicle/webapp/src/lib/studio-api.ts",
    '''  right_contexts?: ReviewRecordContext[];\n  job_open_resolution_reviews: number;\n''',
    '''  right_contexts?: ReviewRecordContext[];\n  review_groups?: ReviewGroupDetail[];\n  job_open_resolution_reviews: number;\n''',
)
replace_once(
    "apps/chronicle/webapp/src/lib/studio-api.ts",
    '''export async function submitReviewDecision(\n  auth: string | null,\n  reviewId: string,\n  decision: ReviewDecision,\n  rationale: string,\n  confidence = 0.5,\n): Promise<ReviewDetail> {\n''',
    '''export async function submitReviewDecision(\n  auth: string | null,\n  reviewId: string,\n  decision: ReviewDecision,\n  rationale: string,\n  confidence = 0.5,\n  groupDecisions: ReviewGroupDecisionInput[] = [],\n): Promise<ReviewDetail> {\n''',
)
replace_once(
    "apps/chronicle/webapp/src/lib/studio-api.ts",
    '''      body: JSON.stringify({ decision, rationale, confidence }),\n''',
    '''      body: JSON.stringify({\n        decision,\n        rationale,\n        confidence,\n        group_decisions: groupDecisions,\n      }),\n''',
)

# Queue copy/counts: one row is now a batch, not a proven equivalence class.
replace_once(
    "apps/chronicle/webapp/src/pages/studio/StudioReviewPage.tsx",
    '''            系统只组织候选与证据，不替你决定历史身份。相同语义簇只审核一次；“证据不足，暂不确定”始终不会触发合并。\n''',
    '''            系统把指向同一已发布身份/事件的重复问题组织成审核批次，但批次本身不代表同一身份；“证据不足，暂不确定”始终不会触发合并。\n''',
)
replace_once(
    "apps/chronicle/webapp/src/pages/studio/StudioReviewPage.tsx",
    '''              const members = review.member_count ?? 1;\n              return (\n''',
    '''              const members = review.member_count ?? 1;\n              const groups = review.group_count ?? 1;\n              return (\n''',
)
replace_once(
    "apps/chronicle/webapp/src/pages/studio/StudioReviewPage.tsx",
    '''                      {members > 1 ? `该审核主题合并了 ${members} 个底层候选` : "1 个底层候选"}\n''',
    '''                      {groups > 1 ? `该审核批次包含 ${groups} 个来源候选组 / ${members} 个底层候选` : members > 1 ? `1 个来源候选组 / ${members} 个底层候选` : "1 个来源候选组 / 1 个底层候选"}\n''',
)

print("R19 review batching patch applied")
