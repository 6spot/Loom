---
task: M4-T6
issue: 151
status: in_review
depends_on: [148, 150]
created_at: 2026-08-22
started_at: 2026-08-22
completed_at:
completion_pr:
merge_sha:
---

# M4-T6 — Neutral Template / Binding fixtures

## Goal

Provide small non-domain-specific fixtures that exercise birth, Binding and Session semantics and can be reused by later scheduler/replay/Agency gates.

## Implementation contract

- Adapt the neutral counter-style Capability and add only minimal second Capability needed for dependency/binding tests.
- Create at least two versioned Templates with different bindings/bootstrap recipes.
- Include globally installed-but-disabled semantics.
- Cover Action/Event/Facet and declarations needed later for Work/Reaction, without implementing scheduler here.
- Bootstrap Events are normal first Events stamped at initial World Time and attributed to bootstrap Session.
- Keep examples outside Core/Runtime authority layers.

## Acceptance

- [ ] Templates create distinct immutable bindings.
- [ ] Disabled Action cannot execute.
- [ ] New Template revision does not mutate existing World.
- [ ] Bootstrap Session/Revision evidence is observable internally.
- [ ] Architecture + standard gates pass.

## Verification evidence

- `python3 tools/check_architecture.py` → `Loom architecture dependency policy: OK`.
- `cargo fmt --all -- --check` → passed.
- `cargo check --workspace --all-targets --all-features` → passed.
- `cargo clippy --workspace --all-targets --all-features -- -D warnings` → passed.
- `cargo test -p loom-composition-tests --test neutral_templates -- --nocapture` → 2 tests passed.
- `cargo test -p loom-composition-tests --all-targets --all-features` → all composition tests passed.
- `cargo test --workspace --all-features` → all workspace tests and doc-tests passed; PostgreSQL fixtures use their configured no-database skip path when `LOOM_TEST_POSTGRES_URL` is unset.
- `RUSTDOCFLAGS='-D warnings' cargo doc --workspace --all-features --no-deps` → passed.

## Progress Log

- 2026-08-22 — Planned.
- 2026-08-22 — Added reusable composition-boundary counter/observer Capabilities, two immutable Template revisions, target-World Binding coverage, bootstrap provenance assertions, and Work/Reaction declarations.
