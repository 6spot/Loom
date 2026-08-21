//! Runtime-owned persistence ports and the read models exchanged with adapters.
//!
//! The traits in this module are the narrow dependency-inversion boundary for
//! World reads, Timeline commits and Durable Work operations. They describe
//! authority and concurrency semantics without selecting a database or a
//! locking implementation. In particular, a commit accepts only the private
//! Runtime authority token [`ValidatedResolution`]; the protocol
//! [`loom_protocol::Resolution`] never crosses this boundary.

use std::{
    fmt,
    future::Future,
    pin::Pin,
    sync::{
        Arc,
        atomic::{AtomicI64, Ordering},
    },
};

use loom_core::{
    AssociationRole, EntityId, EventId, EventSeq, RelationshipId, TimelineId, TimelineVersion,
    WorkHandlerId, WorkId, WorldEffect, WorldInstant,
};
use loom_protocol::{NewWork, ProposedEvent, WorkSchedule};
use serde_json::Value;

use crate::{BaseWorldSnapshot, BaseWorldView, ValidatedResolution};

/// Executor-neutral future returned by Runtime persistence I/O ports.
///
/// Persistence adapters may use `SQLx` or another asynchronous driver without
/// choosing an executor for Runtime. Capability code never receives this type:
/// resolvers operate on the already-pinned in-memory `BaseWorldView`.
pub type PersistenceFuture<'a, T> = Pin<Box<dyn Future<Output = T> + 'a>>;

/// An explicit platform-time coordinate used for leases and technical retry.
///
/// `PlatformTime` is operational metadata. It is deliberately distinct from
/// [`WorldInstant`], which is semantic time in a World Timeline. A retry
/// backoff or lease deadline must not advance World Time or become a World
/// Event merely because platform time moved forward.
#[derive(Clone, Copy, Debug, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct PlatformTime(i64);

impl PlatformTime {
    /// Creates a platform-time coordinate supplied by the caller/adapter.
    #[must_use]
    pub const fn new(value: i64) -> Self {
        Self(value)
    }

    /// Returns the underlying platform-time coordinate.
    #[must_use]
    pub const fn value(self) -> i64 {
        self.0
    }
}

impl From<i64> for PlatformTime {
    fn from(value: i64) -> Self {
        Self::new(value)
    }
}

impl From<PlatformTime> for i64 {
    fn from(value: PlatformTime) -> Self {
        value.value()
    }
}

impl fmt::Display for PlatformTime {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

/// Runtime-owned source of operational platform time.
///
/// Platform time is infrastructure metadata for leases, retry availability
/// and adapter commit metadata. It is not World Time, and this port is
/// intentionally not part of the Capability resolution context. The
/// application composition root may inject a system-clock adapter; tests can
/// inject a deterministic implementation without giving a Capability access
/// to that clock.
pub trait PlatformClock {
    /// Returns the platform time for the current Runtime execution boundary.
    fn now(&self) -> PlatformTime;
}

impl<T> PlatformClock for Arc<T>
where
    T: PlatformClock + ?Sized,
{
    fn now(&self) -> PlatformTime {
        (**self).now()
    }
}

/// A deterministic, Runtime-injectable platform clock for tests and fixtures.
///
/// Clones share the same value, so a test can advance the clock after it has
/// been injected into a Runtime. It never reads wall-clock state.
#[derive(Clone, Debug)]
pub struct ManualPlatformClock {
    value: Arc<AtomicI64>,
}

impl ManualPlatformClock {
    /// Creates a manual clock at the supplied platform time.
    #[must_use]
    pub fn new(value: PlatformTime) -> Self {
        Self {
            value: Arc::new(AtomicI64::new(value.value())),
        }
    }

    /// Sets the value returned by subsequent [`PlatformClock::now`] calls.
    pub fn set(&self, value: PlatformTime) {
        self.value.store(value.value(), Ordering::Relaxed);
    }
}

impl Default for ManualPlatformClock {
    fn default() -> Self {
        Self::new(PlatformTime::default())
    }
}

impl PlatformClock for ManualPlatformClock {
    fn now(&self) -> PlatformTime {
        PlatformTime::new(self.value.load(Ordering::Relaxed))
    }
}

/// The only durable semantic statuses supported by v0 Durable Work.
///
/// Lease ownership, retry availability and attempt counts are separate
/// Runtime metadata. Claiming a `Pending` Work therefore never changes this
/// enum to a transient `Running` or `Retrying` variant.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub enum WorkStatus {
    /// Work is eligible for execution when its schedule/availability allows.
    Pending,
    /// Runtime atomically completed this Work with its accepted outcome.
    Completed,
    /// Runtime or operator policy cancelled this Work.
    Cancelled,
    /// Runtime permanently stopped this Work after its retry policy was spent.
    Dead,
}

