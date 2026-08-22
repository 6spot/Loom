use super::PgStorage;

const WORLD_ID: &str = "00000000-0000-0000-0000-000000000101";
const TIMELINE_ID: &str = "00000000-0000-0000-0000-000000000102";
const ENTITY_ID: &str = "00000000-0000-0000-0000-000000000103";

fn postgres_url() -> Option<String> {
    match std::env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) => Some(url),
        Err(error) if std::env::var_os("LOOM_REQUIRE_POSTGRES_TESTS").is_some() => {
            panic!("LOOM_TEST_POSTGRES_URL is required for PostgreSQL tests: {error}")
        }
        Err(_) => None,
    }
}

fn database_error_code(error: &sqlx::Error) -> Option<String> {
    error
        .as_database_error()
        .and_then(sqlx::error::DatabaseError::code)
        .map(std::borrow::Cow::into_owned)
}

#[tokio::test]
async fn postgres_18_schema_contract() {
    let Some(database_url) = postgres_url() else {
        return;
    };

    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");

    let server_version: i32 =
        sqlx::query_scalar("SELECT current_setting('server_version_num')::integer")
            .fetch_one(&storage.pool)
            .await
            .expect("PostgreSQL should report its server version");
    assert!(
        (180_000..190_000).contains(&server_version),
        "schema gate must run against PostgreSQL 18, got server_version_num={server_version}"
    );

    storage
        .migrate()
        .await
        .expect("migrations should apply to an empty PostgreSQL 18 database");
    storage
        .migrate()
        .await
        .expect("re-running unchanged migrations should be deterministic");
    storage.health().await.expect("health query should succeed");

    let loom_table_count: i64 = sqlx::query_scalar(
        "SELECT count(*)::bigint \
         FROM information_schema.tables \
         WHERE table_schema = 'public' AND table_name LIKE 'loom_%'",
    )
    .fetch_one(&storage.pool)
    .await
    .expect("schema tables should be inspectable");
    assert_eq!(loom_table_count, 16);

    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
        .bind(WORLD_ID)
        .execute(&storage.pool)
        .await
        .expect("test World should insert");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(TIMELINE_ID)
        .bind(WORLD_ID)
        .execute(&storage.pool)
        .await
        .expect("test Timeline should insert");
    sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
        .bind(TIMELINE_ID)
        .bind(ENTITY_ID)
        .execute(&storage.pool)
        .await
        .expect("test Entity should insert");

    let duplicate_entity =
        sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
            .bind(TIMELINE_ID)
            .bind(ENTITY_ID)
            .execute(&storage.pool)
            .await
            .expect_err("duplicate Timeline-local Entity identity must be rejected");
    assert_eq!(
        database_error_code(&duplicate_entity).as_deref(),
        Some("23505")
    );

    let missing_facet_owner = sqlx::query(
        "INSERT INTO loom_entity_facet \
         (timeline_id, entity_id, facet_type, schema_revision, value) \
         VALUES ($1::uuid, $2::uuid, 'test.missing', 1, '{}'::jsonb)",
    )
    .bind(TIMELINE_ID)
    .bind("00000000-0000-0000-0000-000000000199")
    .execute(&storage.pool)
    .await
    .expect_err("Facet owner foreign key must be enforced");
    assert_eq!(
        database_error_code(&missing_facet_owner).as_deref(),
        Some("23503")
    );

    let invalid_u64_range = sqlx::query(
        "INSERT INTO loom_timeline \
         (timeline_id, world_id, head_event_seq) \
         VALUES ('00000000-0000-0000-0000-000000000198'::uuid, $1::uuid, -1)",
    )
    .bind(WORLD_ID)
    .execute(&storage.pool)
    .await
    .expect_err("negative EventSeq representation must be rejected");
    assert_eq!(
        database_error_code(&invalid_u64_range).as_deref(),
        Some("23514")
    );

    storage.close().await;
}

