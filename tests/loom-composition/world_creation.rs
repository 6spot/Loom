use std::str::FromStr;

use loom_api::{
    ActionRequest, ApiErrorCode, CreateWorldFromTemplateRequest, EventQuery, LoomApi, WorldService,
    WorldTemplateDescriptor,
};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityId, CapabilityManifest,
    CapabilityRegistrar, CapabilityRegistry, EventDefinition, RegistrationError, ResolutionContext,
    ResolverError,
};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventTypeId, SchemaRevision, TimelineId, TimelineVersion,
    WorldEffect, WorldId, WorldInstant,
};
use loom_protocol::{ActionInvocation, ProposedEvent, Resolution, ResolveOutcome};
use loom_runtime::{ExecutionOrigin, ExecutionSessionStore, IdentityAllocator, PlatformTime, Runtime, RuntimeRevisionCapability, RuntimeRevisionDescriptor, RuntimeRevisionId};
use loom_storage::InMemoryStore;
use serde_json::{Value, json};

const CAPABILITY: &str = "bootstrap.basic";
const ACTION: &str = "bootstrap.create_entity";
const EVENT: &str = "bootstrap.entity_created";

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

#[derive(Clone, Copy)]
struct FixedIdentityAllocator {
    world_id: WorldId,
    timeline_id: TimelineId,
}

impl IdentityAllocator for FixedIdentityAllocator {
    fn allocate_world_id(&self) -> WorldId {
        self.world_id
    }

    fn allocate_timeline_id(&self) -> TimelineId {
        self.timeline_id
    }
}

struct BootstrapCapability {
    manifest: CapabilityManifest,
}

impl Capability for BootstrapCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_event(EventDefinition::new(
            EventTypeId::from(EVENT),
            SchemaRevision::new(1),
        ))?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(ACTION), SchemaRevision::new(1)),
            CreateEntityResolver,
        )?;
        Ok(())
    }
}

struct CreateEntityResolver;

impl ActionResolver for CreateEntityResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id::<EventId>(input, "event_id")?;
        let entity_id = parse_id::<EntityId>(input, "entity_id")?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(EVENT),
            SchemaRevision::new(1),
            json!({"entity_id": entity_id.to_string()}),
        )
        .with_effect(WorldEffect::CreateEntity { entity_id });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
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


fn ensure_bootstrap_revision(store: &InMemoryStore, reg: &CapabilityRegistry) {
    let descriptor = RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("bootstrap-explicit-v0"),
        PlatformTime::default(),
        "test-build",
        reg.loom_version().clone(),
        reg.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("test:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("bootstrap revision should be valid");
    store
        .confirm_revision(descriptor.clone())
        .expect("bootstrap revision should be confirmed");
    store
        .activate_revision(descriptor.id().clone(), None, PlatformTime::default())
        .expect("bootstrap revision should be activated");
}

fn registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([BootstrapCapability {
        manifest: CapabilityManifest::parse(CAPABILITY, "0.1.0")
            .expect("bootstrap manifest should parse"),
    }])
    .expect("bootstrap registry should assemble")
}

fn template_request(initial_world_time: WorldInstant) -> CreateWorldFromTemplateRequest {
    CreateWorldFromTemplateRequest::new(
        WorldTemplateDescriptor::new("bootstrap", 1, initial_world_time)
            .requires_capability(CAPABILITY, "^0.1.0"),
    )
}

