---
task: C2-R2-T17
issue: 586
kind: leaf
parent: C2-R2
depends_on: [C2-R2-T16, C2-R2-D01]
created_at: 2026-09-08
---

# 真实章节阅读、事件定位与第二轮独立验收

## Scope

[Issue #586](https://github.com/6spot/Loom/issues/586) owns the bounded implementation steps. 在全新数据环境中用真实 provider 和固定完整章节验证第二轮可读性、叙事时间、事件对应和返回体验，独立结束本轮。

Canonical contracts: [continuous reading](../../../../apps/chronicle/docs/continuous-reading.md), [reading experience](../../../../apps/chronicle/docs/reading-experience.md). Dependency and file ownership: [initiative index](README.md).

## Acceptance

- [ ] 四个完整自然章通过真实0.2生产/审核/发布，译文及来源可完整阅读。
- [ ] 至少12个真实核对点证明时间、回溯、事件和人物地点对应；未知保留，未来头衔不被带入。
- [ ] 事件/其他来源/原文探索能返回原 unit 与叙事时间，桌面与窄屏流程有实际证据。
- [ ] 所有自动门与独立内容审核通过，未验证项如实记录且不能被当成已验收。
- [ ] 本轮所有子任务满足各自验收要求，相关 CI 与独立内容核对证据完整。

## Verification requirements

Run the checks specified in the linked Issue and the current [delivery guide](../../../development/task-completion.md). Record actual acceptance, test/CI results and any unavailable checks in the delivery PR.

## Live acceptance status

Latest experiment (2026-09-12): [staged generation and model review report](../../../../apps/chronicle/corpus/second-round/acceptance/staged-production-20260912.md).

- Luna returned the whole-chapter prose in one 114.150-second call and a
  separate extraction response in 124.013 seconds. Natural prose paragraphs
  did not create separate translation calls. Original annotations remained
  available as context; this experiment translated the defined main-text scope.
- Two model reviews ran in parallel with extraction; their comparison also
  returned a complete response. Five calls reported 194,987 total tokens.
  Citation defects, wrong actors/state subjects, and erroneous adjudication
  remain. **Content is not accepted.**
- Six trial checkpoint checks passed without another HTTP call. These are
  file-level experiment checks, not production worker/DB recovery tests.
- The user subsequently clarified pure-text-only translation and per-step
  single/multiple models; [discussion and task boundaries](../staged-production-discussion.md)
  record those requirements. Production contracts and workers are unchanged;
  no database writes, publication, deployment, browser or R3 acceptance claim.

Previous same-model generation regression (v6, preserved): [run evidence](../../../../apps/chronicle/corpus/second-round/acceptance/run-live-r2-20260912-v6.json),
[complete request and both responses](../../../../apps/chronicle/corpus/second-round/acceptance/candidate-live-r2-20260912-v6.json),
and [independent full-chapter review](../../../../apps/chronicle/corpus/second-round/acceptance/reading-review-20260912-v6.md).

- `07c6c40`, prompt v6, real `gpt-5.6-luna`, the same complete 0.2 request.
  Two semantic calls / two HTTP attempts; 128,583 provider-reported tokens,
  no billed cost reported. Initial bundle was empty; the only correction
  returned 10 entities / 6 events / 2 claims but still failed three source
  reference checks. The joint candidate was rejected; history replays.
- All 41 translated blocks and 13,728 characters were preserved in correction.
  Independent review of every source/translation block still **FAILS**:
  reversed actors and kinship, missing complete annotations and arguments,
  wrong event place/season, and lost reading associations. Some v5 mistakes
  improved; others remained or regressed. One sample does not establish a
  general model or prompt quality claim.
- No database writes, human publication decisions or browser walkthrough.
  #586 / #549 remain unaccepted; R3 must be assessed independently.

### Previous generation-only regression (v5, preserved)

[Run evidence](../../../../apps/chronicle/corpus/second-round/acceptance/run-live-r2-20260912-v5.json),
[complete request and both responses](../../../../apps/chronicle/corpus/second-round/acceptance/candidate-live-r2-20260912-v5.json),
and [independent content review](../../../../apps/chronicle/corpus/second-round/acceptance/reading-review-20260912-v5.md).

- `20054a3`, prompt v5, real `gpt-5.6-luna`, same complete 0.2 request.
  One initial call plus one correction, two HTTP attempts, 158,933 total
  provider-reported tokens; billed cost unknown.
- Seven initial validator errors were all sent to correction. The final
  candidate passes mechanical validation and preserves all 41 ordered
  translated blocks and their 15,943 characters exactly. History replays.
- **Content review still fails:** wrong actors, classical-word and quotation
  interpretation errors, and omitted embedded notes remain in that prose.
  Structural `accepted=true` does not certify semantic quality.
- This isolated run performed no database writes, human review, publication
  or browser walkthrough. It is not this task's four-chapter acceptance and
  says nothing about R3 0.3 content. #586 and #549 remain unaccepted.

### Previous full-stack retest (2026-09-12, preserved)

Evidence: [run evidence](../../../../apps/chronicle/corpus/second-round/acceptance/run-live-r2-20260912-v4.json),
[complete failed candidates](../../../../apps/chronicle/corpus/second-round/acceptance/candidate-live-r2-20260912-v4.json),
and [independent content review](../../../../apps/chronicle/corpus/second-round/acceptance/reading-review-20260912.md).

- Fresh isolated 0.2 run on `74d2f20`, prompt v4, real `gpt-5.6-luna`;
  one job claim, one initial call and one correction, no Studio retry.
- The first chapter failed: 28 translated blocks became one 8,888-character
  block, exceeding 8,192; four source-anchor errors remained. Event spans
  fell from 11 to 0. Independent review confirmed three concrete omissions.
- No accepted chapter, review item or publication was produced in this retest.
  The remaining two uploaded chapters are pending; 通鑑 was not uploaded in it.
- **Not accepted.** R2 fixes in PR #663 do not close #586 or #549. Browser
  fixture results and the pending R3 0.3 work do not certify this real content.

### Previous run (2026-09-11, preserved)

Evidence: `apps/chronicle/corpus/second-round/acceptance/run-live-r2.json` and
`reading-review.md`.

- Real `gpt-5.6-luna` 0.2 chain ran in an isolated Compose stack through Studio
  and the public reading HTTP routes; `--mode live` preflight returned `READY`.
- The four frozen chapters are complete and readable (三國志 66 units/5 groups;
  資治通鑑卷65 64 units/1 group).
- The second-round reading semantics fail on real content: every `year_key` is
  `unknown`; body event-word segments and `context_entities` are empty; the
  資治通鑑 chapter has no events and one group; generation needed repeated
  fail-closed claims on the `reading_time`/anchor contract rules.
- Claim accounting is recorded in `run-live-r2.json.generation_limits`: the raw
  `ingestion_jobs.attempt` claim count (三國志 4, 資治通鑑 2) includes the
  `needs_review` resume claim and does not exceed the `max_attempts=3` retry
  budget; T03's per-chunk `max_correction_rounds` is fixed at 1 (2 model
  attempts) before fail-closed.
