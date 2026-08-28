//! Agency Wake integration tests (T17 — CV-034..CV-037).
//!
//! Runtime and `InMemoryStore` are controlled drivers only. Assertions about
//! World, Work, Event, Facet, Timeline and Session state use `LoomClient`.

#![allow(clippy::too_many_lines)]

use std::sync::Arc;

use loom_agency::{
    CognitiveExecutor, CognitiveFuture, CognitiveMetadata, CognitiveRequest, DecisionReusePolicy,
    DeterministicCognitiveExecutor, DeterministicCognitiveStep, ExecutionPolicy,
};
use loom_api::{
    ActionService, AdminCognitiveDisposition, AdminCognitiveOutcome, AdminExecutionSession,
    AdminExecutionSessionRequest, AdminExecutionSessionStatus, AdminScheduleAgencyWakeRequest,
    AdminService, AdminWorkStatus, CreateWorldFromTemplateRequest, EntityId, EventQuery,
    FacetOwner, FacetQuery, HistoryService, QueryService, TimelineTarget, TimelineVersion,
    WorldInstant, WorldService, WorldTemplateDescriptor,
};
use loom_boundary::{BoundaryConfig, RequireAdminAuthorization, router_with_admin};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, RegistrationError, ResolutionContext, ResolverError,
};
use loom_client::LoomClient;
use loom_core::{ActionTypeId, FacetTypeId, SchemaRevision, WorkId};
use loom_neutral::{COUNTER_SEED_ACTION, registry as neutral_registry};
use loom_protocol::{ActionInvocation, Rejection, ResolveOutcome, WorkSchedule};
use loom_runtime::{
    PlatformTime, Runtime, RuntimeRevisionCapability, RuntimeRevisionDescriptor, RuntimeRevisionId,
};
use loom_storage::InMemoryStore;
use loom_validator::{agency, validator_registry};
use serde_json::json;
use uuid::Uuid;

const REJECTION_CAPABILITY: &str = "validator.agency.rejection";
const REJECTION_ACTION: &str = "validator.agency.reject";
const AGENT_UUID: &str = "00000000-0000-0000-0000-000000005101";

#[test]
fn agency_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(agency::SUITE, "agency");
    assert_eq!(agency::CV_RANGE, "CV-034..CV-037");
    assert_eq!(agency::CAPABILITY_AREA, "agency");
    assert_eq!(agency::suite_name(), "agency");
    assert!(agency::owns_cv("CV-034"));
    assert!(agency::owns_cv("CV-037"));
    assert!(!agency::owns_cv("CV-033"));
    assert!(!agency::owns_cv("CV-038"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 31);
    assert!(registry.get("CV-034").is_none());
    assert!(registry.get("CV-040").is_some());
}

#[derive(Clone, Debug)]
struct RejectionCapability {
    manifest: CapabilityManifest,
}

impl RejectionCapability {
    fn new() -> Self {
        Self {
            manifest: CapabilityManifest::parse(REJECTION_CAPABILITY, "0.1.0")
                .expect("rejection fixture manifest"),
        }
    }
}

impl Capability for RejectionCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(REJECTION_ACTION), SchemaRevision::new(1))
                .with_description("test-only semantic rejection fixture"),
            RejectionResolver,
        )
    }
}

struct RejectionResolver;

impl ActionResolver for RejectionResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        _input: &serde_json::Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Ok(ResolveOutcome::Rejected(Rejection::new(
            "validator.agency.semantic_rejection",
            "test-only Agency action was semantically refused",
        )))
    }
}

struct SharedDeterministicExecutor(Arc<DeterministicCognitiveExecutor>);

impl CognitiveExecutor for SharedDeterministicExecutor {
    fn metadata(&self) -> CognitiveMetadata {
        self.0.metadata()
    }

    fn execute<'a>(&'a self, request: &'a CognitiveRequest) -> CognitiveFuture<'a> {
        self.0.execute(request)
    }
}

