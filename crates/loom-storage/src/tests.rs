use std::{str::FromStr, sync::Arc};

use loom_api::{ActionRequest, ActionService, ExecutionResult, TimelineTarget};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EventDefinition, RegistrationError, ResolutionContext, ResolverError,
    WorkHandler, WorkHandlerDefinition,
};
use loom_core::{
    ActionTypeId, EntityId, EventId, EventSeq, EventTypeId, SchemaRevision, TimelineId,
    WorkHandlerId, WorkId, WorldEffect, WorldId, WorldInstant,
};
use loom_protocol::{ActionInvocation, ResolveOutcome};
use loom_runtime::{
    CommitError, EffectEngine, NewWork, PlatformTime, ProposedEvent, Resolution, Runtime,
    WorkMutation, WorkRecord, WorkSchedule, WorkStatus,
};
use serde_json::{Value, json};

use crate::InMemoryStore;

const OWNER: &str = "test";

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

fn world() -> WorldId {
    id(1)
}

fn timeline() -> TimelineId {
    id(2)
}

fn event(value: u128) -> EventId {
    id(value)
}

fn entity(value: u128) -> EntityId {
    id(value)
}

fn work(value: u128) -> WorkId {
    id(value)
}

fn registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([TestCapability {
        manifest: CapabilityManifest::parse(OWNER, "0.1.0")
            .expect("test Capability manifest should parse"),
    }])
    .expect("test Capability registry should assemble")
}

fn validated(
    store: &InMemoryStore,
    registry: &CapabilityRegistry,
    resolution: Resolution,
) -> loom_runtime::ValidatedResolution {
    let snapshot = store
        .snapshot(timeline())
        .expect("test Timeline should exist");
    let view = snapshot.world_view();
    EffectEngine::new(registry)
        .validate(&view, OWNER, resolution)
        .expect("test Resolution should validate")
}

fn pending_work(work_id: WorkId) -> WorkRecord {
    pending_work_with_handler(work_id, WorkHandlerId::from("test.handler"))
}

fn pending_work_with_handler(work_id: WorkId, handler: WorkHandlerId) -> WorkRecord {
    WorkRecord {
        id: work_id,
        timeline_id: timeline(),
        handler,
        schema_revision: SchemaRevision::new(1),
        payload: json!({"work": work_id.to_string()}),
        due_world_time: None,
        causal_event_id: None,
        origin_work_id: None,
        status: WorkStatus::Pending,
        attempt_count: 0,
        claim_generation: 0,
        available_at: PlatformTime::new(0),
        last_error: None,
        lease: None,
    }
}

fn event_with_effect(event_id: EventId, effect: WorldEffect, occurred_at: i64) -> ProposedEvent {
    ProposedEvent::new(
        event_id,
        EventTypeId::from("test.changed"),
        SchemaRevision::new(1),
        WorldInstant::new(occurred_at),
        json!({"event": event_id.to_string()}),
    )
    .with_effect(effect)
}

struct TestCapability {
    manifest: CapabilityManifest,
}

const NO_CHANGE_CAPABILITY: &str = "test.no_change";
const NO_CHANGE_ACTION: &str = "test.no_change_action";
const SCHEDULE_ACTION: &str = "test.schedule_work";
const CANCEL_ACTION: &str = "test.cancel_work";
const EMPTY_WORK_HANDLER: &str = "test.empty_work";

struct NoChangeCapability {
    manifest: CapabilityManifest,
}

impl Capability for NoChangeCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(NO_CHANGE_ACTION), SchemaRevision::new(1)),
            EmptyResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(SCHEDULE_ACTION), SchemaRevision::new(1)),
            ScheduleResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(CANCEL_ACTION), SchemaRevision::new(1)),
            CancelResolver,
        )?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(
                WorkHandlerId::from(EMPTY_WORK_HANDLER),
                SchemaRevision::new(1),
            ),
            EmptyWorkHandler,
        )
    }
}

fn no_change_registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([NoChangeCapability {
        manifest: CapabilityManifest::parse(NO_CHANGE_CAPABILITY, "0.1.0")
            .expect("no-change Capability manifest should parse"),
    }])
    .expect("no-change Capability registry should assemble")
}

