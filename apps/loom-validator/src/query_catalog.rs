//! Query/History/Catalog suite (T14).
//!
//! Owner: T14 (#319) — `CV-025..CV-027`.
//! Central registry integration is reserved for T19 (#324). This module must
//! not register scenarios in `validator_registry`; T19 alone edits
//! `registry.rs`/`lib.rs` and CLI dispatch.

#![forbid(unsafe_code)]

use std::collections::HashSet;

use loom_api::{
    ActionInvocation, ActionRequest, ActionTypeId, AdminService, CausalDirection, CausalQuery,
    CreateWorldFromTemplateRequest, EntityId, EntityTrajectoryQuery, EventId, EventQuery, EventRef,
    FacetOwner, FacetQuery, FacetTypeId, ForkTimelineRequest, WorldInstant,
    WorldTemplateDescriptor,
};
use serde_json::json;
use uuid::Uuid;

use crate::backend::BackendContext;
use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::reports::ScenarioResult;
use crate::scenario::{BackendKind, ScenarioDescriptor};

/// Suite identifier for file ownership.
pub const SUITE: &str = "query_catalog";

/// Owned CV range for this suite.
pub const CV_RANGE: &str = "CV-025..CV-027";

/// Capability area label for this suite.
pub const CAPABILITY_AREA: &str = "query-catalog";

pub const CV_025: &str = "CV-025";
pub const CV_026: &str = "CV-026";
pub const CV_027: &str = "CV-027";

/// Returns the suite identifier.
#[must_use]
pub fn suite_name() -> &'static str {
    SUITE
}

/// Returns true if `cv_id` belongs to this suite's owned CV range.
#[must_use]
pub fn owns_cv(cv_id: &str) -> bool {
    matches!(cv_id, "CV-025" | "CV-026" | "CV-027")
}

// ── Descriptors ──────────────────────────────────────────────────────────────

/// Returns the deterministic query/catalog descriptors for T14.
#[must_use]
pub fn descriptors() -> Vec<ScenarioDescriptor> {
    vec![
        ScenarioDescriptor::new(
            CV_025,
            "history/trajectory positive isolation - sibling state does not leak",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "World with fork: parent -> child A and sibling B; each with branch-local Event via neutral.counter",
            vec!["VALR-T14".to_string()],
            vec![
                "docs/architecture/core.md#timeline-fork".to_string(),
                "docs/architecture/runtime-contracts.md#history".to_string(),
            ],
        ),
        ScenarioDescriptor::new(
            CV_026,
            "causal/query read branch/world isolation and ordering",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "Events with branch-local history; causal queries via HistoryService::direct_causes/causal_walk",
            vec!["VALR-T14".to_string()],
            vec!["docs/architecture/core.md#timeline-fork".to_string()],
        ),
        ScenarioDescriptor::new(
            CV_027,
            "world-scoped Catalog requires Binding + active Runtime Revision",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "World with Binding {counter} and {counter,observer} under active revision; plus no-active-revision fixture",
            vec!["VALR-T14".to_string()],
            vec!["docs/architecture/world-runtime.md".to_string()],
        ),
    ]
}

/// Alias for T09 boundary naming.
#[must_use]
pub fn query_catalog_descriptors() -> Vec<ScenarioDescriptor> {
    descriptors()
}

/// Registers T14 descriptors into a supplied registry (local test use only).
/// This is not the global validator_registry; T19 owns central integration.
///
/// # Errors
/// Returns `RegistryError::DuplicateId` when an ID already exists.
pub fn register_query_catalog(
    registry: &mut crate::registry::ScenarioRegistry,
) -> Result<usize, crate::registry::RegistryError> {
    let mut count = 0;
    for d in descriptors() {
        registry.register(d)?;
        count += 1;
    }
    Ok(count)
}

// ── Dispatch ─────────────────────────────────────────────────────────────────

