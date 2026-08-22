//! Reusable neutral Capability and Template composition fixtures.
//!
//! This crate is a composition/test boundary. The fixture semantics deliberately
//! stay outside Loom's Runtime, Core, Protocol and API crates so later scheduler,
//! replay and Agency tests can reuse the same small world language without
//! turning those layers into domain examples.

#![forbid(unsafe_code)]

pub mod neutral;
