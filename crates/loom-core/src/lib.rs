//! Loom Core: stable world primitives and invariant contracts.
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
//! Core must remain independent from Tokio, SQLx, Axum, GPUI, pgvector, model
//! providers, network clients, platform clocks and random-number implementations.
//! World-affecting nondeterminism is always injected through explicit Runtime
//! boundaries rather than hidden inside Core primitives.
//!
//! # Documentation contract
//!
//! Every new public Core type, enum variant and high-risk field must document its
//! meaning, owner, truth domain, lifecycle, forbidden uses and its distinction
//! from neighboring concepts. The normative detailed contract lives in
//! `docs/architecture/runtime-contracts.md`.

#![forbid(unsafe_code)]
