mod support;

use std::str::FromStr;

use loom_capability::CapabilityRegistry;
use loom_core::{TimelineId, WorkId, WorldId};
use loom_protocol::Resolution;
use loom_runtime::{
    CommitError, CommitStore, EffectEngine, PlatformTime, WorkError, WorkStatus, WorkStore,
    WorldStore,
};
use loom_storage::PgStorage;
use sqlx::PgPool;
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

async fn authority() -> Option<(TestDatabase, PgStorage, PgPool, TimelineId, WorkId)> {
    let database = TestDatabase::provision("work-stale-completion").await?;
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id: WorldId = id(0x2600);
    let timeline_id: TimelineId = id(0x2601);
    let work_id: WorkId = id(0x2610);
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid) ON CONFLICT DO NOTHING")
        .bind(world_id.to_string())
        .execute(&pool)
        .await
        .expect("test World should insert");
    sqlx::query(
        "INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid) \
         ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id.to_string())
    .bind(world_id.to_string())
    .execute(&pool)
    .await
    .expect("test Timeline should insert");
    sqlx::query(
        "INSERT INTO loom_work \
         (timeline_id, work_id, target_kind, target_handler, schema_revision, payload, \
          effective_due_world_time, logical_schedule_order, status, attempt_count, \
          claim_generation, available_at) \
         VALUES ($1::uuid, $2::uuid, 'capability_work', 'postgres.work.stale', 1, \
                 '{}'::jsonb, 0, 1, 'pending', 0, 0, 0)",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .execute(&pool)
    .await
    .expect("test Work should insert");
    Some((database, storage, pool, timeline_id, work_id))
}

#[tokio::test]
async fn postgres_18_work_stale_reclaimed_fence_cannot_complete() {
    let Some((database, storage, pool, timeline_id, work_id)) = authority().await else {
        return;
    };
    let first = WorkStore::claim(
        &storage,
        timeline_id,
        work_id,
        PlatformTime::new(10),
        PlatformTime::new(20),
    )
    .await
    .expect("first claim should succeed");
    let second = WorkStore::claim(
        &storage,
        timeline_id,
        work_id,
        PlatformTime::new(20),
        PlatformTime::new(30),
    )
    .await
    .expect("expired Work should be reclaimable");
    assert_eq!(first.fence(), 1);
    assert_eq!(second.fence(), 2);

    let snapshot = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("Timeline should be readable");
    let registry = CapabilityRegistry::new();
    let token = EffectEngine::new(&registry)
        .validate(
            &snapshot.world_view(),
            "postgres.work.stale",
            Resolution::default(),
        )
        .expect("empty completion Resolution should validate");
    let stale = CommitStore::commit(&storage, &token, Some(&first), PlatformTime::new(21))
        .await
        .expect_err("reclaimed stale fence must not complete Work");
    assert!(matches!(
        stale,
        CommitError::Work(WorkError::StaleClaim { .. })
    ));

    let after_stale = WorkStore::work(&storage, timeline_id, work_id)
        .await
        .expect("Work read should succeed")
        .expect("Work should remain present");
    assert_eq!(after_stale.status, WorkStatus::Pending);
    assert_eq!(after_stale.claim_generation, 2);
    assert_eq!(
        after_stale
            .lease
            .expect("new lease must survive stale commit")
            .fence(),
        2
    );
    let result = CommitStore::commit(&storage, &token, Some(&second), PlatformTime::new(21))
        .await
        .expect("current fence should still complete after stale loser");
    assert_eq!(result.completed_work, Some(work_id));
    assert_eq!(result.version.state_revision.value(), 1);
    let completed = WorkStore::work(&storage, timeline_id, work_id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(completed.status, WorkStatus::Completed);
    assert!(completed.lease.is_none());

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}
