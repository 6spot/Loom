mod support;

use support::TestDatabase;

const WORLD_ID: &str = "00000000-0000-0000-0000-00000000a101";
const TIMELINE_ID: &str = "00000000-0000-0000-0000-00000000a102";
const ENTITY_ID: &str = "00000000-0000-0000-0000-00000000a103";

#[tokio::test]
async fn postgres_18_schema_starts_empty_runs_migrations_and_enforces_constraints() {
    let Some(database) = TestDatabase::provision("schema").await else {
        return;
    };
    let pool = database.pool().await;
    assert_postgres_18(&pool).await;

    let table_count: i64 = sqlx::query_scalar(
        "SELECT count(*)::bigint FROM information_schema.tables \
         WHERE table_schema = 'public' AND table_name LIKE 'loom_%'",
    )
    .fetch_one(&pool)
    .await
    .expect("migrated Loom tables should be inspectable");
    assert_eq!(table_count, 12);

    let migration_count: i64 = sqlx::query_scalar("SELECT count(*)::bigint FROM _sqlx_migrations")
        .fetch_one(&pool)
        .await
        .expect("SQLx migration history should exist in a fresh database");
    assert!(migration_count >= 1);

    verify_identity_and_owner_constraints(&pool).await;

    let storage = database.storage().await;
    storage
        .migrate()
        .await
        .expect("re-running unchanged migrations should be deterministic");
    storage.health().await.expect("health query should succeed");
    storage.close().await;
    pool.close().await;
    database.cleanup().await;
}

async fn assert_postgres_18(pool: &sqlx::PgPool) {
    let server_version: i32 =
        sqlx::query_scalar("SELECT current_setting('server_version_num')::integer")
            .fetch_one(pool)
            .await
            .expect("PostgreSQL should report its server version");
    assert!(
        (180_000..190_000).contains(&server_version),
        "PostgreSQL integration gate requires major version 18, got server_version_num={server_version}"
    );
}

async fn verify_identity_and_owner_constraints(pool: &sqlx::PgPool) {
    sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
        .bind(WORLD_ID)
        .execute(pool)
        .await
        .expect("schema fixture World should insert");
    sqlx::query("INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)")
        .bind(TIMELINE_ID)
        .bind(WORLD_ID)
        .execute(pool)
        .await
        .expect("schema fixture Timeline should insert");
    sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
        .bind(TIMELINE_ID)
        .bind(ENTITY_ID)
        .execute(pool)
        .await
        .expect("schema fixture Entity should insert");

    let duplicate =
        sqlx::query("INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)")
            .bind(TIMELINE_ID)
            .bind(ENTITY_ID)
            .execute(pool)
            .await
            .expect_err("duplicate Timeline-local Entity identity must be rejected");
    assert_eq!(database_error_code(&duplicate).as_deref(), Some("23505"));

    let missing_owner = sqlx::query(
        "INSERT INTO loom_entity_facet \
         (timeline_id, entity_id, facet_type, schema_revision, value) \
         VALUES ($1::uuid, '00000000-0000-0000-0000-00000000a199'::uuid, 'test.missing', 1, '{}'::jsonb)",
    )
    .bind(TIMELINE_ID)
    .execute(pool)
    .await
    .expect_err("Facet owner foreign key must be enforced");
    assert_eq!(
        database_error_code(&missing_owner).as_deref(),
        Some("23503")
    );
}

fn database_error_code(error: &sqlx::Error) -> Option<String> {
    error
        .as_database_error()
        .and_then(sqlx::error::DatabaseError::code)
        .map(std::borrow::Cow::into_owned)
}
