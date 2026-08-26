//! Query/History/Catalog suite integration (T14).
//!
//! Validates CV-025..CV-027 via formal public surfaces only.
//! Uses controlled InMemory and PostgreSQL harnesses where available.

mod common;

use std::sync::Arc;

use loom_api::{CatalogService, WorldService};
use loom_client::LoomClient;
use loom_validator::{
    BackendContext, BackendKind, ScenarioResult, query_catalog, validator_registry,
};

use common::{InMemoryServer, PgServer};

fn assert_pass(result: &ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass on real service: outcome={:?} finding={}",
        result.outcome(),
        result.finding().render()
    );
}

fn in_memory_context(scope: &str) -> (BackendContext, InMemoryServer) {
    let (server, client) = InMemoryServer::start().expect("in-memory service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_scope(scope.to_string())
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart();
    (ctx, server)
}

fn pg_context(scope: &str) -> Option<(BackendContext, PgServer)> {
    let (server, client) = match PgServer::start() {
        Ok(v) => v,
        Err(e) => {
            eprintln!("postgres not available for {scope}: {e} (prerequisite)");
            return None;
        }
    };
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_scope(scope.to_string())
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart();
    Some((ctx, server))
}

#[test]
fn query_catalog_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(query_catalog::SUITE, "query_catalog");
    assert_eq!(query_catalog::CV_RANGE, "CV-025..CV-027");
    assert_eq!(query_catalog::CAPABILITY_AREA, "query-catalog");
    assert_eq!(query_catalog::suite_name(), "query_catalog");
    assert!(query_catalog::owns_cv("CV-025"));
    assert!(query_catalog::owns_cv("CV-027"));
    assert!(!query_catalog::owns_cv("CV-024"));
    assert!(!query_catalog::owns_cv("CV-028"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-025").is_none());
    assert!(registry.get("CV-040").is_none());

    // Local descriptors must be exactly 3 and disjoint
    let local = query_catalog::descriptors();
    assert_eq!(local.len(), 3);
    let ids: Vec<_> = local.iter().map(|d| d.id_str().to_string()).collect();
    assert_eq!(ids, vec!["CV-025", "CV-026", "CV-027"]);
}

#[test]
fn cv025_history_trajectory_isolation_on_in_memory() {
    let descriptors = query_catalog::descriptors();
    let d = descriptors
        .iter()
        .find(|d| d.id_str() == "CV-025")
        .expect("CV-025");
    let (ctx, _server) = in_memory_context("CV-025");
    let result = query_catalog::execute_query_catalog(d, &ctx);
    assert_pass(&result, "CV-025 InMemory");
}

#[test]
fn cv026_causal_query_isolation_on_in_memory() {
    let descriptors = query_catalog::descriptors();
    let d = descriptors
        .iter()
        .find(|d| d.id_str() == "CV-026")
        .expect("CV-026");
    let (ctx, _server) = in_memory_context("CV-026");
    let result = query_catalog::execute_query_catalog(d, &ctx);
    assert_pass(&result, "CV-026 InMemory");
}

#[test]
fn cv027_world_scoped_catalog_positive_on_in_memory() {
    let descriptors = query_catalog::descriptors();
    let d = descriptors
        .iter()
        .find(|d| d.id_str() == "CV-027")
        .expect("CV-027");
    let (ctx, _server) = in_memory_context("CV-027-positive");
    let result = query_catalog::execute_query_catalog(d, &ctx);
    assert_pass(&result, "CV-027 positive InMemory");
}

#[test]
fn cv027_no_active_revision_is_not_permissive() {
    // Negative case: harness with registered software but no active revision
    let (server, client) =
        InMemoryServer::start_without_active_revision().expect("no-active service should start");
    // Global catalog must still be available (installed), world-scoped must not fallback
    let global = client
        .catalog()
        .expect("global catalog should be available even without active revision");
    assert!(
        global
            .capabilities
            .iter()
            .any(|c| c.id.to_string() == "neutral.counter"),
        "global catalog should contain neutral.counter"
    );
    // World creation without active revision must be unavailable (CV-011 pattern)
    let world_attempt = {
        let rt = common::leaked_runtime();
        rt.block_on(async {
            client
                .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
                    loom_api::WorldTemplateDescriptor::new(
                        "validator.t14.cv027.negative",
                        1,
                        loom_api::WorldInstant::new(10),
                    )
                    .requires_capability("neutral.counter", "^0.1.0"),
                ))
                .await
        })
    };
    assert!(
        matches!(&world_attempt, Err(e) if e.code == loom_api::ApiErrorCode::Unavailable),
        "world creation without active revision should be Unavailable, got {world_attempt:?}"
    );

    // World-scoped catalog for a random WorldId must be Unavailable/NotFound, not a permissive fallback to global
    let dummy_world = loom_api::WorldId::new(uuid::Uuid::new_v4());
    let rt = common::leaked_runtime();
    let scoped = rt.block_on(async { client.catalog_for_world(dummy_world).await });
    match scoped {
        Ok(catalog) => {
            // If it succeeded (should not for no-active), ensure it is not permissive global fallback
            assert_ne!(
                catalog.capabilities.len(),
                global.capabilities.len(),
                "world-scoped catalog without active revision must not silently equal global catalog"
            );
            panic!(
                "world-scoped catalog without active revision should be Unavailable/NotFound, but succeeded with {} caps",
                catalog.capabilities.len()
            );
        }
        Err(e) => {
            assert!(
                matches!(
                    e.code,
                    loom_api::ApiErrorCode::Unavailable | loom_api::ApiErrorCode::NotFound
                ),
                "world-scoped catalog without active revision should be Unavailable or NotFound, got {:?} - {}",
                e.code,
                e.message
            );
        }
    };

    // Also verify the descriptor execution correctly observes the negative case as Pass
    let descriptors = query_catalog::descriptors();
    let d = descriptors
        .iter()
        .find(|d| d.id_str() == "CV-027")
        .expect("CV-027");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_scope("CV-027-negative")
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart();
    let result = query_catalog::execute_query_catalog(d, &ctx);
    assert_pass(&result, "CV-027 negative InMemory (no active)");
}

