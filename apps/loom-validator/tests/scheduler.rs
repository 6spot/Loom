//! Scheduler suite (T12) — CV-018/CV-019 controlled fencing harness and CV-020
//! Timeline independence via the public surface.
//!
//! CV-018/CV-019 use only the test composition root's existing
//! Runtime/WorkStore/Scheduler/Storage authority for setup and control. Every
//! finding assertion is made from `LoomClient` public/formal reads; the driver
//! return values are never the Validator evidence. Production Scheduler
//! descriptors remain unchanged until the separately owned registry work.

mod common;

use loom_api::{
    ActionInvocation, ActionTypeId, AdminLogicalWorkStatus, AdminService, AdminWorkStatus,
    CreateWorldFromTemplateRequest, EventQuery, HistoryService, TimelineService, TimelineTarget,
    WorkId, WorkSchedule, WorldInstant, WorldService, WorldTemplateDescriptor,
};
use loom_client::LoomClient;
use loom_validator::{BackendContext, BackendKind, ScenarioResult, scheduler, validator_registry};
use serde_json::{Value, json};
use uuid::Uuid;

fn cv020_descriptor() -> loom_validator::ScenarioDescriptor {
    scheduler::descriptors()
        .into_iter()
        .find(|d| d.id_str() == scheduler::CV_020)
        .expect("CV-020 descriptor should exist")
}

fn assert_pass(result: &ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass against the real Loom service: {result:?}"
    );
    // Ensure evidence is via public surface, not internal tables.
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("public-surface:loom-client::AdminService::schedule_agency_wake"),
        "CV-020 should evidence schedule_agency_wake: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::AdminService::timeline_logical_status"),
        "CV-020 should evidence timeline_logical_status: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::TimelineService::inspect_timeline"),
        "CV-020 should evidence inspect_timeline: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::HistoryService::list_events"),
        "CV-020 should evidence list_events: {evidence}"
    );
    assert!(
        !evidence.to_ascii_lowercase().contains("loom_storage")
            && !evidence.to_ascii_lowercase().contains("pgstorage")
            && !evidence.to_ascii_lowercase().contains("sqlx"),
        "CV-020 must not use Storage/SQLx internals: {evidence}"
    );
}

fn context(client: LoomClient, backend: BackendKind, scope: &str) -> BackendContext {
    BackendContext::new(client)
        .with_backend_kind(backend)
        .with_scope(scope)
}

#[derive(Clone, Debug, PartialEq)]
struct PublicSchedulerObservation {
    logical: loom_api::AdminTimelineLogicalStatus,
    snapshot: loom_api::TimelineSnapshot,
    history: Vec<loom_api::CommittedEvent>,
}

fn observe_scheduler_state(
    client: &LoomClient,
    target: TimelineTarget,
) -> PublicSchedulerObservation {
    common::leaked_runtime().block_on(async {
        PublicSchedulerObservation {
            logical: client
                .timeline_logical_status(target)
                .await
                .expect("public Timeline logical status read should succeed"),
            snapshot: client
                .inspect_timeline(target)
                .await
                .expect("public Timeline inspect read should succeed"),
            history: client
                .list_events(EventQuery::all(target))
                .await
                .expect("public Timeline history read should succeed"),
        }
    })
}

fn public_work(
    observation: &PublicSchedulerObservation,
    work_id: WorkId,
) -> &AdminLogicalWorkStatus {
    observation
        .logical
        .works
        .iter()
        .find(|work| work.work_id == work_id)
        .unwrap_or_else(|| panic!("public logical status omitted Work {work_id}"))
}

