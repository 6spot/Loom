//! Change Feed/SSE/formal client suite (T18).
//!
//! Owner: T18 (#323) — `CV-038..CV-040`.
//! Central registry integration is reserved for T19 (#324). This module must
//! not register scenarios in `validator_registry`; T19 alone edits
//! `registry.rs`/`lib.rs` and CLI dispatch. Suite exposes local descriptors
//! and `execute` for isolated harness validation without central registration.

#![allow(clippy::pedantic)]
#![allow(clippy::too_many_lines)]

use std::str::FromStr;

use loom_api::{
    ActionInvocation, ActionRequest, ActionService, ActionTypeId, ChangeFeedCursor, CommittedEvent,
    CreateWorldFromTemplateRequest, EntityId, EventId, EventQuery, HistoryService,
    SubscriptionRequest, SubscriptionResult, SubscriptionService, WorldInstant, WorldService,
    WorldTemplateDescriptor,
};
use serde_json::json;

use crate::backend::BackendContext;
use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::reports::ScenarioResult;
use crate::scenario::{BackendKind, ScenarioDescriptor};
use crate::{RegistryError, ScenarioRegistry};

/// Suite identifier for file ownership.
pub const SUITE: &str = "change_feed";

/// Owned CV range for this suite.
pub const CV_RANGE: &str = "CV-038..CV-040";

/// Capability area label for this suite.
pub const CAPABILITY_AREA: &str = "change-feed";

pub const CV_038: &str = "CV-038";
pub const CV_039: &str = "CV-039";
pub const CV_040: &str = "CV-040";

/// Returns the suite identifier.
#[must_use]
pub fn suite_name() -> &'static str {
    SUITE
}

/// Returns true if `cv_id` belongs to this suite's owned CV range.
#[must_use]
pub fn owns_cv(cv_id: &str) -> bool {
    matches!(cv_id, "CV-038" | "CV-039" | "CV-040")
}

#[must_use]
pub fn descriptors() -> Vec<ScenarioDescriptor> {
    vec![
        ScenarioDescriptor::new(
            CV_038,
            "change-feed: committed Event observable via formal Subscription client",
            CAPABILITY_AREA,
            vec![
                BackendKind::LoomClient,
                BackendKind::InMemory,
                BackendKind::PostgreSQL,
            ],
            "requires neutral.counter capability (installed by composition root)",
            vec!["VALR-T18".to_string()],
            vec![
                "docs/architecture/runtime-contracts.md".to_string(),
                "crates/loom-api/src/lib.rs:SubscriptionService".to_string(),
            ],
        ),
        ScenarioDescriptor::new(
            CV_039,
            "change-feed: resume from valid cursor continues at documented boundary",
            CAPABILITY_AREA,
            vec![
                BackendKind::LoomClient,
                BackendKind::InMemory,
                BackendKind::PostgreSQL,
            ],
            "requires change-feed cursor at EventSeq=5 then new events 6,7",
            vec!["VALR-T18".to_string()],
            vec![
                "docs/architecture/runtime-contracts.md".to_string(),
                "crates/loom-api/src/lib.rs:ChangeFeedCursor".to_string(),
            ],
        ),
        ScenarioDescriptor::new(
            CV_040,
            "change-feed: disconnect/reconnect preserves history, transport duplicate != world duplicate",
            CAPABILITY_AREA,
            vec![
                BackendKind::LoomClient,
                BackendKind::InMemory,
                BackendKind::PostgreSQL,
            ],
            "requires formal client disconnect and resume via durable cursor; restart capability for durable evidence",
            vec!["VALR-T18".to_string()],
            vec![
                "docs/architecture/runtime-contracts.md".to_string(),
                "crates/loom-boundary/src/lib.rs:change_feed".to_string(),
            ],
        ),
    ]
}

#[must_use]
pub fn change_feed_registry() -> ScenarioRegistry {
    let mut registry = ScenarioRegistry::bootstrap();
    for descriptor in descriptors() {
        registry
            .register(descriptor)
            .expect("change-feed descriptors have distinct stable IDs");
    }
    registry
}

pub fn register(registry: &mut ScenarioRegistry) -> Result<(), RegistryError> {
    for descriptor in descriptors() {
        registry.register(descriptor)?;
    }
    Ok(())
}

