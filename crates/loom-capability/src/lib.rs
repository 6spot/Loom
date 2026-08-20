//! Loom Capability: semantic extension and ownership contracts.
//!
//! # Responsibility
//!
//! A Capability defines a coherent set of world semantics and registers the
//! definitions and executable logic needed to interpret them. v0 Capability
//! registrations include manifests, Facet/Relationship/Event definitions,
//! Action resolvers, read-only invariants, Durable Work handlers and reactions.
//!
//! Every semantic type has one owning Capability. A Capability may read semantic
//! domains declared as dependencies, but it may directly produce mutations only
//! for semantics it owns. Cross-Capability mutation is composed through Runtime-
//! mediated subresolution so each semantic owner remains responsible for its own
//! rules while all resulting changes may still join one atomic Timeline commit.
//!
//! # Authority and truth
//!
//! Capability code has semantic power but never Runtime authority. Resolvers and
//! Work handlers may return untrusted `Resolution` values; invariants may only
//! accept or reject CandidateWorldView state. Capability code cannot construct a
//! Runtime-approved commit token, append an Event directly or mutate persistence.
//!
//! # Forbidden resources
//!
//! Capability implementations must not receive raw database handles, SQL
//! transactions, network clients, platform clocks, raw randomness, provider
//! clients or direct commit handles. Required nondeterminism and external
//! cognition are requested through explicit Runtime-controlled boundaries.
//!
//! # Documentation contract
//!
//! Every semantic definition must document its owner, schema/version meaning,
//! allowed participants or inputs, reads/writes, invariants and relationship to
//! neighboring semantics. Resolver/Invariant/WorkHandler docs must also state
//! what they are forbidden to mutate. See `docs/architecture/runtime-contracts.md`.

#![forbid(unsafe_code)]
