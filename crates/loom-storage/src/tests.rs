use std::{
    str::FromStr,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};

use loom_agency::{
    AgentContextRequest, CognitiveError, CognitiveExecutor, CognitiveFuture, CognitiveMetadata,
    CognitiveRequest, ContextSource, DecisionReusePolicy, ExecutionPolicy, ExecutorMetadata,
};
use loom_api::{
    ActionRequest, ActionService, AdminScheduleAgencyWakeRequest, AdminService,
    AdminTerminalWorkState, AdminTerminalizeWorkRequest, ApiErrorCode, ChangeFeedCursor,
    CreateWorldFromTemplateRequest, ExecutionResult, ForkTimelineRequest,
    IngressAuthorizationContext, IngressEnvelope, IngressId, IngressProvenance, IngressService,
    IngressStatus, IngressTimeMetadata, SubscriptionRequest, SubscriptionResult,
    SubscriptionService, TimelineTarget, WorldService, WorldTemplateDescriptor,
};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityDependency, CapabilityId,
    CapabilityManifest, CapabilityRegistrar, CapabilityRegistry, EventDefinition, FacetDefinition,
    RegistrationError, RelationshipDefinition, ResolutionContext, ResolverError, WorkHandler,
    WorkHandlerDefinition,
};
use loom_core::{
    ActionTypeId, Entity, EntityId, EventId, EventRef, EventSeq, EventTypeId, FacetOwner,
    FacetTypeId, RelationshipParticipant, RelationshipTypeId, SchemaRevision, StateRevision,
    TimelineId, TimelineVersion, WorkHandlerId, WorkId, WorldEffect, WorldId, WorldInstant,
};
use loom_protocol::{
    ActionInvocation, CausalLink, NewWork, ProposedEvent, Rejection, Resolution, ResolveOutcome,
    WorkMutation, WorkSchedule,
};
use loom_runtime::{
    AdvanceWorldTime, AgentContextItem, AgentContextPlan, AgentWorldViewBuilder, BindingError,
    ChangeFeedStore, ChronologyBudgetExceeded, CognitiveDisposition, CommitAuthorityContext,
    CommitError, CommitStore, DeterministicCognitiveExecutor, DeterministicCognitiveStep,
    EffectEngine, ExecutionEvidence, ExecutionSessionStore, ForkWork, IngressStore,
    IngressSubmission, LogicalWorkTransition, ManualPlatformClock, PinnedReadPolicy, PlatformTime,
    Runtime, RuntimeControlStore, RuntimeRevisionCapability, RuntimeRevisionDescriptor,
    RuntimeRevisionError, RuntimeRevisionId, RuntimeRevisionStore, SchedulerCommitStore,
    TimelineDriverResult, TimelineFork, TimelineForkStore, WorkError, WorkRecord, WorkStatus,
    WorkTarget, WorkTerminalState, WorkTerminalization, WorldRuntimeBinding,
    WorldRuntimeBindingStore, WorldTimeError,
};
use semver::{Version, VersionReq};
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

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the ancestry feed acceptance scenario is intentionally linear"
)]
async fn change_feed_is_bounded_strict_after_and_ancestry_qualified() {
    let store = InMemoryStore::new();
    let test_registry = registry();
    let child_timeline = id::<TimelineId>(3);
    let grandchild_timeline = id::<TimelineId>(4);
    store
        .create_timeline(world(), timeline())
        .expect("root Timeline should be created");

    let commit_event = |timeline_id, event_id| {
        let token = validated_at(
            &store,
            &test_registry,
            timeline_id,
            Resolution::new(
                vec![ProposedEvent::new(
                    event_id,
                    EventTypeId::from("test.changed"),
                    SchemaRevision::new(1),
                    json!({"event": event_id.to_string()}),
                )],
                Vec::new(),
            ),
        )
        .expect("feed Event should validate");
        store
            .commit(&token, None, PlatformTime::new(1))
            .expect("feed Event should commit");
    };

    let root_event = event(201);
    commit_event(timeline(), root_event);
    let root_fork_version = store
        .snapshot(timeline())
        .expect("root fork position should be readable")
        .version();
    TimelineForkStore::fork_timeline(
        &store,
        &TimelineFork::new(timeline(), root_fork_version, child_timeline),
    )
    .await
    .expect("child Timeline should fork");

    let root_tail = event(202);
    commit_event(timeline(), root_tail);
    let child_event = event(203);
    commit_event(child_timeline, child_event);
    let child_fork_version = store
        .snapshot(child_timeline)
        .expect("grandchild fork position should be readable")
        .version();
    TimelineForkStore::fork_timeline(
        &store,
        &TimelineFork::new(child_timeline, child_fork_version, grandchild_timeline),
    )
    .await
    .expect("grandchild Timeline should fork");

    let child_tail = event(204);
    commit_event(child_timeline, child_tail);
    let grandchild_event = event(205);
    commit_event(grandchild_timeline, grandchild_event);

    let first_page =
        ChangeFeedStore::read_change_feed(&store, grandchild_timeline, EventSeq::new(0), 2)
            .await
            .expect("grandchild feed page should be readable");
    assert_eq!(first_page.world_id, world());
    assert_eq!(first_page.events.len(), 2);
    assert!(first_page.has_more);
    assert_eq!(
        first_page
            .events
            .iter()
            .map(loom_runtime::CommittedEvent::event_ref)
            .collect::<Vec<_>>(),
        vec![
            EventRef::new(timeline(), root_event),
            EventRef::new(child_timeline, child_event),
        ]
    );

    let resumed =
        ChangeFeedStore::read_change_feed(&store, grandchild_timeline, EventSeq::new(1), 10)
            .await
            .expect("older cursor should resume without a gap");
    assert_eq!(
        resumed
            .events
            .iter()
            .map(loom_runtime::CommittedEvent::event_ref)
            .collect::<Vec<_>>(),
        vec![
            EventRef::new(child_timeline, child_event),
            EventRef::new(grandchild_timeline, grandchild_event),
        ]
    );
    assert!(!resumed.has_more);

    let child_page =
        ChangeFeedStore::read_change_feed(&store, child_timeline, EventSeq::new(0), 10)
            .await
            .expect("child feed should use its immutable fork boundary");
    assert_eq!(
        child_page
            .events
            .iter()
            .map(loom_runtime::CommittedEvent::event_ref)
            .collect::<Vec<_>>(),
        vec![
            EventRef::new(timeline(), root_event),
            EventRef::new(child_timeline, child_event),
            EventRef::new(child_timeline, child_tail),
        ]
    );

    let runtime = Runtime::new(&store, registry()).expect("feed Runtime should assemble");
    let backpressure = SubscriptionService::subscribe(
        &runtime,
        SubscriptionRequest::new(TimelineTarget::new(world(), grandchild_timeline), 257),
    )
    .await
    .expect("over-demand should return a bounded response");
    match backpressure {
        SubscriptionResult::Backpressure(value) => assert_eq!(value.max_events, 256),
        other => panic!("expected Backpressure, got {other:?}"),
    }

    let target = TimelineTarget::new(world(), grandchild_timeline);
    let page = SubscriptionService::subscribe(&runtime, SubscriptionRequest::new(target, 2))
        .await
        .expect("bounded subscription page should be readable");
    let next_cursor = match page {
        SubscriptionResult::Events(page) => {
            assert_eq!(page.events.len(), 2);
            assert!(page.has_more);
            page.next_cursor
                .expect("non-empty page should advance cursor")
        }
        other => panic!("expected Events, got {other:?}"),
    };
    assert_eq!(next_cursor.after, EventSeq::new(2));

    let resumed = SubscriptionService::subscribe(
        &runtime,
        SubscriptionRequest::resume(target, ChangeFeedCursor::after(target, EventSeq::new(3)), 2),
    )
    .await
    .expect("empty resumed page should preserve cursor");
    assert_eq!(
        resumed,
        SubscriptionResult::Resumed(loom_api::SubscriptionResume {
            cursor: ChangeFeedCursor::after(target, EventSeq::new(3)),
        })
    );
}

fn world() -> WorldId {
    id(1)
}

fn timeline() -> TimelineId {
    id(2)
}

fn second_timeline() -> TimelineId {
    id(3)
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

fn runtime_revision() -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("r1"),
        PlatformTime::new(10),
        "loom-core-build-1",
        Version::new(0, 1, 0),
        [RuntimeRevisionCapability::new(
            OWNER,
            "test-build-1",
            Version::new(1, 0, 0),
            VersionReq::parse("^0.1.0").expect("Loom compatibility should parse"),
        )],
    )
    .map(|revision| {
        revision
            .with_execution_policy_id("execution-v1")
            .with_provider_policy_id("provider-v1")
            .with_change_summary("test revision metadata")
            .with_semantic_behavior_changed(true)
    })
    .expect("Runtime Revision descriptor should be valid")
}

#[tokio::test]
async fn runtime_revision_history_is_immutable_and_activation_uses_generation_cas() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("World fixture should be created");
    let revision = runtime_revision();

    RuntimeRevisionStore::register_revision(&store, revision.clone())
        .await
        .expect("revision should publish once");
    assert_eq!(
        RuntimeRevisionStore::register_revision(&store, revision.clone()).await,
        Err(RuntimeRevisionError::RevisionAlreadyExists {
            revision_id: RuntimeRevisionId::from("r1")
        })
    );
    assert_eq!(
        RuntimeRevisionStore::confirm_revision(&store, revision.clone()).await,
        Ok(revision.clone())
    );
    assert_eq!(
        RuntimeRevisionStore::read_active_revision(&store)
            .await
            .expect("active selection should be readable before activation"),
        None
    );

    let before = store
        .snapshot(timeline())
        .expect("Timeline should be readable before activation");
    let selection = RuntimeRevisionStore::activate_revision(
        &store,
        RuntimeRevisionId::from("r1"),
        None,
        PlatformTime::new(20),
    )
    .await
    .expect("first activation should win the empty-selection CAS");
    assert_eq!(selection.revision(), &revision);
    assert_eq!(selection.generation(), 1);
    assert_eq!(selection.activated_at(), PlatformTime::new(20));
    let history = RuntimeRevisionStore::read_activation_history(&store)
        .await
        .expect("activation history should be readable after activation");
    assert_eq!(history.len(), 1);
    assert_eq!(history[0].revision_id(), &RuntimeRevisionId::from("r1"));
    assert_eq!(history[0].generation(), 1);
    assert_eq!(history[0].activated_at(), PlatformTime::new(20));
    assert_eq!(
        RuntimeRevisionStore::activate_revision(
            &store,
            RuntimeRevisionId::from("r1"),
            None,
            PlatformTime::new(21),
        )
        .await,
        Err(RuntimeRevisionError::ActiveRevisionConflict {
            expected_generation: None,
            actual_generation: Some(1),
        })
    );
    let after = store
        .snapshot(timeline())
        .expect("Timeline should be readable after activation");
    assert_eq!(
        RuntimeRevisionStore::read_activation_history(&store)
            .await
            .expect("activation history should remain readable after the loser")
            .len(),
        1
    );
    assert_eq!(after.version(), before.version());
    assert_eq!(after.world_time(), before.world_time());
    assert!(after.events.is_empty());
    assert!(after.works.is_empty());
}

#[tokio::test]
async fn world_binding_is_persisted_once_and_shared_across_timelines() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("first Timeline should be created");
    store
        .create_timeline(world(), second_timeline())
        .expect("second Timeline should share the World");
    let binding = WorldRuntimeBinding::new(
        [(
            CapabilityId::from(OWNER),
            CapabilityDependency::parse(OWNER, "^0.1.0")
                .expect("binding requirement should parse")
                .version,
        )],
        json!({"fixture": "immutable"}),
        1,
        Some("test-template".to_owned()),
    );

    WorldRuntimeBindingStore::persist_binding(&store, world(), binding.clone())
        .await
        .expect("binding should persist once");
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&store, world())
            .await
            .expect("binding should reload"),
        binding
    );
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&store, world())
            .await
            .expect("second Timeline should see the World binding"),
        binding
    );

    let replacement = WorldRuntimeBinding::new(
        [(
            CapabilityId::from("replacement"),
            CapabilityDependency::parse("replacement", "*")
                .expect("replacement requirement should parse")
                .version,
        )],
        json!({"fixture": "replacement"}),
        2,
        Some("replacement".to_owned()),
    );
    assert_eq!(
        WorldRuntimeBindingStore::persist_binding(&store, world(), replacement).await,
        Err(BindingError::BindingAlreadyExists { world_id: world() })
    );
}

#[tokio::test]
async fn different_worlds_keep_distinct_bindings() {
    let store = InMemoryStore::new();
    let other_world = id::<WorldId>(4);
    let other_timeline = id::<TimelineId>(5);
    store
        .create_timeline(world(), timeline())
        .expect("first World fixture should be created");
    store
        .create_timeline(other_world, other_timeline)
        .expect("second World fixture should be created");
    let first = WorldRuntimeBinding::new(
        [(
            CapabilityId::from(OWNER),
            CapabilityDependency::parse(OWNER, "^0.1.0")
                .expect("first World requirement should parse")
                .version,
        )],
        json!({"fixture": "first-world"}),
        1,
        Some("first-world".to_owned()),
    );
    let second = WorldRuntimeBinding::new(
        [(
            CapabilityId::from("other"),
            CapabilityDependency::parse("other", "*")
                .expect("second World requirement should parse")
                .version,
        )],
        json!({"fixture": "second-world"}),
        1,
        Some("second-world".to_owned()),
    );

    WorldRuntimeBindingStore::persist_binding(&store, world(), first.clone())
        .await
        .expect("first World binding should persist");
    WorldRuntimeBindingStore::persist_binding(&store, other_world, second.clone())
        .await
        .expect("second World binding should persist");
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&store, world()).await,
        Ok(first)
    );
    assert_eq!(
        WorldRuntimeBindingStore::read_binding(&store, other_world).await,
        Ok(second)
    );
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

fn validated_at(
    store: &InMemoryStore,
    registry: &CapabilityRegistry,
    timeline_id: TimelineId,
    resolution: Resolution,
) -> Result<loom_runtime::ValidatedResolution, loom_runtime::RuntimeError> {
    let snapshot = store
        .snapshot(timeline_id)
        .expect("test Timeline should exist");
    EffectEngine::new(registry).validate(&snapshot.world_view(), OWNER, resolution)
}

fn pending_work(work_id: WorkId) -> WorkRecord {
    pending_work_with_handler(work_id, WorkHandlerId::from("test.handler"))
}

