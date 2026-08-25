#![allow(
    clippy::too_many_lines,
    clippy::len_zero,
    clippy::unneeded_struct_pattern
)]
use loom_agency::{DeterministicCognitiveExecutor, DeterministicCognitiveStep, ExecutionPolicy};
use loom_api::{
    ActionRequest, ActionService, AdminScheduleAgencyWakeRequest, AdminService, ApiErrorCode,
    CatalogService, ChangeFeedCursor, EventQuery, FacetQuery, HistoryService, IngressEnvelope,
    IngressService, QueryService, SubscriptionRequest, SubscriptionService, TimelineService,
    WorldService,
};
use loom_composition_tests::neutral::{
    self, BLOB_ATTACH_ACTION, BLOB_FACET, COUNTER_FACET, COUNTER_INCREMENT_ACTION,
    COUNTER_SEED_ACTION, LINK_CREATE_ACTION, LINK_RELATIONSHIP, SEMANTIC_INDEX_ID,
};
use loom_core::{
    EntityId, EventId, FacetOwner, FacetTypeId, RelationshipId, TimelineVersion, WorkId, WorldId,
    WorldInstant,
};
use loom_protocol::ActionInvocation;
use loom_runtime::{BlobStore, ExecutionSessionStore, PlatformTime, Runtime, WorkStatus};
use loom_storage::{InMemoryBlobStore, InMemoryStore};
use serde_json::json;

fn entity(value: u128) -> EntityId {
    neutral::identity(value)
}
fn world(value: u128) -> WorldId {
    neutral::identity(value)
}
fn timeline(value: u128) -> loom_core::TimelineId {
    neutral::identity(value)
}
fn event(value: u128) -> EventId {
    neutral::identity(value)
}
fn rel(value: u128) -> RelationshipId {
    neutral::identity(value)
}
fn work(value: u128) -> WorkId {
    neutral::identity(value)
}

