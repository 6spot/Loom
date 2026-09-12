# c2r3-contract fixtures (C2-R3-T01)

Contract examples owned by C2-R3-T01 for the third-round person-state
tasks (#622 output, #626 production wiring, #627 read query and the
T02–T15 consumers). Every file is a **contract fixture, not a historical
answer**: the classical names only exercise phase order, office/title
typing, continuity, uncertainty and candidate-key rules.

## Candidate / artifact

- `request.json` — program-owned chapter request (hashes, block offsets,
  coverage, limits). Never model-generated.
- `candidate-valid.json` — passing `chronicle.chapter-candidate / 0.3`.
  Adds `person_states` (three phases, a proven precedence DAG, one
  `unit_phases` binding per translation block, office/affiliation facts
  and a continuity) to a self-contained 0.1/0.2 bundle/translation/reading
  product.
- `artifact-accepted.json` — `chronicle.chapter-artifact / 0.3` produced
  by `accept_person_state_candidate`: program-resolved reading units, the
  accepted `person_states` block, `person_states_sha256` and the stable
  `person_state_candidates` keys with resolved anchors.
- `candidate-*.json` — negative contract examples, each rejected by
  `validate_person_state_candidate` in the named category:
  - `candidate-missing-unit-phase.json` — coverage: a block has no binding.
  - `candidate-phase-cycle.json` — phase precedence forms a cycle.
  - `candidate-unknown-ref.json` — a fact points at an unknown phase.
  - `candidate-wrong-subject.json` — a fact subject is a place entity.
  - `candidate-canonical-id.json` — the model wrote a canonical UUID.
  - `candidate-recommendation-start.json` — recommendation used to start.
  - `candidate-single-fact-disagreement.json` — disagreement has one fact.
  - `candidate-unbound-phase.json` — a phase is bound to no unit.
  - `candidate-unproven-continuity.json` — continuity ends before it starts.
  - `candidate-url.json` — a URL was written into the model block.

## Review / public DTOs

Each example validates against `chronicle-person-state-v0.1.schema.json`
and mirrors an interface in
`apps/chronicle/webapp/src/lib/person-state-types.ts`:

- `unit-people-example.json` — `UnitPeoplePage` (+ `PersonSummary`,
  `StateItem`, `StateChange`).
- `person-states-page-example.json` — `PersonStatePage`.
- `state-evidence-page-example.json` — `StateEvidencePage`.
- `place-state-example.json` — `PlaceStatePage` with administration and
  control as separate dimensions.
- `review-package-example.json` — `ReviewPackage` (frozen plan, stable
  candidate keys, `chapter_state_evidence`).
- `review-decision-example.json` — `AssessmentOverlay` decision payload.

`candidate-valid.json` / `artifact-accepted.json` and the DTO examples
were generated from the request by the pure contract module; regenerate
only through `person_state_contract.accept_person_state_candidate` and
the `example_*` builders so hashes, item ids and candidate keys stay
honest.
