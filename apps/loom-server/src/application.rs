//! Native and Linux-container composition root for `loom-server`.

use std::{
    fs,
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

use axum::Router;
use loom_api::{
    ActionRequest, ActionService, AdminActivateRuntimeRevisionRequest,
    AdminAdvanceWorldTimeRequest, AdminAdvanceWorldTimeResult, AdminEventSessionLookup,
    AdminExecutionSession, AdminExecutionSessionRequest, AdminFuture,
    AdminMissingImplementationBlock, AdminMissingImplementationRequest, AdminRuntimeRevision,
    AdminRuntimeRevisionRequest, AdminRuntimeRevisionSelection, AdminScheduleAgencyWakeRequest,
    AdminScheduleAgencyWakeResult, AdminService, AdminTerminalizeWorkRequest,
    AdminTerminalizeWorkResult, AdminTimelineLogicalStatus, ApiError, ApiFuture, ApiResult,
    CatalogService, CatalogSnapshot, CausalQuery, CausalTraversal, CommittedEvent,
    CreateWorldFromTemplateRequest, CreateWorldFromTemplateResult, EntityTrajectoryQuery,
    EventPage, EventQuery, EventRef, ExecutionResult, FacetQuery, FacetSnapshot,
    ForkTimelineRequest, HistoryService, IngressAcceptance, IngressEnvelope, IngressId,
    IngressService, IngressStatusRecord, QueryService, RelationshipTrajectoryQuery,
    SubscriptionRequest, SubscriptionResult, SubscriptionService, TimelineService,
    TimelineSnapshot, TimelineTarget, TrajectoryPage, WorldService,
};
use loom_boundary::{RequireAdminAuthorization, router_with_admin as boundary_router_with_admin};
use loom_neutral::registry as neutral_registry;
use loom_runtime::{
    CapabilityRegistry, EntropyRequest, EntropySample, EntropySource, EntropySourceError,
    EntropySourceId, ExecutionSessionStore, PinnedWorldReadStore, PlatformClock, PlatformTime,
    Runtime, RuntimeControlStore, RuntimeRevisionCapability, RuntimeRevisionDescriptor,
    RuntimeRevisionError, RuntimeRevisionStore, SchedulerCommitStore, SemanticProjectionStore,
    WorkStore, WorldRuntimeBindingStore, WorldStore, WorldTimeStore,
};
use loom_storage::{BlobStoreInitError, LocalBlobStore, PgStorage};
use tokio::{net::TcpListener, sync::mpsc, time::sleep};
use tracing::{error, info};

use crate::{IngressWorker, SchedulerWorker, ServerConfig, ServerConfigError, ShutdownSignal};

/// Redacted startup/runtime failure for the application boundary.
#[derive(Debug)]
pub enum ServerError {
    /// Environment/configuration did not satisfy the startup contract.
    Config(ServerConfigError),
    /// A local filesystem operation failed.
    Filesystem,
    /// A database, migration, registry or revision startup gate failed.
    Startup { stage: &'static str },
    /// A worker surfaced an API-level authority failure.
    Worker { message: String },
    /// HTTP listener or graceful serving failed.
    Http,
}

impl std::fmt::Display for ServerError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Config(error) => error.fmt(formatter),
            Self::Filesystem => formatter.write_str("server filesystem initialization failed"),
            Self::Startup { stage } => {
                write!(formatter, "server startup validation failed at {stage}")
            }
            Self::Worker { message } => write!(formatter, "server worker failed: {message}"),
            Self::Http => formatter.write_str("server HTTP lifecycle failed"),
        }
    }
}

impl std::error::Error for ServerError {}

impl From<ServerConfigError> for ServerError {
    fn from(error: ServerConfigError) -> Self {
        Self::Config(error)
    }
}

/// Platform wall clock used only for operational metadata such as lease and
/// retry deadlines. It never supplies semantic World Time to Runtime.
#[derive(Clone, Copy, Debug, Default)]
pub struct SystemClock;