#[tokio::test]
async fn neutral_v0_public_workflows_via_api() {
    let store = InMemoryStore::new();
    let entity_id = entity(0x5101);
    let other_entity = entity(0x5102);
    let first_world = world(0x5110);
    let first_timeline = timeline(0x5111);
    let second_world = world(0x5120);
    let second_timeline = timeline(0x5121);

    let catalog_global = {
        let rt = Runtime::new(&store, neutral::registry()).expect("runtime should assemble");
        rt.catalog().expect("global catalog should be readable")
    };
    assert!(
        catalog_global
            .capabilities
            .iter()
            .any(|c| c.id.as_str() == neutral::COUNTER_CAPABILITY)
    );
    assert!(
        catalog_global
            .capabilities
            .iter()
            .any(|c| c.id.as_str() == neutral::OBSERVER_CAPABILITY)
    );
    assert!(
        catalog_global
            .facets
            .iter()
            .any(|f| f.id.as_str() == COUNTER_FACET)
    );
    assert!(
        catalog_global
            .facets
            .iter()
            .any(|f| f.id.as_str() == BLOB_FACET)
    );
    assert!(
        catalog_global
            .relationships
            .iter()
            .any(|r| r.id.as_str() == LINK_RELATIONSHIP)
    );
    assert!(
        catalog_global
            .semantic_indexes
            .iter()
            .any(|i| i.id.as_str() == SEMANTIC_INDEX_ID)
    );
    assert!(
        catalog_global
            .actions
            .iter()
            .any(|a| a.id.as_str() == LINK_CREATE_ACTION)
    );
    assert!(
        catalog_global
            .actions
            .iter()
            .any(|a| a.id.as_str() == BLOB_ATTACH_ACTION)
    );

    let runtime_one = Runtime::new(&store, neutral::registry())
        .expect("runtime one")
        .with_identity_allocator(neutral::FixedIdentityAllocator {
            world_id: first_world,
            timeline_id: first_timeline,
        });

    let w1 = runtime_one
        .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
            neutral::template_revision_one(WorldInstant::new(11), event(0x5130), entity_id),
        ))
        .await
        .expect("revision one birth");

    let scoped_one = runtime_one
        .catalog_for_world(first_world)
        .await
        .expect("scoped catalog")
        .clone();
    assert!(
        scoped_one
            .capabilities
            .iter()
            .any(|c| c.id.as_str() == neutral::COUNTER_CAPABILITY)
    );
    assert!(
        !scoped_one
            .capabilities
            .iter()
            .any(|c| c.id.as_str() == neutral::OBSERVER_CAPABILITY)
    );

    let disabled = runtime_one
        .invoke(ActionRequest::new(
            w1.target,
            ActionInvocation::new(
                neutral::OBSERVER_ACTION.into(),
                json!({"event_id": event(0x5140).to_string(), "entity_id": entity_id.to_string()}),
            ),
        ))
        .await
        .expect_err("observer must be disabled");
    assert_eq!(disabled.code, ApiErrorCode::Unavailable);

    let runtime_two = Runtime::new(&store, neutral::registry())
        .expect("runtime two")
        .with_identity_allocator(neutral::FixedIdentityAllocator {
            world_id: second_world,
            timeline_id: second_timeline,
        });
    let w2 = runtime_two
        .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
            neutral::template_revision_two(
                WorldInstant::new(22),
                event(0x5150),
                event(0x5160),
                entity_id,
            ),
        ))
        .await
        .expect("revision two birth");
    assert_eq!(w1.target.world_id, first_world);
    assert_eq!(w2.target.world_id, second_world);
    assert_ne!(w1.target.timeline_id, w2.target.timeline_id);
    let h1 = runtime_one
        .list_events(EventQuery::all(w1.target))
        .await
        .expect("h1");
    let h2 = runtime_two
        .list_events(EventQuery::all(w2.target))
        .await
        .expect("h2");
    assert_eq!(h1.len(), 1);
    assert_eq!(h2.len(), 2);
    assert!(h2.iter().all(|e| e.occurred_at == WorldInstant::new(22)));

    let second_entity_seed = runtime_one
        .invoke(ActionRequest::new(
            w1.target,
            ActionInvocation::new(
                COUNTER_SEED_ACTION.into(),
                json!({
                    "event_id": event(0x5171).to_string(),
                    "entity_id": other_entity.to_string(),
                    "value": 7
                }),
            ),
        ))
        .await
        .expect("second entity seed should commit");
    assert!(second_entity_seed.is_committed());

    let link_id = rel(0x6001);
    let link_result = runtime_one
        .invoke(ActionRequest::new(
            w1.target,
            ActionInvocation::new(
                LINK_CREATE_ACTION.into(),
                json!({
                    "event_id": event(0x5172).to_string(),
                    "relationship_id": link_id.to_string(),
                    "left_entity": entity_id.to_string(),
                    "right_entity": other_entity.to_string()
                }),
            ),
        ))
        .await
        .expect("link create should commit via public API");
    assert!(link_result.is_committed());

    let counter_facet = runtime_one
        .get_facet(FacetQuery::new(
            w1.target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from(COUNTER_FACET),
        ))
        .await
        .expect("facet get")
        .expect("facet exists");
    assert_eq!(counter_facet.value, json!({"value": 1}));

    let scoped_two = runtime_two
        .catalog_for_world(second_world)
        .await
        .expect("scoped two");
    assert!(
        scoped_two
            .capabilities
            .iter()
            .any(|c| c.id.as_str() == neutral::OBSERVER_CAPABILITY)
    );
    assert!(
        scoped_two
            .semantic_indexes
            .iter()
            .any(|i| i.id.as_str() == SEMANTIC_INDEX_ID)
    );

    let blob_store = InMemoryBlobStore::new();
    let blob_ref = blob_store
        .put(b"neutral-blob-demo", Some("text/plain"))
        .await
        .expect("blob put should succeed");
    let blob_hash = "sha256:neutral-blob-demo";
    let blob_obj = blob_store.read(&blob_ref).await.expect("blob read");
    assert_eq!(blob_obj.bytes, b"neutral-blob-demo");

    let blob_attach = runtime_one
        .invoke(ActionRequest::new(
            w1.target,
            ActionInvocation::new(
                BLOB_ATTACH_ACTION.into(),
                json!({
                    "event_id": event(0x5173).to_string(),
                    "entity_id": entity_id.to_string(),
                    "hash": blob_hash,
                    "media_type": "text/plain"
                }),
            ),
        ))
        .await
        .expect("blob attach should commit");
    assert!(blob_attach.is_committed());
    let blob_facet = runtime_one
        .get_facet(FacetQuery::new(
            w1.target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from(BLOB_FACET),
        ))
        .await
        .expect("blob facet")
        .expect("blob facet exists");
    assert_eq!(blob_facet.value["hash"], json!(blob_hash));

    // Semantic retrieval via generic SemanticProjectionStore public Runtime boundary
    // (real retrieval, not just catalog discovery): register catalog-consistent
    // projection, rebuild deterministic rows from fixed committed EventRefs, and
    // query with bounded limits asserting hit ordering/source.
    {
        use loom_core::{EventRef, SchemaRevision};
        use loom_runtime::{
            SemanticIndexMetric, SemanticIndexSource, SemanticProjectionKey,
            SemanticProjectionQuery, SemanticProjectionRebuild, SemanticProjectionRegistration,
            SemanticProjectionRow,
        };
        let key = SemanticProjectionKey::new(
            w1.target.world_id,
            w1.target.timeline_id,
            SEMANTIC_INDEX_ID.into(),
        );
        let registration = SemanticProjectionRegistration::new(
            key.clone(),
            SemanticIndexSource::new("facet", COUNTER_FACET, SchemaRevision::new(1)),
            SchemaRevision::new(1),
            1,
            "neutral-model-1",
            2,
            SemanticIndexMetric::Cosine,
        )
        .expect("neutral projection registration should be valid");
        runtime_one
            .register_semantic_projection(registration.clone())
            .await
            .expect("projection should register");
        let snap_before = store
            .snapshot(w1.target.timeline_id)
            .expect("snap before projection");
        // Two deterministic rows from fixed committed EventRefs (seed and increment will be second)
        // Use already committed seed 0x5130 and the just attached blob event 0x5173 as sources.
        let rows = vec![
            SemanticProjectionRow::new(
                EventRef::new(w1.target.timeline_id, event(0x5130)),
                "neutral-counter-5101-v1",
                snap_before.version(),
                1,
                "neutral-model-1",
                vec![1.0, 0.0],
            )
            .expect("row 1 should be valid"),
            SemanticProjectionRow::new(
                EventRef::new(w1.target.timeline_id, event(0x5173)),
                "neutral-counter-5101-v2",
                snap_before.version(),
                1,
                "neutral-model-1",
                vec![0.0, 1.0],
            )
            .expect("row 2 should be valid"),
        ];
        runtime_one
            .rebuild_semantic_projection(
                &SemanticProjectionRebuild::new(registration.clone(), None, rows)
                    .expect("rebuild should be valid"),
            )
            .await
            .expect("rebuild should succeed");
        let query = SemanticProjectionQuery::new(
            key.clone(),
            SchemaRevision::new(1),
            1,
            "neutral-model-1",
            vec![1.0, 0.0],
            2,
        )
        .expect("bounded query should be valid");
        let hits = runtime_one
            .query_semantic_projection(query.clone())
            .await
            .expect("query should succeed");
        assert_eq!(hits.len(), 2);
        assert_eq!(
            hits[0].source_ref,
            EventRef::new(w1.target.timeline_id, event(0x5130))
        );
        assert_eq!(
            hits[1].source_ref,
            EventRef::new(w1.target.timeline_id, event(0x5173))
        );
        // Bounded limit check: limit 1 returns only the nearest hit.
        let limited = SemanticProjectionQuery::new(
            key,
            SchemaRevision::new(1),
            1,
            "neutral-model-1",
            vec![1.0, 0.0],
            1,
        )
        .expect("limited query");
        let limited_hits = runtime_one
            .query_semantic_projection(limited)
            .await
            .expect("limited query should succeed");
        assert_eq!(limited_hits.len(), 1);
        assert_eq!(
            limited_hits[0].source_ref,
            EventRef::new(w1.target.timeline_id, event(0x5130))
        );
        // Authority version must not change after projection materialization.
        let snap_after = store
            .snapshot(w1.target.timeline_id)
            .expect("snap after projection");
        assert_eq!(snap_before.version(), snap_after.version());
        assert_eq!(snap_before.events, snap_after.events);
    }

    let inc_event = event(0x5174);
    let inc = runtime_one
        .invoke(ActionRequest::new(
            w1.target,
            ActionInvocation::new(
                COUNTER_INCREMENT_ACTION.into(),
                json!({"event_id": inc_event.to_string(), "entity_id": entity_id.to_string(), "amount": 2}),
            ),
        ))
        .await
        .expect("increment should commit and schedule Reaction");
    assert!(inc.is_committed());

    let all_events = runtime_one
        .list_events(EventQuery::all(w1.target))
        .await
        .expect("all events");
    assert!(all_events.iter().any(|e| e.id == inc_event));
    let page = runtime_one
        .list_events_page(EventQuery::all(w1.target))
        .await
        .expect("page");
    assert_eq!(page.events.len(), all_events.len());
    let fetched = runtime_one
        .get_event(loom_core::EventRef::new(w1.target.timeline_id, inc_event))
        .await
        .expect("get event")
        .expect("event exists");
    assert_eq!(fetched.id, inc_event);
    let trajectory = runtime_one
        .entity_trajectory(loom_api::EntityTrajectoryQuery::all(w1.target, entity_id))
        .await
        .expect("trajectory");
    assert!(trajectory.events.len() <= all_events.len());

    let feed = runtime_one
        .subscribe(SubscriptionRequest::new(w1.target, 10))
        .await
        .expect("subscribe");
    match feed {
        loom_api::SubscriptionResult::Events(page) => assert!(!page.events.is_empty()),
        other => panic!("unexpected feed result {other:?}"),
    }
    let cursor = ChangeFeedCursor::after(w1.target, 1.into());
    let resumed = runtime_one
        .subscribe(SubscriptionRequest::resume(w1.target, cursor, 10))
        .await
        .expect("resume");
    assert!(matches!(
        resumed,
        loom_api::SubscriptionResult::Events(_)
            | loom_api::SubscriptionResult::Resumed(_)
            | loom_api::SubscriptionResult::Backpressure(_)
    ));

    let ingress_envelope = IngressEnvelope::new(
        loom_api::IngressId::from("neutral-ingress-1"),
        loom_api::IdempotencyKey::from("neutral-key-1"),
        loom_api::IngressProvenance::new("neutral-example"),
        w1.target,
        loom_api::IngressAuthorizationContext::new(json!({})),
        loom_api::IngressTimeMetadata::none(),
        ActionInvocation::new(
            COUNTER_INCREMENT_ACTION.into(),
            json!({"event_id": event(0x5175).to_string(), "entity_id": entity_id.to_string(), "amount": 1}),
        ),
    );
    let acceptance = runtime_one
        .submit_ingress(ingress_envelope)
        .await
        .expect("ingress submit");
    assert!(acceptance.is_accepted() || acceptance.is_deduplicated());
    let status = runtime_one
        .ingress_status(loom_api::IngressId::from("neutral-ingress-1"))
        .await
        .expect("ingress status");
    assert!(matches!(
        status.status,
        loom_api::IngressStatus::Accepted
            | loom_api::IngressStatus::Processing
            | loom_api::IngressStatus::Retryable(_)
            | loom_api::IngressStatus::Completed(_)
            | loom_api::IngressStatus::Failed(_)
    ));

    let inspected = runtime_one
        .inspect_timeline(w1.target)
        .await
        .expect("inspect");
    assert_eq!(inspected.target, w1.target);
    // Use a fresh Runtime without FixedIdentityAllocator for fork allocation.
    let fork_helper = Runtime::new(&store, neutral::registry()).expect("fork helper");
    let forked = fork_helper
        .fork(loom_api::ForkTimelineRequest::new(w1.target))
        .await
        .expect("fork");
    assert_ne!(forked.target.timeline_id, w1.target.timeline_id);
    assert_eq!(forked.target.world_id, w1.target.world_id);
    let forked_history = fork_helper
        .list_events(EventQuery::all(forked.target))
        .await
        .expect("forked history");
    let source_history = runtime_one
        .list_events(EventQuery::all(w1.target))
        .await
        .expect("source history");
    assert_eq!(forked_history.len(), source_history.len());
}

