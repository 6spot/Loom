mod support;

use std::str::FromStr;

use loom_api::{ApiErrorCode, ForkTimelineRequest, TimelineTarget};
use loom_capability::CapabilityRegistry;
use loom_core::{
    Entity, EventId, EventRef, EventSeq, StateRevision, TimelineId, TimelineVersion, WorldId,
    WorldInstant,
};
use loom_runtime::{
    BaseWorldSnapshot, ChronologyBudgetState, CommittedEvent, ForkMaterialization, Runtime,
    TimelineFork, TimelineForkStore, WorldStore,
};
use support::TestDatabase;

fn id<T>(value: u128) -> T
where
    T: FromStr,
    T::Err: std::fmt::Debug,
{
    format!("00000000-0000-0000-0000-{value:012x}")
        .parse()
        .expect("test identity should parse")
}

async fn seed_world(pool: &sqlx::PgPool, world_id: WorldId, timeline_id: TimelineId) {
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
        .bind(world_id.to_string())
        .execute(pool)
        .await
        .expect("fork fixture World should insert");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(timeline_id.to_string())
        .bind(world_id.to_string())
        .execute(pool)
        .await
        .expect("fork fixture Timeline should insert");
}

async fn insert_event(pool: &sqlx::PgPool, timeline_id: TimelineId, event_id: EventId, seq: u64) {
    sqlx::query(
        "INSERT INTO loom_event \\
         (timeline_id, event_id, event_seq, event_type, schema_revision, occurred_at, payload, effects) \\
         VALUES ($1::uuid, $2::uuid, $3::numeric, 'test.history.event', 1, 0, '{}'::jsonb, '[]'::jsonb)",
    )
    .bind(timeline_id.to_string())
    .bind(event_id.to_string())
    .bind(seq.to_string())
    .execute(pool)
    .await
    .expect("history Event should insert");
}

