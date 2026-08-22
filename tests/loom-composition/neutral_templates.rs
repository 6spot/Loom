use loom_api::{
    ActionService, ApiErrorCode, EventQuery, HistoryService, TimelineService, WorldService,
};
use loom_composition_tests::neutral::{
    self, COUNTER_CAPABILITY, COUNTER_INCREMENT_WORK, OBSERVER_ACTION, OBSERVER_CAPABILITY,
    OBSERVER_EVENT,
};
use loom_core::{EntityId, EventId, WorldId, WorldInstant};
use loom_runtime::{ExecutionOrigin, ExecutionSessionStatus, ExecutionSessionStore, Runtime};
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
    let first_runtime = Runtime::new(&store, first_registry)
        .expect("neutral Runtime should assemble")
        .with_identity_allocator(neutral::FixedIdentityAllocator {
            world_id: first_world,
            timeline_id: first_timeline,
        });
    first_runtime
        .register_runtime_revision(revision)
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
