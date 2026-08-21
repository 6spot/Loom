use std::sync::{
    Arc, Mutex,
    atomic::{AtomicUsize, Ordering},
};

use loom_api::{ActionRequest, ApiErrorCode, ExecutionResult, LoomApi, TimelineTarget};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityDependency, CapabilityManifest,
    CapabilityRegistrar, CapabilityRegistry, EventDefinition, FacetDefinition, RegistrationError,
    ResolutionContext, ResolverError,
};
use loom_core::{
    ActionTypeId, Entity, EntityId, EventId, EventTypeId, FacetOwner, FacetTypeId, SchemaRevision,
    TimelineId, WorldEffect, WorldId,
};
use loom_protocol::{
    ActionInvocation, CausalLink, ProposedEvent, Rejection, Resolution, ResolveOutcome,
};
use loom_runtime::{
    CallProvenance, CommitError, CommitResult, CommitStore, PersistenceFuture, PlatformTime,
    ReadError, ResolutionBudget, Runtime, TimelineSnapshot, ValidatedResolution, WorkClaim,
    WorkError, WorkRecord, WorkStore, WorldStore,
};
use loom_storage::InMemoryStore;
use serde_json::{Value, json};

const ROOT_CAPABILITY: &str = "composition.root";
const CHILD_CAPABILITY: &str = "composition.child";
const LEAF_CAPABILITY: &str = "composition.leaf";
const ROOT_ACTION: &str = "composition.root_action";
const CHILD_ACTION: &str = "composition.child_action";
const LEAF_ACTION: &str = "composition.leaf_action";
const ROOT_EVENT: &str = "composition.root_event";
const CHILD_EVENT: &str = "composition.child_event";
const LEAF_EVENT: &str = "composition.leaf_event";
const ROOT_FACET: &str = "composition.root_state";
const CHILD_FACET: &str = "composition.child_state";
const LEAF_FACET: &str = "composition.leaf_state";

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

fn entity() -> EntityId {
    id(10)
}

fn event(value: u128) -> EventId {
    id(value)
}

fn target() -> TimelineTarget {
    TimelineTarget::new(world(), timeline())
}

fn integer_schema() -> Value {
    json!({
        "type": "object",
        "required": ["value"],
        "properties": {"value": {"type": "integer"}}
    })
}

fn root_input_schema() -> Value {
    json!({
        "type": "object",
        "required": ["child_event_id", "root_event_id"],
        "properties": {
            "child_event_id": {"type": "string"},
            "root_event_id": {"type": "string"},
            "reject_child": {"type": "boolean"},
            "invalid_child_input": {"type": "boolean"},
            "invalid_child": {"type": "boolean"},
            "cycle": {"type": "boolean"},
            "depth": {"type": "boolean"}
        }
    })
}

fn child_input_schema() -> Value {
    json!({
        "type": "object",
        "required": ["event_id"],
        "properties": {
            "event_id": {"type": "string"},
            "reject": {"type": "boolean"},
            "invalid": {"type": "boolean"},
            "cycle": {"type": "boolean"},
            "depth": {"type": "boolean"}
        }
    })
}

fn leaf_input_schema() -> Value {
    json!({
        "type": "object",
        "required": ["event_id"],
        "properties": {"event_id": {"type": "string"}}
    })
}

#[derive(Clone, Copy)]
enum CapabilityKind {
    Root,
    Child,
    Leaf,
}

struct CompositionCapability {
    manifest: CapabilityManifest,
    kind: CapabilityKind,
}

