use std::{str::FromStr, sync::Arc};

use loom_api::{ActionRequest, ActionService, ExecutionResult, TimelineTarget};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityDependency, CapabilityId,
    CapabilityManifest, CapabilityRegistrar, CapabilityRegistry, EventDefinition, FacetDefinition,
    RegistrationError, RelationshipDefinition, ResolutionContext, ResolverError, WorkHandler,
    WorkHandlerDefinition,
};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventSeq, EventTypeId, FacetOwner, FacetTypeId,
    RelationshipParticipant, RelationshipTypeId, SchemaRevision, TimelineId, WorkHandlerId, WorkId,
    WorldEffect, WorldId, WorldInstant,
};
use loom_protocol::{
    ActionInvocation, NewWork, ProposedEvent, Resolution, ResolveOutcome, WorkMutation,
    WorkSchedule,
};
use loom_runtime::{
    AdvanceWorldTime, BindingError, CommitError, EffectEngine, PlatformTime, Runtime, WorkRecord,
    WorkStatus, WorldRuntimeBinding, WorldRuntimeBindingStore, WorldTimeError,
};
use serde_json::{Value, json};

use crate::InMemoryStore;

const OWNER: &str = "test";

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

fn world() -> WorldId {
    id(1)
}

fn timeline() -> TimelineId {
    id(2)
}

fn second_timeline() -> TimelineId {
    id(3)
}

fn event(value: u128) -> EventId {
    id(value)
}

fn entity(value: u128) -> EntityId {
    id(value)
}

fn work(value: u128) -> WorkId {
    id(value)
}

fn registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([TestCapability {
        manifest: CapabilityManifest::parse(OWNER, "0.1.0")
            .expect("test Capability manifest should parse"),
    }])
    .expect("test Capability registry should assemble")
}

#[tokio::test]
async fn world_binding_is_persisted_once_and_shared_across_timelines() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("first Timeline should be created");
    store
        .create_timeline(world(), second_timeline())
        .expect("second Timeline should share the World");
    let binding = WorldRuntimeBinding::new(
        [(
            CapabilityId::from(OWNER),
            CapabilityDependency::parse(OWNER, "^0.1.0")
                .expect("binding requirement should parse")
                .version,
        )],
        json!({"fixture": "immutable"}),
        1,
        Some("test-template".to_owned()),
    );

    WorldRuntimeBindingStore::persist_binding(&store, world(), binding.clone())
        .await
        .expect("binding should persist once");
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&store, world())
            .await
            .expect("binding should reload"),
        binding
    );
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&store, world())
            .await
            .expect("second Timeline should see the World binding"),
        binding
    );

    let replacement = WorldRuntimeBinding::new(
        [(
            CapabilityId::from("replacement"),
            CapabilityDependency::parse("replacement", "*")
                .expect("replacement requirement should parse")
                .version,
        )],
        json!({"fixture": "replacement"}),
        2,
        Some("replacement".to_owned()),
    );
    assert_eq!(
        WorldRuntimeBindingStore::persist_binding(&store, world(), replacement).await,
        Err(BindingError::BindingAlreadyExists { world_id: world() })
    );
}

#[tokio::test]
async fn different_worlds_keep_distinct_bindings() {
    let store = InMemoryStore::new();
    let other_world = id::<WorldId>(4);
    let other_timeline = id::<TimelineId>(5);
    store
        .create_timeline(world(), timeline())
        .expect("first World fixture should be created");
    store
        .create_timeline(other_world, other_timeline)
        .expect("second World fixture should be created");
    let first = WorldRuntimeBinding::new(
        [(
            CapabilityId::from(OWNER),
            CapabilityDependency::parse(OWNER, "^0.1.0")
                .expect("first World requirement should parse")
                .version,
        )],
        json!({"fixture": "first-world"}),
        1,
        Some("first-world".to_owned()),
    );
    let second = WorldRuntimeBinding::new(
        [(
            CapabilityId::from("other"),
            CapabilityDependency::parse("other", "*")
                .expect("second World requirement should parse")
                .version,
        )],
        json!({"fixture": "second-world"}),
        1,
        Some("second-world".to_owned()),
    );

    WorldRuntimeBindingStore::persist_binding(&store, world(), first.clone())
        .await
        .expect("first World binding should persist");
    WorldRuntimeBindingStore::persist_binding(&store, other_world, second.clone())
        .await
        .expect("second World binding should persist");
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&store, world()).await,
        Ok(first)
    );
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&store, other_world).await,
        Ok(second)
    );
}

