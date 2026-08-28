//! Semantic Blob + pinned-read suite (T15) executed against real Loom service boundaries.
//!
//! - `CV-028`: a test-only Runtime-owned projection fixture drives
//!   register/query/rebuild/delete while public History/Facet/Timeline reads
//!   prove that the derived materialization can be rebuilt without changing
//!   World Truth.
//! - `CV-029`: a concrete `BlobStore` fixture produces a `BlobRef`, then exercises
//!   typed missing/corrupt reads while public Facet/History reads remain stable.
//! - `CV-030`: pinned reads pass via real `InMemory` and `PostgreSQL` HTTP services.
//!
//! Internal derived results are auxiliary only; no SQL/table read is an
//! acceptance assertion.

mod common;

use std::sync::Arc;

use loom_api::{
    ActionInvocation, ActionRequest, ActionService, ActionTypeId, CreateWorldFromTemplateRequest,
    EventQuery, FacetOwner, FacetQuery, FacetTypeId, HistoryService, QueryService, TimelineService,
    WorldInstant, WorldService, WorldTemplateDescriptor,
};
use loom_capability::{SemanticIndexId, SemanticIndexMetric, SemanticIndexSource};
use loom_client::LoomClient;
use loom_core::SchemaRevision;
use loom_runtime::{
    BlobError, BlobStore, PlatformTime, Runtime, RuntimeRevisionCapability,
    RuntimeRevisionDescriptor, RuntimeRevisionId, RuntimeRevisionStore, SemanticProjectionKey,
    SemanticProjectionQuery, SemanticProjectionRebuild, SemanticProjectionRegistration,
    SemanticProjectionRow,
};
use loom_storage::{InMemoryBlobStore, InMemoryStore, PgStorage};
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

fn validator_revision(registry: &loom_capability::CapabilityRegistry) -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("validator-t15-explicit-v0"),
        PlatformTime::default(),
        "validator-t15-test-build",
        registry.loom_version().clone(),
        registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("validator-t15:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("T15 validator revision should be valid")
}

fn start_t15_in_memory_runtime() -> (
    Arc<Runtime<&'static InMemoryStore>>,
    LoomClient,
    tokio::task::JoinHandle<()>,
    InMemoryBlobStore,
) {
    use loom_boundary::{BoundaryConfig, RequireAdminAuthorization, router_with_admin};
    use loom_neutral::registry as neutral_registry;

    let store: &'static InMemoryStore = Box::leak(Box::new(InMemoryStore::new()));
    let registry = neutral_registry();
    registry
        .validate()
        .expect("neutral registry should validate");
    let revision = validator_revision(&registry);
    store
        .confirm_revision(revision.clone())
        .expect("T15 InMemory revision should confirm");
    let active = store
        .read_active_revision()
        .expect("T15 InMemory active revision should read");
    if active
        .as_ref()
        .is_none_or(|selection| selection.revision().id() != revision.id())
    {
        store
            .activate_revision(
                revision.id().clone(),
                active
                    .as_ref()
                    .map(loom_runtime::RuntimeRevisionSelection::generation),
                PlatformTime::default(),
            )
            .expect("T15 InMemory revision should activate");
    }

    let runtime = Arc::new(Runtime::new(store, neutral_registry()).expect("T15 Runtime"));
    let router = router_with_admin(
        runtime.clone(),
        Arc::new(RequireAdminAuthorization),
        BoundaryConfig::default(),
    );
    let (client, server) = common::leaked_runtime().block_on(async {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("T15 InMemory listener");
        let address = listener.local_addr().expect("T15 InMemory address");
        let server = tokio::spawn(async move {
            axum::serve(listener, router)
                .await
                .expect("T15 InMemory server");
        });
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        let client = LoomClient::builder(format!("http://{address}"))
            .admin_token("validator-test-admin")
            .expect("T15 client builder")
            .build()
            .expect("T15 client");
        (client, server)
    });
    (runtime, client, server, InMemoryBlobStore::new())
}