struct EmptyResolver;

impl ActionResolver for EmptyResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        _input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Ok(ResolveOutcome::Resolved(Resolution::default()))
    }
}

struct ScheduleResolver;

impl ActionResolver for ScheduleResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let work_id = input
            .get("work_id")
            .and_then(Value::as_str)
            .ok_or_else(|| ResolverError::new("work_id must be a UUID string"))?
            .parse()
            .map_err(|_| ResolverError::new("work_id must be a UUID string"))?;
        Ok(ResolveOutcome::Resolved(Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::new(
                work_id,
                timeline(),
                WorkHandlerId::from(EMPTY_WORK_HANDLER),
                SchemaRevision::new(1),
                json!({}),
                WorkSchedule::Immediate,
            ))],
        )))
    }
}

struct CancelResolver;

impl ActionResolver for CancelResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let work_id = input
            .get("work_id")
            .and_then(Value::as_str)
            .ok_or_else(|| ResolverError::new("work_id must be a UUID string"))?
            .parse()
            .map_err(|_| ResolverError::new("work_id must be a UUID string"))?;
        Ok(ResolveOutcome::Resolved(Resolution::new(
            Vec::new(),
            vec![WorkMutation::Cancel(work_id)],
        )))
    }
}

struct EmptyWorkHandler;

impl WorkHandler for EmptyWorkHandler {
    fn handle(
        &self,
        _context: &dyn ResolutionContext,
        _payload: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Ok(ResolveOutcome::Resolved(Resolution::default()))
    }
}

impl Capability for TestCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_event(EventDefinition::new(
            EventTypeId::from("test.changed"),
            SchemaRevision::new(1),
        ))
    }
}

#[test]
fn empty_public_action_returns_no_change_without_advancing_timeline_version() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let runtime = Runtime::new(&store, no_change_registry()).expect("Runtime should assemble");
    let before = store
        .snapshot(timeline())
        .expect("test Timeline should be readable")
        .version();

    let result = runtime
        .invoke(ActionRequest::new(
            TimelineTarget::new(world(), timeline()),
            ActionInvocation::new(ActionTypeId::from(NO_CHANGE_ACTION), json!({})),
        ))
        .expect("empty Action should execute");

    assert_eq!(result, ExecutionResult::NoChange);
    let after = store
        .snapshot(timeline())
        .expect("test Timeline should be readable");
    assert_eq!(after.version(), before);
    assert!(after.events.is_empty());
}

#[test]
fn work_only_actions_use_each_injected_platform_time_and_persist_schedule_and_cancel() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let clock = loom_runtime::ManualPlatformClock::new(PlatformTime::new(7));
    let runtime = Runtime::new(&store, no_change_registry())
        .expect("Runtime should assemble")
        .with_platform_clock(clock.clone());
    let target = TimelineTarget::new(world(), timeline());

    let first = runtime
        .invoke(ActionRequest::new(
            target,
            ActionInvocation::new(
                ActionTypeId::from(SCHEDULE_ACTION),
                json!({"work_id": work(30).to_string()}),
            ),
        ))
        .expect("first Work schedule should execute");
    assert!(matches!(
        first,
        ExecutionResult::Committed {
            ref event_ids,
            ..
        } if event_ids.is_empty()
    ));
    assert_eq!(
        store
            .work(timeline(), work(30))
            .expect("first Work should be readable")
            .expect("first Work should exist")
            .available_at,
        PlatformTime::new(7)
    );

    clock.set(11.into());
    let second = runtime
        .invoke(ActionRequest::new(
            target,
            ActionInvocation::new(
                ActionTypeId::from(SCHEDULE_ACTION),
                json!({"work_id": work(31).to_string()}),
            ),
        ))
        .expect("second Work schedule should execute");
    assert!(matches!(
        second,
        ExecutionResult::Committed {
            ref event_ids,
            ..
        } if event_ids.is_empty()
    ));
    assert_eq!(
        store
            .work(timeline(), work(31))
            .expect("second Work should be readable")
            .expect("second Work should exist")
            .available_at,
        PlatformTime::new(11)
    );

    let cancel = runtime
        .invoke(ActionRequest::new(
            target,
            ActionInvocation::new(
                ActionTypeId::from(CANCEL_ACTION),
                json!({"work_id": work(31).to_string()}),
            ),
        ))
        .expect("Work cancellation should execute");
    assert!(matches!(
        cancel,
        ExecutionResult::Committed {
            ref event_ids,
            ..
        } if event_ids.is_empty()
    ));
    assert_eq!(
        store
            .work(timeline(), work(31))
            .expect("cancelled Work should be readable")
            .expect("cancelled Work should exist")
            .status,
        WorkStatus::Cancelled
    );
}

