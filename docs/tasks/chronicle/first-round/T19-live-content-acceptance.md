---
task: C2-R1-T19
issue: 569
kind: leaf
parent: C2-R1
status: in_progress
depends_on: [C2-R1-T18]
created_at: 2026-09-08
started_at: 2026-09-09
completed_at:
completion_pr:
merge_sha:
---

# 真实模型、逐章内容核对与第一轮最终验收

## Scope

[Issue #569](https://github.com/6spot/Loom/issues/569) owns the bounded implementation checklist. 证明真实古文的完整翻译、身份关联、来源核对和连续审核可用，再结束第一轮；不以JSON合法或脚本PASS代替内容验收。

Long-lived contracts: [chapter production](../../../../apps/chronicle/docs/chapter-production.md), [review workflow](../../../../apps/chronicle/docs/review-workflow.md). Ownership and parallel eligibility: [initiative index](README.md).

## Acceptance

- [ ] 真实两书四章全部内容核对，至少12定位案例有独立结论，无已知未解决关键内容错误。
- [ ] 实际完整章模型输出满足预算，运输/语义修正次数、用量和耗时被记录，未宣称未经测量正确率。
- [ ] 真实导入→审核→发布→阅读全文→原文完整闭环及故障/版本观察都有可追溯证据。
- [ ] 19叶所有实际完成记录、PR/merge/验收/CI及根索引一致后才关闭#548。

## Verification

2026-09-09 — Partial delivery (evidence scaffolding + honest NOT_PASSED record; live content acceptance NOT executed):

- `python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_first_round_gate.py' -v` — 12 tests OK on candidate `b611c33`.
- `python3 apps/chronicle/acceptance/first_round_gate.py --mode fixture --env-file /tmp/chronicle-first-round-test.env --source-pack apps/chronicle/corpus/first-round/source-pack.json --evidence-dir /tmp/chronicle-first-round-offline --allow-dirty` — PASS (2 works, 10 faults fail-closed). Explicitly `fixture_only`, NOT live content proof.
- live probe `--mode live ... < /dev/null` — FAIL as designed: `live mode requires an interactive terminal` (fail-closed without an operator; no provider call made).
- New files validate: `manual-content-review.json` parses, 14 case ids match `cases.json` 1:1, both ingest SHAs match `ingest-manifest.json`; `git diff --check` clean.
- `python3 tools/validator_ready.py --root docs/tasks/chronicle/first-round --check --format json` — still reports `task C2-R1 has no status` (pre-existing root-level issue recorded by T16, fix outside this task's file ownership).
- NOT run (blocked, no fabrication): real provider calls, Studio interactive reviews, restart/takeover, publish/public reading, two-revision pinning, browser observations, independent per-chapter content conclusions (13 cases stay `pending`), usage/timing budgets. Verdict `not_passed`; see `apps/chronicle/corpus/first-round/acceptance.md` §4–§6 for the blocker list and the live rerun checklist.

2026-09-09 — Production wiring fix (live READY reached, real execution found the worker never receives `CHRONICLE_CHAPTER_MODEL`; Issue stays `in_progress`, no PASS/completion claim):

- `compose.chronicle.yaml`: pass `CHRONICLE_CHAPTER_MODEL: ${CHRONICLE_CHAPTER_MODEL:-}` into `chronicle-worker` (same fail-soft convention as extraction/presentation; worker fails closed at startup without it).
- `.env.chronicle.example`: document `CHRONICLE_CHAPTER_MODEL` alongside the other two model entries.
- `apps/chronicle/acceptance/first_round_gate.py`: live preflight now requires `CHRONICLE_CHAPTER_MODEL` and records `provider.chapter_model`; READY can no longer be issued for a deployment that cannot execute the joint chapter pipeline.
- `apps/chronicle/docs/chapter-acceptance.md` §2: live env fill-in list now includes `CHRONICLE_CHAPTER_MODEL`.
- Focused tests (`test_first_round_gate.py`, 12→15): missing chapter model fails preflight; READY records the chapter model identity; compose YAML parses with the worker passthrough present.
- Verification on this branch: 15 gate tests OK; fixture gate PASS (2 works/10 faults, non-live); `docker compose --profile worker config` renders the model value when set and `""` when unset; 16 worker wiring/budget tests OK; `git diff --check` clean; `validator_ready.py` still only the known pre-existing root `C2-R1 has no status`.
- After merge, T19 freezes a new candidate and reruns live acceptance; 13 cases stay `pending` until independent review.

2026-09-09 — Live verification round on `ffc58aa` (test server, model `gpt-5.6-luna`; still NOT_PASSED, no completion claim):

- Root causes from the real 先主传 chunk-0 failure evidence (5 extract runs, prompts v1→v3, all fail-closed, old runs preserved):
  diagnostics masked record ids (`ent_*` collapse); model prepended inherited years into `time.original_text`; claim object shape untaught; T01 schema-vs-check literal self-contradiction; `chapter_failed` logged `error: None`; chapter provider ignored `CHRONICLE_MODEL_TIMEOUT_SECONDS`; no per-call latency.
- Owning-layer fixes (346 persistence + 105 worker + 15 gate unit tests OK; `git diff --check` clean; replay of the real attempt-2 candidate: 22→17 errors, 5 claim false positives gone, fail-closed retained):
  `chapter_prompt.py` (ids kept, VERBATIM GROUNDING PROCEDURE, claim shape, v3), `chapter_contract.py` (literal aligned to schema `{kind,value}`), `chapter_extraction.py` (`latency_ms`), `chapter_stage.py` (real `chapter_failed` error — verified in production logs; timeout passthrough), `model_provider.py` (`timeout_from_env`), focused tests incl. `test_chapter_stage_wiring_unit.py` and claim-shape pins.
- Live usage (chunk 0): prompts ~39k→78k chars, ~147–422s per call, zero transport errors (successful-path internal transport retries not instrumented — recorded gap, no numbers invented).
- Best runs reach 4→1 and 9→2 errors; the stubborn remainder is anchor misattribution (real quote/wrong block; invented quote such as 先主留張飛守下邳 with 0 chapter hits) — validator correctly fail-closed every time. Jobs `75f34121` (needs_review) and `db2980b9` (failed, 1 retry left) preserved; server evidence at `/srv/loom-t19-evidence/ffc58aa/`.
- Still open: 通鑑 second book, Studio human review, publish, Reader reading, restart/takeover evidence, 13-case independent conclusions (all `pending`). PR #614 updated; awaiting independent review, not marked PASSED.

2026-09-09 — Live rounds on `0410b15` → `26eb34c` → `9902a37` → `23da90b` (test server, model `gpt-5.6-luna`; still NOT_PASSED, no completion claim):

- Rebased onto origin/main (merged upstream `#615` GitHub-Issue support with this branch's `Multica-No-Close` opt-out); PR #614 is MERGEABLE again with all CI green and no `Closes` intent in body. Each round uses a fresh candidate, fresh compose project (ports 8081→8084), fresh data dir, fresh evidence dir `/srv/loom-t19-evidence/<SHORT>/`; old failed runs/jobs preserved untouched.
- Owning-layer fixes driven by real failures (focused tests each; contracts only tightened): equality diagnostics carry both values (`chapter_contract.py`, prompt stays); prompt v4 pins entity `resolution:{status:"unresolved"}` in guide + validator fail-fast (was: model invented `'new'`, passed validation, died at assemble); prompt v5 adds verbatim script-consistency (was: Simplified surfaces/quotes vs Traditional source); prompt v6 (pushed `558c4bd`, not yet live) defines surface as occurrence-text copy with examples.
- Real outcomes: 26eb34c1 SG chunks 0/1 pass initial-5→correction-0; 9902a374 通鑑卷65 completes all 8 stages and publishes (publication `01a086d0`, full 14362-char translation verified head/tail via Reader API, SHAs archived) — first full single-chapter loop; SG chunk 0 (先主傳) resists across 3+1 (v4) and 3 (v5) runs with shrinking-but-varying misses (surface class eliminated by v5, stubborn anchors remain), all fail-closed; two supervised chunk_failure resolve+resume cycles executed with recorded operator rationales (return-path evidence). 13 cases stay `pending`; cross-chapter pair review, restart/takeover, and browser Reader checks still open.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Started: added `apps/chronicle/corpus/first-round/acceptance.md` (live record, verdict NOT_PASSED) and `manual-content-review.json` (desensitized per-case index, 13 pending + 1 synthetic n/a, no secrets). Acceptance boxes stay unchecked; `completed_at`/`merge_sha` empty until a real live pass. #549/#550 untouched.
