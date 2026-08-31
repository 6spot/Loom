# Loom operations

This runbook covers routine service operations for the supported Compose deployment.

## 1. Start and inspect

Start the stack:

```bash
docker compose up -d
```

Rebuild after source changes:

```bash
docker compose up -d --build
```

Inspect services:

```bash
docker compose ps
```

Inspect all logs:

```bash
docker compose logs
```

Follow server logs:

```bash
docker compose logs -f loom-server
```

Inspect PostgreSQL logs:

```bash
docker compose logs postgres
```

## 2. Health check

Check the public catalog endpoint:

```bash
curl -Sf http://127.0.0.1:8080/v1/catalog
```

A successful response verifies the public HTTP path is reachable. Use logs and CLI/admin inspection for deeper Runtime diagnosis.

## 3. Stop and restart

Stop services without removing containers:

```bash
docker compose stop
```

Start stopped services:

```bash
docker compose start
```

Restart only Loom Server:

```bash
docker compose restart loom-server
```

Remove Compose containers/network while leaving bind-mounted data on disk:

```bash
docker compose down
```

Do not delete the configured Loom data root unless intentional data destruction is required.

## 4. Scheduler operation

Scheduler supervision is part of `loom-server`.

The running server automatically discovers existing, newly created and forked Timelines that retain Pending Work. Operators do not register World/Timeline target IDs in deployment configuration and do not restart the server merely to make a new Timeline visible to Scheduler discovery.

When a Timeline does not progress, inspect Runtime/Work state instead of assuming discovery failed. See `docs/operator-guide.md` and `troubleshooting.md`.

## 5. Update the deployment

Recommended source-based update sequence:

```bash
git pull
docker compose -f compose.yaml config --quiet
docker compose build --pull loom-server
docker compose up -d
```

Then verify:

```bash
docker compose ps
docker compose logs --tail=200 loom-server
curl -Sf http://127.0.0.1:8080/v1/catalog
```

Back up durable data before production upgrades, especially when migrations are involved.

## 6. Runtime inspection

For public World/Timeline operations use `docs/quickstart.md`.

For operator concepts and admin CLI commands use `docs/operator-guide.md`.

Do not repair semantic state with direct SQL. Runtime/admin public procedures own logical recovery operations such as authorized Work terminalization.