fn pending_work_with_handler(work_id: WorkId, handler: WorkHandlerId) -> WorkRecord {
    WorkRecord {
        id: work_id,
        timeline_id: timeline(),
        target: WorkTarget::CapabilityWork {
            owner: None,
            handler,
        },
        schema_revision: SchemaRevision::new(1),
        payload: json!({"work": work_id.to_string()}),
        effective_due_world_time: WorldInstant::new(0),
        logical_schedule_order: 1,
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

fn pending_agency_work(work_id: WorkId, agent: EntityId, cognition: &str) -> WorkRecord {
    WorkRecord {
        id: work_id,
        timeline_id: timeline(),
        target: WorkTarget::agency_wake(agent, cognition),
        schema_revision: SchemaRevision::new(0),
        payload: json!({}),
        effective_due_world_time: WorldInstant::new(0),
        logical_schedule_order: 1,
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

fn event_with_effect(event_id: EventId, effect: WorldEffect, source_time: i64) -> ProposedEvent {
    ProposedEvent::new(
        event_id,
        EventTypeId::from("test.changed"),
        SchemaRevision::new(1),
        json!({"event": event_id.to_string(), "source_time": source_time}),
    )
    .with_effect(effect)
}

#[tokio::test]
async fn ingress_authority_rejects_stale_fence_before_no_change_commit() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let submission = IngressSubmission::new(
        "tenant-a",
        IngressEnvelope::new(
            IngressId::from("ingress-authority"),
            "key-authority",
            IngressProvenance::new("test"),
            TimelineTarget::new(world(), timeline()),
            IngressAuthorizationContext::new(json!({"policy": "test"})),
            IngressTimeMetadata::from_source("source-time"),
            ActionInvocation::new(ActionTypeId::from("test.action"), json!({})),
        ),
        "fingerprint",
        PlatformTime::new(0),
    );
    IngressStore::accept(&store, submission)
        .await
        .expect("Ingress should be accepted");
    let first = IngressStore::claim(
        &store,
        IngressId::from("ingress-authority"),
        PlatformTime::new(0),
        PlatformTime::new(10),
    )
    .await
    .expect("first claim should succeed");
    let _second = IngressStore::claim(
        &store,
        IngressId::from("ingress-authority"),
        PlatformTime::new(10),
        PlatformTime::new(20),
    )
    .await
    .expect("expired claim should be reclaimed");
    let validated = validated(&store, &registry(), Resolution::new(Vec::new(), Vec::new()));
    let result = CommitStore::commit_with_authority(
        &store,
        &validated,
        CommitAuthorityContext {
            current_work: None,
            ingress_claim: Some(first),
            provenance: None,
            session_id: None,
        },
        PlatformTime::new(10),
    )
    .await;
    assert!(matches!(result, Err(CommitError::IngressClaim { .. })));
    assert_eq!(
        store
            .snapshot(timeline())
            .expect("snapshot should exist")
            .version(),
        TimelineVersion::default()
    );
}

#[tokio::test]
async fn ingress_recovery_enumeration_returns_due_pending_and_stale_claims_only() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let first = IngressSubmission::new(
        "tenant-a",
        ingress_test_request("recovery-first", "test.action", json!({})),
        "recovery-first-fingerprint",
        PlatformTime::new(0),
    );
    let second = IngressSubmission::new(
        "tenant-a",
        ingress_test_request("recovery-second", "test.action", json!({})),
        "recovery-second-fingerprint",
        PlatformTime::new(0),
    );
    IngressStore::accept(&store, first)
        .await
        .expect("first durable acceptance should succeed");
    IngressStore::accept(&store, second)
        .await
        .expect("second durable acceptance should succeed");

    let bounded = IngressStore::list_recoverable(&store, PlatformTime::new(0), 1)
        .await
        .expect("bounded recovery enumeration should succeed");
    assert_eq!(bounded, vec![IngressId::from("recovery-first")]);

    let claim = IngressStore::claim(
        &store,
        IngressId::from("recovery-second"),
        PlatformTime::new(0),
        PlatformTime::new(10),
    )
    .await
    .expect("second record should be claimable");
    let active_only = IngressStore::list_recoverable(&store, PlatformTime::new(5), 10)
        .await
        .expect("active leases should be excluded from recovery");
    assert_eq!(active_only, vec![IngressId::from("recovery-first")]);

    let stale_claim = IngressStore::list_recoverable(&store, PlatformTime::new(10), 10)
        .await
        .expect("expired leases should be enumerated for recovery");
    assert_eq!(
        stale_claim,
        vec![
            IngressId::from("recovery-first"),
            IngressId::from("recovery-second")
        ]
    );
    assert_eq!(claim.attempt_count(), 1);
}

fn with_entity_participant(mut event: ProposedEvent, entity_id: EntityId) -> ProposedEvent {
    event.participants = serde_json::from_value(json!([{
        "entity_id": entity_id.to_string(),
        "role": "subject"
    }]))
    .expect("test Event participant should deserialize");
    event
}

fn with_relationship_ref(
    mut event: ProposedEvent,
    relationship_id: loom_core::RelationshipId,
) -> ProposedEvent {
    event.relationship_refs = serde_json::from_value(json!([{
        "relationship_id": relationship_id.to_string(),
        "role": "subject"
    }]))
    .expect("test Event Relationship reference should deserialize");
    event
}

fn relationship_participants() -> Vec<RelationshipParticipant> {
    vec![
        RelationshipParticipant::new(entity(10), "left"),
        RelationshipParticipant::new(entity(11), "right"),
    ]
}

struct TestCapability {
    manifest: CapabilityManifest,
}

const NO_CHANGE_CAPABILITY: &str = "test.no_change";
const NO_CHANGE_ACTION: &str = "test.no_change_action";
const EVENT_ACTION: &str = "test.event_action";
const SEMANTIC_REJECT_ACTION: &str = "test.semantic_reject_action";
const SCHEDULE_ACTION: &str = "test.schedule_work";
const CANCEL_ACTION: &str = "test.cancel_work";
const EMPTY_WORK_HANDLER: &str = "test.empty_work";
const TEST_WORK_HANDLER: &str = "test.handler";
const RETRY_ACTION: &str = "test.ingress_retry_action";

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
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(RETRY_ACTION), SchemaRevision::new(1)),
            FailOnceResolver {
                failed: Arc::new(AtomicBool::new(false)),
            },
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

fn prepare_runtime_lifecycle(store: &InMemoryStore, registry: &CapabilityRegistry) {
    let binding = WorldRuntimeBinding::new(
        registry
            .capabilities()
            .map(|manifest| (manifest.id.clone(), VersionReq::STAR)),
        json!({"fixture": "explicit-runtime-v0"}),
        1,
        Some("explicit-runtime-v0".to_owned()),
    );
    store
        .persist_binding(world(), binding)
        .expect("Runtime fixture binding should be persisted explicitly");

    let revision = runtime_revision_for(registry);
    store
        .confirm_revision(revision.clone())
        .expect("Runtime fixture revision should be confirmed");
    store
        .activate_revision(revision.id().clone(), None, PlatformTime::default())
        .expect("Runtime fixture revision should be active");
}

fn runtime_revision_for(registry: &CapabilityRegistry) -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("explicit-runtime-v0"),
        PlatformTime::default(),
        "test-build",
        registry.loom_version().clone(),
        registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("test:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("Runtime fixture revision should be valid")
}

struct FailOnceResolver {
    failed: Arc<AtomicBool>,
}

struct RejectResolver;

impl ActionResolver for RejectResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        _input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Ok(ResolveOutcome::Rejected(Rejection::new(
            "test.rejected",
            "the test Action was semantically refused",
        )))
    }
}

struct EventResolver;

impl ActionResolver for EventResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = input
            .get("event_id")
            .and_then(Value::as_str)
            .ok_or_else(|| ResolverError::new("event_id must be a UUID string"))?
            .parse()
            .map_err(|_| ResolverError::new("event_id must be a UUID string"))?;
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![ProposedEvent::new(
                event_id,
                EventTypeId::from("test.changed"),
                SchemaRevision::new(1),
                json!({"event": event_id.to_string()}),
            )],
            Vec::new(),
        )))
    }
}

fn ingress_test_request(id: &str, action: &str, input: Value) -> IngressEnvelope {
    IngressEnvelope::new(
        IngressId::from(id),
        format!("{id}-key"),
        IngressProvenance::new("in-memory-test"),
        TimelineTarget::new(world(), timeline()),
        IngressAuthorizationContext::new(json!({})),
        IngressTimeMetadata::none(),
        ActionInvocation::new(ActionTypeId::from(action), input),
    )
}

fn ingress_test_runtime(store: &InMemoryStore) -> (Runtime<&InMemoryStore>, ManualPlatformClock) {
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = no_change_registry();
    prepare_runtime_lifecycle(store, &registry);
    let clock = ManualPlatformClock::new(PlatformTime::new(0));
    let runtime = Runtime::new(store, registry)
        .expect("Runtime should assemble")
        .with_platform_clock(clock.clone());
    (runtime, clock)
}

#[tokio::test]
async fn runtime_requires_an_active_revision_without_mutating_binding() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let binding = WorldRuntimeBinding::new(
        [(CapabilityId::from(OWNER), VersionReq::STAR)],
        json!({"fixture": "missing-revision"}),
        1,
        Some("missing-revision".to_owned()),
    );
    store
        .persist_binding(world(), binding.clone())
        .expect("binding should be persisted explicitly");
    let runtime = Runtime::new(&store, registry()).expect("Runtime should assemble");

    let error = runtime
        .invoke(ActionRequest::new(
            TimelineTarget::new(world(), timeline()),
            ActionInvocation::new(
                ActionTypeId::from(EVENT_ACTION),
                json!({"event_id": event(901).to_string()}),
            ),
        ))
        .await
        .expect_err("missing active revision should be unavailable");
    assert_eq!(error.code, ApiErrorCode::Unavailable);
    assert_eq!(
        store.read_binding(world()).expect("binding should remain"),
        binding
    );
}

#[tokio::test]
async fn runtime_rejects_partial_binding_compatibility_without_mutating_binding() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let binding = WorldRuntimeBinding::new(
        [
            (CapabilityId::from(OWNER), VersionReq::STAR),
            (CapabilityId::from("test.missing"), VersionReq::STAR),
        ],
        json!({"fixture": "partial-binding"}),
        1,
        Some("partial-binding".to_owned()),
    );
    store
        .persist_binding(world(), binding.clone())
        .expect("binding should be persisted explicitly");
    let registry = registry();
    let revision = runtime_revision_for(&registry);
    store
        .confirm_revision(revision.clone())
        .expect("revision should be confirmed");
    store
        .activate_revision(revision.id().clone(), None, PlatformTime::default())
        .expect("revision should be active");
    let runtime = Runtime::new(&store, registry).expect("Runtime should assemble");

    let error = runtime
        .invoke(ActionRequest::new(
            TimelineTarget::new(world(), timeline()),
            ActionInvocation::new(
                ActionTypeId::from(EVENT_ACTION),
                json!({"event_id": event(902).to_string()}),
            ),
        ))
        .await
        .expect_err("partial binding compatibility should be unavailable");
    assert_eq!(error.code, ApiErrorCode::Unavailable);
    assert_eq!(
        store.read_binding(world()).expect("binding should remain"),
        binding
    );
}

#[tokio::test]
async fn runtime_registry_change_cannot_mutate_the_persisted_binding() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    prepare_runtime_lifecycle(&store, &registry);
    let binding = store
        .read_binding(world())
        .expect("binding should be readable");
    let changed_registry = CapabilityRegistry::assemble([TestCapability {
        manifest: CapabilityManifest::parse(OWNER, "0.2.0")
            .expect("changed Capability manifest should parse"),
    }])
    .expect("changed Capability registry should assemble");
    let runtime = Runtime::new(&store, changed_registry).expect("Runtime should assemble");

    let error = runtime
        .invoke(ActionRequest::new(
            TimelineTarget::new(world(), timeline()),
            ActionInvocation::new(
                ActionTypeId::from(EVENT_ACTION),
                json!({"event_id": event(903).to_string()}),
            ),
        ))
        .await
        .expect_err("changed registry should be unavailable");
    assert_eq!(error.code, ApiErrorCode::Unavailable);
    assert_eq!(
        store.read_binding(world()).expect("binding should remain"),
        binding
    );
}

impl ActionResolver for FailOnceResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        if !self.failed.swap(true, Ordering::AcqRel) {
            return Err(ResolverError::new("deterministic technical failure"));
        }
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
                json!({"retry": true}),
                WorkSchedule::Immediate,
            ))],
        )))
    }
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
        registrar.register_facet(FacetDefinition::new(
            FacetTypeId::from("test.facet"),
            SchemaRevision::new(1),
            json!({"type": "object"}),
        ))?;
        registrar.register_relationship(RelationshipDefinition::new(
            RelationshipTypeId::from("test.relationship"),
            SchemaRevision::new(1),
        ))?;
        registrar.register_event(EventDefinition::new(
            EventTypeId::from("test.changed"),
            SchemaRevision::new(1),
        ))?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(EVENT_ACTION), SchemaRevision::new(1)),
            EventResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(
                ActionTypeId::from(SEMANTIC_REJECT_ACTION),
                SchemaRevision::new(1),
            ),
            RejectResolver,
        )?;
        registrar.register_work_handler(
            WorkHandlerDefinition::new(
                WorkHandlerId::from(TEST_WORK_HANDLER),
                SchemaRevision::new(1),
            ),
            EmptyWorkHandler,
        )
    }
}

#[tokio::test]
async fn empty_public_action_returns_no_change_without_advancing_timeline_version() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = no_change_registry();
    prepare_runtime_lifecycle(&store, &registry);
    let runtime = Runtime::new(&store, registry).expect("Runtime should assemble");
    let before = store
        .snapshot(timeline())
        .expect("test Timeline should be readable")
        .version();

    let result = runtime
        .invoke(ActionRequest::new(
            TimelineTarget::new(world(), timeline()),
            ActionInvocation::new(ActionTypeId::from(NO_CHANGE_ACTION), json!({})),
        ))
        .await
        .expect("empty Action should execute");

    assert_eq!(result, ExecutionResult::NoChange);
    let after = store
        .snapshot(timeline())
        .expect("test Timeline should be readable");
    assert_eq!(after.version(), before);
    assert!(after.events.is_empty());
    let session = store.list_sessions().unwrap().pop().unwrap();
    assert!(session.event_refs().is_empty());
}

#[tokio::test]
async fn committed_event_has_atomic_bidirectional_session_provenance() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    prepare_runtime_lifecycle(&store, &registry);
    let runtime = Runtime::new(&store, registry).expect("Runtime should assemble");
    let event_id = event(900);
    let result = runtime
        .invoke(ActionRequest::new(
            TimelineTarget::new(world(), timeline()),
            ActionInvocation::new(
                ActionTypeId::from(EVENT_ACTION),
                json!({"event_id": event_id.to_string()}),
            ),
        ))
        .await
        .expect("Event Action should commit");
    assert!(matches!(result, ExecutionResult::Committed { .. }));

    let event_ref = EventRef::new(timeline(), event_id);
    let session_id = loom_runtime::ExecutionSessionStore::session_for_event(&store, event_ref)
        .await
        .expect("Event provenance should be readable")
        .expect("committed Event should have one producing Session");
    let session = store
        .read_session(session_id)
        .expect("Session should be readable");
    assert_eq!(session.event_refs(), &[event_ref]);
    assert_eq!(
        loom_runtime::ExecutionSessionStore::events_for_session(&store, session_id)
            .await
            .expect("Session Event query should be readable"),
        vec![event_ref]
    );
}

#[tokio::test]
async fn ingress_finalization_crash_recovers_without_repeating_authority_mutation() {
    let store = InMemoryStore::new();
    let (runtime, clock) = ingress_test_runtime(&store);
    runtime
        .submit_ingress(ingress_test_request(
            "ingress-finalization-crash",
            SCHEDULE_ACTION,
            json!({"work_id": work(301).to_string()}),
        ))
        .await
        .unwrap();
    store.fail_next_ingress_finalization_for_test();
    assert!(
        runtime
            .process_ingress(
                IngressId::from("ingress-finalization-crash"),
                0.into(),
                10.into(),
                0.into()
            )
            .await
            .is_err()
    );
    let after_commit = store.snapshot(timeline()).unwrap();
    assert_eq!(
        (
            after_commit.events.len(),
            after_commit.works.len(),
            after_commit.journal.len()
        ),
        (0, 1, 1)
    );
    let started = store.list_sessions().unwrap().pop().unwrap();
    assert!(
        started.status() == loom_runtime::ExecutionSessionStatus::Started
            && started.commit_provenance().is_some()
    );

    clock.set(PlatformTime::new(10));
    let completion = runtime
        .process_ingress(
            IngressId::from("ingress-finalization-crash"),
            10.into(),
            20.into(),
            10.into(),
        )
        .await
        .unwrap();
    assert!(completion.is_committed());
    let after_recovery = store.snapshot(timeline()).unwrap();
    assert_eq!(after_recovery.version(), after_commit.version());
    assert_eq!(
        (
            after_recovery.events.len(),
            after_recovery.works.len(),
            after_recovery.journal.len()
        ),
        (0, 1, 1)
    );
    assert_eq!(store.ingress_authority_commit_attempts_for_test(), 1);
    let sessions = store.list_sessions().unwrap();
    assert_eq!(sessions.len(), 1);
    assert_eq!(
        sessions[0].status(),
        loom_runtime::ExecutionSessionStatus::Committed
    );
    assert_eq!(sessions[0].ingress_completion(), Some(&completion));
}

