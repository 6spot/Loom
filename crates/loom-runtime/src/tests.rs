use std::str::FromStr;

use loom_capability::{
    CandidateWorldView as CapabilityCandidateWorldView, Capability, CapabilityManifest,
    CapabilityRegistrar, CapabilityRegistry, EventDefinition as CapabilityEventDefinition,
    FacetDefinition as CapabilityFacetDefinition, Invariant, InvariantViolation,
    RelationshipDefinition as CapabilityRelationshipDefinition, RelationshipRole,
};
use loom_core::{
    Entity, EntityId, EventId, EventSeq, FacetOwner, FacetTypeId, Relationship, RelationshipId,
    RelationshipParticipant, RelationshipTypeId, SchemaRevision, StateRevision, TimelineId,
    TimelineVersion, WorldEffect, WorldId, WorldInstant,
};
use loom_protocol::{
    CausalLink, EventParticipant, EventRelationshipRef, ProposedEvent, Rejection, Resolution,
    ResolveOutcome,
};
use serde_json::json;

use super::{
    BaseWorldSnapshot, BaseWorldView, EffectEngine, ReadDependency, ValidationError,
    ValidationOutcome,
};

const OWNER: &str = "counter";
const OTHER_OWNER: &str = "other";

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    let text = format!("00000000-0000-0000-0000-{value:012x}");
    text.parse().expect("test identity should parse")
}

fn world() -> WorldId {
    id(1)
}

fn timeline() -> TimelineId {
    id(2)
}

fn entity(value: u128) -> EntityId {
    id(value)
}

fn event(value: u128) -> EventId {
    id(value)
}

fn relationship(value: u128) -> RelationshipId {
    id(value)
}

fn base_view() -> BaseWorldView {
    let entity_id = entity(10);
    let facet_type = FacetTypeId::from("counter.value");
    let snapshot = BaseWorldSnapshot::new(
        world(),
        timeline(),
        TimelineVersion::new(EventSeq::new(4), StateRevision::new(4)),
        WorldInstant::new(4),
    )
    .with_entity(Entity {
        id: entity_id,
        world_id: world(),
    })
    .with_entity(Entity {
        id: entity(11),
        world_id: world(),
    })
    .with_facet(
        FacetOwner::entity(entity_id),
        facet_type,
        SchemaRevision::new(1),
        json!({"value": 1}),
    )
    .with_event(event(100));
    BaseWorldView::new(snapshot)
}

fn registry() -> CapabilityRegistry {
    let capability = BasicCapability {
        manifest: CapabilityManifest::parse("counter", "0.1.0")
            .expect("test Capability manifest should parse"),
    };
    CapabilityRegistry::assemble(vec![capability]).expect("Capability registry should assemble")
}

fn invariant_registry() -> CapabilityRegistry {
    let capability = SpiCapability {
        manifest: CapabilityManifest::parse("counter", "0.1.0")
            .expect("test Capability manifest should parse"),
    };
    CapabilityRegistry::assemble(vec![capability]).expect("Capability registry should assemble")
}

fn register_basic_semantics(
    registrar: &mut CapabilityRegistrar,
) -> Result<(), loom_capability::RegistrationError> {
    registrar.register_facet(CapabilityFacetDefinition::new(
        FacetTypeId::from("counter.value"),
        SchemaRevision::new(1),
        json!({
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "integer"}}
        }),
    ))?;
    registrar.register_event(
        CapabilityEventDefinition::new(
            loom_core::EventTypeId::from("counter.changed"),
            SchemaRevision::new(1),
        )
        .with_payload_schema(json!({
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "integer"}}
        })),
    )?;
    registrar.register_relationship(
        CapabilityRelationshipDefinition::new(
            RelationshipTypeId::from("counter.pair"),
            SchemaRevision::new(1),
        )
        .with_role(RelationshipRole::new("left".into(), 1, Some(1)))
        .with_role(RelationshipRole::new("right".into(), 1, Some(1))),
    )?;
    Ok(())
}

fn proposed_event(value: u128) -> ProposedEvent {
    ProposedEvent::new(
        event(value),
        loom_core::EventTypeId::from("counter.changed"),
        SchemaRevision::new(1),
        WorldInstant::new(5),
        json!({"value": value}),
    )
}

fn pair_participants() -> Vec<RelationshipParticipant> {
    vec![
        RelationshipParticipant::new(entity(10), "left"),
        RelationshipParticipant::new(entity(11), "right"),
    ]
}

fn pair_relationship(id: RelationshipId) -> Relationship {
    Relationship::new(
        id,
        world(),
        RelationshipTypeId::from("counter.pair"),
        pair_participants(),
    )
}

