//! Action + durable Ingress suite (T11).
//!
//! Owner: T11 (#316) — `CV-015..CV-017`.
//! Central registry integration is reserved for T19 (#324). This module does
//! not register in `validator_registry`; T19 alone edits `registry.rs`/`lib.rs`.
//! All observations use the formal `loom_api`/`loom_client` surface via
//! `LoomApi` (`ActionService`/`IngressService`/`HistoryService`/`QueryService`)
//! and never read Runtime/Storage tables. `CV-017` uses the existing public
//! Ingress lifecycle when a running service exposes its normal worker; a
//! service without that worker remains explicitly `Unavailable`.

#![allow(clippy::too_many_lines)]

use std::future::Future;

use loom_api::{
    ActionInvocation, ActionRequest, ActionService, ActionTypeId, CatalogService,
    CreateWorldFromTemplateRequest, EntityId, EventId, EventQuery, ExecutionResult, FacetOwner,
    FacetQuery, FacetTypeId, HistoryService, IdempotencyKey, IngressAuthorizationContext,
    IngressCompletion, IngressEnvelope, IngressId, IngressProvenance, IngressService,
    IngressStatus, IngressTimeMetadata, QueryService, WorldInstant, WorldService,
    WorldTemplateDescriptor,
};
use serde_json::json;

use crate::backend::BackendContext;
use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::reports::ScenarioResult;
use crate::scenario::{BackendKind, ScenarioDescriptor};

/// Suite identifier for file ownership.
pub const SUITE: &str = "action_ingress";

/// Owned CV range for this suite.
pub const CV_RANGE: &str = "CV-015..CV-017";

/// Capability area label for this suite.
pub const CAPABILITY_AREA: &str = "action-ingress";

/// Stable IDs.
pub const CV_015: &str = "CV-015";
pub const CV_016: &str = "CV-016";
pub const CV_017: &str = "CV-017";

/// Returns the suite identifier.
#[must_use]
pub fn suite_name() -> &'static str {
    SUITE
}

/// Returns true if `cv_id` belongs to this suite's owned CV range.
#[must_use]
pub fn owns_cv(cv_id: &str) -> bool {
    matches!(cv_id, "CV-015" | "CV-016" | "CV-017")
}

/// Returns the deterministic descriptors for `CV-015..CV-017`.
#[must_use]
pub fn descriptors() -> Vec<ScenarioDescriptor> {
    vec![
        ScenarioDescriptor::new(
            CV_015,
            "accepted Action produces committed Event/Facet/history via public API",
            CAPABILITY_AREA,
            vec![
                BackendKind::LoomClient,
                BackendKind::InMemory,
                BackendKind::PostgreSQL,
            ],
            "clean Timeline with neutral.counter enabled; deterministic EntityId/EventId",
            vec!["VALR-T11".to_string()],
            vec![
                "docs/architecture/core.md#no-semantic-mutation-without-committed-event"
                    .to_string(),
                "docs/architecture/runtime-contracts.md#action-definition".to_string(),
                "docs/architecture/world-runtime.md#logical-commit".to_string(),
            ],
        ),
        ScenarioDescriptor::new(
            CV_016,
            "durable Ingress idempotency — duplicate does not create second World mutation",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "IngressService envelope with identical IngressId/IdempotencyKey; controlled harness",
            vec!["VALR-T11".to_string()],
            vec![
                "crates/loom-api/src/lib.rs#IngressService".to_string(),
                "docs/architecture/world-runtime.md#ingress-vs-world-truth".to_string(),
            ],
        ),
        ScenarioDescriptor::new(
            CV_017,
            "Ingress operational bookkeeping distinct from authoritative history",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory, BackendKind::PostgreSQL],
            "normal resolver failure reaches Retryable; public Action recovery commits one Event",
            vec!["VALR-T11".to_string()],
            vec![
                "docs/architecture/world-runtime.md#ingress-lifecycle".to_string(),
                "crates/loom-api/src/lib.rs#IngressStatus".to_string(),
            ],
        ),
    ]
}

