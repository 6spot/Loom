mod support;

use loom_core::{
    EntityId, EventId, FacetOwner, FacetTypeId, RelationshipId, TimelineId, TimelineVersion,
    WorldId, WorldInstant,
};
use loom_runtime::{
    PinnedReadBoundary, PinnedReadPolicy, PinnedReadSession, PinnedWorldReadStore, ReadError,
};
use loom_storage::InMemoryStore;
use support::TestDatabase;

const WORLD_ID: &str = "00000000-0000-0000-0000-000000000701";
const TIMELINE_ID: &str = "00000000-0000-0000-0000-000000000702";
const ENTITY_ID: &str = "00000000-0000-0000-0000-000000000703";
const SESSION_ID: &str = "00000000-0000-0000-0000-000000000704";
const RELATIONSHIP_ID: &str = "00000000-0000-0000-0000-000000000711";
const EVENT_ID: &str = "00000000-0000-0000-0000-000000000712";

fn session(
    world_id: WorldId,
    timeline_id: TimelineId,
    version: TimelineVersion,
) -> PinnedReadSession {
    PinnedReadSession::new(
        SESSION_ID.parse().expect("Session ID should parse"),
        world_id,
        timeline_id,
        version,
        WorldInstant::default(),
    )
}

#[tokio::test]
async fn in_memory_pinned_boundary_records_dependencies_and_cache_hits() {
    let store = InMemoryStore::new();
    let world_id: WorldId = "00000000-0000-0000-0000-000000000705"
        .parse()
        .expect("World ID");
    let timeline_id: TimelineId = "00000000-0000-0000-0000-000000000706"
        .parse()
        .expect("Timeline ID");
    let entity_id: EntityId = "00000000-0000-0000-0000-000000000707"
        .parse()
        .expect("Entity ID");
    store
        .create_timeline(world_id, timeline_id)
        .expect("Timeline fixture should be created");
    store
        .seed_entity(
            timeline_id,
            loom_core::Entity {
                id: entity_id,
                world_id,
            },
        )
        .expect("Entity fixture should be seeded");

    let pinned = session(world_id, timeline_id, TimelineVersion::default());
    let mut boundary = PinnedReadBoundary::new(&store, PinnedReadPolicy::new(1, 2));
    assert!(
        boundary
            .entity(&pinned, entity_id)
            .await
            .expect("point read should succeed")
            .value()
            .is_some()
    );
    assert!(
        boundary
            .entity(&pinned, entity_id)
            .await
            .expect("cached point read should succeed")
            .value()
            .is_some()
    );
    assert_eq!(boundary.metrics().cache_hits(), 1);
    assert_eq!(pinned.read_set().len(), 1);
}

#[tokio::test]
async fn in_memory_pinned_boundary_rejects_stale_version_before_returning_data() {
    let store = InMemoryStore::new();
    let world_id: WorldId = "00000000-0000-0000-0000-000000000708"
        .parse()
        .expect("World ID");
    let timeline_id: TimelineId = "00000000-0000-0000-0000-000000000709"
        .parse()
        .expect("Timeline ID");
    let entity_id: EntityId = "00000000-0000-0000-0000-000000000710"
        .parse()
        .expect("Entity ID");
    store
        .create_timeline(world_id, timeline_id)
        .expect("Timeline fixture should be created");
    let pinned = session(
        world_id,
        timeline_id,
        TimelineVersion::new(1.into(), 1.into()),
    );
    let error = PinnedWorldReadStore::read_entity(&store, &pinned, entity_id)
        .await
        .expect_err("stale point read must fail before returning a value");
    assert!(matches!(error, ReadError::PinnedVersionMismatch { .. }));
}