#[tokio::test]
async fn ingress_unknown_outcome_retries_reconciliation_without_dispatching_again() {
    let store = InMemoryStore::new();
    let (runtime, _clock) = ingress_test_runtime(&store);
    runtime
        .submit_ingress(ingress_test_request(
            "ingress-unknown",
            SCHEDULE_ACTION,
            json!({"work_id": work(302).to_string()}),
        ))
        .await
        .unwrap();
    store.fail_next_ingress_commit_unknown_for_test();
    assert!(
        runtime
            .process_ingress(
                IngressId::from("ingress-unknown"),
                0.into(),
                10.into(),
                0.into()
            )
            .await
            .is_err()
    );
    let first_session = store.list_sessions().unwrap().pop().unwrap();
    assert!(first_session.commit_provenance().is_some());
    assert!(matches!(
        store
            .ingress(IngressId::from("ingress-unknown"))
            .unwrap()
            .status,
        IngressStatus::Retryable(_)
    ));
    assert!(
        runtime
            .process_ingress(
                IngressId::from("ingress-unknown"),
                0.into(),
                10.into(),
                0.into()
            )
            .await
            .is_err()
    );
    let second_session = store.list_sessions().unwrap().pop().unwrap();
    assert_eq!(second_session.id(), first_session.id());
    assert_eq!(
        second_session.commit_provenance(),
        first_session.commit_provenance()
    );
    assert_eq!(store.ingress_authority_commit_attempts_for_test(), 1);
    let snapshot = store.snapshot(timeline()).unwrap();
    assert!(snapshot.events.is_empty() && snapshot.works.is_empty() && snapshot.journal.is_empty());
}

#[tokio::test]
async fn retryable_ingress_with_only_failed_session_starts_a_fresh_attempt() {
    let store = InMemoryStore::new();
    let (runtime, _clock) = ingress_test_runtime(&store);
    runtime
        .submit_ingress(ingress_test_request(
            "ingress-failed-session",
            RETRY_ACTION,
            json!({"work_id": work(303).to_string()}),
        ))
        .await
        .unwrap();
    runtime
        .process_ingress(
            IngressId::from("ingress-failed-session"),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(0),
        )
        .await
        .expect_err("first attempt should fail technically");
    let first = store.list_sessions().unwrap().pop().unwrap();
    assert_eq!(first.status(), loom_runtime::ExecutionSessionStatus::Failed);
    assert!(matches!(
        store
            .ingress(IngressId::from("ingress-failed-session"))
            .unwrap()
            .status,
        IngressStatus::Retryable(_)
    ));

    let completion = runtime
        .process_ingress(
            IngressId::from("ingress-failed-session"),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(0),
        )
        .await
        .unwrap();
    assert!(completion.is_committed());
    let sessions = store.list_sessions().unwrap();
    assert_eq!(sessions.len(), 2);
    assert!(
        sessions
            .iter()
            .any(|session| { session.status() == loom_runtime::ExecutionSessionStatus::Failed })
    );
    let committed = sessions
        .iter()
        .find(|session| session.status() == loom_runtime::ExecutionSessionStatus::Committed)
        .expect("fresh attempt should be committed");
    assert_ne!(committed.id(), first.id());
    assert_eq!(store.snapshot(timeline()).unwrap().works.len(), 1);
    let record = store
        .ingress(IngressId::from("ingress-failed-session"))
        .unwrap();
    assert!(matches!(record.status, IngressStatus::Completed(_)));
    assert_eq!(record.attempt_count, 2);
    assert_eq!(record.claim_fence, 2);
}

#[tokio::test]
async fn work_only_actions_use_each_injected_platform_time_and_persist_schedule_and_cancel() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = no_change_registry();
    prepare_runtime_lifecycle(&store, &registry);
    let clock = loom_runtime::ManualPlatformClock::new(PlatformTime::new(7));
    let runtime = Runtime::new(&store, registry)
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
        .await
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
        .await
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
        .await
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

#[tokio::test]
async fn zero_event_work_completion_commits_runtime_state_atomically() {
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
    let registry = no_change_registry();
    prepare_runtime_lifecycle(&store, &registry);
    let runtime = Runtime::new(&store, registry).expect("Runtime should assemble");

    let result = runtime
        .execute_work(
            TimelineTarget::new(world(), timeline()),
            work(40),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(2),
        )
        .await
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

fn agency_executor(
    steps: impl IntoIterator<Item = DeterministicCognitiveStep>,
) -> DeterministicCognitiveExecutor {
    DeterministicCognitiveExecutor::new(steps)
}

struct SharedAgencyExecutor(Arc<DeterministicCognitiveExecutor>);

impl CognitiveExecutor for SharedAgencyExecutor {
    fn metadata(&self) -> CognitiveMetadata {
        self.0.metadata()
    }

    fn execute<'a>(&'a self, request: &'a CognitiveRequest) -> CognitiveFuture<'a> {
        self.0.execute(request)
    }
}

#[tokio::test]
async fn agency_wake_resample_rejects_stale_decision_and_records_discarded_cost() {
    let scripted = Arc::new(agency_executor([
        DeterministicCognitiveStep::act(ActionInvocation::new(
            ActionTypeId::from(EVENT_ACTION),
            json!({"event_id": event(4301).to_string()}),
        )),
        DeterministicCognitiveStep::act(ActionInvocation::new(
            ActionTypeId::from(EVENT_ACTION),
            json!({"event_id": event(4302).to_string()}),
        )),
    ]));
    run_agency_wake_cas_conflict(ExecutionPolicy::default(), scripted, event(4302), 2, false).await;
}

#[tokio::test]
async fn agency_wake_reuse_revalidates_fresh_context_and_records_reused_cost() {
    let scripted = Arc::new(agency_executor([DeterministicCognitiveStep::act(
        ActionInvocation::new(
            ActionTypeId::from(EVENT_ACTION),
            json!({"event_id": event(4303).to_string()}),
        ),
    )]));
    run_agency_wake_cas_conflict(
        ExecutionPolicy::default().with_decision_reuse(DecisionReusePolicy::ReuseDeterministic),
        scripted,
        event(4303),
        1,
        true,
    )
    .await;
}

#[expect(
    clippy::too_many_lines,
    reason = "the in-memory Agency Wake CAS helper keeps both policy branches and provenance assertions together"
)]
async fn run_agency_wake_cas_conflict(
    policy: ExecutionPolicy,
    scripted: Arc<DeterministicCognitiveExecutor>,
    expected_event: EventId,
    expected_executor_calls: usize,
    reused: bool,
) {
    let store = Arc::new(InMemoryStore::new());
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    prepare_runtime_lifecycle(&store, &registry);
    store
        .seed_entity(
            timeline(),
            Entity {
                id: entity(10),
                world_id: world(),
            },
        )
        .expect("Agency Agent should exist");
    store
        .seed_work(pending_agency_work(
            work(430),
            entity(10),
            "deterministic.fake",
        ))
        .expect("Agency Wake should be seeded");
    let mut conflict_work =
        pending_work_with_handler(work(431), WorkHandlerId::from(EMPTY_WORK_HANDLER));
    conflict_work.logical_schedule_order = 2;
    store
        .seed_work(conflict_work)
        .expect("conflict Work should be seeded");
    let runtime = Runtime::new(store.as_ref(), registry)
        .expect("Runtime should assemble")
        .with_cognitive_executor(SharedAgencyExecutor(Arc::clone(&scripted)))
        .with_cognitive_policy(policy);

    store.inject_scheduler_conflict_once_for_test(work(431));
    let first_result = runtime
        .execute_work(
            TimelineTarget::new(world(), timeline()),
            work(430),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(2),
        )
        .await;
    let result = if reused {
        first_result.expect("Agency Wake should reuse after the injected CAS conflict")
    } else {
        assert!(matches!(
            first_result,
            Err(loom_api::ApiError {
                code: loom_api::ApiErrorCode::Conflict,
                ..
            })
        ));
        let after_conflict = store
            .snapshot(timeline())
            .expect("post-conflict snapshot should exist");
        assert!(after_conflict.events.is_empty());
        assert_eq!(
            after_conflict
                .works
                .iter()
                .find(|record| record.id == work(430))
                .expect("pending Agency Wake should remain readable")
                .attempt_count,
            1
        );
        runtime
            .execute_work(
                TimelineTarget::new(world(), timeline()),
                work(430),
                PlatformTime::new(2),
                PlatformTime::new(12),
                PlatformTime::new(4),
            )
            .await
            .expect("resampled Agency Wake should commit on the retry")
    };
    assert!(matches!(
        result,
        ExecutionResult::Committed { ref event_ids, .. } if event_ids == &[expected_event]
    ));
    assert_eq!(scripted.calls(), expected_executor_calls);

    let snapshot = store
        .snapshot(timeline())
        .expect("post-conflict snapshot should exist");
    assert_eq!(snapshot.events.len(), 1, "one Action mutation may win");
    assert_eq!(snapshot.events[0].id, expected_event);
    assert_eq!(
        snapshot
            .works
            .iter()
            .find(|record| record.id == work(430))
            .expect("Agency Wake should remain readable")
            .status,
        WorkStatus::Completed
    );
    assert_eq!(
        snapshot
            .works
            .iter()
            .find(|record| record.id == work(431))
            .expect("conflict Work should remain readable")
            .status,
        WorkStatus::Cancelled
    );

    let sessions = store.list_sessions().expect("Sessions should be readable");
    assert_eq!(
        sessions.len(),
        2,
        "CAS recovery creates old and fresh Sessions"
    );
    let failed = sessions
        .iter()
        .find(|session| session.status() == loom_runtime::ExecutionSessionStatus::Failed)
        .expect("stale cognition Session should be failed");
    let committed = sessions
        .iter()
        .find(|session| session.status() == loom_runtime::ExecutionSessionStatus::Committed)
        .expect("fresh cognition Session should commit");
    let discarded = failed.cognitive_evidence();
    let recovered = committed.cognitive_evidence();
    assert_eq!(discarded.discarded_count(), 1);
    assert_eq!(discarded.fresh_count(), 0);
    assert_eq!(discarded.reused_count(), 0);
    assert_eq!(discarded.context_bytes(), 0);
    assert_eq!(recovered.discarded_count(), 0);
    assert_eq!(recovered.context_entries(), 0);
    if reused {
        assert_eq!(recovered.reused_count(), 1);
        assert_eq!(recovered.fresh_count(), 0);
        assert_ne!(
            discarded.observations()[0].version,
            recovered.observations()[0].version,
            "reuse must record a fresh pinned Timeline coordinate"
        );
    } else {
        assert_eq!(recovered.reused_count(), 0);
        assert_eq!(recovered.fresh_count(), 1);
    }
    assert_eq!(
        recovered.observations()[0].outcome,
        loom_runtime::CognitiveOutcome::Act
    );
    assert_eq!(
        recovered.observations()[0].disposition,
        if reused {
            CognitiveDisposition::Reused
        } else {
            CognitiveDisposition::Fresh
        }
    );
}

#[tokio::test]
async fn admin_agency_wake_schedule_and_cancel_use_logical_work_authority() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    prepare_runtime_lifecycle(&store, &registry);
    store
        .seed_entity(
            timeline(),
            Entity {
                id: entity(10),
                world_id: world(),
            },
        )
        .expect("Agency Agent should exist");
    let runtime = Runtime::new(&store, registry).expect("Runtime should assemble");
    let target = TimelineTarget::new(world(), timeline());
    let initial = store
        .snapshot(timeline())
        .expect("initial snapshot should exist");

    let scheduled = AdminService::schedule_agency_wake(
        &runtime,
        AdminScheduleAgencyWakeRequest {
            target,
            expected_version: initial.version(),
            work_id: work(410),
            agent: entity(10),
            cognition: "deterministic.fake".to_owned(),
            payload: json!({"policy": "default"}),
            schedule: WorkSchedule::Immediate,
        },
    )
    .await
    .expect("explicit Wake schedule should commit");
    let scheduled_snapshot = store
        .snapshot(timeline())
        .expect("scheduled snapshot should exist");
    assert_eq!(scheduled.version, scheduled_snapshot.version());
    assert_eq!(scheduled_snapshot.works[0].id, work(410));
    assert_eq!(scheduled_snapshot.works[0].status, WorkStatus::Pending);

    let cancelled = AdminService::terminalize_work(
        &runtime,
        AdminTerminalizeWorkRequest {
            target,
            work_id: work(410),
            expected_version: scheduled.version,
            terminal_state: AdminTerminalWorkState::Cancelled,
        },
    )
    .await
    .expect("explicit Wake cancellation should commit");
    let cancelled_snapshot = store
        .snapshot(timeline())
        .expect("cancelled snapshot should exist");
    assert_eq!(cancelled.version, cancelled_snapshot.version());
    assert_eq!(cancelled_snapshot.works[0].status, WorkStatus::Cancelled);
}

#[tokio::test]
async fn agency_no_action_completes_wake_without_world_event() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    prepare_runtime_lifecycle(&store, &registry);
    store
        .seed_entity(
            timeline(),
            Entity {
                id: entity(10),
                world_id: world(),
            },
        )
        .expect("Agency Agent should exist");
    store
        .seed_work(pending_agency_work(
            work(400),
            entity(10),
            "deterministic.fake",
        ))
        .expect("Agency Wake should be seeded");
    let runtime = Runtime::new(&store, registry)
        .expect("Runtime should assemble")
        .with_cognitive_executor(agency_executor([DeterministicCognitiveStep::no_action()]));

    let result = runtime
        .execute_work(
            TimelineTarget::new(world(), timeline()),
            work(400),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(2),
        )
        .await
        .expect("NoAction Wake should complete");
    assert!(matches!(
        result,
        ExecutionResult::Committed { ref event_ids, .. } if event_ids.is_empty()
    ));
    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert!(snapshot.events.is_empty());
    assert_eq!(snapshot.chronology_budget().consumed, 1);
    assert_eq!(snapshot.works[0].status, WorkStatus::Completed);
    let session = store.list_sessions().unwrap().pop().unwrap();
    assert_eq!(
        session.status(),
        loom_runtime::ExecutionSessionStatus::Committed
    );
    assert_eq!(session.cognitive_evidence().len(), 1);
}

#[tokio::test]
async fn agency_act_reuses_action_authority_and_commits_atomically() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    prepare_runtime_lifecycle(&store, &registry);
    store
        .seed_entity(
            timeline(),
            Entity {
                id: entity(10),
                world_id: world(),
            },
        )
        .expect("Agency Agent should exist");
    let event_id = event(401);
    store
        .seed_work(pending_agency_work(
            work(401),
            entity(10),
            "deterministic.fake",
        ))
        .expect("Agency Wake should be seeded");
    let runtime = Runtime::new(&store, registry)
        .expect("Runtime should assemble")
        .with_cognitive_executor(agency_executor([DeterministicCognitiveStep::act(
            ActionInvocation::new(
                ActionTypeId::from(EVENT_ACTION),
                json!({"event_id": event_id.to_string()}),
            ),
        )]));

    let result = runtime
        .execute_work(
            TimelineTarget::new(world(), timeline()),
            work(401),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(2),
        )
        .await
        .expect("Act Wake should complete");
    assert!(matches!(
        result,
        ExecutionResult::Committed { ref event_ids, .. } if event_ids == &[event_id]
    ));
    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(snapshot.events.len(), 1);
    assert_eq!(snapshot.events[0].id, event_id);
    assert_eq!(snapshot.works[0].status, WorkStatus::Completed);
    assert_eq!(snapshot.chronology_budget().consumed, 1);
}