#[test]
fn candidate_overlay_shadows_base_for_later_validation_reads() {
    let first_id = event(1);
    let second_id = event(2);
    let entity_id = entity(10);
    let facet_type = FacetTypeId::from("counter.value");
    let first = proposed_event(1).with_effect(WorldEffect::PutFacet {
        owner: FacetOwner::entity(entity_id),
        facet_type: facet_type.clone(),
        schema_revision: SchemaRevision::new(1),
        value: json!({"value": 2}),
    });
    let second = proposed_event(2).with_participant(EventParticipant::new(entity_id, "actor"));
    assert_eq!(first.id, first_id);
    assert_eq!(second.id, second_id);

    let registry = invariant_registry();
    let engine = EffectEngine::from_capability_registry(&registry)
        .expect("Capability registry should pass Runtime assembly validation");

    let validated = engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![first, second], Vec::new()),
        )
        .expect("candidate overlay should validate");
    assert!(
        validated
            .read_set()
            .entries()
            .iter()
            .any(|dependency| matches!(dependency, ReadDependency::Facet { .. }))
    );
}

#[test]
fn missing_entity_and_relationship_references_are_rejected() {
    let missing_entity_event =
        proposed_event(1).with_participant(EventParticipant::new(entity(999), "actor"));
    let registry = registry();
    let engine = EffectEngine::new(&registry);
    let entity_error = engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![missing_entity_event], Vec::new()),
        )
        .expect_err("missing Entity must block validation");
    assert!(matches!(
        entity_error,
        super::RuntimeError::Validation(ValidationError::MissingEntity { .. })
    ));

    let mut missing_relationship_event = proposed_event(2);
    missing_relationship_event
        .relationship_refs
        .push(EventRelationshipRef::new(relationship(999), "subject"));
    let relationship_error = engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![missing_relationship_event], Vec::new()),
        )
        .expect_err("missing Relationship must block validation");
    assert!(matches!(
        relationship_error,
        super::RuntimeError::Validation(ValidationError::MissingRelationship { .. })
    ));
}

#[test]
fn relationship_structure_is_checked_at_the_effect_boundary() {
    let invalid = proposed_event(1).with_effect(WorldEffect::CreateRelationship {
        relationship_id: relationship(20),
        relationship_type: RelationshipTypeId::from("counter.pair"),
        participants: vec![RelationshipParticipant::new(entity(10), "left")],
    });
    let registry = registry();
    let error = EffectEngine::new(&registry)
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![invalid], Vec::new()),
        )
        .expect_err("one participant cannot satisfy a two-party definition");
    assert!(matches!(
        error,
        super::RuntimeError::Validation(ValidationError::RelationshipStructure { .. })
    ));
}

#[test]
fn relationship_identity_collision_spans_active_and_ended_lifecycles() {
    let registry = registry();
    let engine = EffectEngine::new(&registry);
    let relationship_id = relationship(20);
    let create = proposed_event(20).with_effect(WorldEffect::CreateRelationship {
        relationship_id,
        relationship_type: RelationshipTypeId::from("counter.pair"),
        participants: pair_participants(),
    });
    let end = proposed_event(21).with_effect(WorldEffect::EndRelationship { relationship_id });
    let recreate = proposed_event(22).with_effect(WorldEffect::CreateRelationship {
        relationship_id,
        relationship_type: RelationshipTypeId::from("counter.pair"),
        participants: pair_participants(),
    });
    let lifecycle_error = engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![create, end, recreate], Vec::new()),
        )
        .expect_err("an ended Relationship identity must not be reused");
    assert!(matches!(
        lifecycle_error,
        super::RuntimeError::Validation(ValidationError::DuplicateIdentity {
            kind: "Relationship",
            ..
        })
    ));

    let inactive_base = BaseWorldSnapshot::new(
        world(),
        timeline(),
        TimelineVersion::new(EventSeq::new(4), StateRevision::new(4)),
        WorldInstant::new(4),
    )
    .with_entity(Entity {
        id: entity(10),
        world_id: world(),
    })
    .with_entity(Entity {
        id: entity(11),
        world_id: world(),
    })
    .with_relationship(pair_relationship(relationship_id), false);
    let inactive_error = engine
        .validate(
            &BaseWorldView::new(inactive_base),
            OWNER,
            Resolution::new(
                vec![
                    proposed_event(23).with_effect(WorldEffect::CreateRelationship {
                        relationship_id,
                        relationship_type: RelationshipTypeId::from("counter.pair"),
                        participants: pair_participants(),
                    }),
                ],
                Vec::new(),
            ),
        )
        .expect_err("an inactive base Relationship identity must not be reused");
    assert!(matches!(
        inactive_error,
        super::RuntimeError::Validation(ValidationError::DuplicateIdentity {
            kind: "Relationship",
            ..
        })
    ));
}

