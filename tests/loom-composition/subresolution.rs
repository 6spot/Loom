use std::sync::{
    Arc, Mutex,
    atomic::{AtomicUsize, Ordering},
};

use loom_api::{ActionRequest, ApiErrorCode, ExecutionResult, LoomApi, TimelineTarget};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityDependency, CapabilityId,
    CapabilityManifest, CapabilityRegistrar, CapabilityRegistry, EventDefinition, FacetDefinition,
    RegistrationError, ResolutionContext, ResolverError,
};
use loom_core::{
    ActionTypeId, Entity, EntityId, EventId, EventTypeId, ExecutionSessionId, FacetOwner,
    FacetTypeId, SchemaRevision, TimelineId, WorldEffect, WorldId,
};
use loom_protocol::{
    ActionInvocation, CausalLink, ProposedEvent, Rejection, Resolution, ResolveOutcome,
};
use loom_runtime::{
    CallProvenance, CommitError, CommitResult, CommitStore, ExecutionSession,
    ExecutionSessionStatus, ExecutionSessionStore, PersistenceFuture, PlatformTime, ReadError,
    ResolutionBudget, Runtime, RuntimeRevisionCapability, RuntimeRevisionDescriptor,
    RuntimeRevisionError, RuntimeRevisionId, RuntimeRevisionSelection, RuntimeRevisionStore,
    SemanticProjectionError, SemanticProjectionHit, SemanticProjectionKey, SemanticProjectionQuery,
    SemanticProjectionRebuild, SemanticProjectionRegistration, SemanticProjectionStore,
    SessionError, TimelineSnapshot, ValidatedResolution, WorkClaim, WorkError, WorkRecord,
    WorkStore, WorldRuntimeBinding, WorldRuntimeBindingStore, WorldStore,
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
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_event_id(input, "event_id")?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(LEAF_EVENT),
            SchemaRevision::new(1),
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

impl SemanticProjectionStore for CountingStore {
    fn register_semantic_projection(
        &self,
        registration: SemanticProjectionRegistration,
    ) -> PersistenceFuture<'_, Result<(), SemanticProjectionError>> {
        SemanticProjectionStore::register_semantic_projection(&self.inner, registration)
    }

    fn query_semantic_projection(
        &self,
        query: SemanticProjectionQuery,
    ) -> PersistenceFuture<'_, Result<Vec<SemanticProjectionHit>, SemanticProjectionError>> {
        SemanticProjectionStore::query_semantic_projection(&self.inner, query)
    }

    fn rebuild_semantic_projection<'a>(
        &'a self,
        rebuild: &'a SemanticProjectionRebuild,
    ) -> PersistenceFuture<'a, Result<(), SemanticProjectionError>> {
        SemanticProjectionStore::rebuild_semantic_projection(&self.inner, rebuild)
    }

    fn delete_semantic_projection(
        &self,
        key: SemanticProjectionKey,
    ) -> PersistenceFuture<'_, Result<(), SemanticProjectionError>> {
        SemanticProjectionStore::delete_semantic_projection(&self.inner, key)
    }
}

impl WorldRuntimeBindingStore for CountingStore {
    fn read_binding(
        &self,
        world_id: WorldId,
    ) -> PersistenceFuture<'_, Result<WorldRuntimeBinding, loom_runtime::BindingError>> {
        WorldRuntimeBindingStore::read_binding(&self.inner, world_id)
    }

    fn persist_binding(
        &self,
        world_id: WorldId,
        binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<(), loom_runtime::BindingError>> {
        WorldRuntimeBindingStore::persist_binding(&self.inner, world_id, binding)
    }

    fn ensure_binding(
        &self,
        world_id: WorldId,
        legacy_binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<WorldRuntimeBinding, loom_runtime::BindingError>> {
        WorldRuntimeBindingStore::ensure_binding(&self.inner, world_id, legacy_binding)
    }
}

impl RuntimeRevisionStore for CountingStore {
    fn register_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> PersistenceFuture<'_, Result<(), RuntimeRevisionError>> {
        RuntimeRevisionStore::register_revision(&self.inner, revision)
    }

    fn confirm_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionDescriptor, RuntimeRevisionError>> {
        RuntimeRevisionStore::confirm_revision(&self.inner, revision)
    }

    fn read_revision(
        &self,
        revision_id: RuntimeRevisionId,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionDescriptor, RuntimeRevisionError>> {
        RuntimeRevisionStore::read_revision(&self.inner, revision_id)
    }

    fn list_revisions(
        &self,
    ) -> PersistenceFuture<'_, Result<Vec<RuntimeRevisionDescriptor>, RuntimeRevisionError>> {
        RuntimeRevisionStore::list_revisions(&self.inner)
    }

    fn read_active_revision(
        &self,
    ) -> PersistenceFuture<'_, Result<Option<RuntimeRevisionSelection>, RuntimeRevisionError>> {
        RuntimeRevisionStore::read_active_revision(&self.inner)
    }

    fn activate_revision(
        &self,
        revision_id: RuntimeRevisionId,
        expected_generation: Option<u64>,
        activated_at: PlatformTime,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionSelection, RuntimeRevisionError>> {
        RuntimeRevisionStore::activate_revision(
            &self.inner,
            revision_id,
            expected_generation,
            activated_at,
        )
    }
}

