//! Approved concrete neutral Capabilities installed by the Loom composition root.

use std::str::FromStr;

use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EventDefinition, Reaction, RegistrationError, RelationshipDefinition,
    RelationshipRole, ResolutionContext, ResolverError, SemanticIndexDefinition,
    SemanticIndexMetric, SemanticIndexSource, WorkHandler, WorkHandlerDefinition,
};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventTypeId, FacetOwner, FacetTypeId, RelationshipId,
    RelationshipTypeId, SchemaRevision, WorkHandlerId, WorldEffect,
};
use loom_protocol::{ProposedEvent, Resolution, ResolveOutcome};
use semver::VersionReq;
use serde_json::{Value, json};

/// Neutral Capability that owns a small integer Facet and its mutations.
pub const COUNTER_CAPABILITY: &str = "neutral.counter";
/// Neutral Capability that observes the counter through a dependent semantic module.
pub const OBSERVER_CAPABILITY: &str = "neutral.observer";
/// Counter Facet semantic key.
pub const COUNTER_FACET: &str = "neutral.counter.value";
/// Action that creates an Entity and its initial counter Facet.
pub const COUNTER_SEED_ACTION: &str = "neutral.counter.seed";
/// Action that increments the counter Facet.
pub const COUNTER_INCREMENT_ACTION: &str = "neutral.counter.increment";
/// Event emitted by the counter seed Action.
pub const COUNTER_SEEDED_EVENT: &str = "neutral.counter.seeded";
/// Event emitted by the counter increment Action.
pub const COUNTER_INCREMENTED_EVENT: &str = "neutral.counter.incremented";
/// Durable Work handler that reuses counter increment semantics.
pub const COUNTER_INCREMENT_WORK: &str = "neutral.counter.increment_work";
/// Observer Action semantic key.
pub const OBSERVER_ACTION: &str = "neutral.observer.observe";
/// Observer Event semantic key.
pub const OBSERVER_EVENT: &str = "neutral.observer.observed";
/// Observer Work handler semantic key.
pub const OBSERVER_WORK: &str = "neutral.observer.observe_work";
/// Neutral membership Relationship semantic key (Entity/Relationship demonstration).
pub const LINK_RELATIONSHIP: &str = "neutral.link.membership";
/// Action that creates a neutral membership Relationship linking two Entities.
pub const LINK_CREATE_ACTION: &str = "neutral.link.create";
/// Event emitted by the link creation Action.
pub const LINK_CREATED_EVENT: &str = "neutral.link.created";
/// Facet that holds an immutable blob reference for an Entity.
pub const BLOB_FACET: &str = "neutral.blob.reference";
/// Action that attaches a blob reference to an Entity (blob-reference demonstration).
pub const BLOB_ATTACH_ACTION: &str = "neutral.blob.attach";
/// Event emitted by the blob attach Action.
pub const BLOB_ATTACHED_EVENT: &str = "neutral.blob.attached";
/// Semantic index that projects the counter Facet (semantic retrieval demonstration).
pub const SEMANTIC_INDEX_ID: &str = "neutral.counter.semantic";

/// Builds the globally installed registry for the approved neutral extensions.
///
/// Both manifests and their semantic registrations are assembled through the
/// standard registry API. The observer explicitly declares its counter
/// dependency, so the resulting catalog contains the complete installed
/// capability/action set used by the composition root.
///
/// # Panics
///
/// Panics only if the checked-in manifests, dependency declaration or semantic
/// registrations are internally inconsistent.
#[must_use]
pub fn registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble(vec![
        Box::new(CounterCapability {
            manifest: CapabilityManifest::parse(COUNTER_CAPABILITY, "0.1.0")
                .expect("neutral counter manifest should parse"),
        }) as Box<dyn Capability>,
        Box::new(ObserverCapability {
            manifest: CapabilityManifest::parse(OBSERVER_CAPABILITY, "0.1.0")
                .expect("neutral observer manifest should parse")
                .requires_version(
                    COUNTER_CAPABILITY,
                    VersionReq::parse("^0.1.0")
                        .expect("neutral dependency requirement should parse"),
                ),
        }) as Box<dyn Capability>,
    ])
    .expect("neutral Capability registry should assemble")
}

