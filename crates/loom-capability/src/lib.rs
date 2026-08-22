//! Loom Capability: semantic extension API/SPI and ownership contracts.
//!
//! # Responsibility
//!
//! This crate defines how a Capability declares and registers coherent World
//! semantics. v0 contracts include manifests, Facet/Relationship/Event/Action
//! definitions, Action resolvers, read-only invariants, Durable Work handlers,
//! reactions and the host ports a resolver may use while it is being executed.
//!
//! Concrete domain implementations should depend on this crate; this crate does
//! not depend on those implementations.
//!
//! Every semantic type has one owning Capability. A Capability may read semantic
//! domains declared as dependencies, but it may directly produce mutations only
//! for semantics it owns. Cross-Capability mutation is composed through a
//! Runtime-mediated subresolution so each semantic owner remains responsible for
//! its own rules while all resulting changes may still join one atomic Timeline
//! commit.
//!
//! # Protocol boundary
//!
//! Capability contracts speak in `loom-core` World values and untrusted
//! `loom-protocol` execution values. Resolvers may return a protocol
//! `Resolution`/`ResolveOutcome`; they never need to import `loom-runtime` merely
//! to construct their output.
//!
//! The host-facing `ResolutionContext` and world-view ports belong on this
//! extension side: they specify what a host must provide in order to execute
//! Capability logic. `loom-runtime` implements that host behavior.
//!
//! Therefore the Cargo direction is:
//!
//! ```text
//! loom-capability -> loom-core
//! loom-capability -> loom-protocol
//! loom-capability -X-> loom-runtime
//! ```
//!
//! # Authority and truth
//!
//! Capability code has semantic power but never Runtime authority. Resolvers
//! and Work handlers produce untrusted proposals; invariants may only
//! accept/reject candidate state. Capability code cannot construct
//! `ValidatedResolution`, append an Event directly or mutate persistence.
//!
//! # Unified exposure rule
//!
//! Capability registers **semantics**, never public transport/application
//! exposure. It must not register HTTP/SSE/WebSocket/gRPC routes, CLI commands,
//! GPUI engine endpoints or SDK services. A semantic Action such as
//! `finance.transfer` becomes externally available only through the unified
//! `loom-api` contract.
//!
//! > Extension defines semantics; Loom owns exposure.
//!
//! # Forbidden resources
//!
//! Capability implementations must not receive raw database handles, SQL
//! transactions, network clients, platform clocks, raw randomness, provider
//! clients or direct commit handles. Required nondeterminism and external
//! cognition are requested through explicit host-controlled boundaries.
//!
//! # Documentation contract
//!
//! Every semantic definition documents its owner, schema/version meaning,
//! allowed participants or inputs, reads/writes and relationship to neighboring
//! semantics. Resolver/Invariant/WorkHandler docs also state what they are
//! forbidden to mutate. See `docs/architecture/runtime-contracts.md` and
//! `docs/architecture/governance.md`.

#![forbid(unsafe_code)]

use std::{
    collections::{BTreeMap, BTreeSet},
    error::Error,
    fmt,
    sync::Arc,
};

use loom_core::{
    ActionTypeId, AssociationRole, Entity, EntityId, EventTypeId, FacetOwner, FacetTypeId,
    Relationship, RelationshipId, RelationshipTypeId, SchemaRevision, TimelineId, TimelineVersion,
    WorkHandlerId, WorldInstant,
};
use loom_protocol::{ActionInvocation, ResolveOutcome, WorkSchedule};
use semver::{Version, VersionReq};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Stable software identity of one registered Capability.
///
/// `CapabilityId` belongs to Capability metadata rather than World Truth. The
/// registry uses it to identify an owner and to resolve declared dependency
/// edges. It is not a World Entity, semantic Action ID or transport route.
#[derive(Clone, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct CapabilityId(String);

impl CapabilityId {
    /// Creates a Capability metadata identifier from a stable key.
    ///
    /// The registry validates uniqueness and dependency references. This value
    /// constructor does not grant registration or Runtime authority.
    #[must_use]
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Borrows the stable Capability key.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Reports whether the key is empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    /// Returns the owned Capability key.
    #[must_use]
    pub fn into_string(self) -> String {
        self.0
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
        value.into_string()
    }
}

impl fmt::Display for CapabilityId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// A declared dependency on another Capability and its compatible version
/// range.
///
/// This is software assembly metadata, not a World relationship or Runtime
/// execution edge. The registry resolves `id` against registered manifests and
/// rejects a missing or incompatible provider before a registry is used for
/// resolution. `version` is a semver requirement, so malformed requirements
/// are rejected while the declaration is constructed rather than silently
/// treated as unconstrained.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CapabilityDependency {
    /// Capability metadata identifier required by the declaring Capability.
    pub id: CapabilityId,
    /// Semver range accepted for the required Capability.
    pub version: VersionReq,
}

impl CapabilityDependency {
    /// Creates a typed Capability dependency declaration.
    #[must_use]
    pub fn new(id: impl Into<CapabilityId>, version: VersionReq) -> Self {
        Self {
            id: id.into(),
            version,
        }
    }

    /// Parses a semver dependency declaration from a human-authored range.
    ///
    /// # Errors
    ///
    /// Returns the semver parser error when `version` is not a valid
    /// requirement. The invalid declaration is therefore never admitted as a
    /// valid dependency value.
    pub fn parse(id: impl Into<CapabilityId>, version: &str) -> Result<Self, semver::Error> {
        Ok(Self::new(id, VersionReq::parse(version)?))
    }
}

/// Capability software metadata used during registry assembly.
///
/// A manifest identifies one Capability implementation, its own semver
/// version, the Loom contract version it can run against, and the other
/// Capabilities it requires. It is software metadata, not World state and not
/// a permission grant. The registry owns dependency validation; a manifest
/// alone does not make any semantic registration available.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CapabilityManifest {
    /// Stable metadata identity of this Capability.
    pub id: CapabilityId,
    /// Version of this Capability implementation and its registered schemas.
    pub version: Version,
    /// Loom contract versions accepted by this Capability.
    pub loom_compatibility: VersionReq,
    /// Capability providers required before this registration can be assembled.
    pub dependencies: Vec<CapabilityDependency>,
    /// Human-readable metadata for central discovery; it has no execution
    /// semantics.
    pub description: String,
}

/// Compiles one Capability-owned schema as Draft 2020-12 metadata.
///
/// Capability registration uses this helper to reject malformed schema
/// documents before a registry can be handed to Runtime. Runtime may use the
/// companion [`validate_json_schema`] helper for instance checks, but this
/// function does not retain a validator, authorize an Effect or grant commit
/// authority. The raw schema document remains owned by its registered
/// Capability definition.
///
/// # Errors
///
/// Returns a deterministic, boundary-safe explanation when `schema` is not a
/// valid Draft 2020-12 document or a referenced resource cannot be resolved.
pub fn validate_json_schema_document(schema: &Value) -> Result<(), String> {
    jsonschema::draft202012::new(schema)
        .map(|_| ())
        .map_err(|error| format!("invalid Draft 2020-12 schema: {error}"))
}

/// Validates one instance against a Capability-owned Draft 2020-12 schema.
///
/// This is a focused implementation helper shared by the Capability assembly
/// and Runtime validation boundaries. It does not change the schema document,
/// infer a schema revision, invoke a resolver or make the instance commit
/// eligible; Runtime still owns candidate-state validation and commit
/// authority.
///
/// # Errors
///
/// Returns a deterministic validator/compiler explanation when the schema is
/// malformed or when `value` violates the schema.
pub fn validate_json_schema(schema: &Value, value: &Value) -> Result<(), String> {
    let validator = jsonschema::draft202012::new(schema)
        .map_err(|error| format!("invalid Draft 2020-12 schema: {error}"))?;
    validator.validate(value).map_err(|error| error.to_string())
}

impl CapabilityManifest {
    /// Creates a manifest with no Capability dependencies and an unconstrained
    /// Loom contract requirement.
    #[must_use]
    pub fn new(id: impl Into<CapabilityId>, version: Version) -> Self {
        Self {
            id: id.into(),
            version,
            loom_compatibility: VersionReq::STAR,
            dependencies: Vec::new(),
            description: String::new(),
        }
    }

    /// Parses a manifest version from a semver string.
    ///
    /// # Errors
    ///
    /// Returns the semver parser error when `version` is not a valid version.
    pub fn parse(id: impl Into<CapabilityId>, version: &str) -> Result<Self, semver::Error> {
        Ok(Self::new(id, Version::parse(version)?))
    }

    /// Sets a human-readable discovery description.
    #[must_use]
    pub fn with_description(mut self, description: impl Into<String>) -> Self {
        self.description = description.into();
        self
    }

    /// Sets the Loom contract compatibility requirement.
    #[must_use]
    pub fn compatible_with(mut self, requirement: VersionReq) -> Self {
        self.loom_compatibility = requirement;
        self
    }

    /// Adds one required Capability/version range to the manifest.
    #[must_use]
    pub fn requires(mut self, dependency: CapabilityDependency) -> Self {
        self.dependencies.push(dependency);
        self
    }

    /// Adds one required Capability using a parsed semver range.
    #[must_use]
    pub fn requires_version(
        mut self,
        id: impl Into<CapabilityId>,
        requirement: VersionReq,
    ) -> Self {
        self.dependencies
            .push(CapabilityDependency::new(id, requirement));
        self
    }
}

/// Schema metadata for one Capability-owned Facet semantic type.
///
/// A `FacetDefinition` describes the shape of Timeline-local state; it does not
/// contain a Facet instance and cannot write one. The registrar supplies the
/// owning Capability when the definition is admitted. `schema` is JSON Schema
/// 2020-12 metadata owned by the Capability and is validated by Runtime at the
/// candidate-state boundary.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct FacetDefinition {
    /// Stable semantic key of the Facet schema.
    pub id: FacetTypeId,
    /// Schema revision used to interpret Facet values.
    pub schema_revision: SchemaRevision,
    /// JSON Schema metadata for complete Facet replacement values.
    pub schema: Value,
    /// Human-readable semantic description for registry/catalog consumers.
    pub description: String,
}

