use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};

use loom_api::{
    ActionRequest, ApiErrorCode, CreateWorldFromTemplateRequest, LoomApi, TimelineTarget,
    WorldService, WorldTemplateDescriptor,
};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EntropyRequest, EntropySample, RegistrationError, ResolutionContext,
    ResolverError, WorkHandler, WorkHandlerDefinition,
};
use loom_core::{ActionTypeId, SchemaRevision, WorkHandlerId, WorkId, WorldInstant};
use loom_protocol::{ActionInvocation, Resolution, ResolveOutcome, WorkTarget};
use loom_runtime::{
    EntropySource, EntropySourceError, EntropySourceId, ExecutionOrigin, ExecutionSession,
    ExecutionSessionStatus, ExecutionSessionStore, PlatformTime, ResolutionBudget, Runtime,
    WorkRecord, WorkStatus,
};
use loom_storage::InMemoryStore;
use serde_json::{Value, json};

const CAPABILITY: &str = "entropy.finish";
const ACTION: &str = "entropy.finish.action";
const WORK_HANDLER: &str = "entropy.finish.work";
const SOURCE_ID: &str = "entropy-finish-test";

fn id<T>(value: u128) -> T
where
    T: std::str::FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

#[derive(Clone)]
struct CountingEntropySource {
    calls: Arc<AtomicUsize>,
}

impl EntropySource for CountingEntropySource {
    fn source_id(&self) -> EntropySourceId {
        EntropySourceId::from(SOURCE_ID)
    }

    fn sample(&self, request: &EntropyRequest) -> Result<EntropySample, EntropySourceError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(EntropySample::new(vec![0; request.byte_count()]))
    }
}

struct EntropyFinishCapability {
    manifest: CapabilityManifest,
}

impl Capability for EntropyFinishCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(ACTION), SchemaRevision::new(1)),
            EntropyFinishResolver,
        )?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(WorkHandlerId::from(WORK_HANDLER), SchemaRevision::new(1)),
            EntropyFinishResolver,
        )?;
        Ok(())
    }
}

struct EntropyFinishResolver;

impl EntropyFinishResolver {
    fn resolve_entropy(
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        context.request_entropy(&EntropyRequest::new(1))?;
        if input.get("fail").and_then(Value::as_bool) == Some(true) {
            context.request_entropy(&EntropyRequest::new(1))?;
        }
        Ok(ResolveOutcome::Resolved(Resolution::new(
            Vec::new(),
            Vec::new(),
        )))
    }
}

impl ActionResolver for EntropyFinishResolver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Self::resolve_entropy(context, input)
    }
}

impl WorkHandler for EntropyFinishResolver {
    fn handle(
        &self,
        context: &dyn ResolutionContext,
        payload: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Self::resolve_entropy(context, payload)
    }
}

fn registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([EntropyFinishCapability {
        manifest: CapabilityManifest::parse(CAPABILITY, "0.1.0")
            .expect("entropy test manifest should parse"),
    }])
    .expect("entropy test registry should assemble")
}

fn runtime(store: &InMemoryStore, calls: Arc<AtomicUsize>) -> Runtime<&InMemoryStore> {
    Runtime::new(store, registry())
        .expect("entropy test Runtime should assemble")
        .with_entropy_source(CountingEntropySource { calls })
        .with_resolution_budget(ResolutionBudget::unlimited().with_max_entropy_requests(1))
}

async fn create_empty_world<S>(runtime: &Runtime<S>) -> TimelineTarget
where
    S: loom_runtime::WorldStore
        + loom_runtime::WorldRuntimeBindingStore
        + loom_runtime::CommitStore
        + loom_runtime::WorkStore
        + loom_runtime::WorldLifecycleStore
        + loom_runtime::RuntimeRevisionStore
        + ExecutionSessionStore,
{
    runtime
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new("entropy-finish", 1, WorldInstant::new(0))
                .requires_capability(CAPABILITY, "^0.1.0"),
        ))
        .await
        .expect("empty World should be created")
        .target
}

async fn terminal_session(
    store: &InMemoryStore,
    origin: ExecutionOrigin,
    status: ExecutionSessionStatus,
) -> ExecutionSession {
    ExecutionSessionStore::list_sessions(store)
        .await
        .expect("Session list should be readable")
        .into_iter()
        .find(|session| {
            session.origin() == origin
                && session.status() == status
                && !session.entropy_evidence().is_empty()
        })
        .expect("expected terminal Session should be present")
}

fn assert_frozen_entropy(session: &ExecutionSession) {
    let evidence = session.entropy_evidence();
    assert_eq!(evidence.source_id().as_str(), SOURCE_ID);
    assert_eq!(evidence.len(), 1);
    assert_eq!(evidence.observations()[0].ordinal, 0);
    assert_eq!(evidence.observations()[0].request.byte_count(), 1);
    assert_eq!(evidence.observations()[0].sample.as_bytes(), &[0]);

    let encoded = serde_json::to_value(session).expect("Session should serialize");
    let restored: ExecutionSession =
        serde_json::from_value(encoded).expect("Session should deserialize");
    assert_eq!(&restored, session);
}

