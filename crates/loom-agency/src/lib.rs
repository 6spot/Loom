//! Loom Agency: agent-local perception, context and decision extension contracts.
//!
//! # Responsibility
//!
//! This crate defines the boundary between a persistent Agent identity and any
//! cognitive executor used to choose an attempted action. It owns AgentWorldView
//! composition contracts, context selection, decision contracts and
//! cognitive-executor SPI. LLMs, rules, humans or hybrid executors are
//! implementations of cognition; none of them define Agent identity.
//!
//! # Knowledge boundary
//!
//! Agency never receives the authoritative BaseWorldView directly. Agent input
//! must be constructed from observation, information, knowledge, memory,
//! visibility and context-budget rules so subjective knowledge cannot collapse
//! into omniscient World Truth.
//!
//! # Protocol and dependency boundary
//!
//! Cognition ultimately returns a `Decision`: attempt one `ActionInvocation` or
//! take no action. `ActionInvocation` belongs to `loom-protocol`, allowing Agency
//! to express its decision without depending on `loom-runtime`.
//!
//! ```text
//! loom-agency -> loom-core
//! loom-agency -> loom-protocol
//! loom-agency -X-> loom-runtime
//! ```
//!
//! Concrete Cognitive Provider adapters depend on this Agency SPI and are wired
//! by an Application composition root. This crate must not embed a vendor SDK,
//! network client or Runtime implementation merely because cognition will later
//! be executed by Runtime.
//!
//! # Output boundary
//!
//! Cognitive execution cannot emit committed Events, World Effects,
//! `Resolution` or `ValidatedResolution`. Long-lived goals/desires belong to
//! Capability-owned state rather than a generic Runtime `Intent` object.
//!
//! > Cognition decides what to attempt; Capability decides what that attempt
//! > means; Runtime decides what becomes reality.
//!
//! # Public exposure
//!
//! Agency is an engine extension contract, not an external Loom API. GPUI/HTTP/
//! CLI/SDK consumers use `loom-api`; they do not import Agency internals to invoke
//! cognition directly as a public engine surface.
//!
//! # Core distinction
//!
//! `World Truth`, `Information Space` and `Agent Knowledge` are separate domains.
//! Agency explains what an Agent can perceive/recall/consider and what it chooses
//! to attempt; Capability/Runtime explain what that attempt actually means and
//! whether it becomes reality.
//!
//! # Documentation contract
//!
//! Every public Agency abstraction must document whether it represents
//! perception, knowledge, context, cognition or decision; what authoritative
//! information it is intentionally prevented from seeing; and how it hands off
//! through Protocol to the execution engine. See
//! `docs/architecture/runtime-contracts.md` and
//! `docs/architecture/governance.md`.

#![forbid(unsafe_code)]
