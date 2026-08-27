//! T14-local causal fixture.
//!
//! The production suite remains public-API-only. This module composes a
//! minimal test Capability and Runtime so CV-026 can exercise causal input
//! through the public Action/History traits without changing shared fixtures.

#![allow(dead_code)]

use loom_api::{
    ActionInvocation, ActionRequest, CausalDirection, CausalQuery, CreateWorldFromTemplateRequest,
    EventQuery, EventRef, ExecutionResult, FacetOwner, FacetTypeId, ForkTimelineRequest, LoomApi,
    WorldInstant, WorldTemplateDescriptor,
};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EventDefinition, FacetDefinition, ResolutionContext, ResolverError,
};
use loom_core::{ActionTypeId, EntityId, EventId, EventTypeId, SchemaRevision, WorldEffect};
use loom_neutral::registry as neutral_registry;
use loom_protocol::{CausalLink, ProposedEvent, Resolution, ResolveOutcome};
use loom_runtime::{
    PlatformTime, Runtime, RuntimeRevisionCapability, RuntimeRevisionDescriptor, RuntimeRevisionId,
    WorldRuntimeBindingStore,
};
use loom_storage::InMemoryStore;
use serde_json::{Value, json};
use uuid::Uuid;

const CAPABILITY: &str = "t14.causal.counter";
const FACET: &str = "t14.causal.counter.value";
const SEED_ACTION: &str = "t14.causal.counter.seed";
const INCREMENT_ACTION: &str = "t14.causal.counter.increment";
const SEEDED_EVENT: &str = "t14.causal.counter.seeded";
const INCREMENTED_EVENT: &str = "t14.causal.counter.incremented";

struct CausalCounter;

impl Capability for CausalCounter {
    fn manifest(&self) -> &CapabilityManifest {
        static MANIFEST: std::sync::OnceLock<CapabilityManifest> = std::sync::OnceLock::new();
        MANIFEST.get_or_init(|| {
            CapabilityManifest::parse(CAPABILITY, "0.1.0")
                .expect("causal fixture manifest should parse")
        })
    }

    fn register(
        &self,
        registrar: &mut CapabilityRegistrar,
    ) -> Result<(), loom_capability::RegistrationError> {
        registrar.register_facet(FacetDefinition::new(
            FacetTypeId::from(FACET),
            SchemaRevision::new(1),
            json!({
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "integer"}}
            }),
        ))?;
        registrar.register_event(
            EventDefinition::new(EventTypeId::from(SEEDED_EVENT), SchemaRevision::new(1))
                .with_payload_schema(counter_event_schema()),
        )?;
        registrar.register_event(
            EventDefinition::new(EventTypeId::from(INCREMENTED_EVENT), SchemaRevision::new(1))
                .with_payload_schema(counter_event_schema()),
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(SEED_ACTION), SchemaRevision::new(1))
                .with_input_schema(json!({
                    "type": "object",
                    "required": ["event_id", "entity_id", "value"],
                    "properties": {
                        "event_id": {"type": "string"},
                        "entity_id": {"type": "string"},
                        "value": {"type": "integer"}
                    }
                })),
            SeedResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(INCREMENT_ACTION), SchemaRevision::new(1))
                .with_input_schema(json!({
                    "type": "object",
                    "required": ["event_id", "entity_id", "amount"],
                    "properties": {
                        "event_id": {"type": "string"},
                        "entity_id": {"type": "string"},
                        "amount": {"type": "integer"},
                        "cause_event_id": {"type": "string"}
                    }
                })),
            IncrementResolver,
        )?;
        Ok(())
    }
}

struct SeedResolver;