struct AgencyHarness {
    client: LoomClient,
    store: &'static InMemoryStore,
    runtime: Arc<Runtime<&'static InMemoryStore>>,
    target: TimelineTarget,
    agent: EntityId,
    executor: Arc<DeterministicCognitiveExecutor>,
    _server: tokio::task::JoinHandle<()>,
}

fn test_runtime() -> &'static tokio::runtime::Runtime {
    static RUNTIME: std::sync::OnceLock<&'static tokio::runtime::Runtime> =
        std::sync::OnceLock::new();
    RUNTIME.get_or_init(|| {
        Box::leak(Box::new(
            tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .expect("agency test runtime"),
        ))
    })
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    test_runtime().block_on(future)
}

fn uuid() -> Uuid {
    Uuid::new_v4()
}

fn agent() -> EntityId {
    EntityId::new(AGENT_UUID.parse().expect("fixed agent UUID"))
}

fn revision_descriptor(registry: &CapabilityRegistry) -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("validator-agency-v0"),
        PlatformTime::default(),
        "validator-agency-test",
        registry.loom_version().clone(),
        registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("validator-agency:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("agency revision descriptor")
}

fn agency_registry() -> CapabilityRegistry {
    let mut registry = neutral_registry();
    registry
        .register(&RejectionCapability::new())
        .expect("register semantic rejection fixture");
    registry.validate().expect("agency registry validates");
    registry
}

async fn start_harness(
    script: impl IntoIterator<Item = DeterministicCognitiveStep>,
    policy: ExecutionPolicy,
) -> AgencyHarness {
    let store: &'static InMemoryStore = Box::leak(Box::new(InMemoryStore::new()));
    let registry = agency_registry();
    let revision = revision_descriptor(&registry);
    store
        .confirm_revision(revision.clone())
        .expect("confirm agency revision");
    store
        .activate_revision(revision.id().clone(), None, PlatformTime::default())
        .expect("activate agency revision");

    let executor = Arc::new(DeterministicCognitiveExecutor::new(script));
    let runtime = Arc::new(
        Runtime::new(store, registry)
            .expect("agency Runtime")
            .with_cognitive_executor(SharedDeterministicExecutor(Arc::clone(&executor)))
            .with_cognitive_policy(policy),
    );
    let router = router_with_admin(
        Arc::clone(&runtime),
        Arc::new(RequireAdminAuthorization),
        BoundaryConfig::default(),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("agency listener");
    let address = listener.local_addr().expect("agency address");
    let server = tokio::spawn(async move {
        axum::serve(listener, router)
            .await
            .expect("agency test server");
    });
    tokio::time::sleep(std::time::Duration::from_millis(25)).await;
    let client = LoomClient::builder(format!("http://{address}"))
        .admin_token("validator-test-admin")
        .expect("agency client builder")
        .build()
        .expect("agency client");

    let agent = agent();
    let created = client
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new("validator.t17.agency", 1, WorldInstant::new(42))
                .requires_capability("neutral.counter", "^0.1.0")
                .requires_capability(REJECTION_CAPABILITY, "^0.1.0"),
        ))
        .await
        .expect("create Agency fixture World");
    let seed = client
        .invoke(loom_api::ActionRequest::new(
            created.target,
            ActionInvocation::new(
                ActionTypeId::from(COUNTER_SEED_ACTION),
                json!({
                    "event_id": uuid().to_string(),
                    "entity_id": agent.to_string(),
                    "value": 0,
                }),
            ),
        ))
        .await
        .expect("seed Agency agent");
    assert!(seed.is_committed(), "agent seed must commit: {seed:?}");

    AgencyHarness {
        client,
        store,
        runtime,
        target: created.target,
        agent,
        executor,
        _server: server,
    }
}

