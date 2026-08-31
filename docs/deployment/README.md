# Loom deployment guides

This directory contains the current supported deployment and operator runbooks for Loom.

Use one guide per workflow rather than one large deployment manual.

## Guides

- [`install.md`](install.md) — first deployment with Docker Compose and native `loom-server` startup.
- [`configuration.md`](configuration.md) — environment variables, ports, data root and Compose wiring.
- [`operations.md`](operations.md) — start/stop/restart/update, health checks, logs and basic runtime inspection.
- [`backup-recovery.md`](backup-recovery.md) — PostgreSQL + blob backup and recovery considerations.
- [`troubleshooting.md`](troubleshooting.md) — deployment/runtime symptoms and first diagnostic steps.
- [`repository-and-data-layout.md`](repository-and-data-layout.md) — project directories, executable roots and persistent data layout.

For public Loom workflows after the service is running, use `docs/quickstart.md`.

For Runtime concepts an operator needs to interpret, use `docs/operator-guide.md`.

For local development/test procedures, use `docs/development/README.md`.

## Supported baseline

The current official single-host deployment uses:

- Linux/Ubuntu baseline;
- PostgreSQL 18 + pgvector 0.8.6;
- `compose.yaml` for PostgreSQL + `loom-server`;
- `${LOOM_DATA_DIR:-./loom}/postgres` for PostgreSQL data;
- `${LOOM_DATA_DIR:-./loom}/blobs` for Loom blob data;
- lifecycle-managed Scheduler supervision inside `loom-server`.

Current repository configuration is the final operational source. When this documentation and configuration disagree, fix the documentation/configuration conflict rather than preserving two deployment paths.