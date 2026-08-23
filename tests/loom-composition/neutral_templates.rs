use loom_api::{
    ActionService, ApiErrorCode, EventQuery, HistoryService, TimelineService, WorldService,
};
use loom_composition_tests::neutral::{
    self, COUNTER_CAPABILITY, COUNTER_INCREMENT_ACTION, COUNTER_INCREMENT_WORK, OBSERVER_ACTION,
    OBSERVER_CAPABILITY, OBSERVER_EVENT,
};
use loom_core::{EntityId, EventId, WorldId, WorldInstant};
use loom_runtime::{
    ExecutionOrigin, ExecutionSessionStatus, ExecutionSessionStore, PlatformTime, Runtime,
    RuntimeRevisionCapability, RuntimeRevisionDescriptor, RuntimeRevisionId, WorkStatus,
    WorkTarget,
};
use loom_storage::InMemoryStore;
use serde_json::json;

#[expect(
    clippy::too_many_lines,
    reason = "one acceptance scenario covers both Template births and their pinned evidence"
)]
#[tokio::test]
async fn neutral_template_revisions_pin_distinct_bindings_and_bootstrap_evidence() {
    let store = InMemoryStore::new();
    let entity_id = neutral::identity::<EntityId>(0x5101);
    let first_world = neutral::identity::<WorldId>(0x5110);
    let first_timeline = neutral::identity(0x5111);
    let second_world = neutral::identity::<WorldId>(0x5120);
    let second_timeline = neutral::identity(0x5121);

    let first_registry = neutral::registry();
    let revision = neutral::runtime_revision(&first_registry);
    let revision_two = RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("neutral-fixtures-r2"),
        PlatformTime::new(3),
        "neutral-fixtures-r2",
        revision.loom_version().clone(),
        first_registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("neutral-fixture-r2:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("neutral Runtime Revision R2 should be valid");
    let first_runtime = Runtime::new(&store, first_registry)
        .expect("neutral Runtime should assemble")
        .with_identity_allocator(neutral::FixedIdentityAllocator {
            world_id: first_world,
            timeline_id: first_timeline,
        });
    first_runtime
        .register_runtime_revision(revision.clone())
        .await
        .expect("neutral Runtime Revision should publish");
    first_runtime
        .activate_runtime_revision(
            "neutral-fixtures-r1".into(),
            None,
            loom_runtime::PlatformTime::new(2),
        )
        .await
        .expect("neutral Runtime Revision should activate");

    let first = first_runtime
        .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
            neutral::template_revision_one(
                WorldInstant::new(11),
                neutral::identity::<EventId>(0x5130),
                entity_id,
            ),
        ))
        .await
        .expect("Template revision one should create a World");
    let first_binding = store
        .read_binding(first_world)
        .expect("first World Binding should be inspectable");
    assert_eq!(first_binding.revision(), 1);
    assert_eq!(first_binding.template_provenance(), Some("neutral.world@1"));
    assert_eq!(first_binding.requirements().len(), 1);
    assert!(
        first_binding
            .requirements()
            .contains_key(&COUNTER_CAPABILITY.into())
    );
    assert!(
        !first_binding
            .requirements()
            .contains_key(&OBSERVER_CAPABILITY.into())
    );

    let first_history = first_runtime
        .list_events(EventQuery::all(first.target))
        .await
        .expect("first bootstrap history should be inspectable");
    assert_eq!(first_history.len(), 1);
    assert_eq!(first_history[0].occurred_at, WorldInstant::new(11));

    let disabled = first_runtime
        .invoke(loom_api::ActionRequest::new(
            first.target,
            loom_protocol::ActionInvocation::new(
                OBSERVER_ACTION.into(),
                json!({
                    "event_id": neutral::identity::<EventId>(0x5140).to_string(),
                    "entity_id": entity_id.to_string(),
                }),
            ),
        ))
        .await
        .expect_err("installed observer Action must be disabled for revision one");
    assert_eq!(disabled.code, ApiErrorCode::Unavailable);

    let second_registry = neutral::registry();
    let second_runtime = Runtime::new(&store, second_registry)
        .expect("second neutral Runtime should assemble")
        .with_identity_allocator(neutral::FixedIdentityAllocator {
            world_id: second_world,
            timeline_id: second_timeline,
        });
    let second = second_runtime
        .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
            neutral::template_revision_two(
                WorldInstant::new(22),
                neutral::identity::<EventId>(0x5150),
                neutral::identity::<EventId>(0x5160),
                entity_id,
            ),
        ))
        .await
        .expect("Template revision two should create a later World");
    let second_binding = store
        .read_binding(second_world)
        .expect("second World Binding should be inspectable");
    assert_eq!(second_binding.revision(), 2);
    assert_eq!(
        second_binding.template_provenance(),
        Some("neutral.world@2")
    );
    assert_eq!(second_binding.requirements().len(), 2);
    assert!(
        second_binding
            .requirements()
            .contains_key(&COUNTER_CAPABILITY.into())
    );
    assert!(
        second_binding
            .requirements()
            .contains_key(&OBSERVER_CAPABILITY.into())
    );

    let second_history = second_runtime
        .list_events(EventQuery::all(second.target))
        .await
        .expect("second bootstrap history should be inspectable");
    assert_eq!(second_history.len(), 2);
    assert!(
        second_history
            .iter()
            .all(|event| event.occurred_at == WorldInstant::new(22))
    );
    assert_eq!(second_history[1].event_type.as_str(), OBSERVER_EVENT);

    let sessions = ExecutionSessionStore::list_sessions(&store)
        .await
        .expect("bootstrap Session evidence should be inspectable");
    assert_eq!(sessions.len(), 2);
    assert!(
        sessions
            .iter()
            .all(|session| session.origin() == ExecutionOrigin::Runtime)
    );
    assert!(
        sessions
            .iter()
            .all(|session| session.status() == ExecutionSessionStatus::Committed)
    );
    let first_session = sessions
        .iter()
        .find(|session| session.assembly().binding().revision() == 1)
        .expect("revision one bootstrap Session should be present");
    let second_session = sessions
        .iter()
        .find(|session| session.assembly().binding().revision() == 2)
        .expect("revision two bootstrap Session should be present");
    assert_eq!(
        first_session
            .assembly()
            .runtime_revision()
            .revision()
            .id()
            .as_str(),
        "neutral-fixtures-r1"
    );
    assert_eq!(
        first_session
            .assembly()
            .implementations()
            .capabilities()
            .len(),
        1
    );
    assert_eq!(
        second_session
            .assembly()
            .implementations()
            .capabilities()
            .len(),
        2
    );
    assert_eq!(
        second_session
            .assembly()
            .implementations()
            .capability(&OBSERVER_CAPABILITY.into())
            .expect("observer implementation should be pinned")
            .implementation_id(),
        "neutral-fixture:neutral.observer@0.1.0"
    );

    assert_eq!(
        store
            .read_binding(first_world)
            .expect("first World Binding should remain readable"),
        first_binding,
        "a later Template revision must not mutate the existing World Binding"
    );

    let first_after_revision_two = first_runtime
        .inspect_timeline(first.target)
        .await
        .expect("first World should remain inspectable after revision two birth");
    assert_eq!(first_after_revision_two.world_time, WorldInstant::new(11));
    assert_eq!(first_after_revision_two.version, first.version);

    let first_r1_execution = first_runtime
        .invoke(loom_api::ActionRequest::new(
            first.target,
            loom_protocol::ActionInvocation::new(
                COUNTER_INCREMENT_ACTION.into(),
                json!({
                    "event_id": neutral::identity::<EventId>(0x5170).to_string(),
                    "entity_id": entity_id.to_string(),
                    "amount": 1,
                }),
            ),
        ))
        .await
        .expect("first neutral Action should execute under R1");
    assert!(first_r1_execution.is_committed());
    let first_history_after_r1 = first_runtime
        .list_events(EventQuery::all(first.target))
        .await
        .expect("first World history should remain readable after R1 execution");
    assert_eq!(first_history_after_r1.len(), 2);
    assert!(
        first_history_after_r1
            .iter()
            .all(|event| event.occurred_at == WorldInstant::new(11)),
        "ordinary Action commits must use pinned World Time"
    );

    first_runtime
        .register_runtime_revision(revision_two)
        .await
        .expect("neutral Runtime Revision R2 should publish");
    let r1_generation = first_runtime
        .active_runtime_revision()
        .await
        .expect("active Runtime Revision should remain readable")
        .expect("R1 should remain active before the switch")
        .generation();
    first_runtime
        .activate_runtime_revision(
            RuntimeRevisionId::from("neutral-fixtures-r2"),
            Some(r1_generation),
            PlatformTime::new(4),
        )
        .await
        .expect("compatible neutral Runtime Revision R2 should activate");

    let first_r2_execution = first_runtime
        .invoke(loom_api::ActionRequest::new(
            first.target,
            loom_protocol::ActionInvocation::new(
                COUNTER_INCREMENT_ACTION.into(),
                json!({
                    "event_id": neutral::identity::<EventId>(0x5180).to_string(),
                    "entity_id": entity_id.to_string(),
                    "amount": 1,
                }),
            ),
        ))
        .await
        .expect("next neutral Action should execute under R2");
    assert!(first_r2_execution.is_committed());
    let sessions_after_r2 = ExecutionSessionStore::list_sessions(&store)
        .await
        .expect("R1 and R2 Session evidence should be inspectable");
    let application_sessions = sessions_after_r2
        .iter()
        .filter(|session| session.origin() == ExecutionOrigin::Application)
        .collect::<Vec<_>>();
    assert_eq!(application_sessions.len(), 2);
    assert!(application_sessions.iter().any(|session| {
        session
            .assembly()
            .runtime_revision()
            .revision()
            .id()
            .as_str()
            == "neutral-fixtures-r1"
    }));
    assert!(application_sessions.iter().any(|session| {
        session
            .assembly()
            .runtime_revision()
            .revision()
            .id()
            .as_str()
            == "neutral-fixtures-r2"
    }));

    let incompatible_revision = RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("neutral-fixtures-incompatible"),
        PlatformTime::new(5),
        "neutral-fixtures-incompatible",
        revision.loom_version().clone(),
        std::iter::empty(),
    )
    .expect("empty incompatible Runtime Revision should be valid history metadata");
    first_runtime
        .register_runtime_revision(incompatible_revision)
        .await
        .expect("incompatible Runtime Revision should publish as immutable history");
    let r2_generation = first_runtime
        .active_runtime_revision()
        .await
        .expect("R2 active selection should remain readable")
        .expect("R2 should be active before incompatible activation")
        .generation();
    first_runtime
        .activate_runtime_revision(
            RuntimeRevisionId::from("neutral-fixtures-incompatible"),
            Some(r2_generation),
            PlatformTime::new(6),
        )
        .await
        .expect("incompatible Runtime Revision should activate as platform history");
    let binding_before_incompatible = store
        .read_binding(first_world)
        .expect("first World Binding should remain readable before incompatibility");
    let history_before_incompatible = first_runtime
        .list_events(EventQuery::all(first.target))
        .await
        .expect("first World history should remain readable before incompatibility");
    let session_count_before_incompatible = ExecutionSessionStore::list_sessions(&store)
        .await
        .expect("Session ledger should remain readable before incompatibility")
        .len();
    let unavailable = first_runtime
        .invoke(loom_api::ActionRequest::new(
            first.target,
            loom_protocol::ActionInvocation::new(
                COUNTER_INCREMENT_ACTION.into(),
                json!({
                    "event_id": neutral::identity::<EventId>(0x5190).to_string(),
                    "entity_id": entity_id.to_string(),
                    "amount": 1,
                }),
            ),
        ))
        .await
        .expect_err("incompatible active assembly must make execution unavailable");
    assert_eq!(unavailable.code, ApiErrorCode::Unavailable);
    assert_eq!(
        store
            .read_binding(first_world)
            .expect("incompatible execution must not remove the Binding"),
        binding_before_incompatible
    );
    assert_eq!(
        first_runtime
            .list_events(EventQuery::all(first.target))
            .await
            .expect("incompatible execution must not damage history"),
        history_before_incompatible
    );
    assert_eq!(
        ExecutionSessionStore::list_sessions(&store)
            .await
            .expect("incompatible execution must not start a Session")
            .len(),
        session_count_before_incompatible
    );
}