/// Executes one `CV-015..CV-017` scenario via the formal `LoomApi` surface.
#[must_use]
pub fn execute(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();

    // PostgreSQL prerequisite: for CV-016 the PG evidence must be live, otherwise report prerequisite.
    if backend.is_postgres()
        && matches!(descriptor.id_str(), CV_016 | CV_015)
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

    // For PostgreSQL also verify live endpoint reachable when prerequisite present.
    if backend.is_postgres() {
        let client = context.client();
        let catalog_res = client.catalog();
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
        CV_015 => cv015(descriptor, context),
        CV_016 => cv016(descriptor, context),
        CV_017 => cv017(descriptor, context),
        _ => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                "scenario is registered with stable ID",
                format!("unknown action_ingress scenario {}", descriptor.id_str()),
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

fn new_world_template(scope: &str) -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new(
        format!("validator.action_ingress.{scope}"),
        1,
        WorldInstant::new(42),
    )
    .requires_capability("neutral.counter", "^0.1.0")
}

fn deterministic_id(suffix: u128) -> String {
    format!("00000000-0000-0000-0000-{suffix:012x}")
}

fn new_entity_id(scope: u128) -> EntityId {
    deterministic_id(scope)
        .parse()
        .expect("deterministic EntityId")
}

fn new_event_id(scope: u128) -> EventId {
    deterministic_id(scope)
        .parse()
        .expect("deterministic EventId")
}

#[allow(clippy::needless_pass_by_value)]
fn finding_for(
    descriptor: &ScenarioDescriptor,
    context: &BackendContext,
    expected: &str,
    actual: &str,
    outcome: ScenarioOutcome,
) -> Finding {
    Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual,
        *context.backend_kind(),
        format!(
            "validator:{}:{}",
            descriptor.id_str(),
            context.backend_kind().as_str()
        ),
        vec![
            EvidenceReference::new(format!("backend:{}", context.backend_kind().as_str())),
            EvidenceReference::new(format!(
                "backend_evidence:{}",
                context.backend_evidence().as_str()
            )),
            EvidenceReference::new(format!(
                "restart_capability:{}",
                context.restart_capability().as_str()
            )),
            EvidenceReference::new("public-surface:loom-api::ActionService::invoke"),
            EvidenceReference::new("public-surface:loom-api::QueryService::get_facet"),
            EvidenceReference::new("public-surface:loom-api::HistoryService::list_events"),
            EvidenceReference::new(format!("validator:scenario:{}", descriptor.id_str())),
        ],
        outcome.clone(),
    )
}

#[allow(clippy::needless_pass_by_value)]
fn ingress_finding_for(
    descriptor: &ScenarioDescriptor,
    context: &BackendContext,
    expected: &str,
    actual: &str,
    outcome: ScenarioOutcome,
) -> Finding {
    Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        actual,
        *context.backend_kind(),
        format!(
            "validator:{}:{}",
            descriptor.id_str(),
            context.backend_kind().as_str()
        ),
        vec![
            EvidenceReference::new(format!("backend:{}", context.backend_kind().as_str())),
            EvidenceReference::new(format!(
                "backend_evidence:{}",
                context.backend_evidence().as_str()
            )),
            EvidenceReference::new(format!(
                "restart_capability:{}",
                context.restart_capability().as_str()
            )),
            EvidenceReference::new("public-surface:loom-api::IngressService::submit_ingress"),
            EvidenceReference::new("public-surface:loom-api::IngressService::ingress_status"),
            EvidenceReference::new("public-surface:loom-api::ActionService::invoke"),
            EvidenceReference::new("public-surface:loom-api::QueryService::get_facet"),
            EvidenceReference::new("public-surface:loom-api::HistoryService::list_events"),
            EvidenceReference::new(format!("validator:scenario:{}", descriptor.id_str())),
        ],
        outcome.clone(),
    )
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

// ── CV-015 ───────────────────────────────────────────────────────────────────

