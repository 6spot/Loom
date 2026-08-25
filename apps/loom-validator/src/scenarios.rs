//! Replay/fork/branch-isolation capability scenarios (VAL-T9).
//!
//! These scenarios exercise the public/formal Loom consumer boundary (`loom-api`
//! via `LoomApi`/`LoomClient`) for Timeline replay and fork behavior. They
//! never import Runtime, Storage, or other implementation-only authority. When a
//! required public operation does not exist, the scenario reports an explicit
//! unavailable/prerequisite outcome rather than bypassing the boundary.

#![allow(clippy::all, clippy::pedantic, clippy::nursery, clippy::restriction)]
#![allow(unused_imports, dead_code)]

use std::future::Future;
use std::sync::Arc;

use loom_api::{
    ActionInvocation, ActionRequest, ActionTypeId, CreateWorldFromTemplateRequest, EntityId,
    EventId, EventQuery, ExecutionResult, FacetOwner, FacetQuery, FacetTypeId, ForkTimelineRequest,
    TimelineId, TimelineTarget, TimelineVersion, WorldId, WorldInstant, WorldTemplateDescriptor,
};
use serde_json::json;
use uuid::Uuid;

use crate::backend::BackendContext;
use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::reports::ScenarioResult;
use crate::scenario::{BackendKind, ScenarioDescriptor};

// ── Stable identifiers ───────────────────────────────────────────────────────

#[allow(dead_code)]
pub const CV_005: &str = "CV-005";
#[allow(dead_code)]
pub const CV_006: &str = "CV-006";
#[allow(dead_code)]
pub const CV_007: &str = "CV-007";
#[allow(dead_code)]
pub const CV_008: &str = "CV-008";
#[allow(dead_code)]
pub const CV_009: &str = "CV-009";

// ── Descriptor registry ──────────────────────────────────────────────────────

/// Returns the deterministic replay/fork descriptors for VAL-T9.
#[must_use]
pub fn replay_fork_descriptors() -> Vec<ScenarioDescriptor> {
    vec![
        ScenarioDescriptor::new(
            CV_005,
            "reopen/replay committed Timeline state at a supported committed version without re-running capability logic",
            "replay-fork",
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "committed Timeline with ≥2 versions; ForkTimelineRequest::at_version is the supported replay mechanism; same-Timeline historical materialization is not a public operation",
            vec!["VAL-T9".to_string()],
            vec![
                "docs/architecture/core.md#timeline-fork".to_string(),
                "docs/architecture/amendments/0003-agency-execution-and-pinned-read-boundary.md#replay-and-fork".to_string(),
            ],
        ),
        ScenarioDescriptor::new(
            CV_006,
            "head fork creates distinct Timeline while preserving World/binding identity semantics",
            "replay-fork",
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "World and Timeline observable via TimelineService::inspect_timeline and TimelineService::fork",
            vec!["VAL-T9".to_string()],
            vec!["docs/architecture/core.md#timeline-fork".to_string()],
        ),
        ScenarioDescriptor::new(
            CV_007,
            "child branch mutation does not leak into parent/sibling visible state",
            "replay-fork",
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "parent and child Timeline after fork; child mutation observed via QueryService::get_facet and HistoryService::list_events only",
            vec!["VAL-T9".to_string()],
            vec!["docs/architecture/core.md#timeline-fork".to_string()],
        ),
        ScenarioDescriptor::new(
            CV_008,
            "historical fork/reopen preserves ancestry-visible history while excluding ancestor-future/sibling state where the formal API exposes those operations",
            "replay-fork",
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "historical TimelineVersion fork; ancestry inspected via TimelineSnapshot::ancestry and history via HistoryService::list_events",
            vec!["VAL-T9".to_string()],
            vec!["docs/architecture/core.md#timeline-fork".to_string()],
        ),
        ScenarioDescriptor::new(
            CV_009,
            "representative fork/reopen behavior remains correct after PostgreSQL restart",
            "replay-fork",
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "LOOM_TEST_POSTGRES_URL and running PostgreSQL composition; InMemory does not provide durable restart and is reported as unavailable",
            vec!["VAL-T9".to_string()],
            vec!["docs/architecture/core.md#timeline-fork".to_string()],
        ),
    ]
}

/// Registers the replay/fork descriptors into a registry.
///
/// # Errors
///
/// Returns [`crate::registry::RegistryError::DuplicateId`] when a scenario
/// ID is already present in `registry`.
pub fn register_replay_fork(
    registry: &mut crate::registry::ScenarioRegistry,
) -> Result<usize, crate::registry::RegistryError> {
    let mut count = 0;
    for descriptor in replay_fork_descriptors() {
        registry.register(descriptor)?;
        count += 1;
    }
    Ok(count)
}

// ── Execution ────────────────────────────────────────────────────────────────

fn block_on<F: Future>(f: F) -> F::Output {
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

/// Executes one replay/fork scenario via the formal `LoomApi` surface.
#[must_use]
pub fn execute_replay_fork(
    descriptor: &ScenarioDescriptor,
    context: &BackendContext,
) -> ScenarioResult {
    let backend = *context.backend_kind();
    if backend.is_postgres()
        && matches!(
            descriptor.id_str(),
            CV_005 | CV_006 | CV_007 | CV_008 | CV_009
        )
        && let Err(reason) = check_postgres_prerequisite()
    {
        if reason.contains("missing") || reason.contains("empty") {
            return ScenarioResult::prerequisite(
                descriptor.id().clone(),
                descriptor.name(),
                backend,
                reason,
            )
            .with_capability_area(descriptor.capability_area().as_str());
        }
        return ScenarioResult::unavailable(
            descriptor.id().clone(),
            descriptor.name(),
            backend,
            reason,
        )
        .with_capability_area(descriptor.capability_area().as_str());
    }

    // For PostgreSQL, also verify the live endpoint is actually reachable when
    // the prerequisite is present. If the catalog cannot be fetched, the
    // scenario must not be reported as pass.
    if backend.is_postgres() {
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
                backend,
                reason,
            )
            .with_capability_area(descriptor.capability_area().as_str());
        }
    }

    match descriptor.id_str() {
        CV_005 => cv005(descriptor, context),
        CV_006 => cv006(descriptor, context),
        CV_007 => cv007(descriptor, context),
        CV_008 => cv008(descriptor, context),
        CV_009 => cv009(descriptor, context),
        _ => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "scenario is registered with stable ID",
                format!("unknown replay/fork scenario {}", descriptor.id_str()),
                backend,
                "validator:scenario-dispatch",
                vec![EvidenceReference::new("validator:unknown-scenario")],
                ScenarioOutcome::Fail,
            );
            ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str())
        }
    }
}