fn start_t15_postgres_runtime() -> (
    Arc<Runtime<PgStorage>>,
    LoomClient,
    tokio::task::JoinHandle<()>,
    InMemoryBlobStore,
    common::PgServer,
) {
    use loom_boundary::{BoundaryConfig, RequireAdminAuthorization, router_with_admin};
    use loom_neutral::registry as neutral_registry;

    // PgServer owns the repository-managed PostgreSQL 18 startup contract.
    // The T15 Runtime below is a second public boundary over the same control
    // database, with unique World IDs and no direct SQL assertions.
    let (bootstrap, _) = PgServer::start().expect("T15 PostgreSQL service should start");
    let url = std::env::var("LOOM_TEST_POSTGRES_URL")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "postgresql://loom:loom@127.0.0.1:15432/loom_control".to_owned());
    let store = common::leaked_runtime().block_on(async {
        let store = PgStorage::connect(&url)
            .await
            .expect("T15 PostgreSQL storage should connect");
        store.health().await.expect("T15 PostgreSQL health");
        store.migrate().await.expect("T15 PostgreSQL migrations");
        let registry = neutral_registry();
        registry
            .validate()
            .expect("neutral registry should validate");
        let revision = validator_revision(&registry);
        RuntimeRevisionStore::confirm_revision(&store, revision.clone())
            .await
            .expect("T15 PostgreSQL revision should confirm");
        let active = RuntimeRevisionStore::read_active_revision(&store)
            .await
            .expect("T15 PostgreSQL active revision should read");
        if active
            .as_ref()
            .is_none_or(|selection| selection.revision().id() != revision.id())
        {
            RuntimeRevisionStore::activate_revision(
                &store,
                revision.id().clone(),
                active
                    .as_ref()
                    .map(loom_runtime::RuntimeRevisionSelection::generation),
                PlatformTime::default(),
            )
            .await
            .expect("T15 PostgreSQL revision should activate");
        }
        store
    });
    let runtime = Arc::new(Runtime::new(store, neutral_registry()).expect("T15 Runtime"));
    let router = router_with_admin(
        runtime.clone(),
        Arc::new(RequireAdminAuthorization),
        BoundaryConfig::default(),
    );
    let (client, server) = common::leaked_runtime().block_on(async {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("T15 PostgreSQL listener");
        let address = listener.local_addr().expect("T15 PostgreSQL address");
        let server = tokio::spawn(async move {
            axum::serve(listener, router)
                .await
                .expect("T15 PostgreSQL server");
        });
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        let client = LoomClient::builder(format!("http://{address}"))
            .admin_token("validator-test-admin")
            .expect("T15 client builder")
            .build()
            .expect("T15 client");
        (client, server)
    });
    (runtime, client, server, InMemoryBlobStore::new(), bootstrap)
}

