//! Query/History/Catalog suite integration (T14).
//!
//! Validates CV-025..CV-027 via formal public surfaces only.
//! Uses controlled `InMemory` and `PostgreSQL` harnesses where available.

mod common;
mod query_catalog_causal_fixture;

use std::{collections::HashSet, sync::Arc};

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
    query_catalog_causal_fixture::verify();
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
    query_catalog_causal_fixture::verify_bound_world_without_active_revision();
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
    // The T14-local fixture above creates the bound World while active, then
    // observes that same World with no active revision through public Catalog.
    // Also verify the descriptor records the no-active observation as Pass.
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
    let capability_ids = |catalog: &loom_api::CatalogSnapshot| {
        catalog
            .capabilities
            .iter()
            .map(|capability| capability.id.to_string())
            .collect::<HashSet<_>>()
    };
    let capabilities_a = capability_ids(&catalog_a);
    let capabilities_b = capability_ids(&catalog_b);
    assert_eq!(
        capabilities_a,
        HashSet::from(["neutral.counter".to_owned()]),
        "W_a capability identity set must be exactly counter"
    );
    assert_eq!(
        capabilities_b,
        HashSet::from(["neutral.counter".to_owned(), "neutral.observer".to_owned(),]),
        "W_b capability identity set must be exactly counter plus observer"
    );
    // Ensure world-scoped is subset of global
    for cap in &catalog_a.capabilities {
        assert!(
            global.capability(&cap.id).is_some(),
            "world-scoped cap should be subset of global"
        );
    }
    for cap in &catalog_b.capabilities {
        assert!(
            global.capability(&cap.id).is_some(),
            "world-scoped cap should be subset of global"
        );
    }
}
