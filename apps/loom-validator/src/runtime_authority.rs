//! Negative Runtime Binding/Revision authority scenarios (V0).
//!
//! The composition-root fixtures may seed an intentionally incompatible
//! active revision or omit activation. Every observation and execution below
//! goes through the public `LoomClient`/`loom-api` surface.

#![allow(clippy::all, clippy::pedantic, clippy::nursery, clippy::restriction)]

use std::future::Future;

use loom_api::{
    ActionInvocation, ActionRequest, ActionService, AdminActivateRuntimeRevisionRequest,
    AdminService, CatalogService, CreateWorldFromTemplateRequest, TimelineTarget, WorldInstant,
    WorldService, WorldTemplateDescriptor,
};
use serde_json::json;

use crate::backend::BackendContext;
use crate::finding::{EvidenceReference, Finding};
use crate::outcome::ScenarioOutcome;
use crate::reports::ScenarioResult;
use crate::scenario::{BackendKind, ScenarioDescriptor};
use crate::{RegistryError, ScenarioRegistry};

pub const CV_010: &str = "CV-010";
pub const CV_011: &str = "CV-011";
const CAPABILITY_AREA: &str = "runtime-authority";
const COUNTER: &str = "neutral.counter";
const OBSERVER: &str = "neutral.observer";
const INCREMENT: &str = "neutral.counter.increment";

#[must_use]
pub fn descriptors() -> Vec<ScenarioDescriptor> {
    vec![
        ScenarioDescriptor::new(
            CV_010,
            "runtime authority: reject partial A+B binding under A-only active revision",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory],
            "test composition root supplies a persisted A+B World and an A-only active revision",
            vec!["ME-266".to_owned()],
            vec!["docs/architecture/world-runtime.md".to_owned()],
        ),
        ScenarioDescriptor::new(
            CV_011,
            "runtime authority: reject execution without an active Runtime Revision",
            CAPABILITY_AREA,
            vec![BackendKind::InMemory],
            "test composition root supplies installed software with no active Runtime Revision",
            vec!["ME-266".to_owned()],
            vec!["docs/architecture/runtime-contracts.md".to_owned()],
        ),
    ]
}

pub fn register_runtime_authority(registry: &mut ScenarioRegistry) -> Result<(), RegistryError> {
    for descriptor in descriptors() {
        registry.register(descriptor)?;
    }
    Ok(())
}

#[must_use]
pub fn execute_runtime_authority(
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

    match descriptor.id_str() {
        CV_010 => execute_partial_binding(descriptor, context),
        CV_011 => execute_missing_revision(descriptor, context),
        _ => result_fail(
            descriptor,
            context,
            "registered runtime-authority scenario",
            format!("unknown runtime-authority scenario {}", descriptor.id_str()),
        ),
    }
}

