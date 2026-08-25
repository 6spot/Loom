//! Shared test harness for the validator's VAL-T8 lifecycle scenarios.
//!
//! This module composes the real Loom application/service boundary
//! (`loom-runtime` + `loom-storage` + `loom-neutral` + `loom-boundary`) over
//! HTTP, using only dev-dependencies. Production `loom-validator` keeps a
//! public-only surface (`loom-api` + `loom-client`); this test-only harness is
//! where real InMemory/PostgreSQL services are built and restarted so the
//! scenarios are exercised against genuine application boundaries with durable
//! state that survives a real boundary rebuild.

#![allow(dead_code)]

use std::{env, path::Path, process::Command, sync::Arc};

use loom_api::{
    CreateWorldFromTemplateRequest, TimelineTarget, WorldService, WorldTemplateDescriptor,
};
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

const DEFAULT_POSTGRES_CONTROL_URL: &str = "postgresql://loom:loom@127.0.0.1:15432/loom_control";

/// A process-lifetime tokio runtime whose spawns (including the axum HTTP
/// server) survive the calling thread, so a restarted service's server task is
/// not dropped when a worker thread exits.
pub fn leaked_runtime() -> &'static tokio::runtime::Runtime {
    static RUNTIME: std::sync::OnceLock<&'static tokio::runtime::Runtime> =
        std::sync::OnceLock::new();
    RUNTIME.get_or_init(|| {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("failed to build validator test runtime");
        Box::leak(Box::new(rt))
    })
}

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

fn ensure_validator_revision_in_memory(
    store: &InMemoryStore,
    registry: &CapabilityRegistry,
) -> Result<(), String> {
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

async fn ensure_validator_revision_pg(
    store: &PgStorage,
    registry: &CapabilityRegistry,
) -> Result<(), String> {
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

struct InMemoryHandle {
    store: &'static InMemoryStore,
    server: tokio::task::JoinHandle<()>,
}

/// A real InMemory-backed Loom service over HTTP with a genuine restart that
/// terminates and rebuilds the application boundary while preserving the store.
#[derive(Clone)]
pub struct InMemoryServer {
    inner: Arc<Mutex<InMemoryHandle>>,
}

impl InMemoryServer {
    /// Starts a real `InMemory` Loom HTTP service and returns its public client.
    pub fn start() -> Result<(Self, LoomClient), String> {
        let store: &'static InMemoryStore = Box::leak(Box::new(InMemoryStore::new()));
        let (client, handle) = leaked_runtime().block_on(start_in_memory(store))?;
        Ok((
            Self {
                inner: Arc::new(Mutex::new(handle)),
            },
            client,
        ))
    }

    /// Starts a service with a persisted A+B World and an intentionally
    /// partial A-only active Runtime Revision. The state is seeded through the
    /// test composition root; the scenario observes and exercises it through
    /// the public HTTP client.
    pub fn start_partial_binding() -> Result<(Self, LoomClient, TimelineTarget), String> {
        let store: &'static InMemoryStore = Box::leak(Box::new(InMemoryStore::new()));
        let (client, handle, target) = leaked_runtime().block_on(start_in_memory_partial(store))?;
        Ok((
            Self {
                inner: Arc::new(Mutex::new(handle)),
            },
            client,
            target,
        ))
    }

    /// Starts a service with registered software but no active Runtime
    /// Revision, so the public surface can verify that execution is denied.
    pub fn start_without_active_revision() -> Result<(Self, LoomClient), String> {
        let store: &'static InMemoryStore = Box::leak(Box::new(InMemoryStore::new()));
        let (client, handle) = leaked_runtime().block_on(start_in_memory_without_active(store))?;
        Ok((
            Self {
                inner: Arc::new(Mutex::new(handle)),
            },
            client,
        ))
    }

    /// Terminates the current service boundary and rebuilds it on the preserved
    /// store, returning a new public client to the new boundary.
    pub fn restart(&self) -> Result<LoomClient, String> {
        let inner = Arc::clone(&self.inner);
        let rt = leaked_runtime();
        std::thread::spawn(move || {
            rt.block_on(async {
                let mut guard = inner.lock().await;
                guard.server.abort();
                let (client, handle) = start_in_memory(guard.store).await?;
                *guard = handle;
                Ok::<LoomClient, String>(client)
            })
        })
        .join()
        .map_err(|_| "in-memory restart thread panicked".to_string())?
    }
}

async fn start_in_memory(
    store: &'static InMemoryStore,
) -> Result<(LoomClient, InMemoryHandle), String> {
    let registry = neutral_registry();
    registry.validate().map_err(|e| format!("{e:?}"))?;
    ensure_validator_revision_in_memory(store, &registry)?;
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
            eprintln!("in-memory server failed: {e}");
        }
    });
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    let client = admin_client(addr)?;
    Ok((client, InMemoryHandle { store, server }))
}

