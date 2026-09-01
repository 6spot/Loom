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
| C0-T8 | #470 | completed | Canonical Publication v0: stable UUIDv7 Entity/Event identity over source-owned representations and accepted Resolution Links |
| C0-T9 | #471 | completed | PostgreSQL persistence: durably store staged, resolution, and canonical layers without collapsing provenance |
| C0-T10 | #472 | completed | Chronicle read model/API: Timeline, Event Detail, and Entity Detail application contracts over persisted data |
| C0-T11 | #473 | in_progress | First usable UI: Timeline + Event Detail + Entity Detail with canonical navigation and source/evidence traceability |

## Current baseline

C0-T1 through C0-T7 were delivered by PR #459 and merged to `main` as `2e6dec7689bccfd4fc409a4a0486824d4bcb5791` on 2026-09-01.

C0-T8 was delivered by PR #476 and merged to `main` as `481a91ab1c42403f8baa43cfed3aa9ef3f0e4bca` on 2026-09-01. PR #476 superseded closed Draft PR #475 after the connector failed to transition its Draft state. Acceptance evidence includes a 61-test Chronicle discovery run, real 武帝纪 + 吴主传 publication, full resolution-boundary audit, byte-stable existing-catalog rerun, and human-readable semantic inspection. The accepted real publication produced 66 CanonicalEntities, 45 CanonicalEvents, and 2 `related_occurrence` relations. Post-merge Task Ledger reconciliation was merged by PR #477 before C0-T9 started.

C0-T9 was delivered by PR #478 and squash-merged to `main` as `c408757f56f8c3e1da76eb575e973d296024b9b4` on 2026-09-01. Reconciliation PR #479 merged as `2b08babe6778a7b3d5df8d3612e442a515772ce8` before C0-T10 started. The retained real C0-T7/C0-T8 artifacts form a versioned Chronicle golden integration dataset. Dedicated Chronicle PG18 CI passed five persistence tests against `pgvector/pgvector:0.8.6-pg18` / PostgreSQL 18.6, including a full 武帝纪 + 吴主传 real-data round trip. The persisted result preserves 66 CanonicalEntities, 45 CanonicalEvents, 2 `related_occurrence` relations, exact catalog membership, uncertain-place separation, and staged Claim payloads.

Architecture Amendment 0006 was accepted by PR #481 and merged as `44764edc57d9b899afa4c0353de7530756e5dc68`. It distinguishes Loom engine persistence from explicitly registered Application-owned product persistence. Chronicle remains isolated behind `CHRONICLE_DATABASE_URL`; no Loom Runtime/World/Timeline/Work/Binding persistence authority moved into the application.

C0-T10 was delivered by PR #480 and squash-merged to `main` as `5786681ae4053d7b169d112caee82c74f26a6894` on 2026-09-01. Reconciliation PR #482 squash-merged as `de6887bba46dd9010a3bfb0a4aa799b9ec1eeaed`. Before delivery, exact merge-candidate Chronicle workflow run `33518070773` and core CI run `33518070753` both passed against the accepted Amendment 0006 boundary. The final read model provides deterministic Timeline, Event Detail, and Entity Detail contracts; preserves canonical/source/evidence/Resolution separation; supports participant and place Entity navigation; and keeps all reads inside Chronicle-owned PostgreSQL read-only transactions.

C0-T11 / #473 is now the active Chronicle task. It adds the first browser exploration surface while consuming only the C0-T10 HTTP contracts; no UI code may read staged artifacts or Chronicle PostgreSQL directly.

## Planned vertical slice

```text
C0-T9  PostgreSQL persistence      ✓ completed
   ↓
C0-T10 Chronicle read model / API ✓ completed
   ↓
C0-T11 Timeline + Event Detail + Entity Detail UI ← active
```

### C0-T8 — Canonical Publication v0 / #470

Completed. Accepted cross-source Resolution Links are converted into stable CanonicalEntity and CanonicalEvent identities while staged Source/Entity/Event/Claim records remain immutable. UUIDv7 is generated by application code and remains stable across reruns when an existing catalog is supplied. `same_entity` and `same_occurrence` group representations; `related_occurrence`, `uncertain`, and `not_same` do not merge identities. Canonical publication does not synthesize historical truth or rewrite Claims.

### C0-T9 — PostgreSQL persistence / #471

Completed. Chronicle-owned PostgreSQL migrations, transaction-safe/idempotent stores, real-data persistence verification, versioned golden artifacts, and dedicated PG18 CI are delivered. Staged records, Resolution Links, and canonical publication output remain separate auditable layers. Canonical UUID stability, provenance/evidence, unresolved decisions, and related-but-distinct Events are preserved. pgvector is not required merely for persistence. Under Architecture Amendment 0006, Chronicle's registered product persistence remains distinct from Loom engine persistence and does not redefine Loom Core/Runtime/Storage authority.

### C0-T10 — Chronicle read model / API / #472

Completed. Persisted Chronicle data is exposed through stable application contracts for Timeline, Event Detail, and Entity Detail. Timeline returns canonical Events once rather than once per source representation. Detail reads expose canonical identity plus source-specific representations, Claims, exact evidence/provenance, related Events, participant/place involvement, and explicit uncertainty. Presentation labels are deterministic but never replace source evidence or convert disagreement into asserted truth.

### C0-T11 — Timeline + Event Detail + Entity Detail UI / #473

In progress. Build the first genuinely usable historical exploration surface over the C0-T10 API. The primary path is Timeline → Event Detail → source representations/evidence → Entity Detail / related Events. The UI must preserve the distinction between canonical occurrence, source perspective, Claims, and uncertainty. The initial implementation deliberately uses a zero-build browser layer over the existing Python read server so product validation is not blocked on frontend framework adoption.

## Continuation rule

Continue #473 until C0-T11 is delivered, manually validated against the retained two-source world, merged, and reconciled on `main`. Do not start map/search/graph/learning/counterfactual surfaces before this first exploration slice proves usable.
