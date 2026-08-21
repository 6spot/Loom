//! Runtime orchestration over the unified API, Capability registry and ports.
//!
//! This module owns the composition that turns one public Action or Durable
//! Work execution into the existing Runtime validation and persistence path.
//! It does not define a second protocol, storage boundary or public endpoint.

use std::{cell::RefCell, rc::Rc, sync::Arc};

use loom_api::{
    ActionDescriptor, ActionRequest, ActionService, ApiError, ApiResult, CatalogService,
    CatalogSnapshot, CommittedEvent as ApiCommittedEvent, EventQuery, ExecutionResult, FacetQuery,
    FacetSnapshot as ApiFacetSnapshot, HistoryService, QueryService, TimelineService,
    TimelineSnapshot as ApiTimelineSnapshot, TimelineTarget,
};
use loom_capability::{
    CapabilityId, CapabilityRegistry, DispatchError, ResolutionContext, ResolutionContextError,
    ResolverError,
};
use loom_core::{ActionTypeId, TimelineId, WorkId};
use loom_protocol::{ActionInvocation, Resolution, ResolveOutcome};

use crate::{
    BudgetUsage, CallProvenance, CommitError, CommitStore, CommittedEvent, EffectEngine,
    ManualPlatformClock, PlatformClock, PlatformTime, ReadError, ResolutionBudget, RuntimeError,
    TimelineSnapshot, ValidatedResolution, ValidationError, WorkClaim, WorkError, WorkRecord,
    WorkStore, WorldStore,
};

use super::validation::ResolutionSegment;

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
    resolution_budget: ResolutionBudget,
}