impl ActionResolver for SeedResolver {
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
            EventTypeId::from(SEEDED_EVENT),
            SchemaRevision::new(1),
            json!({"entity_id": entity_id.to_string(), "value": value}),
        )
        .with_effect(WorldEffect::CreateEntity { entity_id })
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity_id),
            facet_type: FacetTypeId::from(FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": value}),
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

struct IncrementResolver;

impl ActionResolver for IncrementResolver {
    fn resolve(
        &self,
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
            .get_facet(FacetOwner::entity(entity_id), &FacetTypeId::from(FACET))?
            .ok_or_else(|| ResolverError::new("counter Facet is missing"))?
            .value
            .get("value")
            .and_then(Value::as_i64)
            .ok_or_else(|| ResolverError::new("counter value must be an integer"))?;
        let value = current
            .checked_add(amount)
            .ok_or_else(|| ResolverError::new("counter value overflowed"))?;
        let mut event = ProposedEvent::new(
            event_id,
            EventTypeId::from(INCREMENTED_EVENT),
            SchemaRevision::new(1),
            json!({"entity_id": entity_id.to_string(), "previous": current, "amount": amount, "value": value}),
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity_id),
            facet_type: FacetTypeId::from(FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": value}),
        });
        if let Some(cause) = input.get("cause_event_id") {
            let cause_id = cause
                .as_str()
                .ok_or_else(|| ResolverError::new("cause_event_id must be a UUID string"))?
                .parse()
                .map_err(|_| ResolverError::new("cause_event_id must be a UUID string"))?;
            event = event.with_causal_link(CausalLink::new(cause_id));
        }
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

fn counter_event_schema() -> Value {
    json!({
        "type": "object",
        "required": ["entity_id", "value"],
        "properties": {
            "entity_id": {"type": "string"},
            "previous": {"type": "integer"},
            "amount": {"type": "integer"},
            "value": {"type": "integer"}
        }
    })
}

fn parse_id<T>(input: &Value, key: &str) -> Result<T, ResolverError>
where
    T: std::str::FromStr,
{
    input
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| ResolverError::new(format!("{key} must be a UUID string")))?
        .parse()
        .map_err(|_| ResolverError::new(format!("{key} must be a UUID string")))
}

fn event(value: u128) -> EventId {
    EventId::new(Uuid::from_u128(value))
}

fn entity(value: u128) -> EntityId {
    EntityId::new(Uuid::from_u128(value))
}

fn fixture_runtime() -> &'static tokio::runtime::Runtime {
    static RUNTIME: std::sync::OnceLock<&'static tokio::runtime::Runtime> =
        std::sync::OnceLock::new();
    RUNTIME.get_or_init(|| {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("causal fixture test runtime should build");
        Box::leak(Box::new(runtime))
    })
}

fn fixture_registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([CausalCounter]).expect("causal fixture registry should assemble")
}

