# Application integration

This guide covers how an upper-layer application connects to Loom and how to keep application-owned persistence separate from Loom-owned state.

## Connect through public surfaces

For a separately running application, prefer the public `loom-server` HTTP surface through `loom-client` or another client generated/implemented against `loom-api` semantics.

Use `docs/quickstart.md` as the executable reference for currently supported public operations.

## Do not connect to Loom PostgreSQL as an application API

The Loom database is a persistence implementation behind Runtime-owned contracts.

An application must not read or mutate Loom tables directly to implement product features. Direct SQL creates a second contract that bypasses Loom validation, history, ordering and evolution rules.

## Application-owned databases

An application may use its own database for concerns it owns, such as:

- users and product accounts;
- UI preferences;
- import job bookkeeping;
- external-source metadata;
- derived search/index caches;
- application analytics.

Keep the authority boundary explicit. If a value is authoritative World state, read/write it through Loom. If it is application metadata, keep it application-owned.

## Import pipelines

For ingestion-heavy applications, use a staged pipeline:

```text
external source
→ raw/staging record
→ normalization/validation
→ Loom-compatible application command
→ public Loom Action/Ingress surface
→ authoritative Loom state/history
```

The staging layer is allowed to be retryable and replaceable. It must not silently become the semantic source of truth after data has been accepted into Loom.

## Failure handling

Treat transport failures, rejected Loom operations and semantic validation failures differently. Do not turn an HTTP retry mechanism into a second semantic retry/ordering engine.

For server deployment and operator recovery, follow `docs/deployment/` and `docs/operator-guide.md` rather than application-specific database repair scripts.
