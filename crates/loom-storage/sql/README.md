# PostgreSQL SQL ownership

This directory contains Loom's runtime PostgreSQL statements. Schema evolution and DDL stay in `../migrations/`.

Rules:

- `loom-storage` is the only crate that may own SQLx/PostgreSQL implementation details.
- Production `SELECT`, `INSERT`, `UPDATE`, and `DELETE` statements live in this directory, grouped by persistence domain.
- Rust adapter code owns transaction orchestration, parameter binding, result decoding, and Runtime-port implementation; it loads SQL from these files with `include_str!`.
- Do not expose `PgPool`, SQLx transactions, PostgreSQL row types, table names, or direct SQL authority to Runtime/API/Boundary/Application code.
- Existing applied migrations are immutable. Add new migration files instead of editing shipped migration history.
- Prefer one statement/operation per file with explicit selected/inserted columns; do not use `SELECT *`.

Expected domains include `world`, `timeline`, `event`, `work`, `binding`, `runtime_revision`, `logical_journal`, `session`, `ancestry`, `ingress`, and `projection` as those persistence surfaces land.
