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

2026-09-09/10 — Live round on `855a1dc` (prompt v6 + anchor-miss fork hints; still NOT_PASSED):

- 通鑑卷65 republished as `01a08753` (64 translation blocks, 14984 chars, head/tail complete) and verified in a REAL headless-chromium render (DOM 17413 chars, 64 segments, revision-pinned, per-block 原文 links; screenshot archived). Reader API + browser both green for the second book.
- SG job 1: all 3 chunks extracted+assembled; 7 same-revision cross-chapter entity pair reviews opened, all decided `same_entity` by the operator against 原文 (5 defaults + 2 script-variant exceptions with recorded rationales), resolve completed; publish then failed closed with `publication_plan_stale` (ZZ had published first — frozen plans never rebase by design, verified in code). Job kept as terminal evidence; SG job 2 opened on the same pinned revision.
- Live worker restart/takeover: SIGTERM graceful (`signal 15; finishing current step`), new instance reclaimed the 300s lease, job continued — log archived. Cost: one job-claim consumed from the 3-claim bounded budget.
- SG job 2: chunks 0+1 passed, chunk 2 missed by 4 anchor/alias cases; claims exhausted → Studio retry refused by design (`attempt 3 >= max_attempts 3`, bounds not loosened). SG job 3 opened on the same revision; 13 cases stay `pending`.

2026-09-10 — Leader-directed evidence remediation + live round on `5024be1` (recall observability; still NOT_PASSED):

- B1: acceptance §1–§6 marked historical baseline (`b611c33`, pre-live); new authoritative §0 current-candidate summary (single auditable mouth); 结论前置 rewritten to current state.
- B2: §12 rewritten — all rows are operator observations (not counted); independent-conclusion mouth stays 0/13 with recall gaps preserved; no PASS wording.
- B3: pair-decision/review snapshots reconciled — `reviews-sg-open.json` labeled pre-decision historical; FINAL API snapshots (`job-sanguozhi-1-FINAL.json` + 7 `*-FINAL.json`, 7/7 resolved/same_entity) + `review-snapshot-reconciliation.md` with reproducible command archived server-side.
- B4: owning-layer recall decision implemented + formally documented (acceptance §13): hard floors rejected (gameable, sparse-chapter false positives, `passed`/`count` unchanged); `bundle_recall_observations` added to the validation report (v0.1→0.2, API-visible via existing projection); `RecallObservationsTests` green with contract/extraction/wiring/gate suites; skeletal-bundle negatives retained.
- B5 live round (port 8086, model `gpt-5.6-luna`): recall verified live (SG chunk-0 correction: 10 entities/0.79 per-1000, 16519-char translation); SG job completed all 8 stages and published 3 chapters (`01a088b2`: 先主傳 10ent/7evt, 周瑜傳 20ent/10evt, 魯肅傳 23ent/11evt/6clm — all Traditional names) after 22/22 pair decisions (19 persons + 3 places) + resume; ZZ job completed and published (`01a088e7`, 64 blocks) after 1 cross-book batch decision (曹操 same_entity — second-source coverage); 4-chapter Reader API + real-chromium renders (screenshots + DOM head/tail asserts) all green. Old failures preserved; bounds untouched; 13 cases stay `pending` for independent review.

2026-09-10 — Remaining-blocker remediation (still NOT_PASSED):

- B1: 22 pair + 1 batch FINAL snapshots archived on `5024be17` (`reviews-FINAL/` 22/22 resolved/same_entity, batch FINAL, both jobs FINAL) + `review-snapshot-reconciliation.md` with rerun commands; historical `855a1dc0` mapping documented.
- B2: `manual-content-review.json` blockers rewritten to current unfinished items + candidate `5024be17`; 13 pending / 0/13 / verdict `not_passed` preserved.
- B3: PR #614 body rewritten to historical-plus-current `5024be17` NOT_PASSED summary; zero close-intent lines; markers kept.
- B4: Studio real-browser flow closed — node + playwright chromium installed on the test server (env only, not committed); canonical `chapter-reader-smoke.mjs` PASSES on all 4 published chapters (64/43/16/10 blocks, source-panel open/expand/close, direct-open/refresh/mobile); Studio `/studio/review` login gate verified, authenticated queue shows 0 pending and the decided trail (`已选择：同一实体`), screenshots archived. Second ZZ import deepened the matrix: 12 reviews decided (10 same_entity + 2 event same_occurrence), then publish failed closed on published-canonical stability (`would collapse existing canonical IDs`) — recorded as terminal evidence without softening decisions. Retained blockers: all-unresolved mentions modeling, thin systematic batch matrix, pending independent 13-case review.

