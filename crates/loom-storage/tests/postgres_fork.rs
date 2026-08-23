mod support;

use std::str::FromStr;

use loom_core::{
    Entity, EventId, EventRef, EventSeq, StateRevision, TimelineId, TimelineVersion, WorldId,
    WorldInstant,
};
use loom_runtime::{
    BaseWorldSnapshot, ChronologyBudgetState, ForkMaterialization, TimelineFork, TimelineForkStore,
    WorldStore,
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
    assert!(child_b.events.is_empty());
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
    assert!(child_c.events.is_empty());
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