#[tokio::test]
async fn legacy_world_binding_is_materialized_once() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("legacy Timeline fixture should be created");
    let first = WorldRuntimeBinding::new(
        [(
            CapabilityId::from(OWNER),
            CapabilityDependency::parse(OWNER, "^0.1.0")
                .expect("first legacy requirement should parse")
                .version,
        )],
        json!({"fixture": "legacy-first"}),
        1,
        Some("m3-compatibility-baseline".to_owned()),
    );
    let second = WorldRuntimeBinding::new(
        [(
            CapabilityId::from("replacement"),
            CapabilityDependency::parse("replacement", "*")
                .expect("second legacy requirement should parse")
                .version,
        )],
        json!({"fixture": "legacy-second"}),
        2,
        Some("must-not-replace".to_owned()),
    );

    assert_eq!(
        WorldRuntimeBindingStore::ensure_binding(&store, world(), first.clone()).await,
        Ok(first.clone())
    );
    assert_eq!(
        WorldRuntimeBindingStore::ensure_binding(&store, world(), second).await,
        Ok(first.clone())
    );
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&store, world()).await,
        Ok(first)
    );
}

fn validated(
    store: &InMemoryStore,
    registry: &CapabilityRegistry,
    resolution: Resolution,
) -> loom_runtime::ValidatedResolution {
    let snapshot = store
        .snapshot(timeline())
        .expect("test Timeline should exist");
    let view = snapshot.world_view();
    EffectEngine::new(registry)
        .validate(&view, OWNER, resolution)
        .expect("test Resolution should validate")
}

fn pending_work(work_id: WorkId) -> WorkRecord {
    pending_work_with_handler(work_id, WorkHandlerId::from("test.handler"))
}

fn pending_work_with_handler(work_id: WorkId, handler: WorkHandlerId) -> WorkRecord {
    WorkRecord {
        id: work_id,
        timeline_id: timeline(),
        handler,
        schema_revision: SchemaRevision::new(1),
        payload: json!({"work": work_id.to_string()}),
        due_world_time: None,
        causal_event_id: None,
        origin_work_id: None,
        status: WorkStatus::Pending,
        attempt_count: 0,
        claim_generation: 0,
        available_at: PlatformTime::new(0),
        last_error: None,
        lease: None,
    }
}

fn event_with_effect(event_id: EventId, effect: WorldEffect, source_time: i64) -> ProposedEvent {
    ProposedEvent::new(
        event_id,
        EventTypeId::from("test.changed"),
        SchemaRevision::new(1),
        json!({"event": event_id.to_string(), "source_time": source_time}),
    )
    .with_effect(effect)
}

fn with_entity_participant(mut event: ProposedEvent, entity_id: EntityId) -> ProposedEvent {
    event.participants = serde_json::from_value(json!([{
        "entity_id": entity_id.to_string(),
        "role": "subject"
    }]))
    .expect("test Event participant should deserialize");
    event
}

fn with_relationship_ref(
    mut event: ProposedEvent,
    relationship_id: loom_core::RelationshipId,
) -> ProposedEvent {
    event.relationship_refs = serde_json::from_value(json!([{
        "relationship_id": relationship_id.to_string(),
        "role": "subject"
    }]))
    .expect("test Event Relationship reference should deserialize");
    event
}

