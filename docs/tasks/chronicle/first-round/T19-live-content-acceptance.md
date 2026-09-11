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

2026-09-10 — SG3/ZZ3 substantive round (still NOT_PASSED):

- Two 魯肅傳 unmodeled mentions dispositioned: temporal expressions (建安二十二年/十九年) with no entity referent; unresolved+null is correct restraint (query evidence), not a miss.
- SG3 (2nd SG import, same frozen bytes): 3 chunks attempt-1 pass; 43 reviews (15 within-revision + 23 same-source re-import consistency + 5 cross-book incl. 1 event), side semantics corrected before clicking; 43/43 genuine browser decision-clicks (86 screenshots) with 36 same_entity + 6 same_occurrence + 1 related_occurrence (南郡 campaign vs 江陵 capture — first C07-principle application); job completed and published `01a089d6`.
- ZZ3 (2nd ZZ import): 3 bounded + 2 supervised runs; 7 reviews spanning three corpus bundles (2 cross-book 周瑜/諸葛亮 + 5 multi-bundle); 7/7 browser clicks; job completed and published `01a08a13` (event merge published this time — contrast with ZZ2 retained, not unified).
- Hollow persistence: SG3 先主傳 4658/0.37 condensed (key terms present); SG3 周瑜傳 7108/1.41 fixes v8r1 gaps (公瑾15×, 左右任命 present); ZZ3 9804/0.91 near-full with all previously-missing entities; canonical smokes 4/4 + DOM asserts; every chapter has ≥1 full translation across evidence but no single publication is all-full.
- 13 cases stay pending (0/13); verdict NOT_PASSED; nothing closed.

2026-09-10 — Canonical audit index synced to SG3/ZZ3 (still NOT_PASSED):

- `manual-content-review.json` B2–B5 rewritten: SG3 43-review + ZZ3 7-review browser decisions, publications `01a089d6`/`01a08a13`, correct unresolved time-expression disposition (建安二十二年/十九年), current hollows (SG3 先主傳 4658/0.37; SG3 周瑜傳 7108 fixes v8 r1; ZZ3 9804/0.91), prior v8 values marked historical; 13 pending / 0/13 preserved.
- §12 method/reconciliation notes, C01–C07/C11 rows, negative findings, top conclusion, and §16 matrix table all updated to SG3/ZZ3 current with v8-first marked historical; canonical review-flow retained mocked-only; matrix/event-merge gaps retained.
- Consistency: JSON parses, 14 cases 1:1, 13 pending, `git diff --check` clean, gate 15 tests OK.

2026-09-10 — §17 browser-boundary sync (still NOT_PASSED):

- §17 now records SG3 43/43 + ZZ3 7/7 genuine Studio browser decision-clicks (100 before/after screenshots, final states 43/43 and 7/7, API 0-open) as the current record; v8-first 27 clicks and the 23+12 API traces explicitly historical; canonical review-flow-smoke.mjs retained mocked-only. SG3 4658/0.37 condensed, 13 pending/0/13, matrix/event-merge gaps (ZZ2 fail-closed + ZZ3 success) preserved; nothing closed.

2026-09-10 — v10 content-complete round (still NOT_PASSED):

- Root cause + fix for condensed corrections: bounded correction re-asks regressed full initial translations (16404→7318, 16906→6139, 13551→2663; SG3 4658/0.37) yet passed structural validation. Prompt v10 requires copying the previous translation blocks through unchanged; measured fix (ZZ 14353→14353, SG 11974 preserved). Focused tests added; extraction 36 tests OK.
- Four-chapter content-complete evidence on `7e637dd`: SG `01a08a8e` (先主傳 11974/0.95, 周瑜傳 7177/1.43, 魯肅傳 5224/1.45) + ZZ `01a08a66` (14353/1.34), artifact hashes recorded; canonical smokes 4/4 + real-chromium DOM head/tail + screenshots. Rendering/smoke does not substitute review.
- Hollow-pass dispositioned per chapter-production.md §96: a 1803-char initial candidate passed structural validation (job b0c5e3c6, cancelled pre-publish, run evidence kept); no length gate added; 13 cases carry the completeness judgment.
- Event-merge semantics documented: ZZ2 fail-closed (two existing canonical IDs would collapse), ZZ3 and ZZ-v10 joins published; both terminal outcomes retained.
- 13 cases stay pending (0/13); verdict NOT_PASSED; canonical review-flow retained mocked-only; nothing closed.

2026-09-10 — v10 audit-surface reconciliation (still NOT_PASSED):

