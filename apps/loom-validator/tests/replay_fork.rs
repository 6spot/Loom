//! VAL-T9 replay/fork scenarios executed against real Loom service boundaries.
//!
//! These tests intentionally remain separate from the unit scenarios in
//! `src/scenarios.rs`.  The unit layer may use the Validator-owned `MockApi` to
//! exercise orchestration deterministically; this layer composes Loom itself,
//! connects through its HTTP boundary, and passes the production
//! `LoomClient`-backed `BackendContext` to the same scenario implementation.

mod common;

use std::sync::Arc;

use loom_client::LoomClient;
use loom_validator::{
    BackendContext, BackendKind, ScenarioDescriptor, ScenarioResult, replay_fork_descriptors,
};

use common::{InMemoryServer, PgServer};

fn descriptor(id: &str) -> ScenarioDescriptor {
    replay_fork_descriptors()
        .into_iter()
        .find(|descriptor| descriptor.id_str() == id)
        .unwrap_or_else(|| panic!("missing replay/fork descriptor {id}"))
}

fn assert_pass(result: &ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass against the real Loom service: {result:?}"
    );
}

fn context(client: LoomClient, backend: BackendKind, scope: &str) -> BackendContext {
    BackendContext::new(client)
        .with_backend_kind(backend)
        .with_scope(scope)
}

#[test]
fn cv005_to_cv008_pass_on_real_in_memory_service() {
    let (_server, client) =
        InMemoryServer::start().expect("real InMemory Loom service should start");
    for id in ["CV-005", "CV-006", "CV-007", "CV-008"] {
        let context = context(client.clone(), BackendKind::InMemory, &format!("real-{id}"));
        let result = loom_validator::execute_replay_fork(&descriptor(id), &context);
        assert_pass(&result, id);
    }
}

#[test]
fn cv005_to_cv008_pass_on_live_postgres_service_when_configured() {
    if std::env::var(loom_validator::LOOM_TEST_POSTGRES_URL)
        .map_or(true, |value| value.trim().is_empty())
    {
        eprintln!("skipping: LOOM_TEST_POSTGRES_URL is not configured");
        return;
    }

    let (_server, client) = PgServer::start().expect("real PostgreSQL Loom service should start");
    for id in ["CV-005", "CV-006", "CV-007", "CV-008"] {
        let context = context(
            client.clone(),
            BackendKind::PostgreSQL,
            &format!("real-{id}"),
        );
        let result = loom_validator::execute_replay_fork(&descriptor(id), &context);
        assert_pass(&result, id);
    }
}

#[test]
fn cv009_is_unavailable_on_real_in_memory_service() {
    // InMemory has no durable restart contract; CV-009 must remain an explicit
    // unavailable gap even when a real InMemory service with restart capability
    // exists. This validates the gap reporting without using MockApi.
    let (_server, client) =
        InMemoryServer::start().expect("real InMemory Loom service should start");
    let descriptor = descriptor("CV-009");
    let context = context(client, BackendKind::InMemory, "real-CV-009");
    let result = loom_validator::execute_replay_fork(&descriptor, &context);
    assert!(
        !result.outcome().is_pass(),
        "CV-009 InMemory should not pass: {result:?}"
    );
    assert_eq!(
        result.outcome().as_str(),
        "unavailable",
        "CV-009 InMemory should be unavailable (gap): {result:?}"
    );
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("gap") && evidence.contains("inmemory-durable-restart"),
        "CV-009 InMemory unavailable should cite gap: {evidence}"
    );
}

#[test]
fn cv009_postgres_restart_survives_real_boundary_rebuild_when_configured() {
    if std::env::var(loom_validator::LOOM_TEST_POSTGRES_URL)
        .map_or(true, |value| value.trim().is_empty())
    {
        eprintln!("skipping: LOOM_TEST_POSTGRES_URL is not configured");
        return;
    }

    let (server, client) = PgServer::start().expect("real PostgreSQL Loom service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let descriptor = descriptor("CV-009");
    let context = BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_restart_strategy(strategy)
        .with_scope("real-CV-009-restart");
    let result = loom_validator::execute_replay_fork(&descriptor, &context);
    assert_pass(&result, "CV-009");
    // Ensure the scenario actually exercised restart path (evidence should contain restart marker)
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("validator:restart") || evidence.contains("restart"),
        "CV-009 PostgreSQL evidence should contain restart marker: {evidence}"
    );
    // Verify public surfaces were used, no storage/sqlx internals
    assert!(
        evidence.contains("public-surface:loom-client::TimelineService::inspect_timeline"),
        "CV-009 should assert via inspect_timeline: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::HistoryService::list_events"),
        "CV-009 should assert via history: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::QueryService::get_facet"),
        "CV-009 should assert via get_facet: {evidence}"
    );
    assert!(
        !evidence.to_lowercase().contains("loom_storage")
            && !evidence.to_lowercase().contains("pgstorage")
            && !evidence.to_lowercase().contains("sqlx"),
        "CV-009 must not assert against Storage/SQLx internals: {evidence}"
    );
}