#[test]
fn relationship_identity_allows_new_and_rejects_existing_active_ids() {
    let registry = registry();
    let engine = EffectEngine::new(&registry);
    let new_relationship = proposed_event(24).with_effect(WorldEffect::CreateRelationship {
        relationship_id: relationship(24),
        relationship_type: RelationshipTypeId::from("counter.pair"),
        participants: pair_participants(),
    });
    engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![new_relationship], Vec::new()),
        )
        .expect("a never-before-used Relationship identity should be valid");

    let active_base = BaseWorldSnapshot::new(
        world(),
        timeline(),
        TimelineVersion::new(EventSeq::new(4), StateRevision::new(4)),
        WorldInstant::new(4),
    )
    .with_entity(Entity {
        id: entity(10),
        world_id: world(),
    })
    .with_entity(Entity {
        id: entity(11),
        world_id: world(),
    })
    .with_relationship(pair_relationship(relationship(25)), true);
    let active_error = engine
        .validate(
            &BaseWorldView::new(active_base),
            OWNER,
            Resolution::new(
                vec![
                    proposed_event(25).with_effect(WorldEffect::CreateRelationship {
                        relationship_id: relationship(25),
                        relationship_type: RelationshipTypeId::from("counter.pair"),
                        participants: pair_participants(),
                    }),
                ],
                Vec::new(),
            ),
        )
        .expect_err("an active Relationship identity must not be reused");
    assert!(matches!(
        active_error,
        super::RuntimeError::Validation(ValidationError::DuplicateIdentity {
            kind: "Relationship",
            ..
        })
    ));
}

#[test]
fn proposer_cannot_mutate_another_capabilitys_facet() {
    let event = proposed_event(1).with_effect(WorldEffect::PutFacet {
        owner: FacetOwner::entity(entity(10)),
        facet_type: FacetTypeId::from("counter.value"),
        schema_revision: SchemaRevision::new(1),
        value: json!({"value": 2}),
    });
    let registry = registry();
    let error = EffectEngine::new(&registry)
        .validate(
            &base_view(),
            OTHER_OWNER,
            Resolution::new(vec![event], Vec::new()),
        )
        .expect_err("cross-capability direct mutation must be rejected");
    assert!(matches!(
        error,
        super::RuntimeError::Validation(ValidationError::SemanticOwnerMismatch { .. })
    ));
}

#[test]
fn causal_links_accept_ancestry_and_prior_batch_events() {
    let mut first = proposed_event(1);
    first.causal_links.push(CausalLink::new(event(100)));
    let mut second = proposed_event(2);
    second.causal_links.push(CausalLink::new(event(1)));
    let registry = registry();
    EffectEngine::new(&registry)
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![first, second], Vec::new()),
        )
        .expect("ancestry and prior batch causes are valid");
}

#[test]
fn forward_and_cyclic_causal_links_are_rejected() {
    let mut forward = proposed_event(1);
    forward.causal_links.push(CausalLink::new(event(2)));
    let second = proposed_event(2);
    let registry = registry();
    let engine = EffectEngine::new(&registry);
    let forward_error = engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![forward, second], Vec::new()),
        )
        .expect_err("forward causal links are invalid");
    assert!(matches!(
        forward_error,
        super::RuntimeError::Validation(ValidationError::InvalidCausalReference { .. })
    ));

    let mut first = proposed_event(3);
    first.causal_links.push(CausalLink::new(event(4)));
    let mut second = proposed_event(4);
    second.causal_links.push(CausalLink::new(event(3)));
    let cycle_error = engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![first, second], Vec::new()),
        )
        .expect_err("cyclic causal links are invalid");
    assert!(matches!(
        cycle_error,
        super::RuntimeError::Validation(ValidationError::InvalidCausalReference { .. })
    ));
}

#[test]
fn event_identity_collision_spans_ancestry_and_batch() {
    let registry = registry();
    let engine = EffectEngine::new(&registry);

    let ancestry_error = engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![proposed_event(100)], Vec::new()),
        )
        .expect_err("an ancestry Event identity must not be reused");
    assert!(matches!(
        ancestry_error,
        super::RuntimeError::Validation(ValidationError::DuplicateIdentity { kind: "Event", .. })
    ));

    engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![proposed_event(101)], Vec::new()),
        )
        .expect("a new Event identity should be valid");

    let first = proposed_event(102);
    let second = proposed_event(102);
    let batch_error = engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![first, second], Vec::new()),
        )
        .expect_err("a batch-local Event identity must not be reused");
    assert!(matches!(
        batch_error,
        super::RuntimeError::Validation(ValidationError::DuplicateIdentity { kind: "Event", .. })
    ));
}