async fn schedule(
    client: &LoomClient,
    target: TimelineTarget,
    agent: EntityId,
    work_id: WorkId,
    cognition: &str,
) -> TimelineVersion {
    let before = client
        .timeline_logical_status(target)
        .await
        .expect("read pre-schedule Timeline");
    let scheduled = client
        .schedule_agency_wake(AdminScheduleAgencyWakeRequest {
            target,
            expected_version: before.version,
            work_id,
            agent,
            cognition: cognition.to_owned(),
            payload: json!({"cv": "T17", "work_id": work_id.to_string()}),
            schedule: WorkSchedule::Immediate,
        })
        .await
        .expect("schedule Agency Wake");
    assert_eq!(scheduled.target, target);
    assert_eq!(scheduled.work_id, work_id);
    scheduled.version
}

async fn wake_session(client: &LoomClient, target: TimelineTarget) -> AdminExecutionSession {
    let sessions = client
        .list_execution_sessions()
        .await
        .expect("list Agency Sessions");
    let session = sessions
        .into_iter()
        .find(|session| {
            session.target == target && !session.cognitive_evidence.observations.is_empty()
        })
        .expect("Agency Session with cognitive provenance");
    client
        .get_execution_session(AdminExecutionSessionRequest {
            session_id: session.id,
        })
        .await
        .expect("read Agency Session through LoomClient")
}

async fn cognitive_sessions(
    client: &LoomClient,
    target: TimelineTarget,
) -> Vec<AdminExecutionSession> {
    let sessions = client
        .list_execution_sessions()
        .await
        .expect("list Agency Sessions")
        .into_iter()
        .filter(|session| {
            session.target == target && !session.cognitive_evidence.observations.is_empty()
        })
        .collect::<Vec<_>>();
    let mut result = Vec::with_capacity(sessions.len());
    for session in sessions {
        result.push(
            client
                .get_execution_session(AdminExecutionSessionRequest {
                    session_id: session.id,
                })
                .await
                .expect("read Agency Session through LoomClient"),
        );
    }
    result
}

#[test]
fn cv034_no_action_completes_wake_without_world_event_or_facet_mutation() {
    block_on(async {
        let harness = start_harness(
            [DeterministicCognitiveStep::no_action()],
            ExecutionPolicy::default(),
        )
        .await;
        let events_before = harness
            .client
            .list_events(EventQuery::all(harness.target))
            .await
            .expect("CV-034 history before");
        assert!(
            harness
                .client
                .get_facet(FacetQuery::new(
                    harness.target,
                    FacetOwner::entity(harness.agent),
                    FacetTypeId::from("neutral.blob.reference")
                ))
                .await
                .expect("CV-034 Facet before")
                .is_none()
        );

        let work_id = WorkId::new(uuid());
        schedule(
            &harness.client,
            harness.target,
            harness.agent,
            work_id,
            "deterministic.fake",
        )
        .await;
        let result = harness
            .runtime
            .execute_work(
                harness.target,
                work_id,
                PlatformTime::new(0),
                PlatformTime::new(10),
                PlatformTime::new(1),
            )
            .await
            .expect("NoAction Wake execution");
        assert!(
            result.is_committed(),
            "NoAction is a Work-only commit: {result:?}"
        );

        let status = harness
            .client
            .timeline_logical_status(harness.target)
            .await
            .expect("CV-034 Timeline evidence");
        assert_ne!(status.version, loom_core::TimelineVersion::default());
        assert!(
            status
                .works
                .iter()
                .any(|work| work.work_id == work_id && work.status == AdminWorkStatus::Completed)
        );
        assert_eq!(
            harness
                .client
                .list_events(EventQuery::all(harness.target))
                .await
                .expect("CV-034 history after"),
            events_before
        );
        assert!(
            harness
                .client
                .get_facet(FacetQuery::new(
                    harness.target,
                    FacetOwner::entity(harness.agent),
                    FacetTypeId::from("neutral.blob.reference")
                ))
                .await
                .expect("CV-034 Facet after")
                .is_none()
        );

        let session = wake_session(&harness.client, harness.target).await;
        assert_eq!(session.status, AdminExecutionSessionStatus::Committed);
        assert_eq!(session.cognitive_evidence.fresh_count, 1);
        assert_eq!(
            session.cognitive_evidence.observations[0].outcome,
            AdminCognitiveOutcome::NoAction
        );
        assert_eq!(
            session.cognitive_evidence.observations[0].disposition,
            AdminCognitiveDisposition::Fresh
        );
        assert_eq!(
            session.cognitive_evidence.observations[0].executor_id,
            "deterministic.fake"
        );
    });
}

