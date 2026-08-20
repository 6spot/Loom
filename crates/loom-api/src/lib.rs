//! Loom unified public application API.
//!
//! # Responsibility
//!
//! `loom-api` is the single public consumption contract for using Loom as one
//! engine. Applications and transport adapters consume Loom through this layer
//! rather than importing concrete Capability modules, Storage repositories or
//! Runtime internals.
//!
//! Expected API domains include World, Timeline, Action, Query, History,
//! Subscription, Capability Catalog/Discovery and a separately scoped Runtime
//! Administration surface. Exact trait boundaries should remain cohesive and
//! small; this crate must not become one giant `LoomService` god trait.
//!
//! # Exposure rule
//!
//! Capability modules define semantics such as `finance.transfer`; they do not
//! define HTTP routes, CLI commands, GPUI engine endpoints or SDK surfaces.
//! Transport/application layers expose those semantics only through Loom API.
//!
//! > Extension defines semantics; Loom owns exposure.
//! >
//! > One engine, one public contract, many semantic extensions.
//!
//! # Dependency direction
//!
//! This crate may depend on `loom-core` and `loom-protocol` for stable public
//! identities/semantic values that genuinely belong in the consumption
//! contract. It must not depend on `loom-runtime`, `loom-storage`,
//! `loom-boundary`, concrete Capability crates or concrete provider adapters.
//!
//! Runtime implements the API contracts; Boundary adapts HTTP/SSE/WebSocket to
//! them. Therefore both Runtime and Boundary may depend on `loom-api`, while
//! `loom-api` remains independent of either implementation.
//!
//! # Forbidden leakage
//!
//! Public API contracts must not expose internal authority or implementation
//! details such as `ValidatedResolution`, mutation overlays, ReadSet recorders,
//! database transactions, Work claim leases, Capability Resolver objects or
//! provider clients.
//!
//! # Documentation contract
//!
//! Every public API service, request/response type and high-risk field must
//! explain semantic meaning, authorization/authority boundary and relationship
//! to internal execution protocol. See `docs/architecture/governance.md`.

#![forbid(unsafe_code)]