impl PlatformClock for SystemClock {
    fn now(&self) -> PlatformTime {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |duration| {
                i64::try_from(duration.as_millis()).unwrap_or(i64::MAX)
            });
        PlatformTime::new(millis)
    }
}

/// OS-backed entropy adapter held by Runtime and exposed to Capabilities only
/// through the mediated entropy request contract.
#[derive(Clone, Copy, Debug, Default)]
pub struct SystemEntropySource;

impl EntropySource for SystemEntropySource {
    fn source_id(&self) -> EntropySourceId {
        EntropySourceId::from("os-csprng")
    }

    fn sample(&self, request: &EntropyRequest) -> Result<EntropySample, EntropySourceError> {
        let mut bytes = vec![0_u8; request.byte_count()];
        getrandom::fill(&mut bytes)
            .map_err(|_| EntropySourceError::new("OS entropy source is unavailable"))?;
        Ok(EntropySample::new(bytes))
    }
}

/// Boundary-facing API wrapper that queues accepted Ingress identities for the
/// single bounded application worker while delegating every semantic method to
/// the same Runtime authority implementation.
pub struct ApplicationApi {
    runtime: Arc<Runtime<PgStorage>>,
    ingress_sender: mpsc::Sender<IngressId>,
}

impl ApplicationApi {
    fn new(runtime: Arc<Runtime<PgStorage>>, ingress_sender: mpsc::Sender<IngressId>) -> Self {
        Self {
            runtime,
            ingress_sender,
        }
    }
}

impl WorldService for ApplicationApi {
    fn create_world_from_template(
        &self,
        request: CreateWorldFromTemplateRequest,
    ) -> ApiFuture<'_, CreateWorldFromTemplateResult> {
        self.runtime.create_world_from_template(request)
    }
}

impl ActionService for ApplicationApi {
    fn invoke(&self, request: ActionRequest) -> ApiFuture<'_, ExecutionResult> {
        self.runtime.invoke(request)
    }
}

impl TimelineService for ApplicationApi {
    fn inspect_timeline(&self, target: TimelineTarget) -> ApiFuture<'_, TimelineSnapshot> {
        self.runtime.inspect_timeline(target)
    }

    fn fork(&self, request: ForkTimelineRequest) -> ApiFuture<'_, TimelineSnapshot> {
        Box::pin(self.runtime.fork(request))
    }
}

impl QueryService for ApplicationApi {
    fn get_facet(&self, query: FacetQuery) -> ApiFuture<'_, Option<FacetSnapshot>> {
        self.runtime.get_facet(query)
    }
}

impl HistoryService for ApplicationApi {
    fn list_events(&self, query: EventQuery) -> ApiFuture<'_, Vec<CommittedEvent>> {
        self.runtime.list_events(query)
    }

    fn list_events_page(&self, query: EventQuery) -> ApiFuture<'_, EventPage> {
        self.runtime.list_events_page(query)
    }

    fn get_event(&self, event_ref: EventRef) -> ApiFuture<'_, Option<CommittedEvent>> {
        self.runtime.get_event(event_ref)
    }

    fn direct_causes(&self, event_ref: EventRef) -> ApiFuture<'_, Vec<EventRef>> {
        self.runtime.direct_causes(event_ref)
    }

    fn direct_effects(&self, event_ref: EventRef) -> ApiFuture<'_, Vec<EventRef>> {
        self.runtime.direct_effects(event_ref)
    }

    fn causal_walk(&self, query: CausalQuery) -> ApiFuture<'_, CausalTraversal> {
        self.runtime.causal_walk(query)
    }

    fn entity_trajectory(&self, query: EntityTrajectoryQuery) -> ApiFuture<'_, TrajectoryPage> {
        self.runtime.entity_trajectory(query)
    }

    fn relationship_trajectory(
        &self,
        query: RelationshipTrajectoryQuery,
    ) -> ApiFuture<'_, TrajectoryPage> {
        self.runtime.relationship_trajectory(query)
    }
}