macro_rules! run_cv028_projection_case {
    ($runtime:expr, $client:expr) => {{
        let runtime = $runtime;
        let client = $client;
        common::leaked_runtime().block_on(async move {
            let target = client
                .create_world_from_template(CreateWorldFromTemplateRequest::new(
                    WorldTemplateDescriptor::new(
                        format!("validator.t15.cv028.{}", Uuid::new_v4()),
                        1,
                        WorldInstant::new(42),
                    )
                    .requires_capability("neutral.counter", "^0.1.0"),
                ))
                .await
                .expect("CV-028 world creation")
                .target;
            let entity_id = loom_api::EntityId::new(Uuid::new_v4());
            let event_id = loom_api::EventId::new(Uuid::new_v4());
            let seed = client
                .invoke(ActionRequest::new(
                    target,
                    ActionInvocation::new(
                        ActionTypeId::from("neutral.counter.seed"),
                        serde_json::json!({
                            "event_id": event_id.to_string(),
                            "entity_id": entity_id.to_string(),
                            "value": 3,
                        }),
                    ),
                ))
                .await
                .expect("CV-028 seed action");
            assert!(
                matches!(seed, loom_api::ExecutionResult::Committed { .. }),
                "CV-028 seed should commit: {seed:?}"
            );

            // These are the only authority observations: all projection
            // operations below are test-only driver activity.
            let history_before = client
                .list_events(EventQuery::all(target))
                .await
                .expect("CV-028 history before projection");
            let facet_before = client
                .get_facet(FacetQuery::new(
                    target,
                    FacetOwner::entity(entity_id),
                    FacetTypeId::from("neutral.counter.value"),
                ))
                .await
                .expect("CV-028 facet before projection");
            let timeline_before = client
                .inspect_timeline(target)
                .await
                .expect("CV-028 timeline before projection");
            assert_eq!(history_before.len(), 1);
            assert_eq!(
                facet_before
                    .as_ref()
                    .and_then(|facet| facet.value.get("value"))
                    .and_then(serde_json::Value::as_i64),
                Some(3)
            );

            let registration = SemanticProjectionRegistration::new(
                SemanticProjectionKey::new(
                    target.world_id,
                    target.timeline_id,
                    SemanticIndexId::new("neutral.counter.semantic"),
                ),
                SemanticIndexSource::new(
                    "facet",
                    "neutral.counter.value",
                    SchemaRevision::new(1),
                ),
                SchemaRevision::new(1),
                1,
                "neutral-model-1",
                2,
                SemanticIndexMetric::Cosine,
            )
            .expect("CV-028 projection registration");
            runtime
                .register_semantic_projection(registration.clone())
                .await
                .expect("CV-028 Runtime projection registration");
            let rebuild = SemanticProjectionRebuild::new(
                registration.clone(),
                Some(1),
                vec![
                    SemanticProjectionRow::new(
                        history_before[0].event_ref(),
                        "cv028-counter-seed",
                        timeline_before.version,
                        1,
                        "neutral-model-1",
                        vec![3.0, 0.0],
                    )
                    .expect("CV-028 projection row"),
                ],
            )
            .expect("CV-028 rebuild request");
            runtime
                .rebuild_semantic_projection(&rebuild)
                .await
                .expect("CV-028 projection rebuild");
            let query = SemanticProjectionQuery::new(
                registration.key.clone(),
                SchemaRevision::new(1),
                1,
                "neutral-model-1",
                vec![3.0, 0.0],
                1,
            )
            .expect("CV-028 projection query");
            let first_hits = runtime
                .query_semantic_projection(query.clone())
                .await
                .expect("CV-028 projection query after rebuild");
            assert_eq!(first_hits.len(), 1);
            assert_eq!(first_hits[0].source_ref, history_before[0].event_ref());

            runtime
                .delete_semantic_projection(registration.key.clone())
                .await
                .expect("CV-028 projection delete");
            let history_after_delete = client
                .list_events(EventQuery::all(target))
                .await
                .expect("CV-028 history after projection delete");
            let facet_after_delete = client
                .get_facet(FacetQuery::new(
                    target,
                    FacetOwner::entity(entity_id),
                    FacetTypeId::from("neutral.counter.value"),
                ))
                .await
                .expect("CV-028 facet after projection delete");
            let timeline_after_delete = client
                .inspect_timeline(target)
                .await
                .expect("CV-028 timeline after projection delete");
            assert_eq!(history_after_delete, history_before);
            assert_eq!(facet_after_delete, facet_before);
            assert_eq!(timeline_after_delete.version, timeline_before.version);
            assert_eq!(timeline_after_delete.world_time, timeline_before.world_time);

            // Re-register/rebuild the derived rows, then repeat the public
            // authority reads. The hit is auxiliary evidence only.
            runtime
                .register_semantic_projection(registration.clone())
                .await
                .expect("CV-028 projection re-registration");
            runtime
                .rebuild_semantic_projection(&rebuild)
                .await
                .expect("CV-028 projection rebuild after delete");
            let second_hits = runtime
                .query_semantic_projection(query)
                .await
                .expect("CV-028 projection query after rebuild");
            assert_eq!(second_hits.len(), 1);
            assert_eq!(second_hits[0].source_ref, history_before[0].event_ref());
            assert_eq!(
                client
                    .list_events(EventQuery::all(target))
                    .await
                    .expect("CV-028 final public history"),
                history_before
            );
            assert_eq!(
                client
                    .get_facet(FacetQuery::new(
                        target,
                        FacetOwner::entity(entity_id),
                        FacetTypeId::from("neutral.counter.value"),
                    ))
                    .await
                    .expect("CV-028 final public facet"),
                facet_before
            );
            let timeline_after_rebuild = client
                .inspect_timeline(target)
                .await
                .expect("CV-028 final public timeline");
            assert_eq!(timeline_after_rebuild.version, timeline_before.version);
            assert_eq!(timeline_after_rebuild.world_time, timeline_before.world_time);
        });
    }};
}

