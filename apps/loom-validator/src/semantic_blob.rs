//! Semantic/Blob/Pinned Reads suite (T15).
//!
//! Owner: T15 (#320) — `CV-028..CV-030`.
//! Central registry integration is reserved for T19 (#324). This module must
//! not register scenarios in `validator_registry` autonomously; T19 alone edits
//! `registry.rs`/`lib.rs` and CLI dispatch. Only `CV-030` is an implementable
//! public-surface candidate via existing `ForkTimelineRequest::at_version` +
//! `QueryService::get_facet`/`HistoryService`/`TimelineService::inspect_timeline`.
//! `CV-028` (semantic projection rebuild) and `CV-029` (blob reference fetch)
//! are explicit public-surface coverage gaps per `t08-coverage-matrix.md`:
//! no public `loom-api`/`loom-client` semantic projection or blob fetch service
//! exists, and this leaf must not invent one, enter internal
//! `loom-runtime`/`loom-storage` tables, or forge a `Pass`. They remain
//! blocked gap metadata and are not registered as candidates.

#![allow(clippy::all, clippy::pedantic, clippy::nursery, clippy::restriction)]
#![allow(unused_imports, dead_code)]

use std::future::Future;
use std::sync::Arc;

use loom_api::{
    ActionInvocation, ActionRequest, ActionTypeId, CreateWorldFromTemplateRequest, EntityId,
    EventId, EventQuery, FacetOwner, FacetQuery, FacetTypeId, ForkTimelineRequest, TimelineTarget,
    TimelineVersion, WorldInstant, WorldTemplateDescriptor,
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
pub const CV_028: &str = "CV-028";
#[allow(dead_code)]
pub const CV_029: &str = "CV-029";
#[allow(dead_code)]
pub const CV_030: &str = "CV-030";

/// Suite identifier for file ownership.
pub const SUITE: &str = "semantic_blob";

/// Owned CV range for this suite.
pub const CV_RANGE: &str = "CV-028..CV-030";

/// Capability area label for this suite.
pub const CAPABILITY_AREA: &str = "semantic-blob";

/// Returns the suite identifier.
#[must_use]
pub fn suite_name() -> &'static str {
    SUITE
}

/// Returns true if `cv_id` belongs to this suite's owned CV range.
#[must_use]
pub fn owns_cv(cv_id: &str) -> bool {
    matches!(cv_id, "CV-028" | "CV-029" | "CV-030")
}

// ── Descriptor registry (T09 fence / T19 surface) ────────────────────────────

/// Returns the implementable descriptor(s) for this suite.
///
/// Only `CV-030` is a registrable candidate. `CV-028` and `CV-029` are
/// deliberate public-surface gaps and are not returned here; they remain
/// documented in the ledger and via `blocked_descriptors()` for T19
/// visibility without enlarging the central registry.
#[must_use]
pub fn descriptors() -> Vec<ScenarioDescriptor> {
    vec![ScenarioDescriptor::new(
        CV_030,
        "pinned/versioned read via fork at explicit TimelineVersion preserves pinned revision consistency",
        CAPABILITY_AREA,
        vec![BackendKind::InMemory, BackendKind::PostgreSQL],
        "committed Timeline with pinned TimelineVersion fork; ForkTimelineRequest::at_version is the supported pinned-read mechanism",
        vec!["VALR-T15".to_string()],
        vec![
            "docs/architecture/amendments/0003-agency-execution-and-pinned-read-boundary.md#replay-and-fork".to_string(),
            "docs/tasks/validator-recert/stage-2/t08-coverage-matrix.md#CV-030".to_string(),
        ],
    )]
}

/// Returns descriptors for the blocked public-surface gaps.
///
/// These are never registered into `validator_registry` (T19 fence). They exist
/// solely so the ledger and tooling can cite stable gap metadata without
/// forging a `Pass`.
#[must_use]
pub fn blocked_descriptors() -> Vec<ScenarioDescriptor> {
    vec![
        ScenarioDescriptor::new(
            CV_028,
            "semantic projection rebuildable, not authority (blocked — no public SemanticService)",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "no public SemanticService/rebuild/query API exists in loom-api; only SemanticIndexDescriptor metadata via CatalogService",
            vec!["VALR-T15".to_string()],
            vec!["docs/tasks/validator-recert/stage-2/t08-coverage-matrix.md#CV-028".to_string()],
        ),
        ScenarioDescriptor::new(
            CV_029,
            "blob/reference missing does not rewrite history (blocked — no public BlobService)",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "no public BlobService/blob read API exists in loom-api; FacetSnapshot.value may contain opaque BlobReference but fetch cannot be observed via public surface",
            vec!["VALR-T15".to_string()],
            vec!["docs/tasks/validator-recert/stage-2/t08-coverage-matrix.md#CV-029".to_string()],
        ),
    ]
}