struct CounterCapability {
    manifest: CapabilityManifest,
}

impl Capability for CounterCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    #[allow(clippy::too_many_lines)]
    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_facet(
            loom_capability::FacetDefinition::new(
                FacetTypeId::from(COUNTER_FACET),
                SchemaRevision::new(1),
                json!({
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"type": "integer"}}
                }),
            )
            .with_description("A neutral integer counter Facet."),
        )?;
        registrar.register_facet(
            loom_capability::FacetDefinition::new(
                FacetTypeId::from(BLOB_FACET),
                SchemaRevision::new(1),
                json!({
                    "type": "object",
                    "required": ["hash", "media_type"],
                    "properties": {
                        "hash": {"type": "string"},
                        "media_type": {"type": "string"}
                    }
                }),
            )
            .with_description("A neutral blob reference retained as an Entity Facet."),
        )?;
        registrar.register_relationship(
            RelationshipDefinition::new(
                RelationshipTypeId::from(LINK_RELATIONSHIP),
                SchemaRevision::new(1),
            )
            .with_role(RelationshipRole::new("member".into(), 2, Some(2)))
            .with_description("A neutral membership linking two Entities."),
        )?;
        registrar.register_event(
            EventDefinition::new(
                EventTypeId::from(COUNTER_SEEDED_EVENT),
                SchemaRevision::new(1),
            )
            .with_payload_schema(json!({
                "type": "object",
                "required": ["entity_id", "value"],
                "properties": {
                    "entity_id": {"type": "string"},
                    "value": {"type": "integer"}
                }
            })),
        )?;
        registrar.register_event(
            EventDefinition::new(
                EventTypeId::from(COUNTER_INCREMENTED_EVENT),
                SchemaRevision::new(1),
            )
            .with_payload_schema(json!({
                "type": "object",
                "required": ["entity_id", "previous", "amount", "value"],
                "properties": {
                    "entity_id": {"type": "string"},
                    "previous": {"type": "integer"},
                    "amount": {"type": "integer"},
                    "value": {"type": "integer"}
                }
            })),
        )?;
        registrar.register_event(
            EventDefinition::new(
                EventTypeId::from(LINK_CREATED_EVENT),
                SchemaRevision::new(1),
            )
            .with_payload_schema(json!({
                "type": "object",
                "required": ["relationship_id", "left_entity", "right_entity"],
                "properties": {
                    "relationship_id": {"type": "string"},
                    "left_entity": {"type": "string"},
                    "right_entity": {"type": "string"}
                }
            })),
        )?;
        registrar.register_event(
            EventDefinition::new(
                EventTypeId::from(BLOB_ATTACHED_EVENT),
                SchemaRevision::new(1),
            )
            .with_payload_schema(json!({
                "type": "object",
                "required": ["entity_id", "hash", "media_type"],
                "properties": {
                    "entity_id": {"type": "string"},
                    "hash": {"type": "string"},
                    "media_type": {"type": "string"}
                }
            })),
        )?;
        registrar.register_action(
            ActionDefinition::new(
                ActionTypeId::from(COUNTER_SEED_ACTION),
                SchemaRevision::new(1),
            )
            .with_input_schema(json!({
                "type": "object",
                "required": ["event_id", "entity_id", "value"],
                "properties": {
                    "event_id": {"type": "string"},
                    "entity_id": {"type": "string"},
                    "value": {"type": "integer"}
                }
            })),
            SeedCounterResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(
                ActionTypeId::from(COUNTER_INCREMENT_ACTION),
                SchemaRevision::new(1),
            )
            .with_input_schema(counter_mutation_schema()),
            IncrementCounterResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(
                ActionTypeId::from(LINK_CREATE_ACTION),
                SchemaRevision::new(1),
            )
            .with_input_schema(json!({
                "type": "object",
                "required": ["event_id", "relationship_id", "left_entity", "right_entity"],
                "properties": {
                    "event_id": {"type": "string"},
                    "relationship_id": {"type": "string"},
                    "left_entity": {"type": "string"},
                    "right_entity": {"type": "string"}
                }
            })),
            CreateLinkResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(
                ActionTypeId::from(BLOB_ATTACH_ACTION),
                SchemaRevision::new(1),
            )
            .with_input_schema(json!({
                "type": "object",
                "required": ["event_id", "entity_id", "hash", "media_type"],
                "properties": {
                    "event_id": {"type": "string"},
                    "entity_id": {"type": "string"},
                    "hash": {"type": "string"},
                    "media_type": {"type": "string"}
                }
            })),
            AttachBlobResolver,
        )?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(
                WorkHandlerId::from(COUNTER_INCREMENT_WORK),
                SchemaRevision::new(1),
            )
            .with_payload_schema(counter_mutation_schema()),
            IncrementCounterResolver,
        )?;
        registrar.register_reaction(Reaction::new(
            EventTypeId::from(COUNTER_INCREMENTED_EVENT),
            WorkHandlerId::from(COUNTER_INCREMENT_WORK),
        ))?;
        registrar.register_semantic_index(SemanticIndexDefinition::new(
            SEMANTIC_INDEX_ID,
            SemanticIndexSource::new("facet", COUNTER_FACET, SchemaRevision::new(1)),
            SchemaRevision::new(1),
            1,
            "neutral-model-1",
            2,
            SemanticIndexMetric::Cosine,
            json!({"normalization": "unit"}),
        ))?;
        Ok(())
    }
}

