//! Runtime orchestration over the unified API, Capability registry and ports.
//!
//! This module owns the composition that turns one public Action or Durable
//! Work execution into the existing Runtime validation and persistence path.
//! It does not define a second protocol, storage boundary or public endpoint.

use std::{
    cell::RefCell,
    collections::{BTreeMap, HashSet},
    future::Future,
    pin::Pin,
    rc::Rc,
    sync::{Arc, Mutex},
};

use loom_agency::{
    AgentContextRequest, AgentRef, AgentWorldView, CognitiveExecutor, CognitiveMetadata, Decision,
    DecisionReusePolicy, ExecutionPolicy,
};
use loom_api::{
    ActionDescriptor, ActionRequest, ActionService, AdminActivateRuntimeRevisionRequest,
    AdminAdvanceWorldTimeRequest, AdminAdvanceWorldTimeResult, AdminChronologyBudget,
    AdminCognitiveDisposition, AdminCognitiveEvidence, AdminCognitiveObservation,
    AdminCognitiveOutcome, AdminCommitProvenance, AdminDecisionReusePolicy, AdminEntropyEvidence,
    AdminEntropyObservation, AdminEventSessionLookup, AdminExecutionOrigin, AdminExecutionRoot,
    AdminExecutionSession, AdminExecutionSessionRequest, AdminExecutionSessionStatus,
    AdminLogicalWorkStatus, AdminMissingImplementationBlock, AdminMissingImplementationRequest,
    AdminReadDependency, AdminResolutionCallEdge, AdminRuntimeRevision,
    AdminRuntimeRevisionCapability, AdminRuntimeRevisionRequest, AdminRuntimeRevisionSelection,
    AdminScheduleAgencyWakeRequest, AdminScheduleAgencyWakeResult, AdminService,
    AdminTerminalWorkState, AdminTerminalizeWorkRequest, AdminTerminalizeWorkResult,
    AdminTimelineLogicalStatus, AdminWorkStatus, ApiError, ApiFuture, ApiResult,
    BlobReadRequest as ApiBlobReadRequest, BlobReadResult as ApiBlobReadResult,
    BlobReference as ApiBlobReference, CatalogService, CatalogSnapshot, CausalDirection,
    CausalQuery, CausalTraversal, ChangeFeedCursor, ChangeFeedPage as ApiChangeFeedPage,
    CommittedEvent as ApiCommittedEvent, CreateWorldFromTemplateRequest,
    CreateWorldFromTemplateResult, EntityTrajectoryQuery, EventDescriptor, EventPage, EventQuery,
    ExecutionResult, FacetDescriptor, FacetQuery, FacetSnapshot as ApiFacetSnapshot,
    ForkTimelineRequest, HistoryService, IngressAcceptance, IngressCompletion, IngressEnvelope,
    IngressId, IngressService, IngressStatus, IngressStatusRecord, QueryService,
    ReactionDescriptor, RelationshipDescriptor, RelationshipRoleDescriptor,
    RelationshipTrajectoryQuery, SemanticIndexDescriptor,
    SemanticProjectionHit as ApiSemanticProjectionHit,
    SemanticProjectionQuery as ApiSemanticProjectionQuery,
    SemanticProjectionRead as ApiSemanticProjectionRead, SubscriptionBackpressure,
    SubscriptionRequest, SubscriptionResult, SubscriptionResume, SubscriptionService,
    TimelineService, TimelineSnapshot as ApiTimelineSnapshot, TimelineTarget, TrajectoryPage,
    WorkHandlerDescriptor, WorldService, WorldTemplateDescriptor,
};
use loom_capability::{
    CapabilityId, CapabilityRegistry, DispatchError, EntropyBudgetDimension, EntropyError,
    EntropyRequest, EntropySample, ResolutionContext, ResolutionContextError, ResolverError,
    SemanticQueryError, SemanticQueryRequest, SemanticQueryResult,
};
use loom_core::{ActionTypeId, EventId, EventRef, EventSeq, TimelineId, TimelineVersion, WorkId};
use loom_protocol::{
    ActionInvocation, NewWork, Resolution, ResolveOutcome, WorkMutation, WorkSchedule, WorkTarget,
};
use semver::VersionReq;
use serde_json::{Value, json};

use crate::{
    AdvanceWorldTime, AgentContextPlan, AgentWorldViewBuilder, BaseWorldSnapshot, BaseWorldView,
    BindingError, BlobError, BlobHash, BlobId, BlobMetadata, BlobRef, BlobStore, BudgetDimension,
    BudgetError, BudgetUsage, CallProvenance, CandidateWorldView, ChangeFeedStore,
    ChronologyBudgetExceeded, ChronologyBudgetPolicy, CognitiveAssembly, CognitiveDisposition,
    CognitiveEvidence, CognitiveGatewayError, CognitiveOutcome, CommitAuthorityContext,
    CommitError, CommitProvenance, CommitStore, CommittedEvent, EffectEngine, EntropyEvidence,
    EntropySource, EntropySourceId, ExecutionAssembly, ExecutionEvidence, ExecutionOrigin,
    ExecutionRoot, ExecutionSession, ExecutionSessionStatus, ExecutionSessionStore, FailurePolicy,
    ForkError, ForkMaterialization, ForkWork, HistoricalTimelineState, HistoryBudget,
    IdentityAllocator, IngressClaim, IngressError, IngressStore, IngressSubmission,
    IngressTechnicalFailure, LifecycleError, LogicalCommit, LogicalWorkState,
    LogicalWorkTransition, MAX_SEMANTIC_QUERY_DEPTH, MAX_SEMANTIC_QUERY_FILTERS,
    MAX_SEMANTIC_QUERY_RESULT_BYTES, ManualPlatformClock, PersistenceFuture, PinnedReadBoundary,
    PinnedReadPolicy, PinnedReadSession, PinnedWorldReadStore, PlatformClock, PlatformTime,
    ReadDependency, ReadError, ReadSet, ResolutionBudget, RuntimeControlStore, RuntimeError,
    RuntimeRevisionActivation, RuntimeRevisionAssembly, RuntimeRevisionDescriptor,
    RuntimeRevisionError, RuntimeRevisionId, RuntimeRevisionSelection, RuntimeRevisionStore,
    SchedulerCommitStore, SchedulerDiscoveryError, SchedulerDiscoveryPage,
    SchedulerDiscoveryRequest, SchedulerDiscoveryStore, SemanticProjectionError,
    SemanticProjectionFilter, SemanticProjectionHit, SemanticProjectionKey,
    SemanticProjectionQuery, SemanticProjectionRebuild, SemanticProjectionRegistration,
    SemanticProjectionStore, SessionError, TimelineBlockedOnMissingImplementation,
    TimelineDriverBlock, TimelineDriverResult, TimelineFork, TimelineForkStore, TimelineSnapshot,
    UnavailableEntropySource, UuidV7IdentityAllocator, ValidatedResolution, ValidationError,
    WorkClaim, WorkError, WorkRecord, WorkStatus, WorkStore, WorkTerminalState,
    WorkTerminalization, WorldLifecycleStore, WorldRuntimeBinding, WorldRuntimeBindingStore,
    WorldStore, WorldTimeError, WorldTimeStore, WorldTimeTransition, semantic_projection_hit_bytes,
};

use super::validation::ResolutionSegment;

type MissingImplementationObservations =
    Arc<Mutex<BTreeMap<(TimelineId, WorkId), (PlatformTime, PlatformTime)>>>;

struct AuthorityFailure {
    error: ApiError,
    evidence: ExecutionEvidence,
    commit_error: Option<CommitError>,
    validated: Option<ValidatedResolution>,
    changes_runtime_state: bool,
    provenance: Option<CommitProvenance>,
}

struct PreparedAuthority {
    context: CommitAuthorityContext,
    validated: ValidatedResolution,
    changes_runtime_state: bool,
    provenance: Option<CommitProvenance>,
}

enum PreparedAuthorityOutcome {
    Rejected {
        rejection: loom_protocol::Rejection,
        evidence: ExecutionEvidence,
    },
    Prepared(Box<PreparedAuthority>),
}

enum AuthorityExecution {
    Rejected {
        rejection: loom_protocol::Rejection,
        evidence: ExecutionEvidence,
    },
    Committed {
        result: Box<crate::CommitResult>,
        validated: Box<ValidatedResolution>,
        changes_runtime_state: bool,
        provenance: Option<CommitProvenance>,
    },
}

enum IngressRecovery {
    None,
    Resumable(Box<ExecutionSession>),
    TerminalFailed,
}

/// A Runtime composition root for one Capability registry and persistence
/// adapter.
///
/// `Runtime` is the implementation of the focused `loom-api` service traits.
/// Every Action is routed by semantic ID through the supplied
/// `CapabilityRegistry`, resolved against one pinned `BaseWorldView`, checked
/// by the existing `EffectEngine`, and committed only through a
/// `CommitStore`. The generic store is a composition-root dependency: this
/// type never names or imports a concrete storage adapter.
///
/// The registry and store are implementation state, not public API data. A
/// consumer must use the `loom-api` traits implemented by this type; it cannot
/// obtain a resolver, `ValidatedResolution`, candidate overlay or transaction
/// through those traits. The adapter must implement all three Runtime ports so
/// World reads, Timeline CAS and Durable Work completion share the same
/// authority boundary.
pub struct Runtime<S> {
    registry: CapabilityRegistry,
    store: S,
    platform_clock: Arc<dyn PlatformClock>,
    entropy_source: Arc<dyn EntropySource>,
    cognitive_executor: crate::cognitive::CognitiveExecutorHandle,
    cognitive_policy: ExecutionPolicy,
    identity_allocator: Arc<dyn IdentityAllocator>,
    resolution_budget: ResolutionBudget,
    history_budget: HistoryBudget,
    failure_policy: FailurePolicy,
    chronology_budget: ChronologyBudgetPolicy,
    missing_implementation_observations: MissingImplementationObservations,
    blob_store: Option<Arc<dyn BlobStore>>,
}

/// Runtime-only authority value for one validated Template birth.
///
/// API descriptors remain untrusted public input. This value is created only
/// after Capability compatibility/dependency closure and every ordered
/// bootstrap Action has passed the normal Runtime validation pipeline. Storage
/// can consume its validated resolutions through the atomic birth port, but no
/// caller can construct or retarget this plan.
struct ValidatedWorldBirthPlan {
    world_id: loom_core::WorldId,
    timeline_id: TimelineId,
    initial_world_time: loom_core::WorldInstant,
    binding: WorldRuntimeBinding,
    bootstrap: Vec<ValidatedResolution>,
    evidence: ExecutionEvidence,
}

impl<S> Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore,
{
    /// Creates a Runtime after validating the assembled Capability registry.
    ///
    /// API Action commits use a deterministic zero-valued clock until the
    /// composition root injects an application clock with
    /// [`Self::with_platform_clock`]. World semantic time always comes from
    /// the pinned Timeline snapshot and is never derived from this value.
    ///
    /// # Errors
    ///
    /// Returns the registry assembly error when its dependency, ownership or
    /// reaction checks have not passed. No Runtime is returned in that case.
    pub fn new(
        store: S,
        registry: CapabilityRegistry,
    ) -> Result<Self, loom_capability::RegistryError> {
        registry.validate()?;
        Ok(Self {
            registry,
            store,
            platform_clock: Arc::new(ManualPlatformClock::default()),
            entropy_source: Arc::new(UnavailableEntropySource),
            cognitive_executor: Arc::new(crate::UnavailableCognitiveExecutor),
            cognitive_policy: ExecutionPolicy::default(),
            identity_allocator: Arc::new(UuidV7IdentityAllocator),
            resolution_budget: ResolutionBudget::default(),
            history_budget: HistoryBudget::default(),
            failure_policy: FailurePolicy::default(),
            chronology_budget: ChronologyBudgetPolicy::default(),
            missing_implementation_observations: Arc::new(Mutex::new(BTreeMap::new())),
            blob_store: None,
        })
    }

    /// Injects the application-selected immutable blob adapter.
    ///
    /// The adapter is retained behind the Runtime-owned `BlobStore` port;
    /// concrete object-store/provider types never cross the public API.
    #[must_use]
    pub fn with_blob_store<B>(mut self, blob_store: B) -> Self
    where
        B: BlobStore + 'static,
    {
        self.blob_store = Some(Arc::new(blob_store));
        self
    }

    /// Injects the Runtime-owned operational clock used by public Action
    /// commits.
    ///
    /// Runtime samples the clock once for each Action commit. This value
    /// affects only adapter metadata such as newly scheduled Work's retry
    /// availability. It does not advance World Time or enter a committed
    /// Event. Explicit Work execution methods receive their own platform-time
    /// arguments so lease and retry boundaries remain visible.
    #[must_use]
    pub fn with_platform_clock<C>(mut self, clock: C) -> Self
    where
        C: PlatformClock + 'static,
    {
        self.platform_clock = Arc::new(clock);
        self
    }

    /// Injects the Runtime-owned controlled entropy source used by new root
    /// Execution Sessions. Capability code receives only mediated sample data.
    #[must_use]
    pub fn with_entropy_source<E>(mut self, source: E) -> Self
    where
        E: EntropySource + 'static,
    {
        self.entropy_source = Arc::new(source);
        self
    }

    /// Injects the Agency `CognitiveExecutor` selected by the application
    /// composition root. Runtime retains only the SPI object; provider/vendor
    /// clients remain inside the concrete adapter.
    #[must_use]
    pub fn with_cognitive_executor<E>(mut self, executor: E) -> Self
    where
        E: CognitiveExecutor + Send + Sync + 'static,
    {
        self.cognitive_executor = Arc::new(executor);
        self
    }

    /// Pins the value-only Agency execution policy for future root Sessions.
    /// The active Runtime Revision supplies the policy revision/identity when
    /// the Execution Assembly is created.
    #[must_use]
    pub fn with_cognitive_policy(mut self, policy: ExecutionPolicy) -> Self {
        self.cognitive_policy = policy;
        self
    }

    /// Injects the Runtime-owned technical identity allocator.
    ///
    /// Applications normally use the `UUIDv7` default. Tests and deterministic
    /// composition roots can supply a controlled allocator without exposing it
    /// through `loom-api` or Capability resolution. The allocator supplies
    /// identity only; it does not supply World Time or commit authority.
    #[must_use]
    pub fn with_identity_allocator<A>(mut self, allocator: A) -> Self
    where
        A: IdentityAllocator + 'static,
    {
        self.identity_allocator = Arc::new(allocator);
        self
    }

    /// Injects the Runtime policy limiting one root Resolution execution.
    ///
    /// The same policy is applied to every owner-tagged segment produced by a
    /// root Action/Work call tree. Event, Effect and Work limits therefore
    /// aggregate across child Capabilities, while subresolution depth/count
    /// are checked before child dispatch.
    #[must_use]
    pub fn with_resolution_budget(mut self, budget: ResolutionBudget) -> Self {
        self.resolution_budget = budget;
        self
    }

    /// Injects Runtime-owned history and causal traversal bounds.
    #[must_use]
    pub fn with_history_budget(mut self, budget: HistoryBudget) -> Self {
        self.history_budget = budget;
        self
    }

    /// Injects the bounded Runtime policy for automatic technical Work
    /// failures. The policy changes only platform retry/terminalization
    /// behavior; it never changes Work's semantic due time or logical order.
    #[must_use]
    pub fn with_failure_policy(mut self, failure_policy: FailurePolicy) -> Self {
        self.failure_policy = failure_policy;
        self
    }

    /// Injects the bounded same-World-Time Scheduler chronology policy.
    #[must_use]
    pub fn with_chronology_budget(mut self, policy: ChronologyBudgetPolicy) -> Self {
        self.chronology_budget = policy;
        self
    }

    /// Convenience form for configuring the per-WorldInstant completion
    /// limit without constructing a policy value at the call site.
    #[must_use]
    pub fn with_chronology_budget_limit(self, max_completions: u64) -> Self {
        self.with_chronology_budget(ChronologyBudgetPolicy::new(max_completions))
    }

    async fn execution_assembly(
        &self,
        snapshot: &TimelineSnapshot,
        binding: WorldRuntimeBinding,
    ) -> ApiResult<ExecutionAssembly> {
        let active_selection = self
            .store
            .select_active_revision()
            .await
            .map_err(|error| map_runtime_revision_error(&error))?;
        let selection = active_selection
            .ok_or_else(|| map_runtime_revision_error(&RuntimeRevisionError::NoActiveRevision))?;
        let implementations = selection
            .revision()
            .compatible_with(&binding)
            .map_err(|error| map_revision_compatibility_error(&error))?;

        // The persisted revision is a description of the composition root's
        // exact software. Validate that the immutable registry supplied to
        // this Runtime still represents that description before Session start.
        // The registry itself is never refreshed or re-selected while a
        // Session is executing.
        if !runtime_revision_matches_registry(&self.registry, &implementations) {
            return Err(ApiError::unavailable(
                "active Runtime Revision implementation does not match the installed registry",
            ));
        }

        let session_id = self.identity_allocator.allocate_execution_session_id();
        if session_id.is_nil() {
            return Err(ApiError::internal(
                "Runtime identity allocator returned an invalid Execution Session identity",
            ));
        }
        let cognitive_policy = self.cognitive_policy_for(&selection);
        let cognitive =
            CognitiveAssembly::new(self.cognitive_executor.metadata(), cognitive_policy);
        Ok(ExecutionAssembly::new(
            session_id,
            snapshot.world_id(),
            snapshot.timeline_id(),
            snapshot.version(),
            snapshot.world_time(),
            binding,
            selection,
            implementations,
            &self.resolution_budget,
            self.entropy_source.source_id(),
        )
        .with_cognitive(cognitive))
    }

    fn cognitive_policy_for(&self, selection: &RuntimeRevisionSelection) -> ExecutionPolicy {
        let mut policy = self.cognitive_policy.clone();
        policy.policy_id = selection
            .revision()
            .execution_policy_id()
            .map_or_else(|| policy.policy_id.clone(), str::to_owned);
        policy.revision = selection.revision().id().to_string();
        policy
    }

    async fn start_execution_session_with_root(
        &self,
        assembly: ExecutionAssembly,
        origin: ExecutionOrigin,
        root: ExecutionRoot,
    ) -> ApiResult<ExecutionSession> {
        let session = ExecutionSession::new_with_root(
            assembly.session_id(),
            origin,
            assembly,
            root,
            self.platform_clock.now(),
        );
        self.store
            .start_session(session.clone())
            .await
            .map_err(|error| map_session_error(&error))?;
        Ok(session)
    }

    async fn start_ingress_execution_session(
        &self,
        assembly: ExecutionAssembly,
        ingress_id: IngressId,
        action: ActionTypeId,
    ) -> ApiResult<ExecutionSession>
    where
        S: ExecutionSessionStore,
    {
        let session = ExecutionSession::new_ingress_with_root(
            assembly.session_id(),
            ingress_id.clone(),
            assembly,
            ExecutionRoot::ingress(ingress_id).with_action(action),
            self.platform_clock.now(),
        );
        self.store
            .start_session(session.clone())
            .await
            .map_err(|error| map_session_error(&error))?;
        Ok(session)
    }

    async fn finish_execution_session(
        &self,
        session_id: loom_core::ExecutionSessionId,
        status: ExecutionSessionStatus,
    ) -> ApiResult<ExecutionSession> {
        self.store
            .finish_session(session_id, status, self.platform_clock.now())
            .await
            .map_err(|error| map_session_error(&error))
    }

    async fn finish_execution_session_with_evidence(
        &self,
        session_id: loom_core::ExecutionSessionId,
        status: ExecutionSessionStatus,
        evidence: ExecutionEvidence,
    ) -> ApiResult<ExecutionSession> {
        check_session_provenance_budget(&self.resolution_budget, &evidence, None)?;
        self.store
            .finish_session_with_evidence(session_id, status, self.platform_clock.now(), evidence)
            .await
            .map_err(|error| map_session_error(&error))
    }

    async fn finish_ingress_execution_session_with_evidence(
        &self,
        session_id: loom_core::ExecutionSessionId,
        status: ExecutionSessionStatus,
        evidence: ExecutionEvidence,
        completion: IngressCompletion,
        provenance: Option<CommitProvenance>,
    ) -> ApiResult<ExecutionSession>
    where
        S: ExecutionSessionStore,
    {
        check_session_provenance_budget(&self.resolution_budget, &evidence, provenance.as_ref())?;
        self.store
            .finish_session_with_ingress_completion_and_evidence(
                session_id,
                status,
                self.platform_clock.now(),
                evidence,
                completion,
                provenance,
            )
            .await
            .map_err(|error| map_session_error(&error))
    }

    async fn record_ingress_provenance(
        &self,
        session_id: loom_core::ExecutionSessionId,
        provenance: CommitProvenance,
    ) -> ApiResult<ExecutionSession>
    where
        S: ExecutionSessionStore,
    {
        self.store
            .record_ingress_provenance(session_id, provenance)
            .await
            .map_err(|error| map_session_error(&error))
    }

    /// Explicitly publishes a Runtime Revision through the Platform History
    /// port. Runtime construction itself never registers or activates a
    /// revision as a side effect.
    ///
    /// # Errors
    ///
    /// Returns the typed Platform History error from the persistence adapter.
    pub async fn register_runtime_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> Result<(), RuntimeRevisionError>
    where
        S: RuntimeRevisionStore,
    {
        self.store.register_revision(revision).await
    }

    /// Explicitly confirms the composition root's known Runtime Revision
    /// descriptor. A matching immutable publication is returned; a conflicting
    /// descriptor under the same ID is rejected without changing Platform or
    /// World state.
    ///
    /// # Errors
    ///
    /// Returns the typed Platform History error when the descriptor is absent,
    /// conflicting or the adapter is unavailable.
    pub async fn confirm_runtime_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> Result<RuntimeRevisionDescriptor, RuntimeRevisionError>
    where
        S: RuntimeRevisionStore,
    {
        self.store.confirm_revision(revision).await
    }

    /// Reads the current active Runtime Revision selection for a root Session
    /// start. The returned descriptor is a clone and therefore remains pinned
    /// if a later activation changes the selection pointer.
    ///
    /// # Errors
    ///
    /// Returns the typed Platform History read error from the persistence
    /// adapter.
    pub async fn active_runtime_revision(
        &self,
    ) -> Result<Option<RuntimeRevisionSelection>, RuntimeRevisionError>
    where
        S: RuntimeRevisionStore,
    {
        self.store.select_active_revision().await
    }

    /// Reads one immutable published Runtime Revision through the
    /// Runtime-owned admin/read port.
    ///
    /// # Errors
    ///
    /// Returns the typed Runtime Revision persistence error when the
    /// publication is absent or unavailable.
    pub async fn runtime_revision(
        &self,
        revision_id: RuntimeRevisionId,
    ) -> Result<RuntimeRevisionDescriptor, RuntimeRevisionError>
    where
        S: RuntimeRevisionStore,
    {
        self.store.read_revision(revision_id).await
    }

    /// Lists immutable published Runtime Revisions in adapter-defined stable
    /// order (the built-in adapters use revision ID order).
    ///
    /// # Errors
    ///
    /// Returns the typed Runtime Revision persistence error when the history
    /// cannot be read.
    pub async fn runtime_revisions(
        &self,
    ) -> Result<Vec<RuntimeRevisionDescriptor>, RuntimeRevisionError>
    where
        S: RuntimeRevisionStore,
    {
        self.store.list_revisions().await
    }

    /// Reads successful Runtime Revision activations in commit order.
    ///
    /// # Errors
    ///
    /// Returns the typed Runtime Revision persistence error when the
    /// activation history cannot be read.
    pub async fn runtime_activation_history(
        &self,
    ) -> Result<Vec<RuntimeRevisionActivation>, RuntimeRevisionError>
    where
        S: RuntimeRevisionStore,
    {
        self.store.list_activation_history().await
    }

    /// Validates the explicitly selected Runtime Revision against the
    /// registered Capability implementations at a process startup/readiness
    /// boundary. This is a read-only gate: it never registers or activates a
    /// revision and never touches World/Binding state.
    ///
    /// # Errors
    ///
    /// Returns [`RuntimeRevisionError::NoActiveRevision`] when no explicit
    /// selection exists, or [`RuntimeRevisionError::IncompatibleActiveRevision`]
    /// when the selected descriptor does not match the registered software.
    pub async fn validate_active_runtime_revision(
        &self,
    ) -> Result<RuntimeRevisionSelection, RuntimeRevisionError>
    where
        S: RuntimeRevisionStore,
    {
        let Some(selection) = self.store.select_active_revision().await? else {
            return Err(RuntimeRevisionError::NoActiveRevision);
        };
        if !runtime_revision_descriptor_matches_registry(&self.registry, selection.revision()) {
            return Err(RuntimeRevisionError::IncompatibleActiveRevision {
                revision_id: selection.revision().id().clone(),
            });
        }
        Ok(selection)
    }

    /// Explicitly activates a previously registered Runtime Revision through
    /// the generation CAS. This operation is Platform History only and never
    /// mutates World, Timeline, Event, State or World Runtime Binding data.
    ///
    /// # Errors
    ///
    /// Returns a typed missing-revision, incompatible-revision,
    /// stale-generation or storage error. Incompatible revisions are rejected
    /// before the storage CAS and therefore cannot change active selection or
    /// World/Binding state.
    pub async fn activate_runtime_revision(
        &self,
        revision_id: RuntimeRevisionId,
        expected_generation: Option<u64>,
        activated_at: PlatformTime,
    ) -> Result<RuntimeRevisionSelection, RuntimeRevisionError>
    where
        S: RuntimeRevisionStore,
    {
        let revision = self.store.read_revision(revision_id.clone()).await?;
        if !runtime_revision_descriptor_matches_registry(&self.registry, &revision) {
            return Err(RuntimeRevisionError::IncompatibleActiveRevision { revision_id });
        }
        self.store
            .activate_revision(revision_id, expected_generation, activated_at)
            .await
    }

    /// Enumerates one bounded durable Ingress recovery batch through the
    /// existing persistence port. The caller supplies the operational clock;
    /// Runtime does not introduce a second recovery state model.
    ///
    /// # Errors
    ///
    /// Returns the API-mapped persistence error from the Ingress adapter.
    pub async fn list_recoverable_ingress_ids(
        &self,
        now: PlatformTime,
        limit: usize,
    ) -> ApiResult<Vec<IngressId>>
    where
        S: IngressStore,
    {
        self.store
            .list_recoverable(now, limit)
            .await
            .map_err(map_ingress_error)
    }

    async fn binding_for_world(
        &self,
        world_id: loom_core::WorldId,
    ) -> ApiResult<WorldRuntimeBinding> {
        self.store
            .read_binding(world_id)
            .await
            .map_err(|error| map_binding_error(&error))
    }

    fn validate_template_binding(
        &self,
        template: &WorldTemplateDescriptor,
    ) -> ApiResult<WorldRuntimeBinding> {
        if template.id.is_empty() {
            return Err(ApiError::invalid_request(
                "World Template identity must not be empty",
            ));
        }

        let mut requirements = BTreeMap::new();
        for requirement in &template.capabilities {
            let capability = CapabilityId::from(requirement.id.as_str());
            if capability.is_empty() {
                return Err(ApiError::invalid_request(
                    "World Template Capability identity must not be empty",
                ));
            }
            let version =
                VersionReq::parse(requirement.version_requirement()).map_err(|error| {
                    ApiError::invalid_request(format!(
                        "Template Capability {} has an invalid compatibility requirement: {error}",
                        requirement.id
                    ))
                })?;
            self.validate_capability_closure(&capability, version, &mut requirements)?;
        }

        Ok(WorldRuntimeBinding::new(
            requirements,
            template.configuration.clone(),
            template.revision,
            Some(template.provenance()),
        ))
    }

    fn validate_capability_closure(
        &self,
        capability: &CapabilityId,
        requirement: VersionReq,
        requirements: &mut BTreeMap<CapabilityId, VersionReq>,
    ) -> ApiResult<()> {
        let manifest = self.registry.capability(capability).ok_or_else(|| {
            ApiError::unavailable(format!(
                "Template Capability {capability} is not installed in the active Runtime"
            ))
        })?;
        if !requirement.matches(&manifest.version) {
            return Err(ApiError::unavailable(format!(
                "Template Capability {capability} requires {requirement}, active version is {}",
                manifest.version
            )));
        }

        if let Some(existing) = requirements.get_mut(capability) {
            if existing != &requirement {
                let combined = format!("{existing}, {requirement}");
                *existing = VersionReq::parse(&combined).map_err(|error| {
                    ApiError::invalid_request(format!(
                        "Template Capability {capability} has incompatible requirements: {error}"
                    ))
                })?;
            }
        } else {
            requirements.insert(capability.clone(), requirement);
        }

        for dependency in &manifest.dependencies {
            self.validate_capability_closure(
                &dependency.id,
                dependency.version.clone(),
                requirements,
            )?;
        }
        Ok(())
    }

    #[allow(clippy::too_many_lines)]
    fn validate_world_template(
        &self,
        template: &WorldTemplateDescriptor,
        world_id: loom_core::WorldId,
        timeline_id: TimelineId,
        assembly: &ExecutionAssembly,
        entropy_evidence: &mut EntropyEvidence,
        final_evidence: &mut ExecutionEvidence,
    ) -> ApiResult<ValidatedWorldBirthPlan> {
        let initial_base = BaseWorldView::new(BaseWorldSnapshot::new(
            world_id,
            timeline_id,
            loom_core::TimelineVersion::default(),
            template.initial_world_time,
        ));
        let engine = EffectEngine::new(&self.registry).with_budget(assembly.execution_policy());
        let mut base = initial_base;
        let mut bootstrap = Vec::with_capacity(template.bootstrap_actions.len());
        let mut total_usage = BudgetUsage::default();
        let mut evidence = ExecutionEvidence::new(assembly.entropy_source_id().clone());
        let mut has_runtime_changes = false;

        for invocation in &template.bootstrap_actions {
            if let Err(error) = enabled_action(&self.registry, assembly, &invocation.action)
                .map_err(map_dispatch_error)
            {
                *final_evidence = evidence.clone();
                return Err(error);
            }
            if let Err(error) = engine
                .validate_action_input(&invocation.action, &invocation.input)
                .map_err(|error| map_action_input_error(&error))
            {
                *final_evidence = evidence.clone();
                return Err(error);
            }
            let mut execution_entropy_evidence =
                EntropyEvidence::new(assembly.entropy_source_id().clone());
            let mut execution_final_evidence =
                ExecutionEvidence::new(assembly.entropy_source_id().clone());
            let (outcome, execution) = match dispatch_root_action(
                &base,
                &self.registry,
                assembly,
                &*self.entropy_source,
                &mut execution_entropy_evidence,
                &mut execution_final_evidence,
                invocation,
            ) {
                Ok(result) => result,
                Err(error) => {
                    append_entropy_evidence(entropy_evidence, &execution_entropy_evidence);
                    evidence.append(&execution_final_evidence);
                    *final_evidence = evidence.clone();
                    return Err(map_dispatch_error(error));
                }
            };
            append_entropy_evidence(entropy_evidence, &execution.entropy_evidence);
            let ResolveOutcome::Resolved(_) = outcome else {
                evidence.append(&execution_final_evidence);
                *final_evidence = evidence.clone();
                return Err(ApiError::invalid_request(format!(
                    "Template bootstrap Action {} was semantically rejected",
                    invocation.action
                )));
            };
            let mut validation_read_set = ReadSet::default();
            let mut validated = match engine
                .validate_segments_with_entropy_and_reads(
                    &base,
                    &execution.segments,
                    execution.call_provenance,
                    execution.entropy_evidence,
                    &mut validation_read_set,
                )
                .map_err(|error| map_runtime_error(&error))
            {
                Ok(validated) => validated,
                Err(error) => {
                    evidence.append(&evidence_with_read_set(
                        execution_final_evidence,
                        validation_read_set,
                    ));
                    *final_evidence = evidence.clone();
                    return Err(error);
                }
            };
            validated.append_validated_work(Vec::new(), execution.read_set.clone());
            if let Err(error) =
                self.expand_reactions(&base, assembly, &engine, &mut validated, None)
            {
                evidence.append(&validated_evidence(&validated));
                *final_evidence = evidence.clone();
                return Err(error);
            }
            has_runtime_changes |= changes_runtime_state(&validated, None);
            evidence.append(&validated_evidence(&validated));
            total_usage = total_usage.combine(BudgetUsage::from_resolution(validated.resolution()));
            if let Err(error) = assembly
                .execution_policy()
                .check(total_usage)
                .map_err(|error| ApiError::invalid_request(error.to_string()))
            {
                *final_evidence = evidence.clone();
                return Err(error);
            }

            let mut candidate = CandidateWorldView::from_base(&base);
            for event in validated.events() {
                for effect in &event.effects {
                    candidate.apply_effect(effect);
                }
                candidate.note_event(event.id);
            }
            base = BaseWorldView::new(candidate.into_base_snapshot());
            bootstrap.push(validated);
        }

        *final_evidence = evidence.clone();
        Ok(ValidatedWorldBirthPlan {
            world_id,
            timeline_id,
            initial_world_time: template.initial_world_time,
            binding: assembly.binding().clone(),
            bootstrap,
            evidence: evidence.with_no_change(!has_runtime_changes),
        })
    }

    /// Expands matching enabled Reactions into validated Immediate Work while
    /// retaining the enclosing Resolution's single commit boundary.
    ///
    /// Reaction expansion copies an Event payload into the Work input and adds
    /// the authoritative Event identity as `event_id`. It records the Event as
    /// Work causality and, for Scheduler execution, records the current Work
    /// as derivation provenance. No handler is called from this method.
    fn expand_reactions(
        &self,
        base: &BaseWorldView,
        assembly: &ExecutionAssembly,
        engine: &EffectEngine<'_>,
        validated: &mut ValidatedResolution,
        origin_work_id: Option<WorkId>,
    ) -> ApiResult<()> {
        let mut additions = Vec::new();
        let mut generated_ids = Vec::new();
        let mut generated_event_ids = Vec::new();

        for event in validated.events() {
            for registered in self.registry.reactions() {
                if registered.reaction.event_type != event.event_type {
                    continue;
                }

                // A globally registered Reaction is inert unless both its
                // Reaction owner and its target Work owner are enabled by the
                // pinned World Binding and assembled in this Session.
                if !enabled_capability(&self.registry, assembly, &registered.owner) {
                    continue;
                }
                let Some(handler) = self.registry.work_handler(&registered.reaction.handler) else {
                    return Err(ApiError::internal(
                        "Runtime registry contains a Reaction with no Work handler",
                    ));
                };
                if !enabled_capability(&self.registry, assembly, &handler.owner) {
                    continue;
                }
                if let Some(limit) = assembly.execution_policy().max_reaction_schedules()
                    && additions.len() >= limit
                {
                    return Err(ApiError::invalid_request(
                        "Reaction scheduling exceeds the Runtime resource bound",
                    ));
                }

                let work_id = self.identity_allocator.allocate_work_id();
                if work_id.is_nil() {
                    return Err(ApiError::internal(
                        "Runtime identity allocator returned an invalid Reaction Work identity",
                    ));
                }
                let event_id = self.identity_allocator.allocate_event_id();
                if event_id.is_nil() {
                    return Err(ApiError::internal(
                        "Runtime identity allocator returned an invalid Reaction Event identity",
                    ));
                }
                if validated.events().iter().any(|event| event.id == event_id)
                    || generated_event_ids.contains(&event_id)
                {
                    return Err(ApiError::internal(
                        "Runtime generated a duplicate Reaction Event identity",
                    ));
                }
                generated_event_ids.push(event_id);
                if validated.work().iter().any(|mutation| {
                    matches!(mutation, WorkMutation::Schedule(work) if work.id == work_id)
                }) || generated_ids.contains(&work_id)
                {
                    return Err(ApiError::internal(
                        "Runtime generated a duplicate Reaction Work identity",
                    ));
                }
                generated_ids.push(work_id);

                additions.push((
                    handler.owner.clone(),
                    NewWork {
                        id: work_id,
                        timeline_id: validated.timeline_id(),
                        target: WorkTarget::CapabilityWork {
                            owner: Some(handler.owner.to_string()),
                            handler: registered.reaction.handler.clone(),
                        },
                        schema_revision: handler.definition.schema_revision,
                        payload: reaction_work_payload(event, event_id),
                        schedule: WorkSchedule::Immediate,
                        causal_event_id: Some(event.id),
                        origin_work_id,
                    },
                ));
            }
        }

        engine
            .append_reaction_work(base, validated, additions)
            .map_err(|error| map_runtime_error(&error))
    }

