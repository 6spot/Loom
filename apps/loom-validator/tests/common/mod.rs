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

pub mod t20;

use std::{env, path::Path, process::Command, sync::Arc};

use loom_api::{
    CreateWorldFromTemplateRequest, ExecutionResult, TimelineTarget, TimelineVersion,
    WorkHandlerId, WorkId, WorkSchedule, WorldService, WorldTemplateDescriptor,
};
use loom_boundary::{BoundaryConfig, RequireAdminAuthorization, router_with_admin};
use loom_capability::CapabilityRegistry;
use loom_client::LoomClient;
use loom_neutral::registry as neutral_registry;
use loom_protocol::{NewWork, Resolution, WorkMutation};
use loom_runtime::{
    CommitStore, EffectEngine, PlatformTime, Runtime, RuntimeRevisionCapability,
    RuntimeRevisionDescriptor, RuntimeRevisionId, RuntimeRevisionStore, SchedulerCommitStore,
    ValidatedResolution, WorkClaim, WorkStore, WorldStore,
};
use loom_storage::{InMemoryStore, PgStorage};
use serde_json::Value;
use tokio::sync::Mutex;

const DEFAULT_POSTGRES_CONTROL_URL: &str = "postgresql://loom:loom@127.0.0.1:15432/loom_control";
const SCHEDULER_TEST_MAX_COMPLETIONS: u64 = 128;

async fn schedule_capability_work<S>(
    store: &S,
    target: TimelineTarget,
    work_id: WorkId,
    payload: Value,
    schedule: WorkSchedule,
) -> Result<TimelineVersion, String>
where
    S: WorldStore + CommitStore,
{
    let registry = neutral_registry();
    let snapshot = WorldStore::snapshot(store, target.timeline_id)
        .await
        .map_err(|error| format!("snapshot before scheduling test Work failed: {error:?}"))?;
    let work = NewWork::capability_work(
        work_id,
        target.timeline_id,
        "neutral.counter",
        WorkHandlerId::from(loom_neutral::COUNTER_INCREMENT_WORK),
        loom_api::SchemaRevision::new(1),
        payload,
        schedule,
    );
    let resolution = Resolution::new(Vec::new(), vec![WorkMutation::Schedule(work)]);
    let validated = EffectEngine::new(&registry)
        .validate(&snapshot.world_view(), "neutral.counter", resolution)
        .map_err(|error| format!("test Work scheduling validation failed: {error:?}"))?;
    let result = CommitStore::commit(store, &validated, None, PlatformTime::new(0))
        .await
        .map_err(|error| format!("test Work scheduling commit failed: {error:?}"))?;
    Ok(result.version)
}

async fn complete_claim<S>(
    store: &S,
    target: TimelineTarget,
    claim: WorkClaim,
    now: PlatformTime,
) -> Result<loom_runtime::CommitResult, String>
where
    S: WorldStore + SchedulerCommitStore,
{
    let registry = neutral_registry();
    let snapshot = WorldStore::snapshot(store, target.timeline_id)
        .await
        .map_err(|error| format!("snapshot before test Work completion failed: {error:?}"))?;
    let validated: ValidatedResolution = EffectEngine::new(&registry)
        .validate(
            &snapshot.world_view(),
            "validator.t12.scheduler.fencing.stale-completion",
            Resolution::default(),
        )
        .map_err(|error| format!("stale-completion validation failed: {error:?}"))?;
    SchedulerCommitStore::commit_scheduler_work(
        store,
        &validated,
        &claim,
        now,
        SCHEDULER_TEST_MAX_COMPLETIONS,
    )
    .await
    .map_err(|error| format!("scheduler completion commit failed: {error:?}"))
}

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

