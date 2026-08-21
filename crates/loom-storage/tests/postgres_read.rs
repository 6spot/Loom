mod support;

use loom_core::TimelineId;
use loom_runtime::WorldStore;
use support::TestDatabase;

const WORLD_ID: &str = "00000000-0000-0000-0000-000000000301";
const TIMELINE_ID: &str = "00000000-0000-0000-0000-000000000302";

#[tokio::test]
async fn postgres_18_empty_timeline_snapshot_parity() {
    let Some(database) = TestDatabase::provision("read-empty").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid) ON CONFLICT DO NOTHING")
        .bind(WORLD_ID)
        .execute(&pool)
        .await
        .expect("empty snapshot World should insert");
    sqlx::query(
        "INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid) \
         ON CONFLICT DO NOTHING",
    )
    .bind(TIMELINE_ID)
    .bind(WORLD_ID)
    .execute(&pool)
    .await
    .expect("empty snapshot Timeline should insert");

    let timeline: TimelineId = TIMELINE_ID.parse().expect("TimelineId should parse");
    let snapshot = WorldStore::snapshot(&storage, timeline)
        .await
        .expect("empty PostgreSQL Timeline should be readable");

    assert_eq!(snapshot.world_id().to_string(), WORLD_ID);
    assert_eq!(snapshot.version().head_event_seq.value(), 0);
    assert_eq!(snapshot.version().state_revision.value(), 0);
    assert_eq!(snapshot.world_time().value(), 0);
    assert!(snapshot.events.is_empty());
    assert!(snapshot.works.is_empty());

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}