fn scheduler_fixture(client: &LoomClient) -> (TimelineTarget, loom_api::EntityId) {
    let agent = loom_api::EntityId::new(Uuid::new_v4());
    let bootstrap_event = loom_api::EventId::new(Uuid::new_v4());
    let target = common::leaked_runtime().block_on(async {
        client
            .create_world_from_template(CreateWorldFromTemplateRequest::new(
                WorldTemplateDescriptor::new(
                    "validator.t12.scheduler.controlled-fencing.v1",
                    1,
                    WorldInstant::new(100),
                )
                .requires_capability("neutral.counter", "^0.1.0")
                .with_bootstrap_action(ActionInvocation::new(
                    ActionTypeId::from("neutral.counter.seed"),
                    json!({
                        "event_id": bootstrap_event.to_string(),
                        "entity_id": agent.to_string(),
                        "value": 1,
                    }),
                )),
            ))
            .await
            .expect("controlled scheduler fixture World should be created")
            .target
    });
    (target, agent)
}

fn work_payload(work_id: WorkId, entity_id: loom_api::EntityId) -> Value {
    json!({
        "event_id": loom_api::EventId::new(Uuid::new_v4()).to_string(),
        "entity_id": entity_id.to_string(),
        "amount": 1,
        "work_id": work_id.to_string(),
    })
}

fn assert_logical_head_rejection_and_order(
    client: &LoomClient,
    target: TimelineTarget,
    entity_id: loom_api::EntityId,
    first: WorkId,
    second: WorkId,
    schedule: impl Fn(WorkId, Value) -> Result<(), String>,
    execute: impl Fn(WorkId) -> Result<loom_api::ExecutionResult, String>,
) {
    schedule(first, work_payload(first, entity_id))
        .expect("first controlled Work should be scheduled");
    schedule(second, work_payload(second, entity_id))
        .expect("second controlled Work should be scheduled");

    let before = observe_scheduler_state(client, target);
    let first_status = public_work(&before, first);
    let second_status = public_work(&before, second);
    assert_eq!(first_status.status, AdminWorkStatus::Pending);
    assert_eq!(second_status.status, AdminWorkStatus::Pending);
    assert_eq!(
        first_status.effective_due_world_time,
        second_status.effective_due_world_time
    );
    assert!(
        first_status.logical_schedule_order < second_status.logical_schedule_order,
        "the public logical status must expose deterministic predecessor order"
    );

    let later_error =
        execute(second).expect_err("non-head Work must be rejected by Runtime authority");
    assert!(
        later_error.contains("NotLogicalHead")
            || later_error.to_ascii_lowercase().contains("logical head"),
        "non-head rejection should retain the authoritative reason: {later_error}"
    );
    let after_rejection = observe_scheduler_state(client, target);
    assert_eq!(
        after_rejection, before,
        "non-head rejection must have no public authoritative mutation"
    );

    assert!(
        matches!(
            execute(first),
            Ok(loom_api::ExecutionResult::Committed { .. })
        ),
        "logical head should execute through Runtime authority"
    );
    let after_head = observe_scheduler_state(client, target);
    assert_eq!(
        public_work(&after_head, first).status,
        AdminWorkStatus::Completed
    );
    assert_eq!(
        public_work(&after_head, second).status,
        AdminWorkStatus::Pending
    );
    assert!(after_head.logical.logical_commit_count > before.logical.logical_commit_count);
    assert!(after_head.history.len() > before.history.len());

    assert!(
        matches!(
            execute(second),
            Ok(loom_api::ExecutionResult::Committed { .. })
        ),
        "the successor should execute after its public predecessor completion"
    );
    let final_state = observe_scheduler_state(client, target);
    assert_eq!(
        public_work(&final_state, first).status,
        AdminWorkStatus::Completed
    );
    assert_eq!(
        public_work(&final_state, second).status,
        AdminWorkStatus::Completed
    );
    assert!(final_state.logical.logical_commit_count > after_head.logical.logical_commit_count);
    assert!(final_state.history.len() > after_head.history.len());
}