impl FacetDefinition {
    /// Creates a Facet definition with an empty description.
    #[must_use]
    pub fn new(id: FacetTypeId, schema_revision: SchemaRevision, schema: Value) -> Self {
        Self {
            id,
            schema_revision,
            schema,
            description: String::new(),
        }
    }

    /// Sets the Facet's semantic description.
    #[must_use]
    pub fn with_description(mut self, description: impl Into<String>) -> Self {
        self.description = description.into();
        self
    }
}

/// Cardinality declaration for one semantic role in a Relationship.
///
/// Roles constrain a Relationship's structural participants; they do not
/// grant access or define domain behavior. Runtime uses this metadata while
/// validating a candidate `CreateRelationship` effect.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RelationshipRole {
    /// Stable role label interpreted by the owning Capability.
    pub role: AssociationRole,
    /// Minimum number of participants carrying this role.
    pub minimum: u16,
    /// Optional maximum number of participants carrying this role.
    pub maximum: Option<u16>,
}

impl RelationshipRole {
    /// Creates one role cardinality declaration.
    #[must_use]
    pub const fn new(role: AssociationRole, minimum: u16, maximum: Option<u16>) -> Self {
        Self {
            role,
            minimum,
            maximum,
        }
    }
}

/// Structural metadata for one Capability-owned Relationship type.
///
/// The definition describes participant roles and cardinality only. A
/// `RelationshipDefinition` does not create a Relationship instance, mutate
/// participant sets or expose a transport endpoint. Participant identities are
/// supplied later by a Runtime-validated `WorldEffect`.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RelationshipDefinition {
    /// Stable semantic key of the Relationship schema.
    pub id: RelationshipTypeId,
    /// Schema revision used to interpret Relationship metadata.
    pub schema_revision: SchemaRevision,
    /// Declared participant roles and their cardinality.
    pub roles: Vec<RelationshipRole>,
    /// Facet schemas permitted on instances of this Relationship type.
    pub allowed_facets: Vec<FacetTypeId>,
    /// Human-readable semantic description.
    pub description: String,
}

impl RelationshipDefinition {
    /// Creates an empty Relationship definition.
    #[must_use]
    pub fn new(id: RelationshipTypeId, schema_revision: SchemaRevision) -> Self {
        Self {
            id,
            schema_revision,
            roles: Vec::new(),
            allowed_facets: Vec::new(),
            description: String::new(),
        }
    }

    /// Adds one participant role declaration.
    #[must_use]
    pub fn with_role(mut self, role: RelationshipRole) -> Self {
        self.roles.push(role);
        self
    }

    /// Allows one Capability-owned Facet schema on this Relationship type.
    #[must_use]
    pub fn with_allowed_facet(mut self, facet: FacetTypeId) -> Self {
        self.allowed_facets.push(facet);
        self
    }

    /// Sets the Relationship's semantic description.
    #[must_use]
    pub fn with_description(mut self, description: impl Into<String>) -> Self {
        self.description = description.into();
        self
    }
}

/// Schema metadata for one Capability-owned Event type.
///
/// An `EventDefinition` describes the semantic envelope accepted for a
/// `ProposedEvent`; it is not a committed Event and it does not append to the
/// Event Ledger. Runtime owns event ordering, causal validation and commit.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct EventDefinition {
    /// Stable semantic key of the Event schema.
    pub id: EventTypeId,
    /// Schema revision used to interpret the Event payload and associations.
    pub schema_revision: SchemaRevision,
    /// Optional JSON Schema metadata for the Event payload.
    pub payload_schema: Option<Value>,
    /// Roles allowed for direct Entity participants.
    pub participant_roles: Vec<AssociationRole>,
    /// Roles allowed for referenced Relationships.
    pub relationship_roles: Vec<AssociationRole>,
    /// Human-readable semantic description.
    pub description: String,
}

impl EventDefinition {
    /// Creates an Event definition with no association or payload restrictions.
    #[must_use]
    pub fn new(id: EventTypeId, schema_revision: SchemaRevision) -> Self {
        Self {
            id,
            schema_revision,
            payload_schema: None,
            participant_roles: Vec::new(),
            relationship_roles: Vec::new(),
            description: String::new(),
        }
    }

    /// Sets JSON Schema metadata for the Event payload.
    #[must_use]
    pub fn with_payload_schema(mut self, schema: Value) -> Self {
        self.payload_schema = Some(schema);
        self
    }

    /// Allows one direct Entity association role.
    #[must_use]
    pub fn with_participant_role(mut self, role: AssociationRole) -> Self {
        self.participant_roles.push(role);
        self
    }

    /// Allows one Relationship reference role.
    #[must_use]
    pub fn with_relationship_role(mut self, role: AssociationRole) -> Self {
        self.relationship_roles.push(role);
        self
    }

    /// Sets the Event's semantic description.
    #[must_use]
    pub fn with_description(mut self, description: impl Into<String>) -> Self {
        self.description = description.into();
        self
    }
}

/// Metadata for one Capability-owned Action resolver.
///
/// `ActionDefinition` describes discovery and schema interpretation. The
/// resolver implementation is registered separately so metadata cannot itself
/// become a Runtime or commit handle. Consumers invoke the Action through the
/// unified Loom API, never through this definition.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ActionDefinition {
    /// Stable semantic key selected by `ActionInvocation`.
    pub id: ActionTypeId,
    /// Schema revision used to interpret the Action input.
    pub schema_revision: SchemaRevision,
    /// Optional JSON Schema metadata for the Action input.
    pub input_schema: Option<Value>,
    /// Human-readable semantic description.
    pub description: String,
}

impl ActionDefinition {
    /// Creates an Action definition with no input schema.
    #[must_use]
    pub fn new(id: ActionTypeId, schema_revision: SchemaRevision) -> Self {
        Self {
            id,
            schema_revision,
            input_schema: None,
            description: String::new(),
        }
    }

    /// Sets JSON Schema metadata for Action input.
    #[must_use]
    pub fn with_input_schema(mut self, schema: Value) -> Self {
        self.input_schema = Some(schema);
        self
    }

    /// Sets the Action's semantic description.
    #[must_use]
    pub fn with_description(mut self, description: impl Into<String>) -> Self {
        self.description = description.into();
        self
    }
}

/// Metadata for one Capability-owned Durable Work handler.
///
/// A Work handler definition routes a future obligation to a handler. It does
/// not represent a Work instance, claim lease or lifecycle transition. Runtime
/// remains responsible for current-Work completion/cancellation and technical
/// retry state.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct WorkHandlerDefinition {
    /// Stable semantic key used to route Durable Work.
    pub id: WorkHandlerId,
    /// Schema revision used to interpret handler payloads.
    pub schema_revision: SchemaRevision,
    /// Optional JSON Schema metadata for the handler payload.
    pub payload_schema: Option<Value>,
    /// Human-readable semantic description.
    pub description: String,
}

impl WorkHandlerDefinition {
    /// Creates a Work handler definition with no payload schema.
    #[must_use]
    pub fn new(id: WorkHandlerId, schema_revision: SchemaRevision) -> Self {
        Self {
            id,
            schema_revision,
            payload_schema: None,
            description: String::new(),
        }
    }

    /// Sets JSON Schema metadata for handler payloads.
    #[must_use]
    pub fn with_payload_schema(mut self, schema: Value) -> Self {
        self.payload_schema = Some(schema);
        self
    }

    /// Sets the Work handler's semantic description.
    #[must_use]
    pub fn with_description(mut self, description: impl Into<String>) -> Self {
        self.description = description.into();
        self
    }
}

/// A declarative reaction from one committed Event type to immediate Work.
///
/// A reaction is registration metadata, not an autonomous background task and
/// not an Event/Effect producer. Runtime may use the mapping after a matching
/// Event commits to schedule one `WorkHandlerId` with `WorkSchedule::Immediate`,
/// then execute it through the normal WorkHandler/Resolution/validation path.
/// Reaction registration does not execute code or mutate World state.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
pub struct Reaction {
    /// Event type whose committed occurrence activates this reaction.
    pub event_type: EventTypeId,
    /// Work handler that Runtime should schedule for later evaluation.
    pub handler: WorkHandlerId,
}

impl Reaction {
    /// Creates an Event-to-immediate-Work reaction mapping.
    #[must_use]
    pub const fn new(event_type: EventTypeId, handler: WorkHandlerId) -> Self {
        Self {
            event_type,
            handler,
        }
    }

    /// Returns the only v0 schedule permitted by this reaction contract.
    #[must_use]
    pub const fn schedule(&self) -> WorkSchedule {
        WorkSchedule::Immediate
    }
}

/// A read-only value returned by a host World view for one current Facet.
///
/// `FacetValue` is a Timeline-local read model, not a mutation command. Its
/// complete value is interpreted by the owning Capability; Runtime decides
/// whether a later `WorldEffect::PutFacet` is valid and commit-eligible.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct FacetValue {
    /// Schema revision used to interpret `value`.
    pub schema_revision: SchemaRevision,
    /// Complete current Facet value visible in the pinned view.
    pub value: Value,
}

impl FacetValue {
    /// Creates a read-only Facet value descriptor.
    #[must_use]
    pub const fn new(schema_revision: SchemaRevision, value: Value) -> Self {
        Self {
            schema_revision,
            value,
        }
    }
}

/// Compatibility name for the read-only Facet value returned by a view.
///
/// This alias remains a Capability-side read model; it is not the public
/// `loom-api` snapshot and cannot be used to mutate candidate or committed
/// state.
pub type FacetSnapshot = FacetValue;

