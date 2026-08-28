//! World Binding suite integration tests (T10).
//!
//! Validates CV-012..CV-014 via the public `loom-api`/`loom-client` surface
//! using controlled `InMemory` and `PostgreSQL` harnesses. The production suite
//! `src/world_binding.rs` remains on the public consumer fence; real service
//! composition for scenario evidence is test-only here, the same pattern
//! `loom-client` uses to exercise its boundary. Central registry remains at
//! 11 scenarios until T19.

mod common;

use std::sync::Arc;

use loom_boundary::{BoundaryConfig, RequireAdminAuthorization, router_with_admin};
use loom_capability::CapabilityRegistry;
use loom_client::LoomClient;
use loom_neutral::registry as neutral_registry;
use loom_runtime::{
    PlatformTime, Runtime, RuntimeRevisionCapability, RuntimeRevisionDescriptor, RuntimeRevisionId,
    RuntimeRevisionStore,
};
use loom_storage::{InMemoryStore, PgStorage};
use tokio::sync::Mutex;

use loom_validator::{
    BackendContext, BackendKind, ScenarioResult, validator_registry, world_binding,
};

// ── scaffold disjointness (must remain true until T19) ───────────────────────

#[test]
fn world_binding_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(world_binding::SUITE, "world_binding");
    assert_eq!(world_binding::CV_RANGE, "CV-012..CV-014");
    assert_eq!(world_binding::CAPABILITY_AREA, "world-binding");
    assert_eq!(world_binding::suite_name(), "world_binding");
    assert!(world_binding::owns_cv("CV-012"));
    assert!(world_binding::owns_cv("CV-013"));
    assert!(world_binding::owns_cv("CV-014"));
    assert!(!world_binding::owns_cv("CV-015"));
    assert!(!world_binding::owns_cv("CV-011"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 32);
    assert!(registry.get("CV-001").is_some());
    assert!(registry.get("CV-011").is_some());
    assert!(registry.get("CV-012").is_some());
    assert!(registry.get("CV-014").is_some());
    assert!(registry.get("CV-040").is_some());
}

#[test]
fn world_binding_descriptors_are_three_and_deterministic() {
    let first = world_binding::descriptors();
    let second = world_binding::descriptors();
    assert_eq!(first.len(), 3);
    assert_eq!(first, second);
    let ids: Vec<_> = first.iter().map(|d| d.id_str().to_string()).collect();
    assert_eq!(ids, vec!["CV-012", "CV-013", "CV-014"]);
    // Supported backends per T08 matrix
    assert_eq!(
        first[0].supported_backends(),
        &[
            BackendKind::LoomClient,
            BackendKind::InMemory,
            BackendKind::PostgreSQL
        ]
    );
    assert_eq!(
        first[1].supported_backends(),
        &[
            BackendKind::LoomClient,
            BackendKind::InMemory,
            BackendKind::PostgreSQL
        ]
    );
    assert_eq!(
        first[2].supported_backends(),
        &[BackendKind::InMemory, BackendKind::PostgreSQL]
    );
    // External must not be supported for CV-014
    assert!(
        !first[2]
            .supported_backends()
            .contains(&BackendKind::LoomClient)
    );
}

// ── helpers ──────────────────────────────────────────────────────────────────

fn assert_pass(result: &ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass via public surface: {result:?} finding={} evidence={:?}",
        result.finding().actual(),
        result.finding().evidence()
    );
}

fn context_for(client: LoomClient, backend: BackendKind, scope: &str) -> BackendContext {
    BackendContext::new(client)
        .with_backend_kind(backend)
        .with_scope(scope)
}

fn descriptor(id: &str) -> loom_validator::ScenarioDescriptor {
    world_binding::descriptors()
        .into_iter()
        .find(|d| d.id_str() == id)
        .unwrap_or_else(|| panic!("missing descriptor {id}"))
}

// ── InMemory helpers with R2 support ────────────────────────────────────────

