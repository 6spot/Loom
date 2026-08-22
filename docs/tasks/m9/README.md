# Milestone 9 Task Index — Ingress + Subscription + Boundary + Server

Parent issue: #95; depends on M8 gate #94.

| Task | Issue | Status | Record |
| --- | ---: | --- | --- |
| M9-T1 Ingress/Subscription contract | #96 | planned | `t1-ingress-subscription-contract.md` |
| M9-T2 durable Ingress persistence | #97 | planned | `t2-durable-ingress-persistence.md` |
| M9-T3 Ingress Runtime processing | #98 | planned | `t3-ingress-runtime-processing.md` |
| M9-T4 World Change Feed | #99 | planned | `t4-world-change-feed.md` |
| M9-T5 HTTP/SSE boundary | #100 | planned | `t5-http-sse-boundary.md` |
| M9-T6 HTTP Loom client | #101 | planned | `t6-http-loom-client.md` |
| M9-T7 `loom-server` | #102 | planned | `t7-loom-server.md` |
| M9-T8 black-box server gate | #103 | planned | `t8-server-blackbox-gate.md` |

#96 is root. #99 may proceed after it while #97→#98 completes Ingress. Boundary/client/server converge before #103. Parent #95 closes only after the process-level HTTP/SSE/restart gate passes.
