# Loom deployment configuration

This guide explains the deployment-facing configuration surface. Application semantics remain owned by the current architecture/runtime documentation.

## 1. Base database and data-root settings

Current `.env.example` includes:

```env
POSTGRES_USER=loom
POSTGRES_PASSWORD=loom
POSTGRES_DB=loom_control
LOOM_DATABASE_URL=postgresql://loom:loom@localhost:5432/loom_control
LOOM_DATA_DIR=./loom
LOOM_BIND_ADDR=0.0.0.0:8080
```

For Compose, `LOOM_DATABASE_URL` is assembled with host `postgres:5432`; native startup uses the configured URL directly.

Production deployments should replace the development PostgreSQL password and keep secrets outside version control.

## 2. Port publishing

The container listens on port 8080. The host port is selected by `LOOM_PORT` in `compose.yaml` and defaults to 8080.

Default effective mapping:

```text
host :8080 → loom-server :8080
```

If Loom should only be reachable through a local reverse proxy, restrict the host binding in a deployment-specific Compose override rather than exposing an unprotected management surface to the public Internet.

## 3. Runtime publication metadata

The current deployment exposes stable non-secret publication metadata such as:

```env
LOOM_RUNTIME_REVISION_ID=loom-server
LOOM_CORE_BUILD_REF=loom-server-0.1.0
```

These describe the running software composition. Do not use them as mutable World state or as a substitute for Runtime Revision APIs.

## 4. Worker/Scheduler operational settings

Current deployment wiring includes operational settings such as:

```env
LOOM_WORKER_LEASE_MS=30000
LOOM_WORKER_RETRY_BACKOFF_MS=1000
LOOM_WORKER_SCHEDULER_POLL_LIMIT=1
LOOM_WORKER_POLL_MS=100
LOOM_INGRESS_QUEUE_CAPACITY=256
```

These tune operational cadence/capacity. They do not grant the deployment layer authority over logical Work ordering or World Time.

The current Scheduler Supervisor discovers Timelines automatically. Do not add per-World or per-Timeline deployment target variables.

## 5. `.env` is not automatic container passthrough

Docker Compose uses `.env` for interpolation. A variable existing in `.env.example` does **not** by itself guarantee that the variable is present inside `loom-server`.

Before relying on a deployment setting, inspect the rendered configuration:

```bash
docker compose -f compose.yaml config
```

Check the `loom-server.environment` section for the variable.

This is especially important for Runtime and HTTP resource limits listed in `.env.example`: only variables explicitly wired by the current Compose configuration are passed to the container.

## 6. Native startup

For native `loom-server`, the process reads supported environment variables directly. Use the current `.env.example` and `apps/loom-server` configuration parser as the source for supported names/defaults.

Do not reuse environment variables from historical tasks or old CI logs without confirming they still exist in the current code.

## 7. Validate changes

For deployment configuration changes, run at least:

```bash
docker compose -f compose.yaml config --quiet
```

When changing environment wiring, also inspect the rendered configuration and verify the intended value is present under the correct service.