fn validator_revision_r2(registry: &CapabilityRegistry) -> RuntimeRevisionDescriptor {
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
    .expect("validator T10 R2 revision should be valid")
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

async fn ensure_r2_revision_pg(
    store: &PgStorage,
    descriptor: RuntimeRevisionDescriptor,
) -> Result<(), String> {
    match RuntimeRevisionStore::confirm_revision(store, descriptor).await {
        Ok(_) => Ok(()),
        Err(error) if format!("{error:?}").contains("already exists") => Ok(()),
        Err(error) => Err(format!("{error:?}")),
    }
}

struct PgR2Handle {
    store: PgStorage,
    server: tokio::task::JoinHandle<()>,
}

/// `PostgreSQL` service composition for CV-014's real T10 R2 fixture.
#[derive(Clone)]
pub struct PgR2Server {
    inner: Arc<Mutex<PgR2Handle>>,
}

impl PgR2Server {
    pub fn start() -> Result<(Self, LoomClient), String> {
        let (url, uses_repository_default) = postgres_url();
        let store = leaked_runtime().block_on(async {
            let store = match PgStorage::connect(&url).await {
                Ok(store) => store,
                Err(initial_error) if uses_repository_default => {
                    start_repository_postgres()?;
                    PgStorage::connect(&url).await.map_err(|retry_error| {
                        format!(
                            "PostgreSQL remained unavailable: {initial_error:?}; {retry_error:?}"
                        )
                    })?
                }
                Err(error) => return Err(format!("PostgreSQL unavailable: {error:?}")),
            };
            store.health().await.map_err(|error| format!("{error:?}"))?;
            store
                .migrate()
                .await
                .map_err(|error| format!("{error:?}"))?;
            Ok::<PgStorage, String>(store)
        })?;
        let (client, handle) = leaked_runtime().block_on(start_pg_r2(store.clone()))?;
        Ok((
            Self {
                inner: Arc::new(Mutex::new(handle)),
            },
            client,
        ))
    }

    pub fn restart(&self) -> Result<LoomClient, String> {
        let inner = Arc::clone(&self.inner);
        std::thread::spawn(move || {
            leaked_runtime().block_on(async {
                let mut guard = inner.lock().await;
                guard.server.abort();
                let (client, handle) = start_pg_r2(guard.store.clone()).await?;
                *guard = handle;
                Ok::<LoomClient, String>(client)
            })
        })
        .join()
        .map_err(|_| "pg-r2 restart thread panicked".to_owned())?
    }
}

async fn start_pg_r2(store: PgStorage) -> Result<(LoomClient, PgR2Handle), String> {
    let registry = neutral_registry();
    registry.validate().map_err(|error| format!("{error:?}"))?;
    ensure_validator_revision_pg(&store, &registry).await?;
    ensure_r2_revision_pg(&store, validator_revision_r2(&registry)).await?;
    ensure_r2_revision_pg(&store, historical_counter_revision(&registry)).await?;
    let runtime = Runtime::new(store.clone(), registry).map_err(|error| format!("{error:?}"))?;
    let router = router_with_admin(
        Arc::new(runtime),
        Arc::new(RequireAdminAuthorization),
        BoundaryConfig::default(),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|error| error.to_string())?;
    let address = listener.local_addr().map_err(|error| error.to_string())?;
    let server = tokio::spawn(async move {
        if let Err(error) = axum::serve(listener, router).await {
            eprintln!("pg-r2 server failed: {error}");
        }
    });
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    let client = admin_client(address)?;
    Ok((client, PgR2Handle { store, server }))
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

    /// Test-only control seam: schedule generic Capability Work through the
    /// existing Runtime validation and `CommitStore` authority. Validator
    /// findings must use the `LoomClient` reads, never this return value.
    pub fn schedule_work_for_test(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        payload: Value,
        schedule: WorkSchedule,
    ) -> Result<TimelineVersion, String> {
        let store = leaked_runtime().block_on(async {
            let guard = self.inner.lock().await;
            guard.store
        });
        leaked_runtime().block_on(schedule_capability_work(
            store, target, work_id, payload, schedule,
        ))
    }

    /// Test-only control seam for driving one Work through the existing
    /// Runtime/WorkStore/Scheduler commit authority.
    pub fn execute_work_for_test(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
        retry_available_at: PlatformTime,
    ) -> Result<ExecutionResult, String> {
        let store = leaked_runtime().block_on(async {
            let guard = self.inner.lock().await;
            guard.store
        });
        leaked_runtime().block_on(async {
            let runtime = Runtime::new(store, neutral_registry())
                .map_err(|error| format!("test Runtime construction failed: {error:?}"))?;
            runtime
                .execute_work(target, work_id, now, claimed_until, retry_available_at)
                .await
                .map_err(|error| format!("test Runtime Work execution failed: {error:?}"))
        })
    }

    /// Test-only control seam for obtaining an authoritative claim/fence.
    pub fn claim_work_for_test(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> Result<WorkClaim, String> {
        let store = leaked_runtime().block_on(async {
            let guard = self.inner.lock().await;
            guard.store
        });
        leaked_runtime().block_on(async {
            WorkStore::claim(store, target.timeline_id, work_id, now, claimed_until)
                .await
                .map_err(|error| format!("test Work claim failed: {error:?}"))
        })
    }

    /// Test-only control seam for submitting a claim to the existing atomic
    /// `SchedulerCommitStore` authority.
    pub fn complete_claim_for_test(
        &self,
        target: TimelineTarget,
        claim: WorkClaim,
        now: PlatformTime,
    ) -> Result<loom_runtime::CommitResult, String> {
        let store = leaked_runtime().block_on(async {
            let guard = self.inner.lock().await;
            guard.store
        });
        leaked_runtime().block_on(complete_claim(store, target, claim, now))
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

    /// Test-only control seam: schedule generic Capability Work through the
    /// existing Runtime validation and `CommitStore` authority. Validator
    /// findings must use the `LoomClient` reads, never this return value.
    pub fn schedule_work_for_test(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        payload: Value,
        schedule: WorkSchedule,
    ) -> Result<TimelineVersion, String> {
        let store = leaked_runtime().block_on(async {
            let guard = self.inner.lock().await;
            guard.store.clone()
        });
        leaked_runtime().block_on(schedule_capability_work(
            &store, target, work_id, payload, schedule,
        ))
    }

    /// Test-only control seam for driving one Work through the existing
    /// Runtime/WorkStore/Scheduler commit authority.
    pub fn execute_work_for_test(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
        retry_available_at: PlatformTime,
    ) -> Result<ExecutionResult, String> {
        let store = leaked_runtime().block_on(async {
            let guard = self.inner.lock().await;
            guard.store.clone()
        });
        leaked_runtime().block_on(async {
            let runtime = Runtime::new(store, neutral_registry())
                .map_err(|error| format!("test Runtime construction failed: {error:?}"))?;
            runtime
                .execute_work(target, work_id, now, claimed_until, retry_available_at)
                .await
                .map_err(|error| format!("test Runtime Work execution failed: {error:?}"))
        })
    }

    /// Test-only control seam for obtaining an authoritative claim/fence.
    pub fn claim_work_for_test(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> Result<WorkClaim, String> {
        let store = leaked_runtime().block_on(async {
            let guard = self.inner.lock().await;
            guard.store.clone()
        });
        leaked_runtime().block_on(async {
            WorkStore::claim(&store, target.timeline_id, work_id, now, claimed_until)
                .await
                .map_err(|error| format!("test Work claim failed: {error:?}"))
        })
    }

    /// Test-only control seam for submitting a claim to the existing atomic
    /// `SchedulerCommitStore` authority.
    pub fn complete_claim_for_test(
        &self,
        target: TimelineTarget,
        claim: WorkClaim,
        now: PlatformTime,
    ) -> Result<loom_runtime::CommitResult, String> {
        let store = leaked_runtime().block_on(async {
            let guard = self.inner.lock().await;
            guard.store.clone()
        });
        leaked_runtime().block_on(complete_claim(&store, target, claim, now))
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
