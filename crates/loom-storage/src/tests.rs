use std::{str::FromStr, sync::Arc};

use loom_core::{
    ActionTypeId, EntityId, EventId, EventSeq, EventTypeId, FacetOwner, FacetTypeId,
    SchemaRevision, TimelineId, WorkHandlerId, WorkId, WorldEffect, WorldId, WorldInstant,
};
use loom_runtime::{
    CommitError, EffectEngine, NewWork, PlatformTime, ProposedEvent, Resolution, Runtime,
    WorkMutation, WorkRecord, WorkStatus,
    test_support::{
        ActionDefinition, ActionInvocation, ActionRequest, ActionResolver, ApiErrorCode,
        Capability, CapabilityManifest, CapabilityRegistrar, CapabilityRegistry, EventDefinition,
        EventQuery, ExecutionResult, FacetDefinition, FacetQuery, LoomApi, RegistrationError,
        Rejection, ResolutionContext, ResolveOutcome, ResolverError, TimelineTarget, WorkHandler,
        WorkHandlerDefinition,
    },
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
    WorkRecord {
        id: work_id,
        timeline_id: timeline(),
        handler: WorkHandlerId::from("test.handler"),
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

fn event_with_effect(event_id: EventId, effect: WorldEffect, occurred_at: i64) -> ProposedEvent {
    ProposedEvent::new(
        event_id,
        EventTypeId::from("test.changed"),
        SchemaRevision::new(1),
        WorldInstant::new(occurred_at),
        json!({"event": event_id.to_string()}),
    )
    .with_effect(effect)
}

struct TestCapability {
    manifest: CapabilityManifest,
}

impl Capability for TestCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_event(EventDefinition::new(
            EventTypeId::from("test.changed"),
            SchemaRevision::new(1),
        ))
    }
}

const COUNTER_CAPABILITY: &str = "counter.basic";
const COUNTER_FACET: &str = "counter.value";
const COUNTER_INCREMENT: &str = "counter.increment";
const COUNTER_OBSERVE: &str = "counter.observe";
const COUNTER_INCREMENTED: &str = "counter.incremented";
const COUNTER_OBSERVED: &str = "counter.observed";
const COUNTER_WORK_HANDLER: &str = "counter.increment_work";

struct CounterCapability {
    manifest: CapabilityManifest,
    entity_id: EntityId,
}

impl Capability for CounterCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_facet(
            FacetDefinition::new(
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
        registrar.register_event(
            EventDefinition::new(
                EventTypeId::from(COUNTER_INCREMENTED),
                SchemaRevision::new(1),
            )
            .with_payload_schema(counter_event_schema()),
        )?;
        registrar.register_event(
            EventDefinition::new(EventTypeId::from(COUNTER_OBSERVED), SchemaRevision::new(1))
                .with_payload_schema(json!({
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"type": "integer"}}
                })),
        )?;
        registrar.register_action(
            ActionDefinition::new(
                ActionTypeId::from(COUNTER_INCREMENT),
                SchemaRevision::new(1),
            )
            .with_input_schema(json!({
                "type": "object",
                "required": ["amount", "event_id"],
                "properties": {
                    "amount": {"type": "integer"},
                    "event_id": {"type": "string"}
                }
            }))
            .with_description("Increment the neutral counter."),
            CounterIncrementer {
                entity_id: self.entity_id,
            },
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(COUNTER_OBSERVE), SchemaRevision::new(1))
                .with_input_schema(json!({
                    "type": "object",
                    "required": ["event_id"],
                    "properties": {"event_id": {"type": "string"}}
                }))
                .with_description("Record a zero-Effect observation."),
            CounterObserver {
                entity_id: self.entity_id,
            },
        )?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(
                WorkHandlerId::from(COUNTER_WORK_HANDLER),
                SchemaRevision::new(1),
            )
            .with_payload_schema(json!({
                "type": "object",
                "required": ["amount", "event_id"],
                "properties": {
                    "amount": {"type": "integer"},
                    "event_id": {"type": "string"}
                }
            })),
            CounterIncrementer {
                entity_id: self.entity_id,
            },
        )?;
        Ok(())
    }
}

fn counter_event_schema() -> Value {
    json!({
        "type": "object",
        "required": ["previous", "amount", "value"],
        "properties": {
            "previous": {"type": "integer"},
            "amount": {"type": "integer"},
            "value": {"type": "integer"}
        }
    })
}

#[derive(Clone, Copy)]
struct CounterIncrementer {
    entity_id: EntityId,
}

