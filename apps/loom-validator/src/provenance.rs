//! Session/Revision/Provenance validation (T16).
//!
//! The scenarios in this module are public-consumer checks. Runtime Revision
//! publication and application-boundary restart are supplied by the dedicated
//! integration harness; this production module only consumes `loom-api` via
//! `BackendContext`. Central registry integration remains owned by T19.

#![allow(clippy::too_many_lines)]

use std::future::Future;

use loom_api::{
    ActionInvocation, ActionTypeId, AdminActivateRuntimeRevisionRequest,
    AdminExecutionSessionRequest, AdminReadDependency, AdminRuntimeRevisionRequest, AdminService,
    CreateWorldFromTemplateRequest, EntityId, EventId, EventQuery, EventRef, ExecutionResult,
    FacetOwner, HistoryService, TimelineTarget, WorldInstant, WorldTemplateDescriptor,
};
use serde_json::json;
use uuid::Uuid;

use crate::backend::BackendContext;
use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::reports::ScenarioResult;
use crate::scenario::{BackendKind, ScenarioDescriptor};

pub const SUITE: &str = "provenance";
pub const CV_RANGE: &str = "CV-031..CV-033";
pub const CAPABILITY_AREA: &str = "provenance";
pub const CV_031: &str = "CV-031";
pub const CV_032: &str = "CV-032";
pub const CV_033: &str = "CV-033";

const COUNTER_SEED: &str = "neutral.counter.seed";
const COUNTER_INCREMENT: &str = "neutral.counter.increment";
const COUNTER_CAPABILITY: &str = "neutral.counter";
const PROVENANCE_CAPABILITY: &str = "validator.t16.provenance";
const PROVENANCE_FACET: &str = "validator.t16.provenance.value";
const PROVENANCE_SEED: &str = "validator.t16.provenance.seed";
const PROVENANCE_ROOT: &str = "validator.t16.provenance.root";
const R2_ID: &str = "validator-t16-r2";
const PROVENANCE_R2_ID: &str = "validator-t16-cv033-r2";

#[must_use]
pub const fn suite_name() -> &'static str {
    SUITE
}

#[must_use]
pub fn owns_cv(cv_id: &str) -> bool {
    matches!(cv_id, CV_031 | CV_032 | CV_033)
}

/// Returns the deterministic public-consumer descriptors for T16.
#[must_use]
pub fn descriptors() -> Vec<ScenarioDescriptor> {
    let references = || {
        vec![
            "docs/architecture/world-runtime.md".to_owned(),
            "docs/architecture/runtime-contracts.md".to_owned(),
            "docs/architecture/evolution.md".to_owned(),
            "docs/tasks/validator-recert/stage-2/t08-coverage-matrix.md".to_owned(),
        ]
    };
    vec![
        ScenarioDescriptor::new(
            CV_031,
            "Event to Session to Revision provenance survives compatible activation and restart",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "Session S1 commits E1 under R1; public History/Admin reads retain S1 and R1 after R2 activation and controlled boundary restart",
            vec!["#321".to_owned(), "VALR-T16".to_owned()],
            references(),
        ),
        ScenarioDescriptor::new(
            CV_032,
            "new Session after compatible revision activation uses R2 without rewriting R1 history",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "R2 activation precedes a new Session S2; public Event-to-Session and Session revision projections distinguish E1/R1 from E2/R2 across controlled restart",
            vec!["#321".to_owned(), "VALR-T16".to_owned()],
            references(),
        ),
        ScenarioDescriptor::new(
            CV_033,
            "committed Session retains implementation, read, call and entropy provenance",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "public Admin Session projection retains non-secret implementation identity, ReadSet, Runtime-mediated call edges and controlled entropy observations after compatible activation and restart",
            vec!["#321".to_owned(), "VALR-T16".to_owned()],
            references(),
        ),
    ]
}

