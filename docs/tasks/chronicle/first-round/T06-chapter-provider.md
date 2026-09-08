---
task: C2-R1-T06
issue: 556
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T01]
created_at: 2026-09-08
started_at: 2026-09-08
completed_at:
completion_pr:
merge_sha:
---

# 真实模型与fixture适配新的联合输出协议

## Scope

[Issue #556](https://github.com/6spot/Loom/issues/556) owns the bounded implementation checklist. 生产模型实际收到章级structured-output约束和输出预算，fixture也走同一形状，避免后台仍要求旧的小块bundle。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 实际HTTP请求携带联合schema和output token限制，无程序生成offset/canonical字段。
- [ ] 正常、incomplete/length、无文本、超byte cap、运输重试耗尽全部有明确测试。
- [ ] fixture与live走相同模型candidate形状；生产配置不会静默落入fixture。
- [ ] 旧人物/事件简介provider回归不变，密钥不泄露。

## Verification

2026-09-08 — Implementation on branch `agent/executor/d5cf2794fa51`, awaiting review/merge (delivery PR only; no completion claim yet):

- `python3 -m unittest discover -s apps/chronicle/worker -p 'test_*model*_unit.py'` — **56 tests OK** (33 pre-existing + 23 new chapter/provider/fixture tests).
- `python3 -m unittest discover -s apps/chronicle/worker -p 'test_fixture_model_unit.py'` — **16 tests OK**.
- `python3 tools/check_architecture.py` — **OK** (includes storage SQL ownership gate).
- `python3 tools/check_storage_sql_ownership.py` — **passed**.
- `test_worker_model_wiring_unit.py` — **OK** (worker entry untouched).
- `git diff --check` — **clean**.
- No Postgres/DB tests: change is provider/schema/fixture pure functions + mocked HTTP only (no DB, migration, network). No UI change, so no test/build/smoke:dist applies.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-08 — Implemented chapter-candidate strict projection (`chapter_candidate_model_schema`/`chapter_candidate_text_format`, model-generatable fields only, T01 canonical validator remains acceptance authority), chapter provider envelope (`max_output_tokens` default 65536, 4 MiB default response cap, incomplete/length/refusal fail-closed, transport retry + credential isolation retained), and explicit chapter fixture pack/model (chapter_id + request-fingerprint binding, full translation/structure, no silent fallback). Only the six T06-owned worker files changed; worker entry/env/Compose left to T13/T16. T01 code dependency consumed from default branch merge 0b70308 (PR #590); T01 ledger reconciliation still pending, tracked by coordinator.