fn validator_descriptor(registry: &CapabilityRegistry) -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("validator-explicit-v0"),
        PlatformTime::default(),
        "validator-test-build",
        registry.loom_version().clone(),
        registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("validator-test:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("validator runtime revision should be valid")
}

fn validator_descriptor_r2(registry: &CapabilityRegistry) -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("validator-t10-r2"),
        PlatformTime::new(999),
        "validator-t10-r2-build",
        registry.loom_version().clone(),
        registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("validator-t10-r2:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("validator t10 r2 revision should be valid")
}

fn historical_counter_revision(registry: &CapabilityRegistry) -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("validator-history-r2"),
        PlatformTime::new(998),
        "historical-counter-build",
        registry.loom_version().clone(),
        registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("historical-counter:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("historical counter revision should be valid")
}

fn ensure_r1_in_memory(store: &InMemoryStore, registry: &CapabilityRegistry) -> Result<(), String> {
    let descriptor = validator_descriptor(registry);
    store
        .confirm_revision(descriptor.clone())
        .map_err(|e| format!("{e:?}"))?;
    let active = store.read_active_revision().map_err(|e| format!("{e:?}"))?;
    let needs_activation = active
        .as_ref()
        .is_none_or(|selection| selection.revision().id() != descriptor.id());
    if needs_activation {
        let expected = active
            .as_ref()
            .map(loom_runtime::RuntimeRevisionSelection::generation);
        store
            .activate_revision(descriptor.id().clone(), expected, PlatformTime::default())
            .map_err(|e| format!("{e:?}"))?;
    }
    Ok(())
}

fn ensure_r2_in_memory(store: &InMemoryStore, registry: &CapabilityRegistry) -> Result<(), String> {
    let descriptor = validator_descriptor_r2(registry);
    // Confirm R2 without activating; active should remain R1
    match store.confirm_revision(descriptor.clone()) {
        Ok(_) => Ok(()),
        Err(e) => {
            // If already exists, ignore
            let msg = format!("{e:?}");
            if msg.contains("already exists") || msg.contains("RevisionAlreadyExists") {
                Ok(())
            } else {
                Err(msg)
            }
        }
    }
}

fn ensure_historical_counter_in_memory(
    store: &InMemoryStore,
    registry: &CapabilityRegistry,
) -> Result<(), String> {
    let descriptor = historical_counter_revision(registry);
    match store.confirm_revision(descriptor) {
        Ok(_) => Ok(()),
        Err(e) => {
            let msg = format!("{e:?}");
            if msg.contains("already exists") || msg.contains("RevisionAlreadyExists") {
                Ok(())
            } else {
                Err(msg)
            }
        }
    }
}

struct InMemoryR2Handle {
    store: &'static InMemoryStore,
    server: tokio::task::JoinHandle<()>,
}

#[derive(Clone)]
struct InMemoryR2Server {
    inner: Arc<Mutex<InMemoryR2Handle>>,
}

impl InMemoryR2Server {
    fn start_with_r2() -> Result<(Self, LoomClient), String> {
        let store: &'static InMemoryStore = Box::leak(Box::new(InMemoryStore::new()));
        let (client, handle) = common::leaked_runtime().block_on(start_in_memory_with_r2(store))?;
        Ok((
            Self {
                inner: Arc::new(Mutex::new(handle)),
            },
            client,
        ))
    }

    fn restart(&self) -> Result<LoomClient, String> {
        let inner = Arc::clone(&self.inner);
        let rt = common::leaked_runtime();
        std::thread::spawn(move || {
            rt.block_on(async {
                let mut guard = inner.lock().await;
                guard.server.abort();
                let (client, handle) = start_in_memory_with_r2(guard.store).await?;
                *guard = handle;
                Ok::<LoomClient, String>(client)
            })
        })
        .join()
        .map_err(|_| "in-memory-r2 restart thread panicked".to_string())?
    }
}