/// Executes one T16 scenario through formal/public Loom services.
#[must_use]
pub fn execute(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    if !descriptor.supported_backends().contains(ctx.backend_kind()) {
        return unavailable(descriptor, ctx, "backend is not declared by the T16 matrix");
    }
    if !ctx.can_perform_boundary_restart() {
        return unavailable(
            descriptor,
            ctx,
            "T16 requires ControlledBoundaryRestart; reconnect-only cannot prove durable provenance",
        );
    }
    if ctx.backend_kind().is_postgres()
        && let Err(error) = block_on(async { ctx.api().catalog() })
    {
        return unavailable(
            descriptor,
            ctx,
            format!(
                "PostgreSQL live backend is unavailable: {} ({})",
                error.code, error.message
            ),
        );
    }

    match descriptor.id_str() {
        CV_031 => cv031(descriptor, ctx),
        CV_032 => cv032(descriptor, ctx),
        CV_033 => cv033(descriptor, ctx),
        _ => result_fail(
            descriptor,
            ctx,
            "known T16 scenario",
            "unknown provenance scenario",
        ),
    }
}

fn block_on<F: Future>(future: F) -> F::Output {
    if let Ok(handle) = tokio::runtime::Handle::try_current() {
        tokio::task::block_in_place(|| handle.block_on(future))
    } else {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("validator tokio runtime should build")
            .block_on(future)
    }
}

fn new_id<T>() -> T
where
    T: From<Uuid>,
{
    T::from(Uuid::new_v4())
}

fn template() -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new("validator.t16.provenance.v1", 1, WorldInstant::new(42))
        .requires_capability(COUNTER_CAPABILITY, "^0.1.0")
}

fn provenance_template() -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new("validator.t16.provenance.v1", 1, WorldInstant::new(42))
        .requires_capability(PROVENANCE_CAPABILITY, "^0.1.0")
}

fn invoke(
    ctx: &BackendContext,
    target: TimelineTarget,
    action: &str,
    input: serde_json::Value,
) -> Result<Vec<EventId>, String> {
    match block_on(async {
        ctx.api()
            .invoke_on(
                target.world_id,
                target.timeline_id,
                ActionInvocation::new(ActionTypeId::from(action), input),
            )
            .await
    }) {
        Ok(ExecutionResult::Committed { event_ids, .. }) if !event_ids.is_empty() => Ok(event_ids),
        Ok(other) => Err(format!(
            "expected committed Event from {action}, got {other:?}"
        )),
        Err(error) => Err(format!(
            "{action} failed: {} ({})",
            error.code, error.message
        )),
    }
}

fn create_seed(ctx: &BackendContext) -> Result<(TimelineTarget, EntityId, EventRef), String> {
    let entity_id = new_id::<EntityId>();
    let event_id = new_id::<EventId>();
    let target = block_on(async {
        ctx.api()
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template()))
            .await
    })
    .map_err(|error| format!("World creation failed: {} ({})", error.code, error.message))?
    .target;
    let event_ids = invoke(
        ctx,
        target,
        COUNTER_SEED,
        json!({"event_id": event_id.to_string(), "entity_id": entity_id.to_string(), "value": 7}),
    )?;
    if event_ids[0] != event_id {
        return Err(format!(
            "Runtime changed requested Event identity: {event_ids:?}"
        ));
    }
    Ok((
        target,
        entity_id,
        EventRef::new(target.timeline_id, event_id),
    ))
}

fn create_provenance_seed(
    ctx: &BackendContext,
) -> Result<(TimelineTarget, EntityId, EventRef), String> {
    let entity_id = new_id::<EntityId>();
    let seed_id = new_id::<EventId>();
    let root_id = new_id::<EventId>();
    let target = block_on(async {
        ctx.api()
            .create_world_from_template(CreateWorldFromTemplateRequest::new(provenance_template()))
            .await
    })
    .map_err(|error| format!("World creation failed: {} ({})", error.code, error.message))?
    .target;
    let seed_ids = invoke(
        ctx,
        target,
        PROVENANCE_SEED,
        json!({"event_id": seed_id.to_string(), "entity_id": entity_id.to_string()}),
    )?;
    if seed_ids != vec![seed_id] {
        return Err(format!(
            "unexpected provenance seed identities: {seed_ids:?}"
        ));
    }
    let root_ids = invoke(
        ctx,
        target,
        PROVENANCE_ROOT,
        json!({"event_id": root_id.to_string(), "entity_id": entity_id.to_string()}),
    )?;
    if root_ids != vec![root_id] {
        return Err(format!(
            "unexpected provenance root identities: {root_ids:?}"
        ));
    }
    Ok((
        target,
        entity_id,
        EventRef::new(target.timeline_id, root_id),
    ))
}