fn relationship_participants() -> Vec<RelationshipParticipant> {
    vec![
        RelationshipParticipant::new(entity(10), "left"),
        RelationshipParticipant::new(entity(11), "right"),
    ]
}

struct TestCapability {
    manifest: CapabilityManifest,
}

const NO_CHANGE_CAPABILITY: &str = "test.no_change";
const NO_CHANGE_ACTION: &str = "test.no_change_action";
const SCHEDULE_ACTION: &str = "test.schedule_work";
const CANCEL_ACTION: &str = "test.cancel_work";
const EMPTY_WORK_HANDLER: &str = "test.empty_work";
const TEST_WORK_HANDLER: &str = "test.handler";

struct NoChangeCapability {
    manifest: CapabilityManifest,
}

impl Capability for NoChangeCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(NO_CHANGE_ACTION), SchemaRevision::new(1)),
            EmptyResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(SCHEDULE_ACTION), SchemaRevision::new(1)),
            ScheduleResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(CANCEL_ACTION), SchemaRevision::new(1)),
            CancelResolver,
        )?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(
                WorkHandlerId::from(EMPTY_WORK_HANDLER),
                SchemaRevision::new(1),
            ),
            EmptyWorkHandler,
        )
    }
}

fn no_change_registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([NoChangeCapability {
        manifest: CapabilityManifest::parse(NO_CHANGE_CAPABILITY, "0.1.0")
            .expect("no-change Capability manifest should parse"),
    }])
    .expect("no-change Capability registry should assemble")
}

struct EmptyResolver;

impl ActionResolver for EmptyResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        _input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Ok(ResolveOutcome::Resolved(Resolution::default()))
    }
}

struct ScheduleResolver;

impl ActionResolver for ScheduleResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let work_id = input
            .get("work_id")
            .and_then(Value::as_str)
            .ok_or_else(|| ResolverError::new("work_id must be a UUID string"))?
            .parse()
            .map_err(|_| ResolverError::new("work_id must be a UUID string"))?;
        Ok(ResolveOutcome::Resolved(Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::new(
                work_id,
                timeline(),
                WorkHandlerId::from(EMPTY_WORK_HANDLER),
                SchemaRevision::new(1),
                json!({}),
                WorkSchedule::Immediate,
            ))],
        )))
    }
}

struct CancelResolver;

impl ActionResolver for CancelResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let work_id = input
            .get("work_id")
            .and_then(Value::as_str)
            .ok_or_else(|| ResolverError::new("work_id must be a UUID string"))?
            .parse()
            .map_err(|_| ResolverError::new("work_id must be a UUID string"))?;
        Ok(ResolveOutcome::Resolved(Resolution::new(
            Vec::new(),
            vec![WorkMutation::Cancel(work_id)],
        )))
    }
}

struct EmptyWorkHandler;

impl WorkHandler for EmptyWorkHandler {
    fn handle(
        &self,
        _context: &dyn ResolutionContext,
        _payload: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Ok(ResolveOutcome::Resolved(Resolution::default()))
    }
}

impl Capability for TestCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_facet(FacetDefinition::new(
            FacetTypeId::from("test.facet"),
            SchemaRevision::new(1),
            json!({"type": "object"}),
        ))?;
        registrar.register_relationship(RelationshipDefinition::new(
            RelationshipTypeId::from("test.relationship"),
            SchemaRevision::new(1),
        ))?;
        registrar.register_event(EventDefinition::new(
            EventTypeId::from("test.changed"),
            SchemaRevision::new(1),
        ))?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(
                WorkHandlerId::from(TEST_WORK_HANDLER),
                SchemaRevision::new(1),
            ),
            EmptyWorkHandler,
        )
    }
}