#[tokio::test]
async fn template_world_creation_is_atomic_and_immediately_usable() {
    let store = InMemoryStore::new();
    let reg = registry();
    ensure_bootstrap_revision(&store, &reg);
    let world_id = id::<WorldId>(0x3001);
    let timeline_id = id::<TimelineId>(0x3002);
    let runtime = Runtime::new(&store, reg)
        .expect("Runtime should assemble")
        .with_identity_allocator(FixedIdentityAllocator {
            world_id,
            timeline_id,
        });
    let api: &dyn LoomApi = &runtime;

    let created = api
        .create_world_from_template(template_request(WorldInstant::new(42)))
        .await
        .expect("Template World creation should succeed");
    assert_eq!(created.target.world_id, world_id);
    assert_eq!(created.target.timeline_id, timeline_id);
    assert_eq!(created.version, TimelineVersion::default());
    assert_eq!(created.world_time, WorldInstant::new(42));
    let birth_sessions = ExecutionSessionStore::list_sessions(&store)
        .await
        .expect("Template Session should be persisted");
    assert_eq!(birth_sessions.len(), 1);
    assert_eq!(birth_sessions[0].origin(), ExecutionOrigin::Runtime);
    assert_eq!(birth_sessions[0].assembly().world_id(), world_id);
    assert_eq!(
        birth_sessions[0].status(),
        loom_runtime::ExecutionSessionStatus::Committed
    );

    let event_id = id::<EventId>(0x3010);
    let entity_id = id::<EntityId>(0x3020);
    let committed = api
        .invoke(ActionRequest::new(
            created.target,
            ActionInvocation::new(
                ActionTypeId::from(ACTION),
                json!({
                    "event_id": event_id.to_string(),
                    "entity_id": entity_id.to_string(),
                }),
            ),
        ))
        .await
        .expect("created Timeline should immediately accept semantic Actions");
    assert!(committed.is_committed());

    let history = api
        .list_events(EventQuery::all(created.target))
        .await
        .expect("created Timeline history should be readable");
    assert_eq!(history.len(), 1);
    assert_eq!(history[0].id, event_id);
    assert_eq!(history[0].occurred_at, WorldInstant::new(42));
    assert!(matches!(
        history[0].effects.as_slice(),
        [WorldEffect::CreateEntity { entity_id: actual }] if *actual == entity_id
    ));

    let duplicate = api
        .create_world_from_template(template_request(WorldInstant::new(99)))
        .await
        .expect_err("deterministically reused World identity must conflict");
    assert_eq!(duplicate.code, ApiErrorCode::Conflict);

    let after_conflict = api
        .inspect_timeline(created.target)
        .await
        .expect("failed bootstrap must not damage the existing Timeline");
    assert_eq!(after_conflict.world_time, WorldInstant::new(42));
    let history_after_conflict = api
        .list_events(EventQuery::all(created.target))
        .await
        .expect("existing history should survive failed duplicate bootstrap");
    assert_eq!(history_after_conflict, history);

    let conflicting_world_id = id::<WorldId>(0x3003);
    let timeline_conflict_runtime = Runtime::new(&store, registry())
        .expect("Timeline-conflict Runtime should assemble")
        .with_identity_allocator(FixedIdentityAllocator {
            world_id: conflicting_world_id,
            timeline_id,
        });
    let timeline_conflict = timeline_conflict_runtime
        .create_world_from_template(template_request(WorldInstant::new(70)))
        .await
        .expect_err("reused Timeline identity must conflict even with a fresh World identity");
    assert_eq!(timeline_conflict.code, ApiErrorCode::Conflict);

    let recovered_timeline_id = id::<TimelineId>(0x3004);
    let retry_runtime = Runtime::new(&store, registry())
        .expect("post-conflict Runtime should assemble")
        .with_identity_allocator(FixedIdentityAllocator {
            world_id: conflicting_world_id,
            timeline_id: recovered_timeline_id,
        });
    let recovered = retry_runtime
        .create_world_from_template(template_request(WorldInstant::new(77)))
        .await
        .expect("failed Timeline conflict must not leave a partial World");
    assert_eq!(recovered.target.world_id, conflicting_world_id);
    assert_eq!(recovered.target.timeline_id, recovered_timeline_id);
    assert_eq!(recovered.version, TimelineVersion::default());
    assert_eq!(recovered.world_time, WorldInstant::new(77));
}

#[tokio::test]
async fn template_birth_commits_bootstrap_and_snapshots_binding() {
    let store = InMemoryStore::new();
    let reg = registry();
    ensure_bootstrap_revision(&store, &reg);
    let world_id = id::<WorldId>(0x3101);
    let timeline_id = id::<TimelineId>(0x3102);
    let event_id = id::<EventId>(0x3110);
    let entity_id = id::<EntityId>(0x3120);
    let runtime = Runtime::new(&store, reg)
        .expect("Runtime should assemble")
        .with_identity_allocator(FixedIdentityAllocator {
            world_id,
            timeline_id,
        });
    let api: &dyn LoomApi = &runtime;
    let template = WorldTemplateDescriptor::new("bootstrap", 2, WorldInstant::new(42))
        .requires_capability(CAPABILITY, "^0.1.0")
        .with_configuration(json!({"assembly": "frozen"}))
        .with_bootstrap_action(ActionInvocation::new(
            ActionTypeId::from(ACTION),
            json!({
                "event_id": event_id.to_string(),
                "entity_id": entity_id.to_string(),
            }),
        ));

    let created = api
        .create_world_from_template(CreateWorldFromTemplateRequest::new(template))
        .await
        .expect("Template birth should commit atomically");
    assert_eq!(created.target.world_id, world_id);
    assert_eq!(created.target.timeline_id, timeline_id);
    assert_eq!(created.version.head_event_seq.value(), 1);
    assert_eq!(created.version.state_revision.value(), 1);
    assert_eq!(created.world_time, WorldInstant::new(42));
    let sessions = ExecutionSessionStore::list_sessions(&store)
        .await
        .expect("bootstrap Session should be persisted");
    assert_eq!(sessions.len(), 1);
    assert_eq!(sessions[0].origin(), ExecutionOrigin::Runtime);
    assert_eq!(sessions[0].assembly().world_id(), world_id);
    assert_eq!(
        sessions[0].assembly().timeline_id(),
        timeline_id,
        "Template bootstrap must retain one target Timeline in its Session"
    );
    assert_eq!(
        sessions[0].status(),
        loom_runtime::ExecutionSessionStatus::Committed
    );

    let binding = store
        .read_binding(world_id)
        .expect("Template Binding should be persisted with the World");
    assert_eq!(binding.revision(), 2);
    assert_eq!(binding.template_provenance(), Some("bootstrap@2"));
    assert_eq!(binding.configuration(), &json!({"assembly": "frozen"}));
    assert!(
        binding
            .requirements()
            .contains_key(&CapabilityId::from(CAPABILITY))
    );

    let history = api
        .list_events(EventQuery::all(created.target))
        .await
        .expect("bootstrap history should be readable");
    assert_eq!(history.len(), 1);
    assert_eq!(history[0].id, event_id);
    assert_eq!(history[0].occurred_at, WorldInstant::new(42));

    let next_event_id = id::<EventId>(0x3130);
    let next_entity_id = id::<EntityId>(0x3140);
    let executed = api
        .invoke(ActionRequest::new(
            created.target,
            ActionInvocation::new(
                ActionTypeId::from(ACTION),
                json!({
                    "event_id": next_event_id.to_string(),
                    "entity_id": next_entity_id.to_string(),
                }),
            ),
        ))
        .await
        .expect("newly born World should be immediately executable");
    assert!(executed.is_committed());
}