fn execute_partial_binding(
    descriptor: &ScenarioDescriptor,
    context: &BackendContext,
) -> ScenarioResult {
    let target = match serde_json::from_str::<TimelineTarget>(context.scope()) {
        Ok(target) => target,
        Err(error) => {
            return ScenarioResult::prerequisite(
                descriptor.id().clone(),
                descriptor.name(),
                *context.backend_kind(),
                format!("partial-binding fixture target is unavailable: {error}"),
            )
            .with_capability_area(descriptor.capability_area().as_str());
        }
    };

    let result = block_on(async {
        let active = context
            .client()
            .active_runtime_revision()
            .await?
            .ok_or_else(|| {
                loom_api::ApiError::unavailable("partial fixture has no active revision")
            })?;
        let partial = active
            .revision
            .capabilities
            .iter()
            .any(|capability| capability.capability_id == COUNTER)
            && !active
                .revision
                .capabilities
                .iter()
                .any(|capability| capability.capability_id == OBSERVER);
        if !partial {
            return Err(loom_api::ApiError::invalid_request(
                "partial fixture active revision is not A-only",
            ));
        }

        let partial_catalog = context.client().catalog_for_world(target.world_id).await?;
        let counter_visible = partial_catalog
            .capabilities
            .iter()
            .any(|capability| capability.id.to_string() == COUNTER);
        let observer_hidden = !partial_catalog
            .capabilities
            .iter()
            .any(|capability| capability.id.to_string() == OBSERVER);
        if !(counter_visible && observer_hidden) {
            return Err(loom_api::ApiError::invalid_request(
                "partial active revision did not produce the expected public catalog projection",
            ));
        }

        let execution = context
            .client()
            .invoke(ActionRequest::new(
                target,
                ActionInvocation::new(INCREMENT.into(), json!({"amount": 1})),
            ))
            .await;
        let unavailable = matches!(
            execution,
            Err(ref error) if error.code == loom_api::ApiErrorCode::Unavailable
        );
        if !unavailable {
            return Err(loom_api::ApiError::invalid_request(format!(
                "partial A+B execution was not unavailable: {execution:?}"
            )));
        }

        let full_revision = context
            .client()
            .list_runtime_revisions()
            .await?
            .into_iter()
            .find(|revision| {
                revision
                    .capabilities
                    .iter()
                    .any(|capability| capability.capability_id == COUNTER)
                    && revision
                        .capabilities
                        .iter()
                        .any(|capability| capability.capability_id == OBSERVER)
            })
            .ok_or_else(|| {
                loom_api::ApiError::not_found("full fixture revision was not published")
            })?;
        context
            .client()
            .activate_runtime_revision(AdminActivateRuntimeRevisionRequest {
                revision_id: full_revision.revision_id.clone(),
                expected_generation: Some(active.generation),
            })
            .await?;
        let restored_catalog = context.client().catalog_for_world(target.world_id).await?;
        let binding_still_contains_observer = restored_catalog
            .capabilities
            .iter()
            .any(|capability| capability.id.to_string() == OBSERVER);
        if !binding_still_contains_observer {
            return Err(loom_api::ApiError::invalid_request(
                "restoring compatible software did not expose the persisted B requirement",
            ));
        }
        Ok::<(), loom_api::ApiError>(())
    });

    match result {
        Ok(()) => result_pass(
            descriptor,
            context,
            "A+B World execution is unavailable under A-only software and the binding is unchanged",
            "public Runtime Revision/admin, catalog, action, and restoration checks passed",
        ),
        Err(error) => result_fail(
            descriptor,
            context,
            "A+B World execution is unavailable under A-only software and the binding is unchanged",
            format!("public negative check failed: {error:?}"),
        ),
    }
}

fn execute_missing_revision(
    descriptor: &ScenarioDescriptor,
    context: &BackendContext,
) -> ScenarioResult {
    let result = block_on(async {
        let active = context.client().active_runtime_revision().await?;
        if active.is_some() {
            return Err(loom_api::ApiError::invalid_request(
                "missing-revision fixture unexpectedly has an active revision",
            ));
        }

        let create = context
            .client()
            .create_world_from_template(CreateWorldFromTemplateRequest::new(
                WorldTemplateDescriptor::new(
                    "validator.runtime-authority.no-active",
                    1,
                    WorldInstant::new(1),
                )
                .requires_capability(COUNTER, "^0.1.0"),
            ))
            .await;
        let unavailable = matches!(
            create,
            Err(ref error) if error.code == loom_api::ApiErrorCode::Unavailable
        );
        if unavailable {
            Ok::<(), loom_api::ApiError>(())
        } else {
            Err(loom_api::ApiError::invalid_request(format!(
                "World creation without an active revision was not unavailable: {create:?}"
            )))
        }
    });

    match result {
        Ok(()) => result_pass(
            descriptor,
            context,
            "no active Runtime Revision is observable and execution is unavailable",
            "AdminService returned no active revision and public World creation was unavailable",
        ),
        Err(error) => result_fail(
            descriptor,
            context,
            "no active Runtime Revision is observable and execution is unavailable",
            format!("public negative check failed: {error:?}"),
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
            EvidenceReference::new("public-surface:loom-client"),
            EvidenceReference::new("public-surface:loom-api::AdminService"),
        ],
        outcome,
    )
}

fn result_pass(
    descriptor: &ScenarioDescriptor,
    context: &BackendContext,
    expected: &str,
    actual: &str,
) -> ScenarioResult {
    ScenarioResult::new(
        descriptor.id().clone(),
        ScenarioOutcome::Pass,
        finding_for(descriptor, context, expected, actual, ScenarioOutcome::Pass),
    )
    .with_capability_area(descriptor.capability_area().as_str())
}

fn result_fail(
    descriptor: &ScenarioDescriptor,
    context: &BackendContext,
    expected: &str,
    actual: String,
) -> ScenarioResult {
    ScenarioResult::new(
        descriptor.id().clone(),
        ScenarioOutcome::Fail,
        finding_for(
            descriptor,
            context,
            expected,
            &actual,
            ScenarioOutcome::Fail,
        ),
    )
    .with_capability_area(descriptor.capability_area().as_str())
}