#[test]
fn zero_event_work_completion_commits_runtime_state_atomically() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work_with_handler(
            work(40),
            WorkHandlerId::from(EMPTY_WORK_HANDLER),
        ))
        .expect("empty Work fixture should be seeded");
    let runtime = Runtime::new(&store, no_change_registry()).expect("Runtime should assemble");

    let result = runtime
        .execute_work(
            TimelineTarget::new(world(), timeline()),
            work(40),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(2),
        )
        .expect("empty Work resolution should complete");

    assert!(matches!(
        result,
        ExecutionResult::Committed {
            ref event_ids,
            timeline_version,
        } if event_ids.is_empty() && timeline_version.state_revision.value() == 1
    ));
    let snapshot = store
        .snapshot(timeline())
        .expect("completed Timeline should be readable");
    assert!(snapshot.events.is_empty());
    assert_eq!(snapshot.version().state_revision.value(), 1);
    assert_eq!(
        store
            .work(timeline(), work(40))
            .expect("completed Work should be readable")
            .expect("completed Work should exist")
            .status,
        WorkStatus::Completed
    );
}

#[test]
fn commit_assigns_contiguous_event_sequences_and_advances_once() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    let resolution = Resolution::new(
        vec![
            event_with_effect(
                event(10),
                WorldEffect::CreateEntity {
                    entity_id: entity(20),
                },
                5,
            ),
            ProposedEvent::new(
                event(11),
                EventTypeId::from("test.changed"),
                SchemaRevision::new(1),
                WorldInstant::new(3),
                json!({"fact": true}),
            ),
        ],
        Vec::new(),
    );
    let validated = validated(&store, &registry, resolution);

    let result = store
        .commit(&validated, None, PlatformTime::new(1))
        .expect("matching CAS commit should succeed");
    assert_eq!(
        result
            .events
            .iter()
            .map(|committed| committed.event_seq.value())
            .collect::<Vec<_>>(),
        vec![1, 2]
    );
    assert_eq!(result.version.head_event_seq, EventSeq::new(2));
    assert_eq!(result.version.state_revision.value(), 1);

    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(snapshot.events.len(), 2);
    assert_eq!(snapshot.events[0].event_seq, EventSeq::new(1));
    assert_eq!(snapshot.events[1].event_seq, EventSeq::new(2));
    assert_eq!(snapshot.world_time(), WorldInstant::new(5));
    assert!(snapshot.world_view().entity(entity(20)).is_some());
}

#[test]
fn stale_cas_leaves_event_state_and_work_unchanged() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    let validated = validated(
        &store,
        &registry,
        Resolution::new(
            vec![event_with_effect(
                event(30),
                WorldEffect::CreateEntity {
                    entity_id: entity(31),
                },
                7,
            )],
            Vec::new(),
        ),
    );
    store
        .commit(&validated, None, PlatformTime::new(1))
        .expect("first commit should succeed");
    let before = store.snapshot(timeline()).expect("snapshot should exist");

    let error = store
        .commit(&validated, None, PlatformTime::new(2))
        .expect_err("reusing a stale validated token must conflict");
    assert!(matches!(error, CommitError::TimelineConflict { .. }));

    let after = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after.version(), before.version());
    assert_eq!(after.world_time(), before.world_time());
    assert_eq!(after.events.len(), before.events.len());
    assert_eq!(
        after.world_view().entity(entity(31)),
        before.world_view().entity(entity(31))
    );
    assert!(after.works.is_empty());
}

