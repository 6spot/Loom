mod support;

use std::str::FromStr;

use loom_api::{TimelineService, TimelineTarget};
use loom_capability::CapabilityRegistry;
use loom_core::{TimelineId, TimelineVersion, WorldId, WorldInstant};
use loom_runtime::{LifecycleError, Runtime, WorldLifecycleStore, WorldStore};

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

#[tokio::test]
async fn postgres_18_world_lifecycle_is_atomic_and_immediately_readable() {
    let Some(database) = TestDatabase::provision("lifecycle_success").await else {
        return;
    };
    let storage = database.storage().await;
    let world_id = id::<WorldId>(0x4101);
    let timeline_id = id::<TimelineId>(0x4102);
    let initial_world_time = WorldInstant::new(321);

    let created = WorldLifecycleStore::create_world(
        &storage,
        world_id,
        timeline_id,
        initial_world_time,
    )
    .await
    .expect("PostgreSQL lifecycle bootstrap should commit");
    assert_eq!(created.world_id(), world_id);
    assert_eq!(created.timeline_id(), timeline_id);
    assert_eq!(created.version(), TimelineVersion::default());
    assert_eq!(created.world_time(), initial_world_time);

    let snapshot = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("new PostgreSQL Timeline should be immediately readable");
    assert_eq!(snapshot.world_id(), world_id);
    assert_eq!(snapshot.timeline_id(), timeline_id);
    assert_eq!(snapshot.version(), TimelineVersion::default());
    assert_eq!(snapshot.world_time(), initial_world_time);
    assert!(snapshot.events.is_empty());
    assert!(snapshot.works.is_empty());

    let runtime = Runtime::new(storage.clone(), CapabilityRegistry::new())
        .expect("empty semantic registry should assemble for lifecycle inspection");
    let public = TimelineService::inspect_timeline(
        &runtime,
        TimelineTarget::new(world_id, timeline_id),
    )
    .await
    .expect("public TimelineService should observe committed lifecycle state");
    assert_eq!(public.target, TimelineTarget::new(world_id, timeline_id));
    assert_eq!(public.version, TimelineVersion::default());
    assert_eq!(public.world_time, initial_world_time);

    drop(runtime);
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_world_lifecycle_conflicts_roll_back_without_partial_rows() {
    let Some(database) = TestDatabase::provision("lifecycle_conflict").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;

    let world_a = id::<WorldId>(0x4201);
    let timeline_a = id::<TimelineId>(0x4202);
    WorldLifecycleStore::create_world(
        &storage,
        world_a,
        timeline_a,
        WorldInstant::new(10),
    )
    .await
    .expect("initial lifecycle fixture should commit");

    let unused_timeline = id::<TimelineId>(0x4203);
    let duplicate_world = WorldLifecycleStore::create_world(
        &storage,
        world_a,
        unused_timeline,
        WorldInstant::new(20),
    )
    .await
    .expect_err("duplicate World identity must be a typed lifecycle conflict");
    assert_eq!(
        duplicate_world,
        LifecycleError::WorldAlreadyExists { world_id: world_a }
    );
    let unused_timeline_count: i64 = sqlx::query_scalar(
        "SELECT count(*)::bigint FROM loom_timeline WHERE timeline_id = $1::uuid",
    )
    .bind(unused_timeline.to_string())
    .fetch_one(&pool)
    .await
    .expect("Timeline rollback should be inspectable");
    assert_eq!(unused_timeline_count, 0);

    let world_b = id::<WorldId>(0x4204);
    let duplicate_timeline = WorldLifecycleStore::create_world(
        &storage,
        world_b,
        timeline_a,
        WorldInstant::new(30),
    )
    .await
    .expect_err("duplicate Timeline identity must roll back the fresh World insert");
    assert_eq!(
        duplicate_timeline,
        LifecycleError::TimelineAlreadyExists {
            timeline_id: timeline_a,
        }
    );
    let rolled_back_world_count: i64 =
        sqlx::query_scalar("SELECT count(*)::bigint FROM loom_world WHERE world_id = $1::uuid")
            .bind(world_b.to_string())
            .fetch_one(&pool)
            .await
            .expect("World rollback should be inspectable");
    assert_eq!(rolled_back_world_count, 0);

    let recovered_timeline = id::<TimelineId>(0x4205);
    let recovered = WorldLifecycleStore::create_world(
        &storage,
        world_b,
        recovered_timeline,
        WorldInstant::new(40),
    )
    .await
    .expect("rolled-back World identity must remain reusable");
    assert_eq!(recovered.world_id(), world_b);
    assert_eq!(recovered.timeline_id(), recovered_timeline);
    assert_eq!(recovered.version(), TimelineVersion::default());
    assert_eq!(recovered.world_time(), WorldInstant::new(40));

    let original = WorldStore::snapshot(&storage, timeline_a)
        .await
        .expect("conflicts must not damage the original Timeline");
    assert_eq!(original.world_id(), world_a);
    assert_eq!(original.version(), TimelineVersion::default());
    assert_eq!(original.world_time(), WorldInstant::new(10));

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}