#[tokio::test]
async fn empty_public_action_returns_no_change_without_advancing_timeline_version() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let runtime = Runtime::new(&store, no_change_registry()).expect("Runtime should assemble");
    let before = store
        .snapshot(timeline())
        .expect("test Timeline should be readable")
        .version();

    let result = runtime
        .invoke(ActionRequest::new(
            TimelineTarget::new(world(), timeline()),
            ActionInvocation::new(ActionTypeId::from(NO_CHANGE_ACTION), json!({})),
        ))
        .await
        .expect("empty Action should execute");

    assert_eq!(result, ExecutionResult::NoChange);
    let after = store
        .snapshot(timeline())
        .expect("test Timeline should be readable");
    assert_eq!(after.version(), before);
    assert!(after.events.is_empty());
}

#[tokio::test]
async fn work_only_actions_use_each_injected_platform_time_and_persist_schedule_and_cancel() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let clock = loom_runtime::ManualPlatformClock::new(PlatformTime::new(7));
    let runtime = Runtime::new(&store, no_change_registry())
        .expect("Runtime should assemble")
        .with_platform_clock(clock.clone());
    let target = TimelineTarget::new(world(), timeline());

    let first = runtime
        .invoke(ActionRequest::new(
            target,
            ActionInvocation::new(
                ActionTypeId::from(SCHEDULE_ACTION),
                json!({"work_id": work(30).to_string()}),
            ),
        ))
        .await
        .expect("first Work schedule should execute");
    assert!(matches!(
        first,
        ExecutionResult::Committed {
            ref event_ids,
            ..
        } if event_ids.is_empty()
    ));
    assert_eq!(
        store
            .work(timeline(), work(30))
            .expect("first Work should be readable")
            .expect("first Work should exist")
            .available_at,
        PlatformTime::new(7)
    );

    clock.set(11.into());
    let second = runtime
        .invoke(ActionRequest::new(
            target,
            ActionInvocation::new(
                ActionTypeId::from(SCHEDULE_ACTION),
                json!({"work_id": work(31).to_string()}),
            ),
        ))
        .await
        .expect("second Work schedule should execute");
    assert!(matches!(
        second,
        ExecutionResult::Committed {
            ref event_ids,
            ..
        } if event_ids.is_empty()
    ));
    assert_eq!(
        store
            .work(timeline(), work(31))
            .expect("second Work should be readable")
            .expect("second Work should exist")
            .available_at,
        PlatformTime::new(11)
    );

    let cancel = runtime
        .invoke(ActionRequest::new(
            target,
            ActionInvocation::new(
                ActionTypeId::from(CANCEL_ACTION),
                json!({"work_id": work(31).to_string()}),
            ),
        ))
        .await
        .expect("Work cancellation should execute");
    assert!(matches!(
        cancel,
        ExecutionResult::Committed {
            ref event_ids,
            ..
        } if event_ids.is_empty()
    ));
    assert_eq!(
        store
            .work(timeline(), work(31))
            .expect("cancelled Work should be readable")
            .expect("cancelled Work should exist")
            .status,
        WorkStatus::Cancelled
    );
}

#[tokio::test]
async fn zero_event_work_completion_commits_runtime_state_atomically() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work_with_handler(
            work(40),
            WorkHandlerId::from(EMPTY_WORK_HANDLER),
        ))
        .expect("empty Work fixture should be seeded");
    let runtime = Runtime::new(&store, no_change_registry()).expect("Runtime should assemble");

    let result = runtime
        .execute_work(
            TimelineTarget::new(world(), timeline()),
            work(40),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(2),
        )
        .await
        .expect("empty Work resolution should complete");

    assert!(matches!(
        result,
        ExecutionResult::Committed {
            ref event_ids,
            timeline_version,
        } if event_ids.is_empty() && timeline_version.state_revision.value() == 1
    ));
    let snapshot = store
        .snapshot(timeline())
        .expect("completed Timeline should be readable");
    assert!(snapshot.events.is_empty());
    assert_eq!(snapshot.version().state_revision.value(), 1);
    assert_eq!(
        store
            .work(timeline(), work(40))
            .expect("completed Work should be readable")
            .expect("completed Work should exist")
            .status,
        WorkStatus::Completed
    );
}