impl fmt::Display for WorkStatus {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let name = match self {
            Self::Pending => "Pending",
            Self::Completed => "Completed",
            Self::Cancelled => "Cancelled",
            Self::Dead => "Dead",
        };
        formatter.write_str(name)
    }
}

/// Operational lease metadata kept separate from durable [`WorkStatus`].
///
/// A fence is monotonically replaced on every successful claim. A worker may
/// submit a commit only while the stored fence matches its claim and the
/// supplied platform time is strictly before `claimed_until`.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct WorkLease {
    claimed_until: PlatformTime,
    fence: u64,
}

impl WorkLease {
    /// Creates lease metadata for one fence generation.
    #[must_use]
    pub const fn new(claimed_until: PlatformTime, fence: u64) -> Self {
        Self {
            claimed_until,
            fence,
        }
    }

    /// Returns the explicit platform deadline of the lease.
    #[must_use]
    pub const fn claimed_until(self) -> PlatformTime {
        self.claimed_until
    }

    /// Returns the monotonic claim fence.
    #[must_use]
    pub const fn fence(self) -> u64 {
        self.fence
    }
}

/// Runtime-owned claim evidence required to complete one current Work.
///
/// Storage adapters return this value from [`WorkStore::claim`]. Callers must
/// pass the same value to [`CommitStore::commit`]; the adapter rechecks the
/// Work status, stored fence and lease deadline at the commit linearization
/// point. The public constructor makes this a typed value, but does not grant
/// commit authority: a forged or stale fence is rejected by the adapter.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct WorkClaim {
    timeline_id: TimelineId,
    work_id: WorkId,
    claimed_until: PlatformTime,
    fence: u64,
}

impl WorkClaim {
    /// Creates claim evidence returned by a Work adapter.
    #[must_use]
    pub const fn new(
        timeline_id: TimelineId,
        work_id: WorkId,
        claimed_until: PlatformTime,
        fence: u64,
    ) -> Self {
        Self {
            timeline_id,
            work_id,
            claimed_until,
            fence,
        }
    }

    /// Returns the Timeline containing the claimed Work.
    #[must_use]
    pub const fn timeline_id(self) -> TimelineId {
        self.timeline_id
    }

    /// Returns the claimed Work identity.
    #[must_use]
    pub const fn work_id(self) -> WorkId {
        self.work_id
    }

    /// Returns the platform deadline captured by the claim.
    #[must_use]
    pub const fn claimed_until(self) -> PlatformTime {
        self.claimed_until
    }

    /// Returns the fence generation captured by the claim.
    #[must_use]
    pub const fn fence(self) -> u64 {
        self.fence
    }
}

/// A read model of one Durable Work item and its independent runtime metadata.
///
/// `due_world_time` is semantic scheduling data. `available_at`, `lease`,
/// `attempt_count` and `last_error` are platform/runtime metadata and do not
/// belong to the World Event ledger.
#[derive(Clone, Debug, PartialEq)]
pub struct WorkRecord {
    /// Stable Work identity reused across technical retries.
    pub id: WorkId,
    /// Timeline-local scope of the Work obligation.
    pub timeline_id: TimelineId,
    /// Capability-owned handler key used when the Work executes.
    pub handler: WorkHandlerId,
    /// Schema revision for the serialized handler payload.
    pub schema_revision: loom_core::SchemaRevision,
    /// Serialized handler input, not a precomputed future result.
    pub payload: Value,
    /// Optional World-semantic time at which the Work becomes due.
    pub due_world_time: Option<WorldInstant>,
    /// Optional causal Event that scheduled the Work.
    pub causal_event_id: Option<EventId>,
    /// Optional preceding Work from which this Work was derived.
    pub origin_work_id: Option<WorkId>,
    /// Durable semantic lifecycle status.
    pub status: WorkStatus,
    /// Number of execution claims/attempts made for this Work.
    pub attempt_count: u32,
    /// Monotonic fence generation retained even when no lease is active.
    pub claim_generation: u64,
    /// Platform time at which another claim may be attempted.
    pub available_at: PlatformTime,
    /// Most recent technical failure, if any.
    pub last_error: Option<String>,
    /// Current operational lease, independent from `status`.
    pub lease: Option<WorkLease>,
}

