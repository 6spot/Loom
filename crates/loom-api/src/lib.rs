//! Loom's unified public application contract.
//!
//! # Responsibility
//!
//! `loom-api` is the stable consumption language for using Loom as one engine.
//! Applications and transport adapters use the focused service traits in this
//! crate to invoke semantic Actions and inspect World state/history. They do
//! not import a concrete Capability, Storage repository or Runtime authority
//! type.
//!
//! # Public domains
//!
//! This v0 surface contains only the World-facing contracts needed by the
//! in-memory vertical slice: Action invocation, Timeline inspection, current
//! Facet queries, committed Event history and central Capability/Action
//! discovery. Runtime administration is a separate future API boundary and is
//! deliberately not represented by these traits.
//!
//! # Dependency and exposure rules
//!
//! The crate may depend on `loom-core` and `loom-protocol` for stable World
//! identities, mechanical values and the untrusted `ActionInvocation` input.
//! It must not depend on `loom-runtime`, `loom-storage`, `loom-boundary` or a
//! concrete Capability. The service traits are implemented by Runtime and
//! adapted by Boundary; neither implementation direction changes this public
//! dependency boundary.
//!
//! The API exposes committed read models and execution outcomes, never
//! `ValidatedResolution`, mutation overlays, Runtime read sets, storage
//! transactions, Capability resolver objects or Work claim leases.

#![forbid(unsafe_code)]

use std::{fmt, future::Future, pin::Pin};

pub use loom_core::{
    ActionTypeId, AssociationRole, EntityId, EventId, EventRef, EventSeq, EventTypeId, FacetOwner,
    FacetTypeId, RelationshipId, RelationshipParticipant, RelationshipTypeId, SchemaRevision,
    StateRevision, TimelineAncestry, TimelineId, TimelineVersion, WorldEffect, WorldId,
    WorldInstant,
};
pub use loom_protocol::{
    ActionInvocation, CausalLink, EventParticipant, EventRelationshipRef, Rejection, RejectionCode,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Identifies the World and Timeline a public operation addresses.
///
/// `TimelineTarget` is an API routing value, not a Runtime authorization token
/// or a Timeline snapshot. The pair is carried explicitly so an application
/// cannot accidentally inspect or invoke against a different World branch.
/// Runtime resolves the target to an existing World/Timeline and enforces its
/// lifecycle and access policy.
///
/// This value is a stable public contract suitable for transport adapters. It
/// does not contain a storage key, transaction handle or Runtime-internal
/// snapshot.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct TimelineTarget {
    /// Long-lived World identity containing the addressed Timeline.
    pub world_id: WorldId,
    /// Authoritative history branch within `world_id`.
    pub timeline_id: TimelineId,
}

impl TimelineTarget {
    /// Creates a public World/Timeline target.
    #[must_use]
    pub const fn new(world_id: WorldId, timeline_id: TimelineId) -> Self {
        Self {
            world_id,
            timeline_id,
        }
    }
}

/// Public request for a current-head Timeline fork.
///
/// Runtime reads the source head and allocates the child Timeline identity;
/// callers cannot choose a storage transaction, copy ancestor rows or provide
/// a stale version as an authority token.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ForkTimelineRequest {
    /// World and source Timeline to fork at its current head.
    pub source: TimelineTarget,
}

impl ForkTimelineRequest {
    /// Creates a current-head fork request.
    #[must_use]
    pub const fn new(source: TimelineTarget) -> Self {
        Self { source }
    }

    /// Creates a fork request from separate World/Timeline identities.
    #[must_use]
    pub const fn for_timeline(world_id: WorldId, timeline_id: TimelineId) -> Self {
        Self::new(TimelineTarget::new(world_id, timeline_id))
    }
}

/// Compatibility spelling for consumers that name the operation first.
pub type TimelineForkRequest = ForkTimelineRequest;

/// Stable public identity of a World Template revision source.
///
/// A Template ID is birth metadata, not a subscription key. Runtime copies the
/// selected revision into the immutable World Runtime Binding during birth, so
/// changing or re-registering a later descriptor cannot alter an existing
/// World.
#[derive(Clone, Debug, Default, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct TemplateId(String);

impl TemplateId {
    /// Creates a Template identity from a stable application key.
    #[must_use]
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Borrows the stable Template key.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Reports whether this descriptor has no usable Template identity.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
}

impl From<String> for TemplateId {
    fn from(value: String) -> Self {
        Self::new(value)
    }
}

impl From<&str> for TemplateId {
    fn from(value: &str) -> Self {
        Self::new(value)
    }
}

impl From<TemplateId> for String {
    fn from(value: TemplateId) -> Self {
        value.0
    }
}