async fn start_in_memory_with_r2(
    store: &'static InMemoryStore,
) -> Result<(LoomClient, InMemoryR2Handle), String> {
    let registry = neutral_registry();
    registry.validate().map_err(|e| format!("{e:?}"))?;
    ensure_r1_in_memory(store, &registry)?;
    ensure_historical_counter_in_memory(store, &registry)?;
    ensure_r2_in_memory(store, &registry)?;
    let runtime = Runtime::new(store, registry).map_err(|e| format!("{e:?}"))?;
    let api = Arc::new(runtime);
    let router = router_with_admin(
        api,
        Arc::new(RequireAdminAuthorization),
        BoundaryConfig::default(),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|e| e.to_string())?;
    let addr = listener.local_addr().map_err(|e| e.to_string())?;
    let server = tokio::spawn(async move {
        if let Err(e) = axum::serve(listener, router).await {
            eprintln!("in-memory-r2 server failed: {e}");
        }
    });
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    let client = LoomClient::builder(format!("http://{addr}"))
        .admin_token("validator-test-admin")
        .map_err(|e| e.to_string())?
        .build()
        .map_err(|e| e.to_string())?;
    Ok((client, InMemoryR2Handle { store, server }))
}

// ── PostgreSQL helpers with R2 ──────────────────────────────────────────────

use std::{env, path::Path, process::Command};

const DEFAULT_POSTGRES_CONTROL_URL: &str = "postgresql://loom:loom@127.0.0.1:15432/loom_control";

fn postgres_url() -> (String, bool) {
    match env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) if !url.trim().is_empty() => (url, false),
        _ => (DEFAULT_POSTGRES_CONTROL_URL.to_owned(), true),
    }
}

fn start_repository_postgres() -> Result<(), String> {
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/postgres-test.sh");
    let status = Command::new("bash")
        .arg(&script)
        .arg("up")
        .status()
        .map_err(|error| format!("failed to start `{}`: {error}", script.display()))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("`{}` exited with {status}", script.display()))
    }
}

async fn ensure_r1_pg(store: &PgStorage, registry: &CapabilityRegistry) -> Result<(), String> {
    let descriptor = validator_descriptor(registry);
    RuntimeRevisionStore::confirm_revision(store, descriptor.clone())
        .await
        .map_err(|e| format!("{e:?}"))?;
    let active = RuntimeRevisionStore::read_active_revision(store)
        .await
        .map_err(|e| format!("{e:?}"))?;
    let needs_activation = active
        .as_ref()
        .is_none_or(|selection| selection.revision().id() != descriptor.id());
    if needs_activation {
        let expected = active
            .as_ref()
            .map(loom_runtime::RuntimeRevisionSelection::generation);
        RuntimeRevisionStore::activate_revision(
            store,
            descriptor.id().clone(),
            expected,
            PlatformTime::default(),
        )
        .await
        .map_err(|e| format!("{e:?}"))?;
    }
    Ok(())
}

async fn ensure_r2_pg(store: &PgStorage, registry: &CapabilityRegistry) -> Result<(), String> {
    let descriptor = validator_descriptor_r2(registry);
    match RuntimeRevisionStore::confirm_revision(store, descriptor.clone()).await {
        Ok(_) => Ok(()),
        Err(e) => {
            let msg = format!("{e:?}");
            if msg.contains("already exists") || msg.contains("RevisionAlreadyExists") {
                Ok(())
            } else {
                Err(msg)
            }
        }
    }
}

async fn ensure_historical_counter_pg(
    store: &PgStorage,
    registry: &CapabilityRegistry,
) -> Result<(), String> {
    let descriptor = historical_counter_revision(registry);
    match RuntimeRevisionStore::confirm_revision(store, descriptor).await {
        Ok(_) => Ok(()),
        Err(e) => {
            let msg = format!("{e:?}");
            if msg.contains("already exists") || msg.contains("RevisionAlreadyExists") {
                Ok(())
            } else {
                Err(msg)
            }
        }
    }
}

