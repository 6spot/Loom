# Milestone 7 Task Index — Reactions + Entropy + Scheduler

Parent issue: #81; depends on M6 gate #80.

| Task | Issue | Status | Record |
| --- | ---: | --- | --- |
| M7-T1 Reaction execution contract | #82 | planned | `t1-reaction-execution-contract.md` |
| M7-T2 atomic Reaction Work scheduling | #83 | planned | `t2-reaction-atomic-scheduling.md` |
| M7-T3 Runtime entropy | #84 | planned | `t3-runtime-entropy.md` |
| M7-T4 claim-next due Work | #85 | planned | `t4-claim-next-due-work.md` |
| M7-T5 Runtime worker loop | #86 | planned | `t5-runtime-worker-loop.md` |
| M7-T6 Runtime facilities gate | #87 | planned | `t6-runtime-facilities-gate.md` |

Default order: #82 root → #83/#84 → #85 → #86 → #87. #84 is parallel-safe only after #82. Parent closes after #87 proves atomic reaction obligations, controlled entropy and crash/reclaim scheduler behavior.
