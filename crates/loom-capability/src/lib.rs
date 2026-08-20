//! Loom Capability: semantic extension API/SPI and ownership contracts.
//!
//! # Responsibility
//!
//! This crate defines how a Capability declares and registers coherent World
//! semantics. v0 contracts include manifests, Facet/Relationship/Event/Action
//! definitions, Action resolvers, read-only invariants, Durable Work handlers,
//! reactions and the host ports a resolver may use while it is being executed.
//!
//! Concrete domain implementations should depend on this crate; this crate does
//! not depend on those implementations.
//!
//! Every semantic type has one owning Capability. A Capability may read semantic
//! domains declared as dependencies, but it may directly produce mutations only
//! for semantics it owns. Cross-Capability mutation is composed through a
//! Runtime-mediated subresolution so each semantic owner remains responsible for
//! its own rules while all resulting changes may still join one atomic Timeline
//! commit.
//!
//! # Protocol boundary
//!
//! Capability contracts speak in `loom-core` World values and untrusted
//! `loom-protocol` execution values. Resolvers may return a protocol
//! `Resolution`/`ResolveOutcome`; they never need to import `loom-runtime` merely
//! to construct their output.
//!
//! The host-facing `ResolutionContext` (and similar resolver-required ports)
//! belongs on this extension side: it specifies what a host must provide in order
//! to execute Capability logic. `loom-runtime` implements that host behavior.
//!
//! Therefore the Cargo direction is:
//!
//! ```text
//! loom-capability -> loom-core
//! loom-capability -> loom-protocol
//! loom-capability -X-> loom-runtime
//! ```
//!
//! # Authority and truth
//!
//! Capability code has semantic power but never Runtime authority. Resolvers and
//! Work handlers produce untrusted proposals; invariants may only accept/reject
//! candidate state. Capability code cannot construct `ValidatedResolution`,
//! append an Event directly or mutate persistence.
//!
//! # Unified exposure rule
//!
//! Capability registers **semantics**, never public transport/application
//! exposure. It must not register HTTP/SSE/WebSocket/gRPC routes, CLI commands,
//! GPUI engine endpoints or SDK services. A semantic Action such as
//! `finance.transfer` becomes externally available only through the unified
//! `loom-api` contract.
//!
//! > Extension defines semantics; Loom owns exposure.
//!
//! # Forbidden resources
//!
//! Capability implementations must not receive raw database handles, SQL
//! transactions, network clients, platform clocks, raw randomness, provider
//! clients or direct commit handles. Required nondeterminism and external
//! cognition are requested through explicit host-controlled boundaries.
//!
//! # Documentation contract
//!
//! Every semantic definition must document its owner, schema/version meaning,
//! allowed participants or inputs, reads/writes, invariants and relationship to
//! neighboring semantics. Resolver/Invariant/WorkHandler docs must also state
//! what they are forbidden to mutate. See `docs/architecture/runtime-contracts.md`
//! and `docs/architecture/governance.md`.

#![forbid(unsafe_code)]
