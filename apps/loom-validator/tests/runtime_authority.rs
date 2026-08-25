//! Public-surface negative coverage for the V0 Runtime Binding/Revision model.

mod common;

use loom_validator::{BackendContext, BackendKind, ScenarioRegistry, ScenarioResult};

fn registry() -> ScenarioRegistry {
    let mut registry = ScenarioRegistry::bootstrap();
    loom_validator::register_runtime_authority(&mut registry)
        .expect("runtime-authority registration");
    registry
}

fn assert_pass(result: &ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass against the real negative fixture: {result:?}"
    );
}

#[test]
fn cv010_rejects_partial_binding_without_rewriting_it() {
    let (server, client, target) =
        common::InMemoryServer::start_partial_binding().expect("partial fixture should start");
    let context = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_scope(serde_json::to_string(&target).expect("target should serialize"));
    let scenarios = registry();
    let descriptor = scenarios.get("CV-010").expect("CV-010 descriptor");

    let result = loom_validator::execute_runtime_authority(descriptor, &context);
    assert_pass(&result, "CV-010");
    drop(server);
}

#[test]
fn cv011_rejects_missing_active_revision() {
    let (server, client) = common::InMemoryServer::start_without_active_revision()
        .expect("no-active-revision fixture should start");
    let context = BackendContext::new(client).with_backend_kind(BackendKind::InMemory);
    let scenarios = registry();
    let descriptor = scenarios.get("CV-011").expect("CV-011 descriptor");

    let result = loom_validator::execute_runtime_authority(descriptor, &context);
    assert_pass(&result, "CV-011");
    drop(server);
}