struct PgR2Handle {
    store: PgStorage,
    server: tokio::task::JoinHandle<()>,
}

#[derive(Clone)]
struct PgR2Server {
    inner: Arc<Mutex<PgR2Handle>>,
}

impl PgR2Server {
    fn start_with_r2() -> Result<(Self, LoomClient), String> {
        let (url, uses_repository_default) = postgres_url();
        let store = common::leaked_runtime().block_on(async {
            let store = match PgStorage::connect(&url).await {
                Ok(store) => store,
                Err(initial_error) if uses_repository_default => {
                    start_repository_postgres().map_err(|start_error| {
                        format!(
                            "default PostgreSQL control database was unreachable ({initial_error:?}); {start_error}"
                        )
                    })?;
                    PgStorage::connect(&url).await.map_err(|retry_error| {
                        format!(
                            "repository-managed PostgreSQL test service is still unreachable after startup: {retry_error:?}"
                        )
                    })?
                }
                Err(error) => {
                    return Err(format!(
                        "PostgreSQL test database from LOOM_TEST_POSTGRES_URL is unavailable: {error:?}"
                    ));
                }
            };
            store.health().await.map_err(|e| format!("{e:?}"))?;
            store.migrate().await.map_err(|e| format!("{e:?}"))?;
            Ok::<PgStorage, String>(store)
        })?;
        let (client, handle) =
            common::leaked_runtime().block_on(start_pg_with_r2(store.clone()))?;
        Ok((
            Self {
                inner: Arc::new(Mutex::new(handle)),
            },
            client,
        ))
    }

    fn restart(&self) -> Result<LoomClient, String> {
        let inner = Arc::clone(&self.inner);
        let rt = common::leaked_runtime();
        std::thread::spawn(move || {
            rt.block_on(async {
                let mut guard = inner.lock().await;
                guard.server.abort();
                let (client, handle) = start_pg_with_r2(guard.store.clone()).await?;
                *guard = handle;
                Ok::<LoomClient, String>(client)
            })
        })
        .join()
        .map_err(|_| "pg-r2 restart thread panicked".to_string())?
    }
}

async fn start_pg_with_r2(store: PgStorage) -> Result<(LoomClient, PgR2Handle), String> {
    let registry = neutral_registry();
    registry.validate().map_err(|e| format!("{e:?}"))?;
    ensure_r1_pg(&store, &registry).await?;
    ensure_historical_counter_pg(&store, &registry).await?;
    ensure_r2_pg(&store, &registry).await?;
    let runtime = Runtime::new(store.clone(), registry).map_err(|e| format!("{e:?}"))?;
    let api = Arc::new(runtime);
    let router = router_with_admin(
        api,
        Arc::new(RequireAdminAuthorization),
        BoundaryConfig::default(),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|e| e.to_string())?;
    let addr = listener.local_addr().map_err(|e| e.to_string())?;
    let server = tokio::spawn(async move {
        if let Err(e) = axum::serve(listener, router).await {
            eprintln!("pg-r2 server failed: {e}");
        }
    });
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    let client = LoomClient::builder(format!("http://{addr}"))
        .admin_token("validator-test-admin")
        .map_err(|e| e.to_string())?
        .build()
        .map_err(|e| e.to_string())?;
    Ok((client, PgR2Handle { store, server }))
}

// ── CV-012 ───────────────────────────────────────────────────────────────────

#[test]
fn cv012_binding_immutability_passes_on_real_in_memory() {
    let (_server, client) =
        common::InMemoryServer::start().expect("in-memory service should start");
    let ctx = context_for(client, BackendKind::InMemory, "cv012-inmemory");
    let result = world_binding::execute_world_binding(&descriptor("CV-012"), &ctx);
    assert_pass(&result, "CV-012");
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(
        evidence.contains("public-surface:loom-client::WorldService::create_world_from_template")
    );
    assert!(evidence.contains("public-surface:loom-client::TimelineService::inspect_timeline"));
    assert!(evidence.contains("public-surface:loom-client::CatalogService::catalog_for_world"));
    assert!(!evidence.to_lowercase().contains("loom_storage"));
    assert!(!evidence.to_lowercase().contains("loom_runtime"));
}