impl<S> Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
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
            resolution_budget: ResolutionBudget::unlimited(),
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
        let (outcome, execution) = match dispatch_root_work(
            &base,
            &self.registry,
            self.resolution_budget,
            &work.handler,
            &work.payload,
        ) {
            Ok(execution) => execution,
            Err(error) => {
                let error = map_dispatch_error(error);
                return Err(self.retry_after_failure(&claim, now, retry_available_at, error));
            }
        };

        let engine = EffectEngine::new(&self.registry).with_budget(self.resolution_budget);
        let rejection = match &outcome {
            ResolveOutcome::Rejected(rejection) => Some(rejection.clone()),
            ResolveOutcome::Resolved(_) => None,
        };
        let validation = match &outcome {
            ResolveOutcome::Rejected(_) => {
                engine.validate_segments(&base, &[], execution.call_provenance.clone())
            }
            ResolveOutcome::Resolved(_) => engine.validate_segments(
                &base,
                &execution.segments,
                execution.call_provenance.clone(),
            ),
        };
        let validated = match validation {
            Ok(validated) => validated,
            Err(error) => {
                let error = map_runtime_error(&error);
                return Err(self.retry_after_failure(&claim, now, retry_available_at, error));
            }
        };

        let changes_runtime_state = changes_runtime_state(&validated, Some(&claim));
        match self.store.commit(&validated, Some(&claim), now) {
            Ok(result) => match rejection {
                Some(rejection) => Ok(ExecutionResult::rejected(rejection)),
                None => Ok(execution_result(&result, changes_runtime_state)),
            },
            Err(error) => {
                let error = map_commit_error(&error);
                Err(self.retry_after_failure(&claim, now, retry_available_at, error))
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
        if self.registry.action(&request.invocation.action).is_none() {
            return Err(ApiError::not_found(format!(
                "Action {} was not registered",
                request.invocation.action
            )));
        }
        let engine = EffectEngine::new(&self.registry).with_budget(self.resolution_budget);
        engine
            .validate_action_input(&request.invocation.action, &request.invocation.input)
            .map_err(|error| map_action_input_error(&error))?;
        let (outcome, execution) = dispatch_root_action(
            &base,
            &self.registry,
            self.resolution_budget,
            &request.invocation,
        )
        .map_err(map_dispatch_error)?;
        match outcome {
            ResolveOutcome::Rejected(rejection) => Ok(ExecutionResult::rejected(rejection)),
            ResolveOutcome::Resolved(_) => {
                let validated = engine
                    .validate_segments(&base, &execution.segments, execution.call_provenance)
                    .map_err(|error| map_runtime_error(&error))?;
                self.store
                    .commit(&validated, None, self.platform_clock.now())
                    .map(|result| {
                        execution_result(&result, changes_runtime_state(&validated, None))
                    })
                    .map_err(|error| map_commit_error(&error))
            }
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
    failure: Option<String>,
}

impl ExecutionState {
    fn new(budget: ResolutionBudget) -> Self {
        Self {
            budget,
            usage: BudgetUsage::default(),
            stack: Vec::new(),
            segments: Vec::new(),
            call_provenance: CallProvenance::default(),
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
}

struct RuntimeResolutionContext<'a> {
    base: &'a crate::BaseWorldView,
    registry: &'a CapabilityRegistry,
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
}

fn dispatch_root_action(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    budget: ResolutionBudget,
    invocation: &ActionInvocation,
) -> Result<(ResolveOutcome, ExecutionState), DispatchError> {
    let action = registry
        .action(&invocation.action)
        .ok_or_else(|| DispatchError::UnknownAction(invocation.action.clone()))?;
    let frame = CallFrame {
        owner: action.owner.clone(),
        action: invocation.action.clone(),
    };
    let state = Rc::new(RefCell::new(ExecutionState::new(budget)));
    state
        .borrow_mut()
        .enter_root(frame.clone())
        .map_err(internal_dispatch_error)?;
    let outcome = dispatch_action_frame(base, registry, &state, &frame, invocation)?;
    Ok((outcome, state.borrow().clone()))
}

fn dispatch_root_work(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    budget: ResolutionBudget,
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
    let state = Rc::new(RefCell::new(ExecutionState::new(budget)));
    state
        .borrow_mut()
        .enter_root(frame.clone())
        .map_err(internal_dispatch_error)?;
    let outcome = dispatch_work_frame(base, registry, &state, &frame, handler_id, payload)?;
    Ok((outcome, state.borrow().clone()))
}

fn dispatch_action_frame(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    state: &Rc<RefCell<ExecutionState>>,
    frame: &CallFrame,
    invocation: &ActionInvocation,
) -> Result<ResolveOutcome, DispatchError> {
    let result = {
        let context = RuntimeResolutionContext {
            base,
            registry,
            state: Rc::clone(state),
            frame: frame.clone(),
        };
        registry.resolve_action(&invocation.action, &context, &invocation.input)
    };
    capture_outcome(state, &frame.owner, result)
}

fn dispatch_work_frame(
    base: &crate::BaseWorldView,
    registry: &CapabilityRegistry,
    state: &Rc<RefCell<ExecutionState>>,
    frame: &CallFrame,
    handler_id: &loom_core::WorkHandlerId,
    payload: &serde_json::Value,
) -> Result<ResolveOutcome, DispatchError> {
    let result = {
        let context = RuntimeResolutionContext {
            base,
            registry,
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
    state: &Rc<RefCell<ExecutionState>>,
    caller: &CallFrame,
    invocation: &ActionInvocation,
) -> Result<ResolveOutcome, DispatchError> {
    EffectEngine::new(registry)
        .validate_action_input(&invocation.action, &invocation.input)
        .map_err(|error| {
            let message = format!("child Action input rejected: {error}");
            state.borrow_mut().record_failure(message.clone());
            internal_dispatch_error(message)
        })?;

    let action = registry
        .action(&invocation.action)
        .ok_or_else(|| DispatchError::UnknownAction(invocation.action.clone()))?;
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
    let result = dispatch_action_frame(base, registry, state, &target, invocation);
    state.borrow_mut().leave(&target);
    result
}

fn internal_dispatch_error(message: impl Into<String>) -> DispatchError {
    DispatchError::Resolver(ResolverError::new(message))
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

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use loom_capability::{
        ActionDefinition, ActionResolver, Capability, CapabilityDependency, CapabilityManifest,
        CapabilityRegistrar, RegistrationError, ResolverError,
    };
    use loom_core::{
        ActionTypeId, EventSeq, StateRevision, TimelineId, TimelineVersion, WorldId, WorldInstant,
    };
    use loom_protocol::{ActionInvocation, Rejection, ResolveOutcome};
    use serde_json::{Value, json};

    use crate::{BaseWorldSnapshot, BaseWorldView};

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

    #[test]
    fn runtime_call_edge_is_observable_separately_from_world_causality() {
        let registry = registry();
        let invocation = ActionInvocation::new(ActionTypeId::from("provenance.parent"), json!({}));
        let (outcome, execution) = dispatch_root_action(
            &base(),
            &registry,
            ResolutionBudget::unlimited(),
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
}
