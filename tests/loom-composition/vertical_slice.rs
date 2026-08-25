use std::{
    fs,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::Instant,
};

use loom_api::{
    ActionRequest, ActionService, ApiErrorCode, CausalDirection, CausalQuery,
    EntityTrajectoryQuery, EventQuery, ExecutionResult, FacetQuery, IngressAuthorizationContext,
    IngressEnvelope, IngressProvenance, IngressService, IngressStatus, IngressTimeMetadata,
    LoomApi, RelationshipTrajectoryQuery, TimelineTarget,
};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityId, CapabilityManifest,
    CapabilityRegistrar, CapabilityRegistry, EventDefinition, FacetDefinition, RegistrationError,
    ResolutionContext, ResolverError, SemanticIndexDefinition, SemanticIndexMetric,
    SemanticIndexSource, WorkHandler, WorkHandlerDefinition,
};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventRef, EventTypeId, FacetOwner, FacetTypeId, Relationship,
    RelationshipId, RelationshipParticipant, RelationshipTypeId, SchemaRevision, TimelineId,
    TimelineVersion, WorkHandlerId, WorkId, WorldEffect, WorldId, WorldInstant,
};
use loom_protocol::{
    ActionInvocation, CausalLink, EventRelationshipRef, NewWork, ProposedEvent, Rejection,
    Resolution, ResolveOutcome, WorkMutation, WorkSchedule,
};
use loom_runtime::{
    BlobError, BlobStore, EffectEngine, ExecutionSessionStore, FailurePolicy,
    LogicalWorkTransition, PinnedReadBoundary, PinnedReadPolicy, PinnedReadSession,
    PinnedWorldReadStore, PlatformTime, ReadError, Runtime, RuntimeError,
    RuntimeRevisionCapability, RuntimeRevisionDescriptor, RuntimeRevisionId, SemanticKind,
    SemanticProjectionError, SemanticProjectionKey, SemanticProjectionQuery,
    SemanticProjectionRebuild, SemanticProjectionRegistration, SemanticProjectionRow, TimelineFork,
    TimelineForkStore, ValidationError, WorkRecord, WorkStatus, WorkTarget, WorldRuntimeBinding,
    WorldRuntimeBindingStore,
};
use loom_storage::{InMemoryBlobStore, InMemoryStore, LocalBlobStore};
use semver::{Version, VersionReq};
use serde_json::{Value, json};
fn ensure_vertical_store(store: &InMemoryStore, reg: &loom_capability::CapabilityRegistry) {
    let descriptor = loom_runtime::RuntimeRevisionDescriptor::new(
        loom_runtime::RuntimeRevisionId::from("vertical-explicit-v0"),
        loom_runtime::PlatformTime::default(),
        "test-build",
        reg.loom_version().clone(),
        reg.capabilities().map(|manifest| {
            loom_runtime::RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("test:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("vertical revision should be valid");
    let binding = loom_runtime::WorldRuntimeBinding::new(
        reg.capabilities().map(|m| {
            (
                m.id.clone(),
                semver::VersionReq::parse("*").expect("req should parse"),
            )
        }),
        serde_json::json!({"fixture": "vertical-explicit-v0"}),
        1,
        Some("vertical-explicit-v0".to_owned()),
    );
    let _ = store.persist_binding(world(), binding);
    let _ = store.confirm_revision(descriptor.clone());
    let active = store.read_active_revision().unwrap_or(None);
    let needs_activation = active.as_ref().map_or(true, |s| {
        s.revision().id().as_str() != "vertical-explicit-v0"
    });
    if needs_activation {
        let expected = active.as_ref().map(|s| s.generation());
        let _ = store.activate_revision(
            descriptor.id().clone(),
            expected,
            loom_runtime::PlatformTime::default(),
        );
    }
}

const COUNTER_CAPABILITY: &str = "counter.basic";
const COUNTER_FACET: &str = "counter.value";
const COUNTER_INCREMENT: &str = "counter.increment";
const COUNTER_OBSERVE: &str = "counter.observe";
const COUNTER_INCREMENTED: &str = "counter.incremented";
const COUNTER_OBSERVED: &str = "counter.observed";
const COUNTER_WORK_HANDLER: &str = "counter.increment_work";
const SECONDARY_CAPABILITY: &str = "counter.secondary";
const COUNTER_INDEX: &str = "counter.semantic";
const SECONDARY_INDEX: &str = "secondary.semantic";

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
            .with_participant_role("subject".into())
            .with_payload_schema(counter_event_schema()),
        )?;
        registrar.register_event(
            EventDefinition::new(EventTypeId::from(COUNTER_OBSERVED), SchemaRevision::new(1))
                .with_participant_role("subject".into())
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
        registrar.register_semantic_index(SemanticIndexDefinition::new(
            COUNTER_INDEX,
            SemanticIndexSource::new("facet", COUNTER_FACET, SchemaRevision::new(1)),
            SchemaRevision::new(1),
            1,
            "counter-model-1",
            2,
            SemanticIndexMetric::Cosine,
            json!({"normalization": "unit"}),
        ))?;
        Ok(())
    }
}

struct SecondaryCapability {
    manifest: CapabilityManifest,
}

impl Capability for SecondaryCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_semantic_index(SemanticIndexDefinition::new(
            SECONDARY_INDEX,
            SemanticIndexSource::new("event", COUNTER_OBSERVED, SchemaRevision::new(1)),
            SchemaRevision::new(1),
            1,
            "secondary-model-1",
            2,
            SemanticIndexMetric::Euclidean,
            json!({}),
        ))?;
        Ok(())
    }
}

struct ProjectionRevisionCapability {
    manifest: CapabilityManifest,
    projection_revision: u64,
    model_revision: &'static str,
}

impl Capability for ProjectionRevisionCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_semantic_index(SemanticIndexDefinition::new(
            COUNTER_INDEX,
            SemanticIndexSource::new("facet", COUNTER_FACET, SchemaRevision::new(1)),
            SchemaRevision::new(1),
            self.projection_revision,
            self.model_revision,
            2,
            SemanticIndexMetric::Cosine,
            json!({"normalization": "unit"}),
        ))
    }
}

struct CountingActionResolver {
    calls: Arc<AtomicUsize>,
}

impl ActionResolver for CountingActionResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        _input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(ResolveOutcome::Rejected(Rejection::new(
            "counting.rejected",
            "test resolver reached",
        )))
    }
}

struct CountingCapability {
    manifest: CapabilityManifest,
    calls: Arc<AtomicUsize>,
}

