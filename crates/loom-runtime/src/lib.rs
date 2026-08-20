//! Loom Runtime: execution authority for a persistent World Timeline.
//!
//! # Responsibility
//!
//! This crate owns execution sessions, pinned BaseWorldView access, resolution
//! budgets and ReadSet recording, controlled entropy/cognition gateways,
//! CandidateWorldView construction, Effect validation, Durable Work execution
//! policy and the unique Timeline commit authority.
//!
//! Runtime is the only layer allowed to turn an untrusted semantic `Resolution`
//! into a `ValidatedResolution` and then attempt the short PostgreSQL transaction
//! that appends Events, applies frozen Effects, mutates Durable Work and advances
//! the Timeline version atomically.
//!
//! # Authority and truth
//!
//! Capability resolvers propose semantics; Runtime decides whether those
//! proposals are structurally valid, based on the expected Timeline snapshot and
//! eligible to commit. A successful commit is the linearization point at which
//! proposed Events become World Truth. CAS conflicts are execution conflicts, not
//! domain rejections.
//!
//! Durable Work in this crate represents unresolved future execution rather than
//! future World Truth. Work claims are leases, technical retries use platform
//! time, and current Work completion must be atomic with any resulting World
//! commit.
//!
//! # Forbidden shortcuts
//!
//! Runtime must not let Capability code obtain raw Storage transactions, system
//! clocks, network clients, raw random sources or direct Event-Ledger append
//! handles. Long cognition/resolution work must not hold the Timeline commit lock.
//!
//! # Documentation contract
//!
//! Public Runtime types must explain which authority gate they represent. In
//! particular, `Resolution`, `ValidatedResolution`, World views, ReadSet,
//! ExecutionResult and Durable Work types must never rely on their names alone to
//! communicate safety semantics. See `docs/architecture/runtime-contracts.md`.

#![forbid(unsafe_code)]