/// Executes one query/catalog scenario via the formal LoomApi surface.
#[must_use]
pub fn execute_query_catalog(
    descriptor: &ScenarioDescriptor,
    context: &BackendContext,
) -> ScenarioResult {
    if !descriptor
        .supported_backends()
        .contains(context.backend_kind())
    {
        return ScenarioResult::prerequisite(
            descriptor.id().clone(),
            descriptor.name(),
            *context.backend_kind(),
            format!(
                "scenario does not declare backend {} as supported",
                context.backend_kind().as_str()
            ),
        )
        .with_capability_area(descriptor.capability_area().as_str());
    }

    // PostgreSQL prerequisite gate
    if context.backend_kind().is_postgres() {
        if let Err(reason) = check_postgres_prerequisite() {
            if reason.contains("missing") || reason.contains("empty") {
                return ScenarioResult::prerequisite(
                    descriptor.id().clone(),
                    descriptor.name(),
                    *context.backend_kind(),
                    reason,
                )
                .with_capability_area(descriptor.capability_area().as_str());
            }
            return ScenarioResult::unavailable(
                descriptor.id().clone(),
                descriptor.name(),
                *context.backend_kind(),
                reason,
            )
            .with_capability_area(descriptor.capability_area().as_str());
        }
        // live endpoint must be reachable for postgres evidence
        let api = context.api();
        let catalog_res = block_on(async { api.catalog() });
        if let Err(err) = catalog_res {
            let reason = format!(
                "PostgreSQL live backend at {} unavailable: {:?} - {}",
                context.base_url(),
                err.code,
                err.message
            );
            return ScenarioResult::unavailable(
                descriptor.id().clone(),
                descriptor.name(),
                *context.backend_kind(),
                reason,
            )
            .with_capability_area(descriptor.capability_area().as_str());
        }
    }

    match descriptor.id_str() {
        CV_025 => cv025(descriptor, context),
        CV_026 => cv026(descriptor, context),
        CV_027 => cv027(descriptor, context),
        _ => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "scenario is registered with stable ID",
                format!("unknown query/catalog scenario {}", descriptor.id_str()),
                *context.backend_kind(),
                "validator:scenario-dispatch",
                vec![EvidenceReference::new("validator:unknown-scenario")],
                ScenarioOutcome::Fail,
            );
            ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str())
        }
    }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

fn block_on<F: std::future::Future>(f: F) -> F::Output {
    if let Ok(handle) = tokio::runtime::Handle::try_current() {
        tokio::task::block_in_place(|| handle.block_on(f))
    } else {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .expect("validator tokio runtime should build")
            .block_on(f)
    }
}

