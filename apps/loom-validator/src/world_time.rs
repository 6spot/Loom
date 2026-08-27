//! World Time, chronology and reaction validation (T13).
//!
//! Scenarios consume only `loom-api`/`loom-client`; controlled restart
//! composition is supplied by the integration-test harness.

#![allow(clippy::all, clippy::pedantic, clippy::nursery, clippy::restriction)]

use std::future::Future;

use loom_api::{
    ActionInvocation, ActionRequest, ActionTypeId, AdminAdvanceWorldTimeRequest,
    AdminScheduleAgencyWakeRequest, AdminService, AdminWorkStatus, CatalogService,
    CreateWorldFromTemplateRequest, EventQuery, ExecutionResult, FacetOwner, FacetQuery,
    FacetTypeId, HistoryService, QueryService, TimelineService, TimelineTarget, WorkSchedule,
    WorldInstant, WorldService, WorldTemplateDescriptor,
};
use loom_client::LoomClient;
use serde_json::json;
use uuid::Uuid;

use crate::backend::BackendContext;
use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::reports::ScenarioResult;
use crate::scenario::{BackendKind, ScenarioDescriptor};

pub const SUITE: &str = "world_time";
pub const CV_RANGE: &str = "CV-021..CV-024";
pub const CAPABILITY_AREA: &str = "world-time";
pub const CV_021: &str = "CV-021";
pub const CV_022: &str = "CV-022";
pub const CV_023: &str = "CV-023";
pub const CV_024: &str = "CV-024";

#[must_use]
pub fn suite_name() -> &'static str {
    SUITE
}

#[must_use]
pub fn owns_cv(cv_id: &str) -> bool {
    matches!(cv_id, CV_021 | CV_022 | CV_023 | CV_024)
}

/// Returns the local descriptors; T19 owns central registry integration.
#[must_use]
pub fn descriptors() -> Vec<ScenarioDescriptor> {
    let backends = vec![
        BackendKind::LoomClient,
        BackendKind::InMemory,
        BackendKind::PostgreSQL,
    ];
    let refs = |extra: &str| {
        vec![
            "docs/architecture/world-runtime.md".to_string(),
            "docs/tasks/validator-recert/stage-2/t08-coverage-matrix.md".to_string(),
            extra.to_string(),
        ]
    };
    vec![
        ScenarioDescriptor::new(
            CV_021,
            "explicit World Time advance uses logical CAS authority",
            CAPABILITY_AREA,
            backends.clone(),
            "quiescent Timeline at fixed WorldInstant T10",
            vec!["VALR-T13".to_string()],
            refs("crates/loom-api/src/admin.rs"),
        ),
        ScenarioDescriptor::new(
            CV_022,
            "due Pending Work blocks World Time advancement",
            CAPABILITY_AREA,
            backends.clone(),
            "semantic due Work at T20 and a real quiescence-barrier rejection",
            vec!["VALR-T13".to_string()],
            refs("docs/architecture/world-runtime.md#due-work-quiescence-barrier"),
        ),
        ScenarioDescriptor::new(
            CV_023,
            "committed chronology reconstructs deterministically after boundary restart",
            CAPABILITY_AREA,
            backends.clone(),
            "controlled application-boundary restart preserving the Timeline store",
            vec!["VALR-T13".to_string()],
            refs("crates/loom-api/src/lib.rs#HistoryService"),
        ),
        ScenarioDescriptor::new(
            CV_024,
            "reaction Work is atomically scheduled with its triggering commit",
            CAPABILITY_AREA,
            backends,
            "neutral.counter reaction registered and a seeded Entity",
            vec!["VALR-T13".to_string()],
            refs("docs/architecture/runtime-contracts.md#reaction-registration"),
        ),
    ]
}

/// Compatibility name used by suite-local validation callers.
#[must_use]
pub fn world_time_descriptors() -> Vec<ScenarioDescriptor> {
    descriptors()
}

/// Registers into a caller-owned local registry only. The global registry is
/// intentionally left to T19.
pub fn register_world_time(
    registry: &mut crate::registry::ScenarioRegistry,
) -> Result<usize, crate::registry::RegistryError> {
    let mut count = 0;
    for descriptor in descriptors() {
        registry.register(descriptor)?;
        count += 1;
    }
    Ok(count)
}