impl fmt::Display for TemplateId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// One semantic Capability compatibility requirement declared by a Template.
///
/// The string is a semver requirement, not an exact implementation identity.
/// Runtime parses and validates it against the active installed registry before
/// producing its private birth authority value.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TemplateCapabilityRequirement {
    /// Semantic Capability domain required by the Template.
    pub id: CapabilityId,
    /// Semver range accepted for the installed Capability implementation.
    pub version: String,
}

impl TemplateCapabilityRequirement {
    /// Creates one Template Capability requirement.
    #[must_use]
    pub fn new(id: impl Into<CapabilityId>, version: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            version: version.into(),
        }
    }

    /// Borrows the declared semver requirement.
    #[must_use]
    pub fn version_requirement(&self) -> &str {
        &self.version
    }
}

/// Public, immutable World birth recipe descriptor.
///
/// A descriptor contains only stable consumption values: Capability
/// requirements, immutable assembly configuration, initial semantic World Time
/// and an ordered list of ordinary Action invocations used for semantic
/// bootstrap. It contains no resolver, transaction, storage or exact binary
/// implementation. Runtime validates the complete descriptor before any birth
/// persistence is attempted.
#[derive(Clone, Debug, Default, Deserialize, PartialEq, Serialize)]
pub struct WorldTemplateDescriptor {
    /// Stable identity of the Template family.
    pub id: TemplateId,
    /// Immutable revision of this birth recipe.
    pub revision: u64,
    /// Capability requirements selected by this Template revision.
    pub capabilities: Vec<TemplateCapabilityRequirement>,
    /// Immutable World-level assembly configuration.
    pub configuration: Value,
    /// Semantic World Time assigned to the initial Timeline.
    pub initial_world_time: WorldInstant,
    /// Ordered normal Action inputs used to construct initial semantic state.
    pub bootstrap_actions: Vec<ActionInvocation>,
}

impl WorldTemplateDescriptor {
    /// Creates an empty Template descriptor at an explicit initial World Time.
    #[must_use]
    pub fn new(id: impl Into<TemplateId>, revision: u64, initial_world_time: WorldInstant) -> Self {
        Self {
            id: id.into(),
            revision,
            capabilities: Vec::new(),
            configuration: Value::Object(serde_json::Map::new()),
            initial_world_time,
            bootstrap_actions: Vec::new(),
        }
    }

    /// Adds one Capability compatibility requirement.
    #[must_use]
    pub fn with_capability_requirement(
        mut self,
        requirement: TemplateCapabilityRequirement,
    ) -> Self {
        self.capabilities.push(requirement);
        self
    }

    /// Adds one Capability compatibility requirement from an ID and semver range.
    #[must_use]
    pub fn requires_capability(
        self,
        id: impl Into<CapabilityId>,
        version: impl Into<String>,
    ) -> Self {
        self.with_capability_requirement(TemplateCapabilityRequirement::new(id, version))
    }

    /// Sets immutable World-level assembly configuration.
    #[must_use]
    pub fn with_configuration(mut self, configuration: Value) -> Self {
        self.configuration = configuration;
        self
    }

    /// Appends one ordered semantic bootstrap Action.
    #[must_use]
    pub fn with_bootstrap_action(mut self, action: ActionInvocation) -> Self {
        self.bootstrap_actions.push(action);
        self
    }

    /// Appends ordered semantic bootstrap Actions.
    #[must_use]
    pub fn with_bootstrap_actions<I>(mut self, actions: I) -> Self
    where
        I: IntoIterator<Item = ActionInvocation>,
    {
        self.bootstrap_actions.extend(actions);
        self
    }

    /// Returns the stable Template provenance key copied into the World Binding.
    #[must_use]
    pub fn provenance(&self) -> String {
        format!("{}@{}", self.id, self.revision)
    }
}

/// Public request to create a World from one immutable Template descriptor.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct CreateWorldFromTemplateRequest {
    /// Descriptor whose revision is validated and snapshotted at birth.
    pub template: WorldTemplateDescriptor,
}

impl CreateWorldFromTemplateRequest {
    /// Creates a Template birth request.
    #[must_use]
    pub const fn new(template: WorldTemplateDescriptor) -> Self {
        Self { template }
    }
}

/// Public result of a successful Template birth.
///
/// The initial Timeline snapshot is the same read model used by the ordinary
/// lifecycle API; its version includes any atomically committed bootstrap
/// Events, Effects and logical Work mutations.
pub type CreateWorldFromTemplateResult = TimelineSnapshot;