impl CounterIncrementer {
    fn resolve_increment(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let amount = input
            .get("amount")
            .and_then(Value::as_i64)
            .ok_or_else(|| ResolverError::new("amount must be an integer"))?;
        if amount <= 0 {
            return Ok(ResolveOutcome::Rejected(Rejection::new(
                "counter.invalid_amount",
                "amount must be positive",
            )));
        }
        let event_id = parse_event_id(input)?;
        let current = read_counter(context, self.entity_id)?;
        let next = current
            .checked_add(amount)
            .ok_or_else(|| ResolverError::new("counter value overflowed"))?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(COUNTER_INCREMENTED),
            SchemaRevision::new(1),
            context.world_time(),
            json!({"previous": current, "amount": amount, "value": next}),
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(self.entity_id),
            facet_type: FacetTypeId::from(COUNTER_FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": next}),
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

impl ActionResolver for CounterIncrementer {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        self.resolve_increment(context, input)
    }
}

impl WorkHandler for CounterIncrementer {
    fn handle(
        &self,
        context: &dyn ResolutionContext,
        payload: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        self.resolve_increment(context, payload)
    }
}

#[derive(Clone, Copy)]
struct CounterObserver {
    entity_id: EntityId,
}

impl ActionResolver for CounterObserver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_event_id(input)?;
        let current = read_counter(context, self.entity_id)?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(COUNTER_OBSERVED),
            SchemaRevision::new(1),
            context.world_time(),
            json!({"value": current}),
        );
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

fn parse_event_id(input: &Value) -> Result<EventId, ResolverError> {
    input
        .get("event_id")
        .and_then(Value::as_str)
        .ok_or_else(|| ResolverError::new("event_id must be a UUID string"))?
        .parse()
        .map_err(|_| ResolverError::new("event_id must be a UUID string"))
}

fn read_counter(
    context: &dyn ResolutionContext,
    entity_id: EntityId,
) -> Result<i64, ResolverError> {
    let facet = context
        .get_facet(
            FacetOwner::entity(entity_id),
            &FacetTypeId::from(COUNTER_FACET),
        )?
        .ok_or_else(|| ResolverError::new("counter Facet is missing"))?;
    facet
        .value
        .get("value")
        .and_then(Value::as_i64)
        .ok_or_else(|| ResolverError::new("counter Facet value is not an integer"))
}

fn counter_target() -> TimelineTarget {
    TimelineTarget::new(world(), timeline())
}

fn counter_store() -> InMemoryStore {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("counter Timeline should be created");
    store
        .seed_entity(
            timeline(),
            loom_core::Entity {
                id: entity(10),
                world_id: world(),
            },
        )
        .expect("counter Entity should be seeded");
    store
        .seed_facet(
            timeline(),
            FacetOwner::entity(entity(10)),
            FacetTypeId::from(COUNTER_FACET),
            SchemaRevision::new(1),
            json!({"value": 0}),
        )
        .expect("counter Facet should be seeded");
    store
}

fn counter_registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([CounterCapability {
        manifest: CapabilityManifest::parse(COUNTER_CAPABILITY, "0.1.0")
            .expect("counter Capability manifest should parse")
            .with_description("A neutral counter test Capability."),
        entity_id: entity(10),
    }])
    .expect("counter Capability registry should assemble")
}

fn counter_request(action: &str, input: Value) -> ActionRequest {
    ActionRequest::new(
        counter_target(),
        ActionInvocation::new(ActionTypeId::from(action), input),
    )
}

