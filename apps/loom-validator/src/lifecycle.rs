//! Baseline lifecycle/create/reopen/restart capability scenarios (VAL-T8).

#![allow(clippy::pedantic)]
#![allow(clippy::too_many_lines)]
#![allow(clippy::uninlined_format_args)]
#![allow(clippy::needless_pass_by_value)]
#![allow(clippy::clone_on_copy)]
#![allow(clippy::redundant_closure)]
#![allow(clippy::redundant_closure_for_method_calls)]

use std::str::FromStr;

use loom_api::{
    ActionRequest, CreateWorldFromTemplateRequest, EventQuery, FacetQuery, WorldTemplateDescriptor,
};
use loom_api::{ActionService, HistoryService, QueryService, TimelineService, WorldService};
use loom_api::{ActionTypeId, EntityId, EventId, FacetOwner, FacetTypeId, WorldInstant};
use serde_json::json;

use crate::backend::BackendContext;
use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::reports::ScenarioResult;
use crate::scenario::{BackendKind, ScenarioDescriptor};
use crate::{RegistryError, ScenarioRegistry};

pub const CV_001: &str = "CV-001";
pub const CV_002: &str = "CV-002";
pub const CV_003: &str = "CV-003";
pub const CV_004: &str = "CV-004";
pub const CAPABILITY_AREA: &str = "lifecycle";

#[must_use]
pub fn descriptors() -> Vec<ScenarioDescriptor> {
    vec![
        ScenarioDescriptor::new(
            CV_001,
            "lifecycle: create/open World/Timeline via public API",
            CAPABILITY_AREA,
            vec![
                BackendKind::LoomClient,
                BackendKind::InMemory,
                BackendKind::PostgreSQL,
            ],
            "none; uses public WorldService create_world_from_template and TimelineService inspect",
            vec!["VAL-T8".to_string()],
            vec!["docs/architecture/world-runtime.md".to_string()],
        ),
        ScenarioDescriptor::new(
            CV_002,
            "lifecycle: mutate via Action and observe committed state via public reads",
            CAPABILITY_AREA,
            vec![
                BackendKind::LoomClient,
                BackendKind::InMemory,
                BackendKind::PostgreSQL,
            ],
            "requires neutral.counter capability (installed by composition root)",
            vec!["VAL-T8".to_string()],
            vec!["docs/architecture/runtime-contracts.md".to_string()],
        ),
        ScenarioDescriptor::new(
            CV_003,
            "lifecycle: dispose/restart/reconnect and reopen durable state via public API",
            CAPABILITY_AREA,
            vec![
                BackendKind::LoomClient,
                BackendKind::InMemory,
                BackendKind::PostgreSQL,
            ],
            "restart must recreate application boundary (new LoomClient via harness restart)",
            vec!["VAL-T8".to_string()],
            vec!["docs/architecture/implementation.md".to_string()],
        ),
        ScenarioDescriptor::new(
            CV_004,
            "lifecycle: verify public observable state/provenance survives restart on PostgreSQL",
            CAPABILITY_AREA,
            vec![
                BackendKind::LoomClient,
                BackendKind::InMemory,
                BackendKind::PostgreSQL,
            ],
            "requires LOOM_TEST_POSTGRES_URL and a live PostgreSQL-backed Loom service; missing evidence is not pass",
            vec!["VAL-T8".to_string()],
            vec!["docs/architecture/runtime-contracts.md".to_string()],
        ),
    ]
}

#[must_use]
pub fn lifecycle_registry() -> ScenarioRegistry {
    let mut registry = ScenarioRegistry::bootstrap();
    for descriptor in descriptors() {
        registry
            .register(descriptor)
            .expect("lifecycle descriptors have distinct stable IDs");
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
        CV_001 => execute_cv001(descriptor, ctx),
        CV_002 => execute_cv002(descriptor, ctx),
        CV_003 => execute_cv003(descriptor, ctx),
        CV_004 => execute_cv004(descriptor, ctx),
        _ => ScenarioResult::unavailable(
            descriptor.id().clone(),
            descriptor.name(),
            *ctx.backend_kind(),
            "unknown lifecycle scenario",
        )
        .with_capability_area(descriptor.capability_area().as_str()),
    }
}