#[tokio::test]
async fn commit_assigns_contiguous_event_sequences_and_advances_once() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    let resolution = Resolution::new(
        vec![
            event_with_effect(
                event(10),
                WorldEffect::CreateEntity {
                    entity_id: entity(20),
                },
                5,
            ),
            ProposedEvent::new(
                event(11),
                EventTypeId::from("test.changed"),
                SchemaRevision::new(1),
                json!({"fact": true}),
            ),
        ],
        Vec::new(),
    );
    let validated = validated(&store, &registry, resolution);

    let result = store
        .commit(&validated, None, PlatformTime::new(1))
        .expect("matching CAS commit should succeed");
    assert_eq!(
        result
            .events
            .iter()
            .map(|committed| committed.event_seq.value())
            .collect::<Vec<_>>(),
        vec![1, 2]
    );
    assert_eq!(result.version.head_event_seq, EventSeq::new(2));
    assert_eq!(result.version.state_revision.value(), 1);

    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(snapshot.events.len(), 2);
    assert_eq!(snapshot.events[0].event_seq, EventSeq::new(1));
    assert_eq!(snapshot.events[1].event_seq, EventSeq::new(2));
    assert_eq!(snapshot.world_time(), WorldInstant::new(0));
    assert!(
        snapshot
            .events
            .iter()
            .all(|event| event.occurred_at == WorldInstant::new(0))
    );
    assert!(snapshot.world_view().entity(entity(20)).is_some());
}

#[test]
fn explicit_world_time_transition_is_monotonic_and_stale_cas_loses() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let initial = store.snapshot(timeline()).expect("snapshot should exist");
    let first = AdvanceWorldTime::new(
        timeline(),
        initial.version(),
        initial.world_time(),
        WorldInstant::new(10),
    )
    .expect("forward transition should validate");
    let next = store
        .advance_world_time(first)
        .expect("matching World-Time CAS should succeed");
    assert_eq!(next.head_event_seq, EventSeq::new(0));
    assert_eq!(next.state_revision.value(), 1);
    assert_eq!(
        store.snapshot(timeline()).expect("snapshot").world_time(),
        WorldInstant::new(10)
    );

    let stale = AdvanceWorldTime::new(
        timeline(),
        initial.version(),
        initial.world_time(),
        WorldInstant::new(20),
    )
    .expect("stale forward transition is structurally monotonic");
    assert!(matches!(
        store.advance_world_time(stale),
        Err(WorldTimeError::TimelineConflict { .. })
    ));
    assert!(matches!(
        AdvanceWorldTime::new(
            timeline(),
            next,
            WorldInstant::new(10),
            WorldInstant::new(10),
        ),
        Err(WorldTimeError::NonMonotonic { .. })
    ));
}

#[tokio::test]
async fn storage_hard_checks_accept_same_event_structural_references_and_ordered_effects() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    for entity_id in [entity(10), entity(11)] {
        store
            .seed_entity(
                timeline(),
                loom_core::Entity {
                    id: entity_id,
                    world_id: world(),
                },
            )
            .expect("Relationship participant Entity should be seeded");
    }

    let created_entity = entity(80);
    let entity_event = with_entity_participant(
        event_with_effect(
            event(80),
            WorldEffect::CreateEntity {
                entity_id: created_entity,
            },
            1,
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(created_entity),
            facet_type: FacetTypeId::from("test.facet"),
            schema_revision: SchemaRevision::new(1),
            value: json!({"created": true}),
        }),
        created_entity,
    );
    let created_relationship = loom_core::RelationshipId::from_uuid(
        "00000000-0000-0000-0000-000000000080"
            .parse()
            .expect("test RelationshipId should parse"),
    );
    let relationship_event = with_relationship_ref(
        event_with_effect(
            event(81),
            WorldEffect::CreateRelationship {
                relationship_id: created_relationship,
                relationship_type: RelationshipTypeId::from("test.relationship"),
                participants: relationship_participants(),
            },
            2,
        ),
        created_relationship,
    );

    let validated = validated(
        &store,
        &registry(),
        Resolution::new(vec![entity_event, relationship_event], Vec::new()),
    );
    let result = store
        .commit(&validated, None, PlatformTime::new(1))
        .expect("storage hard checks should agree with Runtime validation");

    assert_eq!(result.events.len(), 2);
    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert!(snapshot.world_view().entity(created_entity).is_some());
    assert_eq!(
        snapshot
            .world_view()
            .facet(
                FacetOwner::entity(created_entity),
                &FacetTypeId::from("test.facet"),
            )
            .expect("created Entity Facet should be readable")
            .value(),
        &json!({"created": true})
    );
    assert!(
        snapshot
            .world_view()
            .relationship(created_relationship)
            .is_some()
    );
}

