//! Semantic Blob + pinned-read suite (T15) executed against real Loom service boundaries.
//!
//! - `InMemory`: `CV-030` passes via real `InMemory`-backed Loom HTTP service.
//! - `PostgreSQL`: `CV-030` passes via real `PostgreSQL`-backed Loom HTTP service
//!   (live, not mocked). `CV-028`/`CV-029` are explicit public-surface gaps and
//!   remain `Unavailable` on every backend; they are never `Pass` and are not
//!   registered into the central `validator_registry`.
//! - Negative: blocked gaps cite gap evidence and never use internal
//!   `loom-storage`/`loom-runtime` tables.

mod common;

use std::sync::Arc;

use loom_client::LoomClient;
use loom_validator::{
    BackendContext, BackendKind, ScenarioDescriptor, ScenarioResult, semantic_blob,
    validator_registry,
};
use uuid::Uuid;

use common::{InMemoryServer, PgServer};

fn descriptor_for(id: &str) -> ScenarioDescriptor {
    if id == "CV-030" {
        semantic_blob::descriptors()
            .into_iter()
            .find(|d| d.id_str() == id)
            .unwrap_or_else(|| panic!("missing semantic_blob descriptor {id}"))
    } else {
        semantic_blob::blocked_descriptors()
            .into_iter()
            .find(|d| d.id_str() == id)
            .unwrap_or_else(|| panic!("missing blocked descriptor {id}"))
    }
}

fn assert_pass(result: &ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass against the real Loom service: {result:?}"
    );
}

fn assert_unavailable(result: &ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_unavailable(),
        "{id} should be unavailable (gap), not pass/fail: {result:?}"
    );
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("gap"),
        "{id} unavailable should cite gap evidence: {evidence}"
    );
    assert!(
        !result.outcome().is_pass(),
        "{id} gap must never be pass: {result:?}"
    );
}

fn unique_scope(prefix: &str) -> String {
    format!("{}-{}-{}", prefix, Uuid::new_v4(), "t15")
}

// ── Scaffold / registry fence ───────────────────────────────────────────────

#[test]
fn semantic_blob_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(semantic_blob::SUITE, "semantic_blob");
    assert_eq!(semantic_blob::CV_RANGE, "CV-028..CV-030");
    assert_eq!(semantic_blob::CAPABILITY_AREA, "semantic-blob");
    assert_eq!(semantic_blob::suite_name(), "semantic_blob");
    assert!(semantic_blob::owns_cv("CV-028"));
    assert!(semantic_blob::owns_cv("CV-029"));
    assert!(semantic_blob::owns_cv("CV-030"));
    assert!(!semantic_blob::owns_cv("CV-027"));
    assert!(!semantic_blob::owns_cv("CV-031"));

    let registry = validator_registry();
    assert_eq!(
        registry.len(),
        11,
        "central registry must stay at 11 until T19"
    );
    assert!(registry.get("CV-028").is_none());
    assert!(registry.get("CV-029").is_none());
    assert!(registry.get("CV-030").is_none());
    assert!(registry.get("CV-040").is_none());

    // Our suite's own descriptors are isolated; only CV-030 is candidate
    let descs = semantic_blob::descriptors();
    assert_eq!(descs.len(), 1);
    assert_eq!(descs[0].id_str(), "CV-030");
    assert!(semantic_blob::owns_cv(descs[0].id_str()));

    let blocked = semantic_blob::blocked_descriptors();
    assert_eq!(blocked.len(), 2);
    assert!(blocked.iter().any(|d| d.id_str() == "CV-028"));
    assert!(blocked.iter().any(|d| d.id_str() == "CV-029"));

    // Registering via suite helper must not affect central registry directly
    let mut isolated = loom_validator::ScenarioRegistry::bootstrap();
    let count = semantic_blob::register(&mut isolated).expect("register should succeed");
    assert_eq!(count, 1);
    assert!(isolated.get("CV-030").is_some());
    assert!(isolated.get("CV-028").is_none());
    assert!(isolated.get("CV-029").is_none());

    // validator_registry must remain 11 (T09 fence)
    let after = validator_registry();
    assert_eq!(after.len(), 11);
}

