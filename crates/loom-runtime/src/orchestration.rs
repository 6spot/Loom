//! Runtime orchestration over the unified API, Capability registry and ports.
//!
//! This module owns the composition that turns one public Action or Durable
//! Work execution into the existing Runtime validation and persistence path.
//! It does not define a second protocol, storage boundary or public endpoint.

use std::{
    cell::RefCell,
    collections::BTreeMap,
    rc::Rc,
    sync::{Arc, Mutex},
};

use loom_api::{
    ActionDescriptor, ActionRequest, ActionService, ApiError, ApiFuture, ApiResult, CatalogService,
    CatalogSnapshot, CommittedEvent as ApiCommittedEvent, CreateWorldFromTemplateRequest,
    CreateWorldFromTemplateResult, EventQuery, ExecutionResult, FacetQuery,
    FacetSnapshot as ApiFacetSnapshot, HistoryService, QueryService, TimelineService,
    TimelineSnapshot as ApiTimelineSnapshot, TimelineTarget, WorldService, WorldTemplateDescriptor,
};
use loom_capability::{
    CapabilityId, CapabilityRegistry, DispatchError, EntropyBudgetDimension, EntropyError,
    EntropyRequest, EntropySample, ResolutionContext, ResolutionContextError, ResolverError,
};
use loom_core::{ActionTypeId, TimelineId, WorkId};
use loom_protocol::{ActionInvocation, Resolution, ResolveOutcome, WorkTarget};
use semver::VersionReq;
use serde_json::json;

use crate::{
    BaseWorldSnapshot, BaseWorldView, BindingError, BudgetError, BudgetUsage, CallProvenance,
    CandidateWorldView, CommitError, CommitStore, CommittedEvent, EffectEngine, EntropyEvidence,
    EntropySource, EntropySourceId, ExecutionAssembly, ExecutionOrigin, ExecutionSession,
    ExecutionSessionStatus, ExecutionSessionStore, FailurePolicy, IdentityAllocator,
    LifecycleError, ManualPlatformClock, PersistenceFuture, PlatformClock, PlatformTime, ReadError,
    ResolutionBudget, RuntimeControlStore, RuntimeError, RuntimeRevisionAssembly,
    RuntimeRevisionCapability, RuntimeRevisionDescriptor, RuntimeRevisionError, RuntimeRevisionId,
    RuntimeRevisionSelection, RuntimeRevisionStore, SessionError,
    TimelineBlockedOnMissingImplementation, TimelineSnapshot, UnavailableEntropySource,
    UuidV7IdentityAllocator, ValidatedResolution, ValidationError, WorkClaim, WorkError,
    WorkRecord, WorkStore, WorkTerminalState, WorkTerminalization, WorldLifecycleStore,
    WorldRuntimeBinding, WorldRuntimeBindingStore, WorldStore,
};

use super::validation::ResolutionSegment;