#[tokio::test]
async fn storage_hard_checks_allow_reference_to_relationship_ended_by_same_event() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    for entity_id in [entity(10), entity(11)] {
        store
            .seed_entity(
                timeline(),
                loom_core::Entity {
                    id: entity_id,
                    world_id: world(),
                },
            )
            .expect("Relationship participant Entity should be seeded");
    }
    let relationship_id = loom_core::RelationshipId::from_uuid(
        "00000000-0000-0000-0000-000000000082"
            .parse()
            .expect("test RelationshipId should parse"),
    );
    store
        .seed_relationship(
            timeline(),
            loom_core::Relationship::new(
                relationship_id,
                world(),
                RelationshipTypeId::from("test.relationship"),
                relationship_participants(),
            ),
            true,
        )
        .expect("active Relationship should be seeded");

    let event = with_relationship_ref(
        event_with_effect(
            event(82),
            WorldEffect::EndRelationship { relationship_id },
            3,
        ),
        relationship_id,
    );
    let validated = validated(
        &store,
        &registry(),
        Resolution::new(vec![event], Vec::new()),
    );
    let result = store
        .commit(&validated, None, PlatformTime::new(1))
        .expect("an Event may reference the active Relationship it ends");
    assert_eq!(result.events.len(), 1);

    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert!(
        snapshot
            .world_view()
            .relationship(relationship_id)
            .is_none(),
        "ended Relationship must not remain active"
    );
}

#[tokio::test]
async fn stale_cas_leaves_event_state_and_work_unchanged() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    let validated = validated(
        &store,
        &registry,
        Resolution::new(
            vec![event_with_effect(
                event(30),
                WorldEffect::CreateEntity {
                    entity_id: entity(31),
                },
                7,
            )],
            Vec::new(),
        ),
    );
    store
        .commit(&validated, None, PlatformTime::new(1))
        .expect("first commit should succeed");
    let before = store.snapshot(timeline()).expect("snapshot should exist");

    let error = store
        .commit(&validated, None, PlatformTime::new(2))
        .expect_err("reusing a stale validated token must conflict");
    assert!(matches!(error, CommitError::TimelineConflict { .. }));

    let after = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after.version(), before.version());
    assert_eq!(after.world_time(), before.world_time());
    assert_eq!(after.events.len(), before.events.len());
    assert_eq!(
        after.world_view().entity(entity(31)),
        before.world_view().entity(entity(31))
    );
    assert!(after.works.is_empty());
}

#[tokio::test]
async fn staged_commit_does_not_expose_event_before_work_failure() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(40)))
        .expect("current Work fixture should be seeded");
    let registry = registry();
    let resolution = Resolution::new(
        vec![event_with_effect(
            event(41),
            WorldEffect::CreateEntity {
                entity_id: entity(42),
            },
            9,
        )],
        vec![WorkMutation::Schedule(NewWork::new(
            work(40),
            timeline(),
            WorkHandlerId::from("test.handler"),
            SchemaRevision::new(1),
            json!({}),
            WorkSchedule::Immediate,
        ))],
    );
    let validated = validated(&store, &registry, resolution);
    let before = store.snapshot(timeline()).expect("snapshot should exist");

    let error = store
        .commit(&validated, None, PlatformTime::new(1))
        .expect_err("duplicate Work should fail before staged swap");
    assert!(matches!(
        error,
        CommitError::Work(loom_runtime::WorkError::DuplicateWork { .. })
    ));

    let after = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after.version(), before.version());
    assert_eq!(after.world_time(), before.world_time());
    assert!(after.events.is_empty());
    assert!(after.world_view().entity(entity(42)).is_none());
    assert_eq!(after.works[0].status, WorkStatus::Pending);
}

