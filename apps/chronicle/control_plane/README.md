# Chronicle control plane (Rust contract)

Normative lifecycle state machines for C1-T1 document ingestion:
`JobStatus`, `StageName`/`StageStatus`, `ChunkStatus`,
`ReviewKind`/`ReviewStatus`, plus supersession numbering.

## Why a standalone workspace?

This crate is intentionally **not** a member of the repository Cargo
workspace (`[workspace]` below makes it its own workspace):

- Chronicle product logic must not become a `loom-core`/`loom-runtime`/...
  dependency or gain hidden Loom engine authority (Amendment 0006 §8).
  A workspace member would require classification in
  `tools/check_architecture.py`'s framework allowlist — an architecture
  change this task must not smuggle in.
- Zero dependencies (`cargo test --offline` works) keep the contract free
  of SQL/DB drivers, which `tools/check_storage_sql_ownership.py` forbids
  outside `loom-storage`.

## Checks

```bash
cargo test --offline
cargo clippy --offline --all-targets -- -D warnings
cargo fmt --check
```

The Python persistence mirror lives in
`../persistence/control_plane.py`; on disagreement this crate wins.
