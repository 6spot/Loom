#[allow(dead_code)]
mod support;

use std::str::FromStr;

use loom_api::{ActionRequest, CreateWorldRequest, EventQuery, FacetQuery, LoomApi};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EventDefinition, RegistrationError, ResolutionContext, ResolverError,
    WorkHandler, WorkHandlerDefinition,
};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventTypeId, FacetOwner, FacetTypeId, SchemaRevision,
    WorkHandlerId, WorkId, WorldEffect, WorldInstant,
};
use loom_protocol::{
    ActionInvocation, NewWork, ProposedEvent, Resolution, ResolveOutcome, WorkMutation,
    WorkSchedule,
};
use loom_runtime::{PlatformTime, Runtime, WorkStatus, WorldStore};
use serde_json::{Value, json};

use support::TestDatabase;

const OWNER: &str = "postgres.restart_resume";
const FACET: &str = "postgres.restart_resume.counter";
const BOOTSTRAP_ACTION: &str = "postgres.restart_resume.bootstrap";
const CONTINUE_ACTION: &str = "postgres.restart_resume.continue";
const BOOTSTRAPPED_EVENT: &str = "postgres.restart_resume.bootstrapped";
const CONTINUED_EVENT: &str = "postgres.restart_resume.continued";
const WORK_EVENT: &str = "postgres.restart_resume.work_applied";
const WORK_HANDLER: &str = "postgres.restart_resume.apply_work";

const ENTITY_ID: u128 = 0x5110;
const BOOTSTRAP_EVENT_ID: u128 = 0x5120;
const CONTINUE_EVENT_ID: u128 = 0x5121;
const WORK_EVENT_ID: u128 = 0x5122;
const WORK_ID: u128 = 0x5130;

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

struct RestartResumeCapability {
    manifest: CapabilityManifest,
}

impl Capability for RestartResumeCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_facet(loom_capability::FacetDefinition::new(
            FacetTypeId::from(FACET),
            SchemaRevision::new(1),
            json!({
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "integer"}}
            }),
        ))?;
        for event_type in [BOOTSTRAPPED_EVENT, CONTINUED_EVENT, WORK_EVENT] {
            registrar.register_event(
                EventDefinition::new(EventTypeId::from(event_type), SchemaRevision::new(1))
                    .with_payload_schema(json!({
                        "type": "object",
                        "required": ["value"],
                        "properties": {"value": {"type": "integer"}}
                    })),
            )?;
        }
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(BOOTSTRAP_ACTION), SchemaRevision::new(1))
                .with_input_schema(json!({
                    "type": "object",
                    "required": ["event_id", "entity_id", "work_id"],
                    "properties": {
                        "event_id": {"type": "string"},
                        "entity_id": {"type": "string"},
                        "work_id": {"type": "string"}
                    }
                })),
            BootstrapResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(CONTINUE_ACTION), SchemaRevision::new(1))
                .with_input_schema(json!({
                    "type": "object",
                    "required": ["event_id"],
                    "properties": {"event_id": {"type": "string"}}
                })),
            ContinueResolver,
        )?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(WorkHandlerId::from(WORK_HANDLER), SchemaRevision::new(1))
                .with_payload_schema(json!({
                    "type": "object",
                    "required": ["event_id", "entity_id"],
                    "properties": {
                        "event_id": {"type": "string"},
                        "entity_id": {"type": "string"}
                    }
                })),
            WorkResolver,
        )?;
        Ok(())
    }
}

struct BootstrapResolver;

impl ActionResolver for BootstrapResolver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id(input, "event_id")?;
        let entity_id = parse_id(input, "entity_id")?;
        let work_id = parse_id(input, "work_id")?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(BOOTSTRAPPED_EVENT),
            SchemaRevision::new(1),
            context.world_time(),
            json!({"value": 1}),
        )
        .with_effect(WorldEffect::CreateEntity { entity_id })
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity_id),
            facet_type: FacetTypeId::from(FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": 1}),
        });
        let work = NewWork::new(
            work_id,
            context.timeline_id(),
            WorkHandlerId::from(WORK_HANDLER),
            SchemaRevision::new(1),
            json!({
                "event_id": id::<EventId>(WORK_EVENT_ID).to_string(),
                "entity_id": entity_id.to_string()
            }),
            WorkSchedule::Immediate,
        );
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            vec![WorkMutation::Schedule(work)],
        )))
    }
}

struct ContinueResolver;

impl ActionResolver for ContinueResolver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id(input, "event_id")?;
        let current = counter_value(context, id(ENTITY_ID))?;
        let next = current
            .checked_add(1)
            .ok_or_else(|| ResolverError::new("counter value overflowed"))?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(CONTINUED_EVENT),
            SchemaRevision::new(1),
            context.world_time(),
            json!({"value": next}),
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(id(ENTITY_ID)),
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

struct WorkResolver;

impl WorkHandler for WorkResolver {
    fn handle(
        &self,
        context: &dyn ResolutionContext,
        payload: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id(payload, "event_id")?;
        let entity_id = parse_id(payload, "entity_id")?;
        let current = counter_value(context, entity_id)?;
        let next = current
            .checked_add(1)
            .ok_or_else(|| ResolverError::new("counter value overflowed"))?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(WORK_EVENT),
            SchemaRevision::new(1),
            context.world_time(),
            json!({"value": next}),
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity_id),
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

fn counter_value(
    context: &dyn ResolutionContext,
    entity_id: EntityId,
) -> Result<i64, ResolverError> {
    context
        .get_facet(FacetOwner::entity(entity_id), &FacetTypeId::from(FACET))
        .map_err(|error| ResolverError::new(error.to_string()))?
        .ok_or_else(|| ResolverError::new("counter Facet is missing"))?
        .value
        .get("value")
        .and_then(Value::as_i64)
        .ok_or_else(|| ResolverError::new("counter Facet value is not an integer"))
}

fn registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([RestartResumeCapability {
        manifest: CapabilityManifest::parse(OWNER, "0.1.0")
            .expect("restart/resume Capability manifest should parse"),
    }])
    .expect("restart/resume Capability registry should assemble")
}