#[tokio::test]
async fn work_creation_and_current_completion_share_zero_event_commit() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(50)))
        .expect("current Work fixture should be seeded");
    let claim = store
        .claim(
            timeline(),
            work(50),
            PlatformTime::new(0),
            PlatformTime::new(10),
        )
        .expect("current Work should be claimable");
    let registry = registry();
    let validated = validated(
        &store,
        &registry,
        Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::new(
                work(51),
                timeline(),
                WorkHandlerId::from("test.handler"),
                SchemaRevision::new(1),
                json!({"next": true}),
                WorkSchedule::At(WorldInstant::new(100)),
            ))],
        ),
    );

    let result = store
        .commit(&validated, Some(&claim), PlatformTime::new(5))
        .expect("Work completion and creation should commit atomically");
    assert!(result.events.is_empty());
    assert_eq!(result.completed_work, Some(work(50)));
    assert_eq!(result.version.head_event_seq, EventSeq::new(0));
    assert_eq!(result.version.state_revision.value(), 1);

    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(snapshot.world_time(), WorldInstant::new(0));
    assert_eq!(snapshot.events.len(), 0);
    assert_eq!(
        snapshot
            .works
            .iter()
            .find(|item| item.id == work(50))
            .expect("current Work should remain readable")
            .status,
        WorkStatus::Completed
    );
    assert_eq!(
        snapshot
            .works
            .iter()
            .find(|item| item.id == work(51))
            .expect("new Work should be readable")
            .status,
        WorkStatus::Pending
    );
}

#[tokio::test]
async fn retry_and_expired_claims_preserve_work_identity_and_fence_winner() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(60)))
        .expect("Work fixture should be seeded");
    let initial = store.snapshot(timeline()).expect("snapshot should exist");
    let first_claim = store
        .claim(
            timeline(),
            work(60),
            PlatformTime::new(0),
            PlatformTime::new(5),
        )
        .expect("first claim should succeed");
    let retried = store
        .retry(
            &first_claim,
            PlatformTime::new(1),
            PlatformTime::new(3),
            Some("temporary failure".to_owned()),
        )
        .expect("technical retry should update metadata only");
    assert_eq!(retried.id, work(60));
    assert_eq!(retried.status, WorkStatus::Pending);
    assert_eq!(retried.attempt_count, 1);
    assert_eq!(retried.last_error.as_deref(), Some("temporary failure"));

    let after_retry = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after_retry.version(), initial.version());
    assert!(after_retry.events.is_empty());
    assert_eq!(after_retry.world_time(), initial.world_time());

    let second_claim = store
        .claim(
            timeline(),
            work(60),
            PlatformTime::new(3),
            PlatformTime::new(6),
        )
        .expect("Work should be claimable after retry availability");
    let registry = CapabilityRegistry::new();
    let validated = validated(&store, &registry, Resolution::new(Vec::new(), Vec::new()));
    let expired = store
        .commit(&validated, Some(&second_claim), PlatformTime::new(6))
        .expect_err("deadline equality must treat the lease as expired");
    assert!(matches!(
        expired,
        CommitError::Work(loom_runtime::WorkError::LeaseExpired { .. })
    ));

    let third_claim = store
        .claim(
            timeline(),
            work(60),
            PlatformTime::new(6),
            PlatformTime::new(10),
        )
        .expect("expired Work should be claimable with a new fence");
    let stale = store
        .commit(&validated, Some(&second_claim), PlatformTime::new(7))
        .expect_err("old fence must lose after re-claim");
    assert!(matches!(
        stale,
        CommitError::Work(loom_runtime::WorkError::StaleClaim { .. })
    ));
    store
        .commit(&validated, Some(&third_claim), PlatformTime::new(7))
        .expect("new fence should be the sole completion winner");

    let final_snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(final_snapshot.events.len(), 0);
    assert_eq!(final_snapshot.world_time(), WorldInstant::new(0));
    assert_eq!(final_snapshot.version().state_revision.value(), 1);
    assert_eq!(
        final_snapshot
            .works
            .iter()
            .find(|item| item.id == work(60))
            .expect("Work should remain readable")
            .status,
        WorkStatus::Completed
    );
}

