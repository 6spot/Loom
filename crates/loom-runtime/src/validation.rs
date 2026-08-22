//! Runtime Effect Engine and the authority gate for validated resolutions.

use std::{
    collections::{HashMap, HashSet},
    fmt,
};

use loom_capability::{CapabilityId, CapabilityRegistry, SemanticKind};
use loom_core::{
    ActionTypeId, AssociationRole, EntityId, EventId, FacetOwner, RelationshipId,
    RelationshipParticipant, SchemaRevision, TimelineId, WorkId, WorldEffect,
};
use loom_protocol::{ProposedEvent, Rejection, Resolution, ResolveOutcome, WorkMutation};
use serde_json::Value;

use crate::{BudgetError, BudgetUsage, CallProvenance, CandidateWorldView, ResolutionBudget};

/// A typed failure raised while an untrusted Resolution crosses the Runtime
/// validation boundary.
///
/// A `ValidationError` means that the proposal is not eligible to become a
/// `ValidatedResolution`. It is deliberately separate from
/// `loom_protocol::Rejection`, which is a normal semantic outcome returned by a
/// Capability resolver and should not be treated as a Runtime defect.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ValidationError {
    /// The proposal refers to a semantic type absent from the registry.
    UnknownSemantic {
        /// Semantic category being looked up.
        kind: SemanticKind,
        /// Stable semantic key that was not registered.
        key: String,
    },
    /// The proposing Capability does not own the mutated semantic.
    SemanticOwnerMismatch {
        /// Semantic category whose owner was checked.
        kind: SemanticKind,
        /// Stable semantic key being mutated or proposed.
        key: String,
        /// Owner recorded in the Runtime registry.
        expected: String,
        /// Opaque proposer key supplied for this validation.
        proposer: String,
    },
    /// The proposal's schema revision differs from registry metadata.
    SchemaRevisionMismatch {
        /// Semantic category whose revision was checked.
        kind: SemanticKind,
        /// Stable semantic key whose revision is invalid.
        key: String,
        /// Registry revision required by Runtime.
        expected: SchemaRevision,
        /// Revision supplied by the untrusted proposal.
        actual: SchemaRevision,
    },
    /// A registered payload/value validator rejected a complete value.
    SchemaViolation {
        /// Semantic category whose schema rejected the value.
        kind: SemanticKind,
        /// Stable semantic key whose value was checked.
        key: String,
        /// Validator-selected explanation of the violation.
        message: String,
    },
    /// An identity was nil or otherwise invalid at the Runtime boundary.
    InvalidIdentity {
        /// Structural category of the invalid identity.
        kind: &'static str,
        /// Technical identity rendered for diagnostics.
        id: String,
    },
    /// A referenced Entity was not present in candidate state.
    MissingEntity {
        /// Entity identity that could not be resolved.
        entity_id: EntityId,
    },
    /// A referenced active Relationship was not present in candidate state.
    MissingRelationship {
        /// Relationship identity that could not be resolved.
        relationship_id: RelationshipId,
    },
    /// A proposed identity collides with base or prior candidate state.
    DuplicateIdentity {
        /// Structural category of the duplicated identity.
        kind: &'static str,
        /// Technical identity rendered for diagnostics.
        id: String,
    },
    /// A Relationship participant set violates its registered structure.
    RelationshipStructure {
        /// Relationship semantic key whose structure failed.
        relationship_type: String,
        /// Explanation of the cardinality/participant violation.
        message: String,
    },
    /// An Event association role is not allowed by its Event definition.
    InvalidAssociationRole {
        /// Event containing the invalid association.
        event_id: EventId,
        /// Role that was not declared by the Event definition.
        role: AssociationRole,
    },
    /// A causal link does not point to ancestry or an earlier batch Event.
    InvalidCausalReference {
        /// Event containing the causal link.
        event_id: EventId,
        /// Referenced cause that was unavailable at this batch position.
        cause_event_id: EventId,
    },
    /// An Event/Effect invariant callback rejected candidate state.
    InvariantViolation {
        /// Event whose candidate state was checked.
        event_id: EventId,
        /// Invariant-selected explanation of the violation.
        message: String,
    },
    /// A Work mutation is scoped to a different Timeline than the base view.
    WorkTimelineMismatch {
        /// Timeline pinned by the candidate view.
        expected: TimelineId,
        /// Timeline supplied by the Work proposal.
        actual: TimelineId,
    },
    /// A Work proposal references an unavailable causal Event.
    MissingWorkCausalEvent {
        /// Work item containing the invalid reference.
        work_id: WorkId,
        /// Event identity that was not available in the Resolution result.
        event_id: EventId,
    },
}

