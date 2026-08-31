# Loom deployment troubleshooting

Use this guide for first-response deployment diagnosis. Runtime semantics and operator recovery remain documented in `docs/operator-guide.md`.

## 1. Compose does not start

Validate the rendered configuration first:

```bash
docker compose -f compose.yaml config --quiet
```

Then inspect service state and logs:

```bash
docker compose ps
docker compose logs --tail=200 postgres
docker compose logs --tail=200 loom-server
```

Common first checks:

- `.env` syntax;
- bind-mount path availability/permissions;
- host port conflicts;
- Docker build failures;
- PostgreSQL healthcheck failures.

## 2. PostgreSQL is unhealthy

Inspect:

```bash
docker compose logs postgres
```

Verify the configured data root and database/user/password values. Do not delete `postgres/` as a generic repair step; that is durable data destruction.

If a production database is externally managed, verify `LOOM_DATABASE_URL` and that the target is PostgreSQL 18 with the required pgvector extension support.

## 3. `loom-server` exits on startup

Inspect:

```bash
docker compose logs --tail=300 loom-server
```

Classify the failure before changing configuration:

- database connection/health;
- migration failure;
- Capability registry/composition failure;
- Runtime Revision publication/activation failure;
- bind/data-directory failure;
- invalid environment configuration;
- HTTP bind/port failure.

Do not bypass startup validation merely to keep the container running.

## 4. HTTP endpoint is unreachable

Check service state:

```bash
docker compose ps
```

Check server logs, then confirm the host port mapping from:

```bash
docker compose -f compose.yaml config
```

Test locally:

```bash
curl -v http://127.0.0.1:8080/v1/catalog
```

If a reverse proxy is used, isolate the problem by testing Loom locally before debugging the proxy/TLS layer.

## 5. `.env` change appears ignored

Remember that Compose `.env` values are interpolation inputs, not automatic environment passthrough.

Inspect:

```bash
docker compose -f compose.yaml config
```

Verify the intended variable appears inside the rendered `loom-server.environment` section. If it does not, the current Compose file is not wiring that variable into the container.

## 6. Timeline is not progressing

Do not immediately restart containers or add Scheduler target variables.

The current server automatically discovers Timelines with Pending Work. A Timeline may still be intentionally blocked by Runtime conditions such as:

- logical head ordering;
- World-Time due-ness;
- retry/backoff or lease claimability;
- Chronology Budget;
- missing compatible implementation.

Use the operator inspection procedures in `docs/operator-guide.md` to identify the actual Runtime state.

## 7. New/forked Timeline is not manually registered

There is no supported deployment step to register a World/Timeline Scheduler target. New and forked Timelines with Pending Work are discovered while `loom-server` remains running.

If behavior contradicts this, diagnose current server/runtime state and logs rather than reintroducing removed target environment variables.

## 8. Data permissions

The server image runs `loom-server` as the non-root `loom` user after preparing `/var/lib/loom/blobs`. PostgreSQL owns its separate data bind mount.

Do not solve a blob permission problem by recursively changing ownership of the PostgreSQL data tree to the Loom server user.

## 9. Escalation evidence

When reporting a deployment failure, capture:

- current commit SHA;
- sanitized relevant `.env`/Compose settings;
- `docker compose config` result or relevant section;
- `docker compose ps`;
- recent PostgreSQL/server logs;
- exact failing public/CLI command;
- whether the failure survives a normal service restart.

Do not include passwords or tokens in issue/Agent logs.