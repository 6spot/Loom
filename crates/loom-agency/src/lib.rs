//! Loom Agency: agent-local perception, context and decision contracts.
//!
//! # Responsibility
//!
//! This crate defines the boundary between a persistent Agent identity and any
//! cognitive executor used to choose an attempted action. It owns AgentWorldView
//! composition, context selection, decision contracts and cognitive-executor
//! interfaces. LLMs, rules, humans or hybrid executors are implementations of
//! cognition; none of them define Agent identity.
//!
//! # Knowledge boundary
//!
//! Agency never receives the authoritative BaseWorldView directly. Agent input
//! must be constructed from observation, information, knowledge, memory,
//! visibility and context-budget rules so subjective knowledge cannot collapse
//! into omniscient World Truth.
//!
//! # Output boundary
//!
//! Cognition ultimately returns a `Decision`: attempt one `ActionInvocation` or
//! take no action. It cannot emit committed Events, World Effects or a Resolution.
//! Long-lived goals/desires belong to Capability-owned state rather than a
//! generic Runtime `Intent` object.
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
//! to Runtime. See `docs/architecture/runtime-contracts.md`.

#![forbid(unsafe_code)]