impl fmt::Display for ValidationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownSemantic { kind, key } => {
                write!(formatter, "unknown {kind} semantic: {key}")
            }
            Self::SemanticOwnerMismatch {
                kind,
                key,
                expected,
                proposer,
            } => write!(
                formatter,
                "{kind} semantic {key} is owned by {expected}, not {proposer}"
            ),
            Self::SchemaRevisionMismatch {
                kind,
                key,
                expected,
                actual,
            } => write!(
                formatter,
                "{kind} semantic {key} requires schema {expected}, received {actual}"
            ),
            Self::SchemaViolation { kind, key, message } => {
                write!(
                    formatter,
                    "{kind} semantic {key} schema violation: {message}"
                )
            }
            Self::InvalidIdentity { kind, id } => {
                write!(formatter, "invalid {kind} identity: {id}")
            }
            Self::MissingEntity { entity_id } => {
                write!(formatter, "missing Entity reference: {entity_id}")
            }
            Self::MissingRelationship { relationship_id } => {
                write!(
                    formatter,
                    "missing active Relationship reference: {relationship_id}"
                )
            }
            Self::DuplicateIdentity { kind, id } => {
                write!(formatter, "duplicate {kind} identity: {id}")
            }
            Self::RelationshipStructure {
                relationship_type,
                message,
            } => write!(
                formatter,
                "relationship {relationship_type} structure violation: {message}"
            ),
            Self::InvalidAssociationRole { event_id, role } => write!(
                formatter,
                "event {event_id} uses undeclared association role {role}"
            ),
            Self::InvalidCausalReference {
                event_id,
                cause_event_id,
            } => write!(
                formatter,
                "event {event_id} cannot reference unavailable cause {cause_event_id}"
            ),
            Self::InvariantViolation { event_id, message } => {
                write!(formatter, "event {event_id} invariant violation: {message}")
            }
            Self::WorkTimelineMismatch { expected, actual } => write!(
                formatter,
                "Work mutation targets Timeline {actual}, expected {expected}"
            ),
            Self::MissingWorkCausalEvent { work_id, event_id } => write!(
                formatter,
                "Work {work_id} references unavailable causal Event {event_id}"
            ),
        }
    }
}

impl std::error::Error for ValidationError {}

/// A Runtime error returned by validation/orchestration code.
///
/// `RuntimeError` is the Rust error channel for malformed proposals and policy
/// limits. It never encodes a normal `Rejection`, which is preserved by
/// `EffectEngine::validate_outcome` as `ValidationOutcome::Rejected`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeError {
    /// The proposal violated a structural, semantic or invariant rule.
    Validation(ValidationError),
    /// The proposal exceeded a configured Runtime budget.
    Budget(BudgetError),
}

