---
task: M12-T1
issue: 198
status: completed
depends_on: [179, 197]
created_at: 2026-08-22
started_at: 2026-08-25
completed_at: 2026-08-25
completion_pr:
merge_sha:
---
# M12-T1 — Official `loom-cli`

- Pure consumer of formal HTTP client/loom-api; no Runtime/Storage/concrete Capability/PgStorage dependency.
- Commands for Catalog/Template/World/Action/State/History/trajectory/causality/fork/feed/Ingress/revision/provenance/Admin controls where authorized.
- Human + deterministic JSON output and meaningful exit/error mapping.
- Configurable URL/auth; no secrets.
- Server remains authority; local validation is UX only.
- Integration tests cover representative workflows.

## Acceptance
- [x] Blocking V0 workflows usable through CLI.
- [x] JSON IDs/cursors script-safe.
- [x] Errors/exit codes meaningful.
- [x] Feed/fork/provenance/Admin operations work.
- [x] Architecture/integration + standard gates pass.

## Verification evidence
- 2026-08-25 workspace `apps/loom-cli` added; `Cargo.toml` workspace members updated; `tools/check_architecture.py` allowlist extended to `loom-client` for `loom-cli`
- `cargo fmt --all -- --check`: ok (after `cargo fmt --all`)
- `cargo check --workspace --all-targets --all-features`: ok
- `cargo clippy --workspace --all-targets --all-features -- -D warnings`: ok
- `cargo doc --workspace --no-deps`: ok
- `cargo deny check advisories bans licenses sources`: ok (advisories ok, bans ok, licenses ok, sources ok)
- `python3 tools/check_architecture.py`: Loom architecture dependency policy: OK, storage SQL ownership check passed
- `cargo test -p loom-cli --all-features`: 4 unit (exit_code_mapping, catalog parsing, client url validation) + 4 integration (cli_output_modes_deterministic, cli_error_mapping_via_client, cli_workflows_via_formal_client_against_boundary, cli_admin_workflows_with_auth) = 8 passed
- Integration tests exercise against `loom-boundary` + `InMemoryStore` + `loom-neutral` registry via `loom-client` (HTTP/SSE) covering: catalog (global/per-world), world create-from-template, timeline inspect/fork, action invoke (seed/increment), facet get, history events/page/event/causes/effects/causal-walk, entity/relationship trajectory, feed subscribe/resume (cursor+SSE), ingress submit/status, admin revision list/get/active/activate, execution sessions/session-for-event, timeline logical status, missing-implementation, terminalize-work, agency-wake schedule, advance-world-time, error mapping
- CLI binary verified: `cargo run -p loom-cli -- --help` lists all commands; `--server`/`--bearer-token`/`--admin-token` via flags+env (`LOOM_SERVER_URL`, `LOOM_BEARER_TOKEN`, `LOOM_ADMIN_TOKEN`) no hard-coded secrets; JSON output via `loom-api` DTO serde (compact) and human pretty; `ApiErrorCode` mapped to distinct exit codes 10-16; local validation (UUID, JSON) UX-only, server authoritative
- No `loom-runtime`/`loom-storage`/`loom-capability`/`loom-boundary`/`PgStorage` production dependencies (only `loom-client` + `loom-api` + `clap`/`tokio`/`serde`); dev-deps use `loom-boundary`/`loom-runtime` for tests only