#[tokio::test]
async fn agency_semantic_rejection_completes_wake_without_fake_event() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    prepare_runtime_lifecycle(&store, &registry);
    store
        .seed_entity(
            timeline(),
            Entity {
                id: entity(10),
                world_id: world(),
            },
        )
        .expect("Agency Agent should exist");
    store
        .seed_work(pending_agency_work(
            work(402),
            entity(10),
            "deterministic.fake",
        ))
        .expect("Agency Wake should be seeded");
    let runtime = Runtime::new(&store, registry)
        .expect("Runtime should assemble")
        .with_cognitive_executor(agency_executor([DeterministicCognitiveStep::act(
            ActionInvocation::new(ActionTypeId::from(SEMANTIC_REJECT_ACTION), json!({})),
        )]));

    let result = runtime
        .execute_work(
            TimelineTarget::new(world(), timeline()),
            work(402),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(2),
        )
        .await
        .expect("semantic rejection should determine the Wake");
    assert!(result.is_rejected());
    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert!(snapshot.events.is_empty());
    assert_eq!(snapshot.works[0].status, WorkStatus::Completed);
    assert_eq!(snapshot.chronology_budget().consumed, 1);
}

#[tokio::test]
async fn agency_technical_failure_retries_pending_wake_without_commit() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    prepare_runtime_lifecycle(&store, &registry);
    store
        .seed_entity(
            timeline(),
            Entity {
                id: entity(10),
                world_id: world(),
            },
        )
        .expect("Agency Agent should exist");
    store
        .seed_work(pending_agency_work(work(403), entity(10), "unconfigured"))
        .expect("Agency Wake should be seeded");
    let runtime = Runtime::new(&store, registry).expect("Runtime should assemble");

    assert!(
        runtime
            .execute_work(
                TimelineTarget::new(world(), timeline()),
                work(403),
                PlatformTime::new(0),
                PlatformTime::new(10),
                PlatformTime::new(2),
            )
            .await
            .is_err()
    );
    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert!(snapshot.events.is_empty());
    assert_eq!(snapshot.version(), TimelineVersion::default());
    assert_eq!(snapshot.works[0].status, WorkStatus::Pending);
    assert!(snapshot.works[0].lease.is_none());
    assert_eq!(snapshot.works[0].attempt_count, 1);
    assert_eq!(snapshot.chronology_budget().consumed, 0);
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the M10 final gate keeps the complete deterministic Agency lifecycle in one scenario"
)]
async fn m10_agency_gate_covers_visibility_order_restart_fork_revision_and_provenance() {
    let store = InMemoryStore::new();
    let setup_runtime = Runtime::new(&store, registry()).expect("Agency Runtime should assemble");
    let revision_one = RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("r1"),
        PlatformTime::new(1),
        "loom-core-build-1",
        Version::new(0, 1, 0),
        [RuntimeRevisionCapability::new(
            OWNER,
            "test-build-1",
            Version::new(0, 1, 0),
            VersionReq::STAR,
        )],
    )
    .expect("Agency Runtime Revision R1 should be valid")
    .with_execution_policy_id("execution-v1")
    .with_provider_policy_id("provider-v1");
    setup_runtime
        .register_runtime_revision(revision_one.clone())
        .await
        .expect("Agency Runtime Revision R1 should publish");
    setup_runtime
        .activate_runtime_revision(RuntimeRevisionId::from("r1"), None, PlatformTime::new(1))
        .await
        .expect("Agency Runtime Revision R1 should activate");

    let target = setup_runtime
        .create_world_from_template(CreateWorldFromTemplateRequest::new(
            WorldTemplateDescriptor::new("agency.gate", 1, WorldInstant::new(0))
                .requires_capability(OWNER, "^0.1.0")
                .with_bootstrap_action(ActionInvocation::new(
                    ActionTypeId::from(EVENT_ACTION),
                    json!({"event_id": event(4400).to_string()}),
                )),
        ))
        .await
        .expect("Template-backed Agency World should be created")
        .target;
    let world_id = target.world_id;
    let timeline_id = target.timeline_id;
    let agent_id = entity(4401);
    let visible_facet = FacetTypeId::from("test.facet");
    let hidden_facet = FacetTypeId::from("hidden.authoritative");
    store
        .seed_entity(
            timeline_id,
            Entity {
                id: agent_id,
                world_id,
            },
        )
        .expect("Agency Agent should be seeded in the Template World");
    store
        .seed_facet(
            timeline_id,
            FacetOwner::entity(agent_id),
            visible_facet.clone(),
            SchemaRevision::new(1),
            json!({"value": 7}),
        )
        .expect("Agent-visible Facet should be seeded");
    store
        .seed_facet(
            timeline_id,
            FacetOwner::entity(agent_id),
            hidden_facet.clone(),
            SchemaRevision::new(1),
            json!({"secret": "authoritative-only"}),
        )
        .expect("hidden authoritative Facet should be seeded");
    assert_eq!(
        store
            .read_binding(world_id)
            .expect("Template Binding should be readable")
            .template_provenance(),
        Some("agency.gate@1")
    );

    let wake_ids = [
        work(4402),
        work(4403),
        work(4404),
        work(4405),
        work(4406),
        work(4407),
    ];
    let mut expected_version = store
        .snapshot(timeline_id)
        .expect("Template Timeline should be readable")
        .version();
    for (work_id, cognition) in wake_ids.into_iter().zip([
        "deterministic.fake",
        "deterministic.fake",
        "deterministic.fake",
        "deterministic.fake",
        "deterministic.fake",
        "missing.cognitive",
    ]) {
        expected_version = AdminService::schedule_agency_wake(
            &setup_runtime,
            AdminScheduleAgencyWakeRequest {
                target,
                expected_version,
                work_id,
                agent: agent_id,
                cognition: cognition.to_owned(),
                payload: json!({"wake": work_id.to_string()}),
                schedule: WorkSchedule::Immediate,
            },
        )
        .await
        .expect("same-instant Agency Wake should schedule through Work authority")
        .version;
    }

    let parent_before_claims = store
        .snapshot(timeline_id)
        .expect("parent Agency Timeline should be readable before claims");
    assert!(
        parent_before_claims
            .works
            .iter()
            .all(|work| work.effective_due_world_time == WorldInstant::new(0))
    );
    assert_eq!(
        parent_before_claims
            .works
            .iter()
            .map(|work| work.logical_schedule_order)
            .collect::<Vec<_>>(),
        (1..=6).collect::<Vec<_>>()
    );

    let fork = setup_runtime
        .fork(ForkTimelineRequest::new(target))
        .await
        .expect("fork with Pending Agency Wakes should survive");
    let fork_snapshot = store
        .snapshot(fork.target.timeline_id)
        .expect("forked Agency Timeline should be readable");
    assert_eq!(fork_snapshot.works.len(), 6);
    assert!(
        fork_snapshot
            .works
            .iter()
            .all(|work| work.status == WorkStatus::Pending)
    );
    assert!(fork_snapshot.works.iter().all(|forked| {
        parent_before_claims.works.iter().any(|parent| {
            forked.id != parent.id
                && forked.target == parent.target
                && forked.effective_due_world_time == parent.effective_due_world_time
                && forked.logical_schedule_order == parent.logical_schedule_order
        })
    }));

    let technical_runtime = Runtime::new(&store, registry())
        .expect("technical-failure Runtime should assemble")
        .with_cognitive_executor(agency_executor([
            DeterministicCognitiveStep::technical_failure(CognitiveError::failed(
                "deterministic provider failure",
            )),
        ]));
    assert!(
        technical_runtime
            .execute_work(
                target,
                work(4402),
                PlatformTime::new(0),
                PlatformTime::new(10),
                PlatformTime::new(2),
            )
            .await
            .is_err()
    );
    let after_technical_failure = store
        .snapshot(timeline_id)
        .expect("technical failure snapshot should be readable");
    let failed_work = after_technical_failure
        .works
        .iter()
        .find(|record| record.id == work(4402))
        .expect("technical Agency Wake should remain readable");
    assert_eq!(failed_work.status, WorkStatus::Pending);
    assert_eq!(failed_work.attempt_count, 1);
    assert!(failed_work.lease.is_none());
    assert_eq!(
        after_technical_failure.chronology_budget().consumed,
        parent_before_claims.chronology_budget().consumed
    );

    let failed_session = store
        .list_sessions()
        .expect("technical Agency Session should be readable")
        .into_iter()
        .find(|session| {
            session.root().target_work == Some(work(4402))
                && session.status() == loom_runtime::ExecutionSessionStatus::Failed
        })
        .expect("technical Agency Session should be persisted");
    assert_eq!(
        failed_session.assembly().runtime_revision().revision().id(),
        &RuntimeRevisionId::from("r1")
    );

    let direct_executor = Arc::new(agency_executor([DeterministicCognitiveStep::no_action()]));
    let direct_runtime = Runtime::new(&store, registry())
        .expect("visibility Runtime should assemble")
        .with_cognitive_executor(SharedAgencyExecutor(Arc::clone(&direct_executor)));
    let pinned = direct_runtime
        .open_pinned_read(failed_session.assembly())
        .await
        .expect("failed Agency Session coordinate should remain readable");
    let request = AgentContextRequest::new(
        loom_agency::AgentRef::new(agent_id),
        timeline_id,
        failed_session.assembly().expected_version(),
        failed_session.assembly().world_time(),
        failed_session
            .assembly()
            .cognitive()
            .policy()
            .context_budget,
    );
    let visible_plan = AgentContextPlan::new().with_item(AgentContextItem::facet(
        "agent.visible",
        ContextSource::Observation,
        FacetOwner::entity(agent_id),
        visible_facet,
    ));
    let mut builder = AgentWorldViewBuilder::new(&store, PinnedReadPolicy::default());
    let visible_view = builder
        .build(
            &pinned,
            request,
            &visible_plan,
            &registry(),
            failed_session.assembly(),
        )
        .await
        .expect("Agent-visible data should cross the bounded context builder");
    assert_eq!(visible_view.context.entries.len(), 1);
    assert_eq!(visible_view.context.entries[0].value, json!({"value": 7}));
    let hidden_error = builder
        .build(
            &pinned,
            request,
            &AgentContextPlan::new().with_item(AgentContextItem::facet(
                "agent.hidden",
                ContextSource::Knowledge,
                FacetOwner::entity(agent_id),
                hidden_facet,
            )),
            &registry(),
            failed_session.assembly(),
        )
        .await
        .expect_err("hidden authoritative data must be denied before cognition");
    assert!(matches!(
        hidden_error,
        loom_runtime::AgentWorldViewError::VisibilityDenied { .. }
    ));
    let mut direct_evidence =
        ExecutionEvidence::new(failed_session.assembly().entropy_source_id().clone());
    direct_runtime
        .execute_cognitive(
            failed_session.assembly(),
            &pinned,
            visible_view,
            &mut direct_evidence,
        )
        .await
        .expect("cognition should receive only the visible Agent view");
    let request = &direct_executor.requests()[0];
    assert_eq!(request.view.context.entries.len(), 1);
    assert!(
        request
            .view
            .context
            .entries
            .iter()
            .all(|entry| entry.key != "agent.hidden")
    );
    assert_eq!(direct_evidence.cognitive_evidence.len(), 1);
    drop(direct_runtime);
    drop(technical_runtime);

    let restart_runtime = Runtime::new(&store, registry())
        .expect("restarted Runtime should assemble")
        .with_cognitive_executor(agency_executor([DeterministicCognitiveStep::no_action()]));
    restart_runtime
        .execute_work(
            target,
            work(4402),
            PlatformTime::new(2),
            PlatformTime::new(12),
            PlatformTime::new(4),
        )
        .await
        .expect("restarted Runtime should complete the retained Wake");
    drop(restart_runtime);

    let revision_two = RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("r2"),
        PlatformTime::new(3),
        "loom-core-build-2",
        Version::new(0, 1, 0),
        [RuntimeRevisionCapability::new(
            OWNER,
            "test-build-2",
            Version::new(0, 1, 0),
            VersionReq::STAR,
        )],
    )
    .expect("compatible Agency Runtime Revision R2 should be valid")
    .with_execution_policy_id("execution-v2")
    .with_provider_policy_id("provider-v2");
    let revision_runtime = Runtime::new(&store, registry())
        .expect("R2 Runtime should assemble")
        .with_cognitive_executor(DeterministicCognitiveExecutor::with_metadata(
            CognitiveMetadata::new(ExecutorMetadata::new("deterministic.fake", "2")),
            [
                DeterministicCognitiveStep::act(ActionInvocation::new(
                    ActionTypeId::from(EVENT_ACTION),
                    json!({"event_id": event(4408).to_string()}),
                )),
                DeterministicCognitiveStep::act(ActionInvocation::new(
                    ActionTypeId::from(SEMANTIC_REJECT_ACTION),
                    json!({}),
                )),
                DeterministicCognitiveStep::no_action().with_delay_polls(2),
                DeterministicCognitiveStep::no_action(),
            ],
        ));
    revision_runtime
        .register_runtime_revision(revision_two.clone())
        .await
        .expect("compatible Agency Runtime Revision R2 should publish");
    let r1_generation = revision_runtime
        .active_runtime_revision()
        .await
        .expect("active Agency Runtime Revision should be readable")
        .expect("R1 should remain active before the switch")
        .generation();
    revision_runtime
        .activate_runtime_revision(
            RuntimeRevisionId::from("r2"),
            Some(r1_generation),
            PlatformTime::new(4),
        )
        .await
        .expect("compatible Agency Runtime Revision R2 should activate");
    revision_runtime
        .execute_work(
            target,
            work(4403),
            PlatformTime::new(4),
            PlatformTime::new(14),
            PlatformTime::new(6),
        )
        .await
        .expect("R2 Agency Act should use normal Action authority");
    let rejection = revision_runtime
        .execute_work(
            target,
            work(4404),
            PlatformTime::new(5),
            PlatformTime::new(15),
            PlatformTime::new(7),
        )
        .await
        .expect("semantic rejection should complete its Wake");
    assert!(rejection.is_rejected());

    store.inject_scheduler_conflict_once_for_test(work(4406));
    assert!(matches!(
        revision_runtime
            .execute_work(
                target,
                work(4405),
                PlatformTime::new(6),
                PlatformTime::new(16),
                PlatformTime::new(8),
            )
            .await,
        Err(loom_api::ApiError {
            code: ApiErrorCode::Conflict,
            ..
        })
    ));
    let after_cas_loss = store
        .snapshot(timeline_id)
        .expect("CAS-loss snapshot should be readable");
    assert_eq!(
        after_cas_loss
            .works
            .iter()
            .find(|record| record.id == work(4405))
            .expect("delayed Agency Wake should remain pending")
            .status,
        WorkStatus::Pending
    );
    assert_eq!(
        after_cas_loss
            .works
            .iter()
            .find(|record| record.id == work(4405))
            .expect("delayed Agency Wake should remain readable")
            .attempt_count,
        1
    );
    assert_eq!(
        after_cas_loss
            .works
            .iter()
            .find(|record| record.id == work(4406))
            .expect("CAS conflict Work should remain readable")
            .status,
        WorkStatus::Cancelled
    );
    revision_runtime
        .execute_work(
            target,
            work(4405),
            PlatformTime::new(8),
            PlatformTime::new(18),
            PlatformTime::new(10),
        )
        .await
        .expect("resampled delayed Agency Wake should complete once");

    assert!(
        revision_runtime
            .execute_work(
                target,
                work(4407),
                PlatformTime::new(10),
                PlatformTime::new(20),
                PlatformTime::new(12),
            )
            .await
            .is_err()
    );
    let final_snapshot = store
        .snapshot(timeline_id)
        .expect("final Agency Timeline should be readable");
    assert_eq!(final_snapshot.events.len(), 2);
    assert!(
        final_snapshot
            .events
            .iter()
            .all(|event| event.occurred_at == WorldInstant::new(0))
    );
    assert_eq!(
        final_snapshot
            .works
            .iter()
            .find(|record| record.id == work(4407))
            .expect("missing cognitive Wake should remain readable")
            .attempt_count,
        0,
        "missing cognitive software must not consume an attempt"
    );
    assert!(
        final_snapshot
            .works
            .iter()
            .filter(|work| work.logical_schedule_order <= 5)
            .all(|work| !work.is_pending())
    );
    assert_eq!(
        store
            .snapshot(fork.target.timeline_id)
            .expect("fork should remain readable after parent execution")
            .works
            .iter()
            .filter(|work| work.is_pending())
            .count(),
        6,
        "parent claims must not mutate forked Pending Wakes"
    );

    let sessions = store
        .list_sessions()
        .expect("Agency Session provenance should survive restart");
    let w2_session = sessions
        .iter()
        .find(|session| {
            session.root().target_work == Some(work(4403))
                && session.status() == loom_runtime::ExecutionSessionStatus::Committed
        })
        .expect("R2 Act Session should be present");
    assert_eq!(
        w2_session.assembly().runtime_revision().revision().id(),
        &RuntimeRevisionId::from("r2")
    );
    let cognitive = &w2_session.cognitive_evidence().observations()[0];
    assert_eq!(cognitive.metadata.executor.id, "deterministic.fake");
    assert_eq!(cognitive.metadata.executor.revision, "2");
    assert_eq!(cognitive.policy.policy_id, "execution-v2");
    assert_eq!(cognitive.timeline_id, timeline_id);
    assert_eq!(cognitive.context_usage.entries, 0);
    assert!(cognitive.context_read_set.is_empty());
    let event_session =
        ExecutionSessionStore::session_for_event(&store, EventRef::new(timeline_id, event(4408)))
            .await
            .expect("Agency Event should resolve to its Session");
    assert_eq!(event_session, Some(w2_session.id()));
    assert_eq!(
        ExecutionSessionStore::events_for_session(&store, w2_session.id())
            .await
            .expect("Session Event refs should survive restart"),
        vec![EventRef::new(timeline_id, event(4408))]
    );
    let w3_session = sessions
        .iter()
        .find(|session| {
            session.root().target_work == Some(work(4404))
                && session.status() == loom_runtime::ExecutionSessionStatus::Rejected
        })
        .expect("semantic rejection Session should be present");
    assert!(w3_session.event_refs().is_empty());
    let w4_sessions = sessions
        .iter()
        .filter(|session| session.root().target_work == Some(work(4405)))
        .collect::<Vec<_>>();
    assert_eq!(w4_sessions.len(), 2);
    assert!(w4_sessions.iter().any(|session| {
        session.status() == loom_runtime::ExecutionSessionStatus::Failed
            && session.cognitive_evidence().discarded_count() == 1
    }));
    assert!(w4_sessions.iter().any(|session| {
        session.status() == loom_runtime::ExecutionSessionStatus::Committed
            && session.cognitive_evidence().fresh_count() == 1
    }));
}