/// Error reported by a host-provided World view or subresolution port.
///
/// The error is an execution-channel value, not a semantic `ResolveOutcome`.
/// It carries no database handle, transaction, provider error or commit
/// authority across the Capability boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolutionContextError {
    /// Boundary-safe explanation of the unavailable host operation.
    pub message: String,
}

impl ResolutionContextError {
    /// Creates a host-port error with boundary-safe text.
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for ResolutionContextError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for ResolutionContextError {}

/// Error channel for Action resolvers and Work handlers.
///
/// `ResolverError` represents an implementation/host failure while resolving;
/// normal world-rule refusal remains `ResolveOutcome::Rejected`. It contains no
/// storage or commit capability and cannot turn an untrusted `Resolution` into
/// World Truth.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolverError {
    /// Boundary-safe explanation of the resolution failure.
    pub message: String,
}

impl ResolverError {
    /// Creates a resolver error with boundary-safe text.
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl From<ResolutionContextError> for ResolverError {
    fn from(error: ResolutionContextError) -> Self {
        Self::new(error.message)
    }
}

impl fmt::Display for ResolverError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for ResolverError {}

/// Compatibility name for the Capability resolver error channel.
pub type CapabilityError = ResolverError;

/// Result alias used by Action resolvers and Work handlers.
pub type CapabilityResult<T> = Result<T, ResolverError>;

/// A pinned authoritative World view supplied by Runtime to a resolver.
///
/// `BaseWorldView` exposes only read operations at one `TimelineVersion`.
/// Runtime implementations must keep all reads on that pinned snapshot rather
/// than mixing revisions. The trait has no storage, SQL, clock, randomness or
/// commit methods, so a Capability can inspect World Truth but cannot mutate it
/// through this boundary.
pub trait BaseWorldView {
    /// Returns the Timeline identity represented by this pinned view.
    fn timeline_id(&self) -> TimelineId;

    /// Returns the exact version pinned for this resolution.
    fn version(&self) -> TimelineVersion;

    /// Returns the World semantic time visible in this snapshot.
    fn world_time(&self) -> WorldInstant;

    /// Reads one Entity identity if it exists in the pinned World structure.
    ///
    /// # Errors
    ///
    /// Returns a host error when the Runtime view cannot complete the read.
    fn get_entity(&self, entity_id: EntityId) -> Result<Option<Entity>, ResolutionContextError>;

    /// Reads one Relationship structure if it exists in the pinned view.
    ///
    /// # Errors
    ///
    /// Returns a host error when the Runtime view cannot complete the read.
    fn get_relationship(
        &self,
        relationship_id: RelationshipId,
    ) -> Result<Option<Relationship>, ResolutionContextError>;

    /// Reads one current Facet value from the pinned Timeline snapshot.
    ///
    /// # Errors
    ///
    /// Returns a host error when the Runtime view cannot complete the read.
    fn get_facet(
        &self,
        owner: FacetOwner,
        facet_type: &FacetTypeId,
    ) -> Result<Option<FacetValue>, ResolutionContextError>;

    /// Alias for `get_facet` using the wording of the resolution contract.
    ///
    /// # Errors
    ///
    /// Propagates the host error returned by `get_facet`.
    fn read_facet(
        &self,
        owner: FacetOwner,
        facet_type: &FacetTypeId,
    ) -> Result<Option<FacetValue>, ResolutionContextError> {
        self.get_facet(owner, facet_type)
    }
}

/// A read-only candidate view used by invariant validation.
///
/// Runtime implements this view as `BaseWorldView + Mutation Overlay`. It must
/// expose effects already applied earlier in the same candidate Resolution, but
/// it exposes no write method. Invariants can therefore inspect candidate state
/// and return a violation, while only Runtime's effect engine can apply or
/// commit mutations.
pub trait CandidateWorldView: BaseWorldView {}

/// Host-facing port used by an Action resolver or Work handler.
///
/// `ResolutionContext` supplies a pinned `BaseWorldView` and a Runtime-mediated
/// subresolution gateway. It is not a database context or transaction and does
/// not expose system time, randomness, network, storage or commit handles. A
/// subresolution returns another untrusted `ResolveOutcome`; Runtime remains
/// responsible for ownership validation and atomic commit composition.
pub trait ResolutionContext {
    /// Returns the pinned Base World view for this resolution.
    fn base_world(&self) -> &dyn BaseWorldView;

    /// Requests a Runtime-mediated subresolution on the same pinned execution
    /// boundary.
    ///
    /// # Errors
    ///
    /// Returns a host error when the Runtime cannot route or execute the
    /// subresolution. A returned `ResolveOutcome` is still untrusted.
    fn subresolve(
        &self,
        invocation: &ActionInvocation,
    ) -> Result<ResolveOutcome, ResolutionContextError>;

    /// Returns the Timeline identity of the pinned view.
    #[must_use]
    fn timeline_id(&self) -> TimelineId {
        self.base_world().timeline_id()
    }

    /// Returns the expected version against which Runtime must compare a
    /// future commit.
    #[must_use]
    fn pinned_version(&self) -> TimelineVersion {
        self.base_world().version()
    }

    /// Returns the World semantic time visible to this resolution.
    #[must_use]
    fn world_time(&self) -> WorldInstant {
        self.base_world().world_time()
    }

    /// Reads a current Facet through the pinned Base World view.
    ///
    /// # Errors
    ///
    /// Propagates the host error returned by the Base World view.
    fn get_facet(
        &self,
        owner: FacetOwner,
        facet_type: &FacetTypeId,
    ) -> Result<Option<FacetValue>, ResolutionContextError> {
        self.base_world().get_facet(owner, facet_type)
    }
}

/// A semantic violation returned by a read-only invariant.
///
/// An invariant violation rejects candidate state; it is not a repair command,
/// Event, Effect or Runtime error. The invariant has no API through which it
/// can mutate the candidate or mark Work complete.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InvariantViolation {
    /// Capability-owned stable code for the violated rule.
    pub code: String,
    /// Human-readable explanation of the invalid candidate state.
    pub message: String,
}

impl InvariantViolation {
    /// Creates a semantic invariant violation.
    #[must_use]
    pub fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}

/// Read-only candidate-state validation SPI.
///
/// Runtime invokes an `Invariant` after applying proposed effects to a
/// `CandidateWorldView`. Implementations may read candidate state and return a
/// violation, but the interface has no effect builder, storage handle or
/// repair channel. A rejected candidate must be repaired by a later resolver
/// proposal, not by an invariant side effect.
pub trait Invariant {
    /// Validates candidate state without mutating it.
    ///
    /// # Errors
    ///
    /// Returns an `InvariantViolation` when candidate state is not valid under
    /// this Capability's rule.
    fn validate(&self, view: &dyn CandidateWorldView) -> Result<(), InvariantViolation>;
}

/// Work-handler SPI for one registered Durable Work semantic key.
///
/// A `WorkHandler` receives only a pinned `ResolutionContext` and serialized
/// payload. It returns the same untrusted `ResolveOutcome` as an Action
/// resolver. It cannot complete, cancel or otherwise change the current Work
/// lifecycle directly; Runtime owns that state transition and its atomicity
/// with any resulting commit.
pub trait WorkHandler {
    /// Resolves one Durable Work payload into an untrusted outcome.
    ///
    /// # Errors
    ///
    /// Returns a handler/host failure through the error channel. A semantic
    /// refusal must be returned as `Ok(ResolveOutcome::Rejected(_))`.
    fn handle(
        &self,
        context: &dyn ResolutionContext,
        payload: &Value,
    ) -> CapabilityResult<ResolveOutcome>;
}

/// Action resolver SPI for one registered semantic Action key.
///
/// An `ActionResolver` receives a read-only host context and untrusted Action
/// input. It can read the pinned World and request Runtime-mediated
/// subresolution, then returns an untrusted protocol outcome. It does not
/// receive a storage/commit handle and cannot make any returned Event or Effect
/// World Truth by itself.
pub trait ActionResolver {
    /// Resolves Action input into an untrusted outcome.
    ///
    /// # Errors
    ///
    /// Returns a resolver/host failure through the error channel. A normal
    /// world-rule refusal must be returned as `Ok(ResolveOutcome::Rejected(_))`.
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> CapabilityResult<ResolveOutcome>;
}

impl<T> ActionResolver for Box<T>
where
    T: ActionResolver + ?Sized,
{
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> CapabilityResult<ResolveOutcome> {
        (**self).resolve(context, input)
    }
}

impl<T> ActionResolver for Arc<T>
where
    T: ActionResolver + ?Sized,
{
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> CapabilityResult<ResolveOutcome> {
        (**self).resolve(context, input)
    }
}

impl<T> WorkHandler for Box<T>
where
    T: WorkHandler + ?Sized,
{
    fn handle(
        &self,
        context: &dyn ResolutionContext,
        payload: &Value,
    ) -> CapabilityResult<ResolveOutcome> {
        (**self).handle(context, payload)
    }
}

impl<T> WorkHandler for Arc<T>
where
    T: WorkHandler + ?Sized,
{
    fn handle(
        &self,
        context: &dyn ResolutionContext,
        payload: &Value,
    ) -> CapabilityResult<ResolveOutcome> {
        (**self).handle(context, payload)
    }
}

impl<T> Invariant for Box<T>
where
    T: Invariant + ?Sized,
{
    fn validate(&self, view: &dyn CandidateWorldView) -> Result<(), InvariantViolation> {
        (**self).validate(view)
    }
}

impl<T> Invariant for Arc<T>
where
    T: Invariant + ?Sized,
{
    fn validate(&self, view: &dyn CandidateWorldView) -> Result<(), InvariantViolation> {
        (**self).validate(view)
    }
}

