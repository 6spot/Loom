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

mod blob;
mod budget;
mod entropy;
mod identity;
mod logical_replay;
mod orchestration;
mod persistence;
mod pinned_reads;
mod provenance;
mod replay;
mod validation;
mod views;

pub use blob::{
    BLOB_HASH_SIZE, BlobError, BlobHash, BlobHashParseError, BlobId, BlobMetadata, BlobObject,
    BlobRef, BlobStore,
};
pub use budget::{BudgetDimension, BudgetError, BudgetUsage, ResolutionBudget};
pub use entropy::{
    DeterministicEntropySource, EntropySource, EntropySourceError, EntropySourceId,
    UnavailableEntropySource,
};
pub use identity::{IdentityAllocator, UuidV7IdentityAllocator};
pub use logical_replay::{
    HistoricalTimelineState, LogicalCommitReplayError, LogicalReplayEngine, LogicalReplayError,
    LogicalWorkReplayError, LogicalWorkState, TimelineLogicalState, replay_timeline,
};
pub use orchestration::Runtime;
pub use persistence::{
    ActiveRuntimeRevision, AdvanceWorldTime, BindingError, ChronologyBudgetConsumption,
    ChronologyBudgetExceeded, ChronologyBudgetPolicy, ChronologyBudgetState, CommitError,
    CommitResult, CommitStore, CommittedEvent, ExecutionAssembly, ExecutionOrigin,
    ExecutionSession, ExecutionSessionStatus, ExecutionSessionStore, FailurePolicy,
    FailurePolicyError, ForkError, ForkMaterialization, ForkWork, IngressClaim, IngressError,
    IngressLease, IngressOperationalRecord, IngressRecord, IngressStore, IngressSubmission,
    LifecycleError, LogicalCommit, LogicalJournalRecord, LogicalJournalStore,
    LogicalWorkTransition, MAX_SEMANTIC_PROJECTION_ROWS, MAX_SEMANTIC_QUERY_DEPTH,
    MAX_SEMANTIC_QUERY_FILTERS, MAX_SEMANTIC_QUERY_RESULT_BYTES, MAX_SEMANTIC_QUERY_RESULTS,
    MAX_SEMANTIC_VECTOR_DIMENSIONS, ManualPlatformClock, PersistenceFuture, PlatformClock,
    PlatformTime, ReadError, RuntimeCapabilityImplementation, RuntimeControlStore, RuntimeRevision,
    RuntimeRevisionAssembly, RuntimeRevisionCapability, RuntimeRevisionCompatibilityError,
    RuntimeRevisionDescriptor, RuntimeRevisionDescriptorError, RuntimeRevisionError,
    RuntimeRevisionId, RuntimeRevisionSelection, RuntimeRevisionStore, SchedulerCommitStore,
    SemanticProjectionError, SemanticProjectionFilter, SemanticProjectionHit,
    SemanticProjectionKey, SemanticProjectionQuery, SemanticProjectionRebuild,
    SemanticProjectionRegistration, SemanticProjectionRow, SemanticProjectionStore, SessionError,
    TimelineBlockedOnMissingImplementation, TimelineDriverBlock, TimelineDriverResult,
    TimelineFork, TimelineForkStore, TimelineSnapshot, WorkClaim, WorkError, WorkLease, WorkRecord,
    WorkStatus, WorkStore, WorkTerminalState, WorkTerminalization, WorldCreation,
    WorldLifecycleStore, WorldRuntimeBinding, WorldRuntimeBindingStore, WorldStore, WorldTimeError,
    WorldTimeStore, WorldTimeTransition, semantic_projection_hit_bytes,
};
pub use pinned_reads::{
    PinnedFacet, PinnedRead, PinnedReadBoundary, PinnedReadCache, PinnedReadMetrics,
    PinnedReadPolicy, PinnedReadSession, PinnedWorldReadStore,
};
pub use provenance::{
    CallProvenance, EntropyEvidence, EntropyObservation, ReadDependency, ReadSet,
    ResolutionCallEdge,
};
pub use replay::{
    ReplayEffectError, ReplayEngine, ReplayError, ReplayEventError, ReplayResult,
    replay_world_state,
};
pub use validation::{
    EffectEngine, RuntimeError, ValidatedResolution, ValidationError, ValidationOutcome,
};
pub use views::{
    BaseWorldSnapshot, BaseWorldView, CandidateWorldView, FacetSnapshot, RelationshipSnapshot,
};

/// Transport-neutral Ingress values are re-exported here so concrete storage
/// adapters can implement the Runtime-owned Ingress port without depending on
/// the higher-level API crate directly.
pub use loom_api::{
    IdempotencyConflict, IdempotencyKey, IngressAcceptance, IngressAuthorizationContext,
    IngressCompletion, IngressEnvelope, IngressId, IngressProvenance, IngressReceipt,
    IngressStatus, IngressStatusRecord, IngressTechnicalFailure, IngressTimeMetadata,
};
pub use loom_capability::SemanticKind;
/// Generic Capability-owned semantic index metadata used by Runtime ports.
pub use loom_capability::{SemanticIndexId, SemanticIndexMetric, SemanticIndexSource};
/// Frozen proposed Event representation consumed by Runtime persistence adapters.
///
/// This explicit export exists because adapters such as `loom-storage` depend on
/// Runtime rather than directly on Protocol. It carries no validation or commit
/// authority by itself; only a [`ValidatedResolution`] is commit-eligible.
pub use loom_protocol::ProposedEvent;
/// Frozen Durable Work mutation representation consumed by Runtime persistence adapters.
///
/// This explicit export is part of the Runtime-owned persistence boundary, not a
/// general Protocol facade. A mutation becomes commit-eligible only as part of a
/// [`ValidatedResolution`].
pub use loom_protocol::WorkMutation;
/// World-semantic schedule representation used by Runtime-owned Work ports.
pub use loom_protocol::WorkSchedule;
/// Frozen Durable Work target representation shared by Runtime and Storage.
pub use loom_protocol::WorkTarget;

#[cfg(test)]
mod tests;