fn request(target: loom_api::TimelineTarget, action: &str, input: Value) -> ActionRequest {
    ActionRequest::new(
        target,
        ActionInvocation::new(ActionTypeId::from(action), input),
    )
}

fn counter_query(target: loom_api::TimelineTarget) -> FacetQuery {
    FacetQuery::new(
        target,
        FacetOwner::entity(id(ENTITY_ID)),
        FacetTypeId::from(FACET),
    )
}

async fn public_counter(api: &dyn LoomApi, target: loom_api::TimelineTarget) -> i64 {
    api.get_facet(counter_query(target))
        .await
        .expect("public Facet read should succeed")
        .expect("restart/resume counter Facet should exist")
        .value
        .get("value")
        .and_then(Value::as_i64)
        .expect("counter value should be an integer")
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the restart/resume acceptance scenario is intentionally linear"
)]
async fn postgres_18_runtime_reconstruction_continues_world_and_pending_work() {
    let Some(database) = TestDatabase::provision("restart_resume").await else {
        return;
    };

    let first_storage = database.storage().await;
    let first_runtime = Runtime::new(first_storage, registry()).expect("Runtime should assemble");
    let first_api: &dyn LoomApi = &first_runtime;
    let created = first_api
        .create_world(CreateWorldRequest::new(WorldInstant::new(7)))
        .await
        .expect("public WorldService creation should succeed");
    assert_eq!(created.version, loom_core::TimelineVersion::default());
    assert_eq!(created.world_time, WorldInstant::new(7));

    let target = created.target;
    let bootstrap_event_id = id::<EventId>(BOOTSTRAP_EVENT_ID);
    let bootstrap = first_api
        .invoke(request(
            target,
            BOOTSTRAP_ACTION,
            json!({
                "event_id": bootstrap_event_id.to_string(),
                "entity_id": id::<EntityId>(ENTITY_ID).to_string(),
                "work_id": id::<WorkId>(WORK_ID).to_string()
            }),
        ))
        .await
        .expect("initial semantic Action should commit through Runtime");
    assert!(bootstrap.is_committed());
    assert_eq!(public_counter(first_api, target).await, 1);
    assert_eq!(
        first_api
            .list_events(EventQuery::all(target))
            .await
            .unwrap()
            .len(),
        1
    );

    drop(first_runtime);

    let second_storage = database.storage().await;
    let read_storage = second_storage.clone();
    let second_runtime =
        Runtime::new(second_storage, registry()).expect("Runtime should reassemble");
    let second_api: &dyn LoomApi = &second_runtime;

    let inspected = second_api
        .inspect_timeline(target)
        .await
        .expect("reconstructed Runtime should read the existing Timeline");
    assert_eq!(inspected.target, target);
    assert_eq!(inspected.version.head_event_seq.value(), 1);
    assert_eq!(inspected.version.state_revision.value(), 1);
    assert_eq!(inspected.world_time, WorldInstant::new(7));
    assert_eq!(public_counter(second_api, target).await, 1);

    let durable_before_continue = WorldStore::snapshot(&read_storage, target.timeline_id)
        .await
        .expect("reconstructed Runtime read port should return durable state");
    assert_eq!(durable_before_continue.events.len(), 1);
    assert_eq!(durable_before_continue.events[0].id, bootstrap_event_id);
    assert_eq!(durable_before_continue.works.len(), 1);
    let pending = &durable_before_continue.works[0];
    assert_eq!(pending.id, id::<WorkId>(WORK_ID));
    assert_eq!(pending.status, WorkStatus::Pending);
    assert_eq!(pending.attempt_count, 0);
    assert_eq!(pending.claim_generation, 0);
    assert!(pending.lease.is_none());

    let continued = second_api
        .invoke(request(
            target,
            CONTINUE_ACTION,
            json!({"event_id": id::<EventId>(CONTINUE_EVENT_ID).to_string()}),
        ))
        .await
        .expect("second semantic Action should resolve from durable state");
    assert!(continued.is_committed());
    assert_eq!(public_counter(second_api, target).await, 2);

    let work_result = second_runtime
        .execute_work(
            target,
            id::<WorkId>(WORK_ID),
            PlatformTime::new(10),
            PlatformTime::new(20),
            PlatformTime::new(30),
        )
        .await
        .expect("inherited Work should claim and execute through Runtime");
    assert!(work_result.is_committed());
    assert_eq!(public_counter(second_api, target).await, 3);

    let durable_after_resume = WorldStore::snapshot(&read_storage, target.timeline_id)
        .await
        .expect("final Runtime read should return continuous authority state");
    assert_eq!(durable_after_resume.events.len(), 3);
    assert_eq!(durable_after_resume.events[0].id, bootstrap_event_id);
    assert_eq!(
        durable_after_resume.events[1].id,
        id::<EventId>(CONTINUE_EVENT_ID)
    );
    assert_eq!(
        durable_after_resume.events[2].id,
        id::<EventId>(WORK_EVENT_ID)
    );
    assert_eq!(durable_after_resume.works.len(), 1);
    let completed = &durable_after_resume.works[0];
    assert_eq!(completed.status, WorkStatus::Completed);
    assert_eq!(completed.attempt_count, 1);
    assert_eq!(completed.claim_generation, 1);
    assert!(completed.lease.is_none());

    drop(second_runtime);
    database.cleanup().await;
}