impl CatalogService for ApplicationApi {
    fn catalog(&self) -> ApiResult<CatalogSnapshot> {
        self.runtime.catalog()
    }

    fn catalog_for_world(&self, world_id: loom_api::WorldId) -> ApiFuture<'_, CatalogSnapshot> {
        self.runtime.catalog_for_world(world_id)
    }
}

impl SubscriptionService for ApplicationApi {
    fn subscribe(&self, request: SubscriptionRequest) -> ApiFuture<'_, SubscriptionResult> {
        self.runtime.subscribe(request)
    }
}

impl IngressService for ApplicationApi {
    fn submit_ingress(&self, request: IngressEnvelope) -> ApiFuture<'_, IngressAcceptance> {
        let runtime = Arc::clone(&self.runtime);
        let sender = self.ingress_sender.clone();
        Box::pin(async move {
            // Reserve before durable acceptance so a full worker queue applies
            // bounded backpressure instead of accepting an un-wakeable item.
            let permit = sender
                .reserve()
                .await
                .map_err(|_| ApiError::unavailable("Ingress worker is unavailable"))?;
            let acceptance = runtime.submit_ingress(request).await?;
            match &acceptance {
                IngressAcceptance::Accepted(receipt) | IngressAcceptance::Deduplicated(receipt) => {
                    permit.send(receipt.ingress_id.clone());
                }
                IngressAcceptance::IdempotencyConflict(_) => {}
            }
            Ok(acceptance)
        })
    }

    fn ingress_status(&self, ingress_id: IngressId) -> ApiFuture<'_, IngressStatusRecord> {
        self.runtime.ingress_status(ingress_id)
    }
}

impl AdminService for ApplicationApi {
    fn active_runtime_revision(&self) -> AdminFuture<'_, Option<AdminRuntimeRevisionSelection>> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::active_runtime_revision(runtime_api).await
        })
    }

    fn list_runtime_revisions(&self) -> AdminFuture<'_, Vec<AdminRuntimeRevision>> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::list_runtime_revisions(runtime_api).await
        })
    }

    fn get_runtime_revision(
        &self,
        request: AdminRuntimeRevisionRequest,
    ) -> AdminFuture<'_, AdminRuntimeRevision> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::get_runtime_revision(runtime_api, request).await
        })
    }

    fn activate_runtime_revision(
        &self,
        request: AdminActivateRuntimeRevisionRequest,
    ) -> AdminFuture<'_, AdminRuntimeRevisionSelection> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::activate_runtime_revision(runtime_api, request).await
        })
    }

    fn list_execution_sessions(&self) -> AdminFuture<'_, Vec<AdminExecutionSession>> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::list_execution_sessions(runtime_api).await
        })
    }

    fn get_execution_session(
        &self,
        request: AdminExecutionSessionRequest,
    ) -> AdminFuture<'_, AdminExecutionSession> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::get_execution_session(runtime_api, request).await
        })
    }

    fn session_for_event(&self, event_ref: EventRef) -> AdminFuture<'_, AdminEventSessionLookup> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::session_for_event(runtime_api, event_ref).await
        })
    }

    fn timeline_logical_status(
        &self,
        target: TimelineTarget,
    ) -> AdminFuture<'_, AdminTimelineLogicalStatus> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::timeline_logical_status(runtime_api, target).await
        })
    }

    fn missing_implementation(
        &self,
        request: AdminMissingImplementationRequest,
    ) -> AdminFuture<'_, Option<AdminMissingImplementationBlock>> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::missing_implementation(runtime_api, request).await
        })
    }

    fn terminalize_work(
        &self,
        request: AdminTerminalizeWorkRequest,
    ) -> AdminFuture<'_, AdminTerminalizeWorkResult> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::terminalize_work(runtime_api, request).await
        })
    }

    fn schedule_agency_wake(
        &self,
        request: AdminScheduleAgencyWakeRequest,
    ) -> AdminFuture<'_, AdminScheduleAgencyWakeResult> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::schedule_agency_wake(runtime_api, request).await
        })
    }

    fn advance_world_time(
        &self,
        request: AdminAdvanceWorldTimeRequest,
    ) -> AdminFuture<'_, AdminAdvanceWorldTimeResult> {
        Box::pin(async move {
            let runtime_api = &*self.runtime;
            loom_api::AdminService::advance_world_time(runtime_api, request).await
        })
    }
}