#[must_use]
pub fn execute_world_time(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    if !descriptor.supported_backends().contains(ctx.backend_kind()) {
        return ScenarioResult::prerequisite(
            descriptor.id().clone(),
            descriptor.name(),
            *ctx.backend_kind(),
            format!(
                "scenario does not declare backend {} as supported",
                ctx.backend_kind()
            ),
        )
        .with_capability_area(descriptor.capability_area().as_str());
    }
    // The repository-managed PostgreSQL default is live and is started by the
    // canonical test harness. No environment variable enables/disables it.
    if ctx.backend_kind().is_postgres()
        && let Err(error) = ctx.client().catalog()
    {
        let reason = format!(
            "PostgreSQL live backend at {} unavailable: {:?} - {}",
            ctx.base_url(),
            error.code,
            error.message
        );
        return ScenarioResult::unavailable(
            descriptor.id().clone(),
            descriptor.name(),
            *ctx.backend_kind(),
            reason,
        )
        .with_capability_area(descriptor.capability_area().as_str());
    }
    match descriptor.id_str() {
        CV_021 => cv021(descriptor, ctx),
        CV_022 => cv022(descriptor, ctx),
        CV_023 => cv023(descriptor, ctx),
        CV_024 => cv024(descriptor, ctx),
        _ => result_fail(
            descriptor,
            ctx,
            "known T13 scenario",
            "unknown world-time scenario",
        ),
    }
}

/// Short suite-local dispatch alias.
#[must_use]
pub fn execute(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    execute_world_time(descriptor, ctx)
}

fn block_on<F: Future>(future: F) -> F::Output {
    if let Ok(handle) = tokio::runtime::Handle::try_current() {
        tokio::task::block_in_place(|| handle.block_on(future))
    } else {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("validator runtime")
            .block_on(future)
    }
}

fn template(scope: &str, time: i64) -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new(format!("validator.t13.{scope}"), 1, WorldInstant::new(time))
        .requires_capability("neutral.counter", "^0.1.0")
}

fn id(seed: u128) -> Uuid {
    Uuid::from_u128(seed)
}

fn needs_restart(ctx: &BackendContext) -> Result<(), String> {
    if ctx.can_perform_boundary_restart() {
        Ok(())
    } else {
        Err(format!(
            "controlled-boundary-restart is required; context provides {}",
            ctx.restart_capability()
        ))
    }
}

fn is_infra(error: &str) -> bool {
    let lower = error.to_ascii_lowercase();
    [
        "unavailable",
        "connection",
        "http request",
        "loom http",
        "refused",
        "timed out",
        "unreachable",
        "internal server",
    ]
    .iter()
    .any(|needle| lower.contains(needle))
}

fn finding_for(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    expected: &str,
    actual: &str,
    outcome: ScenarioOutcome,
    surfaces: &[&str],
) -> Finding {
    let mut evidence = vec![
        EvidenceReference::new(format!("validator:{}:{}", SUITE, descriptor.id_str())),
        EvidenceReference::new(format!("backend:{}", ctx.backend_kind())),
        EvidenceReference::new(format!("backend_evidence:{}", ctx.backend_evidence())),
        EvidenceReference::new(format!("restart_capability:{}", ctx.restart_capability())),
    ];
    evidence.extend(
        surfaces
            .iter()
            .map(|surface| EvidenceReference::new(*surface)),
    );
    Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual,
        *ctx.backend_kind(),
        format!(
            "validator:{}:{}:scope={}",
            descriptor.id_str(),
            ctx.backend_kind(),
            ctx.scope()
        ),
        evidence,
        outcome,
    )
}

