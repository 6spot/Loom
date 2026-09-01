# Chronicle application tasks

This ledger tracks executable implementation work for the Chronicle application under `apps/chronicle/`.

Chronicle is an application-level consumer of Loom. Tasks here must not silently redefine Loom Core, Runtime, Storage, or Capability authority. If an application task requires a new Loom semantic/authority decision, stop and use the repository Architecture Amendment process.

## Active tasks

| Task | Issue | Status | Scope |
| --- | ---: | --- | --- |
| C0-T1 | #462 | in_progress | V0 ingestion prototype: deterministic fixture extraction, normalization, JSON Schema validation, and human-gold comparison |
| C0-T2 | #463 | in_progress | model-v0: source-grounded provider-driven extraction, transport normalization, and machine-readable evaluation |
| C0-T3 | #464 | in_progress | Evaluator v2: hard grounding checks, semantic event/claim matching, and controlled predicate vocabulary |
| C0-T4 | #465 | in_progress | Coverage v0.2 experiment: second-pass coverage research and lessons; not the production ingestion path |
| C0-T5 | #466 | in_progress | Contract-first ingestion: single extraction, deterministic validation, bounded repair; production direction |
| C0-T6 | #467 | in_progress | Cross-source validation: run unchanged Contract v0.2 on a second real historical source and review generalization |
| C0-T7 | #468 | in_progress | Cross-source resolution/linking: conservative candidate blocking plus non-destructive Entity/Event link decisions |