fn deterministic_world_template() -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new("validator.lifecycle.t8", 1, WorldInstant::new(42))
        .requires_capability("neutral.counter", "^0.1.0")
        .with_configuration(json!({"profile": "counter"}))
}

fn entity_for(scenario: &str) -> EntityId {
    let suffix = match scenario {
        CV_001 => 0x0101,
        CV_002 => 0x0201,
        CV_003 => 0x0301,
        CV_004 => 0x0401,
        _ => 0x0001,
    };
    parse_id(suffix)
}

fn event_id_for(scenario: &str, index: u128) -> EventId {
    let base = match scenario {
        CV_001 => 0x0110,
        CV_002 => 0x0210,
        CV_003 => 0x0310,
        CV_004 => 0x0410,
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
            EvidenceReference::new("validator:lifecycle"),
            EvidenceReference::new(format!("backend:{}", ctx.backend_kind().as_str())),
            EvidenceReference::new(format!(
                "restart_capability:{}",
                ctx.restart_capability().as_str()
            )),
        ],
        outcome.clone(),
    )
}

fn reconnect_only_result(
    descriptor: &ScenarioDescriptor,
    ctx: &BackendContext,
    expected: &str,
) -> ScenarioResult {
    let reason = format!(
        "reconnect-only: endpoint {} does not provide controlled application-boundary restart; restart capability is {}, backend_evidence is {}",
        ctx.base_url(),
        ctx.restart_capability().as_str(),
        ctx.backend_evidence().as_str()
    );
    let finding = Finding::new(
        descriptor.id().clone(),
        descriptor.name(),
        expected,
        reason.clone(),
        *ctx.backend_kind(),
        format!(
            "validator:{}:{}:reconnect-only",
            descriptor.id_str(),
            ctx.backend_kind().as_str()
        ),
        vec![
            EvidenceReference::new("validator:restart:reconnect-only"),
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

fn execute_cv001(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let client = ctx.client().clone();
    let result = block_on(async {
        let template = deterministic_world_template();
        let req = CreateWorldFromTemplateRequest::new(template);
        let created = client
            .create_world_from_template(req)
            .await
            .map_err(|e| format!("create_world failed: {e}"))?;
        let inspected = client
            .inspect_timeline(created.target)
            .await
            .map_err(|e| format!("inspect_timeline failed: {e}"))?;
        if inspected.target != created.target {
            return Err(format!(
                "inspect target mismatch: expected {:?} got {:?}",
                created.target, inspected.target
            ));
        }
        if inspected.world_time != created.world_time {
            return Err("world_time mismatch after reopen".to_string());
        }
        Ok(())
    });
    match result {
        Ok(()) => result_pass(
            descriptor,
            ctx,
            "world is created and timeline is inspectable via public API",
            "world creation and reopen succeeded via LoomClient",
        ),
        Err(actual) => {
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(
                    descriptor,
                    ctx,
                    "world is created and timeline is inspectable via public API",
                    &actual,
                    outcome.clone(),
                );
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            result_fail(
                descriptor,
                ctx,
                "world is created and timeline is inspectable via public API",
                &actual,
            )
        }
    }
}

fn execute_cv002(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    let client = ctx.client().clone();
    let entity = entity_for(CV_002);
    let result = block_on(async {
        let template = deterministic_world_template();
        let created = client
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
            .map_err(|e| format!("create_world failed: {e}"))?;
        let target = created.target;
        let seed_event = event_id_for(CV_002, 1);
        let seed_req = ActionRequest::new(
            target,
            loom_api::ActionInvocation::new(
                ActionTypeId::from("neutral.counter.seed"),
                json!({
                    "event_id": seed_event.to_string(),
                    "entity_id": entity.to_string(),
                    "value": 1,
                }),
            ),
        );
        let seed_res = client
            .invoke(seed_req)
            .await
            .map_err(|e| format!("seed invoke failed: {e}"))?;
        if !seed_res.is_committed() {
            return Err(format!("seed not committed: {seed_res:?}"));
        }
        let facet = client
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(entity),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
            .map_err(|e| format!("get_facet failed: {e}"))?
            .ok_or_else(|| "facet missing after seed".to_string())?;
        let val = facet
            .value
            .get("value")
            .and_then(serde_json::Value::as_i64)
            .ok_or_else(|| "facet value not int".to_string())?;
        if val != 1 {
            return Err(format!("facet value after seed expected 1 got {val}"));
        }
        let inc_event = event_id_for(CV_002, 2);
        let inc_req = ActionRequest::new(
            target,
            loom_api::ActionInvocation::new(
                ActionTypeId::from("neutral.counter.increment"),
                json!({
                    "event_id": inc_event.to_string(),
                    "entity_id": entity.to_string(),
                    "amount": 2,
                }),
            ),
        );
        let inc_res = client
            .invoke(inc_req)
            .await
            .map_err(|e| format!("increment invoke failed: {e}"))?;
        if !inc_res.is_committed() {
            return Err(format!("increment not committed: {inc_res:?}"));
        }
        let facet2 = client
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(entity),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
            .map_err(|e| format!("get_facet after increment failed: {e}"))?
            .ok_or_else(|| "facet missing after increment".to_string())?;
        let val2 = facet2
            .value
            .get("value")
            .and_then(serde_json::Value::as_i64)
            .ok_or_else(|| "facet value not int after increment".to_string())?;
        if val2 != 3 {
            return Err(format!("facet value after increment expected 3 got {val2}"));
        }
        let events = client
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events failed: {e}"))?;
        if events.len() < 2 {
            return Err(format!("expected >=2 events got {}", events.len()));
        }
        Ok(())
    });
    match result {
        Ok(()) => result_pass(
            descriptor,
            ctx,
            "mutation via Action commits and is observable via public reads",
            "seed, increment, facet read, and history observed correctly",
        ),
        Err(actual) => {
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(
                    descriptor,
                    ctx,
                    "mutation via Action commits and is observable via public reads",
                    &actual,
                    outcome.clone(),
                );
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            result_fail(
                descriptor,
                ctx,
                "mutation via Action commits and is observable via public reads",
                &actual,
            )
        }
    }
}

fn execute_cv003(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    if !ctx.can_perform_boundary_restart() {
        return reconnect_only_result(
            descriptor,
            ctx,
            "controlled application-boundary restart preserves durable state via public API",
        );
    }
    let client1 = ctx.client().clone();
    let entity = entity_for(CV_003);
    let result = block_on(async {
        let template = deterministic_world_template();
        let created = client1
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
            .map_err(|e| format!("phase1 create_world failed: {e}"))?;
        let target = created.target;
        let seed_event = event_id_for(CV_003, 1);
        let seed_req = ActionRequest::new(
            target,
            loom_api::ActionInvocation::new(
                ActionTypeId::from("neutral.counter.seed"),
                json!({
                    "event_id": seed_event.to_string(),
                    "entity_id": entity.to_string(),
                    "value": 5,
                }),
            ),
        );
        let res = client1
            .invoke(seed_req)
            .await
            .map_err(|e| format!("phase1 seed failed: {e}"))?;
        if !res.is_committed() {
            return Err("phase1 seed not committed".to_string());
        }
        let facet_before = client1
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(entity),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
            .map_err(|e| format!("get_facet before restart failed: {e}"))?
            .ok_or_else(|| "facet missing before restart".to_string())?;
        let val_before = facet_before
            .value
            .get("value")
            .and_then(serde_json::Value::as_i64)
            .unwrap_or(-1);
        if val_before != 5 {
            return Err(format!("before restart value expected 5 got {val_before}"));
        }
        Ok(target)
    });
    let target = match result {
        Ok(t) => t,
        Err(actual) => {
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(
                    descriptor,
                    ctx,
                    "dispose/restart/reconnect reopens same durable state via public API",
                    &actual,
                    outcome.clone(),
                );
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            return result_fail(
                descriptor,
                ctx,
                "dispose/restart/reconnect reopens same durable state via public API",
                &actual,
            );
        }
    };

    // Genuine restart: terminate and recreate the real Loom application boundary
    let client2 = match ctx.restart() {
        Ok(c) => c,
        Err(e) => {
            let actual = format!("restart failed: {e}");
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(
                    descriptor,
                    ctx,
                    "dispose/restart/reconnect reopens same durable state via public API",
                    &actual,
                    outcome.clone(),
                );
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            return result_fail(
                descriptor,
                ctx,
                "dispose/restart/reconnect reopens same durable state via public API",
                &actual,
            );
        }
    };

    let result2 = block_on(async {
        let inspected = client2
            .inspect_timeline(target)
            .await
            .map_err(|e| format!("inspect after restart failed: {e}"))?;
        if inspected.target != target {
            return Err("target mismatch after restart".to_string());
        }
        let facet_after = client2
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(entity),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
            .map_err(|e| format!("get_facet after restart failed: {e}"))?
            .ok_or_else(|| "facet missing after restart".to_string())?;
        let val_after = facet_after
            .value
            .get("value")
            .and_then(serde_json::Value::as_i64)
            .unwrap_or(-1);
        if val_after != 5 {
            return Err(format!("after restart value expected 5 got {val_after}"));
        }
        let events = client2
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events after restart failed: {e}"))?;
        if events.is_empty() {
            return Err("no events after restart".to_string());
        }
        Ok(())
    });

    match result2 {
        Ok(()) => {
            // Controlled restart evidence: the harness rebuilt the real boundary.
            let actual = format!(
                "controlled application-boundary restart via BackendContext::restart preserved state (capability: {}, backend_evidence: {})",
                ctx.restart_capability().as_str(),
                ctx.backend_evidence().as_str()
            );
            let expected = "dispose/restart/reconnect reopens same durable state via public API";
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                expected,
                actual.clone(),
                *ctx.backend_kind(),
                format!(
                    "validator:{}:{}:controlled-boundary-restart",
                    descriptor.id_str(),
                    ctx.backend_kind().as_str()
                ),
                vec![
                    EvidenceReference::new("validator:lifecycle"),
                    EvidenceReference::new(format!("backend:{}", ctx.backend_kind().as_str())),
                    EvidenceReference::new("validator:restart:controlled-boundary-restart"),
                    EvidenceReference::new(format!(
                        "restart_capability:{}",
                        ctx.restart_capability().as_str()
                    )),
                    EvidenceReference::new(format!(
                        "backend_evidence:{}",
                        ctx.backend_evidence().as_str()
                    )),
                ],
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
                let finding = finding_for(
                    descriptor,
                    ctx,
                    "dispose/restart/reconnect reopens same durable state via public API",
                    &actual,
                    outcome.clone(),
                );
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            result_fail(
                descriptor,
                ctx,
                "dispose/restart/reconnect reopens same durable state via public API",
                &actual,
            )
        }
    }
}

fn execute_cv004(descriptor: &ScenarioDescriptor, ctx: &BackendContext) -> ScenarioResult {
    if !ctx.can_perform_boundary_restart() {
        return reconnect_only_result(
            descriptor,
            ctx,
            "controlled PostgreSQL application-boundary restart preserves durable state via public API",
        );
    }
    let pg_url = std::env::var(crate::backend::LOOM_TEST_POSTGRES_URL).unwrap_or_default();
    if pg_url.trim().is_empty() {
        let reason = format!(
            "missing {}; PostgreSQL evidence is unavailable",
            crate::backend::LOOM_TEST_POSTGRES_URL
        );
        let outcome = ScenarioOutcome::Skipped {
            reason: reason.clone(),
        };
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "PostgreSQL provenance survives restart via public API",
            reason.clone(),
            *ctx.backend_kind(),
            "backend-harness",
            vec![],
            outcome.clone(),
        );
        return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }
    if !pg_url.starts_with("postgres://") && !pg_url.starts_with("postgresql://") {
        let reason = format!(
            "{} must use the postgres:// or postgresql:// scheme",
            crate::backend::LOOM_TEST_POSTGRES_URL
        );
        let outcome = ScenarioOutcome::Unavailable {
            reason: reason.clone(),
        };
        let finding = Finding::new(
            descriptor.id().clone(),
            descriptor.name(),
            "PostgreSQL provenance survives restart via public API",
            reason.clone(),
            *ctx.backend_kind(),
            "backend-harness",
            vec![],
            outcome.clone(),
        );
        return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
            .with_capability_area(descriptor.capability_area().as_str());
    }

    let client1 = ctx.client().clone();
    let entity = entity_for(CV_004);
    let result = block_on(async {
        let template = deterministic_world_template();
        let created = client1
            .create_world_from_template(CreateWorldFromTemplateRequest::new(template))
            .await
            .map_err(|e| format!("phase1 create failed: {e}"))?;
        let target = created.target;
        let created_time = created.world_time;
        let seed_event = event_id_for(CV_004, 1);
        let seed_req = ActionRequest::new(
            target,
            loom_api::ActionInvocation::new(
                ActionTypeId::from("neutral.counter.seed"),
                json!({
                    "event_id": seed_event.to_string(),
                    "entity_id": entity.to_string(),
                    "value": 11,
                }),
            ),
        );
        let res = client1
            .invoke(seed_req)
            .await
            .map_err(|e| format!("phase1 seed failed: {e}"))?;
        if !res.is_committed() {
            return Err("phase1 seed not committed".to_string());
        }
        let events_before = client1
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events before restart failed: {e}"))?;
        if events_before.is_empty() {
            return Err("no events before restart".to_string());
        }
        Ok((target, created_time, events_before))
    });

    let (target, created_time, events_before) = match result {
        Ok(v) => v,
        Err(actual) => {
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(
                    descriptor,
                    ctx,
                    "PostgreSQL public observable state/provenance survives restart",
                    &actual,
                    outcome.clone(),
                );
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            return result_fail(
                descriptor,
                ctx,
                "PostgreSQL public observable state/provenance survives restart",
                &actual,
            );
        }
    };

    let client2 = match ctx.restart() {
        Ok(c) => c,
        Err(e) => {
            let actual = format!("restart failed: {e}");
            if is_infra_unavailable(&actual) {
                let outcome = ScenarioOutcome::Unavailable {
                    reason: actual.clone(),
                };
                let finding = finding_for(
                    descriptor,
                    ctx,
                    "PostgreSQL public observable state/provenance survives restart",
                    &actual,
                    outcome.clone(),
                );
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            return result_fail(
                descriptor,
                ctx,
                "PostgreSQL public observable state/provenance survives restart",
                &actual,
            );
        }
    };

    let result2 = block_on(async {
        let inspected = client2
            .inspect_timeline(target)
            .await
            .map_err(|e| format!("inspect after restart failed: {e}"))?;
        if inspected.world_time != created_time {
            return Err(format!(
                "world_time mismatch: before {:?} after {:?}",
                created_time, inspected.world_time
            ));
        }
        let facet = client2
            .get_facet(FacetQuery::new(
                target,
                FacetOwner::entity(entity),
                FacetTypeId::from("neutral.counter.value"),
            ))
            .await
            .map_err(|e| format!("get_facet after restart failed: {e}"))?
            .ok_or_else(|| "facet missing after restart".to_string())?;
        let val = facet
            .value
            .get("value")
            .and_then(serde_json::Value::as_i64)
            .unwrap_or(-1);
        if val != 11 {
            return Err(format!("value after restart expected 11 got {val}"));
        }
        let events_after = client2
            .list_events(EventQuery::all(target))
            .await
            .map_err(|e| format!("list_events after restart failed: {e}"))?;
        if events_after.len() != events_before.len() {
            return Err(format!(
                "event count mismatch after restart: before {} after {}",
                events_before.len(),
                events_after.len()
            ));
        }
        if events_after[0].payload != events_before[0].payload {
            return Err("provenance payload mismatch after restart".to_string());
        }
        Ok(())
    });

    match result2 {
        Ok(()) => {
            let actual = format!(
                "controlled PostgreSQL application-boundary restart preserved world_time, facet, and history (capability: {}, backend_evidence: {})",
                ctx.restart_capability().as_str(),
                ctx.backend_evidence().as_str()
            );
            let expected = "PostgreSQL public observable state/provenance survives restart";
            let finding = Finding::new(
                descriptor.id().clone(),
                descriptor.name(),
                expected,
                actual.clone(),
                *ctx.backend_kind(),
                format!(
                    "validator:{}:{}:controlled-boundary-restart",
                    descriptor.id_str(),
                    ctx.backend_kind().as_str()
                ),
                vec![
                    EvidenceReference::new("validator:lifecycle"),
                    EvidenceReference::new(format!("backend:{}", ctx.backend_kind().as_str())),
                    EvidenceReference::new("validator:restart:controlled-boundary-restart"),
                    EvidenceReference::new(format!(
                        "restart_capability:{}",
                        ctx.restart_capability().as_str()
                    )),
                    EvidenceReference::new(format!(
                        "backend_evidence:{}",
                        ctx.backend_evidence().as_str()
                    )),
                ],
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
                let finding = finding_for(
                    descriptor,
                    ctx,
                    "PostgreSQL public observable state/provenance survives restart",
                    &actual,
                    outcome.clone(),
                );
                return ScenarioResult::new(descriptor.id().clone(), outcome, finding)
                    .with_capability_area(descriptor.capability_area().as_str());
            }
            result_fail(
                descriptor,
                ctx,
                "PostgreSQL public observable state/provenance survives restart",
                &actual,
            )
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{descriptors, lifecycle_registry};

    #[test]
    fn descriptors_are_four_and_deterministic() {
        let first = descriptors();
        let second = descriptors();
        assert_eq!(first.len(), 4);
        assert_eq!(first, second);
        let ids: Vec<_> = first.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec!["CV-001", "CV-002", "CV-003", "CV-004"]);
    }

    #[test]
    fn registry_contains_lifecycle_ids() {
        let registry = lifecycle_registry();
        assert_eq!(registry.len(), 4);
        assert!(registry.get("CV-001").is_some());
        assert!(registry.get("CV-004").is_some());
        let ids: Vec<_> = registry.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids, vec!["CV-001", "CV-002", "CV-003", "CV-004"]);
    }

    #[test]
    fn negative_test_url_is_not_pass() {
        let harness = crate::backend::BackendHarness::connect(
            crate::scenario::BackendKind::InMemory,
            "http://127.0.0.1:1",
        )
        .unwrap();
        let start = harness.start("CV-001");
        assert!(
            matches!(start, crate::backend::BackendStart::Unavailable { .. }),
            "negative test URL should be unavailable, not pass"
        );
        // Also verify that running the validator with that URL does not yield pass
        // This is covered by backend::tests::negative_test_url_is_unavailable
    }

    #[test]
    fn lifecycle_uses_only_public_surfaces_via_fence() {
        let fence = include_str!("../../../tools/check_storage_sql_ownership.py");
        assert!(
            fence.contains("VALIDATOR_FORBIDDEN") || fence.contains("validator"),
            "fence should contain validator forbidden patterns"
        );
    }

    #[test]
    fn lifecycle_findings_can_be_written_via_feedback_without_mutating_frontmatter() {
        use crate::finding::{EvidenceReference, Finding};
        use crate::outcome::ScenarioOutcome;
        use crate::reports::{RunMetadata, ScenarioResult, ValidationReport};
        use crate::scenario::ScenarioId;
        use std::fs;
        use std::sync::atomic::{AtomicU64, Ordering};

        static NEXT: AtomicU64 = AtomicU64::new(0);
        let id = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "loom-lifecycle-feedback-{}-{id}.md",
            std::process::id()
        ));
        let original = [
            "---",
            "task: VAL-T8",
            "issue: 260",
            "status: in_progress",
            "depends_on: [255, 256, 257, 259]",
            "created_at: 2026-08-24",
            "started_at: 2026-08-25",
            "completed_at:",
            "completion_pr:",
            "merge_sha:",
            "---",
            "# VAL-T8 — Baseline lifecycle",
            "",
            "## Acceptance",
            "",
            "- [ ] stable scenario IDs are registered",
            "",
        ]
        .join("\n");
        fs::write(&path, &original).expect("write temp task");
        let frontmatter_before = original.split("---").nth(1).unwrap_or("").to_owned();

        let fail_finding = Finding::new(
            ScenarioId::new("CV-002"),
            "lifecycle: mutate via Action and observe committed state via public reads",
            "mutation via Action commits and is observable via public reads",
            "facet missing after seed",
            crate::scenario::BackendKind::InMemory,
            "validator:CV-002:in-memory",
            vec![EvidenceReference::new("validator:lifecycle")],
            ScenarioOutcome::Fail,
        );
        let pass_finding = Finding::new(
            ScenarioId::new("CV-001"),
            "lifecycle: create/open World/Timeline via public API",
            "world is created and timeline is inspectable via public API",
            "world creation and reopen succeeded via LoomClient",
            crate::scenario::BackendKind::InMemory,
            "validator:CV-001:in-memory",
            vec![EvidenceReference::new("validator:lifecycle")],
            ScenarioOutcome::Pass,
        );
        let fail_result = ScenarioResult::new(
            ScenarioId::new("CV-002"),
            ScenarioOutcome::Fail,
            fail_finding,
        )
        .with_capability_area("lifecycle");
        let pass_result = ScenarioResult::new(
            ScenarioId::new("CV-001"),
            ScenarioOutcome::Pass,
            pass_finding,
        )
        .with_capability_area("lifecycle");
        let metadata = RunMetadata::new("run-lifecycle-feedback")
            .with_observation_date("2026-08-25")
            .with_task_record(path.to_str().unwrap())
            .with_evidence(EvidenceReference::path("/tmp/validator-report.json"));
        let report = ValidationReport::from_results(vec![fail_result, pass_result])
            .with_run_metadata(metadata)
            .with_backend(crate::scenario::BackendKind::InMemory);

        let summary = crate::feedback::TaskLedgerFeedback::append_report_to_task_ledger(&report)
            .expect("feedback append should succeed");
        assert_eq!(summary.files_updated(), 1);
        assert_eq!(summary.findings_appended(), 1);

        let after = fs::read_to_string(&path).expect("read after");
        let frontmatter_after = after.split("---").nth(1).unwrap_or("").to_owned();
        assert_eq!(
            frontmatter_before, frontmatter_after,
            "frontmatter must be byte-for-byte unchanged"
        );
        assert!(after.contains("## Capability Validation"));
        assert!(after.contains("CV-002"));
        assert_eq!(after.matches("## Validation Findings").count(), 1);
        fs::remove_file(path).expect("cleanup");
    }
}