impl WorkRecord {
    /// Builds a pending Work record from a validated `NewWork` proposal.
    #[must_use]
    pub fn from_new_work(work: &NewWork, available_at: PlatformTime) -> Self {
        let due_world_time = match work.schedule {
            WorkSchedule::Immediate => None,
            WorkSchedule::At(instant) => Some(instant),
        };
        Self {
            id: work.id,
            timeline_id: work.timeline_id,
            handler: work.handler.clone(),
            schema_revision: work.schema_revision,
            payload: work.payload.clone(),
            due_world_time,
            causal_event_id: work.causal_event_id,
            origin_work_id: work.origin_work_id,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at,
            last_error: None,
            lease: None,
        }
    }

    /// Returns whether the Work can still be claimed/completed as Pending.
    #[must_use]
    pub const fn is_pending(&self) -> bool {
        matches!(self.status, WorkStatus::Pending)
    }
}

/// One committed Event in authoritative Timeline-local order.
///
/// This read model is produced only after a successful commit. Its `event_seq`
/// is allocated by the commit adapter, never copied from `EventId` ordering or
/// supplied by Protocol.
#[derive(Clone, Debug, PartialEq)]
pub struct CommittedEvent {
    /// Technical Event identity carried by the validated proposal.
    pub id: EventId,
    /// Timeline containing this committed Event.
    pub timeline_id: TimelineId,
    /// Authoritative contiguous sequence assigned at commit.
    pub event_seq: EventSeq,
    /// Capability-owned Event semantic key.
    pub event_type: loom_core::EventTypeId,
    /// Event schema revision.
    pub schema_revision: loom_core::SchemaRevision,
    /// World semantic time carried by the committed Event.
    pub occurred_at: WorldInstant,
    /// Direct Entity associations frozen into the Event.
    pub participants: Vec<loom_protocol::EventParticipant>,
    /// Relationship associations frozen into the Event.
    pub relationship_refs: Vec<loom_protocol::EventRelationshipRef>,
    /// Causal references frozen into the Event.
    pub causal_links: Vec<loom_protocol::CausalLink>,
    /// Capability-owned payload frozen into history.
    pub payload: Value,
    /// Mechanical Effects applied to materialized state.
    pub effects: Vec<WorldEffect>,
}

impl CommittedEvent {
    /// Builds an authoritative read model from one proposal and assigned seq.
    #[must_use]
    pub fn from_proposed(
        timeline_id: TimelineId,
        event_seq: EventSeq,
        event: &ProposedEvent,
    ) -> Self {
        Self {
            id: event.id,
            timeline_id,
            event_seq,
            event_type: event.event_type.clone(),
            schema_revision: event.schema_revision,
            occurred_at: event.occurred_at,
            participants: event.participants.clone(),
            relationship_refs: event.relationship_refs.clone(),
            causal_links: event.causal_links.clone(),
            payload: event.payload.clone(),
            effects: event.effects.clone(),
        }
    }

    /// Adds a persisted direct Entity association while rebuilding history.
    pub fn push_participant(&mut self, entity_id: EntityId, role: AssociationRole) {
        self.participants
            .push(loom_protocol::EventParticipant::new(entity_id, role));
    }

    /// Adds a persisted Relationship association while rebuilding history.
    pub fn push_relationship_ref(
        &mut self,
        relationship_id: RelationshipId,
        role: AssociationRole,
    ) {
        self.relationship_refs
            .push(loom_protocol::EventRelationshipRef::new(
                relationship_id,
                role,
            ));
    }

    /// Adds a persisted causal edge while rebuilding committed history.
    pub fn push_causal_link(&mut self, cause_event_id: EventId) {
        self.causal_links
            .push(loom_protocol::CausalLink::new(cause_event_id));
    }

