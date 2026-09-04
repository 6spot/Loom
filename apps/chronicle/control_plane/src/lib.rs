//! Chronicle C1 ingestion control-plane domain (GitHub #490).
//!
//! This crate freezes the control-plane contract shared by the Chronicle
//! application: status vocabularies, the initial pipeline stage order, and
//! the legal lifecycle transitions for jobs, stages, chunks, runs, and
//! reviews. The same contract is enforced by:
//!
//! - `apps/chronicle/persistence/migrations/0002_chronicle_c1_control_plane.sql`
//!   (`PostgreSQL` `CHECK` vocabularies plus immutability triggers), and
//! - `apps/chronicle/persistence/control_plane_store.py` (transition guards
//!   before any write).
//!
//! # Authority boundary
//!
//! This is Chronicle application-owned orchestration state. It is not Loom
//! Runtime Scheduler/Work authority, not Loom Storage semantics, and not
//! historical-knowledge authority (that remains the C0 staged -> resolution
//! -> canonical path). The crate depends on nothing but `std`: in
//! particular it must never depend on `loom-*`, `sqlx`, `tokio-postgres`,
//! or any database driver. Persistence lives in the Python store behind
//! `CHRONICLE_DATABASE_URL`; the experimental Python model pipeline owns
//! segmentation/extraction semantics, while this crate owns the durable
//! orchestration contract those stages run inside.
//!
//! The [`lifecycle`] module provides a deterministic in-memory fake of the
//! whole control plane so orchestration logic can be tested without a
//! database, a clock, or a worker process.

pub mod lifecycle;
pub mod status;
