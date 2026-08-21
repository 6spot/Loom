mod support;

use std::str::FromStr;

use loom_api::{ActionRequest, EventQuery, ExecutionResult, FacetQuery, LoomApi, TimelineTarget};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EventDefinition, FacetDefinition, RegistrationError, ResolutionContext,
    ResolverError,
};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventTypeId, FacetOwner, FacetTypeId, SchemaRevision,
    TimelineId, WorldEffect, WorldId,
};
use loom_protocol::{ActionInvocation, ProposedEvent, Rejection, Resolution, ResolveOutcome};
use loom_runtime::{Runtime, WorldStore};
use loom_storage::PgStorage;
use serde_json::{Value, json};
use sqlx::PgPool;
use support::TestDatabase;

const OWNER: &str = "postgres.vertical.counter";
const FACET: &str = "postgres.vertical.counter.value";
const INCREMENT: &str = "postgres.vertical.counter.increment";
const OBSERVE: &str = "postgres.vertical.counter.observe";
const NO_CHANGE: &str = "postgres.vertical.counter.no_change";
const INCREMENTED: &str = "postgres.vertical.counter.incremented";
const OBSERVED: &str = "postgres.vertical.counter.observed";

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
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
            EventDefinition::new(EventTypeId::from(INCREMENTED), SchemaRevision::new(1))
                .with_payload_schema(json!({
                    "type": "object",
                    "required": ["previous", "amount", "value"],
                    "properties": {
                        "previous": {"type": "integer"},
                        "amount": {"type": "integer"},
                        "value": {"type": "integer"}
                    }
                })),
        )?;
        registrar.register_event(
            EventDefinition::new(EventTypeId::from(OBSERVED), SchemaRevision::new(1))
                .with_payload_schema(json!({
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"type": "integer"}}
                })),
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(INCREMENT), SchemaRevision::new(1))
                .with_input_schema(json!({
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
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(OBSERVE), SchemaRevision::new(1))
                .with_input_schema(json!({
                    "type": "object",
                    "required": ["event_id"],
                    "properties": {"event_id": {"type": "string"}}
                })),
            CounterObserver {
                entity_id: self.entity_id,
            },
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(NO_CHANGE), SchemaRevision::new(1))
                .with_input_schema(json!({"type": "object"})),
            NoChangeResolver,
        )?;
        Ok(())
    }
}

#[derive(Clone, Copy)]
struct CounterIncrementer {
    entity_id: EntityId,
}

impl ActionResolver for CounterIncrementer {
    fn resolve(
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
                "postgres.vertical.invalid_amount",
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
            EventTypeId::from(INCREMENTED),
            SchemaRevision::new(1),
            context.world_time(),
            json!({"previous": current, "amount": amount, "value": next}),
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(self.entity_id),
            facet_type: FacetTypeId::from(FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": next}),
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
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
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![ProposedEvent::new(
                event_id,
                EventTypeId::from(OBSERVED),
                SchemaRevision::new(1),
                context.world_time(),
                json!({"value": current}),
            )],
            Vec::new(),
        )))
    }
}

struct NoChangeResolver;

impl ActionResolver for NoChangeResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        _input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Ok(ResolveOutcome::Resolved(Resolution::default()))
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
    context
        .get_facet(FacetOwner::entity(entity_id), &FacetTypeId::from(FACET))?
        .ok_or_else(|| ResolverError::new("counter Facet is missing"))?
        .value
        .get("value")
        .and_then(Value::as_i64)
        .ok_or_else(|| ResolverError::new("counter Facet value is not an integer"))
}

fn registry(entity_id: EntityId) -> CapabilityRegistry {
    CapabilityRegistry::assemble([CounterCapability {
        manifest: CapabilityManifest::parse(OWNER, "0.1.0")
            .expect("test Capability manifest should parse"),
        entity_id,
    }])
    .expect("test Capability registry should assemble")
}

fn request(target: TimelineTarget, action: &str, input: Value) -> ActionRequest {
    ActionRequest::new(
        target,
        ActionInvocation::new(ActionTypeId::from(action), input),
    )
}