#[test]
fn cv035_act_reenters_action_authority_and_commits_event_and_facet() {
    block_on(async {
        let event_id = uuid();
        let harness = start_harness(
            [DeterministicCognitiveStep::act(ActionInvocation::new(
                ActionTypeId::from("neutral.blob.attach"),
                json!({
                    "event_id": event_id.to_string(),
                    "entity_id": AGENT_UUID,
                    "hash": "sha256:cv035",
                    "media_type": "text/plain",
                }),
            ))],
            ExecutionPolicy::default(),
        )
        .await;
        let events_before = harness
            .client
            .list_events(EventQuery::all(harness.target))
            .await
            .expect("CV-035 history before");
        let work_id = WorkId::new(uuid());
        schedule(
            &harness.client,
            harness.target,
            harness.agent,
            work_id,
            "deterministic.fake",
        )
        .await;
        let result = harness
            .runtime
            .execute_work(
                harness.target,
                work_id,
                PlatformTime::new(0),
                PlatformTime::new(10),
                PlatformTime::new(1),
            )
            .await
            .expect("Act Wake execution");
        assert!(
            result.is_committed(),
            "Act must commit through normal authority: {result:?}"
        );

        let events = harness
            .client
            .list_events(EventQuery::all(harness.target))
            .await
            .expect("CV-035 history");
        assert_eq!(events.len(), events_before.len() + 1);
        assert_eq!(events.last().expect("Act Event").id, event_id.into());
        let facet = harness
            .client
            .get_facet(FacetQuery::new(
                harness.target,
                FacetOwner::entity(harness.agent),
                FacetTypeId::from("neutral.blob.reference"),
            ))
            .await
            .expect("CV-035 Facet")
            .expect("Act should create blob Facet");
        assert_eq!(facet.value["hash"], json!("sha256:cv035"));
        let session = wake_session(&harness.client, harness.target).await;
        assert_eq!(session.status, AdminExecutionSessionStatus::Committed);
        assert_eq!(session.event_refs.len(), 1);
        assert_eq!(
            session.cognitive_evidence.observations[0].outcome,
            AdminCognitiveOutcome::Act
        );
        assert_eq!(
            session.cognitive_evidence.observations[0].disposition,
            AdminCognitiveDisposition::Fresh
        );
        let lookup = harness
            .client
            .session_for_event(events.last().expect("Act Event").event_ref())
            .await
            .expect("Event to Session lookup");
        assert_eq!(lookup.session_id, Some(session.id));
    });
}