/// Semantic category used in deterministic registration errors.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum SemanticKind {
    /// Capability manifest ownership category.
    Capability,
    /// Facet schema ownership category.
    Facet,
    /// Relationship schema ownership category.
    Relationship,
    /// Event schema ownership category.
    Event,
    /// Action resolver ownership category.
    Action,
    /// Durable Work handler ownership category.
    WorkHandler,
    /// Event-to-Work reaction registration category.
    Reaction,
}

impl fmt::Display for SemanticKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let name = match self {
            Self::Capability => "capability",
            Self::Facet => "facet",
            Self::Relationship => "relationship",
            Self::Event => "event",
            Self::Action => "action",
            Self::WorkHandler => "work_handler",
            Self::Reaction => "reaction",
        };
        formatter.write_str(name)
    }
}

/// Error raised while a Capability contributes registration nodes.
///
/// A registrar rejects duplicate semantic keys within one Capability before
/// the batch reaches the global registry. The error is metadata only; it does
/// not expose or mutate Runtime state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RegistrationError {
    /// The Capability attempted to register the same semantic key twice.
    DuplicateLocal {
        /// Semantic category that was duplicated.
        kind: SemanticKind,
        /// Stable key repeated by the registration batch.
        id: String,
    },
    /// A definition's metadata is structurally invalid for registration.
    InvalidDefinition {
        /// Semantic category with invalid metadata.
        kind: SemanticKind,
        /// Stable key of the invalid definition.
        id: String,
        /// Boundary-safe reason for rejection.
        reason: String,
    },
}

impl fmt::Display for RegistrationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateLocal { kind, id } => {
                write!(formatter, "duplicate {kind} registration: {id}")
            }
            Self::InvalidDefinition { kind, id, reason } => {
                write!(formatter, "invalid {kind} definition {id}: {reason}")
            }
        }
    }
}

impl Error for RegistrationError {}

/// Error raised while assembling or validating a Capability registry.
///
/// Registration errors are deterministic and identify the semantic category,
/// key and owners involved. Dependency errors are deferred until `validate`, so
/// a provider may be registered after a consumer while a template is assembled;
/// callers must validate before handing the registry to Runtime.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RegistryError {
    /// A Capability metadata ID was registered more than once.
    DuplicateCapability {
        /// Repeated Capability metadata identity.
        id: CapabilityId,
    },
    /// A semantic type already has another owning Capability.
    DuplicateSemantic {
        /// Category of the contested semantic key.
        kind: SemanticKind,
        /// Contested semantic key.
        id: String,
        /// Capability that registered the key first.
        existing_owner: CapabilityId,
        /// Capability rejected for claiming the key a second time.
        attempted_owner: CapabilityId,
    },
    /// One Capability declared a provider that is not registered.
    MissingDependency {
        /// Capability declaring the dependency.
        capability: CapabilityId,
        /// Missing provider identity.
        dependency: CapabilityId,
    },
    /// A dependency provider exists but does not satisfy its required range.
    IncompatibleDependency {
        /// Capability declaring the dependency.
        capability: CapabilityId,
        /// Provider identity.
        dependency: CapabilityId,
        /// Range declared by the consumer.
        required: VersionReq,
        /// Provider version found during assembly.
        found: Version,
    },
    /// A Capability cannot run against the registry's Loom contract version.
    IncompatibleLoomVersion {
        /// Capability whose manifest is incompatible.
        capability: CapabilityId,
        /// Range declared by the Capability.
        required: VersionReq,
        /// Loom contract version configured for this registry.
        found: Version,
    },
    /// A dependency ID was repeated in one manifest.
    DuplicateDependency {
        /// Capability containing the repeated declaration.
        capability: CapabilityId,
        /// Repeated provider identity.
        dependency: CapabilityId,
    },
    /// A Capability declared itself as a dependency.
    SelfDependency {
        /// Capability containing the invalid self-edge.
        capability: CapabilityId,
    },
    /// A reaction references an Event semantic type that is not registered.
    UnknownReactionEvent {
        /// Event semantic type used by the invalid reaction.
        event_type: EventTypeId,
    },
    /// A reaction references a Work handler that is not registered.
    UnknownReactionHandler {
        /// Work handler semantic type used by the invalid reaction.
        handler: WorkHandlerId,
    },
    /// Capability dependency edges contain a cycle.
    DependencyCycle {
        /// Deterministic cycle path in declaration/identifier order.
        cycle: Vec<CapabilityId>,
    },
    /// A Capability returned an invalid registration batch.
    Registration {
        /// Capability whose registration failed.
        capability: CapabilityId,
        /// Registrar-level failure.
        source: RegistrationError,
    },
}

impl fmt::Display for RegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateCapability { id } => write!(formatter, "duplicate capability: {id}"),
            Self::DuplicateSemantic {
                kind,
                id,
                existing_owner,
                attempted_owner,
            } => write!(
                formatter,
                "duplicate {kind} {id}: owned by {existing_owner}, attempted by {attempted_owner}"
            ),
            Self::MissingDependency {
                capability,
                dependency,
            } => write!(
                formatter,
                "capability {capability} requires missing dependency {dependency}"
            ),
            Self::IncompatibleDependency {
                capability,
                dependency,
                required,
                found,
            } => write!(
                formatter,
                "capability {capability} requires {dependency} {required}, found {found}"
            ),
            Self::IncompatibleLoomVersion {
                capability,
                required,
                found,
            } => write!(
                formatter,
                "capability {capability} requires Loom {required}, found {found}"
            ),
            Self::DuplicateDependency {
                capability,
                dependency,
            } => write!(
                formatter,
                "capability {capability} declares dependency {dependency} more than once"
            ),
            Self::SelfDependency { capability } => {
                write!(formatter, "capability {capability} depends on itself")
            }
            Self::UnknownReactionEvent { event_type } => {
                write!(
                    formatter,
                    "reaction references unknown event type {event_type}"
                )
            }
            Self::UnknownReactionHandler { handler } => {
                write!(
                    formatter,
                    "reaction references unknown work handler {handler}"
                )
            }
            Self::DependencyCycle { cycle } => {
                write!(formatter, "capability dependency cycle: ")?;
                for (index, id) in cycle.iter().enumerate() {
                    if index > 0 {
                        formatter.write_str(" -> ")?;
                    }
                    formatter.write_str(id.as_str())?;
                }
                Ok(())
            }
            Self::Registration { capability, source } => write!(
                formatter,
                "capability {capability} registration failed: {source}"
            ),
        }
    }
}

impl Error for RegistryError {}

/// A Capability registration entrypoint.
///
/// Implementations expose only semantic definitions and resolver/handler
/// behavior. The registry invokes `register` with a registrar owned by the
/// manifest's Capability ID, so every accepted node receives an unambiguous
/// owner. This trait has no transport, storage, clock, randomness or commit
/// surface.
pub trait Capability {
    /// Returns immutable software metadata for this Capability.
    fn manifest(&self) -> &CapabilityManifest;

    /// Adds this Capability's semantic registration nodes to the registrar.
    ///
    /// # Errors
    ///
    /// Returns a registration error when this Capability contributes duplicate
    /// or structurally invalid semantic metadata.
    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError>;
}

impl<T> Capability for Box<T>
where
    T: Capability + ?Sized,
{
    fn manifest(&self) -> &CapabilityManifest {
        (**self).manifest()
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        (**self).register(registrar)
    }
}

/// Declarative registration builder scoped to one owning Capability.
///
/// `CapabilityRegistrar` accepts semantic definitions and small SPI objects,
/// assigning ownership from its private `owner` value. It stores no Runtime or
/// persistence handle. A batch is committed to the global registry only after
/// all local and global duplicate checks pass.
pub struct CapabilityRegistrar {
    owner: CapabilityId,
    facets: Vec<FacetDefinition>,
    relationships: Vec<RelationshipDefinition>,
    events: Vec<EventDefinition>,
    actions: Vec<(ActionDefinition, Arc<dyn ActionResolver>)>,
    work_handlers: Vec<(WorkHandlerDefinition, Arc<dyn WorkHandler>)>,
    invariants: Vec<Arc<dyn Invariant>>,
    reactions: Vec<Reaction>,
    first_error: Option<RegistrationError>,
}

impl CapabilityRegistrar {
    /// Creates an empty registrar owned by `owner`.
    #[must_use]
    pub fn new(owner: CapabilityId) -> Self {
        Self {
            owner,
            facets: Vec::new(),
            relationships: Vec::new(),
            events: Vec::new(),
            actions: Vec::new(),
            work_handlers: Vec::new(),
            invariants: Vec::new(),
            reactions: Vec::new(),
            first_error: None,
        }
    }

    /// Returns the Capability that owns all nodes in this batch.
    #[must_use]
    pub fn owner(&self) -> &CapabilityId {
        &self.owner
    }

    /// Registers one Facet definition for this Capability.
    ///
    /// # Errors
    ///
    /// Returns a local duplicate/metadata error when this key is already in
    /// the current batch.
    pub fn register_facet(&mut self, definition: FacetDefinition) -> Result<(), RegistrationError> {
        if self.facets.iter().any(|item| item.id == definition.id) {
            return self.record_error(RegistrationError::DuplicateLocal {
                kind: SemanticKind::Facet,
                id: definition.id.to_string(),
            });
        }
        if let Some(error) = invalid_schema_registration(
            SemanticKind::Facet,
            definition.id.to_string(),
            &definition.schema,
        ) {
            return self.record_error(error);
        }
        self.facets.push(definition);
        Ok(())
    }

    /// Registers one Relationship definition for this Capability.
    ///
    /// # Errors
    ///
    /// Returns a local duplicate/metadata error when this key is already in
    /// the current batch or its cardinality metadata is invalid.
    pub fn register_relationship(
        &mut self,
        definition: RelationshipDefinition,
    ) -> Result<(), RegistrationError> {
        if self
            .relationships
            .iter()
            .any(|item| item.id == definition.id)
        {
            return self.record_error(RegistrationError::DuplicateLocal {
                kind: SemanticKind::Relationship,
                id: definition.id.to_string(),
            });
        }
        if let Some(reason) = invalid_relationship_reason(&definition) {
            return self.record_error(RegistrationError::InvalidDefinition {
                kind: SemanticKind::Relationship,
                id: definition.id.to_string(),
                reason,
            });
        }
        self.relationships.push(definition);
        Ok(())
    }

