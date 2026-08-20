//! Runtime orchestration over the unified API, Capability registry and ports.
//!
//! This module owns the composition that turns one public Action or Durable
//! Work execution into the existing Runtime validation and persistence path.
//! It does not define a second protocol, storage boundary or public endpoint.

use loom_api::{
    ActionDescriptor, ActionRequest, ActionService, ApiError, ApiResult, CatalogService,
    CatalogSnapshot, CommittedEvent as ApiCommittedEvent, EventQuery, ExecutionResult, FacetQuery,
    FacetSnapshot as ApiFacetSnapshot, HistoryService, QueryService, TimelineService,
    TimelineSnapshot as ApiTimelineSnapshot, TimelineTarget,
};
use loom_capability::{
    CapabilityRegistry, DispatchError, ResolutionContext, ResolutionContextError,
};
use loom_core::{TimelineId, WorkId};
use loom_protocol::{ActionInvocation, Resolution, ResolveOutcome};

use crate::{
    CommitError, CommitStore, CommittedEvent, EffectEngine, PlatformTime, ReadError, RuntimeError,
    TimelineSnapshot, ValidationOutcome, WorkClaim, WorkError, WorkRecord, WorkStore, WorldStore,
};

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
    platform_time: PlatformTime,
}

impl<S> Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
{
    /// Creates a Runtime after validating the assembled Capability registry.
    ///
    /// `platform_time` defaults to zero for API Action commits because the
    /// public v0 Action contract does not carry an operational clock. Callers
    /// that schedule Work can choose a different default with
    /// [`Self::with_platform_time`]; World semantic time always comes from the
    /// pinned Timeline snapshot and is never derived from this value.
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
            platform_time: PlatformTime::default(),
        })
    }

    /// Sets the operational platform time used by public Action commits.
    ///
    /// This value affects only adapter metadata such as newly scheduled
    /// Work's retry availability. It does not advance World Time or enter a
    /// committed Event. Explicit Work execution methods receive their own
    /// platform-time arguments so lease and retry boundaries remain visible.
    #[must_use]
    pub fn with_platform_time(mut self, platform_time: PlatformTime) -> Self {
        self.platform_time = platform_time;
        self
    }

    /// Executes one claimed Durable Work obligation through the same
    /// Resolution → validation → authority commit path as a public Action.
    ///
    /// The Work is claimed before resolution and is completed atomically with
    /// the resulting Events, Effects and Work mutations. A handler/runtime/
    /// commit failure releases the lease through the existing technical retry
    /// port at `retry_available_at`; that bookkeeping changes no World Truth.
    /// A semantic `Rejected` outcome completes the current Work with an empty
    /// validated Resolution and returns the public rejection unchanged.
    ///
    /// # Errors
    ///
    /// Returns a public service error for missing/stale Work, resolver or
    /// Runtime validation failure, or an unsuccessful atomic commit. The
    /// current Work remains Pending after a technical failure when retry
    /// bookkeeping succeeds.
    pub fn execute_work(
        &self,
        target: TimelineTarget,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
        retry_available_at: PlatformTime,
    ) -> ApiResult<ExecutionResult> {
        let snapshot = self.snapshot_for_target(target)?;
        let work = snapshot
            .works
            .iter()
            .find(|work| work.id == work_id)
            .ok_or_else(|| ApiError::not_found(format!("Work {work_id} was not found")))?;
        if work
            .due_world_time
            .is_some_and(|due| due > snapshot.world_time())
        {
            return Err(ApiError::unavailable("Work is not due in World Time"));
        }

        let claim = self
            .store
            .claim(target.timeline_id, work_id, now, claimed_until)
            .map_err(|error| map_work_error(&error))?;
        let snapshot = match self.snapshot_for_target(target) {
            Ok(snapshot) => snapshot,
            Err(error) => {
                return Err(self.retry_after_failure(&claim, now, retry_available_at, error));
            }
        };
        let base = snapshot.world_view();
        let Some(handler) = self.registry.work_handler(&work.handler) else {
            let error = ApiError::internal("registered Work handler was not found");
            return Err(self.retry_after_failure(&claim, now, retry_available_at, error));
        };
        let owner = handler.owner.as_str().to_owned();
        let context = RuntimeResolutionContext {
            base: &base,
            registry: &self.registry,
        };
        let outcome = match self
            .registry
            .handle_work(&work.handler, &context, &work.payload)
        {
            Ok(outcome) => outcome,
            Err(error) => {
                let error = map_dispatch_error(error);
                return Err(self.retry_after_failure(&claim, now, retry_available_at, error));
            }
        };

        let engine = EffectEngine::new(&self.registry);
        let validation = match engine.validate_outcome(&base, &owner, outcome) {
            Ok(validation) => validation,
            Err(error) => {
                let error = map_runtime_error(&error);
                return Err(self.retry_after_failure(&claim, now, retry_available_at, error));
            }
        };

        match validation {
            ValidationOutcome::Rejected(rejection) => {
                let empty = match engine.validate(&base, &owner, Resolution::default()) {
                    Ok(empty) => empty,
                    Err(error) => {
                        let error = map_runtime_error(&error);
                        return Err(self.retry_after_failure(
                            &claim,
                            now,
                            retry_available_at,
                            error,
                        ));
                    }
                };
                match self.store.commit(&empty, Some(&claim), now) {
                    Ok(_) => Ok(ExecutionResult::rejected(rejection)),
                    Err(error) => {
                        let error = map_commit_error(&error);
                        Err(self.retry_after_failure(&claim, now, retry_available_at, error))
                    }
                }
            }
            ValidationOutcome::Validated(validated) => {
                match self.store.commit(&validated, Some(&claim), now) {
                    Ok(result) => Ok(execution_result(&result)),
                    Err(error) => {
                        let error = map_commit_error(&error);
                        Err(self.retry_after_failure(&claim, now, retry_available_at, error))
                    }
                }
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
    pub fn retry_work(
        &self,
        claim: &WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> Result<WorkRecord, WorkError> {
        self.store.retry(claim, now, available_at, last_error)
    }

    fn snapshot_for_target(&self, target: TimelineTarget) -> ApiResult<TimelineSnapshot> {
        let snapshot = self
            .store
            .snapshot(target.timeline_id)
            .map_err(|error| map_read_error(&error))?;
        if snapshot.world_id() != target.world_id {
            return Err(ApiError::not_found(format!(
                "Timeline {} is not in World {}",
                target.timeline_id, target.world_id
            )));
        }
        Ok(snapshot)
    }

    fn retry_after_failure(
        &self,
        claim: &WorkClaim,
        now: PlatformTime,
        retry_available_at: PlatformTime,
        error: ApiError,
    ) -> ApiError {
        if self
            .store
            .retry(claim, now, retry_available_at, Some(error.message.clone()))
            .is_err()
        {
            return ApiError::internal("Work failure could not be recorded for retry");
        }
        error
    }
}

impl<T> WorldStore for &T
where
    T: WorldStore + ?Sized,
{
    fn snapshot(&self, timeline_id: TimelineId) -> Result<TimelineSnapshot, ReadError> {
        (**self).snapshot(timeline_id)
    }
}

impl<T> CommitStore for &T
where
    T: CommitStore + ?Sized,
{
    fn commit(
        &self,
        resolution: &crate::ValidatedResolution,
        current_work: Option<&WorkClaim>,
        now: PlatformTime,
    ) -> Result<crate::CommitResult, CommitError> {
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
    ) -> Result<WorkClaim, WorkError> {
        (**self).claim(timeline_id, work_id, now, claimed_until)
    }

    fn retry(
        &self,
        claim: &WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> Result<WorkRecord, WorkError> {
        (**self).retry(claim, now, available_at, last_error)
    }

    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
    ) -> Result<Option<WorkRecord>, ReadError> {
        (**self).work(timeline_id, work_id)
    }
}

impl<S> ActionService for Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
{
    fn invoke(&self, request: ActionRequest) -> ApiResult<ExecutionResult> {
        let snapshot = self.snapshot_for_target(request.target)?;
        let base = snapshot.world_view();
        let owner = self
            .registry
            .action(&request.invocation.action)
            .map(|action| action.owner.as_str().to_owned())
            .ok_or_else(|| {
                ApiError::not_found(format!(
                    "Action {} was not registered",
                    request.invocation.action
                ))
            })?;
        let context = RuntimeResolutionContext {
            base: &base,
            registry: &self.registry,
        };
        let outcome = self
            .registry
            .resolve_action(
                &request.invocation.action,
                &context,
                &request.invocation.input,
            )
            .map_err(map_dispatch_error)?;
        let validation = EffectEngine::new(&self.registry)
            .validate_outcome(&base, &owner, outcome)
            .map_err(|error| map_runtime_error(&error))?;
        match validation {
            ValidationOutcome::Rejected(rejection) => Ok(ExecutionResult::rejected(rejection)),
            ValidationOutcome::Validated(validated) => self
                .store
                .commit(&validated, None, self.platform_time)
                .map(|result| execution_result(&result))
                .map_err(|error| map_commit_error(&error)),
        }
    }
}

impl<S> TimelineService for Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
{
    fn inspect_timeline(&self, target: TimelineTarget) -> ApiResult<ApiTimelineSnapshot> {
        let snapshot = self.snapshot_for_target(target)?;
        Ok(ApiTimelineSnapshot::new(
            target,
            snapshot.version(),
            snapshot.world_time(),
        ))
    }
}

impl<S> QueryService for Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
{
    fn get_facet(&self, query: FacetQuery) -> ApiResult<Option<ApiFacetSnapshot>> {
        let snapshot = self.snapshot_for_target(query.target)?;
        let view = snapshot.world_view();
        Ok(view.facet(query.owner, &query.facet_type).map(|facet| {
            ApiFacetSnapshot::new(
                facet.owner(),
                facet.facet_type().clone(),
                facet.schema_revision(),
                facet.value().clone(),
            )
        }))
    }
}

impl<S> HistoryService for Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
{
    fn list_events(&self, query: EventQuery) -> ApiResult<Vec<ApiCommittedEvent>> {
        let snapshot = self.snapshot_for_target(query.target)?;
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
    }
}

impl<S> CatalogService for Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
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

struct RuntimeResolutionContext<'a> {
    base: &'a crate::BaseWorldView,
    registry: &'a CapabilityRegistry,
}

impl ResolutionContext for RuntimeResolutionContext<'_> {
    fn base_world(&self) -> &dyn loom_capability::BaseWorldView {
        self.base
    }

    fn subresolve(
        &self,
        invocation: &ActionInvocation,
    ) -> Result<ResolveOutcome, ResolutionContextError> {
        self.registry
            .resolve_action(&invocation.action, self, &invocation.input)
            .map_err(|error| ResolutionContextError::new(error.to_string()))
    }
}

fn execution_result(result: &crate::CommitResult) -> ExecutionResult {
    if result.events.is_empty() {
        ExecutionResult::no_change()
    } else {
        ExecutionResult::committed(
            result.events.iter().map(|event| event.id).collect(),
            result.version,
        )
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

fn map_read_error(error: &ReadError) -> ApiError {
    match error {
        ReadError::TimelineNotFound { timeline_id } => {
            ApiError::not_found(format!("Timeline {timeline_id} was not found"))
        }
    }
}

fn map_dispatch_error(error: DispatchError) -> ApiError {
    match error {
        DispatchError::UnknownAction(action) => {
            ApiError::not_found(format!("Action {action} was not registered"))
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
        WorkError::InvalidLease { .. } | WorkError::TimelineMismatch { .. } => {
            ApiError::invalid_request("Work claim has invalid timing or Timeline scope")
        }
        WorkError::AttemptOverflow { .. }
        | WorkError::DuplicateWork { .. }
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
        CommitError::DuplicateEvent { .. }
        | CommitError::InvalidEvent { .. }
        | CommitError::InvalidEffect { .. }
        | CommitError::RevisionOverflow => ApiError::internal("Timeline commit failed validation"),
    }
}