/// A public request to resolve one semantic Action on a World Timeline.
///
/// The `ActionInvocation` remains an untrusted Protocol value: it names a
/// Capability-owned semantic Action and carries serialized input, but it does
/// not grant permission or commit authority. Runtime pins the target's
/// Timeline version, resolves the invocation, validates the resulting
/// proposal and owns the commit decision.
///
/// This request is the World-facing boundary for Action execution. It is not
/// an HTTP request, transport envelope, storage command or Capability-specific
/// endpoint.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ActionRequest {
    /// World and Timeline against which the invocation is attempted.
    pub target: TimelineTarget,
    /// Untrusted semantic Action input forwarded to Runtime resolution.
    pub invocation: ActionInvocation,
}

impl ActionRequest {
    /// Creates an Action request for one World Timeline.
    #[must_use]
    pub const fn new(target: TimelineTarget, invocation: ActionInvocation) -> Self {
        Self { target, invocation }
    }

    /// Creates an Action request from separate World and Timeline identities.
    #[must_use]
    pub const fn for_timeline(
        world_id: WorldId,
        timeline_id: TimelineId,
        invocation: ActionInvocation,
    ) -> Self {
        Self::new(TimelineTarget::new(world_id, timeline_id), invocation)
    }
}

/// The public outcome of a semantic Action execution.
///
/// `Committed` means the Runtime commit linearization point accepted the
/// validated proposal and returned the committed Event identities plus the
/// resulting Timeline version. A Work-only commit may therefore be
/// `Committed` with an empty Event list. `NoChange` means the execution
/// contained no Event or Work mutation. `Rejected` is a normal semantic
/// refusal from the Capability, not an infrastructure failure.
///
/// Infrastructure and API failures are returned through `ApiError` instead of
/// being encoded as an outcome variant. In particular, a Timeline CAS conflict
/// is not a domain rejection. This public type intentionally contains no
/// `ValidatedResolution`, overlay, read set, transaction or retry detail.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub enum ExecutionResult {
    /// The proposal became committed Runtime state and, when present, World
    /// history.
    Committed {
        /// Timeline-local identities of Events committed by this execution.
        event_ids: Vec<EventId>,
        /// Timeline version after the successful atomic commit.
        timeline_version: TimelineVersion,
    },
    /// The execution completed without changing World Truth.
    NoChange,
    /// The semantic Action was refused by its owning Capability.
    Rejected(Rejection),
}

impl ExecutionResult {
    /// Creates a committed execution result.
    #[must_use]
    pub const fn committed(event_ids: Vec<EventId>, timeline_version: TimelineVersion) -> Self {
        Self::Committed {
            event_ids,
            timeline_version,
        }
    }

    /// Creates a no-change execution result.
    #[must_use]
    pub const fn no_change() -> Self {
        Self::NoChange
    }

    /// Creates a semantic rejection execution result.
    #[must_use]
    pub const fn rejected(rejection: Rejection) -> Self {
        Self::Rejected(rejection)
    }

    /// Reports whether the execution reached the atomic Runtime commit.
    #[must_use]
    pub const fn is_committed(&self) -> bool {
        matches!(self, Self::Committed { .. })
    }

    /// Reports whether the execution completed without changing World Truth.
    #[must_use]
    pub const fn is_no_change(&self) -> bool {
        matches!(self, Self::NoChange)
    }

    /// Reports whether the owning Capability semantically rejected the action.
    #[must_use]
    pub const fn is_rejected(&self) -> bool {
        matches!(self, Self::Rejected(_))
    }
}

/// Stable category for an API/service failure.
///
/// These categories describe the public boundary only. Runtime, SQL, network,
/// provider and transaction implementation details must be mapped to one of
/// these categories before crossing into `loom-api`.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub enum ApiErrorCode {
    /// The caller supplied an invalid or incomplete public request.
    InvalidRequest,
    /// The addressed World, Timeline or catalog item does not exist.
    NotFound,
    /// The requested operation conflicts with current public state, such as a
    /// stale Timeline version that Runtime could not safely retry.
    Conflict,
    /// The service cannot currently perform the operation but the request is
    /// otherwise valid.
    Unavailable,
    /// A failure occurred inside the service boundary and has no more specific
    /// public classification.
    Internal,
}

/// A typed failure returned by a public Loom service.
///
/// `ApiError` is separate from `ExecutionResult::Rejected`: the latter is a
/// normal Capability-owned semantic outcome, while this type reports request,
/// lookup, concurrency or infrastructure failure at the API boundary. The
/// message is safe boundary-facing text selected by the implementing service;
/// it must not contain SQL, storage transaction, Runtime authority or provider
/// internals.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ApiError {
    /// Stable public category that consumers can branch on.
    pub code: ApiErrorCode,
    /// Boundary-safe explanation suitable for logs or a transport response.
    pub message: String,
}