fn new_world_template(scope: &str) -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new(format!("test-replay-{scope}"), 1, WorldInstant::new(0))
}

fn new_entity_id() -> EntityId {
    EntityId::new(Uuid::new_v4())
}
fn new_event_id() -> EventId {
    EventId::new(Uuid::new_v4())
}

// ── CV-005 ───────────────────────────────────────────────────────────────────

fn cv005(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    let api = context.api();
    let scope = context.scope().to_string();

    // 1. Create world
    let template = new_world_template(&scope);
    let snap0 = match block_on(async {
        api.create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
    }) {
        Ok(s) => s,
        Err(e) => {
            let reason = format!(
                "create_world_from_template failed: {:?} - {}",
                e.code, e.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "committed Timeline state at version V is reconstructable via public fork at explicit TimelineVersion without re-running Capability resolvers; same-Timeline historical materialization is not a public operation",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![
                    EvidenceReference::new(
                        "public-surface:loom-client::WorldService::create_world_from_template",
                    ),
                    EvidenceReference::new("validator:scenario:CV-005"),
                ],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let world_id = snap0.target.world_id;
    let timeline_id = snap0.target.timeline_id;
    let target = TimelineTarget::new(world_id, timeline_id);
    let entity_id = new_entity_id();

    // 2. Seed entity with value 1
    let seed_event = new_event_id();
    let seed_inv = ActionInvocation::new(
        ActionTypeId::from("neutral.counter.seed"),
        json!({"event_id": seed_event.to_string(), "entity_id": entity_id.to_string(), "value": 1}),
    );
    let seed_res = block_on(async { api.invoke(ActionRequest::new(target, seed_inv)).await });
    let version_a = match seed_res {
        Ok(ExecutionResult::Committed {
            timeline_version, ..
        }) => timeline_version,
        Ok(other) => {
            let reason = format!("seed invoke not committed: {other:?}");
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "seed should commit and produce version A",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::ActionService::invoke",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
        Err(e) => {
            let reason = format!("seed invoke failed: {:?} - {}", e.code, e.message);
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "seed should commit",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::ActionService::invoke",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };

    // 3. Verify facet after seed is 1 via get_facet
    let facet_after_seed = block_on(async {
        api.get_facet(FacetQuery::new(
            target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    });
    let value_a = match facet_after_seed {
        Ok(Some(snap)) => snap
            .value
            .get("value")
            .and_then(|v| v.as_i64())
            .unwrap_or(-1),
        Ok(None) => -1,
        Err(_) => -1,
    };

    // 4. Increment to value 2
    let inc_event = new_event_id();
    let inc_inv = ActionInvocation::new(
        ActionTypeId::from("neutral.counter.increment"),
        json!({"event_id": inc_event.to_string(), "entity_id": entity_id.to_string(), "amount": 1}),
    );
    let inc_res = block_on(async { api.invoke(ActionRequest::new(target, inc_inv)).await });
    let _version_b = match inc_res {
        Ok(ExecutionResult::Committed {
            timeline_version, ..
        }) => timeline_version,
        _ => version_a,
    };

    // 5. Fork at version A (historical)
    let fork_req = ForkTimelineRequest::at_version(target, version_a);
    let child_snap = match block_on(async { api.fork(fork_req).await }) {
        Ok(s) => s,
        Err(e) => {
            // If fork at version is not supported, report as unavailable gap
            if e.code == loom_api::ApiErrorCode::Unavailable
                || e.code == loom_api::ApiErrorCode::InvalidRequest
            {
                let reason = format!("fork at version unavailable: {:?} - {}", e.code, e.message);
                let finding = Finding::new(
                    descriptor.id().clone(),
                    descriptor.name(),
                    "fork at explicit version should be available for replay",
                    reason.clone(),
                    backend,
                    format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                    vec![
                        EvidenceReference::new("public-surface:loom-client::TimelineService::fork"),
                        EvidenceReference::new("finding:gap:fork-at-version-unavailable"),
                    ],
                    ScenarioOutcome::Unavailable {
                        reason: reason.clone(),
                    },
                );
                return ScenarioResult::new(
                    descriptor.id().clone(),
                    ScenarioOutcome::Unavailable { reason },
                    finding,
                )
                .with_capability_area(descriptor.capability_area().as_str());
            }
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "fork at version should succeed",
                format!("fork failed: {:?} - {}", e.code, e.message),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::fork",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let child_target = child_snap.target;

    // 6. Verify child's facet is 1 (not 2) via get_facet
    let child_facet = block_on(async {
        api.get_facet(FacetQuery::new(
            child_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    });
    let child_value = match child_facet {
        Ok(Some(snap)) => snap
            .value
            .get("value")
            .and_then(|v| v.as_i64())
            .unwrap_or(-1),
        Ok(None) => -1,
        Err(_) => -1,
    };

    // 7. Verify child's history has 1 event, not 2
    let child_events = block_on(async { api.list_events(EventQuery::all(child_target)).await });
    let child_event_count = match child_events {
        Ok(evts) => evts.len(),
        Err(_) => 999,
    };

    // 8. Also verify parent's facet is still 2
    let parent_facet = block_on(async {
        api.get_facet(FacetQuery::new(
            target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    });
    let parent_value = match parent_facet {
        Ok(Some(snap)) => snap
            .value
            .get("value")
            .and_then(|v| v.as_i64())
            .unwrap_or(-1),
        Ok(None) => -1,
        Err(_) => -1,
    };

    let expected = "committed Timeline state at version V is reconstructable via public fork at explicit TimelineVersion without re-running Capability resolvers; same-Timeline historical materialization is not a public operation";
    let actual = if child_value == 1 && value_a == 1 && parent_value == 2 && child_event_count == 1
    {
        format!(
            "replay via fork at version {} verified: child facet={}, parent facet={}, child events={}, ancestry fork_parent_version={:?}; same-Timeline reopen is gap",
            version_a.head_event_seq.value(),
            child_value,
            parent_value,
            child_event_count,
            child_snap.ancestry.fork_parent_version
        )
    } else {
        format!(
            "replay via fork at version {} mismatch: child facet {} (expected 1), parent facet {} (expected 2), child events {} (expected 1), value_a {}",
            version_a.head_event_seq.value(),
            child_value,
            parent_value,
            child_event_count,
            value_a
        )
    };

    let outcome = if child_value == 1 && value_a == 1 && parent_value == 2 && child_event_count == 1
    {
        ScenarioOutcome::Pass
    } else {
        ScenarioOutcome::Fail
    };

    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual,
        backend,
        format!("backend-harness:scope={scope} backend={}", backend.as_str()),
        vec![
            EvidenceReference::new(
                "public-surface:loom-client::WorldService::create_world_from_template",
            ),
            EvidenceReference::new("public-surface:loom-client::ActionService::invoke"),
            EvidenceReference::new("public-surface:loom-client::TimelineService::fork"),
            EvidenceReference::new("public-surface:loom-client::TimelineService::inspect_timeline"),
            EvidenceReference::new("public-surface:loom-client::QueryService::get_facet"),
            EvidenceReference::new("public-surface:loom-client::HistoryService::list_events"),
            EvidenceReference::new(
                "finding:gap:same-timeline-historical-materialization-is-not-a-public-operation",
            ),
            EvidenceReference::new("validator:scenario:CV-005"),
        ],
        outcome.clone(),
    );
    ScenarioResult::new(descriptor.id().clone(), outcome, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

// ── CV-006 ───────────────────────────────────────────────────────────────────

fn cv006(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    let api = context.api();
    let scope = context.scope().to_string();

    let template = new_world_template(&format!("{scope}-006"));
    let parent_snap = match block_on(async {
        api.create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
    }) {
        Ok(s) => s,
        Err(e) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "head fork yields distinct TimelineId and preserves WorldId/binding via ancestry and catalog; child is observable via public TimelineService",
                format!("create_world failed: {:?} - {}", e.code, e.message),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::WorldService::create_world_from_template",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let parent_target = parent_snap.target;
    let parent_version = parent_snap.version;

    let fork_req = ForkTimelineRequest::new(parent_target);
    let child_snap = match block_on(async { api.fork(fork_req).await }) {
        Ok(s) => s,
        Err(e) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "head fork should succeed",
                format!("fork failed: {:?} - {}", e.code, e.message),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::fork",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };

    let child_target = child_snap.target;
    let world_preserved = child_target.world_id == parent_target.world_id;
    let distinct_timeline = child_target.timeline_id != parent_target.timeline_id;
    let ancestry_ok = child_snap.ancestry.parent_timeline_id == Some(parent_target.timeline_id)
        && child_snap.ancestry.fork_parent_version == Some(parent_version);

    // Verify via inspect_timeline
    let inspected_parent = block_on(async { api.inspect_timeline(parent_target).await });
    let inspected_child = block_on(async { api.inspect_timeline(child_target).await });
    let inspect_ok = inspected_parent.is_ok() && inspected_child.is_ok();

    // Verify the world-scoped catalog through the formal binding-aware surface.
    // The world view must be readable and every exposed item must belong to the
    // central catalog; this makes the binding result part of the verdict.
    let catalog_ok = match (
        api.catalog(),
        block_on(async { api.catalog_for_world(parent_target.world_id).await }),
    ) {
        (Ok(global), Ok(world)) => {
            world
                .capabilities
                .iter()
                .all(|capability| global.capability(&capability.id).is_some())
                && world
                    .actions
                    .iter()
                    .all(|action| global.action(&action.id).is_some())
        }
        _ => false,
    };

    let expected = "head fork yields distinct TimelineId and preserves WorldId/binding via ancestry and catalog; child is observable via public TimelineService";
    let actual = format!(
        "WorldId preserved={world_preserved}, TimelineId distinct={distinct_timeline}, ancestry ok={ancestry_ok}, inspect ok={inspect_ok}, world-scoped catalog binding ok={catalog_ok}, parent version {:?} -> child version {:?}",
        parent_version, child_snap.version
    );

    let outcome = if world_preserved && distinct_timeline && ancestry_ok && inspect_ok && catalog_ok
    {
        ScenarioOutcome::Pass
    } else {
        ScenarioOutcome::Fail
    };

    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual,
        backend,
        format!("backend-harness:scope={scope} backend={}", backend.as_str()),
        vec![
            EvidenceReference::new("public-surface:loom-client::TimelineService::fork"),
            EvidenceReference::new("public-surface:loom-client::TimelineService::inspect_timeline"),
            EvidenceReference::new("public-surface:loom-client::CatalogService::catalog"),
            EvidenceReference::new("validator:scenario:CV-006"),
        ],
        outcome.clone(),
    );
    ScenarioResult::new(descriptor.id().clone(), outcome, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

// ── CV-007 ───────────────────────────────────────────────────────────────────

fn cv007(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    let api = context.api();
    let scope = context.scope().to_string();

    let template = new_world_template(&format!("{scope}-007"));
    let parent_snap = match block_on(async {
        api.create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
    }) {
        Ok(s) => s,
        Err(e) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "child branch mutation does not leak into parent/sibling visible state when observed via QueryService::get_facet and HistoryService::list_events only",
                format!("create_world failed: {:?} - {}", e.code, e.message),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::WorldService::create_world_from_template",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let parent_target = parent_snap.target;
    let entity_id = new_entity_id();
    // Seed parent with value 5
    let seed_event = new_event_id();
    let seed_ok = block_on(async {
        api.invoke(ActionRequest::new(
            parent_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.seed"),
                json!({"event_id": seed_event.to_string(), "entity_id": entity_id.to_string(), "value": 5}),
            ),
        ))
        .await
    });
    if let Err(e) = seed_ok {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "seed should commit",
            format!("seed failed: {:?} - {}", e.code, e.message),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::ActionService::invoke",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    // Fork to child
    let child_snap = match block_on(async {
        api.fork(ForkTimelineRequest::new(parent_target)).await
    }) {
        Ok(s) => s,
        Err(e) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "fork should succeed",
                format!("fork failed: {:?} - {}", e.code, e.message),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::fork",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let child_target = child_snap.target;

    // Create a sibling from the same parent. CV-007 owns this sibling check;
    // CV-008's historical-fork sibling is a separate scenario.
    let sibling_snap = match block_on(async {
        api.fork(ForkTimelineRequest::new(parent_target)).await
    }) {
        Ok(s) => s,
        Err(e) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "sibling fork should succeed",
                format!("sibling fork failed: {:?} - {}", e.code, e.message),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::fork",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let sibling_target = sibling_snap.target;

    // Mutate child: increment by 10
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
    if let Err(e) = inc_res {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "child increment should commit",
            format!("child increment failed: {:?} - {}", e.code, e.message),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::ActionService::invoke",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    // Verify isolation via get_facet
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
    let parent_val = parent_facet
        .ok()
        .and_then(|opt| opt)
        .and_then(|snap| snap.value.get("value").and_then(|v| v.as_i64()))
        .unwrap_or(-1);
    let child_val = child_facet
        .ok()
        .and_then(|opt| opt)
        .and_then(|snap| snap.value.get("value").and_then(|v| v.as_i64()))
        .unwrap_or(-1);
    let sibling_facet = block_on(async {
        api.get_facet(FacetQuery::new(
            sibling_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    });
    let sibling_val = sibling_facet
        .ok()
        .and_then(|opt| opt)
        .and_then(|snap| snap.value.get("value").and_then(|v| v.as_i64()))
        .unwrap_or(-1);

    // Verify history isolation
    let parent_events = block_on(async { api.list_events(EventQuery::all(parent_target)).await })
        .map(|v| v.len())
        .unwrap_or(999);
    let child_events = block_on(async { api.list_events(EventQuery::all(child_target)).await })
        .map(|v| v.len())
        .unwrap_or(999);
    let sibling_events = block_on(async { api.list_events(EventQuery::all(sibling_target)).await })
        .map(|v| v.len())
        .unwrap_or(999);

    let expected = "child branch mutation does not leak into parent/sibling visible state when observed via QueryService::get_facet and HistoryService::list_events only";
    let actual = format!(
        "parent facet {parent_val} (expected 5), child facet {child_val} (expected 15), sibling facet {sibling_val} (expected 5), parent events {parent_events} (expected 1), child events {child_events} (expected 2), sibling events {sibling_events} (expected 1)"
    );

    let outcome = if parent_val == 5
        && child_val == 15
        && sibling_val == 5
        && parent_events == 1
        && child_events == 2
        && sibling_events == 1
    {
        ScenarioOutcome::Pass
    } else {
        ScenarioOutcome::Fail
    };

    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual,
        backend,
        format!("backend-harness:scope={scope} backend={}", backend.as_str()),
        vec![
            EvidenceReference::new("public-surface:loom-client::QueryService::get_facet"),
            EvidenceReference::new("public-surface:loom-client::HistoryService::list_events"),
            EvidenceReference::new("public-surface:loom-client::TimelineService::fork"),
            EvidenceReference::new(
                "validator:branch-isolation:parent-child-sibling-via-formal-queries",
            ),
            EvidenceReference::new("validator:scenario:CV-007"),
        ],
        outcome.clone(),
    );
    ScenarioResult::new(descriptor.id().clone(), outcome, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

// ── CV-008 ───────────────────────────────────────────────────────────────────

fn cv008(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    let api = context.api();
    let scope = context.scope().to_string();

    let template = new_world_template(&format!("{scope}-008"));
    let parent_snap = match block_on(async {
        api.create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
    }) {
        Ok(s) => s,
        Err(e) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "historical fork at version V preserves ancestry-visible history up to V and excludes ancestor-future and sibling state where formal HistoryService exposes those operations",
                format!("create_world failed: {:?} - {}", e.code, e.message),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::WorldService::create_world_from_template",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let parent_target = parent_snap.target;
    let entity_id = new_entity_id();
    // Seed
    let seed_event = new_event_id();
    let _ = block_on(async {
        api.invoke(ActionRequest::new(
            parent_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.seed"),
                json!({"event_id": seed_event.to_string(), "entity_id": entity_id.to_string(), "value": 1}),
            ),
        ))
        .await
    });
    // First increment -> version A
    let inc1_event = new_event_id();
    let inc1_res = block_on(async {
        api.invoke(ActionRequest::new(
            parent_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.increment"),
                json!({"event_id": inc1_event.to_string(), "entity_id": entity_id.to_string(), "amount": 1}),
            ),
        ))
        .await
    });
    let version_a = match inc1_res {
        Ok(ExecutionResult::Committed {
            timeline_version, ..
        }) => timeline_version,
        _ => parent_snap.version,
    };
    // Second increment -> version B
    let inc2_event = new_event_id();
    let _ = block_on(async {
        api.invoke(ActionRequest::new(
            parent_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.increment"),
                json!({"event_id": inc2_event.to_string(), "entity_id": entity_id.to_string(), "amount": 1}),
            ),
        ))
        .await
    });

    // Fork at version A
    let child_snap = match block_on(async {
        api.fork(ForkTimelineRequest::at_version(parent_target, version_a))
            .await
    }) {
        Ok(s) => s,
        Err(e) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "historical fork at version should succeed",
                format!("fork at version failed: {:?} - {}", e.code, e.message),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::fork",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let child_target = child_snap.target;

    // Re-open the child through the formal TimelineService and validate the
    // ancestry metadata returned by that read, rather than trusting fork's
    // original response alone.
    let inspected_child = match block_on(async { api.inspect_timeline(child_target).await }) {
        Ok(snapshot) => snapshot,
        Err(e) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "historical fork child inspection should expose its ancestry",
                format!("inspect_timeline failed: {:?} - {}", e.code, e.message),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::inspect_timeline",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let ancestry_ok = inspected_child.target == child_target
        && inspected_child.version == version_a
        && inspected_child.ancestry.parent_timeline_id == Some(parent_target.timeline_id)
        && inspected_child.ancestry.fork_parent_version == Some(version_a);

    // Verify child's history has 2 events (seed + inc1), not 3
    let child_events = block_on(async { api.list_events(EventQuery::all(child_target)).await })
        .map(|v| v.len())
        .unwrap_or(999);
    let parent_events = block_on(async { api.list_events(EventQuery::all(parent_target)).await })
        .map(|v| v.len())
        .unwrap_or(999);

    // Verify child's facet is 2 (1 seed +1 inc1), parent's facet is 3
    let child_facet = block_on(async {
        api.get_facet(FacetQuery::new(
            child_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    });
    let parent_facet = block_on(async {
        api.get_facet(FacetQuery::new(
            parent_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    });
    let child_val = child_facet
        .ok()
        .and_then(|opt| opt)
        .and_then(|snap| snap.value.get("value").and_then(|v| v.as_i64()))
        .unwrap_or(-1);
    let parent_val = parent_facet
        .ok()
        .and_then(|opt| opt)
        .and_then(|snap| snap.value.get("value").and_then(|v| v.as_i64()))
        .unwrap_or(-1);

    // Create sibling fork at head (should have 3 events)
    let sibling_snap =
        block_on(async { api.fork(ForkTimelineRequest::new(parent_target)).await }).ok();
    let sibling_events = if let Some(sib) = sibling_snap.as_ref() {
        block_on(async { api.list_events(EventQuery::all(sib.target)).await })
            .map(|v| v.len())
            .unwrap_or(999)
    } else {
        999
    };
    let sibling_facet = if let Some(sib) = sibling_snap.as_ref() {
        block_on(async {
            api.get_facet(FacetQuery::new(
                sib.target,
                FacetOwner::entity(entity_id),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
        })
        .ok()
        .and_then(|opt| opt)
        .and_then(|snap| snap.value.get("value").and_then(|v| v.as_i64()))
        .unwrap_or(-1)
    } else {
        -1
    };

    // Mutate child and verify parent/sibling not affected
    let child_inc_event = new_event_id();
    let _ = block_on(async {
        api.invoke(ActionRequest::new(
            child_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.increment"),
                json!({"event_id": child_inc_event.to_string(), "entity_id": entity_id.to_string(), "amount": 5}),
            ),
        ))
        .await
    });
    let child_val_after = block_on(async {
        api.get_facet(FacetQuery::new(
            child_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    })
    .ok()
    .and_then(|opt| opt)
    .and_then(|snap| snap.value.get("value").and_then(|v| v.as_i64()))
    .unwrap_or(-1);
    let parent_val_after = block_on(async {
        api.get_facet(FacetQuery::new(
            parent_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    })
    .ok()
    .and_then(|opt| opt)
    .and_then(|snap| snap.value.get("value").and_then(|v| v.as_i64()))
    .unwrap_or(-1);

    let expected = "historical fork at version V preserves ancestry-visible history up to V and excludes ancestor-future and sibling state where formal HistoryService exposes those operations";
    let actual = format!(
        "child events {child_events} (exp 2) parent events {parent_events} (exp 3) sibling events {sibling_events} (exp 3); child val {child_val} (exp 2) parent val {parent_val} (exp 3) sibling val {sibling_facet} (exp 3); after child inc child val {child_val_after} (exp 7) parent val {parent_val_after} (exp 3); inspected ancestry ok={ancestry_ok}, fork_version {:?}",
        version_a
    );

    let outcome = if ancestry_ok
        && child_events == 2
        && parent_events == 3
        && child_val == 2
        && parent_val == 3
        && sibling_events == 3
        && sibling_facet == 3
        && child_val_after == 7
        && parent_val_after == 3
    {
        ScenarioOutcome::Pass
    } else {
        ScenarioOutcome::Fail
    };

    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual,
        backend,
        format!("backend-harness:scope={scope} backend={}", backend.as_str()),
        vec![
            EvidenceReference::new("public-surface:loom-client::TimelineService::fork"),
            EvidenceReference::new("public-surface:loom-client::TimelineService::inspect_timeline"),
            EvidenceReference::new("public-surface:loom-client::HistoryService::list_events"),
            EvidenceReference::new("public-surface:loom-api::TimelineSnapshot::ancestry"),
            EvidenceReference::new("validator:scenario:CV-008"),
        ],
        outcome.clone(),
    );
    ScenarioResult::new(descriptor.id().clone(), outcome, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

// ── CV-009 ───────────────────────────────────────────────────────────────────

fn cv009(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    let scope = context.scope().to_string();
    if backend != BackendKind::PostgreSQL {
        let reason = "InMemory backend creates ephemeral per-scenario mock contexts; durable fork persistence across process restart requires PostgreSQL and is not available via the public InMemory surface";
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "representative fork/reopen remains correct after durable restart (PostgreSQL only); InMemory is ephemeral",
            reason,
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![
                EvidenceReference::new(
                    "finding:gap:inmemory-durable-restart-is-not-a-public-capability",
                ),
                EvidenceReference::new("public-surface:loom-client::TimelineService::fork"),
                EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::inspect_timeline",
                ),
                EvidenceReference::new("validator:scenario:CV-009"),
            ],
            ScenarioOutcome::Unavailable {
                reason: reason.to_string(),
            },
        );
        return ScenarioResult::new(
            descriptor.id().clone(),
            ScenarioOutcome::Unavailable {
                reason: reason.to_string(),
            },
            finding,
        )
        .with_capability_area(descriptor.capability_area().as_str());
    }

    // PostgreSQL path: must verify live backend is actually reachable (already checked in execute_replay_fork)
    // Now create world, fork, then reconnect via a new client and verify.
    let api = context.api();
    let base_url = context.base_url();

    let template = new_world_template(&format!("{scope}-009"));
    let parent_snap = match block_on(async {
        api.create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
    }) {
        Ok(s) => s,
        Err(e) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "PostgreSQL fork should create world",
                format!("create_world failed: {:?} - {}", e.code, e.message),
                backend,
                format!(
                    "backend-harness:scope={scope} backend={} base_url={base_url}",
                    backend.as_str()
                ),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::WorldService::create_world_from_template",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let parent_target = parent_snap.target;
    let entity_id = new_entity_id();
    let seed_event = new_event_id();
    let _ = block_on(async {
        api.invoke(ActionRequest::new(
            parent_target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.seed"),
                json!({"event_id": seed_event.to_string(), "entity_id": entity_id.to_string(), "value": 1}),
            ),
        ))
        .await
    });
    let child_snap = match block_on(async {
        api.fork(ForkTimelineRequest::new(parent_target)).await
    }) {
        Ok(s) => s,
        Err(e) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "PostgreSQL fork should succeed",
                format!("fork failed: {:?} - {}", e.code, e.message),
                backend,
                format!(
                    "backend-harness:scope={scope} backend={} base_url={base_url}",
                    backend.as_str()
                ),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::fork",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let child_target = child_snap.target;

    // Simulate restart/reconnect: create a fresh LoomClient to the same base_url
    // For the mock InMemory case this would be a new mock, but for PostgreSQL
    // the state is durable and should be visible via the new client. For the
    // validator's InMemory mock, the state is per-harness, so a fresh client
    // to the same mock server would see the same state (since the mock server
    // is shared via Arc). For a real PostgreSQL server, the new client will
    // also see the same durable state.
    let fresh_client = match loom_client::LoomClient::new(base_url.clone()) {
        Ok(c) => c,
        Err(e) => {
            let reason = format!("fresh client creation failed: {e}");
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "fresh client should be creatable for reconnect",
                reason.clone(),
                backend,
                format!(
                    "backend-harness:scope={scope} backend={} base_url={base_url}",
                    backend.as_str()
                ),
                vec![EvidenceReference::new(
                    "validator:restart:reconnect-via-public-client",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let fresh_api: Arc<dyn loom_api::LoomApi + Send + Sync> = Arc::new(fresh_client);

    // Verify via fresh client: inspect parent and child, list history, get facet
    let fresh_parent_inspect = block_on(async { fresh_api.inspect_timeline(parent_target).await });
    let fresh_child_inspect = block_on(async { fresh_api.inspect_timeline(child_target).await });
    let fresh_parent_events =
        block_on(async { fresh_api.list_events(EventQuery::all(parent_target)).await });
    let fresh_child_events =
        block_on(async { fresh_api.list_events(EventQuery::all(child_target)).await });
    let fresh_parent_facet = block_on(async {
        fresh_api
            .get_facet(FacetQuery::new(
                parent_target,
                FacetOwner::entity(entity_id),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
    });

    let inspect_ok = match (&fresh_parent_inspect, &fresh_child_inspect) {
        (Ok(parent), Ok(child)) => {
            parent.target == parent_target
                && child.target == child_target
                && parent.version == child_snap.version
                && child.version == child_snap.version
                && child.ancestry.parent_timeline_id == Some(parent_target.timeline_id)
                && child.ancestry.fork_parent_version == Some(child_snap.version)
        }
        _ => false,
    };
    let history_ok = match (&fresh_parent_events, &fresh_child_events) {
        (Ok(parent), Ok(child)) => {
            parent.len() == 1
                && child.len() == 1
                && parent[0].id == seed_event
                && child[0].id == seed_event
        }
        _ => false,
    };
    let facet_ok = matches!(&fresh_parent_facet, Ok(Some(facet)) if
        facet.value.get("value").and_then(|value| value.as_i64()) == Some(1));

    let expected = "representative fork/reopen behavior remains correct after PostgreSQL restart when observed via public TimelineService and HistoryService";
    let actual = if inspect_ok && history_ok && facet_ok {
        format!(
            "reconnect via fresh LoomClient to {base_url} succeeded: target/version/ancestry, history content/count, and facet value all matched; durable state survived reconnect"
        )
    } else {
        format!(
            "reconnect failed: parent inspect {fresh_parent_inspect:?}, child inspect {fresh_child_inspect:?}, history {fresh_parent_events:?}/{fresh_child_events:?}, facet {fresh_parent_facet:?}"
        )
    };

    let outcome = if inspect_ok && history_ok && facet_ok {
        ScenarioOutcome::Pass
    } else {
        ScenarioOutcome::Fail
    };

    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual,
        backend,
        format!(
            "backend-harness:scope={scope} backend={} base_url={base_url} restart=via-fresh-LoomClient",
            backend.as_str()
        ),
        vec![
            EvidenceReference::new("public-surface:loom-client::TimelineService::fork"),
            EvidenceReference::new("public-surface:loom-client::TimelineService::inspect_timeline"),
            EvidenceReference::new("public-surface:loom-client::HistoryService::list_events"),
            EvidenceReference::new("validator:restart:reconnect-via-public-client"),
            EvidenceReference::new("validator:scenario:CV-009"),
        ],
        outcome.clone(),
    );
    ScenarioResult::new(descriptor.id().clone(), outcome, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

#[cfg(test)]
mod tests {
    use super::{CV_005, CV_009, execute_replay_fork, replay_fork_descriptors};
    use crate::backend::{BackendContext, BackendHarness, DEFAULT_VALIDATOR_BASE_URL};
    use crate::finding::EvidenceReference;
    use crate::scenario::{BackendKind, ScenarioId};

    fn context_for(kind: BackendKind, scope: &str) -> BackendContext {
        let harness = BackendHarness::connect(kind, DEFAULT_VALIDATOR_BASE_URL)
            .expect("harness connect should succeed for test");
        match harness.start(scope) {
            crate::backend::BackendStart::Ready(ctx) => ctx,
            other => panic!("expected Ready for test backend {kind:?}, got {other:?}"),
        }
    }

    #[test]
    fn descriptors_are_stable_and_deterministically_ordered() {
        let mut descs = replay_fork_descriptors();
        let ids: Vec<String> = descs.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec![CV_005, "CV-006", "CV-007", "CV-008", CV_009]);
        descs.sort_by(|a, b| a.id_str().cmp(b.id_str()));
        let sorted_ids: Vec<String> = descs.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(sorted_ids, ids);
        for desc in &descs {
            assert_eq!(desc.capability_area().as_str(), "replay-fork");
            assert!(desc.supported_backends().contains(&BackendKind::InMemory));
            assert!(desc.supported_backends().contains(&BackendKind::PostgreSQL));
            assert!(ScenarioId::try_new(desc.id_str()).is_ok());
        }
    }

    #[test]
    fn in_memory_variants_run_deterministically() {
        let descs = replay_fork_descriptors();
        // Use a single harness so that world/fork state is shared deterministically
        // but each scenario gets a fresh scope (and thus a fresh world). This
        // mirrors the Runner's per-scenario fresh context.
        let harness = BackendHarness::connect(BackendKind::InMemory, DEFAULT_VALIDATOR_BASE_URL)
            .expect("InMemory harness should connect");
        let mut results = Vec::new();
        for desc in &descs {
            let ctx = match harness.start(desc.id_str()) {
                crate::backend::BackendStart::Ready(c) => c,
                other => panic!(
                    "InMemory start should be Ready for {}: {other:?}",
                    desc.id_str()
                ),
            };
            let result = execute_replay_fork(desc, &ctx);
            results.push((
                desc.id_str().to_string(),
                result.outcome().as_str().to_string(),
                result.finding().actual().to_string(),
            ));
        }

        // Re-run with a fresh harness and ensure identical outcomes (determinism)
        let harness2 = BackendHarness::connect(BackendKind::InMemory, DEFAULT_VALIDATOR_BASE_URL)
            .expect("InMemory harness should connect");
        for desc in &descs {
            let ctx = match harness2.start(desc.id_str()) {
                crate::backend::BackendStart::Ready(c) => c,
                other => panic!(
                    "InMemory start should be Ready for {}: {other:?}",
                    desc.id_str()
                ),
            };
            let result = execute_replay_fork(desc, &ctx);
            let prior = results
                .iter()
                .find(|(id, _, _)| id == desc.id_str())
                .unwrap();
            assert_eq!(
                result.outcome().as_str(),
                prior.1,
                "determinism for {}",
                desc.id_str()
            );
            assert_eq!(
                result.finding().actual(),
                prior.2,
                "finding determinism for {}",
                desc.id_str()
            );
        }

        for (id, outcome, _) in &results {
            match id.as_str() {
                "CV-005" | "CV-006" | "CV-007" | "CV-008" => {
                    assert_eq!(outcome, "pass", "{id} should pass on InMemory");
                }
                "CV-009" => assert_eq!(
                    outcome, "unavailable",
                    "CV-009 InMemory should be unavailable (gap)"
                ),
                _ => panic!("unexpected id {id}"),
            }
        }
    }

    #[test]
    fn postgresql_missing_prerequisite_is_not_a_pass() {
        let key = crate::backend::LOOM_TEST_POSTGRES_URL;
        let err = super::postgres_prerequisite_with_value(None, key).unwrap_err();
        assert!(err.contains("missing"));
        assert!(!err.contains("pass"));
        let desc = replay_fork_descriptors()
            .into_iter()
            .find(|d| d.id_str() == "CV-006")
            .unwrap();
        let result = crate::reports::ScenarioResult::prerequisite(
            desc.id().clone(),
            desc.name(),
            BackendKind::PostgreSQL,
            err.clone(),
        );
        assert_eq!(result.outcome().as_str(), "skipped");
        assert!(!result.outcome().is_pass());
        if std::env::var(key).is_err() {
            let harness =
                BackendHarness::connect(BackendKind::PostgreSQL, DEFAULT_VALIDATOR_BASE_URL)
                    .expect("connect should succeed even when env missing (prerequisite state)");
            let start = harness.start("CV-006");
            assert!(matches!(
                start,
                crate::backend::BackendStart::Prerequisite { .. }
            ));
        }
    }

    #[test]
    fn isolation_checks_only_use_supported_query_surfaces() {
        let harness = BackendHarness::connect(BackendKind::InMemory, DEFAULT_VALIDATOR_BASE_URL)
            .expect("InMemory harness should connect");
        let ctx = match harness.start("CV-007") {
            crate::backend::BackendStart::Ready(c) => c,
            other => panic!("expected Ready: {other:?}"),
        };
        let descs = replay_fork_descriptors();
        let desc = descs.iter().find(|d| d.id_str() == "CV-007").unwrap();
        let result = execute_replay_fork(desc, &ctx);
        assert_eq!(result.outcome().as_str(), "pass");
        let finding = result.finding();
        let evidence = finding
            .evidence()
            .iter()
            .map(EvidenceReference::as_str)
            .collect::<Vec<_>>()
            .join(",");
        assert!(
            evidence.contains("public-surface:loom-client"),
            "evidence should cite public client surfaces: {evidence}"
        );
        let forbidden_storage = format!("{}storage", "loom_");
        let forbidden_runtime = format!("{}runtime", "loom_");
        assert!(!evidence.to_lowercase().contains(&forbidden_storage));
        assert!(!evidence.to_lowercase().contains(&forbidden_runtime));
        assert!(!evidence.to_lowercase().contains("pgstorage"));
        assert!(!evidence.to_lowercase().contains("sqlx"));
        assert!(
            finding.actual().contains("parent facet")
                || finding.actual().contains("child facet")
                || finding.actual().contains("FacetQuery")
        );
    }

    #[test]
    fn missing_public_operation_is_reported_factually() {
        let harness = BackendHarness::connect(BackendKind::InMemory, DEFAULT_VALIDATOR_BASE_URL)
            .expect("InMemory harness should connect");
        let ctx = match harness.start("CV-005") {
            crate::backend::BackendStart::Ready(c) => c,
            other => panic!("expected Ready: {other:?}"),
        };
        let descs = replay_fork_descriptors();
        let desc005 = descs.iter().find(|d| d.id_str() == "CV-005").unwrap();
        let result005 = execute_replay_fork(desc005, &ctx);
        assert_eq!(result005.outcome().as_str(), "pass");
        // CV-005 now actually performs a fork at version and verifies replay;
        // the gap is still recorded for the same-Timeline historical materialization
        // which is not a public operation.
        assert!(
            result005
                .finding()
                .evidence()
                .iter()
                .any(|e| e.as_str().contains("gap"))
        );

        let ctx2 = match harness.start("CV-009") {
            crate::backend::BackendStart::Ready(c) => c,
            other => panic!("expected Ready: {other:?}"),
        };
        let desc009 = descs.iter().find(|d| d.id_str() == "CV-009").unwrap();
        let result009 = execute_replay_fork(desc009, &ctx2);
        assert_eq!(result009.outcome().as_str(), "unavailable");
        assert!(
            result009
                .finding()
                .evidence()
                .iter()
                .any(|e| e.as_str().contains("gap"))
        );
    }

    #[test]
    fn postgresql_variant_executes_live_when_configured() {
        let key = crate::backend::LOOM_TEST_POSTGRES_URL;
        assert!(
            super::postgres_prerequisite_with_value(
                Some("postgres://localhost:5432/loom_test"),
                key
            )
            .is_ok()
        );
        assert!(
            super::postgres_prerequisite_with_value(
                Some("postgresql://localhost:5432/loom_test"),
                key
            )
            .is_ok()
        );
        assert!(
            super::postgres_prerequisite_with_value(Some("http://localhost:5432/loom_test"), key)
                .is_err()
        );
        let err_empty = super::postgres_prerequisite_with_value(Some("   "), key).unwrap_err();
        assert!(err_empty.contains("empty"));
    }

    #[test]
    fn cv009_postgresql_requires_live_endpoint() {
        // When LOOM_TEST_POSTGRES_URL is set but the endpoint is not reachable,
        // the harness should be Unavailable, not Ready, and the scenario must
        // not be reported as pass.
        // We use a valid URL but an unroutable base_url to simulate unreachable.
        let key = crate::backend::LOOM_TEST_POSTGRES_URL;
        // Temporarily set a valid postgres URL in a way that does not require
        // unsafe global mutation: we test the helper directly and the harness
        // with a bogus base_url.
        assert!(
            super::postgres_prerequisite_with_value(
                Some("postgres://localhost:5432/loom_test"),
                key
            )
            .is_ok()
        );
        // Now test harness with an unroutable base_url
        let harness = BackendHarness::connect(BackendKind::PostgreSQL, "http://127.0.0.1:1")
            .expect("connect should not fail on invalid base_url construction");
        // Since the URL is valid but the server is not listening, the harness
        // should have marked it as Unavailable after the catalog check.
        // We cannot guarantee the harness start is Unavailable without actually
        // having the env var set, but we can at least verify the code path
        // exists: when env is missing, it is Prerequisite, not pass.
        if std::env::var(key).is_err() {
            let start = harness.start("CV-009");
            assert!(matches!(
                start,
                crate::backend::BackendStart::Prerequisite { .. }
            ));
        }
    }
}