#[test]
fn staged_commit_does_not_expose_event_before_work_failure() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(40)))
        .expect("current Work fixture should be seeded");
    let registry = registry();
    let resolution = Resolution::new(
        vec![event_with_effect(
            event(41),
            WorldEffect::CreateEntity {
                entity_id: entity(42),
            },
            9,
        )],
        vec![WorkMutation::Schedule(NewWork::new(
            work(40),
            timeline(),
            WorkHandlerId::from("test.handler"),
            SchemaRevision::new(1),
            json!({}),
            loom_runtime::WorkSchedule::Immediate,
        ))],
    );
    let validated = validated(&store, &registry, resolution);
    let before = store.snapshot(timeline()).expect("snapshot should exist");

    let error = store
        .commit(&validated, None, PlatformTime::new(1))
        .expect_err("duplicate Work should fail before staged swap");
    assert!(matches!(
        error,
        CommitError::Work(loom_runtime::WorkError::DuplicateWork { .. })
    ));

    let after = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after.version(), before.version());
    assert_eq!(after.world_time(), before.world_time());
    assert!(after.events.is_empty());
    assert!(after.world_view().entity(entity(42)).is_none());
    assert_eq!(after.works[0].status, WorkStatus::Pending);
}

#[test]
fn work_creation_and_current_completion_share_zero_event_commit() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(50)))
        .expect("current Work fixture should be seeded");
    let claim = store
        .claim(
            timeline(),
            work(50),
            PlatformTime::new(0),
            PlatformTime::new(10),
        )
        .expect("current Work should be claimable");
    let registry = CapabilityRegistry::new();
    let validated = validated(
        &store,
        &registry,
        Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::new(
                work(51),
                timeline(),
                WorkHandlerId::from("test.handler"),
                SchemaRevision::new(1),
                json!({"next": true}),
                loom_runtime::WorkSchedule::At(WorldInstant::new(100)),
            ))],
        ),
    );

    let result = store
        .commit(&validated, Some(&claim), PlatformTime::new(5))
        .expect("Work completion and creation should commit atomically");
    assert!(result.events.is_empty());
    assert_eq!(result.completed_work, Some(work(50)));
    assert_eq!(result.version.head_event_seq, EventSeq::new(0));
    assert_eq!(result.version.state_revision.value(), 1);

    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(snapshot.world_time(), WorldInstant::new(0));
    assert_eq!(snapshot.events.len(), 0);
    assert_eq!(
        snapshot
            .works
            .iter()
            .find(|item| item.id == work(50))
            .expect("current Work should remain readable")
            .status,
        WorkStatus::Completed
    );
    assert_eq!(
        snapshot
            .works
            .iter()
            .find(|item| item.id == work(51))
            .expect("new Work should be readable")
            .status,
        WorkStatus::Pending
    );
}

#[test]
fn retry_and_expired_claims_preserve_work_identity_and_fence_winner() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(60)))
        .expect("Work fixture should be seeded");
    let initial = store.snapshot(timeline()).expect("snapshot should exist");
    let first_claim = store
        .claim(
            timeline(),
            work(60),
            PlatformTime::new(0),
            PlatformTime::new(5),
        )
        .expect("first claim should succeed");
    let retried = store
        .retry(
            &first_claim,
            PlatformTime::new(1),
            PlatformTime::new(3),
            Some("temporary failure".to_owned()),
        )
        .expect("technical retry should update metadata only");
    assert_eq!(retried.id, work(60));
    assert_eq!(retried.status, WorkStatus::Pending);
    assert_eq!(retried.attempt_count, 1);
    assert_eq!(retried.last_error.as_deref(), Some("temporary failure"));

    let after_retry = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after_retry.version(), initial.version());
    assert!(after_retry.events.is_empty());
    assert_eq!(after_retry.world_time(), initial.world_time());

    let second_claim = store
        .claim(
            timeline(),
            work(60),
            PlatformTime::new(3),
            PlatformTime::new(6),
        )
        .expect("Work should be claimable after retry availability");
    let registry = CapabilityRegistry::new();
    let validated = validated(&store, &registry, Resolution::new(Vec::new(), Vec::new()));
    let expired = store
        .commit(&validated, Some(&second_claim), PlatformTime::new(6))
        .expect_err("deadline equality must treat the lease as expired");
    assert!(matches!(
        expired,
        CommitError::Work(loom_runtime::WorkError::LeaseExpired { .. })
    ));

    let third_claim = store
        .claim(
            timeline(),
            work(60),
            PlatformTime::new(6),
            PlatformTime::new(10),
        )
        .expect("expired Work should be claimable with a new fence");
    let stale = store
        .commit(&validated, Some(&second_claim), PlatformTime::new(7))
        .expect_err("old fence must lose after re-claim");
    assert!(matches!(
        stale,
        CommitError::Work(loom_runtime::WorkError::StaleClaim { .. })
    ));
    store
        .commit(&validated, Some(&third_claim), PlatformTime::new(7))
        .expect("new fence should be the sole completion winner");

    let final_snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(final_snapshot.events.len(), 0);
    assert_eq!(final_snapshot.world_time(), WorldInstant::new(0));
    assert_eq!(final_snapshot.version().state_revision.value(), 1);
    assert_eq!(
        final_snapshot
            .works
            .iter()
            .find(|item| item.id == work(60))
            .expect("Work should remain readable")
            .status,
        WorkStatus::Completed
    );
}