    /// Registers one Event definition for this Capability.
    ///
    /// # Errors
    ///
    /// Returns a local duplicate error when this key is already in the current
    /// batch.
    pub fn register_event(&mut self, definition: EventDefinition) -> Result<(), RegistrationError> {
        if self.events.iter().any(|item| item.id == definition.id) {
            return self.record_error(RegistrationError::DuplicateLocal {
                kind: SemanticKind::Event,
                id: definition.id.to_string(),
            });
        }
        if let Some(schema) = definition.payload_schema.as_ref()
            && let Some(error) =
                invalid_schema_registration(SemanticKind::Event, definition.id.to_string(), schema)
        {
            return self.record_error(error);
        }
        self.events.push(definition);
        Ok(())
    }

    /// Registers an Action definition and its resolver implementation.
    ///
    /// # Errors
    ///
    /// Returns a local duplicate error when this Action key is already in the
    /// current batch.
    pub fn register_action<R>(
        &mut self,
        definition: ActionDefinition,
        resolver: R,
    ) -> Result<(), RegistrationError>
    where
        R: ActionResolver + 'static,
    {
        if self
            .actions
            .iter()
            .any(|(item, _)| item.id == definition.id)
        {
            return self.record_error(RegistrationError::DuplicateLocal {
                kind: SemanticKind::Action,
                id: definition.id.to_string(),
            });
        }
        if let Some(schema) = definition.input_schema.as_ref()
            && let Some(error) =
                invalid_schema_registration(SemanticKind::Action, definition.id.to_string(), schema)
        {
            return self.record_error(error);
        }
        self.actions.push((definition, Arc::new(resolver)));
        Ok(())
    }

    /// Registers a Work handler definition and its handler implementation.
    ///
    /// # Errors
    ///
    /// Returns a local duplicate error when this handler key is already in the
    /// current batch.
    pub fn register_work_handler<H>(
        &mut self,
        definition: WorkHandlerDefinition,
        handler: H,
    ) -> Result<(), RegistrationError>
    where
        H: WorkHandler + 'static,
    {
        if self
            .work_handlers
            .iter()
            .any(|(item, _)| item.id == definition.id)
        {
            return self.record_error(RegistrationError::DuplicateLocal {
                kind: SemanticKind::WorkHandler,
                id: definition.id.to_string(),
            });
        }
        if let Some(schema) = definition.payload_schema.as_ref()
            && let Some(error) = invalid_schema_registration(
                SemanticKind::WorkHandler,
                definition.id.to_string(),
                schema,
            )
        {
            return self.record_error(error);
        }
        self.work_handlers.push((definition, Arc::new(handler)));
        Ok(())
    }

    /// Registers one read-only invariant for this Capability.
    ///
    /// Invariants are intentionally not keyed by a second semantic type: their
    /// ownership is the surrounding Capability, and Runtime invokes all
    /// registered rules during candidate validation.
    pub fn register_invariant<I>(&mut self, invariant: I)
    where
        I: Invariant + 'static,
    {
        self.invariants.push(Arc::new(invariant));
    }

    /// Registers an Event-to-immediate-Work reaction.
    ///
    /// # Errors
    ///
    /// Returns a local duplicate error when the same Event/handler mapping is
    /// already in the current batch.
    pub fn register_reaction(&mut self, reaction: Reaction) -> Result<(), RegistrationError> {
        if self.reactions.iter().any(|item| item == &reaction) {
            return self.record_error(RegistrationError::DuplicateLocal {
                kind: SemanticKind::Reaction,
                id: format!("{} -> {}", reaction.event_type, reaction.handler),
            });
        }
        self.reactions.push(reaction);
        Ok(())
    }

    fn record_error<T>(&mut self, error: RegistrationError) -> Result<T, RegistrationError> {
        if self.first_error.is_none() {
            self.first_error = Some(error.clone());
        }
        Err(error)
    }

    fn finish(self) -> Result<RegistrationBatch, RegistrationError> {
        if let Some(error) = self.first_error {
            return Err(error);
        }
        Ok(RegistrationBatch {
            owner: self.owner,
            facets: self.facets,
            relationships: self.relationships,
            events: self.events,
            actions: self.actions,
            work_handlers: self.work_handlers,
            invariants: self.invariants,
            reactions: self.reactions,
        })
    }
}

fn invalid_relationship_reason(definition: &RelationshipDefinition) -> Option<String> {
    let mut roles = BTreeSet::new();
    for role in &definition.roles {
        if role.maximum.is_some_and(|maximum| maximum < role.minimum) {
            return Some(format!("role {} has maximum below minimum", role.role));
        }
        if !roles.insert(role.role.clone()) {
            return Some(format!("role {} is declared more than once", role.role));
        }
    }
    None
}

fn invalid_schema_registration(
    kind: SemanticKind,
    id: String,
    schema: &Value,
) -> Option<RegistrationError> {
    validate_json_schema_document(schema)
        .err()
        .map(|reason| RegistrationError::InvalidDefinition { kind, id, reason })
}

struct RegistrationBatch {
    owner: CapabilityId,
    facets: Vec<FacetDefinition>,
    relationships: Vec<RelationshipDefinition>,
    events: Vec<EventDefinition>,
    actions: Vec<(ActionDefinition, Arc<dyn ActionResolver>)>,
    work_handlers: Vec<(WorkHandlerDefinition, Arc<dyn WorkHandler>)>,
    invariants: Vec<Arc<dyn Invariant>>,
    reactions: Vec<Reaction>,
}

/// A Facet definition together with its unique owning Capability.
///
/// The owner is assigned by `CapabilityRegistrar`, not trusted from the
/// definition value. This wrapper is registry metadata; it is not a Facet
/// instance or a write capability.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RegisteredFacet {
    /// Capability that owns and interprets this Facet schema.
    pub owner: CapabilityId,
    /// Registered Facet schema metadata.
    pub definition: FacetDefinition,
}

/// A Relationship definition together with its unique owner.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RegisteredRelationship {
    /// Capability that owns this Relationship semantic type.
    pub owner: CapabilityId,
    /// Registered Relationship schema metadata.
    pub definition: RelationshipDefinition,
}

/// An Event definition together with its unique owner.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RegisteredEvent {
    /// Capability that owns this Event semantic type.
    pub owner: CapabilityId,
    /// Registered Event schema metadata.
    pub definition: EventDefinition,
}

/// An Action definition and resolver together with its unique owner.
///
/// The resolver is exposed only as an execution SPI. It cannot access Registry
/// storage or create a Runtime authority value through this wrapper.
pub struct RegisteredAction {
    /// Capability that owns and interprets this Action.
    pub owner: CapabilityId,
    /// Registered Action discovery/schema metadata.
    pub definition: ActionDefinition,
    resolver: Arc<dyn ActionResolver>,
}

impl RegisteredAction {
    /// Resolves input through the registered Action SPI.
    ///
    /// # Errors
    ///
    /// Propagates the resolver's implementation/host error. A semantic refusal
    /// remains an `Ok(ResolveOutcome::Rejected(_))` value.
    pub fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> CapabilityResult<ResolveOutcome> {
        self.resolver.resolve(context, input)
    }

    /// Borrows the registered resolver for Runtime dispatch.
    #[must_use]
    pub fn resolver(&self) -> &dyn ActionResolver {
        self.resolver.as_ref()
    }
}

/// A Work handler definition and implementation together with its owner.
pub struct RegisteredWorkHandler {
    /// Capability that owns and interprets this Work semantic type.
    pub owner: CapabilityId,
    /// Registered Work handler discovery/schema metadata.
    pub definition: WorkHandlerDefinition,
    handler: Arc<dyn WorkHandler>,
}

impl RegisteredWorkHandler {
    /// Resolves a Work payload through the registered handler SPI.
    ///
    /// # Errors
    ///
    /// Propagates the handler's implementation/host error. The handler cannot
    /// directly complete or cancel its current Work.
    pub fn handle(
        &self,
        context: &dyn ResolutionContext,
        payload: &Value,
    ) -> CapabilityResult<ResolveOutcome> {
        self.handler.handle(context, payload)
    }

    /// Borrows the registered Work handler for Runtime dispatch.
    #[must_use]
    pub fn handler(&self) -> &dyn WorkHandler {
        self.handler.as_ref()
    }
}

/// A read-only invariant together with its owner.
pub struct RegisteredInvariant {
    /// Capability that owns this validation rule.
    pub owner: CapabilityId,
    invariant: Arc<dyn Invariant>,
}

impl RegisteredInvariant {
    /// Validates a candidate view through the registered invariant.
    ///
    /// # Errors
    ///
    /// Returns the semantic violation reported by the invariant.
    pub fn validate(&self, view: &dyn CandidateWorldView) -> Result<(), InvariantViolation> {
        self.invariant.validate(view)
    }
}

/// A registered Event-to-Work reaction together with its owner.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RegisteredReaction {
    /// Capability that owns this reaction behavior.
    pub owner: CapabilityId,
    /// Declarative Event-to-immediate-Work mapping.
    pub reaction: Reaction,
}

