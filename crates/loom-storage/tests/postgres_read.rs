use loom_core::TimelineId;
use loom_runtime::WorldStore;
use loom_storage::PgStorage;

const WORLD_ID: &str = "00000000-0000-0000-0000-000000000301";
const TIMELINE_ID: &str = "00000000-0000-0000-0000-000000000302";

fn postgres_url() -> Option<String> {
    match std::env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) => Some(url),
        Err(error) if std::env::var_os("LOOM_REQUIRE_POSTGRES_TESTS").is_some() => {
            panic!("LOOM_TEST_POSTGRES_URL is required for PostgreSQL tests: {error}")
        }
        Err(_) => None,
    }
}

#[tokio::test]
async fn postgres_18_empty_timeline_snapshot_parity() {
    let Some(database_url) = postgres_url() else {
        return;
    };

    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");
    storage.migrate().await.expect("migrations should be current");

    let pool = sqlx::PgPool::connect(&database_url)
        .await
        .expect("test setup should connect independently");
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
}
