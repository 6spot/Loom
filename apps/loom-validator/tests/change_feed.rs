//! Change Feed suite integration tests (T18) — CV-038..CV-040 via formal client.
//!
//! Validates committed change-feed/SSE behavior through formal Loom client surface,
//! including resume/cursor semantics and disconnect recovery, without polling
//! internal event tables. Uses real `InMemory` and `PostgreSQL` service boundaries
//! with controlled restart where durability is required.

mod common;

use std::sync::Arc;

use loom_client::LoomClient;
use loom_validator::{BackendContext, BackendKind, change_feed, validator_registry};

use common::{InMemoryServer, PgServer};

#[test]
fn change_feed_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(change_feed::SUITE, "change_feed");
    assert_eq!(change_feed::CV_RANGE, "CV-038..CV-040");
    assert_eq!(change_feed::CAPABILITY_AREA, "change-feed");
    assert_eq!(change_feed::suite_name(), "change_feed");
    assert!(change_feed::owns_cv("CV-038"));
    assert!(change_feed::owns_cv("CV-039"));
    assert!(change_feed::owns_cv("CV-040"));
    assert!(!change_feed::owns_cv("CV-037"));
    assert!(!change_feed::owns_cv("CV-012"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-038").is_none());
    assert!(registry.get("CV-040").is_none());

    // Local suite registry should contain CV-038..040 without polluting central registry
    let suite_registry = change_feed::change_feed_registry();
    assert_eq!(suite_registry.len(), 3);
    assert!(suite_registry.get("CV-038").is_some());
    assert!(suite_registry.get("CV-040").is_some());
}

fn in_memory_context(scope: &str) -> (BackendContext, InMemoryServer) {
    let (server, client) = InMemoryServer::start().expect("in-memory service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart()
        .with_scope(scope.to_string());
    (ctx, server)
}

fn pg_context(scope: &str) -> (BackendContext, PgServer) {
    let (server, client) = PgServer::start().expect("pg service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart()
        .with_scope(scope.to_string());
    (ctx, server)
}

fn assert_pass(result: &loom_validator::ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass via formal client: {result:?} finding={:?}",
        result.finding()
    );
    // Ensure evidence mentions formal surfaces and not internal storage
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("public-surface:loom-client::SubscriptionService::subscribe"),
        "{id} evidence should contain subscription surface: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::HistoryService::list_events"),
        "{id} evidence should contain history surface: {evidence}"
    );
    assert!(
        !evidence.to_lowercase().contains("loom_storage")
            && !evidence.to_lowercase().contains("pgstorage")
            && !evidence.to_lowercase().contains("sqlx"),
        "{id} must not assert against storage internals: {evidence}"
    );
}

#[test]
fn cv038_passes_on_real_in_memory_via_formal_subscription() {
    let (ctx, _server) = in_memory_context("CV-038-inmemory");
    let descriptor = change_feed::descriptors()
        .into_iter()
        .find(|d| d.id_str() == "CV-038")
        .expect("CV-038 descriptor");
    let result = change_feed::execute(&descriptor, &ctx);
    assert_pass(&result, "CV-038");
}

#[test]
fn cv039_resume_passes_on_real_in_memory() {
    let (ctx, _server) = in_memory_context("CV-039-inmemory");
    let descriptor = change_feed::descriptors()
        .into_iter()
        .find(|d| d.id_str() == "CV-039")
        .expect("CV-039 descriptor");
    let result = change_feed::execute(&descriptor, &ctx);
    assert_pass(&result, "CV-039");
}

#[test]
fn cv040_disconnect_reconnect_preserves_history_on_real_in_memory() {
    let (ctx, _server) = in_memory_context("CV-040-inmemory");
    let descriptor = change_feed::descriptors()
        .into_iter()
        .find(|d| d.id_str() == "CV-040")
        .expect("CV-040 descriptor");
    let result = change_feed::execute(&descriptor, &ctx);
    assert_pass(&result, "CV-040");
}

#[test]
fn cv038_to_cv040_pass_on_live_postgres_with_controlled_restart() {
    for id in ["CV-038", "CV-039", "CV-040"] {
        let (ctx, _server) = pg_context(&format!("pg-{id}"));
        let descriptor = change_feed::descriptors()
            .into_iter()
            .find(|d| d.id_str() == id)
            .unwrap_or_else(|| panic!("missing {id}"));
        let result = change_feed::execute(&descriptor, &ctx);
        assert_pass(&result, id);
        // For CV-039/040, ensure durable evidence when postgres with controlled restart
        if id == "CV-039" || id == "CV-040" {
            let actual = result.finding().actual().to_ascii_lowercase();
            // Should mention restart or durable for PG path
            assert!(
                actual.contains("restart")
                    || actual.contains("durable")
                    || actual.contains("resume"),
                "{id} PG actual should mention restart/durable/resume: {}",
                result.finding().actual()
            );
        }
    }
}

#[test]
fn change_feed_scenarios_use_formal_client_not_event_table_polling() {
    // Negative check: ensure implementation does not contain forbidden internal polling patterns
    // by inspecting that the change_feed module source uses SubscriptionService and not loom_storage
    let source = include_str!("../src/change_feed.rs");
    assert!(
        source.contains("SubscriptionService::subscribe") || source.contains("SubscriptionRequest"),
        "change_feed should use formal SubscriptionService"
    );
    assert!(
        source.contains("ChangeFeedCursor::after"),
        "change_feed should use documented cursor semantics"
    );
    assert!(
        !source.contains("loom_storage")
            && !source.contains("PgStorage")
            && !source.contains("InMemoryStore"),
        "change_feed must not import storage internals for polling"
    );
    assert!(
        !source.contains("validator_registry") || source.contains("change_feed_registry"),
        "change_feed should not mutate central validator_registry"
    );
}