    /// Observes whether the requested due logical head is blocked because its
    /// target cannot be assembled by the active Runtime Revision.
    ///
    /// The observation is derived from current Timeline/Binding/software
    /// state. It does not claim the Work, consume an attempt, write retry
    /// metadata or advance the Timeline logical revision. A `None` result means
    /// the Work is not the due head or a compatible implementation is present.
    ///
    /// # Errors
    ///
    /// Returns an API error when the target snapshot, World binding, or active
    /// Runtime Revision cannot be read.
    pub async fn missing_implementation_block(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
    ) -> ApiResult<Option<TimelineBlockedOnMissingImplementation>> {
        let snapshot = self.snapshot_for_target(target).await?;
        let Some(work) = snapshot.works.iter().find(|work| work.id == work_id) else {
            return Err(ApiError::not_found(format!("Work {work_id} was not found")));
        };
        if !work.is_pending() || work.effective_due_world_time > snapshot.world_time() {
            return Ok(None);
        }
        let Some(head) = snapshot
            .works
            .iter()
            .filter(|candidate| {
                candidate.is_pending()
                    && candidate.effective_due_world_time <= snapshot.world_time()
            })
            .min_by_key(|candidate| {
                (
                    candidate.effective_due_world_time,
                    candidate.logical_schedule_order,
                )
            })
        else {
            return Ok(None);
        };
        if head.id != work_id {
            return Ok(None);
        }

        let binding = self.binding_for_world(snapshot.world_id()).await?;
        let active_selection = self
            .store
            .select_active_revision()
            .await
            .map_err(|error| map_runtime_revision_error(&error))?;
        let selection = active_selection
            .ok_or_else(|| map_runtime_revision_error(&RuntimeRevisionError::NoActiveRevision))?;
        let active_runtime_revision = selection.revision().id().clone();
        let implementations = selection.revision().compatible_with(&binding);
        let target_has_compatible_implementation = match &work.target {
            WorkTarget::CapabilityWork { .. } => {
                implementations.as_ref().is_ok_and(|implementations| {
                    work_target_has_compatible_implementation(
                        &self.registry,
                        &binding,
                        implementations,
                        work,
                    )
                })
            }
            WorkTarget::AgencyWake { cognition, .. } => {
                self.cognitive_executor.metadata().executor.id == *cognition
            }
        };
        if let Ok(implementations) = implementations.as_ref()
            && runtime_revision_matches_registry(&self.registry, implementations)
            && target_has_compatible_implementation
        {
            self.missing_implementation_observations
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .remove(&(snapshot.timeline_id(), work_id));
            return Ok(None);
        }

        let observed_at = self.platform_clock.now();
        let (first_observed_platform_time, last_observed_platform_time) = {
            let mut observations = self
                .missing_implementation_observations
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let observed = observations
                .entry((snapshot.timeline_id(), work_id))
                .or_insert((observed_at, observed_at));
            observed.1 = observed_at;
            (Some(observed.0), observed.1)
        };

        Ok(Some(TimelineBlockedOnMissingImplementation {
            world_id: snapshot.world_id(),
            timeline_id: snapshot.timeline_id(),
            work_id,
            semantic_requirement: work.target.clone(),
            active_runtime_revision,
            first_observed_platform_time,
            last_observed_platform_time,
        }))
    }

    /// Returns the reconstructable chronology position observed for a
    /// Timeline's current `WorldInstant`.
    ///
    /// # Errors
    ///
    /// Returns an API error when the target Timeline cannot be read.
    pub async fn chronology_budget(
        &self,
        target: TimelineTarget,
    ) -> ApiResult<crate::ChronologyBudgetState> {
        Ok(self.snapshot_for_target(target).await?.chronology_budget())
    }

    /// Drives one Timeline step using the Runtime's default next-due policy.
    ///
    /// A due head is executed only when its semantic and operational
    /// admission checks pass. A blocked or exhausted head stops progression;
    /// it cannot authorize a time advance. When no semantically due Pending
    /// Work exists, the next future due instant is submitted through the
    /// existing World-Time authority, whose storage transaction rechecks the
    /// quiescence predicate under the Timeline lock.
    ///
    /// # Errors
    ///
    /// Returns an API error when the Timeline cannot be read, Work execution
    /// fails, or the authority rejects a stale/non-quiescent transition.
    pub async fn drive_timeline(
        &self,
        target: TimelineTarget,
        now: PlatformTime,
        claimed_until: PlatformTime,
        retry_available_at: PlatformTime,
    ) -> ApiResult<TimelineDriverResult>
    where
        S: RuntimeControlStore
            + SchedulerCommitStore
            + WorldTimeStore
            + SemanticProjectionStore
            + PinnedWorldReadStore,
    {
        let snapshot = self.snapshot_for_target(target).await?;
        let pending_head = snapshot
            .works
            .iter()
            .filter(|work| work.is_pending())
            .min_by_key(|work| (work.effective_due_world_time, work.logical_schedule_order))
            .cloned();

        let Some(head) = pending_head else {
            return Ok(TimelineDriverResult::Idle {
                version: snapshot.version(),
                world_time: snapshot.world_time(),
            });
        };

        if head.effective_due_world_time <= snapshot.world_time() {
            let budget = snapshot.chronology_budget();
            let limit = self.chronology_budget.max_completions();
            if budget.consumed >= limit {
                return Ok(TimelineDriverResult::ChronologyBudgetExceeded(
                    ChronologyBudgetExceeded {
                        timeline_id: snapshot.timeline_id(),
                        world_time: budget.world_time,
                        limit,
                        consumed: budget.consumed,
                    },
                ));
            }

            if let Some(block) = self.missing_implementation_block(target, head.id).await? {
                return Ok(TimelineDriverResult::Blocked {
                    work_id: head.id,
                    reason: TimelineDriverBlock::MissingImplementation(block),
                });
            }
            if now < head.available_at {
                return Ok(TimelineDriverResult::Blocked {
                    work_id: head.id,
                    reason: TimelineDriverBlock::NotAvailable {
                        work_id: head.id,
                        available_at: head.available_at,
                        now,
                    },
                });
            }
            if let Some(lease) = head.lease
                && now < lease.claimed_until()
            {
                return Ok(TimelineDriverResult::Blocked {
                    work_id: head.id,
                    reason: TimelineDriverBlock::LeaseActive {
                        work_id: head.id,
                        claimed_until: lease.claimed_until(),
                    },
                });
            }

            let result = Box::pin(self.execute_work(
                target,
                head.id,
                now,
                claimed_until,
                retry_available_at,
            ))
            .await?;
            return Ok(TimelineDriverResult::Executed {
                work_id: head.id,
                result,
            });
        }

        let transition = AdvanceWorldTime::new(
            snapshot.timeline_id(),
            snapshot.version(),
            snapshot.world_time(),
            head.effective_due_world_time,
        )
        .map_err(|error| map_world_time_error(&error))?;
        let next = self
            .store
            .advance_world_time(transition)
            .await
            .map_err(|error| map_world_time_error(&error))?;
        Ok(TimelineDriverResult::Advanced {
            transition: WorldTimeTransition {
                from: snapshot.world_time(),
                to: head.effective_due_world_time,
            },
            version: next,
        })
    }

    /// Applies an authorized Runtime Control transition to a Pending Work.
    ///
    /// The persistence adapter performs the expected-version CAS and appends
    /// the corresponding logical `Cancel`/`Dead` journal transition atomically.
    /// This method is intentionally outside the ordinary Capability
    /// `WorkMutation` path; callers are expected to place authorization at the
    /// Admin/Runtime Control boundary before invoking it.
    ///
    /// # Errors
    ///
    /// Returns an API error when the target snapshot cannot be read or the
    /// expected Timeline version/Work claim fails in the persistence CAS.
    pub async fn terminalize_work(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        expected_version: loom_core::TimelineVersion,
        terminal_state: WorkTerminalState,
    ) -> ApiResult<loom_core::TimelineVersion>
    where
        S: RuntimeControlStore,
    {
        let snapshot = self.snapshot_for_target(target).await?;
        let terminalization = WorkTerminalization::new(
            snapshot.timeline_id(),
            expected_version,
            work_id,
            terminal_state,
            self.platform_clock.now(),
        );
        self.store
            .terminalize_work(&terminalization)
            .await
            .map_err(|error| map_commit_error(&error))
    }

    /// Schedules one explicit Agency Wake through the existing Durable Work
    /// logical model.
    ///
    /// The API-control request carries only semantic Work data. Runtime pins
    /// the current Timeline snapshot, validates the explicit Agency target and
    /// commits the logical schedule with the normal Timeline CAS. No provider,
    /// timer, Agent queue or second Work authority is involved.
    ///
    /// # Errors
    ///
    /// Returns a public conflict when the expected Timeline version is stale,
    /// or a validation/commit error when the requested Work cannot be admitted.
    pub async fn schedule_agency_wake(
        &self,
        request: AdminScheduleAgencyWakeRequest,
    ) -> ApiResult<AdminScheduleAgencyWakeResult>
    where
        S: CommitStore,
    {
        let snapshot = self.snapshot_for_target(request.target).await?;
        if snapshot.version() != request.expected_version {
            return Err(ApiError::conflict(format!(
                "Timeline version changed: expected {:?}, actual {:?}",
                request.expected_version,
                snapshot.version()
            )));
        }
        let work = NewWork::agency_wake(
            request.work_id,
            snapshot.timeline_id(),
            request.agent,
            request.cognition,
            request.payload,
            request.schedule,
        );
        let resolution = Resolution::new(Vec::new(), vec![WorkMutation::Schedule(work)]);
        let engine = EffectEngine::new(&self.registry).with_budget(self.resolution_budget);
        let validated = engine
            .validate(&snapshot.world_view(), "runtime", resolution)
            .map_err(|error| map_runtime_error(&error))?;
        let result = self
            .store
            .commit(&validated, None, self.platform_clock.now())
            .await
            .map_err(|error| map_commit_error(&error))?;
        Ok(AdminScheduleAgencyWakeResult {
            target: request.target,
            work_id: request.work_id,
            version: result.version,
        })
    }

    /// Executes one claimed Durable Work obligation through the same
    /// Resolution → validation → authority commit path as a public Action.
    ///
    /// Runtime preflights the pinned implementation before claiming the Work;
    /// after claim, resolution and completion are atomic with the resulting
    /// Events, Effects and Work mutations. A handler/runtime/commit failure
    /// enters the bounded Runtime `FailurePolicy`: while attempts remain it
    /// releases the lease through the technical retry port at a
    /// Platform-Time availability, and on exhaustion it appends the
    /// Runtime-owned `Pending` -> `Dead` logical transition. Neither path
    /// creates a World Event or changes World Truth.
    /// A semantic `Rejected` outcome completes the current Work with an empty
    /// validated Resolution and returns the public rejection unchanged.
    ///
    /// # Errors
    ///
    /// Returns a public service error for missing/stale Work, resolver or
    /// Runtime validation failure, or an unsuccessful atomic commit. The
    /// current Work remains Pending after a technical failure only when the
    /// bounded policy records a retry; exhaustion leaves it terminally Dead.
    ///
    /// # Panics
    ///
    /// Panics if a Capability Work reaches the dispatch path without the
    /// handler identity established by preflight target validation.
    pub async fn execute_work(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
        retry_available_at: PlatformTime,
    ) -> ApiResult<ExecutionResult>
    where
        S: RuntimeControlStore
            + SchedulerCommitStore
            + SemanticProjectionStore
            + PinnedWorldReadStore,
    {
        Box::pin(self.execute_work_inner(target, work_id, now, claimed_until, retry_available_at))
            .await
    }

    #[allow(clippy::too_many_lines)]
    async fn execute_work_inner(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
        retry_available_at: PlatformTime,
    ) -> ApiResult<ExecutionResult>
    where
        S: RuntimeControlStore
            + SchedulerCommitStore
            + SemanticProjectionStore
            + PinnedWorldReadStore,
    {
        let snapshot = self.snapshot_for_target(target).await?;
        let work = snapshot
            .works
            .iter()
            .find(|work| work.id == work_id)
            .cloned()
            .ok_or_else(|| ApiError::not_found(format!("Work {work_id} was not found")))?;
        if work.effective_due_world_time > snapshot.world_time() {
            return Err(ApiError::unavailable("Work is not due in World Time"));
        }
        let budget = snapshot.chronology_budget();
        let limit = self.chronology_budget.max_completions();
        if budget.consumed >= limit {
            return Err(ApiError::unavailable(
                ChronologyBudgetExceeded {
                    timeline_id: snapshot.timeline_id(),
                    world_time: budget.world_time,
                    limit,
                    consumed: budget.consumed,
                }
                .to_string(),
            ));
        }
        if self
            .missing_implementation_block(target, work_id)
            .await?
            .is_some()
        {
            return Err(ApiError::unavailable(
                "Work is blocked on a missing compatible implementation",
            ));
        }

        let binding = self.binding_for_world(snapshot.world_id()).await?;
        let assembly = self.execution_assembly(&snapshot, binding).await?;
        let handler_id = match &work.target {
            WorkTarget::CapabilityWork { handler, .. } => {
                validate_work_target(&self.registry, &assembly, &work)?;
                Some(handler)
            }
            WorkTarget::AgencyWake { agent, cognition } => {
                validate_agency_wake_target(&assembly, *agent, cognition)?;
                None
            }
        };

        // Compatibility and exact handler assembly are checked before claim.
        // A missing software implementation therefore cannot consume the
        // Work's technical attempt counter or create a lease.
        let claim = self
            .store
            .claim(target.timeline_id, work_id, now, claimed_until)
            .await
            .map_err(|error| map_work_error(&error))?;
        let mut root = ExecutionRoot::work(work_id);
        if let Some(handler_id) = handler_id {
            root = root.with_action(ActionTypeId::from(format!("work:{handler_id}")));
        } else if let WorkTarget::AgencyWake { agent, cognition } = &work.target {
            root = root.with_agency(format!("agent:{agent};cognition:{cognition}"));
        }
        let session = match self
            .start_execution_session_with_root(assembly.clone(), ExecutionOrigin::Runtime, root)
            .await
        {
            Ok(session) => session,
            Err(error) => {
                return Err(self
                    .apply_failure_policy(
                        snapshot.version(),
                        &claim,
                        now,
                        retry_available_at,
                        error,
                    )
                    .await);
            }
        };

        if let WorkTarget::AgencyWake { agent, cognition } = work.target.clone() {
            return Box::pin(self.execute_agency_wake(
                target,
                snapshot,
                assembly,
                claim,
                session,
                agent,
                cognition,
                now,
                retry_available_at,
                limit,
            ))
            .await;
        }

        let handler_id = handler_id.expect("Capability Work must have a handler");
        let base = snapshot.world_view();
        let mut dispatch_entropy_evidence =
            EntropyEvidence::new(assembly.entropy_source_id().clone());
        let mut dispatch_final_evidence =
            ExecutionEvidence::new(assembly.entropy_source_id().clone());
        let (outcome, execution) = match dispatch_root_work_async(
            &base,
            &self.registry,
            &assembly,
            &*self.entropy_source,
            &self.store,
            &mut dispatch_entropy_evidence,
            &mut dispatch_final_evidence,
            handler_id,
            &work.payload,
        )
        .await
        {
            Ok(execution) => execution,
            Err(error) => {
                let error = map_dispatch_error(error);
                return Err(self
                    .finish_failure_and_apply_policy(
                        snapshot.version(),
                        &session,
                        &claim,
                        now,
                        retry_available_at,
                        error,
                        Some(dispatch_final_evidence),
                    )
                    .await);
            }
        };

        let engine = EffectEngine::new(&self.registry).with_budget(assembly.execution_policy());
        let rejection = match &outcome {
            ResolveOutcome::Rejected(rejection) => Some(rejection.clone()),
            ResolveOutcome::Resolved(_) => None,
        };
        let mut validation_read_set = ReadSet::default();
        let validation = match &outcome {
            ResolveOutcome::Rejected(_) => engine.validate_segments_with_entropy_and_reads(
                &base,
                &[],
                execution.call_provenance.clone(),
                execution.entropy_evidence.clone(),
                &mut validation_read_set,
            ),
            ResolveOutcome::Resolved(_) => engine.validate_segments_with_entropy_and_reads(
                &base,
                &execution.segments,
                execution.call_provenance.clone(),
                execution.entropy_evidence.clone(),
                &mut validation_read_set,
            ),
        };
        let mut validated = match validation {
            Ok(validated) => validated,
            Err(error) => {
                let error = map_runtime_error(&error);
                return Err(self
                    .finish_failure_and_apply_policy(
                        snapshot.version(),
                        &session,
                        &claim,
                        now,
                        retry_available_at,
                        error,
                        Some(evidence_with_read_set(
                            dispatch_final_evidence.clone(),
                            validation_read_set,
                        )),
                    )
                    .await);
            }
        };
        validated.append_validated_work(Vec::new(), execution.read_set.clone());

        if let Err(error) = self.expand_reactions(
            &base,
            &assembly,
            &engine,
            &mut validated,
            Some(claim.work_id()),
        ) {
            return Err(self
                .finish_failure_and_apply_policy(
                    snapshot.version(),
                    &session,
                    &claim,
                    now,
                    retry_available_at,
                    error,
                    Some(validated_evidence(&validated)),
                )
                .await);
        }

        let changes_runtime_state = changes_runtime_state(&validated, Some(&claim));
        match self
            .store
            .commit_scheduler_work_with_session(&validated, &claim, now, limit, session.id())
            .await
        {
            Ok(result) => {
                let status = if rejection.is_some() {
                    ExecutionSessionStatus::Rejected
                } else {
                    ExecutionSessionStatus::Committed
                };
                self.finish_execution_session_with_evidence(
                    session.id(),
                    status,
                    validated_evidence_for_outcome(
                        &validated,
                        rejection.is_none() && !changes_runtime_state,
                    ),
                )
                .await?;
                match rejection {
                    Some(rejection) => Ok(ExecutionResult::rejected(rejection)),
                    None => Ok(execution_result(&result, changes_runtime_state)),
                }
            }
            Err(CommitError::ChronologyBudgetExceeded(exhausted)) => {
                self.finish_execution_session_with_evidence(
                    session.id(),
                    ExecutionSessionStatus::Failed,
                    validated_evidence(&validated),
                )
                .await?;
                Err(ApiError::unavailable(exhausted.to_string()))
            }
            Err(error @ CommitError::CommitOutcomeUnknown { .. }) => {
                let mapped = map_commit_error(&error);
                let reconciliation = match self
                    .reconcile_scheduler_commit(target, &validated, &claim)
                    .await
                {
                    Ok(reconciliation) => reconciliation,
                    Err(reconcile_error) => {
                        self.finish_execution_session_with_evidence(
                            session.id(),
                            ExecutionSessionStatus::Failed,
                            validated_evidence(&validated),
                        )
                        .await?;
                        return Err(reconcile_error);
                    }
                };
                match reconciliation {
                    SchedulerCommitReconciliation::Committed { event_ids, version } => {
                        let status = if rejection.is_some() {
                            ExecutionSessionStatus::Rejected
                        } else {
                            ExecutionSessionStatus::Committed
                        };
                        self.finish_execution_session_with_evidence(
                            session.id(),
                            status,
                            validated_evidence_for_outcome(
                                &validated,
                                rejection.is_none() && !changes_runtime_state,
                            ),
                        )
                        .await?;
                        match rejection {
                            Some(rejection) => Ok(ExecutionResult::rejected(rejection)),
                            None => Ok(ExecutionResult::committed(event_ids, version)),
                        }
                    }
                    SchedulerCommitReconciliation::Absent => Err(self
                        .finish_failure_and_apply_policy(
                            snapshot.version(),
                            &session,
                            &claim,
                            now,
                            retry_available_at,
                            mapped,
                            Some(validated_evidence(&validated)),
                        )
                        .await),
                    SchedulerCommitReconciliation::Ambiguous => {
                        self.finish_execution_session_with_evidence(
                            session.id(),
                            ExecutionSessionStatus::Failed,
                            validated_evidence(&validated),
                        )
                        .await?;
                        Err(ApiError::unavailable(
                            "Scheduler commit outcome remains unknown after reconciliation",
                        ))
                    }
                }
            }
            Err(error) => {
                let error = map_commit_error(&error);
                Err(self
                    .finish_failure_and_apply_policy(
                        snapshot.version(),
                        &session,
                        &claim,
                        now,
                        retry_available_at,
                        error,
                        Some(validated_evidence(&validated)),
                    )
                    .await)
            }
        }
    }

    #[allow(clippy::too_many_arguments, clippy::too_many_lines)]
    async fn execute_agency_wake(
        &self,
        target: TimelineTarget,
        snapshot: TimelineSnapshot,
        assembly: ExecutionAssembly,
        claim: WorkClaim,
        session: ExecutionSession,
        agent: loom_core::EntityId,
        cognition: String,
        now: PlatformTime,
        retry_available_at: PlatformTime,
        chronology_budget_limit: u64,
    ) -> ApiResult<ExecutionResult>
    where
        S: RuntimeControlStore
            + SchedulerCommitStore
            + SemanticProjectionStore
            + PinnedWorldReadStore,
    {
        let mut agency_evidence = ExecutionEvidence::new(assembly.entropy_source_id().clone());
        let pinned = match self.open_pinned_read(&assembly).await {
            Ok(pinned) => pinned,
            Err(error) => {
                return Err(self
                    .finish_failure_and_apply_policy(
                        snapshot.version(),
                        &session,
                        &claim,
                        now,
                        retry_available_at,
                        ApiError::unavailable(error.to_string()),
                        Some(agency_evidence),
                    )
                    .await);
            }
        };
        let request = AgentContextRequest::new(
            AgentRef::new(agent),
            assembly.timeline_id(),
            assembly.expected_version(),
            assembly.world_time(),
            assembly.cognitive().policy().context_budget,
        );
        let mut builder = AgentWorldViewBuilder::new(&self.store, PinnedReadPolicy::default());
        let view = match builder
            .build(
                &pinned,
                request,
                &AgentContextPlan::new(),
                &self.registry,
                &assembly,
            )
            .await
        {
            Ok(view) => view,
            Err(error) => {
                agency_evidence.read_set.extend(pinned.read_set());
                return Err(self
                    .finish_failure_and_apply_policy(
                        snapshot.version(),
                        &session,
                        &claim,
                        now,
                        retry_available_at,
                        ApiError::unavailable(error.to_string()),
                        Some(agency_evidence),
                    )
                    .await);
            }
        };
        let decision = match self
            .execute_cognitive_for(&cognition, &assembly, &pinned, view, &mut agency_evidence)
            .await
        {
            Ok(decision) => decision,
            Err(error) => {
                return Err(self
                    .finish_failure_and_apply_policy(
                        snapshot.version(),
                        &session,
                        &claim,
                        now,
                        retry_available_at,
                        ApiError::unavailable(error.to_string()),
                        Some(agency_evidence),
                    )
                    .await);
            }
        };
        let base = snapshot.world_view();

        match decision {
            Decision::NoAction => {
                let validated =
                    match self.empty_validated_resolution(&base, &assembly, &agency_evidence) {
                        Ok(validated) => validated,
                        Err(error) => {
                            return Err(self
                                .finish_failure_and_apply_policy(
                                    snapshot.version(),
                                    &session,
                                    &claim,
                                    now,
                                    retry_available_at,
                                    error,
                                    Some(agency_evidence),
                                )
                                .await);
                        }
                    };
                let mut evidence = agency_evidence.clone();
                evidence.append(&validated_evidence(&validated));
                match self
                    .store
                    .commit_scheduler_work_with_session(
                        &validated,
                        &claim,
                        self.platform_clock.now(),
                        chronology_budget_limit,
                        session.id(),
                    )
                    .await
                {
                    Ok(result) => {
                        self.finish_execution_session_with_evidence(
                            session.id(),
                            ExecutionSessionStatus::Committed,
                            evidence,
                        )
                        .await?;
                        Ok(ExecutionResult::committed(Vec::new(), result.version))
                    }
                    Err(CommitError::ChronologyBudgetExceeded(error)) => {
                        self.finish_execution_session_with_evidence(
                            session.id(),
                            ExecutionSessionStatus::Failed,
                            evidence,
                        )
                        .await?;
                        Err(ApiError::unavailable(error.to_string()))
                    }
                    Err(error @ CommitError::CommitOutcomeUnknown { .. }) => {
                        let mapped = map_commit_error(&error);
                        match self
                            .reconcile_scheduler_commit(target, &validated, &claim)
                            .await?
                        {
                            SchedulerCommitReconciliation::Committed { version, .. } => {
                                self.finish_execution_session_with_evidence(
                                    session.id(),
                                    ExecutionSessionStatus::Committed,
                                    evidence,
                                )
                                .await?;
                                Ok(ExecutionResult::committed(Vec::new(), version))
                            }
                            SchedulerCommitReconciliation::Absent => Err(self
                                .finish_failure_and_apply_policy(
                                    snapshot.version(),
                                    &session,
                                    &claim,
                                    now,
                                    retry_available_at,
                                    mapped,
                                    Some(evidence),
                                )
                                .await),
                            SchedulerCommitReconciliation::Ambiguous => {
                                self.finish_execution_session_with_evidence(
                                    session.id(),
                                    ExecutionSessionStatus::Failed,
                                    evidence,
                                )
                                .await?;
                                Err(ApiError::unavailable(
                                    "Scheduler commit outcome remains unknown after reconciliation",
                                ))
                            }
                        }
                    }
                    Err(error) => {
                        if matches!(&error, CommitError::TimelineConflict { .. })
                            && assembly.cognitive().policy().decision_reuse
                                == DecisionReusePolicy::ReuseDeterministic
                        {
                            return self
                                .reuse_agency_decision_after_conflict(
                                    target,
                                    &session,
                                    &claim,
                                    agent,
                                    &cognition,
                                    Decision::NoAction,
                                    now,
                                    retry_available_at,
                                    chronology_budget_limit,
                                    evidence,
                                )
                                .await;
                        }
                        let mut evidence = evidence;
                        if matches!(&error, CommitError::TimelineConflict { .. }) {
                            evidence.cognitive_evidence.mark_last_discarded();
                        }
                        Err(self
                            .finish_failure_and_apply_policy(
                                snapshot.version(),
                                &session,
                                &claim,
                                now,
                                retry_available_at,
                                map_commit_error(&error),
                                Some(evidence),
                            )
                            .await)
                    }
                }
            }
            Decision::Act(invocation) => {
                let context =
                    CommitAuthorityContext::direct(Some(claim)).with_session(session.id());
                match self
                    .execute_scheduler_action_authority(
                        &snapshot,
                        &base,
                        &assembly,
                        &invocation,
                        context,
                        &claim,
                        chronology_budget_limit,
                    )
                    .await
                {
                    Ok(AuthorityExecution::Committed {
                        result,
                        validated,
                        changes_runtime_state,
                        ..
                    }) => {
                        let mut evidence = agency_evidence;
                        evidence.append(&validated_evidence(&validated));
                        self.finish_execution_session_with_evidence(
                            session.id(),
                            ExecutionSessionStatus::Committed,
                            evidence,
                        )
                        .await?;
                        Ok(execution_result(&result, changes_runtime_state))
                    }
                    Ok(AuthorityExecution::Rejected {
                        rejection,
                        evidence: action_evidence,
                    }) => {
                        let mut evidence = agency_evidence;
                        evidence.append(&action_evidence);
                        let validated =
                            match self.empty_validated_resolution(&base, &assembly, &evidence) {
                                Ok(validated) => validated,
                                Err(error) => {
                                    return Err(self
                                        .finish_failure_and_apply_policy(
                                            snapshot.version(),
                                            &session,
                                            &claim,
                                            now,
                                            retry_available_at,
                                            error,
                                            Some(evidence),
                                        )
                                        .await);
                                }
                            };
                        evidence.append(&validated_evidence(&validated));
                        match self
                            .store
                            .commit_scheduler_work_with_session(
                                &validated,
                                &claim,
                                self.platform_clock.now(),
                                chronology_budget_limit,
                                session.id(),
                            )
                            .await
                        {
                            Ok(_) => {
                                self.finish_execution_session_with_evidence(
                                    session.id(),
                                    ExecutionSessionStatus::Rejected,
                                    evidence,
                                )
                                .await?;
                                Ok(ExecutionResult::rejected(rejection))
                            }
                            Err(CommitError::ChronologyBudgetExceeded(error)) => {
                                self.finish_execution_session_with_evidence(
                                    session.id(),
                                    ExecutionSessionStatus::Failed,
                                    evidence,
                                )
                                .await?;
                                Err(ApiError::unavailable(error.to_string()))
                            }
                            Err(error @ CommitError::CommitOutcomeUnknown { .. }) => {
                                let mapped = map_commit_error(&error);
                                match self
                                    .reconcile_scheduler_commit(target, &validated, &claim)
                                    .await?
                                {
                                    SchedulerCommitReconciliation::Committed { .. } => {
                                        self.finish_execution_session_with_evidence(
                                            session.id(),
                                            ExecutionSessionStatus::Rejected,
                                            evidence,
                                        )
                                        .await?;
                                        Ok(ExecutionResult::rejected(rejection))
                                    }
                                    SchedulerCommitReconciliation::Absent => Err(self
                                        .finish_failure_and_apply_policy(
                                            snapshot.version(),
                                            &session,
                                            &claim,
                                            now,
                                            retry_available_at,
                                            mapped,
                                            Some(evidence),
                                        )
                                        .await),
                                    SchedulerCommitReconciliation::Ambiguous => {
                                        self.finish_execution_session_with_evidence(
                                            session.id(),
                                            ExecutionSessionStatus::Failed,
                                            evidence,
                                        )
                                        .await?;
                                        Err(ApiError::unavailable(
                                            "Scheduler commit outcome remains unknown after reconciliation",
                                        ))
                                    }
                                }
                            }
                            Err(error) => Err(self
                                .finish_failure_and_apply_policy(
                                    snapshot.version(),
                                    &session,
                                    &claim,
                                    now,
                                    retry_available_at,
                                    map_commit_error(&error),
                                    Some(evidence),
                                )
                                .await),
                        }
                    }
                    Err(failure) => {
                        if matches!(
                            &failure.commit_error,
                            Some(CommitError::TimelineConflict { .. })
                        ) && assembly.cognitive().policy().decision_reuse
                            == DecisionReusePolicy::ReuseDeterministic
                        {
                            let mut discarded_evidence = agency_evidence;
                            discarded_evidence.append(&failure.evidence);
                            return self
                                .reuse_agency_decision_after_conflict(
                                    target,
                                    &session,
                                    &claim,
                                    agent,
                                    &cognition,
                                    Decision::Act(invocation),
                                    now,
                                    retry_available_at,
                                    chronology_budget_limit,
                                    discarded_evidence,
                                )
                                .await;
                        }
                        let mut evidence = agency_evidence;
                        evidence.append(&failure.evidence);
                        if let Some(commit_error @ CommitError::CommitOutcomeUnknown { .. }) =
                            failure.commit_error
                        {
                            let validated = failure.validated.ok_or_else(|| {
                                ApiError::unavailable(
                                    "Scheduler unknown commit lost its validated proposal",
                                )
                            })?;
                            match self
                                .reconcile_scheduler_commit(target, &validated, &claim)
                                .await?
                            {
                                SchedulerCommitReconciliation::Committed { event_ids, version } => {
                                    self.finish_execution_session_with_evidence(
                                        session.id(),
                                        ExecutionSessionStatus::Committed,
                                        evidence,
                                    )
                                    .await?;
                                    Ok(ExecutionResult::committed(event_ids, version))
                                }
                                SchedulerCommitReconciliation::Absent => Err(self
                                    .finish_failure_and_apply_policy(
                                        snapshot.version(),
                                        &session,
                                        &claim,
                                        now,
                                        retry_available_at,
                                        map_commit_error(&commit_error),
                                        Some(evidence),
                                    )
                                    .await),
                                SchedulerCommitReconciliation::Ambiguous => {
                                    self.finish_execution_session_with_evidence(
                                        session.id(),
                                        ExecutionSessionStatus::Failed,
                                        evidence,
                                    )
                                    .await?;
                                    Err(ApiError::unavailable(
                                        "Scheduler commit outcome remains unknown after reconciliation",
                                    ))
                                }
                            }
                        } else {
                            if matches!(
                                &failure.commit_error,
                                Some(CommitError::TimelineConflict { .. })
                            ) {
                                evidence.cognitive_evidence.mark_last_discarded();
                            }
                            Err(self
                                .finish_failure_and_apply_policy(
                                    snapshot.version(),
                                    &session,
                                    &claim,
                                    now,
                                    retry_available_at,
                                    failure.error,
                                    Some(evidence),
                                )
                                .await)
                        }
                    }
                }
            }
        }
    }

