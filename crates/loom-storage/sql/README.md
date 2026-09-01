# PostgreSQL SQL ownership

This directory contains Loom engine/runtime PostgreSQL statements. Schema evolution and DDL stay in `../migrations/`.

Rules:

- `loom-storage` is the only crate that may own SQLx/PostgreSQL implementation details for **Loom engine persistence authority**.
- Production Loom-engine `SELECT`, `INSERT`, `UPDATE`, and `DELETE` statements live in this directory, grouped by persistence domain.
- Rust adapter code owns transaction orchestration, parameter binding, result decoding, and Runtime-port implementation; it loads SQL from these files with `include_str!`.
- Do not expose `PgPool`, SQLx transactions, PostgreSQL row types, Loom engine table names, or direct Loom storage authority to Runtime/API/Boundary/Application code.
- Existing applied migrations are immutable. Add new migration files instead of editing shipped migration history.
- Prefer one statement/operation per file with explicit selected/inserted columns; do not use `SELECT *`.

Expected Loom-engine domains include `world`, `timeline`, `event`, `work`, `binding`, `runtime_revision`, `logical_journal`, `session`, `ancestry`, `ingress`, and `projection` as those persistence surfaces land.

## Application-owned product persistence

Architecture Amendment 0006 distinguishes Loom engine persistence from explicitly registered Application-owned product persistence. A registered Application may own an independent product database/schema, migrations, database driver and queries only for data whose semantic authority belongs to that Application.

That exception does **not** grant access to `PgStorage`, Loom engine SQL, `LOOM_DATABASE_URL`, Runtime persistence ports, or Loom World/Timeline/Work/Binding tables. Loom semantic operations must still go through Loom API/Runtime.

Application SQL roots are closed and explicitly registered by architecture enforcement; there is no general `apps/**` SQL exemption. The first v0 registration is Chronicle's product persistence under `apps/chronicle/persistence/`, using `CHRONICLE_DATABASE_URL` for its historical source/resolution/canonical corpus.