#[tokio::test]
async fn neutral_v0_restart_keeps_binding_and_history() {
    let store = InMemoryStore::new();
    let entity_id = entity(0x5101);
    let world_id = world(0x5200);
    let timeline_id = timeline(0x5201);

    {
        let rt = Runtime::new(&store, neutral::registry())
            .expect("first runtime")
            .with_identity_allocator(neutral::FixedIdentityAllocator {
                world_id,
                timeline_id,
            });
        let created = rt
            .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
                neutral::template_revision_one(WorldInstant::new(11), event(0x5301), entity_id),
            ))
            .await
            .expect("birth");
        let other = entity(0x5202);
        rt.invoke(ActionRequest::new(
            created.target,
            ActionInvocation::new(
                COUNTER_SEED_ACTION.into(),
                json!({"event_id": event(0x5302).to_string(), "entity_id": other.to_string(), "value": 5}),
            ),
        ))
        .await
        .expect("seed other");
        rt.invoke(ActionRequest::new(
            created.target,
            ActionInvocation::new(
                LINK_CREATE_ACTION.into(),
                json!({
                    "event_id": event(0x5303).to_string(),
                    "relationship_id": rel(0x6101).to_string(),
                    "left_entity": entity_id.to_string(),
                    "right_entity": other.to_string()
                }),
            ),
        ))
        .await
        .expect("link");
        let blob_hash = "sha256:restart-blob";
        rt.invoke(ActionRequest::new(
            created.target,
            ActionInvocation::new(
                BLOB_ATTACH_ACTION.into(),
                json!({"event_id": event(0x5304).to_string(), "entity_id": entity_id.to_string(), "hash": blob_hash, "media_type": "text/plain"}),
            ),
        ))
        .await
        .expect("blob attach");
    }

    let rt_restarted = Runtime::new(&store, neutral::registry()).expect("restarted runtime");
    let target = loom_api::TimelineTarget::new(world_id, timeline_id);
    let binding_before = store
        .read_binding(world_id)
        .expect("binding should be present");
    assert_eq!(binding_before.revision(), 1);
    assert_eq!(
        binding_before.template_provenance(),
        Some("neutral.world@1")
    );
    let history = rt_restarted
        .list_events(EventQuery::all(target))
        .await
        .expect("history after restart");
    assert_eq!(history.len(), 4);
    assert!(
        history
            .iter()
            .all(|e| e.occurred_at == WorldInstant::new(11))
    );
    let facet = rt_restarted
        .get_facet(FacetQuery::new(
            target,
            FacetOwner::entity(entity_id),
            FacetTypeId::from(BLOB_FACET),
        ))
        .await
        .expect("facet after restart")
        .expect("blob facet survives restart");
    assert_eq!(facet.value["media_type"], json!("text/plain"));
    let sessions = ExecutionSessionStore::list_sessions(&store)
        .await
        .expect("sessions");
    assert!(
        sessions
            .iter()
            .any(|s| s.assembly().binding().revision() == 1)
    );
}