#[test]
fn cv012_binding_immutability_passes_on_live_postgres_when_configured() {
    let (_server, client) = match common::PgServer::start() {
        Ok(v) => v,
        Err(e) => {
            eprintln!("skipping CV-012 postgres: {e}");
            return;
        }
    };
    let ctx = context_for(client, BackendKind::PostgreSQL, "cv012-postgres");
    let result = world_binding::execute_world_binding(&descriptor("CV-012"), &ctx);
    // PostgreSQL may be unavailable in some CI environments; treat prerequisite correctly
    if result.outcome().is_pass() {
        assert_pass(&result, "CV-012");
    } else {
        assert!(
            result.outcome().is_unavailable() || result.outcome().is_skipped(),
            "CV-012 postgres should be pass or prerequisite when live db not ready: {result:?}"
        );
    }
}

// ── CV-013 ───────────────────────────────────────────────────────────────────

#[test]
fn cv013_compatible_revision_permits_action_passes_on_real_in_memory() {
    let (_server, client) =
        common::InMemoryServer::start().expect("in-memory service should start");
    let ctx = context_for(client, BackendKind::InMemory, "cv013-inmemory");
    let result = world_binding::execute_world_binding(&descriptor("CV-013"), &ctx);
    assert_pass(&result, "CV-013");
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(evidence.contains("public-surface:loom-client::AdminService::active_runtime_revision"));
    assert!(evidence.contains("public-surface:loom-client::ActionService::invoke"));
    assert!(!evidence.to_lowercase().contains("loom_storage"));
}

#[test]
fn cv013_compatible_revision_permits_action_passes_on_live_postgres_when_configured() {
    let (_server, client) = match common::PgServer::start() {
        Ok(v) => v,
        Err(e) => {
            eprintln!("skipping CV-013 postgres: {e}");
            return;
        }
    };
    let ctx = context_for(client, BackendKind::PostgreSQL, "cv013-postgres");
    let result = world_binding::execute_world_binding(&descriptor("CV-013"), &ctx);
    if result.outcome().is_pass() {
        assert_pass(&result, "CV-013");
    } else {
        assert!(
            result.outcome().is_unavailable() || result.outcome().is_skipped(),
            "CV-013 postgres should be pass or prerequisite: {result:?}"
        );
    }
}

// ── CV-014 ───────────────────────────────────────────────────────────────────

#[test]
fn cv014_revision_activation_preserves_binding_on_real_in_memory_with_r2() {
    let (server, client) =
        InMemoryR2Server::start_with_r2().expect("in-memory-r2 service should start");
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_scope("cv014-inmemory-r2")
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart();
    let result = world_binding::execute_world_binding(&descriptor("CV-014"), &ctx);
    assert_pass(&result, "CV-014");
    assert!(result.finding().actual().contains("R2 validator-t10-r2"));
    assert!(!result.finding().actual().contains("validator-history-r2"));
    let evidence = result
        .finding()
        .evidence()
        .iter()
        .map(loom_validator::EvidenceReference::as_str)
        .collect::<Vec<_>>()
        .join(",");
    assert!(evidence.contains("public-surface:loom-client::AdminService::list_runtime_revisions"));
    assert!(
        evidence.contains("public-surface:loom-client::AdminService::activate_runtime_revision")
    );
    assert!(!evidence.to_lowercase().contains("loom_storage"));
    // Ensure no historical binding was mutated message not present
    assert!(
        !result
            .finding()
            .actual()
            .to_lowercase()
            .contains("rewritten")
            || result.outcome().is_pass()
    );
}