#[test]
fn scheduler_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(scheduler::SUITE, "scheduler");
    assert_eq!(scheduler::CV_RANGE, "CV-018..CV-020");
    assert_eq!(scheduler::CAPABILITY_AREA, "scheduler");
    assert_eq!(scheduler::suite_name(), "scheduler");
    assert!(scheduler::owns_cv("CV-018"));
    assert!(scheduler::owns_cv("CV-019"));
    assert!(scheduler::owns_cv("CV-020"));
    assert!(!scheduler::owns_cv("CV-017"));
    assert!(!scheduler::owns_cv("CV-021"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 31);
    assert!(registry.get("CV-018").is_none());
    assert!(registry.get("CV-020").is_some());
    assert!(registry.get("CV-040").is_some());

    // CV-020 is the only descriptor in the suite; CV-018/CV-019 remain blocked gaps
    // without descriptors or Pass results.
    let descriptors = scheduler::descriptors();
    assert_eq!(descriptors.len(), 1, "only CV-020 should have a descriptor");
    assert_eq!(descriptors[0].id_str(), "CV-020");
    assert!(
        descriptors[0]
            .supported_backends()
            .contains(&BackendKind::InMemory)
    );
    assert!(
        descriptors[0]
            .supported_backends()
            .contains(&BackendKind::PostgreSQL)
    );
}

#[test]
fn scheduler_cv020_blocked_gaps_have_no_descriptor_or_pass() {
    // Production descriptors remain owned by the central registry work. The
    // effective T12 amendment exercises these rows below with a test-only
    // controlled driver, without introducing a production schedule/claim/fence
    // API in this leaf.
    let descriptors = scheduler::descriptors();
    assert!(
        descriptors.iter().all(|d| d.id_str() != "CV-018"),
        "CV-018 must not have a descriptor"
    );
    assert!(
        descriptors.iter().all(|d| d.id_str() != "CV-019"),
        "CV-019 must not have a descriptor"
    );
    assert!(scheduler::owns_cv("CV-018"));
    assert!(scheduler::owns_cv("CV-019"));
}

#[test]
fn cv018_logical_head_rejection_and_order_on_in_memory_authority() {
    let (server, client) =
        common::InMemoryServer::start().expect("real InMemory Loom service should start");
    let (target, entity_id) = scheduler_fixture(&client);
    let first = WorkId::new(Uuid::new_v4());
    let second = WorkId::new(Uuid::new_v4());
    assert_logical_head_rejection_and_order(
        &client,
        target,
        entity_id,
        first,
        second,
        |work_id, payload| {
            server
                .schedule_work_for_test(
                    target,
                    work_id,
                    payload,
                    WorkSchedule::At(WorldInstant::new(100)),
                )
                .map(|_| ())
        },
        |work_id| {
            server.execute_work_for_test(
                target,
                work_id,
                loom_runtime::PlatformTime::new(0),
                loom_runtime::PlatformTime::new(10),
                loom_runtime::PlatformTime::new(0),
            )
        },
    );
}

#[test]
fn cv018_logical_head_rejection_and_order_on_controlled_postgres18_authority() {
    let (server, client) = common::PgServer::start()
        .expect("controlled PostgreSQL 18 Loom service should start with explicit test URL");
    let (target, entity_id) = scheduler_fixture(&client);
    let first = WorkId::new(Uuid::new_v4());
    let second = WorkId::new(Uuid::new_v4());
    assert_logical_head_rejection_and_order(
        &client,
        target,
        entity_id,
        first,
        second,
        |work_id, payload| {
            server
                .schedule_work_for_test(
                    target,
                    work_id,
                    payload,
                    WorkSchedule::At(WorldInstant::new(100)),
                )
                .map(|_| ())
        },
        |work_id| {
            server.execute_work_for_test(
                target,
                work_id,
                loom_runtime::PlatformTime::new(0),
                loom_runtime::PlatformTime::new(10),
                loom_runtime::PlatformTime::new(0),
            )
        },
    );
}

