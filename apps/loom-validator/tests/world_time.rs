//! T13 World Time/Chronology/Reaction integration coverage.
//!
//! Every scenario runs through a real HTTP boundary. Restart scenarios use a
//! fresh `LoomClient` returned by the controlled harness; the aggregate test
//! deliberately creates a fresh server/client per CV so CV-023 cannot leave a
//! stale client for CV-024.

mod common;

use std::sync::Arc;

use loom_client::LoomClient;
use loom_validator::{BackendContext, BackendKind, ScenarioResult, validator_registry, world_time};

fn assert_pass(result: &ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass: {}",
        result.finding().render()
    );
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("public-surface:loom-client"),
        "{id} must use public client surfaces: {evidence}"
    );
    assert!(
        !evidence.to_ascii_lowercase().contains("loom_storage")
            && !evidence.to_ascii_lowercase().contains("sqlx"),
        "{id} must not use storage internals: {evidence}"
    );
}

fn in_memory_context(scope: &str) -> (BackendContext, common::InMemoryServer) {
    let (server, client) =
        common::InMemoryServer::start().expect("real InMemory service should start");
    let restart_server = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || restart_server.restart());
    let context = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_scope(scope)
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart();
    (context, server)
}

fn postgres_context(scope: &str) -> (BackendContext, common::PgServer) {
    let (server, client) =
        common::PgServer::start().expect("repository-managed PostgreSQL service should start");
    let restart_server = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || restart_server.restart());
    let context = BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_scope(scope)
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart();
    (context, server)
}

fn descriptor(id: &str) -> loom_validator::ScenarioDescriptor {
    world_time::descriptors()
        .into_iter()
        .find(|item| item.id_str() == id)
        .expect("T13 descriptor")
}

#[test]
fn world_time_suite_is_local_and_non_registering() {
    assert_eq!(world_time::SUITE, "world_time");
    assert_eq!(world_time::CV_RANGE, "CV-021..CV-024");
    assert_eq!(world_time::CAPABILITY_AREA, "world-time");
    assert!(world_time::owns_cv("CV-021") && world_time::owns_cv("CV-024"));
    assert!(!world_time::owns_cv("CV-020") && !world_time::owns_cv("CV-025"));
    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-021").is_none() && registry.get("CV-040").is_none());
    assert_eq!(
        world_time::descriptors()
            .iter()
            .map(loom_validator::ScenarioDescriptor::id_str)
            .collect::<Vec<_>>(),
        ["CV-021", "CV-022", "CV-023", "CV-024"]
    );
}

#[test]
fn cv021_explicit_advance_passes_on_real_in_memory() {
    let (context, _server) = in_memory_context("CV-021-inmemory");
    let result = world_time::execute_world_time(&descriptor("CV-021"), &context);
    assert_pass(&result, "CV-021 InMemory");
    assert!(result.finding().actual().contains("T10→T20"));
}

#[test]
fn cv022_due_work_blocks_advance_on_real_in_memory() {
    let (context, _server) = in_memory_context("CV-022-inmemory");
    let result = world_time::execute_world_time(&descriptor("CV-022"), &context);
    assert_pass(&result, "CV-022 InMemory");
    assert!(result.finding().actual().contains("Pending"));
}

#[test]
fn cv023_chronology_reconstructs_after_controlled_in_memory_restart() {
    let (context, _server) = in_memory_context("CV-023-inmemory");
    let result = world_time::execute_world_time(&descriptor("CV-023"), &context);
    assert_pass(&result, "CV-023 InMemory");
    assert!(
        result
            .finding()
            .actual()
            .contains("controlled-boundary-restart")
    );
}

#[test]
fn cv024_reaction_atomicity_passes_after_controlled_in_memory_restart() {
    let (context, _server) = in_memory_context("CV-024-inmemory");
    let result = world_time::execute_world_time(&descriptor("CV-024"), &context);
    assert_pass(&result, "CV-024 InMemory");
}

#[test]
fn cv021_explicit_advance_passes_on_live_postgres() {
    let (context, _server) = postgres_context("CV-021-postgres");
    let result = world_time::execute_world_time(&descriptor("CV-021"), &context);
    assert_pass(&result, "CV-021 PostgreSQL");
}

#[test]
fn cv022_due_work_blocks_advance_on_live_postgres_and_survives_restart() {
    let (context, _server) = postgres_context("CV-022-postgres");
    let result = world_time::execute_world_time(&descriptor("CV-022"), &context);
    assert_pass(&result, "CV-022 PostgreSQL");
    assert!(
        result
            .finding()
            .evidence()
            .iter()
            .any(|item| item.as_str() == "validator:postgres:live")
    );
}

#[test]
fn cv023_chronology_reconstructs_after_live_postgres_restart() {
    let (context, _server) = postgres_context("CV-023-postgres");
    let result = world_time::execute_world_time(&descriptor("CV-023"), &context);
    assert_pass(&result, "CV-023 PostgreSQL");
    assert!(
        result
            .finding()
            .evidence()
            .iter()
            .any(|item| item.as_str() == "validator:CV-023:controlled-boundary-restart")
    );
}

#[test]
fn cv024_reaction_atomicity_passes_on_live_postgres() {
    let (context, _server) = postgres_context("CV-024-postgres");
    let result = world_time::execute_world_time(&descriptor("CV-024"), &context);
    assert_pass(&result, "CV-024 PostgreSQL");
}

#[test]
fn cv021_to_cv024_all_pass_on_real_in_memory_suite() {
    for id in ["CV-021", "CV-022", "CV-023", "CV-024"] {
        // A CV-023 controlled restart returns a new client and makes the old
        // boundary unavailable. Isolating each loop is therefore part of the
        // fixture contract, not a test workaround.
        let (context, _server) = in_memory_context(&format!("aggregate-{id}"));
        let result = world_time::execute_world_time(&descriptor(id), &context);
        assert_pass(&result, &format!("{id} aggregate InMemory"));
    }
}