#[tokio::test]
async fn chronology_budget_is_atomic_and_due_work_blocks_world_time() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(200)))
        .expect("first Work fixture should be seeded");
    let mut second_work = pending_work(work(201));
    second_work.logical_schedule_order = 2;
    store
        .seed_work(second_work)
        .expect("second Work fixture should be seeded");

    let first_claim = store
        .claim(
            timeline(),
            work(200),
            PlatformTime::new(0),
            PlatformTime::new(10),
        )
        .expect("logical head should be claimable");
    let first_token = validated(&store, &registry(), Resolution::default());
    SchedulerCommitStore::commit_scheduler_work(
        &store,
        &first_token,
        &first_claim,
        PlatformTime::new(1),
        1,
    )
    .await
    .expect("first completion should consume the only budget unit");

    let second_claim = store
        .claim(
            timeline(),
            work(201),
            PlatformTime::new(0),
            PlatformTime::new(10),
        )
        .expect("later Work should become the logical head");
    let second_token = validated(&store, &registry(), Resolution::default());
    let before_exhausted_commit = store.snapshot(timeline()).expect("snapshot should exist");
    let exhausted = SchedulerCommitStore::commit_scheduler_work(
        &store,
        &second_token,
        &second_claim,
        PlatformTime::new(1),
        1,
    )
    .await
    .expect_err("the second same-instant completion must be bounded");
    assert!(matches!(
        exhausted,
        CommitError::ChronologyBudgetExceeded(ChronologyBudgetExceeded {
            timeline_id,
            world_time,
            limit: 1,
            consumed: 1,
        }) if timeline_id == timeline() && world_time == WorldInstant::new(0)
    ));
    let after_exhausted_commit = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(
        after_exhausted_commit.version(),
        before_exhausted_commit.version()
    );
    assert_eq!(after_exhausted_commit.chronology_budget().consumed, 1);
    assert_eq!(after_exhausted_commit.journal.len(), 1);

    let transition = AdvanceWorldTime::new(
        timeline(),
        after_exhausted_commit.version(),
        after_exhausted_commit.world_time(),
        WorldInstant::new(1),
    )
    .expect("transition should be structurally monotonic");
    assert!(matches!(
        store.advance_world_time(transition),
        Err(WorldTimeError::DueWorkPending { work_id }) if work_id == work(201)
    ));
}

#[tokio::test]
async fn timeline_driver_executes_head_then_surfaces_exhaustion() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    prepare_runtime_lifecycle(&store, &registry);
    store
        .seed_work(pending_work(work(210)))
        .expect("first Work fixture should be seeded");
    let mut second_work = pending_work(work(211));
    second_work.logical_schedule_order = 2;
    store
        .seed_work(second_work)
        .expect("second Work fixture should be seeded");
    let runtime = Runtime::new(&store, registry)
        .expect("Runtime should assemble")
        .with_chronology_budget_limit(1);
    let target = TimelineTarget::new(world(), timeline());

    let executed = runtime
        .drive_timeline(
            target,
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(0),
        )
        .await
        .expect("claimable logical head should execute");
    assert!(matches!(
        executed,
        TimelineDriverResult::Executed { work_id, result }
            if work_id == work(210) && result.is_committed()
    ));

    let exhausted = runtime
        .drive_timeline(
            target,
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(0),
        )
        .await
        .expect("budget exhaustion is an observable driver state");
    assert!(matches!(
        exhausted,
        TimelineDriverResult::ChronologyBudgetExceeded(ChronologyBudgetExceeded {
            timeline_id,
            world_time,
            limit: 1,
            consumed: 1,
        }) if timeline_id == timeline() && world_time == WorldInstant::new(0)
    ));
    assert_eq!(
        store
            .snapshot(timeline())
            .expect("snapshot should exist")
            .world_time(),
        WorldInstant::new(0)
    );
}

#[tokio::test]
async fn timeline_driver_advances_only_to_next_future_due_work() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let mut future = pending_work(work(220));
    future.effective_due_world_time = WorldInstant::new(7);
    store
        .seed_work(future)
        .expect("future Work fixture should be seeded");
    let runtime = Runtime::new(&store, registry()).expect("Runtime should assemble");

    let result = runtime
        .drive_timeline(
            TimelineTarget::new(world(), timeline()),
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(0),
        )
        .await
        .expect("quiescent Timeline should advance through the authority");
    assert!(matches!(
        result,
        TimelineDriverResult::Advanced { transition, .. }
            if transition.from == WorldInstant::new(0)
                && transition.to == WorldInstant::new(7)
    ));
    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(snapshot.world_time(), WorldInstant::new(7));
    assert_eq!(snapshot.chronology_budget().consumed, 0);
    assert!(snapshot.events.is_empty());
}

#[tokio::test]
async fn commit_assigns_contiguous_event_sequences_and_advances_once() {
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
    assert_eq!(snapshot.world_time(), WorldInstant::new(0));
    assert!(
        snapshot
            .events
            .iter()
            .all(|event| event.occurred_at == WorldInstant::new(0))
    );
    assert!(snapshot.world_view().entity(entity(20)).is_some());
}

#[test]
fn explicit_world_time_transition_is_monotonic_and_stale_cas_loses() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let initial = store.snapshot(timeline()).expect("snapshot should exist");
    let first = AdvanceWorldTime::new(
        timeline(),
        initial.version(),
        initial.world_time(),
        WorldInstant::new(10),
    )
    .expect("forward transition should validate");
    let next = store
        .advance_world_time(first)
        .expect("matching World-Time CAS should succeed");
    assert_eq!(next.head_event_seq, EventSeq::new(0));
    assert_eq!(next.state_revision.value(), 1);
    assert_eq!(
        store.snapshot(timeline()).expect("snapshot").world_time(),
        WorldInstant::new(10)
    );

    let stale = AdvanceWorldTime::new(
        timeline(),
        initial.version(),
        initial.world_time(),
        WorldInstant::new(20),
    )
    .expect("stale forward transition is structurally monotonic");
    assert!(matches!(
        store.advance_world_time(stale),
        Err(WorldTimeError::TimelineConflict { .. })
    ));
    assert!(matches!(
        AdvanceWorldTime::new(
            timeline(),
            next,
            WorldInstant::new(10),
            WorldInstant::new(10),
        ),
        Err(WorldTimeError::NonMonotonic { .. })
    ));
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the journal fixture covers each logical and operational boundary in one scenario"
)]
async fn logical_journal_tracks_semantic_commits_and_excludes_operational_noise() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();

    let initial = store.snapshot(timeline()).expect("snapshot should exist");
    let event_token = validated(
        &store,
        &registry,
        Resolution::new(
            vec![ProposedEvent::new(
                event(80),
                EventTypeId::from("test.changed"),
                SchemaRevision::new(1),
                json!({"kind": "event-only"}),
            )],
            Vec::new(),
        ),
    );
    store
        .commit(&event_token, None, PlatformTime::new(1))
        .expect("Event-only commit should succeed");

    let after_event = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after_event.journal.len(), 1);
    assert_eq!(after_event.journal[0].before_version, initial.version());
    assert_eq!(after_event.journal[0].after_version, after_event.version());
    assert_eq!(after_event.journal[0].event_ids, vec![event(80)]);
    assert!(after_event.journal[0].work_transitions.is_empty());
    assert!(after_event.journal[0].chronology_budget.is_none());

    let scheduled = work(81);
    let schedule_schema_revision = SchemaRevision::new(1);
    let schedule_payload = json!({"kind": "work-only", "value": 81});
    let schedule_token = validated(
        &store,
        &registry,
        Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::new(
                scheduled,
                timeline(),
                WorkHandlerId::from(TEST_WORK_HANDLER),
                schedule_schema_revision,
                schedule_payload.clone(),
                WorkSchedule::Immediate,
            ))],
        ),
    );
    store
        .commit(&schedule_token, None, PlatformTime::new(2))
        .expect("Work-only commit should succeed");

    let after_schedule = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after_schedule.journal.len(), 2);
    assert_eq!(
        after_schedule.journal[1].before_version,
        after_event.version()
    );
    assert!(matches!(
        &after_schedule.journal[1].work_transitions[0],
        LogicalWorkTransition::Schedule {
            work_id,
            schema_revision,
            payload,
            effective_due_world_time,
            logical_schedule_order,
            ..
        } if *work_id == scheduled
            && *schema_revision == schedule_schema_revision
            && payload == &schedule_payload
            && *effective_due_world_time == WorldInstant::new(0)
            && *logical_schedule_order == 1
    ));
    assert_ne!(schedule_schema_revision, SchemaRevision::default());
    assert_eq!(
        store
            .read_logical_journal(timeline())
            .expect("logical journal should be readable after scheduling"),
        after_schedule.journal
    );

    let journal_before_retry = after_schedule.journal.clone();
    let claim = store
        .claim(
            timeline(),
            scheduled,
            PlatformTime::new(10),
            PlatformTime::new(20),
        )
        .expect("scheduled Work should be claimable");
    store
        .retry(
            &claim,
            PlatformTime::new(11),
            PlatformTime::new(100),
            Some("technical failure".to_owned()),
        )
        .expect("technical retry should succeed");
    assert_eq!(
        store
            .read_logical_journal(timeline())
            .expect("logical journal should be readable"),
        journal_before_retry,
        "claim/retry must not append logical history"
    );

    let retry_claim = store
        .claim(
            timeline(),
            scheduled,
            PlatformTime::new(100),
            PlatformTime::new(110),
        )
        .expect("retried Work should be claimable");
    let completion_token = validated(&store, &registry, Resolution::default());
    store
        .commit(
            &completion_token,
            Some(&retry_claim),
            PlatformTime::new(101),
        )
        .expect("Work completion should succeed");

    let after_completion = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after_completion.journal.len(), 3);
    assert_eq!(
        after_completion.journal[2]
            .after_version
            .state_revision
            .value(),
        3
    );
    assert!(matches!(
        &after_completion.journal[2].work_transitions[0],
        LogicalWorkTransition::Complete { work_id } if *work_id == scheduled
    ));
    let budget = after_completion.journal[2]
        .chronology_budget
        .expect("Work completion should consume one chronology unit");
    assert_eq!(budget.world_time, WorldInstant::new(0));
    assert_eq!((budget.before, budget.after), (0, 1));

    let transition = AdvanceWorldTime::new(
        timeline(),
        after_completion.version(),
        after_completion.world_time(),
        WorldInstant::new(5),
    )
    .expect("World-Time transition should validate");
    store
        .advance_world_time(transition)
        .expect("World-Time transition should succeed");

    let final_snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(final_snapshot.journal.len(), 4);
    assert_eq!(
        final_snapshot.journal[3].world_time,
        Some(loom_runtime::WorldTimeTransition {
            from: WorldInstant::new(0),
            to: WorldInstant::new(5),
        })
    );
    assert!(
        final_snapshot
            .journal
            .windows(2)
            .all(|entries| entries[0].logical_revision() < entries[1].logical_revision())
    );
}

#[tokio::test]
async fn logical_journal_event_and_work_share_one_revision() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    let initial = store.snapshot(timeline()).expect("snapshot should exist");
    let event_id = event(86);
    let work_id = work(87);
    let token = validated(
        &store,
        &registry,
        Resolution::new(
            vec![ProposedEvent::new(
                event_id,
                EventTypeId::from("test.changed"),
                SchemaRevision::new(1),
                json!({"kind": "event-and-work"}),
            )],
            vec![WorkMutation::Schedule(NewWork::new(
                work_id,
                timeline(),
                WorkHandlerId::from(TEST_WORK_HANDLER),
                SchemaRevision::new(1),
                json!({"kind": "event-and-work"}),
                WorkSchedule::Immediate,
            ))],
        ),
    );

    let result = store
        .commit(&token, None, PlatformTime::new(1))
        .expect("combined Event and Work commit should succeed");
    let after = store.snapshot(timeline()).expect("snapshot should exist");

    assert_eq!(result.version, after.version());
    assert_eq!(after.version().head_event_seq.value(), 1);
    assert_eq!(after.version().state_revision.value(), 1);
    assert_eq!(after.journal.len(), 1);
    assert_eq!(after.journal[0].before_version, initial.version());
    assert_eq!(after.journal[0].after_version, after.version());
    assert_eq!(after.journal[0].event_ids, vec![event_id]);
    assert!(matches!(
        &after.journal[0].work_transitions[0],
        LogicalWorkTransition::Schedule { work_id: id, .. } if *id == work_id
    ));
}

