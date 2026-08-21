use loom_api::{
    ActionRequest, ApiErrorCode, EventQuery, ExecutionResult, FacetQuery, LoomApi, TimelineTarget,
};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EventDefinition, FacetDefinition, RegistrationError, ResolutionContext,
    ResolverError, WorkHandler, WorkHandlerDefinition,
};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventTypeId, FacetOwner, FacetTypeId, SchemaRevision,
    TimelineId, WorkHandlerId, WorkId, WorldEffect, WorldId,
};
use loom_protocol::{ActionInvocation, Rejection, ResolveOutcome};
use loom_runtime::{PlatformTime, ProposedEvent, Resolution, Runtime, WorkRecord, WorkStatus};
use loom_storage::InMemoryStore;
use serde_json::{Value, json};

const COUNTER_CAPABILITY: &str = "counter.basic";
const COUNTER_FACET: &str = "counter.value";
const COUNTER_INCREMENT: &str = "counter.increment";
const COUNTER_OBSERVE: &str = "counter.observe";
const COUNTER_INCREMENTED: &str = "counter.incremented";
const COUNTER_OBSERVED: &str = "counter.observed";
const COUNTER_WORK_HANDLER: &str = "counter.increment_work";

fn id<T>(value: u128) -> T
where
    T: std::str::FromStr,
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