impl ApiError {
    /// Creates a typed API error with boundary-safe text.
    #[must_use]
    pub fn new(code: ApiErrorCode, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    /// Creates an invalid-request error.
    #[must_use]
    pub fn invalid_request(message: impl Into<String>) -> Self {
        Self::new(ApiErrorCode::InvalidRequest, message)
    }

    /// Creates a not-found error.
    #[must_use]
    pub fn not_found(message: impl Into<String>) -> Self {
        Self::new(ApiErrorCode::NotFound, message)
    }

    /// Creates a public concurrency/conflict error.
    #[must_use]
    pub fn conflict(message: impl Into<String>) -> Self {
        Self::new(ApiErrorCode::Conflict, message)
    }

    /// Creates a temporary-unavailability error.
    #[must_use]
    pub fn unavailable(message: impl Into<String>) -> Self {
        Self::new(ApiErrorCode::Unavailable, message)
    }

    /// Creates an internal service error without retaining an implementation
    /// error object in the public contract.
    #[must_use]
    pub fn internal(message: impl Into<String>) -> Self {
        Self::new(ApiErrorCode::Internal, message)
    }
}

impl fmt::Display for ApiError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl fmt::Display for ApiErrorCode {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let code = match self {
            Self::InvalidRequest => "invalid_request",
            Self::NotFound => "not_found",
            Self::Conflict => "conflict",
            Self::Unavailable => "unavailable",
            Self::Internal => "internal",
        };
        formatter.write_str(code)
    }
}

impl std::error::Error for ApiError {}

/// A convenient result alias for public Loom service methods.
pub type ApiResult<T> = Result<T, ApiError>;

/// Executor-neutral future returned by public Loom I/O service methods.
///
/// The boxed future keeps the focused service traits object-safe, so an
/// application may continue to consume `&dyn LoomApi` while Runtime awaits
/// asynchronous persistence. The contract chooses no executor and exposes no
/// Runtime, database or transaction type.
pub type ApiFuture<'a, T> = Pin<Box<dyn Future<Output = ApiResult<T>> + 'a>>;

/// The versioned state and World time observed for one Timeline.
///
/// This is a read-only public snapshot descriptor. `version` is the
/// optimistic-concurrency value that Runtime uses for its internal CAS; its
/// presence does not grant the caller permission to commit or allow a caller
/// to bypass Runtime validation. The snapshot contains no storage handle or
/// mutable state overlay.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct TimelineSnapshot {
    /// World and Timeline identity represented by this snapshot.
    pub target: TimelineTarget,
    /// Timeline head/state version observed at one consistent read boundary.
    pub version: TimelineVersion,
    /// Current semantic World time of the Timeline.
    pub world_time: WorldInstant,
    /// Immutable parent/fork position metadata; root Timelines use the root
    /// value. Ancestor Event rows are not duplicated into this snapshot.
    pub ancestry: TimelineAncestry,
}

impl TimelineSnapshot {
    /// Creates a Timeline snapshot descriptor.
    #[must_use]
    pub const fn new(
        target: TimelineTarget,
        version: TimelineVersion,
        world_time: WorldInstant,
    ) -> Self {
        Self {
            target,
            version,
            world_time,
            ancestry: TimelineAncestry::root(),
        }
    }

    /// Creates a public snapshot including immutable Timeline ancestry.
    #[must_use]
    pub const fn with_ancestry(
        target: TimelineTarget,
        version: TimelineVersion,
        world_time: WorldInstant,
        ancestry: TimelineAncestry,
    ) -> Self {
        Self {
            target,
            version,
            world_time,
            ancestry,
        }
    }
}

/// The public result of a successful current-head fork.
pub type ForkTimelineResult = TimelineSnapshot;

/// Query for one current Facet value in a Timeline.
///
/// A Facet value is Timeline-local mutable World state. The query identifies
/// its structural owner and Capability-owned schema key explicitly; it does
/// not expose a database table, JSON patch path or Runtime candidate overlay.
/// Runtime/Storage implementations provide a consistent read for the target
/// Timeline and return `None` when that Facet instance is absent.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct FacetQuery {
    /// World and Timeline whose current state is queried.
    pub target: TimelineTarget,
    /// Entity or Relationship owning the requested Facet instance.
    pub owner: FacetOwner,
    /// Capability-owned Facet schema key to inspect.
    pub facet_type: FacetTypeId,
}

impl FacetQuery {
    /// Creates a current-Facet query.
    #[must_use]
    pub const fn new(target: TimelineTarget, owner: FacetOwner, facet_type: FacetTypeId) -> Self {
        Self {
            target,
            owner,
            facet_type,
        }
    }
}