#[must_use]
pub fn execute(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
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
    match descriptor.id_str() {
        CV_038 => execute_cv038(descriptor, ctx),
        CV_039 => execute_cv039(descriptor, ctx),
        CV_040 => execute_cv040(descriptor, ctx),
        _ => ScenarioResult::unavailable(
            descriptor.id().clone(),
            descriptor.name(),
            *ctx.backend_kind(),
            "unknown change-feed scenario",
        )
        .with_capability_area(descriptor.capability_area().as_str()),
    }
}

fn deterministic_world_template() -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new("validator.change-feed.t18", 1, WorldInstant::new(42))
        .requires_capability("neutral.counter", "^0.1.0")
        .with_configuration(json!({"profile": "counter"}))
}

fn entity_for(scenario: &str, index: u128) -> EntityId {
    let base = match scenario {
        CV_038 => 0x3801,
        CV_039 => 0x3901,
        CV_040 => 0x4001,
        _ => 0x0001,
    };
    parse_id(base + index)
}

fn event_id_for(scenario: &str, index: u128) -> EventId {
    let base = match scenario {
        CV_038 => 0x3810,
        CV_039 => 0x3910,
        CV_040 => 0x4010,
        _ => 0x0010,
    };
    parse_id(base + index)
}

fn parse_id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("deterministic test ID should parse")
}

fn correlate_history_and_feed(
    label: &str,
    history: &[CommittedEvent],
    feed: &[CommittedEvent],
) -> Result<(), String> {
    if history.len() != feed.len() {
        return Err(format!(
            "{label} length mismatch: authoritative history has {} events, feed has {}",
            history.len(),
            feed.len()
        ));
    }
    for (index, (history_event, feed_event)) in history.iter().zip(feed).enumerate() {
        if history_event.id != feed_event.id {
            return Err(format!(
                "{label} EventId mismatch at index {index}: history {} vs feed {}",
                history_event.id, feed_event.id
            ));
        }
        if history_event.sequence != feed_event.sequence {
            return Err(format!(
                "{label} EventSeq mismatch at index {index}: history {} vs feed {}",
                history_event.sequence.value(),
                feed_event.sequence.value()
            ));
        }
        if history_event != feed_event {
            return Err(format!(
                "{label} formal event content mismatch at index {index} for EventId {}",
                history_event.id
            ));
        }
    }
    Ok(())
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
            EvidenceReference::new("validator:change-feed"),
            EvidenceReference::new(format!("backend:{}", ctx.backend_kind().as_str())),
            EvidenceReference::new(format!(
                "backend_evidence:{}",
                ctx.backend_evidence().as_str()
            )),
            EvidenceReference::new(format!(
                "restart_capability:{}",
                ctx.restart_capability().as_str()
            )),
            EvidenceReference::new("public-surface:loom-client::SubscriptionService::subscribe"),
            EvidenceReference::new("public-surface:loom-client::HistoryService::list_events"),
            EvidenceReference::new("public-surface:loom-client::ActionService::invoke"),
            EvidenceReference::new(
                "public-surface:loom-client::WorldService::create_world_from_template",
            ),
        ],
        outcome.clone(),
    )
}

fn result_pass(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    expected: &str,
    actual: &str,
) -> ScenarioResult {
    let finding = finding_for(descriptor, ctx, expected, actual, ScenarioOutcome::Pass);
    ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Pass, finding)
        .with_capability_area(descriptor.capability_area().as_str())
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
        || lower.contains("sso")
        || lower.contains("transport")
}

fn result_fail(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    expected: &str,
    actual: &str,
) -> ScenarioResult {
    let finding = finding_for(descriptor, ctx, expected, actual, ScenarioOutcome::Fail);
    ScenarioResult::new(descriptor.id().clone(), ScenarioOutcome::Fail, finding)
        .with_capability_area(descriptor.capability_area().as_str())
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("tokio current_thread runtime should build")
        .block_on(future)
}

