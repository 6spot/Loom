//! Loom Runtime: execution authority for a persistent World Timeline.
//!
//! # Responsibility
//!
//! This crate owns execution sessions, pinned authoritative world reads,
//! resolution budgets and `ReadSet` recording, controlled entropy/cognition
//! gateways, candidate-state construction, Effect validation, Durable Work
//! execution policy and the unique Timeline commit authority.
//!
//! Runtime consumes untrusted execution values from `loom-protocol`, semantic
//! extension SPI from `loom-capability`, cognition SPI from `loom-agency`, and
//! implements the unified application contracts defined by `loom-api`.
//!
//! Runtime is the only layer allowed to transform an untrusted protocol
//! `Resolution` into a Runtime-owned `ValidatedResolution` and then attempt the
//! short persistence transaction that appends Events, applies frozen Effects,
//! mutates Durable Work and advances the Timeline version atomically.
//!
//! # Cargo dependency boundary
//!
//! Runtime may depend on:
//!
//! ```text
//! loom-core
//! loom-protocol
//! loom-api
//! loom-capability
//! loom-agency
//! ```
//!
//! It must **not** depend on concrete `loom-storage`, `loom-boundary`, concrete
//! Capability implementations or concrete provider adapters.
//!
//! Runtime defines the persistence ports it needs (`CommitStore`/World read/work
//! ports as implementation evidence requires). `loom-storage` implements those
//! ports and therefore depends on Runtime; the Application composition root wires
//! the concrete Storage adapter into Runtime.
//!
//! Likewise Runtime implements `loom-api`; transport adapters depend on the API
//! contract rather than importing Runtime internals.
//!
//! # Authority and truth
//!
//! Capability resolvers propose semantics; Runtime decides whether those
//! proposals are structurally valid, based on the expected Timeline snapshot and
//! eligible to commit. A successful Timeline commit is the linearization point at
//! which proposed Events become World Truth. CAS conflicts are execution
//! conflicts, not domain rejections.
//!
//! `ValidatedResolution` is deliberately kept in this crate as an authority
//! token. It must not be moved into `loom-protocol` or `loom-api` merely to make
//! another crate's signature convenient. Storage may consume it through a
//! Runtime-owned port but cannot construct it.
//!
//! Durable Work represents unresolved future execution rather than future World
//! Truth. Work claims are leases, technical retries use platform time, and
//! current Work completion must be atomic with any resulting World commit.
//!
//! # Unified exposure
//!
//! Runtime does not create module-specific HTTP/CLI/UI surfaces. Its externally
//! consumable capabilities are presented through `loom-api`. Capability modules
//! register semantics with Runtime; they do not bypass the public API contract.
//!
//! # Forbidden shortcuts
//!
//! Runtime must not let Capability code obtain raw Storage transactions, system
//! clocks, network clients, raw random sources or direct Event-Ledger append
//! handles. Runtime itself must not import a concrete `PostgreSQL` adapter or HTTP
//! server to assemble its dependencies. Long cognition/resolution work must not
//! hold the Timeline commit lock.
//!
//! # Documentation contract
//!
//! Public Runtime types must explain which authority gate they represent. In
//! particular, `ValidatedResolution`, Runtime world-view implementations,
//! `ReadSet`, `ExecutionSession`, persistence ports and Durable Work types must never
//! rely on names alone to communicate safety semantics. See
//! `docs/architecture/runtime-contracts.md` and
//! `docs/architecture/governance.md`.

#![forbid(unsafe_code)]

mod budget;
mod orchestration;
mod persistence;
mod provenance;
mod validation;
mod views;

pub use budget::{BudgetDimension, BudgetError, BudgetUsage, ResolutionBudget};
pub use orchestration::Runtime;
pub use persistence::{
    CommitError, CommitResult, CommitStore, CommittedEvent, ManualPlatformClock, PlatformClock,
    PlatformTime, ReadError, TimelineSnapshot, WorkClaim, WorkError, WorkLease, WorkRecord,
    WorkStatus, WorkStore, WorldStore,
};
pub use provenance::{ReadDependency, ReadSet};
pub use validation::{
    EffectEngine, RuntimeError, ValidatedResolution, ValidationError, ValidationOutcome,
};
pub use views::{
    BaseWorldSnapshot, BaseWorldView, CandidateWorldView, FacetSnapshot, RelationshipSnapshot,
};

pub use loom_capability::SemanticKind;
#[doc(hidden)]
pub use loom_protocol::{NewWork, ProposedEvent, Resolution, WorkMutation, WorkSchedule};

/// Test-only access to existing Capability and API contracts.
///
/// This hidden module is used by adapter tests to assemble a real Runtime
/// registry and exercise the same `loom-api` trait objects without adding
/// forbidden adapter-to-framework Cargo edges. It introduces no storage or
/// semantic authority and is not part of the supported application surface.
#[doc(hidden)]
pub mod test_support {
    pub use loom_api::{
        ActionDescriptor, ActionRequest, ActionService, ApiError, ApiErrorCode, ApiResult,
        CatalogService, CatalogSnapshot, CommittedEvent, EventQuery, ExecutionResult, FacetQuery,
        FacetSnapshot, HistoryService, LoomApi, QueryService, TimelineService, TimelineSnapshot,
        TimelineTarget,
    };
    pub use loom_capability::{
        ActionDefinition, ActionResolver, BaseWorldView, CandidateWorldView, Capability,
        CapabilityManifest, CapabilityRegistrar, CapabilityRegistry, CapabilityResult,
        EventDefinition, FacetDefinition, FacetValue, Invariant, InvariantViolation,
        RegistrationError, RelationshipDefinition, RelationshipRole, ResolutionContext,
        ResolutionContextError, ResolverError, WorkHandler, WorkHandlerDefinition,
    };
    pub use loom_protocol::{ActionInvocation, Rejection, ResolveOutcome};
}

#[cfg(test)]
mod tests;