async fn authority() -> Option<(TestDatabase, PgStorage, PgPool, WorldId, TimelineId, EntityId)> {
    let database = TestDatabase::provision("vertical").await?;
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id: WorldId = id(0x3100);
    let timeline_id: TimelineId = id(0x3101);
    let entity_id: EntityId = id(0x3110);

    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
        .bind(world_id.to_string())
        .execute(&pool)
        .await
        .expect("vertical fixture World should insert");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(timeline_id.to_string())
        .bind(world_id.to_string())
        .execute(&pool)
        .await
        .expect("vertical fixture Timeline should insert");
    sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
        .bind(timeline_id.to_string())
        .bind(entity_id.to_string())
        .execute(&pool)
        .await
        .expect("vertical fixture Entity should insert");
    sqlx::query(
        "INSERT INTO loom_entity_facet \
         (timeline_id, entity_id, facet_type, schema_revision, value) \
         VALUES ($1::uuid, $2::uuid, $3, 1, '{\"value\":0}'::jsonb)",
    )
    .bind(timeline_id.to_string())
    .bind(entity_id.to_string())
    .bind(FACET)
    .execute(&pool)
    .await
    .expect("vertical fixture Facet should insert");

    Some((database, storage, pool, world_id, timeline_id, entity_id))
}

#[tokio::test]
async fn postgres_18_public_vertical_slice_preserves_milestone_1_semantics() {
    let Some((database, storage, pool, world_id, timeline_id, entity_id)) = authority().await else {
        return;
    };
    let target = TimelineTarget::new(world_id, timeline_id);
    let runtime = Runtime::new(storage.clone(), registry(entity_id)).expect("Runtime should assemble");
    let api: &dyn LoomApi = &runtime;

    let first = api
        .invoke(request(
            target,
            INCREMENT,
            json!({"amount": 2, "event_id": id::<EventId>(0x3120).to_string()}),
        ))
        .await
        .expect("first public increment should execute");
    assert!(first.is_committed());
    assert_eq!(facet_value(api, target, entity_id).await, 2);

    let second = api
        .invoke(request(
            target,
            INCREMENT,
            json!({"amount": 3, "event_id": id::<EventId>(0x3121).to_string()}),
        ))
        .await
        .expect("second public increment should execute");
    assert!(second.is_committed());
    assert_eq!(facet_value(api, target, entity_id).await, 5);

    let before_rejection = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Timeline should be readable before rejection");
    let rejected = api
        .invoke(request(
            target,
            INCREMENT,
            json!({"amount": 0, "event_id": id::<EventId>(0x3122).to_string()}),
        ))
        .await
        .expect("semantic rejection should be a normal public outcome");
    assert!(matches!(rejected, ExecutionResult::Rejected(_)));
    let after_rejection = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Timeline should remain readable after rejection");
    assert_eq!(after_rejection.version(), before_rejection.version());
    assert_eq!(after_rejection.world_time(), before_rejection.world_time());
    assert_eq!(after_rejection.events.len(), before_rejection.events.len());
    assert_eq!(facet_value(api, target, entity_id).await, 5);

    let zero_effect = api
        .invoke(request(
            target,
            OBSERVE,
            json!({"event_id": id::<EventId>(0x3123).to_string()}),
        ))
        .await
        .expect("zero-Effect Event should commit through the public API");
    assert!(zero_effect.is_committed());
    let after_zero_effect = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Timeline should be readable after zero-Effect Event");
    assert_eq!(
        after_zero_effect.version().head_event_seq.value(),
        before_rejection.version().head_event_seq.value() + 1
    );
    assert_eq!(
        after_zero_effect.version().state_revision,
        before_rejection.version().state_revision
    );
    assert_eq!(facet_value(api, target, entity_id).await, 5);
    let history = api
        .list_events(EventQuery::all(target))
        .await
        .expect("public Event history should be readable");
    assert_eq!(history.len(), 3);
    assert!(history.last().expect("observation should exist").effects.is_empty());

    let before_no_change = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Timeline should be readable before NoChange");
    let no_change = api
        .invoke(request(target, NO_CHANGE, json!({})))
        .await
        .expect("true NoChange should be a normal public outcome");
    assert!(no_change.is_no_change());
    let after_no_change = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Timeline should remain readable after NoChange");
    assert_eq!(after_no_change.version(), before_no_change.version());
    assert_eq!(after_no_change.world_time(), before_no_change.world_time());
    assert_eq!(after_no_change.events.len(), before_no_change.events.len());
    assert_eq!(facet_value(api, target, entity_id).await, 5);

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

async fn facet_value(api: &dyn LoomApi, target: TimelineTarget, entity_id: EntityId) -> i64 {
    api.get_facet(FacetQuery::new(
        target,
        FacetOwner::entity(entity_id),
        FacetTypeId::from(FACET),
    ))
    .await
    .expect("public Facet query should succeed")
    .expect("counter Facet should exist")
    .value
    .get("value")
    .and_then(Value::as_i64)
    .expect("counter Facet value should remain an integer")
}