/// Registers the implementable descriptor(s) into `registry`.
///
/// Only `CV-030` is registered. Blocked gaps `CV-028`/`CV-029` are not
/// registered; calling this does not enlarge the central registry with blocked
/// entries. T19 owns central `validator_registry` integration and must call
/// this explicitly.
///
/// # Errors
///
/// Returns [`crate::registry::RegistryError::DuplicateId`] when a scenario
/// ID is already present in `registry`.
pub fn register(
    registry: &mut crate::registry::ScenarioRegistry,
) -> Result<usize, crate::registry::RegistryError> {
    let mut count = 0;
    for descriptor in descriptors() {
        registry.register(descriptor)?;
        count += 1;
    }
    Ok(count)
}

// ── Execution dispatch ───────────────────────────────────────────────────────

/// Executes one semantic-blob scenario via the formal `LoomApi` surface.
///
/// `CV-030` performs a real pinned read via `ForkTimelineRequest::at_version`.
/// `CV-028`/`CV-029` return explicit `Unavailable` gap results and never
/// report `Pass`; they do not touch internal storage or invent an API.
#[must_use]
pub fn execute(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    // For the implementable PostgreSQL candidate, verify the live endpoint is
    // reachable. The test harness supplies the repository default when the
    // optional connection override is absent; blocked gaps must not enter this
    // gate at all.
    if backend.is_postgres() && descriptor.id_str() == CV_030 {
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
        CV_030 => cv030(descriptor, context),
        CV_028 => cv028_blocked(descriptor, context),
        CV_029 => cv029_blocked(descriptor, context),
        _ => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "scenario is registered with stable ID",
                format!("unknown semantic-blob scenario {}", descriptor.id_str()),
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

fn new_world_template(scope: &str) -> WorldTemplateDescriptor {
    // Unique per execution to avoid cross-test collision; still deterministic within scope.
    WorldTemplateDescriptor::new(format!("validator.t15.{scope}"), 1, WorldInstant::new(42))
        .requires_capability("neutral.counter", "^0.1.0")
}

fn new_entity_id() -> EntityId {
    EntityId::new(Uuid::new_v4())
}

fn new_event_id() -> EventId {
    EventId::new(Uuid::new_v4())
}

// ── CV-028 blocked ───────────────────────────────────────────────────────────

fn cv028_blocked(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    let scope = context.scope().to_string();
    let reason = "CV-028 semantic projection rebuild has no public loom-api/loom-client surface: no SemanticService, rebuild/query, or projection fetch API exists; only SemanticIndexDescriptor metadata via CatalogService::catalog is exposed. Validator cannot observe semantic projection via public surface without Architecture Amendment.";
    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        "blocked: semantic projection rebuild/derived read has no public API; requires Architecture Amendment adding public SemanticService before Validator coverage",
        reason,
        backend,
        format!("backend-harness:scope={scope} backend={}", backend.as_str()),
        vec![
            EvidenceReference::new("finding:gap:CV-028-no-public-semantic-projection-api"),
            EvidenceReference::new(
                "public-surface:loom-client::CatalogService::catalog#SemanticIndexDescriptor-only",
            ),
            EvidenceReference::new("validator:scenario:CV-028"),
            EvidenceReference::new("doc:t08-coverage-matrix.md#CV-028-blocked"),
        ],
        ScenarioOutcome::Unavailable {
            reason: reason.to_string(),
        },
    );
    ScenarioResult::new(
        descriptor.id().clone(),
        ScenarioOutcome::Unavailable {
            reason: reason.to_string(),
        },
        finding,
    )
    .with_capability_area(descriptor.capability_area().as_str())
}

// ── CV-029 blocked ───────────────────────────────────────────────────────────

fn cv029_blocked(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    let scope = context.scope().to_string();
    let reason = "CV-029 blob/reference fetch has no public loom-api/loom-client surface: no BlobService/blob read API exists; FacetSnapshot.value may contain opaque BlobReference via QueryService::get_facet but fetch failure cannot be validated via public surface without Architecture Amendment.";
    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        "blocked: blob availability failure has no public API; requires Architecture Amendment adding public BlobService before Validator coverage",
        reason,
        backend,
        format!("backend-harness:scope={scope} backend={}", backend.as_str()),
        vec![
            EvidenceReference::new("finding:gap:CV-029-no-public-blob-service-api"),
            EvidenceReference::new(
                "public-surface:loom-client::QueryService::get_facet#BlobReference-opaque-only",
            ),
            EvidenceReference::new("validator:scenario:CV-029"),
            EvidenceReference::new("doc:t08-coverage-matrix.md#CV-029-blocked"),
        ],
        ScenarioOutcome::Unavailable {
            reason: reason.to_string(),
        },
    );
    ScenarioResult::new(
        descriptor.id().clone(),
        ScenarioOutcome::Unavailable {
            reason: reason.to_string(),
        },
        finding,
    )
    .with_capability_area(descriptor.capability_area().as_str())
}