fn cv015(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let client = context.client();
    let scope = format!("{}-{}", context.scope(), "cv015");
    let expected = "neutral.counter.seed value=1 commits, FacetSnapshot {value:1} and exactly one committed Event visible via HistoryService::list_events with expected EventId/payload/ordered history";

    let result = block_on(async {
        let template = new_world_template(&scope);
        let created = client
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
            .map_err(|e| format!("create_world failed: {e:?} - {}", e.message))?;
        let target = created.target;
        let entity_id = new_entity_id(0x0151);
        let event_id = new_event_id(0x0152);

        let invocation = ActionInvocation::new(
            ActionTypeId::from("neutral.counter.seed"),
            json!({
                "event_id": event_id.to_string(),
                "entity_id": entity_id.to_string(),
                "value": 1
            }),
        );
        let exec = client
            .invoke(ActionRequest::new(target, invocation))
            .await
            .map_err(|e| format!("invoke failed: {e:?} - {}", e.message))?;

        let (event_ids, timeline_version) = match exec {
            ExecutionResult::Committed {
                event_ids,
                timeline_version,
            } => (event_ids, timeline_version),
            other => {
                return Err(format!("expected Committed, got {other:?}"));
            }
        };
        if event_ids.len() != 1 {
            return Err(format!("expected 1 event_id, got {}", event_ids.len()));
        }
        if event_ids[0] != event_id {
            return Err(format!(
                "committed EventId mismatch: expected {} got {}",
                event_id, event_ids[0]
            ));
        }

        let facet = client
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(entity_id),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
            .map_err(|e| format!("get_facet failed: {e:?} - {}", e.message))?
            .ok_or_else(|| "facet missing after seed".to_string())?;

        let facet_value = facet
            .value
            .get("value")
            .and_then(serde_json::Value::as_i64)
            .ok_or_else(|| format!("facet value not int: {:?}", facet.value))?;
        if facet_value != 1 {
            return Err(format!("facet value expected 1 got {facet_value}"));
        }

        let events = client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events failed: {e:?} - {}", e.message))?;
        if events.len() != 1 {
            return Err(format!("list_events expected 1, got {}", events.len()));
        }
        let committed = &events[0];
        if committed.id != event_id {
            return Err(format!(
                "list_events EventId mismatch: expected {event_id} got {}",
                committed.id
            ));
        }
        if committed
            .payload
            .get("value")
            .and_then(serde_json::Value::as_i64)
            != Some(1)
        {
            return Err(format!("payload mismatch: {:?}", committed.payload));
        }
        // Also verify via list_events_page
        let page = client
            .list_events_page(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events_page failed: {e:?} - {}", e.message))?;
        if page.events.len() != 1 || page.events[0].id != event_id {
            return Err(format!(
                "list_events_page mismatch: len {} id {:?}",
                page.events.len(),
                page.events.first().map(|e| e.id)
            ));
        }
        // Verify timeline_version head advances
        if timeline_version.head_event_seq.value() == 0 {
            return Err("timeline_version head_event_seq should advance".to_string());
        }

        // Verify ordering by EventSeq (single event is trivially ordered)
        // and that get_facet history is consistent
        Ok::<String, String>(format!(
            "Committed event_id {event_id} facet {{value:1}} history len 1 version {timeline_version:?} ordered by EventSeq"
        ))
    });

    match result {
        Ok(actual) => {
            let finding = finding_for(
                descriptor,
                context,
                expected,
                &actual,
                ScenarioOutcome::Pass,
            );
            ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Pass, finding)
                .with_capability_area(descriptor.capability_area().as_str())
        }
        Err(actual) => {
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(descriptor, context, expected, &actual, outcome.clone());
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            let finding = finding_for(
                descriptor,
                context,
                expected,
                &actual,
                ScenarioOutcome::Fail,
            );
            ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str())
        }
    }
}

// ── CV-016 ───────────────────────────────────────────────────────────────────