    #[allow(clippy::too_many_arguments, clippy::too_many_lines)]
    async fn reuse_agency_decision_after_conflict(
        &self,
        target: TimelineTarget,
        previous_session: &ExecutionSession,
        claim: &WorkClaim,
        agent: loom_core::EntityId,
        cognition: &str,
        decision: Decision,
        now: PlatformTime,
        retry_available_at: PlatformTime,
        chronology_budget_limit: u64,
        mut discarded_evidence: ExecutionEvidence,
    ) -> ApiResult<ExecutionResult>
    where
        S: RuntimeControlStore
            + SchedulerCommitStore
            + SemanticProjectionStore
            + PinnedWorldReadStore,
    {
        // The old Session remains useful Platform History, but its pinned
        // version can no longer authorize a commit. Marking the observation
        // discarded makes the lost cognition cost measurable before the new
        // fresh Session is started.
        discarded_evidence.cognitive_evidence.mark_last_discarded();
        self.finish_execution_session_with_evidence(
            previous_session.id(),
            ExecutionSessionStatus::Failed,
            discarded_evidence,
        )
        .await?;

        let snapshot = self.snapshot_for_target(target).await?;
        let is_current_head = snapshot
            .works
            .iter()
            .filter(|work| {
                work.is_pending() && work.effective_due_world_time <= snapshot.world_time()
            })
            .min_by_key(|work| (work.effective_due_world_time, work.logical_schedule_order))
            .is_some_and(|work| work.id == claim.work_id());
        let work_is_pending = snapshot
            .works
            .iter()
            .find(|work| work.id == claim.work_id())
            .is_some_and(WorkRecord::is_pending);
        if !work_is_pending || !is_current_head {
            return Err(ApiError::unavailable(
                "Agency Wake lost its Work claim before deterministic reuse",
            ));
        }

        let binding = self.binding_for_world(snapshot.world_id()).await?;
        let assembly = self.execution_assembly(&snapshot, binding).await?;
        validate_agency_wake_target(&assembly, agent, cognition)?;
        let session = match self
            .start_execution_session_with_root(
                assembly.clone(),
                ExecutionOrigin::Runtime,
                ExecutionRoot::work(claim.work_id())
                    .with_agency(format!("agent:{agent};cognition:{cognition};reuse")),
            )
            .await
        {
            Ok(session) => session,
            Err(error) => {
                return Err(self
                    .apply_failure_policy(snapshot.version(), claim, now, retry_available_at, error)
                    .await);
            }
        };

        let mut evidence = ExecutionEvidence::new(assembly.entropy_source_id().clone());
        let pinned = match self.open_pinned_read(&assembly).await {
            Ok(pinned) => pinned,
            Err(error) => {
                return Err(self
                    .finish_failure_and_apply_policy(
                        snapshot.version(),
                        &session,
                        claim,
                        now,
                        retry_available_at,
                        ApiError::unavailable(error.to_string()),
                        Some(evidence),
                    )
                    .await);
            }
        };
        let request = AgentContextRequest::new(
            AgentRef::new(agent),
            assembly.timeline_id(),
            assembly.expected_version(),
            assembly.world_time(),
            assembly.cognitive().policy().context_budget,
        );
        let mut builder = AgentWorldViewBuilder::new(&self.store, PinnedReadPolicy::default());
        let view = match builder
            .build(
                &pinned,
                request,
                &AgentContextPlan::new(),
                &self.registry,
                &assembly,
            )
            .await
        {
            Ok(view) => view,
            Err(error) => {
                evidence.read_set.extend(pinned.read_set());
                return Err(self
                    .finish_failure_and_apply_policy(
                        snapshot.version(),
                        &session,
                        claim,
                        now,
                        retry_available_at,
                        ApiError::unavailable(error.to_string()),
                        Some(evidence),
                    )
                    .await);
            }
        };
        if let Err(error) = crate::cognitive::record_reused_cognitive(
            &*self.cognitive_executor,
            &assembly,
            &pinned,
            &view,
            &decision,
            &mut evidence,
        ) {
            return Err(self
                .finish_failure_and_apply_policy(
                    snapshot.version(),
                    &session,
                    claim,
                    now,
                    retry_available_at,
                    ApiError::unavailable(error.to_string()),
                    Some(evidence),
                )
                .await);
        }

        let base = snapshot.world_view();
        match decision {
            Decision::NoAction => {
                let validated = match self.empty_validated_resolution(&base, &assembly, &evidence) {
                    Ok(validated) => validated,
                    Err(error) => {
                        return Err(self
                            .finish_failure_and_apply_policy(
                                snapshot.version(),
                                &session,
                                claim,
                                now,
                                retry_available_at,
                                error,
                                Some(evidence),
                            )
                            .await);
                    }
                };
                let mut evidence = evidence;
                evidence.append(&validated_evidence(&validated));
                match self
                    .store
                    .commit_scheduler_work_with_session(
                        &validated,
                        claim,
                        self.platform_clock.now(),
                        chronology_budget_limit,
                        session.id(),
                    )
                    .await
                {
                    Ok(result) => {
                        self.finish_execution_session_with_evidence(
                            session.id(),
                            ExecutionSessionStatus::Committed,
                            evidence,
                        )
                        .await?;
                        Ok(ExecutionResult::committed(Vec::new(), result.version))
                    }
                    Err(CommitError::ChronologyBudgetExceeded(error)) => {
                        self.finish_execution_session_with_evidence(
                            session.id(),
                            ExecutionSessionStatus::Failed,
                            evidence,
                        )
                        .await?;
                        Err(ApiError::unavailable(error.to_string()))
                    }
                    Err(error @ CommitError::CommitOutcomeUnknown { .. }) => {
                        let mapped = map_commit_error(&error);
                        match self
                            .reconcile_scheduler_commit(target, &validated, claim)
                            .await?
                        {
                            SchedulerCommitReconciliation::Committed { version, .. } => {
                                self.finish_execution_session_with_evidence(
                                    session.id(),
                                    ExecutionSessionStatus::Committed,
                                    evidence,
                                )
                                .await?;
                                Ok(ExecutionResult::committed(Vec::new(), version))
                            }
                            SchedulerCommitReconciliation::Absent => Err(self
                                .finish_failure_and_apply_policy(
                                    snapshot.version(),
                                    &session,
                                    claim,
                                    now,
                                    retry_available_at,
                                    mapped,
                                    Some(evidence),
                                )
                                .await),
                            SchedulerCommitReconciliation::Ambiguous => {
                                self.finish_execution_session_with_evidence(
                                    session.id(),
                                    ExecutionSessionStatus::Failed,
                                    evidence,
                                )
                                .await?;
                                Err(ApiError::unavailable(
                                    "Scheduler commit outcome remains unknown after reuse",
                                ))
                            }
                        }
                    }
                    Err(error) => {
                        let mut evidence = evidence;
                        if matches!(&error, CommitError::TimelineConflict { .. }) {
                            evidence.cognitive_evidence.mark_last_discarded();
                        }
                        Err(self
                            .finish_failure_and_apply_policy(
                                snapshot.version(),
                                &session,
                                claim,
                                now,
                                retry_available_at,
                                map_commit_error(&error),
                                Some(evidence),
                            )
                            .await)
                    }
                }
            }
            Decision::Act(invocation) => {
                let context =
                    CommitAuthorityContext::direct(Some(*claim)).with_session(session.id());
                match self
                    .execute_scheduler_action_authority(
                        &snapshot,
                        &base,
                        &assembly,
                        &invocation,
                        context,
                        claim,
                        chronology_budget_limit,
                    )
                    .await
                {
                    Ok(AuthorityExecution::Committed {
                        result,
                        validated,
                        changes_runtime_state,
                        ..
                    }) => {
                        let mut evidence = evidence;
                        evidence.append(&validated_evidence(&validated));
                        self.finish_execution_session_with_evidence(
                            session.id(),
                            ExecutionSessionStatus::Committed,
                            evidence,
                        )
                        .await?;
                        Ok(execution_result(&result, changes_runtime_state))
                    }
                    Ok(AuthorityExecution::Rejected {
                        rejection,
                        evidence: action_evidence,
                    }) => {
                        let mut evidence = evidence;
                        evidence.append(&action_evidence);
                        let validated =
                            match self.empty_validated_resolution(&base, &assembly, &evidence) {
                                Ok(validated) => validated,
                                Err(error) => {
                                    return Err(self
                                        .finish_failure_and_apply_policy(
                                            snapshot.version(),
                                            &session,
                                            claim,
                                            now,
                                            retry_available_at,
                                            error,
                                            Some(evidence),
                                        )
                                        .await);
                                }
                            };
                        evidence.append(&validated_evidence(&validated));
                        match self
                            .store
                            .commit_scheduler_work_with_session(
                                &validated,
                                claim,
                                self.platform_clock.now(),
                                chronology_budget_limit,
                                session.id(),
                            )
                            .await
                        {
                            Ok(_) => {
                                self.finish_execution_session_with_evidence(
                                    session.id(),
                                    ExecutionSessionStatus::Rejected,
                                    evidence,
                                )
                                .await?;
                                Ok(ExecutionResult::rejected(rejection))
                            }
                            Err(CommitError::ChronologyBudgetExceeded(error)) => {
                                self.finish_execution_session_with_evidence(
                                    session.id(),
                                    ExecutionSessionStatus::Failed,
                                    evidence,
                                )
                                .await?;
                                Err(ApiError::unavailable(error.to_string()))
                            }
                            Err(error @ CommitError::CommitOutcomeUnknown { .. }) => {
                                let mapped = map_commit_error(&error);
                                match self
                                    .reconcile_scheduler_commit(target, &validated, claim)
                                    .await?
                                {
                                    SchedulerCommitReconciliation::Committed { .. } => {
                                        self.finish_execution_session_with_evidence(
                                            session.id(),
                                            ExecutionSessionStatus::Rejected,
                                            evidence,
                                        )
                                        .await?;
                                        Ok(ExecutionResult::rejected(rejection))
                                    }
                                    SchedulerCommitReconciliation::Absent => Err(self
                                        .finish_failure_and_apply_policy(
                                            snapshot.version(),
                                            &session,
                                            claim,
                                            now,
                                            retry_available_at,
                                            mapped,
                                            Some(evidence),
                                        )
                                        .await),
                                    SchedulerCommitReconciliation::Ambiguous => {
                                        self.finish_execution_session_with_evidence(
                                            session.id(),
                                            ExecutionSessionStatus::Failed,
                                            evidence,
                                        )
                                        .await?;
                                        Err(ApiError::unavailable(
                                            "Scheduler commit outcome remains unknown after reuse",
                                        ))
                                    }
                                }
                            }
                            Err(error) => {
                                let mut evidence = evidence;
                                if matches!(&error, CommitError::TimelineConflict { .. }) {
                                    evidence.cognitive_evidence.mark_last_discarded();
                                }
                                Err(self
                                    .finish_failure_and_apply_policy(
                                        snapshot.version(),
                                        &session,
                                        claim,
                                        now,
                                        retry_available_at,
                                        map_commit_error(&error),
                                        Some(evidence),
                                    )
                                    .await)
                            }
                        }
                    }
                    Err(failure) => {
                        let mut evidence = evidence;
                        evidence.append(&failure.evidence);
                        if let Some(commit_error @ CommitError::CommitOutcomeUnknown { .. }) =
                            failure.commit_error
                        {
                            let validated = failure.validated.ok_or_else(|| {
                                ApiError::unavailable(
                                    "Scheduler unknown reuse commit lost its validated proposal",
                                )
                            })?;
                            match self
                                .reconcile_scheduler_commit(target, &validated, claim)
                                .await?
                            {
                                SchedulerCommitReconciliation::Committed { event_ids, version } => {
                                    self.finish_execution_session_with_evidence(
                                        session.id(),
                                        ExecutionSessionStatus::Committed,
                                        evidence,
                                    )
                                    .await?;
                                    Ok(ExecutionResult::committed(event_ids, version))
                                }
                                SchedulerCommitReconciliation::Absent => Err(self
                                    .finish_failure_and_apply_policy(
                                        snapshot.version(),
                                        &session,
                                        claim,
                                        now,
                                        retry_available_at,
                                        map_commit_error(&commit_error),
                                        Some(evidence),
                                    )
                                    .await),
                                SchedulerCommitReconciliation::Ambiguous => {
                                    self.finish_execution_session_with_evidence(
                                        session.id(),
                                        ExecutionSessionStatus::Failed,
                                        evidence,
                                    )
                                    .await?;
                                    Err(ApiError::unavailable(
                                        "Scheduler commit outcome remains unknown after reuse",
                                    ))
                                }
                            }
                        } else {
                            if matches!(
                                &failure.commit_error,
                                Some(CommitError::TimelineConflict { .. })
                            ) {
                                evidence.cognitive_evidence.mark_last_discarded();
                            }
                            Err(self
                                .finish_failure_and_apply_policy(
                                    snapshot.version(),
                                    &session,
                                    claim,
                                    now,
                                    retry_available_at,
                                    failure.error,
                                    Some(evidence),
                                )
                                .await)
                        }
                    }
                }
            }
        }
    }

    fn empty_validated_resolution(
        &self,
        base: &BaseWorldView,
        assembly: &ExecutionAssembly,
        evidence: &ExecutionEvidence,
    ) -> ApiResult<ValidatedResolution> {
        let engine = EffectEngine::new(&self.registry).with_budget(assembly.execution_policy());
        let mut validation_read_set = ReadSet::default();
        let mut validated = engine
            .validate_segments_with_entropy_and_reads(
                base,
                &[],
                evidence.call_provenance.clone(),
                evidence.entropy_evidence.clone(),
                &mut validation_read_set,
            )
            .map_err(|error| map_runtime_error(&error))?;
        validated.append_validated_work(Vec::new(), evidence.read_set.clone());
        Ok(validated)
    }

    /// Executes the normal root Action authority once. Both direct Actions
    /// and durable Ingress provide only a pinned root, invocation and generic
    /// authority context; validation, subresolution, reactions and commit are
    /// deliberately linearized here.
    #[allow(clippy::too_many_lines)]
    async fn execute_root_authority(
        &self,
        snapshot: &TimelineSnapshot,
        base: &BaseWorldView,
        assembly: &ExecutionAssembly,
        invocation: &ActionInvocation,
        context: CommitAuthorityContext,
    ) -> Result<AuthorityExecution, AuthorityFailure>
    where
        S: SemanticProjectionStore,
    {
        let prepared = match self
            .prepare_root_authority(snapshot, base, assembly, invocation, context, None)
            .await?
        {
            PreparedAuthorityOutcome::Rejected {
                rejection,
                evidence,
            } => {
                return Ok(AuthorityExecution::Rejected {
                    rejection,
                    evidence,
                });
            }
            PreparedAuthorityOutcome::Prepared(prepared) => *prepared,
        };
        let PreparedAuthority {
            context,
            validated,
            changes_runtime_state,
            provenance,
        } = prepared;
        let result = match self
            .store
            .commit_with_authority(&validated, context, self.platform_clock.now())
            .await
        {
            Ok(result) => result,
            Err(error) => {
                return Err(AuthorityFailure {
                    error: map_commit_error(&error),
                    evidence: validated_evidence(&validated),
                    commit_error: Some(error),
                    validated: Some(validated),
                    changes_runtime_state,
                    provenance,
                });
            }
        };
        let committed_provenance = result.provenance.clone().or(provenance);
        Ok(AuthorityExecution::Committed {
            result: Box::new(result),
            validated: Box::new(validated),
            changes_runtime_state,
            provenance: committed_provenance,
        })
    }

    #[allow(clippy::too_many_lines)]
    async fn prepare_root_authority(
        &self,
        snapshot: &TimelineSnapshot,
        base: &BaseWorldView,
        assembly: &ExecutionAssembly,
        invocation: &ActionInvocation,
        context: CommitAuthorityContext,
        origin_work_id: Option<WorkId>,
    ) -> Result<PreparedAuthorityOutcome, AuthorityFailure>
    where
        S: SemanticProjectionStore,
    {
        let engine = EffectEngine::new(&self.registry).with_budget(assembly.execution_policy());
        let mut context = context.with_session(assembly.session_id());
        if let Err(error) = engine
            .validate_action_input(&invocation.action, &invocation.input)
            .map_err(|error| map_action_input_error(&error))
        {
            return Err(AuthorityFailure {
                error,
                evidence: ExecutionEvidence::new(assembly.entropy_source_id().clone()),
                commit_error: None,
                validated: None,
                changes_runtime_state: false,
                provenance: None,
            });
        }

        let mut dispatch_entropy_evidence =
            EntropyEvidence::new(assembly.entropy_source_id().clone());
        let mut dispatch_final_evidence =
            ExecutionEvidence::new(assembly.entropy_source_id().clone());
        let (outcome, execution) = dispatch_root_action_async(
            base,
            &self.registry,
            assembly,
            &*self.entropy_source,
            &self.store,
            &mut dispatch_entropy_evidence,
            &mut dispatch_final_evidence,
            invocation,
        )
        .await
        .map_err(|error| AuthorityFailure {
            error: map_dispatch_error(error),
            evidence: dispatch_final_evidence.clone(),
            commit_error: None,
            validated: None,
            changes_runtime_state: false,
            provenance: None,
        })?;
        let execution_evidence = dispatch_final_evidence;
        match outcome {
            ResolveOutcome::Rejected(rejection) => Ok(PreparedAuthorityOutcome::Rejected {
                rejection,
                evidence: execution_evidence,
            }),
            ResolveOutcome::Resolved(_) => {
                let mut validation_read_set = ReadSet::default();
                let mut validated = engine
                    .validate_segments_with_entropy_and_reads(
                        base,
                        &execution.segments,
                        execution.call_provenance.clone(),
                        execution.entropy_evidence.clone(),
                        &mut validation_read_set,
                    )
                    .map_err(|error| AuthorityFailure {
                        error: map_runtime_error(&error),
                        evidence: evidence_with_read_set(
                            execution_evidence.clone(),
                            validation_read_set,
                        ),
                        commit_error: None,
                        validated: None,
                        changes_runtime_state: false,
                        provenance: None,
                    })?;
                validated.append_validated_work(Vec::new(), execution.read_set.clone());
                self.expand_reactions(base, assembly, &engine, &mut validated, origin_work_id)
                    .map_err(|error| AuthorityFailure {
                        error,
                        evidence: validated_evidence(&validated),
                        commit_error: None,
                        validated: None,
                        changes_runtime_state: false,
                        provenance: None,
                    })?;

                let changes_runtime_state =
                    changes_runtime_state(&validated, context.current_work.as_ref());
                let expected_event_ids: Vec<_> =
                    validated.events().iter().map(|event| event.id).collect();
                let expected_after_version =
                    expected_after_version(&validated, changes_runtime_state);
                let expected_work_transitions = expected_work_transitions(snapshot, &validated);
                let provenance = context.provenance.as_mut().map(|provenance| {
                    provenance.proposal_identity = logical_proposal_identity(&validated);
                    provenance.expected_after_version = Some(expected_after_version);
                    provenance
                        .expected_event_ids
                        .clone_from(&expected_event_ids);
                    provenance
                        .logical_work_transitions
                        .clone_from(&expected_work_transitions);
                    provenance.clone()
                });
                let evidence = validated_evidence(&validated);
                if let Err(error) = check_session_provenance_budget(
                    &assembly.execution_policy(),
                    &evidence,
                    provenance.as_ref(),
                ) {
                    return Err(AuthorityFailure {
                        error,
                        evidence,
                        commit_error: None,
                        validated: None,
                        changes_runtime_state: false,
                        provenance,
                    });
                }
                if let Some(provenance) = provenance.clone() {
                    self.record_ingress_provenance(provenance.session_id, provenance.clone())
                        .await
                        .map_err(|error| AuthorityFailure {
                            error,
                            evidence: validated_evidence(&validated),
                            commit_error: None,
                            validated: None,
                            changes_runtime_state: false,
                            provenance: Some(provenance.clone()),
                        })?;
                    context.provenance = Some(provenance);
                }
                Ok(PreparedAuthorityOutcome::Prepared(Box::new(
                    PreparedAuthority {
                        context,
                        validated,
                        changes_runtime_state,
                        provenance,
                    },
                )))
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    async fn execute_scheduler_action_authority(
        &self,
        snapshot: &TimelineSnapshot,
        base: &BaseWorldView,
        assembly: &ExecutionAssembly,
        invocation: &ActionInvocation,
        context: CommitAuthorityContext,
        claim: &WorkClaim,
        chronology_budget_limit: u64,
    ) -> Result<AuthorityExecution, AuthorityFailure>
    where
        S: SchedulerCommitStore + SemanticProjectionStore,
    {
        let prepared = self
            .prepare_root_authority(
                snapshot,
                base,
                assembly,
                invocation,
                context,
                Some(claim.work_id()),
            )
            .await?;
        let prepared = match prepared {
            PreparedAuthorityOutcome::Rejected {
                rejection,
                evidence,
            } => {
                return Ok(AuthorityExecution::Rejected {
                    rejection,
                    evidence,
                });
            }
            PreparedAuthorityOutcome::Prepared(prepared) => *prepared,
        };
        let PreparedAuthority {
            context: _context,
            validated,
            changes_runtime_state,
            provenance,
        } = prepared;
        let result = match self
            .store
            .commit_scheduler_work_with_session(
                &validated,
                claim,
                self.platform_clock.now(),
                chronology_budget_limit,
                assembly.session_id(),
            )
            .await
        {
            Ok(result) => result,
            Err(error) => {
                return Err(AuthorityFailure {
                    error: map_commit_error(&error),
                    evidence: validated_evidence(&validated),
                    commit_error: Some(error),
                    validated: Some(validated),
                    changes_runtime_state,
                    provenance,
                });
            }
        };
        let committed_provenance = result.provenance.clone().or(provenance);
        Ok(AuthorityExecution::Committed {
            result: Box::new(result),
            validated: Box::new(validated),
            changes_runtime_state,
            provenance: committed_provenance,
        })
    }

    /// Processes one accepted durable Ingress through the normal root Action
    /// authority path.
    ///
    /// The Ingress row is operational state only: Runtime claims it with the
    /// existing lease/fence port, creates one `ExecutionOrigin::Ingress`
    /// Session, dispatches the contained normal Action, validates the same
    /// segments and reactions as [`ActionService::invoke`], and commits only
    /// through [`CommitStore`]. The Session stores the semantic result before
    /// the Ingress row is finalized, allowing a later worker to recover a
    /// commit/finalization interruption without rerunning the Action.
    ///
    /// # Errors
    ///
    /// Technical failures are recorded through the configured bounded Ingress
    /// retry policy. Missing or incompatible implementations are preflighted
    /// before the claim, matching the normal root contract and consuming no
    /// Ingress attempt.
    #[allow(clippy::too_many_lines)]
    pub async fn process_ingress(
        &self,
        ingress_id: IngressId,
        _now: PlatformTime,
        claimed_until: PlatformTime,
        retry_available_at: PlatformTime,
    ) -> ApiResult<IngressCompletion>
    where
        S: IngressStore + SemanticProjectionStore,
    {
        let record = self
            .store
            .ingress(ingress_id.clone())
            .await
            .map_err(map_ingress_error)?;
        match &record.status {
            IngressStatus::Completed(completion) => {
                if let IngressRecovery::Resumable(session) =
                    self.recover_ingress(&ingress_id).await?
                    && session.status() == ExecutionSessionStatus::Started
                    && session.ingress_completion().is_none()
                {
                    let status = if completion.is_rejected() {
                        ExecutionSessionStatus::Rejected
                    } else {
                        ExecutionSessionStatus::Committed
                    };
                    self.finish_ingress_execution_session_with_evidence(
                        session.id(),
                        status,
                        ExecutionEvidence::from_parts(
                            session.read_set().clone(),
                            session.call_provenance().clone(),
                            session.entropy_evidence().clone(),
                        ),
                        completion.clone(),
                        session.commit_provenance().cloned(),
                    )
                    .await?;
                }
                return Ok(completion.clone());
            }
            IngressStatus::Failed(_) => {
                return Err(ApiError::unavailable(
                    "Ingress has a terminal technical failure",
                ));
            }
            IngressStatus::Accepted | IngressStatus::Processing | IngressStatus::Retryable(_) => {}
        }
        let retryable = matches!(&record.status, IngressStatus::Retryable(_));

        // Recovery is provenance-first: inspect durable Sessions before any
        // fresh snapshot/assembly/action preflight.
        let existing_session = match self.recover_ingress(&ingress_id).await? {
            IngressRecovery::None => None,
            IngressRecovery::Resumable(session) => Some(*session),
            IngressRecovery::TerminalFailed if retryable => None,
            IngressRecovery::TerminalFailed => {
                return Err(ApiError::unavailable(
                    "Ingress terminal Failed Session is not resumable",
                ));
            }
        };
        let mut claim = if existing_session.is_some() {
            Some(
                IngressStore::claim(
                    &self.store,
                    ingress_id.clone(),
                    self.platform_clock.now(),
                    claimed_until,
                )
                .await
                .map_err(map_ingress_error)?,
            )
        } else {
            None
        };

        if let Some(session) = existing_session.as_ref()
            && let Some(completion) = session.ingress_completion().cloned()
            && let Some(claim) = claim.as_ref()
        {
            self.store
                .complete(
                    claim,
                    session.id(),
                    completion.clone(),
                    self.platform_clock.now(),
                )
                .await
                .map_err(map_ingress_error)?;
            return Ok(completion);
        }

        let target = record.submission.envelope.target;
        let invocation = record.submission.envelope.invocation.clone();
        let snapshot = self.snapshot_for_target(target).await?;
        if let Some(session) = existing_session.as_ref()
            && let Some(provenance) = session.commit_provenance()
            && let Some(commit) = snapshot.journal.iter().find(|commit| {
                exact_logical_commit_matches(
                    commit,
                    Some(provenance),
                    session.assembly().timeline_id(),
                    session.assembly().expected_version(),
                    commit.after_version,
                    &commit.event_ids,
                    Some(&provenance.logical_work_transitions),
                )
            })
        {
            let claim_ref = claim.as_ref().ok_or_else(|| {
                ApiError::internal("Ingress recovery claim was lost before finalization")
            })?;
            let completion = IngressCompletion::Committed {
                event_refs: commit
                    .event_ids
                    .iter()
                    .map(|event_id| EventRef::new(commit.timeline_id, *event_id))
                    .collect(),
                timeline_version: commit.after_version,
            };
            self.finish_ingress_execution_session_with_evidence(
                session.id(),
                ExecutionSessionStatus::Committed,
                ExecutionEvidence::from_parts(
                    session.read_set().clone(),
                    session.call_provenance().clone(),
                    session.entropy_evidence().clone(),
                ),
                completion.clone(),
                commit.provenance.clone(),
            )
            .await?;
            self.store
                .complete(
                    claim_ref,
                    session.id(),
                    completion.clone(),
                    self.platform_clock.now(),
                )
                .await
                .map_err(map_ingress_error)?;
            return Ok(completion);
        }
        let (session, claim) = if let Some(session) = existing_session {
            if snapshot.version() != session.assembly().expected_version() {
                let claim_ref = claim.as_ref().ok_or_else(|| {
                    ApiError::internal("Ingress recovery claim was lost before reconciliation")
                })?;
                return Err(self
                    .record_ingress_failure(
                        claim_ref,
                        self.platform_clock.now(),
                        retry_available_at,
                        ApiError::unavailable(
                            "Ingress Started Session requires bounded provenance reconciliation",
                        ),
                    )
                    .await);
            }
            (
                session,
                claim.take().ok_or_else(|| {
                    ApiError::internal("Ingress recovery claim was lost before execution")
                })?,
            )
        } else {
            let binding = self.binding_for_world(snapshot.world_id()).await?;
            let assembly = self.execution_assembly(&snapshot, binding).await?;
            enabled_action(&self.registry, &assembly, &invocation.action)
                .map_err(map_dispatch_error)?;
            claim = Some(
                IngressStore::claim(
                    &self.store,
                    ingress_id.clone(),
                    self.platform_clock.now(),
                    claimed_until,
                )
                .await
                .map_err(map_ingress_error)?,
            );
            match self
                .start_ingress_execution_session(
                    assembly,
                    ingress_id.clone(),
                    invocation.action.clone(),
                )
                .await
            {
                Ok(session) => (
                    session,
                    claim.take().ok_or_else(|| {
                        ApiError::internal("Ingress claim was lost before Session start")
                    })?,
                ),
                Err(error) => {
                    let claim_ref = claim.as_ref().ok_or_else(|| {
                        ApiError::internal("Ingress claim was lost before failure recording")
                    })?;
                    return Err(self
                        .record_ingress_failure(
                            claim_ref,
                            self.platform_clock.now(),
                            retry_available_at,
                            error,
                        )
                        .await);
                }
            }
        };
        let assembly = session.assembly().clone();
        // A Started Session carrying provenance means an earlier authority
        // finalization was unknown. Until that exact journal identity is
        // observed, recovery may only remain bounded/retryable; it must not
        // re-enter Action execution on the unchanged base version.
        if session.commit_provenance().is_some() {
            return Err(self
                .record_ingress_failure(
                    &claim,
                    self.platform_clock.now(),
                    retry_available_at,
                    ApiError::unavailable(
                        "Ingress authority provenance requires reconciliation before retry",
                    ),
                )
                .await);
        }
        enabled_action(&self.registry, &assembly, &invocation.action)
            .map_err(map_dispatch_error)?;

        let context = CommitAuthorityContext {
            current_work: None,
            ingress_claim: Some(claim.clone()),
            provenance: Some(CommitProvenance::new(
                session.id(),
                ingress_id.clone(),
                "pending",
            )),
            session_id: Some(session.id()),
        };
        match self
            .execute_root_authority(
                &snapshot,
                &snapshot.world_view(),
                &assembly,
                &invocation,
                context,
            )
            .await
        {
            Ok(AuthorityExecution::Rejected {
                rejection,
                evidence,
            }) => {
                let completion = IngressCompletion::Rejected(rejection);
                self.finish_ingress_execution_session_with_evidence(
                    session.id(),
                    ExecutionSessionStatus::Rejected,
                    evidence,
                    completion.clone(),
                    None,
                )
                .await?;
                self.store
                    .complete(
                        &claim,
                        session.id(),
                        completion.clone(),
                        self.platform_clock.now(),
                    )
                    .await
                    .map_err(map_ingress_error)?;
                Ok(completion)
            }
            Ok(AuthorityExecution::Committed {
                result,
                validated,
                changes_runtime_state,
                provenance,
            }) => {
                let completion = ingress_completion(&result, changes_runtime_state);
                let status = ExecutionSessionStatus::Committed;
                self.finish_ingress_execution_session_with_evidence(
                    session.id(),
                    status,
                    validated_evidence_for_outcome(&validated, !changes_runtime_state),
                    completion.clone(),
                    provenance.clone(),
                )
                .await?;
                self.store
                    .complete(
                        &claim,
                        session.id(),
                        completion.clone(),
                        self.platform_clock.now(),
                    )
                    .await
                    .map_err(map_ingress_error)?;
                Ok(completion)
            }
            Err(failure) => {
                if matches!(
                    failure.commit_error,
                    Some(CommitError::CommitOutcomeUnknown { .. })
                ) {
                    let validated = failure.validated.ok_or_else(|| {
                        ApiError::unavailable("Ingress unknown commit lost proposal identity")
                    })?;
                    let provenance = failure.provenance;
                    match self
                        .reconcile_ingress_commit(
                            target,
                            &validated,
                            failure.changes_runtime_state,
                            provenance.as_ref(),
                        )
                        .await
                    {
                        Ok(Some((completion, committed_provenance))) => {
                            let status = ExecutionSessionStatus::Committed;
                            self.finish_ingress_execution_session_with_evidence(
                                session.id(),
                                status,
                                validated_evidence_for_outcome(
                                    &validated,
                                    !failure.changes_runtime_state,
                                ),
                                completion.clone(),
                                committed_provenance.or(provenance),
                            )
                            .await?;
                            self.store
                                .complete(
                                    &claim,
                                    session.id(),
                                    completion.clone(),
                                    self.platform_clock.now(),
                                )
                                .await
                                .map_err(map_ingress_error)?;
                            Ok(completion)
                        }
                        Ok(None) | Err(_) => Err(self
                            .record_ingress_failure(
                                &claim,
                                self.platform_clock.now(),
                                retry_available_at,
                                ApiError::unavailable(
                                    "Ingress commit outcome requires bounded reconciliation",
                                ),
                            )
                            .await),
                    }
                } else {
                    Err(self
                        .finish_ingress_failure(
                            &session,
                            &claim,
                            self.platform_clock.now(),
                            retry_available_at,
                            failure.error,
                            failure.evidence,
                        )
                        .await)
                }
            }
        }
    }

    async fn recover_ingress(&self, ingress_id: &IngressId) -> ApiResult<IngressRecovery>
    where
        S: IngressStore + SemanticProjectionStore,
    {
        let sessions = self
            .store
            .list_sessions()
            .await
            .map_err(|error| map_session_error(&error))?;
        let matches: Vec<_> = sessions
            .into_iter()
            .filter(|session| session.ingress_id() == Some(ingress_id))
            .collect();
        classify_ingress_sessions(&matches)
    }

    async fn reconcile_ingress_commit(
        &self,
        target: TimelineTarget,
        resolution: &ValidatedResolution,
        changes_runtime_state: bool,
        provenance: Option<&CommitProvenance>,
    ) -> ApiResult<Option<(IngressCompletion, Option<CommitProvenance>)>>
    where
        S: IngressStore + SemanticProjectionStore,
    {
        let snapshot = self.snapshot_for_target(target).await?;
        let expected_event_ids: Vec<_> = resolution.events().iter().map(|event| event.id).collect();
        let expected_work_transitions = expected_work_transitions(&snapshot, resolution);
        let expected_after_version = expected_after_version(resolution, changes_runtime_state);
        if let Some(commit) = snapshot.journal.iter().find(|commit| {
            exact_logical_commit_matches(
                commit,
                provenance,
                resolution.timeline_id(),
                resolution.base_version(),
                expected_after_version,
                &expected_event_ids,
                Some(&expected_work_transitions),
            )
        }) {
            return Ok(Some((
                IngressCompletion::Committed {
                    event_refs: commit
                        .event_ids
                        .iter()
                        .map(|event_id| EventRef::new(resolution.timeline_id(), *event_id))
                        .collect(),
                    timeline_version: commit.after_version,
                },
                commit.provenance.clone(),
            )));
        }
        if !changes_runtime_state && snapshot.version() == resolution.base_version() {
            return Ok(Some((IngressCompletion::NoChange, provenance.cloned())));
        }
        if snapshot.version() == resolution.base_version() {
            return Ok(None);
        }
        Err(ApiError::unavailable(
            "Ingress commit outcome remains unknown after reconciliation",
        ))
    }

    async fn record_ingress_failure(
        &self,
        claim: &IngressClaim,
        now: PlatformTime,
        retry_available_at: PlatformTime,
        error: ApiError,
    ) -> ApiError
    where
        S: IngressStore + SemanticProjectionStore,
    {
        let failure = IngressTechnicalFailure::new("runtime_failure", error.message.clone());
        if self.failure_policy.allows_retry(claim.attempt_count()) {
            let available_at = match self
                .failure_policy
                .next_available_at(now, retry_available_at)
            {
                Ok(available_at) => available_at,
                Err(policy_error) => {
                    return self
                        .store
                        .fail(
                            claim,
                            now,
                            IngressTechnicalFailure::new(
                                "runtime_failure",
                                policy_error.to_string(),
                            ),
                        )
                        .await
                        .map_or_else(
                            |_| {
                                ApiError::internal(
                                    "Ingress technical failure could not be recorded",
                                )
                            },
                            |_| error.clone(),
                        );
                }
            };
            return IngressStore::retry(&self.store, claim, now, available_at, failure)
                .await
                .map_or_else(
                    |_| ApiError::internal("Ingress technical retry could not be recorded"),
                    |_| error.clone(),
                );
        }
        self.store.fail(claim, now, failure).await.map_or_else(
            |_| ApiError::internal("Ingress technical failure could not be recorded"),
            |_| error.clone(),
        )
    }

    async fn finish_ingress_failure(
        &self,
        session: &ExecutionSession,
        claim: &IngressClaim,
        now: PlatformTime,
        retry_available_at: PlatformTime,
        error: ApiError,
        evidence: ExecutionEvidence,
    ) -> ApiError
    where
        S: IngressStore + SemanticProjectionStore,
    {
        let error = match self
            .finish_execution_session_with_evidence(
                session.id(),
                ExecutionSessionStatus::Failed,
                evidence,
            )
            .await
        {
            Ok(_) => error,
            Err(session_error) => session_error,
        };
        self.record_ingress_failure(claim, now, retry_available_at, error)
            .await
    }

    /// Accepts a pre-canonicalized Ingress submission through the Runtime
    /// operational port. Acceptance never appends a World Event.
    ///
    /// # Errors
    ///
    /// Returns an API-level persistence error when the operational acceptance
    /// authority cannot read or atomically update the Ingress record.
    pub async fn accept_ingress(
        &self,
        submission: IngressSubmission,
    ) -> ApiResult<IngressAcceptance>
    where
        S: IngressStore,
    {
        self.store
            .accept(submission)
            .await
            .map_err(map_ingress_error)
    }

    /// Records a technical Work retry through the Runtime-owned Work port.
    ///
    /// The same Work identity remains Pending and no Timeline/Event/Facet
    /// state is changed. The adapter rechecks the claim fence and lease at its
    /// own linearization point.
    ///
    /// # Errors
    ///
    /// Propagates the typed Work-port error without converting it to a public
    /// Action outcome.
    pub async fn retry_work(
        &self,
        claim: &WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> Result<WorkRecord, WorkError> {
        self.store.retry(claim, now, available_at, last_error).await
    }

    async fn snapshot_for_target(&self, target: TimelineTarget) -> ApiResult<TimelineSnapshot> {
        let snapshot = self
            .store
            .snapshot(target.timeline_id)
            .await
            .map_err(|error| map_read_error(&error))?;
        if snapshot.world_id() != target.world_id {
            return Err(ApiError::not_found(format!(
                "Timeline {} is not in World {}",
                target.timeline_id, target.world_id
            )));
        }
        Ok(snapshot)
    }

    async fn reconcile_scheduler_commit(
        &self,
        target: TimelineTarget,
        resolution: &ValidatedResolution,
        claim: &WorkClaim,
    ) -> ApiResult<SchedulerCommitReconciliation> {
        let snapshot = self.snapshot_for_target(target).await?;
        Ok(reconcile_scheduler_commit_snapshot(
            &snapshot, resolution, claim,
        ))
    }

    async fn apply_failure_policy(
        &self,
        expected_version: loom_core::TimelineVersion,
        claim: &WorkClaim,
        now: PlatformTime,
        retry_available_at: PlatformTime,
        error: ApiError,
    ) -> ApiError
    where
        S: RuntimeControlStore,
    {
        if self.failure_policy.allows_retry(claim.attempt_count()) {
            let available_at = match self
                .failure_policy
                .next_available_at(now, retry_available_at)
            {
                Ok(available_at) => available_at,
                Err(policy_error) => {
                    return match self
                        .terminalize_failed_work(
                            expected_version,
                            claim,
                            now,
                            &policy_error.to_string(),
                        )
                        .await
                    {
                        Ok(()) => error,
                        Err(terminal_error) => terminal_error,
                    };
                }
            };
            if self
                .store
                .retry(claim, now, available_at, Some(error.message.clone()))
                .await
                .is_err()
            {
                return ApiError::internal("Work failure could not be recorded for retry");
            }
            return error;
        }

        match self
            .terminalize_failed_work(expected_version, claim, now, &error.message)
            .await
        {
            Ok(()) => error,
            Err(terminal_error) => terminal_error,
        }
    }

    async fn terminalize_failed_work(
        &self,
        expected_version: loom_core::TimelineVersion,
        claim: &WorkClaim,
        now: PlatformTime,
        last_error: &str,
    ) -> Result<(), ApiError>
    where
        S: RuntimeControlStore,
    {
        let terminalization = WorkTerminalization::new(
            claim.timeline_id(),
            expected_version,
            claim.work_id(),
            WorkTerminalState::Dead,
            now,
        )
        .with_claim(*claim)
        .with_last_error(last_error);
        match self.store.terminalize_work(&terminalization).await {
            Ok(_) => Ok(()),
            Err(CommitError::TimelineConflict { .. }) => self
                .store
                .terminalize_current_work(&terminalization)
                .await
                .map(|_| ())
                .map_err(|error| map_failure_terminalization_error(&error)),
            Err(error) => Err(map_failure_terminalization_error(&error)),
        }
    }

    #[allow(
        clippy::too_many_arguments,
        reason = "failure handling needs the existing execution evidence"
    )]
    async fn finish_failure_and_apply_policy(
        &self,
        expected_version: loom_core::TimelineVersion,
        session: &ExecutionSession,
        claim: &WorkClaim,
        now: PlatformTime,
        retry_available_at: PlatformTime,
        error: ApiError,
        evidence: Option<ExecutionEvidence>,
    ) -> ApiError
    where
        S: RuntimeControlStore,
    {
        let error = match evidence {
            Some(evidence) => match self
                .finish_execution_session_with_evidence(
                    session.id(),
                    ExecutionSessionStatus::Failed,
                    evidence,
                )
                .await
            {
                Ok(_) => error,
                Err(session_error) => session_error,
            },
            None => match self
                .finish_execution_session(session.id(), ExecutionSessionStatus::Failed)
                .await
            {
                Ok(_) => error,
                Err(session_error) => session_error,
            },
        };
        self.apply_failure_policy(expected_version, claim, now, retry_available_at, error)
            .await
    }
}

fn logical_proposal_identity(resolution: &ValidatedResolution) -> String {
    serde_json::to_string(&json!({
        "schema": "loom.logical-proposal.v2",
        "timeline_id": resolution.timeline_id(),
        "base_version": resolution.base_version(),
        "pinned_world_time": resolution.pinned_world_time(),
        "resolution": resolution.resolution(),
    }))
    .expect("validated logical proposal must be JSON serializable")
}

fn validated_evidence(resolution: &ValidatedResolution) -> ExecutionEvidence {
    ExecutionEvidence::from_parts(
        resolution.read_set().clone(),
        resolution.call_provenance().clone(),
        resolution.entropy_evidence().clone(),
    )
}

fn check_session_provenance_budget(
    policy: &ResolutionBudget,
    evidence: &ExecutionEvidence,
    provenance: Option<&CommitProvenance>,
) -> ApiResult<()> {
    let entries = evidence
        .read_set
        .len()
        .saturating_add(evidence.call_provenance.len())
        .saturating_add(evidence.entropy_evidence.len())
        .saturating_add(evidence.cognitive_evidence.len());
    if let Some(limit) = policy.max_session_provenance_entries()
        && entries > limit
    {
        return Err(ApiError::invalid_request(
            "execution provenance entry count exceeds the Runtime resource bound",
        ));
    }

    if let Some(limit) = policy.max_session_provenance_bytes() {
        let evidence_bytes = serde_json::to_vec(evidence)
            .map_err(|_| ApiError::invalid_request("execution provenance could not be encoded"))?;
        let provenance_bytes = provenance
            .map(serde_json::to_vec)
            .transpose()
            .map_err(|_| ApiError::invalid_request("commit provenance could not be encoded"))?;
        let actual = evidence_bytes
            .len()
            .saturating_add(provenance_bytes.as_ref().map_or(0, Vec::len));
        if actual > limit {
            return Err(ApiError::invalid_request(
                "execution provenance exceeds the Runtime resource bound",
            ));
        }
    }
    Ok(())
}

fn execution_evidence(base: &BaseWorldView, execution: &ExecutionState) -> ExecutionEvidence {
    let mut evidence = execution.evidence();
    let mut read_set = base.read_set();
    read_set.extend(evidence.read_set.clone());
    evidence.read_set = read_set;
    evidence
}

fn evidence_with_read_set(mut evidence: ExecutionEvidence, read_set: ReadSet) -> ExecutionEvidence {
    evidence.read_set.extend(read_set);
    evidence
}

fn validated_evidence_for_outcome(
    resolution: &ValidatedResolution,
    no_change: bool,
) -> ExecutionEvidence {
    validated_evidence(resolution).with_no_change(no_change)
}

fn committed_provenance_matches(
    actual: Option<&CommitProvenance>,
    expected: Option<&CommitProvenance>,
) -> bool {
    let (Some(actual), Some(expected)) = (actual, expected) else {
        return false;
    };
    actual.session_id == expected.session_id
        && actual.ingress_id == expected.ingress_id
        && actual.proposal_identity == expected.proposal_identity
        && actual.expected_after_version == expected.expected_after_version
        && actual.expected_event_ids == expected.expected_event_ids
        && actual.logical_work_transitions == expected.logical_work_transitions
}

fn classify_ingress_sessions(matches: &[ExecutionSession]) -> ApiResult<IngressRecovery> {
    let resumable: Vec<_> = matches
        .iter()
        .filter(|session| {
            session.status() == ExecutionSessionStatus::Started
                || session.ingress_completion().is_some()
        })
        .collect();
    match resumable.as_slice() {
        [] if matches
            .iter()
            .any(|session| session.status() == ExecutionSessionStatus::Failed) =>
        {
            Ok(IngressRecovery::TerminalFailed)
        }
        [] => Ok(IngressRecovery::None),
        [session] => Ok(IngressRecovery::Resumable(Box::new((*session).clone()))),
        _ => Err(ApiError::unavailable(
            "Ingress has multiple resumable Session provenance records",
        )),
    }
}

fn exact_logical_commit_matches(
    commit: &LogicalCommit,
    expected: Option<&CommitProvenance>,
    timeline_id: TimelineId,
    before_version: TimelineVersion,
    after_version: TimelineVersion,
    event_ids: &[EventId],
    work_transitions: Option<&[LogicalWorkTransition]>,
) -> bool {
    let (Some(actual), Some(expected)) = (commit.provenance.as_ref(), expected) else {
        return false;
    };
    commit.timeline_id == timeline_id
        && commit.before_version == before_version
        && commit.after_version == after_version
        && commit.event_ids == event_ids
        && expected.expected_after_version == Some(after_version)
        && expected.expected_event_ids == event_ids
        && commit.world_time.is_none()
        && commit.chronology_budget.is_none()
        && committed_provenance_matches(Some(actual), Some(expected))
        && actual.logical_work_transitions == commit.work_transitions
        && work_transitions.is_none_or(|expected| commit.work_transitions == expected)
}

fn expected_after_version(
    resolution: &ValidatedResolution,
    changes_runtime_state: bool,
) -> TimelineVersion {
    TimelineVersion::new(
        loom_core::EventSeq::new(
            resolution.base_version().head_event_seq.value()
                + u64::try_from(resolution.events().len()).unwrap_or(u64::MAX),
        ),
        loom_core::StateRevision::new(
            resolution.base_version().state_revision.value() + u64::from(changes_runtime_state),
        ),
    )
}

fn expected_work_transitions(
    snapshot: &TimelineSnapshot,
    resolution: &ValidatedResolution,
) -> Vec<LogicalWorkTransition> {
    let proposed_work_ids: HashSet<_> = resolution
        .work()
        .iter()
        .filter_map(|mutation| match mutation {
            WorkMutation::Schedule(work) => Some(work.id),
            WorkMutation::Cancel(_) => None,
        })
        .collect();
    let mut next_order = snapshot
        .works
        .iter()
        .filter(|work| !proposed_work_ids.contains(&work.id))
        .map(|work| work.logical_schedule_order)
        .chain(
            snapshot
                .journal
                .iter()
                .filter(|commit| {
                    commit.after_version.state_revision.value()
                        <= resolution.base_version().state_revision.value()
                })
                .flat_map(|commit| {
                    commit.work_transitions.iter().filter_map(|transition| {
                        if let LogicalWorkTransition::Schedule {
                            logical_schedule_order,
                            ..
                        } = transition
                        {
                            Some(*logical_schedule_order)
                        } else {
                            None
                        }
                    })
                }),
        )
        .max()
        .unwrap_or_default();
    resolution
        .work()
        .iter()
        .map(|mutation| match mutation {
            WorkMutation::Schedule(work) => {
                next_order = next_order.saturating_add(1);
                let effective_due_world_time = match work.schedule {
                    WorkSchedule::Immediate => resolution.pinned_world_time(),
                    WorkSchedule::At(instant) => instant,
                };
                LogicalWorkTransition::Schedule {
                    work_id: work.id,
                    target: work.target.clone(),
                    schema_revision: work.schema_revision,
                    payload: work.payload.clone(),
                    effective_due_world_time,
                    logical_schedule_order: next_order,
                    causal_event_id: work.causal_event_id,
                    origin_work_id: work.origin_work_id,
                }
            }
            WorkMutation::Cancel(work_id) => LogicalWorkTransition::Cancel { work_id: *work_id },
        })
        .collect()
}

impl<T> WorldLifecycleStore for &T
where
    T: WorldLifecycleStore + ?Sized,
{
    fn create_world(
        &self,
        world_id: loom_core::WorldId,
        timeline_id: TimelineId,
        initial_world_time: loom_core::WorldInstant,
    ) -> PersistenceFuture<'_, Result<crate::WorldCreation, LifecycleError>> {
        (**self).create_world(world_id, timeline_id, initial_world_time)
    }

    fn create_world_with_binding(
        &self,
        world_id: loom_core::WorldId,
        timeline_id: TimelineId,
        initial_world_time: loom_core::WorldInstant,
        binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<crate::WorldCreation, LifecycleError>> {
        (**self).create_world_with_binding(world_id, timeline_id, initial_world_time, binding)
    }

    fn create_world_with_bootstrap<'a>(
        &'a self,
        world_id: loom_core::WorldId,
        timeline_id: TimelineId,
        initial_world_time: loom_core::WorldInstant,
        binding: WorldRuntimeBinding,
        bootstrap: &'a [ValidatedResolution],
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<crate::WorldCreation, LifecycleError>> {
        (**self).create_world_with_bootstrap(
            world_id,
            timeline_id,
            initial_world_time,
            binding,
            bootstrap,
            now,
        )
    }

    fn create_world_with_bootstrap_for_session<'a>(
        &'a self,
        world_id: loom_core::WorldId,
        timeline_id: TimelineId,
        initial_world_time: loom_core::WorldInstant,
        binding: WorldRuntimeBinding,
        bootstrap: &'a [ValidatedResolution],
        now: PlatformTime,
        session_id: loom_core::ExecutionSessionId,
    ) -> PersistenceFuture<'a, Result<crate::WorldCreation, LifecycleError>> {
        (**self).create_world_with_bootstrap_for_session(
            world_id,
            timeline_id,
            initial_world_time,
            binding,
            bootstrap,
            now,
            session_id,
        )
    }
}