macro_rules! run_cv029_blob_case {
    ($runtime:expr, $client:expr, $blobs:expr) => {{
        let _runtime = $runtime;
        let client = $client;
        let blobs = $blobs;
        common::leaked_runtime().block_on(async move {
            let target = client
                .create_world_from_template(CreateWorldFromTemplateRequest::new(
                    WorldTemplateDescriptor::new(
                        format!("validator.t15.cv029.{}", Uuid::new_v4()),
                        1,
                        WorldInstant::new(42),
                    )
                    .requires_capability("neutral.counter", "^0.1.0"),
                ))
                .await
                .expect("CV-029 world creation")
                .target;
            let entity_id = loom_api::EntityId::new(Uuid::new_v4());
            let seed_event_id = loom_api::EventId::new(Uuid::new_v4());
            client
                .invoke(ActionRequest::new(
                    target,
                    ActionInvocation::new(
                        ActionTypeId::from("neutral.counter.seed"),
                        serde_json::json!({
                            "event_id": seed_event_id.to_string(),
                            "entity_id": entity_id.to_string(),
                            "value": 1,
                        }),
                    ),
                ))
                .await
                .expect("CV-029 seed action");

            let reference = blobs
                .put(b"cv029 immutable body", Some("text/plain"))
                .await
                .expect("CV-029 BlobRef creation");
            assert!(reference.is_consistent());
            assert_eq!(
                blobs
                    .read(&reference)
                    .await
                    .expect("CV-029 blob read before fault")
                    .bytes(),
                b"cv029 immutable body"
            );
            let attach_event_id = loom_api::EventId::new(Uuid::new_v4());
            client
                .invoke(ActionRequest::new(
                    target,
                    ActionInvocation::new(
                        ActionTypeId::from("neutral.blob.attach"),
                        serde_json::json!({
                            "event_id": attach_event_id.to_string(),
                            "entity_id": entity_id.to_string(),
                            "hash": reference.id.to_string(),
                            "media_type": "text/plain",
                        }),
                    ),
                ))
                .await
                .expect("CV-029 blob attach action");

            // Facet and History are the authority observations surrounding
            // adapter-only missing/corrupt reads.
            let history_before = client
                .list_events(EventQuery::all(target))
                .await
                .expect("CV-029 history before blob fault");
            let facet_before = client
                .get_facet(FacetQuery::new(
                    target,
                    FacetOwner::entity(entity_id),
                    FacetTypeId::from("neutral.blob.reference"),
                ))
                .await
                .expect("CV-029 blob facet before fault")
                .expect("CV-029 blob facet should exist");
            assert_eq!(
                facet_before.value.get("hash").and_then(serde_json::Value::as_str),
                Some(reference.id.to_string().as_str())
            );

            blobs
                .delete(&reference)
                .expect("CV-029 blob delete fault injection");
            assert!(matches!(
                blobs.read(&reference).await,
                Err(BlobError::NotFound { .. })
            ));
            assert_eq!(
                client
                    .list_events(EventQuery::all(target))
                    .await
                    .expect("CV-029 history after missing blob"),
                history_before
            );
            assert_eq!(
                client
                    .get_facet(FacetQuery::new(
                        target,
                        FacetOwner::entity(entity_id),
                        FacetTypeId::from("neutral.blob.reference"),
                    ))
                    .await
                    .expect("CV-029 facet after missing blob")
                    .expect("CV-029 blob facet after missing blob"),
                facet_before
            );

            let corrupt_reference = blobs
                .put(b"cv029 corrupt body", Some("text/plain"))
                .await
                .expect("CV-029 corrupt BlobRef creation");
            blobs
                .corrupt(&corrupt_reference, b"cv029 corrupt bodx".to_vec())
                .expect("CV-029 blob corruption fault injection");
            assert!(matches!(
                blobs.read(&corrupt_reference).await,
                Err(BlobError::HashMismatch { .. })
            ));
            assert_eq!(
                client
                    .list_events(EventQuery::all(target))
                    .await
                    .expect("CV-029 history after corrupt blob"),
                history_before
            );
            assert_eq!(
                client
                    .get_facet(FacetQuery::new(
                        target,
                        FacetOwner::entity(entity_id),
                        FacetTypeId::from("neutral.blob.reference"),
                    ))
                    .await
                    .expect("CV-029 facet after corrupt blob")
                    .expect("CV-029 blob facet after corrupt blob"),
                facet_before
            );
        });
    }};
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
        32,
        "central registry contains T19's implementable scenarios"
    );
    assert!(registry.get("CV-028").is_none());
    assert!(registry.get("CV-029").is_none());
    assert!(registry.get("CV-030").is_some());
    assert!(registry.get("CV-040").is_some());

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

    // The central registry contains T19's implementable scenarios.
    let after = validator_registry();
    assert_eq!(after.len(), 32);
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

