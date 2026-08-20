//! Loom Storage: persistence implementations behind Runtime/Core contracts.
//!
//! # Responsibility
//!
//! This crate implements durable representations for Timeline authority, Event
//! Ledger data, materialized State/Facets, Entity/Relationship structure,
//! Durable Work, execution/runtime metadata, pgvector-backed semantic retrieval
//! and object-store references.
//!
//! PostgreSQL is the authoritative database for v0 World/Runtime structured
//! state; object storage holds large immutable/content-addressable blobs. Search,
//! graph, analytics or specialized vector systems may be added later only as
//! rebuildable projections unless the authority architecture is explicitly
//! reviewed again.
//!
//! # Semantic boundary
//!
//! Storage implements persistence semantics chosen by Core/Runtime; it does not
//! define world meaning. Table layout, indexes, JSONB representation, partitions
//! and SQL optimizations are implementation details as long as they preserve the
//! authority, ordering, transaction and replay contracts.
//!
//! # Commit boundary
//!
//! Storage must not accept arbitrary Capability output as commit input. The
//! commit API is expected to require a Runtime-produced `ValidatedResolution`
//! (or equivalent private authority token) and perform Timeline CAS, Event append,
//! State Effects, Work mutations and current-Work completion atomically.
//!
//! # Query model
//!
//! Queryable/referential structures such as Event participants, Event causality,
//! Relationship participants and stable identity references should be normalized;
//! flexible Capability payload/state may use JSONB. Embeddings are retrieval
//! projections, not World Truth.
//!
//! # Documentation contract
//!
//! Public persistence abstractions must document which data is authoritative,
//! which data is materialized/projection/runtime metadata, transaction guarantees,
//! replay expectations and failure behavior. See
//! `docs/architecture/runtime-contracts.md`.

#![forbid(unsafe_code)]