#[tokio::test]
async fn concurrent_cas_and_claim_choose_one_winner() {
    let store = Arc::new(InMemoryStore::new());
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(70)))
        .expect("Work fixture should be seeded");
    let registry = registry();
    let first = validated(
        &store,
        &registry,
        Resolution::new(
            vec![event_with_effect(
                event(71),
                WorldEffect::CreateEntity {
                    entity_id: entity(72),
                },
                2,
            )],
            Vec::new(),
        ),
    );
    let second = validated(
        &store,
        &registry,
        Resolution::new(
            vec![event_with_effect(
                event(73),
                WorldEffect::CreateEntity {
                    entity_id: entity(74),
                },
                3,
            )],
            Vec::new(),
        ),
    );

    let first_store = Arc::clone(&store);
    let second_store = Arc::clone(&store);
    let (first_result, second_result) = std::thread::scope(|scope| {
        let first_handle = scope.spawn(|| first_store.commit(&first, None, PlatformTime::new(0)));
        let second_handle =
            scope.spawn(|| second_store.commit(&second, None, PlatformTime::new(0)));
        (
            first_handle
                .join()
                .expect("first commit thread should finish"),
            second_handle
                .join()
                .expect("second commit thread should finish"),
        )
    });
    assert_eq!(
        usize::from(first_result.is_ok()) + usize::from(second_result.is_ok()),
        1,
        "exactly one stale-CAS contender should win"
    );
    assert_eq!(
        usize::from(matches!(
            first_result,
            Err(CommitError::TimelineConflict { .. })
        )) + usize::from(matches!(
            second_result,
            Err(CommitError::TimelineConflict { .. })
        )),
        1,
        "the losing contender should observe a typed conflict"
    );
    assert_eq!(
        store
            .snapshot(timeline())
            .expect("snapshot should exist")
            .events
            .len(),
        1
    );
}

#[tokio::test]
async fn concurrent_claims_choose_one_fence_winner() {
    let store = Arc::new(InMemoryStore::new());
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(70)))
        .expect("Work fixture should be seeded");
    let claim_store = Arc::clone(&store);
    let other_claim_store = Arc::clone(&store);
    let (claim_one, claim_two) = std::thread::scope(|scope| {
        let claim_one_handle = scope.spawn(|| {
            claim_store.claim(
                timeline(),
                work(70),
                PlatformTime::new(0),
                PlatformTime::new(10),
            )
        });
        let claim_two_handle = scope.spawn(|| {
            other_claim_store.claim(
                timeline(),
                work(70),
                PlatformTime::new(0),
                PlatformTime::new(10),
            )
        });
        (
            claim_one_handle
                .join()
                .expect("first claim thread should finish"),
            claim_two_handle
                .join()
                .expect("second claim thread should finish"),
        )
    });
    assert_eq!(
        usize::from(claim_one.is_ok()) + usize::from(claim_two.is_ok()),
        1
    );
    assert_eq!(
        usize::from(matches!(
            claim_one,
            Err(loom_runtime::WorkError::AlreadyClaimed { .. })
        )) + usize::from(matches!(
            claim_two,
            Err(loom_runtime::WorkError::AlreadyClaimed { .. })
        )),
        1
    );
}