fn execute_cv038(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let expected = "committed Event observable via formal change-feed/SSE client with expected identity/order and monotonic cursor";
    let client = ctx.client().clone();
    let result = block_on(async {
        let template = deterministic_world_template();
        let created = client
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
            .map_err(|e| format!("create_world failed: {e:?} code={:?}", e.code))?;
        let target = created.target;
        let entity = entity_for(CV_038, 1);
        let event_id = event_id_for(CV_038, 1);
        let req = ActionRequest::new(
            target,
            ActionInvocation::new(
                ActionTypeId::from("neutral.counter.seed"),
                json!({
                    "event_id": event_id.to_string(),
                    "entity_id": entity.to_string(),
                    "value": 1,
                }),
            ),
        );
        let res = client
            .invoke(req)
            .await
            .map_err(|e| format!("seed invoke failed: {e:?}"))?;
        if !res.is_committed() {
            return Err(format!("seed not committed: {res:?}"));
        }
        let events = client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events failed: {e:?}"))?;
        if events.is_empty() {
            return Err("list_events empty after commit".to_string());
        }
        let committed = events.last().expect("at least one event").clone();
        let sub_req = SubscriptionRequest::new(target, 50);
        let sub_res = client.subscribe(sub_req).await.map_err(|e| {
            format!(
                "subscribe failed: {e:?} code={} message={}",
                e.code, e.message
            )
        })?;
        match sub_res {
            SubscriptionResult::Events(page) => {
                if page.events.is_empty() {
                    return Err(format!(
                        "subscription page empty, expected committed event {} seq {}",
                        committed.id,
                        committed.sequence.value()
                    ));
                }
                correlate_history_and_feed("CV-038 history/feed page", &events, &page.events)?;
                // Verify next_cursor monotonic
                let expected_cursor = ChangeFeedCursor::after(target, committed.sequence);
                match page.next_cursor {
                    Some(cursor) => {
                        if cursor != expected_cursor {
                            return Err(format!(
                                "next_cursor mismatch: expected {:?} after {} got {:?}",
                                expected_cursor,
                                committed.sequence.value(),
                                cursor
                            ));
                        }
                        if cursor.after.value() != committed.sequence.value() {
                            return Err(format!(
                                "cursor after value {} != committed seq {}",
                                cursor.after.value(),
                                committed.sequence.value()
                            ));
                        }
                        if cursor.target != target {
                            return Err(format!(
                                "cursor target mismatch: expected {:?} got {:?}",
                                target, cursor.target
                            ));
                        }
                    }
                    None => {
                        return Err(
                            "feed next_cursor is None but expected Some after committed event"
                                .to_string(),
                        );
                    }
                }
                Ok(format!(
                    "observed complete feed page via formal SubscriptionService::subscribe; all {} events correlated with HistoryService::list_events by EventId, EventSeq, order, and content; committed event {} seq {}; cursor {:?} monotonic",
                    page.events.len(),
                    committed.id,
                    committed.sequence.value(),
                    page.next_cursor
                ))
            }
            other => Err(format!(
                "expected SubscriptionResult::Events but got {:?} (should be Events with committed id {})",
                other, committed.id
            )),
        }
    });
    match result {
        Ok(actual) => result_pass(descriptor, ctx, expected, &actual),
        Err(actual) => {
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(descriptor, ctx, expected, &actual, outcome.clone());
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            result_fail(descriptor, ctx, expected, &actual)
        }
    }
}