/// Central semantic registry for assembled Capabilities.
///
/// The registry is the single ownership index for Facet, Relationship, Event,
/// Action and Work handler semantic IDs. Registration rejects duplicate owners
/// deterministically. Dependency and Loom-version checks are intentionally
/// performed by `validate` after all template Capabilities have been added,
/// allowing declarations to refer to providers registered later in assembly.
/// The registry contains no transport routes, database handles or autonomous
/// execution loop.
pub struct CapabilityRegistry {
    loom_version: Version,
    capabilities: BTreeMap<CapabilityId, CapabilityManifest>,
    facets: BTreeMap<FacetTypeId, RegisteredFacet>,
    relationships: BTreeMap<RelationshipTypeId, RegisteredRelationship>,
    events: BTreeMap<EventTypeId, RegisteredEvent>,
    actions: BTreeMap<ActionTypeId, RegisteredAction>,
    work_handlers: BTreeMap<WorkHandlerId, RegisteredWorkHandler>,
    invariants: Vec<RegisteredInvariant>,
    reactions: Vec<RegisteredReaction>,
}

impl Default for CapabilityRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl CapabilityRegistry {
    /// Creates an empty registry targeting the workspace's v0 Loom contract.
    #[must_use]
    pub fn new() -> Self {
        Self::with_loom_version(Version::new(0, 1, 0))
    }

    /// Creates an empty registry for an explicit Loom contract version.
    #[must_use]
    pub fn with_loom_version(loom_version: Version) -> Self {
        Self {
            loom_version,
            capabilities: BTreeMap::new(),
            facets: BTreeMap::new(),
            relationships: BTreeMap::new(),
            events: BTreeMap::new(),
            actions: BTreeMap::new(),
            work_handlers: BTreeMap::new(),
            invariants: Vec::new(),
            reactions: Vec::new(),
        }
    }

    /// Assembles and validates a registry from owned Capability values.
    ///
    /// # Errors
    ///
    /// Returns duplicate registration, dependency, version or cycle errors.
    /// No partially assembled registry is returned on failure.
    pub fn assemble<I, C>(capabilities: I) -> Result<Self, RegistryError>
    where
        I: IntoIterator<Item = C>,
        C: Capability,
    {
        let mut registry = Self::new();
        for capability in capabilities {
            registry.register(&capability)?;
        }
        registry.validate()?;
        Ok(registry)
    }

    /// Assembles and validates a registry against an explicit Loom version.
    ///
    /// # Errors
    ///
    /// Returns duplicate registration, dependency, version or cycle errors.
    /// No partially assembled registry is returned on failure.
    pub fn assemble_for_loom_version<I, C>(
        loom_version: Version,
        capabilities: I,
    ) -> Result<Self, RegistryError>
    where
        I: IntoIterator<Item = C>,
        C: Capability,
    {
        let mut registry = Self::with_loom_version(loom_version);
        for capability in capabilities {
            registry.register(&capability)?;
        }
        registry.validate()?;
        Ok(registry)
    }

    /// Returns the Loom contract version against which manifests are checked.
    #[must_use]
    pub const fn loom_version(&self) -> &Version {
        &self.loom_version
    }

    /// Registers one Capability's manifest and semantic nodes.
    ///
    /// Dependency validation is deferred until `validate` so registration order
    /// does not change whether a complete template is accepted. Duplicate
    /// Capability and semantic ownership errors are rejected before the batch
    /// changes this registry.
    ///
    /// # Errors
    ///
    /// Returns a deterministic duplicate or Capability registration error.
    pub fn register(&mut self, capability: &dyn Capability) -> Result<(), RegistryError> {
        let manifest = capability.manifest().clone();
        if self.capabilities.contains_key(&manifest.id) {
            return Err(RegistryError::DuplicateCapability { id: manifest.id });
        }

        let mut registrar = CapabilityRegistrar::new(manifest.id.clone());
        capability
            .register(&mut registrar)
            .map_err(|source| RegistryError::Registration {
                capability: manifest.id.clone(),
                source,
            })?;
        let batch = registrar
            .finish()
            .map_err(|source| RegistryError::Registration {
                capability: manifest.id.clone(),
                source,
            })?;
        self.check_batch(&batch)?;
        self.insert_batch(manifest, batch);
        Ok(())
    }

    /// Alias for `register` emphasizing that this is Capability assembly.
    ///
    /// # Errors
    ///
    /// Propagates the deterministic errors returned by `register`.
    pub fn register_capability(
        &mut self,
        capability: &dyn Capability,
    ) -> Result<(), RegistryError> {
        self.register(capability)
    }

    /// Validates all declared Loom and Capability dependency metadata.
    ///
    /// This is the registry/template assembly gate. It must pass before Runtime
    /// is allowed to use the registry for semantic dispatch.
    ///
    /// # Errors
    ///
    /// Returns missing, duplicate, incompatible, self-referential or cyclic
    /// dependency errors.
    pub fn validate(&self) -> Result<(), RegistryError> {
        for manifest in self.capabilities.values() {
            if !manifest.loom_compatibility.matches(&self.loom_version) {
                return Err(RegistryError::IncompatibleLoomVersion {
                    capability: manifest.id.clone(),
                    required: manifest.loom_compatibility.clone(),
                    found: self.loom_version.clone(),
                });
            }

            let mut dependencies = BTreeSet::new();
            for dependency in &manifest.dependencies {
                if !dependencies.insert(dependency.id.clone()) {
                    return Err(RegistryError::DuplicateDependency {
                        capability: manifest.id.clone(),
                        dependency: dependency.id.clone(),
                    });
                }
                if dependency.id == manifest.id {
                    return Err(RegistryError::SelfDependency {
                        capability: manifest.id.clone(),
                    });
                }
                let Some(provider) = self.capabilities.get(&dependency.id) else {
                    return Err(RegistryError::MissingDependency {
                        capability: manifest.id.clone(),
                        dependency: dependency.id.clone(),
                    });
                };
                if !dependency.version.matches(&provider.version) {
                    return Err(RegistryError::IncompatibleDependency {
                        capability: manifest.id.clone(),
                        dependency: dependency.id.clone(),
                        required: dependency.version.clone(),
                        found: provider.version.clone(),
                    });
                }
            }
        }

        for registered in &self.reactions {
            if !self.events.contains_key(&registered.reaction.event_type) {
                return Err(RegistryError::UnknownReactionEvent {
                    event_type: registered.reaction.event_type.clone(),
                });
            }
            if !self
                .work_handlers
                .contains_key(&registered.reaction.handler)
            {
                return Err(RegistryError::UnknownReactionHandler {
                    handler: registered.reaction.handler.clone(),
                });
            }
        }

        self.validate_dependency_cycles()
    }

    /// Returns a registered Capability manifest by metadata ID.
    #[must_use]
    pub fn capability(&self, id: &CapabilityId) -> Option<&CapabilityManifest> {
        self.capabilities.get(id)
    }

    /// Iterates registered Capability manifests in deterministic key order.
    pub fn capabilities(&self) -> impl Iterator<Item = &CapabilityManifest> {
        self.capabilities.values()
    }

    /// Returns a registered Facet definition and its owning Capability.
    #[must_use]
    pub fn facet(&self, id: &FacetTypeId) -> Option<&RegisteredFacet> {
        self.facets.get(id)
    }

    /// Iterates registered Facet definitions in deterministic key order.
    pub fn facets(&self) -> impl Iterator<Item = &RegisteredFacet> {
        self.facets.values()
    }

    /// Returns a registered Relationship definition and its owner.
    #[must_use]
    pub fn relationship(&self, id: &RelationshipTypeId) -> Option<&RegisteredRelationship> {
        self.relationships.get(id)
    }

    /// Iterates registered Relationship definitions in deterministic key order.
    pub fn relationships(&self) -> impl Iterator<Item = &RegisteredRelationship> {
        self.relationships.values()
    }

    /// Returns a registered Event definition and its owner.
    #[must_use]
    pub fn event(&self, id: &EventTypeId) -> Option<&RegisteredEvent> {
        self.events.get(id)
    }

    /// Iterates registered Event definitions in deterministic key order.
    pub fn events(&self) -> impl Iterator<Item = &RegisteredEvent> {
        self.events.values()
    }

    /// Returns a registered Action resolver and its owner.
    #[must_use]
    pub fn action(&self, id: &ActionTypeId) -> Option<&RegisteredAction> {
        self.actions.get(id)
    }

    /// Iterates registered Action definitions in deterministic key order.
    pub fn actions(&self) -> impl Iterator<Item = &RegisteredAction> {
        self.actions.values()
    }

    /// Returns a registered Work handler and its owner.
    #[must_use]
    pub fn work_handler(&self, id: &WorkHandlerId) -> Option<&RegisteredWorkHandler> {
        self.work_handlers.get(id)
    }

    /// Iterates registered Work handler definitions in deterministic key order.
    pub fn work_handlers(&self) -> impl Iterator<Item = &RegisteredWorkHandler> {
        self.work_handlers.values()
    }

    /// Iterates registered read-only invariants in Capability registration order.
    pub fn invariants(&self) -> impl Iterator<Item = &RegisteredInvariant> {
        self.invariants.iter()
    }

    /// Iterates registered Event reactions in deterministic Capability assembly
    /// order.
    pub fn reactions(&self) -> impl Iterator<Item = &RegisteredReaction> {
        self.reactions.iter()
    }

