# Chronicle Docker deployment

Chronicle can be deployed independently from Loom's Rust server with its own PostgreSQL database and Docker Compose stack.

The production stack is defined by:

```text
apps/chronicle/Dockerfile
compose.chronicle.yaml
.env.chronicle.example
```

## Topology

```text
Internet / reverse proxy
        |
        v
chronicle-web :8080
        |
        v
Docker private network
        |
        +--> postgres :5432
        |
        +--> chronicle-init (one-shot, idempotent import)
```

`postgres` is not published to the host. Only the Chronicle HTTP service may be published.

`chronicle-init` waits for PostgreSQL, applies Chronicle migrations, and imports the retained accepted 武帝纪 + 吴主传 staged / resolution / canonical artifacts. Re-running the same deployment is safe because Chronicle persistence is idempotent for identical accepted artifacts.

## Server prerequisites

The host needs only:

- Git;
- Docker Engine;
- Docker Compose v2 (`docker compose`).

No host Python, Rust, PostgreSQL, pgvector, Node.js, or Chronicle virtualenv is required.

## First deployment

Clone the repository and switch to the desired release/main revision:

```bash
git clone https://github.com/6spot/Loom.git
cd Loom
git switch main
git pull --ff-only
```

Create the environment file:

```bash
cp .env.chronicle.example .env.chronicle
```

Generate a URL-safe database password. Hex is recommended because the Compose connection URL embeds the password directly:

```bash
openssl rand -hex 32
```

Edit `.env.chronicle` and replace `CHRONICLE_POSTGRES_PASSWORD` with that value.

Choose a persistent host directory, for example:

```text
CHRONICLE_DATA_DIR=/srv/loom-data/chronicle
```

Create it before the first start:

```bash
sudo mkdir -p /srv/loom-data/chronicle/postgres
```

Then start the complete stack:

```bash
docker compose \
  --env-file .env.chronicle \
  -f compose.chronicle.yaml \
  up -d --build
```

Inspect status:

```bash
docker compose \
  --env-file .env.chronicle \
  -f compose.chronicle.yaml \
  ps
```

The expected steady state is:

- `postgres` — running / healthy;
- `chronicle-init` — exited with code 0;
- `chronicle-web` — running / healthy.

Inspect the one-shot import result:

```bash
docker compose \
  --env-file .env.chronicle \
  -f compose.chronicle.yaml \
  logs chronicle-init
```

The retained current dataset should report:

```text
chronicle persistence: PASS ... bundles=2 entities=66 events=45 relations=2
```

## Access

By default `.env.chronicle.example` binds Chronicle to loopback only:

```text
CHRONICLE_BIND_IP=127.0.0.1
CHRONICLE_PORT=8080
```

This is recommended when Nginx, Caddy, Traefik, Tailscale, or another reverse proxy provides public HTTPS.

Health check on the server:

```bash
curl http://127.0.0.1:8080/healthz
```

Timeline:

```text
http://127.0.0.1:8080/timeline
```

Search:

```text
http://127.0.0.1:8080/search?q=曹操
```

For temporary direct public access without a reverse proxy, set:

```text
CHRONICLE_BIND_IP=0.0.0.0
```

and allow the configured `CHRONICLE_PORT` through the host/cloud firewall. Direct public HTTP is suitable for short-lived testing; use HTTPS through a reverse proxy for normal internet-facing deployment.

## Upgrade

Pull the desired revision and rerun Compose:

```bash
git switch main
git pull --ff-only

docker compose \
  --env-file .env.chronicle \
  -f compose.chronicle.yaml \
  up -d --build
```

The init container runs again. Identical accepted data imports are no-ops; schema migration checksum drift or immutable-data conflicts fail explicitly rather than overwriting historical records.

## Logs

```bash
docker compose --env-file .env.chronicle -f compose.chronicle.yaml logs -f chronicle-web
```

PostgreSQL logs:

```bash
docker compose --env-file .env.chronicle -f compose.chronicle.yaml logs -f postgres
```

## Stop and restart

Stop containers while preserving PostgreSQL files:

```bash
docker compose --env-file .env.chronicle -f compose.chronicle.yaml down
```

Start again:

```bash
docker compose --env-file .env.chronicle -f compose.chronicle.yaml up -d
```

Do not delete `CHRONICLE_DATA_DIR/postgres` unless intentionally destroying the Chronicle database.

## Backup

The PostgreSQL directory is persistent, but use `pg_dump` for a portable logical backup:

```bash
docker compose \
  --env-file .env.chronicle \
  -f compose.chronicle.yaml \
  exec -T postgres \
  pg_dump -U "$CHRONICLE_POSTGRES_USER" -d "$CHRONICLE_POSTGRES_DB" -Fc \
  > chronicle-$(date +%Y%m%d-%H%M%S).dump
```

If the shell does not have the variables exported, source the env file first:

```bash
set -a
. ./.env.chronicle
set +a
```

The checked-in accepted artifacts remain an independent replay path; a database backup does not replace their provenance role.

## Security boundary

- PostgreSQL is available only on the Compose network and has no host port mapping.
- Chronicle uses its own database credentials and does not consume `LOOM_DATABASE_URL`.
- The browser still reads only the Chronicle HTTP API; it never connects to PostgreSQL directly.
- Use a strong unique database password and do not commit `.env.chronicle`.
- Put the HTTP service behind HTTPS for normal public access.