/// A current, materialized Facet value returned by the public Query service.
///
/// `FacetSnapshot` is a public read model, not a proposed Effect. Its value
/// is the complete Facet replacement currently visible on the addressed
/// Timeline; changing it still requires a semantic Action and a committed
/// Event. The owning Capability defines the meaning of the serialized value
/// and schema revision.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct FacetSnapshot {
    /// Entity or Relationship owning this current Facet instance.
    pub owner: FacetOwner,
    /// Capability-owned schema key for the Facet value.
    pub facet_type: FacetTypeId,
    /// Schema revision used to interpret `value`.
    pub schema_revision: SchemaRevision,
    /// Complete current Facet value in the owning Capability's schema.
    pub value: Value,
}

impl FacetSnapshot {
    /// Creates a public Facet read model.
    #[must_use]
    pub const fn new(
        owner: FacetOwner,
        facet_type: FacetTypeId,
        schema_revision: SchemaRevision,
        value: Value,
    ) -> Self {
        Self {
            owner,
            facet_type,
            schema_revision,
            value,
        }
    }
}

/// Query for committed Event history on one Timeline.
///
/// The v0 query is intentionally limited to a Timeline target and an optional
/// lower Event sequence plus count. It is not a general query language or a
/// storage pagination contract. Results remain ordered by authoritative
/// Timeline `EventSeq`, never by UUID ordering.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EventQuery {
    /// World and Timeline whose committed history is queried.
    pub target: TimelineTarget,
    /// Return Events strictly after this Timeline sequence when present.
    pub after: Option<EventSeq>,
    /// Maximum number of Events requested by the consumer when present.
    pub limit: Option<u32>,
}

impl EventQuery {
    /// Creates a query for the complete committed history of a Timeline.
    #[must_use]
    pub const fn all(target: TimelineTarget) -> Self {
        Self {
            target,
            after: None,
            limit: None,
        }
    }

    /// Creates a bounded history query beginning after an Event sequence.
    #[must_use]
    pub const fn after(target: TimelineTarget, after: EventSeq, limit: Option<u32>) -> Self {
        Self {
            target,
            after: Some(after),
            limit,
        }
    }
}

/// One committed World Event exposed by the public History service.
///
/// Unlike `loom_protocol::ProposedEvent`, this read model carries authoritative
/// Timeline identity and `EventSeq`, and its existence means the enclosing
/// commit succeeded. Its frozen Effects are historical read data, not a public
/// command; consumers must invoke semantic Actions to request future changes.
/// Platform commit timestamps and Runtime execution provenance remain outside
/// this v0 contract.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct CommittedEvent {
    /// Technical identity of the committed Event.
    pub id: EventId,
    /// Timeline containing the committed Event.
    pub timeline_id: TimelineId,
    /// Authoritative Timeline-local ordering assigned at commit.
    pub sequence: EventSeq,
    /// Capability-owned semantic Event schema key.
    pub event_type: EventTypeId,
    /// Schema revision used to interpret the committed payload.
    pub schema_revision: SchemaRevision,
    /// World semantic time at which the Event occurred/effective.
    pub occurred_at: WorldInstant,
    /// Direct Entity associations recorded by the Event.
    pub participants: Vec<EventParticipant>,
    /// Relationship associations recorded by the Event.
    pub relationship_refs: Vec<EventRelationshipRef>,
    /// Causal references to preceding committed Events.
    pub causal_links: Vec<CausalLink>,
    /// Capability-owned semantic payload frozen in the Event history.
    pub payload: Value,
    /// Mechanical Effects frozen under the committed Event.
    pub effects: Vec<WorldEffect>,
}

/// Stable identity used by the public Capability catalog.
///
/// Capability ownership is software metadata, not a World Entity or Runtime
/// authority. The registry owns uniqueness and dependency interpretation;
/// `loom-api` only transports the stable identifier to consumers.
#[derive(Clone, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct CapabilityId(String);

impl CapabilityId {
    /// Creates a Capability catalog identifier.
    #[must_use]
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Borrows the stable Capability identifier.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<String> for CapabilityId {
    fn from(value: String) -> Self {
        Self::new(value)
    }
}

impl From<&str> for CapabilityId {
    fn from(value: &str) -> Self {
        Self::new(value)
    }
}

impl From<CapabilityId> for String {
    fn from(value: CapabilityId) -> Self {
        value.0
    }
}

impl fmt::Display for CapabilityId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// Public descriptor for one registered Capability.
///
/// This is catalog metadata projected by Loom; it is not the Capability
/// implementation or its resolver object. `dependencies` are stable semantic
/// Capability identifiers and are informational at this boundary; registry
/// assembly remains responsible for validating them.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CapabilityDescriptor {
    /// Stable semantic identity of the registered Capability.
    pub id: CapabilityId,
    /// Capability software version exposed for discovery.
    pub version: String,
    /// Human-readable description safe for catalog consumers.
    pub description: String,
    /// Capability identifiers required by this Capability's registration.
    pub dependencies: Vec<CapabilityId>,
}