impl fmt::Display for RuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Validation(error) => error.fmt(formatter),
            Self::Budget(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for RuntimeError {}

impl From<ValidationError> for RuntimeError {
    fn from(value: ValidationError) -> Self {
        Self::Validation(value)
    }
}

/// The result of passing a resolver's normal `ResolveOutcome` through Runtime.
///
/// `Rejected` remains a valid semantic result and does not construct a
/// `ValidatedResolution`. `Validated` is the only value that crosses the
/// Runtime authority gate toward a future commit port.
#[derive(Debug)]
pub enum ValidationOutcome {
    /// Runtime validated a Resolution against the pinned candidate state.
    Validated(ValidatedResolution),
    /// The owning Capability normally refused the attempted behavior.
    Rejected(Rejection),
}

/// One untrusted Resolution segment together with the Capability owner that
/// Runtime observed at its dispatch boundary.
///
/// Segments are an internal Runtime composition value. Capability code can
/// return only an untrusted `Resolution`; Runtime records the owner from the
/// registered Action/Work handler and later validates each segment against its
/// own semantic owner before flattening the segments into one authority token.
#[derive(Clone, Debug)]
pub(crate) struct ResolutionSegment {
    /// Capability that owns the resolver which produced this segment.
    pub(crate) owner: CapabilityId,
    /// Untrusted semantic proposal returned by that resolver.
    pub(crate) resolution: Resolution,
}

impl ResolutionSegment {
    pub(crate) fn new(owner: CapabilityId, resolution: Resolution) -> Self {
        Self { owner, resolution }
    }
}

/// Runtime-owned authority token proving that one Resolution passed candidate
/// validation.
///
/// The fields and constructor are private to `loom-runtime`; Protocol,
/// Capability and API callers can produce only an untrusted `Resolution`.
/// Storage may consume this token through a Runtime-owned persistence port, but
/// successful validation still does not guarantee commit: the port must perform
/// the pinned `TimelineVersion` CAS at its own linearization point.
#[derive(Debug)]
pub struct ValidatedResolution {
    resolution: Resolution,
    timeline_id: TimelineId,
    base_version: loom_core::TimelineVersion,
    pinned_world_time: loom_core::WorldInstant,
    read_set: crate::ReadSet,
    call_provenance: CallProvenance,
}

impl ValidatedResolution {
    /// Returns the Timeline identity against which validation ran.
    ///
    /// The identity is pinned privately with the Runtime authority token so a
    /// commit adapter cannot retarget a validated proposal to another
    /// Timeline. It is immutable and is not a constructor input available to
    /// Protocol or Capability callers.
    #[must_use]
    pub const fn timeline_id(&self) -> TimelineId {
        self.timeline_id
    }

    /// Returns the Timeline version against which validation ran.
    #[must_use]
    pub const fn base_version(&self) -> loom_core::TimelineVersion {
        self.base_version
    }

    /// Returns the Runtime-pinned World Time used to stamp committed Events.
    #[must_use]
    pub const fn pinned_world_time(&self) -> loom_core::WorldInstant {
        self.pinned_world_time
    }

    /// Borrows the validated proposal for a Runtime-owned commit adapter.
    ///
    /// The returned value is still the original protocol shape; this accessor
    /// does not let a caller construct a new authority token or bypass the
    /// version CAS.
    #[must_use]
    pub const fn resolution(&self) -> &Resolution {
        &self.resolution
    }

    /// Returns the proposed Events whose nested Effects passed validation.
    #[must_use]
    pub fn events(&self) -> &[ProposedEvent] {
        &self.resolution.events
    }

    /// Returns the Work mutations validated with the Events.
    #[must_use]
    pub fn work(&self) -> &[WorkMutation] {
        &self.resolution.work
    }

    /// Returns the Runtime-observed provenance for this validation run.
    #[must_use]
    pub const fn read_set(&self) -> &crate::ReadSet {
        &self.read_set
    }

    /// Returns Runtime-observed subresolution call edges for this execution.
    ///
    /// These edges belong to Execution Provenance, not the World Event causal
    /// graph. They are retained on the Runtime authority token for diagnostics
    /// and tests; they do not grant Capability permission or become public API
    /// World data.
    #[must_use]
    pub const fn call_provenance(&self) -> &CallProvenance {
        &self.call_provenance
    }

    pub(crate) fn new(
        resolution: Resolution,
        timeline_id: TimelineId,
        base_version: loom_core::TimelineVersion,
        pinned_world_time: loom_core::WorldInstant,
        read_set: crate::ReadSet,
        call_provenance: CallProvenance,
    ) -> Self {
        Self {
            resolution,
            timeline_id,
            base_version,
            pinned_world_time,
            read_set,
            call_provenance,
        }
    }
}

/// Runtime Effect Engine for one immutable semantic registry and validation
/// policy.
///
/// The engine never mutates the base snapshot. It validates each Event and
/// nested Effect in order, applies successful Effects to a candidate overlay,
/// invokes read-only invariant callbacks against that candidate and creates
/// the Runtime-only `ValidatedResolution` only after every check succeeds.
pub struct EffectEngine<'registry> {
    registry: &'registry CapabilityRegistry,
    budget: ResolutionBudget,
}

impl<'registry> EffectEngine<'registry> {
    /// Creates an Effect Engine over an assembled Capability registry.
    ///
    /// The registry is borrowed for the engine lifetime, keeping semantic
    /// ownership and read-only invariant implementations in the Capability
    /// assembly that Runtime consumes. Callers that have not already passed the
    /// registry assembly gate should use `from_capability_registry`.
    #[must_use]
    pub fn new(registry: &'registry CapabilityRegistry) -> Self {
        Self {
            registry,
            budget: ResolutionBudget::unlimited(),
        }
    }