fn activate_fixture_revision(store: &InMemoryStore, registry: &CapabilityRegistry) {
    let descriptor = RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("t14-causal-fixture-v0"),
        PlatformTime::default(),
        "t14-causal-fixture",
        registry.loom_version().clone(),
        registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("t14-causal-fixture:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("causal fixture revision should be valid");
    store
        .confirm_revision(descriptor.clone())
        .expect("causal fixture revision should publish");
    let active = store
        .read_active_revision()
        .expect("causal fixture active revision should be readable");
    if active
        .as_ref()
        .is_none_or(|selection| selection.revision().id() != descriptor.id())
    {
        store
            .activate_revision(
                descriptor.id().clone(),
                active
                    .as_ref()
                    .map(loom_runtime::RuntimeRevisionSelection::generation),
                PlatformTime::default(),
            )
            .expect("causal fixture revision should activate");
    }
}

/// Executes the CV-026 causal contract through the public Runtime API traits.
///
/// # Panics
///
/// Panics when the controlled fixture cannot be assembled or a required
/// public-surface assertion is not satisfied.
#[allow(clippy::too_many_lines)]
pub fn verify() {
    let store = InMemoryStore::new();
    let registry = fixture_registry();
    activate_fixture_revision(&store, &registry);
    let runtime = Runtime::new(&store, registry).expect("causal fixture Runtime should assemble");
    let api: &dyn LoomApi = &runtime;
    let parent = fixture_runtime()
        .block_on(
            api.create_world_from_template(CreateWorldFromTemplateRequest::new(
                WorldTemplateDescriptor::new(
                    "validator.t14.cv026.causal-fixture",
                    1,
                    WorldInstant::new(42),
                )
                .requires_capability(CAPABILITY, "^0.1.0"),
            )),
        )
        .expect("causal fixture World should be created")
        .target;
    let entity_id = entity(0x2601);
    let seed_id = event(0x2602);
    let seed = fixture_runtime().block_on(api.invoke(ActionRequest::new(
        parent,
        ActionInvocation::new(
            ActionTypeId::from(SEED_ACTION),
            json!({"event_id": seed_id.to_string(), "entity_id": entity_id.to_string(), "value": 5}),
        ),
    )))
    .expect("ancestor seed should commit");
    let ExecutionResult::Committed { event_ids, .. } = seed else {
        panic!("ancestor seed should return committed result");
    };
    assert_eq!(event_ids, vec![seed_id]);
    let ancestor = EventRef::new(parent.timeline_id, seed_id);
    let child = fixture_runtime()
        .block_on(api.fork(ForkTimelineRequest::new(parent)))
        .expect("causal fixture child should fork")
        .target;
    let sibling = fixture_runtime()
        .block_on(api.fork(ForkTimelineRequest::new(parent)))
        .expect("causal fixture sibling should fork")
        .target;
    let child_id = event(0x2603);
    let child_result = fixture_runtime().block_on(api.invoke(ActionRequest::new(
        child,
        ActionInvocation::new(
            ActionTypeId::from(INCREMENT_ACTION),
            json!({"event_id": child_id.to_string(), "entity_id": entity_id.to_string(), "amount": 10, "cause_event_id": seed_id.to_string()}),
        ),
    )))
    .expect("child causal action should commit");
    assert!(matches!(child_result, ExecutionResult::Committed { .. }));
    let child_ref = EventRef::new(child.timeline_id, child_id);
    let causes = fixture_runtime()
        .block_on(api.direct_causes(child_ref))
        .expect("child direct causes should be readable");
    assert_eq!(causes, vec![ancestor]);
    let walk = fixture_runtime()
        .block_on(api.causal_walk(CausalQuery::new(child_ref, CausalDirection::Causes, 4, 10)))
        .expect("child causal walk should be readable");
    assert_eq!(walk.events, vec![ancestor]);
    assert!(!walk.truncated);
    let sibling_seed_ref = EventRef::new(sibling.timeline_id, seed_id);
    let parent_effects = fixture_runtime()
        .block_on(api.direct_effects(ancestor))
        .expect("parent direct effects should be readable");
    assert!(!parent_effects.contains(&child_ref));
    assert!(!parent_effects.contains(&sibling_seed_ref));
    assert!(
        parent_effects
            .iter()
            .all(|event_ref| event_ref.timeline_id != sibling.timeline_id)
    );
    let child_events = fixture_runtime()
        .block_on(api.list_events(EventQuery::all(child)))
        .expect("child history should be readable");
    let sibling_events_before = fixture_runtime()
        .block_on(api.list_events(EventQuery::all(sibling)))
        .expect("sibling history should be readable");
    assert_eq!(child_events.len(), 2);
    assert_eq!(sibling_events_before.len(), 1);
    assert_eq!(child_events[0].id, seed_id);
    assert_eq!(child_events[1].id, child_id);
    assert!(
        child_events
            .windows(2)
            .all(|events| { events[0].sequence.value() < events[1].sequence.value() })
    );
    let parent_events_before = fixture_runtime()
        .block_on(api.list_events(EventQuery::all(parent)))
        .expect("parent history before rejection should be readable");
    let invalid_id = event(0x2604);
    let invalid = fixture_runtime().block_on(api.invoke(ActionRequest::new(
        sibling,
        ActionInvocation::new(
            ActionTypeId::from(INCREMENT_ACTION),
            json!({"event_id": invalid_id.to_string(), "entity_id": entity_id.to_string(), "amount": 7, "cause_event_id": child_id.to_string()}),
        ),
    )));
    assert!(
        invalid.is_err(),
        "sibling causal reference must be rejected"
    );
    let sibling_events_after = fixture_runtime()
        .block_on(api.list_events(EventQuery::all(sibling)))
        .expect("sibling history after rejection should be readable");
    let parent_events_after = fixture_runtime()
        .block_on(api.list_events(EventQuery::all(parent)))
        .expect("parent history after rejection should be readable");
    let child_events_after = fixture_runtime()
        .block_on(api.list_events(EventQuery::all(child)))
        .expect("child history after rejection should be readable");
    assert_eq!(sibling_events_after, sibling_events_before);
    assert_eq!(parent_events_after, parent_events_before);
    assert_eq!(child_events_after, child_events);
    assert!(
        !sibling_events_after
            .iter()
            .any(|event| event.id == invalid_id)
    );
}

/// Creates a World and immutable Binding while a revision is active, then
/// observes that same bound World through a fresh no-active Runtime.
///
/// # Panics
///
/// Panics when the controlled fixture cannot be assembled or the public
/// Catalog surface returns an unexpected result.
pub fn verify_bound_world_without_active_revision() {
    let active_store = InMemoryStore::new();
    let active_registry = neutral_registry();
    activate_fixture_revision(&active_store, &active_registry);
    let active_runtime =
        Runtime::new(&active_store, active_registry).expect("active catalog fixture should build");
    let active_api: &dyn LoomApi = &active_runtime;
    let snapshot = fixture_runtime()
        .block_on(
            active_api.create_world_from_template(CreateWorldFromTemplateRequest::new(
                WorldTemplateDescriptor::new(
                    "validator.t14.cv027.bound-world",
                    1,
                    WorldInstant::new(42),
                )
                .requires_capability("neutral.counter", "^0.1.0"),
            )),
        )
        .expect("bound World should be created while revision is active")
        .target;
    let binding = fixture_runtime()
        .block_on(WorldRuntimeBindingStore::read_binding(
            &active_store,
            snapshot.world_id,
        ))
        .expect("created World should retain immutable Binding");

    let no_active_store = InMemoryStore::new();
    no_active_store
        .create_world(snapshot.world_id)
        .expect("bound World identity should be retained in no-active fixture");
    no_active_store
        .create_timeline(snapshot.world_id, snapshot.timeline_id)
        .expect("bound World Timeline should be retained in no-active fixture");
    fixture_runtime()
        .block_on(WorldRuntimeBindingStore::persist_binding(
            &no_active_store,
            snapshot.world_id,
            binding,
        ))
        .expect("immutable Binding should be retained in no-active fixture");
    let no_active_registry = neutral_registry();
    let no_active_runtime = Runtime::new(&no_active_store, no_active_registry)
        .expect("no-active catalog fixture should build");
    let no_active_api: &dyn LoomApi = &no_active_runtime;
    let global = no_active_api
        .catalog()
        .expect("installed global catalog should remain observable");
    assert!(
        global
            .capabilities
            .iter()
            .any(|capability| capability.id.to_string() == "neutral.counter")
    );
    let scoped = fixture_runtime().block_on(no_active_api.catalog_for_world(snapshot.world_id));
    match scoped {
        Ok(catalog) => panic!(
            "bound World catalog must not fall back to global catalog without active revision: {catalog:?}"
        ),
        Err(error) => assert!(
            matches!(
                error.code,
                loom_api::ApiErrorCode::Unavailable | loom_api::ApiErrorCode::NotFound
            ),
            "bound World should be unavailable/not found without active revision, got {:?}",
            error.code
        ),
    }
}
