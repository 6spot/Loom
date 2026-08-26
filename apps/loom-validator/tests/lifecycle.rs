//! VAL-T8 lifecycle scenarios executed live against real Loom service
//! boundaries.
//!
//! - `InMemory`: CV-001..CV-003 pass against a real `InMemory`-backed Loom HTTP
//!   service; CV-003 restart terminates and rebuilds the application boundary
//!   (preserving the store) and reconnects with a new public client.
//! - `PostgreSQL`: CV-001..CV-004 pass against a real `PostgreSQL`-backed Loom
//!   HTTP service (the `loom-server` backend composition). An explicit
//!   `LOOM_TEST_POSTGRES_URL` may override the repository-local database; when
//!   unset, the repository-managed `PostgreSQL` service is started on demand.
//! - Negative endpoint: `LOOM_VALIDATOR_BASE_URL=http://127.0.0.1:1` never
//!   yields a pass.

mod common;

use std::sync::Arc;

use loom_client::LoomClient;
use loom_validator::{BackendContext, BackendKind, ScenarioRegistry, ScenarioResult};

use common::{InMemoryServer, PgServer};

fn registry() -> ScenarioRegistry {
    let mut registry = ScenarioRegistry::bootstrap();
    loom_validator::register_lifecycle(&mut registry).expect("lifecycle registration");
    registry
}

fn assert_pass(result: &ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass on the real service: {result:?}"
    );
}

fn in_memory_context() -> (BackendContext, InMemoryServer) {
    let (server, client) = InMemoryServer::start().expect("in-memory service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart();
    (ctx, server)
}

fn pg_context() -> (BackendContext, PgServer) {
    let (server, client) = PgServer::start().expect("pg service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart();
    (ctx, server)
}

#[test]
fn cv001_to_cv003_pass_on_real_in_memory() {
    let registry = registry();
    for id in ["CV-001", "CV-002", "CV-003"] {
        let descriptor = registry.get(id).expect("descriptor");
        let (ctx, _server) = in_memory_context();
        let result = loom_validator::execute_lifecycle(descriptor, &ctx);
        assert_pass(&result, id);
    }
}

#[test]
fn cv001_to_cv004_pass_on_live_postgres() {
    let registry = registry();
    for id in ["CV-001", "CV-002", "CV-003", "CV-004"] {
        let descriptor = registry.get(id).expect("descriptor");
        let (ctx, _server) = pg_context();
        let result = loom_validator::execute_lifecycle(descriptor, &ctx);
        assert_pass(&result, id);
    }
}

#[test]
fn negative_endpoint_is_not_pass() {
    let harness =
        loom_validator::BackendHarness::connect(BackendKind::InMemory, "http://127.0.0.1:1")
            .expect("harness");
    let start = harness.start("CV-001");
    assert!(
        matches!(start, loom_validator::BackendStart::Unavailable { .. }),
        "negative endpoint must be unavailable, not pass: {start:?}"
    );
}
