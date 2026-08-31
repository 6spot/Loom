# Chronicle application tasks

This ledger tracks executable implementation work for the Chronicle application under `apps/chronicle/`.

Chronicle is an application-level consumer of Loom. Tasks here must not silently redefine Loom Core, Runtime, Storage, or Capability authority. If an application task requires a new Loom semantic/authority decision, stop and use the repository Architecture Amendment process.

## Active tasks

| Task | Issue | Status | Scope |
| --- | ---: | --- | --- |
| C0-T1 | #462 | in_progress | V0 ingestion prototype: deterministic fixture extraction, normalization, JSON Schema validation, and human-gold comparison |