#[test]
fn vertical_slice_runs_through_loom_api_and_inspects_committed_state_and_history() {
    let store = counter_store();
    let runtime = Runtime::new(&store, counter_registry()).expect("Runtime should assemble");
    let api: &dyn LoomApi = &runtime;

    let first = api
        .invoke(counter_request(
            COUNTER_INCREMENT,
            json!({"amount": 2, "event_id": event(10).to_string()}),
        ))
        .expect("first increment should execute");
    assert!(matches!(first, ExecutionResult::Committed { .. }));
    assert_eq!(
        api.get_facet(FacetQuery::new(
            counter_target(),
            FacetOwner::entity(entity(10)),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .expect("first state query should succeed")
        .expect("counter Facet should exist")
        .value,
        json!({"value": 2})
    );

    let second = api
        .invoke(counter_request(
            COUNTER_INCREMENT,
            json!({"amount": 3, "event_id": event(11).to_string()}),
        ))
        .expect("second increment should execute");
    assert!(matches!(second, ExecutionResult::Committed { .. }));
    assert_eq!(
        api.get_facet(FacetQuery::new(
            counter_target(),
            FacetOwner::entity(entity(10)),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .expect("second state query should succeed")
        .expect("counter Facet should exist")
        .value,
        json!({"value": 5})
    );

    let rejected = api
        .invoke(counter_request(
            COUNTER_INCREMENT,
            json!({"amount": 0, "event_id": event(12).to_string()}),
        ))
        .expect("invalid amount should be a normal outcome");
    match rejected {
        ExecutionResult::Rejected(rejection) => {
            assert_eq!(rejection.code.as_str(), "counter.invalid_amount");
        }
        other => panic!("expected public rejection, got {other:?}"),
    }

    let zero_effect = api
        .invoke(counter_request(
            COUNTER_OBSERVE,
            json!({"event_id": event(13).to_string()}),
        ))
        .expect("zero-Effect observation should execute");
    assert!(matches!(zero_effect, ExecutionResult::Committed { .. }));
    assert_eq!(
        api.get_facet(FacetQuery::new(
            counter_target(),
            FacetOwner::entity(entity(10)),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .expect("post-observation state query should succeed")
        .expect("counter Facet should exist")
        .value,
        json!({"value": 5})
    );

    let history = api
        .list_events(EventQuery::all(counter_target()))
        .expect("history query should succeed");
    assert_eq!(history.len(), 3);
    assert_eq!(history[0].sequence.value(), 1);
    assert_eq!(history[1].sequence.value(), 2);
    assert!(history[2].effects.is_empty());

    let catalog = api.catalog().expect("catalog query should succeed");
    assert_eq!(catalog.capabilities[0].id.as_str(), COUNTER_CAPABILITY);
    assert_eq!(
        catalog
            .action(&ActionTypeId::from(COUNTER_INCREMENT))
            .expect("increment should be discoverable")
            .owner
            .as_str(),
        COUNTER_CAPABILITY
    );
}

#[test]
fn vertical_slice_executes_durable_work_and_completes_atomically() {
    let store = counter_store();
    store
        .seed_work(WorkRecord {
            id: work(20),
            timeline_id: timeline(),
            handler: WorkHandlerId::from(COUNTER_WORK_HANDLER),
            schema_revision: SchemaRevision::new(1),
            payload: json!({"amount": 4, "event_id": event(20).to_string()}),
            due_world_time: None,
            causal_event_id: None,
            origin_work_id: None,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at: PlatformTime::new(0),
            last_error: None,
            lease: None,
        })
        .expect("counter Work should be seeded");
    let runtime = Runtime::new(&store, counter_registry()).expect("Runtime should assemble");
    let api: &dyn LoomApi = &runtime;

    let result = runtime
        .execute_work(
            counter_target(),
            work(20),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(2),
        )
        .expect("Work should commit through Runtime");
    assert!(matches!(result, ExecutionResult::Committed { .. }));
    assert_eq!(
        api.get_facet(FacetQuery::new(
            counter_target(),
            FacetOwner::entity(entity(10)),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .expect("Work state query should succeed")
        .expect("counter Facet should exist")
        .value,
        json!({"value": 4})
    );
    assert_eq!(
        store
            .work(timeline(), work(20))
            .expect("Work lookup should succeed")
            .expect("completed Work should remain inspectable")
            .status,
        WorkStatus::Completed
    );
}

#[test]
fn vertical_slice_technical_retry_leaves_world_truth_unchanged() {
    let retry_store = counter_store();
    retry_store
        .seed_work(WorkRecord {
            id: work(21),
            timeline_id: timeline(),
            handler: WorkHandlerId::from(COUNTER_WORK_HANDLER),
            schema_revision: SchemaRevision::new(1),
            payload: json!({"event_id": event(21).to_string()}),
            due_world_time: None,
            causal_event_id: None,
            origin_work_id: None,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at: PlatformTime::new(0),
            last_error: None,
            lease: None,
        })
        .expect("retry Work should be seeded");
    let retry_runtime =
        Runtime::new(&retry_store, counter_registry()).expect("retry Runtime should assemble");
    let retry_error = retry_runtime
        .execute_work(
            counter_target(),
            work(21),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(3),
        )
        .expect_err("technical handler failure should use retry path");
    assert_eq!(retry_error.code, ApiErrorCode::Internal);
    let retry_snapshot = retry_store
        .snapshot(timeline())
        .expect("retry Timeline should remain readable");
    assert!(retry_snapshot.events.is_empty());
    assert_eq!(
        retry_snapshot
            .world_view()
            .facet(
                FacetOwner::entity(entity(10)),
                &FacetTypeId::from(COUNTER_FACET),
            )
            .expect("seeded counter Facet should remain present")
            .value(),
        &json!({"value": 0})
    );
    let retried_work = retry_store
        .work(timeline(), work(21))
        .expect("retry Work lookup should succeed")
        .expect("retried Work should remain inspectable");
    assert_eq!(retried_work.status, WorkStatus::Pending);
    assert_eq!(retried_work.available_at, PlatformTime::new(3));
    assert!(retried_work.lease.is_none());
}

#[test]
fn commit_assigns_contiguous_event_sequences_and_advances_once() {
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
                WorldInstant::new(3),
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
    assert_eq!(snapshot.world_time(), WorldInstant::new(5));
    assert!(snapshot.world_view().entity(entity(20)).is_some());
}

#[test]
fn stale_cas_leaves_event_state_and_work_unchanged() {
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

#[test]
fn staged_commit_does_not_expose_event_before_work_failure() {
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
            loom_runtime::WorkSchedule::Immediate,
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

#[test]
fn work_creation_and_current_completion_share_zero_event_commit() {
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
    let registry = CapabilityRegistry::new();
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
                loom_runtime::WorkSchedule::At(WorldInstant::new(100)),
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

#[test]
fn retry_and_expired_claims_preserve_work_identity_and_fence_winner() {
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

#[test]
fn concurrent_cas_and_claim_choose_one_winner() {
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

#[test]
fn concurrent_claims_choose_one_fence_winner() {
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