/// The assembled production-like Loom server.
pub struct LoomServer {
    config: ServerConfig,
    router: Router,
    storage: PgStorage,
    // Keeping this handle alive makes the BlobStore part of the composition
    // root lifetime even though current public API routes do not read blobs.
    _blob_store: Arc<dyn loom_runtime::BlobStore>,
    ingress_worker: Option<IngressWorker<PgStorage, SystemClock>>,
    scheduler_worker: Option<SchedulerWorker<PgStorage, SystemClock>>,
    shutdown: ShutdownSignal,
}

impl LoomServer {
    /// Connects, migrates and validates the complete native/container startup
    /// path before returning a server that can bind its HTTP listener.
    ///
    /// # Errors
    ///
    /// Returns a redacted startup error when the database, migrations, local
    /// `BlobStore`, registry or Runtime Revision cannot be validated.
    #[expect(
        clippy::too_many_lines,
        reason = "the composition root keeps startup gates and worker assembly together"
    )]
    pub async fn build(config: ServerConfig) -> Result<Self, ServerError> {
        fs::create_dir_all(config.blob_dir()).map_err(|_| ServerError::Filesystem)?;
        let blob_store = LocalBlobStore::new(config.blob_dir()).map_err(map_blob_error)?;
        let storage = PgStorage::connect(&config.database_url)
            .await
            .map_err(|_| ServerError::Startup {
                stage: "database connection",
            })?;
        storage.health().await.map_err(|_| ServerError::Startup {
            stage: "database health",
        })?;
        storage.migrate().await.map_err(|_| ServerError::Startup {
            stage: "database migrations",
        })?;
        storage.health().await.map_err(|_| ServerError::Startup {
            stage: "database health after migrations",
        })?;

        let registry = installed_registry()?;
        let now = SystemClock.now();
        let candidate_revision = RuntimeRevisionDescriptor::new(
            config.revision_id.clone(),
            now,
            config.core_build_ref.clone(),
            registry.loom_version().clone(),
            registry.capabilities().map(|manifest| {
                RuntimeRevisionCapability::from_manifest(
                    manifest,
                    format!("{}@{}", manifest.id, manifest.version),
                )
            }),
        )
        .map_err(|_| ServerError::Startup {
            stage: "Runtime Revision descriptor",
        })?;

        let runtime = Runtime::new(storage.clone(), registry)
            .map_err(|_| ServerError::Startup {
                stage: "Runtime assembly",
            })?
            .with_platform_clock(SystemClock)
            .with_entropy_source(SystemEntropySource)
            .with_resolution_budget(config.resolution_budget)
            .with_history_budget(config.history_budget)
            .with_failure_policy(config.failure_policy)
            .with_chronology_budget(config.chronology_budget);
        let revision =
            match RuntimeRevisionStore::read_revision(&storage, config.revision_id.clone().into())
                .await
            {
                Ok(existing) => {
                    ensure_candidate_revision_matches_published(&candidate_revision, &existing)?;
                    existing
                }
                Err(RuntimeRevisionError::RevisionNotFound { .. }) => candidate_revision,
                Err(error) => return Err(map_revision_error(error)),
            };
        let revision = runtime
            .confirm_runtime_revision(revision)
            .await
            .map_err(map_revision_error)?;
        ensure_active_revision(&runtime, &revision).await?;

        // Each Runtime instance owns the same concrete PgStorage authority and
        // the same executor/topology contract; PostgreSQL CAS/fences remain the
        // sole cross-worker authority rather than an in-process mutex.
        let scheduler_runtime = Runtime::new(storage.clone(), installed_registry()?)
            .map_err(|_| ServerError::Startup {
                stage: "Scheduler Runtime assembly",
            })?
            .with_platform_clock(SystemClock)
            .with_entropy_source(SystemEntropySource)
            .with_resolution_budget(config.resolution_budget)
            .with_history_budget(config.history_budget)
            .with_failure_policy(config.failure_policy)
            .with_chronology_budget(config.chronology_budget);
        let ingress_runtime = Runtime::new(storage.clone(), installed_registry()?)
            .map_err(|_| ServerError::Startup {
                stage: "Ingress Runtime assembly",
            })?
            .with_platform_clock(SystemClock)
            .with_entropy_source(SystemEntropySource)
            .with_resolution_budget(config.resolution_budget)
            .with_history_budget(config.history_budget)
            .with_failure_policy(config.failure_policy)
            .with_chronology_budget(config.chronology_budget);

        let (ingress_sender, ingress_receiver) = mpsc::channel(config.ingress_queue_capacity);
        let recovery_ids = ingress_runtime
            .list_recoverable_ingress_ids(now, config.ingress_queue_capacity)
            .await
            .map_err(|_| ServerError::Startup {
                stage: "Ingress recovery enumeration",
            })?;
        for ingress_id in recovery_ids {
            ingress_sender
                .try_send(ingress_id)
                .map_err(|_| ServerError::Startup {
                    stage: "Ingress recovery queue",
                })?;
        }
        let shutdown = ShutdownSignal::new();
        let api = Arc::new(ApplicationApi::new(Arc::new(runtime), ingress_sender));
        let router = boundary_router_with_admin(
            Arc::clone(&api),
            Arc::new(RequireAdminAuthorization),
            config.boundary_config,
        );
        let ingress_worker = Some(IngressWorker::new(
            ingress_runtime,
            ingress_receiver,
            SystemClock,
            config.worker_config,
            config.worker_poll_interval,
            shutdown.clone(),
        ));
        let scheduler_worker = config.scheduler_target.map(|target| {
            SchedulerWorker::new(
                scheduler_runtime,
                target,
                SystemClock,
                config.worker_config,
                shutdown.clone(),
            )
        });

        Ok(Self {
            config,
            router,
            storage,
            _blob_store: Arc::new(blob_store),
            ingress_worker,
            scheduler_worker,
            shutdown,
        })
    }

    /// Returns a clone of the fully assembled Boundary router for embedding or
    /// black-box tests without starting the process supervisor.
    pub fn router(&self) -> Router {
        self.router.clone()
    }

    /// Runs HTTP, Ingress and optional Scheduler loops under one graceful
    /// shutdown signal. No worker is spawned per request; each queue/loop is
    /// bounded and uses the shared `PostgreSQL` authority contracts.
    ///
    /// # Errors
    ///
    /// Returns when the HTTP listener, worker authority or graceful lifecycle
    /// cannot complete.
    pub async fn run(self) -> Result<(), ServerError> {
        let listener = TcpListener::bind(self.config.bind_addr)
            .await
            .map_err(|_| ServerError::Http)?;
        info!(address = %self.config.bind_addr, data_root = ?self.config.data_dir(), "loom-server listening");

        let Self {
            config,
            router,
            storage,
            _blob_store,
            ingress_worker,
            scheduler_worker,
            shutdown,
        } = self;
        let serve_shutdown = shutdown.clone();
        let serve = async move {
            let result = axum::serve(listener, router)
                .with_graceful_shutdown(wait_for_shutdown(serve_shutdown.clone()))
                .await;
            serve_shutdown.request();
            result.map_err(|_| ServerError::Http)
        };

        let ingress_shutdown = shutdown.clone();
        let ingress_poll = async move {
            let Some(mut worker) = ingress_worker else {
                return Ok(());
            };
            let result = worker
                .run_until_shutdown()
                .await
                .map_err(|error| ServerError::Worker {
                    message: error.message,
                });
            if result.is_err() {
                ingress_shutdown.request();
            }
            result
        };

        let scheduler_shutdown = shutdown.clone();
        let scheduler_poll = async move {
            let Some(mut worker) = scheduler_worker else {
                return Ok(());
            };
            let result = run_scheduler_until_shutdown(
                &mut worker,
                config.worker_poll_interval,
                config.worker_config.scheduler_poll_limit(),
                scheduler_shutdown.clone(),
            )
            .await
            .map_err(|error| ServerError::Worker {
                message: error.message,
            });
            if result.is_err() {
                scheduler_shutdown.request();
            }
            result
        };

        let (serve_result, ingress_result, scheduler_result) =
            tokio::join!(serve, ingress_poll, scheduler_poll);
        storage.close().await;
        serve_result.and(ingress_result).and(scheduler_result)
    }
}