impl Capability for CompositionCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        match self.kind {
            CapabilityKind::Root => {
                registrar.register_facet(FacetDefinition::new(
                    FacetTypeId::from(ROOT_FACET),
                    SchemaRevision::new(1),
                    integer_schema(),
                ))?;
                registrar.register_event(
                    EventDefinition::new(EventTypeId::from(ROOT_EVENT), SchemaRevision::new(1))
                        .with_payload_schema(integer_schema()),
                )?;
                registrar.register_action(
                    ActionDefinition::new(ActionTypeId::from(ROOT_ACTION), SchemaRevision::new(1))
                        .with_input_schema(root_input_schema()),
                    RootResolver,
                )?;
            }
            CapabilityKind::Child => {
                registrar.register_facet(FacetDefinition::new(
                    FacetTypeId::from(CHILD_FACET),
                    SchemaRevision::new(1),
                    integer_schema(),
                ))?;
                registrar.register_event(
                    EventDefinition::new(EventTypeId::from(CHILD_EVENT), SchemaRevision::new(1))
                        .with_payload_schema(integer_schema()),
                )?;
                registrar.register_action(
                    ActionDefinition::new(ActionTypeId::from(CHILD_ACTION), SchemaRevision::new(1))
                        .with_input_schema(child_input_schema()),
                    ChildResolver,
                )?;
            }
            CapabilityKind::Leaf => {
                registrar.register_facet(FacetDefinition::new(
                    FacetTypeId::from(LEAF_FACET),
                    SchemaRevision::new(1),
                    integer_schema(),
                ))?;
                registrar.register_event(
                    EventDefinition::new(EventTypeId::from(LEAF_EVENT), SchemaRevision::new(1))
                        .with_payload_schema(integer_schema()),
                )?;
                registrar.register_action(
                    ActionDefinition::new(ActionTypeId::from(LEAF_ACTION), SchemaRevision::new(1))
                        .with_input_schema(leaf_input_schema()),
                    LeafResolver,
                )?;
            }
        }
        Ok(())
    }
}

struct RootResolver;

impl ActionResolver for RootResolver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let child_event_id = parse_event_id(input, "child_event_id")?;
        let root_event_id = parse_event_id(input, "root_event_id")?;
        let child_input = if input
            .get("invalid_child_input")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            json!({"event_id": 17})
        } else {
            json!({
                "event_id": child_event_id.to_string(),
                "reject": input.get("reject_child").and_then(Value::as_bool).unwrap_or(false),
                "invalid": input.get("invalid_child").and_then(Value::as_bool).unwrap_or(false),
                "cycle": input.get("cycle").and_then(Value::as_bool).unwrap_or(false),
                "depth": input.get("depth").and_then(Value::as_bool).unwrap_or(false),
            })
        };
        match context.subresolve(&ActionInvocation::new(
            ActionTypeId::from(CHILD_ACTION),
            child_input,
        ))? {
            ResolveOutcome::Rejected(rejection) => Ok(ResolveOutcome::Rejected(rejection)),
            ResolveOutcome::Resolved(_) => {
                let root_event = ProposedEvent::new(
                    root_event_id,
                    EventTypeId::from(ROOT_EVENT),
                    SchemaRevision::new(1),
                    context.world_time(),
                    json!({"value": 2}),
                )
                .with_causal_link(CausalLink::new(child_event_id))
                .with_effect(WorldEffect::PutFacet {
                    owner: FacetOwner::entity(entity()),
                    facet_type: FacetTypeId::from(ROOT_FACET),
                    schema_revision: SchemaRevision::new(1),
                    value: json!({"value": 2}),
                });
                Ok(ResolveOutcome::Resolved(Resolution::new(
                    vec![root_event],
                    Vec::new(),
                )))
            }
        }
    }
}

struct ChildResolver;

impl ActionResolver for ChildResolver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_event_id(input, "event_id")?;
        if input
            .get("reject")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            return Ok(ResolveOutcome::Rejected(Rejection::new(
                "composition.child_rejected",
                "child Capability rejected the requested composition",
            )));
        }
        if input.get("cycle").and_then(Value::as_bool).unwrap_or(false) {
            let _ = context.subresolve(&ActionInvocation::new(
                ActionTypeId::from(CHILD_ACTION),
                json!({
                    "event_id": event(102).to_string(),
                    "cycle": true,
                }),
            ))?;
        }
        if input.get("depth").and_then(Value::as_bool).unwrap_or(false) {
            let _ = context.subresolve(&ActionInvocation::new(
                ActionTypeId::from(LEAF_ACTION),
                json!({"event_id": event(104).to_string()}),
            ))?;
        }
        let value = if input
            .get("invalid")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            json!("invalid")
        } else {
            json!(1)
        };
        let child_event = ProposedEvent::new(
            event_id,
            EventTypeId::from(CHILD_EVENT),
            SchemaRevision::new(1),
            context.world_time(),
            json!({"value": value}),
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity()),
            facet_type: FacetTypeId::from(CHILD_FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": 1}),
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![child_event],
            Vec::new(),
        )))
    }
}

struct LeafResolver;

