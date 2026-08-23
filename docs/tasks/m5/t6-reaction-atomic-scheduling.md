---
task: M5-T6
issue: 158
status: in_review
depends_on: [153, 154, 157]
created_at: 2026-08-22
started_at: 2026-08-23
completed_at:
completion_pr: 220
merge_sha:
---
# M5-T6 — Atomic Reaction Work scheduling

## Contract
- Event Trigger means registered Reaction → Immediate Durable Work, never recursive handler execution.
- Match only semantics enabled by World Binding.
- Reaction Work effective due is current pinned World Time and receives Runtime-assigned logical order.
- Triggering Event + generated Work + journal transitions persist atomically.
- Carry causal Event/origin references while keeping execution provenance separate from World causality.
- Validate handler/schema/Binding before commit; fan-out participates in existing budgets.

## Acceptance
- [x] Event+Reaction Work are all-or-nothing.
- [x] Same-time fan-out order is deterministic.
- [x] Failure leaves no partial Event/Work.
- [x] Reaction chain is bounded and head-ordered.
- [ ] Restart + standard gates pass.

Architecture: Amendment 0001 §8.2 + chronology rules.

## Verification evidence

- `python3 tools/check_architecture.py` → storage SQL ownership and Loom architecture dependency checks passed.
- `cargo fmt --all -- --check` → passed.
- `CARGO_TARGET_DIR=/tmp/loom-target ... cargo check -p loom-runtime -p loom-storage -p loom-composition-tests` → passed.
- `CARGO_TARGET_DIR=/tmp/loom-target ... cargo clippy -p loom-runtime -p loom-storage -p loom-composition-tests --all-targets -- -D warnings` → passed.
- `cargo test -p loom-runtime --lib` → 31 tests passed.
- `cargo test -p loom-storage --lib` → 30 tests passed, including atomic staged-commit, chronology and logical journal coverage.
- `cargo test -p loom-composition-tests --test neutral_templates` → 3 tests passed, including enabled Immediate Reaction Work expansion and chained scheduling assertions.
- `cargo test -p loom-composition-tests --test vertical_slice` → 9 tests passed, including durable Work execution and failure/assembly gates.

PostgreSQL integration/restart and the full workspace gate remain for the repository standard gate.