fn assert_stale_claim_rejection_and_single_winner(
    client: &LoomClient,
    target: TimelineTarget,
    entity_id: loom_api::EntityId,
    schedule: impl Fn(WorkId, Value) -> Result<(), String>,
    claim: impl Fn(
        WorkId,
        loom_runtime::PlatformTime,
        loom_runtime::PlatformTime,
    ) -> Result<loom_runtime::WorkClaim, String>,
    complete: impl Fn(loom_runtime::WorkClaim, loom_runtime::PlatformTime) -> Result<(), String>,
    restart: impl Fn() -> LoomClient,
) {
    let work_id = WorkId::new(Uuid::new_v4());
    schedule(work_id, work_payload(work_id, entity_id))
        .expect("controlled Work should be scheduled");
    let before = observe_scheduler_state(client, target);
    assert_eq!(
        public_work(&before, work_id).status,
        AdminWorkStatus::Pending
    );

    let old_claim = claim(
        work_id,
        loom_runtime::PlatformTime::new(10),
        loom_runtime::PlatformTime::new(20),
    )
    .expect("first owner should obtain the Work claim");
    let new_claim = claim(
        work_id,
        loom_runtime::PlatformTime::new(20),
        loom_runtime::PlatformTime::new(30),
    )
    .expect("expired claim should be reclaimed by the new owner");
    assert_ne!(old_claim.fence(), new_claim.fence());

    // Rebuild the HTTP boundary after reclaim. Claims remain the only control
    // evidence; all acceptance assertions below use this fresh LoomClient.
    let client_after_restart = restart();
    let before_stale_completion = observe_scheduler_state(&client_after_restart, target);
    assert_eq!(before_stale_completion, before);

    let stale_error = complete(old_claim, loom_runtime::PlatformTime::new(21))
        .expect_err("stale owner completion must be rejected by commit authority");
    assert!(
        stale_error.to_ascii_lowercase().contains("stale")
            || stale_error.to_ascii_lowercase().contains("fence"),
        "stale completion should retain its authoritative rejection: {stale_error}"
    );
    let after_stale_completion = observe_scheduler_state(&client_after_restart, target);
    assert_eq!(
        after_stale_completion, before_stale_completion,
        "stale completion must not cause public Work, Timeline or History mutation"
    );

    complete(new_claim, loom_runtime::PlatformTime::new(22))
        .expect("new owner's completion should commit through Scheduler authority");
    let final_state = observe_scheduler_state(&client_after_restart, target);
    assert_eq!(
        public_work(&final_state, work_id).status,
        AdminWorkStatus::Completed
    );
    assert!(final_state.logical.logical_commit_count > before.logical.logical_commit_count);
    assert!(final_state.logical.version.state_revision > before.logical.version.state_revision);
    assert_eq!(
        final_state.history, before.history,
        "empty Work completion must not fabricate a stale or winner Event"
    );
}

#[test]
fn cv019_stale_fence_rejection_and_single_winner_on_in_memory_authority() {
    let (server, client) =
        common::InMemoryServer::start().expect("real InMemory Loom service should start");
    let (target, entity_id) = scheduler_fixture(&client);
    assert_stale_claim_rejection_and_single_winner(
        &client,
        target,
        entity_id,
        |work_id, payload| {
            server
                .schedule_work_for_test(
                    target,
                    work_id,
                    payload,
                    WorkSchedule::At(WorldInstant::new(100)),
                )
                .map(|_| ())
        },
        |work_id, now, claimed_until| {
            server.claim_work_for_test(target, work_id, now, claimed_until)
        },
        |claim, now| {
            server
                .complete_claim_for_test(target, claim, now)
                .map(|_| ())
        },
        || {
            server
                .restart()
                .expect("InMemory boundary restart should succeed")
        },
    );
}