async fn start_in_memory_without_active(
    store: &'static InMemoryStore,
) -> Result<(LoomClient, InMemoryHandle), String> {
    let registry = neutral_registry();
    registry.validate().map_err(|e| format!("{e:?}"))?;
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
            eprintln!("in-memory server failed: {e}");
        }
    });
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    let client = admin_client(addr)?;
    Ok((client, InMemoryHandle { store, server }))
}

async fn start_in_memory_partial(
    store: &'static InMemoryStore,
) -> Result<(LoomClient, InMemoryHandle, TimelineTarget), String> {
    let (client, handle) = start_in_memory(store).await?;
    let target = client
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new(
                "validator.runtime-authority",
                1,
                loom_api::WorldInstant::new(1),
            )
            .requires_capability("neutral.counter", "^0.1.0")
            .requires_capability("neutral.observer", "^0.1.0"),
        ))
        .await
        .map_err(|e| format!("failed to seed A+B World through public API: {e:?}"))?
        .target;

    let registry = neutral_registry();
    let partial = RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("validator-neutral-counter-only"),
        PlatformTime::new(3),
        "validator-counter-only",
        registry.loom_version().clone(),
        registry
            .capabilities()
            .filter(|manifest| manifest.id.as_str() == "neutral.counter")
            .map(|manifest| {
                RuntimeRevisionCapability::from_manifest(
                    manifest,
                    format!("validator-partial:{}@{}", manifest.id, manifest.version),
                )
            }),
    )
    .map_err(|e| format!("failed to build partial revision fixture: {e:?}"))?;
    RuntimeRevisionStore::confirm_revision(store, partial)
        .await
        .map_err(|e| format!("failed to publish partial revision fixture: {e:?}"))?;
    let active = RuntimeRevisionStore::read_active_revision(store)
        .await
        .map_err(|e| format!("failed to read full active revision fixture: {e:?}"))?
        .ok_or_else(|| "full revision fixture was not active".to_owned())?;
    RuntimeRevisionStore::activate_revision(
        store,
        RuntimeRevisionId::from("validator-neutral-counter-only"),
        Some(active.generation()),
        PlatformTime::new(4),
    )
    .await
    .map_err(|e| format!("failed to activate partial revision fixture: {e:?}"))?;

    Ok((client, handle, target))
}

fn admin_client(addr: std::net::SocketAddr) -> Result<LoomClient, String> {
    LoomClient::builder(format!("http://{addr}"))
        .admin_token("validator-test-admin")
        .map_err(|e| e.to_string())?
        .build()
        .map_err(|e| e.to_string())
}

struct PgHandle {
    store: PgStorage,
    server: tokio::task::JoinHandle<()>,
}

/// A real PostgreSQL-backed Loom service over HTTP with a genuine restart that
/// terminates and rebuilds the application boundary against the preserved
/// database.
#[derive(Clone)]
pub struct PgServer {
    inner: Arc<Mutex<PgHandle>>,
}

impl PgServer {
    /// Starts a real PostgreSQL-backed Loom HTTP service and returns its public
    /// client. An explicit `LOOM_TEST_POSTGRES_URL` overrides the repository
    /// default; otherwise the repository-managed `PostgreSQL` service is used and
    /// started on demand when unreachable.
    pub fn start() -> Result<(Self, LoomClient), String> {
        let (url, uses_repository_default) = postgres_url();
        let store = leaked_runtime().block_on(async {
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
        let (client, handle) = leaked_runtime().block_on(start_pg(store.clone()))?;
        Ok((
            Self {
                inner: Arc::new(Mutex::new(handle)),
            },
            client,
        ))
    }

    /// Terminates the current service boundary and rebuilds it against the
    /// preserved database, returning a new public client to the new boundary.
    pub fn restart(&self) -> Result<LoomClient, String> {
        let inner = Arc::clone(&self.inner);
        let rt = leaked_runtime();
        std::thread::spawn(move || {
            rt.block_on(async {
                let mut guard = inner.lock().await;
                guard.server.abort();
                let (client, handle) = start_pg(guard.store.clone()).await?;
                *guard = handle;
                Ok::<LoomClient, String>(client)
            })
        })
        .join()
        .map_err(|_| "pg restart thread panicked".to_string())?
    }
}

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

async fn start_pg(store: PgStorage) -> Result<(LoomClient, PgHandle), String> {
    let registry = neutral_registry();
    registry.validate().map_err(|e| format!("{e:?}"))?;
    ensure_validator_revision_pg(&store, &registry).await?;
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
            eprintln!("pg server failed: {e}");
        }
    });
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    let client = admin_client(addr)?;
    Ok((client, PgHandle { store, server }))
}