fn active_revision(ctx: &BackendContext) -> Result<(String, u64), String> {
    let selection = block_on(async { ctx.client().active_runtime_revision().await })
        .map_err(|error| format!("active Runtime Revision read failed: {}", error.message))?
        .ok_or_else(|| "no active Runtime Revision".to_owned())?;
    Ok((selection.revision.revision_id, selection.generation))
}

fn activate_revision(
    ctx: &BackendContext,
    generation: u64,
    revision_id: &str,
) -> Result<(), String> {
    block_on(async {
        ctx.client()
            .activate_runtime_revision(AdminActivateRuntimeRevisionRequest {
                revision_id: revision_id.to_owned(),
                expected_generation: Some(generation),
            })
            .await
    })
    .map(|_| ())
    .map_err(|error| format!("R2 activation failed: {} ({})", error.code, error.message))
}

fn read_session(
    ctx: &BackendContext,
    session_id: loom_api::ExecutionSessionId,
) -> Result<loom_api::AdminExecutionSession, String> {
    block_on(async {
        ctx.client()
            .get_execution_session(AdminExecutionSessionRequest { session_id })
            .await
    })
    .map_err(|error| format!("Session read failed: {} ({})", error.code, error.message))
}

fn lookup_session(
    ctx: &BackendContext,
    event_ref: EventRef,
) -> Result<loom_api::ExecutionSessionId, String> {
    block_on(async { ctx.client().session_for_event(event_ref).await })
        .map_err(|error| {
            format!(
                "Event-to-Session lookup failed: {} ({})",
                error.code, error.message
            )
        })?
        .session_id
        .ok_or_else(|| format!("Event {event_ref:?} has no producing Session"))
}

fn history_event(
    ctx: &BackendContext,
    event_ref: EventRef,
) -> Result<loom_api::CommittedEvent, String> {
    block_on(async { ctx.api().get_event(event_ref).await })
        .map_err(|error| {
            format!(
                "Event history read failed: {} ({})",
                error.code, error.message
            )
        })?
        .ok_or_else(|| format!("Event {event_ref:?} is absent from public history"))
}

fn history(
    ctx: &BackendContext,
    target: TimelineTarget,
) -> Result<Vec<loom_api::CommittedEvent>, String> {
    block_on(async { ctx.api().list_events(EventQuery::all(target)).await }).map_err(|error| {
        format!(
            "Event history list failed: {} ({})",
            error.code, error.message
        )
    })
}