/// Public descriptor for one Capability-owned semantic Action.
///
/// An `ActionDescriptor` describes discovery metadata only. `id` is not an
/// HTTP route and `input_schema` is not a transport DTO; the actual semantic
/// input still crosses the common `ActionService` as `ActionInvocation`.
/// Runtime/Capability registry owns the definition and maps it into this
/// stable read model without exposing an `ActionResolver` object.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ActionDescriptor {
    /// Stable semantic Action key selected by `ActionInvocation`.
    pub id: ActionTypeId,
    /// Capability that owns and interprets this Action.
    pub owner: CapabilityId,
    /// Schema revision used to interpret the Action input.
    pub schema_revision: SchemaRevision,
    /// Human-readable description safe for discovery clients.
    pub description: String,
    /// Optional schema-shaped metadata for generic consumers; it is not a
    /// transport-specific request/response definition.
    pub input_schema: Option<Value>,
}

/// A coherent public snapshot of registered Capability and Action metadata.
///
/// The snapshot is read-only catalog data assembled centrally by Loom. It does
/// not grant direct access to a Capability module, and it cannot be used to
/// invoke an Action without going through `ActionService`.
#[derive(Clone, Debug, Default, Deserialize, PartialEq, Serialize)]
pub struct CatalogSnapshot {
    /// Registered Capability descriptors visible to the consumer.
    pub capabilities: Vec<CapabilityDescriptor>,
    /// Registered semantic Action descriptors visible through Loom.
    pub actions: Vec<ActionDescriptor>,
}

impl CatalogSnapshot {
    /// Returns the first Action descriptor matching a semantic key.
    #[must_use]
    pub fn action(&self, id: &ActionTypeId) -> Option<&ActionDescriptor> {
        self.actions.iter().find(|action| &action.id == id)
    }

    /// Returns the first Capability descriptor matching a stable identifier.
    #[must_use]
    pub fn capability(&self, id: &CapabilityId) -> Option<&CapabilityDescriptor> {
        self.capabilities
            .iter()
            .find(|capability| &capability.id == id)
    }
}

/// Creates long-lived World identity through the unified Loom API.
///
/// This service exposes only Template-based birth. Callers do not choose UUID
/// algorithms, access storage transactions or obtain Runtime authority tokens.
/// Runtime validates the complete descriptor and atomically snapshots its
/// provenance, semantic Binding and ordered bootstrap recipe into the new
/// World. Once the World exists, changing its truth requires the same semantic
/// Action / Durable Work and Runtime commit path used by every other Timeline.
pub trait WorldService {
    /// Creates one World by validating and atomically applying a Template birth
    /// recipe.
    ///
    /// The default keeps focused third-party API test doubles source-compatible;
    /// the Runtime implementation is the production authority for this method.
    /// A successful result includes the final initial-Timeline version after all
    /// bootstrap Events, Effects and logical Work have committed together.
    fn create_world_from_template(
        &self,
        _request: CreateWorldFromTemplateRequest,
    ) -> ApiFuture<'_, CreateWorldFromTemplateResult> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Template World birth is not implemented by this service",
            ))
        })
    }
}

/// Executes semantic Actions against a World Timeline.
///
/// This is the public Action boundary implemented by Runtime. It accepts one
/// common request shape for every Capability and returns either a committed,
/// no-change or semantically rejected outcome. It must not expose a concrete
/// resolver, storage command or Runtime authority token.
pub trait ActionService {
    /// Resolves and attempts one Action request on the addressed Timeline.
    ///
    /// A semantic refusal is returned as `Ok(ExecutionResult::Rejected(_))`.
    /// Request, lookup, concurrency and infrastructure failures use
    /// `Err(ApiError)` instead. The returned future is executor-neutral and
    /// keeps persistence latency outside Capability semantic execution.
    ///
    /// # Errors
    ///
    /// Returns an `ApiError` when the request cannot be resolved or committed
    /// through the public service boundary.
    fn invoke(&self, request: ActionRequest) -> ApiFuture<'_, ExecutionResult>;

    /// Invokes an Action using separate World/Timeline identities.
    ///
    /// # Errors
    ///
    /// Propagates the `ApiError` returned by `invoke`.
    fn invoke_on(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        invocation: ActionInvocation,
    ) -> ApiFuture<'_, ExecutionResult> {
        self.invoke(ActionRequest::for_timeline(
            world_id,
            timeline_id,
            invocation,
        ))
    }
}

/// Inspects and forks Timelines at the unified public boundary.
///
/// This service is intentionally limited to observation. Initial World/Timeline
/// World creation belongs to [`WorldService`]; fork is a Runtime-owned
/// operation and never an inspection side effect.
pub trait TimelineService {
    /// Returns one consistent public Timeline snapshot.
    ///
    /// # Errors
    ///
    /// Returns an `ApiError` when the World/Timeline cannot be found or read.
    fn inspect_timeline(&self, target: TimelineTarget) -> ApiFuture<'_, TimelineSnapshot>;