#[test]
fn cv036_semantic_rejection_completes_wake_without_false_event_or_facet() {
    block_on(async {
        let harness = start_harness(
            [DeterministicCognitiveStep::act(ActionInvocation::new(
                ActionTypeId::from(REJECTION_ACTION),
                json!({"reason": "semantic"}),
            ))],
            ExecutionPolicy::default(),
        )
        .await;
        let events_before = harness
            .client
            .list_events(EventQuery::all(harness.target))
            .await
            .expect("CV-036 history before");
        let work_id = WorkId::new(uuid());
        schedule(
            &harness.client,
            harness.target,
            harness.agent,
            work_id,
            "deterministic.fake",
        )
        .await;
        let result = harness
            .runtime
            .execute_work(
                harness.target,
                work_id,
                PlatformTime::new(0),
                PlatformTime::new(10),
                PlatformTime::new(1),
            )
            .await
            .expect("semantic rejection is a successful Wake outcome");
        assert!(
            matches!(result, loom_api::ExecutionResult::Rejected(_)),
            "expected semantic rejection, got {result:?}"
        );
        assert_eq!(
            harness
                .client
                .list_events(EventQuery::all(harness.target))
                .await
                .expect("CV-036 history after"),
            events_before
        );
        assert!(
            harness
                .client
                .get_facet(FacetQuery::new(
                    harness.target,
                    FacetOwner::entity(harness.agent),
                    FacetTypeId::from("neutral.blob.reference")
                ))
                .await
                .expect("CV-036 Facet")
                .is_none()
        );
        let status = harness
            .client
            .timeline_logical_status(harness.target)
            .await
            .expect("CV-036 Timeline");
        assert!(
            status
                .works
                .iter()
                .any(|work| work.work_id == work_id && work.status == AdminWorkStatus::Completed)
        );
        let session = wake_session(&harness.client, harness.target).await;
        assert_eq!(session.status, AdminExecutionSessionStatus::Rejected);
        assert_eq!(
            session.cognitive_evidence.observations[0].outcome,
            AdminCognitiveOutcome::Act
        );
        assert!(session.event_refs.is_empty());
    });
}

#[test]
fn cv037_cas_conflict_preserves_winner_and_records_resample_and_reuse_paths() {
    test_runtime().block_on(tokio::task::LocalSet::new().run_until(async {
        run_cas_conflict(DecisionReusePolicy::Resample, true).await;
        run_cas_conflict(DecisionReusePolicy::ReuseDeterministic, false).await;
    }));
}