#[tokio::test]
async fn neutral_v0_replay_and_fork_are_deterministic() {
    let store = InMemoryStore::new();
    let entity_id = entity(0x5101);
    let world_id = world(0x5300);
    let timeline_id = timeline(0x5301);
    let rt = Runtime::new(&store, neutral::registry())
        .expect("runtime")
        .with_identity_allocator(neutral::FixedIdentityAllocator {
            world_id,
            timeline_id,
        });
    let created = rt
        .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
            neutral::template_revision_one(WorldInstant::new(11), event(0x5401), entity_id),
        ))
        .await
        .expect("birth");
    let inc1 = event(0x5402);
    rt.invoke(ActionRequest::new(
        created.target,
        ActionInvocation::new(
            COUNTER_INCREMENT_ACTION.into(),
            json!({"event_id": inc1.to_string(), "entity_id": entity_id.to_string(), "amount": 2}),
        ),
    ))
    .await
    .expect("increment 1");

    let snapshot = store.snapshot(timeline_id).expect("snapshot");
    let pending = snapshot
        .works
        .iter()
        .find(|w| w.status == WorkStatus::Pending)
        .expect("reaction work pending")
        .clone();
    rt.execute_work(
        created.target,
        pending.id,
        PlatformTime::new(0),
        PlatformTime::new(10),
        PlatformTime::new(1),
    )
    .await
    .expect("reaction work should execute");
    let after_work = store.snapshot(timeline_id).expect("after work");
    assert_eq!(after_work.events.len(), 3);
    assert_eq!(after_work.works.len(), 2);

    let replay_target = TimelineVersion::new(1.into(), 1.into());
    let snap_for_replay = store.snapshot(timeline_id).expect("snapshot for replay");
    let replayed = snap_for_replay
        .replay_to(replay_target)
        .expect("replay should be deterministic");
    let replayed_again = snap_for_replay
        .replay_to(replay_target)
        .expect("second replay");
    assert_eq!(
        replayed.logical_state().version,
        replayed_again.logical_state().version
    );
    assert_eq!(replayed.logical_state().version, replay_target);

    let fork_rt = Runtime::new(&store, neutral::registry()).expect("fork runtime helper");
    let forked = fork_rt
        .fork(loom_api::ForkTimelineRequest::new(created.target))
        .await
        .expect("fork should succeed");
    let forked_snap = store
        .snapshot(forked.target.timeline_id)
        .expect("forked snapshot");
    assert_eq!(forked_snap.events.len(), after_work.events.len());
    let fork_inner = Runtime::new(&store, neutral::registry()).expect("fork inner");
    fork_inner
        .invoke(ActionRequest::new(
            forked.target,
            ActionInvocation::new(
                COUNTER_INCREMENT_ACTION.into(),
                json!({"event_id": event(0x5403).to_string(), "entity_id": entity_id.to_string(), "amount": 10}),
            ),
        ))
        .await
        .expect("fork increment");
    let source_after_fork = store.snapshot(timeline_id).expect("source snap after fork");
    let fork_after = store
        .snapshot(forked.target.timeline_id)
        .expect("fork snap after");
    assert_ne!(source_after_fork.events.len(), fork_after.events.len());
    assert_eq!(source_after_fork.events.len(), 3);
    assert_eq!(fork_after.events.len(), 4);
}