fn cv031(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let expected = "E1 remains linked to S1 and S1 remains pinned to R1 after R2 activation and controlled restart";
    let result = (|| {
        let (target, _entity, event_ref) = create_seed(ctx)?;
        let s1 = lookup_session(ctx, event_ref)?;
        let before = read_session(ctx, s1)?;
        let (r1, generation) = active_revision(ctx)?;
        if before.runtime_revision_id != r1 || before.event_refs != vec![event_ref] {
            return Err(format!(
                "initial S1 provenance mismatch: {before:?}; active={r1}"
            ));
        }
        activate_revision(ctx, generation, R2_ID)?;
        let reread = history_event(ctx, event_ref)?;
        let history_after_activation = history(ctx, target)?;
        let after = read_session(ctx, s1)?;
        if reread.event_ref() != event_ref
            || history_after_activation != vec![reread.clone()]
            || after.runtime_revision_id != r1
            || after.event_refs != vec![event_ref]
        {
            return Err(format!(
                "E1/S1 drifted after activation: event={reread:?} session={after:?}"
            ));
        }
        let restarted = ctx
            .restart()
            .map_err(|error| format!("controlled restart failed: {error}"))?;
        let new_api = &restarted;
        let post_event = block_on(async { new_api.get_event(event_ref).await })
            .map_err(|error| format!("post-restart Event read failed: {}", error.message))?
            .ok_or_else(|| "E1 disappeared after controlled restart".to_owned())?;
        let post_history = block_on(async { new_api.list_events(EventQuery::all(target)).await })
            .map_err(|error| {
            format!("post-restart Event history list failed: {}", error.message)
        })?;
        let post_session = block_on(async {
            new_api
                .get_execution_session(AdminExecutionSessionRequest { session_id: s1 })
                .await
        })
        .map_err(|error| format!("post-restart Session read failed: {}", error.message))?;
        if post_event != reread
            || post_history != vec![reread.clone()]
            || post_session.runtime_revision_id != r1
        {
            return Err(format!(
                "post-restart provenance changed: event={post_event:?} session={post_session:?}"
            ));
        }
        Ok(format!(
            "E1 {event_ref:?} -> S1 {s1:?} -> R1 {r1}; target={target:?}; restart retained exact history and Session projection"
        ))
    })();
    match result {
        Ok(actual) => result_pass(descriptor, ctx, expected, actual),
        Err(actual) => result_fail(descriptor, ctx, expected, actual),
    }
}

fn cv032(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let expected = "E1/S1 remains on R1 while new E2/S2 after activation is pinned to R2, including after controlled restart";
    let result = (|| {
        let (target, entity_id, e1_ref) = create_seed(ctx)?;
        let s1 = lookup_session(ctx, e1_ref)?;
        let s1_before = read_session(ctx, s1)?;
        let (r1, generation) = active_revision(ctx)?;
        activate_revision(ctx, generation, R2_ID)?;
        let e2 = new_id::<EventId>();
        let e2_ids = invoke(
            ctx,
            target,
            COUNTER_INCREMENT,
            json!({"event_id": e2.to_string(), "entity_id": entity_id.to_string(), "amount": 1}),
        )?;
        if e2_ids != vec![e2] {
            return Err(format!("unexpected E2 identities: {e2_ids:?}"));
        }
        let e2_ref = EventRef::new(target.timeline_id, e2);
        let s2 = lookup_session(ctx, e2_ref)?;
        let s2_projection = read_session(ctx, s2)?;
        let e1_after = history_event(ctx, e1_ref)?;
        let e2_after = history_event(ctx, e2_ref)?;
        let history_after = history(ctx, target)?;
        if s1_before.runtime_revision_id != r1
            || s2_projection.runtime_revision_id != R2_ID
            || lookup_session(ctx, e1_ref)? != s1
            || e1_after.event_ref() != e1_ref
            || e2_after.event_ref() != e2_ref
            || history_after != vec![e1_after.clone(), e2_after.clone()]
        {
            return Err(format!(
                "R1/R2 Session switch or history identity mismatch: s1={s1_before:?} s2={s2_projection:?}"
            ));
        }
        let restarted = ctx
            .restart()
            .map_err(|error| format!("controlled restart failed: {error}"))?;
        let new_api = &restarted;
        let e1_post = block_on(async { new_api.get_event(e1_ref).await })
            .map_err(|error| format!("post-restart E1 read failed: {}", error.message))?
            .ok_or_else(|| "E1 disappeared after controlled restart".to_owned())?;
        let e2_post = block_on(async { new_api.get_event(e2_ref).await })
            .map_err(|error| format!("post-restart E2 read failed: {}", error.message))?
            .ok_or_else(|| "E2 disappeared after controlled restart".to_owned())?;
        let history_post = block_on(async { new_api.list_events(EventQuery::all(target)).await })
            .map_err(|error| {
            format!("post-restart Event history list failed: {}", error.message)
        })?;
        let s1_post = block_on(async {
            new_api
                .get_execution_session(AdminExecutionSessionRequest { session_id: s1 })
                .await
        })
        .map_err(|error| format!("post-restart S1 read failed: {}", error.message))?;
        let s2_post = block_on(async {
            new_api
                .get_execution_session(AdminExecutionSessionRequest { session_id: s2 })
                .await
        })
        .map_err(|error| format!("post-restart S2 read failed: {}", error.message))?;
        if e1_post != e1_after
            || e2_post != e2_after
            || history_post != vec![e1_after.clone(), e2_after.clone()]
            || s1_post.runtime_revision_id != r1
            || s2_post.runtime_revision_id != R2_ID
        {
            return Err(format!(
                "post-restart R1/R2 provenance drifted: s1={s1_post:?} s2={s2_post:?}"
            ));
        }
        Ok(format!(
            "E1 -> S1 -> R1 and E2 -> S2 -> R2 retained for target={target:?}; history unchanged across restart"
        ))
    })();
    match result {
        Ok(actual) => result_pass(descriptor, ctx, expected, actual),
        Err(actual) => result_fail(descriptor, ctx, expected, actual),
    }
}

