//! Scheduler + fencing suite (T12).
//!
//! Owner: T12 (#317) — `CV-018..CV-020`.
//! Central registry integration is reserved for T19 (#324). This module must
//! not register scenarios in `validator_registry`; T19 alone edits
//! `registry.rs`/`lib.rs` and CLI dispatch.
//! `CV-018` and `CV-019` are recorded as blocked gaps per frozen T08: no public
//! `schedule_work`/`claim`/`fence` surface exists to create or observe head
//! ordering or stale fencing via `loom-api`/`loom-client`. `CV-020` is the only
//! executable public-surface scenario in this suite: independent Timelines are
//! not globally serialized by one Timeline's logical-head constraint.
//! No `loom-storage`/`loom-runtime`/`loom-boundary` imports are permitted.

#![allow(clippy::all, clippy::pedantic, clippy::nursery, clippy::restriction)]
#![allow(unused_imports, dead_code)]

use std::future::Future;

use loom_api::WorkSchedule;
use loom_api::{
    ActionInvocation, ActionRequest, ActionService, ActionTypeId, AdminScheduleAgencyWakeRequest,
    AdminService, AdminTimelineLogicalStatus, AdminWorkStatus, CatalogService,
    CreateWorldFromTemplateRequest, EntityId, EventId, EventQuery, ExecutionResult, HistoryService,
    TimelineService, TimelineTarget, WorkId, WorldInstant, WorldService, WorldTemplateDescriptor,
};
use serde_json::json;
use uuid::Uuid;

use crate::backend::BackendContext;
use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::reports::ScenarioResult;
use crate::scenario::{BackendKind, ScenarioDescriptor};
use crate::{RegistryError, ScenarioRegistry};

/// Suite identifier for file ownership.
pub const SUITE: &str = "scheduler";

/// Owned CV range for this suite.
pub const CV_RANGE: &str = "CV-018..CV-020";

/// Capability area label for this suite.
pub const CAPABILITY_AREA: &str = "scheduler";

/// Stable IDs — `CV-018`/`CV-019` are blocked gaps, `CV-020` is executable.
pub const CV_018: &str = "CV-018";
pub const CV_019: &str = "CV-019";
pub const CV_020: &str = "CV-020";

/// Returns the suite identifier.
#[must_use]
pub fn suite_name() -> &'static str {
    SUITE
}

/// Returns true if `cv_id` belongs to this suite's owned CV range.
#[must_use]
pub fn owns_cv(cv_id: &str) -> bool {
    matches!(cv_id, "CV-018" | "CV-019" | "CV-020")
}

#[must_use]
pub fn descriptors() -> Vec<ScenarioDescriptor> {
    vec![ScenarioDescriptor::new(
        CV_020,
        "independent Timelines not globally serialized by one Timeline's logical-head constraint",
        CAPABILITY_AREA,
        vec![
            BackendKind::LoomClient,
            BackendKind::InMemory,
            BackendKind::PostgreSQL,
        ],
        "Two Worlds/Timelines each with due Pending Work at same fixed WorldInstant; B commits Action while A's head remains Pending; per-Timeline CAS",
        vec!["#317".to_string(), "VALR-T12".to_string()],
        vec![
            "docs/architecture/world-runtime.md".to_string(),
            "docs/tasks/validator-recert/stage-2/t08-coverage-matrix.md".to_string(),
        ],
    )]
}

pub fn register_scheduler(registry: &mut ScenarioRegistry) -> Result<usize, RegistryError> {
    let mut count = 0;
    for descriptor in descriptors() {
        registry.register(descriptor)?;
        count += 1;
    }
    Ok(count)
}

