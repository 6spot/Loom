# Loom backup and recovery

Loom durable state is split across PostgreSQL and the blob store. A complete backup plan must cover both.

## 1. Durable components

For the default Compose deployment:

```text
${LOOM_DATA_DIR:-./loom}/
├── postgres/   # PostgreSQL physical data owned by the postgres service
└── blobs/      # Loom immutable blob data used by loom-server
```

Source code is not a substitute for these data directories.

## 2. Recommended logical backup

For a simple consistent maintenance window, stop `loom-server` before taking the backup so application writes are paused while PostgreSQL and blob data are captured.

```bash
docker compose stop loom-server
```

Create a PostgreSQL logical dump using the deployment's actual database/user values:

```bash
docker compose exec -T postgres \
  pg_dump \
  -U loom \
  -d loom_control \
  -Fc \
  > loom-control.dump
```

Back up the blob directory from the configured Loom data root. With the default path:

```bash
tar -czf loom-blobs.tar.gz ./loom/blobs
```

Restart the server:

```bash
docker compose start loom-server
```

If database/user names differ from defaults, use the actual configured values.

## 3. Backup set

Treat these artifacts as one backup set:

```text
PostgreSQL dump
+
matching blob backup
+
deployment configuration needed to reconnect/restart
```

Keep production secrets in the organization's secret-management/backup procedure rather than committing them to the repository.

## 4. Recovery considerations

Recovery must restore PostgreSQL state and the matching blob store before returning the server to normal writes.

A safe high-level sequence is:

1. stop `loom-server`;
2. provision the supported PostgreSQL 18 + pgvector environment;
3. restore the PostgreSQL dump into the intended database;
4. restore the matching blob tree to `${LOOM_DATA_DIR}/blobs`;
5. verify ownership/permissions expected by the deployment;
6. start `loom-server`;
7. inspect startup logs and the public catalog endpoint;
8. verify representative World/History/Blob reads through public Loom surfaces.

Do not use direct SQL edits as semantic recovery steps. Restore persisted data, then let the current Runtime/migration path validate the deployment.

## 5. Production recommendations

A production backup policy should define:

- backup frequency;
- retention;
- off-host/off-site copies;
- encryption and secret handling;
- restore testing;
- recovery-point/recovery-time objectives;
- upgrade-time backups before migrations.

A backup that has never been restored in a test environment should not be treated as proven recovery evidence.