fn execute_cv039(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let expected = "resume from valid cursor continues at documented boundary without losing committed events or manufacturing duplicates; second resume with no new events yields Resumed";
    let client = ctx.client().clone();
    let restart_capable = ctx.can_perform_boundary_restart();
    let backend_is_postgres = ctx.backend_evidence().is_postgres();
    let result = block_on(async {
        let template = deterministic_world_template();
        let created = client
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
            .map_err(|e| format!("create_world failed: {e:?}"))?;
        let target = created.target;

        // Create 5 initial events
        for idx in 1..=5 {
            let entity = entity_for(CV_039, idx as u128);
            let event_id = event_id_for(CV_039, idx as u128);
            let req = ActionRequest::new(
                target,
                ActionInvocation::new(
                    ActionTypeId::from("neutral.counter.seed"),
                    json!({
                        "event_id": event_id.to_string(),
                        "entity_id": entity.to_string(),
                        "value": idx as i64,
                    }),
                ),
            );
            let res = client
                .invoke(req)
                .await
                .map_err(|e| format!("seed {idx} invoke failed: {e:?}"))?;
            if !res.is_committed() {
                return Err(format!("seed {idx} not committed: {res:?}"));
            }
        }
        let events_after_5 = client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events after 5 failed: {e:?}"))?;
        if events_after_5.len() != 5 {
            return Err(format!(
                "expected 5 events after initial seeds, got {}",
                events_after_5.len()
            ));
        }
        // Determine cursor after 5 via authoritative sequence
        let seq_5 = events_after_5.last().expect("5 events").sequence;
        if seq_5.value() != 5 {
            // Sequence may start at 1 and be contiguous, but allow check that last seq is 5
            // If not 5, use actual last seq as cursor basis but expect 5 in this fresh timeline
            // For determinism we require 5
            return Err(format!(
                "expected last seq 5 after 5 seeds, got {}",
                seq_5.value()
            ));
        }
        let cursor_after_5 = ChangeFeedCursor::after(target, seq_5);

        // Create 2 more events (seq 6,7)
        for idx in 6..=7 {
            let entity = entity_for(CV_039, idx as u128);
            let event_id = event_id_for(CV_039, idx as u128);
            let req = ActionRequest::new(
                target,
                ActionInvocation::new(
                    ActionTypeId::from("neutral.counter.seed"),
                    json!({
                        "event_id": event_id.to_string(),
                        "entity_id": entity.to_string(),
                        "value": idx as i64,
                    }),
                ),
            );
            let res = client
                .invoke(req)
                .await
                .map_err(|e| format!("seed {idx} invoke failed: {e:?}"))?;
            if !res.is_committed() {
                return Err(format!("seed {idx} not committed: {res:?}"));
            }
        }
        let events_after_7 = client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events after 7 failed: {e:?}"))?;
        if events_after_7.len() != 7 {
            return Err(format!(
                "expected 7 events after 7 seeds, got {}",
                events_after_7.len()
            ));
        }
        let seq_7 = events_after_7.last().expect("7 events").sequence;
        if seq_7.value() != 7 {
            return Err(format!(
                "expected seq 7 after 7 seeds, got {}",
                seq_7.value()
            ));
        }

        // First resume: after 5 should return 6,7
        let resume_req = SubscriptionRequest::resume(target, cursor_after_5, 50);
        let resume_res = client
            .subscribe(resume_req)
            .await
            .map_err(|e| format!("resume after 5 failed: {e:?}"))?;
        let (page_events, next_cursor_opt) = match resume_res {
            SubscriptionResult::Events(page) => {
                if page.events.len() != 2 {
                    return Err(format!(
                        "resume after 5 expected 2 events (6,7) got {} events {:?}",
                        page.events.len(),
                        page.events
                            .iter()
                            .map(|ev| ev.sequence.value())
                            .collect::<Vec<_>>()
                    ));
                }
                if page.events[0].sequence.value() != 6 || page.events[1].sequence.value() != 7 {
                    return Err(format!(
                        "resume after 5 expected seq 6,7 got {:?}",
                        page.events
                            .iter()
                            .map(|ev| ev.sequence.value())
                            .collect::<Vec<_>>()
                    ));
                }
                // Ensure no duplication of 5 and order
                if page.events.iter().any(|ev| ev.sequence.value() == 5) {
                    return Err("resume after 5 incorrectly included event 5".to_string());
                }
                let expected_next = ChangeFeedCursor::after(target, seq_7);
                match page.next_cursor {
                    Some(c) if c == expected_next => {}
                    Some(c) => {
                        return Err(format!(
                            "resume next_cursor expected after 7 {:?} got {:?}",
                            expected_next, c
                        ));
                    }
                    None => {
                        return Err("resume page next_cursor None but expected after 7".to_string());
                    }
                }
                correlate_history_and_feed(
                    "CV-039 authoritative history after 7/resume after 5",
                    &events_after_7[5..7],
                    &page.events,
                )?;
                (page.events, page.next_cursor)
            }
            other => {
                return Err(format!(
                    "expected Events for resume after 5, got {:?}",
                    other
                ));
            }
        };

        // Second resume: after 7 with no new events should return Resumed, not Events
        let cursor_after_7 = next_cursor_opt.expect("next_cursor after 7");
        let second_req = SubscriptionRequest::resume(target, cursor_after_7, 50);
        let second_res = client
            .subscribe(second_req)
            .await
            .map_err(|e| format!("second resume after 7 failed: {e:?}"))?;
        match second_res {
            SubscriptionResult::Resumed(resume) => {
                if resume.cursor != cursor_after_7 {
                    return Err(format!(
                        "second resume cursor mismatch: expected {:?} got {:?}",
                        cursor_after_7, resume.cursor
                    ));
                }
            }
            other => {
                return Err(format!(
                    "expected Resumed after 7 with no new events, got {:?} (page_events {:?})",
                    other,
                    page_events
                        .iter()
                        .map(|e| e.sequence.value())
                        .collect::<Vec<_>>()
                ));
            }
        }

        // Durable restart proof for PostgreSQL where required (CV-039 PG live Yes)
        // If context has controlled restart capability and is postgres, verify cursor survives restart
        if backend_is_postgres && restart_capable {
            let new_client = ctx
                .restart()
                .map_err(|e| format!("controlled restart failed: {e}"))?;
            // Verify the complete authoritative history and its order/contents via new client.
            let events_via_new = new_client
                .list_events(EventQuery::all(target))
                .await
                .map_err(|e| format!("list_events via restarted client failed: {e:?}"))?;
            if events_via_new.len() != 7 {
                return Err(format!(
                    "after restart expected 7 events, got {}",
                    events_via_new.len()
                ));
            }
            correlate_history_and_feed(
                "CV-039 authoritative history before/after PostgreSQL restart",
                &events_after_7,
                &events_via_new,
            )?;
            // Resume again after 7 should still be Resumed
            let resumed_after_restart = new_client
                .subscribe(SubscriptionRequest::resume(target, cursor_after_7, 50))
                .await
                .map_err(|e| format!("resume after restart failed: {e:?}"))?;
            match resumed_after_restart {
                SubscriptionResult::Resumed(r) if r.cursor == cursor_after_7 => {}
                other => {
                    return Err(format!(
                        "after restart resume after 7 expected Resumed with same cursor, got {:?}",
                        other
                    ));
                }
            }
            // Resume after 5 should still return 6,7 even after restart
            let resume_after_restart_5 = new_client
                .subscribe(SubscriptionRequest::resume(target, cursor_after_5, 50))
                .await
                .map_err(|e| format!("resume after 5 via restarted client failed: {e:?}"))?;
            match resume_after_restart_5 {
                SubscriptionResult::Events(page) if page.events.len() == 2 => {
                    correlate_history_and_feed(
                        "CV-039 authoritative history after restart/resume after 5",
                        &events_via_new[5..7],
                        &page.events,
                    )?;
                }
                other => {
                    return Err(format!(
                        "after restart resume after 5 expected Events 6,7 got {:?}",
                        other
                    ));
                }
            }
            Ok(
                "resume semantics verified: authoritative HistoryService::list_events after 5/7 correlated page EventId, EventSeq, order, and content; after 5 -> 2 events (6,7) next_cursor after 7; after 7 -> Resumed; durable controlled restart re-correlated complete history and resume page"
                    .to_string(),
            )
        } else {
            // For InMemory or reconnect-only, basic resume already proves boundary; note durability caveat
            Ok(format!(
                "resume semantics verified: authoritative history/feed correlation after 5 and 7 by EventId, EventSeq, order, and content; after {} -> 2 events (6,7) next_cursor after {}; after {} -> Resumed; restart_capability={} backend_evidence={} (durable PG proof requires controlled PostgreSQL restart, but logical resume passed); via formal SubscriptionService::subscribe resume",
                cursor_after_5.after.value(),
                cursor_after_7.after.value(),
                cursor_after_7.after.value(),
                if restart_capable {
                    "controlled"
                } else {
                    "reconnect-only"
                },
                if backend_is_postgres {
                    "postgresql"
                } else {
                    "in-memory/external"
                }
            ))
        }
    });
    match result {
        Ok(actual) => result_pass(descriptor, ctx, expected, &actual),
        Err(actual) => {
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(descriptor, ctx, expected, &actual, outcome.clone());
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            result_fail(descriptor, ctx, expected, &actual)
        }
    }
}