impl<T> WorldStore for &T
where
    T: WorldStore + ?Sized,
{
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        (**self).snapshot(timeline_id)
    }

    fn fork_timeline<'a>(
        &'a self,
        fork: &'a TimelineFork,
    ) -> PersistenceFuture<'a, Result<TimelineSnapshot, ForkError>> {
        (**self).fork_timeline(fork)
    }
}

impl<T> ChangeFeedStore for &T
where
    T: ChangeFeedStore + ?Sized,
{
    fn read_change_feed(
        &self,
        timeline_id: TimelineId,
        after: EventSeq,
        limit: usize,
    ) -> PersistenceFuture<'_, Result<crate::ChangeFeedRead, ReadError>> {
        (**self).read_change_feed(timeline_id, after, limit)
    }
}

impl<T> SchedulerDiscoveryStore for &T
where
    T: SchedulerDiscoveryStore + ?Sized,
{
    fn discover_scheduler_targets(
        &self,
        request: SchedulerDiscoveryRequest,
    ) -> PersistenceFuture<'_, Result<SchedulerDiscoveryPage, SchedulerDiscoveryError>> {
        (**self).discover_scheduler_targets(request)
    }
}

impl<T> TimelineForkStore for &T
where
    T: TimelineForkStore + ?Sized,
{
    fn fork_timeline<'a>(
        &'a self,
        fork: &'a TimelineFork,
    ) -> PersistenceFuture<'a, Result<TimelineSnapshot, ForkError>> {
        (**self).fork_timeline(fork)
    }
}

impl<T> WorldRuntimeBindingStore for &T
where
    T: WorldRuntimeBindingStore + ?Sized,
{
    fn read_binding(
        &self,
        world_id: loom_core::WorldId,
    ) -> PersistenceFuture<'_, Result<WorldRuntimeBinding, BindingError>> {
        (**self).read_binding(world_id)
    }

    fn persist_binding(
        &self,
        world_id: loom_core::WorldId,
        binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<(), BindingError>> {
        (**self).persist_binding(world_id, binding)
    }
}

impl<T> RuntimeRevisionStore for &T
where
    T: RuntimeRevisionStore + ?Sized,
{
    fn register_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> PersistenceFuture<'_, Result<(), RuntimeRevisionError>> {
        (**self).register_revision(revision)
    }

    fn confirm_revision(
        &self,
        revision: RuntimeRevisionDescriptor,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionDescriptor, RuntimeRevisionError>> {
        (**self).confirm_revision(revision)
    }

    fn read_revision(
        &self,
        revision_id: RuntimeRevisionId,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionDescriptor, RuntimeRevisionError>> {
        (**self).read_revision(revision_id)
    }

    fn list_revisions(
        &self,
    ) -> PersistenceFuture<'_, Result<Vec<RuntimeRevisionDescriptor>, RuntimeRevisionError>> {
        (**self).list_revisions()
    }

    fn read_activation_history(
        &self,
    ) -> PersistenceFuture<'_, Result<Vec<RuntimeRevisionActivation>, RuntimeRevisionError>> {
        (**self).read_activation_history()
    }

    fn read_active_revision(
        &self,
    ) -> PersistenceFuture<'_, Result<Option<RuntimeRevisionSelection>, RuntimeRevisionError>> {
        (**self).read_active_revision()
    }

    fn activate_revision(
        &self,
        revision_id: RuntimeRevisionId,
        expected_generation: Option<u64>,
        activated_at: PlatformTime,
    ) -> PersistenceFuture<'_, Result<RuntimeRevisionSelection, RuntimeRevisionError>> {
        (**self).activate_revision(revision_id, expected_generation, activated_at)
    }
}

impl<T> ExecutionSessionStore for &T
where
    T: ExecutionSessionStore + ?Sized,
{
    fn start_session(
        &self,
        session: ExecutionSession,
    ) -> PersistenceFuture<'_, Result<(), SessionError>> {
        (**self).start_session(session)
    }

    fn finish_session(
        &self,
        session_id: loom_core::ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        (**self).finish_session(session_id, status, ended_at)
    }

    fn finish_session_with_entropy(
        &self,
        session_id: loom_core::ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
        entropy_evidence: EntropyEvidence,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        (**self).finish_session_with_entropy(session_id, status, ended_at, entropy_evidence)
    }

    fn finish_session_with_evidence(
        &self,
        session_id: loom_core::ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
        evidence: ExecutionEvidence,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        (**self).finish_session_with_evidence(session_id, status, ended_at, evidence)
    }

    fn finish_session_with_ingress_completion(
        &self,
        session_id: loom_core::ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
        entropy_evidence: EntropyEvidence,
        completion: IngressCompletion,
        provenance: Option<CommitProvenance>,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        (**self).finish_session_with_ingress_completion(
            session_id,
            status,
            ended_at,
            entropy_evidence,
            completion,
            provenance,
        )
    }

    fn finish_session_with_ingress_completion_and_evidence(
        &self,
        session_id: loom_core::ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
        evidence: ExecutionEvidence,
        completion: IngressCompletion,
        provenance: Option<CommitProvenance>,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        (**self).finish_session_with_ingress_completion_and_evidence(
            session_id, status, ended_at, evidence, completion, provenance,
        )
    }

    fn record_ingress_provenance(
        &self,
        session_id: loom_core::ExecutionSessionId,
        provenance: CommitProvenance,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        (**self).record_ingress_provenance(session_id, provenance)
    }

    fn read_session(
        &self,
        session_id: loom_core::ExecutionSessionId,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        (**self).read_session(session_id)
    }

    fn list_sessions(&self) -> PersistenceFuture<'_, Result<Vec<ExecutionSession>, SessionError>> {
        (**self).list_sessions()
    }

    fn session_for_event(
        &self,
        event_ref: loom_core::EventRef,
    ) -> PersistenceFuture<'_, Result<Option<loom_core::ExecutionSessionId>, SessionError>> {
        (**self).session_for_event(event_ref)
    }

    fn events_for_session(
        &self,
        session_id: loom_core::ExecutionSessionId,
    ) -> PersistenceFuture<'_, Result<Vec<loom_core::EventRef>, SessionError>> {
        (**self).events_for_session(session_id)
    }
}

impl<T> IngressStore for &T
where
    T: IngressStore + ?Sized,
{
    fn accept(
        &self,
        submission: IngressSubmission,
    ) -> PersistenceFuture<'_, Result<IngressAcceptance, IngressError>> {
        (**self).accept(submission)
    }

    fn ingress(
        &self,
        ingress_id: IngressId,
    ) -> PersistenceFuture<'_, Result<crate::IngressOperationalRecord, IngressError>> {
        (**self).ingress(ingress_id)
    }

    fn list_recoverable(
        &self,
        now: PlatformTime,
        limit: usize,
    ) -> PersistenceFuture<'_, Result<Vec<IngressId>, IngressError>> {
        (**self).list_recoverable(now, limit)
    }

    fn claim(
        &self,
        ingress_id: IngressId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'_, Result<IngressClaim, IngressError>> {
        (**self).claim(ingress_id, now, claimed_until)
    }

    fn retry<'a>(
        &'a self,
        claim: &'a IngressClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        failure: IngressTechnicalFailure,
    ) -> PersistenceFuture<'a, Result<crate::IngressOperationalRecord, IngressError>> {
        (**self).retry(claim, now, available_at, failure)
    }

    fn complete<'a>(
        &'a self,
        claim: &'a IngressClaim,
        session_id: loom_core::ExecutionSessionId,
        completion: IngressCompletion,
        completed_at: PlatformTime,
    ) -> PersistenceFuture<'a, Result<crate::IngressOperationalRecord, IngressError>> {
        (**self).complete(claim, session_id, completion, completed_at)
    }

    fn fail<'a>(
        &'a self,
        claim: &'a IngressClaim,
        completed_at: PlatformTime,
        failure: IngressTechnicalFailure,
    ) -> PersistenceFuture<'a, Result<crate::IngressOperationalRecord, IngressError>> {
        (**self).fail(claim, completed_at, failure)
    }
}

impl<T> CommitStore for &T
where
    T: CommitStore + ?Sized,
{
    fn commit<'a>(
        &'a self,
        resolution: &'a crate::ValidatedResolution,
        current_work: Option<&'a WorkClaim>,
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<crate::CommitResult, CommitError>> {
        (**self).commit(resolution, current_work, now)
    }

    fn commit_with_authority<'a>(
        &'a self,
        resolution: &'a crate::ValidatedResolution,
        context: CommitAuthorityContext,
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<crate::CommitResult, CommitError>> {
        (**self).commit_with_authority(resolution, context, now)
    }
}

impl<T> SchedulerCommitStore for &T
where
    T: SchedulerCommitStore + ?Sized,
{
    fn commit_scheduler_work<'a>(
        &'a self,
        resolution: &'a crate::ValidatedResolution,
        current_work: &'a WorkClaim,
        now: PlatformTime,
        max_completions: u64,
    ) -> PersistenceFuture<'a, Result<crate::CommitResult, CommitError>> {
        (**self).commit_scheduler_work(resolution, current_work, now, max_completions)
    }

    fn commit_scheduler_work_with_session<'a>(
        &'a self,
        resolution: &'a crate::ValidatedResolution,
        current_work: &'a WorkClaim,
        now: PlatformTime,
        max_completions: u64,
        session_id: loom_core::ExecutionSessionId,
    ) -> PersistenceFuture<'a, Result<crate::CommitResult, CommitError>> {
        (**self).commit_scheduler_work_with_session(
            resolution,
            current_work,
            now,
            max_completions,
            session_id,
        )
    }
}

impl<T> WorldTimeStore for &T
where
    T: WorldTimeStore + ?Sized,
{
    fn advance_world_time(
        &self,
        transition: AdvanceWorldTime,
    ) -> PersistenceFuture<'_, Result<loom_core::TimelineVersion, WorldTimeError>> {
        (**self).advance_world_time(transition)
    }
}

impl<T> WorkStore for &T
where
    T: WorkStore + ?Sized,
{
    fn claim(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'_, Result<WorkClaim, WorkError>> {
        (**self).claim(timeline_id, work_id, now, claimed_until)
    }

    fn retry<'a>(
        &'a self,
        claim: &'a WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> PersistenceFuture<'a, Result<WorkRecord, WorkError>> {
        (**self).retry(claim, now, available_at, last_error)
    }

    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
    ) -> PersistenceFuture<'_, Result<Option<WorkRecord>, ReadError>> {
        (**self).work(timeline_id, work_id)
    }
}

impl<T> RuntimeControlStore for &T
where
    T: RuntimeControlStore + ?Sized,
{
    fn terminalize_work<'a>(
        &'a self,
        terminalization: &'a WorkTerminalization,
    ) -> PersistenceFuture<'a, Result<loom_core::TimelineVersion, CommitError>> {
        (**self).terminalize_work(terminalization)
    }

    fn terminalize_current_work<'a>(
        &'a self,
        terminalization: &'a WorkTerminalization,
    ) -> PersistenceFuture<'a, Result<loom_core::TimelineVersion, CommitError>> {
        (**self).terminalize_current_work(terminalization)
    }
}

impl<T> SemanticProjectionStore for &T
where
    T: SemanticProjectionStore + ?Sized,
{
    fn register_semantic_projection(
        &self,
        registration: SemanticProjectionRegistration,
    ) -> PersistenceFuture<'_, Result<(), SemanticProjectionError>> {
        (**self).register_semantic_projection(registration)
    }

    fn query_semantic_projection(
        &self,
        query: SemanticProjectionQuery,
    ) -> PersistenceFuture<'_, Result<Vec<SemanticProjectionHit>, SemanticProjectionError>> {
        (**self).query_semantic_projection(query)
    }

    fn rebuild_semantic_projection<'a>(
        &'a self,
        rebuild: &'a SemanticProjectionRebuild,
    ) -> PersistenceFuture<'a, Result<(), SemanticProjectionError>> {
        (**self).rebuild_semantic_projection(rebuild)
    }

    fn delete_semantic_projection(
        &self,
        key: SemanticProjectionKey,
    ) -> PersistenceFuture<'_, Result<(), SemanticProjectionError>> {
        (**self).delete_semantic_projection(key)
    }
}

impl<S> WorldService for Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + WorldLifecycleStore
        + RuntimeRevisionStore
        + ExecutionSessionStore,
{
    fn create_world_from_template(
        &self,
        request: CreateWorldFromTemplateRequest,
    ) -> ApiFuture<'_, CreateWorldFromTemplateResult> {
        Box::pin(async move {
            let world_id = self.identity_allocator.allocate_world_id();
            let timeline_id = self.identity_allocator.allocate_timeline_id();
            if world_id.is_nil() || timeline_id.is_nil() {
                return Err(ApiError::internal(
                    "Runtime identity allocator returned an invalid identity",
                ));
            }

            let binding = self.validate_template_binding(&request.template)?;
            let initial_snapshot = TimelineSnapshot::new(
                BaseWorldSnapshot::new(
                    world_id,
                    timeline_id,
                    loom_core::TimelineVersion::default(),
                    request.template.initial_world_time,
                ),
                Vec::new(),
                Vec::new(),
            );
            let assembly = self.execution_assembly(&initial_snapshot, binding).await?;
            let session = self
                .start_execution_session_with_root(
                    assembly.clone(),
                    ExecutionOrigin::Runtime,
                    ExecutionRoot::bootstrap(request.template.provenance()),
                )
                .await?;
            let mut entropy_evidence = EntropyEvidence::new(assembly.entropy_source_id().clone());
            let mut bootstrap_evidence =
                ExecutionEvidence::new(assembly.entropy_source_id().clone());
            let plan = match self.validate_world_template(
                &request.template,
                world_id,
                timeline_id,
                &assembly,
                &mut entropy_evidence,
                &mut bootstrap_evidence,
            ) {
                Ok(plan) => plan,
                Err(error) => {
                    self.finish_execution_session_with_evidence(
                        session.id(),
                        ExecutionSessionStatus::Failed,
                        bootstrap_evidence,
                    )
                    .await?;
                    return Err(error);
                }
            };
            let created = match self
                .store
                .create_world_with_bootstrap_for_session(
                    plan.world_id,
                    plan.timeline_id,
                    plan.initial_world_time,
                    plan.binding,
                    &plan.bootstrap,
                    self.platform_clock.now(),
                    session.id(),
                )
                .await
            {
                Ok(created) => created,
                Err(error) => {
                    self.finish_execution_session_with_evidence(
                        session.id(),
                        ExecutionSessionStatus::Failed,
                        plan.evidence.clone().with_no_change(false),
                    )
                    .await?;
                    return Err(map_lifecycle_error(&error));
                }
            };
            self.finish_execution_session_with_evidence(
                session.id(),
                ExecutionSessionStatus::Committed,
                plan.evidence,
            )
            .await?;
            Ok(ApiTimelineSnapshot::new(
                TimelineTarget::new(created.world_id(), created.timeline_id()),
                created.version(),
                created.world_time(),
            ))
        })
    }
}

impl<S> Runtime<S>
where
    S: SchedulerDiscoveryStore,
{
    /// Discovers a bounded page of Scheduler Timeline targets through the
    /// Runtime-owned persistence port.
    ///
    /// Runtime deliberately forwards the request and result unchanged. The
    /// persistence adapter owns T03 page-bound validation, deterministic
    /// cursor semantics and the Pending-Work discovery predicate; this
    /// façade performs no claim, commit, Work-state or World-Time operation.
    ///
    /// # Errors
    ///
    /// Returns the typed discovery error produced by the persistence adapter.
    pub async fn discover_scheduler_targets(
        &self,
        request: SchedulerDiscoveryRequest,
    ) -> Result<SchedulerDiscoveryPage, SchedulerDiscoveryError> {
        self.store.discover_scheduler_targets(request).await
    }
}

impl<S> Runtime<S>
where
    S: PinnedWorldReadStore,
{
    /// Creates the Runtime-owned bounded point-read boundary for one injected
    /// Storage adapter. The returned helper is intended for Runtime assembly
    /// and refill/restart orchestration; it is never passed to Capability code.
    #[must_use]
    pub fn pinned_read_boundary(&self, policy: PinnedReadPolicy) -> PinnedReadBoundary<'_, S> {
        PinnedReadBoundary::new(&self.store, policy)
    }

    /// Opens a version-fenced point-read session for an already pinned
    /// Execution Assembly.
    ///
    /// # Errors
    ///
    /// Returns the persistence port's error when the assembly's world,
    /// timeline, or version cannot be fenced.
    pub async fn open_pinned_read(
        &self,
        assembly: &ExecutionAssembly,
    ) -> Result<PinnedReadSession, ReadError> {
        self.store.open_pinned_read(assembly).await
    }

    /// Invokes the pinned Agency `CognitiveExecutor` over one restricted
    /// `AgentWorldView` and appends its typed result/provenance to the current
    /// Session evidence envelope.
    ///
    /// The method intentionally accepts no `BaseWorldView`, `WorldStore`,
    /// provider client or mutation authority. Context construction must happen
    /// through [`AgentWorldViewBuilder`](crate::AgentWorldViewBuilder) and the
    /// supplied [`PinnedReadSession`]; the executor sees only the resulting
    /// Agency value.
    ///
    /// # Errors
    ///
    /// Returns a typed gateway error when the Session/view coordinate or
    /// context budget is not pinned, the evidence source does not match, the
    /// executor identity changed, or cognition returned a technical error.
    pub async fn execute_cognitive(
        &self,
        assembly: &ExecutionAssembly,
        session: &PinnedReadSession,
        view: AgentWorldView,
        evidence: &mut ExecutionEvidence,
    ) -> Result<Decision, CognitiveGatewayError> {
        crate::cognitive::execute_cognitive(
            &*self.cognitive_executor,
            assembly,
            session,
            &view,
            evidence,
        )
        .await
    }

    /// Returns the audit-safe metadata of the executor selected by the
    /// application composition root. This is an identity value, not a client
    /// handle or a provider authority.
    #[must_use]
    pub fn cognitive_executor_metadata(&self) -> CognitiveMetadata {
        self.cognitive_executor.metadata()
    }

    /// Reports whether the currently composed executor can satisfy a stable
    /// Agency Wake cognition requirement before context construction begins.
    #[must_use]
    pub fn cognitive_requirement_available(&self, requirement: &str) -> bool {
        self.cognitive_executor_metadata().executor.id == requirement
    }

    /// Invokes cognition after checking the Agency Wake's pinned requirement.
    /// This is the target-aware form used by Wake orchestration; the generic
    /// [`Self::execute_cognitive`] form is useful when the target was already
    /// admitted by the caller.
    ///
    /// # Errors
    ///
    /// Returns a typed gateway error when the target requirement differs from
    /// the pinned executor or the delegated cognition boundary rejects the
    /// pinned context/evidence or returns a technical failure.
    pub async fn execute_cognitive_for(
        &self,
        requirement: &str,
        assembly: &ExecutionAssembly,
        session: &PinnedReadSession,
        view: AgentWorldView,
        evidence: &mut ExecutionEvidence,
    ) -> Result<Decision, CognitiveGatewayError> {
        let pinned = &assembly.cognitive().metadata().executor.id;
        if pinned != requirement {
            return Err(CognitiveGatewayError::CognitiveRequirementMismatch {
                requirement: requirement.to_owned(),
                pinned: pinned.clone(),
            });
        }
        self.execute_cognitive(assembly, session, view, evidence)
            .await
    }
}

impl<S> ActionService for Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore
        + SemanticProjectionStore,
{
    #[allow(clippy::too_many_lines)]
    fn invoke(&self, request: ActionRequest) -> ApiFuture<'_, ExecutionResult> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(request.target).await?;
            let binding = self.binding_for_world(snapshot.world_id()).await?;
            let assembly = self.execution_assembly(&snapshot, binding).await?;
            enabled_action(&self.registry, &assembly, &request.invocation.action)
                .map_err(map_dispatch_error)?;
            let session = self
                .start_execution_session_with_root(
                    assembly.clone(),
                    ExecutionOrigin::Application,
                    ExecutionRoot::action(request.invocation.action.clone()),
                )
                .await?;
            match self
                .execute_root_authority(
                    &snapshot,
                    &snapshot.world_view(),
                    &assembly,
                    &request.invocation,
                    CommitAuthorityContext::direct(None),
                )
                .await
            {
                Ok(AuthorityExecution::Rejected {
                    rejection,
                    evidence,
                }) => {
                    self.finish_execution_session_with_evidence(
                        session.id(),
                        ExecutionSessionStatus::Rejected,
                        evidence,
                    )
                    .await?;
                    Ok(ExecutionResult::rejected(rejection))
                }
                Ok(AuthorityExecution::Committed {
                    result,
                    validated,
                    changes_runtime_state,
                    ..
                }) => {
                    let status = ExecutionSessionStatus::Committed;
                    self.finish_execution_session_with_evidence(
                        session.id(),
                        status,
                        validated_evidence_for_outcome(&validated, !changes_runtime_state),
                    )
                    .await?;
                    Ok(execution_result(&result, changes_runtime_state))
                }
                Err(failure) => {
                    self.finish_execution_session_with_evidence(
                        session.id(),
                        ExecutionSessionStatus::Failed,
                        failure.evidence,
                    )
                    .await?;
                    Err(failure.error)
                }
            }
        })
    }
}

