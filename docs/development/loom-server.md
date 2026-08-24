## Supported Linux deployment

`loom-server` is the production-like composition root. Native startup and the
container entrypoint both run the same sequence: connect to PostgreSQL, check
health, apply repository migrations, validate the installed Capability registry,
confirm/activate the Runtime Revision, construct Runtime/Boundary/workers, and
only then bind the HTTP listener.

Copy `.env.example` to `.env` for local defaults, then run:

```text
docker compose config
docker compose up --build
```

The supported single-host durable root is `${LOOM_DATA_DIR:-./loom}`. Compose
bind-mounts only its documented children:

```text
./loom/postgres  -> PostgreSQL's /var/lib/postgresql
./loom/blobs     -> loom-server's /var/lib/loom/blobs
```

No Docker named volume owns Loom data, and the server container never receives
the PostgreSQL child directory. Change `LOOM_DATA_DIR` to relocate the complete
tree while preserving the `postgres/` and `blobs/` child names.

Required deployment variables are `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`POSTGRES_DB`, `LOOM_DATABASE_URL` (native startup), and `LOOM_DATA_DIR`.
`LOOM_BIND_ADDR`, Runtime publication metadata, bounded worker settings,
Runtime semantic/resource limits, and HTTP limits have non-secret defaults
documented in `.env.example`. Runtime limits are enforced for in-process
callers as well as HTTP requests; transport limits are an independent early
rejection layer. Chronology and technical retry policies are also configured at
the composition root. Provider credentials are not part of this composition
root and must be supplied only by application configuration when a reviewed
provider adapter is installed.