fn result_pass(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    expected: &str,
    actual: String,
    surfaces: &[&str],
) -> ScenarioResult {
    let finding = finding_for(
        descriptor,
        ctx,
        expected,
        &actual,
        ScenarioOutcome::Pass,
        surfaces,
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
    let actual = actual.into();
    let outcome = if is_infra(&actual) {
        ScenarioOutcome::Unavailable {
            reason: actual.clone(),
        }
    } else {
        ScenarioOutcome::Fail
    };
    let finding = finding_for(descriptor, ctx, expected, &actual, outcome.clone(), &[]);
    ScenarioResult::new(descriptor.id().clone(), outcome, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

fn create(
    ctx: &BackendContext,
    scope: &str,
    time: i64,
) -> Result<loom_api::TimelineSnapshot, String> {
    block_on(async {
        ctx.client()
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template(scope, time)))
            .await
    })
    .map_err(|e| format!("create_world_from_template: {:?} - {}", e.code, e.message))
}

fn seed(
    ctx: &BackendContext,
    target: TimelineTarget,
    entity: Uuid,
    event: Uuid,
    value: i64,
) -> Result<loom_api::TimelineVersion, String> {
    let result = block_on(async { ctx.api().invoke(ActionRequest::new(target, ActionInvocation::new(ActionTypeId::from("neutral.counter.seed"), json!({"event_id": event.to_string(), "entity_id": entity.to_string(), "value": value})))).await }).map_err(|e| format!("seed invoke: {:?} - {}", e.code, e.message))?;
    match result {
        ExecutionResult::Committed {
            timeline_version, ..
        } => Ok(timeline_version),
        other => Err(format!("seed was not committed: {other:?}")),
    }
}

fn increment(
    ctx: &BackendContext,
    target: TimelineTarget,
    entity: Uuid,
    event: Uuid,
    amount: i64,
) -> Result<loom_api::TimelineVersion, String> {
    let result = block_on(async { ctx.api().invoke(ActionRequest::new(target, ActionInvocation::new(ActionTypeId::from("neutral.counter.increment"), json!({"event_id": event.to_string(), "entity_id": entity.to_string(), "amount": amount})))).await }).map_err(|e| format!("increment invoke: {:?} - {}", e.code, e.message))?;
    match result {
        ExecutionResult::Committed {
            timeline_version, ..
        } => Ok(timeline_version),
        other => Err(format!("increment was not committed: {other:?}")),
    }
}

fn schedule(
    ctx: &BackendContext,
    target: TimelineTarget,
    version: loom_api::TimelineVersion,
    entity: Uuid,
    work: Uuid,
    at: i64,
) -> Result<(), String> {
    block_on(async {
        ctx.client()
            .schedule_agency_wake(AdminScheduleAgencyWakeRequest {
                target,
                expected_version: version,
                work_id: loom_api::WorkId::new(work),
                agent: loom_api::EntityId::new(entity),
                cognition: "validator.t13.cognition@1".to_string(),
                payload: json!({"suite": SUITE}),
                schedule: WorkSchedule::At(WorldInstant::new(at)),
            })
            .await
    })
    .map(|_| ())
    .map_err(|e| format!("schedule_agency_wake: {:?} - {}", e.code, e.message))
}

fn status(
    ctx: &BackendContext,
    target: TimelineTarget,
) -> Result<loom_api::AdminTimelineLogicalStatus, String> {
    block_on(async { ctx.client().timeline_logical_status(target).await })
        .map_err(|e| format!("timeline_logical_status: {:?} - {}", e.code, e.message))
}

fn cv021(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let expected = "explicit T10→T20 advance commits one logical CAS revision, creates no Event, and is observable at T20";
    let result = (|| {
        let snapshot = create(ctx, &format!("{}-cv021", ctx.scope()), 10)?;
        let before_events = block_on(async {
            ctx.client()
                .list_events(EventQuery::all(snapshot.target))
                .await
        })
        .map_err(|e| format!("history before: {:?} - {}", e.code, e.message))?;
        let advanced = block_on(async {
            ctx.client()
                .advance_world_time(AdminAdvanceWorldTimeRequest {
                    target: snapshot.target,
                    expected_version: snapshot.version,
                    current: WorldInstant::new(10),
                    next: WorldInstant::new(20),
                })
                .await
        })
        .map_err(|e| format!("advance_world_time: {:?} - {}", e.code, e.message))?;
        let after = block_on(async { ctx.api().inspect_timeline(snapshot.target).await })
            .map_err(|e| format!("inspect_timeline: {:?} - {}", e.code, e.message))?;
        let after_events = block_on(async {
            ctx.api()
                .list_events(EventQuery::all(snapshot.target))
                .await
        })
        .map_err(|e| format!("history after: {:?} - {}", e.code, e.message))?;
        if advanced.from != WorldInstant::new(10)
            || advanced.to != WorldInstant::new(20)
            || after.world_time != WorldInstant::new(20)
            || after.version != advanced.version
            || advanced.version.state_revision.value()
                != snapshot.version.state_revision.value() + 1
            || before_events.len() != after_events.len()
        {
            return Err(format!(
                "invalid advance result={advanced:?} after={after:?} event_counts={}/{}",
                before_events.len(),
                after_events.len()
            ));
        }
        Ok(format!(
            "fixed logical transition T10→T20; version {:?}→{:?}; Event count unchanged at {}",
            snapshot.version,
            after.version,
            after_events.len()
        ))
    })();
    match result {
        Ok(actual) => result_pass(
            descriptor,
            ctx,
            expected,
            actual,
            &[
                "public-surface:loom-client::AdminService::advance_world_time",
                "public-surface:loom-client::TimelineService::inspect_timeline",
                "public-surface:loom-client::HistoryService::list_events",
                "validator:CV-021:explicit-time-CAS",
            ],
        ),
        Err(actual) => result_fail(descriptor, ctx, expected, actual),
    }
}

fn cv022(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let expected = "a semantically due Pending Work at T20 rejects T20→T30, preserving World Time, TimelineVersion, Work head and chronology budget";
    let result = (|| {
        let snapshot = create(ctx, &format!("{}-cv022", ctx.scope()), 20)?;
        let entity = id(0x2201);
        let seeded = seed(ctx, snapshot.target, entity, id(0x2202), 5)?;
        // The neutral.counter increment Action is the published semantic
        // reaction path that creates the due Pending Work. This avoids making
        // an administrative schedule operation stand in for semantic Work.
        let _incremented = increment(ctx, snapshot.target, entity, id(0x2203), 1)?;
        let before = status(ctx, snapshot.target)?;
        let attempt = block_on(async {
            ctx.client()
                .advance_world_time(AdminAdvanceWorldTimeRequest {
                    target: snapshot.target,
                    expected_version: before.version,
                    current: WorldInstant::new(20),
                    next: WorldInstant::new(30),
                })
                .await
        });
        let rejection = match attempt {
            Ok(value) => return Err(format!("advance unexpectedly committed: {value:?}")),
            Err(error) => format!("{:?} - {}", error.code, error.message),
        };
        let after = status(ctx, snapshot.target)?;
        let inspected = block_on(async { ctx.api().inspect_timeline(snapshot.target).await })
            .map_err(|e| format!("inspect after rejection: {:?} - {}", e.code, e.message))?;
        let pending = after
            .works
            .iter()
            .filter(|work_status| {
                work_status.status == AdminWorkStatus::Pending
                    && work_status.effective_due_world_time == WorldInstant::new(20)
            })
            .count();
        let rejection_lower = rejection.to_ascii_lowercase();
        if !(rejection_lower.contains("quiescence") || rejection_lower.contains("due"))
            || pending == 0
            || after.version != before.version
            || after.world_time != WorldInstant::new(20)
            || inspected.world_time != WorldInstant::new(20)
        {
            return Err(format!(
                "barrier mismatch rejection={rejection} seeded={seeded:?} before={before:?} after={after:?} inspected={inspected:?}"
            ));
        }
        let mut restart_verified = false;
        if ctx.backend_kind().is_postgres() {
            needs_restart(ctx)?;
            let restarted = ctx
                .restart()
                .map_err(|error| format!("controlled boundary restart: {error}"))?;
            let restarted_status =
                block_on(async { restarted.timeline_logical_status(snapshot.target).await })
                    .map_err(|e| {
                        format!(
                            "timeline_logical_status after restart: {:?} - {}",
                            e.code, e.message
                        )
                    })?;
            let restarted_timeline =
                block_on(async { restarted.inspect_timeline(snapshot.target).await }).map_err(
                    |e| {
                        format!(
                            "inspect_timeline after restart: {:?} - {}",
                            e.code, e.message
                        )
                    },
                )?;
            if restarted_status != after
                || restarted_timeline.world_time != WorldInstant::new(20)
                || restarted_timeline.version != before.version
            {
                return Err(format!(
                    "post-restart barrier state changed: before={before:?} after={after:?} restarted={restarted_status:?} timeline={restarted_timeline:?}"
                ));
            }
            restart_verified = true;
        }
        Ok(format!(
            "semantic reaction produced {pending} due Pending Work at T20; rejection={rejection}; chronology_budget={:?}; restart_verified={restart_verified}",
            after.chronology_budget
        ))
    })();
    match result {
        Ok(actual) => result_pass(
            descriptor,
            ctx,
            expected,
            actual,
            &[
                "public-surface:loom-client::AdminService::advance_world_time",
                "public-surface:loom-client::AdminService::timeline_logical_status",
                "public-surface:loom-client::TimelineService::inspect_timeline",
                "validator:CV-022:quiescence-barrier",
                "validator:postgres:live",
            ],
        ),
        Err(actual) => result_fail(descriptor, ctx, expected, actual),
    }
}

type ChronologyObservation = (
    Vec<loom_api::CommittedEvent>,
    loom_api::EventPage,
    loom_api::TimelineSnapshot,
    loom_api::AdminTimelineLogicalStatus,
    Option<serde_json::Value>,
);

fn chronology(
    client: &LoomClient,
    target: TimelineTarget,
    entity: Uuid,
) -> Result<ChronologyObservation, String> {
    let events = block_on(async { client.list_events(EventQuery::all(target)).await })
        .map_err(|e| format!("list_events: {:?} - {}", e.code, e.message))?;
    let page = block_on(async { client.list_events_page(EventQuery::all(target)).await })
        .map_err(|e| format!("list_events_page: {:?} - {}", e.code, e.message))?;
    let timeline = block_on(async { client.inspect_timeline(target).await })
        .map_err(|e| format!("inspect_timeline: {:?} - {}", e.code, e.message))?;
    let logical = block_on(async { client.timeline_logical_status(target).await })
        .map_err(|e| format!("timeline_logical_status: {:?} - {}", e.code, e.message))?;
    let facet = block_on(async {
        client
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(loom_api::EntityId::new(entity)),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
    })
    .map_err(|e| format!("get_facet: {:?} - {}", e.code, e.message))?
    .map(|value| value.value);
    Ok((events, page, timeline, logical, facet))
}

fn cv023(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let expected = "EventSeq chronology, Timeline logical state, Work order and materialized state are identical before and after a controlled boundary restart";
    let result = (|| {
        needs_restart(ctx)?;
        let snapshot = create(ctx, &format!("{}-cv023", ctx.scope()), 10)?;
        let entity = id(0x2301);
        let seeded = seed(ctx, snapshot.target, entity, id(0x2302), 1)?;
        let _advanced = block_on(async {
            ctx.client()
                .advance_world_time(AdminAdvanceWorldTimeRequest {
                    target: snapshot.target,
                    expected_version: seeded,
                    current: WorldInstant::new(10),
                    next: WorldInstant::new(20),
                })
                .await
        })
        .map_err(|e| format!("advance: {:?} - {}", e.code, e.message))?;
        let incremented = increment(ctx, snapshot.target, entity, id(0x2303), 1)?;
        schedule(ctx, snapshot.target, incremented, entity, id(0x2304), 20)?;
        let before = chronology(ctx.client(), snapshot.target, entity)?;
        let client = ctx
            .restart()
            .map_err(|e| format!("controlled boundary restart: {e}"))?;
        let after = chronology(&client, snapshot.target, entity)?;
        let ordered_before = before
            .0
            .windows(2)
            .all(|window| window[0].sequence < window[1].sequence);
        let identity_order = before
            .0
            .iter()
            .map(|event| {
                (
                    event.sequence,
                    event.id,
                    event.event_type.clone(),
                    event.occurred_at,
                )
            })
            .collect::<Vec<_>>()
            == after
                .0
                .iter()
                .map(|event| {
                    (
                        event.sequence,
                        event.id,
                        event.event_type.clone(),
                        event.occurred_at,
                    )
                })
                .collect::<Vec<_>>();
        if !ordered_before
            || !identity_order
            || before.1 != after.1
            || before.2 != after.2
            || before.3 != after.3
            || before.4 != after.4
        {
            return Err(format!(
                "reconstruction mismatch before={before:?} after={after:?}"
            ));
        }
        Ok(format!(
            "EventSeq chronology and logical order reconstructed identically across controlled-boundary-restart; events={} version={:?} world_time={:?}",
            after.0.len(),
            after.2.version,
            after.2.world_time
        ))
    })();
    match result {
        Ok(actual) => result_pass(
            descriptor,
            ctx,
            expected,
            actual,
            &[
                "public-surface:loom-client::HistoryService::list_events",
                "public-surface:loom-client::HistoryService::list_events_page",
                "public-surface:loom-client::TimelineService::inspect_timeline",
                "public-surface:loom-client::AdminService::timeline_logical_status",
                "public-surface:loom-client::QueryService::get_facet",
                "validator:CV-023:controlled-boundary-restart",
                "validator:postgres:live",
            ],
        ),
        Err(actual) => result_fail(descriptor, ctx, expected, actual),
    }
}

fn cv024(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let expected = "neutral.counter increment Event and reaction Pending Work share the triggering logical commit and remain observable together after restart";
    let result = (|| {
        needs_restart(ctx)?;
        let snapshot = create(ctx, &format!("{}-cv024", ctx.scope()), 10)?;
        let entity = id(0x2401);
        let seeded = seed(ctx, snapshot.target, entity, id(0x2402), 5)?;
        let incremented = increment(ctx, snapshot.target, entity, id(0x2403), 1)?;
        let events = block_on(async {
            ctx.client()
                .list_events(EventQuery::all(snapshot.target))
                .await
        })
        .map_err(|e| format!("history: {:?} - {}", e.code, e.message))?;
        let logical = status(ctx, snapshot.target)?;
        let increment_event = events
            .iter()
            .find(|event| event.event_type.to_string() == "neutral.counter.incremented");
        let pending = logical
            .works
            .iter()
            .filter(|work| {
                work.status == AdminWorkStatus::Pending
                    && work.effective_due_world_time == WorldInstant::new(10)
            })
            .count();
        if incremented.head_event_seq.value() != seeded.head_event_seq.value() + 1
            || incremented.state_revision.value() != seeded.state_revision.value() + 1
            || increment_event.is_none()
            || pending == 0
            || logical.version != incremented
        {
            return Err(format!(
                "reaction atomicity mismatch seeded={seeded:?} incremented={incremented:?} events={events:?} logical={logical:?}"
            ));
        }
        let client = ctx
            .restart()
            .map_err(|e| format!("controlled boundary restart: {e}"))?;
        let after_events =
            block_on(async { client.list_events(EventQuery::all(snapshot.target)).await })
                .map_err(|e| format!("history after restart: {:?} - {}", e.code, e.message))?;
        let after_logical =
            block_on(async { client.timeline_logical_status(snapshot.target).await })
                .map_err(|e| format!("logical after restart: {:?} - {}", e.code, e.message))?;
        if after_events != events || after_logical != logical {
            return Err(format!(
                "post-restart reaction state changed: before events={events:?} logical={logical:?}; after events={after_events:?} logical={after_logical:?}"
            ));
        }
        Ok(format!(
            "incremented Event and {pending} Pending reaction Work observed at one logical version {:?}; restart preserved both",
            incremented
        ))
    })();
    match result {
        Ok(actual) => result_pass(
            descriptor,
            ctx,
            expected,
            actual,
            &[
                "public-surface:loom-client::ActionService::invoke",
                "public-surface:loom-client::HistoryService::list_events",
                "public-surface:loom-client::AdminService::timeline_logical_status",
                "validator:CV-024:reaction-atomic-commit",
                "validator:restart:controlled-boundary-restart",
            ],
        ),
        Err(actual) => result_fail(descriptor, ctx, expected, actual),
    }
}