#[tokio::test]
async fn invalid_template_birth_leaves_no_world_or_timeline_artifact() {
    let store = InMemoryStore::new();
    let reg = registry();
    ensure_bootstrap_revision(&store, &reg);
    let world_id = id::<WorldId>(0x3201);
    let timeline_id = id::<TimelineId>(0x3202);
    let runtime = Runtime::new(&store, reg)
        .expect("Runtime should assemble")
        .with_identity_allocator(FixedIdentityAllocator {
            world_id,
            timeline_id,
        });
    let api: &dyn LoomApi = &runtime;
    let result = api
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new("invalid", 1, WorldInstant::new(9))
                .requires_capability(CAPABILITY, "^0.1.0")
                .with_bootstrap_action(ActionInvocation::new(
                    ActionTypeId::from("bootstrap.missing"),
                    json!({}),
                )),
        ))
        .await
        .expect_err("unknown bootstrap Action must fail before persistence");
    assert_eq!(result.code, ApiErrorCode::NotFound);
    let sessions = ExecutionSessionStore::list_sessions(&store)
        .await
        .expect("failed bootstrap Session should remain auditable");
    assert_eq!(sessions.len(), 1);
    assert_eq!(sessions[0].origin(), ExecutionOrigin::Runtime);
    assert_eq!(
        sessions[0].status(),
        loom_runtime::ExecutionSessionStatus::Failed
    );
    assert!(store.snapshot(timeline_id).is_err());
    assert!(store.read_binding(world_id).is_err());
}

#[tokio::test]
async fn template_revisions_are_snapshotted_per_future_world() {
    let store = InMemoryStore::new();
    let reg = registry();
    ensure_bootstrap_revision(&store, &reg);
    let first_world = id::<WorldId>(0x3301);
    let first_timeline = id::<TimelineId>(0x3302);
    let second_world = id::<WorldId>(0x3303);
    let second_timeline = id::<TimelineId>(0x3304);

    let first_runtime = Runtime::new(&store, reg)
        .expect("first Runtime should assemble")
        .with_identity_allocator(FixedIdentityAllocator {
            world_id: first_world,
            timeline_id: first_timeline,
        });
    first_runtime
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new("revisioned", 1, WorldInstant::new(10))
                .requires_capability(CAPABILITY, "^0.1.0")
                .with_configuration(json!({"rules": "v1"})),
        ))
        .await
        .expect("first Template revision should create a World");

    let second_runtime = Runtime::new(&store, registry())
        .expect("second Runtime should assemble")
        .with_identity_allocator(FixedIdentityAllocator {
            world_id: second_world,
            timeline_id: second_timeline,
        });
    second_runtime
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new("revisioned", 2, WorldInstant::new(20))
                .requires_capability(CAPABILITY, "^0.1.0")
                .with_configuration(json!({"rules": "v2"})),
        ))
        .await
        .expect("second Template revision should create a later World");

    let first_binding = store
        .read_binding(first_world)
        .expect("first World Binding should remain readable");
    assert_eq!(first_binding.revision(), 1);
    assert_eq!(first_binding.template_provenance(), Some("revisioned@1"));
    assert_eq!(first_binding.configuration(), &json!({"rules": "v1"}));

    let second_binding = store
        .read_binding(second_world)
        .expect("second World Binding should be readable");
    assert_eq!(second_binding.revision(), 2);
    assert_eq!(second_binding.template_provenance(), Some("revisioned@2"));
    assert_eq!(second_binding.configuration(), &json!({"rules": "v2"}));
}
