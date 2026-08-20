//! Loom Core: the stable **World Language** of Loom.
//!
//! # Responsibility
//!
//! This crate defines the smallest domain-independent vocabulary required for a
//! persistent Loom World to exist: strong identities, Timeline/world-time value
//! types, Entity/Relationship structure, Event association primitives, Facet
//! ownership references and mechanical World Effects.
//!
//! Core defines **mechanism, identity and hard invariants**. It does not define
//! what employment, money, combat, emotion, politics, memory or any other
//! domain concept means; those semantics belong to Capability modules.
//!
//! # Authority and truth
//!
//! Types in this crate may describe World Truth, but this crate does not own the
//! Runtime commit transaction. A Core value existing in memory does not make it
//! committed reality. World Truth changes only when `loom-runtime` successfully
//! commits validated Events and their frozen Effects to a Timeline.
//!
//! # Dependency boundary
//!
//! `loom-core` is the bottom of the Loom Cargo dependency DAG. It must not depend
//! on any higher Loom crate. It must also remain independent from Tokio, `SQLx`,
//! Axum, GPUI, pgvector, model providers, network clients, platform clocks and
//! random-number implementations.
//!
//! Core is **not** a `common`, `shared-model` or DTO dumping ground. A type does
//! not belong here merely because multiple crates need it. Cross-component
//! untrusted execution values belong to `loom-protocol`; public consumption
//! contracts belong to `loom-api`.
//!
//! World-affecting nondeterminism is injected through explicit Runtime boundaries
//! rather than hidden inside Core primitives.
//!
//! # Documentation contract
//!
//! Every new public Core type, enum variant and high-risk field must document its
//! meaning, owner, truth domain, lifecycle, forbidden uses and its distinction
//! from neighboring concepts. The normative detailed contracts live in
//! `docs/architecture/runtime-contracts.md` and
//! `docs/architecture/governance.md`.

#![forbid(unsafe_code)]

mod ids;
mod structure;
mod values;

pub use ids::{
    ActionTypeId, EntityId, EventId, EventTypeId, ExecutionSessionId, FacetTypeId, RelationshipId,
    RelationshipTypeId, SchemaRevision, TimelineId, WorkHandlerId, WorkId, WorldId,
};
pub use structure::{
    Entity, FacetOwner, Relationship, RelationshipParticipant, RelationshipRole, WorldEffect,
};
pub use values::{EventSeq, StateRevision, TimelineVersion, WorldDuration, WorldInstant};
