//! Loom Boundary: controlled exchange between external systems and a World.
//!
//! # Responsibility
//!
//! This crate owns external ingress and committed-world output boundaries. Ingress
//! validates, normalizes and deduplicates external input before converting it into
//! Runtime work or an `ActionInvocation`. Output exposes committed World changes
//! (for example through the World Change Feed) to Applications/integrations.
//!
//! # Authority and truth
//!
//! Receiving external data does not make it World Truth. Ingress acceptance means
//! transport/runtime trust only; semantic truth is decided through Capability
//! resolution and Runtime commit. Conversely, only already committed Events may
//! appear as authoritative world output.
//!
//! # External side effects
//!
//! Core/Runtime do not directly control the real world. A downstream Application
//! may react to committed output and perform an external side effect, but any
//! resulting external influence must re-enter Loom through Ingress before it can
//! affect World Truth again.
//!
//! # Forbidden shortcuts
//!
//! Boundary adapters cannot mutate World State directly, append Events directly
//! or expose transport success as semantic success. `occurred_at` in an external
//! source and platform `received_at` are distinct and must remain auditable.
//!
//! # Documentation contract
//!
//! Every public boundary type must state whether it represents untrusted external
//! input, accepted ingress metadata, committed output or transport/runtime state,
//! and must document where World authority begins and ends. See
//! `docs/architecture/runtime-contracts.md`.

#![forbid(unsafe_code)]
