use std::{
    process,
    sync::atomic::{AtomicU64, Ordering},
};

use loom_storage::PgStorage;
use sqlx::{AssertSqlSafe, PgPool};
use url::Url;

static NEXT_DATABASE: AtomicU64 = AtomicU64::new(1);

/// One isolated PostgreSQL database created for an integration-test fixture.
///
/// `LOOM_TEST_POSTGRES_URL` is a control-database connection. The configured
/// role must be allowed to create/drop databases. Each fixture creates a unique
/// child database, applies Loom migrations from scratch, and requires explicit
/// async cleanup at the end of the test.
pub struct TestDatabase {
    control_pool: PgPool,
    database_name: String,
    database_url: String,
}

impl TestDatabase {
    /// Creates a unique empty database and applies the embedded Loom migrations.
    pub async fn provision(label: &str) -> Option<Self> {
        let control_url = postgres_control_url()?;
        let control_pool = PgPool::connect(&control_url)
            .await
            .expect("PostgreSQL test control database should accept connections");
        let database_name = unique_database_name(label);
        let create_sql = format!("CREATE DATABASE {}", quote_identifier(&database_name));
        sqlx::query(AssertSqlSafe(create_sql))
            .execute(&control_pool)
            .await
            .expect("PostgreSQL test role should create isolated databases");

        let database_url = child_database_url(&control_url, &database_name);
        let storage = PgStorage::connect(&database_url)
            .await
            .expect("isolated PostgreSQL test database should accept connections");
        if let Err(error) = storage.migrate().await {
            storage.close().await;
            drop_database(&control_pool, &database_name).await;
            panic!("migrations should apply to a fresh isolated database: {error}");
        }
        storage.close().await;

        Some(Self {
            control_pool,
            database_name,
            database_url,
        })
    }

    /// Opens Loom's concrete storage adapter against this isolated database.
    pub async fn storage(&self) -> PgStorage {
        PgStorage::connect(&self.database_url)
            .await
            .expect("isolated PostgreSQL storage connection should succeed")
    }

    /// Opens a direct SQLx pool for test fixture setup and schema assertions.
    pub async fn pool(&self) -> PgPool {
        PgPool::connect(&self.database_url)
            .await
            .expect("isolated PostgreSQL fixture pool should connect")
    }

    /// Drops the isolated database, force-closing any leaked test connections.
    pub async fn cleanup(self) {
        drop_database(&self.control_pool, &self.database_name).await;
        self.control_pool.close().await;
    }
}

/// Asserts that a pool is connected to PostgreSQL major version 18.
pub async fn assert_postgres_18(pool: &PgPool) {
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

fn postgres_control_url() -> Option<String> {
    match std::env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) => Some(url),
        Err(error) if std::env::var_os("LOOM_REQUIRE_POSTGRES_TESTS").is_some() => {
            panic!("LOOM_TEST_POSTGRES_URL is required for PostgreSQL tests: {error}")
        }
        Err(_) => None,
    }
}

fn child_database_url(control_url: &str, database_name: &str) -> String {
    let mut url = Url::parse(control_url).expect("LOOM_TEST_POSTGRES_URL should be a valid URL");
    url.set_path(&format!("/{database_name}"));
    url.to_string()
}

fn unique_database_name(label: &str) -> String {
    let label = label
        .chars()
        .filter(|character| character.is_ascii_alphanumeric())
        .take(20)
        .collect::<String>()
        .to_ascii_lowercase();
    let counter = NEXT_DATABASE.fetch_add(1, Ordering::Relaxed);
    format!("loom_{label}_{}_{}", process::id(), counter)
}

fn quote_identifier(identifier: &str) -> String {
    debug_assert!(identifier
        .chars()
        .all(|character| character.is_ascii_lowercase() || character.is_ascii_digit() || character == '_'));
    format!("\"{identifier}\"")
}

async fn drop_database(control_pool: &PgPool, database_name: &str) {
    let drop_sql = format!(
        "DROP DATABASE IF EXISTS {} WITH (FORCE)",
        quote_identifier(database_name)
    );
    sqlx::query(AssertSqlSafe(drop_sql))
        .execute(control_pool)
        .await
        .expect("isolated PostgreSQL test database should be droppable");
}
