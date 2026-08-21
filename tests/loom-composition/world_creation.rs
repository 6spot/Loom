use std::str::FromStr;

use loom_api::{
    ActionRequest, ApiErrorCode, CreateWorldRequest, EventQuery, LoomApi, WorldService,
};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EventDefinition, RegistrationError, ResolutionContext, ResolverError,
};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventTypeId, SchemaRevision, TimelineId, TimelineVersion,
    WorldEffect, WorldId, WorldInstant,
};
use loom_protocol::{ActionInvocation, ProposedEvent, Resolution, ResolveOutcome};
use loom_runtime::{IdentityAllocator, Runtime};
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
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id::<EventId>(input, "event_id")?;
        let entity_id = parse_id::<EntityId>(input, "entity_id")?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(EVENT),
            SchemaRevision::new(1),
            context.world_time(),
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

fn registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([BootstrapCapability {
        manifest: CapabilityManifest::parse(CAPABILITY, "0.1.0")
            .expect("bootstrap manifest should parse"),
    }])
    .expect("bootstrap registry should assemble")
}

#[tokio::test]
async fn public_world_creation_is_atomic_and_immediately_usable() {
    let store = InMemoryStore::new();
    let world_id = id::<WorldId>(0x3001);
    let timeline_id = id::<TimelineId>(0x3002);
    let runtime = Runtime::new(&store, registry())
        .expect("Runtime should assemble")
        .with_identity_allocator(FixedIdentityAllocator {
            world_id,
            timeline_id,
        });
    let api: &dyn LoomApi = &runtime;

    let created = api
        .create_world(CreateWorldRequest::new(WorldInstant::new(42)))
        .await
        .expect("public World creation should succeed");
    assert_eq!(created.target.world_id, world_id);
    assert_eq!(created.target.timeline_id, timeline_id);
    assert_eq!(created.version, TimelineVersion::default());
    assert_eq!(created.world_time, WorldInstant::new(42));

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

    let duplicate = WorldService::create_world(api, CreateWorldRequest::new(WorldInstant::new(99)))
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
        .create_world(CreateWorldRequest::new(WorldInstant::new(70)))
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
        .create_world(CreateWorldRequest::new(WorldInstant::new(77)))
        .await
        .expect("failed Timeline conflict must not leave a partial World");
    assert_eq!(recovered.target.world_id, conflicting_world_id);
    assert_eq!(recovered.target.timeline_id, recovered_timeline_id);
    assert_eq!(recovered.version, TimelineVersion::default());
    assert_eq!(recovered.world_time, WorldInstant::new(77));
}