#[tokio::test]
async fn storage_hard_checks_accept_same_event_structural_references_and_ordered_effects() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    for entity_id in [entity(10), entity(11)] {
        store
            .seed_entity(
                timeline(),
                loom_core::Entity {
                    id: entity_id,
                    world_id: world(),
                },
            )
            .expect("Relationship participant Entity should be seeded");
    }

    let created_entity = entity(80);
    let entity_event = with_entity_participant(
        event_with_effect(
            event(80),
            WorldEffect::CreateEntity {
                entity_id: created_entity,
            },
            1,
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(created_entity),
            facet_type: FacetTypeId::from("test.facet"),
            schema_revision: SchemaRevision::new(1),
            value: json!({"created": true}),
        }),
        created_entity,
    );
    let created_relationship = loom_core::RelationshipId::from_uuid(
        "00000000-0000-0000-0000-000000000080"
            .parse()
            .expect("test RelationshipId should parse"),
    );
    let relationship_event = with_relationship_ref(
        event_with_effect(
            event(81),
            WorldEffect::CreateRelationship {
                relationship_id: created_relationship,
                relationship_type: RelationshipTypeId::from("test.relationship"),
                participants: relationship_participants(),
            },
            2,
        ),
        created_relationship,
    );

    let validated = validated(
        &store,
        &registry(),
        Resolution::new(vec![entity_event, relationship_event], Vec::new()),
    );
    let result = store
        .commit(&validated, None, PlatformTime::new(1))
        .expect("storage hard checks should agree with Runtime validation");

    assert_eq!(result.events.len(), 2);
    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert!(snapshot.world_view().entity(created_entity).is_some());
    assert_eq!(
        snapshot
            .world_view()
            .facet(
                FacetOwner::entity(created_entity),
                &FacetTypeId::from("test.facet"),
            )
            .expect("created Entity Facet should be readable")
            .value(),
        &json!({"created": true})
    );
    assert!(
        snapshot
            .world_view()
            .relationship(created_relationship)
            .is_some()
    );
}

#[tokio::test]
async fn storage_hard_checks_allow_reference_to_relationship_ended_by_same_event() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    for entity_id in [entity(10), entity(11)] {
        store
            .seed_entity(
                timeline(),
                loom_core::Entity {
                    id: entity_id,
                    world_id: world(),
                },
            )
            .expect("Relationship participant Entity should be seeded");
    }
    let relationship_id = loom_core::RelationshipId::from_uuid(
        "00000000-0000-0000-0000-000000000082"
            .parse()
            .expect("test RelationshipId should parse"),
    );
    store
        .seed_relationship(
            timeline(),
            loom_core::Relationship::new(
                relationship_id,
                world(),
                RelationshipTypeId::from("test.relationship"),
                relationship_participants(),
            ),
            true,
        )
        .expect("active Relationship should be seeded");

    let event = with_relationship_ref(
        event_with_effect(
            event(82),
            WorldEffect::EndRelationship { relationship_id },
            3,
        ),
        relationship_id,
    );
    let validated = validated(
        &store,
        &registry(),
        Resolution::new(vec![event], Vec::new()),
    );
    let result = store
        .commit(&validated, None, PlatformTime::new(1))
        .expect("an Event may reference the active Relationship it ends");
    assert_eq!(result.events.len(), 1);

    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert!(
        snapshot
            .world_view()
            .relationship(relationship_id)
            .is_none(),
        "ended Relationship must not remain active"
    );
}

#[tokio::test]
async fn stale_cas_leaves_event_state_and_work_unchanged() {
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

#[tokio::test]
async fn staged_commit_does_not_expose_event_before_work_failure() {
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
            WorkSchedule::Immediate,
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
    assert!(after.journal.is_empty());
}

#[tokio::test]
async fn work_creation_and_current_completion_share_zero_event_commit() {
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
    let registry = registry();
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
                WorkSchedule::At(WorldInstant::new(100)),
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

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the M5-T1 fixture keeps scheduling, restart-visible order and retry invariants together"
)]
async fn logical_work_target_due_and_order_survive_commits_and_retry() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_entity(
            timeline(),
            Entity {
                id: entity(10),
                world_id: world(),
            },
        )
        .expect("Agency Wake Agent Entity should be seeded");
    let registry = registry();
    let first = work(70);
    let second = work(71);
    let agency = work(72);
    let first_resolution = Resolution::new(
        Vec::new(),
        vec![
            WorkMutation::Schedule(NewWork::new(
                first,
                timeline(),
                WorkHandlerId::from(TEST_WORK_HANDLER),
                SchemaRevision::new(1),
                json!({"first": true}),
                WorkSchedule::Immediate,
            )),
            WorkMutation::Schedule(NewWork::new(
                second,
                timeline(),
                WorkHandlerId::from(TEST_WORK_HANDLER),
                SchemaRevision::new(1),
                json!({"second": true}),
                WorkSchedule::Immediate,
            )),
        ],
    );
    let first_token = validated(&store, &registry, first_resolution);
    store
        .commit(&first_token, None, PlatformTime::new(10))
        .expect("first scheduling commit should succeed");

    let second_token = validated(
        &store,
        &registry,
        Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::agency_wake(
                agency,
                timeline(),
                entity(10),
                "cognition.default",
                json!({"wake": true}),
                WorkSchedule::Immediate,
            ))],
        ),
    );
    store
        .commit(&second_token, None, PlatformTime::new(11))
        .expect("second scheduling commit should succeed");

    let snapshot = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(snapshot.works.len(), 3);
    assert_eq!(
        snapshot
            .works
            .iter()
            .map(|work| work.logical_schedule_order)
            .collect::<Vec<_>>(),
        vec![1, 2, 3]
    );
    assert!(
        snapshot
            .works
            .iter()
            .all(|work| work.effective_due_world_time == WorldInstant::new(0))
    );
    assert!(matches!(
        snapshot
            .works
            .iter()
            .find(|work| work.id == agency)
            .expect("Agency Wake should be readable")
            .target,
        WorkTarget::AgencyWake { .. }
    ));

    let before_retry = snapshot
        .works
        .iter()
        .find(|work| work.id == first)
        .expect("first Work should be readable")
        .clone();
    let claim = store
        .claim(
            timeline(),
            first,
            PlatformTime::new(20),
            PlatformTime::new(30),
        )
        .expect("first Work should be claimable");
    let retried = store
        .retry(
            &claim,
            PlatformTime::new(21),
            PlatformTime::new(100),
            Some("temporary failure".to_owned()),
        )
        .expect("retry should be recorded");
    assert_eq!(retried.target, before_retry.target);
    assert_eq!(
        retried.effective_due_world_time,
        before_retry.effective_due_world_time
    );
    assert_eq!(
        retried.logical_schedule_order,
        before_retry.logical_schedule_order
    );
    assert_eq!(retried.available_at, PlatformTime::new(100));
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the D-1 fixture keeps invalid, duplicate, valid, reclaim and retry boundaries together"
)]
async fn agency_wake_requires_existing_agent_before_order_allocation() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let registry = registry();
    let invalid = work(73);
    let invalid_token = validated(
        &store,
        &registry,
        Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::agency_wake(
                invalid,
                timeline(),
                entity(99),
                "cognition.default",
                json!({"wake": "invalid-agent"}),
                WorkSchedule::Immediate,
            ))],
        ),
    );
    let initial = store.snapshot(timeline()).expect("snapshot should exist");
    let error = store
        .commit(&invalid_token, None, PlatformTime::new(10))
        .expect_err("an Agency Wake for a missing Agent Entity must be rejected");
    assert!(matches!(
        error,
        CommitError::Work(WorkError::StorageUnavailable { message })
            if message.contains("Agent Entity")
    ));
    let after_invalid = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after_invalid.version(), initial.version());
    assert!(after_invalid.works.is_empty());

    store
        .seed_entity(
            timeline(),
            Entity {
                id: entity(10),
                world_id: world(),
            },
        )
        .expect("valid Agency Wake Agent Entity should be seeded");
    let valid = work(74);
    let valid_resolution = Resolution::new(
        Vec::new(),
        vec![WorkMutation::Schedule(NewWork::agency_wake(
            valid,
            timeline(),
            entity(10),
            "cognition.default",
            json!({"wake": "valid-agent"}),
            WorkSchedule::Immediate,
        ))],
    );
    let valid_token = validated(&store, &registry, valid_resolution.clone());
    store
        .commit(&valid_token, None, PlatformTime::new(11))
        .expect("valid Agency Wake should commit");
    let after_valid = store.snapshot(timeline()).expect("snapshot should exist");
    let valid_before_duplicate = after_valid
        .works
        .iter()
        .find(|work| work.id == valid)
        .expect("valid Agency Wake should be readable")
        .clone();
    assert_eq!(valid_before_duplicate.logical_schedule_order, 1);
    assert_eq!(
        valid_before_duplicate.effective_due_world_time,
        WorldInstant::new(0)
    );
    assert!(matches!(
        &valid_before_duplicate.target,
        WorkTarget::AgencyWake { agent, cognition }
            if *agent == entity(10) && cognition == "cognition.default"
    ));

    let duplicate_token = validated(&store, &registry, valid_resolution);
    let duplicate = store
        .commit(&duplicate_token, None, PlatformTime::new(12))
        .expect_err("duplicate Agency Wake identity must be rejected");
    assert!(matches!(
        duplicate,
        CommitError::Work(WorkError::DuplicateWork { work_id }) if work_id == valid
    ));
    let after_duplicate = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after_duplicate.version(), after_valid.version());
    assert_eq!(
        after_duplicate
            .works
            .iter()
            .find(|work| work.id == valid)
            .expect("valid Agency Wake should remain readable")
            .logical_schedule_order,
        1
    );

    let second = work(75);
    let second_token = validated(
        &store,
        &registry,
        Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::agency_wake(
                second,
                timeline(),
                entity(10),
                "cognition.default",
                json!({"wake": "second-valid-agent"}),
                WorkSchedule::Immediate,
            ))],
        ),
    );
    store
        .commit(&second_token, None, PlatformTime::new(13))
        .expect("second valid Agency Wake should commit");
    let before_reclaim = store
        .snapshot(timeline())
        .expect("snapshot should exist")
        .works
        .into_iter()
        .find(|work| work.id == valid)
        .expect("valid Agency Wake should remain readable");
    assert_eq!(before_reclaim.logical_schedule_order, 1);

    let first_claim = store
        .claim(
            timeline(),
            valid,
            PlatformTime::new(20),
            PlatformTime::new(30),
        )
        .expect("valid Agency Wake should be claimable");
    let reclaimed = store
        .claim(
            timeline(),
            valid,
            PlatformTime::new(30),
            PlatformTime::new(40),
        )
        .expect("expired Agency Wake lease should be reclaimable");
    assert_ne!(first_claim.fence(), reclaimed.fence());
    let retried = store
        .retry(
            &reclaimed,
            PlatformTime::new(31),
            PlatformTime::new(100),
            Some("temporary agency failure".to_owned()),
        )
        .expect("reclaimed Agency Wake should be retryable");
    assert_eq!(retried.target, before_reclaim.target);
    assert_eq!(
        retried.effective_due_world_time,
        before_reclaim.effective_due_world_time
    );
    assert_eq!(
        retried.logical_schedule_order,
        before_reclaim.logical_schedule_order
    );
}

#[tokio::test]
async fn retry_and_expired_claims_preserve_work_identity_and_fence_winner() {
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

#[tokio::test]
async fn runtime_control_terminalization_is_cas_journaled_and_not_resurrectable() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let work_id = work(61);
    store
        .seed_work(pending_work(work_id))
        .expect("Work fixture should be seeded");
    let initial = store.snapshot(timeline()).expect("snapshot should exist");
    let terminalized = RuntimeControlStore::terminalize_work(
        &store,
        &WorkTerminalization::new(
            timeline(),
            initial.version(),
            work_id,
            WorkTerminalState::Cancelled,
            PlatformTime::new(1),
        ),
    )
    .await
    .expect("authorized cancellation should commit");
    assert_eq!(terminalized.state_revision.value(), 1);

    let after = store.snapshot(timeline()).expect("snapshot should exist");
    let cancelled = after
        .works
        .iter()
        .find(|item| item.id == work_id)
        .expect("cancelled Work should remain readable");
    assert_eq!(cancelled.status, WorkStatus::Cancelled);
    assert!(cancelled.lease.is_none());
    assert_eq!(after.events.len(), 0);
    assert_eq!(after.journal.len(), 1);
    assert!(matches!(
        after.journal[0].work_transitions.as_slice(),
        [LogicalWorkTransition::Cancel { work_id: cancelled_id }] if *cancelled_id == work_id
    ));

    let stale = RuntimeControlStore::terminalize_work(
        &store,
        &WorkTerminalization::new(
            timeline(),
            initial.version(),
            work_id,
            WorkTerminalState::Dead,
            PlatformTime::new(2),
        ),
    )
    .await
    .expect_err("a stale control CAS must not rewrite terminal Work");
    assert!(matches!(stale, CommitError::TimelineConflict { .. }));
    let claim = store
        .claim(
            timeline(),
            work_id,
            PlatformTime::new(3),
            PlatformTime::new(4),
        )
        .expect_err("terminal Work must not be claimed again");
    assert!(matches!(claim, WorkError::NotPending { .. }));
}

#[tokio::test]
async fn runtime_failure_terminalization_recovers_stale_cas_without_reclaim() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let work_id = work(62);
    store
        .seed_work(pending_work(work_id))
        .expect("failure Work fixture should be seeded");

    let initial = store.snapshot(timeline()).expect("snapshot should exist");
    let claim = store
        .claim(
            timeline(),
            work_id,
            PlatformTime::new(0),
            PlatformTime::new(10),
        )
        .expect("failure Work should be claimed once");

    let concurrent = validated(
        &store,
        &registry(),
        Resolution::new(
            vec![event_with_effect(
                event(63),
                WorldEffect::CreateEntity {
                    entity_id: entity(64),
                },
                1,
            )],
            Vec::new(),
        ),
    );
    store
        .commit(&concurrent, None, PlatformTime::new(1))
        .expect("the concurrent logical commit should advance the Timeline");

    let terminalization = WorkTerminalization::new(
        timeline(),
        initial.version(),
        work_id,
        WorkTerminalState::Dead,
        PlatformTime::new(2),
    )
    .with_claim(claim)
    .with_last_error("handler failed");
    let stale = RuntimeControlStore::terminalize_work(&store, &terminalization)
        .await
        .expect_err("the execution snapshot must be stale after the concurrent commit");
    assert!(matches!(stale, CommitError::TimelineConflict { .. }));

    let before_recovery = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(before_recovery.journal.len(), 1);
    assert_eq!(before_recovery.version().state_revision.value(), 1);
    let recovered = RuntimeControlStore::terminalize_current_work(&store, &terminalization)
        .await
        .expect("bounded stale-CAS recovery should read the current version atomically");
    let after = store.snapshot(timeline()).expect("snapshot should exist");

    assert_eq!(recovered, after.version());
    assert_eq!(after.version().head_event_seq.value(), 1);
    assert_eq!(after.version().state_revision.value(), 2);
    assert_eq!(after.journal.len(), 2);
    assert_eq!(after.events.len(), 1);
    assert_eq!(after.journal[1].before_version, before_recovery.version());
    assert_eq!(after.journal[1].after_version, after.version());
    assert!(matches!(
        after.journal[1].work_transitions.as_slice(),
        [LogicalWorkTransition::Dead { work_id: dead_id }] if *dead_id == work_id
    ));

    let terminal = after
        .works
        .iter()
        .find(|item| item.id == work_id)
        .expect("terminalized Work should remain readable");
    assert_eq!(terminal.status, WorkStatus::Dead);
    assert_eq!(terminal.attempt_count, 1);
    assert!(terminal.lease.is_none());
    assert_eq!(terminal.last_error.as_deref(), Some("handler failed"));
    assert!(matches!(
        store.claim(
            timeline(),
            work_id,
            PlatformTime::new(3),
            PlatformTime::new(4),
        ),
        Err(WorkError::NotPending { .. })
    ));
    let duplicate = RuntimeControlStore::terminalize_current_work(&store, &terminalization)
        .await
        .expect_err("a recovered terminalization must not append a second revision");
    assert!(matches!(
        duplicate,
        CommitError::Work(WorkError::NotPending { .. })
    ));
    let after_duplicate = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after_duplicate.version(), after.version());
    assert_eq!(after_duplicate.journal, after.journal);
}