#[must_use]
pub fn execute_scheduler(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    if !descriptor.supported_backends().contains(ctx.backend_kind()) {
        return ScenarioResult::prerequisite(
            descriptor.id().clone(),
            descriptor.name(),
            *ctx.backend_kind(),
            format!(
                "scenario does not declare backend {} as supported",
                ctx.backend_kind().as_str()
            ),
        )
        .with_capability_area(descriptor.capability_area().as_str());
    }

    // PostgreSQL live prerequisite handling — consistent with T10/T11 leaves.
    if ctx.backend_kind().is_postgres() {
        if let Err(reason) = check_postgres_prerequisite() {
            if reason.contains("missing") || reason.contains("empty") {
                return ScenarioResult::prerequisite(
                    descriptor.id().clone(),
                    descriptor.name(),
                    *ctx.backend_kind(),
                    reason,
                )
                .with_capability_area(descriptor.capability_area().as_str());
            }
            return ScenarioResult::unavailable(
                descriptor.id().clone(),
                descriptor.name(),
                *ctx.backend_kind(),
                reason,
            )
            .with_capability_area(descriptor.capability_area().as_str());
        }
        // verify live endpoint reachable
        let api = ctx.api();
        let catalog_res = block_on(async { api.catalog() });
        if let Err(err) = catalog_res {
            let reason = format!(
                "PostgreSQL live backend at {} unavailable: {:?} - {}",
                ctx.base_url(),
                err.code,
                err.message
            );
            return ScenarioResult::unavailable(
                descriptor.id().clone(),
                descriptor.name(),
                *ctx.backend_kind(),
                reason,
            )
            .with_capability_area(descriptor.capability_area().as_str());
        }
    }

    match descriptor.id_str() {
        CV_020 => cv020(descriptor, ctx),
        _ => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "scenario is registered with stable ID",
                format!("unknown scheduler scenario {}", descriptor.id_str()),
                *ctx.backend_kind(),
                format!(
                    "backend-harness:scope={} backend={}",
                    ctx.scope(),
                    ctx.backend_kind().as_str()
                ),
                vec![EvidenceReference::new("validator:unknown-scenario")],
                ScenarioOutcome::Fail,
            );
            ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str())
        }
    }
}

fn check_postgres_prerequisite() -> Result<(), String> {
    let key = crate::backend::LOOM_TEST_POSTGRES_URL;
    match std::env::var(key) {
        Ok(v) => postgres_prerequisite_with_value(Some(v.as_str()), key),
        Err(std::env::VarError::NotPresent) => postgres_prerequisite_with_value(None, key),
        Err(std::env::VarError::NotUnicode(_)) => Err(format!("{key} is not valid Unicode")),
    }
}