// ── CV-028/CV-029 controlled Runtime/Storage fixtures ──────────────────────

#[test]
fn cv028_projection_rebuild_delete_preserves_public_world_truth_in_memory() {
    let (runtime, client, server, _blobs) = start_t15_in_memory_runtime();
    let _keep = server;
    run_cv028_projection_case!(runtime, client);
}

#[test]
fn cv028_projection_rebuild_delete_preserves_public_world_truth_on_pg18() {
    let (runtime, client, server, _blobs, _bootstrap) = start_t15_postgres_runtime();
    let _keep = server;
    run_cv028_projection_case!(runtime, client);
}

#[test]
fn cv029_blob_failures_preserve_public_facet_and_history_in_memory() {
    let (runtime, client, server, blobs) = start_t15_in_memory_runtime();
    let _keep = server;
    run_cv029_blob_case!(runtime, client, blobs);
}

#[test]
fn cv029_blob_failures_preserve_public_facet_and_history_on_pg18() {
    let (runtime, client, server, blobs, _bootstrap) = start_t15_postgres_runtime();
    let _keep = server;
    run_cv029_blob_case!(runtime, client, blobs);
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
    assert_eq!(registry.len(), 32);
    assert!(registry.get("CV-028").is_none());
    assert!(registry.get("CV-029").is_none());
    assert!(registry.get("CV-030").is_some());
}

// ── T09 fence: no lib registry edit via suite ───────────────────────────────

#[test]
fn semantic_blob_register_fence_preserves_only_cv030() {
    let mut isolated = loom_validator::ScenarioRegistry::bootstrap();
    let before = validator_registry().len();
    assert_eq!(before, 32);
    semantic_blob::register(&mut isolated).expect("register");
    assert_eq!(isolated.len(), 1);
    assert!(isolated.get("CV-030").is_some());
    assert!(isolated.get("CV-028").is_none());
    assert!(isolated.get("CV-029").is_none());
    // Ensure central remains untouched
    assert_eq!(validator_registry().len(), 32);
}
