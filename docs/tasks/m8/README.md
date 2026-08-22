# Milestone 8 Task Index — Semantic Retrieval + Blob Foundation

Parent issue: #88; depends on M7 gate #87.

| Task | Issue | Status | Record |
| --- | ---: | --- | --- |
| M8-T1 semantic/blob authority contract | #89 | planned | `t1-semantic-blob-authority-contract.md` |
| M8-T2 SemanticIndex contract | #90 | planned | `t2-semantic-index-contract.md` |
| M8-T3 PostgreSQL pgvector | #91 | planned | `t3-postgres-pgvector.md` |
| M8-T4 Runtime semantic retrieval | #92 | planned | `t4-runtime-semantic-retrieval.md` |
| M8-T5 Object Store/Blob | #93 | planned | `t5-blob-object-store.md` |
| M8-T6 semantic/blob gate | #94 | planned | `t6-semantic-blob-gate.md` |

#89 is the root. #93 is parallel-safe after it; #90→#91→#92 forms the semantic path. #94 closes the milestone only after projections can be rebuilt/removed without changing World authority and blob integrity/replay contracts pass.
