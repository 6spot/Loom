# M11 — Resilience, Resource Bounds + Capacity Evidence

Parent #143; depends on Agency gate #192.

```text
#193 resource bounds
  ↓
#194 property/fault/security
#172/#192/#193 -> #195 capacity benchmarks
#180/#194/#195 -> #196 topology/CI stress
all -> #197 hardening/capacity gate
```

| Task | Issue | Status |
| --- | ---: | --- |
| M11-T1 | #193 | done |
| M11-T2 | #194 | planned |
| M11-T3 | #195 | completed — see `t3-capacity-benchmarks.md` (reproducible `loom-bench` + Postgres evidence; thresholds are evidence not invariants) |
| M11-T4 | #196 | planned |
| M11-T5 | #197 | planned |

This milestone measures and documents V0's real capacity envelope; thresholds are implementation evidence, not new architecture invariants.