impl Capability for CountingCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_action(
            ActionDefinition::new(
                ActionTypeId::from("counting.action"),
                SchemaRevision::new(1),
            )
            .with_input_schema(json!({
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "integer"}}
            })),
            CountingActionResolver {
                calls: Arc::clone(&self.calls),
            },
        )
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
        let mut event = ProposedEvent::new(
            event_id,
            EventTypeId::from(COUNTER_INCREMENTED),
            SchemaRevision::new(1),
            json!({"previous": current, "amount": amount, "value": next}),
        )
        .with_participant(loom_protocol::EventParticipant::new(
            self.entity_id,
            "subject",
        ))
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(self.entity_id),
            facet_type: FacetTypeId::from(COUNTER_FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": next}),
        });
        if let Some(cause) = input.get("cause_event_id") {
            let cause_event_id = cause
                .as_str()
                .ok_or_else(|| ResolverError::new("cause_event_id must be a UUID string"))?
                .parse()
                .map_err(|_| ResolverError::new("cause_event_id must be a UUID string"))?;
            event = event.with_causal_link(CausalLink::new(cause_event_id));
        }
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
            json!({"value": current}),
        )
        .with_participant(loom_protocol::EventParticipant::new(
            self.entity_id,
            "subject",
        ));
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

fn counter_registry_with_secondary() -> CapabilityRegistry {
    CapabilityRegistry::assemble(vec![
        Box::new(CounterCapability {
            manifest: CapabilityManifest::parse(COUNTER_CAPABILITY, "0.1.0")
                .expect("counter Capability manifest should parse")
                .with_description("A neutral counter test Capability."),
            entity_id: entity(10),
        }) as Box<dyn Capability>,
        Box::new(SecondaryCapability {
            manifest: CapabilityManifest::parse(SECONDARY_CAPABILITY, "0.1.0")
                .expect("secondary Capability manifest should parse"),
        }),
    ])
    .expect("counter and secondary Capability registry should assemble")
}

fn projection_v2_registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([ProjectionRevisionCapability {
        manifest: CapabilityManifest::parse(COUNTER_CAPABILITY, "0.1.0")
            .expect("projection v2 Capability manifest should parse"),
        projection_revision: 2,
        model_revision: "counter-model-2",
    }])
    .expect("projection v2 Capability registry should assemble")
}

fn counter_request(action: &str, input: Value) -> ActionRequest {
    ActionRequest::new(
        counter_target(),
        ActionInvocation::new(ActionTypeId::from(action), input),
    )
}

fn scheduled_counter_work(
    work_id: WorkId,
    handler: &str,
    schema_revision: SchemaRevision,
    payload: Value,
) -> Resolution {
    Resolution::new(
        Vec::new(),
        vec![WorkMutation::Schedule(NewWork::new(
            work_id,
            timeline(),
            WorkHandlerId::from(handler),
            schema_revision,
            payload,
            WorkSchedule::Immediate,
        ))],
    )
}

fn work_validation_error(
    registry: &CapabilityRegistry,
    base: &loom_runtime::BaseWorldView,
    proposer: &str,
    work_id: WorkId,
    handler: &str,
    schema_revision: SchemaRevision,
    payload: Value,
) -> RuntimeError {
    EffectEngine::new(registry)
        .validate(
            base,
            proposer,
            scheduled_counter_work(work_id, handler, schema_revision, payload),
        )
        .expect_err("invalid Work metadata must be rejected")
}

#[tokio::test]
async fn composition_invalid_action_input_is_stopped_before_resolver() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("counting Timeline should be created");
    let calls = Arc::new(AtomicUsize::new(0));
    let registry = CapabilityRegistry::assemble([CountingCapability {
        manifest: CapabilityManifest::parse("counting", "0.1.0")
            .expect("counting Capability manifest should parse"),
        calls: Arc::clone(&calls),
    }])
    .expect("counting Capability registry should assemble");
    ensure_vertical_store(&store, &registry);
    let runtime = Runtime::new(&store, registry).expect("Runtime should assemble");
    let api: &dyn LoomApi = &runtime;

    let invalid = api
        .invoke(counter_request(
            "counting.action",
            json!({"value": "not-an-integer"}),
        ))
        .await
        .expect_err("invalid Action input must be a request error");
    assert_eq!(invalid.code, ApiErrorCode::InvalidRequest);
    assert_eq!(calls.load(Ordering::SeqCst), 0);

    let valid = api
        .invoke(counter_request("counting.action", json!({"value": 1})))
        .await
        .expect("valid Action input should reach the resolver");
    assert!(matches!(valid, ExecutionResult::Rejected(_)));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn composition_work_schedule_validates_identity_and_payload_before_commit() {
    let store = counter_store();
    let registry = counter_registry();
    let base = store
        .snapshot(timeline())
        .expect("counter Timeline should exist")
        .world_view();
    let valid_payload = json!({"amount": 1, "event_id": event(90).to_string()});

    let unknown = work_validation_error(
        &registry,
        &base,
        COUNTER_CAPABILITY,
        work(90),
        "counter.unknown_work",
        SchemaRevision::new(1),
        valid_payload.clone(),
    );
    assert!(matches!(
        unknown,
        RuntimeError::Validation(ValidationError::UnknownSemantic {
            kind: SemanticKind::WorkHandler,
            ..
        })
    ));

    let owner = work_validation_error(
        &registry,
        &base,
        "another.capability",
        work(91),
        COUNTER_WORK_HANDLER,
        SchemaRevision::new(1),
        valid_payload.clone(),
    );
    assert!(matches!(
        owner,
        RuntimeError::Validation(ValidationError::SemanticOwnerMismatch {
            kind: SemanticKind::WorkHandler,
            ..
        })
    ));

    let revision = work_validation_error(
        &registry,
        &base,
        COUNTER_CAPABILITY,
        work(92),
        COUNTER_WORK_HANDLER,
        SchemaRevision::new(2),
        valid_payload.clone(),
    );
    assert!(matches!(
        revision,
        RuntimeError::Validation(ValidationError::SchemaRevisionMismatch {
            kind: SemanticKind::WorkHandler,
            ..
        })
    ));

    let payload = work_validation_error(
        &registry,
        &base,
        COUNTER_CAPABILITY,
        work(93),
        COUNTER_WORK_HANDLER,
        SchemaRevision::new(1),
        json!({
            "amount": "not-an-integer",
            "event_id": event(93).to_string()
        }),
    );
    assert!(matches!(
        payload,
        RuntimeError::Validation(ValidationError::SchemaViolation {
            kind: SemanticKind::WorkHandler,
            ..
        })
    ));

    let validated = EffectEngine::new(&registry)
        .validate(
            &base,
            COUNTER_CAPABILITY,
            scheduled_counter_work(
                work(94),
                COUNTER_WORK_HANDLER,
                SchemaRevision::new(1),
                valid_payload,
            ),
        )
        .expect("valid Work should remain schedulable");
    store
        .commit(&validated, None, PlatformTime::new(0))
        .expect("valid Work should commit");
    assert_eq!(
        store
            .work(timeline(), work(94))
            .expect("Work lookup should succeed")
            .expect("scheduled Work should exist")
            .status,
        WorkStatus::Pending
    );
}