struct ObserverCapability {
    manifest: CapabilityManifest,
}

impl Capability for ObserverCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_event(
            EventDefinition::new(EventTypeId::from(OBSERVER_EVENT), SchemaRevision::new(1))
                .with_payload_schema(json!({
                    "type": "object",
                    "required": ["entity_id", "value"],
                    "properties": {
                        "entity_id": {"type": "string"},
                        "value": {"type": "integer"}
                    }
                })),
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(OBSERVER_ACTION), SchemaRevision::new(1))
                .with_input_schema(json!({
                    "type": "object",
                    "required": ["event_id", "entity_id"],
                    "properties": {
                        "event_id": {"type": "string"},
                        "entity_id": {"type": "string"}
                    }
                })),
            ObserveCounterResolver,
        )?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(WorkHandlerId::from(OBSERVER_WORK), SchemaRevision::new(1))
                .with_payload_schema(json!({
                    "type": "object",
                    "required": ["event_id", "entity_id"],
                    "properties": {
                        "event_id": {"type": "string"},
                        "entity_id": {"type": "string"}
                    }
                })),
            ObserveCounterResolver,
        )?;
        registrar.register_reaction(Reaction::new(
            EventTypeId::from(OBSERVER_EVENT),
            WorkHandlerId::from(OBSERVER_WORK),
        ))?;
        Ok(())
    }
}

fn counter_mutation_schema() -> Value {
    json!({
        "type": "object",
        "required": ["event_id", "entity_id", "amount"],
        "properties": {
            "event_id": {"type": "string"},
            "entity_id": {"type": "string"},
            "amount": {"type": "integer"}
        }
    })
}

struct SeedCounterResolver;

