//! Loom Boundary: transport adapters over the unified Loom API.
//!
//! # Responsibility
//!
//! This crate maps external protocols such as HTTP/JSON, SSE and, where truly
//! required, WebSocket onto the stable application contracts defined by
//! `loom-api`. It also maps committed Loom output back into transport-specific
//! representations.
//!
//! Boundary owns transport concerns such as routing, framing, status codes,
//! reconnect behavior and transport/auth middleware. It does **not** own World
//! semantics, Runtime authority or Capability dispatch.
//!
//! # Cargo dependency boundary
//!
//! Among Loom workspace crates, Boundary depends on `loom-api` rather than
//! `loom-runtime` or `loom-capability`:
//!
//! ```text
//! loom-boundary -> loom-api
//! loom-boundary -X-> loom-runtime
//! loom-boundary -X-> loom-capability
//! ```
//!
//! The Application composition root provides an implementation of the Loom API
//! (normally backed by Runtime) to the Boundary adapter.
//!
//! # Unified exposure rule
//!
//! Boundary is the only place transport may be expressed, but it must expose the
//! **Loom API**, not individual module internals. A Capability Action such as
//! `finance.transfer` is invoked through the common Action API; Boundary must not
//! route directly to a Finance resolver or invent a Finance-specific engine
//! controller that bypasses Loom's public contract.
//!
//! ```text
//! HTTP / SSE / WebSocket
//!          ↓
//!       Loom API
//!          ↓
//!  Runtime implementation
//!          ↓
//! Capability Registry
//! ```
//!
//! # Authority and truth
//!
//! Receiving external data does not make it World Truth. Transport acceptance
//! means only that the request/input crossed the Boundary. Semantic acceptance
//! and World mutation still require the normal API → Runtime → Capability →
//! Resolution → validation → Timeline Commit path.
//!
//! Conversely, authoritative world output must originate from already committed
//! World changes; transport delivery/acknowledgement does not mutate World Truth.
//!
//! # External side effects
//!
//! Loom Core/Runtime do not directly control the real world. A downstream
//! Application may react to committed output and perform an external side effect,
//! but any resulting influence must re-enter through the public Loom boundary
//! before it can affect World Truth again.
//!
//! # Forbidden shortcuts
//!
//! Boundary must not:
//!
//! - mutate World State or append Events directly;
//! - import concrete Capability implementations/resolvers;
//! - import Runtime internals to bypass `loom-api`;
//! - import SQLx/pgvector/object-store repositories;
//! - expose transport success as semantic success.
//!
//! # Documentation contract
//!
//! Every public boundary type must state whether it represents transport input,
//! public API mapping, committed output or transport/runtime metadata, and must
//! document where Loom authority begins and ends. See
//! `docs/architecture/governance.md` and
//! `docs/architecture/runtime-contracts.md`.

#![forbid(unsafe_code)]