    /// Allocates a child Timeline from the source's current committed head.
    ///
    /// The default keeps focused API test doubles source-compatible. Runtime's
    /// implementation is the authority for the atomic reconstruction and
    /// branch-local Pending Work clone.
    fn fork(&self, _request: ForkTimelineRequest) -> ApiFuture<'_, ForkTimelineResult> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Timeline fork is not implemented by this service",
            ))
        })
    }

    /// Explicit operation-name alias for [`Self::fork`].
    fn fork_timeline(&self, request: ForkTimelineRequest) -> ApiFuture<'_, ForkTimelineResult> {
        self.fork(request)
    }
}

/// Reads current materialized World state through the unified API.
///
/// The v0 Query surface exposes only the Facet lookup required by the vertical
/// slice. It returns a read model and never a mutable repository, candidate
/// overlay or direct write handle.
pub trait QueryService {
    /// Reads one current Facet value, returning `None` when it is absent.
    ///
    /// # Errors
    ///
    /// Returns an `ApiError` when the target cannot be found or read.
    fn get_facet(&self, query: FacetQuery) -> ApiFuture<'_, Option<FacetSnapshot>>;
}

/// Reads committed World history through the unified API.
///
/// Results are committed Event read models ordered by Timeline `EventSeq`.
/// This service cannot append, rewrite or replay history.
pub trait HistoryService {
    /// Lists committed Events matching the bounded v0 history query.
    ///
    /// # Errors
    ///
    /// Returns an `ApiError` when the target cannot be found or its history
    /// cannot be read.
    fn list_events(&self, query: EventQuery) -> ApiFuture<'_, Vec<CommittedEvent>>;
}

/// Discovers centrally registered Capability and semantic Action definitions.
///
/// The catalog is the single public discovery surface for all semantic
/// extensions. It does not expose a Capability resolver or permit a consumer
/// to bypass `ActionService` with a module-specific endpoint.
pub trait CatalogService {
    /// Returns the currently visible central catalog snapshot.
    ///
    /// # Errors
    ///
    /// Returns an `ApiError` when the catalog cannot be read.
    fn catalog(&self) -> ApiResult<CatalogSnapshot>;
}

/// A compile-time composition bound for a complete World-facing Loom API.
///
/// This trait intentionally has no methods and is implemented automatically
/// for a service that provides the focused Action, Timeline, Query, History
/// and Catalog contracts. It offers consumers one unified bound without
/// creating a giant service trait or adding a Runtime implementation type.
pub trait LoomApi:
    ActionService + CatalogService + HistoryService + QueryService + TimelineService + WorldService
{
}