impl ActionResolver for LeafResolver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_event_id(input, "event_id")?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(LEAF_EVENT),
            SchemaRevision::new(1),
            context.world_time(),
            json!({"value": 3}),
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity()),
            facet_type: FacetTypeId::from(LEAF_FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": 3}),
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

fn parse_event_id(input: &Value, field: &str) -> Result<EventId, ResolverError> {
    input
        .get(field)
        .and_then(Value::as_str)
        .ok_or_else(|| ResolverError::new(format!("{field} must be a UUID string")))?
        .parse()
        .map_err(|_| ResolverError::new(format!("{field} must be a UUID string")))
}

fn registry(root_depends_on_child: bool) -> CapabilityRegistry {
    let mut root =
        CapabilityManifest::parse(ROOT_CAPABILITY, "0.1.0").expect("root manifest should parse");
    if root_depends_on_child {
        root = root.requires(
            CapabilityDependency::parse(CHILD_CAPABILITY, "^0.1.0")
                .expect("child dependency should parse"),
        );
    }
    let child = CapabilityManifest::parse(CHILD_CAPABILITY, "0.1.0")
        .expect("child manifest should parse")
        .requires(
            CapabilityDependency::parse(LEAF_CAPABILITY, "^0.1.0")
                .expect("leaf dependency should parse"),
        );
    CapabilityRegistry::assemble([
        CompositionCapability {
            manifest: root,
            kind: CapabilityKind::Root,
        },
        CompositionCapability {
            manifest: child,
            kind: CapabilityKind::Child,
        },
        CompositionCapability {
            manifest: CapabilityManifest::parse(LEAF_CAPABILITY, "0.1.0")
                .expect("leaf manifest should parse"),
            kind: CapabilityKind::Leaf,
        },
    ])
    .expect("composition registry should assemble")
}

struct CountingStore {
    inner: InMemoryStore,
    commits: Arc<AtomicUsize>,
    provenance: Arc<Mutex<Option<CallProvenance>>>,
}

impl CountingStore {
    fn new() -> Self {
        let inner = InMemoryStore::new();
        inner
            .create_timeline(world(), timeline())
            .expect("composition Timeline should be created");
        inner
            .seed_entity(
                timeline(),
                Entity {
                    id: entity(),
                    world_id: world(),
                },
            )
            .expect("composition Entity should be seeded");
        for facet in [ROOT_FACET, CHILD_FACET, LEAF_FACET] {
            inner
                .seed_facet(
                    timeline(),
                    FacetOwner::entity(entity()),
                    FacetTypeId::from(facet),
                    SchemaRevision::new(1),
                    json!({"value": 0}),
                )
                .expect("composition Facet should be seeded");
        }
        Self {
            inner,
            commits: Arc::new(AtomicUsize::new(0)),
            provenance: Arc::new(Mutex::new(None)),
        }
    }

    fn commit_count(&self) -> usize {
        self.commits.load(Ordering::SeqCst)
    }

    fn call_provenance(&self) -> CallProvenance {
        self.provenance
            .lock()
            .expect("provenance mutex should not be poisoned")
            .clone()
            .expect("successful composition should expose provenance")
    }
}

impl loom_runtime::WorldLifecycleStore for CountingStore {
    fn create_world(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        initial_world_time: loom_core::WorldInstant,
    ) -> PersistenceFuture<'_, Result<loom_runtime::WorldCreation, loom_runtime::LifecycleError>>
    {
        loom_runtime::WorldLifecycleStore::create_world(
            &self.inner,
            world_id,
            timeline_id,
            initial_world_time,
        )
    }
}

impl WorldStore for CountingStore {
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        Box::pin(async move { self.inner.snapshot(timeline_id) })
    }
}

impl CommitStore for CountingStore {
    fn commit<'a>(
        &'a self,
        resolution: &'a ValidatedResolution,
        current_work: Option<&'a WorkClaim>,
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<CommitResult, CommitError>> {
        self.commits.fetch_add(1, Ordering::SeqCst);
        *self
            .provenance
            .lock()
            .expect("provenance mutex should not be poisoned") =
            Some(resolution.call_provenance().clone());
        Box::pin(async move { self.inner.commit(resolution, current_work, now) })
    }
}

