mod support;

use std::str::FromStr;

use loom_api::{
    ActionInvocation, ApiErrorCode, CreateWorldFromTemplateRequest, EventQuery, LoomApi,
    TimelineService, TimelineTarget, WorldTemplateDescriptor,
};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityDependency, CapabilityId,
    CapabilityManifest, CapabilityRegistrar, CapabilityRegistry, EventDefinition,
    RegistrationError, ResolutionContext, ResolverError,
};
use loom_core::{
    ActionTypeId, EventId, EventTypeId, SchemaRevision, TimelineId, TimelineVersion, WorldId,
    WorldInstant,
};
use loom_protocol::{ProposedEvent, Resolution, ResolveOutcome};
use loom_runtime::{
    BindingError, IdentityAllocator, LifecycleError, Runtime, WorldLifecycleStore,
    WorldRuntimeBinding, WorldRuntimeBindingStore, WorldStore,
};
use serde_json::json;

use support::TestDatabase;

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

const TEMPLATE_CAPABILITY: &str = "postgres.template";
const TEMPLATE_ACTION: &str = "postgres.template.birth";
const TEMPLATE_EVENT: &str = "postgres.template.born";

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

struct TemplateCapability {
    manifest: CapabilityManifest,
}

impl Capability for TemplateCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_event(EventDefinition::new(
            EventTypeId::from(TEMPLATE_EVENT),
            SchemaRevision::new(1),
        ))?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(TEMPLATE_ACTION), SchemaRevision::new(1)),
            TemplateResolver,
        )?;
        Ok(())
    }
}

struct TemplateResolver;

impl ActionResolver for TemplateResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &serde_json::Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = input
            .get("event_id")
            .and_then(serde_json::Value::as_str)
            .ok_or_else(|| ResolverError::new("event_id must be a UUID string"))?
            .parse::<EventId>()
            .map_err(|_| ResolverError::new("event_id must be a UUID string"))?;
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![ProposedEvent::new(
                event_id,
                EventTypeId::from(TEMPLATE_EVENT),
                SchemaRevision::new(1),
                json!({"value": "born"}),
            )],
            Vec::new(),
        )))
    }
}

fn template_registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([TemplateCapability {
        manifest: CapabilityManifest::parse(TEMPLATE_CAPABILITY, "0.1.0")
            .expect("Template Capability manifest should parse"),
    }])
    .expect("Template registry should assemble")
}

fn template(event_id: EventId) -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new("postgres-template", 2, WorldInstant::new(321))
        .requires_capability(TEMPLATE_CAPABILITY, "^0.1.0")
        .with_configuration(json!({"fixture": "postgres-template"}))
        .with_bootstrap_action(ActionInvocation::new(
            ActionTypeId::from(TEMPLATE_ACTION),
            json!({"event_id": event_id.to_string()}),
        ))
}

