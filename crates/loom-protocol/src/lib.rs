//! Loom internal execution protocol.
//!
//! # Responsibility
//!
//! `loom-protocol` is the neutral language shared by Loom components while an
//! execution is still only a proposal. It exists to let Runtime, Capability and
//! Agency exchange strongly typed values without creating circular Cargo
//! dependencies.
//!
//! Expected concepts include `ActionInvocation`, `Resolution`, `ResolveOutcome`,
//! `Rejection`, `ProposedEvent`, `NewWork`, `WorkMutation` and other small value
//! specifications that genuinely cross execution boundaries.
//!
//! # Authority and truth
//!
//! Values in this crate are **not** Runtime authority and are not automatically
//! World Truth. In particular, an untrusted `Resolution` may describe Events and
//! Effects that a Capability believes should happen, but only `loom-runtime` may
//! validate that proposal and produce its private commit-authority token.
//!
//! # Dependency direction
//!
//! This crate may depend on `loom-core` because Protocol speaks in stable World
//! identities and mechanisms. It must not depend on Runtime, Capability, Agency,
//! API, Storage, Boundary, concrete providers or concrete Capability crates.
//!
//! Do not move `ValidatedResolution`, database transaction types, HTTP request
//! types or provider implementations here merely because more than one crate
//! would find them convenient.
//!
//! # Relationship to other Loom languages
//!
//! - `loom-core` is the **World Language**: what a World is.
//! - `loom-protocol` is the **Internal Execution Language**: what components may
//!   propose/exchange before reality is committed.
//! - `loom-api` is the **Public Consumption Language**: how Applications consume
//!   Loom as one engine.
//! - `loom-runtime` is the authority that decides which proposals can become
//!   reality.
//!
//! # Public documentation contract
//!
//! Every public protocol type and high-risk field must explain its semantic
//! meaning, owner, truth domain, allowed creators/consumers, forbidden uses and
//! version/concurrency rules. See `docs/architecture/runtime-contracts.md` and
//! `docs/architecture/governance.md`.

#![forbid(unsafe_code)]
