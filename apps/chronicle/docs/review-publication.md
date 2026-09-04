# Chronicle cross-source resolution, review, and publication (C1-T8)

Connects a newly assembled source bundle to the existing C0
staged/resolution/canonical path, routing genuine ambiguity through
an explicit human-review workflow instead of auto-merging. Pure
request/validation/merge logic lives in
`apps/chronicle/persistence/resolve_publish.py` (no model, no
network); the durable worker path lives in
`apps/chronicle/worker/ingestion_worker.py` (`resolve` / `publish`
stages) on the C1-T1 control-plane tables behind
`CHRONICLE_DATABASE_URL`.

```text
assembled source bundle (one revision, label c1rev-<id>)
        │
        ▼
resolve: candidates vs persisted corpus (C0 blocking reused)
        │  → initial all-uncertain artifacts (persisted)
        │  → one stage_gate ReviewItem per candidate (same job)
        │  → needs_review while any candidate is open
        │  → resume applies recorded decisions → final artifacts
        ▼
publish: prior corpus resolutions + final decisions
        │  → C0 publication (same-links union, rest stay distinct)
        │  → catalog persisted, UUIDs reused from latest catalog
        ▼
ingestion_outputs: source-bundle + cross-source-resolution(s)
                   + canonical-catalog (exact hashes)
```

## Key contracts

- **C0 semantics reused, not bypassed.** Candidate blocking is
  `resolution_v0` unchanged (same Entity type + exact stable
  surface; Event time compatibility + participant/place overlap).
  Publication is `publication_v0` unchanged (only `same_entity` /
  `same_occurrence` union; `uncertain` / `not_same` /
  `related_occurrence` never merge; negative constraints and
  existing-ID collapse fail closed with `PublicationConflict`).
- **The deterministic layer never merges.** Initial decisions are
  all `uncertain`: a shared surface alone never proves identity.
  Only a recorded human decision (exact C0 vocabulary per link
  kind) can produce `same_entity` / `same_occurrence`.
- **Every candidate blocks, and that is the safe choice.**
  Publishing first as singletons and merging later is unsafe: a
  later accepted same-link across two published canonical UUIDs
  fails closed instead of merging. Review therefore happens
  *before* first publication whenever candidates exist.
  Non-blocking uncertainty is the complement: human-resolved
  `uncertain` flows into publication as non-merging evidence, and
  a job with zero candidates publishes unattended.
- **Reviews are durable and deterministic.** Items carry full
  left/right bundle/ref provenance, signals, and the allowed
  decision vocabulary. Opening is adopt-or-create (crash-safe, no
  duplicates). Dismissed items are collected as explicit `uncertain`
  decisions (a terminal reviewed state, distinct from never
  reviewed): giving up on a review never merges, while a candidate
  with no review item at all still fails finalization closed.
  Resume reuses completed stages and never re-runs accepted
  extraction work.
- **No new state machine.** Review items reuse the frozen
  `stage_gate` kind; `resume_job` still refuses while any item is
  open. No migration was needed.
- **Deterministic artifacts.** No timestamps, UUIDs, or randomness
  in generated artifacts (audit times live only in
  `review_items` rows). Initial artifacts bind decisions by content
  hash, so stale decisions cannot apply to changed inputs.
- **Crash windows adopt, never regenerate.** A recorded catalog
  output is re-persisted (idempotent no-op) on re-entry so the
  same identities never get fresh UUIDs. Superseded initial
  artifacts stay persisted for audit but never publish alongside
  the finals that replace them.
- **Fail closed.** Publication conflicts park the job as `failed`
  (bounded Studio retry on a fresh job with fresh review); no
  silent identity choice is ever made. Replacing a source still
  means a new immutable revision (C1-T3); old canonical records
  are never destructively deleted.

## Production hook

The deployed worker runs real `resolve`/`publish` whenever the job
carries a real assembled bundle output (the C1-T7 artifact); other
jobs keep the deterministic fake executor for those stages.
`present` stays fake (Reader Presentation is C1-T12 scope).

## Reviewing (until the Studio queue lands in C1-T11)

```python
import resolve_publish as R
R.resolve_resolution_review(
    conn, review_id=...,
    decision="same_entity",  # C0 vocabulary, validated per link kind
    rationale="source-bounded reason",
    confidence=0.9,
)
```

After every open item is resolved or dismissed, resume through the
existing Studio operation (`needs_review` -> `running`), and the
next worker claim finalizes and publishes deterministically.
