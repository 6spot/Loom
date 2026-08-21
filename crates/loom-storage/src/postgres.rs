//! PostgreSQL 18 storage foundation for Loom Runtime persistence ports.
//!
//! This module owns concrete SQLx/PostgreSQL concerns. `PgStorage` deliberately
//! exposes no `PgPool` accessor: Runtime and higher Loom layers consume
//! Runtime-owned persistence traits rather than reaching through the adapter to
//! issue SQL directly. M2-T1 establishes connection, migration and health
//! behavior only; WorldStore, CommitStore and WorkStore implementations are
//! introduced by their dedicated Milestone 2 tasks.

use sqlx::{PgPool, postgres::PgPoolOptions};

static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!();

/// Concrete PostgreSQL persistence adapter owned by `loom-storage`.
///
/// The contained SQLx pool is intentionally private. Application composition
/// code may construct this adapter and inject it into Runtime-owned persistence
/// ports, but Core/Protocol/API/Capability/Runtime code must never receive the
/// underlying pool or SQLx transaction types.
#[derive(Clone, Debug)]
pub struct PgStorage {
    pool: PgPool,
}

impl PgStorage {
    /// Connects to an existing PostgreSQL database without changing its schema.
    ///
    /// Migrations are explicit through [`Self::migrate`] so deployment/startup
    /// policy can decide when schema changes are allowed. This method owns only
    /// concrete adapter setup; it does not grant Runtime commit authority.
    ///
    /// # Errors
    ///
    /// Returns [`sqlx::Error`] when SQLx cannot establish the PostgreSQL pool.
    pub async fn connect(database_url: &str) -> Result<Self, sqlx::Error> {
        let pool = PgPoolOptions::new().connect(database_url).await?;
        Ok(Self { pool })
    }

    /// Applies the embedded, repository-versioned SQLx migrations.
    ///
    /// SQL migrations under `crates/loom-storage/migrations` are the readable
    /// database representation of the already-reviewed Loom persistence
    /// contract. Re-running this method is safe: SQLx records applied migration
    /// checksums and does not replay an unchanged migration.
    ///
    /// # Errors
    ///
    /// Returns [`sqlx::migrate::MigrateError`] if migration metadata is invalid,
    /// a migration checksum changed, or PostgreSQL rejects a migration.
    pub async fn migrate(&self) -> Result<(), sqlx::migrate::MigrateError> {
        MIGRATOR.run(&self.pool).await
    }

    /// Checks whether the configured PostgreSQL authority database is reachable.
    ///
    /// This is an operational adapter health check only. A successful result
    /// does not mean migrations are current and does not imply any World commit
    /// has been authorized.
    ///
    /// # Errors
    ///
    /// Returns [`sqlx::Error`] when the pool cannot execute a trivial query.
    pub async fn health(&self) -> Result<(), sqlx::Error> {
        let _: i32 = sqlx::query_scalar("SELECT 1").fetch_one(&self.pool).await?;
        Ok(())
    }

    /// Gracefully closes the SQLx pool owned by this adapter.
    pub async fn close(&self) {
        self.pool.close().await;
    }
}

#[cfg(test)]
mod tests {
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

        let server_version: i32 = sqlx::query_scalar(
            "SELECT current_setting('server_version_num')::integer",
        )
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
        assert_eq!(loom_table_count, 12);

        sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid)")
            .bind(WORLD_ID)
            .execute(&storage.pool)
            .await
            .expect("test World should insert");
        sqlx::query(
            "INSERT INTO loom_timeline (timeline_id, world_id) VALUES ($1::uuid, $2::uuid)",
        )
        .bind(TIMELINE_ID)
        .bind(WORLD_ID)
        .execute(&storage.pool)
        .await
        .expect("test Timeline should insert");
        sqlx::query(
            "INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)",
        )
        .bind(TIMELINE_ID)
        .bind(ENTITY_ID)
        .execute(&storage.pool)
        .await
        .expect("test Entity should insert");

        let duplicate_entity = sqlx::query(
            "INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid)",
        )
        .bind(TIMELINE_ID)
        .bind(ENTITY_ID)
        .execute(&storage.pool)
        .await
        .expect_err("duplicate Timeline-local Entity identity must be rejected");
        assert_eq!(database_error_code(&duplicate_entity).as_deref(), Some("23505"));

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
}