#[tokio::test]
#[allow(clippy::too_many_lines)]
async fn postgres_point_reads_use_one_row_queries_and_version_fences() {
    let Some(database) = TestDatabase::provision("pinned-read").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id: WorldId = WORLD_ID.parse().expect("World ID should parse");
    let timeline_id: TimelineId = TIMELINE_ID.parse().expect("Timeline ID should parse");
    let entity_id: EntityId = ENTITY_ID.parse().expect("Entity ID should parse");
    let relationship_id: RelationshipId = RELATIONSHIP_ID
        .parse()
        .expect("Relationship ID should parse");
    let event_id: EventId = EVENT_ID.parse().expect("Event ID should parse");

    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
        .bind(WORLD_ID)
        .execute(&pool)
        .await
        .expect("World should insert");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(TIMELINE_ID)
        .bind(WORLD_ID)
        .execute(&pool)
        .await
        .expect("Timeline should insert");
    sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
        .bind(TIMELINE_ID)
        .bind(ENTITY_ID)
        .execute(&pool)
        .await
        .expect("Entity should insert");
    sqlx::query(
        "INSERT INTO loom_entity_facet (timeline_id, entity_id, facet_type, schema_revision, value) \
         VALUES ($1::uuid, $2::uuid, 'test.pinned', 1, '{\"value\":7}'::jsonb)",
    )
    .bind(TIMELINE_ID)
    .bind(ENTITY_ID)
    .execute(&pool)
    .await
    .expect("Facet should insert");
    sqlx::query(
        "INSERT INTO loom_relationship (timeline_id, relationship_id, relationship_type, active) \
         VALUES ($1::uuid, $2::uuid, 'test.pinned', TRUE)",
    )
    .bind(TIMELINE_ID)
    .bind(RELATIONSHIP_ID)
    .execute(&pool)
    .await
    .expect("Relationship should insert");
    sqlx::query(
        "INSERT INTO loom_relationship_participant \
         (timeline_id, relationship_id, participant_order, entity_id, role) \
         VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'subject')",
    )
    .bind(TIMELINE_ID)
    .bind(RELATIONSHIP_ID)
    .bind(ENTITY_ID)
    .execute(&pool)
    .await
    .expect("Relationship participant should insert");
    sqlx::query(
        "INSERT INTO loom_event \
         (timeline_id, event_id, event_seq, event_type, schema_revision, occurred_at, payload, effects) \
         VALUES ($1::uuid, $2::uuid, 1, 'test.pinned', 1, 0, '{}'::jsonb, '[]'::jsonb)",
    )
    .bind(TIMELINE_ID)
    .bind(EVENT_ID)
    .execute(&pool)
    .await
    .expect("Event should insert");

    let pinned = session(world_id, timeline_id, TimelineVersion::default());
    let mut boundary = PinnedReadBoundary::new(&storage, PinnedReadPolicy::new(1, 8));
    let entity = boundary
        .entity(&pinned, entity_id)
        .await
        .expect("Entity point read should succeed");
    assert!(entity.value().is_some());
    assert_eq!(entity.metrics().rows_read(), 1);
    let facet = boundary
        .facet(
            &pinned,
            FacetOwner::entity(entity_id),
            &FacetTypeId::from("test.pinned"),
        )
        .await
        .expect("Facet point read should succeed");
    assert_eq!(
        facet
            .value()
            .as_ref()
            .map(|value| value.value["value"].clone()),
        Some(7.into())
    );
    assert_eq!(pinned.read_set().len(), 2);
    let relationship = boundary
        .relationship(&pinned, relationship_id)
        .await
        .expect("Relationship point read should succeed");
    assert_eq!(relationship.metrics().rows_read(), 1);
    assert_eq!(
        relationship
            .value()
            .as_ref()
            .map(|value| value.participants().len()),
        Some(1)
    );

    sqlx::query(
        "UPDATE loom_timeline SET head_event_seq = 1, state_revision = 1 \
         WHERE timeline_id = $1::uuid",
    )
    .bind(TIMELINE_ID)
    .execute(&pool)
    .await
    .expect("Timeline Event version should advance");
    let event_session = session(
        world_id,
        timeline_id,
        TimelineVersion::new(1.into(), 1.into()),
    );
    let mut event_boundary = PinnedReadBoundary::new(&storage, PinnedReadPolicy::new(1, 8));
    let event = event_boundary
        .event(&event_session, event_id)
        .await
        .expect("Event point read should succeed");
    assert_eq!(event.value().as_ref().map(|value| value.id), Some(event_id));
    assert_eq!(event.metrics().rows_read(), 1);

    sqlx::query("UPDATE loom_timeline SET state_revision = 2 WHERE timeline_id = $1::uuid")
        .bind(TIMELINE_ID)
        .execute(&pool)
        .await
        .expect("Timeline version should advance");
    // A revision-keyed cache may continue to serve the immutable V0 value;
    // a fresh Runtime boundary must fence its next database read instead of
    // silently adopting V1.
    let mut fresh_boundary = PinnedReadBoundary::new(&storage, PinnedReadPolicy::new(1, 8));
    let stale = fresh_boundary
        .entity(&pinned, entity_id)
        .await
        .expect_err("a later point read must reject the old version");
    assert!(matches!(stale, ReadError::PinnedVersionMismatch { .. }));

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

#[tokio::test]
async fn postgres_point_read_amplification_stays_bounded_as_world_grows() {
    let Some(database) = TestDatabase::provision("pinned-read-bench").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;

    for world_size in [1_usize, 32, 256] {
        let world_text = format_uuid(0x720 + world_size as u128);
        let timeline_text = format_uuid(0x820 + world_size as u128);
        sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
            .bind(&world_text)
            .execute(&pool)
            .await
            .expect("benchmark World should insert");
        sqlx::query(
            "INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)",
        )
        .bind(&timeline_text)
        .bind(&world_text)
        .execute(&pool)
        .await
        .expect("benchmark Timeline should insert");
        let target_text = format_uuid(0x10_000 + (world_size - 1) as u128);
        for index in 0..world_size {
            let entity_text = format_uuid(0x10_000 + index as u128);
            sqlx::query(
                "INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)",
            )
            .bind(&timeline_text)
            .bind(entity_text)
            .execute(&pool)
            .await
            .expect("benchmark Entity should insert");
        }

        let world_id: WorldId = world_text.parse().expect("benchmark World ID");
        let timeline_id: TimelineId = timeline_text.parse().expect("benchmark Timeline ID");
        let entity_id: EntityId = target_text.parse().expect("benchmark Entity ID");
        let pinned = session(world_id, timeline_id, TimelineVersion::default());
        let read = PinnedWorldReadStore::read_entity(&storage, &pinned, entity_id)
            .await
            .expect("benchmark point read should succeed");
        println!(
            "world_size={world_size} rows={} bytes={} latency_us={}",
            read.metrics().rows_read(),
            read.metrics().bytes_read(),
            read.metrics().latency_micros()
        );
        assert!(read.value().is_some());
        assert_eq!(read.metrics().rows_read(), 1);
    }

    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}

fn format_uuid(value: u128) -> String {
    format!("{value:032x}")
}