impl<S> IngressService for Runtime<S>
where
    S: IngressStore,
{
    fn submit_ingress(&self, request: IngressEnvelope) -> ApiFuture<'_, IngressAcceptance> {
        Box::pin(async move {
            let ingress_bytes = serde_json::to_vec(&request)
                .map_err(|_| ApiError::invalid_request("Ingress payload could not be encoded"))?
                .len();
            self.resolution_budget
                .check_value(BudgetDimension::IngressPayloadBytes, ingress_bytes)
                .map_err(|_| {
                    ApiError::invalid_request("Ingress payload exceeds the Runtime bound")
                })?;
            let canonical_request = (
                &request.provenance,
                &request.target,
                &request.authorization,
                &request.time_metadata,
                &request.invocation,
            );
            let request_fingerprint = match serde_json::to_string(&canonical_request) {
                Ok(serialized) => semantic_query_fingerprint(&serialized),
                Err(_) => {
                    return Err(ApiError::internal(
                        "Ingress request could not be canonicalized",
                    ));
                }
            };
            let submission = IngressSubmission::new(
                request.provenance.source.clone(),
                request,
                request_fingerprint,
                self.platform_clock.now(),
            );
            self.store
                .accept(submission)
                .await
                .map_err(map_ingress_error)
        })
    }

    fn ingress_status(&self, ingress_id: IngressId) -> ApiFuture<'_, IngressStatusRecord> {
        Box::pin(async move {
            let record = self
                .store
                .ingress(ingress_id)
                .await
                .map_err(map_ingress_error)?;
            Ok(IngressStatusRecord::new(
                record.ingress_id().clone(),
                record.idempotency_key().clone(),
                record.status,
            ))
        })
    }
}

impl<S> Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore,
{
    /// Forks the addressed Timeline at its requested committed position.
    /// Omitting the request version selects the current head.
    ///
    /// Runtime allocates the child identity, reconstructs the semantic head
    /// through the persistence fork seam and returns only the public child
    /// snapshot. The storage adapter owns the source CAS and atomic write.
    ///
    /// # Errors
    ///
    /// Returns an API error when the source cannot be read, the source changes
    /// before the fork commit, or the persistence authority rejects the child.
    pub async fn fork_timeline(&self, target: TimelineTarget) -> ApiResult<ApiTimelineSnapshot> {
        self.fork_head(ForkTimelineRequest::new(target)).await
    }

    /// Request-form alias for [`Self::fork_timeline`].
    ///
    /// # Errors
    ///
    /// Returns the same API errors as [`Self::fork_timeline`].
    pub async fn fork(&self, request: ForkTimelineRequest) -> ApiResult<ApiTimelineSnapshot> {
        self.fork_head(request).await
    }

    fn replay_visible_to(
        &self,
        source: TimelineSnapshot,
        target: TimelineVersion,
    ) -> Pin<Box<dyn Future<Output = ApiResult<HistoricalTimelineState>> + '_>> {
        self.replay_visible_to_inner(source, target, HashSet::new())
    }

    fn replay_visible_to_inner(
        &self,
        source: TimelineSnapshot,
        target: TimelineVersion,
        mut seen: HashSet<TimelineId>,
    ) -> Pin<Box<dyn Future<Output = ApiResult<HistoricalTimelineState>> + '_>> {
        Box::pin(async move {
            if !seen.insert(source.timeline_id()) {
                return Err(map_historical_fork_error());
            }
            let ancestry = source.ancestry();
            let Some(parent_timeline_id) = ancestry.parent_timeline_id else {
                return source
                    .replay_to(target)
                    .map_err(|_| map_historical_fork_error());
            };
            let Some(boundary) = ancestry.fork_parent_version else {
                return Err(map_historical_fork_error());
            };
            let parent = self
                .snapshot_for_target(TimelineTarget::new(source.world_id(), parent_timeline_id))
                .await?;
            if version_before(target, boundary) {
                return self
                    .replay_visible_to_inner(parent, target, seen)
                    .await
                    .map(|historical| historical.retarget_timeline(source.timeline_id()));
            }

            let historical_parent = self.replay_visible_to_inner(parent, boundary, seen).await?;
            let parent_logical = historical_parent.logical_state();
            let initial = historical_parent.materialization().retarget(
                source.timeline_id(),
                boundary,
                historical_parent.world_time(),
            );
            let logical_order_high_water = parent_logical
                .works
                .iter()
                .map(|work| work.logical_schedule_order)
                .max()
                .unwrap_or_default();
            let initial_chronology_budget = parent_logical.chronology_budget;
            let initial_works = source
                .works
                .iter()
                .filter(|work| work.logical_schedule_order <= logical_order_high_water)
                .map(logical_work_seed)
                .collect();
            let branch_events = source
                .events
                .iter()
                .filter(|event| {
                    event.timeline_id == source.timeline_id()
                        && event.event_seq > boundary.head_event_seq
                })
                .cloned()
                .collect::<Vec<_>>();
            source
                .replay_from_seed_with_events(
                    initial,
                    initial_works,
                    initial_chronology_budget,
                    logical_order_high_water,
                    &branch_events,
                    target,
                )
                .map_err(|_| map_historical_fork_error())
        })
    }

    async fn fork_head(&self, request: ForkTimelineRequest) -> ApiResult<ApiTimelineSnapshot> {
        let source = self.snapshot_for_target(request.source).await?;
        let fork_version = request.source_version.unwrap_or(source.version());
        let historical = self.replay_visible_to(source.clone(), fork_version).await?;
        let child_timeline_id = self.identity_allocator.allocate_timeline_id();
        if child_timeline_id.is_nil() {
            return Err(ApiError::internal(
                "Runtime identity allocator returned a nil child Timeline",
            ));
        }

        let pending = historical
            .logical_state()
            .pending_works()
            .cloned()
            .collect::<Vec<_>>();
        let mut work_ids = BTreeMap::new();
        for work in &pending {
            let child_work_id = self.identity_allocator.allocate_work_id();
            if child_work_id.is_nil()
                || work_ids.insert(work.work_id, child_work_id).is_some()
                || work_ids.values().filter(|id| **id == child_work_id).count() > 1
            {
                return Err(ApiError::internal(
                    "Runtime identity allocator returned a duplicate or nil child Work",
                ));
            }
        }

        let pending_work = pending
            .iter()
            .map(|work| {
                let origin_work_id = work.origin_work_id.map(|origin_work_id| {
                    work_ids
                        .get(&origin_work_id)
                        .copied()
                        .unwrap_or(origin_work_id)
                });
                let child = WorkRecord {
                    id: work_ids[&work.work_id],
                    timeline_id: child_timeline_id,
                    target: work.target.clone(),
                    schema_revision: work.schema_revision,
                    payload: work.payload.clone(),
                    effective_due_world_time: work.effective_due_world_time,
                    logical_schedule_order: work.logical_schedule_order,
                    causal_event_id: work.causal_event_id,
                    origin_work_id,
                    status: WorkStatus::Pending,
                    attempt_count: 0,
                    claim_generation: 0,
                    available_at: PlatformTime::default(),
                    last_error: None,
                    lease: None,
                };
                ForkWork {
                    source_work_id: work.work_id,
                    work: child,
                }
            })
            .collect();
        let logical_schedule_order = historical
            .logical_state()
            .works
            .iter()
            .map(|work| work.logical_schedule_order)
            .max()
            .unwrap_or_default();
        let materialization = ForkMaterialization::new(
            historical.materialization().clone(),
            historical.logical_state().chronology_budget,
            logical_schedule_order,
        );
        let fork = TimelineFork::new(source.timeline_id(), source.version(), child_timeline_id)
            .at_version(fork_version)
            .with_materialization(materialization)
            .with_pending_work(pending_work);
        let child = self
            .store
            .fork_timeline(&fork)
            .await
            .map_err(|error| map_fork_error(&error))?;
        Ok(ApiTimelineSnapshot::with_ancestry(
            TimelineTarget::new(child.world_id(), child.timeline_id()),
            child.version(),
            child.world_time(),
            child.ancestry(),
        ))
    }

    async fn snapshot_for_event_ref(&self, event_ref: EventRef) -> ApiResult<TimelineSnapshot> {
        self.store
            .snapshot(event_ref.timeline_id)
            .await
            .map_err(|error| map_read_error(&error))
    }

    fn project_catalog(&self, available: Option<&HashSet<CapabilityId>>) -> CatalogSnapshot {
        project_catalog(&self.registry, available)
    }
}

impl<S> Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore
        + SemanticProjectionStore,
{
    async fn read_semantic_projection(
        &self,
        query: ApiSemanticProjectionQuery,
    ) -> ApiResult<ApiSemanticProjectionRead> {
        let snapshot = self.snapshot_for_target(query.target).await?;
        let source_revision = query.source_revision.unwrap_or(snapshot.version());
        if source_revision.head_event_seq.value() > snapshot.version().head_event_seq.value()
            || source_revision.state_revision.value() > snapshot.version().state_revision.value()
        {
            return Err(ApiError::invalid_request(
                "requested semantic source revision is not committed on the Timeline",
            ));
        }

        let mut internal = SemanticProjectionQuery::new(
            SemanticProjectionKey::new(
                query.target.world_id,
                query.target.timeline_id,
                query.index_id.clone().into(),
            ),
            query.source_schema_revision,
            query.projection_revision,
            query.model_revision.clone(),
            query.vector,
            query.limit,
        )
        .map_err(map_public_semantic_projection_error)?
        .with_max_result_bytes(query.max_result_bytes)
        .with_depth(query.depth);
        if let Some(source_hash) = query.source_hash {
            internal = internal.with_filter(SemanticProjectionFilter::source_hash(source_hash));
        }
        let hits = self
            .query_semantic_projection(internal)
            .await
            .map_err(map_public_semantic_projection_error)?;
        if let Some(actual) = hits
            .iter()
            .map(|hit| hit.source_revision)
            .find(|actual| *actual != source_revision)
        {
            return Err(ApiError::semantic_projection_stale(format!(
                "semantic projection source revision is stale: requested {source_revision:?}, materialized {actual:?}"
            )));
        }
        Ok(ApiSemanticProjectionRead {
            target: query.target,
            index_id: query.index_id,
            source_revision,
            source_schema_revision: query.source_schema_revision,
            projection_revision: query.projection_revision,
            model_revision: query.model_revision,
            hits: hits.into_iter().map(api_semantic_projection_hit).collect(),
        })
    }

    /// Registers one projection scope after checking its metadata against the
    /// Capability-owned semantic index definition.
    ///
    /// # Errors
    ///
    /// Returns a typed metadata, registry or persistence error.
    pub async fn register_semantic_projection(
        &self,
        registration: SemanticProjectionRegistration,
    ) -> Result<(), SemanticProjectionError> {
        registration.validate()?;
        validate_projection_registration(&self.registry, &registration)?;
        self.store.register_semantic_projection(registration).await
    }

    /// Queries one registered projection through the Runtime-owned port.
    /// Storage never receives a Capability registry or a provider handle.
    ///
    /// # Errors
    ///
    /// Returns a typed registry, bound, mismatch or persistence error.
    pub async fn query_semantic_projection(
        &self,
        query: SemanticProjectionQuery,
    ) -> Result<Vec<SemanticProjectionHit>, SemanticProjectionError> {
        query.validate()?;
        let policy = self.resolution_budget;
        if let Some(limit) = policy.max_semantic_results()
            && usize::try_from(query.limit).unwrap_or(usize::MAX) > limit
        {
            return Err(SemanticProjectionError::LimitExceeded {
                limit: u32::try_from(limit).unwrap_or(u32::MAX),
                actual: query.limit,
            });
        }
        if let Some(limit) = policy.max_semantic_result_bytes()
            && usize::try_from(query.max_result_bytes).unwrap_or(usize::MAX) > limit
        {
            return Err(SemanticProjectionError::LimitExceeded {
                limit: u32::try_from(limit).unwrap_or(u32::MAX),
                actual: query.max_result_bytes,
            });
        }
        if let Some(limit) = policy.max_semantic_depth()
            && usize::try_from(query.depth).unwrap_or(usize::MAX) > limit
        {
            return Err(SemanticProjectionError::LimitExceeded {
                limit: u32::try_from(limit).unwrap_or(u32::MAX),
                actual: query.depth,
            });
        }
        if let Some(limit) = policy.max_semantic_filters()
            && query.filters.len() > limit
        {
            return Err(SemanticProjectionError::LimitExceeded {
                limit: u32::try_from(limit).unwrap_or(u32::MAX),
                actual: u32::try_from(query.filters.len()).unwrap_or(u32::MAX),
            });
        }
        validate_projection_query_index(&self.registry, &query.key)?;
        self.ensure_semantic_index_enabled(
            query.key.world_id,
            query.key.timeline_id,
            &query.key.index_id,
        )
        .await?;
        self.store.query_semantic_projection(query).await
    }

    /// Atomically rebuilds one projection after checking its definition and
    /// bounded row set.
    ///
    /// # Errors
    ///
    /// Returns a typed registry, revision, bound or persistence error.
    pub async fn rebuild_semantic_projection(
        &self,
        rebuild: &SemanticProjectionRebuild,
    ) -> Result<(), SemanticProjectionError> {
        rebuild.validate()?;
        validate_projection_registration(&self.registry, &rebuild.registration)?;
        self.store.rebuild_semantic_projection(rebuild).await
    }

    /// Deletes only the projection materialization; World authority is not
    /// addressed by this operation.
    ///
    /// # Errors
    ///
    /// Returns a typed registry or persistence error.
    pub async fn delete_semantic_projection(
        &self,
        key: SemanticProjectionKey,
    ) -> Result<(), SemanticProjectionError> {
        validate_projection_query_index(&self.registry, &key)?;
        self.store.delete_semantic_projection(key).await
    }

    async fn ensure_semantic_index_enabled(
        &self,
        world_id: loom_core::WorldId,
        timeline_id: TimelineId,
        index_id: &loom_capability::SemanticIndexId,
    ) -> Result<(), SemanticProjectionError> {
        let binding = self
            .store
            .read_binding(world_id)
            .await
            .map_err(|error| match error {
                BindingError::WorldNotFound { world_id } => {
                    SemanticProjectionError::ScopeNotFound {
                        world_id,
                        timeline_id,
                    }
                }
                BindingError::BindingNotFound { .. }
                | BindingError::BindingAlreadyExists { .. }
                | BindingError::StorageUnavailable { .. } => {
                    SemanticProjectionError::StorageUnavailable {
                        message: "World Runtime Binding is unavailable".to_owned(),
                    }
                }
            })?;
        let index = self
            .registry
            .semantic_index(index_id)
            .expect("query index was validated immediately before availability check");
        let manifest = self
            .registry
            .capability(&index.owner)
            .expect("registered semantic index owner must have a manifest");
        if !binding.allows(&index.owner, &manifest.version) {
            return Err(SemanticProjectionError::MetadataMismatch {
                field: "world_binding".to_owned(),
                expected: "enabled".to_owned(),
                actual: "disabled".to_owned(),
            });
        }
        let active = self
            .store
            .select_active_revision()
            .await
            .map_err(|_| SemanticProjectionError::StorageUnavailable {
                message: "Runtime Revision selection is unavailable".to_owned(),
            })?
            .ok_or_else(|| SemanticProjectionError::StorageUnavailable {
                message: "Runtime Revision selection is unavailable".to_owned(),
            })?;
        if !active
            .revision()
            .capability(&index.owner)
            .is_some_and(|implementation| {
                implementation.version() == &manifest.version
                    && implementation.loom_compatibility() == &manifest.loom_compatibility
            })
        {
            return Err(SemanticProjectionError::MetadataMismatch {
                field: "runtime_revision".to_owned(),
                expected: "compatible".to_owned(),
                actual: "incompatible".to_owned(),
            });
        }
        Ok(())
    }
}

fn validate_projection_query_index(
    registry: &CapabilityRegistry,
    key: &SemanticProjectionKey,
) -> Result<(), SemanticProjectionError> {
    if registry.semantic_index(&key.index_id).is_none() {
        return Err(SemanticProjectionError::IndexNotRegistered { key: key.clone() });
    }
    Ok(())
}

fn validate_projection_registration(
    registry: &CapabilityRegistry,
    registration: &SemanticProjectionRegistration,
) -> Result<(), SemanticProjectionError> {
    let Some(index) = registry.semantic_index(&registration.key.index_id) else {
        return Err(SemanticProjectionError::IndexNotRegistered {
            key: registration.key.clone(),
        });
    };
    let definition = &index.definition;
    if definition.source != registration.source {
        return Err(SemanticProjectionError::SourceMismatch {
            expected: format!("{:?}", definition.source),
            actual: format!("{:?}", registration.source),
        });
    }
    if definition.schema_revision != registration.schema_revision {
        return Err(SemanticProjectionError::MetadataMismatch {
            field: "schema_revision".to_owned(),
            expected: definition.schema_revision.value().to_string(),
            actual: registration.schema_revision.value().to_string(),
        });
    }
    if definition.projection_revision != registration.projection_revision {
        return Err(SemanticProjectionError::RevisionMismatch {
            expected: definition.projection_revision,
            actual: registration.projection_revision,
        });
    }
    if definition.model_revision != registration.model_revision {
        return Err(SemanticProjectionError::MetadataMismatch {
            field: "model_revision".to_owned(),
            expected: definition.model_revision.clone(),
            actual: registration.model_revision.clone(),
        });
    }
    if definition.dimensions != registration.dimensions {
        return Err(SemanticProjectionError::DimensionMismatch {
            expected: definition.dimensions.to_string(),
            actual: registration.dimensions.to_string(),
        });
    }
    if definition.metric != registration.metric {
        return Err(SemanticProjectionError::MetadataMismatch {
            field: "metric".to_owned(),
            expected: definition.metric.as_str().to_owned(),
            actual: registration.metric.as_str().to_owned(),
        });
    }
    Ok(())
}

/// Lower operational bound used by Runtime even though the public API permits
/// a larger request. The page reader receives this bound before any history
/// access, so over-demand cannot turn into an oversized read.
pub const MAX_CHANGE_FEED_OPERATIONAL_PAGE_SIZE: u32 = 256;

fn query_limit(limit: Option<u32>, budget: HistoryBudget) -> ApiResult<usize> {
    let max_limit = budget.max_query_page_size();
    let limit = limit.unwrap_or(max_limit);
    if limit == 0 || limit > max_limit {
        return Err(ApiError::invalid_request(format!(
            "query limit must be between 1 and {max_limit}"
        )));
    }
    Ok(usize::try_from(limit).expect("the bounded query limit fits usize"))
}

fn history_page<'a, I>(events: I, query: EventQuery, budget: HistoryBudget) -> ApiResult<EventPage>
where
    I: IntoIterator<Item = &'a CommittedEvent>,
{
    let limit = query_limit(query.limit, budget)?;
    let mut matching: Vec<_> = events
        .into_iter()
        .filter(|event| query.after.is_none_or(|after| event.event_seq > after))
        .take(limit + 1)
        .collect();
    let next_after = if matching.len() > limit {
        matching.truncate(limit);
        matching.last().map(|event| event.sequence())
    } else {
        None
    };
    Ok(EventPage {
        events: matching.into_iter().map(api_event).collect(),
        next_after,
    })
}

fn validate_causal_query(query: CausalQuery, budget: HistoryBudget) -> ApiResult<()> {
    let max_depth = budget.max_causal_depth();
    let max_results = budget.max_causal_results();
    if query.max_depth == 0 || query.max_depth > max_depth {
        return Err(ApiError::invalid_request(format!(
            "causal max_depth must be between 1 and {max_depth}"
        )));
    }
    if query.limit == 0 || query.limit > max_results {
        return Err(ApiError::invalid_request(format!(
            "causal limit must be between 1 and {max_results}"
        )));
    }
    Ok(())
}

fn visible_event(snapshot: &TimelineSnapshot, event_ref: EventRef) -> Option<&CommittedEvent> {
    snapshot
        .events
        .iter()
        .find(|event| event.event_ref() == event_ref)
}

fn causal_neighbors(
    snapshot: &TimelineSnapshot,
    event: &CommittedEvent,
    direction: CausalDirection,
) -> Vec<EventRef> {
    let mut neighbors: Vec<EventRef> = match direction {
        CausalDirection::Causes => event
            .causal_links
            .iter()
            .filter_map(|link| {
                snapshot
                    .events
                    .iter()
                    .find(|candidate| candidate.id == link.event_id())
                    .map(CommittedEvent::event_ref)
            })
            .collect(),
        CausalDirection::Effects => snapshot
            .events
            .iter()
            .filter(|candidate| {
                candidate
                    .causal_links
                    .iter()
                    .any(|link| link.event_id() == event.id)
            })
            .map(CommittedEvent::event_ref)
            .collect(),
    };
    neighbors.sort_by(|left, right| {
        let left_event = visible_event(snapshot, *left)
            .expect("causal neighbor must belong to the visible snapshot");
        let right_event = visible_event(snapshot, *right)
            .expect("causal neighbor must belong to the visible snapshot");
        (left_event.event_seq, left_event.timeline_id, left_event.id).cmp(&(
            right_event.event_seq,
            right_event.timeline_id,
            right_event.id,
        ))
    });
    neighbors.dedup();
    neighbors
}

fn catalog_owner_visible(owner: &CapabilityId, available: Option<&HashSet<CapabilityId>>) -> bool {
    available.is_none_or(|available| available.contains(owner))
}

fn project_catalog(
    registry: &CapabilityRegistry,
    available: Option<&HashSet<CapabilityId>>,
) -> CatalogSnapshot {
    let capabilities = registry
        .capabilities()
        .filter(|manifest| catalog_owner_visible(&manifest.id, available))
        .map(api_capability_descriptor)
        .collect();
    let actions = registry
        .actions()
        .filter(|action| catalog_owner_visible(&action.owner, available))
        .map(api_action_descriptor)
        .collect();
    let facets = registry
        .facets()
        .filter(|facet| catalog_owner_visible(&facet.owner, available))
        .map(api_facet_descriptor)
        .collect();
    let relationships = registry
        .relationships()
        .filter(|relationship| catalog_owner_visible(&relationship.owner, available))
        .map(api_relationship_descriptor)
        .collect();
    let events = registry
        .events()
        .filter(|event| catalog_owner_visible(&event.owner, available))
        .map(api_event_descriptor)
        .collect();
    let work_handlers = registry
        .work_handlers()
        .filter(|handler| catalog_owner_visible(&handler.owner, available))
        .map(api_work_handler_descriptor)
        .collect();
    let mut reactions: Vec<_> = registry
        .reactions()
        .filter(|reaction| catalog_owner_visible(&reaction.owner, available))
        .map(api_reaction_descriptor)
        .collect();
    reactions.sort_by(|left, right| {
        (&left.event_type, &left.handler, &left.owner).cmp(&(
            &right.event_type,
            &right.handler,
            &right.owner,
        ))
    });
    let semantic_indexes = registry
        .semantic_indexes()
        .filter(|index| catalog_owner_visible(&index.owner, available))
        .map(api_semantic_index_descriptor)
        .collect();
    CatalogSnapshot {
        capabilities,
        actions,
        facets,
        relationships,
        events,
        work_handlers,
        reactions,
        semantic_indexes,
    }
}

fn api_capability_descriptor(
    manifest: &loom_capability::CapabilityManifest,
) -> loom_api::CapabilityDescriptor {
    loom_api::CapabilityDescriptor {
        id: manifest.id.as_str().into(),
        version: manifest.version.to_string(),
        loom_compatibility: manifest.loom_compatibility.to_string(),
        description: manifest.description.clone(),
        dependencies: manifest
            .dependencies
            .iter()
            .map(|dependency| dependency.id.as_str().into())
            .collect(),
        dependency_requirements: manifest
            .dependencies
            .iter()
            .map(|dependency| loom_api::CapabilityDependencyDescriptor {
                id: dependency.id.as_str().into(),
                version: dependency.version.to_string(),
            })
            .collect(),
    }
}

fn api_action_descriptor(action: &loom_capability::RegisteredAction) -> ActionDescriptor {
    ActionDescriptor {
        id: action.definition.id.clone(),
        owner: action.owner.as_str().into(),
        schema_revision: action.definition.schema_revision,
        description: action.definition.description.clone(),
        input_schema: action.definition.input_schema.clone(),
    }
}

fn api_facet_descriptor(facet: &loom_capability::RegisteredFacet) -> FacetDescriptor {
    FacetDescriptor {
        id: facet.definition.id.clone(),
        owner: facet.owner.as_str().into(),
        schema_revision: facet.definition.schema_revision,
        description: facet.definition.description.clone(),
        schema: facet.definition.schema.clone(),
    }
}

fn api_relationship_descriptor(
    relationship: &loom_capability::RegisteredRelationship,
) -> RelationshipDescriptor {
    RelationshipDescriptor {
        id: relationship.definition.id.clone(),
        owner: relationship.owner.as_str().into(),
        schema_revision: relationship.definition.schema_revision,
        roles: relationship
            .definition
            .roles
            .iter()
            .map(|role| RelationshipRoleDescriptor {
                role: role.role.clone(),
                minimum: role.minimum,
                maximum: role.maximum,
            })
            .collect(),
        allowed_facets: relationship.definition.allowed_facets.clone(),
        description: relationship.definition.description.clone(),
    }
}

fn api_event_descriptor(event: &loom_capability::RegisteredEvent) -> EventDescriptor {
    EventDescriptor {
        id: event.definition.id.clone(),
        owner: event.owner.as_str().into(),
        schema_revision: event.definition.schema_revision,
        payload_schema: event.definition.payload_schema.clone(),
        participant_roles: event.definition.participant_roles.clone(),
        relationship_roles: event.definition.relationship_roles.clone(),
        description: event.definition.description.clone(),
    }
}

fn api_work_handler_descriptor(
    handler: &loom_capability::RegisteredWorkHandler,
) -> WorkHandlerDescriptor {
    WorkHandlerDescriptor {
        id: handler.definition.id.clone(),
        owner: handler.owner.as_str().into(),
        schema_revision: handler.definition.schema_revision,
        payload_schema: handler.definition.payload_schema.clone(),
        description: handler.definition.description.clone(),
    }
}

fn api_reaction_descriptor(reaction: &loom_capability::RegisteredReaction) -> ReactionDescriptor {
    ReactionDescriptor {
        owner: reaction.owner.as_str().into(),
        event_type: reaction.reaction.event_type.clone(),
        handler: reaction.reaction.handler.clone(),
    }
}

fn api_semantic_index_descriptor(
    index: &loom_capability::RegisteredSemanticIndex,
) -> SemanticIndexDescriptor {
    SemanticIndexDescriptor {
        id: index.definition.id.as_str().to_owned(),
        owner: index.owner.as_str().into(),
        source_kind: index.definition.source.kind.clone(),
        source_type_id: index.definition.source.type_id.clone(),
        source_schema_revision: index.definition.source.schema_revision,
        schema_revision: index.definition.schema_revision,
        projection_revision: index.definition.projection_revision,
        model_revision: index.definition.model_revision.clone(),
        dimensions: index.definition.dimensions,
        metric: index.definition.metric.as_str().to_owned(),
        configuration: index.definition.configuration.clone(),
        description: index.definition.description.clone(),
    }
}

fn api_admin_revision(revision: &RuntimeRevisionDescriptor) -> AdminRuntimeRevision {
    AdminRuntimeRevision {
        revision_id: revision.id().to_string(),
        published_at: revision.published_at().value(),
        core_build_ref: revision.core_build_ref().to_owned(),
        loom_version: revision.loom_version().to_string(),
        capabilities: revision
            .capabilities()
            .values()
            .map(|capability| AdminRuntimeRevisionCapability {
                capability_id: capability.capability_id().to_string(),
                implementation_id: capability.implementation_id().to_owned(),
                version: capability.version().to_string(),
                loom_compatibility: capability.loom_compatibility().to_string(),
            })
            .collect(),
        execution_policy_id: revision.execution_policy_id().map(str::to_owned),
        provider_policy_id: revision.provider_policy_id().map(str::to_owned),
        change_summary: revision.change_summary().map(str::to_owned),
        semantic_behavior_changed: revision.semantic_behavior_changed(),
    }
}

fn api_admin_revision_selection(
    selection: &RuntimeRevisionSelection,
) -> AdminRuntimeRevisionSelection {
    AdminRuntimeRevisionSelection {
        revision: api_admin_revision(selection.revision()),
        generation: selection.generation(),
        activated_at: selection.activated_at().value(),
    }
}

fn api_admin_origin(origin: ExecutionOrigin) -> AdminExecutionOrigin {
    match origin {
        ExecutionOrigin::Application => AdminExecutionOrigin::Application,
        ExecutionOrigin::Ingress => AdminExecutionOrigin::Ingress,
        ExecutionOrigin::Operator => AdminExecutionOrigin::Operator,
        ExecutionOrigin::Runtime => AdminExecutionOrigin::Runtime,
    }
}

fn api_admin_session_status(status: ExecutionSessionStatus) -> AdminExecutionSessionStatus {
    match status {
        ExecutionSessionStatus::Started => AdminExecutionSessionStatus::Started,
        ExecutionSessionStatus::Committed => AdminExecutionSessionStatus::Committed,
        ExecutionSessionStatus::NoChange => AdminExecutionSessionStatus::NoChange,
        ExecutionSessionStatus::Rejected => AdminExecutionSessionStatus::Rejected,
        ExecutionSessionStatus::Failed => AdminExecutionSessionStatus::Failed,
        ExecutionSessionStatus::Blocked => AdminExecutionSessionStatus::Blocked,
    }
}

fn api_admin_cognitive_disposition(disposition: CognitiveDisposition) -> AdminCognitiveDisposition {
    match disposition {
        CognitiveDisposition::Fresh => AdminCognitiveDisposition::Fresh,
        CognitiveDisposition::Reused => AdminCognitiveDisposition::Reused,
        CognitiveDisposition::Discarded => AdminCognitiveDisposition::Discarded,
    }
}

fn api_admin_cognitive_outcome(outcome: &CognitiveOutcome) -> AdminCognitiveOutcome {
    match outcome {
        CognitiveOutcome::Act => AdminCognitiveOutcome::Act,
        CognitiveOutcome::NoAction => AdminCognitiveOutcome::NoAction,
        CognitiveOutcome::Error(_) => AdminCognitiveOutcome::Error,
    }
}

fn api_admin_decision_reuse(policy: DecisionReusePolicy) -> AdminDecisionReusePolicy {
    match policy {
        DecisionReusePolicy::Resample => AdminDecisionReusePolicy::Resample,
        DecisionReusePolicy::ReuseDeterministic => AdminDecisionReusePolicy::ReuseDeterministic,
    }
}

fn api_admin_cognitive_evidence(evidence: &CognitiveEvidence) -> AdminCognitiveEvidence {
    AdminCognitiveEvidence {
        observations: evidence
            .observations()
            .iter()
            .map(|observation| AdminCognitiveObservation {
                ordinal: observation.ordinal,
                executor_id: observation.metadata.executor.id.clone(),
                executor_revision: observation.metadata.executor.revision.clone(),
                provider_id: observation
                    .metadata
                    .provider
                    .as_ref()
                    .map(|provider| provider.id.clone()),
                provider_revision: observation
                    .metadata
                    .provider
                    .as_ref()
                    .map(|provider| provider.revision.clone()),
                model_id: observation
                    .metadata
                    .model
                    .as_ref()
                    .map(|model| model.id.clone()),
                model_revision: observation
                    .metadata
                    .model
                    .as_ref()
                    .map(|model| model.revision.clone()),
                policy_id: observation.policy.policy_id.clone(),
                policy_revision: observation.policy.revision.clone(),
                decision_reuse: api_admin_decision_reuse(observation.policy.decision_reuse),
                agent: observation.agent.entity_id,
                timeline_id: observation.timeline_id,
                version: observation.version,
                world_time: observation.world_time,
                context_entries: observation.context_usage.entries,
                context_bytes: observation.context_usage.bytes,
                context_entities: observation.context_usage.entities,
                context_relationships: observation.context_usage.relationships,
                context_events: observation.context_usage.events,
                context_semantic_results: observation.context_usage.semantic_results,
                context_depth: observation.context_usage.depth,
                context_semantic_queries: observation.context_usage.semantic_queries,
                outcome: api_admin_cognitive_outcome(&observation.outcome),
                disposition: api_admin_cognitive_disposition(observation.disposition),
            })
            .collect(),
        fresh_count: evidence.fresh_count(),
        reused_count: evidence.reused_count(),
        discarded_count: evidence.discarded_count(),
        context_entries: evidence.context_entries(),
        context_bytes: evidence.context_bytes(),
    }
}

fn api_admin_read_dependency(dependency: &ReadDependency) -> AdminReadDependency {
    match dependency {
        ReadDependency::Entity { entity_id, present } => AdminReadDependency::Entity {
            entity_id: *entity_id,
            present: *present,
        },
        ReadDependency::Relationship {
            relationship_id,
            present,
        } => AdminReadDependency::Relationship {
            relationship_id: *relationship_id,
            present: *present,
        },
        ReadDependency::Facet {
            owner,
            facet_type,
            schema_revision,
        } => AdminReadDependency::Facet {
            owner: *owner,
            facet_type: facet_type.clone(),
            schema_revision: *schema_revision,
        },
        ReadDependency::Event { event_id, present } => AdminReadDependency::Event {
            event_id: *event_id,
            present: *present,
        },
        ReadDependency::Semantic {
            index_id,
            query_fingerprint,
            source_schema_revision,
            projection_revision,
            model_revision,
            source_refs,
            ..
        } => AdminReadDependency::Semantic {
            index_id: index_id.to_string(),
            query_fingerprint: query_fingerprint.clone(),
            source_schema_revision: *source_schema_revision,
            projection_revision: *projection_revision,
            model_revision: model_revision.clone(),
            source_refs: source_refs.clone(),
        },
    }
}

