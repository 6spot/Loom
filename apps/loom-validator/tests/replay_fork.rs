//! VAL-T9 replay/fork scenarios executed against real Loom service boundaries.
//!
//! These tests intentionally remain separate from the unit scenarios in
//! `src/scenarios.rs`.  The unit layer may use the Validator-owned `MockApi` to
//! exercise orchestration deterministically; this layer composes Loom itself,
//! connects through its HTTP boundary, and passes the production
//! `LoomClient`-backed `BackendContext` to the same scenario implementation.

mod common;

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