#[tokio::test]
async fn runtime_terminalization_rejects_cross_work_claim_without_mutation() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    let claimed_work = work(65);
    let target_work = work(66);
    store
        .seed_work(pending_work(claimed_work))
        .expect("claimed Work fixture should be seeded");
    let mut target_fixture = pending_work(target_work);
    target_fixture.logical_schedule_order = 2;
    store
        .seed_work(target_fixture)
        .expect("target Work fixture should be seeded");
    let claim = store
        .claim(
            timeline(),
            claimed_work,
            PlatformTime::new(0),
            PlatformTime::new(10),
        )
        .expect("claimed Work should have a live fence");
    let before = store.snapshot(timeline()).expect("snapshot should exist");

    let error = RuntimeControlStore::terminalize_work(
        &store,
        &WorkTerminalization::new(
            timeline(),
            before.version(),
            target_work,
            WorkTerminalState::Dead,
            PlatformTime::new(1),
        )
        .with_claim(claim),
    )
    .await
    .expect_err("a claim for another Work must be rejected");
    assert!(matches!(
        error,
        CommitError::Work(WorkError::WorkMismatch { expected, actual })
            if expected == target_work && actual == claimed_work
    ));

    let after = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after.version(), before.version());
    assert_eq!(after.events, before.events);
    assert_eq!(after.journal, before.journal);
    assert_eq!(after.works, before.works);
}

#[test]
fn scheduler_non_head_claim_is_rejected_without_mutation() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("test Timeline should be created");
    store
        .seed_work(pending_work(work(67)))
        .expect("head Work fixture should be seeded");
    let mut non_head = pending_work(work(68));
    non_head.logical_schedule_order = 2;
    store
        .seed_work(non_head)
        .expect("non-head Work fixture should be seeded");
    let before = store.snapshot(timeline()).expect("snapshot should exist");

    let error = store
        .claim(
            timeline(),
            work(68),
            PlatformTime::new(0),
            PlatformTime::new(10),
        )
        .expect_err("Scheduler claim must reject a non-head Work");
    assert!(matches!(
        error,
        WorkError::NotLogicalHead { work_id, head_work_id }
            if work_id == work(68) && head_work_id == work(67)
    ));

    let after = store.snapshot(timeline()).expect("snapshot should exist");
    assert_eq!(after.version(), before.version());
    assert_eq!(after.events, before.events);
    assert_eq!(after.journal, before.journal);
    assert_eq!(after.works, before.works);
}

