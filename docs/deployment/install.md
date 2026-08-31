# Loom installation

This guide covers the supported first-deployment paths. Runtime usage after startup is documented in `docs/quickstart.md`.

## 1. Docker Compose deployment (recommended)

Prerequisites:

- Linux host;
- Git;
- Docker Engine;
- Docker Compose v2.

Clone the repository:

```bash
git clone https://github.com/6spot/Loom.git
cd Loom
```

Create local configuration:

```bash
cp .env.example .env
```

At minimum, replace the development PostgreSQL password before production use. Do not commit production secrets.

Validate configuration:

```bash
docker compose -f compose.yaml config --quiet
```

Start the durable stack:

```bash
docker compose up -d --build
```

The Compose stack starts:

- PostgreSQL 18 + pgvector 0.8.6;
- `loom-server` after PostgreSQL becomes healthy.

`loom-server` startup applies the current migrations and assembles the Runtime composition. Scheduler supervision is part of the server lifecycle; no World/Timeline Scheduler target IDs are required.

Check status:

```bash
docker compose ps
```

Check the public catalog endpoint:

```bash
curl -Sf http://127.0.0.1:8080/v1/catalog
```

For a human-readable CLI check from a Rust development checkout:

```bash
cargo run -p loom-cli -- \
  --server http://127.0.0.1:8080 \
  --output human \
  catalog
```

## 2. Data location

By default Compose stores durable state under:

```text
./loom/
├── postgres/
└── blobs/
```

Set `LOOM_DATA_DIR` to an absolute host path for a production deployment, for example:

```env
LOOM_DATA_DIR=/data/loom
```

Keep the `postgres/` and `blobs/` children together under the chosen Loom data root unless a future canonical deployment procedure says otherwise.

See `repository-and-data-layout.md` for ownership details.

## 3. Native server startup

Use this path when PostgreSQL 18 + pgvector 0.8.6 is already managed outside the official Compose stack.

The repository pins Rust 1.97.1.

Build:

```bash
cargo build --release -p loom-server
```

Set the connection and data root:

```bash
export LOOM_DATABASE_URL='postgresql://loom:<password>@127.0.0.1:5432/loom_control'
export LOOM_DATA_DIR='/data/loom'
export LOOM_BIND_ADDR='0.0.0.0:8080'
```

Start:

```bash
./target/release/loom-server
```

The native process follows the same Runtime/migration authority as the Compose server.

## 4. First-deployment acceptance

Before considering the base deployment usable, verify:

- PostgreSQL is healthy;
- `loom-server` remains running;
- `/v1/catalog` responds successfully;
- startup logs do not show migration/registry/revision failures;
- persistent `postgres/` and `blobs/` paths exist at the intended data root;
- a clean server restart preserves the existing database state.

Then use `docs/quickstart.md` to create a World and exercise the public Loom workflow.