    /// Returns the assigned sequence using the API-oriented name.
    #[must_use]
    pub const fn sequence(&self) -> EventSeq {
        self.event_seq
    }
}

/// A coherent Runtime read snapshot of one Timeline.
///
/// `base` is suitable for constructing a [`BaseWorldView`]. `events` and
/// `works` are read models from the same authority snapshot, so callers never
/// observe an Event ledger from one revision with materialized state from
/// another revision.
#[derive(Clone, Debug)]
pub struct TimelineSnapshot {
    /// Pinned materialized World state used by Runtime validation.
    pub base: BaseWorldSnapshot,
    /// Committed Event ledger in Timeline-local sequence order.
    pub events: Vec<CommittedEvent>,
    /// Durable Work records visible in this Timeline snapshot.
    pub works: Vec<WorkRecord>,
}

impl TimelineSnapshot {
    /// Creates a coherent Timeline snapshot from its Runtime read models.
    #[must_use]
    pub const fn new(
        base: BaseWorldSnapshot,
        events: Vec<CommittedEvent>,
        works: Vec<WorkRecord>,
    ) -> Self {
        Self {
            base,
            events,
            works,
        }
    }

    /// Returns the pinned Timeline identity.
    #[must_use]
    pub const fn timeline_id(&self) -> TimelineId {
        self.base.timeline_id()
    }

    /// Returns the World identity containing this Timeline.
    #[must_use]
    pub const fn world_id(&self) -> loom_core::WorldId {
        self.base.world_id()
    }

    /// Returns the pinned optimistic-concurrency version.
    #[must_use]
    pub const fn version(&self) -> TimelineVersion {
        self.base.version()
    }

    /// Returns the pinned World semantic time.
    #[must_use]
    pub const fn world_time(&self) -> WorldInstant {
        self.base.world_time()
    }

    /// Creates the Runtime validation view for this coherent snapshot.
    #[must_use]
    pub fn world_view(&self) -> BaseWorldView {
        BaseWorldView::new(self.base.clone())
    }
}

/// Result of a successful atomic Timeline commit.
#[derive(Clone, Debug, PartialEq)]
pub struct CommitResult {
    /// Timeline targeted by the commit.
    pub timeline_id: TimelineId,
    /// Version after the commit linearization point. A successful commit with
    /// no Events, Work mutations or current-Work completion returns the
    /// unchanged version rather than advancing `state_revision`.
    pub version: TimelineVersion,
    /// Events appended by this commit, in assigned sequence order.
    pub events: Vec<CommittedEvent>,
    /// Current Work completed by this commit, if a claim was supplied.
    pub completed_work: Option<WorkId>,
}

/// A failure reading a Runtime Timeline snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ReadError {
    /// The requested Timeline does not exist in the adapter authority.
    TimelineNotFound { timeline_id: TimelineId },
    /// The persistence authority could not complete a coherent read.
    StorageUnavailable { message: String },
}

impl fmt::Display for ReadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TimelineNotFound { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} was not found")
            }
            Self::StorageUnavailable { message } => formatter.write_str(message),
        }
    }
}

impl std::error::Error for ReadError {}

/// Typed failures for Durable Work claim, retry and completion checks.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WorkError {
    /// The requested Timeline does not exist.
    TimelineNotFound { timeline_id: TimelineId },
    /// The requested Work does not exist in the Timeline.
    WorkNotFound {
        timeline_id: TimelineId,
        work_id: WorkId,
    },
    /// A token or proposal targets a different Timeline than the Work.
    TimelineMismatch {
        expected: TimelineId,
        actual: TimelineId,
    },
    /// Claiming/completing is only valid for Pending Work.
    NotPending { work_id: WorkId, status: WorkStatus },
    /// A live lease already owns this Pending Work.
    AlreadyClaimed {
        work_id: WorkId,
        claimed_until: PlatformTime,
    },
    /// The requested claim deadline is not after the supplied current time.
    InvalidLease {
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    },
    /// The Work is waiting for technical retry availability.
    NotAvailable {
        work_id: WorkId,
        available_at: PlatformTime,
        now: PlatformTime,
    },
    /// A worker attempted to commit at or after its lease deadline.
    LeaseExpired {
        work_id: WorkId,
        claimed_until: PlatformTime,
        now: PlatformTime,
    },
    /// The supplied claim fence no longer owns the Work.
    StaleClaim {
        work_id: WorkId,
        expected_fence: u64,
        actual_fence: Option<u64>,
    },
    /// The Work was expected to have a lease but none is stored.
    MissingLease { work_id: WorkId },
    /// The Work cannot represent another execution attempt.
    AttemptOverflow { work_id: WorkId },
    /// A Work identity would be scheduled twice in one atomic commit.
    DuplicateWork { work_id: WorkId },
    /// A scheduled Work points at an Event absent from the staged ledger.
    MissingCausalEvent { work_id: WorkId, event_id: EventId },
    /// The persistence authority could not complete a Work I/O operation.
    StorageUnavailable { message: String },
}