2026-09-10 — Single-narrative remediation (still NOT_PASSED):
- §12 corrected: FINAL paths/counts now match `5024be17` (22-pair + 1-batch FINALs; ZZ2 12-review round); C04/C05/C06 rewritten as current-vs-history (855a1dc0 clearly historical); 劉備-triangle IDs pinned per round. §0 pointer extended to §12–§17.
- 13 cases verified still all pending (0/13, verdict `not_passed`); unresolved chapter mentions explicitly retained as a content blocker (JSON + §12 + §16).
- Cross-book matrix explicitly defined (§16 exists-vs-missing table): 1 published batch + 12 decided-unpublished + import-level second source exist; systematic matrix, post-publish event merges, within-chapter co-reference modeling are missing. Never called a complete loop.
- Studio browser boundary precisely documented (§17): canonical reader smokes (real backend) + real-UI reads (ad-hoc driver) + API decisions vs mocked review-flow smoke kept distinct; browser decision-click recorded as the unmet blocker.

## Progress Log

- 2026-09-08 — Planned under #548 with explicit dependencies and file ownership. No implementation or completion claim.
- 2026-09-09 — Started: added `apps/chronicle/corpus/first-round/acceptance.md` (live record, verdict NOT_PASSED) and `manual-content-review.json` (desensitized per-case index, 13 pending + 1 synthetic n/a, no secrets). Acceptance boxes stay unchecked; `completed_at`/`merge_sha` empty until a real live pass. #549/#550 untouched.

2026-09-10 — Substantive round on `a517dcd`/`0bb5c6a` (still NOT_PASSED):

- Batch-recall investigation: cross-book candidate blocking needs shared stable surfaces; 魯肅/程普/黃蓋/夏口 missing from ZZ bundles is extraction recall on the ZZ side, not a blocking-logic miss. No code change (cannot script model answers); recorded.
- Prompt v7 (prefer resolved over hedged unresolved) verified live: published chapters' mentions resolved 12/12, 19/19, 8/10 (was 0 everywhere); 先主→ent_001 劉備 and 11 more span-copy linkages recorded (C01 bundle evidence, first time).
- Temp-ID fail-fast fix (prompt v8 + validator mirror of assembler 000–999 rule) after live `ent_1001` killed a job at assemble; 99 unit + 15 gate tests green.
- Genuine Studio browser decision-clicks: ad-hoc playwright driver logged in, opened/filled/submitted all 27 reviews (22 same-revision + 5 cross-book incl. 1 event same_occurrence) with 34 before/after screenshots; API verified 0 open; FINAL snapshots 27/27; job completed and published SG (`01a08997`).
- Hollow/condensed translation findings (content failures, published artifacts retained): v7 先主傳 2412 chars/0.192 (孫權 x0), v8 ZZ 2808/0.26, v8 周瑜傳 3182/0.63 with dropped subplots (左右督任命/陳就/蘇飛) and 公瑾 normalization; v8 先主傳 (16516/1.31) and 魯肅傳 (5155/1.43) full. Recall section makes hollowness visible; no fidelity gate added (recorded §13 philosophy).
- 13 cases stay pending (0/13); verdict NOT_PASSED; nothing closed.

2026-09-10 — v8 audit-narrative sync (still NOT_PASSED):

- PR body, `manual-content-review.json` B2–B5, §12 (method note, C01–C07/C11–C13 rows, negative findings), §16 matrix table, and §17 browser boundary all synchronized to v8 current (`0bb5c6a`): published SG `01a08997` (ch0 16516/1.31 full, ch1 3182/0.63 with dropped subplots, ch2 5155/1.43) + ZZ `01a08975` (2808/0.26 hollow); mentions resolved 12/12, 19/19, 8/10 with 先主→ent_001 linkage; 27/27 browser decision-clicks (22 same-revision incl. 1 event + 5 cross-book); hollow/condensed findings retained as content failures; 5024/855a1dc0 rounds explicitly historical.
- 13 cases stay pending (0/13, verdict `not_passed`); cross-book/event-merge gaps, hollow chapters, and canonical-script review-flow coverage remain blockers; nothing closed.

2026-09-10 — v8 full-sync follow-up (still NOT_PASSED):

- Canonical chapter-reader smokes PASS on all 4 v8 chapters (43/16/10/62 blocks) plus headless-chromium DOM head/tail asserts (18718/4510/6666/4762 chars) and screenshots; rendering/content separation explicitly recorded (hollow chapters still render).
- JSON B2–B5, §12 rows/findings, §16 matrix, §17 boundary, PR body all synchronized to v8 current (mention linkage 12/12·19/19·8/10, 27/27 browser clicks, hollow failures); 5024/855a1dc0 explicitly historical.
- 13 cases stay pending (0/13); verdict NOT_PASSED; nothing closed.
