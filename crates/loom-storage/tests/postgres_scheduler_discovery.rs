mod support;

use std::str::FromStr;

use loom_core::{TimelineId, WorkId};
use loom_runtime::{
    SchedulerDiscoveryCursor, SchedulerDiscoveryError, SchedulerDiscoveryRequest,
    SchedulerDiscoveryStore, SchedulerDiscoveryTarget,
};
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

async fn insert_target(pool: &PgPool, target: SchedulerDiscoveryTarget) {
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid) ON CONFLICT DO NOTHING")
        .bind(target.world_id.to_string())
        .execute(pool)
        .await
        .expect("discovery test World should insert");
    sqlx::query(
        "INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid) \
         ON CONFLICT DO NOTHING",
    )
    .bind(target.timeline_id.to_string())
    .bind(target.world_id.to_string())
    .execute(pool)
    .await
    .expect("discovery test Timeline should insert");
}

async fn insert_work(
    pool: &PgPool,
    timeline_id: TimelineId,
    work_id: WorkId,
    logical_schedule_order: i64,
    status: &str,
    due_world_time: i64,
    available_at: i64,
) {
    sqlx::query(
        "INSERT INTO loom_work \
         (timeline_id, work_id, target_kind, target_handler, schema_revision, payload, \
          effective_due_world_time, logical_schedule_order, status, attempt_count, \
          claim_generation, available_at) \
         VALUES ($1::uuid, $2::uuid, 'capability_work', 'discovery.test.handler', 1, \
                 '{}'::jsonb, $3, $4, $5, 0, 0, $6)",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .bind(due_world_time)
    .bind(logical_schedule_order)
    .bind(status)
    .bind(available_at)
    .execute(pool)
    .await
    .expect("discovery test Work should insert");
}

async fn seed_ordered_fixture(pool: &PgPool, targets: &[SchedulerDiscoveryTarget; 3]) {
    for &target in targets {
        insert_target(pool, target).await;
    }

    insert_work(pool, targets[0].timeline_id, id(0x1110), 1, "pending", 0, 0).await;
    insert_work(pool, targets[0].timeline_id, id(0x1111), 2, "pending", 0, 0).await;
    insert_work(pool, targets[1].timeline_id, id(0x1112), 1, "pending", 0, 0).await;
    insert_work(
        pool,
        targets[2].timeline_id,
        id(0x1113),
        1,
        "pending",
        100,
        1_000,
    )
    .await;
    sqlx::query(
        "UPDATE loom_work SET lease_claimed_until = $2, lease_fence = $3::numeric \
         WHERE timeline_id = $1::uuid AND work_id = $4::uuid",
    )
    .bind(targets[2].timeline_id.to_string())
    .bind(2_000_i64)
    .bind("7")
    .bind(id::<WorkId>(0x1113).to_string())
    .execute(pool)
    .await
    .expect("discovery test lease should be seeded");
}

async fn assert_discovery_read_only(pool: &PgPool, target: SchedulerDiscoveryTarget) {
    let pending_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM loom_work WHERE timeline_id = $1::uuid AND status = 'pending'",
    )
    .bind(target.timeline_id.to_string())
    .fetch_one(pool)
    .await
    .expect("discovery test Work count should be readable");
    assert_eq!(pending_count, 1);
    let lease: (i64, String) = sqlx::query_as(
        "SELECT lease_claimed_until, lease_fence::text FROM loom_work \
         WHERE timeline_id = $1::uuid AND work_id = $2::uuid",
    )
    .bind(target.timeline_id.to_string())
    .bind(id::<WorkId>(0x1113).to_string())
    .fetch_one(pool)
    .await
    .expect("discovery test lease should remain readable");
    assert_eq!(lease, (2_000, "7".to_owned()));
}

#[tokio::test]
async fn postgres_18_scheduler_discovery_decodes_ordered_targets_and_continuation() {
    let database = TestDatabase::provision("scheduler-discovery").await;
    let storage = database.storage().await;
    let pool = database.pool().await;
    let targets = [
        SchedulerDiscoveryTarget::new(id(0x1100), id(0x1101)),
        SchedulerDiscoveryTarget::new(id(0x1100), id(0x1102)),
        SchedulerDiscoveryTarget::new(id(0x1101), id(0x1103)),
    ];
    seed_ordered_fixture(&pool, &targets).await;

    let first = SchedulerDiscoveryStore::discover_scheduler_targets(
        &storage,
        SchedulerDiscoveryRequest::new(2).expect("discovery page should be bounded"),
    )
    .await
    .expect("PostgreSQL discovery should decode a page");
    assert_eq!(first.targets, targets[..2]);
    let cursor = first
        .continuation()
        .expect("a later target should produce a continuation");
    assert_eq!(cursor, SchedulerDiscoveryCursor::after(targets[1]));

    let resumed = SchedulerDiscoveryStore::discover_scheduler_targets(
        &storage,
        SchedulerDiscoveryRequest::new(2)
            .expect("discovery page should be bounded")
            .with_cursor(cursor),
    )
    .await
    .expect("PostgreSQL discovery should resume after the cursor");
    assert_eq!(resumed.targets, targets[2..]);
    assert_eq!(resumed.continuation(), None);
    assert_discovery_read_only(&pool, targets[2]).await;

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_scheduler_discovery_returns_empty_without_pending_work() {
    let database = TestDatabase::provision("scheduler-discovery-empty").await;
    let storage = database.storage().await;
    let pool = database.pool().await;
    let target = SchedulerDiscoveryTarget::new(id(0x1200), id(0x1201));
    insert_target(&pool, target).await;
    insert_work(&pool, target.timeline_id, id(0x1210), 1, "completed", 0, 0).await;
    insert_work(&pool, target.timeline_id, id(0x1211), 2, "cancelled", 0, 0).await;

    let page = SchedulerDiscoveryStore::discover_scheduler_targets(
        &storage,
        SchedulerDiscoveryRequest::new(4).expect("discovery page should be bounded"),
    )
    .await
    .expect("empty PostgreSQL discovery should succeed");
    assert!(page.targets.is_empty());
    assert_eq!(page.continuation(), None);

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_18_scheduler_discovery_maps_storage_failures_and_validates_bounds() {
    let database = TestDatabase::provision("scheduler-discovery-error").await;
    let storage = database.storage().await;

    let invalid = SchedulerDiscoveryRequest {
        page_size: 0,
        cursor: None,
    };
    assert_eq!(
        SchedulerDiscoveryStore::discover_scheduler_targets(&storage, invalid).await,
        Err(SchedulerDiscoveryError::InvalidPageSize {
            max: loom_runtime::MAX_SCHEDULER_DISCOVERY_PAGE_SIZE,
            actual: 0,
        })
    );

    storage.close().await;
    let error = SchedulerDiscoveryStore::discover_scheduler_targets(
        &storage,
        SchedulerDiscoveryRequest::new(1).expect("discovery page should be bounded"),
    )
    .await
    .expect_err("a closed PostgreSQL pool should fail discovery");
    assert!(matches!(
        error,
        SchedulerDiscoveryError::StorageUnavailable { message }
            if message.contains("Scheduler discovery")
    ));

    database.cleanup().await;
}