#[test]
fn semantic_blob_descriptors_are_stable_and_not_centrally_registered() {
    let descs = semantic_blob::descriptors();
    assert_eq!(descs[0].capability_area().as_str(), "semantic-blob");
    assert_eq!(descs[0].id_str(), "CV-030");
    // Blocked descriptors are stable but never centrally registered
    for blocked in semantic_blob::blocked_descriptors() {
        assert!(semantic_blob::owns_cv(blocked.id_str()));
        assert!(validator_registry().get(blocked.id_str()).is_none());
    }
}

// ── CV-030 InMemory ─────────────────────────────────────────────────────────

#[test]
fn cv030_pinned_read_pass_on_real_in_memory() {
    let (server, client) =
        InMemoryServer::start().expect("real InMemory Loom service should start");
    let _keep = server;
    let scope = unique_scope("cv030-inmem");
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_scope(scope.clone());
    let descriptor = descriptor_for("CV-030");
    let result = semantic_blob::execute(&descriptor, &ctx);
    assert_pass(&result, "CV-030");
    // Evidence: must go via public loom-api/loom-client surfaces only
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("public-surface:loom-client::WorldService::create_world_from_template"),
        "CV-030 InMemory evidence should contain WorldService: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::ActionService::invoke"),
        "CV-030 InMemory evidence should contain ActionService: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::QueryService::get_facet"),
        "CV-030 InMemory evidence should contain QueryService: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::HistoryService::list_events"),
        "CV-030 InMemory evidence should contain HistoryService: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::TimelineService::fork#at_version"),
        "CV-030 InMemory evidence should contain fork at_version: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::TimelineService::inspect_timeline"),
        "CV-030 InMemory evidence should contain inspect_timeline: {evidence}"
    );
    // Must not assert projection/blob is authority and must not touch storage internals
    assert!(
        !evidence.to_lowercase().contains("loom_storage")
            && !evidence.to_lowercase().contains("pgstorage")
            && !evidence.to_lowercase().contains("sqlx")
            && !evidence.to_lowercase().contains("semantic_projection")
            && !evidence.to_lowercase().contains("blobstore"),
        "CV-030 must not assert via internal storage/projection/blob internals: {evidence}"
    );
    // Actual should mention pinned stability, ancestry, version
    assert!(
        result.finding().actual().contains("pinned")
            || result.finding().actual().contains("pinned_version"),
        "CV-030 actual should describe pinned stability: {}",
        result.finding().actual()
    );
    assert!(
        result.finding().actual().contains("fork_parent_version")
            || result.finding().actual().contains("ancestry"),
        "CV-030 actual should describe ancestry: {}",
        result.finding().actual()
    );
    // Must not claim projection is authority
    assert!(
        !result
            .finding()
            .expected()
            .to_lowercase()
            .contains("projection is world authority")
            && !result
                .finding()
                .actual()
                .to_lowercase()
                .contains("projection is world authority"),
        "CV-030 must not assert projection is World authority"
    );
    // Verify scope uniqueness propagated to finding
    assert!(
        result.finding().actual().contains(&scope) || result.finding().actual().contains("scope="),
        "CV-030 finding should contain scope for uniqueness"
    );
}

// ── CV-030 PostgreSQL live ──────────────────────────────────────────────────

#[test]
fn cv030_pinned_read_pass_on_live_postgres() {
    let (server, client) = PgServer::start().expect("real PostgreSQL Loom service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let _keep = server;
    let scope = unique_scope("cv030-pg");
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart()
        .with_scope(scope.clone());
    let descriptor = descriptor_for("CV-030");
    let result = semantic_blob::execute(&descriptor, &ctx);
    assert_pass(&result, "CV-030");
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("public-surface:loom-client::TimelineService::fork#at_version"),
        "CV-030 PG evidence should contain fork at_version: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::TimelineService::inspect_timeline"),
        "CV-030 PG evidence should contain inspect_timeline: {evidence}"
    );
    assert!(
        evidence.contains("public-surface:loom-client::QueryService::get_facet"),
        "CV-030 PG evidence should contain get_facet: {evidence}"
    );
    assert!(
        evidence.contains("validator:restart:controlled-boundary-restart"),
        "CV-030 PG evidence should contain controlled restart: {evidence}"
    );
    assert!(
        !evidence.to_lowercase().contains("loom_storage")
            && !evidence.to_lowercase().contains("sqlx"),
        "CV-030 PG must not use internal storage: {evidence}"
    );
    assert!(
        result.finding().backend().as_str() == "postgresql",
        "CV-030 PG finding should report postgresql backend: {}",
        result.finding().backend().as_str()
    );
    // T08 requires PG live; ensure finding reflects controlled PostgreSQL evidence, not external
    assert!(
        result.finding().backend().as_str() == "postgresql",
        "CV-030 PG should be postgresql evidence"
    );
}