/// Loads environment configuration, assembles the server, and runs it.
///
/// # Errors
///
/// Returns a redacted configuration, startup, worker or HTTP lifecycle error.
pub async fn run_from_env() -> Result<(), ServerError> {
    let config = ServerConfig::from_env()?;
    let server = LoomServer::build(config).await?;
    Box::pin(server.run()).await
}

async fn run_scheduler_until_shutdown<S>(
    worker: &mut SchedulerWorker<S, SystemClock>,
    poll_interval: std::time::Duration,
    poll_limit: usize,
    shutdown: ShutdownSignal,
) -> ApiResult<()>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore
        + RuntimeControlStore
        + SchedulerCommitStore
        + WorldTimeStore
        + SemanticProjectionStore
        + PinnedWorldReadStore,
{
    while !shutdown.is_requested() {
        worker.run_bounded(poll_limit).await?;
        sleep(poll_interval).await;
    }
    Ok(())
}

async fn ensure_active_revision(
    runtime: &Runtime<PgStorage>,
    revision: &RuntimeRevisionDescriptor,
) -> Result<(), ServerError> {
    match runtime.validate_active_runtime_revision().await {
        Ok(active) if active.revision() == revision => Ok(()),
        Ok(_) => Err(ServerError::Startup {
            stage: "active Runtime Revision selection",
        }),
        Err(RuntimeRevisionError::NoActiveRevision) => runtime
            .activate_runtime_revision(revision.id().clone(), None, SystemClock.now())
            .await
            .map(|_| ())
            .map_err(map_revision_error),
        Err(error) => Err(map_revision_error(error)),
    }
}

