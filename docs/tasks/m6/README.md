# M6 — Deterministic Replay + Timeline Fork

Parent #138; depends on M5 gate #161.

```text
#162 Event/frozen-Effect state replay
  ↓
#163 Timeline Logical State replay
  ↓
#164 ancestry/EventRef + head fork
  ↓
#165 historical fork
  ↓
#166 ancestry-aware history/causality
  ↓
#167 replay/fork final gate
```

| Task | Issue | Status |
| --- | ---: | --- |
| M6-T1 | #162 | completed |
| M6-T2 | #163 | completed |
| M6-T3 | #164 | completed |
| M6-T4 | #165 | completed |
| M6-T5 | #166 | completed |
| M6-T6 | #167 | completed |

Replay never reruns resolver, Reaction, entropy, cognition or provider. Fork keeps the same World identity/Binding and clones only logical Pending future with branch-local Work IDs.