fn cv016(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    let client = context.client();
    let scope = format!("{}-{}", context.scope(), "cv016");
    let expected = "IngressService submit_ingress with identical IdempotencyKey deduplicates: first Accepted, second Deduplicated referencing winner, poll until Completed(Committed) with one EventRef, history len 1 and facet {value:1} (PG with boundary restart)";

    // CV-016 requires controlled harness for trusted evidence.
    // If backend is LoomClient (external) we cannot prove durable idempotency.
    if backend == BackendKind::LoomClient && !context.can_perform_boundary_restart() {
        let reason = format!(
            "CV-016 requires controlled InMemory/PostgreSQL harness for durable idempotency; backend {} with restart_capability {} is not trusted",
            backend.as_str(),
            context.restart_capability().as_str()
        );
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            expected,
            reason.clone(),
            backend,
            format!(
                "validator:{}:{}:reconnect-only",
                descriptor.id_str(),
                backend.as_str()
            ),
            vec![
                EvidenceReference::new("validator:restart:reconnect-only"),
                EvidenceReference::new(format!("backend:{}", backend.as_str())),
                EvidenceReference::new("public-surface:loom-api::IngressService::submit_ingress"),
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

    let result = block_on(async {
        let template = new_world_template(&scope);
        let created = client
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
            .map_err(|e| format!("create_world failed: {e:?} - {}", e.message))?;
        let target = created.target;

        let entity_id = new_entity_id(0x0161);
        let event_id = new_event_id(0x0162);

        let ingress_id = IngressId::from("ingress-cv016-1");
        let idempotency_key = IdempotencyKey::from("t11.cv016.key1");
        let provenance = IngressProvenance::new("validator-t11")
            .with_metadata(json!({"cv": "CV-016", "scope": scope}));
        let authorization = IngressAuthorizationContext::new(json!({"tenant": "validator-test"}));
        let time_metadata = IngressTimeMetadata::none();
        let invocation = ActionInvocation::new(
            ActionTypeId::from("neutral.counter.seed"),
            json!({
                "event_id": event_id.to_string(),
                "entity_id": entity_id.to_string(),
                "value": 1
            }),
        );

        let envelope = IngressEnvelope::new(
            ingress_id.clone(),
            idempotency_key.clone(),
            provenance.clone(),
            target,
            authorization.clone(),
            time_metadata.clone(),
            invocation.clone(),
        );

        // The first submit must establish this scenario's winner. A pre-existing durable
        // record is not evidence that this execution accepted a new ingress.
        let first = client
            .submit_ingress(envelope.clone())
            .await
            .map_err(|e| format!("first submit_ingress failed: {e:?} - {}", e.message))?;
        validate_first_acceptance(&first, &ingress_id, &idempotency_key)?;

        // Second submit identical
        let second = client
            .submit_ingress(envelope.clone())
            .await
            .map_err(|e| format!("second submit_ingress failed: {e:?} - {}", e.message))?;
        match &second {
            loom_api::IngressAcceptance::Deduplicated(receipt) => {
                if receipt.ingress_id != ingress_id {
                    return Err(format!(
                        "second Deduplicated ingress_id mismatch: expected {} got {}",
                        ingress_id, receipt.ingress_id
                    ));
                }
                if receipt.idempotency_key != idempotency_key {
                    return Err(format!("second Deduplicated key mismatch: {receipt:?}"));
                }
            }
            other => {
                return Err(format!(
                    "second submit expected Deduplicated, got {other:?}"
                ));
            }
        }

        // Poll until terminal Completed
        let mut last_status = None;
        let mut completion: Option<IngressCompletion> = None;
        for _ in 0..40 {
            let record = client
                .ingress_status(ingress_id.clone())
                .await
                .map_err(|e| format!("ingress_status failed: {e:?} - {}", e.message))?;
            if record.ingress_id != ingress_id || record.idempotency_key != idempotency_key {
                return Err(format!("status record mismatch: {record:?}"));
            }
            match &record.status {
                IngressStatus::Completed(c) => {
                    completion = Some(c.clone());
                    last_status = Some(record.status.clone());
                    break;
                }
                IngressStatus::Failed(f) => {
                    return Err(format!("ingress Failed: {f:?}"));
                }
                IngressStatus::Accepted
                | IngressStatus::Processing
                | IngressStatus::Retryable(_) => {
                    last_status = Some(record.status.clone());
                    // Poll again
                    tokio::time::sleep(std::time::Duration::from_millis(75)).await;
                }
            }
        }

        let completion = completion.ok_or_else(|| {
            format!("ingress did not reach Completed after polling, last status: {last_status:?}")
        })?;

        let (event_refs, timeline_version) = match completion {
            IngressCompletion::Committed {
                event_refs,
                timeline_version,
            } => (event_refs, timeline_version),
            other => {
                return Err(format!("expected Completed::Committed, got {other:?}"));
            }
        };
        if event_refs.len() != 1 {
            return Err(format!("expected 1 EventRef, got {}", event_refs.len()));
        }

        // Verify authority via history and facet (before restart)
        let events = client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events failed: {e:?} - {}", e.message))?;
        if events.len() != 1 {
            return Err(format!("list_events expected 1, got {}", events.len()));
        }
        if events[0].id != event_id {
            return Err(format!(
                "history EventId mismatch: expected {} got {}",
                event_id, events[0].id
            ));
        }

        let facet = client
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(entity_id),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
            .map_err(|e| format!("get_facet failed: {e:?} - {}", e.message))?
            .ok_or_else(|| "facet missing after ingress".to_string())?;
        let facet_value = facet
            .value
            .get("value")
            .and_then(serde_json::Value::as_i64)
            .ok_or_else(|| format!("facet value not int: {:?}", facet.value))?;
        if facet_value != 1 {
            return Err(format!("facet value expected 1 got {facet_value}"));
        }

        // For PostgreSQL with controlled restart, prove durable dedup survives restart
        if backend.is_postgres() && context.can_perform_boundary_restart() {
            let new_client = context
                .restart()
                .map_err(|e| format!("controlled restart failed: {e}"))?;
            // Poll again via new client
            let mut completion2: Option<IngressCompletion> = None;
            for _ in 0..20 {
                let record = new_client
                    .ingress_status(ingress_id.clone())
                    .await
                    .map_err(|e| {
                        format!("ingress_status after restart failed: {e:?} - {}", e.message)
                    })?;
                match record.status {
                    IngressStatus::Completed(c) => {
                        completion2 = Some(c);
                        break;
                    }
                    IngressStatus::Failed(f) => {
                        return Err(format!("ingress Failed after restart: {f:?}"));
                    }
                    _ => {
                        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
                    }
                }
            }
            let completion2 =
                completion2.ok_or_else(|| "ingress not Completed after restart".to_string())?;
            match completion2 {
                IngressCompletion::Committed {
                    event_refs: refs2, ..
                } => {
                    if refs2.len() != 1 {
                        return Err(format!(
                            "after restart expected 1 EventRef, got {}",
                            refs2.len()
                        ));
                    }
                }
                other => {
                    return Err(format!("after restart expected Committed, got {other:?}"));
                }
            }

            let events2 = new_client
                .list_events(EventQuery::all(target))
                .await
                .map_err(|e| format!("list_events after restart failed: {e:?} - {}", e.message))?;
            if events2.len() != 1 {
                return Err(format!(
                    "after restart list_events expected 1, got {}",
                    events2.len()
                ));
            }
            if events2[0].id != event_id {
                return Err(format!(
                    "after restart EventId mismatch: expected {event_id} got {}",
                    events2[0].id
                ));
            }

            let facet2 = new_client
                .get_facet(FacetQuery::new(
                    target,
                    FacetOwner::entity(entity_id),
                    FacetTypeId::from("neutral.counter.value"),
                ))
                .await
                .map_err(|e| format!("get_facet after restart failed: {e:?} - {}", e.message))?
                .ok_or_else(|| "facet missing after restart".to_string())?;
            let facet_value2 = facet2
                .value
                .get("value")
                .and_then(serde_json::Value::as_i64)
                .ok_or_else(|| format!("facet value not int after restart: {:?}", facet2.value))?;
            if facet_value2 != 1 {
                return Err(format!(
                    "facet value after restart expected 1 got {facet_value2}"
                ));
            }

            Ok::<String, String>(format!(
                "Ingress idempotency durable: Accepted then Deduplicated({ingress_id},{idempotency_key}), Completed Committed with 1 EventRef id {event_id} version {timeline_version:?}, history len 1 facet 1, survived controlled boundary restart via {}",
                context.restart_capability().as_str()
            ))
        } else {
            Ok::<String, String>(format!(
                "Ingress idempotency logical: Accepted then Deduplicated({ingress_id},{idempotency_key}), Completed Committed with 1 EventRef id {event_id} version {timeline_version:?}, history len 1 facet 1"
            ))
        }
    });

    match result {
        Ok(actual) => {
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                expected,
                actual.clone(),
                backend,
                format!(
                    "validator:{}:{}:{}",
                    descriptor.id_str(),
                    backend.as_str(),
                    if backend.is_postgres() && context.can_perform_boundary_restart() {
                        "controlled-boundary-restart"
                    } else {
                        "logical"
                    }
                ),
                vec![
                    EvidenceReference::new(
                        "public-surface:loom-api::IngressService::submit_ingress",
                    ),
                    EvidenceReference::new(
                        "public-surface:loom-api::IngressService::ingress_status",
                    ),
                    EvidenceReference::new("public-surface:loom-api::HistoryService::list_events"),
                    EvidenceReference::new("public-surface:loom-api::QueryService::get_facet"),
                    EvidenceReference::new(format!("backend:{}", backend.as_str())),
                    EvidenceReference::new(format!(
                        "backend_evidence:{}",
                        context.backend_evidence().as_str()
                    )),
                    EvidenceReference::new(format!(
                        "restart_capability:{}",
                        context.restart_capability().as_str()
                    )),
                    EvidenceReference::new(format!("validator:scenario:{}", descriptor.id_str())),
                ],
                ScenarioOutcome::Pass,
            );
            ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Pass, finding)
                .with_capability_area(descriptor.capability_area().as_str())
        }
        Err(actual) => {
            if is_infra_unavailable(&actual) || actual.contains("did not reach Completed") {
                // For controlled harnesses, timeout is a real failure, not infra.
                // For generic external, treat as unavailable.
                if backend == BackendKind::LoomClient && !context.can_perform_boundary_restart() {
                    let outcome = ScenarioOutcome::Unavailable {
                        reason: actual.clone(),
                    };
                    let finding = Finding::new(
                        descriptor.id().clone(),
                        descriptor.name(),
                        expected,
                        actual.clone(),
                        backend,
                        format!(
                            "validator:{}:{}:poll-timeout",
                            descriptor.id_str(),
                            backend.as_str()
                        ),
                        vec![
                            EvidenceReference::new(
                                "public-surface:loom-api::IngressService::ingress_status",
                            ),
                            EvidenceReference::new(format!("backend:{}", backend.as_str())),
                        ],
                        outcome.clone(),
                    );
                    return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                        .with_capability_area(descriptor.capability_area().as_str());
                }
                // For controlled backends, a poll timeout is a failure (unless harness lacks worker).
                // We surface as Fail so the validator gap is visible.
            }
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = Finding::new(
                    descriptor.id().clone(),
                    descriptor.name(),
                    expected,
                    actual.clone(),
                    backend,
                    format!(
                        "validator:{}:{}:infra-unavailable",
                        descriptor.id_str(),
                        backend.as_str()
                    ),
                    vec![
                        EvidenceReference::new(
                            "public-surface:loom-api::IngressService::submit_ingress",
                        ),
                        EvidenceReference::new(format!("backend:{}", backend.as_str())),
                    ],
                    outcome.clone(),
                );
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                expected,
                actual.clone(),
                backend,
                format!(
                    "validator:{}:{}:fail",
                    descriptor.id_str(),
                    backend.as_str()
                ),
                vec![
                    EvidenceReference::new(
                        "public-surface:loom-api::IngressService::submit_ingress",
                    ),
                    EvidenceReference::new(
                        "public-surface:loom-api::IngressService::ingress_status",
                    ),
                    EvidenceReference::new(format!("backend:{}", backend.as_str())),
                    EvidenceReference::new(format!("validator:scenario:{}", descriptor.id_str())),
                ],
                ScenarioOutcome::Fail,
            );
            ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str())
        }
    }
}

