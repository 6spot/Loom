---
task: C2-R1-T16
issue: 566
kind: leaf
parent: C2-R1
status: completed
depends_on: [C2-R1-T02, C2-R1-T04, C2-R1-T06]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at: 2026-09-09
completion_pr: 606
merge_sha: d5cd8b88c3b95f3adf7a27aa390f58012a44e496
---

# 空语料初始化、配置与第一轮CI路径覆盖

## Scope

[Issue #566](https://github.com/6spot/Loom/issues/566) owns the bounded implementation checklist. 真正用空开发环境开始，默认部署不暗中导入旧C0人物；新语料/合同/任务记录的变更也会触发正确CI。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [x] 新空目录启动后无旧C0 canonical数据，迁移/重复启动成功，public空态和Studio鉴权正常。
- [x] 显式C0回归仍可独立运行；migration-only与artifact导入互斥/参数错误明确。
- [x] provider预算配置从env传到现worker服务，没有秘密写进仓库。
- [x] corpus-only/ledger-only/schema-only变更触发正确检查，新测试确实运行；退休工作流不复活。

## Verification

- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_migrate_only_unit.py' -v` — 10 tests OK (DB-free: parser mutual exclusion, real `apply_migrations` replay against a fake connection, idempotent re-run, `chronicle.migration-run` report).
- `python3 -m unittest discover -s apps/chronicle/corpus -p 'test_first_round_pack.py' -v` — 11 tests OK.
- `python3 -m unittest discover -s apps/chronicle/persistence -p 'test_chapter_contract_unit.py' -v` — 42 tests OK (schema-side check wired in CI).
- `docker compose --env-file .env.chronicle.example -f compose.chronicle.yaml config` — validates OK (quiet); `git diff --check` clean.
- Fresh-stack docker run (throwaway `CHRONICLE_DATA_DIR`, image built from `apps/chronicle/Dockerfile`, then torn down): `chronicle-init` exit 0 with `chronicle migrate: PASS migrations=6`; DB holds 0 canonical entities/events/bundles with 6 recorded migration versions; container restart repeats only the migration with an identical report; `GET /healthz` 200; `GET /api/v1/public/timeline` and `/api/v1/public/search?q=曹操` return well-formed empty pages (`total: 0`); Studio `/api/v1/studio/jobs` returns 401 without/wrong credentials and 200 with the env-configured admin.
- `python3 tools/validator_ready.py --root docs/tasks/chronicle/first-round --check --format json` — currently errors on this root (`task C2-R1 has no status` after the Task Ledger non-authoritative normalization); not wired as a CI gate. Fixing `tools/validator_ready.py` is outside this task's file ownership — flagged in the delivery PR.
- DB-backed C0 regression (`test_real_dataset_postgres.py`) not re-run here: it requires the PG18 control service and is untouched by this change (still loads `.artifacts/c0-t7` explicitly into an isolated test database).

2026-09-09 — Post-merge reconciliation (delivery PR #606 MERGED as `d5cd8b88c3b95f3adf7a27aa390f58012a44e496` on 2026-09-09): front matter now carries actual start/completion_pr/merge_sha and all acceptance boxes are checked against the delivery evidence above. Post-merge spot checks on the T17 integration head: `docker compose --env-file .env.chronicle.example -f compose.chronicle.yaml config -q` — validates OK; `.github/workflows/ci.yml` first-round ledger routing (`chronicle_first-round` classify outputs) present; `git diff --check` — clean. Transitive note: T04/T06 ledger completion remains owned by their own deliveries (both code-merged on the default branch).

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Implemented: `--migrate-only` in `chronicle_persist.py` (+ `test_migrate_only_unit.py`); Compose init switched to migration-only; five `CHRONICLE_CHAPTER_*` budget envs passed through the worker service and documented in `.env.chronicle.example`; `deployment.md` rewritten for the fresh empty-state flow with an explicit C0 regression pointer; `ci.yml` gained first-round ledger routing plus a lightweight `chronicle-first-round` job (corpus/contract/note checks, no Rust/Postgres matrix). Retired C1 workflows not restored. `chronicle_persist.py`'s import path is backward compatible (`--catalog` still required without `--migrate-only`).
- 2026-09-09 — Reconciled post-merge (see Verification): PR #606 merged, acceptance checked.