impl fmt::Display for WorkError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TimelineNotFound { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} was not found")
            }
            Self::WorkNotFound {
                timeline_id,
                work_id,
            } => write!(
                formatter,
                "Work {work_id} was not found in Timeline {timeline_id}"
            ),
            Self::TimelineMismatch { expected, actual } => write!(
                formatter,
                "Work claim targets Timeline {actual}, expected {expected}"
            ),
            Self::NotPending { work_id, status } => {
                write!(formatter, "Work {work_id} is {status}, not Pending")
            }
            Self::AlreadyClaimed {
                work_id,
                claimed_until,
            } => write!(
                formatter,
                "Work {work_id} is leased until platform time {claimed_until}"
            ),
            Self::InvalidLease {
                work_id,
                now,
                claimed_until,
            } => write!(
                formatter,
                "Work {work_id} lease deadline {claimed_until} is not after now {now}"
            ),
            Self::NotAvailable {
                work_id,
                available_at,
                now,
            } => write!(
                formatter,
                "Work {work_id} is unavailable until platform time {available_at}, now {now}"
            ),
            Self::LeaseExpired {
                work_id,
                claimed_until,
                now,
            } => write!(
                formatter,
                "Work {work_id} lease expired at {claimed_until}; commit time is {now}"
            ),
            Self::StaleClaim {
                work_id,
                expected_fence,
                actual_fence,
            } => write!(
                formatter,
                "Work {work_id} claim fence {expected_fence} is stale; stored fence {actual_fence:?}"
            ),
            Self::MissingLease { work_id } => {
                write!(formatter, "Work {work_id} has no active lease")
            }
            Self::AttemptOverflow { work_id } => {
                write!(formatter, "Work {work_id} attempt count overflowed")
            }
            Self::DuplicateWork { work_id } => {
                write!(formatter, "Work {work_id} is scheduled more than once")
            }
            Self::MissingCausalEvent { work_id, event_id } => write!(
                formatter,
                "Work {work_id} references missing causal Event {event_id}"
            ),
            Self::StorageUnavailable { message } => formatter.write_str(message),
        }
    }
}

impl std::error::Error for WorkError {}

/// Typed failures raised before the atomic commit swap.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CommitError {
    /// The validated token targets a missing Timeline.
    TimelineNotFound { timeline_id: TimelineId },
    /// The token's pinned version is stale at the commit linearization point.
    TimelineConflict {
        expected: TimelineVersion,
        actual: TimelineVersion,
    },
    /// A claim token targets a different Timeline than the validated token.
    TimelineMismatch {
        expected: TimelineId,
        actual: TimelineId,
    },
    /// An Event identity is already present in the Timeline ledger/batch.
    DuplicateEvent { event_id: EventId },
    /// A proposed Event or association violates the storage hard boundary.
    InvalidEvent { event_id: EventId, message: String },
    /// A frozen Effect cannot be applied to the staged materialized state.
    InvalidEffect { event_id: EventId, message: String },
    /// A Work mutation or current Work claim failed its typed checks.
    Work(WorkError),
    /// The persistence authority could not complete the atomic transaction.
    StorageUnavailable { message: String },
    /// The revision or Event sequence cannot be represented by its value type.
    RevisionOverflow,
}