type MissingImplementationObservations =
    Arc<Mutex<BTreeMap<(TimelineId, WorkId), (PlatformTime, PlatformTime)>>>;

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
    identity_allocator: Arc<dyn IdentityAllocator>,
    resolution_budget: ResolutionBudget,
    failure_policy: FailurePolicy,
    missing_implementation_observations: MissingImplementationObservations,
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
            identity_allocator: Arc::new(UuidV7IdentityAllocator),
            resolution_budget: ResolutionBudget::unlimited(),
            failure_policy: FailurePolicy::default(),
            missing_implementation_observations: Arc::new(Mutex::new(BTreeMap::new())),
        })
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

    /// Injects the bounded Runtime policy for automatic technical Work
    /// failures. The policy changes only platform retry/terminalization
    /// behavior; it never changes Work's semantic due time or logical order.
    #[must_use]
    pub fn with_failure_policy(mut self, failure_policy: FailurePolicy) -> Self {
        self.failure_policy = failure_policy;
        self
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
        let (selection, legacy_migration) = match active_selection {
            Some(selection) => (selection, false),
            None => (self.legacy_runtime_revision(), true),
        };
        // M3 Worlds can carry the checked-in compatibility baseline while a
        // test/application Runtime intentionally installs only a subset of
        // that historical registry. The synthetic, non-activated migration
        // selection preserves that pre-M4 behavior; an explicitly activated
        // revision remains strict against every immutable Binding requirement.
        let compatibility_binding = if legacy_migration {
            WorldRuntimeBinding::new(
                binding
                    .requirements()
                    .iter()
                    .filter(|(capability_id, _)| self.registry.capability(capability_id).is_some())
                    .map(|(capability_id, requirement)| {
                        (capability_id.clone(), requirement.clone())
                    }),
                binding.configuration().clone(),
                binding.revision(),
                binding.template_provenance().map(str::to_owned),
            )
        } else {
            binding.clone()
        };
        let implementations = selection
            .revision()
            .compatible_with(&compatibility_binding)
            .map_err(|error| map_revision_compatibility_error(&error))?;

        // The persisted revision is a description of the composition root's
        // exact software. Validate that the immutable registry supplied to
        // this Runtime still represents that description before Session start.
        // The registry itself is never refreshed or re-selected while a
        // Session is executing.
        for implementation in implementations.capabilities().values() {
            let Some(manifest) = self.registry.capability(implementation.capability_id()) else {
                return Err(ApiError::unavailable(
                    "active Runtime Revision implementation is not installed",
                ));
            };
            if manifest.version != *implementation.version()
                || manifest.loom_compatibility != *implementation.loom_compatibility()
            {
                return Err(ApiError::unavailable(
                    "active Runtime Revision implementation does not match the installed registry",
                ));
            }
        }

        let session_id = self.identity_allocator.allocate_execution_session_id();
        if session_id.is_nil() {
            return Err(ApiError::internal(
                "Runtime identity allocator returned an invalid Execution Session identity",
            ));
        }
        Ok(ExecutionAssembly::new(
            session_id,
            snapshot.world_id(),
            snapshot.timeline_id(),
            snapshot.version(),
            snapshot.world_time(),
            binding,
            selection,
            implementations,
            self.resolution_budget,
            self.entropy_source.source_id(),
        ))
    }

    fn legacy_runtime_revision(&self) -> RuntimeRevisionSelection {
        let loom_version = self.registry.loom_version().clone();
        let capabilities = self.registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("legacy-registry:{}@{}", manifest.id, manifest.version),
            )
        });
        let descriptor = RuntimeRevisionDescriptor::new(
            RuntimeRevisionId::from("legacy-registry"),
            PlatformTime::default(),
            "legacy-registry",
            loom_version,
            capabilities,
        )
        .expect("the immutable assembled Capability registry must form a legacy revision");
        RuntimeRevisionSelection::new(descriptor, 0, PlatformTime::default())
    }

    async fn start_execution_session(
        &self,
        assembly: ExecutionAssembly,
        origin: ExecutionOrigin,
    ) -> ApiResult<ExecutionSession> {
        let session = ExecutionSession::new(
            assembly.session_id(),
            origin,
            assembly,
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

    async fn finish_execution_session_with_entropy(
        &self,
        session_id: loom_core::ExecutionSessionId,
        status: ExecutionSessionStatus,
        entropy_evidence: EntropyEvidence,
    ) -> ApiResult<ExecutionSession> {
        self.store
            .finish_session_with_entropy(
                session_id,
                status,
                self.platform_clock.now(),
                entropy_evidence,
            )
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

    /// Explicitly activates a previously registered Runtime Revision through
    /// the generation CAS. This operation is Platform History only and never
    /// mutates World, Timeline, Event, State or World Runtime Binding data.
    ///
    /// # Errors
    ///
    /// Returns a typed missing-revision, stale-generation or storage error.
    pub async fn activate_runtime_revision(
        &self,
        revision_id: RuntimeRevisionId,
        expected_generation: Option<u64>,
        activated_at: PlatformTime,
    ) -> Result<RuntimeRevisionSelection, RuntimeRevisionError>
    where
        S: RuntimeRevisionStore,
    {
        self.store
            .activate_revision(revision_id, expected_generation, activated_at)
            .await
    }

    async fn binding_for_world(
        &self,
        world_id: loom_core::WorldId,
    ) -> ApiResult<WorldRuntimeBinding> {
        self.store
            .ensure_binding(world_id, legacy_binding())
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

    fn validate_world_template(
        &self,
        template: &WorldTemplateDescriptor,
        world_id: loom_core::WorldId,
        timeline_id: TimelineId,
        assembly: &ExecutionAssembly,
        entropy_evidence: &mut EntropyEvidence,
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

        for invocation in &template.bootstrap_actions {
            enabled_action(&self.registry, assembly, &invocation.action)
                .map_err(map_dispatch_error)?;
            engine
                .validate_action_input(&invocation.action, &invocation.input)
                .map_err(|error| map_action_input_error(&error))?;
            let mut execution_entropy_evidence =
                EntropyEvidence::new(assembly.entropy_source_id().clone());
            let (outcome, execution) = match dispatch_root_action(
                &base,
                &self.registry,
                assembly,
                &*self.entropy_source,
                &mut execution_entropy_evidence,
                invocation,
            ) {
                Ok(result) => result,
                Err(error) => {
                    append_entropy_evidence(entropy_evidence, &execution_entropy_evidence);
                    return Err(map_dispatch_error(error));
                }
            };
            append_entropy_evidence(entropy_evidence, &execution.entropy_evidence);
            let ResolveOutcome::Resolved(_) = outcome else {
                return Err(ApiError::invalid_request(format!(
                    "Template bootstrap Action {} was semantically rejected",
                    invocation.action
                )));
            };
            let validated = engine
                .validate_segments_with_entropy(
                    &base,
                    &execution.segments,
                    execution.call_provenance,
                    execution.entropy_evidence,
                )
                .map_err(|error| map_runtime_error(&error))?;
            total_usage = total_usage.combine(BudgetUsage::from_resolution(validated.resolution()));
            assembly
                .execution_policy()
                .check(total_usage)
                .map_err(|error| ApiError::invalid_request(error.to_string()))?;

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

        Ok(ValidatedWorldBirthPlan {
            world_id,
            timeline_id,
            initial_world_time: template.initial_world_time,
            binding: assembly.binding().clone(),
            bootstrap,
        })
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
        let (selection, compatibility_binding) = if let Some(selection) = active_selection {
            (selection, binding.clone())
        } else {
            let compatibility_binding = WorldRuntimeBinding::new(
                binding
                    .requirements()
                    .iter()
                    .filter(|(capability_id, _)| self.registry.capability(capability_id).is_some())
                    .map(|(capability_id, requirement)| {
                        (capability_id.clone(), requirement.clone())
                    }),
                binding.configuration().clone(),
                binding.revision(),
                binding.template_provenance().map(str::to_owned),
            );
            (self.legacy_runtime_revision(), compatibility_binding)
        };
        let active_runtime_revision = selection.revision().id().clone();
        let implementations = selection.revision().compatible_with(&compatibility_binding);
        if let Ok(implementations) = implementations.as_ref()
            && work_target_has_compatible_implementation(
                &self.registry,
                &compatibility_binding,
                implementations,
                work,
            )
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
    #[allow(clippy::too_many_lines)]
    pub async fn execute_work(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
        retry_available_at: PlatformTime,
    ) -> ApiResult<ExecutionResult>
    where
        S: RuntimeControlStore,
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
        if self
            .missing_implementation_block(target, work_id)
            .await?
            .is_some()
        {
            return Err(ApiError::unavailable(
                "Work is blocked on a missing compatible implementation",
            ));
        }

        let handler_id = match &work.target {
            WorkTarget::CapabilityWork { handler, .. } => handler,
            WorkTarget::AgencyWake { .. } => {
                return Err(ApiError::unavailable(
                    "Agency Wake execution is not available in this Runtime",
                ));
            }
        };

        let binding = self.binding_for_world(snapshot.world_id()).await?;
        let assembly = self.execution_assembly(&snapshot, binding).await?;
        validate_work_target(&self.registry, &assembly, &work)?;

        // Compatibility and exact handler assembly are checked before claim.
        // A missing software implementation therefore cannot consume the
        // Work's technical attempt counter or create a lease.
        let claim = self
            .store
            .claim(target.timeline_id, work_id, now, claimed_until)
            .await
            .map_err(|error| map_work_error(&error))?;
        let session = match self
            .start_execution_session(assembly.clone(), ExecutionOrigin::Runtime)
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
        let base = snapshot.world_view();
        let mut dispatch_entropy_evidence =
            EntropyEvidence::new(assembly.entropy_source_id().clone());
        let (outcome, execution) = match dispatch_root_work(
            &base,
            &self.registry,
            &assembly,
            &*self.entropy_source,
            &mut dispatch_entropy_evidence,
            handler_id,
            &work.payload,
        ) {
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
                        Some(dispatch_entropy_evidence),
                    )
                    .await);
            }
        };

        let engine = EffectEngine::new(&self.registry).with_budget(assembly.execution_policy());
        let rejection = match &outcome {
            ResolveOutcome::Rejected(rejection) => Some(rejection.clone()),
            ResolveOutcome::Resolved(_) => None,
        };
        let validation = match &outcome {
            ResolveOutcome::Rejected(_) => engine.validate_segments_with_entropy(
                &base,
                &[],
                execution.call_provenance.clone(),
                execution.entropy_evidence.clone(),
            ),
            ResolveOutcome::Resolved(_) => engine.validate_segments_with_entropy(
                &base,
                &execution.segments,
                execution.call_provenance.clone(),
                execution.entropy_evidence.clone(),
            ),
        };
        let validated = match validation {
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
                        Some(execution.entropy_evidence.clone()),
                    )
                    .await);
            }
        };

        let changes_runtime_state = changes_runtime_state(&validated, Some(&claim));
        match self.store.commit(&validated, Some(&claim), now).await {
            Ok(result) => {
                let status = if rejection.is_some() {
                    ExecutionSessionStatus::Rejected
                } else {
                    ExecutionSessionStatus::Committed
                };
                self.finish_execution_session_with_entropy(
                    session.id(),
                    status,
                    validated.entropy_evidence().clone(),
                )
                .await?;
                match rejection {
                    Some(rejection) => Ok(ExecutionResult::rejected(rejection)),
                    None => Ok(execution_result(&result, changes_runtime_state)),
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
                        Some(validated.entropy_evidence().clone()),
                    )
                    .await)
            }
        }
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
        entropy_evidence: Option<EntropyEvidence>,
    ) -> ApiError
    where
        S: RuntimeControlStore,
    {
        let error = match entropy_evidence {
            Some(entropy_evidence) => match self
                .finish_execution_session_with_entropy(
                    session.id(),
                    ExecutionSessionStatus::Failed,
                    entropy_evidence,
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

    fn ensure_binding(
        &self,
        world_id: loom_core::WorldId,
        legacy_binding: WorldRuntimeBinding,
    ) -> PersistenceFuture<'_, Result<WorldRuntimeBinding, BindingError>> {
        (**self).ensure_binding(world_id, legacy_binding)
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

    fn read_session(
        &self,
        session_id: loom_core::ExecutionSessionId,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        (**self).read_session(session_id)
    }

    fn list_sessions(&self) -> PersistenceFuture<'_, Result<Vec<ExecutionSession>, SessionError>> {
        (**self).list_sessions()
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
                .start_execution_session(assembly.clone(), ExecutionOrigin::Runtime)
                .await?;
            let mut entropy_evidence = EntropyEvidence::new(assembly.entropy_source_id().clone());
            let plan = match self.validate_world_template(
                &request.template,
                world_id,
                timeline_id,
                &assembly,
                &mut entropy_evidence,
            ) {
                Ok(plan) => plan,
                Err(error) => {
                    self.finish_execution_session_with_entropy(
                        session.id(),
                        ExecutionSessionStatus::Failed,
                        entropy_evidence,
                    )
                    .await?;
                    return Err(error);
                }
            };
            let created = match self
                .store
                .create_world_with_bootstrap(
                    plan.world_id,
                    plan.timeline_id,
                    plan.initial_world_time,
                    plan.binding,
                    &plan.bootstrap,
                    self.platform_clock.now(),
                )
                .await
            {
                Ok(created) => created,
                Err(error) => {
                    self.finish_execution_session_with_entropy(
                        session.id(),
                        ExecutionSessionStatus::Failed,
                        entropy_evidence.clone(),
                    )
                    .await?;
                    return Err(map_lifecycle_error(&error));
                }
            };
            self.finish_execution_session_with_entropy(
                session.id(),
                ExecutionSessionStatus::Committed,
                entropy_evidence,
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

impl<S> ActionService for Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore,
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
                .start_execution_session(assembly.clone(), ExecutionOrigin::Application)
                .await?;
            let base = snapshot.world_view();
            let engine = EffectEngine::new(&self.registry).with_budget(assembly.execution_policy());
            if let Err(error) = engine
                .validate_action_input(&request.invocation.action, &request.invocation.input)
                .map_err(|error| map_action_input_error(&error))
            {
                self.finish_execution_session(session.id(), ExecutionSessionStatus::Failed)
                    .await?;
                return Err(error);
            }
            let mut dispatch_entropy_evidence =
                EntropyEvidence::new(assembly.entropy_source_id().clone());
            let (outcome, execution) = match dispatch_root_action(
                &base,
                &self.registry,
                &assembly,
                &*self.entropy_source,
                &mut dispatch_entropy_evidence,
                &request.invocation,
            ) {
                Ok(result) => result,
                Err(error) => {
                    let error = map_dispatch_error(error);
                    self.finish_execution_session_with_entropy(
                        session.id(),
                        ExecutionSessionStatus::Failed,
                        dispatch_entropy_evidence,
                    )
                    .await?;
                    return Err(error);
                }
            };
            let execution_entropy_evidence = execution.entropy_evidence.clone();
            match outcome {
                ResolveOutcome::Rejected(rejection) => {
                    self.finish_execution_session_with_entropy(
                        session.id(),
                        ExecutionSessionStatus::Rejected,
                        execution_entropy_evidence,
                    )
                    .await?;
                    Ok(ExecutionResult::rejected(rejection))
                }
                ResolveOutcome::Resolved(_) => {
                    let validated = match engine
                        .validate_segments_with_entropy(
                            &base,
                            &execution.segments,
                            execution.call_provenance,
                            execution.entropy_evidence,
                        )
                        .map_err(|error| map_runtime_error(&error))
                    {
                        Ok(validated) => validated,
                        Err(error) => {
                            self.finish_execution_session_with_entropy(
                                session.id(),
                                ExecutionSessionStatus::Failed,
                                execution_entropy_evidence.clone(),
                            )
                            .await?;
                            return Err(error);
                        }
                    };
                    let result = match self
                        .store
                        .commit(&validated, None, self.platform_clock.now())
                        .await
                        .map_err(|error| map_commit_error(&error))
                    {
                        Ok(result) => result,
                        Err(error) => {
                            self.finish_execution_session_with_entropy(
                                session.id(),
                                ExecutionSessionStatus::Failed,
                                validated.entropy_evidence().clone(),
                            )
                            .await?;
                            return Err(error);
                        }
                    };
                    self.finish_execution_session_with_entropy(
                        session.id(),
                        ExecutionSessionStatus::Committed,
                        validated.entropy_evidence().clone(),
                    )
                    .await?;
                    Ok(execution_result(
                        &result,
                        changes_runtime_state(&validated, None),
                    ))
                }
            }
        })
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
            Ok(ApiTimelineSnapshot::new(
                target,
                snapshot.version(),
                snapshot.world_time(),
            ))
        })
    }
}