fn refs(events: &[CommittedEvent]) -> Vec<EventRef> {
    events.iter().map(CommittedEvent::event_ref).collect()
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the PostgreSQL ancestry round-trip fixture is intentionally linear"
)]
async fn postgres_18_current_head_fork_round_trip_preserves_qualified_ancestor_event_ref() {
    let Some(database) = TestDatabase::provision("fork_event_ref").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id = id::<WorldId>(0x5101);
    let timeline_a = id::<TimelineId>(0x5102);
    let timeline_b = id::<TimelineId>(0x5103);
    let timeline_c = id::<TimelineId>(0x5104);
    let event_id = id::<EventId>(0x5110);

    seed_world(&pool, world_id, timeline_a).await;
    sqlx::query(
        "UPDATE loom_timeline SET head_event_seq = 1, state_revision = 1 WHERE timeline_id = $1::uuid",
    )
    .bind(timeline_a.to_string())
    .execute(&pool)
    .await
    .expect("non-default source version should update");
    sqlx::query(
        "INSERT INTO loom_event \
         (timeline_id, event_id, event_seq, event_type, schema_revision, occurred_at, payload, effects) \
         VALUES ($1::uuid, $2::uuid, 1, 'test.fork.event', 1, 0, '{}'::jsonb, '[]'::jsonb)",
    )
    .bind(timeline_a.to_string())
    .bind(event_id.to_string())
    .execute(&pool)
    .await
    .expect("source Event should insert");

    let source_before = WorldStore::snapshot(&storage, timeline_a)
        .await
        .expect("source snapshot should read");
    assert_eq!(
        source_before.version(),
        TimelineVersion::new(EventSeq::new(1), StateRevision::new(1))
    );

    let child_b = TimelineForkStore::fork_timeline(
        &storage,
        &TimelineFork::new(timeline_a, source_before.version(), timeline_b),
    )
    .await
    .expect("A to B fork should commit");
    assert_eq!(
        refs(&child_b.events),
        vec![EventRef::new(timeline_a, event_id)]
    );
    assert_eq!(
        child_b.ancestry().parent_timeline_id,
        Some(timeline_a),
        "the direct parent must remain A"
    );
    assert_eq!(
        child_b.ancestry().fork_parent_event,
        Some(EventRef::new(timeline_a, event_id))
    );
    let retried_child_b = TimelineForkStore::fork_timeline(
        &storage,
        &TimelineFork::new(timeline_a, source_before.version(), timeline_b),
    )
    .await
    .expect("retrying the same child identity should be idempotent");
    assert_eq!(retried_child_b.ancestry(), child_b.ancestry());

    storage.close().await;
    let restarted = database.storage().await;
    let b_after_restart = WorldStore::snapshot(&restarted, timeline_b)
        .await
        .expect("B ancestry should survive adapter restart");
    assert_eq!(
        b_after_restart.ancestry().parent_timeline_id,
        Some(timeline_a)
    );
    assert_eq!(
        b_after_restart.ancestry().fork_parent_event,
        Some(EventRef::new(timeline_a, event_id))
    );

    let child_c = TimelineForkStore::fork_timeline(
        &restarted,
        &TimelineFork::new(timeline_b, b_after_restart.version(), timeline_c),
    )
    .await
    .expect("B to C fork should commit");
    assert_eq!(
        refs(&child_c.events),
        vec![EventRef::new(timeline_a, event_id)]
    );
    assert_eq!(
        child_c.ancestry().parent_timeline_id,
        Some(timeline_b),
        "C's direct parent must remain B"
    );
    assert_eq!(
        child_c.ancestry().fork_parent_event,
        Some(EventRef::new(timeline_a, event_id))
    );

    let c_after_restart = WorldStore::snapshot(&restarted, timeline_c)
        .await
        .expect("C ancestry should round-trip from PostgreSQL");
    assert_eq!(
        c_after_restart.ancestry().parent_timeline_id,
        Some(timeline_b)
    );
    assert_eq!(
        c_after_restart.ancestry().fork_parent_event,
        Some(EventRef::new(timeline_a, event_id))
    );
    assert_eq!(
        WorldStore::snapshot(&restarted, timeline_a)
            .await
            .expect("source should remain readable")
            .version(),
        source_before.version()
    );

    restarted.close().await;
    pool.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_current_head_fork_without_event_round_trips_none() {
    let Some(database) = TestDatabase::provision("fork_no_event").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id = id::<WorldId>(0x5201);
    let timeline_a = id::<TimelineId>(0x5202);
    let timeline_b = id::<TimelineId>(0x5203);

    seed_world(&pool, world_id, timeline_a).await;
    let source_before = WorldStore::snapshot(&storage, timeline_a)
        .await
        .expect("empty source snapshot should read");
    let child = TimelineForkStore::fork_timeline(
        &storage,
        &TimelineFork::new(timeline_a, source_before.version(), timeline_b),
    )
    .await
    .expect("empty source fork should commit");
    assert_eq!(child.ancestry().fork_parent_event, None);
    assert_eq!(
        WorldStore::snapshot(&storage, timeline_b)
            .await
            .expect("empty child ancestry should round-trip")
            .ancestry()
            .fork_parent_event,
        None
    );
    assert_eq!(
        WorldStore::snapshot(&storage, timeline_a)
            .await
            .expect("empty source should remain readable")
            .version(),
        source_before.version()
    );

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the PostgreSQL restart fixture covers both inherited fork positions"
)]
async fn postgres_runtime_fork_replays_child_visible_boundary_after_restart() {
    let Some(database) = TestDatabase::provision("historical_child_fork").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id = id::<WorldId>(0x5401);
    let timeline_a = id::<TimelineId>(0x5402);
    let event_one = id::<EventId>(0x5410);
    let event_two = id::<EventId>(0x5411);

    seed_world(&pool, world_id, timeline_a).await;
    for (event_id, event_seq, state_revision) in [(event_one, 1, 1), (event_two, 2, 2)] {
        sqlx::query(
            "INSERT INTO loom_event \
             (timeline_id, event_id, event_seq, event_type, schema_revision, occurred_at, payload, effects) \
             VALUES ($1::uuid, $2::uuid, $3, 'test.fork.event', 1, 0, '{}'::jsonb, '[]'::jsonb)",
        )
        .bind(timeline_a.to_string())
        .bind(event_id.to_string())
        .bind(event_seq)
        .execute(&pool)
        .await
        .expect("source Event should insert");
        sqlx::query(
            "INSERT INTO loom_logical_journal \
             (timeline_id, after_state_revision, before_head_event_seq, before_state_revision, \
              after_head_event_seq, event_ids, work_transitions) \
             VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, '[]'::jsonb)",
        )
        .bind(timeline_a.to_string())
        .bind(state_revision)
        .bind(state_revision - 1)
        .bind(state_revision - 1)
        .bind(event_seq)
        .bind(format!("[\"{event_id}\"]"))
        .execute(&pool)
        .await
        .expect("source logical commit should insert");
    }
    sqlx::query(
        "UPDATE loom_timeline SET head_event_seq = 1, state_revision = 1 \
         WHERE timeline_id = $1::uuid",
    )
    .bind(timeline_a.to_string())
    .execute(&pool)
    .await
    .expect("source should expose the first committed position");

    let version = TimelineVersion::new(EventSeq::new(1), StateRevision::new(1));
    let runtime =
        Runtime::new(&storage, CapabilityRegistry::new()).expect("Runtime should assemble");
    let child_b = runtime
        .fork(ForkTimelineRequest::at_version(
            TimelineTarget::new(world_id, timeline_a),
            version,
        ))
        .await
        .expect("A to B historical fork should commit");
    let timeline_b = child_b.target.timeline_id;

    sqlx::query(
        "UPDATE loom_timeline SET head_event_seq = 2, state_revision = 2 \
         WHERE timeline_id = $1::uuid",
    )
    .bind(timeline_a.to_string())
    .execute(&pool)
    .await
    .expect("parent tail should commit after B");

    storage.close().await;
    let restarted = database.storage().await;
    let restarted_runtime = Runtime::new(&restarted, CapabilityRegistry::new())
        .expect("Runtime should reassemble after restart");
    let child_current = restarted_runtime
        .fork(ForkTimelineRequest::new(TimelineTarget::new(
            world_id, timeline_b,
        )))
        .await
        .expect("B current inherited head should be forkable after restart");
    let child_boundary = restarted_runtime
        .fork(ForkTimelineRequest::at_version(
            TimelineTarget::new(world_id, timeline_b),
            version,
        ))
        .await
        .expect("B inherited boundary should be forkable after restart");
    for child in [child_current, child_boundary] {
        let snapshot = WorldStore::snapshot(&restarted, child.target.timeline_id)
            .await
            .expect("forked child should be readable after restart");
        assert_eq!(snapshot.version(), version);
        assert!(snapshot.events.is_empty());
        assert_eq!(snapshot.ancestry().parent_timeline_id, Some(timeline_b));
    }
    assert_eq!(
        WorldStore::snapshot(&restarted, timeline_a)
            .await
            .expect("parent should remain readable")
            .version(),
        TimelineVersion::new(EventSeq::new(2), StateRevision::new(2))
    );

    let invalid = restarted_runtime
        .fork(ForkTimelineRequest::at_version(
            TimelineTarget::new(world_id, timeline_b),
            TimelineVersion::new(EventSeq::new(99), StateRevision::new(99)),
        ))
        .await
        .expect_err("a position before B's inherited boundary must fail");
    assert_eq!(invalid.code, ApiErrorCode::InvalidRequest);

    restarted.close().await;
    pool.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_historical_fork_persists_materialization_after_restart() {
    let Some(database) = TestDatabase::provision("historical_fork_materialization").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id = id::<WorldId>(0x5301);
    let timeline_a = id::<TimelineId>(0x5302);
    let timeline_b = id::<TimelineId>(0x5303);
    let entity_id = id(0x5310);

    seed_world(&pool, world_id, timeline_a).await;
    let version = TimelineVersion::default();
    let materialization = ForkMaterialization::new(
        BaseWorldSnapshot::new(world_id, timeline_a, version, WorldInstant::new(7)).with_entity(
            Entity {
                id: entity_id,
                world_id,
            },
        ),
        ChronologyBudgetState::new(WorldInstant::new(7), 2),
        9,
    );
    let child = TimelineForkStore::fork_timeline(
        &storage,
        &TimelineFork::new(timeline_a, version, timeline_b).with_materialization(materialization),
    )
    .await
    .expect("historical materialization should commit atomically");
    assert_eq!(child.world_time(), WorldInstant::new(7));
    assert!(child.world_view().entity(entity_id).is_some());
    assert_eq!(child.version(), version);

    storage.close().await;
    let restarted = database.storage().await;
    let after_restart = WorldStore::snapshot(&restarted, timeline_b)
        .await
        .expect("historical child should survive restart");
    assert_eq!(after_restart.world_time(), WorldInstant::new(7));
    assert!(after_restart.world_view().entity(entity_id).is_some());
    assert_eq!(
        WorldStore::snapshot(&restarted, timeline_a)
            .await
            .expect("source should remain immutable")
            .world_time(),
        WorldInstant::default()
    );

    restarted.close().await;
    pool.close().await;
    database.cleanup().await;
}

#[tokio::test]
#[expect(
    clippy::too_many_lines,
    reason = "the PostgreSQL visible ancestry fixture covers several immutable branch boundaries"
)]
async fn postgres_18_visible_history_is_bounded_across_grandchild_and_restart() {
    let Some(database) = TestDatabase::provision("visible_history").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id = id::<WorldId>(0x5301);
    let timeline_a = id::<TimelineId>(0x5302);
    let timeline_b = id::<TimelineId>(0x5303);
    let timeline_c = id::<TimelineId>(0x5304);
    let event_a1 = id::<EventId>(0x5311);
    let event_a2 = id::<EventId>(0x5312);
    let event_a3 = id::<EventId>(0x5313);
    let event_b3 = id::<EventId>(0x5323);

    seed_world(&pool, world_id, timeline_a).await;
    insert_event(&pool, timeline_a, event_a1, 1).await;
    insert_event(&pool, timeline_a, event_a2, 2).await;
    sqlx::query(
        "UPDATE loom_timeline SET head_event_seq = 2, state_revision = 2 WHERE timeline_id = $1::uuid",
    )
    .bind(timeline_a.to_string())
    .execute(&pool)
    .await
    .expect("source head should update");

    let source = WorldStore::snapshot(&storage, timeline_a)
        .await
        .expect("source history should read");
    assert_eq!(
        refs(&source.events),
        vec![
            EventRef::new(timeline_a, event_a1),
            EventRef::new(timeline_a, event_a2),
        ]
    );
    let child_b = TimelineForkStore::fork_timeline(
        &storage,
        &TimelineFork::new(timeline_a, source.version(), timeline_b),
    )
    .await
    .expect("child fork should commit");
    assert_eq!(refs(&child_b.events), refs(&source.events));

    insert_event(&pool, timeline_b, event_b3, 3).await;
    sqlx::query(
        "UPDATE loom_timeline SET head_event_seq = 3, state_revision = 3 WHERE timeline_id = $1::uuid",
    )
    .bind(timeline_b.to_string())
    .execute(&pool)
    .await
    .expect("child head should update");
    let child = WorldStore::snapshot(&storage, timeline_b)
        .await
        .expect("child history should include its local Event");
    assert_eq!(
        refs(&child.events),
        vec![
            EventRef::new(timeline_a, event_a1),
            EventRef::new(timeline_a, event_a2),
            EventRef::new(timeline_b, event_b3),
        ]
    );

    let grandchild = TimelineForkStore::fork_timeline(
        &storage,
        &TimelineFork::new(timeline_b, child.version(), timeline_c),
    )
    .await
    .expect("grandchild fork should commit");
    assert_eq!(refs(&grandchild.events), refs(&child.events));
    assert_eq!(
        grandchild.ancestry().fork_parent_event,
        Some(EventRef::new(timeline_b, event_b3))
    );

    insert_event(&pool, timeline_a, event_a3, 3).await;
    sqlx::query(
        "UPDATE loom_timeline SET head_event_seq = 3, state_revision = 3 WHERE timeline_id = $1::uuid",
    )
    .bind(timeline_a.to_string())
    .execute(&pool)
    .await
    .expect("source future should update");
    assert_eq!(
        refs(
            &WorldStore::snapshot(&storage, timeline_b)
                .await
                .expect("child history should remain bounded")
                .events
        ),
        refs(&child.events)
    );
    assert_eq!(
        refs(
            &WorldStore::snapshot(&storage, timeline_c)
                .await
                .expect("grandchild history should remain bounded")
                .events
        ),
        refs(&grandchild.events)
    );

    storage.close().await;
    let restarted = database.storage().await;
    let after_restart = WorldStore::snapshot(&restarted, timeline_c)
        .await
        .expect("visible ancestry should survive restart");
    assert_eq!(refs(&after_restart.events), refs(&grandchild.events));

    restarted.close().await;
    pool.close().await;
    database.cleanup().await;
}