#[tokio::test]
async fn postgres_18_world_lifecycle_is_atomic_and_immediately_readable() {
    let Some(database) = TestDatabase::provision("lifecycle_success").await else {
        return;
    };
    let storage = database.storage().await;
    let world_id = id::<WorldId>(0x4101);
    let timeline_id = id::<TimelineId>(0x4102);
    let initial_world_time = WorldInstant::new(321);

    let created =
        WorldLifecycleStore::create_world(&storage, world_id, timeline_id, initial_world_time)
            .await
            .expect("PostgreSQL lifecycle bootstrap should commit");
    assert_eq!(created.world_id(), world_id);
    assert_eq!(created.timeline_id(), timeline_id);
    assert_eq!(created.version(), TimelineVersion::default());
    assert_eq!(created.world_time(), initial_world_time);

    let snapshot = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("new PostgreSQL Timeline should be immediately readable");
    assert_eq!(snapshot.world_id(), world_id);
    assert_eq!(snapshot.timeline_id(), timeline_id);
    assert_eq!(snapshot.version(), TimelineVersion::default());
    assert_eq!(snapshot.world_time(), initial_world_time);
    assert!(snapshot.events.is_empty());
    assert!(snapshot.works.is_empty());

    let runtime = Runtime::new(storage.clone(), CapabilityRegistry::new())
        .expect("empty semantic registry should assemble for lifecycle inspection");
    let public =
        TimelineService::inspect_timeline(&runtime, TimelineTarget::new(world_id, timeline_id))
            .await
            .expect("public TimelineService should observe committed lifecycle state");
    assert_eq!(public.target, TimelineTarget::new(world_id, timeline_id));
    assert_eq!(public.version, TimelineVersion::default());
    assert_eq!(public.world_time, initial_world_time);

    drop(runtime);
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the PostgreSQL Template birth matrix is intentionally linear"
)]
async fn postgres_18_template_birth_is_atomic_and_snapshots_binding() {
    let Some(database) = TestDatabase::provision("template_birth").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id = id::<WorldId>(0x4401);
    let timeline_id = id::<TimelineId>(0x4402);
    let event_id = id::<EventId>(0x4410);

    {
        let runtime = Runtime::new(&storage, template_registry())
            .expect("Template Runtime should assemble")
            .with_identity_allocator(FixedIdentityAllocator {
                world_id,
                timeline_id,
            });
        let api: &dyn LoomApi = &runtime;
        let created = api
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template(event_id)))
            .await
            .expect("PostgreSQL Template birth should commit");
        assert_eq!(created.target, TimelineTarget::new(world_id, timeline_id));
        assert_eq!(created.version.head_event_seq.value(), 1);
        assert_eq!(created.world_time, WorldInstant::new(321));

        let binding = WorldRuntimeBindingStore::read_binding(&storage, world_id)
            .await
            .expect("Template Binding should be persisted atomically");
        assert_eq!(binding.revision(), 2);
        assert_eq!(binding.template_provenance(), Some("postgres-template@2"));
        assert_eq!(
            binding.configuration(),
            &json!({"fixture": "postgres-template"})
        );
        assert!(
            binding
                .requirements()
                .contains_key(&CapabilityId::from(TEMPLATE_CAPABILITY))
        );

        let history = api
            .list_events(EventQuery::all(created.target))
            .await
            .expect("Template bootstrap history should be readable");
        assert_eq!(history.len(), 1);
        assert_eq!(history[0].id, event_id);
    }

    let invalid_world_id = id::<WorldId>(0x4421);
    let invalid_timeline_id = id::<TimelineId>(0x4422);
    {
        let runtime = Runtime::new(&storage, template_registry())
            .expect("invalid Template Runtime should assemble")
            .with_identity_allocator(FixedIdentityAllocator {
                world_id: invalid_world_id,
                timeline_id: invalid_timeline_id,
            });
        let api: &dyn LoomApi = &runtime;
        let rejected = api
            .create_world_from_template(CreateWorldFromTemplateRequest::new(
                WorldTemplateDescriptor::new("invalid", 1, WorldInstant::new(7))
                    .requires_capability(TEMPLATE_CAPABILITY, "^0.1.0")
                    .with_bootstrap_action(ActionInvocation::new(
                        ActionTypeId::from("postgres.template.missing"),
                        json!({}),
                    )),
            ))
            .await
            .expect_err("unknown Template bootstrap Action must be rejected before persistence");
        assert_eq!(rejected.code, ApiErrorCode::NotFound);
    }

    let invalid_world_count: i64 =
        sqlx::query_scalar("SELECT count(*)::bigint FROM loom_world WHERE world_id = $1::uuid")
            .bind(invalid_world_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("invalid World row count should be queryable");
    assert_eq!(invalid_world_count, 0);
    let invalid_timeline_count: i64 = sqlx::query_scalar(
        "SELECT count(*)::bigint FROM loom_timeline WHERE timeline_id = $1::uuid",
    )
    .bind(invalid_timeline_id.to_string())
    .fetch_one(&pool)
    .await
    .expect("invalid Timeline row count should be queryable");
    assert_eq!(invalid_timeline_count, 0);

    let conflict_runtime = Runtime::new(&storage, template_registry())
        .expect("conflict Template Runtime should assemble")
        .with_identity_allocator(FixedIdentityAllocator {
            world_id,
            timeline_id,
        });
    let conflict_api: &dyn LoomApi = &conflict_runtime;
    let conflict = conflict_api
        .create_world_from_template(CreateWorldFromTemplateRequest::new(template(
            id::<EventId>(0x4411),
        )))
        .await
        .expect_err("duplicate Template World identity must conflict");
    assert_eq!(conflict.code, ApiErrorCode::Conflict);

    let original = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Template conflict must preserve the original Timeline");
    assert_eq!(original.events.len(), 1);
    assert_eq!(original.events[0].id, event_id);

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_world_lifecycle_conflicts_roll_back_without_partial_rows() {
    let Some(database) = TestDatabase::provision("lifecycle_conflict").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;

    let world_a = id::<WorldId>(0x4201);
    let timeline_a = id::<TimelineId>(0x4202);
    WorldLifecycleStore::create_world(&storage, world_a, timeline_a, WorldInstant::new(10))
        .await
        .expect("initial lifecycle fixture should commit");

    let unused_timeline = id::<TimelineId>(0x4203);
    let duplicate_world = WorldLifecycleStore::create_world(
        &storage,
        world_a,
        unused_timeline,
        WorldInstant::new(20),
    )
    .await
    .expect_err("duplicate World identity must be a typed lifecycle conflict");
    assert_eq!(
        duplicate_world,
        LifecycleError::WorldAlreadyExists { world_id: world_a }
    );
    let unused_timeline_count: i64 = sqlx::query_scalar(
        "SELECT count(*)::bigint FROM loom_timeline WHERE timeline_id = $1::uuid",
    )
    .bind(unused_timeline.to_string())
    .fetch_one(&pool)
    .await
    .expect("Timeline rollback should be inspectable");
    assert_eq!(unused_timeline_count, 0);

    let world_b = id::<WorldId>(0x4204);
    let duplicate_timeline =
        WorldLifecycleStore::create_world(&storage, world_b, timeline_a, WorldInstant::new(30))
            .await
            .expect_err("duplicate Timeline identity must roll back the fresh World insert");
    assert_eq!(
        duplicate_timeline,
        LifecycleError::TimelineAlreadyExists {
            timeline_id: timeline_a,
        }
    );
    let rolled_back_world_count: i64 =
        sqlx::query_scalar("SELECT count(*)::bigint FROM loom_world WHERE world_id = $1::uuid")
            .bind(world_b.to_string())
            .fetch_one(&pool)
            .await
            .expect("World rollback should be inspectable");
    assert_eq!(rolled_back_world_count, 0);

    let recovered_timeline = id::<TimelineId>(0x4205);
    let recovered = WorldLifecycleStore::create_world(
        &storage,
        world_b,
        recovered_timeline,
        WorldInstant::new(40),
    )
    .await
    .expect("rolled-back World identity must remain reusable");
    assert_eq!(recovered.world_id(), world_b);
    assert_eq!(recovered.timeline_id(), recovered_timeline);
    assert_eq!(recovered.version(), TimelineVersion::default());
    assert_eq!(recovered.world_time(), WorldInstant::new(40));

    let original = WorldStore::snapshot(&storage, timeline_a)
        .await
        .expect("conflicts must not damage the original Timeline");
    assert_eq!(original.world_id(), world_a);
    assert_eq!(original.version(), TimelineVersion::default());
    assert_eq!(original.world_time(), WorldInstant::new(10));

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_world_runtime_binding_survives_restart_and_rejects_mutation() {
    let Some(database) = TestDatabase::provision("binding_lifecycle").await else {
        return;
    };
    let storage = database.storage().await;
    let world_id = id::<WorldId>(0x4301);
    let timeline_id = id::<TimelineId>(0x4302);
    let binding = WorldRuntimeBinding::new(
        [(
            CapabilityId::from("binding.test"),
            CapabilityDependency::parse("binding.test", "^0.1.0")
                .expect("binding requirement should parse")
                .version,
        )],
        json!({"fixture": "postgres"}),
        1,
        Some("binding-test".to_owned()),
    );

    WorldLifecycleStore::create_world_with_binding(
        &storage,
        world_id,
        timeline_id,
        WorldInstant::new(0),
        binding.clone(),
    )
    .await
    .expect("World and Binding should commit atomically");
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&storage, world_id)
            .await
            .expect("Binding should be readable"),
        binding
    );
    storage.close().await;

    let restarted = database.storage().await;
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&restarted, world_id)
            .await
            .expect("Binding should survive adapter restart"),
        binding
    );
    let replacement = WorldRuntimeBinding::new(
        [(
            CapabilityId::from("binding.other"),
            CapabilityDependency::parse("binding.other", "*")
                .expect("replacement requirement should parse")
                .version,
        )],
        json!({"fixture": "replacement"}),
        2,
        Some("replacement".to_owned()),
    );
    assert_eq!(
        WorldRuntimeBindingStore::persist_binding(&restarted, world_id, replacement).await,
        Err(BindingError::BindingAlreadyExists { world_id })
    );
    restarted.close().await;
    database.cleanup().await;
}