    /// Dispatches one Action through its registered resolver.
    ///
    /// # Errors
    ///
    /// Returns `UnknownAction` when no owner is registered, or propagates the
    /// resolver's implementation/host error. A semantic rejection remains an
    /// `Ok(ResolveOutcome::Rejected(_))` value.
    pub fn resolve_action(
        &self,
        id: &ActionTypeId,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, DispatchError> {
        let Some(action) = self.action(id) else {
            return Err(DispatchError::UnknownAction(id.clone()));
        };
        action
            .resolve(context, input)
            .map_err(DispatchError::Resolver)
    }

    /// Dispatches one Durable Work payload through its registered handler.
    ///
    /// # Errors
    ///
    /// Returns `UnknownWorkHandler` when no owner is registered, or propagates
    /// the handler's implementation/host error.
    pub fn handle_work(
        &self,
        id: &WorkHandlerId,
        context: &dyn ResolutionContext,
        payload: &Value,
    ) -> Result<ResolveOutcome, DispatchError> {
        let Some(handler) = self.work_handler(id) else {
            return Err(DispatchError::UnknownWorkHandler(id.clone()));
        };
        handler
            .handle(context, payload)
            .map_err(DispatchError::Handler)
    }

    fn check_batch(&self, batch: &RegistrationBatch) -> Result<(), RegistryError> {
        for definition in &batch.facets {
            if let Some(existing) = self.facets.get(&definition.id) {
                return Err(RegistryError::DuplicateSemantic {
                    kind: SemanticKind::Facet,
                    id: definition.id.to_string(),
                    existing_owner: existing.owner.clone(),
                    attempted_owner: batch.owner.clone(),
                });
            }
        }
        for definition in &batch.relationships {
            if let Some(existing) = self.relationships.get(&definition.id) {
                return Err(RegistryError::DuplicateSemantic {
                    kind: SemanticKind::Relationship,
                    id: definition.id.to_string(),
                    existing_owner: existing.owner.clone(),
                    attempted_owner: batch.owner.clone(),
                });
            }
        }
        for definition in &batch.events {
            if let Some(existing) = self.events.get(&definition.id) {
                return Err(RegistryError::DuplicateSemantic {
                    kind: SemanticKind::Event,
                    id: definition.id.to_string(),
                    existing_owner: existing.owner.clone(),
                    attempted_owner: batch.owner.clone(),
                });
            }
        }
        for (definition, _) in &batch.actions {
            if let Some(existing) = self.actions.get(&definition.id) {
                return Err(RegistryError::DuplicateSemantic {
                    kind: SemanticKind::Action,
                    id: definition.id.to_string(),
                    existing_owner: existing.owner.clone(),
                    attempted_owner: batch.owner.clone(),
                });
            }
        }
        for (definition, _) in &batch.work_handlers {
            if let Some(existing) = self.work_handlers.get(&definition.id) {
                return Err(RegistryError::DuplicateSemantic {
                    kind: SemanticKind::WorkHandler,
                    id: definition.id.to_string(),
                    existing_owner: existing.owner.clone(),
                    attempted_owner: batch.owner.clone(),
                });
            }
        }
        for reaction in &batch.reactions {
            if self
                .reactions
                .iter()
                .any(|registered| registered.reaction == *reaction)
            {
                return Err(RegistryError::DuplicateSemantic {
                    kind: SemanticKind::Reaction,
                    id: format!("{} -> {}", reaction.event_type, reaction.handler),
                    existing_owner: self
                        .reactions
                        .iter()
                        .find(|registered| registered.reaction == *reaction)
                        .map_or_else(
                            || batch.owner.clone(),
                            |registered| registered.owner.clone(),
                        ),
                    attempted_owner: batch.owner.clone(),
                });
            }
        }
        Ok(())
    }

    fn insert_batch(&mut self, manifest: CapabilityManifest, batch: RegistrationBatch) {
        let owner = batch.owner;
        self.capabilities.insert(manifest.id.clone(), manifest);

        for definition in batch.facets {
            self.facets.insert(
                definition.id.clone(),
                RegisteredFacet {
                    owner: owner.clone(),
                    definition,
                },
            );
        }
        for definition in batch.relationships {
            self.relationships.insert(
                definition.id.clone(),
                RegisteredRelationship {
                    owner: owner.clone(),
                    definition,
                },
            );
        }
        for definition in batch.events {
            self.events.insert(
                definition.id.clone(),
                RegisteredEvent {
                    owner: owner.clone(),
                    definition,
                },
            );
        }
        for (definition, resolver) in batch.actions {
            self.actions.insert(
                definition.id.clone(),
                RegisteredAction {
                    owner: owner.clone(),
                    definition,
                    resolver,
                },
            );
        }
        for (definition, handler) in batch.work_handlers {
            self.work_handlers.insert(
                definition.id.clone(),
                RegisteredWorkHandler {
                    owner: owner.clone(),
                    definition,
                    handler,
                },
            );
        }
        self.invariants.extend(
            batch
                .invariants
                .into_iter()
                .map(|invariant| RegisteredInvariant {
                    owner: owner.clone(),
                    invariant,
                }),
        );
        self.reactions.extend(
            batch
                .reactions
                .into_iter()
                .map(|reaction| RegisteredReaction {
                    owner: owner.clone(),
                    reaction,
                }),
        );
    }

    fn validate_dependency_cycles(&self) -> Result<(), RegistryError> {
        let mut states = BTreeMap::new();
        let mut path = Vec::new();
        for id in self.capabilities.keys() {
            if !states.contains_key(id) {
                self.visit_dependency(id, &mut states, &mut path)?;
            }
        }
        Ok(())
    }

    fn visit_dependency(
        &self,
        id: &CapabilityId,
        states: &mut BTreeMap<CapabilityId, VisitState>,
        path: &mut Vec<CapabilityId>,
    ) -> Result<(), RegistryError> {
        match states.get(id) {
            Some(VisitState::Done) => return Ok(()),
            Some(VisitState::Visiting) => {
                let start = path.iter().position(|item| item == id).unwrap_or(0);
                let mut cycle = path[start..].to_vec();
                cycle.push(id.clone());
                return Err(RegistryError::DependencyCycle { cycle });
            }
            None => {}
        }

        states.insert(id.clone(), VisitState::Visiting);
        path.push(id.clone());
        if let Some(manifest) = self.capabilities.get(id) {
            for dependency in &manifest.dependencies {
                self.visit_dependency(&dependency.id, states, path)?;
            }
        }
        path.pop();
        states.insert(id.clone(), VisitState::Done);
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum VisitState {
    Visiting,
    Done,
}

/// Error returned when registry dispatch cannot route an Action or Work item.
///
/// Unknown semantic IDs are registry assembly/lookup failures. Resolver and
/// handler failures stay on their explicit error channel; neither variant is a
/// Capability-owned semantic rejection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DispatchError {
    /// No registered Action owns this semantic key.
    UnknownAction(ActionTypeId),
    /// A registered Action is not available in the target World's Runtime
    /// Binding. The Runtime supplies the World-level enablement decision.
    UnavailableAction(ActionTypeId),
    /// The registered Action resolver failed while executing.
    Resolver(ResolverError),
    /// No registered Work handler owns this semantic key.
    UnknownWorkHandler(WorkHandlerId),
    /// The registered Work handler failed while executing.
    Handler(ResolverError),
}

impl fmt::Display for DispatchError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownAction(id) => write!(formatter, "unknown action: {id}"),
            Self::UnavailableAction(id) => write!(formatter, "action is unavailable: {id}"),
            Self::Resolver(error) => write!(formatter, "action resolver failed: {error}"),
            Self::UnknownWorkHandler(id) => write!(formatter, "unknown work handler: {id}"),
            Self::Handler(error) => write!(formatter, "work handler failed: {error}"),
        }
    }
}