impl<S> QueryService for Runtime<S>
where
    S: WorldStore
        + WorldRuntimeBindingStore
        + CommitStore
        + WorkStore
        + RuntimeRevisionStore
        + ExecutionSessionStore,
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
            let limit = query.limit.map_or(usize::MAX, |limit| {
                usize::try_from(limit).unwrap_or(usize::MAX)
            });
            Ok(snapshot
                .events
                .iter()
                .filter(|event| query.after.is_none_or(|after| event.event_seq > after))
                .take(limit)
                .map(api_event)
                .collect())
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
        let capabilities = self
            .registry
            .capabilities()
            .map(|manifest| loom_api::CapabilityDescriptor {
                id: manifest.id.as_str().into(),
                version: manifest.version.to_string(),
                description: manifest.description.clone(),
                dependencies: manifest
                    .dependencies
                    .iter()
                    .map(|dependency| dependency.id.as_str().into())
                    .collect(),
            })
            .collect();
        let actions = self
            .registry
            .actions()
            .map(|action| ActionDescriptor {
                id: action.definition.id.clone(),
                owner: action.owner.as_str().into(),
                schema_revision: action.definition.schema_revision,
                description: action.definition.description.clone(),
                input_schema: action.definition.input_schema.clone(),
            })
            .collect();
        Ok(CatalogSnapshot {
            capabilities,
            actions,
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
    failure: Option<String>,
}

impl ExecutionState {
    fn new(budget: ResolutionBudget, entropy_source_id: EntropySourceId) -> Self {
        Self {
            budget,
            usage: BudgetUsage::default(),
            stack: Vec::new(),
            segments: Vec::new(),
            call_provenance: CallProvenance::default(),
            entropy_evidence: EntropyEvidence::new(entropy_source_id),
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
}

fn dispatch_root_action(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    entropy_source: &dyn EntropySource,
    entropy_evidence: &mut EntropyEvidence,
    invocation: &ActionInvocation,
) -> Result<(ResolveOutcome, ExecutionState), DispatchError> {
    let action = enabled_action(registry, assembly, &invocation.action)?;
    let frame = CallFrame {
        owner: action.owner.clone(),
        action: invocation.action.clone(),
    };
    let state = Rc::new(RefCell::new(ExecutionState::new(
        assembly.execution_policy(),
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
    Ok((outcome?, execution))
}

fn dispatch_root_work(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    entropy_source: &dyn EntropySource,
    entropy_evidence: &mut EntropyEvidence,
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
        assembly.execution_policy(),
        assembly.entropy_source_id().clone(),
    )));
    state
        .borrow_mut()
        .enter_root(frame.clone())
        .map_err(internal_dispatch_error)?;
    let outcome = dispatch_work_frame(
        base,
        registry,
        assembly,
        entropy_source,
        &state,
        &frame,
        handler_id,
        payload,
    );
    let execution = state.borrow().clone();
    *entropy_evidence = execution.entropy_evidence.clone();
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
        };
        registry.resolve_action(&invocation.action, &context, &invocation.input)
    };
    capture_outcome(state, &frame.owner, result)
}

#[allow(clippy::too_many_arguments)]
fn dispatch_work_frame(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    entropy_source: &dyn EntropySource,
    state: &Rc<RefCell<ExecutionState>>,
    frame: &CallFrame,
    handler_id: &loom_core::WorkHandlerId,
    payload: &serde_json::Value,
) -> Result<ResolveOutcome, DispatchError> {
    let result = {
        let context = RuntimeResolutionContext {
            base,
            registry,
            assembly,
            entropy_source,
            state: Rc::clone(state),
            frame: frame.clone(),
        };
        registry.handle_work(handler_id, &context, payload)
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

/// Returns the repository-owned compatibility descriptor used while migrating
/// M3 Worlds that predate World Runtime Binding.
///
/// This is deliberately a checked-in fixture rather than a projection of the
/// process-local registry. The registry describes installed software; using it
/// here would make the first Runtime process silently decide a World's
/// permanent semantic enablement. M4-T3 replaces this interim birth baseline
/// with the validated Template binding path.
fn legacy_binding() -> WorldRuntimeBinding {
    const M3_COMPATIBILITY_CAPABILITIES: &[&str] = &[
        "bootstrap.basic",
        "composition.child",
        "composition.leaf",
        "composition.root",
        "counter",
        "counter.basic",
        "counting",
        "postgres.commit.test",
        "postgres.restart_resume",
        "postgres.vertical.counter",
        "postgres.work.test",
        "provenance.child",
        "provenance.parent",
        "test",
        "test.no_change",
    ];

    WorldRuntimeBinding::new(
        M3_COMPATIBILITY_CAPABILITIES.iter().map(|capability_id| {
            (
                CapabilityId::from(*capability_id),
                VersionReq::parse("^0.1.0")
                    .expect("the checked-in M3 baseline requirement should parse"),
            )
        }),
        json!({"baseline": "m3-compatibility-baseline-v1"}),
        1,
        Some("m3-compatibility-baseline-v1".to_owned()),
    )
}

fn map_runtime_revision_error(error: &RuntimeRevisionError) -> ApiError {
    match error {
        RuntimeRevisionError::RevisionNotFound { .. }
        | RuntimeRevisionError::RevisionDescriptorMismatch { .. }
        | RuntimeRevisionError::RevisionAlreadyExists { .. }
        | RuntimeRevisionError::ActiveRevisionConflict { .. }
        | RuntimeRevisionError::ActivationGenerationOverflow
        | RuntimeRevisionError::StorageUnavailable { .. } => {
            ApiError::unavailable("Runtime Revision selection is unavailable")
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
        | SessionError::StorageUnavailable { .. } => {
            ApiError::unavailable("Execution Session provenance is unavailable")
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
        ReadError::StorageUnavailable { .. } => {
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
        CommitError::TimelineMismatch { .. } => {
            ApiError::invalid_request("Commit target does not match the pinned Timeline")
        }
        CommitError::Work(_) => ApiError::conflict("Work state changed before commit"),
        CommitError::StorageUnavailable { .. } => {
            ApiError::unavailable("Persistence authority is temporarily unavailable")
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
    };
    use loom_core::{
        ActionTypeId, EventSeq, StateRevision, TimelineId, TimelineVersion, WorldId, WorldInstant,
    };
    use loom_protocol::{ActionInvocation, Rejection, ResolveOutcome};
    use semver::Version;
    use serde_json::{Value, json};

    use crate::{BaseWorldSnapshot, BaseWorldView, DeterministicEntropySource};

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

    fn base() -> BaseWorldView {
        BaseWorldView::new(BaseWorldSnapshot::new(
            id::<WorldId>(1),
            id::<TimelineId>(2),
            TimelineVersion::new(EventSeq::new(0), StateRevision::new(0)),
            WorldInstant::new(0),
        ))
    }

    fn test_assembly(
        registry: &CapabilityRegistry,
        binding: WorldRuntimeBinding,
    ) -> ExecutionAssembly {
        test_assembly_with_budget(registry, binding, ResolutionBudget::unlimited())
    }

    fn test_assembly_with_budget(
        registry: &CapabilityRegistry,
        binding: WorldRuntimeBinding,
        execution_policy: ResolutionBudget,
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
        let (outcome, execution) = dispatch_root_action(
            &base(),
            &registry,
            &assembly,
            &source,
            &mut entropy_evidence,
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
    fn entropy_is_ordered_and_retained_in_session_provenance() {
        let registry = entropy_registry();
        let assembly = test_assembly(&registry, entropy_binding());
        let source =
            DeterministicEntropySource::with_source_id("test-entropy", vec![vec![1, 2], vec![3]]);
        let invocation = ActionInvocation::new(ActionTypeId::from("entropy.sample"), json!({}));
        let mut entropy_evidence = EntropyEvidence::new(assembly.entropy_source_id().clone());
        let (outcome, execution) = dispatch_root_action(
            &base(),
            &registry,
            &assembly,
            &source,
            &mut entropy_evidence,
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
            ResolutionBudget::unlimited().with_max_entropy_requests(1),
        );
        let source =
            DeterministicEntropySource::with_source_id("test-entropy", vec![vec![1, 2], vec![3]]);
        let invocation = ActionInvocation::new(ActionTypeId::from("entropy.sample"), json!({}));
        let mut entropy_evidence = EntropyEvidence::new(assembly.entropy_source_id().clone());
        let error = dispatch_root_action(
            &base(),
            &registry,
            &assembly,
            &source,
            &mut entropy_evidence,
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
            ResolutionBudget::unlimited().with_max_entropy_bytes(2),
        );
        let total_bytes_source =
            DeterministicEntropySource::with_source_id("test-entropy", vec![vec![1, 2], vec![3]]);
        let mut total_bytes_evidence =
            EntropyEvidence::new(total_bytes_assembly.entropy_source_id().clone());
        let total_bytes_error = dispatch_root_action(
            &base(),
            &registry,
            &total_bytes_assembly,
            &total_bytes_source,
            &mut total_bytes_evidence,
            &invocation,
        )
        .expect_err("total entropy bytes should reject the second request");
        assert_eq!(total_bytes_source.calls(), 1);
        assert!(total_bytes_error.to_string().contains("entropy_bytes"));

        let request_bytes_assembly = test_assembly_with_budget(
            &registry,
            entropy_binding(),
            ResolutionBudget::unlimited().with_max_entropy_request_bytes(1),
        );
        let request_bytes_source =
            DeterministicEntropySource::with_source_id("test-entropy", vec![vec![1, 2], vec![3]]);
        let mut request_bytes_evidence =
            EntropyEvidence::new(request_bytes_assembly.entropy_source_id().clone());
        let request_bytes_error = dispatch_root_action(
            &base(),
            &registry,
            &request_bytes_assembly,
            &request_bytes_source,
            &mut request_bytes_evidence,
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

    #[test]
    fn m3_compatibility_baseline_is_stable_across_runtime_registries() {
        let first = legacy_binding();
        let second = legacy_binding();

        assert_eq!(first, second);
        assert_eq!(
            first.template_provenance(),
            Some("m3-compatibility-baseline-v1")
        );
        assert_eq!(
            first.requirement(&CapabilityId::from("not-in-the-baseline")),
            None
        );
    }
}