// ── Blocked gaps ─────────────────────────────────────────────────────────────

#[test]
fn cv028_and_cv029_are_blocked_gaps_on_in_memory_and_pg() {
    let (im_server, im_client) = InMemoryServer::start().expect("InMemory service should start");
    let _keep_im = im_server;
    for id in ["CV-028", "CV-029"] {
        let scope = unique_scope(&format!("blocked-{id}-inmem"));
        let ctx = BackendContext::new(im_client.clone())
            .with_backend_kind(BackendKind::InMemory)
            .with_scope(scope);
        let descriptor = descriptor_for(id);
        let result = semantic_blob::execute(&descriptor, &ctx);
        assert_unavailable(&result, id);
        // Ensure not pass and cites correct gap
        let evidence = result
            .finding()
            .evidence()
            .iter()
            .map(loom_validator::EvidenceReference::as_str)
            .collect::<Vec<_>>()
            .join(",");
        if id == "CV-028" {
            assert!(
                evidence.contains("CV-028") && evidence.to_lowercase().contains("semantic"),
                "CV-028 evidence should cite semantic gap: {evidence}"
            );
        } else {
            assert!(
                evidence.contains("CV-029") && evidence.to_lowercase().contains("blob"),
                "CV-029 evidence should cite blob gap: {evidence}"
            );
        }
        assert!(!result.outcome().is_pass(), "{id} must never be Pass");
    }

    let (pg_server, pg_client) = PgServer::start().expect("PG service should start");
    let _keep_pg = pg_server;
    for id in ["CV-028", "CV-029"] {
        let scope = unique_scope(&format!("blocked-{id}-pg"));
        let ctx = BackendContext::new(pg_client.clone())
            .with_backend_kind(BackendKind::PostgreSQL)
            .with_scope(scope);
        let descriptor = descriptor_for(id);
        let result = semantic_blob::execute(&descriptor, &ctx);
        assert_unavailable(&result, id);
        assert!(
            !result.outcome().is_pass(),
            "{id} PG gap must never be Pass"
        );
    }
}

#[test]
fn cv028_cv029_do_not_enlarge_central_registry_even_when_executed() {
    // Executing blocked scenarios must not have side effect of registering them
    let (server, client) = InMemoryServer::start().expect("InMemory should start");
    let _keep = server;
    for id in ["CV-028", "CV-029"] {
        let descriptor = descriptor_for(id);
        let ctx = BackendContext::new(client.clone())
            .with_backend_kind(BackendKind::InMemory)
            .with_scope(unique_scope(&format!("registry-fence-{id}")));
        let _ = semantic_blob::execute(&descriptor, &ctx);
    }
    let registry = validator_registry();
    assert_eq!(registry.len(), 11);
    assert!(registry.get("CV-028").is_none());
    assert!(registry.get("CV-029").is_none());
    assert!(
        registry.get("CV-030").is_none(),
        "central registry still 11 until T19"
    );
}

// ── T09 fence: no lib registry edit via suite ───────────────────────────────

#[test]
fn semantic_blob_register_fence_preserves_only_cv030() {
    let mut isolated = loom_validator::ScenarioRegistry::bootstrap();
    let before = validator_registry().len();
    assert_eq!(before, 11);
    semantic_blob::register(&mut isolated).expect("register");
    assert_eq!(isolated.len(), 1);
    assert!(isolated.get("CV-030").is_some());
    assert!(isolated.get("CV-028").is_none());
    assert!(isolated.get("CV-029").is_none());
    // Ensure central remains untouched
    assert_eq!(validator_registry().len(), 11);
}