#[test]
fn cv019_stale_fence_rejection_and_single_winner_on_controlled_postgres18_authority() {
    let (server, client) = common::PgServer::start()
        .expect("controlled PostgreSQL 18 Loom service should start with explicit test URL");
    let (target, entity_id) = scheduler_fixture(&client);
    assert_stale_claim_rejection_and_single_winner(
        &client,
        target,
        entity_id,
        |work_id, payload| {
            server
                .schedule_work_for_test(
                    target,
                    work_id,
                    payload,
                    WorkSchedule::At(WorldInstant::new(100)),
                )
                .map(|_| ())
        },
        |work_id, now, claimed_until| {
            server.claim_work_for_test(target, work_id, now, claimed_until)
        },
        |claim, now| {
            server
                .complete_claim_for_test(target, claim, now)
                .map(|_| ())
        },
        || {
            server
                .restart()
                .expect("PostgreSQL boundary restart should succeed")
        },
    );
}

#[test]
fn cv020_independent_timelines_pass_on_real_in_memory_service() {
    let (_server, client) =
        common::InMemoryServer::start().expect("real InMemory Loom service should start");
    let descriptor = cv020_descriptor();
    let ctx = context(client, BackendKind::InMemory, "real-CV-020-inmemory");
    let result = scheduler::execute_scheduler(&descriptor, &ctx);
    assert_pass(&result, "CV-020");
    // Verify fixed WorldInstant per spec (evidence contains deterministic instant handling).
    let actual = result.finding().actual();
    assert!(
        actual.contains("fixed_instant=100"),
        "CV-020 should use fixed WorldInstant 100: {actual}"
    );
    assert!(
        actual.contains("independent timelines verified"),
        "CV-020 actual should describe independence: {actual}"
    );
}

#[test]
fn cv020_independent_timelines_pass_on_live_postgres_service_when_configured() {
    // Controlled PostgreSQL evidence: when LOOM_TEST_POSTGRES_URL is not set or the
    // repository-managed DB is unreachable, the harness reports prerequisite/unavailable
    // rather than synthetic pass. This test starts the real PgStorage-backed service
    // and asserts the per-Timeline independence via the same public CAS boundaries.
    let pg_start = common::PgServer::start();
    let (_server, client) = match pg_start {
        Ok(pair) => pair,
        Err(e) => {
            // If PostgreSQL is not available in this environment, document the gap
            // without claiming Pass. The ledger records the attempt; this test
            // remains green by asserting the unavailable signal instead of failing.
            let descriptor = cv020_descriptor();
            let ctx = BackendContext::new(
                LoomClient::builder("http://127.0.0.1:1")
                    .build()
                    .expect("client"),
            )
            .with_backend_kind(BackendKind::PostgreSQL)
            .with_scope("real-CV-020-postgres-unavailable");
            let result = scheduler::execute_scheduler(&descriptor, &ctx);
            assert!(
                !result.outcome().is_pass(),
                "CV-020 PostgreSQL when unavailable should not pass: {result:?}"
            );
            eprintln!("PG unavailable, skipping live pass assertion: {e}");
            return;
        }
    };
    let descriptor = cv020_descriptor();
    let ctx = context(client, BackendKind::PostgreSQL, "real-CV-020-postgres");
    let result = scheduler::execute_scheduler(&descriptor, &ctx);
    if result.outcome().is_pass() {
        assert_pass(&result, "CV-020");
        let actual = result.finding().actual();
        assert!(
            actual.contains("fixed_instant=100"),
            "CV-020 PG should use fixed WorldInstant 100: {actual}"
        );
    } else if result.outcome().is_unavailable() || result.outcome().is_skipped() {
        // PostgreSQL not configured for a trusted live evidence class in this env — this
        // still exercises the public-surface code path without claiming a synthetic Pass.
        eprintln!(
            "PG live not configured, CV-020 returned {}: {:?}",
            result.outcome().as_str(),
            result
        );
    } else {
        assert_pass(&result, "CV-020");
    }
}
