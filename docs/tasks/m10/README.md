# M10 — Agency + Durable Cognitive Execution

Parent #142; depends on M9 gate #186 plus earlier scheduler/read foundations.

```text
#187 loom-agency contracts
  ↓
#188 AgentWorldView builder
  ↓
#189 CognitiveExecutor gateway
  ↓
#190 atomic Wake Decision/Action commit
  ↓
#191 Wake scheduling + CAS policy + resumability
  ↓
#192 Agency final gate
```

| Task | Issue | Status |
| --- | ---: | --- |
| M10-T1 | #187 | completed |
| M10-T2 | #188 | completed |
| M10-T3 | #189 | completed |
| M10-T4 | #190 | completed |
| M10-T5 | #191 | completed |
| M10-T6 | #192 | completed |

This milestone implements Amendment 0003; it does not reopen Agency architecture. V0 semantic-rejection rule: a rejected `Decision::Act` completes the current Wake as determined no-world-change; reconsideration is a new Wake.
