# Loom repository and data layout

This guide explains the parts of the repository an operator/developer is most likely to encounter and separates source code from durable runtime data.

## 1. Top-level repository layout

```text
Loom/
├── apps/
├── capabilities/
├── crates/
├── examples/
├── tests/
├── tools/
├── docker/
├── docs/
├── .github/
├── compose.yaml
├── compose.test-db.yaml
├── Dockerfile
├── .env.example
├── Cargo.toml
├── Cargo.lock
├── rust-toolchain.toml
├── AGENTS.md
└── README.md
```

Loom is one Rust workspace. The crate boundaries below are code responsibility/dependency boundaries, not a microservice layout.

## 2. Applications

`apps/` contains executable/composition roots and user-facing Loom applications:

```text
apps/
├── loom-server/      # main running server/composition root
├── loom-cli/         # official command-line public consumer
└── loom-validator/   # validation/certification application
```

`loom-server` assembles Runtime, Storage, Boundary and selected implementations into the running process. Ordinary upper-layer applications should consume Loom through the public surface; see `docs/application-development/README.md`.

## 3. Core crates

```text
crates/
├── loom-core/        # World language/domain concepts
├── loom-protocol/    # internal execution proposal language
├── loom-api/         # public Loom consumption contract
├── loom-capability/  # semantic extension API/SPI
├── loom-agency/      # cognition/decision/context contracts
├── loom-runtime/     # execution, validation, logical commit, scheduler authority
├── loom-storage/     # persistence adapter, migrations and SQL ownership
├── loom-boundary/    # HTTP/JSON/SSE adapter over loom-api
├── loom-client/      # Rust HTTP client for public Loom API
└── loom-bench/       # benchmark/capacity tooling
```

For exact dependency/public-exposure rules, use `docs/architecture/governance.md` rather than this operational summary.

## 4. Capabilities and examples

```text
capabilities/
└── loom-neutral/

examples/
└── neutral-v0/
```

`loom-neutral` is the current neutral example/fixture capability set. `examples/neutral-v0` contains supported example templates/workflows used by Quickstart and composition testing.

## 5. Tests and tools

```text
tests/
└── loom-composition/

tools/
├── test.sh
├── postgres-test.sh
├── check_architecture.py
├── check_storage_sql_ownership.py
└── validator/gate tooling...
```

These support development/CI and are not persistent runtime data.

## 6. Documentation

```text
docs/
├── architecture/              # canonical architecture authority map/contracts
├── application-development/   # build upper-layer products on Loom
├── development/               # Loom development and test procedures
├── deployment/                # deployment/runbook procedures
├── tasks/                     # implementation audit ledger
├── quickstart.md
├── operator-guide.md
├── developer-guide.md
└── capacity-envelope.md
```

Root `AGENTS.md` is the repository-wide Agent instruction entry point. Application-specific Agent instructions belong under the application itself when needed.

Use `docs/README.md` as the documentation index.

## 7. Container/deployment files

- `compose.yaml` — supported PostgreSQL + `loom-server` single-host stack;
- `compose.test-db.yaml` — PostgreSQL test service, not the production server stack;
- `Dockerfile` — production-oriented `loom-server` image;
- `docker/loom-entrypoint.sh` — container startup/user/blob-directory preparation;
- `.env.example` — non-secret configuration template.

## 8. Durable runtime data

Default Compose data root:

```text
./loom/
├── postgres/
└── blobs/
```

`postgres/` is owned/used by the PostgreSQL service.

`blobs/` is mounted into `loom-server` as its blob store.

This runtime `loom/` directory is fundamentally different from repository source directories. It should normally be ignored by Git and protected by the deployment backup procedure.

## 9. Recommended production separation

A production host can separate source and durable data, for example:

```text
/opt/loom/source/      # Git checkout/build/deployment files
/data/loom/            # LOOM_DATA_DIR
├── postgres/
└── blobs/
/backup/loom/          # backup destination/policy-owned location
```

Set:

```env
LOOM_DATA_DIR=/data/loom
```

This allows source updates/re-clones without treating the repository checkout itself as the only copy of production data.

## 10. What can be recreated vs what must be backed up

Generally recreatable from source/build process:

- `apps/`, `crates/`, `capabilities/`, docs, tools;
- container images;
- Cargo build artifacts.

Durable deployment state requiring backup/recovery policy:

- PostgreSQL data/content;
- Loom blob data;
- external secret/configuration material needed to reconnect the deployment.

See `backup-recovery.md` for the backup workflow.