#[tokio::test]
async fn action_budget_failure_finishes_session_with_prior_entropy() {
    let store = InMemoryStore::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let runtime = runtime(&store, Arc::clone(&calls));
    let target = create_empty_world(&runtime).await;
    let api: &dyn LoomApi = &runtime;

    let error = api
        .invoke(ActionRequest::new(
            target,
            ActionInvocation::new(ActionTypeId::from(ACTION), json!({"fail": true})),
        ))
        .await
        .expect_err("second request should fail the Action before validation");
    assert_eq!(error.code, ApiErrorCode::Internal);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(
        store
            .snapshot(target.timeline_id)
            .expect("Timeline should remain readable")
            .events
            .is_empty()
    );

    let session = terminal_session(
        &store,
        ExecutionOrigin::Application,
        ExecutionSessionStatus::Failed,
    )
    .await;
    assert_frozen_entropy(&session);
}

#[tokio::test]
async fn work_budget_failure_finishes_session_with_prior_entropy() {
    let store = InMemoryStore::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let runtime = runtime(&store, Arc::clone(&calls));
    let target = create_empty_world(&runtime).await;
    let work_id = id::<WorkId>(0x4101);
    store
        .seed_work(WorkRecord {
            id: work_id,
            timeline_id: target.timeline_id,
            target: WorkTarget::CapabilityWork {
                owner: Some(CAPABILITY.to_owned()),
                handler: WorkHandlerId::from(WORK_HANDLER),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({"fail": true}),
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
        .expect("entropy test Work should be seeded");

    let error = runtime
        .execute_work(
            target,
            work_id,
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(2),
        )
        .await
        .expect_err("second request should fail the Work before validation");
    assert_eq!(error.code, ApiErrorCode::Internal);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(
        store
            .snapshot(target.timeline_id)
            .expect("Timeline should remain readable")
            .events
            .is_empty()
    );
    assert_eq!(
        store
            .work(target.timeline_id, work_id)
            .expect("Work lookup should succeed")
            .expect("Work should remain persisted")
            .status,
        WorkStatus::Pending
    );

    let session = terminal_session(
        &store,
        ExecutionOrigin::Runtime,
        ExecutionSessionStatus::Failed,
    )
    .await;
    assert_frozen_entropy(&session);
}

#[tokio::test]
async fn template_budget_failure_finishes_session_with_prior_entropy() {
    let store = InMemoryStore::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let runtime = runtime(&store, Arc::clone(&calls));
    let error = runtime
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new("entropy-finish-failure", 1, WorldInstant::new(0))
                .requires_capability(CAPABILITY, "^0.1.0")
                .with_bootstrap_action(ActionInvocation::new(
                    ActionTypeId::from(ACTION),
                    json!({"fail": true}),
                )),
        ))
        .await
        .expect_err("second request should fail Template bootstrap before validation");
    assert_eq!(error.code, ApiErrorCode::Internal);
    assert_eq!(calls.load(Ordering::SeqCst), 1);

    let session = terminal_session(
        &store,
        ExecutionOrigin::Runtime,
        ExecutionSessionStatus::Failed,
    )
    .await;
    assert_frozen_entropy(&session);
    assert!(store.snapshot(session.assembly().timeline_id()).is_err());
}

#[tokio::test]
async fn action_and_work_success_finish_sessions_with_entropy() {
    let store = InMemoryStore::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let runtime = runtime(&store, Arc::clone(&calls));
    let target = create_empty_world(&runtime).await;
    let api: &dyn LoomApi = &runtime;

    let action_result = api
        .invoke(ActionRequest::new(
            target,
            ActionInvocation::new(ActionTypeId::from(ACTION), json!({"fail": false})),
        ))
        .await
        .expect("one entropy sample should permit Action completion");
    assert!(action_result.is_no_change());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    let action_session = terminal_session(
        &store,
        ExecutionOrigin::Application,
        ExecutionSessionStatus::Committed,
    )
    .await;
    assert_frozen_entropy(&action_session);

    let work_id = id::<WorkId>(0x4201);
    store
        .seed_work(WorkRecord {
            id: work_id,
            timeline_id: target.timeline_id,
            target: WorkTarget::CapabilityWork {
                owner: Some(CAPABILITY.to_owned()),
                handler: WorkHandlerId::from(WORK_HANDLER),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({"fail": false}),
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
        .expect("successful entropy test Work should be seeded");
    let work_result = runtime
        .execute_work(
            target,
            work_id,
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(2),
        )
        .await
        .expect("one entropy sample should permit Work completion");
    assert!(work_result.is_committed());
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    let work_session = terminal_session(
        &store,
        ExecutionOrigin::Runtime,
        ExecutionSessionStatus::Committed,
    )
    .await;
    assert_frozen_entropy(&work_session);
}

#[tokio::test]
async fn template_success_finishes_session_with_ordered_entropy() {
    let store = InMemoryStore::new();
    let calls = Arc::new(AtomicUsize::new(0));
    let runtime = runtime(&store, Arc::clone(&calls));
    let created = runtime
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new("entropy-finish-success", 1, WorldInstant::new(0))
                .requires_capability(CAPABILITY, "^0.1.0")
                .with_bootstrap_action(ActionInvocation::new(
                    ActionTypeId::from(ACTION),
                    json!({"fail": false}),
                )),
        ))
        .await
        .expect("one successful entropy sample should permit Template bootstrap");
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(
        store
            .snapshot(created.target.timeline_id)
            .expect("created Timeline should be readable")
            .events
            .is_empty()
    );

    let session = terminal_session(
        &store,
        ExecutionOrigin::Runtime,
        ExecutionSessionStatus::Committed,
    )
    .await;
    assert_frozen_entropy(&session);
}