impl ExecutionSessionStore for CountingStore {
    fn start_session(
        &self,
        session: ExecutionSession,
    ) -> PersistenceFuture<'_, Result<(), SessionError>> {
        ExecutionSessionStore::start_session(&self.inner, session)
    }

    fn finish_session(
        &self,
        session_id: ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        ExecutionSessionStore::finish_session(&self.inner, session_id, status, ended_at)
    }

    fn read_session(
        &self,
        session_id: ExecutionSessionId,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        ExecutionSessionStore::read_session(&self.inner, session_id)
    }

    fn list_sessions(&self) -> PersistenceFuture<'_, Result<Vec<ExecutionSession>, SessionError>> {
        ExecutionSessionStore::list_sessions(&self.inner)
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
    let sessions = ExecutionSessionStore::list_sessions(&store)
        .await
        .expect("Action Session should be persisted");
    assert_eq!(sessions.len(), 1);
    assert_eq!(
        sessions[0].origin(),
        loom_runtime::ExecutionOrigin::Application
    );
    assert_eq!(sessions[0].id(), sessions[0].assembly().session_id());
    assert_eq!(sessions[0].assembly().world_id(), world());
    assert_eq!(sessions[0].assembly().timeline_id(), timeline());
    assert_eq!(
        sessions[0]
            .assembly()
            .expected_version()
            .head_event_seq
            .value(),
        0,
        "the root and all subresolutions must retain one input TimelineVersion",
    );
    assert_eq!(
        sessions[0]
            .assembly()
            .runtime_revision()
            .revision()
            .id()
            .as_str(),
        "legacy-registry",
    );
    assert!(sessions[0].status().is_terminal());
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

const SWITCH_CAPABILITY: &str = "session.switch";
const SWITCH_ACTION: &str = "session.switch_action";

struct SwitchingCapability {
    manifest: CapabilityManifest,
    store: Arc<InMemoryStore>,
}

impl Capability for SwitchingCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(SWITCH_ACTION), SchemaRevision::new(1))
                .with_input_schema(json!({"type": "object"})),
            SwitchingResolver {
                store: Arc::clone(&self.store),
            },
        )?;
        Ok(())
    }
}

struct SwitchingResolver {
    store: Arc<InMemoryStore>,
}

impl ActionResolver for SwitchingResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        _input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let sessions = self
            .store
            .list_sessions()
            .expect("Session should be durable before resolver dispatch");
        assert_eq!(sessions.len(), 1);
        assert_eq!(sessions[0].status(), ExecutionSessionStatus::Started);
        self.store
            .activate_revision(
                RuntimeRevisionId::from("r2"),
                Some(1),
                PlatformTime::new(20),
            )
            .expect("resolver hook should activate the next revision");
        Ok(ResolveOutcome::Rejected(Rejection::new(
            "session.switch_rejected",
            "test resolver switched the active revision after Session start",
        )))
    }
}

fn revision_for_registry(
    registry: &CapabilityRegistry,
    id: &str,
    implementation_prefix: &str,
) -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from(id),
        PlatformTime::new(1),
        format!("{id}-build"),
        registry
            .capabilities()
            .next()
            .expect("test registry should have one Capability")
            .version
            .clone(),
        registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!(
                    "{implementation_prefix}:{}@{}",
                    manifest.id, manifest.version
                ),
            )
        }),
    )
    .expect("test registry should form a Runtime Revision")
}