fn postgres_prerequisite_with_value(value: Option<&str>, key: &str) -> Result<(), String> {
    match value {
        None => Err(format!("missing {key}; PostgreSQL evidence is unavailable")),
        Some(v) if v.trim().is_empty() => {
            Err(format!("empty {key}; PostgreSQL evidence is unavailable"))
        }
        Some(v) if !(v.starts_with("postgres://") || v.starts_with("postgresql://")) => Err(
            format!("{key} must use the postgres:// or postgresql:// scheme"),
        ),
        Some(_) => Ok(()),
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

fn world_template_for(scope: &str) -> WorldTemplateDescriptor {
    let _ = scope;
    WorldTemplateDescriptor::new(
        "validator.t12.scheduler.fencing.v1",
        1,
        WorldInstant::new(100),
    )
    .requires_capability("neutral.counter", "^0.1.0")
}

fn new_entity_id() -> EntityId {
    EntityId::new(Uuid::new_v4())
}
fn new_event_id() -> EventId {
    EventId::new(Uuid::new_v4())
}
fn new_work_id() -> WorkId {
    WorkId::new(Uuid::new_v4())
}

fn is_infra_unavailable(actual: &str) -> bool {
    let lower = actual.to_ascii_lowercase();
    lower.contains("unavailable")
        || lower.contains("connection")
        || lower.contains("not found")
        || lower.contains("internal")
        || lower.contains("http request failed")
        || lower.contains("loom http")
        || lower.contains("unreachable")
        || lower.contains("refused")
        || lower.contains("timed out")
}

fn finding_for(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    expected: &str,
    actual: &str,
    outcome: ScenarioOutcome,
) -> Finding {
    Finding::new(
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
        vec![
            EvidenceReference::new(format!("validator:scheduler:{}", descriptor.id_str())),
            EvidenceReference::new(format!("backend:{}", ctx.backend_kind().as_str())),
            EvidenceReference::new(format!(
                "backend_evidence:{}",
                ctx.backend_evidence().as_str()
            )),
            EvidenceReference::new(format!(
                "restart_capability:{}",
                ctx.restart_capability().as_str()
            )),
        ],
        outcome,
    )
}

fn result_pass(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    expected: &str,
    actual: &str,
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
        vec![
            EvidenceReference::new(format!("validator:scheduler:{}", descriptor.id_str())),
            EvidenceReference::new(format!("backend:{}", ctx.backend_kind().as_str())),
            EvidenceReference::new(format!(
                "backend_evidence:{}",
                ctx.backend_evidence().as_str()
            )),
            EvidenceReference::new(format!(
                "restart_capability:{}",
                ctx.restart_capability().as_str()
            )),
            EvidenceReference::new(
                "public-surface:loom-client::WorldService::create_world_from_template",
            ),
            EvidenceReference::new(
                "public-surface:loom-client::AdminService::schedule_agency_wake",
            ),
            EvidenceReference::new("public-surface:loom-client::ActionService::invoke"),
            EvidenceReference::new(
                "public-surface:loom-client::AdminService::timeline_logical_status",
            ),
            EvidenceReference::new("public-surface:loom-client::TimelineService::inspect_timeline"),
            EvidenceReference::new("public-surface:loom-client::HistoryService::list_events"),
        ],
        ScenarioOutcome::Pass,
    );
    ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Pass, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

fn result_fail(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    expected: &str,
    actual: String,
) -> ScenarioResult {
    ScenarioResult::new(
        descriptor.id().clone(),
        ScenarioOutcome::Fail,
        finding_for(descriptor, ctx, expected, &actual, ScenarioOutcome::Fail),
    )
    .with_capability_area(descriptor.capability_area().as_str())
}

// ── CV-020 ───────────────────────────────────────────────────────────────────

fn cv020(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let api = ctx.api();
    let client = ctx.client().clone();
    let scope = ctx.scope().to_string();
    let expected = "independent Timelines not globally serialized: B commits Action/Event/version while A's due Pending Work remains Pending; per-Timeline CAS, fixed WorldInstant, formal reads";
    let fixed_instant = WorldInstant::new(100);

    // 1. Create two independent Worlds at fixed WorldInstant 100.
    let template_a = world_template_for(&format!("{scope}-A"));
    let created_a = match block_on(async {
        api.create_world_from_template(CreateWorldFromTemplateRequest::new(template_a.clone()))
            .await
    }) {
        Ok(s) => s,
        Err(e) => {
            let actual = format!(
                "create_world_from_template A failed: {:?} - {}",
                e.code, e.message
            );
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(descriptor, ctx, expected, &actual, outcome.clone());
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            return result_fail(descriptor, ctx, expected, actual);
        }
    };
    if created_a.world_time != fixed_instant {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A world_time mismatch: expected {} got {}",
                fixed_instant.value(),
                created_a.world_time.value()
            ),
        );
    }
    let target_a = created_a.target;
    // Use the logical status version for CAS — the snapshot version from creation may be stale if
    // the runtime's logical journal is observed via AdminService. Fetching the fresh status mirrors
    // the public-consumer convenience path exercised in loom-cli::agency_wake_convenience_resolves_version_via_status.
    let mut version_a0 = match block_on(async { client.timeline_logical_status(target_a).await }) {
        Ok(status) => status.version,
        Err(e) => {
            // Fallback to creation version if status read fails — but report as unavailable if infra.
            if is_infra_unavailable(&format!("{:?}", e.code)) {
                let actual = format!(
                    "timeline_logical_status A pre-schedule failed: {:?} - {}",
                    e.code, e.message
                );
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(descriptor, ctx, expected, &actual, outcome.clone());
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            created_a.version
        }
    };
    if version_a0 != created_a.version {
        // Creation and status should align on a fresh world; if not, we use the fresh status version
        // for the CAS to avoid the stale-version Conflict observed in earlier runs.
    }

    let template_b = world_template_for(&format!("{scope}-B"));
    let created_b = match block_on(async {
        api.create_world_from_template(CreateWorldFromTemplateRequest::new(template_b.clone()))
            .await
    }) {
        Ok(s) => s,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "create_world_from_template B failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    if created_b.world_time != fixed_instant {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B world_time mismatch: expected {} got {}",
                fixed_instant.value(),
                created_b.world_time.value()
            ),
        );
    }
    let target_b = created_b.target;
    let _version_b0_initial =
        match block_on(async { client.timeline_logical_status(target_b).await }) {
            Ok(status) => status.version,
            Err(_) => created_b.version,
        };

    if target_a.world_id == target_b.world_id && target_a.timeline_id == target_b.timeline_id {
        return result_fail(
            descriptor,
            ctx,
            expected,
            "A and B targets are identical; expected independent Worlds/Timelines".to_string(),
        );
    }
    if target_a.world_id == target_b.world_id {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A and B share same WorldId {}; expected independent Worlds (distinct WorldId) for timeline-scoped test",
                target_a.world_id
            ),
        );
    }

    // 2. Ensure Agency Wake agent entities exist — schedule_agency_wake validates that the agent
    //    Entity is already present in the Timeline's entity set (InMemoryStore commit check).
    //    The frozen T08 world template is otherwise empty, so we seed one counter Facet per Timeline
    //    using the agent's own EntityId before scheduling. This keeps the fixed WorldInstant and
    //    per-Timeline CAS guarantees intact and uses only public surfaces.
    let work_id_a = new_work_id();
    let work_id_b = new_work_id();
    let agent_a = new_entity_id();
    let agent_b = new_entity_id();

    // Seed agent entity for A
    let bootstrap_event_a = new_event_id();
    let seed_a = ActionRequest::new(
        target_a,
        ActionInvocation::new(
            ActionTypeId::from("neutral.counter.seed"),
            json!({
                "event_id": bootstrap_event_a.to_string(),
                "entity_id": agent_a.to_string(),
                "value": 1,
            }),
        ),
    );
    let seed_res_a = match block_on(async { api.invoke(seed_a).await }) {
        Ok(r) => r,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "bootstrap seed A for agent failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    let version_a0_after_seed = match seed_res_a {
        ExecutionResult::Committed {
            timeline_version, ..
        } => timeline_version,
        other => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!("bootstrap seed A not committed: {:?}", other),
            );
        }
    };
    // Seed agent entity for B
    let bootstrap_event_b = new_event_id();
    let seed_b = ActionRequest::new(
        target_b,
        ActionInvocation::new(
            ActionTypeId::from("neutral.counter.seed"),
            json!({
                "event_id": bootstrap_event_b.to_string(),
                "entity_id": agent_b.to_string(),
                "value": 1,
            }),
        ),
    );
    let seed_res_b = match block_on(async { api.invoke(seed_b).await }) {
        Ok(r) => r,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "bootstrap seed B for agent failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    let version_b0_after_seed = match seed_res_b {
        ExecutionResult::Committed {
            timeline_version, ..
        } => timeline_version,
        other => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!("bootstrap seed B not committed: {:?}", other),
            );
        }
    };

    // Update expected versions to the post-seed committed versions for the CAS.
    version_a0 = version_a0_after_seed;
    let mut version_b0_inner = version_b0_after_seed;
    // Use the fresh status version as the CAS expected_version for schedule — this matches the
    // convenience path and ensures we test the exact public CAS the CLI uses.
    // Fetch fresh status for both to be safe.
    if let Ok(status) = block_on(async { client.timeline_logical_status(target_a).await }) {
        if status.version != version_a0 {
            version_a0 = status.version;
        }
    }
    if let Ok(status) = block_on(async { client.timeline_logical_status(target_b).await }) {
        if status.version != version_b0_inner {
            version_b0_inner = status.version;
        }
    }
    let version_b0 = version_b0_inner;

    let schedule_a = AdminScheduleAgencyWakeRequest {
        target: target_a,
        expected_version: version_a0,
        work_id: work_id_a,
        agent: agent_a,
        cognition: "scheduler.t12.cognition.v1".to_string(),
        payload: json!({"scheduler": "t12-cv020", "timeline": "A", "scope": scope}),
        schedule: WorkSchedule::At(fixed_instant),
    };
    // Pre-schedule diagnostics
    let pre_a_status = block_on(async { client.timeline_logical_status(target_a).await });
    let pre_a_inspect = block_on(async { api.inspect_timeline(target_a).await });
    let schedule_res_a = match block_on(async {
        client.schedule_agency_wake(schedule_a.clone()).await
    }) {
        Ok(r) => r,
        Err(e) => {
            let fresh_status = block_on(async { client.timeline_logical_status(target_a).await });
            let fresh_inspect = block_on(async { api.inspect_timeline(target_a).await });
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "schedule_agency_wake A failed: {:?} - {}; expected_version {:?} creation {:?} pre_status {:?} pre_inspect {:?} fresh_status {:?} fresh_inspect {:?}",
                    e.code,
                    e.message,
                    version_a0,
                    created_a.version,
                    pre_a_status.as_ref().map(|s| format!("{:?}", s.version)),
                    pre_a_inspect.as_ref().map(|s| format!("{:?}", s.version)),
                    fresh_status
                        .as_ref()
                        .map(|s| format!("{:?} w{:?}", s.version, s.works.len())),
                    fresh_inspect.as_ref().map(|s| format!(
                        "{:?} wtime {}",
                        s.version,
                        s.world_time.value()
                    ))
                ),
            );
        }
    };
    if schedule_res_a.target != target_a || schedule_res_a.work_id != work_id_a {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "schedule A target/work mismatch: expected {:?}/{:?} got {:?}/{:?}",
                target_a, work_id_a, schedule_res_a.target, schedule_res_a.work_id
            ),
        );
    }
    let version_a1 = schedule_res_a.version;

    let schedule_b = AdminScheduleAgencyWakeRequest {
        target: target_b,
        expected_version: version_b0,
        work_id: work_id_b,
        agent: agent_b,
        cognition: "scheduler.t12.cognition.v1".to_string(),
        payload: json!({"scheduler": "t12-cv020", "timeline": "B", "scope": scope}),
        schedule: WorkSchedule::At(fixed_instant),
    };
    let schedule_res_b = match block_on(async { client.schedule_agency_wake(schedule_b).await }) {
        Ok(r) => r,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "schedule_agency_wake B failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    if schedule_res_b.target != target_b || schedule_res_b.work_id != work_id_b {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "schedule B target/work mismatch: expected {:?}/{:?} got {:?}/{:?}",
                target_b, work_id_b, schedule_res_b.target, schedule_res_b.work_id
            ),
        );
    }
    let version_b1 = schedule_res_b.version;

    // Verify that scheduling used per-Timeline CAS and did not cross-serialize:
    // A schedule should not affect B version and vice versa. Here version_a1 should be distinct progression from version_a0,
    // version_b1 from version_b0, and they are independent (not sharing same generation counter).
    // We don't assert exact values but ensure they are not equal to initial.
    if version_a1 == version_a0 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A version did not advance after schedule: before {:?} after {:?}",
                version_a0, version_a1
            ),
        );
    }
    if version_b1 == version_b0 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B version did not advance after schedule: before {:?} after {:?}",
                version_b0, version_b1
            ),
        );
    }

    // 3. Observe both Timelines' logical status after wakes: both Pending at same due time.
    let status_a_after_schedule =
        match block_on(async { client.timeline_logical_status(target_a).await }) {
            Ok(s) => s,
            Err(e) => {
                return result_fail(
                    descriptor,
                    ctx,
                    expected,
                    format!(
                        "timeline_logical_status A after schedule failed: {:?} - {}",
                        e.code, e.message
                    ),
                );
            }
        };
    let status_b_after_schedule =
        match block_on(async { client.timeline_logical_status(target_b).await }) {
            Ok(s) => s,
            Err(e) => {
                return result_fail(
                    descriptor,
                    ctx,
                    expected,
                    format!(
                        "timeline_logical_status B after schedule failed: {:?} - {}",
                        e.code, e.message
                    ),
                );
            }
        };

    let a_work = status_a_after_schedule
        .works
        .iter()
        .find(|w| w.work_id == work_id_a);
    let b_work = status_b_after_schedule
        .works
        .iter()
        .find(|w| w.work_id == work_id_b);

    match a_work {
        Some(w)
            if w.status == AdminWorkStatus::Pending
                && w.effective_due_world_time == fixed_instant => {}
        Some(w) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "A work not Pending at fixed due: status {:?} due {}",
                    w.status,
                    w.effective_due_world_time.value()
                ),
            );
        }
        None => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "A work {:?} not found in timeline_logical_status works {:?}",
                    work_id_a, status_a_after_schedule.works
                ),
            );
        }
    }
    match b_work {
        Some(w)
            if w.status == AdminWorkStatus::Pending
                && w.effective_due_world_time == fixed_instant => {}
        Some(w) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "B work not Pending at fixed due after schedule: status {:?} due {}",
                    w.status,
                    w.effective_due_world_time.value()
                ),
            );
        }
        None => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "B work {:?} not found in status {:?}",
                    work_id_b, status_b_after_schedule.works
                ),
            );
        }
    }

    if status_a_after_schedule.world_time != fixed_instant {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A world_time after schedule expected {} got {}",
                fixed_instant.value(),
                status_a_after_schedule.world_time.value()
            ),
        );
    }
    if status_b_after_schedule.world_time != fixed_instant {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B world_time after schedule expected {} got {}",
                fixed_instant.value(),
                status_b_after_schedule.world_time.value()
            ),
        );
    }
    if status_a_after_schedule.version != version_a1 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A status version mismatch after schedule: status {:?} vs schedule result {:?}",
                status_a_after_schedule.version, version_a1
            ),
        );
    }
    if status_b_after_schedule.version != version_b1 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B status version mismatch after schedule: status {:?} vs schedule result {:?}",
                status_b_after_schedule.version, version_b1
            ),
        );
    }

    // inspect_timeline verification after schedule
    let snap_a_after_schedule = match block_on(async { api.inspect_timeline(target_a).await }) {
        Ok(s) => s,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "inspect_timeline A after schedule failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    let snap_b_after_schedule = match block_on(async { api.inspect_timeline(target_b).await }) {
        Ok(s) => s,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "inspect_timeline B after schedule failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    if snap_a_after_schedule.version != version_a1 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "inspect A version after schedule mismatch: inspect {:?} vs schedule {:?}",
                snap_a_after_schedule.version, version_a1
            ),
        );
    }
    if snap_b_after_schedule.version != version_b1 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "inspect B version after schedule mismatch: inspect {:?} vs schedule {:?}",
                snap_b_after_schedule.version, version_b1
            ),
        );
    }
    if snap_a_after_schedule.world_time != fixed_instant
        || snap_b_after_schedule.world_time != fixed_instant
    {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "inspect world_time after schedule mismatch: A {} B {} expected {}",
                snap_a_after_schedule.world_time.value(),
                snap_b_after_schedule.world_time.value(),
                fixed_instant.value()
            ),
        );
    }

    // history before B's final invoke should contain exactly the bootstrap seed (1 event each)
    let events_a_before = match block_on(async { api.list_events(EventQuery::all(target_a)).await })
    {
        Ok(v) => v,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "list_events A before B invoke failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    let events_b_before = match block_on(async { api.list_events(EventQuery::all(target_b)).await })
    {
        Ok(v) => v,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "list_events B before invoke failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    if events_a_before.len() != 1 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A history before B final invoke expected 1 bootstrap event, got {}",
                events_a_before.len()
            ),
        );
    }
    if events_b_before.len() != 1 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B history before final invoke expected 1 bootstrap event, got {}",
                events_b_before.len()
            ),
        );
    }
    if events_a_before[0].id != bootstrap_event_a {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A bootstrap event mismatch: expected {:?} got {:?}",
                bootstrap_event_a, events_a_before[0].id
            ),
        );
    }
    if events_b_before[0].id != bootstrap_event_b {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B bootstrap event mismatch: expected {:?} got {:?}",
                bootstrap_event_b, events_b_before[0].id
            ),
        );
    }

    // 4. Only on Timeline B commit deterministic neutral.counter.seed
    let entity_b = new_entity_id();
    let event_seed_b = new_event_id();
    let invoke_b = ActionRequest::new(
        target_b,
        ActionInvocation::new(
            ActionTypeId::from("neutral.counter.seed"),
            json!({
                "event_id": event_seed_b.to_string(),
                "entity_id": entity_b.to_string(),
                "value": 1,
            }),
        ),
    );
    let invoke_res_b = match block_on(async { api.invoke(invoke_b).await }) {
        Ok(r) => r,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!("invoke B seed failed: {:?} - {}", e.code, e.message),
            );
        }
    };
    let (event_ids_b, version_b2) = match invoke_res_b {
        ExecutionResult::Committed {
            event_ids,
            timeline_version,
        } => (event_ids, timeline_version),
        other => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!("B seed not committed: {:?}", other),
            );
        }
    };
    if event_ids_b.is_empty() {
        return result_fail(
            descriptor,
            ctx,
            expected,
            "B seed committed but no event_ids".to_string(),
        );
    }

    // version must advance after commit
    if version_b2 == version_b1 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B version did not advance after commit: before {:?} after {:?}",
                version_b1, version_b2
            ),
        );
    }

    // 5. Observe via formal reads: A still Pending, B committed, per-Timeline independence.

    // A logical status after B commit — must remain Pending and unchanged
    let status_a_after_b = match block_on(async { client.timeline_logical_status(target_a).await })
    {
        Ok(s) => s,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "timeline_logical_status A after B commit failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    let a_work_after = status_a_after_b
        .works
        .iter()
        .find(|w| w.work_id == work_id_a);
    match a_work_after {
        Some(w)
            if w.status == AdminWorkStatus::Pending
                && w.effective_due_world_time == fixed_instant => {}
        Some(w) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "A work after B commit not still Pending: status {:?} due {}",
                    w.status,
                    w.effective_due_world_time.value()
                ),
            );
        }
        None => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "A work missing after B commit: {:?}",
                    status_a_after_b.works
                ),
            );
        }
    }
    if status_a_after_b.version != version_a1 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A version changed after B commit (cross-timeline serialization): before {:?} after {:?}",
                version_a1, status_a_after_b.version
            ),
        );
    }
    if status_a_after_b.world_time != fixed_instant {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A world_time changed after B commit: {}",
                status_a_after_b.world_time.value()
            ),
        );
    }

    // B logical status after commit — work still Pending (wake not executed), version advanced, world_time still fixed_instant
    let status_b_after = match block_on(async { client.timeline_logical_status(target_b).await }) {
        Ok(s) => s,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "timeline_logical_status B after commit failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    let b_work_after = status_b_after.works.iter().find(|w| w.work_id == work_id_b);
    match b_work_after {
        Some(w)
            if w.status == AdminWorkStatus::Pending
                && w.effective_due_world_time == fixed_instant => {}
        Some(w) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "B work after commit not Pending at fixed due: status {:?} due {}",
                    w.status,
                    w.effective_due_world_time.value()
                ),
            );
        }
        None => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!("B work missing after commit: {:?}", status_b_after.works),
            );
        }
    }
    if status_b_after.version != version_b2 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B status version after commit mismatch: status {:?} vs commit {:?}",
                status_b_after.version, version_b2
            ),
        );
    }
    if status_b_after.world_time != fixed_instant {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B world_time after commit changed: {}",
                status_b_after.world_time.value()
            ),
        );
    }

    let snap_a_final = match block_on(async { api.inspect_timeline(target_a).await }) {
        Ok(s) => s,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "inspect_timeline A final failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    let snap_b_final = match block_on(async { api.inspect_timeline(target_b).await }) {
        Ok(s) => s,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!(
                    "inspect_timeline B final failed: {:?} - {}",
                    e.code, e.message
                ),
            );
        }
    };
    if snap_a_final.version != version_a1 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A inspect version final mismatch vs independent commit: A {:?} expected {:?}",
                snap_a_final.version, version_a1
            ),
        );
    }
    if snap_b_final.version != version_b2 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B inspect version final mismatch: inspect {:?} vs commit {:?}",
                snap_b_final.version, version_b2
            ),
        );
    }
    if snap_b_final.world_time != fixed_instant || snap_a_final.world_time != fixed_instant {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "inspect world_time final mismatch: A {} B {}",
                snap_a_final.world_time.value(),
                snap_b_final.world_time.value()
            ),
        );
    }

    // History: A has exactly its bootstrap event, B has bootstrap + final commit (2 events)
    let events_a_final = match block_on(async { api.list_events(EventQuery::all(target_a)).await })
    {
        Ok(v) => v,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!("list_events A final failed: {:?} - {}", e.code, e.message),
            );
        }
    };
    let events_b_final = match block_on(async { api.list_events(EventQuery::all(target_b)).await })
    {
        Ok(v) => v,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!("list_events B final failed: {:?} - {}", e.code, e.message),
            );
        }
    };
    if events_a_final.len() != 1 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A history after B commit expected 1 bootstrap event, got {}",
                events_a_final.len()
            ),
        );
    }
    if events_a_final[0].id != bootstrap_event_a {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A final history bootstrap mismatch: expected {:?} got {:?}",
                bootstrap_event_a, events_a_final[0].id
            ),
        );
    }
    if events_b_final.len() != 2 {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B history after commit expected 2 events (bootstrap+final), got {}",
                events_b_final.len()
            ),
        );
    }
    // Ensure bootstrap is first, final is second and ordering by EventSeq is preserved
    if events_b_final[0].id != bootstrap_event_b {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B history first event should be bootstrap {:?} got {:?}",
                bootstrap_event_b, events_b_final[0].id
            ),
        );
    }
    let b_event_found = events_b_final
        .iter()
        .any(|e| event_ids_b.contains(&e.id) || e.id == event_seed_b);
    if !b_event_found {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B committed final event not in history: expected {:?} found {:?}",
                event_ids_b,
                events_b_final.iter().map(|e| e.id).collect::<Vec<_>>()
            ),
        );
    }
    // Ensure the final event is the second entry and matches expected final seed
    if events_b_final[1].id != event_seed_b && !event_ids_b.contains(&events_b_final[1].id) {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B final history second event mismatch: expected {:?} got {:?}",
                event_seed_b, events_b_final[1].id
            ),
        );
    }
    // Verify ordering by EventSeq (implicit) — single event is ordered
    // Also verify list_events_page matches list_events
    let page_b = match block_on(async { api.list_events_page(EventQuery::all(target_b)).await }) {
        Ok(p) => p,
        Err(e) => {
            return result_fail(
                descriptor,
                ctx,
                expected,
                format!("list_events_page B failed: {:?} - {}", e.code, e.message),
            );
        }
    };
    if page_b.events.len() != events_b_final.len() {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B list_events_page len {} vs list_events len {}",
                page_b.events.len(),
                events_b_final.len()
            ),
        );
    }

    // Ensure A history does NOT contain B's event (timeline isolation)
    if events_a_final.iter().any(|e| event_ids_b.contains(&e.id)) {
        return result_fail(
            descriptor,
            ctx,
            expected,
            "A history contains B's event — timeline isolation violated".to_string(),
        );
    }

    // Ensure B's logical_commit_count incremented (when available)
    if status_b_after.logical_commit_count <= status_b_after_schedule.logical_commit_count {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "B logical_commit_count not incremented after commit: before {} after {}",
                status_b_after_schedule.logical_commit_count, status_b_after.logical_commit_count
            ),
        );
    }
    if status_a_after_b.logical_commit_count != status_a_after_schedule.logical_commit_count {
        return result_fail(
            descriptor,
            ctx,
            expected,
            format!(
                "A logical_commit_count changed after B commit (global serialization): before {} after {}",
                status_a_after_schedule.logical_commit_count, status_a_after_b.logical_commit_count
            ),
        );
    }

    let actual = format!(
        "independent timelines verified: fixed_instant={}, A target={:?} version {:?}->{:?} work {:?} Pending due={}, B target={:?} version {:?}->{:?}->commit {:?} work {:?} Pending due={}, B event {:?} in history len {}, A history len {} preserved, A logical_commit_count {} stable, B {}->{}",
        fixed_instant.value(),
        target_a,
        version_a0,
        version_a1,
        work_id_a,
        fixed_instant.value(),
        target_b,
        version_b0,
        version_b1,
        version_b2,
        work_id_b,
        fixed_instant.value(),
        event_ids_b,
        events_b_final.len(),
        events_a_final.len(),
        status_a_after_schedule.logical_commit_count,
        status_b_after_schedule.logical_commit_count,
        status_b_after.logical_commit_count,
    );
    result_pass(descriptor, ctx, expected, &actual)
}