    /// Creates an Effect Engine after checking the Capability registry's
    /// dependency and registration assembly invariants.
    ///
    /// # Errors
    ///
    /// Returns the Capability registry error when dependency/version/reaction
    /// validation has not passed.
    pub fn from_capability_registry(
        registry: &'registry CapabilityRegistry,
    ) -> Result<Self, loom_capability::RegistryError> {
        registry.validate()?;
        Ok(Self::new(registry))
    }

    /// Replaces the Runtime budget policy used before validation.
    #[must_use]
    pub fn with_budget(mut self, budget: ResolutionBudget) -> Self {
        self.budget = budget;
        self
    }

    /// Returns the immutable semantic metadata used by this engine.
    #[must_use]
    pub const fn registry(&self) -> &CapabilityRegistry {
        self.registry
    }

    /// Validates untrusted input against a registered Action schema before
    /// Runtime dispatches to its resolver.
    ///
    /// Action input is an external request boundary, so a schema violation is
    /// a Runtime validation error and never a Capability-owned semantic
    /// `Rejection`. The resolver is not invoked when this check fails.
    ///
    /// # Errors
    ///
    /// Returns a Runtime validation error when the Action is unknown or its
    /// input does not satisfy the registered Draft 2020-12 schema.
    pub fn validate_action_input(
        &self,
        action: &ActionTypeId,
        input: &Value,
    ) -> Result<(), RuntimeError> {
        let definition =
            self.registry
                .action(action)
                .ok_or_else(|| ValidationError::UnknownSemantic {
                    kind: SemanticKind::Action,
                    key: action.to_string(),
                })?;
        validate_json_schema(
            definition.definition.input_schema.as_ref(),
            input,
            SemanticKind::Action,
            &action.to_string(),
        )
        .map_err(|message| ValidationError::SchemaViolation {
            kind: SemanticKind::Action,
            key: action.to_string(),
            message,
        })?;
        Ok(())
    }

    /// Validates one untrusted Resolution against a pinned base view.
    ///
    /// `proposer` is the opaque Capability owner key selected by the Runtime
    /// router. It is compared with registry metadata for every semantic Event,
    /// Facet and Relationship mutation. The caller receives an authority token
    /// only after all Events, Effects, Work references and invariants pass.
    ///
    /// # Errors
    ///
    /// Returns `RuntimeError::Budget` for a policy limit and
    /// `RuntimeError::Validation` for any malformed, unauthorized or
    /// structurally invalid proposal.
    pub fn validate(
        &self,
        base: &crate::BaseWorldView,
        proposer: &str,
        resolution: Resolution,
    ) -> Result<ValidatedResolution, RuntimeError> {
        self.validate_segments(
            base,
            &[ResolutionSegment::new(
                CapabilityId::from(proposer),
                resolution,
            )],
            CallProvenance::default(),
        )
    }

    /// Validates owner-tagged Resolution segments against one shared candidate
    /// and flattens them into one Runtime authority token.
    ///
    /// Segments are processed in the order Runtime observed them. Each
    /// segment's Events and Work mutations are checked with that segment's
    /// semantic owner, while all segments share one candidate overlay and one
    /// aggregate budget. A failure in any segment returns before a commit token
    /// can be produced; the caller therefore has one atomic commit input rather
    /// than one token per Capability.
    ///
    /// # Errors
    ///
    /// Returns `RuntimeError::Budget` when the aggregate proposal exceeds a
    /// configured limit, or `RuntimeError::Validation` for any invalid segment.
    pub(crate) fn validate_segments(
        &self,
        base: &crate::BaseWorldView,
        segments: &[ResolutionSegment],
        call_provenance: CallProvenance,
    ) -> Result<ValidatedResolution, RuntimeError> {
        let aggregate_usage = segments
            .iter()
            .fold(BudgetUsage::default(), |usage, segment| {
                usage.combine(BudgetUsage::from_resolution(&segment.resolution))
            });
        self.budget
            .check(aggregate_usage)
            .map_err(RuntimeError::Budget)?;

        let mut candidate = CandidateWorldView::from_base(base);
        let mut flattened = Resolution::default();
        for segment in segments {
            for event in &segment.resolution.events {
                if event.id.is_nil() {
                    return Err(ValidationError::InvalidIdentity {
                        kind: "Event",
                        id: event.id.to_string(),
                    }
                    .into());
                }
                if candidate.event_exists(event.id) {
                    return Err(ValidationError::DuplicateIdentity {
                        kind: "Event",
                        id: event.id.to_string(),
                    }
                    .into());
                }
                let mut event_candidate = candidate.fork();
                validate_event(
                    self.registry,
                    &mut event_candidate,
                    segment.owner.as_str(),
                    event,
                )?;
                self.validate_invariants(&event_candidate, event)?;
                candidate = event_candidate;
                candidate.note_event(event.id);
                flattened.events.push(event.clone());
            }
            validate_work(
                self.registry,
                &mut candidate,
                segment.owner.as_str(),
                &segment.resolution,
            )?;
            flattened
                .work
                .extend(segment.resolution.work.iter().cloned());
        }

        let mut read_set = base.read_set();
        read_set.extend(candidate.read_set());
        Ok(ValidatedResolution::new(
            flattened,
            base.timeline_id(),
            base.version(),
            base.world_time(),
            read_set,
            call_provenance,
        ))
    }

