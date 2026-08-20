//! Loom Storage: persistence adapters implementing Runtime-owned ports.
//!
//! # Responsibility
//!
//! This crate contains concrete persistence implementations for Timeline
//! authority, Event Ledger data, materialized State/Facets,
//! Entity/Relationship structure, Durable Work, execution/runtime metadata,
//! pgvector-backed semantic retrieval and object-store references.
//!
//! PostgreSQL is the authoritative database for v0 structured World/Runtime
//! state; object storage holds large immutable/content-addressable blobs. Search,
//! graph, analytics or specialized vector systems may be added later only as
//! rebuildable projections unless the authority architecture is explicitly
//! reviewed again.
//!
//! # Dependency inversion
//!
//! Runtime defines the persistence ports required by its execution/commit
//! authority. Storage depends on `loom-runtime` and implements those ports:
//!
//! ```text
//! loom-storage -> loom-runtime
//! loom-runtime -X-> loom-storage
//! ```
//!
//! The Application composition root creates the concrete adapter (for example
//! `PgStorage`) and injects it into Runtime. Runtime must never import
//! `loom_storage::PgStorage` or otherwise know which database implementation was
//! selected.
//!
//! Storage may also use stable `loom-core` identities/value types where required
//! by its concrete representation.
//!
//! # Semantic boundary
//!
//! Storage implements persistence semantics chosen by Core/Runtime; it does not
//! define World meaning. Table layout, indexes, JSONB representation, partitions
//! and SQL optimizations are implementation details as long as they preserve the
//! authority, ordering, transaction and replay contracts.
//!
//! # Commit authority
//!
//! Storage must not accept arbitrary Capability/Protocol output as a World
//! commit. A Runtime-owned persistence port may require a Runtime-produced
//! `ValidatedResolution` (or equivalent authority token). Storage can consume
//! that value through the trait contract but cannot construct it or downgrade
//! the authority check to accepting raw `Resolution`.
//!
//! The concrete PostgreSQL transaction must preserve Timeline CAS, Event append,
//! frozen State Effects, Work mutations and current-Work completion atomically.
//!
//! # Query model
//!
//! Queryable/referential structures such as Event participants, Event causality,
//! Relationship participants and stable identity references should be normalized;
//! flexible Capability payload/state may use JSONB. Embeddings are retrieval
//! projections, not World Truth.
//!
//! # Public exposure
//!
//! Storage is not a public Loom API. HTTP/CLI/GPUI/SDK consumers must never call
//! repositories or SQL queries directly. Public reads/writes go through
//! `loom-api` and Runtime authority.
//!
//! # Documentation contract
//!
//! Public persistence abstractions must document which data is authoritative,
//! which data is materialized/projection/runtime metadata, transaction
//! guarantees, replay expectations and failure behavior. See
//! `docs/architecture/governance.md` and
//! `docs/architecture/runtime-contracts.md`.

#![forbid(unsafe_code)]