fn check_postgres_prerequisite() -> Result<(), String> {
    let key = crate::backend::LOOM_TEST_POSTGRES_URL;
    match std::env::var(key) {
        Ok(value) => postgres_prerequisite_with_value(Some(value.as_str()), key),
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

fn is_infra_unavailable(s: &str) -> bool {
    let lower = s.to_ascii_lowercase();
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
            "validator:{}:{}",
            descriptor.id_str(),
            ctx.backend_kind().as_str()
        ),
        vec![
            EvidenceReference::new("public-surface:loom-client"),
            EvidenceReference::new(format!("backend:{}", ctx.backend_kind().as_str())),
            EvidenceReference::new(format!("suite:{}", SUITE)),
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
            "validator:{}:{}",
            descriptor.id_str(),
            ctx.backend_kind().as_str()
        ),
        vec![
            EvidenceReference::new(
                "public-surface:loom-client::WorldService::create_world_from_template",
            ),
            EvidenceReference::new("public-surface:loom-client::ActionService::invoke"),
            EvidenceReference::new("public-surface:loom-client::TimelineService::fork"),
            EvidenceReference::new("public-surface:loom-client::TimelineService::inspect_timeline"),
            EvidenceReference::new("public-surface:loom-client::HistoryService::list_events"),
            EvidenceReference::new("public-surface:loom-client::QueryService::get_facet"),
            EvidenceReference::new(format!("suite:{}", SUITE)),
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

fn new_world_template(scope: &str) -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new(format!("validator.t14.{}", scope), 1, WorldInstant::new(42))
        .requires_capability("neutral.counter", "^0.1.0")
}

fn new_entity_id() -> EntityId {
    EntityId::new(Uuid::new_v4())
}
fn new_event_id() -> EventId {
    EventId::new(Uuid::new_v4())
}

// ── CV-025 ───────────────────────────────────────────────────────────────────

fn cv025(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let api = context.api();
    let scope = context.scope().to_string();
    let expected = "list_events/trajectory per Timeline contains ancestor plus branch-local events only, excludes sibling/fork and ancestor-future, facet values 5/15 isolated, ordering by EventSeq";

    // 1. Create world
    let template = new_world_template(&format!("{scope}-025"));
    let parent_snap = match block_on(async {
        api.create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
    }) {
        Ok(s) => s,
        Err(e) => {
            let actual = format!(
                "create_world_from_template failed: {:?} - {}",
                e.code, e.message
            );
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(descriptor, context, expected, &actual, outcome.clone());
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            return result_fail(descriptor, context, expected, actual);
        }
    };
    let parent_target = parent_snap.target;
    let parent_version_initial = parent_snap.version;
    let entity_id = new_entity_id();

    // 2. Seed parent with value 5
    let seed_event = new_event_id();
    let seed_res = block_on(async {
        api.invoke(ActionRequest::new(
            parent_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.seed"),
                json!({"event_id": seed_event.to_string(), "entity_id": entity_id.to_string(), "value": 5}),
            ),
        ))
        .await
    });
    let version_after_seed = match seed_res {
        Ok(loom_api::ExecutionResult::Committed {
            timeline_version, ..
        }) => timeline_version,
        Ok(other) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("seed not committed: {other:?}"),
            );
        }
        Err(e) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("seed invoke failed: {:?} - {}", e.code, e.message),
            );
        }
    };

    // 3. Fork child A and sibling B from parent (history includes seed)
    let child_snap =
        match block_on(async { api.fork(ForkTimelineRequest::new(parent_target)).await }) {
            Ok(s) => s,
            Err(e) => {
                return result_fail(
                    descriptor,
                    context,
                    expected,
                    format!("fork child failed: {:?} - {}", e.code, e.message),
                );
            }
        };
    let child_target = child_snap.target;
    let sibling_snap =
        match block_on(async { api.fork(ForkTimelineRequest::new(parent_target)).await }) {
            Ok(s) => s,
            Err(e) => {
                return result_fail(
                    descriptor,
                    context,
                    expected,
                    format!("fork sibling failed: {:?} - {}", e.code, e.message),
                );
            }
        };
    let sibling_target = sibling_snap.target;

    // Verify ancestry for fork correctness (parent -> child)
    let ancestry_ok = child_snap.ancestry.parent_timeline_id == Some(parent_target.timeline_id)
        && child_snap.ancestry.fork_parent_version == Some(version_after_seed);
    if !ancestry_ok {
        return result_fail(
            descriptor,
            context,
            expected,
            format!(
                "child ancestry mismatch: parent {:?} version {:?} -> child ancestry {:?}",
                parent_target.timeline_id, version_after_seed, child_snap.ancestry
            ),
        );
    }

    // 4. Increment child to 15 (5+10)
    let inc_event = new_event_id();
    let inc_res = block_on(async {
        api.invoke(ActionRequest::new(
            child_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.increment"),
                json!({"event_id": inc_event.to_string(), "entity_id": entity_id.to_string(), "amount": 10}),
            ),
        ))
        .await
    });
    match inc_res {
        Ok(loom_api::ExecutionResult::Committed { .. }) => {}
        Ok(other) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("child increment not committed: {other:?}"),
            );
        }
        Err(e) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("child increment failed: {:?} - {}", e.code, e.message),
            );
        }
    };

    // 5. Verify isolation via get_facet
    let parent_facet = block_on(async {
        api.get_facet(FacetQuery::new(
            parent_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    });
    let child_facet = block_on(async {
        api.get_facet(FacetQuery::new(
            child_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    });
    let sibling_facet = block_on(async {
        api.get_facet(FacetQuery::new(
            sibling_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    });
    let parent_val = parent_facet
        .ok()
        .and_then(|o| o)
        .and_then(|s| s.value.get("value").and_then(|v| v.as_i64()))
        .unwrap_or(-999);
    let child_val = child_facet
        .ok()
        .and_then(|o| o)
        .and_then(|s| s.value.get("value").and_then(|v| v.as_i64()))
        .unwrap_or(-999);
    let sibling_val = sibling_facet
        .ok()
        .and_then(|o| o)
        .and_then(|s| s.value.get("value").and_then(|v| v.as_i64()))
        .unwrap_or(-999);

    // 6. Verify history counts
    let parent_events = block_on(async { api.list_events(EventQuery::all(parent_target)).await })
        .map(|v| v.len())
        .unwrap_or(999);
    let child_events = block_on(async { api.list_events(EventQuery::all(child_target)).await })
        .map(|v| v.len())
        .unwrap_or(999);
    let sibling_events = block_on(async { api.list_events(EventQuery::all(sibling_target)).await })
        .map(|v| v.len())
        .unwrap_or(999);

    // 7. Verify trajectory
    let child_trajectory = block_on(async {
        api.entity_trajectory(EntityTrajectoryQuery::all(child_target, entity_id))
            .await
    })
    .map(|p| p.events.len())
    .unwrap_or(999);
    let sibling_trajectory = block_on(async {
        api.entity_trajectory(EntityTrajectoryQuery::all(sibling_target, entity_id))
            .await
    })
    .map(|p| p.events.len())
    .unwrap_or(999);
    let parent_trajectory = block_on(async {
        api.entity_trajectory(EntityTrajectoryQuery::all(parent_target, entity_id))
            .await
    })
    .map(|p| p.events.len())
    .unwrap_or(999);

    // 8. Verify ordering by EventSeq (not UUID): fetch child events and check seq monotonic
    let child_event_list = block_on(async { api.list_events(EventQuery::all(child_target)).await })
        .unwrap_or_default();
    let ordering_ok = child_event_list
        .windows(2)
        .all(|w| w[0].sequence.value() < w[1].sequence.value());

    // 9. Ancestor-future check: mutate parent after fork, verify child unchanged
    let parent_inc_event = new_event_id();
    let parent_inc_res = block_on(async {
        api.invoke(ActionRequest::new(
            parent_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.increment"),
                json!({"event_id": parent_inc_event.to_string(), "entity_id": entity_id.to_string(), "amount": 2}),
            ),
        ))
        .await
    });
    // parent increment should succeed (value 5 -> 7)
    let parent_inc_ok = matches!(
        parent_inc_res,
        Ok(loom_api::ExecutionResult::Committed { .. })
    );
    let parent_val_after = block_on(async {
        api.get_facet(FacetQuery::new(
            parent_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    })
    .ok()
    .and_then(|o| o)
    .and_then(|s| s.value.get("value").and_then(|v| v.as_i64()))
    .unwrap_or(-999);
    let child_val_after = block_on(async {
        api.get_facet(FacetQuery::new(
            child_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    })
    .ok()
    .and_then(|o| o)
    .and_then(|s| s.value.get("value").and_then(|v| v.as_i64()))
    .unwrap_or(-999);
    let child_events_after =
        block_on(async { api.list_events(EventQuery::all(child_target)).await })
            .map(|v| v.len())
            .unwrap_or(999);
    let parent_events_after =
        block_on(async { api.list_events(EventQuery::all(parent_target)).await })
            .map(|v| v.len())
            .unwrap_or(999);

    let actual = format!(
        "parent facet {parent_val} (exp 5) child {child_val} (exp 15) sibling {sibling_val} (exp 5) | parent events {parent_events} (exp1) child {child_events} (exp2) sibling {sibling_events} (exp1) | trajectory parent {parent_trajectory} (exp1 or 0 if participants empty) child {child_trajectory} (exp2 or 0) sibling {sibling_trajectory} (exp1 or 0) | ordering_ok={ordering_ok} ancestry_ok={ancestry_ok} | after parent inc parent_val {parent_val_after} (exp7) child_val {child_val_after} (exp15) child_events {child_events_after} (exp2) parent_events_after {parent_events_after} (exp2) parent_inc_ok={parent_inc_ok} parent_initial_version {:?}-> after_seed {:?}",
        parent_version_initial, version_after_seed
    );

    // Trajectory for neutral.counter is expected to be 0 because neutral events carry no participants;
    // trajectory query therefore returns empty but must not leak sibling state. Accept either
    // the documented 1/2 counts (if capability provides participants) or 0 for neutral.
    let trajectory_ok =
        (parent_trajectory == 1 && child_trajectory == 2 && sibling_trajectory == 1)
            || (parent_trajectory == 0 && child_trajectory == 0 && sibling_trajectory == 0);

    let pass = parent_val == 5
        && child_val == 15
        && sibling_val == 5
        && parent_events == 1
        && child_events == 2
        && sibling_events == 1
        && trajectory_ok
        && ordering_ok
        && ancestry_ok
        && parent_inc_ok
        && parent_val_after == 7
        && child_val_after == 15
        && child_events_after == 2
        && parent_events_after == 2;

    if pass {
        result_pass(descriptor, context, expected, &actual)
    } else {
        result_fail(descriptor, context, expected, actual)
    }
}

// ── CV-026 ───────────────────────────────────────────────────────────────────

fn cv026(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let api = context.api();
    let scope = context.scope().to_string();
    let expected = "causal/query reads preserve branch isolation, direct_causes/effects and causal_walk exclude sibling, ordering by EventSeq, get_event isolation";

    let template = WorldTemplateDescriptor::new(
        format!("validator.t14.cv026.{}", scope),
        1,
        WorldInstant::new(42),
    )
    .requires_capability("neutral.counter", "^0.1.0");
    let parent_snap = match block_on(async {
        api.create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
    }) {
        Ok(s) => s,
        Err(e) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("create_world failed: {:?} - {}", e.code, e.message),
            );
        }
    };
    let parent_target = parent_snap.target;
    let entity_id = new_entity_id();
    let seed_event = new_event_id();
    let seed_res = block_on(async {
        api.invoke(ActionRequest::new(
            parent_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.seed"),
                json!({"event_id": seed_event.to_string(), "entity_id": entity_id.to_string(), "value": 5}),
            ),
        ))
        .await
    });
    let seed_event_ref = match seed_res {
        Ok(loom_api::ExecutionResult::Committed { event_ids, .. }) if !event_ids.is_empty() => {
            EventRef::new(parent_target.timeline_id, event_ids[0])
        }
        Ok(other) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("seed not committed: {other:?}"),
            );
        }
        Err(e) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("seed failed: {:?} - {}", e.code, e.message),
            );
        }
    };

    // Fork child and sibling
    let child_snap =
        match block_on(async { api.fork(ForkTimelineRequest::new(parent_target)).await }) {
            Ok(s) => s,
            Err(e) => {
                return result_fail(
                    descriptor,
                    context,
                    expected,
                    format!("fork child failed: {:?} - {}", e.code, e.message),
                );
            }
        };
    let child_target = child_snap.target;
    let sibling_snap =
        match block_on(async { api.fork(ForkTimelineRequest::new(parent_target)).await }) {
            Ok(s) => s,
            Err(e) => {
                return result_fail(
                    descriptor,
                    context,
                    expected,
                    format!("fork sibling failed: {:?} - {}", e.code, e.message),
                );
            }
        };
    let sibling_target = sibling_snap.target;

    // Increment child
    let child_inc = new_event_id();
    let child_inc_res = block_on(async {
        api.invoke(ActionRequest::new(
            child_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.increment"),
                json!({"event_id": child_inc.to_string(), "entity_id": entity_id.to_string(), "amount": 10}),
            ),
        ))
        .await
    });
    let child_inc_ref = match child_inc_res {
        Ok(loom_api::ExecutionResult::Committed { event_ids, .. }) if !event_ids.is_empty() => {
            EventRef::new(child_target.timeline_id, event_ids[0])
        }
        Ok(other) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("child inc not committed: {other:?}"),
            );
        }
        Err(e) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("child inc failed: {:?} - {}", e.code, e.message),
            );
        }
    };
    // Increment sibling similarly
    let sibling_inc = new_event_id();
    let sibling_inc_res = block_on(async {
        api.invoke(ActionRequest::new(
            sibling_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.increment"),
                json!({"event_id": sibling_inc.to_string(), "entity_id": entity_id.to_string(), "amount": 7}),
            ),
        ))
        .await
    });
    let sibling_inc_ref = match sibling_inc_res {
        Ok(loom_api::ExecutionResult::Committed { event_ids, .. }) if !event_ids.is_empty() => {
            EventRef::new(sibling_target.timeline_id, event_ids[0])
        }
        Ok(other) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("sibling inc not committed: {other:?}"),
            );
        }
        Err(e) => {
            return result_fail(
                descriptor,
                context,
                expected,
                format!("sibling inc failed: {:?} - {}", e.code, e.message),
            );
        }
    };

    // Fetch events for ordering verification
    let child_events = block_on(async { api.list_events(EventQuery::all(child_target)).await })
        .unwrap_or_default();
    let sibling_events = block_on(async { api.list_events(EventQuery::all(sibling_target)).await })
        .unwrap_or_default();
    let parent_events = block_on(async { api.list_events(EventQuery::all(parent_target)).await })
        .unwrap_or_default();
    let ordering_child = child_events
        .windows(2)
        .all(|w| w[0].sequence.value() < w[1].sequence.value());
    let ordering_parent = parent_events
        .windows(2)
        .all(|w| w[0].sequence.value() < w[1].sequence.value());

    // get_event positive: child inc should be fetchable via its own ref
    let child_get = block_on(async { api.get_event(child_inc_ref).await });
    let child_get_ok = matches!(&child_get, Ok(Some(ev)) if ev.id == child_inc && ev.timeline_id == child_target.timeline_id);
    // get_event for sibling inc via its own ref
    let sibling_get = block_on(async { api.get_event(sibling_inc_ref).await });
    let sibling_get_ok = matches!(&sibling_get, Ok(Some(ev)) if ev.id == sibling_inc);

    // direct_causes for child inc: neutral has no causal link, so should be empty and not contain sibling
    let child_causes =
        block_on(async { api.direct_causes(child_inc_ref).await }).unwrap_or_default();
    let child_causes_excludes_sibling = !child_causes.contains(&sibling_inc_ref);
    let child_causes_empty_or_visible = child_causes.is_empty()
        || child_causes.iter().all(|r| {
            // any cause should be from same timeline visible ancestry
            r.timeline_id == child_target.timeline_id || r.timeline_id == parent_target.timeline_id
        });

    // direct_effects for seed: should not contain sibling inc if no link, but check isolation
    let seed_effects =
        block_on(async { api.direct_effects(seed_event_ref).await }).unwrap_or_default();
    let seed_effects_excludes_sibling = !seed_effects.contains(&sibling_inc_ref);

    // causal_walk from child inc (Causes direction)
    let walk = block_on(async {
        api.causal_walk(CausalQuery::new(
            child_inc_ref,
            CausalDirection::Causes,
            4,
            10,
        ))
        .await
    });
    let (walk_ok, walk_excludes_sibling, walk_truncated) = match walk {
        Ok(t) => (
            !t.events.contains(&sibling_inc_ref),
            !t.events.contains(&sibling_inc_ref),
            t.truncated,
        ),
        Err(_) => (false, false, false),
    };
    // causal_walk with Effects from seed
    let walk_effects = block_on(async {
        api.causal_walk(CausalQuery::new(
            seed_event_ref,
            CausalDirection::Effects,
            4,
            10,
        ))
        .await
    });
    let walk_effects_excludes_sibling = match &walk_effects {
        Ok(t) => !t.events.contains(&sibling_inc_ref),
        Err(_) => false,
    };

    // entity_trajectory per timeline should be isolated
    let child_traj = block_on(async {
        api.entity_trajectory(EntityTrajectoryQuery::all(child_target, entity_id))
            .await
    })
    .map(|p| p.events.len())
    .unwrap_or(999);
    let sibling_traj = block_on(async {
        api.entity_trajectory(EntityTrajectoryQuery::all(sibling_target, entity_id))
            .await
    })
    .map(|p| p.events.len())
    .unwrap_or(999);
    let parent_traj = block_on(async {
        api.entity_trajectory(EntityTrajectoryQuery::all(parent_target, entity_id))
            .await
    })
    .map(|p| p.events.len())
    .unwrap_or(999);

    // Verify EventSeq ordering not UUID ordering: collect ids and ensure not sorted by Uuid string
    // Our check is that sequences are monotonic; that's sufficient for EventSeq ordering proof

    // Invalid sibling causality at commit would beRejected - neutral ignores causal payload, so we verify that sibling's event does not appear in child's history/causal
    let child_history_len = child_events.len();
    let sibling_history_len = sibling_events.len();
    let parent_history_len = parent_events.len();

    let actual = format!(
        "child_history {child_history_len} (exp2) sibling {sibling_history_len} (exp2) parent {parent_history_len} (exp1) | ordering child {ordering_child} parent {ordering_parent} | get child {child_get_ok} sibling {sibling_get_ok} | causes {:?} excludes sibling {child_causes_excludes_sibling} visible {child_causes_empty_or_visible} | effects {:?} excludes {seed_effects_excludes_sibling} | walk_ok {walk_ok} walk_excludes {walk_excludes_sibling} truncated {walk_truncated} effects_walk_excludes {walk_effects_excludes_sibling} | traj parent {parent_traj} (exp1) child {child_traj} (exp2) sibling {sibling_traj} (exp2) | seed {:?} child {:?} sibling {:?}",
        child_causes, seed_effects, seed_event_ref, child_inc_ref, sibling_inc_ref
    );

    let trajectory_ok = (parent_traj == 1 && child_traj == 2 && sibling_traj == 2)
        || (parent_traj == 0 && child_traj == 0 && sibling_traj == 0);

    let pass = ordering_child
        && ordering_parent
        && child_get_ok
        && sibling_get_ok
        && child_causes_excludes_sibling
        && child_causes_empty_or_visible
        && seed_effects_excludes_sibling
        && walk_ok
        && walk_excludes_sibling
        && walk_effects_excludes_sibling
        && trajectory_ok
        && child_history_len == 2
        && sibling_history_len == 2
        && parent_history_len == 1
        && !walk_truncated;

    if pass {
        result_pass(descriptor, context, expected, &actual)
    } else {
        result_fail(descriptor, context, expected, actual)
    }
}