- acceptance top conclusion and §0 pointer synced to v10 `7e637dd` (four-chapter content-complete); §12/§16/§17 v8/SG3 wording explicitly relabeled historical (v10 in §20). No stale "无单 publication 四章全完整" / SG3-as-current.
- PR body current summary + 内容/验证 sections synced to v10 (candidate 7e637dd, prompt v10, extraction 36); SG3/ZZ3 bullets marked historical; zero close-intent.
- canonical index `manual-content-review.json`: added `evidence_notes` labeling `job-sg2-FINAL.json` as the pre-decision needs_review snapshot and `job-sg2-resumed.json` as the 21/21-resolved terminal record; candidate `7e637dd`; 13 pending / 0/13 / reviewer empty / `not_passed` preserved.
- Consistency: JSON parses, 14 cases 1:1, 13 pending, no stale v8-current strings, `git diff --check` clean, gate 15 + contract/extraction/wiring 101 tests OK.

2026-09-10 — v10 real-browser review round + systematic matrix (still NOT_PASSED):

- Real-browser review-flow evidence on current candidate 7e637dd: SG job 5ee49e77 (3 chunks; resolve opened 43) 43/43 and ZZ job 3417517d 1/1 decided via ad-hoc playwright open/fill/submit (window.confirm), 88 before/after screenshots, API open 0, FINAL 43/43 + 1/1; publications 01a08b08 (先主傳 16312/1.30, 周瑜傳 7068/1.41, 魯肅傳 5169/1.44) and 01a08ad9 (14718/1.37); canonical reader smoke 4/4.
- Systematic cross-book matrix documented (§21): covered = same-revision, published-bundle↔import consistency, cross-book SG↔ZZ entity/event, three-bundle transitivity, same-source re-import, event same_occurrence + related_occurrence (fa3fd04c non-merge); missing = exhaustive source-pair×kind matrix and matrix-level pass/fail criterion retained.
- Event-merge: ZZ2 fail-closed; ZZ3/ZZ-v10/v10-browser joins published; general rule deferred, both terminal outcomes retained.
- canonical review-flow-smoke.mjs retained mocked-only; 13 cases stay pending (0/13, reviewer empty, not_passed); nothing closed.

2026-09-10 — canonical index current/history repair (still NOT_PASSED):

- manual-content-review.json blockers B2/B5/B6 (+B4) synced: current = browser round publications 01a08b08/01a08ad9, SG 43/43 + ZZ 1/1 real-browser decisions, 88 screenshots; API round 01a08a8e/01a08a66 labeled same-candidate historical comparison; older SG3/ZZ3 (100 screenshots) and 0bb5c6a0 rounds historical.
- acceptance §16 rewritten: v10 browser round rows are current; SG3/ZZ3, v8-first, ZZ2 rows marked historical; missing-matrix row now states exhaustive source-pair×kind matrix + matrix-level criterion undefined; event-merge both outcomes retained.
- 13 pending / 0/13 / reviewer empty / not_passed preserved; mocked-only retained. Consistency: JSON 1:1, pending 13, no stale SG3-current labels, gate 15 + 101 unit tests OK, diff clean.

2026-09-10 — owning-layer gap disposition + reviewer material (still NOT_PASSED):

- Matrix criterion defined and executed (§22): 6 cells {same_revision, same_book_reimport, cross_book} x {entity, event}; 5 PASS (27/27, 53/53, 9/9, 31/31, 3/3), same_revision x event EMPTY -> matrix-level FAIL, missing cell retained (evidence /srv/loom-t19-evidence/7e637dd3/matrix-all.py).
- General post-publication event-merge rule documented from owning code (publication_v0._build_canonical_records): a merge component maps to at most one existing canonical id; >=2 -> fail-closed (ZZ2), single/new join publishes (ZZ3/ZZ-v10/v10-browser); both outcomes retained.
- canonical review-flow-smoke.mjs real-backend coverage recorded as explicit unmet requirement (out of T19 file scope); ad-hoc browser evidence provided.
- §23 added: per-case source-grounded reviewer material (13 cases with original quotes + current publication/evidence locations); 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — §23 C04 current/history clarification (still NOT_PASSED):

- §23 intro now states event/entity linkage cells follow §22's executed matrix (current candidate cross_book×event non-empty; same_revision×event EMPTY -> matrix-level FAIL); any same-revision event same_occurrence example is the historical SG3 round. C04 row relabeled accordingly; C05 cites current cross_book×event 3/3 PASS. 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — event round resolves same_revision×event coverage (still NOT_PASSED):