- **Not accepted / no LM-39 acceptance claim.** The failures are
  generation/projection contract defects routed to T03/LM-25, T04/LM-26,
  T05/LM-27, T07/LM-29, T08/LM-30 and T14/LM-36 (recorded in
  `reading-review.md` and `run-live-r2.json.ownership_handoffs`). This failed run
  is preserved as regression evidence; a fresh live rerun plus independent
  content review must pass first. Independent human content confirmation, the
  live browser walkthrough, and provider cost capture remain unverified.

## Progress Log

- 2026-09-12 — Recorded a bounded staged trial: whole-chapter translation, independent extraction, two model reviews, and comparison. All HTTP responses completed; citation/content/adjudication quality remains unaccepted. Recorded the user's pure-prose, checkpoint, configurable-model and exception-review requirements without changing production authority.
- 2026-09-12 — Archived the v5 generation-only regression separately from the full-stack runs. Metadata correction preserves the complete prose and passes replay; independent content review still fails. No publication, browser or R3 acceptance claim.
- 2026-09-12 — Retested 0.2 prompt v4 in a fresh isolated environment; retained both rejected candidates and full validation reports. Independently confirmed three translation omissions and two omitted repair diagnostics. No publication or live acceptance claim; four-chapter/content/browser requirements remain open.
- 2026-09-08 — Planned under #549 with explicit upstream dependencies, implementation steps and file ownership. No feature or completion claim.
- 2026-09-08 — Final gate also waits for design-preparation D01/#588. D01 delivers the reusable background skill and candidate archive only; future Studio/image-display tasks are not silently added to this acceptance scope.
- 2026-09-11 — Ran the real-provider live acceptance on the frozen four chapters. Recorded `run-live-r2.json` and `reading-review.md`. Content acceptance failed: unresolved narrative time, no body event spans, no context entities, and fail-closed generation retries. Task remains in progress; findings require the owning leaves to fix and re-verify.
- 2026-09-11 — Addressed Reviewer CHANGES_REQUIRED on PR #657: removed the closing LM-39 directive (kept a non-closing `Multica-Issue: LM-39` link), reconciled the recorded claim count (4) with `max_attempts=3` and T03's `max_correction_rounds=1`, preserved the failed live run as regression evidence, and recorded the ownership handoffs for T03/LM-25, T04/LM-26, T05/LM-27, T07/LM-29, T08/LM-30 and T14/LM-36. No LM-39 acceptance claim until those fixes land and a fresh live rerun plus independent review pass.