#[test]
fn concurrent_cas_and_claim_choose_one_winner() {
    let store = Arc::new(InMemoryStore::new());
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(70)))
        .expect("Work fixture should be seeded");
    let registry = registry();
    let first = validated(
        &store,
        &registry,
        Resolution::new(
            vec![event_with_effect(
                event(71),
                WorldEffect::CreateEntity {
                    entity_id: entity(72),
                },
                2,
            )],
            Vec::new(),
        ),
    );
    let second = validated(
        &store,
        &registry,
        Resolution::new(
            vec![event_with_effect(
                event(73),
                WorldEffect::CreateEntity {
                    entity_id: entity(74),
                },
                3,
            )],
            Vec::new(),
        ),
    );

    let first_store = Arc::clone(&store);
    let second_store = Arc::clone(&store);
    let (first_result, second_result) = std::thread::scope(|scope| {
        let first_handle = scope.spawn(|| first_store.commit(&first, None, PlatformTime::new(0)));
        let second_handle =
            scope.spawn(|| second_store.commit(&second, None, PlatformTime::new(0)));
        (
            first_handle
                .join()
                .expect("first commit thread should finish"),
            second_handle
                .join()
                .expect("second commit thread should finish"),
        )
    });
    assert_eq!(
        usize::from(first_result.is_ok()) + usize::from(second_result.is_ok()),
        1,
        "exactly one stale-CAS contender should win"
    );
    assert_eq!(
        usize::from(matches!(
            first_result,
            Err(CommitError::TimelineConflict { .. })
        )) + usize::from(matches!(
            second_result,
            Err(CommitError::TimelineConflict { .. })
        )),
        1,
        "the losing contender should observe a typed conflict"
    );
    assert_eq!(
        store
            .snapshot(timeline())
            .expect("snapshot should exist")
            .events
            .len(),
        1
    );
}

#[test]
fn concurrent_claims_choose_one_fence_winner() {
    let store = Arc::new(InMemoryStore::new());
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(70)))
        .expect("Work fixture should be seeded");
    let claim_store = Arc::clone(&store);
    let other_claim_store = Arc::clone(&store);
    let (claim_one, claim_two) = std::thread::scope(|scope| {
        let claim_one_handle = scope.spawn(|| {
            claim_store.claim(
                timeline(),
                work(70),
                PlatformTime::new(0),
                PlatformTime::new(10),
            )
        });
        let claim_two_handle = scope.spawn(|| {
            other_claim_store.claim(
                timeline(),
                work(70),
                PlatformTime::new(0),
                PlatformTime::new(10),
            )
        });
        (
            claim_one_handle
                .join()
                .expect("first claim thread should finish"),
            claim_two_handle
                .join()
                .expect("second claim thread should finish"),
        )
    });
    assert_eq!(
        usize::from(claim_one.is_ok()) + usize::from(claim_two.is_ok()),
        1
    );
    assert_eq!(
        usize::from(matches!(
            claim_one,
            Err(loom_runtime::WorkError::AlreadyClaimed { .. })
        )) + usize::from(matches!(
            claim_two,
            Err(loom_runtime::WorkError::AlreadyClaimed { .. })
        )),
        1
    );
}