impl WorkStore for CountingStore {
    fn claim(
        &self,
        timeline_id: TimelineId,
        work_id: loom_core::WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'_, Result<WorkClaim, WorkError>> {
        WorkStore::claim(&self.inner, timeline_id, work_id, now, claimed_until)
    }

    fn retry<'a>(
        &'a self,
        claim: &'a WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> PersistenceFuture<'a, Result<WorkRecord, WorkError>> {
        WorkStore::retry(&self.inner, claim, now, available_at, last_error)
    }

    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: loom_core::WorkId,
    ) -> PersistenceFuture<'_, Result<Option<WorkRecord>, ReadError>> {
        WorkStore::work(&self.inner, timeline_id, work_id)
    }
}

fn request(input: Value) -> ActionRequest {
    ActionRequest::new(
        target(),
        ActionInvocation::new(ActionTypeId::from(ROOT_ACTION), input),
    )
}

fn normal_input() -> Value {
    json!({
        "child_event_id": event(100).to_string(),
        "root_event_id": event(101).to_string(),
    })
}

#[tokio::test]
async fn cross_capability_resolution_flattens_owner_segments_into_one_commit() {
    let store = CountingStore::new();
    let runtime = Runtime::new(&store, registry(true)).expect("Runtime should assemble");
    let result = (&runtime as &dyn LoomApi)
        .invoke(request(normal_input()))
        .await
        .expect("cross-Capability composition should commit");
    assert!(matches!(result, ExecutionResult::Committed { .. }));
    assert_eq!(store.commit_count(), 1);
    let provenance = store.call_provenance();
    assert_eq!(provenance.len(), 1);
    let edge = &provenance.edges()[0];
    assert_eq!(edge.caller_capability.as_str(), ROOT_CAPABILITY);
    assert_eq!(edge.target_capability.as_str(), CHILD_CAPABILITY);
    assert_eq!(edge.caller_action.as_str(), ROOT_ACTION);
    assert_eq!(edge.target_action.as_str(), CHILD_ACTION);

    let snapshot = store
        .snapshot(timeline())
        .await
        .expect("composition Timeline should remain readable");
    assert_eq!(snapshot.events.len(), 2);
    assert_eq!(snapshot.events[0].event_type.as_str(), CHILD_EVENT);
    assert_eq!(snapshot.events[1].event_type.as_str(), ROOT_EVENT);
    assert_eq!(snapshot.events[1].causal_links.len(), 1);
    assert_eq!(
        snapshot
            .world_view()
            .facet(FacetOwner::entity(entity()), &FacetTypeId::from(ROOT_FACET))
            .expect("root Facet should exist")
            .value(),
        &json!({"value": 2})
    );
    assert_eq!(
        snapshot
            .world_view()
            .facet(
                FacetOwner::entity(entity()),
                &FacetTypeId::from(CHILD_FACET)
            )
            .expect("child Facet should exist")
            .value(),
        &json!({"value": 1})
    );
    assert_eq!(
        snapshot
            .events
            .iter()
            .map(|event| event.causal_links.len())
            .sum::<usize>(),
        1,
        "subresolution call edges must not become World Event causality",
    );
}

#[tokio::test]
async fn child_rejection_remains_a_semantic_outcome_without_commit() {
    let store = CountingStore::new();
    let runtime = Runtime::new(&store, registry(true)).expect("Runtime should assemble");
    let mut input = normal_input();
    input["reject_child"] = json!(true);
    let result = (&runtime as &dyn LoomApi)
        .invoke(request(input))
        .await
        .expect("child rejection should remain an API result");
    match result {
        ExecutionResult::Rejected(rejection) => {
            assert_eq!(rejection.code.as_str(), "composition.child_rejected");
        }
        other => panic!("expected child rejection, got {other:?}"),
    }
    assert_eq!(store.commit_count(), 0);
    assert!(
        store
            .snapshot(timeline())
            .await
            .expect("Timeline should exist")
            .events
            .is_empty()
    );
}

#[tokio::test]
async fn undeclared_child_capability_is_rejected_before_commit() {
    let store = CountingStore::new();
    let runtime = Runtime::new(&store, registry(false)).expect("Runtime should assemble");
    let error = (&runtime as &dyn LoomApi)
        .invoke(request(normal_input()))
        .await
        .expect_err("undeclared subresolution must fail before commit");
    assert_eq!(error.code, ApiErrorCode::Internal);
    assert_eq!(store.commit_count(), 0);
    assert!(
        store
            .snapshot(timeline())
            .await
            .expect("Timeline should exist")
            .events
            .is_empty()
    );
}