fn api_admin_session(session: &ExecutionSession) -> AdminExecutionSession {
    let assembly = session.assembly();
    let root = session.root();
    AdminExecutionSession {
        id: session.id(),
        origin: api_admin_origin(session.origin()),
        target: TimelineTarget::new(assembly.world_id(), assembly.timeline_id()),
        expected_version: assembly.expected_version(),
        world_time: assembly.world_time(),
        runtime_revision_id: assembly.runtime_revision().revision().id().to_string(),
        root: AdminExecutionRoot {
            action: root.action.clone(),
            target_work: root.target_work,
            current_work: root.current_work,
            ingress: root
                .ingress
                .as_ref()
                .map(|ingress| ingress.as_str().to_owned()),
            bootstrap: root.bootstrap.clone(),
            agency: root.agency.clone(),
        },
        started_at: session.started_at().value(),
        ended_at: session.ended_at().map(PlatformTime::value),
        status: api_admin_session_status(session.status()),
        no_change: session.is_no_change(),
        event_refs: session.event_refs().to_vec(),
        read_set: session
            .read_set()
            .entries()
            .iter()
            .map(api_admin_read_dependency)
            .collect(),
        call_provenance: session
            .call_provenance()
            .edges()
            .iter()
            .map(|edge| AdminResolutionCallEdge {
                caller_capability: edge.caller_capability.to_string(),
                caller_action: edge.caller_action.clone(),
                target_capability: edge.target_capability.to_string(),
                target_action: edge.target_action.clone(),
            })
            .collect(),
        entropy_evidence: AdminEntropyEvidence {
            source_id: session.entropy_evidence().source_id().to_string(),
            observations: session
                .entropy_evidence()
                .observations()
                .iter()
                .map(|observation| AdminEntropyObservation {
                    ordinal: observation.ordinal,
                    requested_bytes: observation.request.byte_count(),
                })
                .collect(),
        },
        cognitive_evidence: api_admin_cognitive_evidence(session.cognitive_evidence()),
        commit_provenance: session
            .commit_provenance()
            .map(|provenance| AdminCommitProvenance {
                session_id: provenance.session_id,
                ingress_id: provenance.ingress_id.as_str().to_owned(),
                proposal_identity: provenance.proposal_identity.clone(),
                expected_after_version: provenance.expected_after_version,
                expected_event_ids: provenance.expected_event_ids.clone(),
                logical_work_transition_count: u64::try_from(
                    provenance.logical_work_transitions.len(),
                )
                .expect("logical Work transition count must fit the public count"),
            }),
    }
}

fn api_admin_work_status(status: WorkStatus) -> AdminWorkStatus {
    match status {
        WorkStatus::Pending => AdminWorkStatus::Pending,
        WorkStatus::Completed => AdminWorkStatus::Completed,
        WorkStatus::Cancelled => AdminWorkStatus::Cancelled,
        WorkStatus::Dead => AdminWorkStatus::Dead,
    }
}

fn api_admin_missing_implementation(
    block: TimelineBlockedOnMissingImplementation,
) -> ApiResult<AdminMissingImplementationBlock> {
    let semantic_requirement = serde_json::to_value(block.semantic_requirement)
        .map_err(|_| ApiError::internal("Runtime liveness value could not be projected"))?;
    Ok(AdminMissingImplementationBlock {
        world_id: block.world_id,
        timeline_id: block.timeline_id,
        work_id: block.work_id,
        semantic_requirement,
        active_runtime_revision: block.active_runtime_revision.to_string(),
        first_observed_platform_time: block.first_observed_platform_time.map(PlatformTime::value),
        last_observed_platform_time: block.last_observed_platform_time.value(),
    })
}

fn version_before(candidate: TimelineVersion, boundary: TimelineVersion) -> bool {
    candidate.head_event_seq < boundary.head_event_seq
        || candidate.state_revision < boundary.state_revision
}

fn logical_work_seed(work: &WorkRecord) -> LogicalWorkState {
    LogicalWorkState {
        work_id: work.id,
        target: work.target.clone(),
        schema_revision: work.schema_revision,
        payload: work.payload.clone(),
        effective_due_world_time: work.effective_due_world_time,
        logical_schedule_order: work.logical_schedule_order,
        causal_event_id: work.causal_event_id,
        origin_work_id: work.origin_work_id,
        status: WorkStatus::Pending,
    }
}

impl<S> TimelineService for Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore,
{
    fn inspect_timeline(&self, target: TimelineTarget) -> ApiFuture<'_, ApiTimelineSnapshot> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(target).await?;
            Ok(ApiTimelineSnapshot::with_ancestry(
                target,
                snapshot.version(),
                snapshot.world_time(),
                snapshot.ancestry(),
            ))
        })
    }

    fn fork(&self, request: ForkTimelineRequest) -> ApiFuture<'_, ApiTimelineSnapshot> {
        Box::pin(async move { self.fork_head(request).await })
    }
}

impl<S> QueryService for Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore
        + SemanticProjectionStore,
{
    fn get_facet(&self, query: FacetQuery) -> ApiFuture<'_, Option<ApiFacetSnapshot>> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(query.target).await?;
            let view = snapshot.world_view();
            Ok(view.facet(query.owner, &query.facet_type).map(|facet| {
                ApiFacetSnapshot::new(
                    facet.owner(),
                    facet.facet_type().clone(),
                    facet.schema_revision(),
                    facet.value().clone(),
                )
            }))
        })
    }

    fn query_semantic_projection(
        &self,
        query: ApiSemanticProjectionQuery,
    ) -> ApiFuture<'_, ApiSemanticProjectionRead> {
        Box::pin(async move { self.read_semantic_projection(query).await })
    }

    fn read_blob(&self, request: ApiBlobReadRequest) -> ApiFuture<'_, ApiBlobReadResult> {
        Box::pin(async move {
            let store = self
                .blob_store
                .as_ref()
                .ok_or_else(|| ApiError::blob_unavailable("BlobStore is not configured"))?;
            let reference = runtime_blob_reference(&request.reference)?;
            let object = store
                .read(&reference)
                .await
                .map_err(|error| map_blob_error(&error))?;
            Ok(ApiBlobReadResult {
                reference: api_blob_reference(object.reference()),
                bytes: object.into_bytes(),
            })
        })
    }
}

impl<S> HistoryService for Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore,
{
    fn list_events(&self, query: EventQuery) -> ApiFuture<'_, Vec<ApiCommittedEvent>> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(query.target).await?;
            Ok(history_page(snapshot.events.iter(), query, self.history_budget)?.events)
        })
    }

    fn list_events_page(&self, query: EventQuery) -> ApiFuture<'_, EventPage> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(query.target).await?;
            history_page(snapshot.events.iter(), query, self.history_budget)
        })
    }

    fn get_event(&self, event_ref: EventRef) -> ApiFuture<'_, Option<ApiCommittedEvent>> {
        Box::pin(async move {
            let snapshot = self
                .store
                .snapshot(event_ref.timeline_id)
                .await
                .map_err(|error| map_read_error(&error))?;
            Ok(snapshot
                .events
                .iter()
                .find(|event| event.event_ref() == event_ref)
                .map(api_event))
        })
    }

    fn direct_causes(&self, event_ref: EventRef) -> ApiFuture<'_, Vec<EventRef>> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_event_ref(event_ref).await?;
            let event = visible_event(&snapshot, event_ref)
                .ok_or_else(|| ApiError::not_found(format!("Event {event_ref:?} was not found")))?;
            Ok(causal_neighbors(&snapshot, event, CausalDirection::Causes))
        })
    }

    fn direct_effects(&self, event_ref: EventRef) -> ApiFuture<'_, Vec<EventRef>> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_event_ref(event_ref).await?;
            let event = visible_event(&snapshot, event_ref)
                .ok_or_else(|| ApiError::not_found(format!("Event {event_ref:?} was not found")))?;
            Ok(causal_neighbors(&snapshot, event, CausalDirection::Effects))
        })
    }

    fn causal_walk(&self, query: CausalQuery) -> ApiFuture<'_, CausalTraversal> {
        Box::pin(async move {
            validate_causal_query(query, self.history_budget)?;
            let snapshot = self.snapshot_for_event_ref(query.root).await?;
            if visible_event(&snapshot, query.root).is_none() {
                return Err(ApiError::not_found(format!(
                    "Event {:?} was not found",
                    query.root
                )));
            }

            let mut queue = std::collections::VecDeque::from([(query.root, 0_u32)]);
            let mut visited = HashSet::from([query.root]);
            let mut events = Vec::new();
            let mut truncated = false;
            while let Some((current, depth)) = queue.pop_front() {
                if depth >= query.max_depth {
                    continue;
                }
                let Some(current_event) = visible_event(&snapshot, current) else {
                    continue;
                };
                for next in causal_neighbors(&snapshot, current_event, query.direction) {
                    if !visited.insert(next) {
                        continue;
                    }
                    if events.len() >= usize::try_from(query.limit).unwrap_or(usize::MAX) {
                        truncated = true;
                        continue;
                    }
                    events.push(next);
                    queue.push_back((next, depth + 1));
                }
            }
            Ok(CausalTraversal { events, truncated })
        })
    }

    fn entity_trajectory(&self, query: EntityTrajectoryQuery) -> ApiFuture<'_, TrajectoryPage> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(query.target).await?;
            history_page(
                snapshot.events.iter().filter(|event| {
                    event
                        .participants
                        .iter()
                        .any(|participant| participant.entity_id == query.entity_id)
                }),
                EventQuery {
                    target: query.target,
                    after: query.after,
                    limit: query.limit,
                },
                self.history_budget,
            )
        })
    }

    fn relationship_trajectory(
        &self,
        query: RelationshipTrajectoryQuery,
    ) -> ApiFuture<'_, TrajectoryPage> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(query.target).await?;
            history_page(
                snapshot.events.iter().filter(|event| {
                    event
                        .relationship_refs
                        .iter()
                        .any(|relationship| relationship.relationship_id == query.relationship_id)
                }),
                EventQuery {
                    target: query.target,
                    after: query.after,
                    limit: query.limit,
                },
                self.history_budget,
            )
        })
    }
}

impl<S> SubscriptionService for Runtime<S>
where
    S: ChangeFeedStore,
{
    fn subscribe(&self, request: SubscriptionRequest) -> ApiFuture<'_, SubscriptionResult> {
        Box::pin(async move {
            request.validate()?;
            let operational_limit = self.history_budget.max_change_feed_page_size();
            if request.limit > operational_limit {
                return Ok(SubscriptionResult::Backpressure(SubscriptionBackpressure {
                    resume_from: request.resume_from,
                    retry_after_ms: None,
                    max_events: operational_limit,
                }));
            }

            let after = request
                .resume_from
                .map_or_else(|| EventSeq::new(0), |cursor| cursor.after);
            let limit = usize::try_from(request.limit)
                .expect("validated Change Feed limit must fit the platform usize");
            let page = self
                .store
                .read_change_feed(request.target.timeline_id, after, limit)
                .await
                .map_err(|error| map_read_error(&error))?;
            if page.world_id != request.target.world_id {
                return Err(ApiError::not_found(format!(
                    "Timeline {} is not in World {}",
                    request.target.timeline_id, request.target.world_id
                )));
            }

            let next_cursor = page
                .events
                .last()
                .map(|event| ChangeFeedCursor::after(request.target, event.sequence()));
            if page.events.is_empty()
                && let Some(cursor) = request.resume_from
            {
                return Ok(SubscriptionResult::Resumed(SubscriptionResume { cursor }));
            }

            Ok(SubscriptionResult::Events(ApiChangeFeedPage {
                events: page.events.iter().map(api_event).collect(),
                next_cursor,
                has_more: page.has_more,
            }))
        })
    }
}

impl<S> CatalogService for Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore,
{
    fn catalog(&self) -> ApiResult<CatalogSnapshot> {
        Ok(self.project_catalog(None))
    }

    fn catalog_for_world(&self, world_id: loom_core::WorldId) -> ApiFuture<'_, CatalogSnapshot> {
        Box::pin(async move {
            let binding = self.binding_for_world(world_id).await?;
            let selection = self
                .store
                .select_active_revision()
                .await
                .map_err(|error| map_runtime_revision_error(&error))?
                .ok_or_else(|| {
                    map_runtime_revision_error(&RuntimeRevisionError::NoActiveRevision)
                })?;
            let mut available = HashSet::new();
            for manifest in self.registry.capabilities() {
                let compatible_binding = binding.allows(&manifest.id, &manifest.version);
                let current_software =
                    selection
                        .revision()
                        .capability(&manifest.id)
                        .is_some_and(|implementation| {
                            implementation.version() == &manifest.version
                                && implementation.loom_compatibility()
                                    == &manifest.loom_compatibility
                        });
                if compatible_binding && current_software {
                    available.insert(manifest.id.clone());
                }
            }
            Ok(self.project_catalog(Some(&available)))
        })
    }
}

impl<S> AdminService for Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore
        + RuntimeControlStore
        + WorldTimeStore,
{
    fn active_runtime_revision(
        &self,
    ) -> loom_api::AdminFuture<'_, Option<AdminRuntimeRevisionSelection>> {
        Box::pin(async move {
            self.active_runtime_revision()
                .await
                .map(|selection| selection.as_ref().map(api_admin_revision_selection))
                .map_err(|error| map_admin_runtime_revision_error(&error))
        })
    }

    fn list_runtime_revisions(&self) -> loom_api::AdminFuture<'_, Vec<AdminRuntimeRevision>> {
        Box::pin(async move {
            self.runtime_revisions()
                .await
                .map(|revisions| revisions.iter().map(api_admin_revision).collect())
                .map_err(|error| map_admin_runtime_revision_error(&error))
        })
    }

    fn get_runtime_revision(
        &self,
        request: AdminRuntimeRevisionRequest,
    ) -> loom_api::AdminFuture<'_, AdminRuntimeRevision> {
        Box::pin(async move {
            self.runtime_revision(RuntimeRevisionId::from(request.revision_id))
                .await
                .map(|revision| api_admin_revision(&revision))
                .map_err(|error| map_admin_runtime_revision_error(&error))
        })
    }

    fn activate_runtime_revision(
        &self,
        request: AdminActivateRuntimeRevisionRequest,
    ) -> loom_api::AdminFuture<'_, AdminRuntimeRevisionSelection> {
        Box::pin(async move {
            self.activate_runtime_revision(
                RuntimeRevisionId::from(request.revision_id),
                request.expected_generation,
                self.platform_clock.now(),
            )
            .await
            .map(|selection| api_admin_revision_selection(&selection))
            .map_err(|error| map_admin_runtime_revision_error(&error))
        })
    }

    fn list_execution_sessions(&self) -> loom_api::AdminFuture<'_, Vec<AdminExecutionSession>> {
        Box::pin(async move {
            self.store
                .list_sessions()
                .await
                .map(|sessions| sessions.iter().map(api_admin_session).collect())
                .map_err(|error| map_admin_session_error(&error))
        })
    }

    fn get_execution_session(
        &self,
        request: AdminExecutionSessionRequest,
    ) -> loom_api::AdminFuture<'_, AdminExecutionSession> {
        Box::pin(async move {
            self.store
                .read_session(request.session_id)
                .await
                .map(|session| api_admin_session(&session))
                .map_err(|error| map_admin_session_error(&error))
        })
    }

    fn session_for_event(
        &self,
        event_ref: EventRef,
    ) -> loom_api::AdminFuture<'_, AdminEventSessionLookup> {
        Box::pin(async move {
            let session_id = self
                .store
                .session_for_event(event_ref)
                .await
                .map_err(|error| map_admin_session_error(&error))?;
            Ok(AdminEventSessionLookup {
                event_ref,
                session_id,
            })
        })
    }

    fn timeline_logical_status(
        &self,
        target: TimelineTarget,
    ) -> loom_api::AdminFuture<'_, AdminTimelineLogicalStatus> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(target).await?;
            let chronology = snapshot.chronology_budget();
            let works = snapshot
                .works
                .iter()
                .map(|work| AdminLogicalWorkStatus {
                    work_id: work.id,
                    status: api_admin_work_status(work.status),
                    effective_due_world_time: work.effective_due_world_time,
                    logical_schedule_order: work.logical_schedule_order,
                })
                .collect();
            Ok(AdminTimelineLogicalStatus {
                target,
                version: snapshot.version(),
                world_time: snapshot.world_time(),
                chronology_budget: AdminChronologyBudget {
                    world_time: chronology.world_time,
                    consumed: chronology.consumed,
                },
                logical_revision: snapshot.version().state_revision,
                logical_commit_count: u64::try_from(snapshot.logical_journal().len())
                    .expect("logical journal length must fit the public count"),
                works,
            })
        })
    }

    fn missing_implementation(
        &self,
        request: AdminMissingImplementationRequest,
    ) -> loom_api::AdminFuture<'_, Option<AdminMissingImplementationBlock>> {
        Box::pin(async move {
            let block = self
                .missing_implementation_block(request.target, request.work_id)
                .await?;
            block.map(api_admin_missing_implementation).transpose()
        })
    }

    fn terminalize_work(
        &self,
        request: AdminTerminalizeWorkRequest,
    ) -> loom_api::AdminFuture<'_, AdminTerminalizeWorkResult> {
        Box::pin(async move {
            let terminal_state = match request.terminal_state {
                AdminTerminalWorkState::Dead => WorkTerminalState::Dead,
                AdminTerminalWorkState::Cancelled => WorkTerminalState::Cancelled,
            };
            let version = self
                .terminalize_work(
                    request.target,
                    request.work_id,
                    request.expected_version,
                    terminal_state,
                )
                .await?;
            Ok(AdminTerminalizeWorkResult {
                target: request.target,
                version,
                terminal_state: request.terminal_state,
            })
        })
    }

    fn schedule_agency_wake(
        &self,
        request: AdminScheduleAgencyWakeRequest,
    ) -> loom_api::AdminFuture<'_, AdminScheduleAgencyWakeResult> {
        Box::pin(async move { self.schedule_agency_wake(request).await })
    }

    fn advance_world_time(
        &self,
        request: AdminAdvanceWorldTimeRequest,
    ) -> loom_api::AdminFuture<'_, AdminAdvanceWorldTimeResult> {
        Box::pin(async move {
            // Resolve the public World/Timeline pair before touching the
            // Runtime-owned Timeline CAS port. The storage port is keyed by
            // TimelineId only and therefore must not be used as a World
            // authorization shortcut.
            let snapshot = self.snapshot_for_target(request.target).await?;
            let transition = AdvanceWorldTime::new(
                snapshot.timeline_id(),
                request.expected_version,
                request.current,
                request.next,
            )
            .map_err(|error| map_world_time_error(&error))?;
            let version = self
                .store
                .advance_world_time(transition)
                .await
                .map_err(|error| map_world_time_error(&error))?;
            Ok(AdminAdvanceWorldTimeResult {
                target: request.target,
                from: request.current,
                to: request.next,
                version,
            })
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct CallFrame {
    owner: CapabilityId,
    action: ActionTypeId,
}

#[derive(Clone, Debug)]
struct ExecutionState {
    budget: ResolutionBudget,
    usage: BudgetUsage,
    stack: Vec<CallFrame>,
    segments: Vec<ResolutionSegment>,
    call_provenance: CallProvenance,
    entropy_evidence: EntropyEvidence,
    read_set: crate::ReadSet,
    failure: Option<String>,
}

impl ExecutionState {
    fn new(budget: &ResolutionBudget, entropy_source_id: EntropySourceId) -> Self {
        Self {
            budget: *budget,
            usage: BudgetUsage::default(),
            stack: Vec::new(),
            segments: Vec::new(),
            call_provenance: CallProvenance::default(),
            entropy_evidence: EntropyEvidence::new(entropy_source_id),
            read_set: crate::ReadSet::default(),
            failure: None,
        }
    }

    fn enter_root(&mut self, frame: CallFrame) -> Result<(), String> {
        self.budget
            .check(self.usage)
            .map_err(|error| error.to_string())?;
        self.stack.push(frame);
        Ok(())
    }

    fn enter_child(&mut self, caller: &CallFrame, target: CallFrame) -> Result<(), String> {
        if self.stack.iter().any(|frame| frame == &target) {
            return Err(format!(
                "subresolution cycle detected for ({}, {})",
                target.owner, target.action
            ));
        }

        let depth = self.stack.len();
        let count = self.usage.subresolution_count().saturating_add(1);
        let usage = self.usage.with_subresolution(depth, count);
        self.budget
            .check(usage)
            .map_err(|error| error.to_string())?;

        self.call_provenance.record(crate::ResolutionCallEdge {
            caller_capability: caller.owner.clone(),
            caller_action: caller.action.clone(),
            target_capability: target.owner.clone(),
            target_action: target.action.clone(),
        });
        self.usage = usage;
        self.stack.push(target);
        Ok(())
    }

    fn leave(&mut self, frame: &CallFrame) {
        if self.stack.last() == Some(frame) {
            self.stack.pop();
        }
    }

    fn record_segment(
        &mut self,
        owner: CapabilityId,
        resolution: Resolution,
    ) -> Result<(), String> {
        let usage = self
            .usage
            .combine(BudgetUsage::from_resolution(&resolution));
        self.budget
            .check(usage)
            .map_err(|error| error.to_string())?;
        self.usage = usage;
        self.segments
            .push(ResolutionSegment::new(owner, resolution));
        Ok(())
    }

    fn record_failure(&mut self, message: String) {
        if self.failure.is_none() {
            self.failure = Some(message);
        }
    }

    fn reserve_entropy(&mut self, request_bytes: usize) -> Result<(), EntropyError> {
        if request_bytes == 0 {
            return Err(EntropyError::InvalidRequest {
                byte_count: request_bytes,
            });
        }
        let usage = self.usage.with_entropy(request_bytes);
        if let Err(error) = self.budget.check(usage) {
            return Err(entropy_budget_error(error));
        }
        self.usage = usage;
        Ok(())
    }

    fn record_entropy(&mut self, request: EntropyRequest, sample: EntropySample) {
        self.entropy_evidence.record(request, sample);
    }

    fn reserve_semantic(
        &mut self,
        depth: usize,
        filters: usize,
        result_limit: usize,
        result_bytes: usize,
    ) -> Result<(), BudgetError> {
        let request_usage = self.usage.with_semantic_request(depth, filters);
        let worst_case = request_usage.with_semantic_result(result_limit, result_bytes);
        self.budget.check(worst_case)?;
        self.usage = request_usage;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn record_semantic(
        &mut self,
        dependency: ReadDependency,
        result_bytes: usize,
    ) -> Result<(), BudgetError> {
        let source_count = match &dependency {
            ReadDependency::Semantic { source_refs, .. } => source_refs.len(),
            _ => 0,
        };
        let usage = self.usage.with_semantic_result(source_count, result_bytes);
        self.budget.check(usage)?;
        self.usage = usage;
        self.read_set.record(dependency);
        Ok(())
    }

    fn evidence(&self) -> ExecutionEvidence {
        ExecutionEvidence::from_parts(
            self.read_set.clone(),
            self.call_provenance.clone(),
            self.entropy_evidence.clone(),
        )
    }
}

fn append_entropy_evidence(target: &mut EntropyEvidence, additional: &EntropyEvidence) {
    debug_assert_eq!(target.source_id(), additional.source_id());
    let mut combined = EntropyEvidence::new(target.source_id().clone());
    for observation in target
        .observations()
        .iter()
        .chain(additional.observations())
    {
        combined.record(observation.request.clone(), observation.sample.clone());
    }
    *target = combined;
}

fn entropy_budget_error(error: BudgetError) -> EntropyError {
    #[allow(clippy::match_same_arms)]
    let dimension = match error.dimension {
        crate::BudgetDimension::EntropyRequests => EntropyBudgetDimension::Requests,
        crate::BudgetDimension::EntropyBytes => EntropyBudgetDimension::Bytes,
        crate::BudgetDimension::EntropyRequestBytes => EntropyBudgetDimension::RequestBytes,
        _ => EntropyBudgetDimension::Requests,
    };
    EntropyError::BudgetExceeded {
        dimension,
        limit: error.limit,
        actual: error.actual,
    }
}

struct RuntimeResolutionContext<'a> {
    base: &'a crate::BaseWorldView,
    registry: &'a CapabilityRegistry,
    assembly: &'a ExecutionAssembly,
    entropy_source: &'a dyn EntropySource,
    state: Rc<RefCell<ExecutionState>>,
    frame: CallFrame,
    semantic_store: Option<&'a dyn SemanticProjectionStore>,
}

impl ResolutionContext for RuntimeResolutionContext<'_> {
    fn base_world(&self) -> &dyn loom_capability::BaseWorldView {
        self.base
    }

    fn subresolve(
        &self,
        invocation: &ActionInvocation,
    ) -> Result<ResolveOutcome, ResolutionContextError> {
        dispatch_child_action(
            self.base,
            self.registry,
            self.assembly,
            self.entropy_source,
            &self.state,
            &self.frame,
            invocation,
        )
        .map_err(|error| {
            let message = error.to_string();
            self.state.borrow_mut().record_failure(message.clone());
            ResolutionContextError::new(message)
        })
    }

    fn request_entropy(
        &self,
        request: &EntropyRequest,
    ) -> Result<EntropySample, ResolutionContextError> {
        if self.entropy_source.source_id() != *self.assembly.entropy_source_id() {
            let entropy_error = EntropyError::SourceUnavailable {
                message: "entropy source identity changed after Session pin".to_owned(),
            };
            self.state
                .borrow_mut()
                .record_failure(entropy_error.to_string());
            return Err(ResolutionContextError::entropy(entropy_error));
        }
        let request_bytes = request.byte_count();
        let reservation = { self.state.borrow_mut().reserve_entropy(request_bytes) };
        if let Err(error) = reservation {
            let message = error.to_string();
            self.state.borrow_mut().record_failure(message);
            return Err(ResolutionContextError::entropy(error));
        }

        let sample = self.entropy_source.sample(request).map_err(|error| {
            let entropy_error = EntropyError::SourceUnavailable {
                message: error.message,
            };
            self.state
                .borrow_mut()
                .record_failure(entropy_error.to_string());
            ResolutionContextError::entropy(entropy_error)
        })?;
        if sample.len() != request_bytes {
            let entropy_error = EntropyError::SampleLengthMismatch {
                requested: request_bytes,
                actual: sample.len(),
            };
            self.state
                .borrow_mut()
                .record_failure(entropy_error.to_string());
            return Err(ResolutionContextError::entropy(entropy_error));
        }
        self.state
            .borrow_mut()
            .record_entropy(request.clone(), sample.clone());
        Ok(sample)
    }

    fn query_semantic<'a>(
        &'a self,
        request: &'a SemanticQueryRequest,
    ) -> loom_capability::SemanticQueryFuture<'a> {
        Box::pin(async move {
            let Some(store) = self.semantic_store else {
                return Err(ResolutionContextError::semantic(
                    SemanticQueryError::Unavailable {
                        message: "semantic retrieval is unavailable in this host context"
                            .to_owned(),
                    },
                ));
            };
            let result = query_semantic_host(
                self.base,
                self.registry,
                self.assembly,
                store,
                &self.state,
                request,
            )
            .await
            .map_err(|error| {
                self.state.borrow_mut().record_failure(error.to_string());
                ResolutionContextError::semantic(error)
            })?;
            Ok(result)
        })
    }
}

#[allow(clippy::too_many_lines)]
async fn query_semantic_host(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    store: &dyn SemanticProjectionStore,
    state: &Rc<RefCell<ExecutionState>>,
    request: &SemanticQueryRequest,
) -> Result<SemanticQueryResult, SemanticQueryError> {
    let index =
        registry
            .semantic_index(&request.index_id)
            .ok_or_else(|| SemanticQueryError::Missing {
                index_id: request.index_id.clone(),
            })?;
    let manifest =
        registry
            .capability(&index.owner)
            .ok_or_else(|| SemanticQueryError::Unavailable {
                message: format!("semantic index owner {} is unavailable", index.owner),
            })?;
    if !assembly.binding().allows(&index.owner, &manifest.version) {
        return Err(SemanticQueryError::Mismatch {
            field: "world_binding".to_owned(),
            expected: "enabled".to_owned(),
            actual: "disabled".to_owned(),
        });
    }
    if !assembly
        .runtime_revision()
        .revision()
        .capability(&index.owner)
        .is_some_and(|implementation| {
            implementation.version() == &manifest.version
                && implementation.loom_compatibility() == &manifest.loom_compatibility
        })
    {
        return Err(SemanticQueryError::Mismatch {
            field: "runtime_revision".to_owned(),
            expected: "compatible".to_owned(),
            actual: "incompatible".to_owned(),
        });
    }
    let policy = assembly.execution_policy();
    let max_result_bytes = u32::try_from(
        policy
            .max_semantic_result_bytes()
            .unwrap_or(MAX_SEMANTIC_QUERY_RESULT_BYTES as usize)
            .min(MAX_SEMANTIC_QUERY_RESULT_BYTES as usize),
    )
    .unwrap_or(MAX_SEMANTIC_QUERY_RESULT_BYTES);
    let depth = usize::try_from(request.depth).unwrap_or(usize::MAX);
    let filters = request.filters.len();
    let result_limit = usize::try_from(request.limit).unwrap_or(usize::MAX);
    if let Err(error) = state.borrow_mut().reserve_semantic(
        depth,
        filters,
        result_limit,
        usize::try_from(max_result_bytes).unwrap_or(usize::MAX),
    ) {
        return Err(SemanticQueryError::Bounds {
            dimension: error.dimension.to_string(),
            limit: error.limit,
            actual: error.actual,
        });
    }
    let key = SemanticProjectionKey::new(
        assembly.world_id(),
        assembly.timeline_id(),
        request.index_id.clone(),
    );
    let mut query = SemanticProjectionQuery::new(
        key,
        request.source_schema_revision,
        request.projection_revision,
        request.model_revision.clone(),
        request.vector.clone(),
        request.limit,
    )
    .map_err(map_semantic_projection_error)?
    .with_max_result_bytes(max_result_bytes)
    .with_depth(request.depth);
    for filter in &request.filters {
        query = query.with_filter(SemanticProjectionFilter {
            source_hash: filter.source_hash.clone(),
        });
    }
    let hits = store
        .query_semantic_projection(query)
        .await
        .map_err(map_semantic_projection_error)?;
    let result_bytes = hits
        .iter()
        .map(semantic_projection_hit_bytes)
        .sum::<usize>();
    if let Some(limit) = policy.max_semantic_result_bytes()
        && result_bytes > limit
    {
        return Err(SemanticQueryError::Bounds {
            dimension: "semantic_result_bytes".to_owned(),
            limit,
            actual: result_bytes,
        });
    }
    let source_refs = hits.iter().map(|hit| hit.source_ref).collect::<Vec<_>>();
    let query_spec = normalized_semantic_query_spec(request);
    let query_fingerprint = semantic_query_fingerprint(&query_spec);
    let dependency = ReadDependency::Semantic {
        index_id: request.index_id.clone(),
        query_fingerprint,
        query_spec,
        source_schema_revision: request.source_schema_revision,
        projection_revision: request.projection_revision,
        model_revision: request.model_revision.clone(),
        source_refs: source_refs.clone(),
    };
    state
        .borrow_mut()
        .record_semantic(dependency.clone(), result_bytes)
        .map_err(|error| SemanticQueryError::Bounds {
            dimension: error.dimension.to_string(),
            limit: error.limit,
            actual: error.actual,
        })?;
    base.record_dependency(dependency);
    Ok(SemanticQueryResult {
        hits: hits
            .into_iter()
            .map(|hit| loom_capability::SemanticQueryHit {
                source_ref: hit.source_ref,
                source_hash: hit.source_hash,
                source_revision: hit.source_revision,
                projection_revision: hit.projection_revision,
                model_revision: hit.model_revision,
                distance: hit.distance,
            })
            .collect(),
    })
}

fn map_semantic_projection_error(error: SemanticProjectionError) -> SemanticQueryError {
    match error {
        SemanticProjectionError::InvalidRequest { message } => {
            SemanticQueryError::InvalidRequest { message }
        }
        SemanticProjectionError::ScopeNotFound { .. } => SemanticQueryError::Missing {
            index_id: loom_capability::SemanticIndexId::from("unknown"),
        },
        SemanticProjectionError::IndexNotRegistered { key } => SemanticQueryError::Missing {
            index_id: key.index_id,
        },
        SemanticProjectionError::MetadataMismatch {
            field,
            expected,
            actual,
        } => SemanticQueryError::Mismatch {
            field,
            expected,
            actual,
        },
        SemanticProjectionError::SourceMismatch { expected, actual } => SemanticQueryError::Stale {
            field: "source_schema_revision".to_owned(),
            expected,
            actual,
        },
        SemanticProjectionError::RevisionMismatch { expected, actual } => {
            SemanticQueryError::Stale {
                field: "projection_revision".to_owned(),
                expected: expected.to_string(),
                actual: actual.to_string(),
            }
        }
        SemanticProjectionError::DimensionMismatch { expected, actual } => {
            SemanticQueryError::Mismatch {
                field: "dimensions".to_owned(),
                expected,
                actual,
            }
        }
        SemanticProjectionError::LimitExceeded { limit, actual } => SemanticQueryError::Bounds {
            dimension: if limit == MAX_SEMANTIC_QUERY_RESULT_BYTES {
                "result_bytes"
            } else if limit == MAX_SEMANTIC_QUERY_FILTERS {
                "filter_count"
            } else if limit == MAX_SEMANTIC_QUERY_DEPTH {
                "depth"
            } else {
                "result_count"
            }
            .to_owned(),
            limit: usize::try_from(limit).unwrap_or(usize::MAX),
            actual: usize::try_from(actual).unwrap_or(usize::MAX),
        },
        SemanticProjectionError::StorageUnavailable { message } => {
            SemanticQueryError::Unavailable { message }
        }
    }
}

fn normalized_semantic_query_spec(request: &SemanticQueryRequest) -> String {
    let mut filters = request
        .filters
        .iter()
        .map(|filter| filter.source_hash.as_deref().unwrap_or("<none>").to_owned())
        .collect::<Vec<_>>();
    filters.sort();
    let vector = request
        .vector
        .iter()
        .map(|value| value.to_bits().to_string())
        .collect::<Vec<_>>()
        .join(",");
    format!(
        "index={}|source_schema={}|projection={}|model={}|limit={}|depth={}|filters={}|vector={}",
        request.index_id,
        request.source_schema_revision,
        request.projection_revision,
        request.model_revision,
        request.limit,
        request.depth,
        filters.join(","),
        vector,
    )
}

fn semantic_query_fingerprint(spec: &str) -> String {
    let mut hash = 14_695_981_039_346_656_037_u64;
    for byte in spec.bytes() {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(1_099_511_628_211);
    }
    format!("{hash:016x}")
}

fn dispatch_root_action(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    entropy_source: &dyn EntropySource,
    entropy_evidence: &mut EntropyEvidence,
    evidence: &mut ExecutionEvidence,
    invocation: &ActionInvocation,
) -> Result<(ResolveOutcome, ExecutionState), DispatchError> {
    let action = enabled_action(registry, assembly, &invocation.action)?;
    let frame = CallFrame {
        owner: action.owner.clone(),
        action: invocation.action.clone(),
    };
    let state = Rc::new(RefCell::new(ExecutionState::new(
        &assembly.execution_policy(),
        assembly.entropy_source_id().clone(),
    )));
    state
        .borrow_mut()
        .enter_root(frame.clone())
        .map_err(internal_dispatch_error)?;
    let outcome = dispatch_action_frame(
        base,
        registry,
        assembly,
        entropy_source,
        &state,
        &frame,
        invocation,
    );
    let execution = state.borrow().clone();
    *entropy_evidence = execution.entropy_evidence.clone();
    *evidence = execution_evidence(base, &execution);
    Ok((outcome?, execution))
}

