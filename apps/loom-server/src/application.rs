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
    BlobReadRequest, BlobReadResult, CatalogService, CatalogSnapshot, CausalQuery, CausalTraversal,
    CommittedEvent, CreateWorldFromTemplateRequest, CreateWorldFromTemplateResult,
    EntityTrajectoryQuery, EventPage, EventQuery, EventRef, ExecutionResult, FacetQuery,
    FacetSnapshot, ForkTimelineRequest, HistoryService, IngressAcceptance, IngressEnvelope,
    IngressId, IngressService, IngressStatusRecord, QueryService, RelationshipTrajectoryQuery,
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
use tokio::{net::TcpListener, sync::mpsc};
use tracing::{error, info};

use crate::{IngressWorker, SchedulerSupervisor, ServerConfig, ServerConfigError, ShutdownSignal};

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

    fn query_semantic_projection(
        &self,
        query: loom_api::SemanticProjectionQuery,
    ) -> ApiFuture<'_, loom_api::SemanticProjectionRead> {
        loom_api::QueryService::query_semantic_projection(&*self.runtime, query)
    }

    fn read_blob(&self, request: BlobReadRequest) -> ApiFuture<'_, BlobReadResult> {
        loom_api::QueryService::read_blob(&*self.runtime, request)
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
    scheduler_supervisor: SchedulerSupervisor<PgStorage, SystemClock>,
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
            .with_chronology_budget(config.chronology_budget)
            .with_blob_store(blob_store.clone());
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
        let scheduler_supervisor = SchedulerSupervisor::new(
            scheduler_runtime,
            SystemClock,
            config.worker_config,
            shutdown.clone(),
        );

        Ok(Self {
            config,
            router,
            storage,
            _blob_store: Arc::new(blob_store),
            ingress_worker,
            scheduler_supervisor,
            shutdown,
        })
    }

    /// Returns a clone of the fully assembled Boundary router for embedding or
    /// black-box tests without starting the process supervisor.
    pub fn router(&self) -> Router {
        self.router.clone()
    }

    /// Runs HTTP, Ingress and automatic Scheduler supervision under one
    /// graceful shutdown signal. No worker is spawned per request; each
    /// queue/loop is bounded and uses the shared `PostgreSQL` authority
    /// contracts.
    ///
    /// # Errors
    ///
    /// Returns when the HTTP listener, worker authority or graceful lifecycle
    /// cannot complete.
    pub async fn run(self) -> Result<(), ServerError> {
        let listener = TcpListener::bind(self.config.bind_addr)
            .await
            .map_err(|_| ServerError::Http)?;
        Box::pin(self.run_with_listener(listener)).await
    }

    /// Runs the assembled server on an already-bound listener.
    ///
    /// The composition and lifecycle are identical to [`Self::run`]. Keeping
    /// listener ownership injectable lets the focused integration gate reserve
    /// an OS-assigned port before it starts the real HTTP boundary, without
    /// adding a deployment setting or a second server path.
    async fn run_with_listener(self, listener: TcpListener) -> Result<(), ServerError> {
        info!(address = %self.config.bind_addr, data_root = ?self.config.data_dir(), "loom-server listening");

        let Self {
            config,
            router,
            storage,
            _blob_store,
            ingress_worker,
            scheduler_supervisor,
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
            run_scheduler_supervisor_until_shutdown(
                scheduler_supervisor,
                config.worker_poll_interval,
                scheduler_shutdown,
            )
            .await
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

async fn run_scheduler_supervisor_until_shutdown<S, C>(
    mut supervisor: SchedulerSupervisor<S, C>,
    poll_interval: std::time::Duration,
    shutdown: ShutdownSignal,
) -> Result<(), ServerError>
where
    S: loom_runtime::SchedulerDiscoveryStore
        + WorldStore
        + WorldRuntimeBindingStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore
        + RuntimeControlStore
        + SchedulerCommitStore
        + WorldTimeStore
        + SemanticProjectionStore
        + PinnedWorldReadStore,
    C: PlatformClock,
{
    let result = supervisor
        .run_until_shutdown(poll_interval)
        .await
        .map_err(|error| ServerError::Worker {
            message: error.message,
        });
    if result.is_err() {
        shutdown.request();
    }
    result
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
    use loom_api::{
        ActionRequest, ActionService, AdminService, AdminWorkStatus,
        CreateWorldFromTemplateRequest, EventQuery, FacetQuery, HistoryService, QueryService,
        WorldService, WorldTemplateDescriptor,
    };
    use loom_capability::CapabilityRegistry;
    use loom_client::LoomClient;
    use loom_core::{
        ActionTypeId, EntityId, EventId, FacetOwner, FacetTypeId, SchemaRevision, TimelineId,
        WorkHandlerId, WorkId, WorldId, WorldInstant,
    };
    use loom_protocol::ActionInvocation;
    use loom_runtime::{
        ChronologyBudgetPolicy, FailurePolicy, HistoryBudget, ManualPlatformClock, PlatformTime,
        ResolutionBudget, Runtime, RuntimeRevisionCapability, RuntimeRevisionDescriptor,
        WorkRecord, WorkStatus, WorkTarget,
    };
    use loom_storage::InMemoryStore;
    use serde_json::json;
    use std::{
        net::SocketAddr,
        path::{Path, PathBuf},
        process,
        sync::atomic::{AtomicU64, Ordering},
        time::{Duration, Instant},
    };

    static NEXT_FIXTURE: AtomicU64 = AtomicU64::new(1);

    use super::{
        LoomServer, ServerError, SystemClock, ensure_candidate_revision_matches_published,
        installed_registry, run_scheduler_supervisor_until_shutdown,
    };
    use crate::{SchedulerSupervisor, ServerConfig, ShutdownSignal, WorkerConfig};

    fn id<T>(value: u128) -> T
    where
        T: std::str::FromStr,
        T::Err: std::fmt::Debug,
    {
        format!("00000000-0000-0000-0000-{value:012x}")
            .parse()
            .expect("test identity should parse")
    }

    fn pending_work(timeline_id: TimelineId, work_id: WorkId) -> WorkRecord {
        WorkRecord {
            id: work_id,
            timeline_id,
            target: WorkTarget::CapabilityWork {
                owner: None,
                handler: WorkHandlerId::from("missing.scheduler.handler"),
            },
            schema_revision: SchemaRevision::new(1),
            payload: false.into(),
            effective_due_world_time: WorldInstant::default(),
            logical_schedule_order: 1,
            causal_event_id: None,
            origin_work_id: None,
            status: WorkStatus::Pending,
            attempt_count: 0,
            claim_generation: 0,
            available_at: PlatformTime::default(),
            last_error: None,
            lease: None,
        }
    }

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

    fn postgres_test_config(database_url: String, data_dir: PathBuf) -> ServerConfig {
        ServerConfig {
            database_url,
            bind_addr: SocketAddr::from(([127, 0, 0, 1], 0)),
            data_dir,
            revision_id: "scheduler-t18-test".to_owned(),
            core_build_ref: "scheduler-t18-test-build".to_owned(),
            worker_config: WorkerConfig::new(30_000, 0)
                .expect("test worker timing should be valid")
                .with_scheduler_poll_limit(1)
                .expect("test scheduler poll bound should be valid"),
            worker_poll_interval: Duration::from_secs(1),
            ingress_queue_capacity: 16,
            boundary_config: loom_boundary::BoundaryConfig::default(),
            resolution_budget: ResolutionBudget::default(),
            history_budget: HistoryBudget::default(),
            failure_policy: FailurePolicy::new(3, 0).expect("test failure policy should be valid"),
            chronology_budget: ChronologyBudgetPolicy::new(8),
        }
    }

    fn unique_data_dir() -> PathBuf {
        let fixture = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../target")
            .join(format!("loom-server-t18-{}-{fixture}", process::id()))
    }

    fn scheduler_environment() -> [Option<std::ffi::OsString>; 2] {
        ["LOOM_SCHEDULER_WORLD_ID", "LOOM_SCHEDULER_TIMELINE_ID"].map(std::env::var_os)
    }

    fn assert_no_fixed_scheduler_environment() {
        for name in ["LOOM_SCHEDULER_WORLD_ID", "LOOM_SCHEDULER_TIMELINE_ID"] {
            assert!(
                std::env::var_os(name).is_none(),
                "T18 must run without fixed Scheduler target variable {name}"
            );
        }
    }

    async fn wait_for_public_server(client: &LoomClient) {
        for _ in 0..100 {
            if let Ok(Some(_)) = client.active_runtime_revision().await {
                return;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        panic!("the real LoomServer did not become reachable through its public Admin API");
    }

    async fn wait_for_scheduler_completion(
        client: &LoomClient,
        target: loom_api::TimelineTarget,
        entity_id: EntityId,
        work_id: WorkId,
    ) -> (
        loom_api::AdminTimelineLogicalStatus,
        loom_api::FacetSnapshot,
        Vec<loom_api::CommittedEvent>,
    ) {
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            let status = client
                .timeline_logical_status(target)
                .await
                .expect("Timeline logical status should remain publicly readable");
            let facet = client
                .get_facet(FacetQuery::new(
                    target,
                    FacetOwner::entity(entity_id),
                    FacetTypeId::from(loom_neutral::COUNTER_FACET),
                ))
                .await
                .expect("Scheduler-updated Facet should remain publicly readable")
                .expect("Scheduler-updated counter Facet should exist");
            let history = client
                .list_events(EventQuery::all(target))
                .await
                .expect("Scheduler-produced History should remain publicly readable");
            let counter_value = facet.value["value"].as_i64().unwrap_or_default();
            let increment_count = history
                .iter()
                .filter(|event| {
                    event.event_type
                        == loom_api::EventTypeId::from(loom_neutral::COUNTER_INCREMENTED_EVENT)
                })
                .count();
            let completed = status
                .works
                .iter()
                .any(|work| work.work_id == work_id && work.status == AdminWorkStatus::Completed);
            if completed && counter_value >= 3 && increment_count >= 2 {
                return (status, facet, history);
            }

            assert!(
                Instant::now() < deadline,
                "Scheduler did not complete the discovered Work through public surfaces: status={status:?}, facet={facet:?}, history_len={} ",
                history.len()
            );
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
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

    #[expect(
        clippy::too_many_lines,
        reason = "the focused live gate keeps its public workflow readable in one scenario"
    )]
    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn world_created_after_server_start_is_auto_scheduled_over_public_http() {
        assert_no_fixed_scheduler_environment();

        let database = loom_storage::test_support::TestDatabase::provision("scheduler-t18").await;
        let data_dir = unique_data_dir();
        let config = postgres_test_config(database.database_url().to_owned(), data_dir.clone());
        let config_before = format!("{config:?}");
        let scheduler_environment_before = scheduler_environment();

        let server = LoomServer::build(config.clone())
            .await
            .expect("real LoomServer should start against PostgreSQL 18");
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("the test HTTP listener should bind");
        let address = listener
            .local_addr()
            .expect("the test HTTP listener should expose its address");
        let shutdown = server.shutdown.clone();
        let client = LoomClient::builder(format!("http://{address}"))
            .admin_token("scheduler-t18-test-admin")
            .expect("test Admin token should be representable")
            .build()
            .expect("public Loom client should build");

        let workflow = async {
            wait_for_public_server(&client).await;
            let active_before_world = client
                .active_runtime_revision()
                .await
                .expect("active Runtime Revision should be readable before World creation");
            assert!(
                active_before_world.is_some(),
                "the server must be serving before the World is created"
            );

            let entity_id: EntityId = id(0x1801);
            let seed_event_id: EventId = id(0x1802);
            let increment_event_id: EventId = id(0x1803);
            let created = client
                .create_world_from_template(CreateWorldFromTemplateRequest::new(
                    WorldTemplateDescriptor::new("scheduler-t18-world", 1, WorldInstant::default())
                        .requires_capability(loom_neutral::COUNTER_CAPABILITY, "^0.1.0")
                        .with_bootstrap_action(ActionInvocation::new(
                            ActionTypeId::from(loom_neutral::COUNTER_SEED_ACTION),
                            json!({
                                "event_id": seed_event_id.to_string(),
                                "entity_id": entity_id.to_string(),
                                "value": 1,
                            }),
                        )),
                ))
                .await
                .expect("World creation should cross the public HTTP boundary");
            let target = created.target;

            let initial_facet = client
                .get_facet(FacetQuery::new(
                    target,
                    FacetOwner::entity(entity_id),
                    FacetTypeId::from(loom_neutral::COUNTER_FACET),
                ))
                .await
                .expect("the created World Facet should be publicly readable")
                .expect("the bootstrap counter Facet should exist");
            assert_eq!(initial_facet.value["value"], json!(1));

            let direct_action = client
                .invoke(ActionRequest::new(
                    target,
                    ActionInvocation::new(
                        ActionTypeId::from(loom_neutral::COUNTER_INCREMENT_ACTION),
                        json!({
                            "event_id": increment_event_id.to_string(),
                            "entity_id": entity_id.to_string(),
                            "amount": 1,
                        }),
                    ),
                ))
                .await
                .expect("the public Action should commit and schedule its Reaction Work");
            assert!(
                matches!(direct_action, loom_api::ExecutionResult::Committed { .. }),
                "the seed follow-up Action should commit before Scheduler observation"
            );

            let pending_status = client
                .timeline_logical_status(target)
                .await
                .expect("Pending Work should be observable through the public Admin surface");
            let pending_work_id = pending_status
                .works
                .iter()
                .find(|work| work.status == AdminWorkStatus::Pending)
                .map(|work| work.work_id)
                .expect("the public status read should observe the Reaction Pending Work");

            let (final_status, final_facet, final_history) =
                wait_for_scheduler_completion(&client, target, entity_id, pending_work_id).await;
            let completed_work = final_status
                .works
                .iter()
                .find(|work| work.work_id == pending_work_id)
                .expect("the observed Work should remain in the public status read");
            assert_eq!(completed_work.status, AdminWorkStatus::Completed);
            assert!(
                final_facet.value["value"].as_i64().unwrap_or_default() >= 3,
                "the Scheduler Work should advance the public counter Facet"
            );
            assert!(
                final_history
                    .iter()
                    .filter(|event| {
                        event.event_type
                            == loom_api::EventTypeId::from(loom_neutral::COUNTER_INCREMENTED_EVENT)
                    })
                    .count()
                    >= 2,
                "History should include both the direct increment and Scheduler Work increment"
            );
            assert!(
                final_history.iter().any(|event| {
                    event.event_type
                        == loom_api::EventTypeId::from(loom_neutral::COUNTER_INCREMENTED_EVENT)
                        && event.payload["value"].as_i64() == Some(3)
                }),
                "History should expose the Scheduler-produced increment at value 3"
            );

            shutdown.request();
        };

        let (server_result, ()) = tokio::join!(server.run_with_listener(listener), workflow);
        assert!(
            server_result.is_ok(),
            "real LoomServer should stop cleanly after the public observation: {server_result:?}"
        );
        assert_eq!(
            config_before,
            format!("{config:?}"),
            "ServerConfig must remain unchanged through World creation and Scheduler completion"
        );
        assert_eq!(
            scheduler_environment_before,
            scheduler_environment(),
            "the test must not mutate fixed Scheduler target environment"
        );

        database.cleanup().await;
        std::fs::remove_dir_all(&data_dir).expect("test BlobStore data should be removable");
    }

    #[tokio::test(flavor = "current_thread")]
    async fn scheduler_supervisor_failure_requests_shared_server_shutdown() {
        let store = InMemoryStore::new();
        let world_id: WorldId = id(0x100);
        let timeline_id: TimelineId = id(0x101);
        store
            .create_timeline(world_id, timeline_id)
            .expect("test Timeline should be created");
        store
            .seed_work(pending_work(timeline_id, id(0x102)))
            .expect("Pending Work should be seeded");
        let runtime = Runtime::new(&store, CapabilityRegistry::new())
            .expect("empty registry should assemble");
        let shutdown = ShutdownSignal::new();
        let supervisor = SchedulerSupervisor::new(
            runtime,
            SystemClock,
            WorkerConfig::new(10, 1).expect("worker timings should be valid"),
            shutdown.clone(),
        );

        let result = run_scheduler_supervisor_until_shutdown(
            supervisor,
            Duration::from_millis(1),
            shutdown.clone(),
        )
        .await;

        assert!(matches!(result, Err(ServerError::Worker { .. })));
        assert!(shutdown.is_requested());
    }

    #[test]
    fn scheduler_supervisor_uses_no_fixed_target_for_an_empty_store() {
        let runtime = Runtime::new(InMemoryStore::new(), CapabilityRegistry::new())
            .expect("empty registry should assemble");
        let supervisor = SchedulerSupervisor::new(
            runtime,
            ManualPlatformClock::new(PlatformTime::new(7)),
            WorkerConfig::new(10, 1).expect("worker timings should be valid"),
            ShutdownSignal::new(),
        );

        assert!(!supervisor.shutdown_signal().is_requested());
    }
}
