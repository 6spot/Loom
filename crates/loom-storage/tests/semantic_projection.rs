mod support;

use std::str::FromStr;

use loom_core::{EventRef, SchemaRevision, TimelineId, TimelineVersion, WorldId, WorldInstant};
use loom_runtime::{
    SemanticIndexMetric, SemanticIndexSource, SemanticProjectionKey, SemanticProjectionQuery,
    SemanticProjectionRebuild, SemanticProjectionRegistration, SemanticProjectionRow,
    SemanticProjectionStore, WorldLifecycleStore, WorldStore,
};
use loom_storage::InMemoryStore;

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

fn registration(world_id: WorldId, timeline_id: TimelineId) -> SemanticProjectionRegistration {
    SemanticProjectionRegistration::new(
        SemanticProjectionKey::new(world_id, timeline_id, "test.semantic".into()),
        SemanticIndexSource::new("event", "test.source", SchemaRevision::new(1)),
        SchemaRevision::new(1),
        1,
        "model-1",
        2,
        SemanticIndexMetric::Euclidean,
    )
    .expect("test registration should be valid")
}

fn rows() -> Vec<SemanticProjectionRow> {
    vec![
        SemanticProjectionRow::new(
            EventRef::new(id(10), id(11)),
            "hash-a",
            TimelineVersion::default(),
            1,
            "model-1",
            vec![0.0, 0.0],
        )
        .expect("first projection row should be valid"),
        SemanticProjectionRow::new(
            EventRef::new(id(10), id(12)),
            "hash-b",
            TimelineVersion::default(),
            1,
            "model-1",
            vec![2.0, 0.0],
        )
        .expect("second projection row should be valid"),
    ]
}

#[tokio::test]
async fn in_memory_projection_is_bounded_rebuildable_and_authority_neutral() {
    let store = InMemoryStore::new();
    let world_id = id::<WorldId>(1);
    let timeline_id = id::<TimelineId>(2);
    WorldLifecycleStore::create_world(&store, world_id, timeline_id, WorldInstant::default())
        .await
        .expect("projection scope World should exist");
    let registration = registration(world_id, timeline_id);
    SemanticProjectionStore::register_semantic_projection(&store, registration.clone())
        .await
        .expect("projection registration should succeed");
    let rebuild = SemanticProjectionRebuild::new(registration.clone(), Some(1), rows())
        .expect("projection rebuild should be bounded and typed");
    SemanticProjectionStore::rebuild_semantic_projection(&store, &rebuild)
        .await
        .expect("projection rebuild should succeed");
    let before = WorldStore::snapshot(&store, timeline_id)
        .await
        .expect("authority snapshot should be readable");
    let query = SemanticProjectionQuery::new(
        registration.key.clone(),
        SchemaRevision::new(1),
        1,
        "model-1",
        vec![1.0, 0.0],
        1,
    )
    .expect("bounded query should be valid");
    let hits = SemanticProjectionStore::query_semantic_projection(&store, query)
        .await
        .expect("projection query should succeed");
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].source_ref.event_id, id(11));
    SemanticProjectionStore::delete_semantic_projection(&store, registration.key)
        .await
        .expect("projection deletion should succeed");
    let after = WorldStore::snapshot(&store, timeline_id)
        .await
        .expect("authority snapshot should remain readable");
    assert_eq!(before.version(), after.version());
    assert_eq!(before.events, after.events);
    assert_eq!(before.base, after.base);
}

#[tokio::test]
async fn postgres_pgvector_projection_round_trip_and_mismatch_are_typed() {
    let Some(database) = TestDatabase::provision("semantic_projection").await else {
        return;
    };
    let storage = database.storage().await;
    let pool = database.pool().await;
    let world_id = id::<WorldId>(101);
    let timeline_id = id::<TimelineId>(102);
    WorldLifecycleStore::create_world(&storage, world_id, timeline_id, WorldInstant::default())
        .await
        .expect("PostgreSQL projection scope should exist");
    let registration = registration(world_id, timeline_id);
    SemanticProjectionStore::register_semantic_projection(&storage, registration.clone())
        .await
        .expect("pgvector projection registration should succeed");
    let rebuild = SemanticProjectionRebuild::new(registration.clone(), Some(1), rows())
        .expect("pgvector rebuild should be valid");
    SemanticProjectionStore::rebuild_semantic_projection(&storage, &rebuild)
        .await
        .expect("pgvector rebuild should succeed");
    let query = SemanticProjectionQuery::new(
        registration.key.clone(),
        SchemaRevision::new(1),
        1,
        "model-1",
        vec![1.0, 0.0],
        1,
    )
    .expect("pgvector query should be valid");
    let hits = SemanticProjectionStore::query_semantic_projection(&storage, query)
        .await
        .expect("pgvector query should succeed");
    assert_eq!(hits[0].source_ref.event_id, id(11));
    let before_delete = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("authority snapshot should be readable before projection delete");
    let bad_query = SemanticProjectionQuery::new(
        registration.key.clone(),
        SchemaRevision::new(1),
        1,
        "model-1",
        vec![1.0, 0.0, 0.0],
        1,
    )
    .expect("mismatched query vector remains a structurally bounded request");
    let error = SemanticProjectionStore::query_semantic_projection(&storage, bad_query)
        .await
        .expect_err("dimension mismatch must be deterministic");
    assert!(matches!(
        error,
        loom_runtime::SemanticProjectionError::DimensionMismatch { .. }
    ));
    SemanticProjectionStore::delete_semantic_projection(&storage, registration.key)
        .await
        .expect("pgvector projection delete should succeed");
    let after_delete = WorldStore::snapshot(&storage, timeline_id)
        .await
        .expect("authority snapshot should be readable after projection delete");
    assert_eq!(before_delete.version(), after_delete.version());
    assert_eq!(before_delete.events, after_delete.events);
    assert_eq!(before_delete.base, after_delete.base);
    pool.close().await;
    storage.close().await;
    database.cleanup().await;
}