    /// Validates a normal resolver result while preserving Capability
    /// rejection as a normal outcome.
    ///
    /// # Errors
    ///
    /// Returns a Runtime error only when a resolved proposal violates Runtime
    /// validation or budget policy.
    pub fn validate_outcome(
        &self,
        base: &crate::BaseWorldView,
        proposer: &str,
        outcome: ResolveOutcome,
    ) -> Result<ValidationOutcome, RuntimeError> {
        match outcome {
            ResolveOutcome::Resolved(resolution) => self
                .validate(base, proposer, resolution)
                .map(ValidationOutcome::Validated),
            ResolveOutcome::Rejected(rejection) => Ok(ValidationOutcome::Rejected(rejection)),
        }
    }

    fn validate_invariants(
        &self,
        candidate: &CandidateWorldView,
        event: &ProposedEvent,
    ) -> Result<(), ValidationError> {
        for invariant in self.registry.invariants() {
            invariant.validate(candidate).map_err(|violation| {
                ValidationError::InvariantViolation {
                    event_id: event.id,
                    message: format!("{}: {}", violation.code, violation.message),
                }
            })?;
        }
        Ok(())
    }
}

fn validate_event(
    registry: &CapabilityRegistry,
    candidate: &mut CandidateWorldView,
    proposer: &str,
    event: &ProposedEvent,
) -> Result<(), ValidationError> {
    if event.id.is_nil() {
        return Err(ValidationError::InvalidIdentity {
            kind: "Event",
            id: event.id.to_string(),
        });
    }

    let definition =
        registry
            .event(&event.event_type)
            .ok_or_else(|| ValidationError::UnknownSemantic {
                kind: SemanticKind::Event,
                key: event.event_type.to_string(),
            })?;
    ensure_owner(
        SemanticKind::Event,
        event.event_type.to_string(),
        definition.owner.as_str(),
        proposer,
    )?;
    ensure_revision(
        SemanticKind::Event,
        event.event_type.to_string(),
        definition.definition.schema_revision,
        event.schema_revision,
    )?;
    validate_json_schema(
        definition.definition.payload_schema.as_ref(),
        &event.payload,
        SemanticKind::Event,
        &event.event_type.to_string(),
    )
    .map_err(|message| ValidationError::SchemaViolation {
        kind: SemanticKind::Event,
        key: event.event_type.to_string(),
        message,
    })?;

    let mut reference_candidate = candidate.fork();

    for causal_link in &event.causal_links {
        let cause_event_id = causal_link.event_id();
        if !candidate.event_exists(cause_event_id) {
            return Err(ValidationError::InvalidCausalReference {
                event_id: event.id,
                cause_event_id,
            });
        }
    }

    for effect in &event.effects {
        validate_effect(registry, candidate, proposer, effect)?;
        candidate.apply_effect(effect);
        if matches!(
            effect,
            WorldEffect::CreateEntity { .. } | WorldEffect::CreateRelationship { .. }
        ) {
            reference_candidate.apply_effect(effect);
        }
    }

    for participant in &event.participants {
        validate_event_participant(
            &reference_candidate,
            &definition.definition.participant_roles,
            event,
            participant,
        )?;
    }
    for relationship in &event.relationship_refs {
        if !definition.definition.relationship_roles.is_empty()
            && !definition
                .definition
                .relationship_roles
                .iter()
                .any(|role| role == &relationship.role)
        {
            return Err(ValidationError::InvalidAssociationRole {
                event_id: event.id,
                role: relationship.role.clone(),
            });
        }
        if reference_candidate
            .relationship(relationship.relationship_id)
            .is_none()
        {
            return Err(ValidationError::MissingRelationship {
                relationship_id: relationship.relationship_id,
            });
        }
    }
    candidate.extend_read_set(reference_candidate.read_set());
    Ok(())
}