#[tokio::test]
async fn vertical_slice_runs_through_loom_api_and_inspects_committed_state_and_history() {
    let store = counter_store();
    ensure_vertical_store(&store, &counter_registry());
    let runtime = Runtime::new(&store, counter_registry()).expect("Runtime should assemble");
    let api: &dyn LoomApi = &runtime;

    let first = api
        .invoke(counter_request(
            COUNTER_INCREMENT,
            json!({"amount": 2, "event_id": event(10).to_string()}),
        ))
        .await
        .expect("first increment should execute");
    assert!(matches!(first, ExecutionResult::Committed { .. }));
    assert_eq!(
        api.get_facet(FacetQuery::new(
            counter_target(),
            FacetOwner::entity(entity(10)),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .await
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
        .await
        .expect("second increment should execute");
    assert!(matches!(second, ExecutionResult::Committed { .. }));
    assert_eq!(
        api.get_facet(FacetQuery::new(
            counter_target(),
            FacetOwner::entity(entity(10)),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .await
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
        .await
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
        .await
        .expect("zero-Effect observation should execute");
    assert!(matches!(zero_effect, ExecutionResult::Committed { .. }));
    assert_eq!(
        api.get_facet(FacetQuery::new(
            counter_target(),
            FacetOwner::entity(entity(10)),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .await
        .expect("post-observation state query should succeed")
        .expect("counter Facet should exist")
        .value,
        json!({"value": 5})
    );

    let history = api
        .list_events(EventQuery::all(counter_target()))
        .await
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

#[tokio::test]
async fn ingress_runs_through_the_normal_action_authority_and_persists_provenance() {
    let store = counter_store();
    ensure_vertical_store(&store, &counter_registry());
    let runtime = Runtime::new(&store, counter_registry()).expect("Runtime should assemble");
    let request = IngressEnvelope::new(
        "ingress-commit-1",
        "counter-key-1",
        IngressProvenance::new("composition-test"),
        counter_target(),
        IngressAuthorizationContext::new(json!({"role": "test"})),
        IngressTimeMetadata::none(),
        ActionInvocation::new(
            ActionTypeId::from(COUNTER_INCREMENT),
            json!({"amount": 2, "event_id": event(180).to_string()}),
        ),
    );

    let accepted = runtime
        .submit_ingress(request)
        .await
        .expect("Ingress should be accepted");
    assert!(accepted.is_accepted());
    let completion = runtime
        .process_ingress(
            "ingress-commit-1".into(),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(0),
        )
        .await
        .expect("Ingress Action should commit through Runtime authority");
    assert!(completion.is_committed());

    let status = runtime
        .ingress_status("ingress-commit-1".into())
        .await
        .expect("Ingress status should be readable");
    assert!(matches!(status.status, IngressStatus::Completed(_)));
    let session = store
        .list_sessions()
        .expect("Session provenance should be readable")
        .into_iter()
        .find(|session| {
            session
                .ingress_id()
                .is_some_and(|id| id.as_str() == "ingress-commit-1")
        })
        .expect("Ingress should have one root Session");
    assert_eq!(session.origin(), loom_runtime::ExecutionOrigin::Ingress);
    assert_eq!(session.ingress_completion(), Some(&completion));
    assert_eq!(store.snapshot(timeline()).unwrap().events.len(), 1);
}

#[tokio::test]
async fn ingress_rejection_is_completed_without_world_mutation_or_retry() {
    let store = counter_store();
    ensure_vertical_store(&store, &counter_registry());
    let runtime = Runtime::new(&store, counter_registry()).expect("Runtime should assemble");
    let request = IngressEnvelope::new(
        "ingress-rejected-1",
        "counter-key-rejected",
        IngressProvenance::new("composition-test"),
        counter_target(),
        IngressAuthorizationContext::new(json!({})),
        IngressTimeMetadata::none(),
        ActionInvocation::new(
            ActionTypeId::from(COUNTER_INCREMENT),
            json!({"amount": 0, "event_id": event(181).to_string()}),
        ),
    );

    runtime
        .submit_ingress(request)
        .await
        .expect("Ingress should be accepted");
    let completion = runtime
        .process_ingress(
            "ingress-rejected-1".into(),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(0),
        )
        .await
        .expect("semantic rejection should be terminal");
    assert!(completion.is_rejected());
    assert_eq!(
        store.snapshot(timeline()).unwrap().version(),
        TimelineVersion::default()
    );
    let record = store
        .ingress("ingress-rejected-1".into())
        .expect("Ingress record should remain durable");
    assert!(matches!(record.status, IngressStatus::Completed(_)));
    assert_eq!(record.attempt_count, 1);
}

#[tokio::test]
async fn binding_aware_catalog_and_bounded_entity_trajectory_use_public_projections() {
    let store = counter_store();
    WorldRuntimeBindingStore::persist_binding(
        &store,
        world(),
        WorldRuntimeBinding::new(
            [(
                CapabilityId::from(COUNTER_CAPABILITY),
                VersionReq::parse("^0.1.0").expect("counter requirement should parse"),
            )],
            json!({"fixture": "binding-catalog"}),
            1,
            Some("binding-catalog".to_owned()),
        ),
    )
    .await
    .expect("catalog fixture binding should persist once");
    ensure_vertical_store(&store, &counter_registry_with_secondary());
    let runtime =
        Runtime::new(&store, counter_registry_with_secondary()).expect("Runtime should assemble");
    let api: &dyn LoomApi = &runtime;

    for event_id in [event(40), event(41)] {
        let result = api
            .invoke(counter_request(
                COUNTER_INCREMENT,
                json!({"amount": 1, "event_id": event_id.to_string()}),
            ))
            .await
            .expect("counter Event should commit");
        assert!(matches!(result, ExecutionResult::Committed { .. }));
    }

    let global = api.catalog().expect("global catalog should be readable");
    assert_eq!(global.capabilities.len(), 2);
    assert_eq!(global.semantic_indexes.len(), 2);
    assert_eq!(global.facets.len(), 1);
    assert_eq!(global.events.len(), 2);
    assert_eq!(global.work_handlers.len(), 1);

    let scoped = api
        .catalog_for_world(world())
        .await
        .expect("World catalog should be readable");
    assert_eq!(scoped.capabilities.len(), 1);
    assert_eq!(scoped.capabilities[0].id.as_str(), COUNTER_CAPABILITY);
    assert_eq!(scoped.actions.len(), 2);
    assert_eq!(scoped.semantic_indexes.len(), 1);
    assert_eq!(scoped.semantic_indexes[0].id, COUNTER_INDEX);
    let disabled_query = SemanticProjectionQuery::new(
        SemanticProjectionKey::new(world(), timeline(), SECONDARY_INDEX.into()),
        SchemaRevision::new(1),
        1,
        "secondary-model-1",
        vec![0.0, 0.0],
        1,
    )
    .expect("disabled-index query should be structurally valid");
    let invalid_limit_query = SemanticProjectionQuery {
        limit: 0,
        ..disabled_query.clone()
    };
    let invalid_limit = runtime
        .query_semantic_projection(invalid_limit_query)
        .await
        .expect_err("Runtime must not trust constructor-only query bounds");
    assert!(matches!(
        invalid_limit,
        SemanticProjectionError::LimitExceeded {
            limit: 1_024,
            actual: 0
        }
    ));
    let disabled = runtime
        .query_semantic_projection(disabled_query)
        .await
        .expect_err("World Binding should disable the secondary index");
    assert!(matches!(
        disabled,
        SemanticProjectionError::MetadataMismatch { ref field, .. } if field == "world_binding"
    ));

    let first_page = api
        .entity_trajectory(EntityTrajectoryQuery {
            target: counter_target(),
            entity_id: entity(10),
            after: None,
            limit: Some(1),
        })
        .await
        .expect("Entity trajectory should be readable");
    assert_eq!(first_page.events.len(), 1);
    assert_eq!(first_page.events[0].id, event(40));
    assert_eq!(first_page.next_after, Some(1.into()));

    let second_page = api
        .entity_trajectory(EntityTrajectoryQuery::after(
            counter_target(),
            entity(10),
            first_page.next_after.expect("page should expose cursor"),
            Some(1),
        ))
        .await
        .expect("next Entity trajectory page should be readable");
    assert_eq!(second_page.events.len(), 1);
    assert_eq!(second_page.events[0].id, event(41));
    assert_eq!(second_page.next_after, None);

    let fetched = api
        .get_event(first_page.events[0].event_ref())
        .await
        .expect("EventRef lookup should be readable")
        .expect("committed Event should exist");
    assert_eq!(fetched.id, event(40));
}

#[tokio::test]
async fn causal_queries_follow_only_qualified_authoritative_event_links() {
    let store = counter_store();
    ensure_vertical_store(&store, &counter_registry());
    let runtime = Runtime::new(&store, counter_registry()).expect("Runtime should assemble");
    let api: &dyn LoomApi = &runtime;

    api.invoke(counter_request(
        COUNTER_INCREMENT,
        json!({"amount": 1, "event_id": event(50).to_string()}),
    ))
    .await
    .expect("cause Event should commit");
    api.invoke(counter_request(
        COUNTER_INCREMENT,
        json!({
            "amount": 1,
            "event_id": event(51).to_string(),
            "cause_event_id": event(50).to_string()
        }),
    ))
    .await
    .expect("effect Event should commit");

    let cause = EventRef::new(timeline(), event(50));
    let effect = EventRef::new(timeline(), event(51));
    assert_eq!(api.direct_causes(effect).await.unwrap(), vec![cause]);
    assert_eq!(api.direct_effects(cause).await.unwrap(), vec![effect]);
    let walk = api
        .causal_walk(CausalQuery::new(effect, CausalDirection::Causes, 4, 4))
        .await
        .expect("causal walk should be bounded and readable");
    assert_eq!(walk.events, vec![cause]);
    assert!(!walk.truncated);
}

#[tokio::test]
async fn vertical_slice_executes_durable_work_and_completes_atomically() {
    let store = counter_store();
    store
        .seed_work(WorkRecord {
            id: work(20),
            timeline_id: timeline(),
            target: WorkTarget::CapabilityWork {
                owner: Some(COUNTER_CAPABILITY.to_owned()),
                handler: WorkHandlerId::from(COUNTER_WORK_HANDLER),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({"amount": 4, "event_id": event(20).to_string()}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 1,
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
    ensure_vertical_store(&store, &counter_registry());
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
        .await
        .expect("Work should commit through Runtime");
    assert!(matches!(result, ExecutionResult::Committed { .. }));
    assert_eq!(
        api.get_facet(FacetQuery::new(
            counter_target(),
            FacetOwner::entity(entity(10)),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .await
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

#[tokio::test]
async fn missing_active_work_implementation_is_unavailable_before_claim() {
    let store = counter_store();
    store
        .seed_work(WorkRecord {
            id: work(22),
            timeline_id: timeline(),
            target: WorkTarget::CapabilityWork {
                owner: Some(COUNTER_CAPABILITY.to_owned()),
                handler: WorkHandlerId::from(COUNTER_WORK_HANDLER),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({"amount": 4, "event_id": event(22).to_string()}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 1,
            causal_event_id: None,
            origin_work_id: None,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at: PlatformTime::new(0),
            last_error: None,
            lease: None,
        })
        .expect("missing-implementation Work should be seeded");
    let registry = counter_registry();
    let loom_version = registry
        .capabilities()
        .next()
        .expect("counter registry should have one Capability")
        .version
        .clone();
    let missing_revision = RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("missing-counter"),
        PlatformTime::new(1),
        "missing-counter-build",
        loom_version,
        std::iter::empty(),
    )
    .expect("an empty revision descriptor should be valid publication metadata");
    ensure_vertical_store(&store, &registry);
    let runtime = Runtime::new(&store, registry).expect("Runtime should assemble");
    runtime
        .register_runtime_revision(missing_revision)
        .await
        .expect("missing revision should register as immutable history");
    store
        .activate_revision(
            RuntimeRevisionId::from("missing-counter"),
            Some(1),
            PlatformTime::new(2),
        )
        .expect("the persisted incompatible revision should be available for the negative test");

    let blocked = runtime
        .missing_implementation_block(counter_target(), work(22))
        .await
        .expect("missing implementation observation should succeed")
        .expect("due Work should expose a typed blockage");
    assert_eq!(blocked.world_id, world());
    assert_eq!(blocked.timeline_id, timeline());
    assert_eq!(blocked.work_id, work(22));
    assert_eq!(
        blocked.active_runtime_revision,
        RuntimeRevisionId::from("missing-counter")
    );
    assert_eq!(blocked.last_observed_platform_time, PlatformTime::new(0));
    assert_eq!(
        blocked.first_observed_platform_time,
        Some(PlatformTime::new(0))
    );
    assert!(matches!(
        blocked.semantic_requirement,
        WorkTarget::CapabilityWork { .. }
    ));

    let error = runtime
        .execute_work(
            counter_target(),
            work(22),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(3),
        )
        .await
        .expect_err("missing compatible software must stop before claim");
    assert_eq!(error.code, ApiErrorCode::Unavailable);
    let work = store
        .work(timeline(), work(22))
        .expect("Work lookup should succeed")
        .expect("Work should remain persisted");
    assert_eq!(work.attempt_count, 0);
    assert_eq!(work.claim_generation, 0);
    assert!(work.lease.is_none());
    assert!(
        ExecutionSessionStore::list_sessions(&store)
            .await
            .expect("Session ledger should remain readable")
            .is_empty(),
        "unavailable software must not start a Session"
    );
}

#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "the D-2 fixture covers full Binding compatibility, blockage observability and recovery"
)]
async fn missing_observer_matches_full_assembly_compatibility_predicate() {
    let store = counter_store();
    let work_id = work(24);
    store
        .seed_work(WorkRecord {
            id: work_id,
            timeline_id: timeline(),
            target: WorkTarget::CapabilityWork {
                owner: Some(COUNTER_CAPABILITY.to_owned()),
                handler: WorkHandlerId::from(COUNTER_WORK_HANDLER),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({"amount": 4, "event_id": event(24).to_string()}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 1,
            causal_event_id: None,
            origin_work_id: None,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at: PlatformTime::new(0),
            last_error: None,
            lease: None,
        })
        .expect("loom-compatibility Work should be seeded");
    let binding = WorldRuntimeBinding::new(
        [
            (
                CapabilityId::from(COUNTER_CAPABILITY),
                VersionReq::parse("^0.1.0").expect("counter Binding requirement should parse"),
            ),
            (
                CapabilityId::from(SECONDARY_CAPABILITY),
                VersionReq::parse("^0.1.0").expect("secondary Binding requirement should parse"),
            ),
        ],
        json!({"fixture": "full-compatibility"}),
        1,
        Some("full-compatibility-test".to_owned()),
    );
    WorldRuntimeBindingStore::persist_binding(&store, world(), binding)
        .await
        .expect("the A+B Binding should persist");

    let registry = counter_registry_with_secondary();
    let loom_version = registry.loom_version().clone();
    let incompatible_revision = RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("full-compatibility-mismatch"),
        PlatformTime::new(1),
        "full-compatibility-mismatch-build",
        loom_version.clone(),
        [
            RuntimeRevisionCapability::new(
                COUNTER_CAPABILITY,
                "counter-build-compatible",
                Version::new(0, 1, 0),
                VersionReq::STAR,
            ),
            RuntimeRevisionCapability::new(
                SECONDARY_CAPABILITY,
                "secondary-build-mismatch",
                Version::new(0, 1, 0),
                VersionReq::parse(">=0.1.0")
                    .expect("a valid alternate Loom compatibility requirement should parse"),
            ),
        ],
    )
    .expect("the active A+B revision metadata should be structurally valid");
    ensure_vertical_store(&store, &registry);
    let runtime = Runtime::new(&store, registry).expect("Runtime should assemble");
    runtime
        .register_runtime_revision(incompatible_revision)
        .await
        .expect("the revision should register");
    store
        .activate_revision(
            RuntimeRevisionId::from("full-compatibility-mismatch"),
            Some(1),
            PlatformTime::new(2),
        )
        .expect("the persisted incompatible revision should be available for the negative test");

    let blocked = runtime
        .missing_implementation_block(counter_target(), work_id)
        .await
        .expect("missing implementation observation should succeed")
        .expect("the mismatched Loom compatibility must produce a blockage");
    assert_eq!(blocked.world_id, world());
    assert_eq!(blocked.timeline_id, timeline());
    assert_eq!(blocked.work_id, work_id);
    assert_eq!(
        blocked.active_runtime_revision,
        RuntimeRevisionId::from("full-compatibility-mismatch")
    );
    assert_eq!(
        blocked.first_observed_platform_time,
        Some(PlatformTime::new(0))
    );
    assert_eq!(blocked.last_observed_platform_time, PlatformTime::new(0));
    assert!(matches!(
        blocked.semantic_requirement,
        WorkTarget::CapabilityWork { .. }
    ));

    let error = runtime
        .execute_work(
            counter_target(),
            work_id,
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(3),
        )
        .await
        .expect_err("assembly-incompatible software must stop before claim");
    assert_eq!(error.code, ApiErrorCode::Unavailable);
    let work = store
        .work(timeline(), work_id)
        .expect("Work lookup should succeed")
        .expect("Work should remain persisted");
    assert_eq!(work.attempt_count, 0);
    assert_eq!(work.claim_generation, 0);
    assert!(work.lease.is_none());
    assert!(
        ExecutionSessionStore::list_sessions(&store)
            .await
            .expect("Session ledger should remain readable")
            .is_empty(),
        "assembly-incompatible software must not start a Session"
    );

    let compatible_revision = RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("full-compatibility-match"),
        PlatformTime::new(3),
        "full-compatibility-match-build",
        loom_version,
        [
            RuntimeRevisionCapability::new(
                COUNTER_CAPABILITY,
                "counter-build-compatible",
                Version::new(0, 1, 0),
                VersionReq::STAR,
            ),
            RuntimeRevisionCapability::new(
                SECONDARY_CAPABILITY,
                "secondary-build-compatible",
                Version::new(0, 1, 0),
                VersionReq::STAR,
            ),
        ],
    )
    .expect("the fully compatible A+B revision should be valid");
    runtime
        .register_runtime_revision(compatible_revision)
        .await
        .expect("the compatible revision should register");
    runtime
        .activate_runtime_revision(
            RuntimeRevisionId::from("full-compatibility-match"),
            Some(2),
            PlatformTime::new(4),
        )
        .await
        .expect("the compatible revision should activate");
    assert!(
        runtime
            .missing_implementation_block(counter_target(), work_id)
            .await
            .expect("compatible implementation observation should succeed")
            .is_none()
    );
    assert!(
        runtime
            .execute_work(
                counter_target(),
                work_id,
                PlatformTime::new(0),
                PlatformTime::new(10),
                PlatformTime::new(3),
            )
            .await
            .expect("the fully compatible A+B assembly should execute the Work")
            .is_committed()
    );
}

#[tokio::test]
async fn work_schema_revision_mismatch_blocks_before_claim() {
    let store = counter_store();
    let work_id = work(25);
    store
        .seed_work(WorkRecord {
            id: work_id,
            timeline_id: timeline(),
            target: WorkTarget::CapabilityWork {
                owner: Some(COUNTER_CAPABILITY.to_owned()),
                handler: WorkHandlerId::from(COUNTER_WORK_HANDLER),
            },
            schema_revision: SchemaRevision::new(2),
            payload: json!({"amount": 4, "event_id": event(25).to_string()}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 1,
            causal_event_id: None,
            origin_work_id: None,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at: PlatformTime::new(0),
            last_error: None,
            lease: None,
        })
        .expect("schema-mismatch Work should be seeded");
    ensure_vertical_store(&store, &counter_registry());
    let runtime = Runtime::new(&store, counter_registry()).expect("Runtime should assemble");

    let blocked = runtime
        .missing_implementation_block(counter_target(), work_id)
        .await
        .expect("schema compatibility observation should succeed")
        .expect("a handler schema mismatch must produce a typed blockage");
    assert_eq!(blocked.work_id, work_id);
    assert!(matches!(
        blocked.semantic_requirement,
        WorkTarget::CapabilityWork { .. }
    ));

    let error = runtime
        .execute_work(
            counter_target(),
            work_id,
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(3),
        )
        .await
        .expect_err("schema-incompatible Work must stop before claim");
    assert_eq!(error.code, ApiErrorCode::Unavailable);
    let work = store
        .work(timeline(), work_id)
        .expect("Work lookup should succeed")
        .expect("Work should remain persisted");
    assert_eq!(work.attempt_count, 0);
    assert_eq!(work.claim_generation, 0);
    assert!(work.lease.is_none());
    assert!(
        ExecutionSessionStore::list_sessions(&store)
            .await
            .expect("Session ledger should remain readable")
            .is_empty(),
        "schema-incompatible Work must not start a Session"
    );
}

#[tokio::test]
async fn vertical_slice_technical_retry_leaves_world_truth_unchanged() {
    let retry_store = counter_store();
    retry_store
        .seed_work(WorkRecord {
            id: work(21),
            timeline_id: timeline(),
            target: WorkTarget::CapabilityWork {
                owner: Some(COUNTER_CAPABILITY.to_owned()),
                handler: WorkHandlerId::from(COUNTER_WORK_HANDLER),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({"event_id": event(21).to_string()}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 1,
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
    ensure_vertical_store(&retry_store, &counter_registry());
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
        .await
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

#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "the bounded retry scenario asserts each terminalization invariant"
)]
async fn bounded_failure_policy_terminalizes_after_configured_attempts() {
    let store = counter_store();
    let work_id = work(23);
    store
        .seed_work(WorkRecord {
            id: work_id,
            timeline_id: timeline(),
            target: WorkTarget::CapabilityWork {
                owner: Some(COUNTER_CAPABILITY.to_owned()),
                handler: WorkHandlerId::from(COUNTER_WORK_HANDLER),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({"event_id": event(23).to_string()}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 1,
            causal_event_id: None,
            origin_work_id: None,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at: PlatformTime::new(0),
            last_error: None,
            lease: None,
        })
        .expect("bounded-failure Work should be seeded");
    let before = store
        .work(timeline(), work_id)
        .expect("Work lookup should succeed")
        .expect("Work should exist");
    ensure_vertical_store(&store, &counter_registry());
    let runtime = Runtime::new(&store, counter_registry())
        .expect("Runtime should assemble")
        .with_failure_policy(FailurePolicy::new(2, 5).expect("test FailurePolicy should be valid"));

    runtime
        .execute_work(
            counter_target(),
            work_id,
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(1),
        )
        .await
        .expect_err("first technical failure should return the handler error");
    let retried = store
        .work(timeline(), work_id)
        .expect("retried Work lookup should succeed")
        .expect("retried Work should exist");
    assert_eq!(retried.status, WorkStatus::Pending);
    assert_eq!(retried.attempt_count, 1);
    assert_eq!(retried.available_at, PlatformTime::new(5));
    assert_eq!(
        retried.effective_due_world_time,
        before.effective_due_world_time
    );
    assert_eq!(
        retried.logical_schedule_order,
        before.logical_schedule_order
    );
    assert_eq!(
        store
            .snapshot(timeline())
            .expect("snapshot should exist")
            .journal
            .len(),
        0
    );

    runtime
        .execute_work(
            counter_target(),
            work_id,
            PlatformTime::new(5),
            PlatformTime::new(15),
            PlatformTime::new(6),
        )
        .await
        .expect_err("attempt exhaustion should still return the technical failure");
    let after = store
        .snapshot(timeline())
        .expect("terminalized Timeline should remain readable");
    let terminal = after
        .works
        .iter()
        .find(|work| work.id == work_id)
        .expect("terminalized Work should remain inspectable");
    assert_eq!(terminal.status, WorkStatus::Dead);
    assert_eq!(terminal.attempt_count, 2);
    assert_eq!(
        terminal.effective_due_world_time,
        before.effective_due_world_time
    );
    assert_eq!(
        terminal.logical_schedule_order,
        before.logical_schedule_order
    );
    assert!(terminal.lease.is_none());
    assert!(after.events.is_empty());
    assert_eq!(after.world_time(), WorldInstant::new(0));
    assert_eq!(after.version().state_revision.value(), 1);
    assert_eq!(after.journal.len(), 1);
    assert!(matches!(
        after.journal[0].work_transitions.as_slice(),
        [LogicalWorkTransition::Dead { work_id: dead_id }] if *dead_id == work_id
    ));
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "ME-212 combines the already-delivered read, projection, blob and pinned-read contracts"
)]
async fn m7_t6_combination_gate_is_bounded_restart_safe_and_authority_neutral() {
    let store = counter_store();
    let second_world = id::<WorldId>(100);
    let second_timeline = id::<TimelineId>(101);
    store
        .create_timeline(second_world, second_timeline)
        .expect("second World Binding scope should be created");
    store
        .seed_entity(
            timeline(),
            loom_core::Entity {
                id: entity(11),
                world_id: world(),
            },
        )
        .expect("relationship participant Entity should be seeded");
    let relationship_id = id::<RelationshipId>(400);
    store
        .seed_relationship(
            timeline(),
            Relationship::new(
                relationship_id,
                world(),
                RelationshipTypeId::from("test.relationship"),
                vec![
                    RelationshipParticipant::new(entity(10), "left"),
                    RelationshipParticipant::new(entity(11), "right"),
                ],
            ),
            true,
        )
        .expect("relationship fixture should be seeded");

    WorldRuntimeBindingStore::persist_binding(
        &store,
        world(),
        WorldRuntimeBinding::new(
            [(
                CapabilityId::from(COUNTER_CAPABILITY),
                VersionReq::parse("^0.1.0").expect("counter binding requirement should parse"),
            )],
            json!({"fixture": "me-212-counter"}),
            1,
            Some("me-212-counter".to_owned()),
        ),
    )
    .await
    .expect("counter-only World Binding should persist");
    WorldRuntimeBindingStore::persist_binding(
        &store,
        second_world,
        WorldRuntimeBinding::new(
            [(
                CapabilityId::from(SECONDARY_CAPABILITY),
                VersionReq::parse("^0.1.0").expect("secondary binding requirement should parse"),
            )],
            json!({"fixture": "me-212-secondary"}),
            1,
            Some("me-212-secondary".to_owned()),
        ),
    )
    .await
    .expect("secondary-only World Binding should persist");

    ensure_vertical_store(&store, &counter_registry_with_secondary());
    let runtime = Runtime::new(&store, counter_registry_with_secondary())
        .expect("ME-212 Runtime should assemble");
    let api: &dyn LoomApi = &runtime;

    let global = api.catalog().expect("global catalog should be readable");
    assert_eq!(global.capabilities.len(), 2);
    assert_eq!(global.semantic_indexes.len(), 2);
    let counter_catalog = api
        .catalog_for_world(world())
        .await
        .expect("counter World catalog should be readable");
    assert_eq!(
        counter_catalog
            .capabilities
            .iter()
            .map(|capability| capability.id.as_str())
            .collect::<Vec<_>>(),
        vec![COUNTER_CAPABILITY]
    );
    assert_eq!(counter_catalog.semantic_indexes.len(), 1);
    assert_eq!(counter_catalog.semantic_indexes[0].id, COUNTER_INDEX);
    let secondary_catalog = api
        .catalog_for_world(second_world)
        .await
        .expect("secondary World catalog should be readable");
    assert_eq!(
        secondary_catalog
            .capabilities
            .iter()
            .map(|capability| capability.id.as_str())
            .collect::<Vec<_>>(),
        vec![SECONDARY_CAPABILITY]
    );
    assert_eq!(secondary_catalog.semantic_indexes.len(), 1);
    assert_eq!(secondary_catalog.semantic_indexes[0].id, SECONDARY_INDEX);

    assert!(
        api.invoke(counter_request(
            COUNTER_INCREMENT,
            json!({"amount": 1, "event_id": event(210).to_string()}),
        ))
        .await
        .expect("root Event should commit")
        .is_committed()
    );

    let child_timeline = id::<TimelineId>(500);
    let root_version = store
        .snapshot(timeline())
        .expect("root version should be readable")
        .version();
    let child = TimelineForkStore::fork_timeline(
        &store,
        &TimelineFork::new(timeline(), root_version, child_timeline),
    )
    .await
    .expect("child Timeline should fork at the current committed root version");
    assert_eq!(child.ancestry().parent_timeline_id, Some(timeline()));
    let child_target = TimelineTarget::new(world(), child_timeline);

    let relationship_event = ProposedEvent::new(
        event(213),
        EventTypeId::from(COUNTER_INCREMENTED),
        SchemaRevision::new(1),
        json!({"previous": 1, "amount": 0, "value": 1}),
    )
    .with_participant(loom_protocol::EventParticipant::new(entity(10), "subject"));
    let mut relationship_event = relationship_event;
    relationship_event
        .relationship_refs
        .push(EventRelationshipRef::new(relationship_id, "subject"));
    let relationship_registry = counter_registry();
    let relationship_resolution = EffectEngine::new(&relationship_registry)
        .validate(
            &store
                .snapshot(timeline())
                .expect("relationship base snapshot should be readable")
                .world_view(),
            COUNTER_CAPABILITY,
            Resolution::new(vec![relationship_event], Vec::new()),
        )
        .expect("relationship Event should pass Runtime validation");
    store
        .commit(&relationship_resolution, None, PlatformTime::new(1))
        .expect("relationship Event should commit through the authority adapter");

    assert!(
        api.invoke(counter_request(
            COUNTER_INCREMENT,
            json!({"amount": 1, "event_id": event(211).to_string()}),
        ))
        .await
        .expect("parent future Event should commit")
        .is_committed()
    );
    assert!(
        api.invoke_on(
            world(),
            child_timeline,
            ActionInvocation::new(
                ActionTypeId::from(COUNTER_INCREMENT),
                json!({
                    "amount": 1,
                    "event_id": event(212).to_string(),
                    "cause_event_id": event(210).to_string()
                }),
            ),
        )
        .await
        .expect("child branch Event should commit")
        .is_committed()
    );

    let child_trajectory = api
        .entity_trajectory(EntityTrajectoryQuery::all(child_target, entity(10)))
        .await
        .expect("child Entity trajectory should be readable");
    assert_eq!(
        child_trajectory
            .events
            .iter()
            .map(|event| event.id)
            .collect::<Vec<_>>(),
        vec![event(210), event(212)]
    );
    assert!(
        !child_trajectory
            .events
            .iter()
            .any(|committed_event| committed_event.id == event(211))
    );
    let relationship_trajectory = api
        .relationship_trajectory(RelationshipTrajectoryQuery::all(
            counter_target(),
            relationship_id,
        ))
        .await
        .expect("Relationship trajectory should be readable");
    assert_eq!(
        relationship_trajectory
            .events
            .iter()
            .map(|event| event.id)
            .collect::<Vec<_>>(),
        vec![event(213)]
    );
    let child_event_ref = EventRef::new(child_timeline, event(212));
    assert_eq!(
        api.direct_causes(child_event_ref)
            .await
            .expect("child causal source should be readable"),
        vec![EventRef::new(timeline(), event(210))]
    );
    let causal_walk = api
        .causal_walk(CausalQuery::new(
            child_event_ref,
            CausalDirection::Causes,
            1,
            1,
        ))
        .await
        .expect("bounded child causal walk should be readable");
    assert_eq!(
        causal_walk.events,
        vec![EventRef::new(timeline(), event(210))]
    );
    assert!(!causal_walk.truncated);

    let authority_before_projection = store
        .snapshot(timeline())
        .expect("authority snapshot should be readable before projection changes");
    let projection_key = SemanticProjectionKey::new(world(), timeline(), COUNTER_INDEX.into());
    let registration_v1 = SemanticProjectionRegistration::new(
        projection_key.clone(),
        SemanticIndexSource::new("facet", COUNTER_FACET, SchemaRevision::new(1)),
        SchemaRevision::new(1),
        1,
        "counter-model-1",
        2,
        SemanticIndexMetric::Cosine,
    )
    .expect("projection revision one should be valid");
    runtime
        .register_semantic_projection(registration_v1.clone())
        .await
        .expect("projection revision one should register");
    let child_version = store
        .snapshot(child_timeline)
        .expect("child version should be readable")
        .version();
    let rows_v1 = vec![
        SemanticProjectionRow::new(
            EventRef::new(timeline(), event(210)),
            "root-source",
            authority_before_projection.version(),
            1,
            "counter-model-1",
            vec![1.0, 0.0],
        )
        .expect("root projection row should be valid"),
        SemanticProjectionRow::new(
            child_event_ref,
            "child-source",
            child_version,
            1,
            "counter-model-1",
            vec![0.0, 1.0],
        )
        .expect("child projection row should be valid"),
    ];
    runtime
        .rebuild_semantic_projection(
            &SemanticProjectionRebuild::new(registration_v1.clone(), Some(1), rows_v1)
                .expect("projection revision one rebuild should be valid"),
        )
        .await
        .expect("projection revision one should rebuild");
    let projection_query = SemanticProjectionQuery::new(
        projection_key.clone(),
        SchemaRevision::new(1),
        1,
        "counter-model-1",
        vec![1.0, 0.0],
        2,
    )
    .expect("projection query should be bounded");
    let hits = runtime
        .query_semantic_projection(projection_query.clone())
        .await
        .expect("projection query should be served through Runtime");
    assert_eq!(hits.len(), 2);
    assert_eq!(hits[0].source_ref, EventRef::new(timeline(), event(210)));

    ensure_vertical_store(&store, &counter_registry_with_secondary());
    let restarted_runtime = Runtime::new(&store, counter_registry_with_secondary())
        .expect("Runtime should restart over the same authority adapter");
    assert_eq!(
        restarted_runtime
            .query_semantic_projection(projection_query)
            .await
            .expect("projection should survive Runtime restart")
            .len(),
        2
    );
    restarted_runtime
        .delete_semantic_projection(projection_key.clone())
        .await
        .expect("projection delete should only remove its materialization");
    assert!(matches!(
        restarted_runtime
            .query_semantic_projection(
                SemanticProjectionQuery::new(
                    projection_key.clone(),
                    SchemaRevision::new(1),
                    1,
                    "counter-model-1",
                    vec![1.0, 0.0],
                    1,
                )
                .expect("deleted projection query should remain structurally valid"),
            )
            .await,
        Err(SemanticProjectionError::IndexNotRegistered { .. })
    ));

    ensure_vertical_store(&store, &projection_v2_registry());
    let v2_runtime = Runtime::new(&store, projection_v2_registry())
        .expect("model revision two Runtime should assemble");
    let registration_v2 = SemanticProjectionRegistration::new(
        projection_key.clone(),
        SemanticIndexSource::new("facet", COUNTER_FACET, SchemaRevision::new(1)),
        SchemaRevision::new(1),
        2,
        "counter-model-2",
        2,
        SemanticIndexMetric::Cosine,
    )
    .expect("projection revision two should be valid");
    v2_runtime
        .register_semantic_projection(registration_v2.clone())
        .await
        .expect("model change should register as a new projection revision");
    let rows_v2 = vec![
        SemanticProjectionRow::new(
            EventRef::new(timeline(), event(210)),
            "root-source-v2",
            authority_before_projection.version(),
            2,
            "counter-model-2",
            vec![1.0, 0.0],
        )
        .expect("model revision two row should be valid"),
    ];
    v2_runtime
        .rebuild_semantic_projection(
            &SemanticProjectionRebuild::new(registration_v2, Some(2), rows_v2)
                .expect("model revision two rebuild should be valid"),
        )
        .await
        .expect("model revision two should rebuild");
    let v2_hits = v2_runtime
        .query_semantic_projection(
            SemanticProjectionQuery::new(
                projection_key,
                SchemaRevision::new(1),
                2,
                "counter-model-2",
                vec![1.0, 0.0],
                1,
            )
            .expect("model revision two query should be valid"),
        )
        .await
        .expect("model revision two query should succeed");
    assert_eq!(v2_hits.len(), 1);
    let authority_after_projection = store
        .snapshot(timeline())
        .expect("authority snapshot should remain readable after projection changes");
    assert_eq!(
        authority_before_projection.version(),
        authority_after_projection.version()
    );
    assert_eq!(
        authority_before_projection.events,
        authority_after_projection.events
    );
    assert_eq!(
        authority_before_projection.base,
        authority_after_projection.base
    );

    let blob_store = InMemoryBlobStore::new();
    let blob_reference = blob_store
        .put(b"ME-212 immutable blob", Some("text/plain"))
        .await
        .expect("blob put should succeed");
    assert_eq!(
        blob_store
            .put(b"ME-212 immutable blob", Some("text/plain"))
            .await
            .expect("duplicate blob put should be idempotent"),
        blob_reference
    );
    assert!(matches!(
        blob_store
            .put(b"ME-212 immutable blob", Some("application/octet-stream"))
            .await,
        Err(BlobError::MetadataMismatch { .. })
    ));
    assert_eq!(
        blob_store
            .read(&blob_reference)
            .await
            .expect("blob read should verify immutable metadata")
            .bytes(),
        b"ME-212 immutable blob"
    );
    blob_store
        .corrupt(&blob_reference, b"tampered".to_vec())
        .expect("test adapter should permit deterministic corruption simulation");
    assert!(matches!(
        blob_store.read(&blob_reference).await,
        Err(BlobError::SizeMismatch { .. } | BlobError::HashMismatch { .. })
    ));
    blob_store
        .delete(&blob_reference)
        .expect("blob delete should remove only the adapter object");
    assert!(matches!(
        blob_store.read(&blob_reference).await,
        Err(BlobError::NotFound { .. })
    ));

    let local_root = std::env::temp_dir().join(format!("loom-me212-gate-{}", std::process::id()));
    let _ = fs::remove_dir_all(&local_root);
    fs::create_dir_all(&local_root).expect("local blob fixture directory should be created");
    let local_reference = {
        let local_store = LocalBlobStore::new(&local_root).expect("local BlobStore should open");
        local_store
            .put(b"reopen me", None)
            .await
            .expect("local blob put should succeed")
    };
    let reopened_local_store =
        LocalBlobStore::new(&local_root).expect("local BlobStore should reopen");
    assert_eq!(
        reopened_local_store
            .read(&local_reference)
            .await
            .expect("reopened local blob should read")
            .bytes(),
        b"reopen me"
    );
    reopened_local_store
        .delete(&local_reference)
        .await
        .expect("reopened local blob should delete its object");
    fs::remove_dir_all(&local_root).expect("local blob fixture directory should be cleaned");
    let authority_after_blob = store
        .snapshot(timeline())
        .expect("authority snapshot should remain readable after blob failures");
    assert_eq!(
        authority_after_projection.version(),
        authority_after_blob.version()
    );
    assert_eq!(
        authority_after_projection.events,
        authority_after_blob.events
    );

    let pinned_session = PinnedReadSession::new(
        id(900),
        world(),
        timeline(),
        authority_before_projection.version(),
        authority_before_projection.world_time(),
    );
    let mut pinned_boundary = PinnedReadBoundary::new(&store, PinnedReadPolicy::new(1, 2));
    pinned_boundary
        .entity(&pinned_session, entity(10))
        .await
        .expect("pinned Entity read should succeed")
        .value()
        .as_ref()
        .expect("pinned Entity should exist");
    pinned_boundary
        .entity(&pinned_session, entity(10))
        .await
        .expect("exact-version cache read should succeed");
    assert_eq!(pinned_boundary.metrics().cache_hits(), 1);

    let race_session = PinnedReadSession::new(
        id(901),
        world(),
        timeline(),
        authority_before_projection.version(),
        authority_before_projection.world_time(),
    );
    ensure_vertical_store(&store, &counter_registry());
    let race_runtime =
        Runtime::new(&store, counter_registry()).expect("race Runtime should assemble");
    let (commit_result, raced_read) = tokio::join!(
        race_runtime.invoke(counter_request(
            COUNTER_INCREMENT,
            json!({"amount": 1, "event_id": event(220).to_string()}),
        )),
        PinnedWorldReadStore::read_entity(&store, &race_session, entity(10)),
    );
    assert!(
        commit_result
            .expect("concurrent authority commit should complete")
            .is_committed()
    );
    match raced_read {
        Ok(read) => assert!(read.value().is_some()),
        Err(ReadError::PinnedVersionMismatch { .. }) => {}
        Err(error) => panic!("pinned race returned an unrelated error: {error:?}"),
    }
    let mut stale_boundary = PinnedReadBoundary::new(&store, PinnedReadPolicy::new(1, 0));
    let stale = stale_boundary
        .entity(&pinned_session, entity(10))
        .await
        .expect_err("fresh boundary must fence the old pinned version");
    assert!(matches!(stale, ReadError::PinnedVersionMismatch { .. }));
    assert!(stale_boundary.policy().should_restart(0, &stale));
    let latest = store
        .snapshot(timeline())
        .expect("latest pinned version should be readable");
    let latest_session = PinnedReadSession::new(
        id(902),
        world(),
        timeline(),
        latest.version(),
        latest.world_time(),
    );
    let mut benchmark_boundary = PinnedReadBoundary::new(&store, PinnedReadPolicy::new(1, 2));
    let started = Instant::now();
    let benchmark_read = benchmark_boundary
        .entity(&latest_session, entity(10))
        .await
        .expect("latest pinned Entity read should succeed");
    let latency_us = started.elapsed().as_micros();
    println!(
        "ME-212 benchmark adapter=InMemory backend=local world_size=2 rows={} bytes={} latency_us={} cache_capacity={} max_restarts={}",
        benchmark_read.metrics().rows_read(),
        benchmark_read.metrics().bytes_read(),
        latency_us,
        benchmark_boundary.policy().cache_capacity(),
        benchmark_boundary.policy().max_restarts(),
    );
    assert_eq!(benchmark_read.metrics().rows_read(), 1);
    assert!(benchmark_read.value().is_some());
}