#[test]
fn neutral_registry_declares_work_and_reactions_without_running_a_scheduler() {
    let registry = neutral::registry();
    assert!(
        registry
            .work_handler(&COUNTER_INCREMENT_WORK.into())
            .is_some()
    );
    assert!(registry.reactions().any(|registered| {
        registered.reaction.event_type.as_str() == neutral::COUNTER_INCREMENTED_EVENT
            && registered.reaction.handler.as_str() == COUNTER_INCREMENT_WORK
    }));
    assert!(registry.reactions().any(|registered| {
        registered.reaction.event_type.as_str() == OBSERVER_EVENT
            && registered.reaction.handler.as_str() == neutral::OBSERVER_WORK
    }));
}

#[tokio::test]
async fn enabled_reaction_expands_to_atomic_immediate_work_and_chains() {
    let store = InMemoryStore::new();
    let world_id = neutral::identity::<WorldId>(0x5200);
    let timeline_id = neutral::identity(0x5201);
    let entity_id = neutral::identity::<EntityId>(0x5202);
    let trigger_event_id = neutral::identity::<EventId>(0x5203);
    let runtime = Runtime::new(&store, neutral::registry())
        .expect("neutral Runtime should assemble")
        .with_identity_allocator(neutral::FixedIdentityAllocator {
            world_id,
            timeline_id,
        });

    let target = runtime
        .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
            neutral::template_revision_one(
                WorldInstant::new(7),
                neutral::identity(0x5204),
                entity_id,
            ),
        ))
        .await
        .expect("neutral World should be created")
        .target;

    runtime
        .invoke(loom_api::ActionRequest::new(
            target,
            loom_protocol::ActionInvocation::new(
                COUNTER_INCREMENT_ACTION.into(),
                json!({
                    "event_id": trigger_event_id.to_string(),
                    "entity_id": entity_id.to_string(),
                    "amount": 1,
                }),
            ),
        ))
        .await
        .expect("increment Action should commit with its Reaction Work");

    let after_action = store
        .snapshot(timeline_id)
        .expect("Timeline snapshot should be readable");
    assert_eq!(after_action.events.len(), 2);
    assert_eq!(after_action.works.len(), 1);
    let reaction_work = &after_action.works[0];
    assert_eq!(reaction_work.status, WorkStatus::Pending);
    assert_eq!(reaction_work.effective_due_world_time, WorldInstant::new(7));
    assert_eq!(reaction_work.logical_schedule_order, 1);
    assert_eq!(reaction_work.causal_event_id, Some(trigger_event_id));
    assert_eq!(reaction_work.origin_work_id, None);
    assert!(matches!(
        reaction_work.target,
        WorkTarget::CapabilityWork { .. }
    ));
    let generated_event_id = reaction_work
        .payload
        .get("event_id")
        .and_then(serde_json::Value::as_str)
        .expect("Reaction Work should carry a fresh handler Event identity")
        .parse::<EventId>()
        .expect("Reaction Work Event identity should be valid");
    assert_ne!(generated_event_id, trigger_event_id);
    assert_eq!(reaction_work.payload["amount"], json!(1));

    runtime
        .execute_work(
            target,
            reaction_work.id,
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(1),
        )
        .await
        .expect("Reaction Work should execute through the normal Work path");

    let after_work = store
        .snapshot(timeline_id)
        .expect("Timeline snapshot after Reaction Work should be readable");
    assert_eq!(after_work.events.len(), 3);
    assert_eq!(after_work.works.len(), 2);
    assert_eq!(after_work.works[0].status, WorkStatus::Completed);
    let chained_work = after_work
        .works
        .iter()
        .find(|work| work.status == WorkStatus::Pending)
        .expect("the committed Event should schedule the next Reaction Work");
    assert_eq!(chained_work.origin_work_id, Some(reaction_work.id));
    assert_eq!(chained_work.causal_event_id, Some(generated_event_id));
    assert_eq!(chained_work.effective_due_world_time, WorldInstant::new(7));
    assert_eq!(chained_work.logical_schedule_order, 2);
    assert_eq!(after_work.chronology_budget().consumed, 1);
}