#[tokio::test]
async fn repeated_pair_is_rejected_as_a_path_cycle() {
    let store = CountingStore::new();
    let runtime = Runtime::new(&store, registry(true)).expect("Runtime should assemble");
    let mut input = normal_input();
    input["cycle"] = json!(true);
    let error = (&runtime as &dyn LoomApi)
        .invoke(request(input))
        .await
        .expect_err("A -> B -> A must be rejected deterministically");
    assert_eq!(error.code, ApiErrorCode::Internal);
    assert_eq!(store.commit_count(), 0);
    assert!(
        store
            .snapshot(timeline())
            .await
            .expect("Timeline should exist")
            .events
            .is_empty()
    );
}

#[tokio::test]
async fn depth_budget_stops_nested_dispatch_before_the_leaf_resolver() {
    let store = CountingStore::new();
    let runtime = Runtime::new(&store, registry(true))
        .expect("Runtime should assemble")
        .with_resolution_budget(ResolutionBudget::unlimited().with_max_subresolution_depth(1));
    let mut input = normal_input();
    input["depth"] = json!(true);
    let error = (&runtime as &dyn LoomApi)
        .invoke(request(input))
        .await
        .expect_err("depth budget must stop B -> C before dispatch");
    assert_eq!(error.code, ApiErrorCode::Internal);
    assert_eq!(store.commit_count(), 0);
}

#[tokio::test]
async fn subresolution_count_budget_stops_the_first_child_dispatch() {
    let store = CountingStore::new();
    let runtime = Runtime::new(&store, registry(true))
        .expect("Runtime should assemble")
        .with_resolution_budget(ResolutionBudget::unlimited().with_max_subresolution_count(0));
    let error = (&runtime as &dyn LoomApi)
        .invoke(request(normal_input()))
        .await
        .expect_err("zero child dispatch budget must stop A -> B before dispatch");
    assert_eq!(error.code, ApiErrorCode::Internal);
    assert_eq!(store.commit_count(), 0);
}

#[tokio::test]
async fn aggregate_budget_covers_child_and_root_segments() {
    let store = CountingStore::new();
    let runtime = Runtime::new(&store, registry(true))
        .expect("Runtime should assemble")
        .with_resolution_budget(ResolutionBudget::unlimited().with_max_events(1));
    let error = (&runtime as &dyn LoomApi)
        .invoke(request(normal_input()))
        .await
        .expect_err("two owner segments must exceed one-event aggregate budget");
    assert_eq!(error.code, ApiErrorCode::Internal);
    assert_eq!(store.commit_count(), 0);
    assert!(
        store
            .snapshot(timeline())
            .await
            .expect("Timeline should exist")
            .events
            .is_empty()
    );
}

#[tokio::test]
async fn invalid_child_segment_fails_before_commit_eligibility() {
    let store = CountingStore::new();
    let runtime = Runtime::new(&store, registry(true)).expect("Runtime should assemble");
    let mut input = normal_input();
    input["invalid_child"] = json!(true);
    let error = (&runtime as &dyn LoomApi)
        .invoke(request(input))
        .await
        .expect_err("invalid child payload must fail validation");
    assert_eq!(error.code, ApiErrorCode::Internal);
    assert_eq!(store.commit_count(), 0);
    assert!(
        store
            .snapshot(timeline())
            .await
            .expect("Timeline should exist")
            .events
            .is_empty()
    );
}

#[tokio::test]
async fn invalid_child_input_fails_before_child_dispatch_and_commit() {
    let store = CountingStore::new();
    let runtime = Runtime::new(&store, registry(true)).expect("Runtime should assemble");
    let mut input = normal_input();
    input["invalid_child_input"] = json!(true);
    let error = (&runtime as &dyn LoomApi)
        .invoke(request(input))
        .await
        .expect_err("invalid child input must fail before child dispatch");
    assert_eq!(error.code, ApiErrorCode::Internal);
    assert_eq!(store.commit_count(), 0);
    assert!(
        store
            .snapshot(timeline())
            .await
            .expect("Timeline should exist")
            .events
            .is_empty()
    );
}