- event round job d7c18548 (new SG import, v10): 58 reviews decided via real browser open/fill/submit (116 screenshots), incl. the first current-candidate same_revision event candidate 07a7c595 (孫策去世 vs 魯肅去世) adjudicated not_same; publish then fail-closed on event canonical collapse (two existing canonical ids), retained.
- §22 criterion split into Coverage vs Publish: Coverage PASS (6/6 cells covered+terminal: 41/41, 1/1 not_same, 174/174, 31/31, 48/48, 4/4); Publish FAIL (event-round canonical-collapse terminal retained). §16/§17/§0 and JSON blocker updated; matrix script /srv/loom-t19-evidence/7e637dd3/matrix-all.py.
- canonical review-flow-smoke.mjs real-backend coverage remains explicit unmet (out of T19 scope). 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — §23 synced to §22 coverage/publish split (still NOT_PASSED):

- §23 intro now cites §22 coverage/publish: Coverage PASS 6/6 (same_revision×event 1/1 = 07a7c595 human not_same; cross_book×event 4/4), Publish FAIL (event round canonical collapse retained, ZZ2 same class; ZZ3/ZZ-v10/v10-browser success); SG3 same_occurrence explicitly historical. C04/C05 rows updated. 13 pending / 0/13 / reviewer empty; mocked-only and both event-merge outcomes retained.

2026-09-10 — explicit unmet requirements registered (§24, still NOT_PASSED):

- §24 added with reproducible commands + terminal evidence for three unmet items: (1) canonical-stability Publish FAIL (by-design fail-closed in publication_v0; ZZ2 and event-round terminal files); (2) current C04 event-evidence path (no same_revision 先主傳↔周瑜傳 赤壁 candidate; material = published 01a08b08 translations + historical SG3 same_occurrence); (3) canonical review-flow-smoke.mjs real-backend coverage (T11/T18 scope). JSON evidence_notes updated; 13 pending / 0/13 / reviewer empty / not_passed preserved; both event-merge outcomes retained.

2026-09-10 — §24 reproducibility fixes (still NOT_PASSED):

- Replaced literal <job>/short IDs with two exact copyable review queries using full UUIDs (SG2 e4e952f0-ec61-4f5e-b9c9-7f4363e11fb7 and event d7c18548-b51d-4581-be06-f26cad9fdd06; browser SG 5ee49e77-5980-4263-95c0-d23d3323160e noted), credentials read only from server env; clarified SG2's 848a296f 赤壁 is cross-book ZZ↔SG, not the C04 same-revision pair.
- Added credential-free review-flow-smoke.mjs capability check: grep of supported modes + `node ... --mode real-backend` prints the mocked-api-only FAIL message and exits 1 (real output captured).
- Unmet dispositions, 13 pending / 0/13 / reviewer empty, C04 awaiting independent review, Publish FAIL and mocked-only blockers preserved.

2026-09-10 — C04 source-grounded material + ownership escalations (still NOT_PASSED):

- §25 added: current candidate C04 material - original quotes (與曹公戰於赤壁，大破之 / 遇於赤壁); SG publication 01a08b08 (revision d848e43a) translations with block/source-block ids (先主傳 t_013 b_025, t_015 b_029; 周瑜傳 t_008 b_101, t_011 b_107); bundle entity 赤壁 cross-bundle link fdeec79e (d848 ent_001010 with 86ac/21cd); no same_revision 先主↔周瑜 event candidate. Explicitly notes 848a296f (cross-book) is NOT the C04 pair. No conclusions pre-filled.
- §24 items 1 (canonical-stability Publish FAIL) and 3 (review-flow real-backend) formally escalated to owning layers (architecture Amendment / T11-T18 UI scripts) with the decision required; fail-closed and mocked-only dispositions retained.
- 13 pending / 0/13 / reviewer empty / not_passed preserved.

2026-09-10 — independent C04 finding recorded (still NOT_PASSED):

- §25.5 records the independent Reviewer finding (head 0c03ab3): translation evidence at 01a08b08 matches the anchors, but no current same-revision 先主傳↔周瑜傳 event candidate exists; 848a296f (cross-book) and historical SG3 same_occurrence are not substitutes, so the C04 cross-chapter event link is not accepted (no PASS). Case stays pending.
- §24 escalations annotated as Reviewer-confirmed and bounded to owning layers (canonical-stability architecture; T11/T18 UI scripts); T19 does not relax fail-closed or mocked-only contracts. JSON evidence_notes updated; 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — 13-case source-grounded appendix (still NOT_PASSED):