impl ActionResolver for SeedCounterResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id::<EventId>(input, "event_id")?;
        let entity_id = parse_id::<EntityId>(input, "entity_id")?;
        let value = input
            .get("value")
            .and_then(Value::as_i64)
            .ok_or_else(|| ResolverError::new("value must be an integer"))?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(COUNTER_SEEDED_EVENT),
            SchemaRevision::new(1),
            json!({"entity_id": entity_id.to_string(), "value": value}),
        )
        .with_effect(WorldEffect::CreateEntity { entity_id })
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity_id),
            facet_type: FacetTypeId::from(COUNTER_FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": value}),
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

struct IncrementCounterResolver;

impl IncrementCounterResolver {
    fn resolve_increment(
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id::<EventId>(input, "event_id")?;
        let entity_id = parse_id::<EntityId>(input, "entity_id")?;
        let amount = input
            .get("amount")
            .and_then(Value::as_i64)
            .ok_or_else(|| ResolverError::new("amount must be an integer"))?;
        let current = context
            .get_facet(
                FacetOwner::entity(entity_id),
                &FacetTypeId::from(COUNTER_FACET),
            )?
            .ok_or_else(|| ResolverError::new("counter Facet is missing"))?
            .value
            .get("value")
            .and_then(Value::as_i64)
            .ok_or_else(|| ResolverError::new("counter Facet value is not an integer"))?;
        let value = current
            .checked_add(amount)
            .ok_or_else(|| ResolverError::new("counter value overflowed"))?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(COUNTER_INCREMENTED_EVENT),
            SchemaRevision::new(1),
            json!({
                "entity_id": entity_id.to_string(),
                "previous": current,
                "amount": amount,
                "value": value,
            }),
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity_id),
            facet_type: FacetTypeId::from(COUNTER_FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": value}),
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

impl ActionResolver for IncrementCounterResolver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Self::resolve_increment(context, input)
    }
}

impl WorkHandler for IncrementCounterResolver {
    fn handle(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Self::resolve_increment(context, input)
    }
}

struct CreateLinkResolver;

impl ActionResolver for CreateLinkResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id::<EventId>(input, "event_id")?;
        let relationship_id = parse_id::<RelationshipId>(input, "relationship_id")?;
        let left_entity = parse_id::<EntityId>(input, "left_entity")?;
        let right_entity = parse_id::<EntityId>(input, "right_entity")?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(LINK_CREATED_EVENT),
            SchemaRevision::new(1),
            json!({
                "relationship_id": relationship_id.to_string(),
                "left_entity": left_entity.to_string(),
                "right_entity": right_entity.to_string(),
            }),
        )
        .with_effect(WorldEffect::CreateRelationship {
            relationship_id,
            relationship_type: RelationshipTypeId::from(LINK_RELATIONSHIP),
            participants: vec![
                loom_core::RelationshipParticipant::new(left_entity, "member"),
                loom_core::RelationshipParticipant::new(right_entity, "member"),
            ],
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

struct AttachBlobResolver;

impl ActionResolver for AttachBlobResolver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id::<EventId>(input, "event_id")?;
        let entity_id = parse_id::<EntityId>(input, "entity_id")?;
        let hash = input
            .get("hash")
            .and_then(Value::as_str)
            .ok_or_else(|| ResolverError::new("hash must be a string"))?;
        let media_type = input
            .get("media_type")
            .and_then(Value::as_str)
            .ok_or_else(|| ResolverError::new("media_type must be a string"))?;
        // Validate Entity exists via Facet presence or we allow blob attach only after counter exists.
        context
            .get_facet(
                FacetOwner::entity(entity_id),
                &FacetTypeId::from(COUNTER_FACET),
            )?
            .ok_or_else(|| ResolverError::new("counter Facet is missing for blob owner"))?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(BLOB_ATTACHED_EVENT),
            SchemaRevision::new(1),
            json!({
                "entity_id": entity_id.to_string(),
                "hash": hash,
                "media_type": media_type,
            }),
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity_id),
            facet_type: FacetTypeId::from(BLOB_FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"hash": hash, "media_type": media_type}),
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

struct ObserveCounterResolver;

impl ObserveCounterResolver {
    fn resolve_observation(
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id::<EventId>(input, "event_id")?;
        let entity_id = parse_id::<EntityId>(input, "entity_id")?;
        let value = context
            .get_facet(
                FacetOwner::entity(entity_id),
                &FacetTypeId::from(COUNTER_FACET),
            )?
            .ok_or_else(|| ResolverError::new("counter Facet is missing"))?
            .value
            .get("value")
            .and_then(Value::as_i64)
            .ok_or_else(|| ResolverError::new("counter Facet value is not an integer"))?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(OBSERVER_EVENT),
            SchemaRevision::new(1),
            json!({"entity_id": entity_id.to_string(), "value": value}),
        );
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

impl ActionResolver for ObserveCounterResolver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Self::resolve_observation(context, input)
    }
}

impl WorkHandler for ObserveCounterResolver {
    fn handle(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Self::resolve_observation(context, input)
    }
}

fn parse_id<T>(input: &Value, field: &str) -> Result<T, ResolverError>
where
    T: FromStr,
{
    input
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| ResolverError::new(format!("{field} must be a UUID string")))?
        .parse()
        .map_err(|_| ResolverError::new(format!("{field} must be a UUID string")))
}