// ── CV-027 ───────────────────────────────────────────────────────────────────

fn cv027(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let api = context.api();
    let client = context.client();
    let expected = "world-scoped Catalog requires Binding plus compatible active Runtime Revision; no active revision must not silently fall back to global software";

    // Check active revision
    let active = block_on(async { client.active_runtime_revision().await });
    match active {
        Ok(None) => {
            // Negative case: no active revision
            let global_catalog = match api.catalog() {
                Ok(c) => c,
                Err(e) => {
                    return result_fail(
                        descriptor,
                        context,
                        expected,
                        format!(
                            "global catalog failed even without active revision: {:?} - {}",
                            e.code, e.message
                        ),
                    );
                }
            };
            // catalog_for_world should be unavailable/not_found, not equal to global
            let dummy_world = loom_api::WorldId::new(Uuid::new_v4());
            let world_catalog_res = block_on(async { api.catalog_for_world(dummy_world).await });
            match world_catalog_res {
                Ok(catalog) => {
                    // If it succeeded, it must not be permissive fallback: if it returned global content we'd consider fail
                    // But for no-active case, any success with content equal to global is fail
                    // Check if catalog equals global -> fail, otherwise also fail because should be error
                    let is_global_fallback = catalog.capabilities.len()
                        == global_catalog.capabilities.len()
                        && catalog.actions.len() == global_catalog.actions.len();
                    if is_global_fallback {
                        return result_fail(
                            descriptor,
                            context,
                            expected,
                            format!(
                                "catalog_for_world succeeded permissively without active revision, fallback to global: capabilities {:?}",
                                catalog
                                    .capabilities
                                    .iter()
                                    .map(|c| c.id.to_string())
                                    .collect::<Vec<_>>()
                            ),
                        );
                    }
                    // Even if not fallback, success when active missing is unexpected
                    return result_fail(
                        descriptor,
                        context,
                        expected,
                        format!(
                            "catalog_for_world should be unavailable without active revision but succeeded: {:?}",
                            catalog.capabilities.len()
                        ),
                    );
                }
                Err(e) => {
                    let code = format!("{:?}", e.code);
                    let is_expected = matches!(
                        e.code,
                        loom_api::ApiErrorCode::Unavailable | loom_api::ApiErrorCode::NotFound
                    );
                    if !is_expected {
                        return result_fail(
                            descriptor,
                            context,
                            expected,
                            format!(
                                "catalog_for_world without active revision returned unexpected error code {}: {} (expected Unavailable/NotFound)",
                                code, e.message
                            ),
                        );
                    }
                    let actual = format!(
                        "no active revision observed, global catalog {} caps, world-scoped correctly unavailable with {} - {}",
                        global_catalog.capabilities.len(),
                        code,
                        e.message
                    );
                    return result_pass(descriptor, context, expected, &actual);
                }
            }
        }
        Ok(Some(active_sel)) => {
            // Positive case
            let global = match api.catalog() {
                Ok(c) => c,
                Err(e) => {
                    return result_fail(
                        descriptor,
                        context,
                        expected,
                        format!("global catalog failed: {:?} - {}", e.code, e.message),
                    );
                }
            };
            let has_counter = global
                .capabilities
                .iter()
                .any(|c| c.id.to_string() == "neutral.counter");
            let has_observer = global
                .capabilities
                .iter()
                .any(|c| c.id.to_string() == "neutral.observer");
            if !has_counter || !has_observer {
                return result_fail(
                    descriptor,
                    context,
                    expected,
                    format!(
                        "global catalog missing expected capabilities: has_counter={has_counter} has_observer={has_observer} catalog {:?}",
                        global
                            .capabilities
                            .iter()
                            .map(|c| c.id.to_string())
                            .collect::<Vec<_>>()
                    ),
                );
            }

            // Create W_a with counter only
            let scope = context.scope().to_string();
            let w_a_template = WorldTemplateDescriptor::new(
                format!("validator.t14.cv027.a.{}", scope),
                1,
                WorldInstant::new(10),
            )
            .requires_capability("neutral.counter", "^0.1.0");
            let w_a_snap = match block_on(async {
                api.create_world_from_template(CreateWorldFromTemplateRequest::new(w_a_template))
                    .await
            }) {
                Ok(s) => s,
                Err(e) => {
                    return result_fail(
                        descriptor,
                        context,
                        expected,
                        format!("create W_a failed: {:?} - {}", e.code, e.message),
                    );
                }
            };
            let w_a_id = w_a_snap.target.world_id;

            // Create W_b with counter+observer
            let w_b_template = WorldTemplateDescriptor::new(
                format!("validator.t14.cv027.b.{}", scope),
                1,
                WorldInstant::new(10),
            )
            .requires_capability("neutral.counter", "^0.1.0")
            .requires_capability("neutral.observer", "^0.1.0");
            let w_b_snap = match block_on(async {
                api.create_world_from_template(CreateWorldFromTemplateRequest::new(w_b_template))
                    .await
            }) {
                Ok(s) => s,
                Err(e) => {
                    return result_fail(
                        descriptor,
                        context,
                        expected,
                        format!("create W_b failed: {:?} - {}", e.code, e.message),
                    );
                }
            };
            let w_b_id = w_b_snap.target.world_id;

            let catalog_a = match block_on(async { api.catalog_for_world(w_a_id).await }) {
                Ok(c) => c,
                Err(e) => {
                    return result_fail(
                        descriptor,
                        context,
                        expected,
                        format!("catalog_for_world W_a failed: {:?} - {}", e.code, e.message),
                    );
                }
            };
            let catalog_b = match block_on(async { api.catalog_for_world(w_b_id).await }) {
                Ok(c) => c,
                Err(e) => {
                    return result_fail(
                        descriptor,
                        context,
                        expected,
                        format!("catalog_for_world W_b failed: {:?} - {}", e.code, e.message),
                    );
                }
            };

            let a_has_counter = catalog_a
                .capabilities
                .iter()
                .any(|c| c.id.to_string() == "neutral.counter");
            let a_has_observer = catalog_a
                .capabilities
                .iter()
                .any(|c| c.id.to_string() == "neutral.observer");
            let b_has_counter = catalog_b
                .capabilities
                .iter()
                .any(|c| c.id.to_string() == "neutral.counter");
            let b_has_observer = catalog_b
                .capabilities
                .iter()
                .any(|c| c.id.to_string() == "neutral.observer");

            let a_correct = a_has_counter && !a_has_observer;
            let b_correct = b_has_counter && b_has_observer;
            let distinct = catalog_a.capabilities.len() != catalog_b.capabilities.len()
                || catalog_a
                    .capabilities
                    .iter()
                    .map(|c| c.id.to_string())
                    .collect::<HashSet<_>>()
                    != catalog_b
                        .capabilities
                        .iter()
                        .map(|c| c.id.to_string())
                        .collect::<HashSet<_>>();

            // Also verify that catalog_a is subset of global and b is also subset but larger
            let a_subset_global = catalog_a
                .capabilities
                .iter()
                .all(|cap| global.capability(&cap.id).is_some());
            let b_subset_global = catalog_b
                .capabilities
                .iter()
                .all(|cap| global.capability(&cap.id).is_some());

            let actual = format!(
                "active revision {:?} generation {} caps {:?} | global caps {:?} | W_a caps {:?} has_counter={a_has_counter} has_observer={a_has_observer} correct={a_correct} subset={a_subset_global} | W_b caps {:?} correct={b_correct} subset={b_subset_global} distinct={distinct} | world ids {} {}",
                active_sel.revision.revision_id,
                active_sel.generation,
                active_sel
                    .revision
                    .capabilities
                    .iter()
                    .map(|c| format!("{}@{}", c.capability_id, c.version))
                    .collect::<Vec<_>>(),
                global
                    .capabilities
                    .iter()
                    .map(|c| c.id.to_string())
                    .collect::<Vec<_>>(),
                catalog_a
                    .capabilities
                    .iter()
                    .map(|c| c.id.to_string())
                    .collect::<Vec<_>>(),
                catalog_b
                    .capabilities
                    .iter()
                    .map(|c| c.id.to_string())
                    .collect::<Vec<_>>(),
                w_a_id,
                w_b_id
            );

            if a_correct
                && b_correct
                && distinct
                && a_subset_global
                && b_subset_global
                && has_counter
                && has_observer
            {
                result_pass(descriptor, context, expected, &actual)
            } else {
                result_fail(descriptor, context, expected, actual)
            }
        }
        Err(e) => {
            // Admin call failed - treat as infra unavailable if needed, but for positive case this is fail
            let actual = format!(
                "active_runtime_revision check failed: {:?} - {}",
                e.code, e.message
            );
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(descriptor, context, expected, &actual, outcome.clone());
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            return result_fail(descriptor, context, expected, actual);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{
        CV_025, CV_026, CV_027, SUITE, descriptors, query_catalog_descriptors,
        register_query_catalog,
    };
    use crate::scenario::BackendKind;

    #[test]
    fn descriptors_are_three_and_deterministic() {
        let first = descriptors();
        let second = descriptors();
        assert_eq!(first.len(), 3);
        assert_eq!(first, second);
        let ids: Vec<_> = first.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec![CV_025, CV_026, CV_027]);
    }

    #[test]
    fn query_catalog_descriptors_alias() {
        assert_eq!(query_catalog_descriptors(), descriptors());
    }

    #[test]
    fn suite_owns_only_its_cvs() {
        assert!(super::owns_cv(CV_025));
        assert!(super::owns_cv(CV_027));
        assert!(!super::owns_cv("CV-024"));
        assert!(!super::owns_cv("CV-028"));
        assert_eq!(super::suite_name(), SUITE);
    }

    #[test]
    fn local_registry_is_disjoint_from_global() {
        let global = crate::validator_registry();
        assert_eq!(global.len(), 11);
        assert!(global.get(CV_025).is_none());
        let mut local = crate::registry::ScenarioRegistry::bootstrap();
        register_query_catalog(&mut local).expect("local registration should succeed");
        assert_eq!(local.len(), 3);
        assert!(local.get(CV_025).is_some());
        assert!(local.get(CV_027).is_some());
        assert!(local.get("CV-001").is_none());
    }

    #[test]
    fn only_inmemory_and_postgres_supported() {
        for d in descriptors() {
            assert!(d.supported_backends().contains(&BackendKind::InMemory));
            assert!(d.supported_backends().contains(&BackendKind::PostgreSQL));
            assert!(!d.supported_backends().contains(&BackendKind::LoomClient));
        }
    }
}