#[tokio::test]
async fn active_revision_switch_after_session_start_does_not_rebind_assembly() {
    let store = Arc::new(InMemoryStore::new());
    store
        .create_timeline(world(), timeline())
        .expect("switch Timeline should be created");
    WorldRuntimeBindingStore::persist_binding(
        store.as_ref(),
        world(),
        WorldRuntimeBinding::new(
            [(
                CapabilityId::from(SWITCH_CAPABILITY),
                CapabilityDependency::parse(SWITCH_CAPABILITY, "^0.1.0")
                    .expect("test requirement should parse")
                    .version,
            )],
            json!({"fixture": "revision-switch"}),
            1,
            Some("revision-switch".to_owned()),
        ),
    )
    .await
    .expect("switch binding should persist once");
    let registry = CapabilityRegistry::assemble([SwitchingCapability {
        manifest: CapabilityManifest::parse(SWITCH_CAPABILITY, "0.1.0")
            .expect("switch manifest should parse"),
        store: Arc::clone(&store),
    }])
    .expect("switch registry should assemble");
    let r1 = revision_for_registry(&registry, "r1", "implementation-r1");
    let r2 = revision_for_registry(&registry, "r2", "implementation-r2");
    let runtime = Runtime::new(store.as_ref(), registry).expect("Runtime should assemble");
    runtime
        .register_runtime_revision(r1)
        .await
        .expect("R1 should register");
    runtime
        .register_runtime_revision(r2)
        .await
        .expect("R2 should register");
    runtime
        .activate_runtime_revision(RuntimeRevisionId::from("r1"), None, PlatformTime::new(2))
        .await
        .expect("R1 should activate");

    let result = (&runtime as &dyn LoomApi)
        .invoke(ActionRequest::new(
            target(),
            ActionInvocation::new(ActionTypeId::from(SWITCH_ACTION), json!({})),
        ))
        .await
        .expect("the resolver's semantic rejection should remain a normal outcome");
    assert!(matches!(result, ExecutionResult::Rejected(_)));

    let sessions = ExecutionSessionStore::list_sessions(store.as_ref())
        .await
        .expect("Session should survive the active-revision switch");
    assert_eq!(sessions.len(), 1);
    let session = &sessions[0];
    assert_eq!(session.origin(), loom_runtime::ExecutionOrigin::Application);
    assert_eq!(session.status(), ExecutionSessionStatus::Rejected);
    assert_eq!(
        session
            .assembly()
            .runtime_revision()
            .revision()
            .id()
            .as_str(),
        "r1"
    );
    assert_eq!(
        session
            .assembly()
            .implementations()
            .capability(&CapabilityId::from(SWITCH_CAPABILITY))
            .expect("R1 implementation should be pinned")
            .implementation_id(),
        "implementation-r1:session.switch@0.1.0"
    );
    assert_eq!(
        runtime
            .active_runtime_revision()
            .await
            .expect("active revision should remain readable")
            .expect("R2 should be active")
            .revision()
            .id()
            .as_str(),
        "r2"
    );
}

#[tokio::test]
async fn world_binding_rejects_installed_but_disabled_action_before_dispatch() {
    let store = CountingStore::new();
    let binding = WorldRuntimeBinding::new(
        [(
            CapabilityId::from(ROOT_CAPABILITY),
            CapabilityDependency::parse(ROOT_CAPABILITY, "^0.1.0")
                .expect("root binding requirement should parse")
                .version,
        )],
        json!({"fixture": "root-only"}),
        1,
        Some("binding-test".to_owned()),
    );
    WorldRuntimeBindingStore::persist_binding(&store, world(), binding)
        .await
        .expect("World binding should persist once");

    let runtime = Runtime::new(&store, registry(true)).expect("Runtime should assemble");
    let error = (&runtime as &dyn LoomApi)
        .invoke(ActionRequest::new(
            target(),
            ActionInvocation::new(
                ActionTypeId::from(CHILD_ACTION),
                json!({"event_id": event(200).to_string()}),
            ),
        ))
        .await
        .expect_err("installed child Action must remain unavailable outside the binding");
    assert_eq!(error.code, ApiErrorCode::Unavailable);
    assert_eq!(store.commit_count(), 0);
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