#[test]
fn cv025_to_cv027_postgres_when_available() {
    // Controlled PostgreSQL path: requires live endpoint.
    // If unavailable, test is prerequisite (not failed).
    let descriptors = query_catalog::descriptors();
    for id in ["CV-025", "CV-026", "CV-027"] {
        let d = descriptors.iter().find(|d| d.id_str() == id).expect(id);
        let Some((ctx, _server)) = pg_context(id) else {
            // Prerequisite missing is not a failure; we emit a skipped outcome via descriptor execution
            // Instead, we run the descriptor with a Postgres kind but missing URL to verify prerequisite handling
            // We use BackendHarness to simulate missing PG and check that result is not Pass
            let harness = loom_validator::BackendHarness::connect(
                BackendKind::PostgreSQL,
                "http://127.0.0.1:8080",
            )
            .expect("harness");
            // Ensure harness start reports prerequisite when env missing
            if std::env::var(loom_validator::LOOM_TEST_POSTGRES_URL).is_err() {
                let start = harness.start(id);
                assert!(
                    matches!(start, loom_validator::BackendStart::Prerequisite { .. }),
                    "postgres prerequisite should be reported when URL missing"
                );
            }
            continue;
        };
        let result = query_catalog::execute_query_catalog(d, &ctx);
        // For postgres backend, result may be Pass or Unavailable (if live not reachable); but must not be Fail due to logic
        // We assert it is not Fail; Pass is expected when PG live.
        assert!(
            !result.outcome().is_fail(),
            "{id} on postgres should not fail: {result:?}"
        );
        if result.outcome().is_pass() {
            // ok
        } else {
            eprintln!("{id} postgres prerequisite/unavailable (not fail): {result:?}");
        }
    }
}

#[test]
fn catalog_authority_does_not_use_global_fallback_on_controlled_in_memory() {
    // Direct formal-surface check via LoomClient without BackendContext
    let (server, client) = InMemoryServer::start().expect("in-memory");
    let _guard = server;
    let rt = common::leaked_runtime();
    let (global, w_a, w_b) = rt.block_on(async {
        let global = client.catalog().expect("global catalog");
        let w_a = client
            .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
                loom_api::WorldTemplateDescriptor::new(
                    "validator.t14.direct.a",
                    1,
                    loom_api::WorldInstant::new(1),
                )
                .requires_capability("neutral.counter", "^0.1.0"),
            ))
            .await
            .expect("W_a")
            .target
            .world_id;
        let w_b = client
            .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
                loom_api::WorldTemplateDescriptor::new(
                    "validator.t14.direct.b",
                    1,
                    loom_api::WorldInstant::new(1),
                )
                .requires_capability("neutral.counter", "^0.1.0")
                .requires_capability("neutral.observer", "^0.1.0"),
            ))
            .await
            .expect("W_b")
            .target
            .world_id;
        (global, w_a, w_b)
    });
    let rt = common::leaked_runtime();
    let (catalog_a, catalog_b) = rt.block_on(async {
        (
            client.catalog_for_world(w_a).await.expect("catalog A"),
            client.catalog_for_world(w_b).await.expect("catalog B"),
        )
    });
    assert!(
        catalog_a
            .capabilities
            .iter()
            .any(|c| c.id.to_string() == "neutral.counter")
    );
    assert!(
        !catalog_a
            .capabilities
            .iter()
            .any(|c| c.id.to_string() == "neutral.observer"),
        "W_a with counter-only binding must not expose observer"
    );
    assert!(
        catalog_b
            .capabilities
            .iter()
            .any(|c| c.id.to_string() == "neutral.observer"),
        "W_b with counter+observer must expose observer"
    );
    assert_ne!(
        catalog_a.capabilities.len(),
        catalog_b.capabilities.len(),
        "different bindings must yield different world-scoped catalogs"
    );
    // Ensure world-scoped is subset of global
    for cap in &catalog_a.capabilities {
        assert!(
            global.capability(&cap.id).is_some(),
            "world-scoped cap should be subset of global"
        );
    }
}
