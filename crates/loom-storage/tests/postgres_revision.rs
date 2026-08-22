mod support;

use std::str::FromStr;

use loom_capability::CapabilityId;
use loom_core::{TimelineId, TimelineVersion, WorldId, WorldInstant};
use loom_runtime::{
    PlatformTime, RuntimeRevisionCapability, RuntimeRevisionDescriptor, RuntimeRevisionError,
    RuntimeRevisionId, RuntimeRevisionStore, WorldLifecycleStore, WorldStore,
};
use semver::{Version, VersionReq};

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

fn revision() -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from("postgres-r1"),
        PlatformTime::new(100),
        "loom-postgres-build-1",
        Version::new(0, 1, 0),
        [RuntimeRevisionCapability::new(
            CapabilityId::from("postgres.test"),
            "postgres-test-build-1",
            Version::new(1, 2, 3),
            VersionReq::parse("^0.1.0").expect("Loom compatibility should parse"),
        )],
    )
    .expect("PostgreSQL revision descriptor should be valid")
}

#[tokio::test]
async fn postgres_runtime_revision_history_survives_restart_and_is_world_neutral() {
    let Some(database) = TestDatabase::provision("runtime_revision").await else {
        return;
    };
    let storage = database.storage().await;
    let world_id = id::<WorldId>(0x5101);
    let timeline_id = id::<TimelineId>(0x5102);
    WorldLifecycleStore::create_world(&storage, world_id, timeline_id, WorldInstant::new(7))
        .await
        .expect("World fixture should be created");
    let before = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Timeline should be readable before activation");
    let revision = revision();

    RuntimeRevisionStore::register_revision(&storage, revision.clone())
        .await
        .expect("Runtime Revision should publish once");
    let selection = RuntimeRevisionStore::activate_revision(
        &storage,
        RuntimeRevisionId::from("postgres-r1"),
        None,
        PlatformTime::new(200),
    )
    .await
    .expect("first activation should use the empty-selection CAS");
    assert_eq!(selection.revision(), &revision);
    assert_eq!(selection.generation(), 1);
    assert_eq!(
        RuntimeRevisionStore::activate_revision(
            &storage,
            RuntimeRevisionId::from("postgres-r1"),
            None,
            PlatformTime::new(201),
        )
        .await,
        Err(RuntimeRevisionError::ActiveRevisionConflict {
            expected_generation: None,
            actual_generation: Some(1),
        })
    );
    let after = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Timeline should remain readable after activation");
    assert_eq!(after.version(), TimelineVersion::default());
    assert_eq!(after.world_id(), before.world_id());
    assert_eq!(after.timeline_id(), before.timeline_id());
    assert_eq!(after.world_time(), before.world_time());
    assert_eq!(after.events, before.events);
    assert_eq!(after.works, before.works);
    let pool = database.pool().await;
    let event_count: i64 = sqlx::query_scalar("SELECT count(*)::bigint FROM loom_event")
        .fetch_one(&pool)
        .await
        .expect("World Event table should be queryable");
    assert_eq!(event_count, 0);
    let timeline_time: i64 =
        sqlx::query_scalar("SELECT world_time FROM loom_timeline WHERE timeline_id = $1::uuid")
            .bind(timeline_id.to_string())
            .fetch_one(&pool)
            .await
            .expect("Timeline logical state should be queryable");
    assert_eq!(timeline_time, 7);
    pool.close().await;
    storage.close().await;

    let restarted = database.storage().await;
    assert_eq!(
        RuntimeRevisionStore::read_revision(&restarted, RuntimeRevisionId::from("postgres-r1"))
            .await
            .expect("published Runtime Revision should survive restart"),
        revision
    );
    let active = RuntimeRevisionStore::read_active_revision(&restarted)
        .await
        .expect("active Runtime Revision should survive restart")
        .expect("active selection should exist");
    assert_eq!(active.revision(), &revision);
    assert_eq!(active.generation(), 1);
    assert_eq!(active.activated_at(), PlatformTime::new(200));
    restarted.close().await;
    database.cleanup().await;
}