impl fmt::Display for CommitError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TimelineNotFound { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} was not found")
            }
            Self::TimelineConflict { expected, actual } => write!(
                formatter,
                "Timeline CAS conflict: expected {expected:?}, actual {actual:?}"
            ),
            Self::TimelineMismatch { expected, actual } => write!(
                formatter,
                "commit claim targets Timeline {actual}, expected {expected}"
            ),
            Self::DuplicateEvent { event_id } => {
                write!(
                    formatter,
                    "Event {event_id} is already committed or duplicated"
                )
            }
            Self::InvalidEvent { event_id, message } => {
                write!(formatter, "Event {event_id} is invalid: {message}")
            }
            Self::InvalidEffect { event_id, message } => {
                write!(
                    formatter,
                    "Effect under Event {event_id} is invalid: {message}"
                )
            }
            Self::Work(error) => error.fmt(formatter),
            Self::StorageUnavailable { message } => formatter.write_str(message),
            Self::RevisionOverflow => {
                formatter.write_str("Timeline revision or Event sequence overflow")
            }
        }
    }
}

impl std::error::Error for CommitError {}

impl From<WorkError> for CommitError {
    fn from(value: WorkError) -> Self {
        Self::Work(value)
    }
}

/// Runtime read port required by validation and public history projections.
pub trait WorldStore {
    /// Reads one coherent Timeline snapshot asynchronously.
    ///
    /// The returned base state, Event ledger and Work records correspond to
    /// one adapter snapshot. Implementations must not expose a mixture of
    /// revisions. The Future is executor-neutral and must not be exposed to
    /// Capability semantic code.
    ///
    /// # Errors
    ///
    /// Returns [`ReadError::TimelineNotFound`] when the Timeline is absent, or
    /// [`ReadError::StorageUnavailable`] when the authority cannot be read.
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>>;

    /// Alias emphasizing the read-side operation for callers that use the
    /// port as a `read_snapshot` dependency.
    fn read_snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        self.snapshot(timeline_id)
    }
}

/// Runtime commit port whose semantic input is exclusively authority-gated.
pub trait CommitStore {
    /// Atomically commits one Runtime-validated proposal.
    ///
    /// `resolution.base_version()` is the expected Timeline CAS version and
    /// `resolution.timeline_id()` is the immutable commit target. If
    /// `current_work` is present, the implementation must verify its Pending
    /// status, live lease and fence at the same linearization point. The
    /// supplied `now` is explicit platform time and is never World Time.
    /// When the validated Resolution is empty and no current Work claim is
    /// supplied, a successful no-op must leave the Timeline version and
    /// observable World/Work state unchanged.
    ///
    /// # Errors
    ///
    /// Returns a typed error before changing observable state. In particular,
    /// [`CommitError::TimelineConflict`] does not partially append Events or
    /// mutate State/Work.
    fn commit<'a>(
        &'a self,
        resolution: &'a ValidatedResolution,
        current_work: Option<&'a WorkClaim>,
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<CommitResult, CommitError>>;
}

/// Runtime Work/claim port for operational metadata and current-Work fences.
pub trait WorkStore {
    /// Claims one Pending Work until an explicit platform deadline.
    ///
    /// Claiming only updates lease/attempt metadata. It does not change Work
    /// status or Timeline version. The returned Future is executor-neutral so
    /// SQL-backed adapters never need to block inside Runtime.
    ///
    /// # Errors
    ///
    /// Returns [`WorkError::AlreadyClaimed`], [`WorkError::NotAvailable`] or a
    /// typed identity/status/infrastructure error when the claim cannot linearize.
    fn claim(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'_, Result<WorkClaim, WorkError>>;

    /// Records a technical retry without changing World Truth.
    ///
    /// The same Work identity remains `Pending`; only platform availability,
    /// attempt metadata and the last error change. No Event, Facet, structure,
    /// Timeline version or World Time is advanced.
    ///
    /// # Errors
    ///
    /// Returns a typed stale/expired claim, Work lifecycle or infrastructure error.
    fn retry<'a>(
        &'a self,
        claim: &'a WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> PersistenceFuture<'a, Result<WorkRecord, WorkError>>;

    /// Reads one Work record from a Timeline.
    ///
    /// `Ok(None)` means the Timeline exists but has no such Work identity.
    ///
    /// # Errors
    ///
    /// Returns [`ReadError::TimelineNotFound`] for an unknown Timeline or a
    /// storage-unavailable error when the authority cannot be read.
    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
    ) -> PersistenceFuture<'_, Result<Option<WorkRecord>, ReadError>>;
}
