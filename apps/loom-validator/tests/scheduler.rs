//! Scheduler suite (T12) — CV-020 Timeline independence via public surface.
//!
//! `CV-018`/`CV-019` are frozen T08 blocked gaps: no public schedule/claim/fence
//! surface exists, so no descriptor, no Pass, no central registry entry is
//! produced for them. `CV-020` is the only executable row in this suite and is
//! verified here against real `InMemory` and controlled `PostgreSQL` Loom
//! services over the HTTP boundary. Assertions use only
//! `loom-api`/`loom-client` public reads: `AdminService::schedule_agency_wake`,
//! `AdminService::timeline_logical_status`, `TimelineService::inspect_timeline`,
//! `HistoryService::list_events` — no DB/table inspection.

mod common;

use loom_client::LoomClient;
use loom_validator::{BackendContext, BackendKind, ScenarioResult, scheduler, validator_registry};

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
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-018").is_none());
    assert!(registry.get("CV-020").is_none());
    assert!(registry.get("CV-040").is_none());

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
    // Frozen T08: CV-018 (logical-head) and CV-019 (stale fencing) have no public
    // schedule/claim/fence surface. This test documents the blocked state without
    // constructing Pass findings.
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
    // No ScenarioOutcome::Pass for blocked rows — verified by absence of descriptors.
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