// ── CV-030 pinned version stability ─────────────────────────────────────────

fn cv030(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    let api = context.api();
    let scope = context.scope().to_string();

    // 1. Create world with unique template; use actual returned TimelineVersion.
    let template = new_world_template(&scope);
    let snap0 = match block_on(async {
        api.create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
    }) {
        Ok(snapshot) => snapshot,
        Err(error) => {
            let reason = format!(
                "create_world_from_template failed: {:?} - {}",
                error.code, error.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "pinned read via fork at version preserves pinned revision consistency via public loom-api",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![
                    EvidenceReference::new(
                        "public-surface:loom-client::WorldService::create_world_from_template",
                    ),
                    EvidenceReference::new("validator:scenario:CV-030"),
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

    // 2. Seed entity with value 10; capture pinned TimelineVersion (version_a).
    let seed_event = new_event_id();
    let seed_inv = ActionInvocation::new(
        ActionTypeId::from("neutral.counter.seed"),
        json!({
            "event_id": seed_event.to_string(),
            "entity_id": entity_id.to_string(),
            "value": 10
        }),
    );
    let version_a = match block_on(async { api.invoke(ActionRequest::new(target, seed_inv)).await })
    {
        Ok(loom_api::ExecutionResult::Committed {
            event_ids: _,
            timeline_version,
        }) => timeline_version,
        Ok(other) => {
            let reason = format!("seed invoke not committed: {other:?}");
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "seed with value 10 should commit and yield pinned TimelineVersion",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::ActionService::invoke#seed",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
        Err(error) => {
            let reason = format!("seed invoke failed: {:?} - {}", error.code, error.message);
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "seed should commit",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::ActionService::invoke#seed",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };

    // 3. Verify pinned facet is 10 via public get_facet.
    let facet_a = match block_on(async {
        api.get_facet(FacetQuery::new(
            target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    }) {
        Ok(value) => value,
        Err(error) => {
            let reason = format!(
                "get_facet at pinned version failed: {:?} - {}",
                error.code, error.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "get_facet at pinned version should return 10 via public QueryService",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::QueryService::get_facet",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let value_a = facet_a
        .as_ref()
        .and_then(|snap| snap.value.get("value").and_then(|value| value.as_i64()))
        .unwrap_or(-1);
    if value_a != 10 {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "pinned facet value 10 should be visible via public get_facet after seed",
            format!("facet value {value_a} != 10 at pinned version {version_a:?}"),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::QueryService::get_facet",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    // 4. Verify history at pinned version has 1 event (seed) via public list_events.
    let history_a = match block_on(async { api.list_events(EventQuery::all(target)).await }) {
        Ok(events) => events,
        Err(error) => {
            let reason = format!(
                "list_events at pinned version failed: {:?} - {}",
                error.code, error.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "history at pinned version should be observable via public HistoryService",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::HistoryService::list_events",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    if history_a.len() != 1 {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "history at pinned version should contain exactly 1 event (seed)",
            format!(
                "history len {} != 1 at version_a {version_a:?}",
                history_a.len()
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::HistoryService::list_events",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }
    // Capture pinned event id for later ancestry / history checks.
    let pinned_event_id = history_a[0].id;

    // 5. Submit second commit on source: increment to 11 at new head.
    let inc_event = new_event_id();
    let inc_inv = ActionInvocation::new(
        ActionTypeId::from("neutral.counter.increment"),
        json!({
            "event_id": inc_event.to_string(),
            "entity_id": entity_id.to_string(),
            "amount": 1
        }),
    );
    let version_b = match block_on(async { api.invoke(ActionRequest::new(target, inc_inv)).await })
    {
        Ok(loom_api::ExecutionResult::Committed {
            event_ids: _,
            timeline_version,
        }) => timeline_version,
        Ok(other) => {
            let reason = format!("second invoke not committed: {other:?}");
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "second commit (increment to 11) should commit and advance TimelineVersion",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::ActionService::invoke#increment",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
        Err(error) => {
            let reason = format!("second invoke failed: {:?} - {}", error.code, error.message);
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "second commit should succeed",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::ActionService::invoke#increment",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };

    if version_b == version_a {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "second commit should advance TimelineVersion beyond pinned version",
            format!("version_b {version_b:?} == version_a {version_a:?}"),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::ActionService::invoke#increment",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    // 6. Verify source head now reads 11.
    let facet_b = match block_on(async {
        api.get_facet(FacetQuery::new(
            target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    }) {
        Ok(value) => value,
        Err(error) => {
            let reason = format!(
                "get_facet at head failed: {:?} - {}",
                error.code, error.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "head get_facet should return 11 after second commit",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::QueryService::get_facet",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let value_b = facet_b
        .as_ref()
        .and_then(|snap| snap.value.get("value").and_then(|value| value.as_i64()))
        .unwrap_or(-1);
    if value_b != 11 {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "head facet should be 11 after second commit via public get_facet",
            format!(
                "facet value {value_b} != 11 at version_b {version_b:?} (pinned {version_a:?})"
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::QueryService::get_facet",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    let history_b = match block_on(async { api.list_events(EventQuery::all(target)).await }) {
        Ok(events) => events,
        Err(error) => {
            let reason = format!(
                "list_events at head failed: {:?} - {}",
                error.code, error.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "head history should be observable via public HistoryService",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::HistoryService::list_events",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    if history_b.len() != 2 {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "head history should contain exactly 2 events after second commit",
            format!(
                "history len {} != 2 at version_b {version_b:?}",
                history_b.len()
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::HistoryService::list_events",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    // Bind both returned TimelineVersion fields to the public history boundary.
    // A version is only useful evidence here when its EventSeq identifies the
    // corresponding committed head and its StateRevision advances with the
    // second commit.
    let versions_match_history = version_a.head_event_seq == history_a[0].sequence
        && history_b[0].sequence == version_a.head_event_seq
        && history_b[1].sequence == version_b.head_event_seq
        && history_b[0].sequence < history_b[1].sequence
        && version_b.head_event_seq > version_a.head_event_seq
        && version_b.state_revision > version_a.state_revision;
    if !versions_match_history {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "returned TimelineVersion fields must match the corresponding history EventSeq and advance state revision",
            format!(
                "version_a {version_a:?}, version_b {version_b:?}, history_a seq {:?}, history_b seqs [{:?}, {:?}]",
                history_a[0].sequence, history_b[0].sequence, history_b[1].sequence,
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![
                EvidenceReference::new(
                    "public-surface:loom-client::ActionService::invoke#seed+increment",
                ),
                EvidenceReference::new("public-surface:loom-client::HistoryService::list_events"),
                EvidenceReference::new("validator:timeline-version-eventseq-state-revision"),
            ],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    let pinned_event_ref = history_a[0].event_ref();

    // 7. Fork at pinned version_a via public ForkTimelineRequest::at_version.
    let fork_req = ForkTimelineRequest::at_version(target, version_a);
    let child_snapshot = match block_on(async { api.fork(fork_req).await }) {
        Ok(snapshot) => snapshot,
        Err(error) => {
            let reason = format!(
                "fork at pinned version failed: {:?} - {}",
                error.code, error.message
            );
            // Map InvalidForkVersion to Fail (not unavailable) because surface is expected to exist.
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "fork at explicit pinned TimelineVersion should succeed via public TimelineService",
                reason.clone(),
                backend,
                format!(
                    "backend-harness:scope={scope} backend={} pinned={version_a:?} head={version_b:?}",
                    backend.as_str()
                ),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::fork#at_version",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let child_target = child_snapshot.target;

    // 8. Verify fork ancestry preserves pinned version and fork parent event.
    let ancestry = child_snapshot.ancestry;
    if ancestry.fork_parent_version != Some(version_a) {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "fork ancestry fork_parent_version should equal pinned TimelineVersion via public inspect_timeline",
            format!(
                "ancestry fork_parent_version {:?} != Some({:?}) pinned {version_a:?} child {} ancestry {:?}",
                ancestry.fork_parent_version, version_a, child_target.timeline_id, ancestry
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![
                EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::fork#at_version",
                ),
                EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::inspect_timeline#ancestry.fork_parent_version",
                ),
            ],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }
    if ancestry.parent_timeline_id != Some(timeline_id) {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "fork ancestry parent_timeline_id should equal source TimelineId",
            format!(
                "parent_timeline_id {:?} != Some({})",
                ancestry.parent_timeline_id, timeline_id
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::TimelineService::inspect_timeline#ancestry.parent_timeline_id",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }
    // Fork parent event is expected when pinned version had an event at that boundary.
    // At version_a after seed, there is an event; fork should record it.
    if ancestry.fork_parent_event.is_none() {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "fork ancestry should contain fork_parent_event for pinned version with event",
            format!(
                "fork_parent_event is None at pinned {version_a:?} (expected EventRef for seed {})",
                pinned_event_id
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::TimelineService::inspect_timeline#ancestry.fork_parent_event",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }
    // Verify fork_parent_event id matches pinned event when resolved via visible history.
    // The event ref's timeline_id is source; id should correspond to pinned event.
    if let Some(fork_event) = ancestry.fork_parent_event {
        if fork_event != pinned_event_ref {
            // Not strictly required to be identical if runtime chooses boundary differently,
            // but for this pinned seed it should be the seed event. Report details but allow
            // alternative if history still consistent. We'll enforce equality for determinism.
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "fork_parent_event id should equal pinned seed EventId via public ancestry",
                format!(
                    "fork_parent_event {:?} != pinned source event {:?} at {version_a:?}",
                    fork_event, pinned_event_ref
                ),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::inspect_timeline#ancestry.fork_parent_event",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    }

    // 9. Also verify via explicit inspect_timeline on fork target.
    let child_inspect = match block_on(async { api.inspect_timeline(child_target).await }) {
        Ok(snapshot) => snapshot,
        Err(error) => {
            let reason = format!(
                "inspect_timeline on fork target failed: {:?} - {}",
                error.code, error.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "fork target inspect_timeline should succeed via public TimelineService",
                reason.clone(),
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
    if child_inspect.ancestry.fork_parent_version != Some(version_a) {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "inspect_timeline ancestry on fork should preserve pinned version",
            format!(
                "inspect ancestry {:?} != Some({:?})",
                child_inspect.ancestry.fork_parent_version, version_a
            ),
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
    if child_inspect.ancestry.parent_timeline_id != Some(timeline_id)
        || child_inspect.ancestry.fork_parent_event != Some(pinned_event_ref)
    {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "fork inspect ancestry must preserve the source TimelineId and pinned boundary EventRef",
            format!(
                "child inspect ancestry {:?} expected parent {} and event {:?}",
                child_inspect.ancestry, timeline_id, pinned_event_ref
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![
                EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::inspect_timeline#ancestry",
                ),
                EvidenceReference::new("public-surface:loom-client::HistoryService::list_events"),
                EvidenceReference::new("validator:fork-parent-event-ref"),
            ],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }
    // Child version should equal pinned version (materialized at fork boundary).
    if child_inspect.version != version_a {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "fork target version should equal pinned TimelineVersion after fork",
            format!(
                "child inspect version {:?} (fork snapshot {:?}) != pinned {version_a:?}",
                child_inspect.version, child_snapshot.version
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::TimelineService::inspect_timeline#version",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    // 10. Verify fork target reads pinned value 10, not head 11.
    let child_facet = match block_on(async {
        api.get_facet(FacetQuery::new(
            child_target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    }) {
        Ok(value) => value,
        Err(error) => {
            let reason = format!(
                "get_facet on fork target failed: {:?} - {}",
                error.code, error.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "fork get_facet should return pinned value 10 via public QueryService",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::QueryService::get_facet#fork",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let child_value = child_facet
        .as_ref()
        .and_then(|snap| snap.value.get("value").and_then(|value| value.as_i64()))
        .unwrap_or(-1);
    if child_value != 10 {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "fork target get_facet should preserve pinned value 10 via public QueryService while head is 11",
            format!(
                "child facet {child_value} != 10 at pinned {version_a:?} (head {value_b} at {version_b:?}) child_version {:?} ancestry {:?}",
                child_snapshot.version, ancestry
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![
                EvidenceReference::new(
                    "public-surface:loom-client::QueryService::get_facet#fork-pinned",
                ),
                EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::fork#at_version",
                ),
            ],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    // 11. Verify fork history is pinned (1 event), not head (2).
    let child_history = match block_on(async {
        api.list_events(EventQuery::all(child_target)).await
    }) {
        Ok(events) => events,
        Err(error) => {
            let reason = format!(
                "list_events on fork target failed: {:?} - {}",
                error.code, error.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "fork history should be observable via public HistoryService and be pinned",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::HistoryService::list_events#fork",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    if child_history.len() != 1 {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "fork history should contain exactly 1 event (pinned) via public HistoryService",
            format!(
                "child history len {} != 1 (pinned {version_a:?}, head {version_b:?}, head len {}) child ancestry {:?}",
                child_history.len(),
                history_b.len(),
                ancestry
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::HistoryService::list_events#fork",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }
    if child_history[0].id != pinned_event_id {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "fork history event id should equal pinned seed EventId via public HistoryService",
            format!(
                "child event {} != pinned {}",
                child_history[0].id, pinned_event_id
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::HistoryService::list_events#fork",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }
    if child_history[0].event_ref() != pinned_event_ref {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "fork history must retain the pinned source EventRef including its source TimelineId",
            format!(
                "child event ref {:?} != pinned source event ref {:?}",
                child_history[0].event_ref(),
                pinned_event_ref
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![
                EvidenceReference::new(
                    "public-surface:loom-client::HistoryService::list_events#fork",
                ),
                EvidenceReference::new("validator:fork-history-event-ref"),
            ],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }
    // Order by EventSeq
    if child_history[0].sequence != history_a[0].sequence {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "fork history sequence should match pinned history via EventSeq ordering",
            format!(
                "child seq {:?} != pinned seq {:?}",
                child_history[0].sequence, history_a[0].sequence
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::HistoryService::list_events#fork",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    // 12. Re-verify source head still 11 after fork via public reads (stability).
    let facet_after_fork = match block_on(async {
        api.get_facet(FacetQuery::new(
            target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from("neutral.counter.value"),
        ))
        .await
    }) {
        Ok(value) => value,
        Err(error) => {
            let reason = format!(
                "get_facet on source after fork failed: {:?} - {}",
                error.code, error.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "source head should remain 11 after fork via public QueryService",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::QueryService::get_facet#source-after-fork",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    let value_after = facet_after_fork
        .as_ref()
        .and_then(|snap| snap.value.get("value").and_then(|value| value.as_i64()))
        .unwrap_or(-1);
    if value_after != 11 {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "source head should remain 11 after fork (pinned stability) via public QueryService",
            format!("source after fork {value_after} != 11"),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::QueryService::get_facet#source-after-fork",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    // 13. Verify history pagination / world_time consistency also visible via public APIs.
    // Use inspect_timeline on source to ensure world_time is still observable and version_b.
    let source_inspect = match block_on(async { api.inspect_timeline(target).await }) {
        Ok(snapshot) => snapshot,
        Err(error) => {
            let reason = format!(
                "inspect_timeline on source after fork failed: {:?} - {}",
                error.code, error.message
            );
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "source inspect should succeed via public TimelineService",
                reason.clone(),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![EvidenceReference::new(
                    "public-surface:loom-client::TimelineService::inspect_timeline#source",
                )],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    };
    if source_inspect.version != version_b {
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "source version should remain at head version_b after fork via public inspect_timeline",
            format!(
                "source_version {:?} != version_b {version_b:?} pinned {version_a:?}",
                source_inspect.version
            ),
            backend,
            format!("backend-harness:scope={scope} backend={}", backend.as_str()),
            vec![EvidenceReference::new(
                "public-surface:loom-client::TimelineService::inspect_timeline#source",
            )],
            ScenarioOutcome::Fail,
        );
        return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    // T08 requires the PostgreSQL pinned read to survive a genuine boundary
    // restart. Production contexts are reconnect-only; only an explicitly
    // controlled harness may claim this durable evidence.
    if backend.is_postgres() {
        if !context.can_perform_boundary_restart() {
            let reason = "CV-030 PostgreSQL durable pinned-read evidence requires a controlled application-boundary restart; this context only provides reconnect-only capability";
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "PostgreSQL pinned reads must be re-observed after a controlled boundary restart",
                reason,
                backend,
                format!(
                    "backend-harness:scope={scope} backend={} restart_capability={}",
                    backend.as_str(),
                    context.restart_capability().as_str()
                ),
                vec![
                    EvidenceReference::new("finding:gap:controlled-postgres-restart-required"),
                    EvidenceReference::new("validator:restart:controlled-boundary-required"),
                    EvidenceReference::new(
                        "public-surface:loom-client::TimelineService::inspect_timeline",
                    ),
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

        let fresh_client = match context.restart() {
            Ok(client) => client,
            Err(error) => {
                let reason = format!("controlled PostgreSQL boundary restart failed: {error}");
                let finding = Finding::new(
                    descriptor.id().clone(),
                    descriptor.name(),
                    "PostgreSQL pinned reads must be re-observed after a controlled boundary restart",
                    reason.clone(),
                    backend,
                    format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                    vec![
                        EvidenceReference::new("validator:restart:controlled-boundary-restart"),
                        EvidenceReference::new(
                            "public-surface:loom-client::TimelineService::inspect_timeline",
                        ),
                    ],
                    ScenarioOutcome::Fail,
                );
                return ScenarioResult::new(
                    descriptor.id().clone(),
                    ScenarioOutcome::Fail,
                    finding,
                )
                .with_capability_area(descriptor.capability_area().as_str());
            }
        };
        let fresh_api: Arc<dyn loom_api::LoomApi + Send + Sync> = Arc::new(fresh_client);
        let restart_observation = block_on(async {
            let source = fresh_api
                .inspect_timeline(target)
                .await
                .map_err(|error| format!("source inspect after restart failed: {error:?}"))?;
            let source_facet = fresh_api
                .get_facet(FacetQuery::new(
                    target,
                    FacetOwner::entity(entity_id),
                    FacetTypeId::from("neutral.counter.value"),
                ))
                .await
                .map_err(|error| format!("source facet after restart failed: {error:?}"))?;
            let source_history = fresh_api
                .list_events(EventQuery::all(target))
                .await
                .map_err(|error| format!("source history after restart failed: {error:?}"))?;
            let child = fresh_api
                .inspect_timeline(child_target)
                .await
                .map_err(|error| format!("fork inspect after restart failed: {error:?}"))?;
            let child_facet = fresh_api
                .get_facet(FacetQuery::new(
                    child_target,
                    FacetOwner::entity(entity_id),
                    FacetTypeId::from("neutral.counter.value"),
                ))
                .await
                .map_err(|error| format!("fork facet after restart failed: {error:?}"))?;
            let child_history = fresh_api
                .list_events(EventQuery::all(child_target))
                .await
                .map_err(|error| format!("fork history after restart failed: {error:?}"))?;
            Ok::<_, String>((
                source,
                source_facet,
                source_history,
                child,
                child_facet,
                child_history,
            ))
        });
        let (
            source_after_restart,
            source_facet_after_restart,
            source_history_after_restart,
            child_after_restart,
            child_facet_after_restart,
            child_history_after_restart,
        ) = match restart_observation {
            Ok(observation) => observation,
            Err(reason) => {
                let finding = Finding::new(
                    descriptor.id().clone(),
                    descriptor.name(),
                    "PostgreSQL public facet/history/inspect reads must survive a controlled restart",
                    reason,
                    backend,
                    format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                    vec![
                        EvidenceReference::new("validator:restart:controlled-boundary-restart"),
                        EvidenceReference::new(
                            "public-surface:loom-client::QueryService::get_facet",
                        ),
                        EvidenceReference::new(
                            "public-surface:loom-client::HistoryService::list_events",
                        ),
                        EvidenceReference::new(
                            "public-surface:loom-client::TimelineService::inspect_timeline",
                        ),
                    ],
                    ScenarioOutcome::Fail,
                );
                return ScenarioResult::new(
                    descriptor.id().clone(),
                    ScenarioOutcome::Fail,
                    finding,
                )
                .with_capability_area(descriptor.capability_area().as_str());
            }
        };
        let source_value_after_restart = source_facet_after_restart
            .as_ref()
            .and_then(|snapshot| snapshot.value.get("value").and_then(|value| value.as_i64()))
            .unwrap_or(-1);
        let child_value_after_restart = child_facet_after_restart
            .as_ref()
            .and_then(|snapshot| snapshot.value.get("value").and_then(|value| value.as_i64()))
            .unwrap_or(-1);
        let restart_history_ok = source_history_after_restart.len() == 2
            && child_history_after_restart.len() == 1
            && source_history_after_restart == history_b
            && child_history_after_restart == child_history
            && source_history_after_restart[0].sequence == version_a.head_event_seq
            && source_history_after_restart[1].sequence == version_b.head_event_seq
            && child_history_after_restart[0].event_ref() == pinned_event_ref;
        let restart_ancestry_ok = child_after_restart.version == version_a
            && child_after_restart.ancestry.parent_timeline_id == Some(timeline_id)
            && child_after_restart.ancestry.fork_parent_version == Some(version_a)
            && child_after_restart.ancestry.fork_parent_event == Some(pinned_event_ref);
        let restart_versions_ok = source_after_restart.version == version_b
            && source_after_restart.version.head_event_seq > version_a.head_event_seq
            && source_after_restart.version.state_revision > version_a.state_revision;
        if source_value_after_restart != 11
            || child_value_after_restart != 10
            || !restart_history_ok
            || !restart_ancestry_ok
            || !restart_versions_ok
        {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "PostgreSQL restart must preserve source head 11, fork pinned value 10, history EventSeq, TimelineVersion, and complete ancestry EventRef",
                format!(
                    "after restart source={source_after_restart:?} source_value={source_value_after_restart} source_history={source_history_after_restart:?}; child={child_after_restart:?} child_value={child_value_after_restart} child_history={child_history_after_restart:?}; history_ok={restart_history_ok} ancestry_ok={restart_ancestry_ok} versions_ok={restart_versions_ok}"
                ),
                backend,
                format!("backend-harness:scope={scope} backend={}", backend.as_str()),
                vec![
                    EvidenceReference::new("validator:restart:controlled-boundary-restart"),
                    EvidenceReference::new("public-surface:loom-client::QueryService::get_facet"),
                    EvidenceReference::new(
                        "public-surface:loom-client::HistoryService::list_events",
                    ),
                    EvidenceReference::new(
                        "public-surface:loom-client::TimelineService::inspect_timeline",
                    ),
                    EvidenceReference::new("validator:timeline-version-eventseq-state-revision"),
                    EvidenceReference::new("validator:fork-parent-event-ref"),
                ],
                ScenarioOutcome::Fail,
            );
            return ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str());
        }
    }

    // All checks passed. Produce PASS. Do not assert projection/blob is authority.
    let expected = "pinned/versioned read via fork at explicit TimelineVersion returns data consistent with the pinned revision/version contract rather than silently following newer active projection";
    let restart_note = if backend.is_postgres() {
        "; controlled PostgreSQL boundary restart/reconnect re-read source and fork public state"
    } else {
        ""
    };
    let actual = format!(
        "pinned stability verified: scope={scope} pinned_version={version_a:?} (value 10, history 1, event {pinned_event_id}, fork_parent_event {fork_parent_event:?}) head_version={version_b:?} (value 11, history 2) fork_target={fork_target} fork_version={fork_version:?} fork_value=10 fork_history=1 ancestry_fork_parent_version={ancestry_version:?} source_head_stable=11{restart_note}; inspected via public loom-api/loom-client only: WorldService::create_world_from_template, ActionService::invoke, QueryService::get_facet, HistoryService::list_events, TimelineService::fork at_version + inspect_timeline; no projection/blob authority asserted; T09 fence preserved",
        fork_parent_event = ancestry.fork_parent_event,
        fork_target = child_target.timeline_id,
        fork_version = child_snapshot.version,
        ancestry_version = ancestry.fork_parent_version,
    );

    let mut evidence = vec![
        EvidenceReference::new(
            "public-surface:loom-client::WorldService::create_world_from_template",
        ),
        EvidenceReference::new("public-surface:loom-client::ActionService::invoke#seed+increment"),
        EvidenceReference::new(
            "public-surface:loom-client::QueryService::get_facet#pinned+head+fork",
        ),
        EvidenceReference::new(
            "public-surface:loom-client::HistoryService::list_events#pinned+head+fork",
        ),
        EvidenceReference::new("public-surface:loom-client::TimelineService::fork#at_version"),
        EvidenceReference::new(
            "public-surface:loom-client::TimelineService::inspect_timeline#fork+source",
        ),
        EvidenceReference::new("validator:scenario:CV-030#pinned-stability"),
        EvidenceReference::new("doc:t08-coverage-matrix.md#CV-030"),
        EvidenceReference::new("t09-fence:preserved-no-lib-registry-edit"),
    ];
    if backend.is_postgres() {
        evidence.push(EvidenceReference::new(
            "validator:restart:controlled-boundary-restart",
        ));
    }

    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual,
        backend,
        format!(
            "backend-harness:scope={scope} backend={} pinned={version_a:?} head={version_b:?}",
            backend.as_str()
        ),
        evidence,
        ScenarioOutcome::Pass,
    );
    ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Pass, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

#[cfg(test)]
mod tests {
    use super::{CV_030, blocked_descriptors, descriptors, owns_cv, register, suite_name};
    use crate::ScenarioRegistry;
    use crate::scenario::ScenarioId;

    #[test]
    fn suite_metadata_is_stable() {
        assert_eq!(super::SUITE, "semantic_blob");
        assert_eq!(super::CV_RANGE, "CV-028..CV-030");
        assert_eq!(super::CAPABILITY_AREA, "semantic-blob");
        assert_eq!(suite_name(), "semantic_blob");
        assert!(owns_cv("CV-028"));
        assert!(owns_cv("CV-029"));
        assert!(owns_cv("CV-030"));
        assert!(!owns_cv("CV-027"));
        assert!(!owns_cv("CV-031"));
    }

    #[test]
    fn descriptors_expose_only_cv030_as_candidate() {
        let descs = descriptors();
        assert_eq!(descs.len(), 1, "only CV-030 should be registrable");
        assert_eq!(descs[0].id_str(), CV_030);
        assert_eq!(descs[0].capability_area().as_str(), super::CAPABILITY_AREA);
        // blocked gaps must not appear in registrable descriptors
        assert!(descs.iter().all(|d| owns_cv(d.id_str())));
        assert!(!descs.iter().any(|d| d.id_str() == "CV-028"));
        assert!(!descs.iter().any(|d| d.id_str() == "CV-029"));
        // but owns_cv still true for blocked range
        assert!(owns_cv("CV-028"));
        assert!(owns_cv("CV-029"));

        let blocked = blocked_descriptors();
        assert_eq!(blocked.len(), 2);
        assert!(blocked.iter().any(|d| d.id_str() == "CV-028"));
        assert!(blocked.iter().any(|d| d.id_str() == "CV-029"));
    }

    #[test]
    fn register_adds_only_cv030_and_preserves_t09_fence() {
        let mut registry = ScenarioRegistry::bootstrap();
        // Seed with stable 11 to simulate validator_registry baseline
        let stable = crate::validator_registry();
        assert_eq!(stable.len(), 11);
        for desc in stable.iter().cloned().collect::<Vec<_>>() {
            registry.register(desc).expect("stable should register");
        }
        assert_eq!(registry.len(), 11);
        let count = register(&mut registry).expect("register should succeed");
        assert_eq!(count, 1);
        assert_eq!(registry.len(), 12);
        assert!(registry.get(CV_030).is_some());
        assert!(registry.get("CV-028").is_none());
        assert!(registry.get("CV-029").is_none());
        // Ensure deterministic ordering
        let mut ids: Vec<_> = registry.iter().map(|d| d.id_str().to_string()).collect();
        ids.sort();
        assert_eq!(ids[0], "CV-001");
        assert_eq!(ids.last().unwrap(), "CV-030");
    }

    #[test]
    fn blocked_descriptors_are_not_registered_via_register() {
        let mut registry = ScenarioRegistry::bootstrap();
        register(&mut registry).expect("register");
        assert!(registry.get("CV-028").is_none());
        assert!(registry.get("CV-029").is_none());
        // blocked_descriptors remain documented but unregistered
        for desc in blocked_descriptors() {
            assert!(registry.get(desc.id_str()).is_none());
            // Ensure they still have stable IDs
            assert!(ScenarioId::try_new(desc.id_str()).is_ok());
        }
    }
}