#[allow(clippy::too_many_arguments)]
async fn dispatch_root_action_async(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    entropy_source: &dyn EntropySource,
    semantic_store: &dyn SemanticProjectionStore,
    entropy_evidence: &mut EntropyEvidence,
    evidence: &mut ExecutionEvidence,
    invocation: &ActionInvocation,
) -> Result<(ResolveOutcome, ExecutionState), DispatchError> {
    let action = enabled_action(registry, assembly, &invocation.action)?;
    let frame = CallFrame {
        owner: action.owner.clone(),
        action: invocation.action.clone(),
    };
    let state = Rc::new(RefCell::new(ExecutionState::new(
        &assembly.execution_policy(),
        assembly.entropy_source_id().clone(),
    )));
    state
        .borrow_mut()
        .enter_root(frame.clone())
        .map_err(internal_dispatch_error)?;
    let result = {
        let context = RuntimeResolutionContext {
            base,
            registry,
            assembly,
            entropy_source,
            state: Rc::clone(&state),
            frame: frame.clone(),
            semantic_store: Some(semantic_store),
        };
        registry
            .resolve_action_async(&invocation.action, &context, &invocation.input)
            .await
    };
    let outcome = capture_outcome(&state, &frame.owner, result);
    let execution = state.borrow().clone();
    *entropy_evidence = execution.entropy_evidence.clone();
    *evidence = execution_evidence(base, &execution);
    Ok((outcome?, execution))
}

#[allow(clippy::too_many_arguments)]
async fn dispatch_root_work_async(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    entropy_source: &dyn EntropySource,
    semantic_store: &dyn SemanticProjectionStore,
    entropy_evidence: &mut EntropyEvidence,
    evidence: &mut ExecutionEvidence,
    handler_id: &loom_core::WorkHandlerId,
    payload: &serde_json::Value,
) -> Result<(ResolveOutcome, ExecutionState), DispatchError> {
    let handler = registry
        .work_handler(handler_id)
        .ok_or_else(|| DispatchError::UnknownWorkHandler(handler_id.clone()))?;
    let frame = CallFrame {
        owner: handler.owner.clone(),
        action: ActionTypeId::from(format!("work:{handler_id}")),
    };
    let state = Rc::new(RefCell::new(ExecutionState::new(
        &assembly.execution_policy(),
        assembly.entropy_source_id().clone(),
    )));
    state
        .borrow_mut()
        .enter_root(frame.clone())
        .map_err(internal_dispatch_error)?;
    let result = {
        let context = RuntimeResolutionContext {
            base,
            registry,
            assembly,
            entropy_source,
            state: Rc::clone(&state),
            frame: frame.clone(),
            semantic_store: Some(semantic_store),
        };
        registry
            .handle_work_async(handler_id, &context, payload)
            .await
    };
    let outcome = capture_outcome(&state, &frame.owner, result);
    let execution = state.borrow().clone();
    *entropy_evidence = execution.entropy_evidence.clone();
    *evidence = execution_evidence(base, &execution);
    Ok((outcome?, execution))
}

fn dispatch_action_frame(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    entropy_source: &dyn EntropySource,
    state: &Rc<RefCell<ExecutionState>>,
    frame: &CallFrame,
    invocation: &ActionInvocation,
) -> Result<ResolveOutcome, DispatchError> {
    let result = {
        let context = RuntimeResolutionContext {
            base,
            registry,
            assembly,
            entropy_source,
            state: Rc::clone(state),
            frame: frame.clone(),
            semantic_store: None,
        };
        registry.resolve_action(&invocation.action, &context, &invocation.input)
    };
    capture_outcome(state, &frame.owner, result)
}

fn capture_outcome(
    state: &Rc<RefCell<ExecutionState>>,
    owner: &CapabilityId,
    result: Result<ResolveOutcome, DispatchError>,
) -> Result<ResolveOutcome, DispatchError> {
    let outcome = result?;
    if let Some(failure) = state.borrow().failure.clone() {
        return Err(internal_dispatch_error(failure));
    }
    if let ResolveOutcome::Resolved(resolution) = &outcome {
        state
            .borrow_mut()
            .record_segment(owner.clone(), resolution.clone())
            .map_err(internal_dispatch_error)?;
    }
    if let Some(failure) = state.borrow().failure.clone() {
        return Err(internal_dispatch_error(failure));
    }
    Ok(outcome)
}

fn dispatch_child_action(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    entropy_source: &dyn EntropySource,
    state: &Rc<RefCell<ExecutionState>>,
    caller: &CallFrame,
    invocation: &ActionInvocation,
) -> Result<ResolveOutcome, DispatchError> {
    let action = enabled_action(registry, assembly, &invocation.action)?;
    EffectEngine::new(registry)
        .with_budget(assembly.execution_policy())
        .validate_action_input(&invocation.action, &invocation.input)
        .map_err(|error| {
            let message = format!("child Action input rejected: {error}");
            state.borrow_mut().record_failure(message.clone());
            internal_dispatch_error(message)
        })?;

    let target = CallFrame {
        owner: action.owner.clone(),
        action: invocation.action.clone(),
    };
    if caller.owner != target.owner {
        let authorized = registry.capability(&caller.owner).is_some_and(|manifest| {
            manifest
                .dependencies
                .iter()
                .any(|dependency| dependency.id == target.owner)
        });
        if !authorized {
            let message = format!(
                "Capability {} has no direct dependency on {}",
                caller.owner, target.owner
            );
            state.borrow_mut().record_failure(message.clone());
            return Err(internal_dispatch_error(message));
        }
    }

    let enter_error = { state.borrow_mut().enter_child(caller, target.clone()) };
    if let Err(message) = enter_error {
        state.borrow_mut().record_failure(message.clone());
        return Err(internal_dispatch_error(message));
    }
    let result = dispatch_action_frame(
        base,
        registry,
        assembly,
        entropy_source,
        state,
        &target,
        invocation,
    );
    state.borrow_mut().leave(&target);
    result
}

fn internal_dispatch_error(message: impl Into<String>) -> DispatchError {
    DispatchError::Resolver(ResolverError::new(message))
}

fn enabled_capability(
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    capability: &CapabilityId,
) -> bool {
    let Some(manifest) = registry.capability(capability) else {
        return false;
    };
    assembly.binding().allows(capability, &manifest.version)
        && assembly
            .implementations()
            .capability(capability)
            .is_some_and(|implementation| implementation.version() == &manifest.version)
}

fn reaction_work_payload(event: &crate::ProposedEvent, event_id: EventId) -> Value {
    let mut payload = match &event.payload {
        Value::Object(object) => object.clone(),
        value => {
            let mut object = serde_json::Map::new();
            object.insert("event".to_owned(), value.clone());
            object
        }
    };
    payload.insert("event_id".to_owned(), Value::String(event_id.to_string()));
    Value::Object(payload)
}

fn enabled_action<'a>(
    registry: &'a CapabilityRegistry,
    assembly: &ExecutionAssembly,
    action_id: &ActionTypeId,
) -> Result<&'a loom_capability::RegisteredAction, DispatchError> {
    let action = registry
        .action(action_id)
        .ok_or_else(|| DispatchError::UnknownAction(action_id.clone()))?;
    let Some(manifest) = registry.capability(&action.owner) else {
        return Err(DispatchError::UnavailableAction(action_id.clone()));
    };
    let enabled = assembly.binding().allows(&action.owner, &manifest.version)
        && assembly
            .implementations()
            .capability(&action.owner)
            .is_some_and(|implementation| implementation.version() == &manifest.version);
    if !enabled {
        return Err(DispatchError::UnavailableAction(action_id.clone()));
    }
    Ok(action)
}

fn runtime_revision_matches_registry(
    registry: &CapabilityRegistry,
    implementations: &RuntimeRevisionAssembly,
) -> bool {
    implementations
        .capabilities()
        .values()
        .all(|implementation| {
            let Some(manifest) = registry.capability(implementation.capability_id()) else {
                return false;
            };
            manifest.version == *implementation.version()
                && manifest.loom_compatibility == *implementation.loom_compatibility()
        })
}

fn runtime_revision_descriptor_matches_registry(
    registry: &CapabilityRegistry,
    revision: &RuntimeRevisionDescriptor,
) -> bool {
    revision.loom_version() == registry.loom_version()
        && revision.capabilities().len() == registry.capabilities().count()
        && revision
            .capabilities()
            .iter()
            .all(|(capability_id, implementation)| {
                registry.capability(capability_id).is_some_and(|manifest| {
                    manifest.version == *implementation.version()
                        && manifest.loom_compatibility == *implementation.loom_compatibility()
                })
            })
}

fn validate_work_target(
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    work: &WorkRecord,
) -> ApiResult<()> {
    let target = &work.target;
    let WorkTarget::CapabilityWork { owner, handler } = target else {
        return Err(ApiError::unavailable(
            "Agency Wake execution requires the Agency runtime path",
        ));
    };
    let handler_id = handler;
    let Some(handler) = registry.work_handler(handler_id) else {
        return Err(ApiError::not_found(format!(
            "Work handler {handler_id} was not registered"
        )));
    };
    if handler.definition.schema_revision != work.schema_revision {
        return Err(ApiError::unavailable(
            "Work handler schema revision is not compatible with the persisted Work",
        ));
    }
    if owner
        .as_deref()
        .is_some_and(|owner| owner != handler.owner.as_str())
    {
        return Err(ApiError::unavailable(
            "Work target owner does not match its registered handler",
        ));
    }
    let Some(manifest) = registry.capability(&handler.owner) else {
        return Err(ApiError::unavailable(
            "Work handler owner is not installed in the active Runtime Revision",
        ));
    };
    let compatible = assembly.binding().allows(&handler.owner, &manifest.version)
        && assembly
            .implementations()
            .capability(&handler.owner)
            .is_some_and(|implementation| implementation.version() == &manifest.version);
    if !compatible {
        return Err(ApiError::unavailable(
            "Work handler has no compatible pinned implementation",
        ));
    }
    Ok(())
}

fn validate_agency_wake_target(
    assembly: &ExecutionAssembly,
    agent: loom_core::EntityId,
    cognition: &str,
) -> ApiResult<()> {
    if agent.is_nil() {
        return Err(ApiError::invalid_request(
            "Agency Wake Agent identity must not be nil",
        ));
    }
    if assembly.cognitive().metadata().executor.id != cognition {
        return Err(ApiError::unavailable(format!(
            "Agency Wake cognition requirement {cognition} is not available"
        )));
    }
    Ok(())
}

fn work_target_has_compatible_implementation(
    registry: &CapabilityRegistry,
    binding: &WorldRuntimeBinding,
    implementations: &RuntimeRevisionAssembly,
    work: &WorkRecord,
) -> bool {
    let WorkTarget::CapabilityWork { owner, handler } = &work.target else {
        // Agency Wake has no Capability WorkHandler fallback. Until the
        // target-specific Agency executor is assembled, it is a typed missing
        // implementation blockage rather than a technical attempt.
        return false;
    };
    let Some(registered) = registry.work_handler(handler) else {
        return false;
    };
    if owner
        .as_deref()
        .is_some_and(|owner| owner != registered.owner.as_str())
    {
        return false;
    }
    let Some(manifest) = registry.capability(&registered.owner) else {
        return false;
    };
    if registered.definition.schema_revision != work.schema_revision {
        return false;
    }
    let Some(implementation) = implementations.capability(&registered.owner) else {
        return false;
    };
    binding.allows(&registered.owner, &manifest.version)
        && implementation.version() == &manifest.version
        && implementation.loom_compatibility() == &manifest.loom_compatibility
}

fn changes_runtime_state(
    resolution: &ValidatedResolution,
    current_work: Option<&WorkClaim>,
) -> bool {
    !resolution.events().is_empty() || !resolution.work().is_empty() || current_work.is_some()
}

#[derive(Clone, Debug, PartialEq)]
enum SchedulerCommitReconciliation {
    Committed {
        event_ids: Vec<EventId>,
        version: loom_core::TimelineVersion,
    },
    Absent,
    Ambiguous,
}

fn reconcile_scheduler_commit_snapshot(
    snapshot: &TimelineSnapshot,
    resolution: &ValidatedResolution,
    claim: &WorkClaim,
) -> SchedulerCommitReconciliation {
    let expected_event_ids: Vec<_> = resolution.events().iter().map(|event| event.id).collect();
    if let Some(commit) = snapshot.journal.iter().find(|commit| {
        commit.timeline_id == resolution.timeline_id()
            && commit.before_version == resolution.base_version()
            && commit.event_ids == expected_event_ids
            && commit.work_transitions.iter().any(|transition| {
                matches!(
                    transition,
                    LogicalWorkTransition::Complete { work_id } if *work_id == claim.work_id()
                )
            })
    }) {
        return SchedulerCommitReconciliation::Committed {
            event_ids: commit.event_ids.clone(),
            version: commit.after_version,
        };
    }

    let claim_is_still_current = snapshot
        .works
        .iter()
        .find(|work| work.id == claim.work_id())
        .is_some_and(|work| {
            work.status == WorkStatus::Pending
                && work.lease.is_some_and(|lease| {
                    lease.fence() == claim.fence() && lease.claimed_until() == claim.claimed_until()
                })
        });
    if snapshot.version() == resolution.base_version() && claim_is_still_current {
        SchedulerCommitReconciliation::Absent
    } else {
        SchedulerCommitReconciliation::Ambiguous
    }
}

fn execution_result(result: &crate::CommitResult, changes_runtime_state: bool) -> ExecutionResult {
    if changes_runtime_state {
        ExecutionResult::committed(
            result.events.iter().map(|event| event.id).collect(),
            result.version,
        )
    } else {
        ExecutionResult::no_change()
    }
}

fn ingress_completion(
    result: &crate::CommitResult,
    changes_runtime_state: bool,
) -> IngressCompletion {
    if !changes_runtime_state {
        return IngressCompletion::NoChange;
    }
    IngressCompletion::Committed {
        event_refs: result
            .events
            .iter()
            .map(CommittedEvent::event_ref)
            .collect(),
        timeline_version: result.version,
    }
}

fn api_event(event: &CommittedEvent) -> ApiCommittedEvent {
    ApiCommittedEvent {
        id: event.id,
        timeline_id: event.timeline_id,
        sequence: event.event_seq,
        event_type: event.event_type.clone(),
        schema_revision: event.schema_revision,
        occurred_at: event.occurred_at,
        participants: event.participants.clone(),
        relationship_refs: event.relationship_refs.clone(),
        causal_links: event.causal_links.clone(),
        payload: event.payload.clone(),
        effects: event.effects.clone(),
    }
}

fn map_public_semantic_projection_error(error: SemanticProjectionError) -> ApiError {
    match error {
        SemanticProjectionError::InvalidRequest { message } => ApiError::invalid_request(message),
        SemanticProjectionError::LimitExceeded { limit, actual } => ApiError::invalid_request(
            format!("semantic projection query exceeds bound {limit} with value {actual}"),
        ),
        SemanticProjectionError::ScopeNotFound { .. }
        | SemanticProjectionError::IndexNotRegistered { .. }
        | SemanticProjectionError::StorageUnavailable { .. } => {
            ApiError::semantic_projection_unavailable(
                "semantic projection materialization is unavailable",
            )
        }
        SemanticProjectionError::SourceMismatch { .. } => {
            ApiError::semantic_projection_source_mismatch(
                "semantic projection source metadata does not match the request",
            )
        }
        SemanticProjectionError::RevisionMismatch { .. }
        | SemanticProjectionError::MetadataMismatch { .. } => ApiError::semantic_projection_stale(
            "semantic projection materialization does not match the requested revision",
        ),
        SemanticProjectionError::DimensionMismatch { .. } => {
            ApiError::invalid_request("semantic projection vector dimensions are invalid")
        }
    }
}

fn api_semantic_projection_hit(hit: SemanticProjectionHit) -> ApiSemanticProjectionHit {
    ApiSemanticProjectionHit {
        source_ref: hit.source_ref,
        source_hash: hit.source_hash,
        source_revision: hit.source_revision,
        projection_revision: hit.projection_revision,
        model_revision: hit.model_revision,
        distance: hit.distance,
    }
}

fn runtime_blob_reference(reference: &ApiBlobReference) -> ApiResult<BlobRef> {
    let id_hash = BlobHash::from_hex(&reference.id)
        .map_err(|_| ApiError::invalid_request("blob reference id is not a valid hash"))?;
    let metadata_hash = BlobHash::from_hex(&reference.content_hash)
        .map_err(|_| ApiError::invalid_request("blob reference content hash is not valid"))?;
    let reference = BlobRef::new(
        BlobId::new(id_hash),
        BlobMetadata::new(
            metadata_hash,
            reference.size,
            reference.content_type.clone(),
        ),
    );
    if !reference.is_consistent() {
        return Err(ApiError::invalid_request(
            "blob reference identity and content hash must match",
        ));
    }
    Ok(reference)
}

fn api_blob_reference(reference: &BlobRef) -> ApiBlobReference {
    ApiBlobReference::new(
        reference.id.to_string(),
        reference.metadata.content_hash.to_string(),
        reference.metadata.size,
        reference.metadata.content_type.clone(),
    )
}

fn map_blob_error(error: &BlobError) -> ApiError {
    match error {
        BlobError::NotFound { .. } => {
            ApiError::blob_not_found("requested blob reference was not found")
        }
        BlobError::HashMismatch { .. }
        | BlobError::SizeMismatch { .. }
        | BlobError::InvalidReference { .. }
        | BlobError::MetadataMismatch { .. } => {
            ApiError::blob_integrity_mismatch("requested blob failed integrity verification")
        }
        BlobError::Unavailable { .. } => {
            ApiError::blob_unavailable("requested blob is currently unavailable")
        }
    }
}

fn map_runtime_revision_error(error: &RuntimeRevisionError) -> ApiError {
    match error {
        RuntimeRevisionError::RevisionNotFound { .. }
        | RuntimeRevisionError::RevisionDescriptorMismatch { .. }
        | RuntimeRevisionError::RevisionAlreadyExists { .. }
        | RuntimeRevisionError::ActiveRevisionConflict { .. }
        | RuntimeRevisionError::NoActiveRevision
        | RuntimeRevisionError::IncompatibleActiveRevision { .. }
        | RuntimeRevisionError::ActivationGenerationOverflow
        | RuntimeRevisionError::StorageUnavailable { .. } => {
            ApiError::unavailable("Runtime Revision selection is unavailable")
        }
    }
}

fn map_admin_runtime_revision_error(error: &RuntimeRevisionError) -> ApiError {
    match error {
        RuntimeRevisionError::RevisionNotFound { revision_id } => {
            ApiError::not_found(format!("Runtime Revision {revision_id} was not found"))
        }
        RuntimeRevisionError::RevisionAlreadyExists { .. }
        | RuntimeRevisionError::RevisionDescriptorMismatch { .. }
        | RuntimeRevisionError::ActiveRevisionConflict { .. }
        | RuntimeRevisionError::IncompatibleActiveRevision { .. }
        | RuntimeRevisionError::ActivationGenerationOverflow => {
            ApiError::conflict("Runtime Revision operation conflicted with current selection")
        }
        RuntimeRevisionError::NoActiveRevision => {
            ApiError::not_found("no active Runtime Revision is selected")
        }
        RuntimeRevisionError::StorageUnavailable { .. } => {
            ApiError::unavailable("Runtime Revision persistence is unavailable")
        }
    }
}

fn map_revision_compatibility_error(error: &crate::RuntimeRevisionCompatibilityError) -> ApiError {
    match error {
        crate::RuntimeRevisionCompatibilityError::MissingCapability { .. }
        | crate::RuntimeRevisionCompatibilityError::VersionMismatch { .. } => {
            ApiError::unavailable(
                "active Runtime Revision has no compatible implementation for this World",
            )
        }
    }
}

fn map_session_error(error: &SessionError) -> ApiError {
    match error {
        SessionError::SessionAlreadyExists { .. }
        | SessionError::SessionNotFound { .. }
        | SessionError::InvalidTransition { .. }
        | SessionError::EntropySourceMismatch { .. }
        | SessionError::EntropyEvidenceUnavailable { .. }
        | SessionError::ProvenanceUnavailable { .. }
        | SessionError::IngressCompletionUnavailable { .. }
        | SessionError::StorageUnavailable { .. } => {
            ApiError::unavailable("Execution Session provenance is unavailable")
        }
    }
}

fn map_admin_session_error(error: &SessionError) -> ApiError {
    match error {
        SessionError::SessionNotFound { session_id } => {
            ApiError::not_found(format!("Execution Session {session_id} was not found"))
        }
        SessionError::SessionAlreadyExists { .. }
        | SessionError::InvalidTransition { .. }
        | SessionError::EntropySourceMismatch { .. }
        | SessionError::EntropyEvidenceUnavailable { .. }
        | SessionError::ProvenanceUnavailable { .. }
        | SessionError::IngressCompletionUnavailable { .. } => {
            ApiError::conflict("Execution Session provenance is not readable in this state")
        }
        SessionError::StorageUnavailable { .. } => {
            ApiError::unavailable("Execution Session persistence is unavailable")
        }
    }
}

fn map_ingress_error(error: IngressError) -> ApiError {
    match error {
        IngressError::IngressNotFound { ingress_id } => {
            ApiError::not_found(format!("Ingress {ingress_id} was not found"))
        }
        IngressError::IngressAlreadyExists { .. } => {
            ApiError::conflict("Ingress identity already exists")
        }
        IngressError::NotClaimable { .. } => ApiError::conflict("Ingress is no longer claimable"),
        IngressError::AlreadyClaimed { .. } | IngressError::StaleClaim { .. } => {
            ApiError::conflict("Ingress claim is no longer usable")
        }
        IngressError::NotAvailable { .. } => ApiError::unavailable("Ingress is not available yet"),
        IngressError::InvalidLease { .. } => {
            ApiError::invalid_request("Ingress lease has invalid timing")
        }
        IngressError::MissingLease { .. } | IngressError::LeaseExpired { .. } => {
            ApiError::conflict("Ingress lease is no longer usable")
        }
        IngressError::AttemptOverflow { .. } => {
            ApiError::internal("Ingress attempt counter overflowed")
        }
        IngressError::StorageUnavailable { .. } => {
            ApiError::unavailable("Ingress persistence is unavailable")
        }
    }
}

fn map_binding_error(error: &BindingError) -> ApiError {
    match error {
        BindingError::WorldNotFound { world_id } => {
            ApiError::not_found(format!("World {world_id} was not found"))
        }
        BindingError::BindingNotFound { .. } => {
            ApiError::internal("World Runtime Binding is missing")
        }
        BindingError::BindingAlreadyExists { .. } => {
            ApiError::conflict("World Runtime Binding already exists")
        }
        BindingError::StorageUnavailable { .. } => {
            ApiError::unavailable("Persistence authority is temporarily unavailable")
        }
    }
}

fn map_lifecycle_error(error: &LifecycleError) -> ApiError {
    match error {
        LifecycleError::WorldAlreadyExists { world_id } => {
            ApiError::conflict(format!("World {world_id} already exists"))
        }
        LifecycleError::TimelineAlreadyExists { timeline_id } => {
            ApiError::conflict(format!("Timeline {timeline_id} already exists"))
        }
        LifecycleError::StorageUnavailable { .. } => {
            ApiError::unavailable("Persistence authority is temporarily unavailable")
        }
    }
}

fn map_read_error(error: &ReadError) -> ApiError {
    match error {
        ReadError::TimelineNotFound { timeline_id } => {
            ApiError::not_found(format!("Timeline {timeline_id} was not found"))
        }
        ReadError::PinnedVersionMismatch { .. } => {
            ApiError::conflict("Timeline changed during pinned read; restart the resolution")
        }
        ReadError::PinnedWorldMismatch { .. } => {
            ApiError::not_found("Timeline is not part of the requested World")
        }
        ReadError::StorageUnavailable { .. } => {
            ApiError::unavailable("Persistence authority is temporarily unavailable")
        }
    }
}

fn map_fork_error(error: &ForkError) -> ApiError {
    match error {
        ForkError::SourceTimelineNotFound { timeline_id } => {
            ApiError::not_found(format!("source Timeline {timeline_id} was not found"))
        }
        ForkError::TimelineAlreadyExists { timeline_id } => {
            ApiError::conflict(format!("child Timeline {timeline_id} already exists"))
        }
        ForkError::SourceVersionConflict { .. } => {
            ApiError::conflict("source Timeline changed before fork commit")
        }
        ForkError::InvalidForkVersion { .. } => map_historical_fork_error(),
        ForkError::InvalidWork { .. } => ApiError::internal("Timeline fork Work plan was invalid"),
        ForkError::StorageUnavailable { .. } => {
            ApiError::unavailable("Timeline fork persistence is unavailable")
        }
    }
}

fn map_historical_fork_error() -> ApiError {
    ApiError::invalid_request("source TimelineVersion is not a committed visible history position")
}

fn map_world_time_error(error: &WorldTimeError) -> ApiError {
    match error {
        WorldTimeError::TimelineNotFound { timeline_id } => {
            ApiError::not_found(format!("Timeline {timeline_id} was not found"))
        }
        WorldTimeError::DueWorkPending { .. } => {
            ApiError::conflict("Timeline has semantically due Pending Work")
        }
        WorldTimeError::TimelineConflict { .. } | WorldTimeError::CurrentTimeMismatch { .. } => {
            ApiError::conflict("Timeline changed before World-Time advancement")
        }
        WorldTimeError::NonMonotonic { .. } | WorldTimeError::RevisionOverflow => {
            ApiError::invalid_request("World-Time transition is not valid")
        }
        WorldTimeError::StorageUnavailable { .. } => {
            ApiError::unavailable("Persistence authority is temporarily unavailable")
        }
    }
}

fn map_dispatch_error(error: DispatchError) -> ApiError {
    match error {
        DispatchError::UnknownAction(action) => {
            ApiError::not_found(format!("Action {action} was not registered"))
        }
        DispatchError::UnavailableAction(_) => {
            ApiError::unavailable("Action is not enabled for this World")
        }
        DispatchError::UnknownWorkHandler(_) => {
            ApiError::internal("registered Work handler was not found")
        }
        DispatchError::Resolver(_) => ApiError::internal("Action resolver failed"),
        DispatchError::Handler(_) => ApiError::internal("Work handler failed"),
    }
}

fn map_runtime_error(error: &RuntimeError) -> ApiError {
    match error {
        RuntimeError::Validation(_) | RuntimeError::Budget(_) => {
            ApiError::internal("Runtime rejected an invalid resolution")
        }
    }
}

fn map_action_input_error(error: &RuntimeError) -> ApiError {
    if matches!(
        error,
        RuntimeError::Validation(ValidationError::SchemaViolation {
            kind: loom_capability::SemanticKind::Action,
            ..
        })
    ) {
        ApiError::invalid_request("Action input does not match its registered schema")
    } else if matches!(error, RuntimeError::Budget(_)) {
        ApiError::invalid_request("Action input exceeds the Runtime resource bound")
    } else {
        map_runtime_error(error)
    }
}

fn map_work_error(error: &WorkError) -> ApiError {
    match error {
        WorkError::TimelineNotFound { timeline_id }
        | WorkError::WorkNotFound { timeline_id, .. } => ApiError::not_found(format!(
            "Work target in Timeline {timeline_id} was not found"
        )),
        WorkError::NotDue { .. } => ApiError::unavailable("Work is not due in World Time"),
        WorkError::NotLogicalHead { .. } => {
            ApiError::conflict("Work cannot bypass the Timeline logical head")
        }
        WorkError::NotAvailable { .. } => ApiError::unavailable("Work is not available yet"),
        WorkError::AlreadyClaimed { .. }
        | WorkError::NotPending { .. }
        | WorkError::StaleClaim { .. }
        | WorkError::MissingLease { .. }
        | WorkError::LeaseExpired { .. } => ApiError::conflict("Work claim is no longer usable"),
        WorkError::InvalidLease { .. }
        | WorkError::TimelineMismatch { .. }
        | WorkError::WorkMismatch { .. } => {
            ApiError::invalid_request("Work claim has invalid timing, Timeline or Work scope")
        }
        WorkError::StorageUnavailable { .. } => {
            ApiError::unavailable("Persistence authority is temporarily unavailable")
        }
        WorkError::AttemptOverflow { .. }
        | WorkError::DuplicateWork { .. }
        | WorkError::LogicalScheduleOrderOverflow { .. }
        | WorkError::ChronologyBudgetOverflow { .. }
        | WorkError::MissingCausalEvent { .. } => {
            ApiError::internal("Work adapter rejected the execution metadata")
        }
    }
}

fn map_commit_error(error: &CommitError) -> ApiError {
    match error {
        CommitError::TimelineNotFound { timeline_id } => {
            ApiError::not_found(format!("Timeline {timeline_id} was not found"))
        }
        CommitError::TimelineConflict { .. } => {
            ApiError::conflict("Timeline changed before the resolution could commit")
        }
        CommitError::ChronologyBudgetExceeded(_) => {
            ApiError::unavailable("Timeline chronology budget is exhausted")
        }
        CommitError::CommitOutcomeUnknown { .. } => {
            ApiError::unavailable("Scheduler commit outcome is unknown")
        }
        CommitError::TimelineMismatch { .. } => {
            ApiError::invalid_request("Commit target does not match the pinned Timeline")
        }
        CommitError::IngressClaim { .. } => {
            ApiError::conflict("Ingress claim fence is stale or expired")
        }
        CommitError::Work(_) => ApiError::conflict("Work state changed before commit"),
        CommitError::StorageUnavailable { .. } => {
            ApiError::unavailable("Persistence authority is temporarily unavailable")
        }
        CommitError::SessionLink { .. } => {
            ApiError::internal("Commit Session provenance link was rejected")
        }
        CommitError::DuplicateEvent { .. }
        | CommitError::InvalidEvent { .. }
        | CommitError::InvalidEffect { .. }
        | CommitError::RevisionOverflow => ApiError::internal("Timeline commit failed validation"),
    }
}

