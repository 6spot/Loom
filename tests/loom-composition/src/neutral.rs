//! Test-only World Templates and Runtime helpers for the approved neutral extensions.

use std::str::FromStr;

use loom_api::{ActionRequest, ActionService, TimelineTarget, WorldTemplateDescriptor};
use loom_core::{ActionTypeId, EntityId, EventId, TimelineId, WorldId, WorldInstant};
pub use loom_neutral::{
    BLOB_ATTACH_ACTION, BLOB_ATTACHED_EVENT, BLOB_FACET, COUNTER_CAPABILITY, COUNTER_FACET,
    COUNTER_INCREMENT_ACTION, COUNTER_INCREMENT_WORK, COUNTER_INCREMENTED_EVENT,
    COUNTER_SEED_ACTION, COUNTER_SEEDED_EVENT, LINK_CREATE_ACTION, LINK_CREATED_EVENT,
    LINK_RELATIONSHIP, OBSERVER_ACTION, OBSERVER_CAPABILITY, OBSERVER_EVENT, OBSERVER_WORK,
    SEMANTIC_INDEX_ID, registry,
};
use loom_protocol::ActionInvocation;
use loom_runtime::{
    IdentityAllocator, PlatformTime, Runtime, RuntimeRevisionCapability, RuntimeRevisionDescriptor,
};
use loom_storage::InMemoryStore;
use serde_json::{Value, json};

/// Stable Template family used by both fixture revisions.
pub const TEMPLATE_ID: &str = "neutral.world";

/// Builds the first Template revision: counter semantics only and one seed
/// bootstrap Action.
#[must_use]
pub fn template_revision_one(
    initial_world_time: WorldInstant,
    seed_event_id: EventId,
    entity_id: EntityId,
) -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new(TEMPLATE_ID, 1, initial_world_time)
        .requires_capability(COUNTER_CAPABILITY, "^0.1.0")
        .with_configuration(json!({"profile": "counter"}))
        .with_bootstrap_action(ActionInvocation::new(
            ActionTypeId::from(COUNTER_SEED_ACTION),
            json!({
                "event_id": seed_event_id.to_string(),
                "entity_id": entity_id.to_string(),
                "value": 1,
            }),
        ))
}

/// Builds the second Template revision: observer semantics (and its counter
/// dependency) with a seed followed by an observation bootstrap Action.
#[must_use]
pub fn template_revision_two(
    initial_world_time: WorldInstant,
    seed_event_id: EventId,
    observation_event_id: EventId,
    entity_id: EntityId,
) -> WorldTemplateDescriptor {
    WorldTemplateDescriptor::new(TEMPLATE_ID, 2, initial_world_time)
        .requires_capability(OBSERVER_CAPABILITY, "^0.1.0")
        .with_configuration(json!({"profile": "observer"}))
        .with_bootstrap_actions([
            ActionInvocation::new(
                ActionTypeId::from(COUNTER_SEED_ACTION),
                json!({
                    "event_id": seed_event_id.to_string(),
                    "entity_id": entity_id.to_string(),
                    "value": 2,
                }),
            ),
            ActionInvocation::new(
                ActionTypeId::from(OBSERVER_ACTION),
                json!({
                    "event_id": observation_event_id.to_string(),
                    "entity_id": entity_id.to_string(),
                }),
            ),
        ])
}

/// Creates the immutable Runtime Revision publication matching the installed
/// neutral registry for composition fixtures.
///
/// # Panics
///
/// Panics if the fixture registry cannot produce a valid immutable descriptor.
#[must_use]
pub fn runtime_revision(
    capability_registry: &loom_capability::CapabilityRegistry,
) -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        "neutral-fixtures-r1",
        PlatformTime::new(1),
        "neutral-fixtures",
        capability_registry.loom_version().clone(),
        capability_registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("neutral-fixture:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("neutral Runtime Revision should be valid")
}

/// Deterministic World/Timeline allocator for composition tests.
#[derive(Clone, Copy, Debug)]
pub struct FixedIdentityAllocator {
    /// World identity returned by this allocator.
    pub world_id: WorldId,
    /// Timeline identity returned by this allocator.
    pub timeline_id: TimelineId,
}

impl IdentityAllocator for FixedIdentityAllocator {
    fn allocate_world_id(&self) -> WorldId {
        self.world_id
    }

    fn allocate_timeline_id(&self) -> TimelineId {
        self.timeline_id
    }
}

/// Convenience constructor for an identity used by neutral fixtures.
///
/// # Panics
///
/// Panics if the fixed UUID-shaped fixture value cannot be parsed as `T`.
#[must_use]
pub fn identity<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("neutral fixture identity should parse")
}

/// Invokes an Action through the public API for a neutral World.
///
/// # Errors
///
/// Returns the API error produced by Runtime when the target, binding, input or
/// semantic Action cannot be executed.
pub async fn invoke(
    runtime: &Runtime<&InMemoryStore>,
    target: TimelineTarget,
    action: impl Into<ActionTypeId>,
    input: Value,
) -> loom_api::ApiResult<loom_api::ExecutionResult> {
    runtime
        .invoke(ActionRequest::new(
            target,
            ActionInvocation::new(action.into(), input),
        ))
        .await
}