- Acceptance section 26 added: exact original anchors for all 13 real cases with chars-normalized-utf8 [start,end) offsets (spot-verified 10/10 against sources) plus current publication pointers (SG 01a08b08 revision d848e43a; ZZ 01a08ad9). No pass/fail pre-filled. §25.5 C04 judgment and §24 escalations unchanged; no owner decisions arrived yet. 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — independent-review worksheet (still NOT_PASSED):

- Acceptance section 27 added: per-case original-translation-reference/event-boundary worksheet for all 13 cases (source anchor with offsets, current translation window, linkage/boundary notes) with verdict/rationale/evidence cells left blank for the independent reviewer. No verdict prefilled; C04 event link stays not-accepted (§25.5). Owner decisions for the two escalations not yet received. 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — §27 neutralized to observation/[hypothesis] (still NOT_PASSED):

- §27 reference/event/boundary column rewritten so every entry is a checkable observation or an explicitly labeled [hypothesis]; removed pre-judgments (C07 merge recommendation, C08/C09 "position correct", C11/C12 completeness claims, C13 synchronicity claim). Verdict/basis/evidence cells stay blank. C04 missing current event candidate and the two escalations unchanged; 13 pending / 0/13 / not_passed preserved.

2026-09-10 — deterministic 13-case replay (still NOT_PASSED):

- Acceptance section 28 added: pure-repo source-window command + server translation-window script (case_windows.py, output case_windows.out 13/13, 0 MISSING). Generates comparison windows only, writes no verdicts. §27 unchanged and neutral; C04 missing event candidate and escalations unchanged; 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — locator/hash packet (still NOT_PASSED):

- Acceptance section 29 added: deterministic locator/hash packet (case_hashes.py -> case_hashes.out) with source-window sha, translation artifact/revision/block/window sha, HEAD/TAIL hashes, and annotation counts. Locator-only; §27/§28 unchanged; no verdicts written; C04 unaccepted (no current same-revision event candidate); escalations tracked; 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — full-context + reference/event locator packet (still NOT_PASSED):

- Acceptance section 30 added: case_context.py -> case_context.out (124 lines; run inside worker container) with per-case ±250-char context+sha and bundle entity/event/claim record_sources anchors for the case blocks. Locator-only, no verdicts. §27-§29 unchanged; C04 unaccepted; escalations tracked; 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — full-chapter pair packet (still NOT_PASSED):

- Acceptance section 31 added: chapter_pairs.py outputs complete source/translation files and per-block alignment for all four chapters with sha256 (sg0 12591/16312, sg1 5030/7068, sg2 3594/5169, zz 10715/14718; zz single translation block over 127 source blocks). Locator-only; no verdicts; C04 unaccepted; escalations tracked; 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — sentence-level reading index (still NOT_PASSED):

- Acceptance section 32 added: chapter_index.py outputs deterministic source-block and translation-sentence indexes with offsets+sha16, resolving ZZ's single-block limitation (zz 127/1/492; sg0 86/43/552; sg1 32/16/214; sg2 19/10/164). Locator-only; no verdicts; C04 unaccepted; escalations tracked; 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — one-command review-bundle replay (still NOT_PASSED):

- Acceptance section 33 added: regen_review_bundle.sh deterministically regenerates the 25-file 13-case review bundle and review-bundle-manifest.json (25 files, 0 missing). Input-consistency only; locator-only, no verdicts; C04 unaccepted; escalations tracked; 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — side-by-side reading companion (still NOT_PASSED):

- Acceptance section 34 added: chapter-<name>-sidebyside.md (SG block->referencing translation blocks; ZZ proportional/ordinal locator, not an alignment claim), wired into regen_review_bundle.sh (manifest 29 files, 0 missing). Locator-only; no verdicts; C04 unaccepted; escalations tracked; 13 pending / 0/13 / reviewer empty preserved.

2026-09-10 — reviewer-fill protocol (still NOT_PASSED):

- `manual-content-review.json` gained `reviewer_instructions`: per-case fields (status pending|pass|fail, conclusion, evidence, reviewer) are reviewer-only; inputs listed (acceptance sections 23/25-34 + review-bundle-manifest.json); invariants keep 13 pending / 0 pass / 0 fail / reviewer null / verdict not_passed until the independent reviewer concludes. No locator material added; C04 unaccepted; escalations tracked; nothing closed.

2026-09-10 — independent Reviewer conclusions (still NOT_PASSED):