fn map_failure_terminalization_error(error: &CommitError) -> ApiError {
    if matches!(error, CommitError::TimelineConflict { .. }) {
        ApiError::conflict("Work terminalization requires explicit Runtime Control")
    } else {
        map_commit_error(error)
    }
}

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use loom_capability::{
        ActionDefinition, ActionResolver, Capability, CapabilityDependency, CapabilityManifest,
        CapabilityRegistrar, DispatchError, EntropyBudgetDimension, EntropyError, EntropyRequest,
        RegistrationError, ResolutionContext, ResolverError, ResolverErrorKind,
        SemanticIndexDefinition, SemanticIndexMetric, SemanticIndexSource, SemanticQueryRequest,
    };
    use loom_core::{
        ActionTypeId, EntityId, EventId, EventSeq, EventTypeId, FacetOwner, FacetTypeId,
        RelationshipId, SchemaRevision, StateRevision, TimelineId, TimelineVersion, WorkHandlerId,
        WorkId, WorldId, WorldInstant,
    };
    use loom_protocol::{ActionInvocation, ProposedEvent, Rejection, Resolution, ResolveOutcome};
    use semver::Version;
    use serde_json::{Value, json};

    use crate::{
        BaseWorldSnapshot, BaseWorldView, DeterministicEntropySource, RuntimeRevisionCapability,
        SchedulerDiscoveryCursor, SchedulerDiscoveryTarget,
    };

    use super::*;

    fn id<T>(value: u128) -> T
    where
        T: FromStr,
        T::Err: std::fmt::Debug,
    {
        format!("00000000-0000-0000-0000-{value:012x}")
            .parse()
            .expect("test identity should parse")
    }

    #[derive(Default)]
    struct SchedulerDiscoveryObservation {
        requests: Vec<SchedulerDiscoveryRequest>,
        commit_mutations: usize,
        work_mutations: usize,
    }

    struct SchedulerDiscoveryTestStore {
        observation: std::sync::Arc<std::sync::Mutex<SchedulerDiscoveryObservation>>,
        response: std::sync::Arc<
            std::sync::Mutex<Option<Result<SchedulerDiscoveryPage, SchedulerDiscoveryError>>>,
        >,
    }

    impl SchedulerDiscoveryTestStore {
        fn new(response: Result<SchedulerDiscoveryPage, SchedulerDiscoveryError>) -> Self {
            Self {
                observation: std::sync::Arc::new(std::sync::Mutex::new(
                    SchedulerDiscoveryObservation::default(),
                )),
                response: std::sync::Arc::new(std::sync::Mutex::new(Some(response))),
            }
        }
    }

    impl SchedulerDiscoveryStore for SchedulerDiscoveryTestStore {
        fn discover_scheduler_targets(
            &self,
            request: SchedulerDiscoveryRequest,
        ) -> PersistenceFuture<'_, Result<SchedulerDiscoveryPage, SchedulerDiscoveryError>>
        {
            self.observation
                .lock()
                .expect("discovery observation should not be poisoned")
                .requests
                .push(request);
            let response = self
                .response
                .lock()
                .expect("discovery response should not be poisoned")
                .take()
                .expect("test discovery response should be consumed once");
            Box::pin(async move { response })
        }
    }

    fn runtime_for_scheduler_discovery(
        store: SchedulerDiscoveryTestStore,
    ) -> Runtime<SchedulerDiscoveryTestStore> {
        Runtime {
            registry: CapabilityRegistry::new(),
            store,
            platform_clock: std::sync::Arc::new(ManualPlatformClock::default()),
            entropy_source: std::sync::Arc::new(UnavailableEntropySource),
            cognitive_executor: std::sync::Arc::new(crate::UnavailableCognitiveExecutor),
            cognitive_policy: ExecutionPolicy::default(),
            identity_allocator: std::sync::Arc::new(UuidV7IdentityAllocator),
            resolution_budget: ResolutionBudget::default(),
            history_budget: HistoryBudget::default(),
            failure_policy: FailurePolicy::default(),
            chronology_budget: ChronologyBudgetPolicy::default(),
            missing_implementation_observations: std::sync::Arc::new(std::sync::Mutex::new(
                std::collections::BTreeMap::new(),
            )),
            blob_store: None,
        }
    }

    #[test]
    fn runtime_scheduler_discovery_passes_request_and_page_through_unchanged() {
        let first = SchedulerDiscoveryTarget::new(id(1), id(2));
        let second = SchedulerDiscoveryTarget::new(id(3), id(4));
        let request = SchedulerDiscoveryRequest::new(2)
            .expect("test request should satisfy the T03 bound")
            .with_cursor(SchedulerDiscoveryCursor::after(first));
        let expected_page = SchedulerDiscoveryPage::new(
            vec![second],
            Some(SchedulerDiscoveryCursor::after(second)),
        );
        let store = SchedulerDiscoveryTestStore::new(Ok(expected_page.clone()));
        let observation = store.observation.clone();
        let runtime = runtime_for_scheduler_discovery(store);

        let actual = block_on(runtime.discover_scheduler_targets(request))
            .expect("Runtime should return the store page");

        assert_eq!(actual, expected_page);
        let observation = observation
            .lock()
            .expect("discovery observation should not be poisoned");
        assert_eq!(observation.requests, vec![request]);
        assert_eq!(observation.commit_mutations, 0);
        assert_eq!(observation.work_mutations, 0);
    }

    #[test]
    fn runtime_scheduler_discovery_preserves_typed_persistence_failure() {
        let expected = SchedulerDiscoveryError::StorageUnavailable {
            message: "controlled discovery failure".to_owned(),
        };
        let store = SchedulerDiscoveryTestStore::new(Err(expected.clone()));
        let runtime = runtime_for_scheduler_discovery(store);
        let request = SchedulerDiscoveryRequest::new(1).expect("test request should be bounded");

        let actual = block_on(runtime.discover_scheduler_targets(request))
            .expect_err("Runtime should return the persistence error");

        assert_eq!(actual, expected);
    }

    struct ParentCapability {
        manifest: CapabilityManifest,
    }

    impl Capability for ParentCapability {
        fn manifest(&self) -> &CapabilityManifest {
            &self.manifest
        }

        fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
            registrar.register_action(
                ActionDefinition::new(
                    ActionTypeId::from("provenance.parent"),
                    loom_core::SchemaRevision::new(1),
                ),
                ParentResolver,
            )
        }
    }

    struct ChildCapability {
        manifest: CapabilityManifest,
    }

    impl Capability for ChildCapability {
        fn manifest(&self) -> &CapabilityManifest {
            &self.manifest
        }

        fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
            registrar.register_action(
                ActionDefinition::new(
                    ActionTypeId::from("provenance.child"),
                    loom_core::SchemaRevision::new(1),
                ),
                ChildResolver,
            )
        }
    }

    struct ParentResolver;

    impl ActionResolver for ParentResolver {
        fn resolve(
            &self,
            context: &dyn loom_capability::ResolutionContext,
            _input: &Value,
        ) -> Result<ResolveOutcome, ResolverError> {
            let child = context.subresolve(&ActionInvocation::new(
                ActionTypeId::from("provenance.child"),
                json!({}),
            ))?;
            assert!(matches!(child, ResolveOutcome::Rejected(_)));
            Ok(ResolveOutcome::Rejected(Rejection::new(
                "provenance.parent_rejected",
                "test parent rejection",
            )))
        }
    }

    struct ChildResolver;

    impl ActionResolver for ChildResolver {
        fn resolve(
            &self,
            _context: &dyn loom_capability::ResolutionContext,
            _input: &Value,
        ) -> Result<ResolveOutcome, ResolverError> {
            Ok(ResolveOutcome::Rejected(Rejection::new(
                "provenance.child_rejected",
                "test child rejection",
            )))
        }
    }

    struct ReadObservationCapability {
        manifest: CapabilityManifest,
    }

    impl Capability for ReadObservationCapability {
        fn manifest(&self) -> &CapabilityManifest {
            &self.manifest
        }

        fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
            registrar.register_action(
                ActionDefinition::new(
                    ActionTypeId::from("provenance.read.reject"),
                    SchemaRevision::new(1),
                ),
                ReadRejectResolver,
            )?;
            registrar.register_action(
                ActionDefinition::new(
                    ActionTypeId::from("provenance.read.fail"),
                    SchemaRevision::new(1),
                ),
                ReadFailResolver,
            )
        }
    }

    fn observe_base_reads(context: &dyn ResolutionContext) {
        let base = context.base_world();
        let _ = base.get_entity(id::<EntityId>(10));
        let _ = base.get_facet(
            FacetOwner::entity(id::<EntityId>(10)),
            &FacetTypeId::from("provenance.read.facet"),
        );
        let _ = base.get_relationship(id::<RelationshipId>(20));
        let _ = base.get_entity(id::<EntityId>(10));
    }

    struct ReadRejectResolver;

    impl ActionResolver for ReadRejectResolver {
        fn resolve(
            &self,
            context: &dyn ResolutionContext,
            _input: &Value,
        ) -> Result<ResolveOutcome, ResolverError> {
            observe_base_reads(context);
            Ok(ResolveOutcome::Rejected(Rejection::new(
                "provenance.read.rejected",
                "read provenance rejection",
            )))
        }
    }

    struct ReadFailResolver;

    impl ActionResolver for ReadFailResolver {
        fn resolve(
            &self,
            context: &dyn ResolutionContext,
            _input: &Value,
        ) -> Result<ResolveOutcome, ResolverError> {
            observe_base_reads(context);
            Err(ResolverError::new("read provenance failure"))
        }
    }

    struct EntropyCapability {
        manifest: CapabilityManifest,
    }

    impl Capability for EntropyCapability {
        fn manifest(&self) -> &CapabilityManifest {
            &self.manifest
        }

        fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
            registrar.register_action(
                ActionDefinition::new(
                    ActionTypeId::from("entropy.sample"),
                    loom_core::SchemaRevision::new(1),
                ),
                EntropyResolver,
            )
        }
    }

    struct EntropyResolver;

    impl ActionResolver for EntropyResolver {
        fn resolve(
            &self,
            context: &dyn ResolutionContext,
            _input: &Value,
        ) -> Result<ResolveOutcome, ResolverError> {
            let _first = context.request_entropy(&EntropyRequest::new(2))?;
            let _second = context.request_entropy(&EntropyRequest::new(1))?;
            Ok(ResolveOutcome::Rejected(Rejection::new(
                "entropy.test_rejected",
                "entropy test does not mutate the World",
            )))
        }
    }

    struct SemanticCapability {
        manifest: CapabilityManifest,
    }

    impl Capability for SemanticCapability {
        fn manifest(&self) -> &CapabilityManifest {
            &self.manifest
        }

        fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
            registrar.register_semantic_index(SemanticIndexDefinition::new(
                "semantic.test.index",
                SemanticIndexSource::new("facet", "semantic.test.facet", SchemaRevision::new(1)),
                SchemaRevision::new(1),
                1,
                "semantic-model-1",
                2,
                SemanticIndexMetric::Cosine,
                json!({}),
            ))
        }
    }

    #[derive(Clone)]
    struct SemanticTestStore {
        hits: Vec<SemanticProjectionHit>,
    }

    impl SemanticProjectionStore for SemanticTestStore {
        fn register_semantic_projection(
            &self,
            _registration: SemanticProjectionRegistration,
        ) -> PersistenceFuture<'_, Result<(), SemanticProjectionError>> {
            Box::pin(async { Ok(()) })
        }

        fn query_semantic_projection(
            &self,
            _query: SemanticProjectionQuery,
        ) -> PersistenceFuture<'_, Result<Vec<SemanticProjectionHit>, SemanticProjectionError>>
        {
            let hits = self.hits.clone();
            Box::pin(async move { Ok(hits) })
        }

        fn rebuild_semantic_projection<'a>(
            &'a self,
            _rebuild: &'a SemanticProjectionRebuild,
        ) -> PersistenceFuture<'a, Result<(), SemanticProjectionError>> {
            Box::pin(async { Ok(()) })
        }

        fn delete_semantic_projection(
            &self,
            _key: SemanticProjectionKey,
        ) -> PersistenceFuture<'_, Result<(), SemanticProjectionError>> {
            Box::pin(async { Ok(()) })
        }
    }

    fn semantic_registry() -> CapabilityRegistry {
        CapabilityRegistry::assemble(vec![Box::new(SemanticCapability {
            manifest: CapabilityManifest::parse("semantic.test", "0.1.0")
                .expect("semantic test manifest should parse"),
        })])
        .expect("semantic test registry should assemble")
    }

    fn semantic_binding() -> WorldRuntimeBinding {
        WorldRuntimeBinding::new(
            [(
                CapabilityId::from("semantic.test"),
                VersionReq::parse("^0.1.0").expect("semantic requirement should parse"),
            )],
            json!({"fixture": "semantic"}),
            1,
            Some("semantic-test".to_owned()),
        )
    }

    fn semantic_hit(value: u128) -> SemanticProjectionHit {
        SemanticProjectionHit {
            source_ref: loom_core::EventRef::new(id::<TimelineId>(2), id(value)),
            source_hash: format!("source-{value}"),
            source_revision: TimelineVersion::default(),
            projection_revision: 1,
            model_revision: "semantic-model-1".to_owned(),
            distance: 0.0,
        }
    }

    fn block_on<F: std::future::Future>(future: F) -> F::Output {
        let mut future = Box::pin(future);
        let waker = std::task::Waker::noop();
        let mut context = std::task::Context::from_waker(waker);
        loop {
            match future.as_mut().poll(&mut context) {
                std::task::Poll::Ready(output) => return output,
                std::task::Poll::Pending => std::thread::yield_now(),
            }
        }
    }

    #[test]
    fn semantic_host_records_ordered_evidence_and_applies_session_bounds() {
        let registry = semantic_registry();
        let assembly = test_assembly(&registry, semantic_binding());
        let state = Rc::new(RefCell::new(ExecutionState::new(
            &assembly.execution_policy(),
            assembly.entropy_source_id().clone(),
        )));
        let store = SemanticTestStore {
            hits: vec![semantic_hit(11), semantic_hit(12)],
        };
        let request = SemanticQueryRequest::new(
            "semantic.test.index",
            SchemaRevision::new(1),
            1,
            "semantic-model-1",
            vec![1.0, 0.0],
            2,
        );
        let result = block_on(query_semantic_host(
            &base(),
            &registry,
            &assembly,
            &store,
            &state,
            &request,
        ))
        .expect("semantic host should return bounded hits");
        assert_eq!(result.hits.len(), 2);
        let reads = state.borrow().read_set.entries().to_vec();
        assert!(matches!(
            &reads[0],
            ReadDependency::Semantic {
                source_refs,
                query_fingerprint,
                query_spec,
                ..
            } if source_refs.iter().map(|source| source.event_id).collect::<Vec<_>>()
                == vec![id(11), id(12)]
                && !query_fingerprint.is_empty()
                && query_spec.contains("index=semantic.test.index")
        ));
        let repeat = block_on(query_semantic_host(
            &base(),
            &registry,
            &assembly,
            &store,
            &state,
            &request,
        ))
        .expect("same semantic snapshot should be repeatable");
        assert_eq!(repeat, result);
        assert_eq!(state.borrow().read_set.len(), 1);

        for limit in [3, 2] {
            let bounded_assembly = test_assembly_with_budget(
                &registry,
                semantic_binding(),
                &ResolutionBudget::unlimited().with_max_semantic_results(limit),
            );
            let bounded_state = Rc::new(RefCell::new(ExecutionState::new(
                &bounded_assembly.execution_policy(),
                bounded_assembly.entropy_source_id().clone(),
            )));
            let bounded_result = block_on(query_semantic_host(
                &base(),
                &registry,
                &bounded_assembly,
                &store,
                &bounded_state,
                &request,
            ))
            .expect("under and exact semantic result bounds should pass");
            assert_eq!(bounded_result.hits.len(), 2);
        }

        let bounded_assembly = test_assembly_with_budget(
            &registry,
            semantic_binding(),
            &ResolutionBudget::unlimited().with_max_semantic_results(1),
        );
        let bounded_state = Rc::new(RefCell::new(ExecutionState::new(
            &bounded_assembly.execution_policy(),
            bounded_assembly.entropy_source_id().clone(),
        )));
        let error = block_on(query_semantic_host(
            &base(),
            &registry,
            &bounded_assembly,
            &store,
            &bounded_state,
            &request,
        ))
        .expect_err("session result bound must reject before adapter materialization");
        assert!(matches!(
            error,
            SemanticQueryError::Bounds { ref dimension, .. } if dimension == "semantic_results"
        ));
        assert!(bounded_state.borrow().read_set.is_empty());
    }

    #[test]
    fn session_provenance_entry_budget_accepts_under_exact_and_rejects_over() {
        let registry = semantic_registry();
        let assembly = test_assembly(&registry, semantic_binding());
        let mut evidence = ExecutionEvidence::new(assembly.entropy_source_id().clone());
        for value in [10, 11, 12] {
            evidence.read_set.record(ReadDependency::Entity {
                entity_id: id(value),
                present: true,
            });
        }

        for limit in [4, 3] {
            check_session_provenance_budget(
                &ResolutionBudget::unlimited().with_max_session_provenance_entries(limit),
                &evidence,
                None,
            )
            .expect("under and exact provenance entry bounds should pass");
        }
        let error = check_session_provenance_budget(
            &ResolutionBudget::unlimited().with_max_session_provenance_entries(2),
            &evidence,
            None,
        )
        .expect_err("over provenance entry bound should fail");
        assert!(error.to_string().contains("entry count"));
    }

    fn registry() -> CapabilityRegistry {
        CapabilityRegistry::assemble(vec![
            Box::new(ParentCapability {
                manifest: CapabilityManifest::parse("provenance.parent", "0.1.0")
                    .expect("parent manifest should parse")
                    .requires(
                        CapabilityDependency::parse("provenance.child", "^0.1.0")
                            .expect("child dependency should parse"),
                    ),
            }) as Box<dyn Capability>,
            Box::new(ChildCapability {
                manifest: CapabilityManifest::parse("provenance.child", "0.1.0")
                    .expect("child manifest should parse"),
            }),
        ])
        .expect("provenance registry should assemble")
    }

    fn read_registry() -> CapabilityRegistry {
        CapabilityRegistry::assemble(vec![Box::new(ReadObservationCapability {
            manifest: CapabilityManifest::parse("provenance.read", "0.1.0")
                .expect("read provenance manifest should parse"),
        })])
        .expect("read provenance registry should assemble")
    }

    fn read_binding() -> WorldRuntimeBinding {
        WorldRuntimeBinding::new(
            [(
                CapabilityId::from("provenance.read"),
                VersionReq::parse("^0.1.0").expect("read provenance requirement should parse"),
            )],
            json!({"fixture": "read-provenance"}),
            1,
            Some("read-provenance-test".to_owned()),
        )
    }

    fn base() -> BaseWorldView {
        BaseWorldView::new(BaseWorldSnapshot::new(
            id::<WorldId>(1),
            id::<TimelineId>(2),
            TimelineVersion::new(EventSeq::new(0), StateRevision::new(0)),
            WorldInstant::new(0),
        ))
    }

    fn reconciliation_token_and_claim() -> (ValidatedResolution, WorkClaim) {
        let registry = registry();
        let resolution = EffectEngine::new(&registry)
            .validate(
                &base(),
                "provenance.parent",
                loom_protocol::Resolution::default(),
            )
            .expect("test resolution should validate");
        let claim = WorkClaim::with_attempt_count(
            id::<TimelineId>(2),
            id::<WorkId>(7),
            PlatformTime::new(10),
            1,
            1,
        );
        (resolution, claim)
    }

    fn reconciliation_work(
        work_id: WorkId,
        status: WorkStatus,
        lease: Option<crate::WorkLease>,
    ) -> WorkRecord {
        WorkRecord {
            id: work_id,
            timeline_id: id::<TimelineId>(2),
            target: WorkTarget::CapabilityWork {
                owner: None,
                handler: WorkHandlerId::from("test.handler"),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 1,
            causal_event_id: None,
            origin_work_id: None,
            status,
            attempt_count: 1,
            claim_generation: 1,
            available_at: PlatformTime::new(0),
            last_error: None,
            lease,
        }
    }

    #[test]
    fn ingress_exact_recovery_rejects_after_event_and_work_mismatch() {
        let timeline_id = id::<TimelineId>(91);
        let before = TimelineVersion::default();
        let after = TimelineVersion::new(EventSeq::default(), StateRevision::new(1));
        let transition = LogicalWorkTransition::Schedule {
            work_id: id::<WorkId>(92),
            target: WorkTarget::CapabilityWork {
                owner: Some("test".to_owned()),
                handler: WorkHandlerId::from("test.handler"),
            },
            schema_revision: SchemaRevision::new(1),
            payload: json!({"value": 1}),
            effective_due_world_time: WorldInstant::new(0),
            logical_schedule_order: 1,
            causal_event_id: None,
            origin_work_id: None,
        };
        let mut provenance = CommitProvenance::new(
            id::<loom_core::ExecutionSessionId>(93),
            IngressId::from("ingress-regression"),
            "canonical-proposal",
        );
        provenance.expected_after_version = Some(after);
        provenance.expected_event_ids = Vec::new();
        provenance.logical_work_transitions = vec![transition.clone()];
        let commit = LogicalCommit {
            timeline_id,
            before_version: before,
            after_version: after,
            world_time: None,
            event_ids: Vec::new(),
            work_transitions: vec![transition.clone()],
            chronology_budget: None,
            provenance: Some(provenance.clone()),
        };
        let matches = |commit: &LogicalCommit| {
            exact_logical_commit_matches(
                commit,
                Some(&provenance),
                timeline_id,
                before,
                after,
                &[],
                Some(std::slice::from_ref(&transition)),
            )
        };
        assert!(matches(&commit));
        let mut tampered = commit.clone();
        tampered.after_version = TimelineVersion::new(EventSeq::new(1), StateRevision::new(1));
        assert!(!matches(&tampered));
        let mut tampered = commit.clone();
        tampered.event_ids.push(id::<loom_core::EventId>(94));
        assert!(!matches(&tampered));
        let mut tampered = commit;
        if let LogicalWorkTransition::Schedule { payload, .. } = &mut tampered.work_transitions[0] {
            *payload = json!({"value": 2});
        }
        assert!(!matches(&tampered));
    }

    #[test]
    fn failed_ingress_session_is_classified_non_resumable() {
        let ingress_id = IngressId::from("failed-ingress");
        let session = ExecutionSession::new_ingress(
            id::<loom_core::ExecutionSessionId>(95),
            ingress_id,
            test_assembly(&semantic_registry(), semantic_binding()),
            PlatformTime::new(1),
        )
        .finish(ExecutionSessionStatus::Failed, PlatformTime::new(2))
        .expect("Started Session should transition to Failed");
        assert!(matches!(
            classify_ingress_sessions(&[session]),
            Ok(IngressRecovery::TerminalFailed)
        ));
    }

    fn test_assembly(
        registry: &CapabilityRegistry,
        binding: WorldRuntimeBinding,
    ) -> ExecutionAssembly {
        test_assembly_with_budget(registry, binding, &ResolutionBudget::unlimited())
    }

    fn test_assembly_with_budget(
        registry: &CapabilityRegistry,
        binding: WorldRuntimeBinding,
        execution_policy: &ResolutionBudget,
    ) -> ExecutionAssembly {
        let revision = RuntimeRevisionDescriptor::new(
            RuntimeRevisionId::from("test-revision"),
            PlatformTime::default(),
            "test-build",
            Version::new(0, 1, 0),
            registry.capabilities().map(|manifest| {
                RuntimeRevisionCapability::from_manifest(
                    manifest,
                    format!("test:{}@{}", manifest.id, manifest.version),
                )
            }),
        )
        .expect("test registry should form a Runtime Revision");
        let selection = RuntimeRevisionSelection::new(revision.clone(), 1, PlatformTime::default());
        let implementations = revision
            .compatible_with(&binding)
            .expect("test binding should be compatible");
        let view = base();
        ExecutionAssembly::new(
            id::<loom_core::ExecutionSessionId>(3),
            view.world_id(),
            view.timeline_id(),
            view.version(),
            view.world_time(),
            binding,
            selection,
            implementations,
            execution_policy,
            EntropySourceId::from("test-entropy"),
        )
    }

    fn entropy_registry() -> CapabilityRegistry {
        CapabilityRegistry::assemble(vec![Box::new(EntropyCapability {
            manifest: CapabilityManifest::parse("entropy.test", "0.1.0")
                .expect("entropy test manifest should parse"),
        })])
        .expect("entropy test registry should assemble")
    }

    fn entropy_binding() -> WorldRuntimeBinding {
        WorldRuntimeBinding::new(
            [(
                CapabilityId::from("entropy.test"),
                VersionReq::parse("^0.1.0").expect("entropy requirement should parse"),
            )],
            json!({"fixture": "entropy"}),
            1,
            Some("entropy-test".to_owned()),
        )
    }

    #[test]
    fn scheduler_commit_reconciliation_distinguishes_committed_absent_and_ambiguous() {
        let (resolution, claim) = reconciliation_token_and_claim();
        let base_version = resolution.base_version();
        let after_version = TimelineVersion::new(EventSeq::new(0), StateRevision::new(1));
        let committed_journal = vec![crate::LogicalCommit {
            timeline_id: claim.timeline_id(),
            before_version: base_version,
            after_version,
            world_time: None,
            event_ids: Vec::new(),
            work_transitions: vec![LogicalWorkTransition::Complete {
                work_id: claim.work_id(),
            }],
            chronology_budget: Some(crate::ChronologyBudgetConsumption {
                world_time: WorldInstant::new(0),
                before: 0,
                after: 1,
            }),
            provenance: None,
        }];
        let committed = TimelineSnapshot::with_journal(
            BaseWorldSnapshot::new(
                id::<WorldId>(1),
                claim.timeline_id(),
                after_version,
                WorldInstant::new(0),
            ),
            Vec::new(),
            vec![reconciliation_work(
                claim.work_id(),
                WorkStatus::Completed,
                None,
            )],
            committed_journal,
        );
        assert_eq!(
            reconcile_scheduler_commit_snapshot(&committed, &resolution, &claim),
            SchedulerCommitReconciliation::Committed {
                event_ids: Vec::new(),
                version: after_version,
            }
        );
        assert_eq!(committed.journal.len(), 1);
        assert_eq!(committed.chronology_budget().consumed, 1);

        let live_lease = crate::WorkLease::new(claim.claimed_until(), claim.fence());
        let absent = TimelineSnapshot::with_journal(
            BaseWorldSnapshot::new(
                id::<WorldId>(1),
                claim.timeline_id(),
                base_version,
                WorldInstant::new(0),
            ),
            Vec::new(),
            vec![reconciliation_work(
                claim.work_id(),
                WorkStatus::Pending,
                Some(live_lease),
            )],
            Vec::new(),
        );
        assert_eq!(
            reconcile_scheduler_commit_snapshot(&absent, &resolution, &claim),
            SchedulerCommitReconciliation::Absent
        );
        assert!(absent.journal.is_empty());
        assert_eq!(absent.chronology_budget().consumed, 0);

        let ambiguous = TimelineSnapshot::with_journal(
            BaseWorldSnapshot::new(
                id::<WorldId>(1),
                claim.timeline_id(),
                after_version,
                WorldInstant::new(0),
            ),
            Vec::new(),
            vec![reconciliation_work(
                claim.work_id(),
                WorkStatus::Pending,
                Some(live_lease),
            )],
            Vec::new(),
        );
        assert_eq!(
            reconcile_scheduler_commit_snapshot(&ambiguous, &resolution, &claim),
            SchedulerCommitReconciliation::Ambiguous
        );
        assert!(ambiguous.journal.is_empty());
        assert_eq!(ambiguous.chronology_budget().consumed, 0);
    }

    #[test]
    fn runtime_call_edge_is_observable_separately_from_world_causality() {
        let registry = registry();
        let binding = WorldRuntimeBinding::new(
            ["provenance.parent", "provenance.child"]
                .into_iter()
                .map(|id| {
                    (
                        CapabilityId::from(id),
                        VersionReq::parse("^0.1.0").expect("test requirement should parse"),
                    )
                }),
            json!({"fixture": "provenance"}),
            1,
            Some("test-provenance".to_owned()),
        );
        let assembly = test_assembly(&registry, binding);
        let invocation = ActionInvocation::new(ActionTypeId::from("provenance.parent"), json!({}));
        let source = UnavailableEntropySource;
        let mut entropy_evidence = EntropyEvidence::new(assembly.entropy_source_id().clone());
        let mut final_evidence = ExecutionEvidence::new(assembly.entropy_source_id().clone());
        let (outcome, execution) = dispatch_root_action(
            &base(),
            &registry,
            &assembly,
            &source,
            &mut entropy_evidence,
            &mut final_evidence,
            &invocation,
        )
        .expect("root dispatch should complete with semantic rejection");
        assert!(matches!(outcome, ResolveOutcome::Rejected(_)));
        assert_eq!(execution.call_provenance.len(), 1);
        let edge = &execution.call_provenance.edges()[0];
        assert_eq!(edge.caller_capability.as_str(), "provenance.parent");
        assert_eq!(edge.caller_action.as_str(), "provenance.parent");
        assert_eq!(edge.target_capability.as_str(), "provenance.child");
        assert_eq!(edge.target_action.as_str(), "provenance.child");

        let validated = EffectEngine::new(&registry)
            .validate_segments(&base(), &[], execution.call_provenance)
            .expect("empty Work-like validation should retain provenance");
        assert_eq!(validated.call_provenance().len(), 1);
        assert!(validated.events().is_empty());
    }

    #[test]
    fn rejected_and_failed_dispatch_round_trip_base_reads_in_observation_order() {
        let registry = read_registry();
        let assembly = test_assembly(&registry, read_binding());
        let source = UnavailableEntropySource;
        for (action, status, should_reject) in [
            (
                "provenance.read.reject",
                ExecutionSessionStatus::Rejected,
                true,
            ),
            (
                "provenance.read.fail",
                ExecutionSessionStatus::Failed,
                false,
            ),
        ] {
            let invocation = ActionInvocation::new(ActionTypeId::from(action), json!({}));
            let mut entropy_evidence = EntropyEvidence::new(assembly.entropy_source_id().clone());
            let mut final_evidence = ExecutionEvidence::new(assembly.entropy_source_id().clone());
            let result = dispatch_root_action(
                &base(),
                &registry,
                &assembly,
                &source,
                &mut entropy_evidence,
                &mut final_evidence,
                &invocation,
            );
            if should_reject {
                assert!(matches!(
                    result.expect("rejection should return an outcome").0,
                    ResolveOutcome::Rejected(_)
                ));
            } else {
                assert!(result.is_err(), "resolver failure should be returned");
            }

            let entries = final_evidence.read_set.entries();
            assert_eq!(entries.len(), 3, "duplicate observations must be removed");
            assert!(matches!(
                &entries[0],
                ReadDependency::Entity { entity_id, present }
                    if *entity_id == id::<EntityId>(10) && !present
            ));
            assert!(matches!(
                &entries[1],
                ReadDependency::Facet {
                    owner,
                    facet_type,
                    schema_revision,
                } if *owner == FacetOwner::entity(id::<EntityId>(10))
                    && facet_type == &FacetTypeId::from("provenance.read.facet")
                    && schema_revision.is_none()
            ));
            assert!(matches!(
                &entries[2],
                ReadDependency::Relationship {
                    relationship_id,
                    present,
                } if *relationship_id == id::<RelationshipId>(20) && !present
            ));

            let session = ExecutionSession::new(
                assembly.session_id(),
                ExecutionOrigin::Application,
                assembly.clone(),
                PlatformTime::default(),
            )
            .finish_with_evidence(status, PlatformTime::new(1), final_evidence)
            .expect("terminal Session should retain dispatch evidence");
            let encoded = serde_json::to_value(&session).expect("Session should serialize");
            let restored: ExecutionSession =
                serde_json::from_value(encoded).expect("Session should deserialize");
            assert_eq!(restored, session);
        }
    }

    #[test]
    fn bootstrap_validation_failure_round_trips_base_and_candidate_reads() {
        let registry = registry();
        let binding = WorldRuntimeBinding::new(
            ["provenance.parent", "provenance.child"]
                .into_iter()
                .map(|id| {
                    (
                        CapabilityId::from(id),
                        VersionReq::parse("^0.1.0").expect("provenance requirement should parse"),
                    )
                }),
            json!({"fixture": "bootstrap-read-provenance"}),
            1,
            Some("bootstrap-read-provenance-test".to_owned()),
        );
        let assembly = test_assembly(&registry, binding);
        let base = base();
        let _ = base.entity(id::<EntityId>(10));
        let _ = base.facet(
            FacetOwner::entity(id::<EntityId>(10)),
            &FacetTypeId::from("bootstrap.read.facet"),
        );
        let _ = base.relationship(id::<RelationshipId>(20));
        let invalid_event = ProposedEvent::new(
            id::<EventId>(30),
            EventTypeId::from("bootstrap.invalid"),
            SchemaRevision::new(1),
            json!({}),
        );
        let mut validation_reads = ReadSet::default();
        let error = EffectEngine::new(&registry)
            .validate_segments_with_entropy_and_reads(
                &base,
                &[ResolutionSegment::new(
                    CapabilityId::from("provenance.parent"),
                    Resolution::new(vec![invalid_event], Vec::new()),
                )],
                CallProvenance::default(),
                EntropyEvidence::new(assembly.entropy_source_id().clone()),
                &mut validation_reads,
            )
            .expect_err("bootstrap validation should retain evidence on error");
        assert!(matches!(error, RuntimeError::Validation(_)));
        let evidence = evidence_with_read_set(
            ExecutionEvidence::from_parts(
                base.read_set(),
                CallProvenance::default(),
                EntropyEvidence::new(assembly.entropy_source_id().clone()),
            ),
            validation_reads,
        );
        assert_eq!(evidence.read_set.len(), 4);
        assert!(matches!(
            &evidence.read_set.entries()[3],
            ReadDependency::Event { event_id, present }
                if *event_id == id::<EventId>(30) && !present
        ));
        let session = ExecutionSession::new(
            assembly.session_id(),
            ExecutionOrigin::Runtime,
            assembly,
            PlatformTime::default(),
        )
        .finish_with_evidence(
            ExecutionSessionStatus::Failed,
            PlatformTime::new(1),
            evidence,
        )
        .expect("bootstrap failure Session should retain evidence");
        let encoded = serde_json::to_value(&session).expect("Session should serialize");
        let restored: ExecutionSession =
            serde_json::from_value(encoded).expect("Session should deserialize");
        assert_eq!(restored, session);
    }

    #[test]
    fn entropy_is_ordered_and_retained_in_session_provenance() {
        let registry = entropy_registry();
        let assembly = test_assembly(&registry, entropy_binding());
        let source =
            DeterministicEntropySource::with_source_id("test-entropy", vec![vec![1, 2], vec![3]]);
        let invocation = ActionInvocation::new(ActionTypeId::from("entropy.sample"), json!({}));
        let mut entropy_evidence = EntropyEvidence::new(assembly.entropy_source_id().clone());
        let mut final_evidence = ExecutionEvidence::new(assembly.entropy_source_id().clone());
        let (outcome, execution) = dispatch_root_action(
            &base(),
            &registry,
            &assembly,
            &source,
            &mut entropy_evidence,
            &mut final_evidence,
            &invocation,
        )
        .expect("deterministic entropy dispatch should succeed");
        assert!(matches!(outcome, ResolveOutcome::Rejected(_)));
        assert_eq!(source.calls(), 2);
        assert_eq!(
            execution.entropy_evidence.source_id().as_str(),
            "test-entropy"
        );
        assert_eq!(execution.entropy_evidence.len(), 2);
        assert_eq!(execution.entropy_evidence.observations()[0].ordinal, 0);
        assert_eq!(
            execution.entropy_evidence.observations()[0]
                .sample
                .as_bytes(),
            &[1, 2]
        );
        assert_eq!(execution.entropy_evidence.observations()[1].ordinal, 1);
        assert_eq!(
            execution.entropy_evidence.observations()[1]
                .sample
                .as_bytes(),
            &[3]
        );

        let session = ExecutionSession::new(
            assembly.session_id(),
            ExecutionOrigin::Application,
            assembly.clone(),
            PlatformTime::default(),
        );
        let finished = session
            .finish_with_entropy(
                ExecutionSessionStatus::Rejected,
                PlatformTime::default(),
                execution.entropy_evidence.clone(),
            )
            .expect("Session should retain same-source entropy evidence");
        assert_eq!(finished.entropy_evidence(), &execution.entropy_evidence);
        let encoded = serde_json::to_value(&finished).expect("Session should serialize");
        let restored: ExecutionSession =
            serde_json::from_value(encoded).expect("Session evidence should deserialize");
        assert_eq!(restored, finished);
        assert_eq!(source.calls(), 2);
    }

    #[test]
    fn entropy_budget_fails_before_the_next_source_call() {
        let registry = entropy_registry();
        let assembly = test_assembly_with_budget(
            &registry,
            entropy_binding(),
            &ResolutionBudget::unlimited().with_max_entropy_requests(1),
        );
        let source =
            DeterministicEntropySource::with_source_id("test-entropy", vec![vec![1, 2], vec![3]]);
        let invocation = ActionInvocation::new(ActionTypeId::from("entropy.sample"), json!({}));
        let mut entropy_evidence = EntropyEvidence::new(assembly.entropy_source_id().clone());
        let mut final_evidence = ExecutionEvidence::new(assembly.entropy_source_id().clone());
        let error = dispatch_root_action(
            &base(),
            &registry,
            &assembly,
            &source,
            &mut entropy_evidence,
            &mut final_evidence,
            &invocation,
        )
        .expect_err("second entropy request should exceed the pinned policy");

        assert_eq!(source.calls(), 1);
        assert!(error.to_string().contains("entropy_requests"));
        match &error {
            DispatchError::Resolver(resolver) => match resolver.kind() {
                ResolverErrorKind::Entropy(EntropyError::BudgetExceeded {
                    dimension,
                    limit,
                    actual,
                }) => {
                    assert_eq!(*dimension, EntropyBudgetDimension::Requests);
                    assert_eq!(*limit, 1);
                    assert_eq!(*actual, 2);
                }
                other => panic!("expected typed entropy budget failure, got {other:?}"),
            },
            other => panic!("expected resolver dispatch failure, got {other:?}"),
        }
    }

    #[test]
    fn entropy_byte_limits_are_checked_before_source_calls() {
        let registry = entropy_registry();
        let invocation = ActionInvocation::new(ActionTypeId::from("entropy.sample"), json!({}));

        let total_bytes_assembly = test_assembly_with_budget(
            &registry,
            entropy_binding(),
            &ResolutionBudget::unlimited().with_max_entropy_bytes(2),
        );
        let total_bytes_source =
            DeterministicEntropySource::with_source_id("test-entropy", vec![vec![1, 2], vec![3]]);
        let mut total_bytes_evidence =
            EntropyEvidence::new(total_bytes_assembly.entropy_source_id().clone());
        let mut total_bytes_final_evidence =
            ExecutionEvidence::new(total_bytes_assembly.entropy_source_id().clone());
        let total_bytes_error = dispatch_root_action(
            &base(),
            &registry,
            &total_bytes_assembly,
            &total_bytes_source,
            &mut total_bytes_evidence,
            &mut total_bytes_final_evidence,
            &invocation,
        )
        .expect_err("total entropy bytes should reject the second request");
        assert_eq!(total_bytes_source.calls(), 1);
        assert!(total_bytes_error.to_string().contains("entropy_bytes"));

        let request_bytes_assembly = test_assembly_with_budget(
            &registry,
            entropy_binding(),
            &ResolutionBudget::unlimited().with_max_entropy_request_bytes(1),
        );
        let request_bytes_source =
            DeterministicEntropySource::with_source_id("test-entropy", vec![vec![1, 2], vec![3]]);
        let mut request_bytes_evidence =
            EntropyEvidence::new(request_bytes_assembly.entropy_source_id().clone());
        let mut request_bytes_final_evidence =
            ExecutionEvidence::new(request_bytes_assembly.entropy_source_id().clone());
        let request_bytes_error = dispatch_root_action(
            &base(),
            &registry,
            &request_bytes_assembly,
            &request_bytes_source,
            &mut request_bytes_evidence,
            &mut request_bytes_final_evidence,
            &invocation,
        )
        .expect_err("per-request entropy bytes should reject the first request");
        assert_eq!(request_bytes_source.calls(), 0);
        assert!(
            request_bytes_error
                .to_string()
                .contains("entropy_request_bytes")
        );
    }
}