#[tokio::test]
async fn concurrent_cas_and_claim_choose_one_winner() {
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

#[tokio::test]
async fn concurrent_claims_choose_one_fence_winner() {
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

#[tokio::test]
async fn current_head_fork_clones_only_pending_work_and_is_idempotent_for_child_id() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("source Timeline should be created");
    let mut source_work = pending_work(work(80));
    source_work.attempt_count = 4;
    source_work.claim_generation = 7;
    source_work.available_at = PlatformTime::new(99);
    source_work.last_error = Some("transient".to_owned());
    source_work.lease = Some(loom_runtime::WorkLease::new(100.into(), 7));
    store
        .seed_work(source_work.clone())
        .expect("source Pending Work should be seeded");

    let mut child_work = source_work.clone();
    child_work.id = work(81);
    child_work.timeline_id = second_timeline();
    let fork = TimelineFork::new(timeline(), TimelineVersion::default(), second_timeline())
        .with_pending_work(vec![ForkWork {
            source_work_id: source_work.id,
            work: child_work,
        }]);
    let child = TimelineForkStore::fork_timeline(&store, &fork)
        .await
        .expect("head fork should commit atomically");

    assert_eq!(child.world_id(), world());
    assert_eq!(child.ancestry().parent_timeline_id, Some(timeline()));
    assert_eq!(
        child.ancestry().fork_parent_version,
        Some(TimelineVersion::default())
    );
    assert!(
        child.events.is_empty(),
        "ancestor Events must not be copied"
    );
    let inherited = &child.works[0];
    assert_eq!(inherited.id, work(81));
    assert_eq!(
        inherited.effective_due_world_time,
        source_work.effective_due_world_time
    );
    assert_eq!(
        inherited.logical_schedule_order,
        source_work.logical_schedule_order
    );
    assert_eq!(inherited.attempt_count, 0);
    assert_eq!(inherited.claim_generation, 0);
    assert_eq!(inherited.available_at, PlatformTime::default());
    assert!(inherited.last_error.is_none());
    assert!(inherited.lease.is_none());

    let second = TimelineForkStore::fork_timeline(&store, &fork)
        .await
        .expect("retrying the same child identity should be idempotent");
    assert_eq!(second.ancestry(), child.ancestry());
    assert_eq!(
        store
            .snapshot(timeline())
            .expect("source should remain readable")
            .works[0],
        source_work
    );

    let mut invalid_work = source_work.clone();
    invalid_work.id = work(82);
    invalid_work.timeline_id = id(4);
    invalid_work.payload = json!({"tampered": true});
    let tampered_fork = TimelineFork::new(timeline(), TimelineVersion::default(), id(4))
        .with_pending_work(vec![ForkWork {
            source_work_id: source_work.id,
            work: invalid_work,
        }]);
    assert!(matches!(
        TimelineForkStore::fork_timeline(&store, &tampered_fork).await,
        Err(loom_runtime::ForkError::InvalidWork { .. })
    ));
    assert!(matches!(
        store.snapshot(id(4)),
        Err(loom_runtime::ReadError::TimelineNotFound { .. })
    ));
}

#[tokio::test]
async fn current_head_fork_resolves_parent_event_through_ancestry() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("source Timeline should be created");
    let registry = registry();
    let event_id = event(90);
    let token = validated(
        &store,
        &registry,
        Resolution::new(
            vec![ProposedEvent::new(
                event_id,
                EventTypeId::from("test.changed"),
                SchemaRevision::new(1),
                json!({"kind": "ancestry-event"}),
            )],
            Vec::new(),
        ),
    );
    store
        .commit(&token, None, PlatformTime::new(1))
        .expect("source Event should commit at a non-default version");
    let source_before = store.snapshot(timeline()).expect("source snapshot");

    let child_b = TimelineForkStore::fork_timeline(
        &store,
        &TimelineFork::new(timeline(), source_before.version(), second_timeline()),
    )
    .await
    .expect("first fork should commit");
    assert_eq!(
        child_b
            .events
            .iter()
            .map(loom_runtime::CommittedEvent::event_ref)
            .collect::<Vec<_>>(),
        vec![EventRef::new(timeline(), event_id)]
    );
    assert_eq!(
        child_b.ancestry().fork_parent_event,
        Some(EventRef::new(timeline(), event_id))
    );

    let child_c_id: TimelineId = id(4);
    let child_c = TimelineForkStore::fork_timeline(
        &store,
        &TimelineFork::new(second_timeline(), child_b.version(), child_c_id),
    )
    .await
    .expect("second fork should commit");
    assert_eq!(
        child_c
            .events
            .iter()
            .map(loom_runtime::CommittedEvent::event_ref)
            .collect::<Vec<_>>(),
        vec![EventRef::new(timeline(), event_id)]
    );
    assert_eq!(
        child_c.ancestry().fork_parent_event,
        Some(EventRef::new(timeline(), event_id))
    );

    let child_c_before_parent_event = TimelineForkStore::fork_timeline(
        &store,
        &TimelineFork::new(second_timeline(), child_b.version(), id(5))
            .at_version(TimelineVersion::default()),
    )
    .await
    .expect("second fork at B's pre-boundary position should commit");
    assert_eq!(
        child_c_before_parent_event.ancestry().fork_parent_event,
        None,
        "C's requested V0 must not inherit A's later EventRef"
    );
    assert!(child_c_before_parent_event.events.is_empty());
    assert_eq!(
        store
            .snapshot(timeline())
            .expect("source remains readable")
            .version(),
        source_before.version()
    );
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the regression covers the complete historical fork boundary"
)]
async fn historical_runtime_fork_replays_pending_future_without_parent_tail() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("source Timeline should be created");
    let registry = registry();

    let first_event = validated(
        &store,
        &registry,
        Resolution::new(
            vec![event_with_effect(
                event(100),
                WorldEffect::CreateEntity {
                    entity_id: entity(100),
                },
                0,
            )],
            Vec::new(),
        ),
    );
    store
        .commit(&first_event, None, PlatformTime::new(1))
        .expect("first Event should commit");

    let scheduled = work(100);
    let schedule = validated(
        &store,
        &registry,
        Resolution::new(
            Vec::new(),
            vec![WorkMutation::Schedule(NewWork::new(
                scheduled,
                timeline(),
                WorkHandlerId::from(TEST_WORK_HANDLER),
                SchemaRevision::new(1),
                json!({"historical": true}),
                WorkSchedule::Immediate,
            ))],
        ),
    );
    store
        .commit(&schedule, None, PlatformTime::new(2))
        .expect("historical Pending Work should commit");
    let fork_version = store.snapshot(timeline()).expect("fork point").version();

    let cancel = validated(
        &store,
        &registry,
        Resolution::new(Vec::new(), vec![WorkMutation::Cancel(scheduled)]),
    );
    store
        .commit(&cancel, None, PlatformTime::new(3))
        .expect("parent Work completion should commit after the fork point");
    let parent_tail = validated(
        &store,
        &registry,
        Resolution::new(
            vec![event_with_effect(
                event(101),
                WorldEffect::CreateEntity {
                    entity_id: entity(101),
                },
                0,
            )],
            Vec::new(),
        ),
    );
    store
        .commit(&parent_tail, None, PlatformTime::new(4))
        .expect("parent tail should commit");

    let runtime = Runtime::new(&store, registry).expect("Runtime should assemble");
    let child = runtime
        .fork(ForkTimelineRequest::at_version(
            TimelineTarget::new(world(), timeline()),
            fork_version,
        ))
        .await
        .expect("historical fork should commit");
    let child_snapshot = store
        .snapshot(child.target.timeline_id)
        .expect("child should be readable");

    assert_eq!(child_snapshot.version(), fork_version);
    assert_eq!(
        child_snapshot.ancestry().fork_parent_version,
        Some(fork_version)
    );
    assert_eq!(
        child_snapshot
            .events
            .iter()
            .map(loom_runtime::CommittedEvent::event_ref)
            .collect::<Vec<_>>(),
        vec![EventRef::new(timeline(), event(100))]
    );
    assert!(child_snapshot.world_view().entity(entity(100)).is_some());
    assert!(child_snapshot.world_view().entity(entity(101)).is_none());
    assert_eq!(child_snapshot.works.len(), 1);
    assert_eq!(child_snapshot.works[0].status, WorkStatus::Pending);
    assert_ne!(child_snapshot.works[0].id, scheduled);
    assert_eq!(
        child_snapshot.works[0].logical_schedule_order, 1,
        "the historical logical order is preserved for the branch"
    );

    let child_current = runtime
        .fork(ForkTimelineRequest::new(child.target))
        .await
        .expect("forking a child at its current inherited head should commit");
    let child_boundary = runtime
        .fork(ForkTimelineRequest::at_version(child.target, fork_version))
        .await
        .expect("forking a child at its inherited boundary should commit");
    for forked_child in [child_current, child_boundary] {
        let snapshot = store
            .snapshot(forked_child.target.timeline_id)
            .expect("forked child should be readable");
        assert_eq!(snapshot.version(), fork_version);
        assert_eq!(snapshot.world_time(), child_snapshot.world_time());
        assert_eq!(
            snapshot
                .events
                .iter()
                .map(loom_runtime::CommittedEvent::event_ref)
                .collect::<Vec<_>>(),
            vec![EventRef::new(timeline(), event(100))]
        );
        assert!(snapshot.world_view().entity(entity(100)).is_some());
        assert!(snapshot.world_view().entity(entity(101)).is_none());
        assert_eq!(snapshot.works.len(), 1);
        assert_eq!(snapshot.works[0].target, child_snapshot.works[0].target);
        assert_eq!(snapshot.works[0].payload, child_snapshot.works[0].payload);
        assert_eq!(
            snapshot.works[0].logical_schedule_order,
            child_snapshot.works[0].logical_schedule_order
        );
        assert_ne!(snapshot.works[0].id, child_snapshot.works[0].id);
    }

    let child_ancestor = runtime
        .fork(ForkTimelineRequest::at_version(
            child.target,
            TimelineVersion::default(),
        ))
        .await
        .expect("a committed ancestor position should remain visible through B");
    let ancestor_snapshot = store
        .snapshot(child_ancestor.target.timeline_id)
        .expect("ancestor fork should be readable");
    assert_eq!(ancestor_snapshot.version(), TimelineVersion::default());
    assert!(ancestor_snapshot.world_view().entity(entity(100)).is_none());
    assert!(ancestor_snapshot.works.is_empty());

    let child_c = runtime
        .fork(ForkTimelineRequest::at_version(
            child.target,
            TimelineVersion::default(),
        ))
        .await
        .expect("B should fork C at the visible inherited zero position");
    let grandchild_current = runtime
        .fork(ForkTimelineRequest::new(child_c.target))
        .await
        .expect("C current inherited position should be forkable");
    let grandchild_boundary = runtime
        .fork(ForkTimelineRequest::at_version(
            child_c.target,
            TimelineVersion::default(),
        ))
        .await
        .expect("C inherited boundary should be forkable");
    for forked_child in [grandchild_current, grandchild_boundary] {
        let snapshot = store
            .snapshot(forked_child.target.timeline_id)
            .expect("grandchild should be readable");
        assert_eq!(snapshot.version(), TimelineVersion::default());
        assert_eq!(
            snapshot.ancestry().parent_timeline_id,
            Some(child_c.target.timeline_id)
        );
        assert!(snapshot.events.is_empty());
        assert!(snapshot.logical_journal().is_empty());
        assert!(snapshot.world_view().entity(entity(100)).is_none());
        assert!(snapshot.world_view().entity(entity(101)).is_none());
        assert!(snapshot.works.is_empty());
    }

    let invalid_child_target = runtime
        .fork(ForkTimelineRequest::at_version(
            child_c.target,
            fork_version,
        ))
        .await
        .expect_err("C cannot fork at B's post-boundary version");
    assert_eq!(invalid_child_target.code, ApiErrorCode::InvalidRequest);

    let invalid = runtime
        .fork(ForkTimelineRequest::at_version(
            child.target,
            TimelineVersion::new(EventSeq::new(99), StateRevision::new(99)),
        ))
        .await
        .expect_err("a beyond-head version must fail before child creation");
    assert_eq!(invalid.code, ApiErrorCode::InvalidRequest);
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the M6 parity gate intentionally keeps the complete replay/fork scenario visible"
)]
async fn m6_replay_fork_branch_isolation_parity_gate_in_memory() {
    let store = InMemoryStore::new();
    store
        .create_timeline(world(), timeline())
        .expect("parent Timeline should be created");
    let capabilities = registry();

    let entity_event = event_with_effect(
        event(600),
        WorldEffect::CreateEntity {
            entity_id: entity(10),
        },
        900,
    )
    .with_effect(WorldEffect::PutFacet {
        owner: FacetOwner::entity(entity(10)),
        facet_type: FacetTypeId::from("test.facet"),
        schema_revision: SchemaRevision::new(1),
        value: json!({"origin": "entity"}),
    });
    let second_entity_event = event_with_effect(
        event(601),
        WorldEffect::CreateEntity {
            entity_id: entity(11),
        },
        901,
    );
    let relationship_id = id::<loom_core::RelationshipId>(620);
    let relationship_event = with_relationship_ref(
        event_with_effect(
            event(602),
            WorldEffect::CreateRelationship {
                relationship_id,
                relationship_type: RelationshipTypeId::from("test.relationship"),
                participants: relationship_participants(),
            },
            902,
        )
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::relationship(relationship_id),
            facet_type: FacetTypeId::from("test.facet"),
            schema_revision: SchemaRevision::new(1),
            value: json!({"origin": "relationship"}),
        }),
        relationship_id,
    );
    let zero_effect_event = ProposedEvent::new(
        event(603),
        EventTypeId::from("test.changed"),
        SchemaRevision::new(1),
        json!({"zero_effect": true}),
    )
    .with_causal_link(CausalLink::new(event(602)));
    let end_relationship_event = with_relationship_ref(
        event_with_effect(
            event(604),
            WorldEffect::EndRelationship { relationship_id },
            904,
        ),
        relationship_id,
    )
    .with_causal_link(CausalLink::new(event(603)));

    for proposal in [
        entity_event,
        second_entity_event,
        relationship_event,
        zero_effect_event,
        end_relationship_event,
    ] {
        let token = validated(
            &store,
            &capabilities,
            Resolution::new(vec![proposal], Vec::new()),
        );
        store
            .commit(&token, None, PlatformTime::new(1))
            .expect("root Event should commit");
    }

    let immediate = work(610);
    let at_work = work(611);
    let agency_wake = work(612);
    let mut reaction_work = NewWork::new(
        work(613),
        timeline(),
        WorkHandlerId::from(TEST_WORK_HANDLER),
        SchemaRevision::new(1),
        json!({"reaction": true}),
        WorkSchedule::Immediate,
    );
    reaction_work.causal_event_id = Some(event(603));
    reaction_work.origin_work_id = Some(immediate);
    let reaction_id = reaction_work.id;
    let schedule_token = validated(
        &store,
        &capabilities,
        Resolution::new(
            Vec::new(),
            vec![
                WorkMutation::Schedule(NewWork::new(
                    immediate,
                    timeline(),
                    WorkHandlerId::from(TEST_WORK_HANDLER),
                    SchemaRevision::new(1),
                    json!({"immediate": true}),
                    WorkSchedule::Immediate,
                )),
                WorkMutation::Schedule(NewWork::new(
                    at_work,
                    timeline(),
                    WorkHandlerId::from(TEST_WORK_HANDLER),
                    SchemaRevision::new(1),
                    json!({"at": true}),
                    WorkSchedule::At(WorldInstant::new(100)),
                )),
                WorkMutation::Schedule(NewWork::agency_wake(
                    agency_wake,
                    timeline(),
                    entity(10),
                    "cognition.default",
                    json!({"wake": true}),
                    WorkSchedule::Immediate,
                )),
            ],
        ),
    );
    store
        .commit(&schedule_token, None, PlatformTime::new(2))
        .expect("scheduled Work should commit");
    let reaction_token = validated(
        &store,
        &capabilities,
        Resolution::new(Vec::new(), vec![WorkMutation::Schedule(reaction_work)]),
    );
    store
        .commit(&reaction_token, None, PlatformTime::new(3))
        .expect("reaction Work should commit");

    let scheduled = store.snapshot(timeline()).expect("scheduled snapshot");
    let scheduled_version = scheduled.version();
    assert_eq!(scheduled.chronology_budget().consumed, 0);
    assert_eq!(scheduled.works.len(), 4);

    let retry_claim = store
        .claim(
            timeline(),
            immediate,
            PlatformTime::new(4),
            PlatformTime::new(8),
        )
        .expect("Immediate Work should be claimable");
    let retried = store
        .retry(
            &retry_claim,
            PlatformTime::new(5),
            PlatformTime::new(9),
            Some("transient operational failure".to_owned()),
        )
        .expect("technical retry should remain operational noise");
    assert_eq!(retried.attempt_count, 1);
    assert_eq!(
        store
            .snapshot(timeline())
            .expect("retry snapshot")
            .version(),
        scheduled_version
    );

    let complete_claim = store
        .claim(
            timeline(),
            immediate,
            PlatformTime::new(10),
            PlatformTime::new(20),
        )
        .expect("retried Work should become claimable");
    SchedulerCommitStore::commit_scheduler_work(
        &store,
        &validated(&store, &capabilities, Resolution::default()),
        &complete_claim,
        PlatformTime::new(11),
        8,
    )
    .await
    .expect("successful Work completion should consume chronology budget");

    let cancel_token = validated(
        &store,
        &capabilities,
        Resolution::new(Vec::new(), vec![WorkMutation::Cancel(reaction_id)]),
    );
    store
        .commit(&cancel_token, None, PlatformTime::new(12))
        .expect("reaction Work should cancel logically");
    let before_dead = store.snapshot(timeline()).expect("pre-dead snapshot");
    store
        .terminalize_work(
            &WorkTerminalization::new(
                timeline(),
                before_dead.version(),
                agency_wake,
                WorkTerminalState::Dead,
                PlatformTime::new(13),
            )
            .with_last_error("bounded provider failure"),
        )
        .expect("Agency Wake should terminalize as Dead");

    let fork_point = store.snapshot(timeline()).expect("fork point snapshot");
    assert_eq!(fork_point.chronology_budget().consumed, 1);
    assert_eq!(
        fork_point
            .works
            .iter()
            .map(|work| (work.id, work.status))
            .collect::<Vec<_>>(),
        vec![
            (immediate, WorkStatus::Completed),
            (agency_wake, WorkStatus::Dead),
            (reaction_id, WorkStatus::Cancelled),
            (at_work, WorkStatus::Pending),
        ]
    );

    let replayed = fork_point
        .replay_to(fork_point.version())
        .expect("root should replay to its current boundary");
    assert!(replayed.world_view().entity(entity(10)).is_some());
    assert!(replayed.world_view().entity(entity(11)).is_some());
    assert!(
        replayed
            .world_view()
            .relationship(relationship_id)
            .is_none()
    );
    assert_eq!(
        replayed
            .logical_state()
            .work(at_work)
            .expect("At Work should replay")
            .status,
        WorkStatus::Pending
    );

    let runtime = Runtime::new(&store, capabilities).expect("Runtime should assemble");
    let target = TimelineTarget::new(world(), timeline());
    let historical_child = runtime
        .fork(ForkTimelineRequest::at_version(
            target,
            fork_point.version(),
        ))
        .await
        .expect("historical fork should use replayed semantic and logical state");
    let child_snapshot = store
        .snapshot(historical_child.target.timeline_id)
        .expect("historical child should be readable");
    assert_eq!(child_snapshot.world_time(), fork_point.world_time());
    assert_eq!(child_snapshot.works.len(), 1);
    assert_ne!(child_snapshot.works[0].id, at_work);
    assert_eq!(child_snapshot.works[0].status, WorkStatus::Pending);
    assert_eq!(child_snapshot.chronology_budget().consumed, 1);
    assert!(child_snapshot.world_view().entity(entity(10)).is_some());
    assert!(
        child_snapshot
            .world_view()
            .relationship(relationship_id)
            .is_none()
    );

    let before_boundary = runtime
        .fork(ForkTimelineRequest::at_version(
            historical_child.target,
            TimelineVersion::default(),
        ))
        .await
        .expect("target before branch boundary should recurse to parent");
    let before_boundary_snapshot = store
        .snapshot(before_boundary.target.timeline_id)
        .expect("before-boundary child should be readable");
    assert_eq!(
        before_boundary_snapshot.version(),
        TimelineVersion::default()
    );
    assert!(before_boundary_snapshot.events.is_empty());
    assert!(
        before_boundary_snapshot
            .world_view()
            .entity(entity(10))
            .is_none()
    );

    let parent_time = AdvanceWorldTime::new(
        timeline(),
        fork_point.version(),
        fork_point.world_time(),
        WorldInstant::new(10),
    )
    .expect("explicit World-Time transition should validate");
    store
        .advance_world_time(parent_time)
        .expect("parent should advance World Time explicitly");
    let parent_head = runtime
        .fork(ForkTimelineRequest::new(target))
        .await
        .expect("current parent fork should commit");
    let sibling = runtime
        .fork(ForkTimelineRequest::new(target))
        .await
        .expect("sibling fork should commit independently");
    let grandchild = runtime
        .fork(ForkTimelineRequest::new(historical_child.target))
        .await
        .expect("grandchild fork should retain historical ancestry");

    let parent_tail = validated_at(
        &store,
        &registry(),
        timeline(),
        Resolution::new(
            vec![event_with_effect(
                event(650),
                WorldEffect::PutFacet {
                    owner: FacetOwner::entity(entity(10)),
                    facet_type: FacetTypeId::from("test.facet"),
                    schema_revision: SchemaRevision::new(1),
                    value: json!({"branch": "parent"}),
                },
                950,
            )],
            Vec::new(),
        ),
    )
    .expect("parent branch Event should validate");
    store
        .commit(&parent_tail, None, PlatformTime::new(14))
        .expect("parent branch should diverge");

    let child_tail = validated_at(
        &store,
        &registry(),
        historical_child.target.timeline_id,
        Resolution::new(
            vec![event_with_effect(
                event(651),
                WorldEffect::CreateEntity {
                    entity_id: entity(651),
                },
                951,
            )],
            Vec::new(),
        ),
    )
    .expect("historical child Event should validate");
    store
        .commit(&child_tail, None, PlatformTime::new(15))
        .expect("historical child should diverge");

    let sibling_tail = validated_at(
        &store,
        &registry(),
        sibling.target.timeline_id,
        Resolution::new(
            vec![event_with_effect(
                event(652),
                WorldEffect::CreateEntity {
                    entity_id: entity(652),
                },
                952,
            )],
            Vec::new(),
        ),
    )
    .expect("sibling Event should validate");
    store
        .commit(&sibling_tail, None, PlatformTime::new(16))
        .expect("sibling should diverge");

    let grandchild_tail = validated_at(
        &store,
        &registry(),
        grandchild.target.timeline_id,
        Resolution::new(
            vec![ProposedEvent::new(
                event(653),
                EventTypeId::from("test.changed"),
                SchemaRevision::new(1),
                json!({"grandchild": true}),
            )],
            Vec::new(),
        ),
    )
    .expect("grandchild Event should validate");
    store
        .commit(&grandchild_tail, None, PlatformTime::new(17))
        .expect("grandchild should diverge");

    let parent_after = store.snapshot(timeline()).expect("parent after divergence");
    let child_after = store
        .snapshot(historical_child.target.timeline_id)
        .expect("child after divergence");
    let sibling_after = store
        .snapshot(sibling.target.timeline_id)
        .expect("sibling after divergence");
    let grandchild_after = store
        .snapshot(grandchild.target.timeline_id)
        .expect("grandchild after divergence");
    assert!(parent_after.world_view().entity(entity(651)).is_none());
    assert!(parent_after.world_view().entity(entity(652)).is_none());
    assert!(child_after.world_view().entity(entity(651)).is_some());
    assert!(child_after.world_view().entity(entity(652)).is_none());
    assert!(sibling_after.world_view().entity(entity(651)).is_none());
    assert!(sibling_after.world_view().entity(entity(652)).is_some());
    assert!(grandchild_after.world_view().entity(entity(651)).is_none());
    assert!(grandchild_after.world_view().entity(entity(652)).is_none());
    assert_eq!(
        parent_after
            .world_view()
            .facet(
                FacetOwner::entity(entity(10)),
                &FacetTypeId::from("test.facet"),
            )
            .expect("parent facet should exist")
            .value(),
        &json!({"branch": "parent"})
    );
    assert_eq!(
        child_after
            .world_view()
            .facet(
                FacetOwner::entity(entity(10)),
                &FacetTypeId::from("test.facet"),
            )
            .expect("child inherited facet should exist")
            .value(),
        &json!({"origin": "entity"})
    );

    let restarted_runtime = Runtime::new(&store, registry()).expect("Runtime should reassemble");
    let replay_after_restart = parent_after
        .replay_to(fork_point.version())
        .expect("restart replay should remain deterministic");
    assert_eq!(
        replay_after_restart
            .logical_state()
            .chronology_budget
            .consumed,
        1
    );
    let restarted_grandchild = restarted_runtime
        .fork(ForkTimelineRequest::new(grandchild.target))
        .await
        .expect("restarted Runtime should preserve grandchild ancestry");
    let restarted_snapshot = store
        .snapshot(restarted_grandchild.target.timeline_id)
        .expect("restarted grandchild child should be readable");
    assert!(
        restarted_snapshot
            .world_view()
            .entity(entity(651))
            .is_none()
    );
    assert!(
        restarted_snapshot
            .world_view()
            .entity(entity(652))
            .is_none()
    );
    assert_eq!(
        restarted_snapshot.ancestry().parent_timeline_id,
        Some(grandchild.target.timeline_id)
    );
    assert_ne!(
        parent_head.target.timeline_id, historical_child.target.timeline_id,
        "head and historical forks must allocate distinct branch identities"
    );
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the ancestry causality fixture keeps visible-prefix cases together"
)]
async fn ancestry_causal_links_follow_visible_branch_history_only() {
    let store = InMemoryStore::new();
    let source = timeline();
    let child = second_timeline();
    let sibling = id::<TimelineId>(6);
    store
        .create_timeline(world(), source)
        .expect("source Timeline should be created");
    let capabilities = registry();

    let root = validated(
        &store,
        &capabilities,
        Resolution::new(
            vec![
                ProposedEvent::new(
                    event(700),
                    EventTypeId::from("test.changed"),
                    SchemaRevision::new(1),
                    json!({"event": 700}),
                ),
                ProposedEvent::new(
                    event(701),
                    EventTypeId::from("test.changed"),
                    SchemaRevision::new(1),
                    json!({"event": 701}),
                ),
            ],
            Vec::new(),
        ),
    );
    store
        .commit(&root, None, PlatformTime::new(1))
        .expect("root history should commit");
    let root_version = store.snapshot(source).expect("root snapshot").version();
    TimelineForkStore::fork_timeline(&store, &TimelineFork::new(source, root_version, child))
        .await
        .expect("child fork should commit");
    TimelineForkStore::fork_timeline(&store, &TimelineFork::new(source, root_version, sibling))
        .await
        .expect("sibling fork should commit");

    let child_event = ProposedEvent::new(
        event(702),
        EventTypeId::from("test.changed"),
        SchemaRevision::new(1),
        json!({"event": 702}),
    )
    .with_causal_link(CausalLink::new(event(700)));
    let child_token = validated_at(
        &store,
        &capabilities,
        child,
        Resolution::new(vec![child_event], Vec::new()),
    )
    .expect("child may reference visible ancestor history");
    store
        .commit(&child_token, None, PlatformTime::new(2))
        .expect("child causal Event should commit");

    let parent_future = validated(
        &store,
        &capabilities,
        Resolution::new(
            vec![ProposedEvent::new(
                event(703),
                EventTypeId::from("test.changed"),
                SchemaRevision::new(1),
                json!({"event": 703}),
            )],
            Vec::new(),
        ),
    );
    store
        .commit(&parent_future, None, PlatformTime::new(3))
        .expect("parent future should commit independently");
    let future_reference = ProposedEvent::new(
        event(704),
        EventTypeId::from("test.changed"),
        SchemaRevision::new(1),
        json!({"event": 704}),
    )
    .with_causal_link(CausalLink::new(event(703)));
    assert!(
        validated_at(
            &store,
            &capabilities,
            child,
            Resolution::new(vec![future_reference], Vec::new()),
        )
        .is_err()
    );

    let sibling_reference = ProposedEvent::new(
        event(705),
        EventTypeId::from("test.changed"),
        SchemaRevision::new(1),
        json!({"event": 705}),
    )
    .with_causal_link(CausalLink::new(event(702)));
    assert!(
        validated_at(
            &store,
            &capabilities,
            sibling,
            Resolution::new(vec![sibling_reference], Vec::new()),
        )
        .is_err()
    );

    let child_snapshot = store.snapshot(child).expect("child snapshot");
    assert_eq!(
        child_snapshot
            .events
            .iter()
            .map(loom_runtime::CommittedEvent::event_ref)
            .collect::<Vec<_>>(),
        vec![
            EventRef::new(source, event(700)),
            EventRef::new(source, event(701)),
            EventRef::new(child, event(702)),
        ]
    );
    assert_eq!(
        store
            .snapshot(sibling)
            .expect("sibling snapshot")
            .events
            .iter()
            .map(loom_runtime::CommittedEvent::event_ref)
            .collect::<Vec<_>>(),
        vec![
            EventRef::new(source, event(700)),
            EventRef::new(source, event(701))
        ]
    );
}