- Reviewer agent `54d5eed4-ef01-479d-9a80-1bc6e55cca2a` independently checked all 13 real cases against the §23/§25–§34 source-grounded package and wrote per-case `status`, `conclusion`, `evidence`, and `reviewer` fields. C01–C03 and C05–C13 are `pass`; C04 is `fail` because the current candidate lacks the required same-revision 先主傳↔周瑜傳 event candidate. The canonical ledger is now 12 pass / 1 fail / 0 pending, with overall `not_passed`; owning-layer fail-closed and mocked-only gaps remain, and T19/#548 stay open.

2026-09-10 — consistency closeout of reviewer conclusions (still NOT_PASSED):

- Verified canonical ledger counts: 12 pass / 1 fail (T02-C04) / 0 pending, +1 not_applicable synthetic N01; reviewer set; verdict not_passed. C04 fail basis (no current same-revision 先主傳↔周瑜傳 event candidate) present in conclusion/evidence.
- Fixed stale "13 pending / 0-13 / reviewer empty" snapshot lines in acceptance sections 12/21/23-34 to point to the reviewer's section 35 result (12 pass / C04 fail, not_passed); updated reviewer_instructions.invariants and status_counts accordingly. Reviewer verdicts and the overall not_passed verdict left unchanged.
- Retained blockers: canonical-stability publish fail-closed, review-flow mocked-only/real-backend gap, C04 same-revision event candidate absence, matrix/event-merge items. T19/#548 stay open.

2026-09-11 — final candidate/provenance reconciliation (still NOT_PASSED):

- Candidate/attribution blocker resolved: final candidate is `c10ba6aa3b6e9ea71b2b0e6c34402fad45be3808` (origin/main, contains #637/#638/#639/#640). Runtime delta vs `57fe539` is only `apps/chronicle/webapp/scripts/review-flow-smoke.mjs` (test tooling, not server/worker/read_api). The canonical `review-flow-smoke.mjs --mode real-backend` PASS therefore belongs to `c10ba6a`, not `57fe539`.
- Provenance rebuilt on `c10ba6a`: image `loom-chronicle:t19-c10ba6aa` (id `sha256:60d530a2094e…`) deployed on project `chronicle-t19-c10ba6aa` (port 8092) over the primary happy-path data; `/srv/loom-t19-evidence/c10ba6aa/fp-provenance.json` records source revision sha256 (`a5dc345f…` SG, `b9831c28…` ZZ; both match the frozen ingest files), publication artifact sha256, evidence file hashes, the real-backend PASS log hash, and the deployed image id.
- Primary happy-path (run candidate `57fe539`, runtime identical to `c10ba6a`): SG job `effb5ac1` → publication `01a08c36` (先主傳 15872/1.26, 周瑜傳 6963/1.38, 魯肅傳 5244/1.46); ZZ job → publication `01a08c46` (14718, 64 blocks); the sole within-revision event candidate `f9e37a9d` (`evt_000003` 先主傳 ↔ `evt_001003` 周瑜傳) terminal `same_occurrence`; all resolution reviews terminal; Reader 4/4 PASS (43/16/10/64); worker restart/takeover resumed mid-extract; evidence `/srv/loom-t19-evidence/57fe5390`.
- Ledger synced: `manual-content-review.json` candidate `c10ba6a`, C04 `pass`, status_counts 13 pass / 0 fail / 0 pending (+1 `not_applicable`), overall verdict stays `not_passed`; acceptance §0/§35 updated. No PASSED self-certification; T19/#548 not closed.

2026-09-11 — evidence-index internal closure on `c10ba6a` (still NOT_PASSED):

- Rebuilt `ready/manifest.json` by re-running the live gate on the `c10ba6a` checkout: candidate=`c10ba6aa3b6e9ea71b2b0e6c34402fad45be3808`, git_clean, result `READY`.
- Rebuilt `fp-final-state.json`: candidate `c10ba6a`, project `chronicle-t19-c10ba6aa`, port 8092, 8 publications, resolution open=0, job statuses.
- Added `fp-runtime-equivalence.json`: hashed mapping between historical run candidate `57fe539` and final candidate `c10ba6a` — `apps/chronicle` runtime tree sha256 equal (`219cdb10…`), changed file list = `apps/chronicle/webapp/scripts/review-flow-smoke.mjs` with per-commit blob sha256, plus deployed image `loom-chronicle:t19-c10ba6aa` (id `sha256:60d530a2…`). So `57fe539` is only historical run data; the candidate is `c10ba6a`.
- `fp-provenance.json` rebuilt to attribute candidate `c10ba6a`, the image id, source/publication/evidence/log hashes. Historical failure evidence (`57fe5390`, `e89e9062`, ZZ3/ZZ4, older rounds) retained; overall `NOT_PASSED`; T19/#548 open.