fn validate_event_participant(
    candidate: &CandidateWorldView,
    allowed_roles: &[AssociationRole],
    event: &ProposedEvent,
    participant: &loom_protocol::EventParticipant,
) -> Result<(), ValidationError> {
    if !allowed_roles.is_empty() && !allowed_roles.iter().any(|role| role == &participant.role) {
        return Err(ValidationError::InvalidAssociationRole {
            event_id: event.id,
            role: participant.role.clone(),
        });
    }
    if participant.entity_id.is_nil() {
        return Err(ValidationError::InvalidIdentity {
            kind: "Entity",
            id: participant.entity_id.to_string(),
        });
    }
    if candidate.entity(participant.entity_id).is_none() {
        return Err(ValidationError::MissingEntity {
            entity_id: participant.entity_id,
        });
    }
    Ok(())
}

fn validate_effect(
    registry: &CapabilityRegistry,
    candidate: &mut CandidateWorldView,
    proposer: &str,
    effect: &WorldEffect,
) -> Result<(), ValidationError> {
    match effect {
        WorldEffect::CreateEntity { entity_id } => validate_create_entity(candidate, *entity_id),
        WorldEffect::PutFacet {
            owner,
            facet_type,
            schema_revision,
            value,
        } => validate_put_facet(
            registry,
            candidate,
            proposer,
            *owner,
            facet_type,
            *schema_revision,
            value,
        ),
        WorldEffect::RemoveFacet { owner, facet_type } => {
            validate_remove_facet(registry, candidate, proposer, *owner, facet_type)
        }
        WorldEffect::CreateRelationship {
            relationship_id,
            relationship_type,
            participants,
        } => validate_create_relationship(
            registry,
            candidate,
            proposer,
            *relationship_id,
            relationship_type,
            participants,
        ),
        WorldEffect::EndRelationship { relationship_id } => {
            validate_end_relationship(registry, candidate, proposer, *relationship_id)
        }
    }
}

fn validate_create_entity(
    candidate: &CandidateWorldView,
    entity_id: EntityId,
) -> Result<(), ValidationError> {
    if entity_id.is_nil() {
        return Err(ValidationError::InvalidIdentity {
            kind: "Entity",
            id: entity_id.to_string(),
        });
    }
    if candidate.entity(entity_id).is_some() {
        return Err(ValidationError::DuplicateIdentity {
            kind: "Entity",
            id: entity_id.to_string(),
        });
    }
    Ok(())
}

fn validate_put_facet(
    registry: &CapabilityRegistry,
    candidate: &CandidateWorldView,
    proposer: &str,
    owner: FacetOwner,
    facet_type: &loom_core::FacetTypeId,
    schema_revision: SchemaRevision,
    value: &serde_json::Value,
) -> Result<(), ValidationError> {
    let definition =
        registry
            .facet(facet_type)
            .ok_or_else(|| ValidationError::UnknownSemantic {
                kind: SemanticKind::Facet,
                key: facet_type.to_string(),
            })?;
    ensure_owner(
        SemanticKind::Facet,
        facet_type.to_string(),
        definition.owner.as_str(),
        proposer,
    )?;
    ensure_revision(
        SemanticKind::Facet,
        facet_type.to_string(),
        definition.definition.schema_revision,
        schema_revision,
    )?;
    ensure_owner_exists(candidate, owner)?;
    validate_json_schema(
        Some(&definition.definition.schema),
        value,
        SemanticKind::Facet,
        &facet_type.to_string(),
    )
    .map_err(|message| ValidationError::SchemaViolation {
        kind: SemanticKind::Facet,
        key: facet_type.to_string(),
        message,
    })
}

