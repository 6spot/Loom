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

use std::{env, sync::Arc};

use loom_boundary::{BoundaryConfig, router};
use loom_client::LoomClient;
use loom_neutral::registry as neutral_registry;
use loom_runtime::Runtime;
use loom_storage::{InMemoryStore, PgStorage};
use tokio::sync::Mutex;

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
    let runtime = Runtime::new(store, registry).map_err(|e| format!("{e:?}"))?;
    let api = Arc::new(runtime);
    let router = router(api, BoundaryConfig::default());
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
    let client = LoomClient::new(format!("http://{addr}")).map_err(|e| e.to_string())?;
    Ok((client, InMemoryHandle { store, server }))
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
    /// client. Requires `LOOM_TEST_POSTGRES_URL`.
    pub fn start() -> Result<(Self, LoomClient), String> {
        let url = env::var("LOOM_TEST_POSTGRES_URL").map_err(|e| e.to_string())?;
        let store = leaked_runtime().block_on(async {
            let store = PgStorage::connect(&url)
                .await
                .map_err(|e| format!("{e:?}"))?;
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

async fn start_pg(store: PgStorage) -> Result<(LoomClient, PgHandle), String> {
    let registry = neutral_registry();
    registry.validate().map_err(|e| format!("{e:?}"))?;
    let runtime = Runtime::new(store.clone(), registry).map_err(|e| format!("{e:?}"))?;
    let api = Arc::new(runtime);
    let router = router(api, BoundaryConfig::default());
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
    let client = LoomClient::new(format!("http://{addr}")).map_err(|e| e.to_string())?;
    Ok((client, PgHandle { store, server }))
}