async fn run_cas_conflict(policy: DecisionReusePolicy, resample: bool) {
    let stale_event = uuid();
    let fresh_event = uuid();
    let scripts = if resample {
        vec![
            DeterministicCognitiveStep::act(ActionInvocation::new(
                ActionTypeId::from("neutral.blob.attach"),
                json!({
                    "event_id": stale_event.to_string(),
                    "entity_id": AGENT_UUID,
                    "hash": "sha256:discarded",
                    "media_type": "text/plain",
                }),
            ))
            .with_delay_polls(50_000),
            DeterministicCognitiveStep::act(ActionInvocation::new(
                ActionTypeId::from("neutral.blob.attach"),
                json!({
                    "event_id": stale_event.to_string(),
                    "entity_id": AGENT_UUID,
                    "hash": "sha256:discarded-by-worker-two",
                    "media_type": "text/plain",
                }),
            )),
            DeterministicCognitiveStep::act(ActionInvocation::new(
                ActionTypeId::from("neutral.blob.attach"),
                json!({
                    "event_id": fresh_event.to_string(),
                    "entity_id": AGENT_UUID,
                    "hash": "sha256:resampled",
                    "media_type": "text/plain",
                }),
            )),
        ]
    } else {
        vec![
            DeterministicCognitiveStep::act(ActionInvocation::new(
                ActionTypeId::from("neutral.blob.attach"),
                json!({
                    "event_id": stale_event.to_string(),
                    "entity_id": AGENT_UUID,
                    "hash": "sha256:reused",
                    "media_type": "text/plain",
                }),
            ))
            .with_delay_polls(50_000),
            DeterministicCognitiveStep::act(ActionInvocation::new(
                ActionTypeId::from("neutral.blob.attach"),
                json!({
                    "event_id": stale_event.to_string(),
                    "entity_id": AGENT_UUID,
                    "hash": "sha256:reused",
                    "media_type": "text/plain",
                }),
            )),
        ]
    };
    let harness = start_harness(
        scripts,
        ExecutionPolicy::default().with_decision_reuse(policy),
    )
    .await;
    let history_before = harness
        .client
        .list_events(EventQuery::all(harness.target))
        .await
        .expect("CV-037 history before workers");
    let work_id = WorkId::new(uuid());
    let conflict_work_id = WorkId::new(uuid());
    schedule(
        &harness.client,
        harness.target,
        harness.agent,
        work_id,
        "deterministic.fake",
    )
    .await;

    // The existing storage seam performs a real authority terminalization of
    // this second Work immediately before the Agency Scheduler CAS. This
    // leaves the first worker's proposal pinned to a stale Timeline version;
    // the second worker path below targets the same Wake and is the only path
    // allowed to produce the winning Event.
    harness
        .client
        .schedule_agency_wake(AdminScheduleAgencyWakeRequest {
            target: harness.target,
            expected_version: harness
                .client
                .timeline_logical_status(harness.target)
                .await
                .expect("read pre-conflict Timeline")
                .version,
            work_id: conflict_work_id,
            agent: harness.agent,
            cognition: "deterministic.fake".to_owned(),
            payload: json!({"cv": "T17", "work_id": conflict_work_id.to_string()}),
            schedule: WorkSchedule::Immediate,
        })
        .await
        .expect("schedule CAS seam conflict Work");
    harness
        .store
        .inject_scheduler_conflict_once_for_test(conflict_work_id);

    // Worker one holds the first fence while cognition is delayed. Worker
    // two then claims the same Wake after that lease expires. Both paths are
    // Runtime workers; no ordinary client Action participates in the race.
    let worker_one = Arc::clone(&harness.runtime);
    let worker_two = Arc::new(
        Runtime::new(harness.store, agency_registry())
            .expect("second Agency worker Runtime")
            .with_cognitive_executor(SharedDeterministicExecutor(Arc::clone(&harness.executor)))
            .with_cognitive_policy(ExecutionPolicy::default().with_decision_reuse(policy)),
    );
    let worker_one_target = harness.target;
    let worker_one_task = tokio::task::spawn_local(async move {
        worker_one
            .execute_work(
                worker_one_target,
                work_id,
                PlatformTime::new(0),
                PlatformTime::new(10),
                PlatformTime::new(1),
            )
            .await
    });
    for _ in 0..10_000 {
        if harness.executor.calls() == 1 {
            break;
        }
        tokio::task::yield_now().await;
    }
    assert_eq!(
        harness.executor.calls(),
        1,
        "worker one must have claimed the Wake before worker two starts"
    );

    let worker_two_target = harness.target;
    let worker_two_first = worker_two
        .execute_work(
            worker_two_target,
            work_id,
            PlatformTime::new(11),
            PlatformTime::new(21),
            PlatformTime::new(12),
        )
        .await;

    if resample {
        assert!(
            worker_two_first.is_err(),
            "Resample worker two must lose the injected CAS: {worker_two_first:?}"
        );
        assert_eq!(harness.executor.calls(), 2);
        let after_loss = harness
            .client
            .timeline_logical_status(harness.target)
            .await
            .expect("read Work after stale CAS loss");
        assert!(
            after_loss
                .works
                .iter()
                .any(|work| work.work_id == work_id && work.status == AdminWorkStatus::Pending)
        );
        let history_after_loss = harness
            .client
            .list_events(EventQuery::all(harness.target))
            .await
            .expect("read History after stale CAS loss");
        assert!(
            history_after_loss
                .iter()
                .all(|event| event.id != stale_event.into())
        );
        assert!(
            history_after_loss
                .iter()
                .all(|event| event.id != fresh_event.into())
        );
        let second_result = worker_two
            .execute_work(
                harness.target,
                work_id,
                PlatformTime::new(12),
                PlatformTime::new(22),
                PlatformTime::new(13),
            )
            .await
            .expect("resampled Agency Wake");
        assert!(
            second_result.is_committed(),
            "resampled result must commit: {second_result:?}"
        );
        assert_eq!(harness.executor.calls(), 3);
    } else {
        assert!(
            worker_two_first.is_ok(),
            "ReuseDeterministic worker two should recover: {worker_two_first:?}"
        );
        assert_eq!(
            harness.executor.calls(),
            2,
            "reuse must not invoke cognition again after worker two's conflict"
        );
    }

    let worker_one_result = worker_one_task.await.expect("worker one path task");
    assert!(
        worker_one_result.is_err(),
        "stale worker one must not overwrite the winner: {worker_one_result:?}"
    );

    let status = harness
        .client
        .timeline_logical_status(harness.target)
        .await
        .expect("CV-037 Timeline status");
    assert!(
        status
            .works
            .iter()
            .any(|work| work.work_id == work_id && work.status == AdminWorkStatus::Completed)
    );
    let events = harness
        .client
        .list_events(EventQuery::all(harness.target))
        .await
        .expect("CV-037 history");
    assert_eq!(
        events.len(),
        history_before.len() + 1,
        "exactly one Agency Event may survive the two-worker race"
    );
    assert!(events.iter().all(|event| event.id != stale_event.into()) || !resample);
    if resample {
        assert!(events.iter().any(|event| event.id == fresh_event.into()));
    }
    let conflict_status = harness
        .client
        .timeline_logical_status(harness.target)
        .await
        .expect("CV-037 conflict Work status");
    assert!(conflict_status.works.iter().any(|work| {
        work.work_id == conflict_work_id && work.status == AdminWorkStatus::Cancelled
    }));
    let blob = harness
        .client
        .get_facet(FacetQuery::new(
            harness.target,
            FacetOwner::entity(harness.agent),
            FacetTypeId::from("neutral.blob.reference"),
        ))
        .await
        .expect("CV-037 blob Facet")
        .expect("winning Agency path blob Facet");
    assert_eq!(
        blob.value["hash"],
        json!(if resample {
            "sha256:resampled"
        } else {
            "sha256:reused"
        })
    );

    let sessions = cognitive_sessions(&harness.client, harness.target).await;
    assert!(sessions.iter().any(|session| {
        session.status == AdminExecutionSessionStatus::Failed
            && session.cognitive_evidence.discarded_count == 1
            && session.cognitive_evidence.observations[0].disposition
                == AdminCognitiveDisposition::Discarded
    }));
    if resample {
        assert!(sessions.iter().any(|session| {
            session.status == AdminExecutionSessionStatus::Committed
                && session.cognitive_evidence.fresh_count == 1
                && session.cognitive_evidence.observations[0].disposition
                    == AdminCognitiveDisposition::Fresh
        }));
        let event = events
            .iter()
            .find(|event| event.id == fresh_event.into())
            .expect("resampled Event");
        let session = sessions
            .iter()
            .find(|session| {
                session
                    .event_refs
                    .iter()
                    .any(|reference| reference == &event.event_ref())
            })
            .expect("resampled Event Session");
        assert_eq!(
            session.cognitive_evidence.observations[0].outcome,
            AdminCognitiveOutcome::Act
        );
    } else {
        assert!(sessions.iter().any(|session| {
            session.status == AdminExecutionSessionStatus::Committed
                && session.cognitive_evidence.reused_count == 1
                && session.cognitive_evidence.observations[0].disposition
                    == AdminCognitiveDisposition::Reused
        }));
        let event = events
            .iter()
            .find(|event| event.id == stale_event.into())
            .expect("reused Event");
        let session = sessions
            .iter()
            .find(|session| {
                session
                    .event_refs
                    .iter()
                    .any(|reference| reference == &event.event_ref())
            })
            .expect("reused Event Session");
        assert_eq!(
            session.cognitive_evidence.observations[0].outcome,
            AdminCognitiveOutcome::Act
        );
    }
}