fn cv033(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let expected = "Session exposes non-secret implementation/version, Facet read, Runtime call and controlled entropy provenance unchanged after activation and restart";
    let result = (|| {
        let (target, entity_id, event_ref) = create_provenance_seed(ctx)?;
        let session_id = lookup_session(ctx, event_ref)?;
        let before = read_session(ctx, session_id)?;
        let (r1, generation) = active_revision(ctx)?;
        let revision_before = block_on(async {
            ctx.client()
                .get_runtime_revision(AdminRuntimeRevisionRequest {
                    revision_id: r1.clone(),
                })
                .await
        })
        .map_err(|error| {
            format!(
                "R1 revision read failed: {} ({})",
                error.code, error.message
            )
        })?;
        let implementation_before = revision_before
            .capabilities
            .iter()
            .find(|capability| capability.capability_id == PROVENANCE_CAPABILITY)
            .ok_or_else(|| "R1 lacks the test-local provenance Capability".to_owned())?;
        if before.runtime_revision_id != r1
            || before.event_refs != vec![event_ref]
            || before.read_set.iter().all(|dependency| {
                !matches!(
                    dependency,
                    AdminReadDependency::Facet {
                        owner: FacetOwner::Entity(owner),
                        facet_type,
                        ..
                    } if *owner == entity_id && *facet_type == PROVENANCE_FACET.into()
                )
            })
            || before.call_provenance.len() != 1
            || before.entropy_evidence.source_id != "validator-t16-entropy"
            || before.entropy_evidence.observations.len() != 1
            || before.entropy_evidence.observations[0].requested_bytes != 4
            || implementation_before.implementation_id.is_empty()
            || implementation_before.version != "0.1.0"
        {
            return Err(format!("CV-033 initial provenance mismatch: {before:?}"));
        }
        let edge = &before.call_provenance[0];
        if edge.caller_capability != PROVENANCE_CAPABILITY
            || edge.caller_action != PROVENANCE_ROOT.into()
            || edge.target_capability != PROVENANCE_CAPABILITY
            || edge.target_action != "validator.t16.provenance.child".into()
        {
            return Err(format!("unexpected Runtime call provenance: {edge:?}"));
        }
        if implementation_before.implementation_id.contains("A5")
            || before.entropy_evidence.source_id.contains("secret")
        {
            return Err("provenance exposed a secret-looking value".to_owned());
        }
        activate_revision(ctx, generation, PROVENANCE_R2_ID)?;
        let restarted = ctx
            .restart()
            .map_err(|error| format!("controlled restart failed: {error}"))?;
        let post_event = block_on(async { restarted.get_event(event_ref).await })
            .map_err(|error| format!("post-restart Event read failed: {}", error.message))?
            .ok_or_else(|| "CV-033 Event disappeared after controlled restart".to_owned())?;
        let post_session = block_on(async {
            restarted
                .get_execution_session(AdminExecutionSessionRequest { session_id })
                .await
        })
        .map_err(|error| format!("post-restart Session read failed: {}", error.message))?;
        let revision_after = block_on(async {
            restarted
                .get_runtime_revision(AdminRuntimeRevisionRequest {
                    revision_id: r1.clone(),
                })
                .await
        })
        .map_err(|error| format!("post-restart R1 revision read failed: {}", error.message))?;
        let implementation_after = revision_after
            .capabilities
            .iter()
            .find(|capability| capability.capability_id == PROVENANCE_CAPABILITY)
            .ok_or_else(|| {
                "post-restart R1 lacks the test-local provenance Capability".to_owned()
            })?;
        if post_event.event_ref() != event_ref
            || post_session.runtime_revision_id != before.runtime_revision_id
            || post_session.read_set != before.read_set
            || post_session.call_provenance != before.call_provenance
            || post_session.entropy_evidence != before.entropy_evidence
            || implementation_after.implementation_id != implementation_before.implementation_id
            || implementation_after.version != implementation_before.version
        {
            return Err(format!(
                "CV-033 provenance drifted after restart: {post_session:?}"
            ));
        }
        Ok(format!(
            "E1 {event_ref:?} -> S1 {session_id:?} -> R1 {r1}; implementation={} version={}; public read/call/entropy evidence retained for target={target:?}",
            implementation_before.implementation_id, implementation_before.version
        ))
    })();
    match result {
        Ok(actual) => result_pass(descriptor, ctx, expected, actual),
        Err(actual) => result_fail(descriptor, ctx, expected, actual),
    }
}

