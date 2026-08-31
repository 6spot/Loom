# Loom deployment security

This guide contains deployment-facing security guidance only. The authoritative application authorization model remains owned by the current API/Runtime implementation and architecture.

## 1. Do not expose admin operations casually

The default server listens on `0.0.0.0:8080` inside the container and Compose publishes a host port.

For Internet-facing deployments, place Loom behind the organization's normal perimeter controls, for example:

- firewall/private-network rules;
- reverse proxy;
- TLS termination;
- authentication/access-control policy;
- request/rate limits appropriate to the deployment.

Avoid exposing administrative operations directly to an untrusted network.

## 2. Secrets

`.env.example` contains development defaults, not production secrets.

At minimum replace the development PostgreSQL password in production and keep secret values outside Git.

Do not include passwords, bearer tokens or admin tokens in:

- committed `.env` files;
- GitHub Issues/PR comments;
- Agent completion reports;
- troubleshooting log excerpts.

## 3. Host port restriction

If only a local reverse proxy should reach Loom, use a deployment-specific Compose override to bind the host port to loopback or a private interface instead of all host interfaces.

Keep such environment-specific policy out of the repository's generic `compose.yaml` unless it becomes the supported universal baseline.

## 4. Data permissions

The runtime image prepares the Loom blob path and runs `loom-server` as the non-root `loom` user.

PostgreSQL data belongs to the separate PostgreSQL service. Do not merge ownership of the PostgreSQL and Loom server data trees merely to solve a permissions issue.

## 5. Backups

Protect PostgreSQL dumps and blob backups as production data. Apply the organization's encryption, access-control and retention policy.

See `backup-recovery.md` for backup composition.