impl Error for DispatchError {}

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use loom_core::{
        ActionTypeId, EntityId, EventId, EventTypeId, FacetOwner, FacetTypeId, SchemaRevision,
        TimelineId, TimelineVersion, WorkHandlerId,
    };
    use loom_protocol::{ProposedEvent, Resolution, WorkSchedule};
    use semver::{Version, VersionReq};
    use serde_json::json;

    use super::{
        ActionDefinition, ActionResolver, BaseWorldView, CandidateWorldView, Capability,
        CapabilityDependency, CapabilityManifest, CapabilityRegistrar, CapabilityRegistry,
        DispatchError, EventDefinition, FacetDefinition, FacetValue, Invariant, InvariantViolation,
        Reaction, RegisteredFacet, RelationshipDefinition, RelationshipRole, ResolutionContext,
        ResolutionContextError, ResolveOutcome, ResolverError, WorkHandler, WorkHandlerDefinition,
    };

    fn manifest(id: &str, version: &str) -> CapabilityManifest {
        CapabilityManifest::parse(id, version).expect("test version should parse")
    }

    struct EmptyCapability {
        manifest: CapabilityManifest,
    }

    impl Capability for EmptyCapability {
        fn manifest(&self) -> &CapabilityManifest {
            &self.manifest
        }

        fn register(
            &self,
            _registrar: &mut CapabilityRegistrar,
        ) -> Result<(), super::RegistrationError> {
            Ok(())
        }
    }

    struct MalformedSchemaCapability {
        manifest: CapabilityManifest,
    }

    impl Capability for MalformedSchemaCapability {
        fn manifest(&self) -> &CapabilityManifest {
            &self.manifest
        }

        fn register(
            &self,
            registrar: &mut CapabilityRegistrar,
        ) -> Result<(), super::RegistrationError> {
            registrar.register_facet(FacetDefinition::new(
                FacetTypeId::from("invalid.facet"),
                SchemaRevision::new(1),
                json!({"type": "not-a-json-schema-type"}),
            ))
        }
    }

    struct EchoResolver;

    impl ActionResolver for EchoResolver {
        fn resolve(
            &self,
            _context: &dyn ResolutionContext,
            input: &serde_json::Value,
        ) -> Result<ResolveOutcome, ResolverError> {
            if input == &json!({"reject": true}) {
                return Ok(ResolveOutcome::Rejected(loom_protocol::Rejection::new(
                    "test.rejected",
                    "test rejection",
                )));
            }
            Ok(ResolveOutcome::Resolved(Resolution::new(
                vec![ProposedEvent::new(
                    EventId::from_str("00000000-0000-0000-0000-000000000001").expect("test id"),
                    EventTypeId::from("test.event"),
                    SchemaRevision::new(1),
                    input.clone(),
                )],
                Vec::new(),
            )))
        }
    }

    struct EmptyWorkHandler;

    impl WorkHandler for EmptyWorkHandler {
        fn handle(
            &self,
            _context: &dyn ResolutionContext,
            _payload: &serde_json::Value,
        ) -> Result<ResolveOutcome, ResolverError> {
            Ok(ResolveOutcome::Resolved(Resolution::default()))
        }
    }

    struct ReadOnlyInvariant;

    impl Invariant for ReadOnlyInvariant {
        fn validate(&self, view: &dyn CandidateWorldView) -> Result<(), InvariantViolation> {
            let _ = view.world_time();
            Ok(())
        }
    }

    struct View;

    impl BaseWorldView for View {
        fn timeline_id(&self) -> TimelineId {
            TimelineId::from_str("00000000-0000-0000-0000-000000000002").expect("test id")
        }

        fn version(&self) -> TimelineVersion {
            TimelineVersion::new(0.into(), 0.into())
        }

        fn world_time(&self) -> loom_core::WorldInstant {
            0.into()
        }

        fn get_entity(
            &self,
            _entity_id: EntityId,
        ) -> Result<Option<loom_core::Entity>, ResolutionContextError> {
            Ok(None)
        }

        fn get_relationship(
            &self,
            _relationship_id: loom_core::RelationshipId,
        ) -> Result<Option<loom_core::Relationship>, ResolutionContextError> {
            Ok(None)
        }

        fn get_facet(
            &self,
            _owner: loom_core::FacetOwner,
            _facet_type: &FacetTypeId,
        ) -> Result<Option<FacetValue>, ResolutionContextError> {
            Ok(None)
        }
    }

    impl CandidateWorldView for View {}

    struct Context {
        view: View,
    }

    impl ResolutionContext for Context {
        fn base_world(&self) -> &dyn BaseWorldView {
            &self.view
        }

        fn subresolve(
            &self,
            _invocation: &loom_protocol::ActionInvocation,
        ) -> Result<ResolveOutcome, ResolutionContextError> {
            Ok(ResolveOutcome::Resolved(Resolution::default()))
        }
    }

    struct FullCapability {
        manifest: CapabilityManifest,
    }

    impl Capability for FullCapability {
        fn manifest(&self) -> &CapabilityManifest {
            &self.manifest
        }

        fn register(
            &self,
            registrar: &mut CapabilityRegistrar,
        ) -> Result<(), super::RegistrationError> {
            registrar.register_facet(FacetDefinition::new(
                FacetTypeId::from("test.facet"),
                SchemaRevision::new(1),
                json!({"type": "object"}),
            ))?;
            registrar.register_relationship(
                RelationshipDefinition::new(
                    loom_core::RelationshipTypeId::from("test.relationship"),
                    SchemaRevision::new(1),
                )
                .with_role(RelationshipRole::new("member".into(), 1, Some(2))),
            )?;
            registrar.register_event(EventDefinition::new(
                EventTypeId::from("test.event"),
                SchemaRevision::new(1),
            ))?;
            registrar.register_action(
                ActionDefinition::new(ActionTypeId::from("test.action"), SchemaRevision::new(1)),
                EchoResolver,
            )?;
            registrar.register_work_handler(
                WorkHandlerDefinition::new(
                    WorkHandlerId::from("test.work"),
                    SchemaRevision::new(1),
                ),
                EmptyWorkHandler,
            )?;
            registrar.register_invariant(ReadOnlyInvariant);
            registrar.register_reaction(Reaction::new(
                EventTypeId::from("test.event"),
                WorkHandlerId::from("test.work"),
            ))?;
            Ok(())
        }
    }

    #[test]
    fn registry_discovers_typed_semantics_and_dispatches() {
        let registry = CapabilityRegistry::assemble([FullCapability {
            manifest: manifest("test.capability", "1.0.0"),
        }])
        .expect("complete registration should validate");

        let action_id = ActionTypeId::from("test.action");
        assert_eq!(registry.actions().count(), 1);
        assert_eq!(
            registry.action(&action_id).expect("action").owner.as_str(),
            "test.capability"
        );
        assert!(
            registry
                .facet(&FacetTypeId::from("test.facet"))
                .is_some_and(
                    |registered: &RegisteredFacet| registered.owner.as_str() == "test.capability"
                )
        );
        assert_eq!(registry.events().count(), 1);
        assert_eq!(registry.relationships().count(), 1);
        assert_eq!(registry.work_handlers().count(), 1);
        assert_eq!(registry.invariants().count(), 1);
        assert_eq!(registry.reactions().count(), 1);
        registry
            .invariants()
            .next()
            .expect("invariant")
            .validate(&View)
            .expect("read-only invariant should accept the view");

        let context = Context { view: View };
        let resolved = registry
            .resolve_action(&action_id, &context, &json!({"value": 1}))
            .expect("action should dispatch");
        assert!(matches!(resolved, ResolveOutcome::Resolved(_)));

        let rejected = registry
            .resolve_action(&action_id, &context, &json!({"reject": true}))
            .expect("semantic rejection is not a dispatch error");
        assert!(matches!(rejected, ResolveOutcome::Rejected(_)));
    }

    #[test]
    fn duplicate_semantic_ownership_is_deterministically_rejected() {
        let mut registry = CapabilityRegistry::new();
        let first = FullCapability {
            manifest: manifest("first", "1.0.0"),
        };
        let second = FullCapability {
            manifest: manifest("second", "1.0.0"),
        };
        registry.register(&first).expect("first registration");
        let error = registry
            .register(&second)
            .expect_err("duplicate action must fail");
        assert!(matches!(
            error,
            super::RegistryError::DuplicateSemantic {
                kind: super::SemanticKind::Facet,
                ..
            }
        ));
        assert_eq!(registry.capabilities().count(), 1);
    }

    #[test]
    fn dependency_and_loom_version_validation_are_assembly_gates() {
        let mut registry = CapabilityRegistry::with_loom_version(Version::new(0, 1, 0));
        let consumer = EmptyCapability {
            manifest: manifest("consumer", "1.0.0")
                .compatible_with(VersionReq::parse(">=0.1,<0.2").expect("range"))
                .requires(CapabilityDependency::new(
                    "provider",
                    VersionReq::parse("^2.0").expect("range"),
                )),
        };
        registry
            .register(&consumer)
            .expect("declarations are staged");
        assert!(matches!(
            registry.validate(),
            Err(super::RegistryError::MissingDependency { .. })
        ));

        let provider = EmptyCapability {
            manifest: manifest("provider", "1.0.0"),
        };
        registry.register(&provider).expect("provider registration");
        assert!(matches!(
            registry.validate(),
            Err(super::RegistryError::IncompatibleDependency { .. })
        ));
    }

    #[test]
    fn malformed_dependency_range_is_rejected_before_registration() {
        let error = CapabilityDependency::parse("provider", "not semver")
            .expect_err("invalid semver must not become metadata");
        assert!(error.to_string().contains("unexpected character"));
    }

    #[test]
    fn draft_2020_boolean_and_composition_schemas_are_enforced() {
        assert!(super::validate_json_schema(&json!(true), &json!({"accepted": true})).is_ok());
        assert!(super::validate_json_schema(&json!(false), &json!({"accepted": true})).is_err());

        let composed = json!({
            "oneOf": [
                {"type": "string"},
                {"type": "integer"}
            ]
        });
        assert!(super::validate_json_schema(&composed, &json!(42)).is_ok());
        assert!(super::validate_json_schema(&composed, &json!(true)).is_err());
    }

    #[test]
    fn malformed_registered_schema_fails_assembly_deterministically() {
        let assemble = || {
            CapabilityRegistry::assemble([MalformedSchemaCapability {
                manifest: manifest("invalid.schema", "1.0.0"),
            }])
            .err()
            .expect("malformed schema must block registry assembly")
        };
        let first = assemble();
        let second = assemble();
        assert_eq!(first, second);
        assert!(matches!(
            first,
            super::RegistryError::Registration {
                source: super::RegistrationError::InvalidDefinition {
                    kind: super::SemanticKind::Facet,
                    ..
                },
                ..
            }
        ));
    }

    #[test]
    fn work_handler_and_reaction_surfaces_do_not_offer_self_completion() {
        let registry = CapabilityRegistry::assemble([FullCapability {
            manifest: manifest("test.capability", "1.0.0"),
        }])
        .expect("complete registration should validate");
        let handler = registry
            .work_handler(&WorkHandlerId::from("test.work"))
            .expect("handler");
        let context = Context { view: View };
        let result = handler
            .handle(&context, &json!({}))
            .expect("handler should resolve");
        assert!(matches!(result, ResolveOutcome::Resolved(_)));
        assert_eq!(
            registry
                .reactions()
                .next()
                .expect("reaction")
                .reaction
                .schedule(),
            WorkSchedule::Immediate
        );
    }

    #[test]
    fn context_exposes_pinned_read_only_view_and_subresolution() {
        let context = Context { view: View };
        assert_eq!(
            context.timeline_id(),
            TimelineId::from_str("00000000-0000-0000-0000-000000000002").expect("test id")
        );
        assert_eq!(
            context.pinned_version(),
            TimelineVersion::new(0.into(), 0.into())
        );
        assert!(
            context
                .get_facet(
                    FacetOwner::entity(
                        EntityId::from_str("00000000-0000-0000-0000-000000000003")
                            .expect("test id"),
                    ),
                    &FacetTypeId::from("test.facet"),
                )
                .expect("read should succeed")
                .is_none()
        );
        let outcome = context
            .subresolve(&loom_protocol::ActionInvocation::new(
                ActionTypeId::from("test.action"),
                json!({}),
            ))
            .expect("subresolution should route through the host port");
        assert!(matches!(outcome, ResolveOutcome::Resolved(_)));
    }

    #[test]
    fn unknown_dispatch_is_separate_from_semantic_rejection() {
        let registry = CapabilityRegistry::new();
        let context = Context { view: View };
        let error = registry
            .resolve_action(&ActionTypeId::from("missing.action"), &context, &json!({}))
            .expect_err("unknown action should be a dispatch error");
        assert!(matches!(error, DispatchError::UnknownAction(_)));
    }
}
