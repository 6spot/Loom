# M8 — Durable Ingress + HTTP/SSE Boundary + Server

Parent #140; primary prerequisite M7 gate #173 plus M5 scheduler topology where noted.

```text
#174 API contracts
  ↓
#175 durable Ingress persistence
  ↓
#176 normal Session+Action processing
#174 + #166 -> #177 Change Feed
#174/#176/#177 -> #178 HTTP/SSE boundary
#178 -> #179 formal client
#160/#171/#176/#178 -> #180 loom-server
all -> #181 black-box gate
```

| Task | Issue | Status |
| --- | ---: | --- |
| M8-T1 | #174 | completed |
| M8-T2 | #175 | completed |
| M8-T3 | #176 | completed |
| M8-T4 | #177 | completed |
| M8-T5 | #178 | completed |
| M8-T6 | #179 | completed |
| M8-T7 | #180 | completed |
| M8-T8 | #181 | completed |

Ingress is reliable platform input only; accepted/deduplicated is not World Truth. Boundary maps only formal Loom API contracts.
