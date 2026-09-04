# Chronicle server (C1-T2)

The long-lived Rust Chronicle application server boundary for C1. One
binary (`chronicle-server`, crate `apps/chronicle/server/`) owns the
Chronicle HTTP surface: distinct public and Studio API namespaces,
single-administrator Studio authentication, health/error behavior, graceful
shutdown, and the same-origin web front.

## Authority boundary

The Rust server owns HTTP transport, routing, and authorization. It does
**not** own historical knowledge:

- Timeline / Event / Entity / Search reads are forwarded to the proven C0
  Python read model (`apps/chronicle/read_api/`, same `CHRONICLE_DATABASE_URL`
  PostgreSQL). The C0 read model remains the single historical read
  authority; this crate introduces no second one.
- The server never opens the Chronicle database directly. Governance
  (`tools/check_storage_sql_ownership.py`) forbids SQLx/PostgreSQL driver
  dependencies in Rust outside `loom-storage`, and this crate has none: no
  `sqlx`, no `tokio-postgres`, no inline SQL, no `loom-*` dependency.
- No Loom Runtime/World/Timeline/Work/Binding authority is read, written,
  or exposed (Architecture Amendment 0006). The server only serves
  Chronicle application-owned product data through the C0 read contracts.
- Proven C0 code (`read_api/server.py`, `web/`) is preserved, not deleted.
  The C0 server runs as the upstream read sidecar during the migration.

If a future need requires the Rust server to take over reads or touch Loom
engine internals, that is an architecture decision first (C1-T2 stop
condition), not an implementation shortcut.

## Entry point and namespaces

```bash
chronicle-server            # reads CHRONICLE_* environment, see below
```

```text
GET /healthz                        public, no auth, no upstream
GET /api/v1/public/timeline         -> upstream /v0/timeline
GET /api/v1/public/search           -> upstream /v0/search
GET /api/v1/public/events/{id}      -> upstream /v0/events/{id}
GET /api/v1/public/entities/{id}    -> upstream /v0/entities/{id}
GET /v0/...                         legacy C0 compat, same upstream mapping
GET /api/v1/studio/status           privileged, admin auth required
/api/v1/studio/* (other)            privileged, admin auth required, 404 when authed
/ , /timeline, /search,             same-origin zero-build browser UI
/events/{id}, /entities/{id},       (embedded at compile time)
/*.mjs, /*.css
```

Only `GET` is served on read routes (C0 parity: other methods get typed
`405 method_not_allowed`). API-shaped unknowns return typed JSON errors;
unknown Studio paths require authentication before revealing existence.

## Studio authentication

One environment-configured administrator. No user database, no RBAC, no
password reset (C1 non-goals).

```bash
CHRONICLE_ADMIN_USER=admin
CHRONICLE_ADMIN_PASSWORD=<at least 8 characters, no control characters>
```

- Both variables must be set together; the server refuses to start when
  only one is present.
- When both are absent, the server still starts but every Studio route
  fails closed with typed `503 studio_auth_unconfigured`. Public reads and
  the web front keep working.
- Clients authenticate with HTTP Basic (`Authorization: Basic ...`) and
  receive `401 unauthorized` plus a `Basic realm="chronicle-studio"`
  challenge when credentials are missing or wrong. Comparison is
  constant-time over both fields.
- Studio document/import/review operations arrive with C1-T3/C1-T4. Until
  then the privileged namespace is the auth boundary plus operational
  status; it must not be bypassed by calling the upstream sidecar directly
  (the sidecar is not published outside the deployment network).

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `CHRONICLE_BIND` | `127.0.0.1` | interface to bind |
| `CHRONICLE_PORT` | `8080` | TCP port to bind |
| `CHRONICLE_UPSTREAM_URL` | `http://127.0.0.1:8081` | C0 read-model sidecar (`http://` only; embedded userinfo rejected) |
| `CHRONICLE_ADMIN_USER` | _(absent)_ | Studio administrator login (ASCII, no `:`/whitespace) |
| `CHRONICLE_ADMIN_PASSWORD` | _(absent)_ | Studio administrator password (min 8 chars) |

Invalid bind/port/upstream values fail startup with a plain-text reason on
stderr and a non-zero exit. Startup prints one JSON line with bind, port,
upstream host/port, and `studio_auth: enabled|disabled` — never
credentials, connection strings, or password material. Per-request access
logs carry method, path without query, and status only.

## Errors, health, shutdown

- Errors use the C0 envelope
  (`{"schema":"chronicle.error","version":"0.1","error":{"code":...}}`)
  with codes `bad_request`, `unauthorized`, `not_found`,
  `method_not_allowed`, `upstream_bad_response`, `upstream_unavailable`,
  `studio_auth_unconfigured`.
- `GET /healthz` returns exactly `{"status":"ok"}` without touching the
  upstream or any credential, so container healthchecks stay meaningful
  during database outages.
- Upstream failures map explicitly: unreachable/timeout becomes
  `503 upstream_unavailable`; an unusable upstream response becomes
  `502 upstream_bad_response`. Upstream status/body otherwise pass through
  unchanged, preserving C0 read semantics byte-for-byte.
- SIGINT/SIGTERM trigger graceful shutdown: in-flight requests drain, then
  the process exits. The shutdown lifecycle is covered by an integration
  test that boots the real router on an ephemeral port.

## Deployment topology

```text
Internet / reverse proxy
        |
        v
chronicle-web :8080 (chronicle-server: namespaces, auth, web front)
        |
        v  CHRONICLE_UPSTREAM_URL=http://chronicle-read:8081
Docker private network
        |
        +--> chronicle-read :8081 (C0 Python read server, internal only)
        +--> postgres :5432
        +--> chronicle-init (one-shot, idempotent import)
```

`chronicle-read` has no host port mapping. Local development without
Compose:

```bash
export CHRONICLE_DATABASE_URL='postgresql://.../chronicle'
python3 apps/chronicle/read_api/server.py --host 127.0.0.1 --port 8081 &
CHRONICLE_UPSTREAM_URL=http://127.0.0.1:8081 \
CHRONICLE_ADMIN_USER=admin \
CHRONICLE_ADMIN_PASSWORD=<secret> \
cargo run --manifest-path apps/chronicle/server/Cargo.toml
```

(The crate is a standalone workspace following the `control_plane`
precedent, so root `Cargo.toml`/`Cargo.lock` are untouched; run its checks
inside `apps/chronicle/server/`: `cargo test`, `cargo clippy --all-targets
-- -D warnings`, `cargo fmt --check`.)

## Verification

- `cargo test` — config/auth/error/static/upstream unit tests plus live
  router integration tests against a mock TCP upstream (namespaces, auth
  matrix, typed errors, web front, shutdown).
- The `Chronicle` workflow additionally fronts the real two-source import
  through the Rust binary and asserts public search plus the Studio
  auth matrix over real HTTP.
- The `Chronicle Docker` workflow deploys the Compose stack and asserts
  the same contracts through the published port.