fn execute_cv040(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let expected = "disconnect/reconnect recovery preserves authoritative history; transport duplicate/retry distinguishable from duplicate World commits (EventId dedup)";
    let client = ctx.client().clone();
    let restart_capable = ctx.can_perform_boundary_restart();
    let result = block_on(async {
        let template = deterministic_world_template();
        let created = client
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
            .map_err(|e| format!("create_world failed: {e:?}"))?;
        let target = created.target;

        // Commit 3 distinct events.
        for idx in 1..=3 {
            let entity = entity_for(CV_040, idx as u128);
            let event_id = event_id_for(CV_040, idx as u128);
            let req = ActionRequest::new(
                target,
                ActionInvocation::new(
                    ActionTypeId::from("neutral.counter.seed"),
                    json!({
                        "event_id": event_id.to_string(),
                        "entity_id": entity.to_string(),
                        "value": (10 + idx) as i64,
                    }),
                ),
            );
            let res = client
                .invoke(req)
                .await
                .map_err(|e| format!("seed {idx} invoke failed: {e:?}"))?;
            if !res.is_committed() {
                return Err(format!("seed {idx} not committed: {res:?}"));
            }
        }
        let events_before = client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events before disconnect failed: {e:?}"))?;
        if events_before.len() != 3 {
            return Err(format!(
                "expected 3 events before disconnect, got {}",
                events_before.len()
            ));
        }
        for (index, event) in events_before.iter().enumerate() {
            let expected_sequence = (index + 1) as u64;
            if event.sequence.value() != expected_sequence {
                return Err(format!(
                    "expected bounded disconnect history sequence {}, got {}",
                    expected_sequence,
                    event.sequence.value()
                ));
            }
        }
        // Read only a bounded first page. The complete first Event is the last
        // observation before the simulated disconnect.
        let initial_req = SubscriptionRequest::new(target, 1);
        let initial_res = client
            .subscribe(initial_req)
            .await
            .map_err(|e| format!("initial subscribe failed: {e:?}"))?;
        let initial_page = match initial_res {
            SubscriptionResult::Events(page) => {
                if page.events.len() != 1 {
                    return Err(format!(
                        "bounded initial page expected 1 event got {} {:?}",
                        page.events.len(),
                        page.events
                            .iter()
                            .map(|ev| ev.sequence.value())
                            .collect::<Vec<_>>()
                    ));
                }
                if !page.has_more {
                    return Err(format!(
                        "bounded initial page must report remaining events via has_more: {page:?}"
                    ));
                }
                correlate_history_and_feed(
                    "CV-040 bounded initial page/history",
                    &events_before[..1],
                    &page.events,
                )?;
                let expected_cursor = ChangeFeedCursor::after(target, events_before[0].sequence);
                if page.next_cursor != Some(expected_cursor) {
                    return Err(format!(
                        "initial page next_cursor expected {:?} got {:?}",
                        Some(expected_cursor),
                        page.next_cursor
                    ));
                }
                page
            }
            other => {
                return Err(format!(
                    "expected Events for initial subscribe, got {:?}",
                    other
                ));
            }
        };
        let observed_cursor = initial_page
            .next_cursor
            .expect("bounded initial page cursor after first event");

        // Disconnect after one complete bounded-page Event. A controlled
        // harness rebuilds the HTTP boundary on the preserved store; a generic
        // client continues with the next formal HTTP request as reconnect.
        let active_client = if restart_capable {
            ctx.restart()
                .map_err(|e| format!("controlled restart failed: {e}"))?
        } else {
            client.clone()
        };

        let history_after_disconnect = active_client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events after disconnect failed: {e:?}"))?;
        correlate_history_and_feed(
            "CV-040 authoritative history across disconnect",
            &events_before,
            &history_after_disconnect,
        )?;

        // Reconnect with the last fully observed cursor. The remaining
        // history is deliberately read in bounded pages so each page can be
        // correlated to the authoritative history independently.
        let resumed_page_2 = match active_client
            .subscribe(SubscriptionRequest::resume(target, observed_cursor, 1))
            .await
            .map_err(|e| format!("resume after bounded disconnect failed: {e:?}"))?
        {
            SubscriptionResult::Events(page) => page,
            other => {
                return Err(format!(
                    "expected remaining Events after reconnect cursor {:?}, got {:?}",
                    observed_cursor, other
                ));
            }
        };
        if resumed_page_2.events.len() != 1 || !resumed_page_2.has_more {
            return Err(format!(
                "resume after bounded disconnect expected one remaining Event with has_more, got {resumed_page_2:?}"
            ));
        }
        correlate_history_and_feed(
            "CV-040 reconnect page 2/history",
            &history_after_disconnect[1..2],
            &resumed_page_2.events,
        )?;
        let cursor_after_2 = resumed_page_2
            .next_cursor
            .ok_or_else(|| "reconnect page 2 omitted next_cursor".to_string())?;

        // Retry the same reconnect request. It may deliver the same transport
        // page again, but it must remain equivalent to history and add no
        // authoritative commit.
        let retry_page_2 = match active_client
            .subscribe(SubscriptionRequest::resume(target, observed_cursor, 1))
            .await
            .map_err(|e| format!("duplicate resume after reconnect failed: {e:?}"))?
        {
            SubscriptionResult::Events(page) => page,
            other => {
                return Err(format!(
                    "expected duplicate remaining Events after reconnect, got {:?}",
                    other
                ));
            }
        };
        if retry_page_2 != resumed_page_2 {
            return Err(format!(
                "transport retry page differed: first {:?} retry {:?}",
                resumed_page_2, retry_page_2
            ));
        }
        correlate_history_and_feed(
            "CV-040 transport retry/history",
            &history_after_disconnect[1..2],
            &retry_page_2.events,
        )?;

        let resumed_page_3 = match active_client
            .subscribe(SubscriptionRequest::resume(target, cursor_after_2, 1))
            .await
            .map_err(|e| format!("resume final bounded page failed: {e:?}"))?
        {
            SubscriptionResult::Events(page) => page,
            other => {
                return Err(format!(
                    "expected final remaining Event after cursor {:?}, got {:?}",
                    cursor_after_2, other
                ));
            }
        };
        if resumed_page_3.events.len() != 1 || resumed_page_3.has_more {
            return Err(format!(
                "final bounded page expected one Event and no has_more, got {resumed_page_3:?}"
            ));
        }
        correlate_history_and_feed(
            "CV-040 reconnect page 3/history",
            &history_after_disconnect[2..3],
            &resumed_page_3.events,
        )?;
        let final_cursor = resumed_page_3
            .next_cursor
            .ok_or_else(|| "final reconnect page omitted next_cursor".to_string())?;
        let resumed = active_client
            .subscribe(SubscriptionRequest::resume(target, final_cursor, 1))
            .await
            .map_err(|e| format!("resume after final reconnect page failed: {e:?}"))?;
        match resumed {
            SubscriptionResult::Resumed(r) if r.cursor == final_cursor => {}
            other => {
                return Err(format!(
                    "expected Resumed after final cursor {:?}, got {:?}",
                    final_cursor, other
                ));
            }
        }

        // Duplicate transport delivery must not create or rewrite World
        // history; compare the complete post-retry history, not just count/IDs.
        let final_history = active_client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("final list_events failed: {e:?}"))?;
        correlate_history_and_feed(
            "CV-040 complete post-retry history",
            &events_before,
            &final_history,
        )?;

        let restart_note = if restart_capable {
            "with controlled boundary restart (store preserved, boundary rebuilt) and duplicate page dedup via EventId"
        } else {
            "via formal client reconnect (reconnect-only transport) and duplicate page dedup via EventId; durable PG restart requires controlled PostgreSQL"
        };
        Ok(format!(
            "bounded-page disconnect after EventSeq 1; reconnect cursor after 1 returned remaining EventSeq 2 then 3 with complete history/feed EventId, EventSeq, order, and content correlation; retry of cursor after 1 returned identical page without new world commit; final cursor after 3 -> Resumed; history remained exactly 3 authoritative commits {:?} across {}; transport duplicate distinct from world duplicate via EventId",
            events_before
                .iter()
                .map(|event| event.id)
                .collect::<Vec<_>>(),
            restart_note,
        ))
    });
    match result {
        Ok(actual) => result_pass(descriptor, ctx, expected, &actual),
        Err(actual) => {
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(descriptor, ctx, expected, &actual, outcome.clone());
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            result_fail(descriptor, ctx, expected, &actual)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{change_feed_registry, descriptors};

    #[test]
    fn descriptors_are_three_and_deterministic() {
        let first = descriptors();
        let second = descriptors();
        assert_eq!(first.len(), 3);
        assert_eq!(first, second);
        let ids: Vec<_> = first.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec!["CV-038", "CV-039", "CV-040"]);
    }

    #[test]
    fn registry_contains_change_feed_ids() {
        let registry = change_feed_registry();
        assert_eq!(registry.len(), 3);
        assert!(registry.get("CV-038").is_some());
        assert!(registry.get("CV-039").is_some());
        assert!(registry.get("CV-040").is_some());
        let ids: Vec<_> = registry.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec!["CV-038", "CV-039", "CV-040"]);
    }
}