#[tokio::test]
async fn postgres_18_read_snapshot_parity() {
    let Some(database_url) = postgres_url() else {
        return;
    };
    let storage = PgStorage::connect(&database_url)
        .await
        .expect("PostgreSQL test database should accept connections");
    storage
        .migrate()
        .await
        .expect("migrations should be current");

    let world_id = "00000000-0000-0000-0000-000000000201";
    let timeline_id = "00000000-0000-0000-0000-000000000202";
    let entity_a = "00000000-0000-0000-0000-000000000203";
    let entity_b = "00000000-0000-0000-0000-000000000204";
    let relationship_id = "00000000-0000-0000-0000-000000000205";
    let event_first = "00000000-0000-0000-0000-000000000299";
    let event_second = "00000000-0000-0000-0000-000000000210";
    let work_id = "00000000-0000-0000-0000-000000000211";

    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid) ON CONFLICT DO NOTHING")
        .bind(world_id)
        .execute(&storage.pool)
        .await
        .expect("read fixture World should insert");
    sqlx::query(
        "INSERT INTO loom_timeline \
         (timeline_id, world_id, head_event_seq, state_revision, world_time) \
         VALUES ($1::uuid, $2::uuid, 2, 3, 42) ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(world_id)
    .execute(&storage.pool)
    .await
    .expect("read fixture Timeline should insert");
    for entity_id in [entity_a, entity_b] {
        sqlx::query(
            "INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid) \
             ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(entity_id)
        .execute(&storage.pool)
        .await
        .expect("read fixture Entity should insert");
    }
    sqlx::query(
        "INSERT INTO loom_relationship \
         (timeline_id, relationship_id, relationship_type, active) \
         VALUES ($1::uuid, $2::uuid, 'test.membership', FALSE) ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(relationship_id)
    .execute(&storage.pool)
    .await
    .expect("read fixture Relationship should insert");
    sqlx::query(
        "INSERT INTO loom_relationship_participant \
         (timeline_id, relationship_id, participant_order, entity_id, role) \
         VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'member') ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(relationship_id)
    .bind(entity_a)
    .execute(&storage.pool)
    .await
    .expect("Relationship participant should insert");
    sqlx::query(
        "INSERT INTO loom_entity_facet \
         (timeline_id, entity_id, facet_type, schema_revision, value) \
         VALUES ($1::uuid, $2::uuid, 'test.counter', 1, '{\"value\":7}'::jsonb) \
         ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(entity_a)
    .execute(&storage.pool)
    .await
    .expect("Entity Facet should insert");
    sqlx::query(
        "INSERT INTO loom_relationship_facet \
         (timeline_id, relationship_id, facet_type, schema_revision, value) \
         VALUES ($1::uuid, $2::uuid, 'test.relationship_state', 2, '{\"ended\":true}'::jsonb) \
         ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(relationship_id)
    .execute(&storage.pool)
    .await
    .expect("Relationship Facet should insert");

    // Insert EventSeq 2 first and give EventSeq 1 the lexicographically larger UUID.
    // A correct adapter must still return [1, 2].
    for (event_id, sequence, event_type, occurred_at) in [
        (event_second, 2_i64, "test.second", 42_i64),
        (event_first, 1_i64, "test.first", 40_i64),
    ] {
        sqlx::query(
            "INSERT INTO loom_event \
             (timeline_id, event_id, event_seq, event_type, schema_revision, occurred_at, payload, effects) \
             VALUES ($1::uuid, $2::uuid, $3, $4, 1, $5, '{}'::jsonb, '[]'::jsonb) \
             ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(event_id)
        .bind(sequence)
        .bind(event_type)
        .bind(occurred_at)
        .execute(&storage.pool)
        .await
        .expect("Event fixture should insert");
    }
    sqlx::query(
        "INSERT INTO loom_event_participant \
         (timeline_id, event_id, participant_order, entity_id, role) \
         VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'actor') ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(event_first)
    .bind(entity_a)
    .execute(&storage.pool)
    .await
    .expect("Event participant should insert");
    sqlx::query(
        "INSERT INTO loom_event_relationship_ref \
         (timeline_id, event_id, reference_order, relationship_id, role) \
         VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'subject') ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(event_first)
    .bind(relationship_id)
    .execute(&storage.pool)
    .await
    .expect("Event Relationship reference should insert");
    sqlx::query(
        "INSERT INTO loom_event_causal_link \
         (timeline_id, event_id, causal_order, cause_event_id) \
         VALUES ($1::uuid, $2::uuid, 0, $3::uuid) ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(event_second)
    .bind(event_first)
    .execute(&storage.pool)
    .await
    .expect("Event causal link should insert");
    sqlx::query(
        "INSERT INTO loom_work \
         (timeline_id, work_id, target_kind, target_handler, schema_revision, payload, \
          effective_due_world_time, logical_schedule_order, status, attempt_count, \
          claim_generation, available_at) \
         VALUES ($1::uuid, $2::uuid, 'capability_work', 'test.handler', 1, '{}'::jsonb, 50, 1, \
          'pending', 2, 4, 9) \
         ON CONFLICT DO NOTHING",
    )
    .bind(timeline_id)
    .bind(work_id)
    .execute(&storage.pool)
    .await
    .expect("Work fixture should insert");

    let timeline: loom_core::TimelineId = timeline_id.parse().expect("TimelineId should parse");
    let snapshot = loom_runtime::WorldStore::snapshot(&storage, timeline)
        .await
        .expect("PostgreSQL snapshot should reconstruct the fixture");
    assert_eq!(snapshot.version().head_event_seq.value(), 2);
    assert_eq!(snapshot.version().state_revision.value(), 3);
    assert_eq!(snapshot.world_time().value(), 42);
    assert_eq!(snapshot.events.len(), 2);
    assert_eq!(snapshot.events[0].event_seq.value(), 1);
    assert_eq!(snapshot.events[1].event_seq.value(), 2);
    assert_eq!(snapshot.events[0].id.to_string(), event_first);
    assert_eq!(snapshot.events[0].participants.len(), 1);
    assert_eq!(snapshot.events[0].relationship_refs.len(), 1);
    assert_eq!(
        snapshot.events[1].causal_links[0].event_id(),
        snapshot.events[0].id
    );
    assert_eq!(snapshot.works.len(), 1);
    assert_eq!(snapshot.works[0].attempt_count, 2);
    assert_eq!(snapshot.works[0].claim_generation, 4);
    assert_eq!(snapshot.works[0].available_at.value(), 9);

    let view = snapshot.world_view();
    let entity: loom_core::EntityId = entity_a.parse().expect("EntityId should parse");
    assert!(view.entity(entity).is_some());
    let relationship: loom_core::RelationshipId = relationship_id
        .parse()
        .expect("RelationshipId should parse");
    assert!(
        view.relationship(relationship).is_none(),
        "ended Relationship must not be active"
    );
    assert_eq!(
        view.facet(
            loom_core::FacetOwner::entity(entity),
            &loom_core::FacetTypeId::from("test.counter"),
        )
        .expect("Entity Facet should be reconstructed")
        .value(),
        &serde_json::json!({"value": 7}),
    );

    let missing: loom_core::TimelineId = "00000000-0000-0000-0000-000000000298"
        .parse()
        .expect("missing TimelineId should parse");
    assert!(matches!(
        loom_runtime::WorldStore::snapshot(&storage, missing).await,
        Err(loom_runtime::ReadError::TimelineNotFound { .. })
    ));
    storage.close().await;
}