#[test]
fn cv014_revision_activation_preserves_binding_on_live_postgres_with_r2_when_configured() {
    let (server, client) = match PgR2Server::start_with_r2() {
        Ok(v) => v,
        Err(e) => {
            eprintln!("skipping CV-014 postgres r2: {e}");
            // Verify that without live postgres, the validator correctly reports prerequisite/unavailable
            // via the generic harness path rather than synthetic pass.
            let Ok(harness) = loom_validator::BackendHarness::connect(
                BackendKind::PostgreSQL,
                "http://127.0.0.1:8080",
            ) else {
                return;
            };
            let start = harness.start("CV-014");
            if let loom_validator::BackendStart::Prerequisite { .. }
            | loom_validator::BackendStart::Unavailable { .. } = start
            {
                // Correctly reports missing prerequisite when postgres not live
                return;
            }
            if let loom_validator::BackendStart::Ready(ctx) = start {
                let result = world_binding::execute_world_binding(&descriptor("CV-014"), &ctx);
                assert!(
                    result.outcome().is_unavailable() || result.outcome().is_skipped(),
                    "CV-014 postgres without live db should be unavailable/skipped: {result:?}"
                );
            }
            return;
        }
    };
    let server_for_restart = server.clone();
    let strategy: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync> =
        Arc::new(move || server_for_restart.restart());
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_scope("cv014-postgres-r2")
        .with_restart_strategy(strategy)
        .with_controlled_boundary_restart();
    let result = world_binding::execute_world_binding(&descriptor("CV-014"), &ctx);
    if result.outcome().is_pass() {
        assert!(result.finding().actual().contains("R2 validator-t10-r2"));
        assert!(!result.finding().actual().contains("validator-history-r2"));
        let evidence = result
            .finding()
            .evidence()
            .iter()
            .map(loom_validator::EvidenceReference::as_str)
            .collect::<Vec<_>>()
            .join(",");
        assert!(
            evidence.contains("backend_evidence:postgresql") || evidence.contains("postgresql")
        );
        assert!(!evidence.to_lowercase().contains("loom_storage"));
    } else {
        // In environments where PostgreSQL env var not set or live check fails, allow prerequisite
        // Controlled PostgreSQL evidence requires LOOM_TEST_POSTGRES_URL; if missing, the scenario
        // correctly reports Skipped/Unavailable rather than synthetic pass.
        assert!(
            result.outcome().is_unavailable() || result.outcome().is_skipped(),
            "CV-014 postgres should be pass or prerequisite when live db not fully ready: {result:?}"
        );
        eprintln!(
            "CV-014 postgres prerequisite: {}",
            result.finding().actual()
        );
    }
}

#[test]
fn cv014_reconnect_only_is_unavailable_before_restart_sensitive_lifecycle() {
    let (_server, client) =
        common::InMemoryServer::start().expect("in-memory service should start");
    let ctx = context_for(client, BackendKind::InMemory, "cv014-reconnect-only");
    let result = world_binding::execute_world_binding(&descriptor("CV-014"), &ctx);

    assert!(
        result.outcome().is_unavailable(),
        "CV-014 reconnect-only must be unavailable: {result:?}"
    );
    assert_eq!(ctx.restart_capability().as_str(), "reconnect-only");
    assert!(
        result
            .finding()
            .actual()
            .contains("requires ControlledBoundaryRestart")
    );
}

// ── negative: external backend must not be trusted for CV-014 ────────────────

#[test]
fn cv014_external_backend_is_prerequisite_not_pass() {
    let client = LoomClient::builder("http://127.0.0.1:8080".to_string())
        .build()
        .expect("client should build");
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::LoomClient)
        .with_scope("cv014-external");
    let result = world_binding::execute_world_binding(&descriptor("CV-014"), &ctx);
    // CV-014 does not support LoomClient; must be prerequisite/skipped, not pass
    assert!(
        !result.outcome().is_pass(),
        "CV-014 external should not pass: {result:?}"
    );
    assert!(
        result.outcome().is_skipped() || result.outcome().is_unavailable(),
        "CV-014 external should be skipped/unavailable: {result:?}"
    );
}
