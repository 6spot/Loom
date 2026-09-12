import type { ChapterContentReviewData, ContentDraft } from "../../src/lib/chapter-content-review";
import type { ReviewDetail } from "../../src/lib/studio-api";

export function contentData(): ChapterContentReviewData {
  return {
    schema: "chronicle.chapter-content-review", version: "0.1",
    plan_fingerprint: "a".repeat(64), candidate_sha256: "b".repeat(64), history_sha256: "c".repeat(64),
    request_fingerprint: "d".repeat(64), pipeline_fingerprint: "e".repeat(64), step_output_sha256s: ["f".repeat(64)],
    candidate: { translation: { blocks: [{ block_id: "t_001", text: "第一段完整译文。" }, { block_id: "t_002", text: "第二段承接前文。" }] }, bundle: { entities: [{ temp_id: "e_1", name: "曹操" }] } },
    issues: [{ id: "subject", type: "processing_error", target: "/translation/blocks/0/text", message: "前后复核对主语提出相反意见", evidence: ["完整原文", "此前模型意见"] }],
    history: [{ index: 0, entry_sha256: "1".repeat(64), step: "review", model: "fixture-a", status: "completed" },
              { index: 1, entry_sha256: "2".repeat(64), step: "review", model: "fixture-b", status: "completed" }],
    history_count: 2, can_accept: true, validation_errors: [], source_scope: { body_block_ids: ["b_1"] },
    source: { context_id: "ctx-1", bundle: "", bundle_sha256: null, record_ref: "anc-1", link_kind: "chapter_content",
              job_id: "job-1", revision_id: "revision-1", chapter_id: "chapter-1", chapter_index: 0, chapter_title: "先主传",
              artifact_sha256: "3".repeat(64), source_title: "三国志", source_sha256: "4".repeat(64), evidence_kinds: ["record_source"],
              available: true, unavailable_reason: null, anchor_count: 1, anchors: [{ anchor_id: "anc-1", chapter_id: "chapter-1", start: 0, end: 20, quote_sha256: "5".repeat(64) }] },
    decision: null,
    patch_targets: [{ path: "/translation/blocks/0/text", before_sha256: "6".repeat(64), label: "第1段译文" },
                    { path: "/translation/blocks/1/text", before_sha256: "7".repeat(64), label: "第2段译文" },
                    { path: "/bundle/entities/0", before_sha256: "8".repeat(64), label: "人物 · 曹操" }],
  };
}

export function contentItem(): ReviewDetail {
  return {
    review_id: "review-1", job_id: "job-1", chunk_id: "chunk-1", status: "open", job_status: "needs_review", kind: "stage_gate",
    created_at: "2026-09-13T01:00:00Z", resolved_at: null, scope: "chapter_content", revision_id: "revision-1",
    document: { document_id: "document-1", title: "先主传", revision_no: 1, filename: "source.txt", source_sha256: "4".repeat(64), language: "lzh", source_label: "fixture" },
    allowed_decisions: ["accept", "revise", "reject"], blocking: true, chapter_content: contentData(),
    job_open_resolution_reviews: 2, candidate_id: "chapter-1", resolution_sha256: "", link_kind: "entity",
    left: { bundle: "", ref: "" }, right: { bundle: "", ref: "" }, suggestion: { decision: "uncertain", confidence: null, signals: [], rationale: null }, decision: null,
    left_context: {} as ReviewDetail["left_context"], right_context: {} as ReviewDetail["right_context"],
  };
}

export function readyDraft(): ContentDraft {
  return { rationale: "已查阅完整原文和两轮复核意见", dispositions: { subject: { disposition: "rejected", rationale: "根据完整原文，当前版本保持正确主语" } }, edits: {} };
}