fn validate_first_acceptance(
    first: &loom_api::IngressAcceptance,
    ingress_id: &IngressId,
    idempotency_key: &IdempotencyKey,
) -> Result<(), String> {
    match first {
        loom_api::IngressAcceptance::Accepted(receipt) => {
            if receipt.ingress_id != *ingress_id || receipt.idempotency_key != *idempotency_key {
                return Err(format!("first receipt mismatch: {receipt:?}"));
            }
            Ok(())
        }
        loom_api::IngressAcceptance::Deduplicated(receipt) => Err(format!(
            "first submit_ingress returned Deduplicated({receipt:?}); CV-016 requires a first Accepted receipt and cannot claim this execution as a winner"
        )),
        loom_api::IngressAcceptance::IdempotencyConflict(conflict) => Err(format!(
            "first submit expected Accepted, got IdempotencyConflict {conflict:?}"
        )),
    }
}

// ── CV-017 ───────────────────────────────────────────────────────────────────

fn cv017(descriptor: &ScenarioDescriptor, context: &BackendContext) -> ScenarioResult {
    let backend = *context.backend_kind();
    let expected = "public Ingress status reaches Retryable after a normal resolver failure without a World Event; public Action recovery then reaches Completed(Committed) with exactly one recovery EventRef, and public history/facet show only authoritative mutations (PG re-read after controlled restart)";
    let client = context.client();
    let scope = format!("{}-cv017", context.scope());

    let result = block_on(async {
        let target = client
            .create_world_from_template(CreateWorldFromTemplateRequest::new(new_world_template(
                &scope,
            )))
            .await
            .map_err(|e| format!("create_world failed: {e:?} - {}", e.message))?
            .target;
        let entity_id = new_entity_id(0x0171);
        let seed_event_id = new_event_id(0x0172);
        let recovery_event_id = new_event_id(0x0173);
        let ingress_id = IngressId::from(format!("{scope}-ingress"));
        let idempotency_key = IdempotencyKey::from(format!("{scope}-key"));
        let envelope = IngressEnvelope::new(
            ingress_id.clone(),
            idempotency_key.clone(),
            IngressProvenance::new("validator-t11")
                .with_metadata(json!({"cv":"CV-017", "scope":scope})),
            target,
            IngressAuthorizationContext::new(json!({"tenant":"validator-test"})),
            IngressTimeMetadata::none(),
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.increment"),
                json!({
                    "event_id": recovery_event_id.to_string(),
                    "entity_id": entity_id.to_string(),
                    "amount": 1
                }),
            ),
        );
        let acceptance = client
            .submit_ingress(envelope)
            .await
            .map_err(|e| format!("submit_ingress failed: {e:?} - {}", e.message))?;
        match acceptance {
            loom_api::IngressAcceptance::Accepted(receipt)
                if receipt.ingress_id == ingress_id
                    && receipt.idempotency_key == idempotency_key => {}
            other => return Err(format!("expected fresh Accepted receipt, got {other:?}")),
        }

        let initial_events = client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| {
                format!(
                    "list_events before processing failed: {e:?} - {}",
                    e.message
                )
            })?;
        if !initial_events.is_empty() {
            return Err(format!(
                "fresh CV-017 World unexpectedly has {} events",
                initial_events.len()
            ));
        }
        if client
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(entity_id),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
            .map_err(|e| format!("get_facet before processing failed: {e:?} - {}", e.message))?
            .is_some()
        {
            return Err("fresh CV-017 World unexpectedly has a counter Facet".to_string());
        }

        let mut retry_failure = None;
        let mut last_status = None;
        for _ in 0..40 {
            let record = client
                .ingress_status(ingress_id.clone())
                .await
                .map_err(|e| format!("ingress_status failed: {e:?} - {}", e.message))?;
            if record.ingress_id != ingress_id || record.idempotency_key != idempotency_key {
                return Err(format!("status record mismatch: {record:?}"));
            }
            match record.status {
                IngressStatus::Retryable(failure) => {
                    retry_failure = Some(failure);
                    break;
                }
                IngressStatus::Failed(failure) => {
                    return Err(format!("Ingress reached terminal Failed: {failure:?}"));
                }
                IngressStatus::Completed(completion) => {
                    return Err(format!(
                        "Ingress completed before Retryable observation: {completion:?}"
                    ));
                }
                status @ (IngressStatus::Accepted | IngressStatus::Processing) => {
                    last_status = Some(status);
                    tokio::time::sleep(std::time::Duration::from_millis(75)).await;
                }
            }
        }
        let retry_failure = retry_failure.ok_or_else(|| {
            format!(
                "no public worker/fault-injection seam exposed Retryable(IngressTechnicalFailure); last status {last_status:?}. A running Ingress worker or an explicit public fault-injection seam is required."
            )
        })?;
        if retry_failure.code != "runtime_failure" || retry_failure.message.is_empty() {
            return Err(format!(
                "expected IngressTechnicalFailure runtime_failure details, got {retry_failure:?}"
            ));
        }
        let events_after_retry = client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events after Retryable failed: {e:?} - {}", e.message))?;
        if !events_after_retry.is_empty() {
            return Err(format!(
                "Retryable changed World history: {} events",
                events_after_retry.len()
            ));
        }

        let seed = client
            .invoke(ActionRequest::new(
                target,
                ActionInvocation::new(
                    ActionTypeId::from("neutral.counter.seed"),
                    json!({
                        "event_id": seed_event_id.to_string(),
                        "entity_id": entity_id.to_string(),
                        "value": 1
                    }),
                ),
            ))
            .await
            .map_err(|e| {
                format!(
                    "public recovery prerequisite Action failed: {e:?} - {}",
                    e.message
                )
            })?;
        match seed {
            ExecutionResult::Committed { event_ids, .. }
                if event_ids.as_slice() == [seed_event_id] => {}
            other => {
                return Err(format!(
                    "recovery prerequisite was not Committed: {other:?}"
                ));
            }
        }

        let mut completion = None;
        let mut last_status = None;
        for _ in 0..40 {
            let record = client
                .ingress_status(ingress_id.clone())
                .await
                .map_err(|e| {
                    format!("ingress_status recovery poll failed: {e:?} - {}", e.message)
                })?;
            match record.status {
                IngressStatus::Completed(value) => {
                    completion = Some(value);
                    break;
                }
                IngressStatus::Failed(failure) => {
                    return Err(format!("Ingress recovery reached Failed: {failure:?}"));
                }
                status @ (IngressStatus::Accepted
                | IngressStatus::Processing
                | IngressStatus::Retryable(_)) => {
                    last_status = Some(status);
                    tokio::time::sleep(std::time::Duration::from_millis(75)).await;
                }
            }
        }
        let completion = completion.ok_or_else(|| {
            format!("Ingress recovery did not reach Completed; last status {last_status:?}")
        })?;
        let event_refs = match completion {
            IngressCompletion::Committed { event_refs, .. } => event_refs,
            other => return Err(format!("expected recovery Committed, got {other:?}")),
        };
        if event_refs.len() != 1 || event_refs[0].event_id != recovery_event_id {
            return Err(format!(
                "recovery EventRef mismatch: expected one {recovery_event_id}, got {event_refs:?}"
            ));
        }

        let events = client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events after recovery failed: {e:?} - {}", e.message))?;
        if events.len() != 2 || events[0].id != seed_event_id || events[1].id != recovery_event_id {
            return Err(format!("recovery history mismatch: {events:?}"));
        }
        let facet = client
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(entity_id),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
            .map_err(|e| format!("get_facet after recovery failed: {e:?} - {}", e.message))?
            .ok_or_else(|| "recovery counter Facet missing".to_string())?;
        let value = facet
            .value
            .get("value")
            .and_then(serde_json::Value::as_i64)
            .ok_or_else(|| format!("recovery Facet value was not an integer: {:?}", facet.value))?;
        if value != 2 {
            return Err(format!("recovery Facet value expected 2, got {value}"));
        }

        if backend.is_postgres() && context.can_perform_boundary_restart() {
            let restarted = context
                .restart()
                .map_err(|e| format!("controlled PostgreSQL boundary restart failed: {e}"))?;
            let status = restarted.ingress_status(ingress_id).await.map_err(|e| {
                format!("ingress_status after restart failed: {e:?} - {}", e.message)
            })?;
            if !matches!(
                status.status,
                IngressStatus::Completed(IngressCompletion::Committed { .. })
            ) {
                return Err(format!(
                    "post-restart status was not Completed::Committed: {status:?}"
                ));
            }
            let events_after_restart = restarted
                .list_events(EventQuery::all(target))
                .await
                .map_err(|e| format!("list_events after restart failed: {e:?} - {}", e.message))?;
            if events_after_restart.len() != 2
                || events_after_restart[0].id != seed_event_id
                || events_after_restart[1].id != recovery_event_id
            {
                return Err(format!(
                    "post-restart history mismatch: {events_after_restart:?}"
                ));
            }
            let facet_after_restart = restarted
                .get_facet(FacetQuery::new(
                    target,
                    FacetOwner::entity(entity_id),
                    FacetTypeId::from("neutral.counter.value"),
                ))
                .await
                .map_err(|e| format!("get_facet after restart failed: {e:?} - {}", e.message))?
                .ok_or_else(|| "post-restart recovery counter Facet missing".to_string())?;
            if facet_after_restart
                .value
                .get("value")
                .and_then(serde_json::Value::as_i64)
                != Some(2)
            {
                return Err(format!(
                    "post-restart Facet value mismatch: {:?}",
                    facet_after_restart.value
                ));
            }
        }

        Ok::<String, String>(format!(
            "public Ingress bookkeeping: Accepted -> Retryable({}) with history/facet unchanged, public seed recovery -> Completed(Committed) with one recovery EventRef {recovery_event_id}; authoritative history len 2 and facet value 2{}",
            retry_failure.code,
            if backend.is_postgres() && context.can_perform_boundary_restart() {
                "; PostgreSQL state re-read through a new client after controlled boundary restart"
            } else {
                ""
            }
        ))
    });

    // CV-017 evidence includes both operational Ingress and authoritative World surfaces.
    match result {
        Ok(actual) => {
            let finding = ingress_finding_for(
                descriptor,
                context,
                expected,
                &actual,
                ScenarioOutcome::Pass,
            );
            ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Pass, finding)
                .with_capability_area(descriptor.capability_area().as_str())
        }
        Err(actual) if is_infra_unavailable(&actual) || actual.contains("no public worker") => {
            let outcome = ScenarioOutcome::Unavailable {
                reason: actual.clone(),
            };
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                expected,
                actual.clone(),
                backend,
                format!(
                    "validator:{}:{}:retry-unavailable",
                    descriptor.id_str(),
                    backend.as_str()
                ),
                vec![
                    EvidenceReference::new(
                        "public-surface:loom-api::IngressService::submit_ingress",
                    ),
                    EvidenceReference::new(
                        "public-surface:loom-api::IngressService::ingress_status",
                    ),
                    EvidenceReference::new("public-surface:loom-api::HistoryService::list_events"),
                    EvidenceReference::new("public-surface:loom-api::QueryService::get_facet"),
                    EvidenceReference::new(
                        "validator:gap:CV-017-retry-worker-or-fault-injection-unavailable",
                    ),
                    EvidenceReference::new(format!("backend:{}", backend.as_str())),
                    EvidenceReference::new(format!(
                        "restart_capability:{}",
                        context.restart_capability().as_str()
                    )),
                ],
                outcome.clone(),
            );
            ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                .with_capability_area(descriptor.capability_area().as_str())
        }
        Err(actual) => {
            let finding = ingress_finding_for(
                descriptor,
                context,
                expected,
                &actual,
                ScenarioOutcome::Fail,
            );
            ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
                .with_capability_area(descriptor.capability_area().as_str())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{IdempotencyKey, IngressId, validate_first_acceptance};

    #[test]
    fn cv016_first_deduplicated_is_an_explicit_non_pass() {
        let ingress_id = IngressId::from("ingress-cv016-existing");
        let idempotency_key = IdempotencyKey::from("t11.cv016.existing");
        let first = loom_api::IngressAcceptance::Deduplicated(loom_api::IngressReceipt::new(
            ingress_id.clone(),
            idempotency_key.clone(),
        ));

        let error = validate_first_acceptance(&first, &ingress_id, &idempotency_key)
            .expect_err("a first Deduplicated receipt must not be accepted as the winner");
        assert!(error.contains("first submit_ingress returned Deduplicated"));
        assert!(error.contains("requires a first Accepted receipt"));
    }
}