fn validate_remove_facet(
    registry: &CapabilityRegistry,
    candidate: &CandidateWorldView,
    proposer: &str,
    owner: FacetOwner,
    facet_type: &loom_core::FacetTypeId,
) -> Result<(), ValidationError> {
    let definition =
        registry
            .facet(facet_type)
            .ok_or_else(|| ValidationError::UnknownSemantic {
                kind: SemanticKind::Facet,
                key: facet_type.to_string(),
            })?;
    ensure_owner(
        SemanticKind::Facet,
        facet_type.to_string(),
        definition.owner.as_str(),
        proposer,
    )?;
    ensure_owner_exists(candidate, owner)
}

fn validate_create_relationship(
    registry: &CapabilityRegistry,
    candidate: &CandidateWorldView,
    proposer: &str,
    relationship_id: RelationshipId,
    relationship_type: &loom_core::RelationshipTypeId,
    participants: &[RelationshipParticipant],
) -> Result<(), ValidationError> {
    if relationship_id.is_nil() {
        return Err(ValidationError::InvalidIdentity {
            kind: "Relationship",
            id: relationship_id.to_string(),
        });
    }
    if candidate.relationship_identity_exists(relationship_id) {
        return Err(ValidationError::DuplicateIdentity {
            kind: "Relationship",
            id: relationship_id.to_string(),
        });
    }
    let definition = registry.relationship(relationship_type).ok_or_else(|| {
        ValidationError::UnknownSemantic {
            kind: SemanticKind::Relationship,
            key: relationship_type.to_string(),
        }
    })?;
    ensure_owner(
        SemanticKind::Relationship,
        relationship_type.to_string(),
        definition.owner.as_str(),
        proposer,
    )?;
    validate_relationship_structure(
        candidate,
        relationship_type,
        &definition.definition.roles,
        participants,
    )
}

fn validate_end_relationship(
    registry: &CapabilityRegistry,
    candidate: &CandidateWorldView,
    proposer: &str,
    relationship_id: RelationshipId,
) -> Result<(), ValidationError> {
    let relationship = candidate
        .relationship(relationship_id)
        .ok_or(ValidationError::MissingRelationship { relationship_id })?;
    let relationship_type = relationship.relationship_type();
    let definition = registry.relationship(relationship_type).ok_or_else(|| {
        ValidationError::UnknownSemantic {
            kind: SemanticKind::Relationship,
            key: relationship_type.to_string(),
        }
    })?;
    ensure_owner(
        SemanticKind::Relationship,
        relationship_type.to_string(),
        definition.owner.as_str(),
        proposer,
    )
}

fn ensure_owner(
    kind: SemanticKind,
    key: String,
    expected: &str,
    proposer: &str,
) -> Result<(), ValidationError> {
    if expected != proposer {
        return Err(ValidationError::SemanticOwnerMismatch {
            kind,
            key,
            expected: expected.to_owned(),
            proposer: proposer.to_owned(),
        });
    }
    Ok(())
}

fn ensure_revision(
    kind: SemanticKind,
    key: String,
    expected: SchemaRevision,
    actual: SchemaRevision,
) -> Result<(), ValidationError> {
    if expected != actual {
        return Err(ValidationError::SchemaRevisionMismatch {
            kind,
            key,
            expected,
            actual,
        });
    }
    Ok(())
}

fn ensure_owner_exists(
    candidate: &CandidateWorldView,
    owner: FacetOwner,
) -> Result<(), ValidationError> {
    match owner {
        FacetOwner::Entity(entity_id) => {
            if entity_id.is_nil() {
                return Err(ValidationError::InvalidIdentity {
                    kind: "Entity",
                    id: entity_id.to_string(),
                });
            }
            if candidate.entity(entity_id).is_none() {
                return Err(ValidationError::MissingEntity { entity_id });
            }
        }
        FacetOwner::Relationship(relationship_id) => {
            if relationship_id.is_nil() {
                return Err(ValidationError::InvalidIdentity {
                    kind: "Relationship",
                    id: relationship_id.to_string(),
                });
            }
            if candidate.relationship(relationship_id).is_none() {
                return Err(ValidationError::MissingRelationship { relationship_id });
            }
        }
    }
    Ok(())
}