fn ensure_candidate_revision_matches_published(
    candidate: &RuntimeRevisionDescriptor,
    published: &RuntimeRevisionDescriptor,
) -> Result<(), ServerError> {
    // The startup candidate is freshly timestamped; publication time is
    // immutable history metadata and is intentionally excluded from this
    // software identity comparison.
    let matches = candidate.id() == published.id()
        && candidate.core_build_ref() == published.core_build_ref()
        && candidate.loom_version() == published.loom_version()
        && candidate.capabilities() == published.capabilities()
        && candidate.execution_policy_id() == published.execution_policy_id()
        && candidate.provider_policy_id() == published.provider_policy_id()
        && candidate.change_summary() == published.change_summary()
        && candidate.semantic_behavior_changed() == published.semantic_behavior_changed();
    if matches {
        Ok(())
    } else {
        Err(ServerError::Startup {
            stage: "Runtime Revision candidate validation",
        })
    }
}

async fn wait_for_shutdown(shutdown: ShutdownSignal) {
    tokio::select! {
        () = shutdown.wait() => {}
        result = tokio::signal::ctrl_c() => {
            if let Err(error) = result {
                error!(%error, "failed to install Ctrl-C handler; waiting for process shutdown signal");
            }
        }
        () = wait_for_unix_shutdown_signal() => {}
    }
    shutdown.request();
}