impl<T> LoomApi for T where
    T: ActionService
        + CatalogService
        + HistoryService
        + QueryService
        + TimelineService
        + WorldService
{
}

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use serde_json::json;

    use super::{
        ActionDescriptor, ActionRequest, ActionService, ApiError, ApiErrorCode, ApiFuture,
        ApiResult, CapabilityDescriptor, CapabilityId, CatalogService, CatalogSnapshot,
        CommittedEvent, CreateWorldFromTemplateRequest, CreateWorldFromTemplateResult, EventQuery,
        ExecutionResult, FacetQuery, FacetSnapshot, HistoryService, LoomApi, QueryService,
        TimelineService, TimelineSnapshot, TimelineTarget, WorldService, WorldTemplateDescriptor,
    };
    use crate::{
        ActionInvocation, ActionTypeId, FacetOwner, FacetTypeId, Rejection, SchemaRevision,
        TimelineId, TimelineVersion, WorldId, WorldInstant,
    };

    fn target() -> TimelineTarget {
        TimelineTarget::new(
            WorldId::from_str("00000000-0000-0000-0000-000000000001")
                .expect("test WorldId should parse"),
            TimelineId::from_str("00000000-0000-0000-0000-000000000002")
                .expect("test TimelineId should parse"),
        )
    }

    #[derive(Default)]
    struct StubApi;

    impl WorldService for StubApi {
        fn create_world_from_template(
            &self,
            request: CreateWorldFromTemplateRequest,
        ) -> ApiFuture<'_, CreateWorldFromTemplateResult> {
            Box::pin(async move {
                Ok(TimelineSnapshot::new(
                    target(),
                    TimelineVersion::default(),
                    request.template.initial_world_time,
                ))
            })
        }
    }

    impl ActionService for StubApi {
        fn invoke(&self, request: ActionRequest) -> ApiFuture<'_, ExecutionResult> {
            Box::pin(async move {
                assert_eq!(request.target, target());
                assert_eq!(request.invocation.action.as_str(), "counter.increment");
                Ok(ExecutionResult::committed(
                    Vec::new(),
                    TimelineVersion::new(1.into(), 1.into()),
                ))
            })
        }
    }

    impl TimelineService for StubApi {
        fn inspect_timeline(&self, target: TimelineTarget) -> ApiFuture<'_, TimelineSnapshot> {
            Box::pin(async move {
                Ok(TimelineSnapshot::new(
                    target,
                    TimelineVersion::new(1.into(), 1.into()),
                    WorldInstant::new(7),
                ))
            })
        }
    }

    impl QueryService for StubApi {
        fn get_facet(&self, query: FacetQuery) -> ApiFuture<'_, Option<FacetSnapshot>> {
            Box::pin(async move {
                Ok(Some(FacetSnapshot::new(
                    query.owner,
                    query.facet_type,
                    SchemaRevision::new(1),
                    json!({"value": 1}),
                )))
            })
        }
    }

    impl HistoryService for StubApi {
        fn list_events(&self, _query: EventQuery) -> ApiFuture<'_, Vec<CommittedEvent>> {
            Box::pin(async { Ok(Vec::new()) })
        }
    }

    impl CatalogService for StubApi {
        fn catalog(&self) -> ApiResult<CatalogSnapshot> {
            Ok(CatalogSnapshot {
                capabilities: vec![CapabilityDescriptor {
                    id: CapabilityId::from("counter.basic"),
                    version: "0.1".to_owned(),
                    description: "test capability".to_owned(),
                    dependencies: Vec::new(),
                }],
                actions: vec![ActionDescriptor {
                    id: ActionTypeId::from("counter.increment"),
                    owner: CapabilityId::from("counter.basic"),
                    schema_revision: SchemaRevision::new(1),
                    description: "increment".to_owned(),
                    input_schema: Some(json!({"type": "object"})),
                }],
            })
        }
    }

    fn assert_complete_api<T: LoomApi>(_: &T) {}

    #[test]
    fn action_request_targets_world_and_timeline_without_transport_types() {
        let request = ActionRequest::for_timeline(
            target().world_id,
            target().timeline_id,
            ActionInvocation::new(
                ActionTypeId::from("counter.increment"),
                json!({"amount": 1}),
            ),
        );
        let encoded = serde_json::to_string(&request).expect("request should serialize");
        let decoded: ActionRequest =
            serde_json::from_str(&encoded).expect("request should deserialize");
        assert_eq!(decoded, request);
    }

    #[test]
    fn execution_outcomes_keep_rejection_and_api_error_channels_distinct() {
        let rejected = ExecutionResult::rejected(Rejection::new(
            "counter.invalid_amount",
            "amount must be positive",
        ));
        assert!(rejected.is_rejected());
        assert!(!rejected.is_committed());

        let conflict = ApiError::conflict("Timeline changed before commit");
        assert_eq!(conflict.code, ApiErrorCode::Conflict);
        assert_ne!(conflict.code, ApiErrorCode::InvalidRequest);
    }

    #[tokio::test]
    async fn focused_services_form_one_public_world_api() {
        let api = StubApi;
        assert_complete_api(&api);

        let created = api
            .create_world_from_template(CreateWorldFromTemplateRequest::new(
                WorldTemplateDescriptor::new("test", 1, WorldInstant::new(11)),
            ))
            .await
            .expect("World should be creatable");
        assert_eq!(created.target, target());
        assert_eq!(created.version, TimelineVersion::default());
        assert_eq!(created.world_time.value(), 11);

        let result = api
            .invoke_on(
                target().world_id,
                target().timeline_id,
                ActionInvocation::new(ActionTypeId::from("counter.increment"), json!({})),
            )
            .await
            .expect("action should execute");
        assert!(result.is_committed());

        let snapshot = api
            .inspect_timeline(target())
            .await
            .expect("timeline should be inspectable");
        assert_eq!(snapshot.world_time.value(), 7);

        let facet = api
            .get_facet(FacetQuery::new(
                target(),
                FacetOwner::entity(
                    crate::EntityId::from_str("00000000-0000-0000-0000-000000000003")
                        .expect("test EntityId should parse"),
                ),
                FacetTypeId::from("counter.value"),
            ))
            .await
            .expect("facet should be queryable")
            .expect("stub facet should exist");
        assert_eq!(facet.schema_revision.value(), 1);

        let catalog = api.catalog().expect("catalog should be discoverable");
        assert!(
            catalog
                .action(&ActionTypeId::from("counter.increment"))
                .is_some()
        );
    }

    #[test]
    fn history_query_defaults_to_authoritative_timeline_ordering() {
        let query = EventQuery::all(target());
        assert_eq!(query.target, target());
        assert!(query.after.is_none());
        assert!(query.limit.is_none());
    }
}