fn evidence(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> Vec<EvidenceReference> {
    vec![
        EvidenceReference::new(format!("validator:provenance:{}", descriptor.id_str())),
        EvidenceReference::new(format!("backend:{}", ctx.backend_kind().as_str())),
        EvidenceReference::new(format!(
            "backend_evidence:{}",
            ctx.backend_evidence().as_str()
        )),
        EvidenceReference::new(format!(
            "restart_capability:{}",
            ctx.restart_capability().as_str()
        )),
        EvidenceReference::new("public-surface:loom-client::ActionService::invoke"),
        EvidenceReference::new("public-surface:loom-client::HistoryService::get_event"),
        EvidenceReference::new("public-surface:loom-client::AdminService::session_for_event"),
        EvidenceReference::new("public-surface:loom-client::AdminService::get_execution_session"),
        EvidenceReference::new(
            "public-surface:loom-client::AdminService::activate_runtime_revision",
        ),
        EvidenceReference::new("public-surface:loom-client::controlled-boundary-restart"),
    ]
}

fn result_pass(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    expected: &str,
    actual: String,
) -> ScenarioResult {
    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual,
        *ctx.backend_kind(),
        format!(
            "validator:{}:{}:scope={}",
            descriptor.id_str(),
            ctx.backend_kind().as_str(),
            ctx.scope()
        ),
        evidence(descriptor, ctx),
        ScenarioOutcome::Pass,
    );
    ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Pass, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

fn result_fail(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    expected: &str,
    actual: impl Into<String>,
) -> ScenarioResult {
    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual.into(),
        *ctx.backend_kind(),
        format!(
            "validator:{}:{}:scope={}",
            descriptor.id_str(),
            ctx.backend_kind().as_str(),
            ctx.scope()
        ),
        evidence(descriptor, ctx),
        ScenarioOutcome::Fail,
    );
    ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

fn unavailable(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    reason: impl Into<String>,
) -> ScenarioResult {
    let reason = reason.into();
    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        "formal/public provenance evidence is available and durable",
        reason.clone(),
        *ctx.backend_kind(),
        format!(
            "validator:{}:{}:scope={}",
            descriptor.id_str(),
            ctx.backend_kind().as_str(),
            ctx.scope()
        ),
        evidence(descriptor, ctx),
        ScenarioOutcome::Unavailable {
            reason: reason.clone(),
        },
    );
    ScenarioResult::new(
        descriptor.id().clone(),
        ScenarioOutcome::Unavailable { reason },
        finding,
    )
    .with_capability_area(descriptor.capability_area().as_str())
}
