# Chronicle application tasks

This ledger tracks executable implementation work for the Chronicle application under `apps/chronicle/`.

Chronicle is an application-level consumer of Loom. Tasks here must not silently redefine Loom Core, Runtime, Storage, or Capability authority. If an application task requires a new Loom semantic/authority decision, stop and use the repository Architecture Amendment process.

## Tasks

| Task | Issue | Status | Scope |
| --- | ---: | --- | --- |
| C0-T1 | #462 | completed | V0 ingestion prototype: deterministic fixture extraction, normalization, JSON Schema validation, and human-gold comparison |
| C0-T2 | #463 | completed | model-v0: source-grounded provider-driven extraction, transport normalization, and machine-readable evaluation |
| C0-T3 | #464 | completed | Evaluator v2: hard grounding checks, semantic event/claim matching, and controlled predicate vocabulary |
| C0-T4 | #465 | completed | Coverage v0.2 experiment: second-pass coverage research and lessons; not the production ingestion path |
| C0-T5 | #466 | completed | Contract-first ingestion: single extraction, deterministic validation, bounded repair; production direction |
| C0-T6 | #467 | completed | Cross-source validation: run unchanged Contract v0.2 on a second real historical source and review generalization |
| C0-T7 | #468 | completed | Cross-source resolution/linking: conservative candidate blocking plus non-destructive Entity/Event link decisions |

## Current baseline

C0-T1 through C0-T7 were delivered by PR #459 and merged to `main` as `2e6dec7689bccfd4fc409a4a0486824d4bcb5791` on 2026-09-01.

The final pre-merge Chronicle prototype discovery ran 50 tests and finished `OK`. The repository's current GitHub Actions path filters do not include Chronicle/Python, so the ledger does not claim a Chronicle GitHub CI pass.

The production direction after C0 is contract-first ingestion followed by non-destructive cross-source resolution. Coverage v0.2 remains development/research evidence only.