fn validate_relationship_structure(
    candidate: &CandidateWorldView,
    relationship_type: &loom_core::RelationshipTypeId,
    roles: &[loom_capability::RelationshipRole],
    participants: &[RelationshipParticipant],
) -> Result<(), ValidationError> {
    let relationship_type_text = relationship_type.to_string();
    if participants.is_empty() {
        return Err(ValidationError::RelationshipStructure {
            relationship_type: relationship_type_text,
            message: "participant set must not be empty".to_owned(),
        });
    }

    let mut entity_ids = HashSet::new();
    let mut role_counts: HashMap<AssociationRole, usize> = HashMap::new();
    for participant in participants {
        if participant.entity_id.is_nil() {
            return Err(ValidationError::InvalidIdentity {
                kind: "Entity",
                id: participant.entity_id.to_string(),
            });
        }
        if !entity_ids.insert(participant.entity_id) {
            return Err(ValidationError::RelationshipStructure {
                relationship_type: relationship_type.to_string(),
                message: format!("Entity {} appears more than once", participant.entity_id),
            });
        }
        if candidate.entity(participant.entity_id).is_none() {
            return Err(ValidationError::MissingEntity {
                entity_id: participant.entity_id,
            });
        }
        *role_counts.entry(participant.role.clone()).or_default() += 1;
    }

    if !roles.is_empty() {
        for participant in participants {
            if !roles.iter().any(|rule| rule.role == participant.role) {
                return Err(ValidationError::RelationshipStructure {
                    relationship_type: relationship_type.to_string(),
                    message: format!("role {} is not declared", participant.role),
                });
            }
        }
    }
    for rule in roles {
        let count = role_counts.get(&rule.role).copied().unwrap_or_default();
        if count < usize::from(rule.minimum)
            || rule
                .maximum
                .is_some_and(|maximum| count > usize::from(maximum))
        {
            return Err(ValidationError::RelationshipStructure {
                relationship_type: relationship_type.to_string(),
                message: format!(
                    "role {} count {count} is outside {}..{}",
                    rule.role,
                    rule.minimum,
                    rule.maximum
                        .map_or_else(|| "unbounded".to_owned(), |maximum| maximum.to_string())
                ),
            });
        }
    }
    Ok(())
}

fn validate_json_schema(
    schema: Option<&Value>,
    value: &Value,
    _kind: SemanticKind,
    _key: &str,
) -> Result<(), String> {
    let Some(schema) = schema else {
        return Ok(());
    };
    loom_capability::validate_json_schema(schema, value)
}

fn validate_work(
    registry: &CapabilityRegistry,
    candidate: &mut CandidateWorldView,
    proposer: &str,
    resolution: &Resolution,
) -> Result<(), ValidationError> {
    for mutation in &resolution.work {
        match mutation {
            WorkMutation::Schedule(work) => {
                if work.id.is_nil() {
                    return Err(ValidationError::InvalidIdentity {
                        kind: "Work",
                        id: work.id.to_string(),
                    });
                }
                let handler = registry.work_handler(&work.handler).ok_or_else(|| {
                    ValidationError::UnknownSemantic {
                        kind: SemanticKind::WorkHandler,
                        key: work.handler.to_string(),
                    }
                })?;
                ensure_owner(
                    SemanticKind::WorkHandler,
                    work.handler.to_string(),
                    handler.owner.as_str(),
                    proposer,
                )?;
                ensure_revision(
                    SemanticKind::WorkHandler,
                    work.handler.to_string(),
                    handler.definition.schema_revision,
                    work.schema_revision,
                )?;
                validate_json_schema(
                    handler.definition.payload_schema.as_ref(),
                    &work.payload,
                    SemanticKind::WorkHandler,
                    &work.handler.to_string(),
                )
                .map_err(|message| ValidationError::SchemaViolation {
                    kind: SemanticKind::WorkHandler,
                    key: work.handler.to_string(),
                    message,
                })?;
                if work.timeline_id != candidate.timeline_id() {
                    return Err(ValidationError::WorkTimelineMismatch {
                        expected: candidate.timeline_id(),
                        actual: work.timeline_id,
                    });
                }
                if let Some(event_id) = work.causal_event_id
                    && !candidate.event_exists(event_id)
                {
                    return Err(ValidationError::MissingWorkCausalEvent {
                        work_id: work.id,
                        event_id,
                    });
                }
            }
            WorkMutation::Cancel(work_id) => {
                if work_id.is_nil() {
                    return Err(ValidationError::InvalidIdentity {
                        kind: "Work",
                        id: work_id.to_string(),
                    });
                }
            }
        }
    }
    Ok(())
}