#[test]
fn zero_effect_event_is_valid_when_event_metadata_is_valid() {
    let registry = registry();
    let validated = EffectEngine::new(&registry)
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![proposed_event(1)], Vec::new()),
        )
        .expect("an Event can record a fact without an Effect");
    assert_eq!(validated.events().len(), 1);
    assert!(validated.events()[0].effects.is_empty());
}

#[test]
fn invalid_event_payload_cannot_produce_validated_resolution() {
    let mut invalid = proposed_event(1);
    invalid.payload = json!({"value": "not-an-integer"});
    let registry = registry();
    let error = EffectEngine::new(&registry)
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![invalid], Vec::new()),
        )
        .expect_err("Event payload schema must be enforced");
    assert!(matches!(
        error,
        super::RuntimeError::Validation(ValidationError::SchemaViolation {
            kind: loom_capability::SemanticKind::Event,
            ..
        })
    ));
}

#[test]
fn invalid_facet_candidate_cannot_produce_validated_resolution() {
    let event = proposed_event(1).with_effect(WorldEffect::PutFacet {
        owner: FacetOwner::entity(entity(10)),
        facet_type: FacetTypeId::from("counter.value"),
        schema_revision: SchemaRevision::new(1),
        value: json!({"value": "not-an-integer"}),
    });
    let registry = registry();
    let error = EffectEngine::new(&registry)
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![event], Vec::new()),
        )
        .expect_err("Facet candidate schema must be enforced");
    assert!(matches!(
        error,
        super::RuntimeError::Validation(ValidationError::SchemaViolation {
            kind: loom_capability::SemanticKind::Facet,
            ..
        })
    ));
}

#[test]
fn validated_resolution_can_only_result_from_engine_validation() {
    let registry = registry();
    let validated = EffectEngine::new(&registry)
        .validate(&base_view(), OWNER, Resolution::default())
        .expect("empty resolution is a valid no-change candidate");
    assert_eq!(validated.timeline_id(), timeline());
    assert!(validated.resolution().events.is_empty());
    assert!(validated.resolution().work.is_empty());
}

#[test]
fn capability_rejection_stays_a_normal_outcome() {
    let rejection = Rejection::new("counter.invalid", "value must be positive");
    let registry = registry();
    let outcome = EffectEngine::new(&registry)
        .validate_outcome(
            &base_view(),
            OWNER,
            ResolveOutcome::Rejected(rejection.clone()),
        )
        .expect("Capability rejection is not a Runtime error");
    assert!(matches!(outcome, ValidationOutcome::Rejected(actual) if actual == rejection));
}

struct CandidateFacetInvariant;

impl Invariant for CandidateFacetInvariant {
    fn validate(&self, view: &dyn CapabilityCandidateWorldView) -> Result<(), InvariantViolation> {
        let value = view
            .get_facet(
                FacetOwner::entity(entity(10)),
                &FacetTypeId::from("counter.value"),
            )
            .map_err(|error| InvariantViolation::new("read_failed", error.to_string()))?
            .expect("test candidate facet should exist")
            .value;
        if value == json!({"value": 2}) {
            Ok(())
        } else {
            Err(InvariantViolation::new(
                "wrong_candidate_value",
                "candidate Facet did not include the prior Effect",
            ))
        }
    }
}

struct BasicCapability {
    manifest: CapabilityManifest,
}

impl Capability for BasicCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(
        &self,
        registrar: &mut CapabilityRegistrar,
    ) -> Result<(), loom_capability::RegistrationError> {
        register_basic_semantics(registrar)
    }
}

struct SpiCapability {
    manifest: CapabilityManifest,
}

impl Capability for SpiCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(
        &self,
        registrar: &mut CapabilityRegistrar,
    ) -> Result<(), loom_capability::RegistrationError> {
        register_basic_semantics(registrar)?;
        registrar.register_invariant(CandidateFacetInvariant);
        Ok(())
    }
}

#[test]
fn capability_registry_metadata_and_invariants_feed_runtime_validation() {
    let capability = SpiCapability {
        manifest: CapabilityManifest::parse("counter", "0.1.0")
            .expect("test Capability manifest should parse"),
    };
    let capability_registry = CapabilityRegistry::assemble(vec![capability])
        .expect("Capability registry should assemble");
    let engine = EffectEngine::from_capability_registry(&capability_registry)
        .expect("Capability metadata should project into Runtime");
    let event = proposed_event(1).with_effect(WorldEffect::PutFacet {
        owner: FacetOwner::entity(entity(10)),
        facet_type: FacetTypeId::from("counter.value"),
        schema_revision: SchemaRevision::new(1),
        value: json!({"value": 2}),
    });
    engine
        .validate(
            &base_view(),
            OWNER,
            Resolution::new(vec![event], Vec::new()),
        )
        .expect("Capability invariant should observe candidate overlay");
}