#[tokio::test]
async fn neutral_v0_agency_deterministic_without_vendor_credentials() {
    let store = InMemoryStore::new();
    let agent = entity(0x5101);
    let world_id = world(0x5400);
    let timeline_id = timeline(0x5401);
    // Use a blob-attach Act that has no Reaction, so the agency wake completes without
    // leaving a pending Reaction head that would block the second wake.
    let fake = DeterministicCognitiveExecutor::new([DeterministicCognitiveStep::act(
        ActionInvocation::new(
            BLOB_ATTACH_ACTION.into(),
            json!({
                "event_id": event(0x5501).to_string(),
                "entity_id": agent.to_string(),
                "hash": "sha256:agency-blob",
                "media_type": "text/plain"
            }),
        ),
    )]);

    let rt = Runtime::new(&store, neutral::registry())
        .expect("runtime")
        .with_identity_allocator(neutral::FixedIdentityAllocator {
            world_id,
            timeline_id,
        })
        .with_cognitive_executor(fake)
        .with_cognitive_policy(ExecutionPolicy::default());

    let created = rt
        .create_world_from_template(loom_api::CreateWorldFromTemplateRequest::new(
            neutral::template_revision_one(WorldInstant::new(11), event(0x5502), agent),
        ))
        .await
        .expect("birth with agent entity");

    let initial = store.snapshot(timeline_id).expect("initial snapshot");
    let wake_id = work(0x7001);
    let _scheduled = AdminService::schedule_agency_wake(
        &rt,
        AdminScheduleAgencyWakeRequest {
            target: created.target,
            expected_version: initial.version(),
            work_id: wake_id,
            agent,
            cognition: "deterministic.fake".to_string(),
            payload: json!({"goal": "neutral-demo"}),
            schedule: loom_protocol::WorkSchedule::Immediate,
        },
    )
    .await
    .expect("wake schedule should commit via public Admin API");

    let execution = rt
        .execute_work(
            created.target,
            wake_id,
            PlatformTime::new(0),
            PlatformTime::new(10),
            PlatformTime::new(1),
        )
        .await
        .expect("agency wake should execute via deterministic fake");

    assert!(matches!(
        execution,
        loom_api::ExecutionResult::Committed { .. }
    ));
    let facet = rt
        .get_facet(FacetQuery::new(
            created.target,
            FacetOwner::entity(agent),
            FacetTypeId::from(BLOB_FACET),
        ))
        .await
        .expect("facet")
        .expect("facet after agency");
    assert_eq!(facet.value["hash"], json!("sha256:agency-blob"));

    let sessions = ExecutionSessionStore::list_sessions(&store)
        .await
        .expect("sessions");
    let wake_session = sessions
        .iter()
        .find(|s| s.cognitive_evidence().len() > 0)
        .expect("agency session should exist");
    let evidence = wake_session.cognitive_evidence();
    assert_eq!(evidence.observations().len(), 1);
    assert_eq!(
        evidence.observations()[0].metadata.executor.id,
        "deterministic.fake"
    );
    assert!(evidence.observations()[0].metadata.provider.is_none());
    let current = store.snapshot(timeline_id).expect("final snapshot");
    assert_eq!(
        current
            .works
            .iter()
            .find(|w| w.id == wake_id)
            .expect("wake")
            .status,
        WorkStatus::Completed
    );
    let wake2 = work(0x7002);
    let v = current.version();
    let rt_noop = Runtime::new(&store, neutral::registry())
        .expect("noop runtime")
        .with_cognitive_executor(DeterministicCognitiveExecutor::new([
            DeterministicCognitiveStep::no_action(),
        ]));
    AdminService::schedule_agency_wake(
        &rt_noop,
        AdminScheduleAgencyWakeRequest {
            target: created.target,
            expected_version: v,
            work_id: wake2,
            agent,
            cognition: "deterministic.fake".to_string(),
            payload: json!({"goal": "noop"}),
            schedule: loom_protocol::WorkSchedule::Immediate,
        },
    )
    .await
    .expect("second wake schedule");
    let result2 = rt_noop
        .execute_work(
            created.target,
            wake2,
            PlatformTime::new(1),
            PlatformTime::new(11),
            PlatformTime::new(2),
        )
        .await
        .expect("noop wake");
    assert!(matches!(
        result2,
        loom_api::ExecutionResult::Committed { .. } | loom_api::ExecutionResult::NoChange
    ));
}