#[cfg(unix)]
async fn wait_for_unix_shutdown_signal() {
    match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
        Ok(mut signal) => {
            signal.recv().await;
        }
        Err(error) => {
            error!(%error, "failed to install SIGTERM handler");
            std::future::pending::<()>().await;
        }
    }
}

#[cfg(not(unix))]
async fn wait_for_unix_shutdown_signal() {
    std::future::pending::<()>().await;
}

fn map_blob_error(_error: BlobStoreInitError) -> ServerError {
    ServerError::Startup {
        stage: "local BlobStore initialization",
    }
}

fn map_revision_error(_error: RuntimeRevisionError) -> ServerError {
    ServerError::Startup {
        stage: "Runtime Revision registration/selection",
    }
}

fn installed_registry() -> Result<CapabilityRegistry, ServerError> {
    let registry = neutral_registry();
    registry.validate().map_err(|_| ServerError::Startup {
        stage: "Capability registry",
    })?;
    Ok(registry)
}

#[cfg(test)]
mod tests {
    use loom_runtime::{PlatformTime, RuntimeRevisionCapability, RuntimeRevisionDescriptor};

    use super::{ServerError, ensure_candidate_revision_matches_published, installed_registry};

    fn revision(
        core_build_ref: &str,
        implementation_override: Option<&str>,
    ) -> RuntimeRevisionDescriptor {
        let registry = installed_registry().expect("the installed test registry should validate");
        let first_capability = registry
            .capabilities()
            .next()
            .expect("the installed test registry should contain a Capability")
            .id
            .clone();
        let capabilities = registry.capabilities().map(|manifest| {
            let implementation_id = if manifest.id == first_capability {
                implementation_override
                    .unwrap_or("neutral-test@expected")
                    .to_owned()
            } else {
                format!("{}@{}", manifest.id, manifest.version)
            };
            RuntimeRevisionCapability::from_manifest(manifest, implementation_id)
        });
        RuntimeRevisionDescriptor::new(
            "loom-server-restart-test",
            PlatformTime::new(1),
            core_build_ref,
            registry.loom_version().clone(),
            capabilities,
        )
        .expect("the test Runtime Revision descriptor should be valid")
    }

    #[test]
    fn startup_accepts_same_build_after_restart_despite_new_publication_time() {
        let persisted_build_one = revision("build-1", None);
        let restarted_build_one = revision("build-1", None);

        ensure_candidate_revision_matches_published(&restarted_build_one, &persisted_build_one)
            .expect("a restart with the same registered build should reuse the publication");
    }

    #[test]
    fn startup_rejects_same_revision_id_when_restart_changes_core_build_ref() {
        let persisted_build_one = revision("build-1", None);
        let restarted_build_two = revision("build-2", None);

        assert!(matches!(
            ensure_candidate_revision_matches_published(&restarted_build_two, &persisted_build_one),
            Err(ServerError::Startup {
                stage: "Runtime Revision candidate validation"
            })
        ));
    }

    #[test]
    fn startup_rejects_same_revision_id_when_restart_changes_implementation_identity() {
        let persisted_build_one = revision("build-1", None);
        let restarted_with_different_implementation =
            revision("build-1", Some("implementation-build-2"));

        assert!(matches!(
            ensure_candidate_revision_matches_published(
                &restarted_with_different_implementation,
                &persisted_build_one,
            ),
            Err(ServerError::Startup {
                stage: "Runtime Revision candidate validation"
            })
        ));
    }
}
